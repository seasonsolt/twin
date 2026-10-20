"""People in the team's recording library: who each speaker is, how a speaker is matched to a person, and the
twin sources that follow from those decisions.

Whoever decides about a recording (its uploader, or an administrator; ``web.library``) is "the owner" below. A
person may only speak for themselves: say a voice is theirs (``web.voice``), or that a speaker given to them is not
(``dispute``), which undoes it and leaves it for the owner to settle.

The owner decides; matching proposes, and decides by itself only where the voice leaves no doubt (``classify``): a
speaker whose voice is very close to one person's samples is taken to be that person, and a long voice matching
nobody becomes a new unnamed person. Either is marked automatic and undone by any decision of the owner, after which
that speaker is never classified again. A person is recognised by voice samples (the centroids of speakers the owner
confirmed *and* chose as samples, and the voice an unnamed person was made from), and candidates are computed when
asked, never stored, so nothing goes stale. Every decision raises the recording's ``revision`` (a page holding an
older one is refused) and the ``wanted`` version of every twin that had or now has a speaker in that recording, in
the same transaction: those twins stay closed until a build of exactly that state completes (see ``Team.built``).
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
Gender = Literal["", "male", "female"]
Decision = Literal["none", "confirmed", "unknown", "mixed"]
# A speaker is offered for review from this similarity to someone's voice samples: in AliMeeting calibration of the
# single-person claim, people absent from a meeting never passed 0.44. The pilot recalibrates it.
SHOW = 0.45
# Candidates closer than this are shown together as "close, tell them apart".
NEAR = 0.05
# A speaker is taken to be someone without asking only this close to the person's samples, this much closer than to
# anyone else, and after speaking this long (a short speaker's voiceprint is unsteady). Conservative until the pilot
# calibrates them.
AUTO = 0.75
AUTO_MARGIN = 0.15
AUTO_MIN_SECONDS = 20.0
# A voice matching nobody becomes a new unnamed person after speaking this long; shorter ones wait for the owner.
NEW_MIN_SECONDS = 60.0
UNNAMED = "未命名"
# Undecided speakers of different recordings are offered as one voice from this similarity to the voice's centroid,
# so the owner settles a colleague once instead of once per meeting (``Team.voices``). Above ``SHOW``: a group is
# confirmed as a whole, and a wrong one would give someone else's words to a twin.
GROUP = 0.6
# A voice heard this little in all, and like nobody, is a fragment: offered together with the others, to set aside.
FRAGMENT_SECONDS = 15.0
# Twin sources made from the library; the rest of the id names the recording and the person's own segments.
SOURCE_PREFIX = "src_lib_"


class Stale(Exception):
    """The page decided on an older transcript or revision of the recording."""


class Person(BaseModel):
    id: str
    name: str
    persona_id: str | None = None
    created_at: str
    # Made from a voice that matched nobody, not named yet.
    auto: bool = False
    gender: Gender = ""
    # The account (``owner_key``) of the person themselves, once they said a voice is theirs.
    account: str | None = None
    speakers: int = 0
    seconds: float = 0
    samples: int = 0
    # A recording the person speaks in, and their speaker there, to hear them.
    recording_id: str | None = None
    speaker_id: str | None = None


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
    # The decision was taken by voice alone (``Team.classify``).
    auto: bool = False
    # The person it was given to said it is not them; it waits for the owner (``dispute``).
    disputed: bool = False
    candidates: list[Candidate] = []
    near: bool = False


class VoiceMember(BaseModel):
    """One undecided speaker of a voice heard across recordings."""

    recording_id: str
    filename: str
    transcript_id: str
    speaker_id: str
    seconds: float


class Voice(BaseModel):
    """Undecided speakers of several recordings who sound like one person (``Team.voices``), longest first."""

    id: str
    members: list[VoiceMember]
    seconds: float
    candidates: list[Candidate] = []
    near: bool = False


class OpenVoice(BaseModel):
    """A speaker nobody has said who they are (``Team.open_voices``)."""

    recording: Recording
    speaker_id: str
    seconds: float
    embedding: list[float]
    # The unnamed person the voice was taken for without asking, if any.
    person_id: str | None = None


def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat()


def _unit(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vector)) or 1.0
    return [x / norm for x in vector]


def _cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        return 0.0
    return sum(x * y for x, y in zip(_unit(a), _unit(b), strict=True))


def cosine(a: list[float], b: list[float]) -> float:
    """How alike two voiceprints are, from -1 to 1 (0 for prints of different models)."""
    return _cosine(a, b)


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
        heard_in: dict[str, tuple[str, str]] = {}
        for person_id, recording_id, _, speaker_id in confirmed:
            if recording_id not in heard:
                recording = self.library.get(recording_id)
                heard[recording_id] = (self.library.speakers(recording) if recording else None) or ()
            speaker = next((s for s in heard[recording_id] if s.id == speaker_id), None)
            counts[person_id] = counts.get(person_id, 0) + 1
            seconds[person_id] = seconds.get(person_id, 0) + (speaker.seconds if speaker else 0)
            heard_in.setdefault(person_id, (recording_id, speaker_id))
        for person in people:
            person.recording_id, person.speaker_id = heard_in.get(person.id, (None, None))
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
            return self._add_person(db, name)

    @staticmethod
    def _add_person(db: sqlite3.Connection, name: str, auto: bool = False) -> Person:
        if db.execute("SELECT 1 FROM people WHERE name = ?", (name,)).fetchone():
            raise ValueError(f"已经有叫「{name}」的人")
        person = Person(id="per_" + uuid.uuid4().hex[:12], name=name, created_at=_now(), auto=auto)
        db.execute(
            "INSERT INTO people (id, name, persona_id, created_at, auto) VALUES (?, ?, NULL, ?, ?)",
            (person.id, person.name, person.created_at, int(auto)),
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
            self._forget(db, person_id)
        return True

    @staticmethod
    def _forget(db: sqlite3.Connection, person_id: str) -> None:
        touched = db.execute(
            "SELECT DISTINCT recording_id FROM attributions WHERE person_id = ?", (person_id,)
        ).fetchall()
        for (recording_id,) in touched:
            Team._reopen(db, recording_id, {person_id})
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

    def prune(self) -> bool:
        """Forget unnamed people no current transcript has them speaking any more (the owner gave their voice to
        someone else, or the recording is gone): an empty "who is this" would stay in the owner's queue forever.
        Returns whether anyone was forgotten."""
        with self.library.transaction() as db:
            return self._prune(db)

    @staticmethod
    def _prune(db: sqlite3.Connection) -> bool:
        empty = [
            row[0]
            for row in db.execute(
                "SELECT p.id FROM people p WHERE p.auto = 1 AND p.persona_id IS NULL AND NOT EXISTS ("
                "SELECT 1 FROM attributions a JOIN recordings r ON r.id = a.recording_id "
                "AND r.transcript_id = a.transcript_id WHERE a.person_id = p.id AND a.decision = 'confirmed')"
            )
        ]
        for person_id in empty:
            Team._forget(db, person_id)
        return bool(empty)

    def set_gender(self, person_id: str, gender: Gender) -> str | None:
        """Record whether the person is a man or a woman (or unsaid); returns their twin's id, if any. Sources do
        not mention it, so no twin is rebuilt."""
        with self.library.transaction() as db:
            row = db.execute("SELECT persona_id FROM people WHERE id = ?", (person_id,)).fetchone()
            if row is None:
                raise ValueError("找不到这个人")
            db.execute("UPDATE people SET gender = ? WHERE id = ?", (gender, person_id))
            return str(row[0]) if row[0] else None

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
                auto=bool(row["auto"]) if row else False,
                disputed=bool(row["disputed"]) if row else False,
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
                "INSERT OR REPLACE INTO attributions (recording_id, transcript_id, speaker_id, decision, person_id, "
                "rejected, updated_at, auto) VALUES (?, ?, ?, ?, ?, ?, ?, 0)",
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
                self._prune(db)
            db.execute("UPDATE recordings SET revision = revision + 1 WHERE id = ?", (recording_id,))
            return int(revision + 1)

    def rename(self, person_id: str, name: str) -> str | None:
        """Name a person (an unnamed one stops being automatic); returns their twin's id, if any. Everyone who
        speaks with them is rebuilt, since their sources call the person by name."""
        name = " ".join(name.split())
        if not name:
            raise ValueError("名字不能为空")
        with self.library.transaction() as db:
            row = db.execute("SELECT persona_id FROM people WHERE id = ?", (person_id,)).fetchone()
            if row is None:
                raise ValueError("找不到这个人")
            if db.execute("SELECT 1 FROM people WHERE name = ? AND id != ?", (name, person_id)).fetchone():
                raise ValueError(f"已经有叫「{name}」的人")
            db.execute("UPDATE people SET name = ?, auto = 0 WHERE id = ?", (name, person_id))
            together = {
                r[0]
                for r in db.execute(
                    "SELECT DISTINCT b.person_id FROM attributions a JOIN attributions b "
                    "ON b.recording_id = a.recording_id AND b.decision = 'confirmed' "
                    "WHERE a.person_id = ? AND a.decision = 'confirmed'",
                    (person_id,),
                )
            }
            self._bump(db, together | {person_id})
            return str(row[0]) if row[0] else None

    def resolve(self, person_id: str, into: str | None) -> None:
        """Settle an unnamed person as the owner heard them: someone already known (``into``), whose voice samples
        they bring along, or nobody known (``None``). Their speakers count as the owner's decisions, and the unnamed
        person is forgotten. ``ValueError`` for a named or unknown person, or an unknown ``into``."""
        with self.library.transaction() as db:
            row = db.execute("SELECT auto FROM people WHERE id = ?", (person_id,)).fetchone()
            if row is None or not row["auto"]:
                raise ValueError("只能处理还没起名的声音")
            if into is not None and (
                into == person_id or not db.execute("SELECT 1 FROM people WHERE id = ?", (into,)).fetchone()
            ):
                raise ValueError("找不到这个人")
            heard = [
                r[0]
                for r in db.execute(
                    "SELECT DISTINCT recording_id FROM attributions WHERE person_id = ? AND decision = 'confirmed'",
                    (person_id,),
                )
            ]
            if into is not None:
                db.execute(
                    "UPDATE attributions SET person_id = ?, auto = 0, updated_at = ? "
                    "WHERE person_id = ? AND decision = 'confirmed'",
                    (into, _now(), person_id),
                )
                db.execute("UPDATE voiceprints SET person_id = ? WHERE person_id = ?", (into, person_id))
            else:
                db.execute(
                    "UPDATE attributions SET decision = 'unknown', person_id = NULL, auto = 0, updated_at = ? "
                    "WHERE person_id = ? AND decision = 'confirmed'",
                    (_now(), person_id),
                )
            for recording_id in heard:
                self._reopen(db, recording_id, {into} if into else set())
                db.execute("UPDATE recordings SET revision = revision + 1 WHERE id = ?", (recording_id,))
            self._forget(db, person_id)

    def classify(self, recording_id: str) -> bool:
        """Decide the recording's untouched speakers where the voice leaves no doubt: very close to one person's
        samples (``AUTO``), or, for a long voice matching nobody, a new unnamed person kept by that voice. Returns
        whether anything was decided. A speaker the owner has acted on is never classified, and a match adds no
        voice sample, so mistakes do not spread."""
        recording = self.library.get(recording_id)
        if recording is None or recording.status != "ready" or recording.transcript_id is None:
            return False
        speakers = self.library.speakers(recording) or ()
        with self.library.transaction() as db:
            current = db.execute("SELECT transcript_id FROM recordings WHERE id = ?", (recording_id,)).fetchone()
            if current is None or current[0] != recording.transcript_id:
                return False
            touched = {
                row[0]
                for row in db.execute(
                    "SELECT speaker_id FROM attributions WHERE recording_id = ? AND transcript_id = ?",
                    (recording_id, recording.transcript_id),
                )
            }
            prints = self._prints(db)
            decided: set[str] = set()
            # Longest first: their voiceprints are the steadiest, and a new person is made from the clearest voice.
            for speaker in sorted(speakers, key=lambda s: -s.seconds):
                if speaker.id in touched or not speaker.embedding:
                    continue
                candidates = self._match(speaker.embedding, prints, set())
                if candidates:
                    best, runner = candidates[0], candidates[1].score if len(candidates) > 1 else 0.0
                    if best.score < AUTO or best.score - runner < AUTO_MARGIN or speaker.seconds < AUTO_MIN_SECONDS:
                        continue
                    person_id = best.person_id
                elif speaker.seconds >= NEW_MIN_SECONDS:
                    person = self._add_person(db, self._unnamed(db), auto=True)
                    person_id = person.id
                    db.execute(
                        "INSERT INTO voiceprints (person_id, recording_id, transcript_id, speaker_id, embedding, "
                        "active, created_at) VALUES (?, ?, ?, ?, ?, 1, ?)",
                        (
                            person_id,
                            recording_id,
                            recording.transcript_id,
                            speaker.id,
                            json.dumps(speaker.embedding),
                            _now(),
                        ),
                    )
                    prints.append((person_id, person.name, speaker.embedding))
                else:
                    continue
                db.execute(
                    "INSERT INTO attributions (recording_id, transcript_id, speaker_id, decision, person_id, "
                    "rejected, updated_at, auto) VALUES (?, ?, ?, 'confirmed', ?, '[]', ?, 1)",
                    (recording_id, recording.transcript_id, speaker.id, person_id, _now()),
                )
                decided.add(person_id)
            if not decided:
                return False
            self._reopen(db, recording_id, decided)
            db.execute("UPDATE recordings SET revision = revision + 1 WHERE id = ?", (recording_id,))
            return True

    def classify_all(self) -> bool:
        """``classify`` every transcribed recording, as after someone's voice samples changed."""
        changed = False
        for recording in self.library.list():
            changed = self.classify(recording.id) or changed
        return changed

    @staticmethod
    def _unnamed(db: sqlite3.Connection) -> str:
        taken = {row[0] for row in db.execute("SELECT name FROM people WHERE name LIKE ?", (UNNAMED + " %",))}
        n = 1
        while f"{UNNAMED} {n}" in taken:
            n += 1
        return f"{UNNAMED} {n}"

    def identities(self) -> dict[str, tuple[list[str], int]]:
        """Per recording, the people its current transcript is attributed to (by name, in speaking order of their
        first speaker) and how many of its speakers are settled (someone, nobody known, or several people)."""
        found: dict[str, tuple[list[str], int]] = {}
        with self.library.read() as db:
            for row in db.execute(
                "SELECT a.recording_id, a.decision, p.name FROM attributions a "
                "JOIN recordings r ON r.id = a.recording_id AND r.transcript_id = a.transcript_id "
                "LEFT JOIN people p ON p.id = a.person_id AND a.decision = 'confirmed' "
                "WHERE a.decision != 'none' ORDER BY a.recording_id, a.speaker_id"
            ):
                names, settled = found.get(row["recording_id"], ([], 0))
                if row["name"] and row["name"] not in names:
                    names.append(row["name"])
                found[row["recording_id"]] = (names, settled + 1)
        return found

    def review(self, recordings: set[str] | None = None) -> list[dict[str, object]]:
        """The owner's confirmation queue: speakers someone said are not them, then undecided speakers whose voice
        matches someone, best match first. ``recordings``: only these."""
        queue: list[dict[str, object]] = []
        for recording in self.library.list():
            if recording.status != "ready" or (recordings is not None and recording.id not in recordings):
                continue
            for speaker in self.speakers(recording):
                if speaker.decision == "none" and (speaker.candidates or speaker.disputed):
                    queue.append(
                        {
                            "recording_id": recording.id,
                            "filename": recording.filename,
                            "transcript_id": recording.transcript_id,
                            "revision": recording.revision,
                            **speaker.model_dump(),
                        }
                    )
        queue.sort(
            key=lambda entry: (
                not entry["disputed"],
                -(entry["candidates"][0]["score"] if entry["candidates"] else 0),  # type: ignore[index]
            )
        )
        return queue

    def voices(self, recordings: set[str] | None = None) -> tuple[list[Voice], list[Voice]]:
        """The undecided speakers of transcribed recordings, grouped by voice across recordings so a colleague heard
        in many meetings is asked about once: (voices, fragments). Longest speakers seed the groups, their
        voiceprints being the steadiest; each later one joins the voice whose centroid it is closest to from
        ``GROUP``, never one already speaking in its recording (diarization told them apart there). Fragments are
        voices heard less than ``FRAGMENT_SECONDS`` and like nobody, which the owner can only set aside. Speakers
        someone disputed wait apart (``review``); those without a voiceprint wait in their recording.
        ``recordings``: only these."""
        with self.library.read() as db:
            rows = {
                (row["recording_id"], row["speaker_id"]): row
                for row in db.execute(
                    "SELECT a.recording_id, a.speaker_id, a.decision, a.rejected, a.disputed FROM attributions a "
                    "JOIN recordings r ON r.id = a.recording_id AND r.transcript_id = a.transcript_id"
                )
            }
            prints = self._prints(db)
        found: list[tuple[VoiceMember, list[float], set[str]]] = []
        for recording in self.library.list():
            if recording.status != "ready" or recording.transcript_id is None:
                continue
            if recordings is not None and recording.id not in recordings:
                continue
            for speaker in self.library.speakers(recording) or ():
                row = rows.get((recording.id, speaker.id))
                if not speaker.embedding or (row is not None and (row["decision"] != "none" or row["disputed"])):
                    continue
                member = VoiceMember(
                    recording_id=recording.id,
                    filename=recording.filename,
                    transcript_id=recording.transcript_id,
                    speaker_id=speaker.id,
                    seconds=round(speaker.seconds, 1),
                )
                found.append((member, _unit(speaker.embedding), set(json.loads(row["rejected"])) if row else set()))
        groups: list[tuple[list[VoiceMember], list[float], set[str]]] = []
        for member, vector, rejected in sorted(found, key=lambda f: (-f[0].seconds, f[0].recording_id)):
            best, best_score = None, GROUP
            for group in groups:
                if any(m.recording_id == member.recording_id for m in group[0]):
                    continue
                score = _cosine(vector, group[1])
                if score >= best_score:
                    best, best_score = group, score
            if best is None:
                groups.append(([member], list(vector), set(rejected)))
            else:
                best[0].append(member)
                best[1][:] = [a + b for a, b in zip(best[1], vector, strict=True)]
                best[2].update(rejected)
        voices: list[Voice] = []
        fragments: list[Voice] = []
        for members, centroid, rejected in groups:
            key = "|".join(sorted(f"{m.recording_id}:{m.transcript_id}:{m.speaker_id}" for m in members))
            candidates = self._match(centroid, prints, rejected)
            voice = Voice(
                id="voice_" + hashlib.sha256(key.encode()).hexdigest()[:12],
                members=members,
                seconds=round(sum(m.seconds for m in members), 1),
                candidates=candidates,
                near=len(candidates) > 1 and candidates[0].score - candidates[1].score < NEAR,
            )
            (fragments if voice.seconds < FRAGMENT_SECONDS and not candidates else voices).append(voice)
        voices.sort(key=lambda v: (-v.seconds, v.id))
        return voices, fragments

    def decide_voice(
        self,
        members: list[tuple[str, str, str]],
        action: Literal["confirm", "unknown"],
        person_id: str | None = None,
    ) -> None:
        """Settle every (recording, transcript, speaker) of a voice at once: as ``person_id``, keeping the longest
        one as their voice sample so later recordings are recognised, or as nobody known. ``Stale`` when any of
        them has another transcript now or was decided meanwhile (the page shows an old grouping); ``ValueError``
        for an unknown speaker or person."""
        if action == "confirm" and not person_id:
            raise ValueError("需要指定是谁")
        heard: list[tuple[str, str, Speaker]] = []
        for recording_id, transcript_id, speaker_id in dict.fromkeys(members):
            recording = self.library.get(recording_id)
            spoken = (self.library.speakers(recording) if recording else None) or ()
            speaker = next((s for s in spoken if s.id == speaker_id), None)
            if speaker is None:
                raise ValueError("这段录音里没有这个说话人")
            heard.append((recording_id, transcript_id, speaker))
        if not heard:
            raise ValueError("没有要确认的声音")
        owner = person_id if action == "confirm" else None
        decision: Decision = "confirmed" if action == "confirm" else "unknown"
        with self.library.transaction() as db:
            if owner and not db.execute("SELECT 1 FROM people WHERE id = ?", (owner,)).fetchone():
                raise ValueError("找不到这个人")
            for recording_id, transcript_id, speaker in heard:
                current = db.execute("SELECT transcript_id FROM recordings WHERE id = ?", (recording_id,)).fetchone()
                row = db.execute(
                    "SELECT decision, rejected FROM attributions WHERE recording_id = ? AND transcript_id = ? "
                    "AND speaker_id = ?",
                    (recording_id, transcript_id, speaker.id),
                ).fetchone()
                if current is None or current[0] != transcript_id or (row is not None and row[0] != "none"):
                    raise Stale()
                rejected = [p for p in json.loads(row[1]) if p != owner] if row else []
                db.execute(
                    "INSERT OR REPLACE INTO attributions (recording_id, transcript_id, speaker_id, decision, "
                    "person_id, rejected, updated_at, auto) VALUES (?, ?, ?, ?, ?, ?, ?, 0)",
                    (recording_id, transcript_id, speaker.id, decision, owner, json.dumps(rejected), _now()),
                )
            longest = max(heard, key=lambda h: h[2].seconds)
            if owner and longest[2].embedding:
                db.execute(
                    "INSERT INTO voiceprints (person_id, recording_id, transcript_id, speaker_id, embedding, "
                    "active, created_at) VALUES (?, ?, ?, ?, ?, 1, ?)",
                    (owner, longest[0], longest[1], longest[2].id, json.dumps(longest[2].embedding), _now()),
                )
            for recording_id in sorted({h[0] for h in heard}):
                if owner:
                    self._reopen(db, recording_id, {owner})
                db.execute("UPDATE recordings SET revision = revision + 1 WHERE id = ?", (recording_id,))

    def attendance(self) -> dict[str, set[str]]:
        """Per recording, the people a speaker of its current transcript is confirmed as: who was there."""
        found: dict[str, set[str]] = {}
        with self.library.read() as db:
            for recording_id, person_id in db.execute(
                "SELECT a.recording_id, a.person_id FROM attributions a "
                "JOIN recordings r ON r.id = a.recording_id AND r.transcript_id = a.transcript_id "
                "WHERE a.decision = 'confirmed'"
            ):
                found.setdefault(recording_id, set()).add(person_id)
        return found

    def dispute(self, recording_id: str, speaker_id: str, people: set[str]) -> str:
        """One of ``people`` (all the same human) says the speaker given to them is not them: the speaker is
        undone, never given to them again by voice, and marked for the owner to settle. Returns whom it was given
        to; ``ValueError`` when it was not given to any of them."""
        recording = self.library.get(recording_id)
        if recording is None or recording.transcript_id is None:
            raise ValueError("找不到这段录音的转写")
        with self.library.read() as db:
            row = db.execute(
                "SELECT person_id FROM attributions WHERE recording_id = ? AND transcript_id = ? AND speaker_id = ? "
                "AND decision = 'confirmed'",
                (recording_id, recording.transcript_id, speaker_id),
            ).fetchone()
        if row is None or row[0] not in people:
            raise ValueError("这段话没有记在你名下")
        person_id = str(row[0])
        try:
            self.decide(recording_id, recording.transcript_id, recording.revision, speaker_id, "reject", person_id)
        except Stale:
            raise ValueError("这段录音刚被修改过，请刷新后再试") from None
        with self.library.transaction() as db:
            db.execute(
                "UPDATE attributions SET disputed = 1 WHERE recording_id = ? AND transcript_id = ? AND speaker_id = ?",
                (recording_id, recording.transcript_id, speaker_id),
            )
        return person_id

    def set_account(self, person_id: str, account: str) -> None:
        """Note that the person is the human signed in as ``account``."""
        with self.library.transaction() as db:
            db.execute("UPDATE people SET account = ? WHERE id = ?", (account, person_id))

    def merge(self, person_id: str, into: str) -> None:
        """Take ``person_id`` and ``into`` for one person, as an administrator heard them: every speaker and voice
        sample of ``person_id`` becomes ``into``'s and ``person_id`` is forgotten. ``ValueError`` when either is
        unknown, or ``person_id`` has a twin of its own (delete or keep it first)."""
        with self.library.transaction() as db:
            rows = {r["id"]: r for r in db.execute("SELECT * FROM people WHERE id IN (?, ?)", (person_id, into))}
            if person_id == into or len(rows) != 2:
                raise ValueError("找不到这个人")
            if rows[person_id]["persona_id"]:
                raise ValueError(f"「{rows[person_id]['name']}」已经有分身，请先删除分身再合并")
            heard = [
                r[0]
                for r in db.execute(
                    "SELECT DISTINCT recording_id FROM attributions WHERE person_id = ? AND decision = 'confirmed'",
                    (person_id,),
                )
            ]
            db.execute(
                "UPDATE attributions SET person_id = ?, updated_at = ? WHERE person_id = ? AND decision = 'confirmed'",
                (into, _now(), person_id),
            )
            db.execute("UPDATE voiceprints SET person_id = ? WHERE person_id = ?", (into, person_id))
            if rows[person_id]["account"] and not rows[into]["account"]:
                db.execute("UPDATE people SET account = ? WHERE id = ?", (rows[person_id]["account"], into))
            if rows[person_id]["gender"] and not rows[into]["gender"]:
                db.execute("UPDATE people SET gender = ? WHERE id = ?", (rows[person_id]["gender"], into))
            for recording_id in heard:
                self._reopen(db, recording_id, {into})
                db.execute("UPDATE recordings SET revision = revision + 1 WHERE id = ?", (recording_id,))
            # Everyone who spoke with them calls them by the kept name now.
            self._bump(db, {into})
            self._forget(db, person_id)

    def similar(self) -> list[tuple[str, str]]:
        """Pairs of people who may be one (``media.merge`` found them under the same name in two libraries)."""
        with self.library.read() as db:
            return [(str(r[0]), str(r[1])) for r in db.execute("SELECT person_id, other_id FROM similar_people")]

    def add_similar(self, person_id: str, other_id: str) -> None:
        with self.library.transaction() as db:
            db.execute(
                "INSERT OR IGNORE INTO similar_people (person_id, other_id, created_at) VALUES (?, ?, ?)",
                (person_id, other_id, _now()),
            )

    def keep_apart(self, person_id: str, other_id: str) -> None:
        """They are two people after all."""
        with self.library.transaction() as db:
            db.execute(
                "DELETE FROM similar_people WHERE (person_id = ? AND other_id = ?) OR (person_id = ? AND other_id = ?)",
                (person_id, other_id, other_id, person_id),
            )

    def open_voices(self) -> list[OpenVoice]:
        """Speakers of current transcripts whom nobody has said who they are, with a voiceprint: undecided ones,
        and those taken by voice alone for an unnamed person who has no twin (``person_id``). What a colleague who
        recorded their own voice may be offered to recognise themselves by (``web.voice``)."""
        with self.library.read() as db:
            rows = {
                (row["recording_id"], row["speaker_id"]): row
                for row in db.execute(
                    "SELECT a.recording_id, a.speaker_id, a.decision, a.person_id, a.auto FROM attributions a "
                    "JOIN recordings r ON r.id = a.recording_id AND r.transcript_id = a.transcript_id"
                )
            }
            unnamed = {row[0] for row in db.execute("SELECT id FROM people WHERE auto = 1 AND persona_id IS NULL")}
        found = []
        for recording in self.library.list():
            if recording.status != "ready" or recording.transcript_id is None:
                continue
            for speaker in self.library.speakers(recording) or ():
                if not speaker.embedding:
                    continue
                row = rows.get((recording.id, speaker.id))
                if row is None or row["decision"] == "none":
                    person_id = None
                elif row["decision"] == "confirmed" and row["auto"] and row["person_id"] in unnamed:
                    person_id = row["person_id"]
                else:
                    continue
                found.append(
                    OpenVoice(
                        recording=recording,
                        speaker_id=speaker.id,
                        seconds=speaker.seconds,
                        embedding=speaker.embedding,
                        person_id=person_id,
                    )
                )
        return found

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
        Team._bump(db, speaking | people)

    @staticmethod
    def _bump(db: sqlite3.Connection, people: set[str]) -> None:
        affected = sorted(people)
        if affected:
            db.execute(
                f"UPDATE personas_sync SET wanted = wanted + 1 WHERE person_id IN ({','.join('?' * len(affected))})",
                affected,
            )

    def proofread(self, recording_id: str, transcript_id: str, changed: bool) -> bool:
        """Note that the recording's transcript was proofread; when its words changed, close the twins of everyone
        identified in it, in the same transaction, so they are rebuilt from the corrected words. False when the
        recording is gone or has another transcript now."""
        with self.library.transaction() as db:
            updated = db.execute(
                "UPDATE recordings SET proofread = ? WHERE id = ? AND transcript_id = ?",
                (transcript_id, recording_id, transcript_id),
            ).rowcount
            if updated and changed:
                self._reopen(db, recording_id, set())
            return bool(updated)

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
            # The model's proofreading where there is one: the person's words as corrected.
            transcript = self.library.cleaned(recording) if recording else None
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
