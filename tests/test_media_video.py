"""Offline generic SSH jobs and permanently labelled video output."""

from __future__ import annotations

import json
import re
import shutil
import stat
import subprocess
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from pydantic import ValidationError
from typer.testing import CliRunner

from twin.cli import app as cli
from twin.config import Settings, VideoSettings, egress_of, make_video_synthesizer
from twin.egress import egress_status
from twin.media.adapters import presentable_from_payload
from twin.media.clip import _font_path
from twin.media.schema import EXPLICIT_LABEL, OPENING_NOTICE, MediaScript, Segment, VideoResult, VideoSegment
from twin.media.script import script_from_presentable
from twin.media.tts import MediaError, MediaRejected, MediaTimeout, MediaUnavailable
from twin.media.video import RemoteVideo, run
from twin.web.media import register

SECRET = "PRIVATE PERSONAL TEXT OR REMOTE PATH"
SOURCE = {
    "reply": "有依据的测试回答。",
    "citations": [],
    "confidence": 0.8,
    "abstain": False,
    "abstain_reason": "",
    "retrieved_ids": [],
}
BODY = {"kind": "chat_reply", "answer": SOURCE}


def script() -> MediaScript:
    return MediaScript(
        source_kind="chat_reply",
        source_fingerprint="test-source",
        persona_name="测试人",
        as_of=None,
        confidence=0.8,
        abstain=False,
        citations=[],
        segments=[
            Segment(index=0, kind="notice", text=OPENING_NOTICE),
            Segment(index=1, kind="speech", text="有依据的测试回答。"),
        ],
    )


class FakeRunner:
    def __init__(self, raw: Path | None = None, stdout: str | None = None, error: Exception | None = None) -> None:
        self.raw, self.stdout, self.error = raw, stdout, error
        self.calls: list[tuple[list[str], str | None, float]] = []
        self.request: dict[str, Any] = {}

    def __call__(self, command: list[str], *, input: str | None, timeout: float) -> subprocess.CompletedProcess[str]:
        self.calls.append((command, input, timeout))
        if self.error:
            raise self.error
        if command[0] == "ssh":
            assert input is not None
            self.request = json.loads(input)
            output = self.stdout
            if output is None:
                output = "ignored progress\n" + json.dumps(
                    {
                        "ok": True,
                        "output": "/jobs/result.mp4",
                        "duration_s": 1.0,
                        "warnings": [SECRET],
                        "segments": [
                            {**s, "heard": s["text"], "cer": 0.1 if i else 0.0, "seed": i}
                            for i, s in enumerate(self.request["segments"])
                        ],
                    }
                )
            return subprocess.CompletedProcess(command, 0, output, SECRET)
        if command[0] == "scp":
            assert self.raw is not None
            shutil.copyfile(self.raw, command[-1])
            return subprocess.CompletedProcess(command, 0, "", SECRET)
        return run(command, input=input, timeout=timeout)


@pytest.fixture
def dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("twin.media.video.ffmpeg_path", lambda: "ffmpeg")
    monkeypatch.setattr("twin.media.video._font_path", lambda _: Path("font.ttc"))
    monkeypatch.setattr("twin.media.video.ImageFont.truetype", lambda *_: None)
    monkeypatch.setattr("twin.media.video.shutil.which", lambda name: name)


@pytest.mark.parametrize(
    "stdout", ["", "progress only", "{}", '{"ok":true}', '{"ok":false}', '{"ok":true}\nnot json', "[]", "null"]
)
def test_bad_last_line_is_generic(dependencies: None, stdout: str, tmp_path: Path) -> None:
    runner = FakeRunner(stdout=stdout)
    with pytest.raises(MediaUnavailable, match="响应无效") as exc:
        RemoteVideo(host="test-alias", command="configured-command", runner=runner).synthesize(
            script(), tmp_path / "out.mp4"
        )
    assert SECRET not in str(exc.value)
    assert len(runner.calls) == 1


def test_failure_response_is_not_reflected(dependencies: None, tmp_path: Path) -> None:
    runner = FakeRunner(stdout=json.dumps({"ok": False, "error": SECRET}))
    with pytest.raises(MediaRejected) as exc:
        RemoteVideo(host="test-alias", command="configured-command", runner=runner).synthesize(
            script(), tmp_path / "out.mp4"
        )
    assert SECRET not in str(exc.value)


