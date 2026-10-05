"""Offline speech HTTP and CLI integration, using only deterministic silence."""

from __future__ import annotations

import io
import json
import stat
import wave
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from twin.cli import app
from twin.config import Settings, TTSSettings
from twin.media.schema import OPENING_NOTICE
from twin.media.tts import (
    MediaError,
    MediaInputTooLong,
    MediaRejected,
    MediaTimeout,
    MediaUnavailable,
    SilentSynthesizer,
    SpeechSynthesizer,
)
from twin.web import create_app
from twin.web.app import MAX_JSON_BYTES

HEADERS = {"X-Twin": "1"}
SOURCE: dict[str, Any] = {
    "reply": "先验证。再推进。",
    "citations": [],
    "confidence": 0.8,
    "abstain": False,
    "abstain_reason": "",
    "retrieved_ids": [],
}
BODY = {"kind": "chat_reply", "answer": SOURCE, "persona_name": "合成人物"}


def configured_silence() -> SilentSynthesizer:
    synth = SilentSynthesizer(max_chars=20)
    synth.name = "openai_compat:speech"
    return synth


def test_capabilities_are_lazy_and_secret_free(tmp_path: Path) -> None:
    calls = 0

    def factory() -> SpeechSynthesizer:
        nonlocal calls
        calls += 1
        return configured_silence()

    settings = Settings(db_path=tmp_path / "twin.db")
    web = create_app(settings, synthesizer_factory=factory)
    assert calls == 0
    with TestClient(web, base_url="http://localhost") as client:
        assert client.get("/").status_code == 200
        assert calls == 0
        response = client.get("/api/media/capabilities")
        assert response.status_code == 200
        assert response.json() == {
            "available": True,
            "backend": "openai_compat:speech",
            "label": "AI 合成 · 模拟推演，不代表本人意见",
            "languages": ["zh"],
            "audio_formats": ["wav"],
        }
        client.get("/api/media/capabilities")
        assert calls == 1
        assert response.headers["cache-control"] == "no-store"
    for factory in (None, SilentSynthesizer):
        with TestClient(create_app(settings, synthesizer_factory=factory), base_url="http://localhost") as client:
            assert client.get("/api/media/capabilities").json()["available"] is False


def test_audio_urls_metadata_and_hardening(tmp_path: Path) -> None:
    settings = Settings(db_path=tmp_path / "twin.db")
    (tmp_path / "media-cache").mkdir(mode=0o755)
    (tmp_path / "media-cache" / "requests").mkdir(mode=0o755)
    with TestClient(create_app(settings, synthesizer_factory=SilentSynthesizer), base_url="http://localhost") as client:
        response = client.post("/api/media/audio", json=BODY, headers=HEADERS)
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["script"]["segments"][0]["text"] == OPENING_NOTICE
        assert result["segments"][0]["index"] == 0
        assert result["manifest"]["ai_generated"] is True
        assert result["manifest"]["generator"] == "twin"
        assert "AI 合成" in result["manifest"]["label"]
        assert response.headers["cache-control"] == "no-store"
        assert len(result["segments"]) == 3
        for segment in result["segments"]:
            audio = client.get(segment["url"])
            assert audio.status_code == 200
            assert audio.headers["content-type"] == "audio/wav"
            assert audio.headers["cache-control"] == "private, no-store"
            assert audio.headers["x-content-type-options"] == "nosniff"
            assert audio.headers["x-frame-options"] == "DENY"
            assert "default-src 'self'" in audio.headers["content-security-policy"]
            assert b"AI-generated; twin; source " in audio.content
            assert result["manifest"]["source_fingerprint"].encode() in audio.content
            with wave.open(io.BytesIO(audio.content), "rb") as wav:
                assert wav.getnchannels() == 1
                assert wav.getnframes() > 0
        repeated = client.post("/api/media/audio", json=BODY, headers=HEADERS).json()
        assert repeated["segments"] == result["segments"]
        abstention = {**SOURCE, "abstain": True, "abstain_reason": "依据不足"}
        result = client.post("/api/media/audio", json={**BODY, "answer": abstention}, headers=HEADERS).json()
        assert all(segment["kind"] == "notice" for segment in result["manifest"]["segments"])
        for path in (tmp_path / "media-cache").rglob("*"):
            assert stat.S_IMODE(path.stat().st_mode) == (0o700 if path.is_dir() else 0o600)


