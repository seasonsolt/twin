"""Generic SSH video jobs, followed by local MP4 processing."""

from __future__ import annotations

import json
import re
import secrets
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .clip import ffmpeg_path, label_metadata
from .schema import MediaScript, VideoResult, VideoSegment
from .tts import MediaInputTooLong, MediaRejected, MediaTimeout, MediaUnavailable


class VideoSynthesizer(Protocol):
    @property
    def name(self) -> str: ...

    def synthesize(self, script: MediaScript, out_path: Path) -> VideoResult: ...


class Runner(Protocol):
    def __call__(
        self, command: list[str], *, input: str | None, timeout: float
    ) -> subprocess.CompletedProcess[str]: ...


def run(command: list[str], *, input: str | None, timeout: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, input=input, timeout=timeout, text=True, capture_output=True, check=True)


class _RemoteSegment(VideoSegment):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    seed: int = Field(strict=True)


class _Success(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    ok: Literal[True]
    output: str
    duration_s: float = Field(gt=0, allow_inf_nan=False)
    warnings: list[str]
    segments: list[_RemoteSegment]


class _Failure(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    ok: Literal[False]
    error: str = Field(min_length=1)


class RemoteVideo:
    name = "remote"

    def __init__(
        self,
        *,
        host: str | None = None,
        command: str,
        timeout_s: float = 3600,
        max_rounds: int = 4,
        max_cer: float = 0.05,
        pause_s: float = 0.25,
        runner: Runner = run,
    ) -> None:
        if (
            host and (re.fullmatch(r"[A-Za-z0-9._-]{1,64}", host) is None or host.startswith("-"))
        ) or not command.strip():
            raise MediaRejected("远端视频配置无效，请检查 [video]")
        self.host, self.command = host, command
        self.timeout_s, self.max_rounds, self.max_cer, self.pause_s = timeout_s, max_rounds, max_cer, pause_s
        self.runner = runner

    def _run(self, command: list[str], input: str | None = None) -> str:
        try:
            result = self.runner(command, input=input, timeout=self.timeout_s)
            if result.returncode:
                raise MediaUnavailable("视频生成失败，请检查远端服务和媒体配置")
            return result.stdout
        except subprocess.TimeoutExpired:
            raise MediaTimeout("视频生成超时，请稍后重试") from None
        except (OSError, subprocess.SubprocessError):
            raise MediaUnavailable("视频生成失败，请检查远端服务和媒体配置") from None

    def synthesize(self, script: MediaScript, out_path: Path) -> VideoResult:
        if script.abstain:
            raise MediaRejected("分身已弃权，不能生成讲述视频")
        texts = [s.text for s in script.segments if s.kind == "speech"]
        if sum(map(len, texts)) > 100_000:
            raise MediaInputTooLong("视频内容过长，请缩短回答")
        segments = [{"id": f"s{i:02d}", "text": text} for i, text in enumerate(texts, 1)]
        job_id = secrets.token_hex(16)
        request = {
            "job_id": job_id,
            "segments": segments,
            "max_rounds": self.max_rounds,
            "max_cer": self.max_cer,
            "pause_s": self.pause_s,
        }
        ffmpeg = ffmpeg_path()
        probe = shutil.which("ffprobe")
        if probe is None:
            raise MediaUnavailable("找不到 ffprobe，请安装 ffmpeg")
        command = (
            ["ssh", "-o", "BatchMode=yes", self.host, self.command] if self.host else ["bash", "-lc", self.command]
        )
        stdout = self._run(command, json.dumps(request, ensure_ascii=False))
        try:
            payload = json.loads(stdout.splitlines()[-1])
            if isinstance(payload, dict) and payload.get("ok") is False:
                _Failure.model_validate(payload)
                raise MediaRejected("远端视频服务拒绝了请求，请检查配置后重试")
            response = _Success.model_validate(payload)
            # Safe absolute paths only: scp must not interpret remote shell syntax or options.
            if re.fullmatch(r"/[A-Za-z0-9_./-]+\.mp4", response.output) is None:
                raise ValueError
            if [{"id": s.id, "text": s.text} for s in response.segments] != segments:
                raise ValueError
        except (IndexError, ValueError, ValidationError):
            raise MediaUnavailable("远端视频响应无效，请检查任务契约") from None
        out_path = Path(out_path)
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(dir=out_path.parent, prefix=".video-") as directory:
                work = Path(directory)
                raw, processed = work / "remote.mp4", work / "processed.mp4"
                if self.host:
                    self._run(["scp", "-o", "BatchMode=yes", f"{self.host}:{response.output}", str(raw)])
                else:
                    shutil.copy(response.output, raw)
                try:
                    info = json.loads(
                        self._run(
                            [
                                probe,
                                "-v",
                                "error",
                                "-select_streams",
                                "v:0",
                                "-show_entries",
                                "stream=width,height",
                                "-of",
                                "json",
                                str(raw),
                            ]
                        )
                    )
                    width, height = info["streams"][0]["width"], info["streams"][0]["height"]
                    if not all(isinstance(n, int) and 0 < n <= 16384 for n in (width, height)):
                        raise ValueError
                except (ValueError, KeyError, IndexError, TypeError):
                    raise MediaUnavailable("远端视频文件无效，请检查任务输出") from None
                self._run(
                    [
                        ffmpeg,
                        "-v",
                        "error",
                        "-y",
                        "-i",
                        str(raw),
                        "-vf",
                        "pad=ceil(iw/2)*2:ceil(ih/2)*2",
                        "-map",
                        "0:v:0",
                        "-map",
                        "0:a:0",
                        "-map_metadata",
                        "-1",
                        "-c:v",
                        "libx264",
                        "-pix_fmt",
                        "yuv420p",
                        "-crf",
                        "23",
                        "-preset",
                        "veryfast",
                        "-c:a",
                        "aac",
                        "-movflags",
                        "+faststart",
                        *label_metadata(script),
                        str(processed),
                    ]
                )
                processed.chmod(0o600)
                processed.replace(out_path)
        except OSError:
            raise MediaUnavailable("无法处理或保存视频，请检查媒体配置和输出目录") from None
        # Do not reflect free-form backend warnings (they may contain personal text or remote paths).
        warnings = [f"{s.id}: cer={s.cer:g}" for s in response.segments if s.cer > self.max_cer]
        if response.warnings:
            warnings.append("远端生成有提示，请检查回听结果")
        return VideoResult(
            output=out_path,
            duration_s=response.duration_s,
            segments=[VideoSegment.model_validate(s.model_dump(exclude={"seed"})) for s in response.segments],
            warnings=warnings,
        )
