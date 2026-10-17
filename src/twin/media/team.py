"""People in an account's recording library: who each speaker is, how a speaker is matched to a person, and the
twin sources that follow from those decisions.

The owner decides; matching only proposes. A person is recognised by voice samples (the centroids of speakers the
owner confirmed *and* chose as samples), and candidates are computed when asked, never stored, so nothing goes
stale. Every decision raises the recording's ``revision`` (a page holding an older one is refused) and the
``wanted`` version of every twin that had or now has a speaker in that recording, in the same transaction: those
twins stay closed until a build of exactly that state completes (see ``Team.built``).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import sqlite3
import uuid
from collections.abc import Iterable
from typing import Literal

from pydantic import BaseModel

from ..util import date_from_name
from .ingest import Speaker, timestamp
from .library import Library, Recording, Transcript

Action = Literal["confirm", "unknown", "mixed", "reject", "clear"]
Decision = Literal["none", "confirmed", "unknown", "mixed"]
# A speaker is offered for review from this similarity to someone's voice samples: in AliMeeting calibration of the
# single-person claim, people absent from a meeting never passed 0.44. The pilot recalibrates it.
SHOW = 0.45
# Candidates closer than this are shown together as "close, tell them apart".
NEAR = 0.05
# Twin sources made from the library; the rest of the id names the recording and the person's own segments.
SOURCE_PREFIX = "src_lib_"


class Stale(Exception):
    """The page decided on an older transcript or revision of the recording."""


class Person(BaseModel):
    id: str
    name: str
    persona_id: str | None = None
    created_at: str
    speakers: int = 0
    seconds: float = 0
    samples: int = 0


class Candidate(BaseModel):
    person_id: str
    name: str
    score: float


class TwinSource(BaseModel):
    """What a twin's source made from one recording holds; the web layer stores it as a persona source."""

    source_id: str
    kind: Literal["audio", "video"]
    title: str
    origin: str
    duration_s: float | None
    date: str | None
    # (speaker, text, whether it is the person) per transcript segment; empty segments keep their number.
    lines: list[tuple[str, str, bool]]


class SpeakerView(BaseModel):
    id: str
    seconds: float
    decision: Decision = "none"
    person_id: str | None = None
    rejected: list[str] = []
    sample: bool = False
    candidates: list[Candidate] = []
    near: bool = False


def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat()


def _unit(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vector)) or 1.0
    return [x / norm for x in vector]


def _cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        return 0.0
    return sum(x * y for x, y in zip(_unit(a), _unit(b), strict=True))