def test_audio_validation_and_cache_containment(tmp_path: Path) -> None:
    settings = Settings(db_path=tmp_path / "twin.db")
    directory = tmp_path / "media-cache"
    directory.mkdir()
    outside = tmp_path / "private.wav"
    outside.write_bytes(b"private")
    (directory / ("a" * 64 + ".wav")).symlink_to(outside)
    (directory / "requests.json").write_bytes(b"private")
    (directory / ("d" * 64 + ".wav")).symlink_to(directory / "requests.json")
    mp3 = directory / ("e" * 64 + ".mp3")
    mp3.write_bytes(b"ID3-test-audio")
    with TestClient(create_app(settings, synthesizer_factory=SilentSynthesizer), base_url="http://localhost") as client:
        assert client.post("/api/media/audio", json=BODY).status_code == 403
        assert (
            client.post("/api/media/audio", json=BODY, headers={**HEADERS, "Host": "evil.invalid"}).status_code == 403
        )
        assert client.post("/api/media/audio", content=b"x" * (MAX_JSON_BYTES + 1), headers=HEADERS).status_code == 413
        assert client.post("/api/media/audio", json={**BODY, "answer": {}}, headers=HEADERS).status_code == 400
        audio = client.get("/api/media/audio/" + mp3.name)
        assert audio.status_code == 200 and audio.content == mp3.read_bytes()
        assert audio.headers["content-type"] == "audio/mpeg"
        assert audio.headers["cache-control"] == "private, no-store"
        for name in (
            "a" * 64 + ".wav",
            "d" * 64 + ".wav",
            "b" * 64 + ".mp3",
            "c" * 64 + ".json",
            "A" * 64 + ".wav",
            "private.wav",
            "..%2Fprivate.wav",
            "%2e%2e%2fprivate.wav",
            "requests%2Fsecret.json",
        ):
            response = client.get("/api/media/audio/" + name)
            assert response.status_code == 404
            assert b"private" not in response.content


@pytest.mark.parametrize(
    ("error", "status"),
    [(MediaUnavailable, 503), (MediaRejected, 502), (MediaTimeout, 504), (MediaInputTooLong, 413)],
)
def test_speech_errors_do_not_reflect_messages(tmp_path: Path, error: type[MediaError], status: int) -> None:
    def factory() -> SpeechSynthesizer:
        raise error("secret-token https://speech.invalid/private")

    with TestClient(
        create_app(Settings(db_path=tmp_path / "twin.db"), synthesizer_factory=factory), base_url="http://localhost"
    ) as client:
        assert client.post("/api/media/script", json=BODY, headers=HEADERS).status_code == 200
        assert client.get("/api/media/capabilities").json()["available"] is False
        response = client.post("/api/media/audio", json=BODY, headers=HEADERS)
        assert response.status_code == status
        assert "secret-token" not in response.text and "https://" not in response.text
        assert "语音" in response.json()["detail"] or "朗读" in response.json()["detail"]


def test_default_misconfiguration_only_affects_speech(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TWIN_MISSING_TTS_KEY", raising=False)
    settings = Settings(
        db_path=tmp_path / "twin.db",
        tts=TTSSettings(
            provider="cloudflare", base_url="https://speech.invalid/ai", api_key_env="TWIN_MISSING_TTS_KEY"
        ),
    )
    with TestClient(create_app(settings), base_url="http://localhost") as client:
        assert client.get("/").status_code == 200
        assert client.post("/api/media/script", json=BODY, headers=HEADERS).status_code == 200
        assert client.get("/api/media/capabilities").json()["available"] is False
        response = client.post("/api/media/audio", json=BODY, headers=HEADERS)
        assert response.status_code == 503
        assert "https://" not in response.text


def test_cli_speak_private_outputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("twin.config.make_synthesizer", lambda _: configured_silence())
    source = tmp_path / "reply.json"
    source.write_text(json.dumps(SOURCE), encoding="utf-8")
    out = tmp_path / "audio"
    out.mkdir(mode=0o755)
    (out / "requests").mkdir(mode=0o755)
    result = CliRunner().invoke(
        app,
        ["media", "speak", str(source), "--kind", "chat_reply", "--name", "合成人物", "--out", str(out)],
    )
    assert result.exit_code == 0, result.output
    manifests = list(out.glob("*.audio.json"))
    assert len(manifests) == 1
    manifest = json.loads(manifests[0].read_bytes())
    assert manifest["ai_generated"] is True and manifest["source_fingerprint"]
    assert list(out.glob("*.wav"))
    for path in [out, *out.rglob("*")]:
        assert stat.S_IMODE(path.stat().st_mode) == (0o700 if path.is_dir() else 0o600)


def test_cli_speak_unconfigured(tmp_path: Path) -> None:
    source = tmp_path / "reply.json"
    source.write_text(json.dumps(SOURCE), encoding="utf-8")
    out = tmp_path / "audio"
    result = CliRunner().invoke(app, ["media", "speak", str(source), "--kind", "chat_reply", "--out", str(out)])
    assert result.exit_code != 0
    assert "语音未配置" in result.output
    assert not out.exists()
