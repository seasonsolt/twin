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
import operator
import sqlite3
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

from ..util import date_from_name
from .collector import ATTRIBUTION_VERSION, CLEANUP_VERSION, LEGACY_ATTRIBUTION
from .cues import Cue
from .ingest import Segment, Speaker, timestamp
from .library import Library, Recording, Transcript

Action = Literal["confirm", "unknown", "mixed", "reject", "clear"]
# How sure voice alone is of a speaker (``tier``): decided without asking, offered to confirm with one key, asked.
Tier = Literal["high", "mid", "low"]
Gender = Literal["", "male", "female"]
Decision = Literal["none", "confirmed", "unknown", "mixed"]
# A speaker is offered for review from this similarity to someone's voice samples: in AliMeeting calibration of the
# single-person claim, people absent from a meeting never passed 0.44. The pilot recalibrates it.
SHOW = 0.45
# Someone is suggested for a speaker only from this similarity. Below it the nearest known voice was nearly never the
# speaker on the pilot library (42 meetings of 20 people, 17 of them known): most of a large meeting's speakers are not
# known yet, and the closest of the known is merely the closest. ``SHOW`` still decides whether a voice matches nobody.
SUGGEST = 0.6
# From here a suggestion is what the owner answers by pressing Enter: on the pilot library every confirmed speaker this
# close to someone's samples was that person.
SURE = 0.75
# Two speakers of one recording this alike are one person the diarization split in two: split halves on the pilot
# library were 0.73-0.85 alike, different people of one meeting never this alike.
SPLIT = 0.75
# Candidates closer than this are shown together as "close, tell them apart".
NEAR = 0.05
# A speaker is taken to be someone without asking only this close to the person's samples, this much closer than to
# anyone else (the runner-up, people or voices the owner could not name: ``STRANGER_RIVALS``), and after speaking this
# long (a short speaker's voiceprint is unsteady). Calibrated on daw's team library split by person (docs/ASR_EVAL.md,
# attribution-v2): only the lead mattered; a lead of 0.15 left 75-88% of named people's speech to the owner, 0.1 with
# strangers as rivals took 8.1% others' speech on the held-out half (9.8% before) and left 58%.
AUTO = 0.6
AUTO_MARGIN = 0.1
AUTO_MIN_SECONDS = 20.0
# The middle tier (``tier``, docs/PLAN_VOICE_COLLECTOR.md): not sure enough to decide alone, but the best candidate
# leads the runner-up by ``MID_MARGIN`` from ``MID_FLOOR``, so the owner is offered them to confirm with one key. On
# daw about 60% of such suggestions were right: too few to give a twin the speech before the owner confirms.
MID_MARGIN = 0.05
MID_FLOOR = 0.45
# 1: voices the owner said are nobody they know, in other recordings (``_strangers``), are rivals too: the best person
# must lead the closest of them as well. Without it a lead of 0.1 took 21% others' speech on daw's held-out half,
# most of it voices the owner could not name.
STRANGER_RIVALS = 1.0
# A voice is one the owner said is nobody they know (``_stranger``) this close to it and this much closer than to
# anyone known: such voices came back meeting after meeting on the pilot library; two of 114 confirmed speakers would
# have passed for one.
STRANGER = 0.75
STRANGER_MARGIN = 0.15
# 1: a recording gives a person at most one speaker by voice alone (the longest), and their other speakers that sound
# like them wait as the middle tier. Off: on daw's team library split by person it only took fewer right claims.
ONE_PER_RECORDING = 0.0
# Which voice samples of a person are matched (``_prints``): at most ``SAMPLE_CAP`` of them (0: all), chosen by
# ``SAMPLE_PICK`` (0: the earliest, 1: from the longest speakers, 2: the most unlike each other, from the longest),
# and a person's score is the mean of their best ``SCORE_TOP`` samples. On daw neither a cap nor a mean did better
# than every sample and the best score (docs/ASR_EVAL.md).
SAMPLE_CAP = 0.0
SAMPLE_PICK = 0.0
SCORE_TOP = 1.0
# A voice matching nobody becomes a new unnamed person after speaking this long; shorter ones wait for the owner.
NEW_MIN_SECONDS = 60.0
UNNAMED = "未命名"
# Undecided speakers of different recordings are offered as one voice from this similarity to *every* speaker
# already in it, so the owner settles a colleague once instead of once per meeting (``Team.voices``). Above ``SHOW``: a
# group is confirmed as a whole, and a wrong one would give someone else's words to a twin. Matching a centroid
# instead let similar colleagues chain into one voice on the pilot library (27 meetings, four people).
GROUP = 0.6
# A voice heard this little in all is a fragment: offered together with the others, to set aside or to give in one
# click to the person it sounds like. Like someone or not: when a fragment that came to sound like the person just
# confirmed was asked about on its own, confirming one voice could leave more questions than before.
FRAGMENT_SECONDS = 15.0
# A voice settled as someone gives them up to this many voice samples, from different recordings: one sample of a
# person heard through varying rooms and microphones recognised none of the waiting speakers on the pilot library,
# a few per person recognised a fifth of the speech, all of it right. Besides the longest, only speakers this long.
# A recording gives a person one sample however many of its speakers are theirs (``Team._prints``): its speakers share
# a room and microphone, so a second sample from it adds no new room, only another chance for that room's other voices
# to sound like them. In a 13-speaker weekly meeting, each voice settled as one colleague added a sample, and the
# meeting's other voices, then that room's next meetings, drifted to whoever was settled most.
VOICE_SAMPLES = 3
SAMPLE_MIN_SECONDS = 60.0
# A voice sample stops standing for its person once the owner gave otherwise this many of the speakers it gave them by
# voice alone, and more than half of them (``Team.decide``): a sample from a room where others sound like the person
# draws those voices meeting after meeting (on daw 28% of samples were closer to someone else's sample than to any of
# their own person's). A guess until the track records on daw are counted; the claims it took go back to the owner.
RETIRE_CORRECTED = 3
# A person heard this long already has what a twin learns from; voices surely theirs wait behind the others. On the
# pilot library a third of the undecided speech was surely or likely someone already past it. A guess until twins built
# from more or less speech are compared.
ENOUGH_SECONDS = 1800.0
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
    # How much longer they would have to be heard to have what a twin learns from (``ENOUGH_SECONDS``).
    lacking: float = 0
    samples: int = 0
    # A recording the person speaks in, and their speaker there, to hear them: one of their voice samples when they
    # have one, the voice others are matched against.
    recording_id: str | None = None
    speaker_id: str | None = None
    # Speakers given to them by voice alone, which the owner may spot-check (``Team.checks``).
    checks: int = 0


class LastMeeting(BaseModel):
    """The latest meeting a person was heard in (``Team.last_meetings``)."""

    recording_id: str
    # The recording's file name without its extension.
    title: str
    # The day, as YYYY-MM-DD.
    date: str


class Check(BaseModel):
    """A speaker given to someone by voice alone, to spot-check (``Team.checks``)."""

    recording_id: str
    filename: str
    transcript_id: str
    revision: int
    speaker_id: str
    seconds: float
    # How sure voice alone was (``attributions.tier``), the best score and its lead; None when the review gave it
    # (``Team.reassign``) or before they were recorded.
    tier: str | None = None
    score: float | None = None
    lead: float | None = None


class VoiceSample(BaseModel):
    """One of a person's voice samples (``Team.samples``): where it was heard, how it was taken, how it fared."""

    id: int
    recording_id: str
    filename: str
    transcript_id: str
    speaker_id: str
    seconds: float
    source: str | None = None
    created_at: str
    # Speakers it gave the person by voice alone that still stand, and those the owner gave otherwise.
    claims: int = 0
    corrected: int = 0


