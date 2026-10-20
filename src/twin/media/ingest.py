"""Long-form media transcription, retaining timestamped segments across backends."""

from __future__ import annotations

import json
import math
import re
import subprocess
import tempfile
import threading
import time
import uuid
import wave
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Protocol

from pydantic import BaseModel, Field, TypeAdapter, model_validator

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
    speaker: str = Field(default="S1", min_length=1, max_length=80)

    @model_validator(mode="after")
    def ordered(self) -> Segment:
        if self.end < self.start:
            raise ValueError("无效时间段")
        return self


Embedding = Annotated[list[Annotated[float, Field(allow_inf_nan=False)]], Field(min_length=1, max_length=1024)]


class Speaker(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    seconds: float = Field(ge=0, allow_inf_nan=False)
    similarity: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    # Unit voiceprint of the speaker (asr-funasr 1.3.0+), kept so a new reference voice is compared without
    # transcribing again.
    embedding: Embedding | None = None


_SIMILARITY: TypeAdapter[float | None] = TypeAdapter(Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)] | None)
_EMBEDDING: TypeAdapter[list[float]] = TypeAdapter(Embedding)


class Transcriber(Protocol):
    diarizes: bool

    def transcribe(self, audio: Path, duration: float, progress: Progress) -> list[Segment]: ...


PROGRESS_LINE = re.compile(r"@@twin-progress ([0-9.]+)\s*$")


class CommandTranscriber:
    diarizes = True

    def __init__(self, command: str, language: str = "zh") -> None:
        self.command, self.language = command, language
        self.diarize = False
        self.reference: Path | None = None
        # Optional extra voices compared in the same run (asr-funasr 1.2.1+); older commands ignore them, leaving
        # `similarities` empty.
        self.references: dict[str, Path] = {}
        self.speakers: list[Speaker] = []
        self.similarities: dict[str, dict[str, float | None]] = {}

    def transcribe(self, audio: Path, duration: float, progress: Progress) -> list[Segment]:
        progress(0, duration)
        request: dict[str, object] = {"audio": str(audio.resolve()), "language": self.language}
        if self.diarize:
            request["diarize"] = True
        if self.reference:
            request["reference"] = str(self.reference.resolve())
        if self.references:
            request["references"] = {name: str(path.resolve()) for name, path in self.references.items()}
        self.speakers, self.similarities = [], {}
        try:
            stdout = self._run(json.dumps(request), duration, progress)
            payload = json.loads(stdout.strip().splitlines()[-1])
            if payload.get("ok") is not True or not isinstance(payload.get("segments"), list):
                raise ValueError()
            segments = [Segment.model_validate(s) for s in payload["segments"]]
            self.speakers = [Speaker.model_validate(s) for s in payload.get("speakers", [])]
            if len({s.id for s in self.speakers}) != len(self.speakers):
                raise ValueError()
            if self.references:
                self.similarities = _similarities(payload.get("speakers", []), set(self.references))
        except (subprocess.SubprocessError, OSError, ValueError, TypeError, IndexError, AttributeError):
            raise RuntimeError("语音识别失败，请检查语音识别配置后重试") from None
        progress(duration, duration)
        return segments

    def embed(self, voice: Path) -> list[float] | None:
        """The voiceprint of a whole recording (asr-funasr 1.3.0+); None when the command cannot give one."""
        request = {"audio": str(voice.resolve()), "language": self.language, "embed": True}
        try:
            stdout = self._run(json.dumps(request), 60, lambda done, total: None)
            payload = json.loads(stdout.strip().splitlines()[-1])
            return _EMBEDDING.validate_python(payload["embedding"]) if payload.get("ok") is True else None
        except (subprocess.SubprocessError, OSError, ValueError, TypeError, IndexError, KeyError, AttributeError):
            return None

    def _run(self, request: str, duration: float, progress: Progress) -> str:
        """Run the command; `@@twin-progress <0..1>` lines on stderr become progress in this (the job's) thread."""
        process = subprocess.Popen(
            ["bash", "-lc", self.command],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        assert process.stdin and process.stdout and process.stderr
        output: list[str] = []
        latest = [0.0]

        def read_progress() -> None:
            assert process.stderr
            for line in process.stderr:
                match = PROGRESS_LINE.search(line)
                if match:
                    latest[0] = float(match.group(1))

        stdout = process.stdout
        readers = [
            threading.Thread(target=lambda: output.append(stdout.read()), daemon=True),
            threading.Thread(target=read_progress, daemon=True),
        ]
        for reader in readers:
            reader.start()
        try:
            process.stdin.write(request)
            process.stdin.close()
        except BrokenPipeError:
            pass
        deadline = time.monotonic() + 1800 + duration
        reported = 0.0
        while process.poll() is None:
            if time.monotonic() > deadline:
                process.kill()
                process.wait()
                raise subprocess.TimeoutExpired(self.command, 1800 + duration)
            if latest[0] > reported:
                reported = min(1.0, latest[0])
                progress(reported * duration, duration)
            time.sleep(0.5)
        for reader in readers:
            reader.join()
        if process.returncode:
            raise subprocess.CalledProcessError(process.returncode, self.command)
        return "".join(output)


def _similarities(rows: list[object], names: set[str]) -> dict[str, dict[str, float | None]]:
    """Speaker id → {voice name: similarity} for the requested voices; speakers without the field are left out."""
    result: dict[str, dict[str, float | None]] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(values := row.get("similarities"), dict):
            continue
        result[str(row["id"])] = {name: _SIMILARITY.validate_python(values[name]) for name in names if name in values}
    return result


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
    diarizes = False

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
    decode(original, audio)
    with wave.open(str(audio), "rb") as wav:
        duration = wav.getnframes() / wav.getframerate()
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("音频为空")
    reported_duration = float(info.get("format", {}).get("duration", duration))
    if math.isfinite(reported_duration) and reported_duration > 0:
        duration = reported_duration
    return audio, duration, creation


def decode(original: Path, audio: Path) -> None:
    """Write the original's sound as 16 kHz mono 16-bit wav, the form transcription and voice cuts read."""
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
            "-f",
            "wav",
            str(audio),
        ],
        capture_output=True,
        check=True,
        timeout=6 * 3600,
    )


_SOUND_LOCKS: dict[str, threading.RLock] = {}
_SOUND_LOCKS_GUARD = threading.Lock()


def sound_lock(folder: Path) -> threading.RLock:
    """One lock per source folder, held while its sound is read or its ``audio.wav`` removed: a slow decode of one
    recording holds up only that recording, and two requests never decode the same original at once."""
    with _SOUND_LOCKS_GUARD:
        return _SOUND_LOCKS.setdefault(str(folder), threading.RLock())


@contextmanager
def readable_wav(folder: Path) -> Iterator[Path]:
    """A source's sound as wav: ``audio.wav`` while its transcription is under way, else decoded again from the
    original into a temporary file that is deleted afterwards. The same original always decodes to the same
    samples, so nothing derived from it needs to be kept. Holds the folder's ``sound_lock`` throughout."""
    with sound_lock(folder):
        wav = folder / "audio.wav"
        if wav.is_file():
            yield wav
            return
        original = next(folder.glob("original.*"), None)
        if original is None:
            raise FileNotFoundError("原始文件已不在")
        temporary = folder / f".audio-{uuid.uuid4().hex}.wav"
        try:
            decode(original, temporary)
            yield temporary
        finally:
            temporary.unlink(missing_ok=True)


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
