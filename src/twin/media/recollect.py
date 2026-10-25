"""Transcribing a recording again with a newer service, keeping what people decided about it.

A newer transcription service (``collector``) may hear a recording better, but its transcript numbers the speakers and
segments anew, and the owner's decisions refer to those numbers. So the recording keeps its transcript while the new
one is made from the playback copy (the 16 kHz audio the first transcription heard); then, in one transaction, the
owner's decisions are carried to the new speakers and segments that cover the same stretches of the recording, and the
recording switches to it. What cannot be carried is reported, for the owner to see first. The old transcript and every
decision about it stay, so the recording can go back to it (``rollback``).

Only people's decisions are carried. Automatic ones are made again for the new transcript: ``Team.classify`` right
after the switch, the review (``media.review``), proofreading and speaker names when their turn comes, as for any new
transcript. A twin is rebuilt only if a person's speech in the recording changed (``Team._reopen``).
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import sqlite3
import uuid
from collections.abc import Iterable, Mapping, Sequence

from pydantic import BaseModel

from .ingest import CommandTranscriber, Progress, Segment, flac_seconds
from .library import Library, Recording, Transcript, TranscriptionError, TranscriptionInterrupted, _interrupted
from .team import Team, cosine, segment_owners

logger = logging.getLogger(__name__)

# A new speaker takes an old speaker's decision when at least this share of its speech lies within that speaker's
# segments: a speaker the new service split in two carries it to both halves, and one it merged from differently
# decided speakers carries neither.
CARRY = 0.8
# A new speaker overlapping a decided old one this much, without taking its decision, is reported as unsettled.
NOTICE = 0.2
# A decision about one segment carries to a new segment lying at least this much within the old one.
SEGMENT_CARRY = 0.5
# A voice sample left on an older transcript moves to the speaker of the current one most like it, from this
# similarity, once that speaker is given to the sample's person; otherwise it stops standing (``settle_samples``). On
# daw two thirds of the samples were left behind this way, and they were far more alike to other people's than samples
# of the current transcripts (median 0.49 against 0.16): kept, they matched voices to several people at once and held
# them back. Moving the ones this alike and retiring the rest let voice alone take 225 waiting speakers, while 715 of
# 825 decisions it had taken came out the same.
SAMPLE_MOVE = 0.9


class Unsettled(BaseModel):
    """A new speaker that covers speech people decided about, but no decision could be carried to."""

    speaker_id: str
    seconds: float
    # Whom the old speakers it overlaps were confirmed as.
    people: list[str]


class Report(BaseModel):
    old_transcript: str
    new_transcript: str
    asr: str | None = None
    # Old speakers with a decision of the owner, and how many new speakers took one.
    decided: int = 0
    carried: int = 0
    unsettled: list[Unsettled] = []
    # The owner's decisions about single segments: carried to new segments, and those (old indices) that were not.
    fixes_carried: int = 0
    fixes_lost: list[int] = []
    # Voice samples moved to the new speaker they now stand on, and their rows before and after (for ``rollback``).
    samples_moved: list[tuple[int, int]] = []
    # Voice samples of the old transcript that stopped standing, finding no new speaker (``settle_samples``).
    samples_retired: list[int] = []
    # Seconds of speech of each person in the recording, before and after.
    seconds: dict[str, tuple[float, float]] = {}


def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat()


def ask(library: Library, recording_ids: Iterable[str]) -> int:
    """Ask for these recordings to be transcribed again, those the current service would transcribe anew
    (``Library.recollectable``); returns how many were asked."""
    wanted = set(recording_ids)
    chosen = [r.id for r in library.recollectable() if r.id in wanted and r.recollect is None]
    with library.transaction() as db:
        for recording_id in chosen:
            db.execute("UPDATE recordings SET recollect = ? WHERE id = ?", (_now(), recording_id))
    return len(chosen)


def waiting(library: Library) -> list[Recording]:
    """Recordings asked to be transcribed again, earliest asked first."""
    with library.read() as db:
        rows = db.execute(
            "SELECT * FROM recordings WHERE recollect IS NOT NULL AND status = 'ready' ORDER BY recollect, id"
        ).fetchall()
    return [Recording.model_validate(dict(row)) for row in rows]


def _overlap(a: tuple[float, float], b: tuple[float, float]) -> float:
    return max(0.0, min(a[1], b[1]) - max(a[0], b[0]))


def _spans(segments: Sequence[Segment]) -> dict[str, list[tuple[float, float]]]:
    found: dict[str, list[tuple[float, float]]] = {}
    for segment in segments:
        if segment.speaker and segment.end > segment.start:
            found.setdefault(segment.speaker, []).append((segment.start, segment.end))
    return found


def speaker_overlap(old: Sequence[Segment], new: Sequence[Segment]) -> dict[str, dict[str, float]]:
    """For each new speaker, the share of its speech within each old speaker's segments."""
    before, after = _spans(old), _spans(new)
    shares: dict[str, dict[str, float]] = {}
    for speaker, spans in after.items():
        total = sum(end - start for start, end in spans)
        shares[speaker] = {
            other: sum(_overlap(a, b) for a in spans for b in theirs) / total
            for other, theirs in before.items()
            if total > 0
        }
    return shares


