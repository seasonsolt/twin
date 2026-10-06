"""Append-only avatar contracts, offline rendering and HTTP."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from typer.testing import CliRunner

from twin.cli import CONFIG_TEMPLATE, app
from twin.config import AvatarSettings, Settings
from twin.identity import Identity
from twin.media.render import render_audio
from twin.media.schema import (
    AVATAR_PRESETS,
    AudioManifest,
    AudioPart,
    AvatarSpec,
    LipSyncTrack,
    MediaScript,
    Segment,
    SpeechRequest,
    SpeechResult,
    WordTiming,
)
from twin.media.tts import SilentSynthesizer
from twin.web import create_app


@pytest.fixture(autouse=True)
def own_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    for name in ("TWIN_CONFIG", "DTWIN_CONFIG", "OPENAI_BASE_URL", "ANTHROPIC_BASE_URL"):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize(
    "values",
    [
        {"fps": 0},
        {"fps": -1},
        {"fps": 1.5},
        {"levels": [-1]},
        {"levels": [4]},
        {"levels": [1.5]},
        {"levels": [True]},
        {"source": "vendor"},
        {"extra": 1},
    ],
)
def test_track_ranges(values: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        LipSyncTrack.model_validate({"source": "pattern", **values})


def test_track_length_cap_frozen_and_roundtrip() -> None:
    track = LipSyncTrack(fps=2, levels=[0, 1, 2, 3] * 300, source="pattern")
    assert LipSyncTrack.model_validate_json(track.model_dump_json()) == track
    assert LipSyncTrack(source="energy").fps == 25
    with pytest.raises(ValidationError):
        LipSyncTrack(fps=2, levels=[0] * 1201, source="energy")
    with pytest.raises(ValidationError):
        track.fps = 3


def test_avatar_presets_fields() -> None:
    assert set(AVATAR_PRESETS) == {"default", "ink", "dawn"}
    assert set(AvatarSpec.model_fields) == {
        "schema_version",
        "avatar_id",
        "palette",
        "mouth_states",
        "stylized",
    }
    for name, preset in AVATAR_PRESETS.items():
        assert preset.avatar_id == name
        assert preset.stylized is True and preset.mouth_states == 4
        assert AvatarSpec.model_validate_json(preset.model_dump_json()) == preset
        with pytest.raises(ValidationError):
            preset.avatar_id = "changed"
        for extra in ("url", "path", "image"):
            with pytest.raises(ValidationError):
                AvatarSpec.model_validate({**preset.model_dump(), extra: "input"})
        for fields in (
            {"stylized": False},
            {"mouth_states": 5},
            {"palette": {"skin": "#ffffff"}},
            {"palette": {**preset.palette, "skin": "url(example)"}},
        ):
            with pytest.raises(ValidationError):
                AvatarSpec.model_validate({**preset.model_dump(), **fields})


def test_old_part_manifest_and_identity_load() -> None:
    part = AudioPart.model_validate_json('{"text":"合成","file_name":"old.wav"}')
    assert part.lipsync is None and part.model_dump(mode="json")["lipsync"] is None
    manifest = AudioManifest.model_validate_json(
        json.dumps(
            {
                "source_fingerprint": "invented",
                "created_at": "2026-01-01T00:00:00Z",
                "segments": [{"parts": [{"text": "合成", "file_name": "old.wav"}]}],
            }
        )
    )
    assert manifest.segments[0].parts[0].lipsync is None
    identity = Identity.model_validate_json('{"name":"合成人物","aliases":[]}')
    assert identity.avatar is None
    assert Identity(name="合成人物", aliases=[], avatar="ink").avatar == "ink"


@pytest.mark.parametrize(
    "preset", ["unknown", "/photo.png", "https://example.invalid/face", "data:image/png;base64,abc"]
)
def test_config_rejects_nonpreset(preset: str) -> None:
    with pytest.raises(ValidationError) as error:
        AvatarSettings(preset=preset)
    message = str(error.value)
    assert all(name in message for name in AVATAR_PRESETS)
    assert "形象仅支持预置" in message
    assert Settings().avatar.preset == "default"


class TimedSynthesizer(SilentSynthesizer):
    def synthesize(self, request: SpeechRequest) -> SpeechResult:
        result = super().synthesize(request)
        return result.model_copy(update={"timings": [WordTiming(text="合成", start_s=0, end_s=result.duration_s or 1)]})


@pytest.mark.parametrize("timed", [False, True])
def test_render_attaches_tracks_to_every_part_and_cache(tmp_path: Path, timed: bool) -> None:
    synth = TimedSynthesizer(max_chars=8) if timed else SilentSynthesizer(max_chars=8)
    script = MediaScript(
        source_kind="chat_reply",
        source_fingerprint="invented",
        persona_name="合成人物",
        as_of=None,
        confidence=0.8,
        abstain=False,
        segments=[
            Segment(index=0, kind="notice", text="合成提示。"),
            Segment(index=1, kind="speech", text="先验证生成内容。再继续推进。"),
        ],
        citations=[],
    )
    output = render_audio(script, synth, tmp_path / "cache")
    parts = [part for segment in output.segments for part in segment.parts]
    assert len(parts) > 2
    for part in parts:
        assert part.lipsync is not None
        assert part.lipsync.source == ("timings" if timed else "energy")
        assert any(part.lipsync.levels) is timed
    manifest = AudioManifest.model_validate_json((tmp_path / "cache" / output.manifest_file).read_bytes())
    assert manifest.segments == output.segments
    assert render_audio(script, synth, tmp_path / "cache").segments == output.segments


def test_http_avatar_audio_and_identity(tmp_path: Path) -> None:
    settings = Settings(db_path=tmp_path / "twin.db", avatar=AvatarSettings(preset="dawn"))
    body = {
        "kind": "chat_reply",
        "answer": {
            "reply": "先验证。",
            "citations": [],
            "confidence": 0.8,
            "abstain": False,
            "abstain_reason": "",
            "retrieved_ids": [],
        },
    }
    with TestClient(create_app(settings, synthesizer_factory=SilentSynthesizer), base_url="http://localhost") as client:
        capabilities = client.get("/api/media/capabilities").json()
        assert capabilities["available"] is False
        assert capabilities["avatar"] == AVATAR_PRESETS["dawn"].model_dump(mode="json")
        assert client.get("/api/identity").json()["avatar"] == "dawn"
        response = client.post("/api/media/audio", json=body, headers={"X-Twin": "1"})
        assert response.status_code == 200
        result = response.json()
        assert result["segments"]
        for segment in result["segments"]:
            assert segment["lipsync"]["source"] == "energy"
            assert set(segment["lipsync"]["levels"]) == {0}


def test_avatar_remains_available_when_speech_fails(tmp_path: Path) -> None:
    def factory() -> SilentSynthesizer:
        raise ValueError("invalid offline config")

    with TestClient(
        create_app(Settings(db_path=tmp_path / "twin.db"), synthesizer_factory=factory), base_url="http://localhost"
    ) as client:
        result = client.get("/api/media/capabilities").json()
        assert result["available"] is False
        assert result["avatar"] == AVATAR_PRESETS["default"].model_dump(mode="json")


def test_identity_show_and_init_template(tmp_path: Path) -> None:
    config = tmp_path / "twin.toml"
    config.write_text(f'db_path = "{tmp_path / "twin.db"}"\n[avatar]\npreset = "ink"\n', encoding="utf-8")
    result = CliRunner().invoke(app, ["--config", str(config), "identity", "show"])
    assert result.exit_code == 0, result.output
    assert "形象：ink（风格化插画，不使用照片）" in result.output
    example = (Path(__file__).resolve().parents[1] / "twin.toml.example").read_text(encoding="utf-8")
    for template in (CONFIG_TEMPLATE, example):
        assert (
            "# [avatar] # 2D 预置形象；或用 vrm_path 指定 3D 模型。\n"
            '# preset = "default" # 可选 default、ink、dawn。' in template
        )