class Team:
    def __init__(self, library: Library) -> None:
        self.library = library

    # ------------------------------------------------------------------ people

    def people(self) -> list[Person]:
        with self.library.read() as db:
            people = [Person.model_validate(dict(row)) for row in db.execute("SELECT * FROM people ORDER BY name")]
            samples = dict(
                db.execute("SELECT person_id, COUNT(*) FROM voiceprints WHERE active = 1 GROUP BY person_id").fetchall()
            )
            confirmed = db.execute(
                "SELECT a.person_id, a.recording_id, a.transcript_id, a.speaker_id FROM attributions a "
                "JOIN recordings r ON r.id = a.recording_id AND r.transcript_id = a.transcript_id "
                "WHERE a.decision = 'confirmed'"
            ).fetchall()
        seconds: dict[str, float] = {}
        counts: dict[str, int] = {}
        heard: dict[str, tuple[Speaker, ...]] = {}
        for person_id, recording_id, _, speaker_id in confirmed:
            if recording_id not in heard:
                recording = self.library.get(recording_id)
                heard[recording_id] = (self.library.speakers(recording) if recording else None) or ()
            speaker = next((s for s in heard[recording_id] if s.id == speaker_id), None)
            counts[person_id] = counts.get(person_id, 0) + 1
            seconds[person_id] = seconds.get(person_id, 0) + (speaker.seconds if speaker else 0)
        for person in people:
            person.samples = samples.get(person.id, 0)
            person.speakers = counts.get(person.id, 0)
            person.seconds = round(seconds.get(person.id, 0), 1)
        return people

    def person(self, person_id: str) -> Person | None:
        return next((p for p in self.people() if p.id == person_id), None)

    def add_person(self, name: str) -> Person:
        name = " ".join(name.split())
        if not name:
            raise ValueError("名字不能为空")
        with self.library.transaction() as db:
            if db.execute("SELECT 1 FROM people WHERE name = ?", (name,)).fetchone():
                raise ValueError(f"已经有叫「{name}」的人")
            person = Person(id="per_" + uuid.uuid4().hex[:12], name=name, created_at=_now())
            db.execute(
                "INSERT INTO people (id, name, persona_id, created_at) VALUES (?, ?, NULL, ?)",
                (person.id, person.name, person.created_at),
            )
        return person

    def delete_person(self, person_id: str) -> bool:
        """Forget a person and their voice samples; their speakers become undecided. False while they have a
        twin (delete the twin first)."""
        with self.library.transaction() as db:
            row = db.execute("SELECT persona_id FROM people WHERE id = ?", (person_id,)).fetchone()
            if row is None:
                return True
            if row["persona_id"]:
                return False
            touched = db.execute(
                "SELECT DISTINCT recording_id FROM attributions WHERE person_id = ?", (person_id,)
            ).fetchall()
            for (recording_id,) in touched:
                self._reopen(db, recording_id, {person_id})
            db.execute(
                "UPDATE attributions SET decision = 'none', person_id = NULL, updated_at = ? WHERE person_id = ?",
                (_now(), person_id),
            )
            for rowid, rejected in db.execute(
                "SELECT rowid, rejected FROM attributions WHERE rejected LIKE ?", (f'%"{person_id}"%',)
            ).fetchall():
                kept = [p for p in json.loads(rejected) if p != person_id]
                db.execute("UPDATE attributions SET rejected = ? WHERE rowid = ?", (json.dumps(kept), rowid))
            db.execute("DELETE FROM people WHERE id = ?", (person_id,))
        return True

    # --------------------------------------------------------------- decisions

    def speakers(self, recording: Recording) -> list[SpeakerView]:
        """Every speaker of the recording's current transcript, with the owner's decision and, while undecided,
        the people their voice matches best."""
        speakers = self.library.speakers(recording)
        if speakers is None:
            return []
        with self.library.read() as db:
            rows = {
                row["speaker_id"]: row
                for row in db.execute(
                    "SELECT * FROM attributions WHERE recording_id = ? AND transcript_id = ?",
                    (recording.id, recording.transcript_id),
                )
            }
            sampled = {
                row[0]
                for row in db.execute(
                    "SELECT speaker_id FROM voiceprints WHERE recording_id = ? AND transcript_id = ? AND active = 1",
                    (recording.id, recording.transcript_id),
                )
            }
            prints = self._prints(db)
        views = []
        for speaker in speakers:
            row = rows.get(speaker.id)
            view = SpeakerView(
                id=speaker.id,
                seconds=round(speaker.seconds, 1),
                decision=row["decision"] if row else "none",
                person_id=row["person_id"] if row else None,
                rejected=json.loads(row["rejected"]) if row else [],
                sample=speaker.id in sampled,
            )
            if view.decision == "none" and speaker.embedding:
                # A speaker's own samples would match it perfectly; they only exist once it is decided anyway.
                view.candidates = self._match(speaker.embedding, prints, set(view.rejected))
                view.near = len(view.candidates) > 1 and view.candidates[0].score - view.candidates[1].score < NEAR
            views.append(view)
        return views

    def decide(
        self,
        recording_id: str,
        transcript_id: str,
        revision: int,
        speaker_id: str,
        action: Action,
        person_id: str | None = None,
        sample: bool = False,
    ) -> int:
        """Record the owner's decision about one speaker; returns the recording's new revision. ``Stale`` when the
        page decided on another transcript or revision; ``ValueError`` for an unknown speaker or person."""
        recording = self.library.get(recording_id)
        if recording is None or recording.transcript_id is None:
            raise ValueError("找不到这段录音的转写")
        speaker = next((s for s in self.library.speakers(recording) or () if s.id == speaker_id), None)
        if speaker is None:
            raise ValueError("这段录音里没有这个说话人")
        if action in {"confirm", "reject"} and not person_id:
            raise ValueError("需要指定是谁")
        with self.library.transaction() as db:
            current = db.execute(
                "SELECT transcript_id, revision FROM recordings WHERE id = ?", (recording_id,)
            ).fetchone()
            if current is None or current["transcript_id"] != transcript_id or current["revision"] != revision:
                raise Stale()
            if person_id and not db.execute("SELECT 1 FROM people WHERE id = ?", (person_id,)).fetchone():
                raise ValueError("找不到这个人")
            row = db.execute(
                "SELECT * FROM attributions WHERE recording_id = ? AND transcript_id = ? AND speaker_id = ?",
                (recording_id, transcript_id, speaker_id),
            ).fetchone()
            decision: Decision = row["decision"] if row else "none"
            owner: str | None = row["person_id"] if row else None
            rejected: list[str] = json.loads(row["rejected"]) if row else []
            before = owner if decision == "confirmed" else None
            if action == "confirm":
                assert person_id is not None
                decision, owner = "confirmed", person_id
                rejected = [p for p in rejected if p != person_id]
            elif action == "reject":
                assert person_id is not None
                rejected = sorted({*rejected, person_id})
                if owner == person_id:
                    decision, owner = "none", None
            elif action == "clear":
                decision, owner = "none", None
            else:
                decision, owner = action, None
            after = owner if decision == "confirmed" else None
            db.execute(
                "INSERT OR REPLACE INTO attributions VALUES (?, ?, ?, ?, ?, ?, ?)",
                (recording_id, transcript_id, speaker_id, decision, owner, json.dumps(rejected), _now()),
            )
            if before != after:
                # The samples taken from this speaker no longer stand for whom they were taken as.
                db.execute(
                    "UPDATE voiceprints SET active = 0 WHERE recording_id = ? AND transcript_id = ? "
                    "AND speaker_id = ? AND person_id IS NOT ?",
                    (recording_id, transcript_id, speaker_id, after),
                )
            already = db.execute(
                "SELECT 1 FROM voiceprints WHERE recording_id = ? AND transcript_id = ? AND speaker_id = ? "
                "AND person_id IS ? AND active = 1",
                (recording_id, transcript_id, speaker_id, after),
            ).fetchone()
            if after and sample and speaker.embedding and not already:
                db.execute(
                    "INSERT INTO voiceprints (person_id, recording_id, transcript_id, speaker_id, embedding, "
                    "active, created_at) VALUES (?, ?, ?, ?, ?, 1, ?)",
                    (after, recording_id, transcript_id, speaker_id, json.dumps(speaker.embedding), _now()),
                )
            if before != after:
                self._reopen(db, recording_id, {p for p in (before, after) if p})
            db.execute("UPDATE recordings SET revision = revision + 1 WHERE id = ?", (recording_id,))
            return int(revision + 1)

    def review(self) -> list[dict[str, object]]:
        """Undecided speakers whose voice matches someone, best match first: the owner's confirmation queue."""
        queue: list[dict[str, object]] = []
        for recording in self.library.list():
            if recording.status != "ready":
                continue
            for speaker in self.speakers(recording):
                if speaker.decision == "none" and speaker.candidates:
                    queue.append(
                        {
                            "recording_id": recording.id,
                            "filename": recording.filename,
                            "transcript_id": recording.transcript_id,
                            "revision": recording.revision,
                            **speaker.model_dump(),
                        }
                    )
        queue.sort(key=lambda entry: -entry["candidates"][0]["score"])  # type: ignore[index]
        return queue

    def _prints(self, db: sqlite3.Connection) -> list[tuple[str, str, list[float]]]:
        return [
            (row["person_id"], row["name"], json.loads(row["embedding"]))
            for row in db.execute(
                "SELECT v.person_id, p.name, v.embedding FROM voiceprints v JOIN people p ON p.id = v.person_id "
                "WHERE v.active = 1"
            )
        ]

    @staticmethod
    def _match(
        embedding: list[float], prints: Iterable[tuple[str, str, list[float]]], rejected: set[str]
    ) -> list[Candidate]:
        """People with active samples the speaker was not denied to be, by their best-matching sample, from
        ``SHOW``; at most the top two."""
        best: dict[str, Candidate] = {}
        for person_id, name, vector in prints:
            if person_id in rejected:
                continue
            score = round(_cosine(embedding, vector), 3)
            if person_id not in best or score > best[person_id].score:
                best[person_id] = Candidate(person_id=person_id, name=name, score=score)
        ranked = sorted((c for c in best.values() if c.score >= SHOW), key=lambda c: -c.score)
        return ranked[:2]

    @staticmethod
    def _reopen(db: sqlite3.Connection, recording_id: str, people: set[str]) -> None:
        """Close the twins of everyone who speaks in the recording (their sources name the others too) and of
        ``people``, whose speakers there just changed."""
        speaking = {
            row[0]
            for row in db.execute(
                "SELECT person_id FROM attributions WHERE recording_id = ? AND decision = 'confirmed'", (recording_id,)
            )
        }
        affected = sorted(speaking | people)
        if affected:
            db.execute(
                f"UPDATE personas_sync SET wanted = wanted + 1 WHERE person_id IN ({','.join('?' * len(affected))})",
                affected,
            )

    # -------------------------------------------------------------- twin sync

    def link(self, person_id: str, persona_id: str) -> None:
        with self.library.transaction() as db:
            db.execute("UPDATE people SET persona_id = ? WHERE id = ?", (persona_id, person_id))
            db.execute(
                "INSERT INTO personas_sync (persona_id, person_id, wanted, done) VALUES (?, ?, 1, 0) "
                "ON CONFLICT(persona_id) DO UPDATE SET person_id = excluded.person_id, wanted = wanted + 1",
                (persona_id, person_id),
            )

    def unlink(self, persona_id: str) -> None:
        with self.library.transaction() as db:
            db.execute("UPDATE people SET persona_id = NULL WHERE persona_id = ?", (persona_id,))
            db.execute("DELETE FROM personas_sync WHERE persona_id = ?", (persona_id,))

    def synced(self) -> list[tuple[str, str, int, int]]:
        """(persona id, person id, wanted, done) of every twin made from this library."""
        with self.library.read() as db:
            rows = db.execute("SELECT persona_id, person_id, wanted, done FROM personas_sync").fetchall()
        return [(str(r[0]), str(r[1]), int(r[2]), int(r[3])) for r in rows]

    def wanted(self, persona_id: str) -> int | None:
        with self.library.read() as db:
            row = db.execute("SELECT wanted FROM personas_sync WHERE persona_id = ?", (persona_id,)).fetchone()
        return int(row[0]) if row else None

    def built(self, persona_id: str, version: int) -> bool:
        """A complete build of the sources written at ``version`` succeeded: open the twin if nothing changed
        since. False when a newer change is waiting, which needs another sync."""
        with self.library.transaction() as db:
            changed = db.execute(
                "UPDATE personas_sync SET done = ? WHERE persona_id = ? AND wanted = ?", (version, persona_id, version)
            ).rowcount
        return bool(changed)

    def sources(self, person_id: str, name: str) -> list[TwinSource]:
        """The twin sources of a person: one per recording where some speaker is confirmed as them, with every
        segment in transcript order (empty ones keep their number) so evidence cites (transcript, segment). The id
        changes with the transcript and with the set of the person's own segments, so a decision that moves one
        sentence from them to someone else drops every chunk and candidate built from the old set."""
        with self.library.read() as db:
            names = dict(db.execute("SELECT id, name FROM people").fetchall())
            rows = db.execute(
                "SELECT a.recording_id, a.transcript_id, a.speaker_id, a.decision, a.person_id FROM attributions a "
                "JOIN recordings r ON r.id = a.recording_id AND r.transcript_id = a.transcript_id "
                "WHERE a.recording_id IN (SELECT recording_id FROM attributions WHERE person_id = ? "
                "AND decision = 'confirmed')",
                (person_id,),
            ).fetchall()
        decided: dict[str, dict[str, tuple[str, str | None]]] = {}
        for recording_id, _, speaker_id, decision, owner in rows:
            decided.setdefault(recording_id, {})[speaker_id] = (decision, owner)
        parsed = []
        for recording_id, speakers in sorted(decided.items()):
            recording = self.library.get(recording_id)
            transcript = self.library.transcript(recording) if recording else None
            if recording is None or transcript is None:
                continue
            parsed.append(self._source(recording, transcript, speakers, person_id, name, names))
        return parsed

    @staticmethod
    def _source(
        recording: Recording,
        transcript: Transcript,
        speakers: dict[str, tuple[str, str | None]],
        person_id: str,
        name: str,
        names: dict[str, str],
    ) -> TwinSource:
        own = {sid for sid, (decision, owner) in speakers.items() if decision == "confirmed" and owner == person_id}
        others: dict[str, str] = {}
        for speaker in transcript.speakers:
            decision, owner = speakers.get(speaker.id, ("none", None))
            if speaker.id in own:
                continue
            if decision == "confirmed" and owner in names:
                others[speaker.id] = names[owner]
            else:
                others[speaker.id] = f"其他人{sum(1 for v in others.values() if v.startswith('其他人')) + 1}"
        lines = [
            (
                name if segment.speaker in own else others.get(segment.speaker, "其他人"),
                f"[{timestamp(segment.start)}] {' '.join(segment.text.split())}" if segment.text.strip() else "",
                segment.speaker in own,
            )
            for segment in transcript.segments
        ]
        mine = ",".join(str(i) for i, segment in enumerate(transcript.segments) if segment.speaker in own)
        digest = hashlib.sha256(f"{transcript.id}|{mine}".encode()).hexdigest()[:12]
        date = recording.creation_time or (found.isoformat() if (found := date_from_name(recording.filename)) else None)
        return TwinSource(
            source_id=f"{SOURCE_PREFIX}{recording.id}_{digest}",
            kind=recording.kind,
            title=recording.filename.rsplit(".", 1)[0],
            origin=f"录音库：{recording.filename}",
            duration_s=recording.duration_s,
            date=date,
            lines=lines,
        )
