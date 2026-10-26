"""Atomic recording-attribution changes shared by library storage and voice matching.

The caller owns the SQLite transaction: losing a voice sample, withdrawing its derived decisions and closing
the affected twins either commit together or do not happen. This module does not open a library or classify a voice.
"""

from __future__ import annotations

import datetime as dt
import sqlite3


def withdraw_samples(db: sqlite3.Connection, samples: set[int]) -> int:
    """Take back the speakers given to someone by voice alone through these voice samples, which no longer stand
    for them: each waits for the owner, offered to whom it was given (``voice_tiers``) rather than dropped.
    Earlier transcripts lose these derived decisions too, so rolling back cannot restore them. Returns how
    many current speakers were taken back; only those change the twins and the recording's revision now."""
    if not samples:
        return 0
    marks = ", ".join("?" * len(samples))
    rows = db.execute(
        "SELECT a.recording_id, a.transcript_id, a.speaker_id, a.person_id, a.transcript_id = r.transcript_id "
        "FROM attributions a JOIN recordings r ON r.id = a.recording_id WHERE a.auto = 1 "
        f"AND a.decision = 'confirmed' AND a.sample IN ({marks})",
        sorted(samples),
    ).fetchall()
    taken: dict[str, set[str]] = {}
    count = 0
    for recording_id, transcript_id, speaker_id, person_id, current in rows:
        db.execute(
            "UPDATE attributions SET decision = 'none', person_id = NULL, suggest = ?, tier = 'mid', "
            "updated_at = ? WHERE recording_id = ? AND transcript_id = ? AND speaker_id = ?",
            (person_id, dt.datetime.now(dt.UTC).isoformat(), recording_id, transcript_id, speaker_id),
        )
        if current:
            taken.setdefault(recording_id, set()).add(person_id)
            count += 1
    for recording_id, people in taken.items():
        reopen_twins(db, recording_id, people)
        db.execute("UPDATE recordings SET revision = revision + 1 WHERE id = ?", (recording_id,))
    return count


def reopen_twins(db: sqlite3.Connection, recording_id: str, people: set[str]) -> None:
    """Close the twins of everyone who speaks in the recording (their sources name the others too), including
    those given segments there (``media.review``), and of ``people``, whose speakers there just changed."""
    speaking = {
        row[0]
        for row in db.execute(
            "SELECT person_id FROM attributions WHERE recording_id = ? AND decision = 'confirmed' "
            "UNION SELECT to_person FROM segment_fixes WHERE recording_id = ? AND action = 'move'",
            (recording_id, recording_id),
        )
        if row[0]
    }
    bump_twins(db, speaking | people)


def bump_twins(db: sqlite3.Connection, people: set[str]) -> None:
    affected = sorted(people)
    if affected:
        db.execute(
            f"UPDATE personas_sync SET wanted = wanted + 1 WHERE person_id IN ({','.join('?' * len(affected))})",
            affected,
        )
