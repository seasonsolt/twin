"""Offline MP4 drawing, encoding and HTTP/CLI integration."""

from __future__ import annotations

import hashlib
import json
import shutil
import stat
import subprocess
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageColor
from typer.testing import CliRunner

from twin.cli import app
from twin.config import MediaSettings, Settings
from twin.media import clip
from twin.media.adapters import presentable_from_payload
from twin.media.schema import (
    AVATAR_PRESETS,
    EXPLICIT_LABEL,
    OPENING_NOTICE,
    AvatarSpec,
    LipSyncTrack,
    MediaScript,
    SpeechRequest,
    SpeechResult,
)
from twin.media.script import script_from_presentable
from twin.media.tts import MediaError, MediaInputTooLong, SilentSynthesizer
from twin.web import create_app
from twin.web.app import MAX_JSON_BYTES

SOURCE: dict[str, Any] = {
    "reply": "你好。",
    "citations": [],
    "confidence": 0.8,
    "abstain": False,
    "abstain_reason": "",
    "retrieved_ids": [],
}
BODY = {"kind": "chat_reply", "answer": SOURCE, "persona_name": "合成人物"}


def script() -> MediaScript:
    return script_from_presentable(presentable_from_payload("chat_reply", SOURCE), "合成人物")


@pytest.fixture
def font() -> Path:
    try:
        return clip._font_path(None)
    except MediaError:
        pytest.skip("Chinese font not installed")


def test_frames_are_deterministic_and_every_card_keeps_the_badge(font: Path) -> None:
    avatar = AVATAR_PRESETS["default"]
    hashes = []
    for level in range(4):
        first = clip._draw_frame(avatar, "你好。", level, font, (1280, 720))
        second = clip._draw_frame(avatar, "你好。", level, font, (1280, 720))
        assert first.tobytes() == second.tobytes()
        hashes.append(hashlib.sha256(first.tobytes()).hexdigest())
    assert len(set(hashes)) == 4
    assert clip._draw_frame(avatar, "另一句。", 0, font, (1280, 720)).tobytes() != first.tobytes()
    background = ImageColor.getrgb(avatar.palette["background"])
    for text, card in [
        (OPENING_NOTICE, False),
        (OPENING_NOTICE, True),
        ("你好。", False),
        (f"回答依据\n{EXPLICIT_LABEL}", True),
    ]:
        image = clip._draw_frame(avatar, text, 0, font, (1280, 720), card=card)
        region = image.crop((25, 25, 500, 65))
        assert any(pixel != background for pixel in region.get_flattened_data())
        assert any(pixel == (255, 255, 255) for pixel in region.get_flattened_data())
    abstention = clip._draw_frame(avatar, "资料不足。", 0, font, (1280, 720), show_avatar=False)
    assert abstention.getpixel((200, 400)) == background


def test_wrap_measures_cjk_characters(font: Path) -> None:
    face = clip.ImageFont.truetype(str(font), 30)
    assert clip._wrap("一二三四\n五六", face, face.getlength("一二")) == ["一二", "三四", "五六"]