@pytest.mark.parametrize(
    "error",
    [
        subprocess.TimeoutExpired("ssh", 1, stderr=SECRET),
        subprocess.CalledProcessError(1, "ssh", stderr=SECRET),
        OSError(SECRET),
    ],
)
def test_transport_errors_are_generic(dependencies: None, error: Exception, tmp_path: Path) -> None:
    expected = MediaTimeout if isinstance(error, subprocess.TimeoutExpired) else MediaUnavailable
    with pytest.raises(expected) as exc:
        RemoteVideo(host="test-alias", command="configured-command", runner=FakeRunner(error=error)).synthesize(
            script(), tmp_path / "out.mp4"
        )
    assert SECRET not in str(exc.value)


def test_general_video_keeps_script_notices(dependencies: None, tmp_path: Path) -> None:
    general = script_from_presentable(presentable_from_payload("chat_reply", {**SOURCE, "mode": "general"}), "人")
    runner = FakeRunner(stdout="{}")
    with pytest.raises(MediaUnavailable, match="响应无效"):
        RemoteVideo(host="test-alias", command="configured-command", runner=runner).synthesize(
            general, tmp_path / "out.mp4"
        )
    assert [s["text"] for s in runner.request["segments"]] == [
        OPENING_NOTICE,
        "以下是通用知识，不代表本人观点。",
        SOURCE["reply"],
    ]


def test_abstention_never_calls_runner(tmp_path: Path) -> None:
    runner = FakeRunner()
    with pytest.raises(MediaRejected, match="弃权"):
        RemoteVideo(host="test-alias", command="configured-command", runner=runner).synthesize(
            script().model_copy(update={"abstain": True}), tmp_path / "out.mp4"
        )
    assert not runner.calls


