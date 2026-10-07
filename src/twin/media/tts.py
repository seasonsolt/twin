"""Speech backends implementing the versioned B2 contract.

Self-hosted MOSS-TTS-Nano or CosyVoice must sit behind an OpenAI-compatible shim:
POST /audio/speech with model, input, voice and response_format. Native vendor APIs
are deliberately not part of the presentation contract.

Cloudflare's output schema declares JSON ``audio`` (documented as base64 MP3) or binary audio/mpeg:
https://developers.cloudflare.com/workers-ai/models/melotts/schema-output.json
The REST API may wrap that JSON object in ``result``.
"""

from __future__ import annotations

import base64
import binascii
import io
import json
import math
import threading
import time
import wave
from collections.abc import AsyncGenerator
from typing import Protocol
from urllib.parse import urlsplit, urlunsplit

import httpx

from ..util import fingerprint, key_from_env
from .schema import AudioFormat, SpeechRequest, SpeechResult, SynthCapabilities, VoiceSpec, WordTiming


class MediaError(RuntimeError):
    """A sanitized speech failure, independent of the backend."""


class MediaUnavailable(MediaError):
    """The service is unavailable or returned an invalid response."""


class MediaRejected(MediaError):
    """The service or capability declaration rejected the request."""


class MediaTimeout(MediaError):
    """The service timed out after retries."""


class MediaInputTooLong(MediaError):
    """The renderer must split the input before synthesis."""


class SpeechSynthesizer(Protocol):
    """Configured preset voice and opaque, secret-free cache identity are backend-neutral."""

    name: str
    voice: VoiceSpec

    @property
    def capabilities(self) -> SynthCapabilities: ...

    @property
    def identity(self) -> str: ...

    def synthesize(self, request: SpeechRequest) -> SpeechResult: ...


def _check_voice(voice: VoiceSpec, capabilities: SynthCapabilities) -> None:
    if capabilities.voices is not None and voice.voice_id not in capabilities.voices:
        raise MediaRejected(
            f"仅支持预置音色：配置音色 {voice.voice_id!r} 不在后端允许列表中"
            f"（共 {len(capabilities.voices)} 个预置音色）"
        )


def _check_request(request: SpeechRequest, capabilities: SynthCapabilities) -> None:
    _check_voice(request.voice, capabilities)
    if len(request.text) > capabilities.max_chars:
        raise MediaInputTooLong("Speech input exceeds max_chars")
    if not request.text.strip():
        raise MediaRejected("Speech input is empty")
    if request.audio_format not in capabilities.audio_formats:
        raise MediaRejected("Unsupported audio format")
    if request.voice.language not in capabilities.languages:
        raise MediaRejected("Unsupported speech language")


class SilentSynthesizer:
    """Deterministic mono PCM silence, 80 ms per character; timings are synthetic, not alignment."""

    def __init__(
        self,
        *,
        voice: VoiceSpec | None = None,
        provides_timings: bool = False,
        max_chars: int = 500,
        sample_rate: int = 16000,
    ) -> None:
        if isinstance(sample_rate, bool) or not isinstance(sample_rate, int) or sample_rate <= 0:
            raise ValueError("sample_rate must be a positive integer")
        self.name = "silent"
        self.voice = voice or VoiceSpec()
        self.sample_rate = sample_rate
        self.capabilities = SynthCapabilities(
            provides_timings=provides_timings,
            max_chars=max_chars,
            audio_formats=["wav"],
            languages=[self.voice.language],
            voices=["default"],
        )
        _check_voice(self.voice, self.capabilities)

    @property
    def identity(self) -> str:
        return fingerprint(
            {
                "backend": self.name,
                "algorithm": "silence-v1",
                "rate": self.sample_rate,
                "timings": self.capabilities.provides_timings,
            }
        )

    def synthesize(self, request: SpeechRequest) -> SpeechResult:
        _check_request(request, self.capabilities)
        frames = max(1, round(len(request.text) * 0.08 * self.sample_rate))
        duration = frames / self.sample_rate
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(self.sample_rate)
            audio.writeframes(b"\0\0" * frames)
        timings = None
        if self.capabilities.provides_timings:
            step = duration / len(request.text)
            timings = [WordTiming(text=c, start_s=i * step, end_s=(i + 1) * step) for i, c in enumerate(request.text)]
        return SpeechResult(
            audio=buffer.getvalue(),
            audio_format="wav",
            sample_rate=self.sample_rate,
            duration_s=duration,
            timings=timings,
        )


