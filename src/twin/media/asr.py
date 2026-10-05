"""Evaluation-only B5 recognition adapters, sharing B2's sanitized MediaError hierarchy.

Cloudflare schemas (read 2026-10-04):
https://developers.cloudflare.com/workers-ai/models/whisper-large-v3-turbo/schema-input.json
https://developers.cloudflare.com/workers-ai/models/whisper-large-v3-turbo/schema-output.json
The self-hosted FunASR/SenseVoice shim implements multipart POST /audio/transcriptions;
its JSON response has text and optional language/duration, not native vendor types.
"""

from __future__ import annotations

import base64
import json
import math
import re
import time
from typing import Protocol
from urllib.parse import urlsplit, urlunsplit

import httpx

from ..util import fingerprint, key_from_env
from .schema import ASRCapabilities, Transcription, TranscriptionRequest
from .tts import MediaError, MediaInputTooLong, MediaRejected, MediaTimeout, MediaUnavailable


class SpeechRecognizer(Protocol):
    """Backend-neutral recognition with a secret-free, opaque service identity."""

    name: str
    capabilities: ASRCapabilities

    @property
    def identity(self) -> str: ...

    def transcribe(self, request: TranscriptionRequest) -> Transcription: ...


def _check_request(request: TranscriptionRequest, capabilities: ASRCapabilities) -> None:
    if not request.audio:
        raise MediaRejected("识别音频为空")
    if len(request.audio) > capabilities.max_audio_bytes:
        raise MediaInputTooLong("识别音频超过大小限制")
    if request.audio_format not in capabilities.audio_formats:
        raise MediaRejected("不支持此识别音频格式")
    if request.language not in capabilities.languages:
        raise MediaRejected("不支持此识别语言")
    if request.prompt is not None and not capabilities.supports_prompt:
        raise MediaRejected("识别服务不支持提示文本")