def segment_map(old: Sequence[Segment], new: Sequence[Segment]) -> dict[int, list[int]]:
    """For each old segment, the new segments lying mostly within it (``SEGMENT_CARRY``)."""
    found: dict[int, list[int]] = {}
    for j, segment in enumerate(new):
        length = segment.end - segment.start
        if length <= 0:
            continue
        for i, before in enumerate(old):
            if _overlap((before.start, before.end), (segment.start, segment.end)) >= SEGMENT_CARRY * length:
                found.setdefault(i, []).append(j)
    return found


def _speech(transcript: Transcript, db: sqlite3.Connection, recording_id: str) -> dict[str, float]:
    """Seconds of speech of each person in this transcript of the recording, as their twins take it."""
    speakers = {
        row[0]: (row[1], row[2])
        for row in db.execute(
            "SELECT speaker_id, decision, person_id FROM attributions WHERE recording_id = ? AND transcript_id = ?",
            (recording_id, transcript.id),
        )
    }
    fixes = {
        row[0]: (row[1], row[2], row[3])
        for row in db.execute(
            "SELECT segment, from_person, action, to_person FROM segment_fixes WHERE recording_id = ? "
            "AND transcript_id = ?",
            (recording_id, transcript.id),
        )
    }
    found: dict[str, float] = {}
    for segment, owner in zip(transcript.segments, segment_owners(transcript, speakers, fixes), strict=True):
        if owner:
            found[owner] = found.get(owner, 0.0) + segment.end - segment.start
    return found


def run(library: Library, recording_id: str, transcriber: CommandTranscriber, progress: Progress) -> Report:
    """Transcribe the recording again from its playback copy, carry the owner's decisions over and switch to the new
    transcript. ``TranscriptionError`` when it could not be transcribed (the recording keeps its transcript and is no
    longer asked for, so a failing service does not take every turn; ``TranscriptionInterrupted`` keeps it asked)."""
    recording = library.get(recording_id)
    old = library.transcript(recording) if recording else None
    folder = library.folder(recording_id)
    playback = folder / "playback.flac"
    if recording is None or old is None or recording.status != "ready" or not playback.is_file():
        raise TranscriptionError("这段录音没有可以重新转写的转写和试听文件")
    try:
        try:
            # The playback copy holds the 16 kHz 16-bit samples themselves; the service reads FLAC as it is.
            duration = flac_seconds(playback)
            transcriber.diarize, transcriber.reference, transcriber.references = True, None, {}
            segments = transcriber.transcribe(playback, duration, progress)
        except BaseException as exc:
            if _interrupted(exc):
                raise TranscriptionInterrupted("重新转写被中断，会重新开始") from exc
            raise TranscriptionError("重新转写失败，原来的转写保持不变") from exc
        speakers = transcriber.speakers
        if not speakers or any(s.embedding is None for s in speakers):
            raise TranscriptionError("转写服务没有返回声纹，原来的转写保持不变")
        new = Transcript(
            id=uuid.uuid4().hex[:12],
            recording_id=recording_id,
            created_at=_now(),
            duration_s=old.duration_s,
            segments=segments,
            speakers=speakers,
            asr=transcriber.asr,
        )
        Library.write_transcript(folder, new)
    except TranscriptionInterrupted:
        raise
    except BaseException:
        library.update(recording_id, recollect=None)
        raise
    report = _switch(library, recording, old, new)
    library.heard_asr(new.asr)
    Team(library).classify(recording_id)
    # The samples no owner's decision carried over move to the speakers voice alone gave their person, or stop.
    settle_samples(library, {recording_id})
    with library.transaction() as db:
        if row := db.execute(
            "SELECT report FROM recollections WHERE recording_id = ? AND new_transcript = ?", (recording_id, new.id)
        ).fetchone():
            settled = Report.model_validate_json(row[0])
            report.samples_moved, report.samples_retired = settled.samples_moved, settled.samples_retired
        after = _speech(new, db, recording_id)
        report.seconds = {
            person: (round(report.seconds.get(person, (0.0, 0.0))[0], 1), round(after.get(person, 0.0), 1))
            for person in sorted({*report.seconds, *after})
        }
        db.execute(
            "UPDATE recollections SET report = ? WHERE recording_id = ? AND new_transcript = ?",
            (report.model_dump_json(), recording_id, new.id),
        )
    return report


