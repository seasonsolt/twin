"""The team's recording library: each meeting is transcribed once, with every speaker's voiceprint, so twins of
several people can later be built from the same recordings. The meetings are the team's, whoever uploaded them;
each recording remembers its uploader (``uploader``, an ``owner_key``), and ``web.library`` decides who may see or
change what.

``data/library/team/`` holds ``library.db`` (the recordings and their status, which survives restarts),
``members/<owner_key>/`` (each member's chunked uploads still arriving, and their own voice, ``media.voice``) and
``recordings/<id>/``. Libraries of one account each, as earlier versions kept them, are merged into it once
(``media.merge``). A recording folder only ever gains files:
``transcript-<transcript_id>.json``, ``playback.flac``, its denoised copy for listening ``playback-denoised.flac``
(``media.denoise``) and, once someone in it is identified, the model's proofreading
``clean-<transcript_id>.json``, and the names the meeting calls its speakers by, ``names-<transcript_id>.json``, are
written once under a temporary name and never changed, so backups hard-link them.
The upload itself is deleted once the transcript and playback copy are verified; only its file name, size and
sha256 are kept.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import json
import logging
import os
import shutil
import sqlite3
import subprocess
import threading
import uuid
from collections.abc import Collection, Iterator, Sequence
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from ..util import prepare_private_file, private_directory
from .collector import ATTRIBUTION_VERSION, CLEANUP_VERSION, CollectorVersion, recollect_scope
from .cues import Cue, Named, said
from .ingest import (
    VIDEO_EXTENSIONS,
    CommandTranscriber,
    Interrupted,
    Progress,
    Segment,
    Speaker,
    extract_flac,
    stopped,
)

logger = logging.getLogger(__name__)

RecordingStatus = Literal["queued", "transcribing", "ready", "failed"]
# Recordings that still take a transcription turn; they count against ``LibrarySettings.max_pending``.
PENDING: tuple[RecordingStatus, ...] = ("queued", "transcribing")

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
    revision INTEGER NOT NULL DEFAULT 0,
    -- The transcript the model was asked to proofread (once per transcript, whatever came of it).
    proofread TEXT,
    -- The transcript the model was asked to name the speakers of (once per transcript, whatever came of it).
    named TEXT,
    -- Who uploaded it (``owner_key`` of their account); NULL when nobody knows, which leaves it to administrators.
    uploader TEXT,
    -- The transcription service that made the current transcript (``collector.asr_version``); NULL when unknown.
    asr TEXT,
    -- When the owner asked for it to be transcribed again by the current service (``media.recollect``).
    recollect TEXT,
    -- The transcript before the last transcription again, which it can go back to (``recollect.rollback``).
    previous TEXT
);
-- The people of this account's meetings; a person may exist before (or without) a twin.
CREATE TABLE IF NOT EXISTS people (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    persona_id TEXT,
    created_at TEXT NOT NULL,
    -- Made automatically from a voice that matched nobody, and not named by the owner yet.
    auto INTEGER NOT NULL DEFAULT 0,
    -- 'male', 'female', or '' when the owner has not said.
    gender TEXT NOT NULL DEFAULT '',
    -- The account (``owner_key``) of the person themselves, once they said a voice of theirs is them.
    account TEXT
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
    created_at TEXT NOT NULL,
    -- How the sample was taken: "speaker" (the owner settled one speaker), "voice" (a voice heard across recordings,
    -- settled at once), "new" (a new unnamed person), "moved" (to a newer transcript); NULL before this was recorded.
    source TEXT,
    -- How many speakers it gave someone by voice alone that the owner then gave otherwise (``Team.decide``).
    corrected INTEGER NOT NULL DEFAULT 0
);
-- Decisions about speakers: the owner's, and those taken by voice alone (``auto``).
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
    -- The person it was given to said "不是我"; it waits for whoever decides about the recording.
    disputed INTEGER NOT NULL DEFAULT 0,
    -- The rules that made an automatic decision (``collector``); NULL for the owner's, and for automatic ones made
    -- before versions were recorded.
    version TEXT,
    -- How sure voice alone was of an automatic decision (``team.tier``; "new" for a new unnamed person), the best
    -- score and its lead over the runner-up, and the voice sample (``voiceprints.id``) that matched best.
    tier TEXT,
    score REAL,
    lead REAL,
    sample INTEGER,
    -- An automatic decision taken back because its sample no longer stands (``Team._withdraw``): whom it was given
    -- to, offered to the owner to confirm while the speaker is undecided.
    suggest TEXT,
    PRIMARY KEY (recording_id, transcript_id, speaker_id)
);
-- Two people who may be one, for an administrator to merge or keep apart (``media.merge``).
CREATE TABLE IF NOT EXISTS similar_people (
    person_id TEXT NOT NULL REFERENCES people(id) ON DELETE CASCADE,
    other_id TEXT NOT NULL REFERENCES people(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    PRIMARY KEY (person_id, other_id)
);
-- The libraries of one account each, as earlier versions kept them, already merged into this one (``media.merge``).
CREATE TABLE IF NOT EXISTS merged_libraries (
    key TEXT PRIMARY KEY,
    merged_at TEXT NOT NULL
);
-- A twin may answer only while done == wanted: every change that affects its recordings raises wanted in the same
-- transaction, and done follows once a complete build of exactly that state has succeeded.
CREATE TABLE IF NOT EXISTS personas_sync (
    persona_id TEXT PRIMARY KEY,
    person_id TEXT NOT NULL,
    wanted INTEGER NOT NULL DEFAULT 1,
    done INTEGER NOT NULL DEFAULT 0,
    -- The wanted version found to only add recordings to the last build: the twin answers from ``done`` meanwhile.
    answerable INTEGER
);
-- The last attempt at a recording's denoised copy for listening (``media.denoise``): ``error`` is '' once made.
CREATE TABLE IF NOT EXISTS denoised (
    recording_id TEXT PRIMARY KEY,
    error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
-- A confirmed speaker heard again piece by piece (``media.review``): the voiceprint of each stretch of their speech,
-- computed once per transcript. ``error`` is set, with no units, when the transcription service could not do it.
CREATE TABLE IF NOT EXISTS reviewed (
    recording_id TEXT NOT NULL,
    transcript_id TEXT NOT NULL,
    speaker_id TEXT NOT NULL,
    error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    PRIMARY KEY (recording_id, transcript_id, speaker_id)
);
CREATE TABLE IF NOT EXISTS review_units (
    recording_id TEXT NOT NULL,
    transcript_id TEXT NOT NULL,
    speaker_id TEXT NOT NULL,
    unit INTEGER NOT NULL,
    -- The transcript segments it joins, as a JSON list of indices, and their (start, end) times.
    segments TEXT NOT NULL,
    parts TEXT NOT NULL,
    -- float32 voiceprint; NULL when too short to compute.
    embedding BLOB,
    PRIMARY KEY (recording_id, transcript_id, speaker_id, unit)
);
-- The owner's decisions about single segments of a confirmed speaker (``media.review``): not ``from_person`` after
-- all ('exclude'), someone else's ('move', to ``to_person``), or theirs indeed ('keep'). They hold while the
-- segment's speaker is still confirmed as ``from_person``. ``auto``: left out by the review itself, since the stretch
-- sounds like someone else or nobody known (``Reviews.settle``); the owner's own decision replaces it.
CREATE TABLE IF NOT EXISTS segment_fixes (
    recording_id TEXT NOT NULL,
    transcript_id TEXT NOT NULL,
    segment INTEGER NOT NULL,
    from_person TEXT NOT NULL,
    action TEXT NOT NULL,
    to_person TEXT,
    updated_at TEXT NOT NULL,
    auto INTEGER NOT NULL DEFAULT 0,
    -- The review rules that made an automatic decision (``collector.CLEANUP_VERSION``), as in ``attributions``.
    version TEXT,
    PRIMARY KEY (recording_id, transcript_id, segment)
);
-- Each time a recording was transcribed again (``media.recollect``): what was carried over to the new transcript,
-- and what could not be, as a JSON ``recollect.Report``.
CREATE TABLE IF NOT EXISTS recollections (
    recording_id TEXT NOT NULL,
    old_transcript TEXT NOT NULL,
    new_transcript TEXT NOT NULL,
    at TEXT NOT NULL,
    report TEXT NOT NULL,
    rolled_back INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (recording_id, new_transcript)
);
-- What the library last heard from the collector, e.g. ``asr``: the service the latest transcription came from.
CREATE TABLE IF NOT EXISTS collector (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
-- Model tokens the library spent (proofreading, and builds of its twins), for the batch quota.
CREATE TABLE IF NOT EXISTS spending (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    kind TEXT NOT NULL,
    tokens INTEGER NOT NULL
);
"""


