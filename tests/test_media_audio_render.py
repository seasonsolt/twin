"""Offline audio rendering, cache, labels, traceability and permissions."""

from __future__ import annotations

import base64
import datetime as dt
import io
import json
import wave
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from twin.media import render
from twin.media.render import export_html, render_audio
from twin.media.schema import (
    AudioManifest,
    AudioPart,
    AudioRender,
    MediaScript,
    Segment,
    SpeechRequest,
    SpeechResult,
    SynthCapabilities,
    VoiceSpec,
)
from twin.media.speech_text import SPEECH_TEXT_VERSION, speech_text
from twin.media.tts import CloudflareMeloTTS, OpenAICompatSpeech, SilentSynthesizer, SpeechSynthesizer


class Recorder:
    """Protocol-only decorator to prove rendering does not inspect concrete backends."""

    def __init__(self, inner: SpeechSynthesizer) -> None:
        self.inner = inner
        self.name = inner.name
        self.voice = inner.voice
        self.capabilities = inner.capabilities
        self.calls: list[SpeechRequest] = []

    @property
    def identity(self) -> str:
        return self.inner.identity

    def synthesize(self, request: SpeechRequest) -> SpeechResult:
        self.calls.append(request)
        return self.inner.synthesize(request)


@pytest.fixture(params=["silent", "cloudflare", "openai"])
def synth(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> Iterator[Recorder]:
    monkeypatch.setenv("TWIN_TTS_KEY", "offline-test-key")
    wav = SilentSynthesizer().synthesize(SpeechRequest(text="测试。")).audio
    mp3 = b"\xff\xfb\x90\x00" + b"\0" * 413

    def handle(req: httpx.Request) -> httpx.Response:
        if req.method == "GET":
            return httpx.Response(404)
        if request.param == "cloudflare":
            return httpx.Response(200, json={"result": {"audio": base64.b64encode(mp3).decode()}, "success": True})
        return httpx.Response(200, content=wav, headers={"content-type": "audio/wav"})

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        inner: SpeechSynthesizer
        if request.param == "silent":
            inner = SilentSynthesizer(provides_timings=True)
        elif request.param == "cloudflare":
            inner = CloudflareMeloTTS("https://speech.invalid/ai", client=client)
        else:
            inner = OpenAICompatSpeech("local-tts", "https://speech.invalid/v1", client=client)
        yield Recorder(inner)


def make_script(
    *, abstain: bool = False, text: str = "第一句。第二句。", fingerprint: str = "source-one"
) -> MediaScript:
    return MediaScript(
        source_kind="chat_reply",
        source_fingerprint=fingerprint,
        persona_name="合成人物",
        as_of=None,
        confidence=0.8,
        abstain=abstain,
        segments=[
            Segment(
                index=0, kind="notice" if abstain else "speech", text="资料不足，请向本人确认。" if abstain else text
            ),
        ],
        citations=[],
    )


def wav_comments(data: bytes) -> list[str]:
    assert data[:4] == b"RIFF" and data[8:12] == b"WAVE"
    assert int.from_bytes(data[4:8], "little") + 8 == len(data)
    offset = 12
    comments: list[str] = []
    while offset < len(data):
        size = int.from_bytes(data[offset + 4 : offset + 8], "little")
        chunk = data[offset + 8 : offset + 8 + size]
        if data[offset : offset + 4] == b"LIST" and chunk[:4] == b"INFO":
            suboffset = 4
            while suboffset < len(chunk):
                subsize = int.from_bytes(chunk[suboffset + 4 : suboffset + 8], "little")
                if chunk[suboffset : suboffset + 4] == b"ICMT":
                    comments.append(chunk[suboffset + 8 : suboffset + 8 + subsize].rstrip(b"\0").decode("utf-8"))
                suboffset += 8 + subsize + subsize % 2
        offset += 8 + size + size % 2
    assert offset == len(data)
    return comments


def mp3_comments(data: bytes) -> list[str]:
    assert data[:6] == b"ID3\x03\x00\x00"
    assert all(n < 128 for n in data[6:10])
    end = 10 + sum(n << shift for n, shift in zip(data[6:10], (21, 14, 7, 0), strict=True))
    offset = 10
    comments: list[str] = []
    while offset < end:
        frame_id = data[offset : offset + 4]
        size = int.from_bytes(data[offset + 4 : offset + 8], "big")
        payload = data[offset + 10 : offset + 10 + size]
        if frame_id == b"TXXX":
            assert payload[0] == 1
            separator = next(i for i in range(1, len(payload), 2) if payload[i : i + 2] == b"\0\0")
            assert payload[1:separator].decode("utf-16") == "AI-generated"
            comments.append(payload[separator + 2 :].decode("utf-16"))
        offset += 10 + size
    assert offset == end
    assert data[end : end + 2] == b"\xff\xfb"
    return comments


def test_cache_hit_has_zero_calls_and_manifest_is_private(synth: Recorder, tmp_path: Path) -> None:
    script = make_script()
    result = render_audio(script, synth, tmp_path / "nested" / "audio")
    calls = len(synth.calls)
    assert calls == len(script.segments)
    assert [call.text for call in synth.calls] == [
        speech_text(segment.text, synth.voice.language, capabilities=synth.capabilities) for segment in script.segments
    ]
    directory = tmp_path / "nested" / "audio"
    raw = (directory / result.manifest_file).read_text()
    manifest = AudioManifest.model_validate_json(raw)
    assert manifest.ai_generated
    assert manifest.source_fingerprint == script.source_fingerprint
    assert manifest.voice == synth.voice
    assert manifest.backend == synth.name
    assert manifest.created_at.tzinfo is not None
    assert manifest.segments == result.segments
    assert "speech.invalid" not in raw
    assert AudioRender.model_validate_json(result.model_dump_json()) == result
    synth.calls.clear()
    again = render_audio(script, synth, directory)
    assert not synth.calls
    assert again == result
    for file in directory.rglob("*"):
        if file.is_file():
            assert file.stat().st_mode & 0o777 == 0o600
        else:
            assert file.stat().st_mode & 0o777 == 0o700


def test_abstain_speaks_notices_only_even_with_stray_speech(synth: Recorder, tmp_path: Path) -> None:
    script = make_script(abstain=True)
    script = script.model_copy(
        update={"segments": [*script.segments, Segment(index=1, kind="speech", text="不可播放。")]}
    )
    result = render_audio(script, synth, tmp_path)
    assert [segment.kind for segment in result.segments] == ["notice"]
    assert [call.text for call in synth.calls] == ["资料不足，请向本人确认。"]


def test_split_order_and_sentence_comma_preference(synth: Recorder, tmp_path: Path) -> None:
    synth.capabilities = synth.capabilities.model_copy(update={"max_chars": 8})
    text = "第一句。第二句，第三句特别长没有标点结束。"
    result = render_audio(make_script(text=text), synth, tmp_path)
    pieces = result.segments[0].parts
    assert [part.text for part in pieces] == ["第一句。", "第二句，", "第三句特别长没有", "标点结束。"]
    assert "".join(part.text for part in pieces) == text
    assert all(len(call.text) <= 8 for call in synth.calls)
    assert [call.text for call in synth.calls] == [
        part.spoken_text for segment in result.segments for part in segment.parts
    ]
    synth.calls.clear()
    render_audio(make_script(text=text), synth, tmp_path)
    assert not synth.calls


@pytest.mark.parametrize("fingerprint", ["odd", "合成指纹-even"])
def test_metadata_is_readable_and_audio_survives(synth: Recorder, tmp_path: Path, fingerprint: str) -> None:
    result = render_audio(make_script(fingerprint=fingerprint), synth, tmp_path)
    for segment in result.segments:
        for part in segment.parts:
            audio = (tmp_path / part.file_name).read_bytes()
            comments = wav_comments(audio) if part.audio_format == "wav" else mp3_comments(audio)
            assert comments == [f"AI-generated; twin; source {fingerprint}"]
            if part.audio_format == "wav":
                with wave.open(io.BytesIO(audio), "rb") as parsed:
                    assert parsed.getnframes() > 0
                    assert part.duration_s == pytest.approx(parsed.getnframes() / parsed.getframerate())
            if synth.capabilities.provides_timings:
                assert part.timings and part.duration_s is not None
                assert part.timings[-1].end_s == pytest.approx(part.duration_s)
            else:
                assert part.timings is None


def test_cache_audio_shared_but_fingerprint_labels_are_not(synth: Recorder, tmp_path: Path) -> None:
    first = render_audio(make_script(fingerprint="one"), synth, tmp_path)
    synth.calls.clear()
    second = render_audio(make_script(fingerprint="two"), synth, tmp_path)
    assert not synth.calls
    assert first.manifest_file != second.manifest_file
    assert first.segments[0].parts[0].file_name != second.segments[0].parts[0].file_name
    for result, source in ((first, "one"), (second, "two")):
        part = result.segments[0].parts[0]
        data = (tmp_path / part.file_name).read_bytes()
        comments = wav_comments(data) if part.audio_format == "wav" else mp3_comments(data)
        assert comments[0].endswith(f"source {source}")


def test_voice_and_algorithm_settings_invalidate_cache(tmp_path: Path) -> None:
    first = Recorder(SilentSynthesizer())
    render_audio(make_script(), first, tmp_path)
    for inner in (
        SilentSynthesizer(voice=VoiceSpec(language="en")),
        SilentSynthesizer(provides_timings=True),
        SilentSynthesizer(sample_rate=8000),
    ):
        recorder = Recorder(inner)
        render_audio(make_script(), recorder, tmp_path)
        assert recorder.calls


def test_corrupt_cache_recovers_and_permissions_are_tightened(tmp_path: Path) -> None:
    synth = Recorder(SilentSynthesizer())
    result = render_audio(make_script(), synth, tmp_path)
    cached = next((tmp_path / "requests").glob("*.json"))
    cached.write_text("{broken")
    for file in tmp_path.rglob("*"):
        if file.is_file():
            file.chmod(0o666)
    synth.calls.clear()
    render_audio(make_script(), synth, tmp_path)
    assert len(synth.calls) == 1
    assert all(file.stat().st_mode & 0o777 == 0o600 for file in tmp_path.rglob("*") if file.is_file())
    assert (tmp_path / result.manifest_file).is_file()


def test_mp3_existing_id3_tag_is_replaced_offline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TWIN_TTS_KEY", "offline-test-key")
    mp3 = b"ID3\x03\x00\x00\x00\x00\x00\x04junk" + b"\xff\xfb\x90\x00" + b"\0" * 413
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, content=mp3, headers={"content-type": "audio/mpeg"})
        )
    ) as client:
        synth = CloudflareMeloTTS("https://speech.invalid/ai", client=client)
        result = render_audio(make_script(), synth, tmp_path)
        assert mp3_comments((tmp_path / result.segments[0].parts[0].file_name).read_bytes()) == [
            "AI-generated; twin; source source-one"
        ]


