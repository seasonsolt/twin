"""Offline B2 conformance: every backend obeys the same normalized speech contract."""

from __future__ import annotations

import base64
import io
import json
import traceback
import wave
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from twin.config import Settings, TTSSettings, load_settings, make_synthesizer
from twin.media.schema import AudioFormat, SpeechRequest, SpeechResult, SynthCapabilities, VoiceSpec
from twin.media.tts import (
    CloudflareMeloTTS,
    MediaInputTooLong,
    MediaRejected,
    MediaTimeout,
    MediaUnavailable,
    OpenAICompatSpeech,
    SilentSynthesizer,
    SpeechSynthesizer,
)

KEY = "super-secret-test-token"
BASE = "https://speech.invalid/private-account/ai"
MP3 = b"\xff\xfb\x90\x00" + b"\0" * 413


def wav_bytes(sample_rate: int = 16000) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(sample_rate)
        audio.writeframes(b"\0\0" * (sample_rate // 10))
    return buffer.getvalue()


class Harness:
    def __init__(self, variant: str, client: httpx.Client) -> None:
        self.variant = variant
        self.calls: list[httpx.Request] = []
        self.status = 200
        self.timeout = False
        self.invalid = False
        self.synth: SpeechSynthesizer
        if variant == "silent":
            self.synth = SilentSynthesizer(provides_timings=True)
        elif variant.startswith("cloudflare"):
            self.synth = CloudflareMeloTTS(BASE, client=client, max_retries=2)
        else:
            self.synth = OpenAICompatSpeech("local-tts", BASE, client=client, max_retries=2)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        assert request.headers["authorization"] == f"Bearer {KEY}"
        if self.timeout:
            raise httpx.ReadTimeout(f"{KEY} {BASE}", request=request)
        if self.status != 200:
            return httpx.Response(self.status, text=f"{KEY} {BASE}")
        if self.invalid:
            return httpx.Response(200, json={"audio": "not-base64", "error": f"{KEY} {BASE}"})
        payload = json.loads(request.content)
        if self.variant.startswith("cloudflare"):
            assert str(request.url) == BASE + "/run/@cf/myshell-ai/melotts"
            assert set(payload) == {"prompt", "lang"}
            assert payload["lang"] == "zh"
            if self.variant == "cloudflare-binary":
                return httpx.Response(200, content=MP3, headers={"content-type": "audio/mpeg"})
            if self.variant == "cloudflare-wav-envelope":
                return httpx.Response(
                    200,
                    json={
                        "result": {"audio": base64.b64encode(wav_bytes(44100)).decode()},
                        "success": True,
                        "errors": [],
                        "messages": [],
                    },
                )
            audio = b"ID3\x03\x00\x00\x00\x00\x00\x00" + MP3 if self.variant == "cloudflare-id3" else MP3
            result = {"audio": base64.b64encode(audio).decode(), "vendor_token": f"{KEY} {BASE}"}
            if self.variant == "cloudflare-envelope":
                return httpx.Response(200, json={"result": result, "success": True, "errors": []})
            return httpx.Response(200, json=result)
        assert str(request.url) == BASE + "/audio/speech"
        assert set(payload) == {"model", "input", "voice", "response_format"}
        assert payload["model"] == "local-tts"
        assert payload["voice"] == "default"
        fmt = payload["response_format"]
        return httpx.Response(
            200,
            content=wav_bytes() if fmt == "wav" else MP3,
            headers={"content-type": "audio/wav" if fmt == "wav" else "audio/mpeg"},
        )


@pytest.fixture(
    params=[
        "silent",
        "cloudflare-json",
        "cloudflare-envelope",
        "cloudflare-binary",
        "cloudflare-wav-envelope",
        "cloudflare-id3",
        "openai",
    ]
)
def backend(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> Iterator[Harness]:
    monkeypatch.setenv("TWIN_TTS_KEY", KEY)
    monkeypatch.setattr("twin.media.tts.time.sleep", lambda _: None)
    holder: list[Harness] = []
    with httpx.Client(transport=httpx.MockTransport(lambda req: holder[0].handle(req))) as client:
        harness = Harness(request.param, client)
        holder.append(harness)
        yield harness


def speech_request(synth: SpeechSynthesizer, fmt: AudioFormat | None = None) -> SpeechRequest:
    return SpeechRequest(
        text="你好，世界。", voice=synth.voice, audio_format=fmt or synth.capabilities.audio_formats[0]
    )


def test_success_contract(backend: Harness) -> None:
    for fmt in backend.synth.capabilities.audio_formats:
        request = speech_request(backend.synth, fmt)
        result = backend.synth.synthesize(request)
        assert result.schema_version == 1
        assert result.audio_format in backend.synth.capabilities.audio_formats
        if backend.variant.startswith("cloudflare"):
            expected = "wav" if backend.variant == "cloudflare-wav-envelope" else "mp3"
            assert result.audio_format == expected
        else:
            assert result.audio_format == request.audio_format
        assert result.audio
        assert set(SpeechResult.model_fields) == {
            "schema_version",
            "audio",
            "audio_format",
            "sample_rate",
            "duration_s",
            "timings",
            "extras",
            "warnings",
        }
        assert KEY not in str(result.extras) and BASE not in str(result.extras)
        assert all(isinstance(k, str) and isinstance(v, str) for k, v in result.extras.items())
        if backend.variant.startswith("cloudflare"):
            assert result.timings is None
            if result.audio_format == "wav":
                assert result.audio == wav_bytes(44100)
                assert result.sample_rate == 44100
                assert result.duration_s == pytest.approx(0.1)
            else:
                assert result.duration_s is None
                assert result.sample_rate is None
            if backend.variant not in {"cloudflare-binary", "cloudflare-wav-envelope"}:
                assert result.extras["vendor_token"] == "[redacted] [redacted]"
        if backend.synth.capabilities.provides_timings:
            assert result.timings and result.duration_s is not None
            assert "".join(t.text for t in result.timings) == request.text
            assert result.timings[-1].end_s == pytest.approx(result.duration_s)
        assert not backend.synth.capabilities.streaming
        assert KEY not in backend.synth.identity and BASE not in backend.synth.identity


@pytest.mark.parametrize("warning", [None, "possibly-truncated", f"{KEY} {BASE}"])
@pytest.mark.parametrize("audio_format", ["wav", "mp3"])
def test_openai_warning_header_maps_to_extras_and_normalized_contract(
    warning: str | None, audio_format: AudioFormat, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TWIN_TTS_KEY", KEY)

    def handle(request: httpx.Request) -> httpx.Response:
        headers = {"content-type": "audio/wav" if audio_format == "wav" else "audio/mpeg"}
        if warning is not None:
            headers["x-speech-warning"] = warning
        return httpx.Response(200, content=wav_bytes() if audio_format == "wav" else MP3, headers=headers)

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        synth = OpenAICompatSpeech("local", BASE, client=client)
        result = synth.synthesize(speech_request(synth, audio_format))
    if warning is None:
        assert result.extras == {} and result.warnings == []
    elif warning == "possibly-truncated":
        assert result.extras["warning"] == warning and result.warnings == [warning]
    else:
        assert result.extras["warning"] == "[redacted] [redacted]" and result.warnings == []
    assert SpeechResult.model_validate({}).warnings == []


def test_too_long_is_local_and_never_split_by_backend(backend: Harness) -> None:
    request = speech_request(backend.synth).model_copy(
        update={"text": "长" * (backend.synth.capabilities.max_chars + 1)}
    )
    with pytest.raises(MediaInputTooLong):
        backend.synth.synthesize(request)
    assert not backend.calls


def test_capability_rejections_are_local(backend: Harness) -> None:
    request = speech_request(backend.synth)
    for update in ({"text": ""}, {"voice": VoiceSpec(language="unsupported")}):
        with pytest.raises(MediaRejected):
            backend.synth.synthesize(request.model_copy(update=update))
    if len(backend.synth.capabilities.audio_formats) == 1:
        other = "mp3" if request.audio_format == "wav" else "wav"
        with pytest.raises(MediaRejected):
            backend.synth.synthesize(request.model_copy(update={"audio_format": other}))
    assert not backend.calls


@pytest.mark.parametrize("status", [400, 401, 403])
def test_http_rejected_without_retry(backend: Harness, status: int) -> None:
    if backend.variant == "silent":
        return
    backend.status = status
    with pytest.raises(MediaRejected) as error:
        backend.synth.synthesize(speech_request(backend.synth))
    assert len(backend.calls) == 1
    assert KEY not in str(error.value) and BASE not in str(error.value)


@pytest.mark.parametrize("failure", ["unavailable", "timeout"])
def test_retry_exhaustion_and_secret_free_traceback(backend: Harness, failure: str) -> None:
    if backend.variant == "silent":
        return
    backend.status = 503
    backend.timeout = failure == "timeout"
    kind = MediaTimeout if backend.timeout else MediaUnavailable
    with pytest.raises(kind) as error:
        backend.synth.synthesize(speech_request(backend.synth))
    assert len(backend.calls) == 3
    rendered = "".join(traceback.format_exception(error.value))
    assert KEY not in rendered and BASE not in rendered


def test_invalid_response_is_sanitized(backend: Harness) -> None:
    if backend.variant == "silent":
        return
    backend.invalid = True
    with pytest.raises(MediaUnavailable) as error:
        backend.synth.synthesize(speech_request(backend.synth))
    assert KEY not in str(error.value) and BASE not in str(error.value)


def test_silence_is_deterministic_and_proportional() -> None:
    synth = SilentSynthesizer()
    one = synth.synthesize(SpeechRequest(text="一"))
    two = synth.synthesize(SpeechRequest(text="一二"))
    assert one == synth.synthesize(SpeechRequest(text="一"))
    assert one.duration_s is not None and two.duration_s == 2 * one.duration_s
    assert one.timings is None
    with wave.open(io.BytesIO(one.audio), "rb") as audio:
        assert audio.getframerate() == one.sample_rate
        assert set(audio.readframes(audio.getnframes())) == {0}


def test_contract_defaults_and_vendor_field_rejection() -> None:
    assert SpeechRequest().schema_version == SpeechResult().schema_version == SynthCapabilities().schema_version == 1
    with pytest.raises(ValidationError):
        SpeechResult.model_validate({"vendor_audio": "abc"})
    with pytest.raises(ValidationError):
        SynthCapabilities(max_chars=0)


@pytest.mark.parametrize("provider", ["silent", "cloudflare", "openai_compat"])
def test_factory_configuration(provider: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TWIN_TTS_KEY", KEY)
    path = tmp_path / "settings.toml"
    path.write_text(
        f'[tts]\nprovider = "{provider}"\nmodel = "local-tts"\nbase_url = "{BASE}"\n'
        'voice = "preset"\nlanguage = "en"\ntimeout = 12\nmax_retries = 0\n'
    )
    settings = load_settings(path)
    synth = make_synthesizer(settings.tts)
    assert synth.voice.voice_id == "preset"
    assert synth.voice.language == "en"
    assert synth.capabilities.languages == ["en"]
    assert KEY not in settings.model_dump_json()
    assert KEY not in synth.identity and BASE not in synth.identity
    assert make_synthesizer(Settings().tts).name == "silent"


@pytest.mark.parametrize("provider", ["cloudflare", "openai_compat"])
def test_factory_requires_explicit_endpoint(provider: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_BASE_URL", BASE)
    with pytest.raises(ValueError, match=r"\[tts\].*base_url"):
        make_synthesizer(TTSSettings.model_validate({"provider": provider, "model": "local-tts"}))


@pytest.mark.parametrize("variable", ["TWIN_TTS_KEY", "TWIN_CUSTOM_SPEECH_KEY"])
@pytest.mark.parametrize("value", [None, ""])
def test_cloudflare_requires_credentials(variable: str, value: str | None, monkeypatch: pytest.MonkeyPatch) -> None:
    if value is None:
        monkeypatch.delenv(variable, raising=False)
    else:
        monkeypatch.setenv(variable, value)
    with pytest.raises(MediaUnavailable, match=variable) as error:
        CloudflareMeloTTS(BASE, api_key_env=variable)
    assert BASE not in str(error.value)
    assert KEY not in str(error.value)
    assert OpenAICompatSpeech("local-tts", BASE, api_key_env=variable).name == "openai_compat:speech"
    monkeypatch.setenv(variable, KEY)
    assert CloudflareMeloTTS(BASE, api_key_env=variable).name == "cloudflare:melotts"


@pytest.mark.parametrize("audio", [b"", b"unknown-container", b"RIFF\x04\x00\x00\x00WAVE", b"\xff"])
def test_cloudflare_rejects_unknown_or_invalid_container(audio: bytes, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TWIN_TTS_KEY", KEY)
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={
                    "result": {"audio": base64.b64encode(audio).decode()},
                    "success": True,
                    "errors": [],
                    "messages": [],
                },
            )
        )
    ) as client:
        synth = CloudflareMeloTTS(BASE, client=client)
        with pytest.raises(MediaUnavailable) as error:
            synth.synthesize(speech_request(synth, "mp3"))
        rendered = "".join(traceback.format_exception(error.value))
        assert KEY not in rendered and BASE not in rendered


def test_factory_requires_shim_model() -> None:
    with pytest.raises(ValueError, match=r"\[tts\].*model"):
        make_synthesizer(TTSSettings(provider="openai_compat", base_url=BASE))


def test_cache_identity_is_endpoint_and_model_sensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    first = OpenAICompatSpeech("a", BASE)
    assert first.identity != OpenAICompatSpeech("b", BASE).identity
    assert first.identity != OpenAICompatSpeech("a", BASE + "/other").identity
    monkeypatch.setenv("TWIN_TTS_KEY", "another-key")
    assert first.identity == OpenAICompatSpeech("a", BASE).identity