class _HTTPRecognizer:
    """Transport failures never expose response bodies, endpoints or chained exceptions."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key_env: str,
        timeout: float,
        max_retries: int,
        client: httpx.Client | None,
    ) -> None:
        try:
            parts = urlsplit(base_url)
        except ValueError:
            raise ValueError("识别服务地址无效") from None
        if (
            parts.scheme not in ("http", "https")
            or not parts.hostname
            or parts.username
            or parts.password
            or parts.query
            or parts.fragment
        ):
            raise ValueError("识别服务地址无效")
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("识别超时必须为正有限数")
        if isinstance(max_retries, bool) or not isinstance(max_retries, int) or max_retries < 0:
            raise ValueError("识别重试次数必须为非负整数")
        self._base_url = base_url.rstrip("/")
        self._key = key_from_env(api_key_env) or "EMPTY"
        self._timeout = timeout
        self._max_retries = max_retries
        self._client = client

    def _identity(self, backend: str, model: str) -> str:
        parts = urlsplit(self._base_url)
        endpoint = urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), "", ""))
        return fingerprint({"backend": backend, "model": model, "endpoint": endpoint, "wire_version": 1})

    def _send(self, client: httpx.Client, request: TranscriptionRequest) -> httpx.Response:
        raise NotImplementedError

    def _post(self, request: TranscriptionRequest) -> httpx.Response:
        for attempt in range(self._max_retries + 1):
            error: MediaError
            try:
                if self._client is None:
                    with httpx.Client() as client:
                        response = self._send(client, request)
                else:
                    response = self._send(self._client, request)
            except httpx.TimeoutException:
                error = MediaTimeout("语音识别服务超时")
            except (httpx.HTTPError, httpx.InvalidURL):
                error = MediaUnavailable("语音识别服务连接失败")
            else:
                if response.status_code in (408, 429) or response.status_code >= 500:
                    error = (
                        MediaTimeout("语音识别服务超时")
                        if response.status_code == 408
                        else MediaUnavailable("语音识别服务不可用")
                    )
                elif response.status_code >= 300:
                    raise MediaRejected(f"语音识别请求被拒绝（HTTP {response.status_code}）") from None
                else:
                    return response
            if attempt == self._max_retries:
                raise error from None
            time.sleep(min(0.1 * 2**attempt, 2.0))
        raise AssertionError("unreachable")

    def _redact(self, text: str) -> str:
        text = text.replace(self._key, "[redacted]").replace(self._base_url, "[redacted]")
        return re.sub(r"https?://[^\s\"<>]+", "[redacted]", text)

    def _decode(self, response: httpx.Response, *, cloudflare: bool) -> Transcription:
        try:
            payload = response.json()
            if not isinstance(payload, dict) or payload.get("success") is False:
                raise ValueError("Invalid envelope")
            result = payload.get("result", payload) if cloudflare else payload
            if not isinstance(result, dict) or not isinstance(result.get("text"), str):
                raise ValueError("Missing text")
            info = result.get("transcription_info", {}) if cloudflare else result
            if not isinstance(info, dict):
                raise ValueError("Invalid metadata")
            language = info.get("language")
            duration = info.get("duration")
            if language is not None and not isinstance(language, str):
                raise ValueError("Invalid language")
            if duration is not None and (
                isinstance(duration, bool)
                or not isinstance(duration, (float, int))
                or not math.isfinite(duration)
                or duration < 0
            ):
                raise ValueError("Invalid duration")
            excluded = {"text"} if cloudflare else {"text", "language", "duration"}
            extras = {
                self._redact(key): self._redact(json.dumps(value, ensure_ascii=False))
                for key, value in result.items()
                if key not in excluded
            }
            return Transcription(
                text=self._redact(result["text"]),
                language=self._redact(language) if language is not None else None,
                duration_s=duration,
                extras=extras,
            )
        except (ValueError, TypeError, OverflowError):
            raise MediaUnavailable("语音识别服务返回无效结果") from None


class CloudflareWhisper(_HTTPRecognizer):
    """Whisper large-v3-turbo with documented base64 audio and initial_prompt JSON fields."""

    def __init__(
        self,
        base_url: str,
        api_key_env: str = "TWIN_ASR_KEY",
        *,
        languages: list[str] | None = None,
        timeout: float = 60.0,
        max_retries: int = 2,
        client: httpx.Client | None = None,
    ) -> None:
        if not key_from_env(api_key_env):
            raise MediaUnavailable("语音识别密钥未配置，请检查 [asr] 的密钥环境变量")
        super().__init__(
            base_url=base_url, api_key_env=api_key_env, timeout=timeout, max_retries=max_retries, client=client
        )
        self.name = "cloudflare:whisper-large-v3-turbo"
        self.capabilities = ASRCapabilities(languages=languages or ["zh"], provides_duration=True)

    @property
    def identity(self) -> str:
        return self._identity("cloudflare", "@cf/openai/whisper-large-v3-turbo")

    def _send(self, client: httpx.Client, request: TranscriptionRequest) -> httpx.Response:
        payload = {"audio": base64.b64encode(request.audio).decode("ascii"), "language": request.language}
        if request.prompt is not None:
            payload["initial_prompt"] = request.prompt
        return client.post(
            self._base_url + "/run/@cf/openai/whisper-large-v3-turbo",
            json=payload,
            headers={"Authorization": f"Bearer {self._key}"},
            timeout=self._timeout,
            follow_redirects=False,
        )

    def transcribe(self, request: TranscriptionRequest) -> Transcription:
        _check_request(request, self.capabilities)
        return self._decode(self._post(request), cloudflare=True)


class OpenAICompatTranscription(_HTTPRecognizer):
    """Self-hosted multipart shim, never implicitly targeting a public service."""

    def __init__(
        self,
        model: str,
        base_url: str,
        api_key_env: str = "TWIN_ASR_KEY",
        *,
        languages: list[str] | None = None,
        timeout: float = 60.0,
        max_retries: int = 2,
        client: httpx.Client | None = None,
    ) -> None:
        super().__init__(
            base_url=base_url, api_key_env=api_key_env, timeout=timeout, max_retries=max_retries, client=client
        )
        self.model = model
        self.name = "openai_compat:transcription"
        self.capabilities = ASRCapabilities(languages=languages or ["zh"])

    @property
    def identity(self) -> str:
        return self._identity("openai_compat", self.model)

    def _send(self, client: httpx.Client, request: TranscriptionRequest) -> httpx.Response:
        data = {"model": self.model, "language": request.language}
        if request.prompt is not None:
            data["prompt"] = request.prompt
        content_type = "audio/wav" if request.audio_format == "wav" else "audio/mpeg"
        return client.post(
            self._base_url + "/audio/transcriptions",
            data=data,
            files={"file": (f"audio.{request.audio_format}", request.audio, content_type)},
            headers={"Authorization": f"Bearer {self._key}"},
            timeout=self._timeout,
            follow_redirects=False,
        )

    def transcribe(self, request: TranscriptionRequest) -> Transcription:
        _check_request(request, self.capabilities)
        return self._decode(self._post(request), cloudflare=False)
