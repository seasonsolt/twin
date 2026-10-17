"""An account's recording library: each meeting is transcribed once, with every speaker's voiceprint, so twins of
several people can later be built from the same recordings.

``data/library/<owner_key>/`` holds ``library.db`` (the recordings and their status, which survives restarts),
``uploads/`` (chunked uploads still arriving) and ``recordings/<id>/``. A recording folder only ever gains files:
``transcript-<transcript_id>.json`` and ``playback.flac`` are written once under a temporary name and never changed,
so backups hard-link them. The upload itself is deleted once both are verified; only its file name, size and sha256
are kept.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import threading
import uuid
import wave
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from ..util import prepare_private_file, private_directory
from .ingest import VIDEO_EXTENSIONS, CommandTranscriber, Progress, Segment, Speaker, extract_audio

RecordingStatus = Literal["queued", "transcribing", "ready", "failed"]
# Recordings that still take a transcription turn; they count against ``LibrarySettings.max_pending``.
PENDING: tuple[RecordingStatus, ...] = ("queued", "transcribing")
# Generous per-recording timeout for re-encoding the playback copy.
ENCODE_TIMEOUT = 6 * 3600

_SCHEMA = """
CREATE TABLE IF NOT EXISTS recordings (
    id TEXT PRIMARY KEY,
    sha256 TEXT NOT NULL UNIQUE,
    filename TEXT NOT NULL,
    size INTEGER NOT NULL,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    error TEXT NOT NULL DEFAULT '',
    duration_s REAL,
    creation_time TEXT,
    transcribed_s REAL NOT NULL DEFAULT 0,
    transcript_id TEXT,
    speakers INTEGER NOT NULL DEFAULT 0,
    segments INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 0
);
-- The people of this account's meetings; a person may exist before (or without) a twin.
CREATE TABLE IF NOT EXISTS people (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    persona_id TEXT,
    created_at TEXT NOT NULL,
    -- Made automatically from a voice that matched nobody, and not named by the owner yet.
    auto INTEGER NOT NULL DEFAULT 0
);
-- Voice samples a person was recognised by: the centroid of a speaker the owner confirmed and chose as a sample.
CREATE TABLE IF NOT EXISTS voiceprints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id TEXT NOT NULL REFERENCES people(id) ON DELETE CASCADE,
    recording_id TEXT NOT NULL,
    transcript_id TEXT NOT NULL,
    speaker_id TEXT NOT NULL,
    embedding TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