class Recording(BaseModel):
    id: str
    sha256: str
    filename: str
    size: int
    # ``transcript``: a meeting transcript brought in as text (``Library.add_transcript``): no sound, no voiceprints.
    kind: Literal["audio", "video", "transcript"]
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
    # The transcript the model was asked to proofread, if any.
    proofread: str | None = None
    # The transcript the model was asked to name the speakers of, if any.
    named: str | None = None
    # Who uploaded it (``owner_key``), if known.
    uploader: str | None = None
    # The transcription service that made the current transcript, if known (``collector``).
    asr: str | None = None
    # When the owner asked for it to be transcribed again, and the transcript before the last time it was.
    recollect: str | None = None
    previous: str | None = None


class Transcript(BaseModel):
    """One transcription of a recording. Segment indices are stable for this ``id``: later stages refer to a
    sentence as (transcript id, segment index), and a new transcription gets a new id instead of renumbering."""

    id: str
    recording_id: str
    created_at: str
    duration_s: float = Field(ge=0)
    segments: list[Segment]
    speakers: list[Speaker]
    # The transcription service that made it (``collector.asr_version``); None when it did not say.
    asr: str | None = None
    # Whether the segments carry the times they were said at. False for a transcript brought in as text whose export
    # gave none: every segment then sits at 0 and the speakers' seconds are estimated from their words.
    timed: bool = True


