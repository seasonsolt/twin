"""Offline B5 conformance shared by both recognition adapters and response envelopes."""

from __future__ import annotations

import base64
import json
import traceback
from collections.abc import Iterator
from email import policy
from email.parser import BytesParser
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from twin.config import ASRSettings, Settings, load_settings, make_recognizer
from twin.media.asr import CloudflareWhisper, OpenAICompatTranscription, SpeechRecognizer
from twin.media.schema import ASRCapabilities, Transcription, TranscriptionRequest
from twin.media.tts import MediaInputTooLong, MediaRejected, MediaTimeout, MediaUnavailable

KEY = "secret-asr-test-token"
BASE = "https://recognition.invalid/private-account/ai"
AUDIO = b"synthetic-audio"


class Harness:
    def __init__(self, variant: str, client: httpx.Client) -> None:
        self.variant = variant
        self.calls: list[httpx.Request] = []
        self.status = 200
        self.failure: str | None = None
        self.body: object | None = None
        self.recognizer: SpeechRecognizer
        if variant.startswith("cloudflare"):
            self.recognizer = CloudflareWhisper(BASE, client=client, max_retries=2)
        else:
            self.recognizer = OpenAICompatTranscription("SenseVoiceSmall", BASE, client=client, max_retries=2)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        assert request.headers["authorization"] == f"Bearer {KEY}"
        if self.failure == "timeout":
            raise httpx.ReadTimeout(f"{KEY} {BASE}", request=request)
        if self.failure == "transport":
            raise httpx.ConnectError(f"{KEY} {BASE}", request=request)
        if self.status != 200:
            return httpx.Response(self.status, text=f"{KEY} {BASE}")
        if self.body is not None:
            return httpx.Response(200, json=self.body)
        fields: dict[str, object]
        if self.variant.startswith("cloudflare"):
            assert str(request.url) == BASE + "/run/@cf/openai/whisper-large-v3-turbo"
            fields = json.loads(request.content)
            assert base64.b64decode(str(fields.pop("audio"))) == AUDIO
            assert fields["language"] == "zh"
            assert set(fields) <= {"language", "initial_prompt"}
            result = {
                "text": "你好，世界。",
                "transcription_info": {"language": "zh", "duration": 1.5, "language_probability": 0.99},
                "segments": [],
                "word_count": 4,
                "vendor": f"{KEY} {BASE}",
            }
            return httpx.Response(
                200,
                json={"success": True, "result": result} if self.variant.endswith("envelope") else result,
            )
        assert str(request.url) == BASE + "/audio/transcriptions"
        message = BytesParser(policy=policy.default).parsebytes(
            f"Content-Type: {request.headers['content-type']}\r\n\r\n".encode() + request.content
        )
        fields = {}
        for part in message.iter_parts():
            name = str(part.get_param("name", header="content-disposition"))
            content = part.get_payload(decode=True)
            assert isinstance(content, bytes)
            fields[name] = content if name == "file" else content.decode("utf-8")
            if name == "file":
                assert part.get_filename() in {"audio.wav", "audio.mp3"}
                assert part.get_content_type() in {"audio/wav", "audio/mpeg"}
        assert fields["file"] == AUDIO
        assert fields["model"] == "SenseVoiceSmall"
        assert fields["language"] == "zh"
        assert set(fields) <= {"file", "model", "language", "prompt"}
        return httpx.Response(
            200, json={"text": "你好，世界。", "language": "zh", "duration": 1.5, "vendor": f"{KEY} {BASE}"}
        )