def _switch(library: Library, recording: Recording, old: Transcript, new: Transcript) -> Report:
    report = Report(old_transcript=old.id, new_transcript=new.id, asr=new.asr)
    shares = speaker_overlap(old.segments, new.segments)
    by_segment = segment_map(old.segments, new.segments)
    embeddings = {s.id: s.embedding for s in new.speakers}
    seconds = {s.id: s.seconds for s in new.speakers}
    now = _now()
    with library.transaction() as db:
        current = db.execute("SELECT transcript_id FROM recordings WHERE id = ?", (recording.id,)).fetchone()
        if current is None or current[0] != old.id:
            raise TranscriptionError("重新转写期间这段录音的转写已经变了，结果没有采用")
        before = _speech(old, db, recording.id)
        report.seconds = {person: (s, 0.0) for person, s in before.items()}
        decided = {
            row["speaker_id"]: row
            for row in db.execute(
                "SELECT * FROM attributions WHERE recording_id = ? AND transcript_id = ? AND auto = 0 "
                "AND decision != 'none'",
                (recording.id, old.id),
            )
        }
        report.decided = len(decided)
        # New speaker -> the old decided speaker it takes the decision of.
        takes: dict[str, str] = {}
        for speaker, share in shares.items():
            best = max(share, key=lambda other: share[other], default=None)
            if best is not None and best in decided and share[best] >= CARRY:
                takes[speaker] = best
            else:
                people = sorted(
                    {
                        str(decided[other]["person_id"])
                        for other, value in share.items()
                        if other in decided and value >= NOTICE and decided[other]["person_id"]
                    }
                )
                if people or any(other in decided and value >= NOTICE for other, value in share.items()):
                    report.unsettled.append(
                        Unsettled(speaker_id=speaker, seconds=round(seconds.get(speaker, 0.0), 1), people=people)
                    )
        for speaker, source in sorted(takes.items()):
            row = decided[source]
            db.execute(
                "INSERT INTO attributions (recording_id, transcript_id, speaker_id, decision, person_id, rejected, "
                "updated_at, auto, disputed) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)",
                (
                    recording.id,
                    new.id,
                    speaker,
                    row["decision"],
                    row["person_id"],
                    row["rejected"],
                    now,
                    row["disputed"],
                ),
            )
        report.carried = len(takes)
        confirmed = {
            speaker: str(decided[source]["person_id"])
            for speaker, source in takes.items()
            if decided[source]["decision"] == "confirmed" and decided[source]["person_id"]
        }
        _move_samples(db, report, recording.id, old.id, new.id, takes, confirmed, embeddings, shares)
        for row in db.execute(
            "SELECT * FROM segment_fixes WHERE recording_id = ? AND transcript_id = ? AND auto = 0",
            (recording.id, old.id),
        ).fetchall():
            targets = [
                j
                for j in by_segment.get(row["segment"], [])
                if confirmed.get(new.segments[j].speaker or "") == row["from_person"]
            ]
            if not targets:
                report.fixes_lost.append(int(row["segment"]))
                continue
            for j in targets:
                db.execute(
                    "INSERT OR REPLACE INTO segment_fixes (recording_id, transcript_id, segment, from_person, action, "
                    "to_person, updated_at, auto) VALUES (?, ?, ?, ?, ?, ?, ?, 0)",
                    (recording.id, new.id, j, row["from_person"], row["action"], row["to_person"], now),
                )
            report.fixes_carried += 1
        db.execute(
            "UPDATE recordings SET transcript_id = ?, previous = ?, asr = ?, speakers = ?, segments = ?, "
            "recollect = NULL, revision = revision + 1, updated_at = ? WHERE id = ?",
            (new.id, old.id, new.asr, len(new.speakers), len(new.segments), now, recording.id),
        )
        Team._reopen(db, recording.id, set(before))
        db.execute(
            "INSERT INTO recollections (recording_id, old_transcript, new_transcript, at, report) "
            "VALUES (?, ?, ?, ?, ?)",
            (recording.id, old.id, new.id, now, report.model_dump_json()),
        )
    return report