-- The owner's decisions about speakers; matching never writes here.
CREATE TABLE IF NOT EXISTS attributions (
    recording_id TEXT NOT NULL,
    transcript_id TEXT NOT NULL,
    speaker_id TEXT NOT NULL,
    decision TEXT NOT NULL DEFAULT 'none',
    person_id TEXT,
    rejected TEXT NOT NULL DEFAULT '[]',
    updated_at TEXT NOT NULL,
    -- Taken by voice alone (``Team.classify``), not by the owner.
    auto INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (recording_id, transcript_id, speaker_id)
);
-- A twin may answer only while done == wanted: every change that affects its recordings raises wanted in the same
-- transaction, and done follows once a complete build of exactly that state has succeeded.
CREATE TABLE IF NOT EXISTS personas_sync (
    persona_id TEXT PRIMARY KEY,
    person_id TEXT NOT NULL,
    wanted INTEGER NOT NULL DEFAULT 1,
    done INTEGER NOT NULL DEFAULT 0
);
"""


class Recording(BaseModel):
    id: str
    sha256: str
    filename: str
    size: int
    kind: Literal["audio", "video"]
    status: RecordingStatus
    error: str = ""
    duration_s: float | None = None
    creation_time: str | None = None
    transcribed_s: float = 0
    transcript_id: str | None = None
    speakers: int = 0
    segments: int = 0
    created_at: str
    updated_at: str
    # Raised whenever the transcript or any decision about its speakers changes; a stale page is refused.
    revision: int = 0


class Transcript(BaseModel):
    """One transcription of a recording. Segment indices are stable for this ``id``: later stages refer to a
    sentence as (transcript id, segment index), and a new transcription gets a new id instead of renumbering."""

    id: str
    recording_id: str
    created_at: str
    duration_s: float = Field(ge=0)
    segments: list[Segment]
    speakers: list[Speaker]


class TranscriptionError(Exception):
    """A recording could not be transcribed; the message is shown to the owner as is."""


def owner_key(email: str | None) -> str:
    """The library folder of an account. Without login every visitor is the same local owner; e-mail addresses
    stay out of paths."""
    if email is None:
        return "local"
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()[:24]


def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat()


_SPEAKERS: dict[str, tuple[Speaker, ...]] = {}
_SPEAKERS_LOCK = threading.Lock()


class Library:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.db_path = root / "library.db"
        self.recordings = root / "recordings"
        # Status changes come from request threads and the transcription job; SQLite serializes writes, this keeps
        # read-modify-write sequences (add, retry, delete) whole.
        self.lock = threading.RLock()
        private_directory(root)
        root.chmod(0o700)
        prepare_private_file(self.db_path)
        with self._db() as db:
            db.execute("PRAGMA journal_mode=WAL")
            # Columns added since a table was first made.
            for table, column in (("recordings", "revision"), ("people", "auto"), ("attributions", "auto")):
                columns = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
                if columns and column not in columns:
                    db.execute(f"ALTER TABLE {table} ADD COLUMN {column} INTEGER NOT NULL DEFAULT 0")
            db.executescript(_SCHEMA)

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        with closing(sqlite3.connect(self.db_path, timeout=30)) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            with db:
                yield db

    def read(self) -> contextlib.AbstractContextManager[sqlite3.Connection]:
        """A connection for reading (writes made through it still commit as one)."""
        return self._db()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """One write transaction (``BEGIN IMMEDIATE``): a decision and the twins it reopens commit together."""
        with closing(sqlite3.connect(self.db_path, timeout=30, isolation_level=None)) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
            except BaseException:
                db.execute("ROLLBACK")
                raise
            db.execute("COMMIT")

    def folder(self, recording_id: str) -> Path:
        return self.recordings / recording_id

    def get(self, recording_id: str) -> Recording | None:
        with self._db() as db:
            row = db.execute("SELECT * FROM recordings WHERE id = ?", (recording_id,)).fetchone()
        return Recording.model_validate(dict(row)) if row else None

    def list(self) -> list[Recording]:
        with self._db() as db:
            rows = db.execute("SELECT * FROM recordings ORDER BY created_at DESC, id").fetchall()
        return [Recording.model_validate(dict(row)) for row in rows]

    def pending(self) -> int:
        with self._db() as db:
            return int(
                db.execute(
                    f"SELECT COUNT(*) FROM recordings WHERE status IN ({','.join('?' * len(PENDING))})", PENDING
                ).fetchone()[0]
            )

    def next_queued(self) -> Recording | None:
        with self._db() as db:
            row = db.execute(
                "SELECT * FROM recordings WHERE status = 'queued' ORDER BY created_at, id LIMIT 1"
            ).fetchone()
        return Recording.model_validate(dict(row)) if row else None

    def update(self, recording_id: str, **fields: object) -> None:
        if not fields:
            return
        names = ", ".join(f"{name} = ?" for name in fields)
        with self._db() as db:
            db.execute(
                f"UPDATE recordings SET {names}, updated_at = ? WHERE id = ?",
                (*fields.values(), _now(), recording_id),
            )

    def add(self, upload: Path, filename: str) -> tuple[Recording, bool]:
        """File a finished upload as a queued recording; the same content uploaded again (under any name) is the
        existing recording, and the upload is dropped. Returns the recording and whether it is new."""
        with upload.open("rb") as file:
            sha = hashlib.file_digest(file, "sha256").hexdigest()
        with self.lock:
            with self._db() as db:
                row = db.execute("SELECT * FROM recordings WHERE sha256 = ?", (sha,)).fetchone()
            if row:
                upload.unlink(missing_ok=True)
                return Recording.model_validate(dict(row)), False
            extension = Path(filename).suffix.lower().lstrip(".")
            recording_id = "rec_" + sha[:20]
            folder = self.folder(recording_id)
            private_directory(folder)
            folder.chmod(0o700)
            original = folder / f"original.{extension}"
            size = upload.stat().st_size
            upload.replace(original)
            original.chmod(0o600)
            now = _now()
            recording = Recording(
                id=recording_id,
                sha256=sha,
                filename=filename,
                size=size,
                kind="video" if extension in VIDEO_EXTENSIONS else "audio",
                status="queued",
                created_at=now,
                updated_at=now,
            )
            data = recording.model_dump()
            with self._db() as db:
                db.execute(
                    f"INSERT INTO recordings ({', '.join(data)}) VALUES ({', '.join('?' * len(data))})",
                    tuple(data.values()),
                )
            return recording, True

    def resume(self) -> int:
        """After a restart: transcriptions that were cut off start again. Returns how many are waiting."""
        with self.lock:
            with self._db() as db:
                db.execute(
                    "UPDATE recordings SET status = 'queued', transcribed_s = 0, updated_at = ? "
                    "WHERE status = 'transcribing'",
                    (_now(),),
                )
            return self.pending()

    def retry(self, recording_id: str) -> Recording | None:
        """Queue a failed recording again; None when it is not failed or its upload is gone."""
        with self.lock:
            recording = self.get(recording_id)
            if recording is None or recording.status != "failed" or not self._original(recording_id):
                return None
            self.update(recording_id, status="queued", error="", transcribed_s=0)
            return self.get(recording_id)

    def delete(self, recording_id: str) -> bool:
        """Remove a recording that is not being transcribed, with the decisions and voice samples taken from it;
        the twins it fed are closed until they are rebuilt without it. False when it is transcribing right now."""
        with self.lock:
            recording = self.get(recording_id)
            if recording is None:
                return True
            if recording.status == "transcribing":
                return False
            with self.transaction() as db:
                db.execute(
                    "UPDATE personas_sync SET wanted = wanted + 1 WHERE person_id IN "
                    "(SELECT person_id FROM attributions WHERE recording_id = ? AND decision = 'confirmed')",
                    (recording_id,),
                )
                db.execute("DELETE FROM attributions WHERE recording_id = ?", (recording_id,))
                db.execute("DELETE FROM voiceprints WHERE recording_id = ?", (recording_id,))
                db.execute("DELETE FROM recordings WHERE id = ?", (recording_id,))
            shutil.rmtree(self.folder(recording_id), ignore_errors=True)
            return True

    def transcript(self, recording: Recording) -> Transcript | None:
        if not recording.transcript_id:
            return None
        path = self.folder(recording.id) / f"transcript-{recording.transcript_id}.json"
        return Transcript.model_validate_json(path.read_text()) if path.is_file() else None

    def speakers(self, recording: Recording) -> tuple[Speaker, ...] | None:
        """The speakers of the recording's transcript (durations and voiceprints), without its segments. A
        published transcript never changes, so each is read once per process: lists over years of meetings do not
        re-read every transcript."""
        if not recording.transcript_id:
            return None
        key = str(self.folder(recording.id) / f"transcript-{recording.transcript_id}.json")
        with _SPEAKERS_LOCK:
            found = _SPEAKERS.get(key)
        if found is None:
            transcript = self.transcript(recording)
            if transcript is None:
                return None
            found = tuple(transcript.speakers)
            with _SPEAKERS_LOCK:
                _SPEAKERS[key] = found
        return found

    def _original(self, recording_id: str) -> Path | None:
        return next(self.folder(recording_id).glob("original.*"), None)

    def transcribe(self, recording_id: str, transcriber: CommandTranscriber, progress: Progress) -> Recording:
        """Transcribe a queued recording with every speaker's voiceprint, keep a FLAC playback copy, then delete
        the upload. On failure the upload stays, the recording is marked failed and ``TranscriptionError`` says
        why."""
        with self.lock:
            recording = self.get(recording_id)
            if recording is None or recording.status != "queued":
                raise TranscriptionError("这段录音已删除或不在排队中")
            self.update(recording_id, status="transcribing", error="", transcribed_s=0)
        folder = self.folder(recording_id)
        audio = folder / "audio.wav"
        try:
            original = self._original(recording_id)
            if original is None:
                raise TranscriptionError("原始文件已不在，请重新上传")
            try:
                audio, duration, creation = extract_audio(original)
            except (subprocess.SubprocessError, OSError, ValueError, wave.Error) as exc:
                raise TranscriptionError("无法读取音频，请确认文件完整且是常见音视频格式") from exc
            self.update(recording_id, duration_s=duration, creation_time=creation)
            transcriber.diarize, transcriber.reference, transcriber.references = True, None, {}
            try:
                segments = transcriber.transcribe(audio, duration, progress)
            except RuntimeError as exc:
                raise TranscriptionError("语音识别失败，请检查转写服务后重试") from exc
            speakers = transcriber.speakers
            if speakers and any(s.embedding is None for s in speakers):
                raise TranscriptionError("转写服务没有返回声纹，需要 asr-funasr 1.3.0 或更新")
            transcript = Transcript(
                id=uuid.uuid4().hex[:12],
                recording_id=recording_id,
                created_at=_now(),
                duration_s=duration,
                segments=segments,
                speakers=speakers,
            )
            self._write_transcript(folder, transcript)
            self._encode_playback(audio, folder / "playback.flac")
            original.unlink()
            audio.unlink(missing_ok=True)
            self.update(
                recording_id,
                status="ready",
                transcript_id=transcript.id,
                transcribed_s=duration,
                speakers=len(speakers),
                segments=len(segments),
            )
        except BaseException as exc:
            audio.unlink(missing_ok=True)
            message = str(exc) if isinstance(exc, TranscriptionError) else "转写失败，请稍后重试"
            self.update(recording_id, status="failed", error=message, transcribed_s=0)
            if isinstance(exc, TranscriptionError):
                raise
            raise TranscriptionError(message) from exc
        result = self.get(recording_id)
        assert result is not None
        return result

    @staticmethod
    def _write_transcript(folder: Path, transcript: Transcript) -> None:
        path = folder / f"transcript-{transcript.id}.json"
        temporary = folder / f".{path.name}.tmp"
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(transcript.model_dump(mode="json"), stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        if Transcript.model_validate_json(temporary.read_text()) != transcript:
            temporary.unlink()
            raise TranscriptionError("转写结果写入校验失败，请重试")
        temporary.replace(path)

    @staticmethod
    def _encode_playback(audio: Path, target: Path) -> None:
        """Lossless FLAC of the 16 kHz mono transcription audio: what later listening and voice samples use."""
        temporary = target.with_name(f".{target.name}.tmp")
        temporary.touch(mode=0o600)
        temporary.chmod(0o600)
        try:
            subprocess.run(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-nostdin",
                    "-y",
                    "-i",
                    str(audio),
                    "-c:a",
                    "flac",
                    "-f",
                    "flac",
                    str(temporary),
                ],
                capture_output=True,
                check=True,
                timeout=ENCODE_TIMEOUT,
            )
            with wave.open(str(audio), "rb") as wav:
                expected = wav.getnframes() / wav.getframerate()
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(temporary)],
                capture_output=True,
                text=True,
                check=True,
                timeout=120,
            )
            actual = float(json.loads(probe.stdout)["format"]["duration"])
        except (subprocess.SubprocessError, OSError, ValueError, KeyError, wave.Error) as exc:
            temporary.unlink(missing_ok=True)
            raise TranscriptionError("试听文件生成失败，请检查 ffmpeg 后重试") from exc
        if abs(actual - expected) > 1:
            temporary.unlink(missing_ok=True)
            raise TranscriptionError("试听文件时长校验失败，请重试")
        temporary.replace(target)