def test_missing_ffmpeg_is_chinese_and_does_not_synthesize(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(clip.shutil, "which", lambda _: None)
    with pytest.raises(MediaError, match=r"找不到 ffmpeg.*install"):
        clip.render_clip(script(), SilentSynthesizer(), AVATAR_PRESETS["default"], tmp_path / "clip.mp4")
    assert not (tmp_path / "media-cache").exists()


def test_missing_font_is_chinese(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(clip.shutil, "which", lambda _: "/fake/ffmpeg")
    monkeypatch.setattr(clip, "FONT_PATHS", ())
    with pytest.raises(MediaError, match=r"找不到中文字体.*\[media\] font_path"):
        clip.render_clip(script(), SilentSynthesizer(), AVATAR_PRESETS["default"], tmp_path / "clip.mp4")
    with pytest.raises(MediaError, match="font_path"):
        clip._font_path(tmp_path / "absent.ttf")


def test_invalid_font_and_excessive_text_fail_before_synthesis(
    font: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(clip.shutil, "which", lambda _: "/fake/ffmpeg")
    invalid = tmp_path / "invalid.ttf"
    invalid.write_bytes(b"not a font")
    with pytest.raises(MediaError, match="无法读取中文字体"):
        clip.render_clip(
            script(), SilentSynthesizer(), AVATAR_PRESETS["default"], tmp_path / "clip.mp4", font_path=invalid
        )
    overlong = script().model_copy(
        update={"segments": [script().segments[1].model_copy(update={"text": "字" * 100_001})]}
    )
    with pytest.raises(MediaInputTooLong, match="过长"):
        clip.render_clip(
            overlong, SilentSynthesizer(), AVATAR_PRESETS["default"], tmp_path / "clip.mp4", font_path=font
        )


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
@pytest.mark.parametrize("opening", ["notice", "missing", "other_notice"])
def test_real_ffmpeg_clip(
    font: Path,
    tmp_path: Path,
    record_property: Any,
    monkeypatch: pytest.MonkeyPatch,
    opening: str,
) -> None:
    out = tmp_path / "clip.mp4"
    source = script()
    if opening == "missing":
        source = source.model_copy(update={"segments": source.segments[1:]})
    elif opening == "other_notice":
        source = source.model_copy(
            update={"segments": [source.segments[0].model_copy(update={"text": "其他提示。"}), *source.segments[1:]]}
        )
    draw = clip._draw_frame
    frames: list[tuple[str, bool]] = []

    def capture(*args: Any, **kwargs: Any) -> Image.Image:
        frames.append((args[1], kwargs["card"]))
        return draw(*args, **kwargs)

    monkeypatch.setattr(clip, "_draw_frame", capture)
    result = clip.render_clip(source, SilentSynthesizer(), AVATAR_PRESETS["default"], out, font_path=font)
    assert frames[0] == (OPENING_NOTICE, opening != "notice")
    assert frames[-1] == (f"回答依据\n{EXPLICIT_LABEL}", True)
    if opening == "notice":
        assert (OPENING_NOTICE, True) not in frames
    else:
        assert (source.segments[0].text, False) in frames
    assert result == out and out.stat().st_size > 0
    assert stat.S_IMODE(out.stat().st_mode) == 0o600
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(out)],
        check=True,
        capture_output=True,
    )
    info = json.loads(probe.stdout)
    assert {stream["codec_name"] for stream in info["streams"]} == {"h264", "aac"}
    assert info["streams"][0]["pix_fmt"] == "yuv420p"
    expected = clip.ENDING_SECONDS + sum(len(segment.text) * 0.08 for segment in source.segments)
    if opening != "notice":
        expected += clip.OPENING_SECONDS
    duration = float(info["format"]["duration"])
    assert duration == pytest.approx(expected, abs=0.1)
    assert info["format"]["tags"]["comment"] == f"AI-generated; twin; source {source.source_fingerprint}"
    assert info["format"]["tags"]["title"] == EXPLICIT_LABEL
    record_property("clip_duration_s", duration)
    record_property("clip_size_bytes", out.stat().st_size)
    print(f"sample clip: {duration:.3f}s, {out.stat().st_size} bytes")
    assert not list(tmp_path.glob(".clip-*"))


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
@pytest.mark.parametrize("has_lipsync", [False, True])
def test_unknown_duration_and_lipsync(
    font: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    has_lipsync: bool,
) -> None:
    class UnknownDuration(SilentSynthesizer):
        def synthesize(self, request: SpeechRequest) -> SpeechResult:
            return super().synthesize(request).model_copy(update={"duration_s": None})

    render_audio = clip.render_audio

    def with_track(*args: Any, **kwargs: Any) -> Any:
        rendered = render_audio(*args, **kwargs)
        track = LipSyncTrack(fps=25, levels=[0, 1, 2, 3] * 50, source="pattern") if has_lipsync else None
        return rendered.model_copy(
            update={
                "segments": [
                    segment.model_copy(
                        update={"parts": [part.model_copy(update={"lipsync": track}) for part in segment.parts]}
                    )
                    for segment in rendered.segments
                ]
            }
        )

    monkeypatch.setattr(clip, "render_audio", with_track)
    draw = clip._draw_frame
    levels = []

    def capture(*args: Any, **kwargs: Any) -> Image.Image:
        levels.append(args[2])
        return draw(*args, **kwargs)

    monkeypatch.setattr(clip, "_draw_frame", capture)
    clip.render_clip(
        script(), UnknownDuration(), AVATAR_PRESETS["ink"], tmp_path / "small.mp4", font_path=font, size=(640, 360)
    )
    assert levels and set(levels) == ({0, 1, 2, 3} if has_lipsync else {0})
    assert levels[0] == levels[-1] == 0


def test_ffmpeg_failure_does_not_echo_stderr(font: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args: Any, **kwargs: Any) -> None:
        raise subprocess.CalledProcessError(1, "ffmpeg", stderr=b"PRIVATE PATH OR TEXT")

    monkeypatch.setattr(clip.shutil, "which", lambda _: "/fake/ffmpeg")
    monkeypatch.setattr(clip.subprocess, "run", fail)
    out = tmp_path / "clip.mp4"
    out.write_bytes(b"previous output")
    with pytest.raises(MediaError, match="视频合成失败") as error:
        clip.render_clip(script(), SilentSynthesizer(), AVATAR_PRESETS["default"], out, font_path=font)
    assert "PRIVATE" not in str(error.value)
    assert error.value.__suppress_context__
    assert out.read_bytes() == b"previous output"
    assert not list(tmp_path.glob(".clip-*"))


def fake_clip(source: MediaScript, synth: Any, avatar: AvatarSpec, out: Path, **kwargs: Any) -> Path:
    assert source.source_fingerprint == script().source_fingerprint
    assert avatar == AVATAR_PRESETS["ink"]
    assert kwargs["font_path"] == "/configured/font.ttc"
    out.write_bytes(b"fake mp4")
    return out


def test_web_clip_and_security(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("twin.web.media.render_clip", fake_clip)
    settings = Settings(db_path=tmp_path / "twin.db", media=MediaSettings(font_path="/configured/font.ttc"))
    settings.avatar.preset = "ink"
    with TestClient(create_app(settings), base_url="http://localhost") as client:
        assert client.post("/api/media/clip", json=BODY).status_code == 403
        assert (
            client.post("/api/media/clip", content=b"x" * (MAX_JSON_BYTES + 1), headers={"X-Twin": "1"}).status_code
            == 413
        )
        assert client.post("/api/media/clip", json={**BODY, "answer": {}}, headers={"X-Twin": "1"}).status_code == 400
        response = client.post("/api/media/clip", json=BODY, headers={"X-Twin": "1"})
        assert response.status_code == 200 and response.content == b"fake mp4"
        assert response.headers["content-type"] == "video/mp4"
        assert response.headers["x-ai-generated"] == "twin"
        assert response.headers["content-disposition"] == 'attachment; filename="twin-media.mp4"'
        assert response.headers["cache-control"] == "no-store"
    assert not list(tmp_path.glob("*.mp4"))


def test_web_failure_cleans_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args: Any, **kwargs: Any) -> None:
        raise MediaError("private backend response")

    monkeypatch.setattr("twin.web.media.render_clip", fail)
    with TestClient(create_app(Settings(db_path=tmp_path / "twin.db")), base_url="http://localhost") as client:
        response = client.post("/api/media/clip", json=BODY, headers={"X-Twin": "1"})
        assert response.status_code == 503
        assert "private" not in response.text
    assert not list(tmp_path.glob("*.mp4"))


def test_cli_writes_clip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(clip, "render_clip", fake_clip)
    source = tmp_path / "reply.json"
    source.write_text(json.dumps(SOURCE), encoding="utf-8")
    config = tmp_path / "twin.toml"
    config.write_text('[avatar]\npreset = "ink"\n[media]\nfont_path = "/configured/font.ttc"\n', encoding="utf-8")
    out = tmp_path / "clip.mp4"
    result = CliRunner().invoke(
        app, ["--config", str(config), "media", "clip", str(source), "--name", "合成人物", "--out", str(out)]
    )
    assert result.exit_code == 0, result.output
    assert out.read_bytes() == b"fake mp4"
    assert SOURCE["reply"] not in result.output


def test_cli_invalid_input_does_not_print_personal_text(tmp_path: Path) -> None:
    source = tmp_path / "reply.json"
    source.write_text(json.dumps({**SOURCE, "confidence": "PRIVATE TEXT"}), encoding="utf-8")
    config = tmp_path / "config.toml"
    config.write_text("", encoding="utf-8")
    result = CliRunner().invoke(
        app, ["--config", str(config), "media", "clip", str(source), "--out", str(tmp_path / "clip.mp4")]
    )
    assert result.exit_code == 1
    assert "无法读取回答" in result.output
    assert "PRIVATE TEXT" not in result.output