class Cleaned(BaseModel):
    """The model's proofreading of one transcript: the same segments, only their words corrected."""

    transcript_id: str
    created_at: str
    changed: int = 0
    failed_batches: int = 0
    segments: list[Segment]


def matches(transcript: Transcript, segments: list[Segment]) -> bool:
    """Whether proofread ``segments`` are the transcript's segments one for one: same number, and each with the
    same times and speaker. Only then may their words stand in for the transcript's."""
    return len(segments) == len(transcript.segments) and all(
        (a.start, a.end, a.speaker) == (b.start, b.end, b.speaker)
        for a, b in zip(segments, transcript.segments, strict=True)
    )


class TranscriptionError(Exception):
    """A recording could not be transcribed; the message is shown to the owner as is."""


class TranscriptionInterrupted(TranscriptionError):
    """Transcription was cut off by the service stopping: the recording is queued again, not failed."""


def _interrupted(exc: BaseException | None) -> bool:
    """Whether a stop signal ended a command somewhere behind the error."""
    while exc is not None:
        if isinstance(exc, Interrupted) or (isinstance(exc, subprocess.CalledProcessError) and stopped(exc.returncode)):
            return True
        exc = exc.__cause__ or exc.__context__
    return False


# The folder of the team's library under ``data/library``.
TEAM = "team"

# How much a person says in a second, to size the speakers of a transcript that is not timed (``add_transcript``).
CHARS_PER_SECOND = 4.0


