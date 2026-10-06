"""Long-form media transcription, retaining timestamped segments across backends."""

from __future__ import annotations

import json
import math
import re
import subprocess
import tempfile
import wave
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel, Field, model_validator

from .asr import SpeechRecognizer
from .schema import TranscriptionRequest

if TYPE_CHECKING:
    from ..config import ASRSettings

Progress = Callable[[float, float], None]
VIDEO_EXTENSIONS = frozenset(["mp4", "mov", "m4v", "webm", "mkv", "avi", "3gp"])
AUDIO_EXTENSIONS = frozenset(["m4a", "mp3", "wav", "aac", "ogg", "opus", "flac", "caf", "amr"])
MEDIA_EXTENSIONS = VIDEO_EXTENSIONS | AUDIO_EXTENSIONS


class Segment(BaseModel):
    start: float = Field(ge=0, allow_inf_nan=False)
    end: float = Field(ge=0, allow_inf_nan=False)
    text: str

    @model_validator(mode="after")
    def ordered(self) -> Segment:
        if self.end < self.start:
            raise ValueError("无效时间段")
        return self


class Transcriber(Protocol):
    def transcribe(self, audio: Path, duration: float, progress: Progress) -> list[Segment]: ...


class CommandTranscriber:
    def __init__(self, command: str, language: str = "zh") -> None:
        self.command, self.language = command, language

    def transcribe(self, audio: Path, duration: float, progress: Progress) -> list[Segment]:
        progress(0, duration)
        try:
            result = subprocess.run(
                ["bash", "-lc", self.command],
                input=json.dumps({"audio": str(audio.resolve()), "language": self.language}),
                text=True,
                capture_output=True,
                check=True,
                timeout=1800 + duration,
            )
            payload = json.loads(result.stdout.strip().splitlines()[-1])
            if payload.get("ok") is not True or not isinstance(payload.get("segments"), list):
                raise ValueError()
            segments = [Segment.model_validate(s) for s in payload["segments"]]
        except (subprocess.SubprocessError, OSError, ValueError, TypeError, IndexError, AttributeError):
            raise RuntimeError("语音识别失败，请检查语音识别配置后重试") from None
        progress(duration, duration)
        return segments


def silence_chunks(audio: Path, duration: float) -> list[tuple[float, float]]:
    result = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostdin",
            "-i",
            str(audio),
            "-af",
            "silencedetect=noise=-35dB:d=0.3",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=1800 + duration,
    )
    silences = [float(t) for t in re.findall(r"silence_end: ([\d.]+)", result.stderr)]
    chunks: list[tuple[float, float]] = []
    start = 0.0
    while start < duration:
        limit = min(start + 25, duration)
        # Prefer the last pause in the window, but avoid many tiny chunks.
        end = max((t for t in silences if start + 5 <= t <= limit), default=limit) if limit < duration else limit
        chunks.append((start, end))
        start = end
    return chunks


class HTTPTranscriber:
    def __init__(self, recognizer: SpeechRecognizer, language: str = "zh") -> None:
        self.recognizer, self.language = recognizer, language

    def transcribe(self, audio: Path, duration: float, progress: Progress) -> list[Segment]:
        segments: list[Segment] = []
        progress(0, duration)
        with wave.open(str(audio), "rb") as source:
            rate = source.getframerate()
            audio_duration = min(duration, source.getnframes() / rate)
            for start, end in silence_chunks(audio, audio_duration):
                source.setpos(round(start * rate))
                frames = source.readframes(round(end * rate) - round(start * rate))
                with tempfile.TemporaryFile() as buffer:
                    with wave.open(buffer, "wb") as chunk:
                        chunk.setparams(source.getparams())
                        chunk.writeframes(frames)
                    buffer.seek(0)
                    result = self.recognizer.transcribe(
                        TranscriptionRequest(
                            audio=buffer.read(),
                            audio_format="wav",
                            language=self.language,
                        )
                    )
                if result.text.strip():
                    segments.append(Segment(start=start, end=end, text=result.text.strip()))
                progress(end, duration)
        return segments


def make_transcriber(settings: ASRSettings) -> Transcriber | None:
    from ..config import make_recognizer

    if settings.provider == "command":
        return (
            CommandTranscriber(settings.command, settings.language)
            if settings.command and settings.command.strip()
            else None
        )
    if not settings.base_url:
        return None
    return HTTPTranscriber(make_recognizer(settings), settings.language)


def extract_audio(original: Path) -> tuple[Path, float, str | None]:
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(original)],
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    )
    info = json.loads(probe.stdout)
    creation = info.get("format", {}).get("tags", {}).get("creation_time")
    if not creation:
        creation = next(
            (
                s.get("tags", {}).get("creation_time")
                for s in info.get("streams", [])
                if s.get("tags", {}).get("creation_time")
            ),
            None,
        )
    audio = original.with_name("audio.wav")
    # Create privately before ffmpeg opens it; no window with world-readable output.
    audio.touch(mode=0o600)
    audio.chmod(0o600)
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            "-y",
            "-i",
            str(original),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            str(audio),
        ],
        capture_output=True,
        check=True,
        timeout=6 * 3600,
    )
    with wave.open(str(audio), "rb") as wav:
        duration = wav.getnframes() / wav.getframerate()
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("音频为空")
    reported_duration = float(info.get("format", {}).get("duration", duration))
    if math.isfinite(reported_duration) and reported_duration > 0:
        duration = reported_duration
    return audio, duration, creation


def timestamp(seconds: float) -> str:
    seconds = int(seconds)
    hours, rest = divmod(seconds, 3600)
    minutes, seconds = divmod(rest, 60)
    return f"{hours}:{minutes:02}:{seconds:02}" if hours else f"{minutes:02}:{seconds:02}"


def transcript_text(filename: str, duration: float, creation: str | None, segments: list[Segment]) -> str:
    header = f"来源文件名：{filename}\n时长：{timestamp(duration)}"
    if creation:
        header += f"\n拍摄/录制时间：{creation}"
    header += "\n转写自音视频，未区分说话人"
    paragraphs: list[str] = []
    words, start = "", 0.0
    for segment in segments:
        text = " ".join(segment.text.split())
        while text:
            if not words:
                start = segment.start
            space = " " if words else ""
            available = 200 - len(words) - len(space)
            if available <= 0:
                paragraphs.append(f"[{timestamp(start)}] {words}")
                words = ""
                continue
            words += space + text[:available]
            text = text[available:]
            if len(words) == 200:
                paragraphs.append(f"[{timestamp(start)}] {words}")
                words = ""
    if words:
        paragraphs.append(f"[{timestamp(start)}] {words}")
    if not paragraphs:
        raise ValueError("没有识别到文字")
    return header + "\n\n" + "\n\n".join(paragraphs)