@pytest.fixture(params=["cloudflare", "cloudflare-envelope", "openai_compat"])
def backend(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> Iterator[Harness]:
    monkeypatch.setenv("TWIN_ASR_KEY", KEY)
    monkeypatch.setattr("twin.media.asr.time.sleep", lambda _: None)
    holder: list[Harness] = []
    with httpx.Client(transport=httpx.MockTransport(lambda req: holder[0].handle(req))) as client:
        harness = Harness(request.param, client)
        holder.append(harness)
        yield harness


def test_success_contract_and_wire_fields(backend: Harness) -> None:
    for fmt in backend.recognizer.capabilities.audio_formats:
        result = backend.recognizer.transcribe(
            TranscriptionRequest(audio=AUDIO, audio_format=fmt, prompt="以下是普通话句子。")
        )
        assert result.schema_version == 1
        assert result.text == "你好，世界。" and result.language == "zh"
        assert result.duration_s == 1.5
        assert KEY not in str(result.extras) and BASE not in str(result.extras)
        assert all(isinstance(k, str) and isinstance(v, str) for k, v in result.extras.items())
        body = backend.calls[-1].content.decode()
        assert "initial_prompt" in body if backend.variant.startswith("cloudflare") else 'name="prompt"' in body
        assert "以下是普通话句子。" in body
    assert KEY not in backend.recognizer.identity and BASE not in backend.recognizer.identity
    assert not backend.recognizer.capabilities.streaming


def test_empty_transcript_and_optional_metadata(backend: Harness) -> None:
    backend.body = {"text": ""}
    result = backend.recognizer.transcribe(TranscriptionRequest(audio=AUDIO))
    assert result.text == "" and result.language is None and result.duration_s is None


def test_optional_prompt(backend: Harness) -> None:
    backend.recognizer.transcribe(TranscriptionRequest(audio=AUDIO))
    assert "initial_prompt" not in backend.calls[-1].content.decode()
    assert 'name="prompt"' not in backend.calls[-1].content.decode()


@pytest.mark.parametrize("status", [301, 400, 401, 403])
def test_rejected_is_sanitized_and_not_retried(backend: Harness, status: int) -> None:
    backend.status = status
    with pytest.raises(MediaRejected) as error:
        backend.recognizer.transcribe(TranscriptionRequest(audio=AUDIO))
    assert len(backend.calls) == 1
    rendered = "".join(traceback.format_exception(error.value))
    assert KEY not in rendered and BASE not in rendered


@pytest.mark.parametrize("failure", ["timeout", "transport", "503", "429", "408"])
def test_retry_errors_are_sanitized(backend: Harness, failure: str) -> None:
    if failure.isdigit():
        backend.status = int(failure)
    else:
        backend.failure = failure
    kind = MediaTimeout if failure in {"timeout", "408"} else MediaUnavailable
    with pytest.raises(kind) as error:
        backend.recognizer.transcribe(TranscriptionRequest(audio=AUDIO))
    assert len(backend.calls) == 3
    rendered = "".join(traceback.format_exception(error.value))
    assert KEY not in rendered and BASE not in rendered


@pytest.mark.parametrize("body", [[], {"error": f"{KEY} {BASE}"}, {"text": 5}, {"success": False, "text": "x"}])
def test_invalid_output(backend: Harness, body: object) -> None:
    backend.body = body
    with pytest.raises(MediaUnavailable) as error:
        backend.recognizer.transcribe(TranscriptionRequest(audio=AUDIO))
    rendered = "".join(traceback.format_exception(error.value))
    assert KEY not in rendered and BASE not in rendered


@pytest.mark.parametrize("duration", [-1, "bad", True])
def test_invalid_duration(backend: Harness, duration: object) -> None:
    backend.body = (
        {"text": "你好", "transcription_info": {"duration": duration}}
        if backend.variant.startswith("cloudflare")
        else {"text": "你好", "duration": duration}
    )
    with pytest.raises(MediaUnavailable):
        backend.recognizer.transcribe(TranscriptionRequest(audio=AUDIO))


def test_capability_rejections_are_local(backend: Harness) -> None:
    for request in (
        TranscriptionRequest(),
        TranscriptionRequest(audio=AUDIO, language="unsupported"),
        TranscriptionRequest(audio=AUDIO).model_copy(update={"audio_format": "ogg"}),
    ):
        with pytest.raises(MediaRejected):
            backend.recognizer.transcribe(request)
    backend.recognizer.capabilities = backend.recognizer.capabilities.model_copy(update={"max_audio_bytes": 1})
    with pytest.raises(MediaInputTooLong):
        backend.recognizer.transcribe(TranscriptionRequest(audio=AUDIO))
    assert not backend.calls


def test_defaults_are_versioned_and_vendor_fields_forbidden() -> None:
    assert (
        TranscriptionRequest().schema_version == Transcription().schema_version == ASRCapabilities().schema_version == 1
    )
    with pytest.raises(ValidationError):
        Transcription.model_validate({"vendor_text": "raw"})
    with pytest.raises(ValidationError):
        ASRCapabilities(max_audio_bytes=0)


@pytest.mark.parametrize("provider", ["cloudflare", "openai_compat"])
def test_factory_configuration(provider: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TWIN_ASR_KEY", KEY)
    path = tmp_path / "settings.toml"
    path.write_text(
        f'[asr]\nprovider = "{provider}"\nmodel = "local-asr"\nbase_url = "{BASE}"\n'
        'language = "en"\ntimeout = 12\nmax_retries = 0\n'
    )
    settings = load_settings(path)
    recognizer = make_recognizer(settings.asr)
    assert recognizer.capabilities.languages == ["en"]
    assert KEY not in recognizer.identity and BASE not in recognizer.identity
    assert KEY not in settings.model_dump_json()


@pytest.mark.parametrize("provider", ["cloudflare", "openai_compat"])
def test_factory_requires_endpoint(provider: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_BASE_URL", BASE)
    with pytest.raises(ValueError, match=r"\[asr\].*base_url"):
        make_recognizer(ASRSettings.model_validate({"provider": provider, "model": "local"}))
    with pytest.raises(ValueError, match=r"\[asr\].*base_url"):
        make_recognizer(Settings().asr)


def test_factory_requires_shim_model() -> None:
    with pytest.raises(ValueError, match=r"\[asr\].*model"):
        make_recognizer(ASRSettings(base_url=BASE))


@pytest.mark.parametrize("value", [None, ""])
def test_keyless_self_hosting_and_cloud_credentials(value: str | None, monkeypatch: pytest.MonkeyPatch) -> None:
    if value is None:
        monkeypatch.delenv("TWIN_ASR_KEY", raising=False)
    else:
        monkeypatch.setenv("TWIN_ASR_KEY", value)
    with pytest.raises(MediaUnavailable) as error:
        make_recognizer(ASRSettings(provider="cloudflare", base_url=BASE))
    assert KEY not in str(error.value) and BASE not in str(error.value)

    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"text": request.headers["authorization"]})

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        recognizer = OpenAICompatTranscription("local", BASE, client=client)
        result = recognizer.transcribe(TranscriptionRequest(audio=AUDIO))
        assert result.text == "Bearer [redacted]"


@pytest.mark.parametrize(
    "body", [b"not JSON", b'{"text":"x","duration":Infinity,"transcription_info":{"duration":Infinity}}']
)
def test_malformed_json_and_nonfinite_duration(backend: Harness, body: bytes) -> None:
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, content=body))) as client:
        recognizer: SpeechRecognizer = (
            CloudflareWhisper(BASE, client=client)
            if backend.variant.startswith("cloudflare")
            else OpenAICompatTranscription("local", BASE, client=client)
        )
        with pytest.raises(MediaUnavailable):
            recognizer.transcribe(TranscriptionRequest(audio=AUDIO))


@pytest.mark.parametrize("base_url", ["ftp://private.invalid", "https://[", "https://user:secret@host.invalid"])
def test_bad_endpoint_does_not_leak(base_url: str) -> None:
    with pytest.raises(ValueError) as error:
        OpenAICompatTranscription("local", base_url)
    assert base_url not in str(error.value)


def test_identity_depends_on_endpoint_and_model_not_key(monkeypatch: pytest.MonkeyPatch) -> None:
    original = OpenAICompatTranscription("a", BASE).identity
    monkeypatch.setenv("TWIN_ASR_KEY", KEY)
    assert original == OpenAICompatTranscription("a", BASE).identity
    assert original != OpenAICompatTranscription("b", BASE).identity
    assert original != OpenAICompatTranscription("a", BASE + "/other").identity