@pytest.mark.parametrize(
    "updates",
    [
        {"host": "user@host"},
        {"host": "a/b"},
        {"host": "-option"},
        {"host": "x" * 65},
        {"host": ""},
        {"command": " "},
        {"timeout_s": 0},
        {"timeout_s": float("inf")},
        {"max_rounds": 0},
        {"max_rounds": 1.5},
        {"max_cer": -1},
        {"max_cer": float("nan")},
        {"pause_s": -1},
        {"pause_s": float("inf")},
    ],
)
def test_settings_validation(updates: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        VideoSettings.model_validate(
            {"provider": "remote", "host": "test-alias", "command": "configured-command", **updates}
        )


def test_settings_factory_and_egress() -> None:
    assert make_video_synthesizer(Settings()) is None
    with pytest.raises(ValidationError):
        VideoSettings(provider="remote")
    settings = Settings(video=VideoSettings(provider="remote", host="test-alias", command="configured-command"))
    assert isinstance(make_video_synthesizer(settings), RemoteVideo)
    info = egress_of(settings.video)
    assert info.kind == "video" and info.external and not info.declared and info.host == "test-alias"
    settings.video.egress = "local"
    assert not egress_of(settings.video).external and egress_of(settings.video).declared
    assert next(row for row in egress_status(settings) if row["kind"] == "video")["provider"] == "remote"
    assert not egress_of(VideoSettings()).external


@pytest.mark.parametrize("change", ["path", "order", "text", "missing", "nan", "seed"])
def test_success_validation(dependencies: None, change: str, tmp_path: Path) -> None:
    segments = [
        {"id": f"s{i:02d}", "text": text, "heard": text, "cer": 0.0, "seed": i}
        for i, text in enumerate([OPENING_NOTICE, script().segments[1].text], 1)
    ]
    payload: dict[str, Any] = {
        "ok": True,
        "output": "/jobs/result.mp4",
        "duration_s": 1.0,
        "warnings": [],
        "segments": segments,
    }
    if change == "path":
        payload["output"] = "/jobs/$(unsafe).mp4"
    elif change == "order":
        payload["segments"] = list(reversed(segments))
    elif change == "text":
        segments[1]["text"] = SECRET
    elif change == "missing":
        payload.pop("duration_s")
    elif change == "nan":
        segments[0]["cer"] = float("nan")
    else:
        segments[0].pop("seed")
    runner = FakeRunner(stdout=json.dumps(payload))
    with pytest.raises(MediaUnavailable):
        RemoteVideo(host="test-alias", command="configured-command", runner=runner).synthesize(
            script(), tmp_path / "out.mp4"
        )
    assert len(runner.calls) == 1


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="ffmpeg required")
def test_real_postprocess_badge_metadata_and_contract(tmp_path: Path) -> None:
    try:
        font = _font_path(None)
    except MediaError:
        pytest.skip("Chinese font required")
    raw = tmp_path / "raw.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=white:s=640x360:r=25",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=48000:cl=mono",
            "-t",
            "1",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            str(raw),
        ],
        check=True,
        capture_output=True,
    )
    runner = FakeRunner(raw=raw)
    out = tmp_path / "out.mp4"
    result = RemoteVideo(host="test-alias", command="configured-command", runner=runner, font_path=font).synthesize(
        script(), out
    )
    assert result.output == out and result.duration_s == 1
    assert result.warnings == ["s02: cer=0.1", "远端生成有提示，请检查回听结果"]
    assert re.fullmatch(r"[A-Za-z0-9_-]{1,64}", runner.request["job_id"])
    assert runner.request["segments"][0] == {"id": "s01", "text": OPENING_NOTICE}
    assert runner.request["max_rounds"] == 4 and runner.request["max_cer"] == 0.05 and runner.request["pause_s"] == 0.25
    assert runner.calls[0][0] == ["ssh", "-o", "BatchMode=yes", "test-alias", "configured-command"]
    assert runner.calls[1][0][:-1] == ["scp", "-o", "BatchMode=yes", "test-alias:/jobs/result.mp4"]
    assert all(timeout == 3600 for _, _, timeout in runner.calls)
    assert stat.S_IMODE(out.stat().st_mode) == 0o600
    assert not list(tmp_path.glob(".video-*"))
    info = json.loads(
        run(
            ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(out)], input=None, timeout=10
        ).stdout
    )
    assert info["format"]["tags"]["title"] == EXPLICIT_LABEL
    assert info["format"]["tags"]["comment"] == "AI-generated; twin; source test-source"
    assert {stream["codec_name"] for stream in info["streams"]} == {"h264", "aac"}
    assert info["streams"][0]["pix_fmt"] == "yuv420p"
    for at in (0, 0.8):
        pixels = subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-ss",
                str(at),
                "-i",
                str(out),
                "-frames:v",
                "1",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "rgb24",
                "-",
            ],
            check=True,
            capture_output=True,
        ).stdout
        image = Image.frombytes("RGB", (640, 360), pixels)
        assert max(image.getpixel((20, 335))) < 200  # permanent bottom-left badge, not white source
        assert min(image.getpixel((20, 20))) > 240


def test_web_job_flow_streaming_and_abstention(tmp_path: Path) -> None:
    class Synth:
        name = "fake"

        def synthesize(self, script: MediaScript, out_path: Path) -> VideoResult:
            assert not script.abstain
            out_path.write_bytes(b"fake labelled mp4")
            return VideoResult(output=out_path, duration_s=1.0, warnings=["s02: cer=0.1"])

    app = FastAPI()
    register(app, Settings(db_path=tmp_path / "twin.db"), video_factory=lambda: Synth())
    with TestClient(app) as client:
        assert client.get("/api/media/capabilities").json()["video"] == {"available": True}
        assert client.post("/api/media/video", json={**BODY, "answer": {**SOURCE, "abstain": True}}).status_code == 400
        response = client.post("/api/media/video", json=BODY)
        assert response.status_code == 200
        job_id = response.json()["job_id"]
        for _ in range(100):
            job = client.get(f"/api/media/video/jobs/{job_id}").json()
            if job["status"] in {"done", "failed"}:
                break
            time.sleep(0.01)
        assert job["status"] == "done", job
        result = job["result"]
        assert result["warnings"] == ["s02: cer=0.1"] and result["duration_s"] == 1
        response = client.get(f"/api/media/video/{result['file']}")
        assert response.content == b"fake labelled mp4"
        assert response.headers["content-type"] == "video/mp4"
        assert response.headers["x-ai-generated"] == "twin"
        assert response.headers["cache-control"] == "private, no-store"
        assert client.get("/api/media/video/invalid.mp4").status_code == 404
        assert client.get(f"/api/media/video/{'f' * 64}.mp4").status_code == 404
        assert client.get("/api/media/video/jobs/missing").status_code == 404
        link = tmp_path / "media-cache" / f"{'e' * 64}.mp4"
        link.symlink_to(tmp_path / "media-cache" / result["file"])
        assert client.get(f"/api/media/video/{link.name}").status_code == 404