def test_wav_result_for_mp3_request_is_labelled_and_cached_as_wav(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TWIN_TTS_KEY", "offline-test-key")
    wav = SilentSynthesizer(sample_rate=44100).synthesize(SpeechRequest(text="测试。")).audio
    envelope = {
        "result": {"audio": base64.b64encode(wav).decode()},
        "success": True,
        "errors": [],
        "messages": [],
    }
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=envelope))) as client:
        synth = Recorder(CloudflareMeloTTS("https://speech.invalid/ai", client=client))
        script = make_script()
        result = render_audio(script, synth, tmp_path)
        assert synth.calls and all(request.audio_format == "mp3" for request in synth.calls)
        manifest = AudioManifest.model_validate_json((tmp_path / result.manifest_file).read_bytes())
        assert manifest.segments == result.segments
        for segment in manifest.segments:
            for part in segment.parts:
                assert part.audio_format == "wav"
                assert part.file_name.endswith(".wav")
                audio = (tmp_path / part.file_name).read_bytes()
                assert audio.startswith(b"RIFF") and not audio.startswith(b"ID3")
                assert wav_comments(audio) == [f"AI-generated; twin; source {script.source_fingerprint}"]
                with wave.open(io.BytesIO(audio), "rb") as parsed, wave.open(io.BytesIO(wav), "rb") as original:
                    assert parsed.getframerate() == 44100
                    assert parsed.getsampwidth() == 2
                    assert parsed.getnchannels() == 1
                    assert part.duration_s == pytest.approx(parsed.getnframes() / parsed.getframerate())
                    assert parsed.readframes(parsed.getnframes()) == original.readframes(original.getnframes())
        assert not list(tmp_path.glob("*.mp3"))
        for path in (tmp_path / "requests").glob("*.json"):
            cached = json.loads(path.read_bytes())
            assert cached["audio_format"] == "wav" and cached["sample_rate"] == 44100
        synth.calls.clear()
        assert render_audio(script, synth, tmp_path) == result
        assert not synth.calls