def _move_samples(
    db: sqlite3.Connection,
    report: Report,
    recording_id: str,
    old: str,
    new: str,
    takes: Mapping[str, str],
    confirmed: Mapping[str, str],
    embeddings: Mapping[str, list[float] | None],
    shares: Mapping[str, Mapping[str, float]],
) -> None:
    """A voice sample taken from an old speaker moves to the new speaker that took its decision (the one covering most
    of it), with that speaker's voiceprint, so later decisions about the new speaker govern it. A sample whose speaker
    has no successor here is left to ``settle_samples``, which moves it once voice alone gave its person a speaker."""
    for row in db.execute(
        "SELECT id, person_id, speaker_id, created_at, source, corrected FROM voiceprints WHERE recording_id = ? "
        "AND transcript_id = ? AND active = 1",
        (recording_id, old),
    ).fetchall():
        heirs = [
            s for s, source in takes.items() if source == row["speaker_id"] and confirmed.get(s) == row["person_id"]
        ]
        if not heirs:
            continue
        heir = max(heirs, key=lambda s: shares[s].get(row["speaker_id"], 0.0))
        vector = embeddings.get(heir)
        if not vector:
            continue
        # The same sample on the new transcript: how it was taken and its track record go with it.
        cursor = db.execute(
            "INSERT INTO voiceprints (person_id, recording_id, transcript_id, speaker_id, embedding, active, "
            "created_at, source, corrected) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)",
            (
                row["person_id"],
                recording_id,
                new,
                heir,
                json.dumps(vector),
                row["created_at"],
                row["source"],
                row["corrected"],
            ),
        )
        db.execute("UPDATE voiceprints SET active = 0 WHERE id = ?", (row["id"],))
        assert cursor.lastrowid is not None
        db.execute("UPDATE attributions SET sample = ? WHERE sample = ?", (cursor.lastrowid, row["id"]))
        report.samples_moved.append((int(row["id"]), int(cursor.lastrowid)))


def settle_samples(library: Library, recordings: set[str] | None = None) -> tuple[int, int]:
    """Voice samples still standing on an older transcript of their recording (``recordings``: only theirs) move
    to the speaker of the current transcript most like them, at least ``SAMPLE_MOVE`` alike and given to the same
    person, by the owner or by voice; the others stop standing. Such a sample cannot be heard (its speaker is numbered
    anew) and was measured by an older service. The decisions it took stay: they are made again under the current
    rules (``collector``). What moved or stopped is added to the transcription again that left it (``rollback``).
    Returns how many moved and how many stopped."""
    with library.read() as db:
        rows = db.execute(
            "SELECT v.id, v.person_id, v.recording_id, v.transcript_id, v.embedding, v.created_at, v.source, "
            "v.corrected FROM voiceprints v JOIN recordings r ON r.id = v.recording_id "
            "WHERE v.active = 1 AND r.transcript_id IS NOT NULL AND v.transcript_id <> r.transcript_id ORDER BY v.id"
        ).fetchall()
    left: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        if recordings is None or row["recording_id"] in recordings:
            left.setdefault(row["recording_id"], []).append(row)
    moved = retired = 0
    for recording_id, samples in left.items():
        recording = library.get(recording_id)
        speakers = library.speakers(recording) if recording else None
        if recording is None or not speakers:
            # Its current transcript cannot be read: nothing tells where the samples went, so they wait.
            continue
        with library.transaction() as db:
            current = db.execute("SELECT transcript_id FROM recordings WHERE id = ?", (recording_id,)).fetchone()
            if current is None or current[0] != recording.transcript_id:
                continue
            given = {
                r["speaker_id"]: r["person_id"]
                for r in db.execute(
                    "SELECT speaker_id, person_id FROM attributions WHERE recording_id = ? AND transcript_id = ? "
                    "AND decision = 'confirmed'",
                    (recording_id, recording.transcript_id),
                )
            }
            standing = {
                (r["person_id"], r["speaker_id"]): r["id"]
                for r in db.execute(
                    "SELECT id, person_id, speaker_id FROM voiceprints WHERE recording_id = ? AND transcript_id = ? "
                    "AND active = 1",
                    (recording_id, recording.transcript_id),
                )
            }
            found = db.execute(
                "SELECT report FROM recollections WHERE recording_id = ? AND new_transcript = ? AND rolled_back = 0",
                (recording_id, recording.transcript_id),
            ).fetchone()
            report = Report.model_validate_json(found[0]) if found else None
            for row in samples:
                vector = json.loads(row["embedding"])
                scored = [(cosine(vector, s.embedding), s) for s in speakers if s.embedding]
                score, heir = max(scored, key=lambda pair: pair[0], default=(0.0, None))
                db.execute("UPDATE voiceprints SET active = 0 WHERE id = ?", (row["id"],))
                # Only the transcript before this one can be gone back to.
                trail = report if report is not None and row["transcript_id"] == report.old_transcript else None
                if heir is None or score < SAMPLE_MOVE or given.get(heir.id) != row["person_id"]:
                    retired += 1
                    if trail is not None:
                        trail.samples_retired.append(int(row["id"]))
                    continue
                into = standing.get((row["person_id"], heir.id))
                if into is None:
                    # The same sample on the current transcript: how it was taken and its track record go with it.
                    cursor = db.execute(
                        "INSERT INTO voiceprints (person_id, recording_id, transcript_id, speaker_id, embedding, "
                        "active, created_at, source, corrected) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)",
                        (
                            row["person_id"],
                            recording_id,
                            recording.transcript_id,
                            heir.id,
                            json.dumps(heir.embedding),
                            row["created_at"],
                            row["source"],
                            row["corrected"],
                        ),
                    )
                    assert cursor.lastrowid is not None
                    into = standing[(row["person_id"], heir.id)] = int(cursor.lastrowid)
                db.execute("UPDATE attributions SET sample = ? WHERE sample = ?", (into, row["id"]))
                moved += 1
                if trail is not None:
                    trail.samples_moved.append((int(row["id"]), into))
            if report is not None:
                db.execute(
                    "UPDATE recollections SET report = ? WHERE recording_id = ? AND new_transcript = ?",
                    (report.model_dump_json(), recording_id, recording.transcript_id),
                )
    if moved or retired:
        logger.info("voice samples left on older transcripts: %d moved, %d retired", moved, retired)
    return moved, retired