class Candidate(BaseModel):
    person_id: str
    name: str
    score: float
    # Close enough to be the answer by default (``SURE``).
    sure: bool = False
    # Already speaking in the same recording, and this alike to them there: diarization split one person (``SPLIT``).
    split: bool = False
    # The meeting calls the speaker by this person's name (``media.cues``).
    called: bool = False


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
    # What the meeting calls the speaker, while undecided, and what was said that names them.
    called: str | None = None
    quote: str = ""


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
    # A member sounds like a voice the owner already said is nobody they know.
    stranger: bool = False
    # What the meeting calls its speakers, and what was said that names them.
    called: str | None = None
    quote: str = ""
    # How long the leading candidate is heard already, when they are surely the one; past ``ENOUGH_SECONDS`` the
    # voice waits behind the others.
    had: float = 0
    enough: bool = False
    # How sure voice alone is of the leading candidate (``tier``): "mid" is offered to confirm with one key. Never
    # "high": what voice alone takes is not asked about.
    tier: Tier = "low"


@dataclass
class _Group:
    """A voice being gathered by ``Team.voices``."""

    members: list[VoiceMember]
    vectors: list[list[float]]
    rejected: set[str]
    likely: str | None
    # People already confirmed in a member's recording: not who this voice is, unless it is their split half.
    present: set[str]
    split: Candidate | None
    stranger: bool
    # What the meeting calls its members, longest member first.
    cues: list[Cue]
    # Whom a member was given to by voice until its sample stopped standing (``Team._withdraw``).
    suggest: str | None = None


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


class _Print(list[float]):
    """A voiceprint that works out its unit vector once (``_unit``): a review compares every undecided speaker with
    every voice sample, and normalising both each time took most of its seconds."""

    __slots__ = ("unit",)

    def __init__(self, vector: Iterable[float]) -> None:
        super().__init__(vector)
        self.unit: list[float] | None = None


def _print(vector: list[float]) -> _Print:
    return vector if isinstance(vector, _Print) else _Print(vector)


def _unit(vector: list[float]) -> list[float]:
    if isinstance(vector, _Print) and vector.unit is not None:
        return vector.unit
    norm = math.sqrt(sum(x * x for x in vector)) or 1.0
    unit = [x / norm for x in vector]
    if isinstance(vector, _Print):
        vector.unit = unit
    return unit


def _cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        return 0.0
    return float(sum(map(operator.mul, _unit(a), _unit(b))))


def segment_owners(
    transcript: Transcript,
    speakers: Mapping[str, tuple[str, str | None]],
    fixes: Mapping[int, tuple[str, str, str | None]],
) -> list[str | None]:
    """Whose each segment is: its speaker's confirmed person, unless the owner left the segment out of that person
    (``exclude``: nobody's) or gave it to someone else (``move``) while the speaker was theirs (``media.review``)."""
    owners: list[str | None] = []
    for i, segment in enumerate(transcript.segments):
        decision, owner = speakers.get(segment.speaker, ("none", None))
        owner = owner if decision == "confirmed" else None
        fix = fixes.get(i)
        if owner and fix and fix[0] == owner and fix[1] in {"exclude", "move"}:
            owner = fix[2] if fix[1] == "move" else None
        owners.append(owner)
    return owners


def cosine(a: list[float], b: list[float]) -> float:
    """How alike two voiceprints are, from -1 to 1 (0 for prints of different models)."""
    return _cosine(a, b)


def _stale(row: Mapping[str, object]) -> bool:
    """Whether an attribution row is an automatic decision of ``Team.classify`` made under other rules than the
    current ones (``collector``). The review's own moves (``Team.reassign``, which name whom the speaker is not)
    belong to the cleanup layer, and the owner's decisions to no layer."""
    if not row["auto"] or row["decision"] != "confirmed":
        return False
    version = row["version"]
    if version is None:
        return row["rejected"] == "[]" and LEGACY_ATTRIBUTION != ATTRIBUTION_VERSION
    return str(version).startswith("attribution-") and version != ATTRIBUTION_VERSION


def tier(candidates: list[Candidate], runner: float, seconds: float) -> Tier:
    """How sure voice alone is of a speaker whose candidates (``Team._match``) are these and whose second most alike
    person scores ``runner`` (whoever it is, however low): "high" is taken without asking (``AUTO``, ``AUTO_MARGIN``,
    ``AUTO_MIN_SECONDS``), "mid" is offered to the owner to confirm (``MID_FLOOR``, ``MID_MARGIN``), "low" is asked."""
    if not candidates:
        return "low"
    best = candidates[0].score
    if best >= AUTO and best - runner >= AUTO_MARGIN and seconds >= AUTO_MIN_SECONDS:
        return "high"
    if best >= MID_FLOOR and best - runner >= MID_MARGIN:
        return "mid"
    return "low"


# A voice sample in ``Team._prints``: its recording, and its person, their name, the voiceprint and its speaker.
_Sample = tuple[str, tuple[str, str, list[float], str]]


def _unlike(samples: list[_Sample], cap: int) -> list[_Sample]:
    """``cap`` of a person's samples, longest first, each next one the most unlike those already chosen."""
    chosen = samples[:1]
    rest = samples[1:]
    while rest and len(chosen) < cap:
        far = min(rest, key=lambda item: max(_cosine(item[1][2], other[1][2]) for other in chosen))
        chosen.append(far)
        rest.remove(far)
    return chosen