def test_cache_key_matches_identity_and_request(tmp_path: Path) -> None:
    synth = Recorder(SilentSynthesizer())
    render_audio(make_script(), synth, tmp_path)
    import hashlib

    for request in synth.calls:
        value = {
            "identity": synth.identity,
            "request": request.model_dump(mode="json"),
            "speech_text_version": SPEECH_TEXT_VERSION,
        }
        key = hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        cache = json.loads((tmp_path / "requests" / (key + ".json")).read_text())
        assert base64.b64decode(cache["audio"])
        assert "extras" not in cache


def test_render_declared_format_not_backend_name(tmp_path: Path) -> None:
    synth = Recorder(SilentSynthesizer())
    synth.name = "unknown-custom-backend"
    synth.capabilities = SynthCapabilities(audio_formats=["wav"])
    result = render_audio(make_script(), synth, tmp_path)
    assert all(part.audio_format == "wav" for segment in result.segments for part in segment.parts)


def test_spoken_text_is_recorded_without_rewriting_script_or_html(synth: Recorder, tmp_path: Path) -> None:
    text = "AI增长3.5%，有2个项目，2026年10月4日18:30复核，版本v1.2。"
    script = make_script(text=text)
    before = script.model_dump_json()
    html = export_html(script, clock=lambda: dt.datetime(2026, 10, 4, tzinfo=dt.UTC))
    result = render_audio(script, synth, tmp_path)
    manifest = AudioManifest.model_validate_json((tmp_path / result.manifest_file).read_bytes())
    assert script.model_dump_json() == before
    assert script.segments[0].text == text
    assert text in html
    assert export_html(script, clock=lambda: dt.datetime(2026, 10, 4, tzinfo=dt.UTC)) == html
    assert manifest.speech_text_version == SPEECH_TEXT_VERSION
    assert [part.spoken_text for segment in manifest.segments for part in segment.parts] == [
        request.text for request in synth.calls
    ]
    for original, segment in zip(script.segments, manifest.segments, strict=True):
        assert "".join(part.text for part in segment.parts) == original.text
        assert "".join(part.spoken_text for part in segment.parts) == speech_text(
            original.text, synth.voice.language, capabilities=synth.capabilities
        )
        assert all(part.speech_text_version == SPEECH_TEXT_VERSION for part in segment.parts)
    assert "百分之三点五" in synth.calls[0].text
    assert synth.calls[0].text.startswith("AI" if synth.capabilities.reads_latin_acronyms else "A I")