def rollback(library: Library, recording_id: str) -> bool:
    """Go back to the transcript before the last transcription again, with every decision about it as it was; the
    samples moved to the new transcript go back too. False when there is nothing to go back to."""
    recording = library.get(recording_id)
    if recording is None or not recording.previous or recording.transcript_id is None:
        return False
    previous = library.transcript(recording.model_copy(update={"transcript_id": recording.previous}))
    if previous is None:
        return False
    with library.transaction() as db:
        current = db.execute("SELECT transcript_id FROM recordings WHERE id = ?", (recording_id,)).fetchone()
        if current is None or current[0] != recording.transcript_id:
            return False
        row = db.execute(
            "SELECT report FROM recollections WHERE recording_id = ? AND new_transcript = ? AND rolled_back = 0",
            (recording_id, recording.transcript_id),
        ).fetchone()
        report = Report.model_validate_json(row[0]) if row else None
        people = {
            r[0]
            for r in db.execute(
                "SELECT person_id FROM attributions WHERE recording_id = ? AND decision = 'confirmed' AND person_id "
                "IS NOT NULL UNION SELECT to_person FROM segment_fixes WHERE recording_id = ? AND action = 'move'",
                (recording_id, recording_id),
            )
            if r[0]
        }
        # Samples of the new transcript stand no more; those moved from the old one stand again.
        db.execute(
            "UPDATE voiceprints SET active = 0 WHERE recording_id = ? AND transcript_id = ?",
            (recording_id, recording.transcript_id),
        )
        for before, after in report.samples_moved if report else ():
            db.execute(
                "UPDATE voiceprints SET active = 1, corrected = COALESCE((SELECT corrected FROM voiceprints "
                "WHERE id = ?), corrected) WHERE id = ?",
                (after, before),
            )
            db.execute("UPDATE attributions SET sample = ? WHERE sample = ?", (before, after))
        for before in report.samples_retired if report else ():
            db.execute("UPDATE voiceprints SET active = 1 WHERE id = ?", (before,))
        db.execute(
            "UPDATE recordings SET transcript_id = ?, previous = NULL, asr = ?, speakers = ?, segments = ?, "
            "revision = revision + 1, updated_at = ? WHERE id = ?",
            (previous.id, previous.asr, len(previous.speakers), len(previous.segments), _now(), recording_id),
        )
        db.execute(
            "UPDATE recollections SET rolled_back = 1 WHERE recording_id = ? AND new_transcript = ?",
            (recording_id, recording.transcript_id),
        )
        Team._reopen(db, recording_id, people)
    return True


def reports(library: Library) -> list[tuple[str, Report, bool]]:
    """Every transcription again, latest first: the recording, what was carried over, and whether it was undone."""
    with library.read() as db:
        rows = db.execute(
            "SELECT recording_id, report, rolled_back FROM recollections ORDER BY at DESC, recording_id"
        ).fetchall()
    return [(row[0], Report.model_validate_json(row[1]), bool(row[2])) for row in rows]