def test_disabled_web_and_failed_jobs_are_generic(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    app = FastAPI()
    register(app, Settings(db_path=tmp_path / "twin.db"))
    with TestClient(app) as client:
        assert not client.get("/api/media/capabilities").json()["video"]["available"]
        assert client.post("/api/media/video", json=BODY).status_code == 503

    class BadSynth:
        name = "fake"

        def synthesize(self, script: MediaScript, out_path: Path) -> VideoResult:
            raise ValueError(SECRET)

    app = FastAPI()
    register(app, Settings(db_path=tmp_path / "twin.db"), video_factory=lambda: BadSynth())
    with TestClient(app) as client:
        job_id = client.post("/api/media/video", json=BODY).json()["job_id"]
        for _ in range(100):
            job = client.get(f"/api/media/video/jobs/{job_id}").json()
            if job["status"] == "failed":
                break
            time.sleep(0.01)
        assert job["status"] == "failed" and SECRET not in str(job)
        assert SECRET not in caplog.text


def test_failed_fetch_preserves_output_and_cleans_temp(dependencies: None, tmp_path: Path) -> None:
    class FailFetch(FakeRunner):
        def __call__(
            self, command: list[str], *, input: str | None, timeout: float
        ) -> subprocess.CompletedProcess[str]:
            if command[0] == "scp":
                Path(command[-1]).write_bytes(b"partial video")
                raise subprocess.TimeoutExpired("scp", timeout, stderr=SECRET)
            return super().__call__(command, input=input, timeout=timeout)

    out = tmp_path / "out.mp4"
    out.write_bytes(b"previous labelled output")
    runner = FailFetch()
    with pytest.raises(MediaTimeout):
        RemoteVideo(host="test-alias", command="configured-command", runner=runner).synthesize(script(), out)
    assert out.read_bytes() == b"previous labelled output"
    assert not list(tmp_path.glob(".video-*"))


def test_notice_is_first_even_when_missing_from_script(dependencies: None, tmp_path: Path) -> None:
    runner = FakeRunner(stdout="{}")
    with pytest.raises(MediaUnavailable):
        RemoteVideo(host="test-alias", command="configured-command", runner=runner).synthesize(
            script().model_copy(update={"segments": script().segments[1:]}), tmp_path / "out.mp4"
        )
    assert runner.request["segments"] == [
        {"id": "s01", "text": OPENING_NOTICE},
        {"id": "s02", "text": script().segments[1].text},
    ]


def test_cli_reports_only_ids_and_cer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class Synth:
        name = "fake"

        def synthesize(self, script: MediaScript, out_path: Path) -> VideoResult:
            return VideoResult(
                output=out_path,
                duration_s=2,
                warnings=["s02: cer=0.1"],
                segments=[VideoSegment(id="s02", text=SECRET, heard=SECRET, cer=0.1)],
            )

    monkeypatch.setattr("twin.config.make_video_synthesizer", lambda _: Synth())
    source = tmp_path / "reply.json"
    source.write_text(json.dumps(SOURCE))
    config = tmp_path / "twin.toml"
    config.write_text("")
    result = CliRunner().invoke(
        cli, ["--config", str(config), "media", "video", str(source), "--out", str(tmp_path / "out.mp4")]
    )
    assert result.exit_code == 0, result.output
    assert "2 秒" in result.output and "s02 cer=0.1" in result.output
    assert SECRET not in result.output and SOURCE["reply"] not in result.output