class Team:
    def __init__(self, library: Library) -> None:
        self.library = library

    # ------------------------------------------------------------------ people

    def people(self) -> list[Person]:
        with self.library.read() as db:
            people = [Person.model_validate(dict(row)) for row in db.execute("SELECT * FROM people ORDER BY name")]
            samples = dict(
                db.execute(
                    "SELECT person_id, COUNT(DISTINCT recording_id) FROM voiceprints WHERE active = 1 "
                    "GROUP BY person_id"
                ).fetchall()
            )
            sampled = db.execute(
                "SELECT v.person_id, v.recording_id, v.speaker_id FROM voiceprints v "
                "JOIN recordings r ON r.id = v.recording_id AND r.transcript_id = v.transcript_id "
                "WHERE v.active = 1 ORDER BY v.rowid"
            ).fetchall()
            confirmed = db.execute(
                "SELECT a.person_id, a.recording_id, a.transcript_id, a.speaker_id, a.auto FROM attributions a "
                "JOIN recordings r ON r.id = a.recording_id AND r.transcript_id = a.transcript_id "
                "WHERE a.decision = 'confirmed'"
            ).fetchall()
        seconds: dict[str, float] = {}
        counts: dict[str, int] = {}
        heard: dict[str, tuple[Speaker, ...]] = {}
        heard_in: dict[str, tuple[str, str]] = {}
        checks: dict[str, int] = {}
        for person_id, recording_id, _, speaker_id, auto in confirmed:
            if auto:
                checks[person_id] = checks.get(person_id, 0) + 1
            if recording_id not in heard:
                recording = self.library.get(recording_id)
                heard[recording_id] = (self.library.speakers(recording) if recording else None) or ()
            speaker = next((s for s in heard[recording_id] if s.id == speaker_id), None)
            counts[person_id] = counts.get(person_id, 0) + 1
            seconds[person_id] = seconds.get(person_id, 0) + (speaker.seconds if speaker else 0)
            heard_in.setdefault(person_id, (recording_id, speaker_id))
        sample_in: dict[str, tuple[str, str]] = {}
        for person_id, recording_id, speaker_id in sampled:
            sample_in.setdefault(person_id, (recording_id, speaker_id))
        for person in people:
            voice = sample_in.get(person.id) or heard_in.get(person.id)
            person.recording_id, person.speaker_id = voice if voice else (None, None)
            person.samples = samples.get(person.id, 0)
            person.speakers = counts.get(person.id, 0)
            person.seconds = round(seconds.get(person.id, 0), 1)
            person.lacking = round(max(0.0, ENOUGH_SECONDS - person.seconds), 1)
            person.checks = checks.get(person.id, 0)
        return people

    def last_meetings(self, recordings: set[str] | None = None) -> dict[str, LastMeeting]:
        """The latest meeting each person was heard in (a speaker given to them, by the owner or by voice), by the
        day it took place: the recording's own creation time, else a date in its file name, else the day it was
        added. ``recordings``: only these, so a viewer is told of meetings they may see."""
        with self.library.read() as db:
            rows = db.execute(
                "SELECT DISTINCT a.person_id, r.id, r.filename, r.creation_time, r.created_at FROM attributions a "
                "JOIN recordings r ON r.id = a.recording_id AND r.transcript_id = a.transcript_id "
                "WHERE a.decision = 'confirmed' AND a.person_id IS NOT NULL"
            ).fetchall()
        latest: dict[str, LastMeeting] = {}
        for row in rows:
            if recordings is not None and row["id"] not in recordings:
                continue
            named = date_from_name(row["filename"])
            day = (row["creation_time"] or (named.isoformat() if named else None) or row["created_at"] or "")[:10]
            if not day:
                continue
            meeting = LastMeeting(recording_id=row["id"], title=row["filename"].rsplit(".", 1)[0], date=day)
            held = latest.get(row["person_id"])
            if held is None or (meeting.date, meeting.recording_id) > (held.date, held.recording_id):
                latest[row["person_id"]] = meeting
        return latest

    def checks(self, person_id: str, recordings: set[str] | None = None) -> list[Check]:
        """The speakers given to the person by voice alone, the least sure first (the smallest lead over the
        runner-up; those the review gave, with no lead, before them), the longest first among equals: the most
        likely mistakes, to hear first. ``recordings``: only these."""
        with self.library.read() as db:
            rows = db.execute(
                "SELECT a.recording_id, a.transcript_id, a.speaker_id, a.tier, a.score, a.lead, r.filename, r.revision "
                "FROM attributions a JOIN recordings r ON r.id = a.recording_id AND r.transcript_id = a.transcript_id "
                "WHERE a.person_id = ? AND a.decision = 'confirmed' AND a.auto = 1",
                (person_id,),
            ).fetchall()
        found = []
        for row in rows:
            if recordings is not None and row["recording_id"] not in recordings:
                continue
            found.append(
                Check(
                    recording_id=row["recording_id"],
                    filename=row["filename"],
                    transcript_id=row["transcript_id"],
                    revision=row["revision"],
                    speaker_id=row["speaker_id"],
                    seconds=round(self._seconds(row["recording_id"], row["speaker_id"]), 1),
                    tier=row["tier"],
                    score=row["score"],
                    lead=row["lead"],
                )
            )
        return sorted(found, key=lambda c: (c.lead if c.lead is not None else -1.0, -c.seconds, c.recording_id))

    def check_counts(self, recordings: set[str]) -> dict[str, int]:
        """How many speakers in these recordings each person was given by voice alone (``checks``)."""
        with self.library.read() as db:
            rows = db.execute(
                "SELECT a.person_id, a.recording_id FROM attributions a JOIN recordings r ON r.id = a.recording_id "
                "AND r.transcript_id = a.transcript_id WHERE a.decision = 'confirmed' AND a.auto = 1"
            ).fetchall()
        found: dict[str, int] = {}
        for person_id, recording_id in rows:
            if recording_id in recordings:
                found[person_id] = found.get(person_id, 0) + 1
        return found

    def samples(self, person_id: str, recordings: set[str] | None = None) -> list[VoiceSample]:
        """The person's voice samples that stand, the earliest first, each with what it gave them by voice alone.
        ``recordings``: only these."""
        with self.library.read() as db:
            rows = db.execute(
                "SELECT v.id, v.recording_id, v.transcript_id, v.speaker_id, v.source, v.created_at, v.corrected, "
                "r.filename, (SELECT COUNT(*) FROM attributions a WHERE a.sample = v.id AND a.auto = 1 "
                "AND a.decision = 'confirmed') AS claims FROM voiceprints v JOIN recordings r ON r.id = v.recording_id "
                "WHERE v.person_id = ? AND v.active = 1 ORDER BY v.id",
                (person_id,),
            ).fetchall()
        return [
            VoiceSample(
                id=row["id"],
                recording_id=row["recording_id"],
                filename=row["filename"],
                transcript_id=row["transcript_id"],
                speaker_id=row["speaker_id"],
                seconds=round(self._seconds(row["recording_id"], row["speaker_id"]), 1),
                source=row["source"],
                created_at=row["created_at"],
                claims=row["claims"],
                corrected=row["corrected"],
            )
            for row in rows
            if recordings is None or row["recording_id"] in recordings
        ]

    def remove_sample(self, person_id: str, sample_id: int) -> int | None:
        """The owner says one of the person's samples does not stand for them: it no longer recognises anyone, and
        the speakers it gave them go back to the owner (``_withdraw``), not dropped. How many went back; None when
        the person has no such sample. The speaker it was taken from stays theirs."""
        with self.library.transaction() as db:
            row = db.execute(
                "SELECT recording_id FROM voiceprints WHERE id = ? AND person_id = ? AND active = 1",
                (sample_id, person_id),
            ).fetchone()
            if row is None:
                return None
            db.execute("UPDATE voiceprints SET active = 0 WHERE id = ?", (sample_id,))
            back = self._withdraw(db, {sample_id})
            if back:
                self._prune(db)
            db.execute("UPDATE recordings SET revision = revision + 1 WHERE id = ?", (row[0],))
            return back

    def person(self, person_id: str) -> Person | None:
        return next((p for p in self.people() if p.id == person_id), None)

    def add_person(self, name: str, persona_id: str | None = None) -> Person:
        """A person by name. ``persona_id``: the twin they already have, made by hand, which the library neither
        builds nor follows (``link`` is for twins made from its recordings)."""
        name = " ".join(name.split())
        if not name:
            raise ValueError("名字不能为空")
        with self.library.transaction() as db:
            return self._add_person(db, name, persona_id=persona_id)

    @staticmethod
    def _add_person(db: sqlite3.Connection, name: str, auto: bool = False, persona_id: str | None = None) -> Person:
        if db.execute("SELECT 1 FROM people WHERE name = ?", (name,)).fetchone():
            raise ValueError(f"已经有叫「{name}」的人")
        person = Person(
            id="per_" + uuid.uuid4().hex[:12], name=name, persona_id=persona_id, created_at=_now(), auto=auto
        )
        db.execute(
            "INSERT INTO people (id, name, persona_id, created_at, auto) VALUES (?, ?, ?, ?, ?)",
            (person.id, person.name, person.persona_id, person.created_at, int(auto)),
        )
        return person

    def roster(self) -> list[tuple[str, str, str | None]]:
        """``(id, name, twin)`` of everyone, read without counting their speech (which ``people`` does)."""
        with self.library.read() as db:
            rows = db.execute("SELECT id, name, persona_id FROM people ORDER BY name").fetchall()
        return [(r["id"], r["name"], r["persona_id"]) for r in rows]

    def attach(self, person_id: str, persona_id: str) -> bool:
        """Say that a twin made by hand is this person's, when neither has the other yet; False otherwise."""
        with self.library.transaction() as db:
            row = db.execute("SELECT persona_id FROM people WHERE id = ?", (person_id,)).fetchone()
            if (
                row is None
                or row["persona_id"]
                or db.execute("SELECT 1 FROM people WHERE persona_id = ?", (persona_id,)).fetchone()
            ):
                return False
            db.execute("UPDATE people SET persona_id = ? WHERE id = ?", (persona_id, person_id))
        return True

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
            "SELECT DISTINCT recording_id FROM attributions WHERE person_id = ? UNION SELECT recording_id FROM "
            "segment_fixes WHERE from_person = ? OR to_person = ?",
            (person_id, person_id, person_id),
        ).fetchall()
        for (recording_id,) in touched:
            Team._reopen(db, recording_id, {person_id})
        db.execute("DELETE FROM segment_fixes WHERE from_person = ? OR to_person = ?", (person_id, person_id))
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
            names = dict(db.execute("SELECT id, name FROM people").fetchall())
        here = self._here(speakers, rows, names)
        present = {person_id for person_id, _, _ in here}
        called = self.library.names(recording)
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
                view.candidates = self._suggest(speaker.embedding, prints, set(view.rejected), here)
            if view.decision == "none":
                cue = called.get(speaker.id)
                view.candidates, view.called = self._called(
                    view.candidates, cue, speaker.embedding or [], prints, names, present | set(view.rejected)
                )
                view.quote = cue.quote if view.called and cue else ""
                view.near = len(view.candidates) > 1 and view.candidates[0].score - view.candidates[1].score < NEAR
            views.append(view)
        return views

    def reassign(self, recording_id: str, transcript_id: str, speaker_id: str, before: str, after: str) -> bool:
        """The review found a speaker confirmed as ``before`` to be ``after`` (``Reviews.settle``): give it to them as
        an automatic decision the owner can undo, with ``before`` among the people it is not, and the voice samples
        taken from it as ``before`` no longer standing for them. False when the speaker is no longer ``before``'s."""
        with self.library.transaction() as db:
            # A decision the owner made after the speaker was heard again stands: they heard it themselves.
            row = db.execute(
                "SELECT a.rejected, a.auto FROM attributions a JOIN recordings r ON r.id = a.recording_id "
                "AND r.transcript_id = a.transcript_id JOIN reviewed v ON v.recording_id = a.recording_id "
                "AND v.transcript_id = a.transcript_id AND v.speaker_id = a.speaker_id WHERE a.recording_id = ? "
                "AND a.transcript_id = ? AND a.speaker_id = ? AND a.decision = 'confirmed' AND a.person_id = ? "
                "AND (a.auto = 1 OR a.updated_at <= v.created_at)",
                (recording_id, transcript_id, speaker_id, before),
            ).fetchone()
            if row is None or not db.execute("SELECT 1 FROM people WHERE id = ?", (after,)).fetchone():
                return False
            refused = set(json.loads(row[0]))
            # Never someone the owner said it is not; and given away once already, it is not passed on again.
            if after in refused or (row[1] and refused):
                return False
            rejected = sorted(refused | {before})
            # Given by the review, not by a voice sample: no tier, no sample's track record.
            db.execute(
                "UPDATE attributions SET person_id = ?, rejected = ?, auto = 1, version = ?, updated_at = ?, "
                "tier = NULL, score = NULL, lead = NULL, sample = NULL "
                "WHERE recording_id = ? AND transcript_id = ? AND speaker_id = ?",
                (after, json.dumps(rejected), CLEANUP_VERSION, _now(), recording_id, transcript_id, speaker_id),
            )
            gone = {
                int(r[0])
                for r in db.execute(
                    "SELECT id FROM voiceprints WHERE recording_id = ? AND transcript_id = ? AND speaker_id = ? "
                    "AND person_id IS NOT ? AND active = 1",
                    (recording_id, transcript_id, speaker_id, after),
                )
            }
            db.execute(
                "UPDATE voiceprints SET active = 0 WHERE recording_id = ? AND transcript_id = ? AND speaker_id = ? "
                "AND person_id IS NOT ?",
                (recording_id, transcript_id, speaker_id, after),
            )
            if self._withdraw(db, gone):
                self._prune(db)
            self._reopen(db, recording_id, {before, after})
            db.execute("UPDATE recordings SET revision = revision + 1 WHERE id = ?", (recording_id,))
            return True

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
            gone: set[int] = set()
            if before != after:
                # The samples taken from this speaker no longer stand for whom they were taken as.
                gone = {
                    int(r[0])
                    for r in db.execute(
                        "SELECT id FROM voiceprints WHERE recording_id = ? AND transcript_id = ? AND speaker_id = ? "
                        "AND person_id IS NOT ? AND active = 1",
                        (recording_id, transcript_id, speaker_id, after),
                    )
                }
                db.execute(
                    "UPDATE voiceprints SET active = 0 WHERE recording_id = ? AND transcript_id = ? "
                    "AND speaker_id = ? AND person_id IS NOT ?",
                    (recording_id, transcript_id, speaker_id, after),
                )
                if row is not None and row["auto"] and before and row["sample"] is not None:
                    # The owner gave otherwise a speaker a sample gave by voice alone: its track record.
                    gone |= self._correct(db, int(row["sample"]))
                self._withdraw(db, gone)
            # The recording already gives them a sample, from this speaker or another (``VOICE_SAMPLES``).
            already = db.execute(
                "SELECT 1 FROM voiceprints WHERE recording_id = ? AND person_id IS ? AND active = 1",
                (recording_id, after),
            ).fetchone()
            if after and sample and speaker.embedding and not already:
                db.execute(
                    "INSERT INTO voiceprints (person_id, recording_id, transcript_id, speaker_id, embedding, "
                    "active, created_at, source) VALUES (?, ?, ?, ?, ?, 1, ?, 'speaker')",
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

    def classify(self, recording_id: str) -> int:
        """Decide the recording's untouched speakers where the voice leaves no doubt: very close to one person's
        samples (``AUTO``), or, for a long voice matching nobody, a new unnamed person kept by that voice, unless the
        owner said that voice is nobody they know (``_stranger``: they would be asked again who it is). Returns how
        many speakers were decided. A speaker the owner has acted on is never classified, and a match adds no voice
        sample, so mistakes do not spread. An automatic decision made under other rules (``collector``) is made
        again: where it comes out the same only its version changes, so only the twins it does change are closed."""
        recording = self.library.get(recording_id)
        if recording is None or recording.status != "ready" or recording.transcript_id is None:
            return 0
        speakers = self.library.speakers(recording) or ()
        with self.library.transaction() as db:
            current = db.execute("SELECT transcript_id FROM recordings WHERE id = ?", (recording_id,)).fetchone()
            if current is None or current[0] != recording.transcript_id:
                return 0
            rows = {
                row["speaker_id"]: row
                for row in db.execute(
                    "SELECT * FROM attributions WHERE recording_id = ? AND transcript_id = ?",
                    (recording_id, recording.transcript_id),
                )
            }
            stale = {speaker_id: row["person_id"] for speaker_id, row in rows.items() if _stale(row)}
            # Who already has a speaker here that stays (``ONE_PER_RECORDING``).
            here = {
                row["person_id"]
                for speaker_id, row in rows.items()
                if speaker_id not in stale and row["decision"] == "confirmed" and row["person_id"]
            }
            prints = self._prints(db)
            strangers = self._strangers(db)
            decided: set[str] = set()
            count = 0
            undone = False
            # Longest first: their voiceprints are the steadiest, and a new person is made from the clearest voice.
            for speaker in sorted(speakers, key=lambda s: -s.seconds):
                if (speaker.id in rows and speaker.id not in stale) or not speaker.embedding:
                    continue
                before = stale.get(speaker.id)
                person_id: str | None = None
                # How sure, the best score, its lead and the sample that matched (``attributions.tier``).
                how: tuple[str, float | None, float | None, int | None] = ("high", None, None, None)
                candidates = self._match(speaker.embedding, prints, set(), floor=SHOW)
                if candidates:
                    runner = self._rival(speaker.embedding, prints, strangers, recording_id)
                    if tier(candidates, runner, speaker.seconds) == "high":
                        person_id = candidates[0].person_id
                        best = candidates[0].score
                        sample = self._sample(db, person_id, speaker.embedding)
                        how = ("high", best, round(best - runner, 3), sample)
                    if person_id is not None and ONE_PER_RECORDING and person_id in here:
                        person_id = None
                elif speaker.seconds >= NEW_MIN_SECONDS and not self._stranger(speaker.embedding, strangers, 0.0):
                    person = self._add_person(db, self._unnamed(db), auto=True)
                    person_id = person.id
                    cursor = db.execute(
                        "INSERT INTO voiceprints (person_id, recording_id, transcript_id, speaker_id, embedding, "
                        "active, created_at, source) VALUES (?, ?, ?, ?, ?, 1, ?, 'new')",
                        (
                            person_id,
                            recording_id,
                            recording.transcript_id,
                            speaker.id,
                            json.dumps(speaker.embedding),
                            _now(),
                        ),
                    )
                    prints.append((person_id, person.name, _print(speaker.embedding)))
                    how = ("new", None, None, cursor.lastrowid)
                if speaker.id in stale and person_id == before:
                    db.execute(
                        "UPDATE attributions SET version = ?, tier = ?, score = ?, lead = ?, sample = ? "
                        "WHERE recording_id = ? AND transcript_id = ? AND speaker_id = ?",
                        (ATTRIBUTION_VERSION, *how, recording_id, recording.transcript_id, speaker.id),
                    )
                    continue
                if speaker.id in stale:
                    db.execute(
                        "DELETE FROM attributions WHERE recording_id = ? AND transcript_id = ? AND speaker_id = ?",
                        (recording_id, recording.transcript_id, speaker.id),
                    )
                    if before:
                        decided.add(before)
                    count += person_id is None
                    undone = True
                if person_id is None:
                    continue
                db.execute(
                    "INSERT INTO attributions (recording_id, transcript_id, speaker_id, decision, person_id, "
                    "rejected, updated_at, auto, version, tier, score, lead, sample) "
                    "VALUES (?, ?, ?, 'confirmed', ?, '[]', ?, 1, ?, ?, ?, ?, ?)",
                    (
                        recording_id,
                        recording.transcript_id,
                        speaker.id,
                        person_id,
                        _now(),
                        ATTRIBUTION_VERSION,
                        *how,
                    ),
                )
                decided.add(person_id)
                here.add(person_id)
                count += 1
            if not count:
                return 0
            self._reopen(db, recording_id, decided)
            if undone:
                # An unnamed person whose only speaker was taken back is nobody any more.
                self._prune(db)
            db.execute("UPDATE recordings SET revision = revision + 1 WHERE id = ?", (recording_id,))
            return count

    def voice_tiers(self, recording: Recording) -> dict[str, tuple[Tier, Candidate | None, float]]:
        """For each undecided speaker of the recording: how sure voice alone is (``tier``), of whom, and by how much
        they lead the runner-up (``_rival``). A speaker sure enough of someone who already has a speaker here is "mid"
        when a recording gives a person one speaker by voice (``ONE_PER_RECORDING``), and so is one the owner acted on
        or one taken back (``classify`` leaves both to the owner); one given to someone by voice until its sample
        stopped standing (``_withdraw``) is offered to them again as "mid", while they still sound most alike. People
        the speaker was denied to be are never candidates."""
        if recording.transcript_id is None:
            return {}
        with self.library.read() as db:
            rows = {
                row["speaker_id"]: row
                for row in db.execute(
                    "SELECT * FROM attributions WHERE recording_id = ? AND transcript_id = ?",
                    (recording.id, recording.transcript_id),
                )
            }
            prints = self._prints(db)
            strangers = self._strangers(db)
        here = {row["person_id"] for row in rows.values() if row["decision"] == "confirmed" and row["person_id"]}
        found: dict[str, tuple[Tier, Candidate | None, float]] = {}
        for speaker in self.library.speakers(recording) or ():
            row = rows.get(speaker.id)
            if not speaker.embedding or (row is not None and row["decision"] != "none"):
                continue
            rejected = set(json.loads(row["rejected"])) if row is not None else set()
            candidates = self._match(speaker.embedding, prints, rejected, floor=SHOW)
            runner = self._rival(speaker.embedding, prints, strangers, recording.id) if candidates else 0.0
            level = tier(candidates, runner, speaker.seconds)
            if level == "high" and ONE_PER_RECORDING and candidates[0].person_id in here:
                level = "mid"
            if level == "high" and row is not None:
                # ``classify`` leaves a speaker the owner acted on, or one taken back, to the owner.
                level = "mid"
            if level == "low" and candidates and row is not None and row["suggest"] == candidates[0].person_id:
                level = "mid"
            best = candidates[0] if candidates else None
            found[speaker.id] = (level, best, round(best.score - runner, 3) if best else 0.0)
        return found

    def classify_all(self) -> int:
        """``classify`` every transcribed recording, as after someone's voice samples changed; how many speakers
        were decided."""
        return sum(self.classify(recording.id) for recording in self.library.list())

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

    def review(self, recordings: set[str] | None = None, *, disputed_only: bool = False) -> list[dict[str, object]]:
        """The owner's confirmation queue: speakers someone said are not them, then undecided speakers whose voice
        matches someone, best match first. ``recordings``: only these. ``disputed_only`` skips matching meetings
        without a dispute: the web queue already groups their undecided speakers in ``voices``."""
        if disputed_only:
            with self.library.read() as db:
                disputed = {
                    row[0]
                    for row in db.execute(
                        "SELECT DISTINCT a.recording_id FROM attributions a JOIN recordings r "
                        "ON r.id = a.recording_id AND r.transcript_id = a.transcript_id "
                        "WHERE a.decision = 'none' AND a.disputed = 1"
                    )
                }
            recordings = disputed if recordings is None else recordings & disputed
            if not recordings:
                return []
        queue: list[dict[str, object]] = []
        for recording in self.library.list():
            if recording.status != "ready" or (recordings is not None and recording.id not in recordings):
                continue
            for speaker in self.speakers(recording):
                if (
                    speaker.decision == "none"
                    and (speaker.candidates or speaker.disputed)
                    and (not disputed_only or speaker.disputed)
                ):
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
        voiceprints being the steadiest; each later one joins the voice whose least similar speaker is still at
        least ``GROUP`` alike, never one already speaking in its recording unless as alike as a split half
        (``SPLIT``: diarization told them apart there otherwise), one whose speakers sound most like someone else
        than it does, or one sounding like someone already confirmed in its recording. Fragments are
        voices heard less than ``FRAGMENT_SECONDS`` that nobody in the meeting calls by name, settled together. Speakers
        someone disputed wait apart (``review``); those without a voiceprint wait in their recording.
        ``recordings``: only these."""
        with self.library.read() as db:
            rows = {
                (row["recording_id"], row["speaker_id"]): row
                for row in db.execute(
                    "SELECT a.recording_id, a.speaker_id, a.decision, a.person_id, a.rejected, a.disputed, a.suggest "
                    "FROM attributions a JOIN recordings r ON r.id = a.recording_id "
                    "AND r.transcript_id = a.transcript_id"
                )
            }
            prints = self._prints(db)
            names = dict(db.execute("SELECT id, name FROM people").fetchall())
            strangers = self._strangers(db)
        # (member, unit voiceprint, people it was denied to be, who it sounds most like, people confirmed beside it,
        # whether it sounds like a voice the owner could not name, what the meeting calls it, whom it was given to
        # until its sample stopped standing)
        found: list[
            tuple[VoiceMember, list[float], set[str], Candidate | None, set[str], bool, Cue | None, str | None]
        ] = []
        # How long each person is heard in all confirmed speakers, whichever recordings are asked about.
        had = {person.id: person.seconds for person in self.people()}
        for recording in self.library.list():
            if recording.status != "ready" or recording.transcript_id is None:
                continue
            if recordings is not None and recording.id not in recordings:
                continue
            spoken = self.library.speakers(recording) or ()
            here = self._here(spoken, {s.id: r for s in spoken if (r := rows.get((recording.id, s.id)))}, names)
            present = {person_id for person_id, _, _ in here}
            naming = self.library.names(recording)
            for speaker in spoken:
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
                rejected = set(json.loads(row["rejected"])) if row else set()
                embedding = _print(speaker.embedding)
                matched = self._suggest(embedding, prints, rejected, here)
                suggest = row["suggest"] if row is not None else None
                if suggest:
                    # Given to them by voice until its sample stopped standing (``_withdraw``).
                    matched.sort(key=lambda c: c.person_id != suggest)
                known = max((c.score for c in self._match(embedding, prints, rejected, floor=-1.0)), default=0.0)
                stranger = self._stranger(embedding, strangers, known)
                lead = matched[0] if matched else None
                cue = naming.get(speaker.id)
                found.append((member, _unit(embedding), rejected, lead, present, stranger, cue, suggest))
        groups: list[_Group] = []
        ordered = sorted(found, key=lambda f: (-f[0].seconds, f[0].recording_id))
        for member, vector, rejected, lead, present, stranger, cue, suggest in ordered:
            likely = lead.person_id if lead else None
            split = lead if lead and lead.split else None
            best, best_score = None, GROUP
            for group in groups:
                if likely and group.likely and likely != group.likely:
                    continue
                if cue and group.cues and cue.name != group.cues[0].name:
                    continue
                if (group.likely in present and not split) or (likely in group.present and not group.split):
                    continue
                score = min(sum(a * b for a, b in zip(vector, other, strict=True)) for other in group.vectors)
                if score < SPLIT and any(m.recording_id == member.recording_id for m in group.members):
                    continue
                if score >= best_score:
                    best, best_score = group, score
            if best is None:
                cues = [cue] if cue else []
                groups.append(
                    _Group([member], [vector], set(rejected), likely, set(present), split, stranger, cues, suggest)
                )
            else:
                best.members.append(member)
                best.vectors.append(vector)
                best.rejected.update(rejected)
                best.likely = best.likely or likely
                best.present.update(present)
                best.split = best.split or split
                best.stranger = best.stranger or stranger
                best.suggest = best.suggest or suggest
                if cue:
                    best.cues.append(cue)
        voices: list[Voice] = []
        fragments: list[Voice] = []
        for group in groups:
            members = group.members
            key = "|".join(sorted(f"{m.recording_id}:{m.transcript_id}:{m.speaker_id}" for m in members))
            centroid = _Print(sum(values) for values in zip(*group.vectors, strict=True))
            matched = self._match(centroid, [p for p in prints if p[0] not in group.present], group.rejected)
            if group.split and group.split.person_id not in {c.person_id for c in matched}:
                matched = [group.split, *matched][:2]
            # The person its speakers sound most like leads, as each of them would show it.
            candidates = sorted(matched, key=lambda c: c.person_id != group.likely)
            cue = group.cues[0].model_copy(update={"sure": any(c.sure for c in group.cues)}) if group.cues else None
            candidates, called = self._called(candidates, cue, centroid, prints, names, group.present | group.rejected)
            near = len(candidates) > 1 and candidates[0].score - candidates[1].score < NEAR
            lead = candidates[0] if candidates and candidates[0].sure and not near else None
            # Its lead over the runner-up and the voices the owner could not name in other recordings (``_rival``).
            heard_in = {m.recording_id for m in members}
            ranked = self._match(centroid, [p for p in prints if p[0] not in group.present], group.rejected, floor=-1.0)
            others = [c.score for c in ranked if candidates and c.person_id != candidates[0].person_id]
            runner = max(
                [
                    *others[:1],
                    *(c.score for c in candidates[1:2]),
                    0.0,
                    *(
                        round(_cosine(centroid, vector), 3)
                        for where, vector in strangers
                        if STRANGER_RIVALS and where not in heard_in
                    ),
                ]
            )
            level = tier(candidates, runner, sum(m.seconds for m in members))
            if level == "high" or (candidates and candidates[0].person_id == group.suggest):
                level = "mid"
            voice = Voice(
                id="voice_" + hashlib.sha256(key.encode()).hexdigest()[:12],
                members=members,
                seconds=round(sum(m.seconds for m in members), 1),
                candidates=candidates,
                near=near,
                stranger=group.stranger,
                called=called,
                quote=cue.quote if called and cue else "",
                had=round(had.get(lead.person_id, 0.0), 1) if lead else 0,
                enough=lead is not None and had.get(lead.person_id, 0.0) >= ENOUGH_SECONDS,
                tier=level,
            )
            (fragments if voice.seconds < FRAGMENT_SECONDS and not called else voices).append(voice)
        # Whoever a twin still lacks first, then the voice heard in the most recordings and the longest: settled, it
        # becomes a rival to everyone else's voice there (``_rival``) and recognises the most. Voices like one the
        # owner already said they do not know wait last, the least likely to teach a twin anything.
        voices.sort(key=lambda v: (v.stranger, v.enough, -len({m.recording_id for m in v.members}), -v.seconds, v.id))
        return voices, fragments

    def unvoiced(self, recordings: set[str] | None = None) -> list[tuple[Recording, int]]:
        """Transcribed recordings with undecided speakers who have no voiceprint, so no voice can hold them: each with
        how many, to be settled in the recording itself. Disputed ones wait apart (``review``). ``recordings``: only
        these."""
        with self.library.read() as db:
            settled = {
                (row[0], row[1])
                for row in db.execute(
                    "SELECT a.recording_id, a.speaker_id FROM attributions a JOIN recordings r "
                    "ON r.id = a.recording_id AND r.transcript_id = a.transcript_id "
                    "WHERE a.decision != 'none' OR a.disputed = 1"
                )
            }
        found = []
        for recording in self.library.list():
            if recording.status != "ready" or (recordings is not None and recording.id not in recordings):
                continue
            silent = sum(
                1
                for speaker in self.library.speakers(recording) or ()
                if not speaker.embedding and (recording.id, speaker.id) not in settled
            )
            if silent:
                found.append((recording, silent))
        return found

    def heard(self, recordings: set[str] | None = None) -> tuple[float, float]:
        """How long people speak in the transcribed recordings, and how much of it is settled (someone, nobody known,
        or several people; not a speaker someone disputed): the owner's progress, measured by what a twin can learn
        from rather than by how many questions are left. ``recordings``: only these."""
        with self.library.read() as db:
            settled = {
                (row[0], row[1])
                for row in db.execute(
                    "SELECT a.recording_id, a.speaker_id FROM attributions a JOIN recordings r "
                    "ON r.id = a.recording_id AND r.transcript_id = a.transcript_id "
                    "WHERE a.decision != 'none' AND a.disputed = 0"
                )
            }
        total = done = 0.0
        for recording in self.library.list():
            if recording.status != "ready" or (recordings is not None and recording.id not in recordings):
                continue
            for speaker in self.library.speakers(recording) or ():
                total += speaker.seconds
                if (recording.id, speaker.id) in settled:
                    done += speaker.seconds
        return round(done, 1), round(total, 1)

    def decide_voice(
        self,
        members: list[tuple[str, str, str]],
        action: Literal["confirm", "unknown", "mixed"],
        person_id: str | None = None,
        *,
        sample: bool = True,
    ) -> None:
        """Settle every (recording, transcript, speaker) of a voice at once: as ``person_id``, keeping up to
        ``VOICE_SAMPLES`` of them from different recordings (the longest, then others at least
        ``SAMPLE_MIN_SECONDS``) as their voice samples so other recordings are recognised, as nobody known, or as
        several people mixed together. ``sample=False`` keeps none (fragments, too short to recognise anyone by).
        ``Stale`` when any of them has another transcript now or was decided meanwhile (the page shows an old
        grouping); ``ValueError`` for an unknown speaker or person."""
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
        decision: Decision = "confirmed" if action == "confirm" else action
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
            sampled: set[str] = set()
            # A recording already giving them a sample gives no second one (``VOICE_SAMPLES``).
            given = {
                row[0]
                for row in db.execute(
                    "SELECT recording_id FROM voiceprints WHERE person_id = ? AND active = 1", (owner,)
                )
            }
            for recording_id, transcript_id, speaker in sorted(heard, key=lambda h: -h[2].seconds):
                if not owner or not sample or len(sampled) >= VOICE_SAMPLES:
                    break
                if not speaker.embedding or recording_id in sampled or recording_id in given:
                    continue
                if sampled and speaker.seconds < SAMPLE_MIN_SECONDS:
                    break
                sampled.add(recording_id)
                db.execute(
                    "INSERT INTO voiceprints (person_id, recording_id, transcript_id, speaker_id, embedding, "
                    "active, created_at, source) VALUES (?, ?, ?, ?, ?, 1, ?, 'voice')",
                    (owner, recording_id, transcript_id, speaker.id, json.dumps(speaker.embedding), _now()),
                )
            for recording_id in sorted({h[0] for h in heard}):
                if owner:
                    self._reopen(db, recording_id, {owner})
                db.execute("UPDATE recordings SET revision = revision + 1 WHERE id = ?", (recording_id,))

    def unlike(self, members: Iterable[tuple[str, str]], person_id: str) -> Candidate | None:
        """Someone else known whom the speakers (recording, speaker) clearly sound more like than ``person_id``, as
        the owner is about to settle them as ``person_id``: ``AUTO_MARGIN`` closer to that person's samples, or, while
        ``person_id`` has none, ``SURE`` close. Said once in place; the owner may well be right, as when someone's
        samples come from one room."""
        vectors = []
        for recording_id, speaker_id in members:
            recording = self.library.get(recording_id)
            speaker = next(
                (s for s in (self.library.speakers(recording) if recording else None) or () if s.id == speaker_id),
                None,
            )
            if speaker is not None and speaker.embedding:
                vectors.append(_unit(speaker.embedding))
        if not vectors:
            return None
        centroid = [sum(values) for values in zip(*vectors, strict=True)]
        with self.library.read() as db:
            prints = self._prints(db)
        other = next(iter(self._match(centroid, prints, {person_id}, floor=SUGGEST)), None)
        own = self._match(centroid, [p for p in prints if p[0] == person_id], set(), floor=-1.0)
        if other is None:
            return None
        if own and other.score - own[0].score >= AUTO_MARGIN:
            return other
        return other if not own and other.score >= SURE else None

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
            # Segments given from one of them to the other were theirs all along.
            db.execute(
                "DELETE FROM segment_fixes WHERE action = 'move' AND ((from_person = ? AND to_person = ?) OR "
                "(from_person = ? AND to_person = ?))",
                (person_id, into, into, person_id),
            )
            db.execute("UPDATE segment_fixes SET from_person = ? WHERE from_person = ?", (into, person_id))
            db.execute("UPDATE segment_fixes SET to_person = ? WHERE to_person = ?", (into, person_id))
            heard += [
                r[0]
                for r in db.execute("SELECT DISTINCT recording_id FROM segment_fixes WHERE to_person = ?", (into,))
                if r[0] not in heard
            ]
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
        those the owner could not name, and those taken by voice alone for an unnamed person who has no twin
        (``person_id``). What a colleague who
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
                # A voice the owner could not name is still the colleague's own to recognise.
                if row is None or row["decision"] in {"none", "unknown"}:
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

    @staticmethod
    def _here(
        speakers: Iterable[Speaker], rows: Mapping[str, sqlite3.Row], names: Mapping[str, str]
    ) -> list[tuple[str, str, list[float]]]:
        """The people confirmed in a recording, from its speakers and their attribution rows by speaker: each one's
        person, name and voiceprint there (``_suggest``)."""
        found: list[tuple[str, str, list[float]]] = []
        for speaker in speakers:
            row = rows.get(speaker.id)
            if speaker.embedding and row is not None and row["decision"] == "confirmed" and row["person_id"]:
                found.append((str(row["person_id"]), names.get(row["person_id"], ""), _print(speaker.embedding)))
        return found

    @staticmethod
    def _stranger(embedding: list[float], strangers: list[tuple[str, list[float]]], known: float) -> bool:
        """Whether the voice is one the owner said is nobody they know (``_strangers``): ``STRANGER`` close to it,
        and closer to it than to anyone known (``known``, the best score) by ``STRANGER_MARGIN``."""
        embedding = _print(embedding)
        score = max((_cosine(embedding, vector) for _, vector in strangers), default=0.0)
        return score >= STRANGER and score - known >= STRANGER_MARGIN

    @staticmethod
    def _rival(
        embedding: list[float],
        prints: Iterable[tuple[str, str, list[float]]],
        strangers: list[tuple[str, list[float]]],
        recording_id: str,
    ) -> float:
        """What the best person must lead (``tier``): the second most alike person with samples, however low, and
        with ``STRANGER_RIVALS`` the closest voice the owner said is nobody they know in another recording (in the
        same one, diarization already told it apart)."""
        embedding = _print(embedding)
        runner = Team._runner(embedding, prints)
        if STRANGER_RIVALS:
            others = [vector for where, vector in strangers if where != recording_id]
            runner = max([runner, *(round(_cosine(embedding, vector), 3) for vector in others)])
        return runner

    def _strangers(self, db: sqlite3.Connection) -> list[tuple[str, list[float]]]:
        """The recording and voiceprint of each speaker the owner said is nobody they know, in current
        transcripts."""
        found: list[tuple[str, list[float]]] = []
        rows = db.execute(
            "SELECT a.recording_id, a.speaker_id FROM attributions a JOIN recordings r ON r.id = a.recording_id "
            "AND r.transcript_id = a.transcript_id WHERE a.decision = 'unknown' AND a.auto = 0"
        ).fetchall()
        for recording_id, speaker_id in rows:
            recording = self.library.get(recording_id)
            speaker = next(
                (s for s in (self.library.speakers(recording) if recording else None) or () if s.id == speaker_id), None
            )
            if speaker is not None and speaker.embedding:
                found.append((recording_id, _print(speaker.embedding)))
        return found

    def _prints(self, db: sqlite3.Connection) -> list[tuple[str, str, list[float]]]:
        """Everyone's active voice samples, one per person and recording (the earliest; ``VOICE_SAMPLES``), also where
        a merge of two people or an older library left more; at most ``SAMPLE_CAP`` per person (``SAMPLE_PICK``)."""
        found: dict[tuple[str, str], tuple[str, str, list[float], str]] = {}
        for row in db.execute(
            "SELECT v.person_id, v.recording_id, v.speaker_id, p.name, v.embedding FROM voiceprints v "
            "JOIN people p ON p.id = v.person_id WHERE v.active = 1 ORDER BY v.id"
        ):
            key = (row["person_id"], row["recording_id"])
            if key not in found:
                found[key] = (row["person_id"], row["name"], _Print(json.loads(row["embedding"])), row["speaker_id"])
        if SAMPLE_CAP <= 0:
            return [(person_id, name, vector) for person_id, name, vector, _ in found.values()]
        by_person: dict[str, list[_Sample]] = {}
        for (person_id, recording_id), sample in found.items():
            by_person.setdefault(person_id, []).append((recording_id, sample))
        kept: list[tuple[str, str, list[float]]] = []
        for samples in by_person.values():
            if SAMPLE_PICK >= 1:
                samples.sort(key=lambda item: -self._seconds(item[0], item[1][3]))
            chosen = samples[: int(SAMPLE_CAP)] if SAMPLE_PICK < 2 else _unlike(samples, int(SAMPLE_CAP))
            kept += [(person_id, name, vector) for _, (person_id, name, vector, _) in chosen]
        return kept

    def _seconds(self, recording_id: str, speaker_id: str) -> float:
        """How long the speaker a sample was taken from spoke; 0 when unknown."""
        recording = self.library.get(recording_id)
        found = next(
            (s for s in (self.library.speakers(recording) if recording else None) or () if s.id == speaker_id), None
        )
        return found.seconds if found else 0.0

    @staticmethod
    def _runner(embedding: list[float], prints: Iterable[tuple[str, str, list[float]]]) -> float:
        """How alike the speaker is to the second most alike person with samples, however low (``tier``)."""
        ranked = Team._match(embedding, prints, set(), floor=-1.0)
        return ranked[1].score if len(ranked) > 1 else 0.0

    @staticmethod
    def _sample(db: sqlite3.Connection, person_id: str, embedding: list[float]) -> int | None:
        """The person's active voice sample (``voiceprints.id``) most alike the voice: the one that recognised it."""
        found = [
            (_cosine(embedding, json.loads(row[1])), int(row[0]))
            for row in db.execute(
                "SELECT id, embedding FROM voiceprints WHERE person_id = ? AND active = 1", (person_id,)
            )
        ]
        return max(found)[1] if found else None

    @staticmethod
    def _match(
        embedding: list[float],
        prints: Iterable[tuple[str, str, list[float]]],
        rejected: set[str],
        floor: float = SUGGEST,
    ) -> list[Candidate]:
        """People with active samples the speaker was not denied to be, by their best-matching sample, from
        ``floor``; at most the top two."""
        embedding = _print(embedding)
        scores: dict[str, tuple[str, list[float]]] = {}
        for person_id, name, vector in prints:
            if person_id not in rejected:
                scores.setdefault(person_id, (name, []))[1].append(_cosine(embedding, vector))
        best: list[Candidate] = []
        for person_id, (name, found) in scores.items():
            top = sorted(found, reverse=True)[: max(1, int(SCORE_TOP))]
            score = round(sum(top) / len(top), 3)
            best.append(Candidate(person_id=person_id, name=name, score=score, sure=score >= SURE))
        ranked = sorted((c for c in best if c.score >= floor), key=lambda c: -c.score)
        return ranked[:2]

    @staticmethod
    def _suggest(
        embedding: list[float],
        prints: list[tuple[str, str, list[float]]],
        rejected: set[str],
        here: list[tuple[str, str, list[float]]],
    ) -> list[Candidate]:
        """Who an undecided speaker may be (``_match``), leaving out the people already confirmed in its recording
        (``here``: each one's person, name and voiceprint there): diarization tells a meeting's people apart, so a
        voice merely like one of them is someone else, unless it is as alike as a split half of theirs (``SPLIT``)."""
        embedding = _print(embedding)
        present = {person_id for person_id, _, _ in here}
        found = {c.person_id: c for c in Team._match(embedding, [p for p in prints if p[0] not in present], rejected)}
        for person_id, name, vector in here:
            score = round(_cosine(embedding, vector), 3)
            if person_id in rejected or score < SPLIT or (person_id in found and found[person_id].score >= score):
                continue
            found[person_id] = Candidate(person_id=person_id, name=name, score=score, sure=True, split=True)
        return sorted(found.values(), key=lambda c: -c.score)[:2]

    @staticmethod
    def _called(
        candidates: list[Candidate],
        cue: Cue | None,
        embedding: list[float],
        prints: list[tuple[str, str, list[float]]],
        names: Mapping[str, str],
        excluded: set[str],
    ) -> tuple[list[Candidate], str | None]:
        """Candidates with what the meeting calls the speaker (``cue``), and that name when it is a cue to show. A
        named person in the team leads the candidates, marked ``called``; they are the answer by default only when
        the voice agrees (a candidate already) or was sure by itself, and a voice sure of someone else is no longer
        sure. A name nobody in the team has is shown as is, for the owner to add them. A person ``excluded`` (already
        confirmed elsewhere in the meeting, or denied) leaves no cue."""
        embedding = _print(embedding)
        if cue is None:
            return candidates, None
        person_id = next((pid for pid, name in names.items() if name == cue.name), None)
        if person_id is None:
            return candidates, cue.name
        found = next((c for c in candidates if c.person_id == person_id), None)
        if person_id in excluded and found is None:
            return candidates, None
        if found is None:
            score = max((round(_cosine(embedding, v), 3) for pid, _, v in prints if pid == person_id), default=0.0)
            found = Candidate(person_id=person_id, name=cue.name, score=score)
        else:
            found = found.model_copy(update={"sure": found.sure or cue.sure})
        others = [c.model_copy(update={"sure": False}) for c in candidates if c.person_id != person_id]
        return [found.model_copy(update={"called": True}), *others][:2], cue.name

    def _withdraw(self, db: sqlite3.Connection, samples: set[int]) -> int:
        """Take back the speakers given to someone by voice alone through these voice samples, which no longer stand
        for them: each waits for the owner, offered to whom it was given (``voice_tiers``) rather than dropped.
        How many were taken back."""
        if not samples:
            return 0
        marks = ", ".join("?" * len(samples))
        rows = db.execute(
            "SELECT a.recording_id, a.transcript_id, a.speaker_id, a.person_id FROM attributions a JOIN recordings r "
            "ON r.id = a.recording_id AND r.transcript_id = a.transcript_id WHERE a.auto = 1 "
            f"AND a.decision = 'confirmed' AND a.sample IN ({marks})",
            sorted(samples),
        ).fetchall()
        taken: dict[str, set[str]] = {}
        for recording_id, transcript_id, speaker_id, person_id in rows:
            db.execute(
                "UPDATE attributions SET decision = 'none', person_id = NULL, suggest = ?, tier = 'mid', "
                "updated_at = ? WHERE recording_id = ? AND transcript_id = ? AND speaker_id = ?",
                (person_id, _now(), recording_id, transcript_id, speaker_id),
            )
            taken.setdefault(recording_id, set()).add(person_id)
        for recording_id, people in taken.items():
            self._reopen(db, recording_id, people)
            db.execute("UPDATE recordings SET revision = revision + 1 WHERE id = ?", (recording_id,))
        return len(rows)

    @staticmethod
    def _correct(db: sqlite3.Connection, sample: int) -> set[int]:
        """Count that the owner gave otherwise a speaker this sample gave by voice alone; the sample itself when that
        makes it stop standing for its person (``RETIRE_CORRECTED``), nothing otherwise."""
        db.execute("UPDATE voiceprints SET corrected = corrected + 1 WHERE id = ?", (sample,))
        row = db.execute("SELECT corrected, active FROM voiceprints WHERE id = ?", (sample,)).fetchone()
        if row is None or not row["active"] or row["corrected"] < RETIRE_CORRECTED:
            return set()
        standing = db.execute(
            "SELECT COUNT(*) FROM attributions WHERE auto = 1 AND decision = 'confirmed' AND sample = ?", (sample,)
        ).fetchone()[0]
        if row["corrected"] <= standing:
            return set()
        db.execute("UPDATE voiceprints SET active = 0 WHERE id = ?", (sample,))
        return {sample}

    @staticmethod
    def _reopen(db: sqlite3.Connection, recording_id: str, people: set[str]) -> None:
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
        """The twin sources of a person: one per recording where some speaker is confirmed as them, or a segment
        was given to them (``media.review``), with every segment in transcript order (empty ones keep their number)
        so evidence cites (transcript, segment). The id changes with the transcript and with the set of the person's
        own segments, so a decision that moves one sentence from them to someone else drops every chunk and
        candidate built from the old set."""
        with self.library.read() as db:
            names = dict(db.execute("SELECT id, name FROM people").fetchall())
            rows = db.execute(
                "SELECT a.recording_id, a.transcript_id, a.speaker_id, a.decision, a.person_id FROM attributions a "
                "JOIN recordings r ON r.id = a.recording_id AND r.transcript_id = a.transcript_id "
                "WHERE a.recording_id IN (SELECT recording_id FROM attributions WHERE person_id = ? "
                "AND decision = 'confirmed' UNION SELECT recording_id FROM segment_fixes WHERE to_person = ? "
                "AND action = 'move')",
                (person_id, person_id),
            ).fetchall()
            fixed = db.execute(
                "SELECT f.recording_id, f.segment, f.from_person, f.action, f.to_person FROM segment_fixes f "
                "JOIN recordings r ON r.id = f.recording_id AND r.transcript_id = f.transcript_id "
                "WHERE f.action != 'keep'"
            ).fetchall()
        decided: dict[str, dict[str, tuple[str, str | None]]] = {}
        for recording_id, _, speaker_id, decision, owner in rows:
            decided.setdefault(recording_id, {})[speaker_id] = (decision, owner)
        fixes: dict[str, dict[int, tuple[str, str, str | None]]] = {}
        for recording_id, segment, before, action, after in fixed:
            fixes.setdefault(recording_id, {})[segment] = (before, action, after)
        parsed = []
        for recording_id, speakers in sorted(decided.items()):
            recording = self.library.get(recording_id)
            # The model's proofreading where there is one: the person's words as corrected.
            transcript = self.library.cleaned(recording) if recording else None
            if recording is None or transcript is None:
                continue
            owners = segment_owners(transcript, speakers, fixes.get(recording_id, {}))
            if person_id not in owners:
                continue
            parsed.append(self._source(recording, transcript, speakers, person_id, name, names, owners))
        return parsed

    @staticmethod
    def _source(
        recording: Recording,
        transcript: Transcript,
        speakers: dict[str, tuple[str, str | None]],
        person_id: str,
        name: str,
        names: dict[str, str],
        owners: list[str | None],
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

        def who(i: int, segment: Segment) -> str:
            owner = owners[i]
            if owner == person_id:
                return name
            decision, confirmed = speakers.get(segment.speaker, ("none", None))
            if owner != (confirmed if decision == "confirmed" else None):
                # Left out of, or given away from, the speaker's person (``media.review``).
                return names.get(owner, "其他人") if owner else "其他人"
            return others.get(segment.speaker, "其他人")

        lines = [
            (
                who(i, segment),
                f"[{timestamp(segment.start)}] {' '.join(segment.text.split())}" if segment.text.strip() else "",
                owners[i] == person_id,
            )
            for i, segment in enumerate(transcript.segments)
        ]
        mine = ",".join(str(i) for i, owner in enumerate(owners) if owner == person_id)
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
