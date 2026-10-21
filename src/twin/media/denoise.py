"""Denoised copies of library recordings, for listening only (asr-funasr 1.5.0+ on a GPU).

On real meetings people hear much more clearly once the noise is taken out, while recognition, diarization and
voiceprints do no better on the denoised audio, some worse (docs/ASR_EVAL.md, 录音降噪与去混响). So a transcribed
recording gains ``playback-denoised.flac`` beside ``playback.flac``: what people listen to plays the denoised one
unless they ask for the original (``listening``), and everything the library computes keeps reading
``playback.flac``. Recordings get theirs one at a time when the transcription service has nothing else to do, those
transcribed before it too; a failure is noted in ``denoised`` and tried again after ``RETRY``.
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess
import uuid
from pathlib import Path

from .ingest import CommandTranscriber, Progress
from .library import Library, Recording

DENOISED = "playback-denoised.flac"
RETRY = dt.timedelta(hours=6)


def listening(library: Library, recording_id: str, original: bool = False) -> Path:
    """The audio people hear of a recording: its denoised copy when it has one, unless ``original``."""
    folder = library.folder(recording_id)
    denoised = folder / DENOISED
    return denoised if not original and denoised.is_file() else folder / "playback.flac"


def denoised(library: Library, recording_id: str) -> bool:
    return (library.folder(recording_id) / DENOISED).is_file()


def waiting(library: Library) -> list[Recording]:
    """Transcribed recordings without a denoised copy whose last attempt, if any, failed more than ``RETRY`` ago,
    oldest first."""
    retry = (dt.datetime.now(dt.UTC) - RETRY).isoformat()
    with library.read() as db:
        recent = {row[0] for row in db.execute("SELECT recording_id FROM denoised WHERE created_at > ?", (retry,))}
    return [
        recording
        for recording in sorted(library.list(), key=lambda r: (r.created_at, r.id))
        if recording.status == "ready"
        and recording.id not in recent
        and (library.folder(recording.id) / "playback.flac").is_file()
        and not denoised(library, recording.id)
    ]


def _seconds(path: Path) -> float:
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    )
    return float(json.loads(probe.stdout)["format"]["duration"])


def _note(library: Library, recording_id: str, error: str) -> None:
    with library.transaction() as db:
        db.execute(
            "INSERT INTO denoised (recording_id, error, created_at) VALUES (?, ?, ?) ON CONFLICT (recording_id) "
            "DO UPDATE SET error = excluded.error, created_at = excluded.created_at",
            (recording_id, error, dt.datetime.now(dt.UTC).isoformat()),
        )


def run(library: Library, recording_id: str, transcriber: CommandTranscriber, progress: Progress) -> bool:
    """Denoise one recording's playback copy; False when there is nothing to do. The copy is kept only when it is
    as long as the original; ``RuntimeError`` (noted, so the queue moves on) when it cannot be made."""
    recording = library.get(recording_id)
    folder = library.folder(recording_id)
    playback, target = folder / "playback.flac", folder / DENOISED
    if recording is None or recording.status != "ready" or not playback.is_file() or target.is_file():
        return False
    temporary = folder / f".{uuid.uuid4().hex}.denoised.tmp.flac"
    try:
        expected = _seconds(playback)
        transcriber.denoise(playback, temporary, expected, progress)
        if abs(_seconds(temporary) - expected) > 1:
            raise RuntimeError("降噪后的试听文件时长不符")
        temporary.chmod(0o600)
        temporary.replace(target)
    except (RuntimeError, subprocess.SubprocessError, OSError, ValueError, KeyError) as exc:
        _note(library, recording_id, str(exc) or type(exc).__name__)
        raise RuntimeError(str(exc) or "降噪失败") from None
    finally:
        temporary.unlink(missing_ok=True)
    _note(library, recording_id, "")
    return True