@pytest.mark.parametrize("max_chars", [2, 3, 5, 8, 20])
@pytest.mark.parametrize(
    "text", ["AI在3.5%的区间，有1,200个项目。v1.2；18:30。", "请用AI辅助整理，但不要生成新的事实。"]
)
def test_split_limit_applies_after_normalization(max_chars: int, text: str, tmp_path: Path) -> None:
    synth = Recorder(SilentSynthesizer(max_chars=max_chars, provides_timings=True))
    synth.capabilities = synth.capabilities.model_copy(update={"reads_latin_acronyms": False})
    script = make_script(text=text)
    result = render_audio(script, synth, tmp_path)
    for original, segment in zip(script.segments, result.segments, strict=True):
        assert "".join(part.text for part in segment.parts) == original.text
        assert "".join(part.spoken_text for part in segment.parts) == speech_text(
            original.text, synth.voice.language, capabilities=synth.capabilities
        )
        assert all(len(part.spoken_text) <= max_chars for part in segment.parts)
        assert all(part.timings and part.timings[0].text == part.spoken_text[0] for part in segment.parts)
    assert all(len(request.text) <= max_chars for request in synth.calls)
    synth.calls.clear()
    assert render_audio(script, synth, tmp_path) == result
    assert not synth.calls


def test_capability_not_backend_name_controls_acronyms(tmp_path: Path) -> None:
    synth = Recorder(SilentSynthesizer())
    synth.name = "cloudflare:melotts"
    first = render_audio(make_script(text="AI有3个项目。"), synth, tmp_path)
    assert synth.calls[0].text == "AI 有三个项目。"
    synth.name = "custom-backend"
    synth.capabilities = synth.capabilities.model_copy(update={"reads_latin_acronyms": False})
    synth.calls.clear()
    second = render_audio(make_script(text="AI有3个项目。"), synth, tmp_path)
    assert synth.calls[0].text == "A I 有三个项目。"
    assert first.segments[0].parts[0].file_name != second.segments[0].parts[0].file_name
    assert first.manifest_file != second.manifest_file