class _HTTPSpeech:
    """Shared transport handling; raw errors and bodies are never exposed or chained."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key_env: str,
        voice: VoiceSpec | None,
        timeout: float,
        max_retries: int,
        client: httpx.Client | None,
    ) -> None:
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be positive and finite")
        if isinstance(max_retries, bool) or not isinstance(max_retries, int) or max_retries < 0:
            raise ValueError("max_retries must be a non-negative integer")
        parts = urlsplit(base_url)
        if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
            raise ValueError("Invalid speech base_url")
        if parts.query or parts.fragment:
            raise ValueError("Speech base_url must not contain query or fragment")
        self._base_url = base_url.rstrip("/")
        self._key = key_from_env(api_key_env) or "EMPTY"
        self.voice = voice or VoiceSpec()
        self._timeout = timeout
        self._max_retries = max_retries
        self._client = client

    def _identity(self, name: str, model: str) -> str:
        parts = urlsplit(self._base_url)
        endpoint = urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), "", ""))
        return fingerprint({"backend": name, "model": model, "endpoint": endpoint})

    def _post(self, path: str, payload: dict[str, str]) -> httpx.Response:
        return self._request("POST", path, payload)

    def _request(self, method: str, path: str, payload: dict[str, str] | None = None) -> httpx.Response:
        for attempt in range(self._max_retries + 1):
            error: MediaError
            try:
                if self._client is None:
                    with httpx.Client() as client:
                        response = self._send(client, method, path, payload)
                else:
                    response = self._send(self._client, method, path, payload)
            except httpx.TimeoutException:
                error = MediaTimeout("Speech service timed out")
            except (httpx.HTTPError, httpx.InvalidURL):
                error = MediaUnavailable("Speech service transport failed")
            else:
                if method == "GET" and response.status_code in (404, 405):
                    return response
                if response.status_code in (408, 429) or response.status_code >= 500:
                    error = (
                        MediaTimeout("Speech service timed out")
                        if response.status_code == 408
                        else MediaUnavailable("Speech service unavailable")
                    )
                elif response.status_code >= 300:
                    raise MediaRejected(f"Speech request rejected (HTTP {response.status_code})") from None
                else:
                    return response
            if attempt == self._max_retries:
                raise error from None
            time.sleep(min(0.1 * 2**attempt, 2.0))
        raise AssertionError("unreachable")

    def _send(self, client: httpx.Client, method: str, path: str, payload: dict[str, str] | None) -> httpx.Response:
        return client.request(
            method,
            self._base_url + path,
            json=payload,
            headers={"Authorization": f"Bearer {self._key}"},
            timeout=self._timeout,
            follow_redirects=False,
        )

    def _extras(self, values: dict[str, object]) -> dict[str, str]:
        extras: dict[str, str] = {}
        for key, value in values.items():
            text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
            for secret in (self._key, self._base_url):
                text = text.replace(secret, "[redacted]")
                key = key.replace(secret, "[redacted]")
            extras[key] = text
        return extras


class CloudflareMeloTTS(_HTTPSpeech):
    """Cloudflare MeloTTS: synthetic/public data only, no alignment or speaker selection.

    The documented MP3 JSON payload was observed on 2026-10-04 to contain RIFF/WAVE
    (16-bit mono PCM, 44.1 kHz) instead. Detect the actual container, independently
    of the requested format or HTTP content type, and normalize WAV timing metadata.
    """

    def __init__(
        self,
        base_url: str,
        api_key_env: str = "TWIN_TTS_KEY",
        *,
        voice: VoiceSpec | None = None,
        languages: list[str] | None = None,
        async_client: httpx.AsyncClient | None = None,
        timeout: float = 60.0,
        max_retries: int = 2,
        client: httpx.Client | None = None,
    ) -> None:
        if not key_from_env(api_key_env):
            raise MediaUnavailable(f"语音密钥未配置：请设置环境变量 {api_key_env}")
        super().__init__(
            base_url=base_url,
            api_key_env=api_key_env,
            voice=voice,
            timeout=timeout,
            max_retries=max_retries,
            client=client,
        )
        self.name = "cloudflare:melotts"
        self._async_client = async_client
        self.capabilities = SynthCapabilities(
            audio_formats=["mp3", "wav"],
            languages=languages or [self.voice.language],
            max_chars=500,
            reads_latin_acronyms=False,
            voices=["default"],
        )
        _check_voice(self.voice, self.capabilities)

    @property
    def identity(self) -> str:
        return fingerprint(
            {"service": self._identity("cloudflare", "@cf/myshell-ai/melotts"), "audio_normalization": 1}
        )

    def synthesize(self, request: SpeechRequest) -> SpeechResult:
        _check_request(request, self.capabilities)
        response = self._post("/run/@cf/myshell-ai/melotts", {"prompt": request.text, "lang": request.voice.language})
        return self._result(response)

    async def synthesize_async(self, request: SpeechRequest) -> SpeechResult:
        """Whole-audio fallback using cancellable I/O while keeping the synchronous B2 API."""
        _check_request(request, self.capabilities)
        client = self._async_client or httpx.AsyncClient()
        try:
            response = await client.post(
                self._base_url + "/run/@cf/myshell-ai/melotts",
                json={"prompt": request.text, "lang": request.voice.language},
                headers={"Authorization": f"Bearer {self._key}"},
                timeout=self._timeout,
                follow_redirects=False,
            )
            if response.status_code == 408:
                raise MediaTimeout("Speech service timed out")
            if response.status_code == 429 or response.status_code >= 500:
                raise MediaUnavailable("Speech service unavailable")
            if response.status_code >= 300:
                raise MediaRejected("Speech request rejected")
            return self._result(response)
        except httpx.TimeoutException:
            raise MediaTimeout("Speech service timed out") from None
        except (httpx.HTTPError, httpx.InvalidURL):
            raise MediaUnavailable("Speech service transport failed") from None
        finally:
            if self._async_client is None:
                await client.aclose()

    def _result(self, response: httpx.Response) -> SpeechResult:
        extras: dict[str, str] = {}
        try:
            content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if content_type in {"audio/mpeg", "audio/wav", "audio/x-wav"}:
                audio = response.content
            elif content_type == "application/json":
                payload = response.json()
                if not isinstance(payload, dict) or payload.get("success") is False:
                    raise ValueError("Invalid envelope")
                result = payload.get("result", payload)
                if not isinstance(result, dict) or not isinstance(result.get("audio"), str):
                    raise ValueError("Missing audio")
                audio = base64.b64decode(result["audio"], validate=True)
                extras = self._extras({key: value for key, value in result.items() if key != "audio"})
                if result is not payload:
                    extras.update(self._extras({key: value for key, value in payload.items() if key != "result"}))
            else:
                raise ValueError("Unexpected content type")
            sample_rate, duration = None, None
            audio_format: AudioFormat
            if audio[:4] == b"RIFF" and audio[8:12] == b"WAVE":
                audio_format = "wav"
                with wave.open(io.BytesIO(audio), "rb") as parsed:
                    sample_rate = parsed.getframerate()
                    if sample_rate <= 0:
                        raise ValueError("Invalid sample rate")
                    duration = parsed.getnframes() / sample_rate
            elif audio.startswith(b"ID3") or (len(audio) >= 2 and audio[0] == 0xFF and audio[1] & 0xE0 == 0xE0):
                audio_format = "mp3"
            else:
                raise ValueError("Unknown audio container")
        except (ValueError, TypeError, binascii.Error, wave.Error, EOFError):
            raise MediaUnavailable("Speech service returned invalid audio") from None
        return SpeechResult(
            audio=audio, audio_format=audio_format, sample_rate=sample_rate, duration_s=duration, extras=extras
        )


def wav_pcm(audio: bytes) -> tuple[int, bytes]:
    try:
        with wave.open(io.BytesIO(audio), "rb") as parsed:
            width, channels = parsed.getsampwidth(), parsed.getnchannels()
            if width not in (1, 2, 3, 4) or not 1 <= channels <= 8 or parsed.getcomptype() != "NONE":
                raise ValueError("Unsupported PCM")
            rate = parsed.getframerate()
            pcm = parsed.readframes(parsed.getnframes())
            if rate <= 0 or not pcm or len(pcm) != parsed.getnframes() * width * channels:
                raise ValueError("Invalid PCM")
            if width == 2 and channels == 1:
                return rate, pcm
            samples = (
                [(value - 128) * 256 for value in pcm]
                if width == 1
                else [
                    int.from_bytes(pcm[offset : offset + width], "little", signed=True) >> (8 * (width - 2))
                    for offset in range(0, len(pcm), width)
                ]
            )
            mono = b"".join(
                round(sum(samples[offset : offset + channels]) / channels).to_bytes(2, "little", signed=True)
                for offset in range(0, len(samples), channels)
            )
            return rate, mono
    except (wave.Error, EOFError, ValueError):
        raise MediaUnavailable("Speech service returned invalid PCM WAV") from None


class OpenAICompatSpeech(_HTTPSpeech):
    """Self-hosted OpenAI-compatible speech shim; no public endpoint is selected implicitly."""

    def __init__(
        self,
        model: str,
        base_url: str,
        api_key_env: str = "TWIN_TTS_KEY",
        *,
        streaming: bool = True,
        async_client: httpx.AsyncClient | None = None,
        voice: VoiceSpec | None = None,
        timeout: float = 60.0,
        max_retries: int = 2,
        client: httpx.Client | None = None,
    ) -> None:
        super().__init__(
            base_url=base_url,
            api_key_env=api_key_env,
            voice=voice,
            timeout=timeout,
            max_retries=max_retries,
            client=client,
        )
        self.model = model
        self.streaming = streaming
        self._async_client = async_client
        self.name = "openai_compat:speech"
        self._capabilities = SynthCapabilities(
            audio_formats=["wav", "mp3"], languages=[self.voice.language], max_chars=1000
        )
        self._voices_loaded = False
        self._capabilities_lock = threading.Lock()

    @property
    def capabilities(self) -> SynthCapabilities:
        """Enumerate presets lazily; cache successful discovery, including unsupported endpoints."""
        with self._capabilities_lock:
            if not self._voices_loaded:
                response = self._request("GET", "/voices")
                if response.status_code == 200:
                    try:
                        payload = response.json()
                        voices = payload["voices"]
                        if not isinstance(voices, list) or not all(isinstance(voice, str) for voice in voices):
                            raise ValueError("Invalid voices")
                    except (ValueError, TypeError, KeyError):
                        raise MediaUnavailable("Speech service returned invalid voices") from None
                    self._capabilities = self._capabilities.model_copy(update={"voices": voices})
                elif response.status_code not in (404, 405):
                    raise MediaUnavailable("Speech service returned invalid voices") from None
                self._voices_loaded = True
            _check_voice(self.voice, self._capabilities)
            return self._capabilities

    @property
    def identity(self) -> str:
        return self._identity("openai_compat", self.model)

    async def stream_pcm(self, request: SpeechRequest) -> AsyncGenerator[tuple[int, bytes]]:
        # Capabilities have been checked by the renderer before entering the async transport.
        _check_request(request, self._capabilities)
        client = self._async_client or httpx.AsyncClient()
        payload = {"model": self.model, "input": request.text, "voice": request.voice.voice_id}
        headers = {"Authorization": f"Bearer {self._key}"}
        try:
            if self.streaming:
                async with client.stream(
                    "POST",
                    self._base_url + "/audio/speech/stream",
                    json=payload,
                    headers=headers,
                    timeout=self._timeout,
                    follow_redirects=False,
                ) as response:
                    if response.status_code not in (404, 405):
                        if response.status_code != 200:
                            raise MediaUnavailable("Speech streaming service unavailable")
                        try:
                            rate = int(response.headers.get("X-Sample-Rate", "0"))
                            if (
                                not 8000 <= rate <= 192000
                                or response.headers.get("content-type", "").split(";")[0] != "audio/pcm"
                            ):
                                raise ValueError("Invalid PCM headers")
                        except ValueError:
                            raise MediaUnavailable("Speech service returned invalid PCM headers") from None
                        pending = b""
                        size = 0
                        async for chunk in response.aiter_bytes():
                            pending += chunk
                            end = len(pending) // 2 * 2
                            if end:
                                size += end
                                yield rate, pending[:end]
                                pending = pending[end:]
                        if pending or not size:
                            raise MediaUnavailable("Speech service returned incomplete PCM")
                        return
            response = await client.post(
                self._base_url + "/audio/speech",
                json={**payload, "response_format": "wav"},
                headers=headers,
                timeout=self._timeout,
                follow_redirects=False,
            )
            if response.status_code != 200:
                raise MediaUnavailable("Speech service unavailable")
            rate, pcm = wav_pcm(response.content)
            for offset in range(0, len(pcm), 8192):
                yield rate, pcm[offset : offset + 8192]
        except httpx.TimeoutException:
            raise MediaTimeout("Speech service timed out") from None
        except (httpx.HTTPError, httpx.InvalidURL):
            raise MediaUnavailable("Speech service transport failed") from None
        finally:
            if self._async_client is None:
                await client.aclose()

    def synthesize(self, request: SpeechRequest) -> SpeechResult:
        _check_request(request, self.capabilities)
        response = self._post(
            "/audio/speech",
            {
                "model": self.model,
                "input": request.text,
                "voice": request.voice.voice_id,
                "response_format": request.audio_format,
            },
        )
        content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        expected = {
            "wav": {"audio/wav", "audio/x-wav", "audio/wave", "application/octet-stream"},
            "mp3": {"audio/mpeg", "audio/mp3", "application/octet-stream"},
        }
        if content_type not in expected[request.audio_format] or not response.content:
            raise MediaUnavailable("Speech service returned invalid audio")
        sample_rate, duration = None, None
        if request.audio_format == "wav":
            try:
                with wave.open(io.BytesIO(response.content), "rb") as audio:
                    sample_rate = audio.getframerate()
                    duration = audio.getnframes() / sample_rate
            except (wave.Error, EOFError, ValueError):
                raise MediaUnavailable("Speech service returned invalid WAV") from None
        warning = response.headers.get("X-Speech-Warning")
        extras = self._extras({"warning": warning}) if warning is not None else {}
        return SpeechResult(
            audio=response.content,
            audio_format=request.audio_format,
            sample_rate=sample_rate,
            duration_s=duration,
            extras=extras,
            warnings=["possibly-truncated"] if warning == "possibly-truncated" else [],
        )