def owner_key(email: str | None) -> str:
    """The library folder of an account. Without login every visitor is the same local owner; e-mail addresses
    stay out of paths."""
    if email is None:
        return "local"
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()[:24]


def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat()


_SPEAKERS: dict[str, tuple[Speaker, ...]] = {}
_NAMES: dict[str, dict[str, Cue]] = {}
_SPEAKERS_LOCK = threading.Lock()


def _file_once(path: Path, content: BaseModel, unverified: str) -> bool:
    """Write ``content`` to ``path`` unless a file is there: under a temporary name, verified, then linked into place,
    so an existing file (which backups may hard-link) is never rewritten. False when one was there already."""
    if path.exists():
        return False
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(content.model_dump(mode="json"), stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        if type(content).model_validate_json(temporary.read_text()) != content:
            raise ValueError(unverified)
        try:
            os.link(temporary, path)
        except FileExistsError:
            return False
        return True
    finally:
        temporary.unlink(missing_ok=True)


def _segments_of(turns: Sequence[tuple[str, str, float | None]], timed: bool) -> list[Segment]:
    """The turns of a transcript as segments: each lasts until the next begins when the export timed them (from the
    first turn, the last for as long as it takes to say), else all of them sit at 0."""
    if not timed:
        return [Segment(start=0.0, end=0.0, text=text, speaker=speaker) for speaker, text, _ in turns]
    first = min(clock for _, _, clock in turns if clock is not None)
    starts = [max(0.0, (clock or 0.0) - first) for _, _, clock in turns]
    segments = []
    for i, (speaker, text, _) in enumerate(turns):
        end = starts[i + 1] if i + 1 < len(turns) else starts[i] + len(text) / CHARS_PER_SECOND
        segments.append(Segment(start=starts[i], end=max(end, starts[i]), text=text, speaker=speaker))
    return segments


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
            for table, column, kind in (
                ("recordings", "revision", "INTEGER NOT NULL DEFAULT 0"),
                ("people", "auto", "INTEGER NOT NULL DEFAULT 0"),
                ("attributions", "auto", "INTEGER NOT NULL DEFAULT 0"),
                ("people", "gender", "TEXT NOT NULL DEFAULT ''"),
                ("recordings", "proofread", "TEXT"),
                ("recordings", "uploader", "TEXT"),
                ("people", "account", "TEXT"),
                ("attributions", "disputed", "INTEGER NOT NULL DEFAULT 0"),
                ("recordings", "named", "TEXT"),
                ("segment_fixes", "auto", "INTEGER NOT NULL DEFAULT 0"),
                ("recordings", "asr", "TEXT"),
                ("attributions", "version", "TEXT"),
                ("segment_fixes", "version", "TEXT"),
                ("recordings", "recollect", "TEXT"),
                ("recordings", "previous", "TEXT"),
                ("attributions", "tier", "TEXT"),
                ("attributions", "score", "REAL"),
                ("attributions", "lead", "REAL"),
                ("attributions", "sample", "INTEGER"),
                ("attributions", "suggest", "TEXT"),
                ("voiceprints", "source", "TEXT"),
                ("voiceprints", "corrected", "INTEGER NOT NULL DEFAULT 0"),
                ("personas_sync", "answerable", "INTEGER"),
            ):
                columns = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
                if columns and column not in columns:
                    db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")
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

    def pending(self, uploader: str | None = None) -> int:
        """Recordings still waiting for transcription; ``uploader``: only theirs."""
        mine = " AND uploader = ?" if uploader is not None else ""
        with self._db() as db:
            return int(
                db.execute(
                    f"SELECT COUNT(*) FROM recordings WHERE status IN ({','.join('?' * len(PENDING))}){mine}",
                    (*PENDING, *([uploader] if uploader is not None else [])),
                ).fetchone()[0]
            )

    def next_queued(self, skip: Collection[str] = ()) -> Recording | None:
        """The longest-waiting queued recording; ``skip``: recordings whose transcription is already starting."""
        with self._db() as db:
            row = db.execute(
                f"SELECT * FROM recordings WHERE status = 'queued' AND id NOT IN ({','.join('?' * len(skip))}) "
                "ORDER BY created_at, id LIMIT 1",
                tuple(skip),
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

    def add(
        self, upload: Path, filename: str, uploader: str | None = None, sha: str | None = None
    ) -> tuple[Recording, bool]:
        """File a finished upload as a queued recording; the same content uploaded again (under any name, by
        anyone) is the existing recording, and the upload is dropped. ``sha`` is the upload's SHA-256 when the
        caller already has it. Returns the recording and whether it is new."""
        if sha is None:
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
                uploader=uploader,
            )
            data = recording.model_dump()
            with self._db() as db:
                db.execute(
                    f"INSERT INTO recordings ({', '.join(data)}) VALUES ({', '.join('?' * len(data))})",
                    tuple(data.values()),
                )
            return recording, True

    def add_transcript(
        self,
        filename: str,
        turns: Sequence[tuple[str, str, float | None]],
        *,
        sha: str,
        size: int,
        uploader: str | None = None,
        date: str | None = None,
    ) -> tuple[Recording, bool]:
        """File a meeting transcript brought in as text, ``(speaker, words, seconds in or None)`` for each turn, as a
        recording that is ready at once: it has no sound to transcribe or play and no voiceprints, so its speakers
        are told apart by their names, and nothing is proofread or asked of the model. The same file brought in
        again (by anyone, under any name) is the recording there already. ``date``: the day of the meeting, as
        ``YYYY-MM-DD``. Returns the recording and whether it is new."""
        with self.lock:
            with self._db() as db:
                row = db.execute("SELECT * FROM recordings WHERE sha256 = ?", (sha,)).fetchone()
            if row:
                return Recording.model_validate(dict(row)), False
            recording_id = "rec_" + sha[:20]
            timed = bool(turns) and all(clock is not None for _, _, clock in turns)
            segments = _segments_of(turns, timed)
            seconds: dict[str, float] = {}
            for segment in segments:
                length = segment.end - segment.start if timed else len(segment.text) / CHARS_PER_SECOND
                seconds[segment.speaker] = seconds.get(segment.speaker, 0.0) + length
            duration = segments[-1].end if timed and segments else 0.0
            folder = self.folder(recording_id)
            private_directory(folder)
            folder.chmod(0o700)
            now = _now()
            transcript = Transcript(
                id=uuid.uuid4().hex[:12],
                recording_id=recording_id,
                created_at=now,
                duration_s=duration,
                segments=segments,
                speakers=[Speaker(id=name, seconds=round(total, 1)) for name, total in seconds.items()],
                timed=timed,
            )
            self.write_transcript(folder, transcript)
            recording = Recording(
                id=recording_id,
                sha256=sha,
                filename=filename,
                size=size,
                kind="transcript",
                status="ready",
                duration_s=duration if timed else None,
                creation_time=date,
                transcribed_s=duration,
                transcript_id=transcript.id,
                speakers=len(transcript.speakers),
                segments=len(segments),
                created_at=now,
                updated_at=now,
                # Words are the transcript's own: nothing is proofread, and the speakers are named by it.
                proofread=transcript.id,
                named=transcript.id,
                uploader=uploader,
            )
            data = recording.model_dump()
            with self._db() as db:
                db.execute(
                    f"INSERT INTO recordings ({', '.join(data)}) VALUES ({', '.join('?' * len(data))})",
                    tuple(data.values()),
                )
            return recording, True

    def resume(self) -> int:
        """After a restart: transcriptions that were cut off start again, and an upload left behind by a stop
        right after its recording was published is deleted. Returns how many are waiting."""
        with self.lock:
            with self._db() as db:
                db.execute(
                    "UPDATE recordings SET status = 'queued', transcribed_s = 0, updated_at = ? "
                    "WHERE status = 'transcribing'",
                    (_now(),),
                )
                ready = [row[0] for row in db.execute("SELECT id FROM recordings WHERE status = 'ready'")]
            for recording_id in ready:
                if (original := self.original(recording_id)) is not None:
                    original.unlink(missing_ok=True)
            return self.pending()

    def retry(self, recording_id: str) -> Recording | None:
        """Queue a failed recording again; None when it is not failed or its upload is gone."""
        with self.lock:
            recording = self.get(recording_id)
            if recording is None or recording.status != "failed" or not self.original(recording_id):
                return None
            self.update(recording_id, status="queued", error="", transcribed_s=0)
            return self.get(recording_id)

    def expire_failed(self, days: int) -> int:
        """Delete the original of every recording that has been failed for ``days`` days (0: never), which a retry
        would need; the recording stays, saying why it cannot be retried, and each deletion is logged. Only an
        administrator's ``[library] failed_keep_days`` turns this on. Returns how many originals went."""
        if days <= 0:
            return 0
        cutoff = (dt.datetime.now(dt.UTC) - dt.timedelta(days=days)).isoformat()
        removed = 0
        with self.lock:
            for recording in self.list():
                if recording.status != "failed" or recording.updated_at >= cutoff:
                    continue
                original = self.original(recording.id)
                if original is None:
                    continue
                logger.warning(
                    "deleting the original of %s (%s, %d bytes), failed since %s: %s",
                    recording.id,
                    recording.filename,
                    recording.size,
                    recording.updated_at,
                    recording.error,
                )
                original.unlink(missing_ok=True)
                self.update(recording.id, error=f"转写失败后超过 {days} 天，原始文件已清理，请重新上传")
                removed += 1
        return removed

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
                    "(SELECT person_id FROM attributions WHERE recording_id = ? AND decision = 'confirmed' "
                    "UNION SELECT to_person FROM segment_fixes WHERE recording_id = ? AND action = 'move')",
                    (recording_id, recording_id),
                )
                db.execute("DELETE FROM attributions WHERE recording_id = ?", (recording_id,))
                for table in ("reviewed", "review_units", "segment_fixes", "denoised"):
                    db.execute(f"DELETE FROM {table} WHERE recording_id = ?", (recording_id,))
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

    def clean_path(self, recording: Recording) -> Path | None:
        if not recording.transcript_id:
            return None
        return self.folder(recording.id) / f"clean-{recording.transcript_id}.json"

    def cleaned(self, recording: Recording) -> Transcript | None:
        """The transcript with the model's corrections, or as recognized when it was not proofread or the
        proofreading does not match it segment for segment."""
        transcript = self.transcript(recording)
        path = self.clean_path(recording)
        if transcript is None or path is None or not path.is_file():
            return transcript
        try:
            clean = Cleaned.model_validate_json(path.read_text())
        except (OSError, ValueError):
            logger.warning("proofreading of %s is unreadable; using the transcript", recording.id)
            return transcript
        if clean.transcript_id != transcript.id or not matches(transcript, clean.segments):
            logger.warning("proofreading of %s does not match its transcript; using the transcript", recording.id)
            return transcript
        return transcript.model_copy(update={"segments": clean.segments})

    def unproofread(self) -> tuple[Recording, ...]:
        """Transcribed recordings someone is identified in whose transcript was not proofread yet, oldest first."""
        with self._db() as db:
            rows = db.execute(
                "SELECT * FROM recordings r WHERE r.status = 'ready' AND r.transcript_id IS NOT NULL "
                "AND r.proofread IS NOT r.transcript_id AND EXISTS (SELECT 1 FROM attributions a "
                "WHERE a.recording_id = r.id AND a.transcript_id = r.transcript_id AND a.decision = 'confirmed') "
                "ORDER BY r.created_at, r.id"
            ).fetchall()
        return tuple(Recording.model_validate(dict(row)) for row in rows)

    def write_cleaned(self, recording: Recording, clean: Cleaned) -> bool:
        """File the proofreading of the recording's transcript, if none is filed yet. False when one was there
        already."""
        transcript = self.transcript(recording)
        path = self.clean_path(recording)
        if transcript is None or path is None or clean.transcript_id != transcript.id:
            raise ValueError("校对结果与转写不对应")
        if not matches(transcript, clean.segments):
            raise ValueError("校对结果与转写的段落不对应")
        return _file_once(path, clean, "校对结果写入校验失败")

    def names_path(self, recording: Recording) -> Path | None:
        if not recording.transcript_id:
            return None
        return self.folder(recording.id) / f"names-{recording.transcript_id}.json"

    def names(self, recording: Recording) -> dict[str, Cue]:
        """What the meeting calls each of its speakers, by speaker; empty until the model was asked. Filed names
        never change, so each file is read once per process."""
        path = self.names_path(recording)
        if path is None:
            return {}
        key = str(path)
        with _SPEAKERS_LOCK:
            found = _NAMES.get(key)
        if found is None:
            if not path.is_file():
                return {}
            try:
                named = Named.model_validate_json(path.read_text())
            except (OSError, ValueError):
                logger.warning("speaker names of %s are unreadable", recording.id)
                return {}
            current = named.transcript_id == recording.transcript_id
            # Names filed before ``said`` was required are held to it here: their quote is what named them.
            kept = [cue for cue in named.speakers if said(cue.name, cue.quote)]
            found = {cue.speaker: cue for cue in kept} if current else {}
            with _SPEAKERS_LOCK:
                _NAMES[key] = found
        return found

    def unnamed(self) -> tuple[Recording, ...]:
        """Transcribed recordings whose speakers the model was not asked to name yet, oldest first."""
        with self._db() as db:
            rows = db.execute(
                "SELECT * FROM recordings WHERE status = 'ready' AND transcript_id IS NOT NULL "
                "AND named IS NOT transcript_id ORDER BY created_at, id"
            ).fetchall()
        return tuple(Recording.model_validate(dict(row)) for row in rows)

    def write_names(self, recording: Recording, named: Named) -> bool:
        """File the names the meeting calls its speakers by, if none are filed yet. False when they were there
        already."""
        speakers = self.speakers(recording)
        path = self.names_path(recording)
        if speakers is None or path is None or named.transcript_id != recording.transcript_id:
            raise ValueError("说话人称呼与转写不对应")
        if not {cue.speaker for cue in named.speakers} <= {speaker.id for speaker in speakers}:
            raise ValueError("说话人称呼里有转写没有的说话人")
        return _file_once(path, named, "说话人称呼写入校验失败")

    def asked_names(self, recording_id: str, transcript_id: str) -> None:
        """Note that the model was asked to name the speakers of this transcript, whatever came of it."""
        with self._db() as db:
            db.execute(
                "UPDATE recordings SET named = ? WHERE id = ? AND transcript_id = ?",
                (transcript_id, recording_id, transcript_id),
            )

    def spend(self, kind: str, tokens: int) -> None:
        if tokens > 0:
            with self._db() as db:
                db.execute("INSERT INTO spending (at, kind, tokens) VALUES (?, ?, ?)", (_now(), kind, tokens))

    def spent(self, since: dt.datetime) -> tuple[int, str | None]:
        """Tokens spent since ``since``, and when the oldest of those was spent."""
        with self._db() as db:
            row = db.execute(
                "SELECT COALESCE(SUM(tokens), 0), MIN(at) FROM spending WHERE at >= ?", (since.isoformat(),)
            ).fetchone()
        return int(row[0]), row[1]

    def heard_asr(self, asr: str | None) -> None:
        """Note the service a transcription just came from as the current one, when it said which."""
        if asr is not None:
            with self._db() as db:
                db.execute(
                    "INSERT INTO collector (key, value) VALUES ('asr', ?) ON CONFLICT (key) DO UPDATE SET value = "
                    "excluded.value",
                    (asr,),
                )

    def collector(self) -> CollectorVersion:
        """What would collect a recording now: the service the latest transcription came from, when it said which,
        and the current attribution and review rules."""
        with self._db() as db:
            row = db.execute("SELECT value FROM collector WHERE key = 'asr'").fetchone()
        return CollectorVersion(asr=row[0] if row else None, attribution=ATTRIBUTION_VERSION, cleanup=CLEANUP_VERSION)

    def recollectable(self) -> tuple[Recording, ...]:
        """Transcribed recordings the current service (``collector``) would transcribe anew, since another one made
        their transcript or it did not say which, oldest first. The owner decides whether to; none while the current
        service is unknown."""
        current = self.collector()
        return tuple(
            recording
            for recording in sorted(self.list(), key=lambda r: (r.created_at, r.id))
            if recording.status == "ready"
            and recording.kind != "transcript"
            and recording.transcript_id is not None
            and recollect_scope(CollectorVersion(recording.asr, current.attribution, current.cleanup), current) == "asr"
        )

    def original(self, recording_id: str) -> Path | None:
        """The upload of a recording not yet transcribed."""
        return next(self.folder(recording_id).glob("original.*"), None)

    def transcribe(self, recording_id: str, transcriber: CommandTranscriber, progress: Progress) -> Recording:
        """Transcribe a queued recording with every speaker's voiceprint, keep the FLAC it was transcribed from as
        the playback copy, then delete the upload. On failure the upload stays, the recording is marked failed and
        ``TranscriptionError`` says why; cut off by the service stopping, it is queued again
        (``TranscriptionInterrupted``)."""
        with self.lock:
            recording = self.get(recording_id)
            if recording is None or recording.status != "queued":
                raise TranscriptionError("这段录音已删除或不在排队中")
            self.update(recording_id, status="transcribing", error="", transcribed_s=0)
        folder = self.folder(recording_id)
        audio = folder / "audio.flac"
        try:
            original = self.original(recording_id)
            if original is None:
                raise TranscriptionError("原始文件已不在，请重新上传")
            try:
                duration, creation = extract_flac(original, audio)
            except (subprocess.SubprocessError, OSError, ValueError, KeyError, IndexError) as exc:
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
                asr=transcriber.asr,
            )
            self.write_transcript(folder, transcript)
            # The very samples the transcript's times refer to.
            audio.replace(folder / "playback.flac")
            # Published before the upload goes: a stop in between leaves a ready recording, never a queued one
            # whose upload is gone.
            self.update(
                recording_id,
                status="ready",
                transcript_id=transcript.id,
                transcribed_s=duration,
                speakers=len(speakers),
                segments=len(segments),
                asr=transcript.asr,
            )
            self.heard_asr(transcript.asr)
        except BaseException as exc:
            audio.unlink(missing_ok=True)
            if _interrupted(exc):
                # Cut off by a stop: waiting again, as ``resume`` also leaves it at start-up, never shown as failed.
                self.update(recording_id, status="queued", error="", transcribed_s=0)
                raise TranscriptionInterrupted("转写被中断，会重新开始") from exc
            message = str(exc) if isinstance(exc, TranscriptionError) else "转写失败，请稍后重试"
            self.update(recording_id, status="failed", error=message, transcribed_s=0)
            if isinstance(exc, TranscriptionError):
                raise
            raise TranscriptionError(message) from exc
        original.unlink(missing_ok=True)
        result = self.get(recording_id)
        assert result is not None
        return result

    @staticmethod
    def write_transcript(folder: Path, transcript: Transcript) -> None:
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