def test_normalization_version_invalidates_unchanged_spoken_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    synth = Recorder(SilentSynthesizer())
    script = make_script()
    first = render_audio(script, synth, tmp_path)
    original_cache = set((tmp_path / "requests").glob("*.json"))
    original_spoken = [request.text for request in synth.calls]
    monkeypatch.setattr(render, "SPEECH_TEXT_VERSION", SPEECH_TEXT_VERSION + 1)
    synth.calls.clear()
    second = render_audio(script, synth, tmp_path)
    assert [request.text for request in synth.calls] == original_spoken
    assert len(set((tmp_path / "requests").glob("*.json")) - original_cache) == len(synth.calls)
    assert first.manifest_file != second.manifest_file
    assert first.segments[0].parts[0].file_name != second.segments[0].parts[0].file_name
    manifest = AudioManifest.model_validate_json((tmp_path / second.manifest_file).read_bytes())
    assert manifest.speech_text_version == SPEECH_TEXT_VERSION + 1
    assert all(part.speech_text_version == SPEECH_TEXT_VERSION + 1 for part in second.segments[0].parts)


def test_segmentation_version_invalidates_manifest_but_reuses_identical_audio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    synth = Recorder(SilentSynthesizer())
    script = make_script()
    first = render_audio(script, synth, tmp_path, segments=[0])
    monkeypatch.setattr(render, "SPEECH_SEGMENT_VERSION", render.SPEECH_SEGMENT_VERSION + 1)
    synth.calls.clear()
    second = render_audio(script, synth, tmp_path, segments=[0])
    assert first.manifest_file != second.manifest_file
    assert not synth.calls
    assert first.segments == second.segments


def test_part_warnings_survive_manifest_and_cache_without_reading_extras(tmp_path: Path) -> None:
    class WarningSynth(SilentSynthesizer):
        calls = 0

        def synthesize(self, request: SpeechRequest) -> SpeechResult:
            self.calls += 1
            return (
                super()
                .synthesize(request)
                .model_copy(update={"warnings": ["possibly-truncated"], "extras": {"opaque": "never-read"}})
            )

    synth = WarningSynth()
    script = make_script(text="请用AI辅助整理，但不要生成新的事实。")
    first = render_audio(script, synth, tmp_path)
    manifest = AudioManifest.model_validate_json((tmp_path / first.manifest_file).read_bytes())
    assert all(part.warnings == ["possibly-truncated"] for segment in manifest.segments for part in segment.parts)
    for cached in (tmp_path / "requests").glob("*.json"):
        value = json.loads(cached.read_text())
        assert value["warnings"] == ["possibly-truncated"] and "extras" not in value
    calls = synth.calls
    second = render_audio(script, synth, tmp_path)
    assert first == second and synth.calls == calls


def test_legacy_audio_contracts_keep_defaults() -> None:
    part = AudioPart.model_validate({"text": "3.5%", "file_name": "old.wav"})
    assert part.spoken_text == "" and part.warnings == []
    assert part.speech_text_version == 0
    manifest = AudioManifest.model_validate({"source_fingerprint": "old", "created_at": "2026-10-04T00:00:00Z"})
    assert manifest.speech_text_version == 0
    assert SynthCapabilities.model_validate({}).reads_latin_acronyms
