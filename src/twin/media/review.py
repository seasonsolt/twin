"""A second look at speakers already confirmed, stretch by stretch.

Diarization can fold several people into one speaker (before asr-funasr 1.3.1 a short-spoken voice was merged into
the nearest large one, and a "broad" speaker of a long meeting collected dozens of them), and once the owner confirms
that speaker, everything in it goes into one person's twin. Taking the people's voice samples to be right, every
confirmed speaker is heard again in stretches (``units``: a transcript segment, or neighbouring segments of the
speaker joined up to ``MIN_SECONDS``), whose voiceprints the transcription service computes once per transcript.
Each is compared with the people's voice samples *from other recordings*: a sample taken from this recording is the
speaker's own centroid, which every stretch of it resembles. A stretch is someone else's when another known person
is ``MARGIN`` closer than the confirmed one, and a stranger's when nobody known comes near (``STRANGER``). One 1.5 s
window cannot tell people apart across meetings (docs/ASR_EVAL.md); a few seconds of one segment mostly can.

The owner hears each suspect stretch and leaves it out of the person's twin, gives it to someone else, or keeps it
(``segment_fixes``). ``Team.sources`` follows those decisions, and since a twin's source id changes with the set of
segments that are the person's, only the recordings whose segments moved are read again.

Calibration (docs/ASR_EVAL.md「已确认说话人逐段复核」): AliMeeting Eval with a voice sample per person from the
first half of their meeting (same room) or from their headset (another channel), stretches of the second half; and
the 8790 copy of a real weekly meeting against samples from other recordings.
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
import subprocess
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np
from pydantic import BaseModel

from .collector import CLEANUP_VERSION, LEGACY_CLEANUP
from .ingest import CommandTranscriber, Segment
from .library import Library, Recording

# Neighbouring segments of a speaker are joined until a stretch is this long: on AliMeeting (Eval, a baseline from
# the first half of the meeting), own stretches were flagged 9% / 6% / 4% of the time at 1.5 / 3 / 5 s and others'
# found 93% / 95% / 97%; 3 s keeps a word or two of someone else from being averaged away in a longer stretch.
MIN_SECONDS = 3.0
# Never across a pause longer than this: segments further apart are different moments of the meeting.
MAX_GAP = 30.0
# Stretches shorter than this are not judged: a voiceprint of a second or so says little.
JUDGE_SECONDS = 1.5
# Someone else's: another known person this much closer than the confirmed one. AliMeeting Eval and Test, 3 s
# stretches: own stretches flagged 3-6% (0.5% from 6 s), others' 95-97%, pointing at the right person 89-93%.
MARGIN = 0.1
# A stranger's: nobody known this close, the confirmed person included, in a stretch of at least
# ``STRANGER_SECONDS`` (shorter ones were flagged a quarter of the time when they were the person's own). Found 67%
# (baseline from the same room) to 84% (another microphone) of the voices of people without samples.
STRANGER = 0.25
STRANGER_SECONDS = 3.0
# Suspect stretches leave the person's twin without asking anyone (``Reviews.settle``): leaving out a stretch of
# theirs costs a little of their speech, keeping someone else's puts words in their mouth, and on AliMeeting the
# rule found 95-97% of others' stretches while flagging 3-6% of the person's own. The owner is asked only about a
# speaker most of whose judged speech is suspect, which is one confirmed as the wrong person rather than one with a
# few stray stretches: of 151 clean AliMeeting speakers none reached half (the worst 47%, the median 0-2%). On the
# team library (470 speakers) 32 reach it, where 66 reached 20%.
FLAG_SHARE = 0.5
# A speaker nearly all unlike the person (``REASSIGN_SHARE`` of judged speech) whose suspect speech mostly sounds
# like one other known person (``REASSIGN_LEAD`` of it) was confirmed as the wrong person: it is given to that person
# without asking, as an automatic decision the owner can undo. Strict on purpose, since a wrong move puts words in
# someone else's mouth: on AliMeeting a single stretch pointed at the right person 89-93% of the time, and here most
# of a speaker's stretches must agree. On the team library 7 of the 32 speakers put to the owner passed it, and 4
# more once those were moved.
REASSIGN_SHARE = 0.9
REASSIGN_LEAD = 0.8
# Rounds of giving away the speakers a moved voice sample was holding up; on the team library the second round moved
# 4 more and the third none.
REASSIGN_ROUNDS = 5
# A speaker the transcription service failed on is tried again after this long.
RETRY = dt.timedelta(hours=6)

Verdict = Literal["", "other", "stranger"]
FixAction = Literal["exclude", "move", "keep"]
Status = Literal["waiting", "failed", "no_samples", "ready"]


@dataclass(frozen=True)
class Unit:
    """Segments of one speaker heard as one stretch."""

    segments: tuple[int, ...]
    parts: tuple[tuple[float, float], ...]

    @property
    def seconds(self) -> float:
        return sum(end - start for start, end in self.parts)


def units(segments: Sequence[Segment], speaker: str) -> list[Unit]:
    """The speaker's stretches, in transcript order: each segment of theirs, joined with the next ones of theirs
    until ``MIN_SECONDS`` long, never across more than ``MAX_GAP``. One left shorter (the next segment of theirs
    is too far) joins the stretch before it, if that is near enough."""
    groups: list[list[int]] = []
    current: list[int] = []

    def seconds(group: list[int]) -> float:
        return sum(segments[i].end - segments[i].start for i in group)

    def close() -> None:
        if (
            seconds(current) < MIN_SECONDS
            and groups
            and segments[current[0]].start - segments[groups[-1][-1]].end <= MAX_GAP
        ):
            groups[-1].extend(current)
        else:
            groups.append(list(current))

    for i, segment in enumerate(segments):
        if segment.speaker != speaker or segment.end <= segment.start:
            continue
        if current and (segment.start - segments[current[-1]].end > MAX_GAP or seconds(current) >= MIN_SECONDS):
            close()
            current = []
        current.append(i)
    if current:
        close()
    return [Unit(tuple(group), tuple((segments[i].start, segments[i].end) for i in group)) for group in groups]


def judge(own: float, other: float, seconds: float) -> Verdict:
    """Whose a stretch sounds like: ``own`` and ``other`` are its similarity to the confirmed person and to the
    closest other known person."""
    if seconds < JUDGE_SECONDS:
        return ""
    if other - own >= MARGIN:
        return "other"
    if max(own, other) < STRANGER and seconds >= STRANGER_SECONDS:
        return "stranger"
    return ""


def cut_parts(audio: Path, output: Path, parts: Sequence[tuple[float, float]], rate: int = 24000) -> None:
    """The parts of ``audio`` one after another as a mono WAV (each input seeks on its own: fast in a long file)."""
    if not parts or any(end <= start for start, end in parts):
        raise ValueError("音频片段为空")
    inputs: list[str] = []
    for start, end in parts:
        inputs += ["-ss", str(start), "-t", str(end - start), "-i", str(audio)]
    joined = "".join(f"[{k}:a]" for k in range(len(parts))) + f"concat=n={len(parts)}:v=0:a=1[out]"
    output.touch(mode=0o600)
    output.chmod(0o600)
    command = ["ffmpeg", "-nostdin", "-v", "error", "-y", *inputs, "-filter_complex", joined, "-map", "[out]"]
    subprocess.run(
        [*command, "-ac", "1", "-ar", str(rate), "-c:a", "pcm_s16le", "-map_metadata", "-1", str(output)],
        check=True,
        capture_output=True,
        timeout=300,
    )


def embed(transcriber: CommandTranscriber, audio: Path, found: list[Unit], scratch: Path) -> list[list[float] | None]:
    """The voiceprint of each stretch: in one request, or one by one from a transcription service older than
    asr-funasr 1.3.2, which answers a request for stretches with the voiceprint of the whole recording."""
    if not found:
        return []
    prints = transcriber.embed_spans(audio, [list(unit.parts) for unit in found])
    if prints is not None:
        return prints
    result: list[list[float] | None] = []
    for unit in found:
        clip = scratch / f".review-{uuid.uuid4().hex}.wav"
        try:
            cut_parts(audio, clip, unit.parts, rate=16000)
            result.append(transcriber.embed(clip))
        finally:
            clip.unlink(missing_ok=True)
    if found and all(value is None for value in result):
        raise RuntimeError("转写服务没能计算声纹，请检查语音识别配置后重试")
    return result


class UnitView(BaseModel):
    index: int
    segments: list[int]
    start: float
    end: float
    seconds: float
    text: str = ""
    verdict: Verdict = ""
    # Similarity to the confirmed person, and to the closest other known person (``like``).
    own: float | None = None
    other: float | None = None
    like: str | None = None
    like_name: str | None = None
    # The owner's decision about it, if any (``segment_fixes``), and whom it was given to.
    fix: FixAction | None = None
    to_person: str | None = None
    to_name: str | None = None
    # Left out by the review itself (``Reviews.settle``), not by the owner.
    auto: bool = False


class SpeakerReview(BaseModel):
    """A confirmed speaker, heard again stretch by stretch."""

    recording_id: str
    filename: str
    transcript_id: str
    revision: int
    speaker_id: str
    person_id: str
    name: str
    status: Status
    error: str = ""
    # Judged speech, the part of it found suspect, and how much of that is still undecided.
    seconds: float = 0
    suspect_seconds: float = 0
    open_seconds: float = 0
    suspects: int = 0
    open: int = 0
    share: float = 0
    # Who the suspect stretches sound like most, by seconds, for "all of them are X".
    likely: str | None = None
    likely_name: str | None = None
    units: list[UnitView] = []


def _blob(vector: list[float] | None) -> bytes | None:
    return None if vector is None else np.asarray(vector, dtype=np.float32).tobytes()


def _unit(vector: np.ndarray) -> np.ndarray:
    norm: np.ndarray = np.linalg.norm(vector, axis=-1, keepdims=True) + 1e-9
    return np.asarray(vector / norm)


class Reviews:
    """The confirmed speakers of the library, heard again (see the module)."""

    def __init__(self, library: Library) -> None:
        self.library = library

    # ------------------------------------------------------------------ computing

    def waiting(self) -> list[Recording]:
        """Transcribed recordings with a confirmed speaker not heard again yet (or whose attempt failed more than
        ``RETRY`` ago), oldest first."""
        retry = (dt.datetime.now(dt.UTC) - RETRY).isoformat()
        with self.library.read() as db:
            rows = db.execute(
                "SELECT DISTINCT a.recording_id FROM attributions a JOIN recordings r ON r.id = a.recording_id "
                "AND r.transcript_id = a.transcript_id WHERE r.status = 'ready' AND a.decision = 'confirmed' "
                "AND NOT EXISTS (SELECT 1 FROM reviewed v WHERE v.recording_id = a.recording_id "
                "AND v.transcript_id = a.transcript_id AND v.speaker_id = a.speaker_id "
                "AND (v.error = '' OR v.created_at > ?)) ORDER BY r.created_at",
                (retry,),
            ).fetchall()
        return [recording for (recording_id,) in rows if (recording := self.library.get(recording_id))]

    def run(self, recording_id: str, transcriber: CommandTranscriber) -> int:
        """Hear the recording's confirmed speakers again (those not heard yet) in one request to the transcription
        service; returns how many. A failure is noted, so the queue moves on, and tried again after ``RETRY``."""
        recording = self.library.get(recording_id)
        transcript = self.library.transcript(recording) if recording else None
        if recording is None or transcript is None:
            return 0
        with self.library.read() as db:
            confirmed = [
                row[0]
                for row in db.execute(
                    "SELECT a.speaker_id FROM attributions a WHERE a.recording_id = ? AND a.transcript_id = ? "
                    "AND a.decision = 'confirmed' AND NOT EXISTS (SELECT 1 FROM reviewed v WHERE "
                    "v.recording_id = a.recording_id AND v.transcript_id = a.transcript_id "
                    "AND v.speaker_id = a.speaker_id AND v.error = '') ORDER BY a.speaker_id",
                    (recording_id, transcript.id),
                )
            ]
        if not confirmed:
            return 0
        found = {speaker: units(transcript.segments, speaker) for speaker in confirmed}
        flat = [unit for speaker in confirmed for unit in found[speaker]]
        audio = self.library.folder(recording_id) / "playback.flac"
        try:
            prints = embed(transcriber, audio, flat, self.library.folder(recording_id))
            if len(prints) != len(flat):
                raise RuntimeError("转写服务返回的声纹数量不对")
        except (RuntimeError, OSError, subprocess.SubprocessError, ValueError) as error:
            self._record(recording_id, transcript.id, {s: [] for s in confirmed}, [], str(error) or "复核失败")
            raise
        self._record(recording_id, transcript.id, found, prints, "")
        self.settle({recording_id})
        return len(confirmed)

    def _record(
        self,
        recording_id: str,
        transcript_id: str,
        found: dict[str, list[Unit]],
        prints: list[list[float] | None],
        error: str,
    ) -> None:
        now = dt.datetime.now(dt.UTC).isoformat()
        with self.library.transaction() as db:
            k = 0
            for speaker_id, stretches in found.items():
                db.execute(
                    "DELETE FROM review_units WHERE recording_id = ? AND transcript_id = ? AND speaker_id = ?",
                    (recording_id, transcript_id, speaker_id),
                )
                db.execute(
                    "INSERT OR REPLACE INTO reviewed (recording_id, transcript_id, speaker_id, error, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (recording_id, transcript_id, speaker_id, error, now),
                )
                for index, unit in enumerate(stretches):
                    db.execute(
                        "INSERT INTO review_units (recording_id, transcript_id, speaker_id, unit, segments, parts, "
                        "embedding) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (
                            recording_id,
                            transcript_id,
                            speaker_id,
                            index,
                            json.dumps(list(unit.segments)),
                            json.dumps([list(p) for p in unit.parts]),
                            _blob(prints[k] if not error else None),
                        ),
                    )
                    k += 1

    # ------------------------------------------------------------------ judging

    @staticmethod
    def _samples(db: sqlite3.Connection, recording_id: str) -> tuple[list[str], dict[str, str], np.ndarray, np.ndarray]:
        """Everyone's active voice samples from recordings other than ``recording_id``, one per person and
        recording (the earliest, as ``Team._prints``): (people, names, owner index per row, unit matrix)."""
        rows = db.execute(
            "SELECT v.person_id, v.recording_id, p.name, v.embedding FROM voiceprints v "
            "JOIN people p ON p.id = v.person_id WHERE v.active = 1 AND v.recording_id != ? ORDER BY v.id",
            (recording_id,),
        ).fetchall()
        seen: set[tuple[str, str]] = set()
        people: list[str] = []
        names: dict[str, str] = {}
        owners: list[int] = []
        vectors: list[list[float]] = []
        for person_id, sample_recording, name, embedding in rows:
            if (person_id, sample_recording) in seen:
                continue
            seen.add((person_id, sample_recording))
            if person_id not in names:
                names[person_id] = name
                people.append(person_id)
            owners.append(people.index(person_id))
            vectors.append(json.loads(embedding))
        if not vectors or len({len(v) for v in vectors}) != 1:
            return people, names, np.zeros(0, dtype=int), np.zeros((0, 0))
        return people, names, np.asarray(owners), _unit(np.asarray(vectors, dtype=np.float64))

    def speaker(self, recording: Recording, speaker_id: str, text: bool = True) -> SpeakerReview | None:
        """The confirmed speaker's stretches with how each sounds, and the owner's decisions; None when the
        speaker is not confirmed as anyone."""
        reviews = self._reviews(recording, {speaker_id}, text=text)
        return reviews[0] if reviews else None

    def suspects(self, recordings: set[str] | None = None, *, units: bool = False) -> list[SpeakerReview]:
        """Confirmed speakers with stretches still waiting for the owner, where at least ``FLAG_SHARE`` of their
        judged speech sounds like someone else or nobody known; most suspect speech first. ``recordings``: only
        these; ``units``: with their stretches."""
        found: list[SpeakerReview] = []
        with self.library.read() as db:
            heard = {
                row[0]
                for row in db.execute(
                    "SELECT DISTINCT v.recording_id FROM reviewed v JOIN recordings r ON r.id = v.recording_id "
                    "AND r.transcript_id = v.transcript_id WHERE v.error = ''"
                )
            }
        for recording_id in sorted(heard):
            if recordings is not None and recording_id not in recordings:
                continue
            recording = self.library.get(recording_id)
            if recording is None:
                continue
            for review in self._reviews(recording, None, text=False):
                if review.status == "ready" and review.open and review.share >= FLAG_SHARE:
                    found.append(review if units else review.model_copy(update={"units": []}))
        found.sort(key=lambda r: -r.open_seconds)
        return found

    def _reviews(self, recording: Recording, only: set[str] | None, *, text: bool) -> list[SpeakerReview]:
        transcript_id = recording.transcript_id
        if transcript_id is None:
            return []
        with self.library.read() as db:
            confirmed = {
                row[0]: row[1]
                for row in db.execute(
                    "SELECT speaker_id, person_id FROM attributions WHERE recording_id = ? AND transcript_id = ? "
                    "AND decision = 'confirmed' AND person_id IS NOT NULL",
                    (recording.id, transcript_id),
                )
                if only is None or row[0] in only
            }
            if not confirmed:
                return []
            reviewed = {
                row[0]: row[1]
                for row in db.execute(
                    "SELECT speaker_id, error FROM reviewed WHERE recording_id = ? AND transcript_id = ?",
                    (recording.id, transcript_id),
                )
            }
            stored: dict[str, list[tuple[int, list[int], list[list[float]], bytes | None]]] = {}
            for row in db.execute(
                "SELECT speaker_id, unit, segments, parts, embedding FROM review_units WHERE recording_id = ? "
                "AND transcript_id = ? ORDER BY speaker_id, unit",
                (recording.id, transcript_id),
            ):
                stored.setdefault(row[0], []).append((row[1], json.loads(row[2]), json.loads(row[3]), row[4]))
            fixes = {
                row[0]: (row[1], row[2], row[3], bool(row[4]))
                for row in db.execute(
                    "SELECT segment, from_person, action, to_person, auto FROM segment_fixes WHERE recording_id = ? "
                    "AND transcript_id = ?",
                    (recording.id, transcript_id),
                )
            }
            everyone = dict(db.execute("SELECT id, name FROM people").fetchall())
            people, names, owners, matrix = self._samples(db, recording.id)
        transcript = self.library.cleaned(recording) if text else None
        result = []
        for speaker_id, person_id in sorted(confirmed.items()):
            review = SpeakerReview(
                recording_id=recording.id,
                filename=recording.filename,
                transcript_id=transcript_id,
                revision=recording.revision,
                speaker_id=speaker_id,
                person_id=person_id,
                name=everyone.get(person_id, ""),
                status="waiting",
            )
            result.append(review)
            if speaker_id not in reviewed:
                continue
            if reviewed[speaker_id]:
                review.status, review.error = "failed", reviewed[speaker_id]
                continue
            mine = [k for k, owner in enumerate(owners) if people[owner] == person_id]
            review.status = "ready" if mine else "no_samples"
            likely: dict[str, float] = {}
            for index, segments, parts, blob in stored.get(speaker_id, []):
                seconds = sum(end - start for start, end in parts)
                view = UnitView(
                    index=index,
                    segments=segments,
                    start=parts[0][0],
                    end=parts[-1][1],
                    seconds=round(seconds, 2),
                )
                fix = fixes.get(segments[0]) if segments else None
                if fix and fix[0] == person_id:
                    view.fix, view.to_person, view.auto = fix[1], fix[2], fix[3]
                    view.to_name = everyone.get(fix[2]) if fix[2] else None
                if transcript is not None:
                    view.text = " ".join(
                        " ".join(transcript.segments[i].text.split()) for i in segments if i < len(transcript.segments)
                    )
                if blob is not None and mine and len(matrix) and len(blob) == matrix.shape[1] * 4:
                    vector = _unit(np.frombuffer(blob, dtype=np.float32).astype(np.float64))
                    scores = matrix @ vector
                    best = np.full(len(people), -1.0)
                    np.maximum.at(best, owners, scores)
                    me = people.index(person_id)
                    own = float(best[me])
                    best[me] = -2.0
                    other_index = int(np.argmax(best)) if len(people) > 1 else -1
                    other = float(best[other_index]) if other_index >= 0 else -1.0
                    view.own, view.other = round(own, 3), (round(other, 3) if other_index >= 0 else None)
                    if other_index >= 0:
                        view.like, view.like_name = people[other_index], names[people[other_index]]
                    view.verdict = judge(own, max(other, -1.0), seconds)
                    if seconds >= JUDGE_SECONDS:
                        review.seconds += seconds
                    if view.verdict:
                        review.suspects += 1
                        review.suspect_seconds += seconds
                        # Left out by the review alone, it still waits for the owner's word if they are asked.
                        if view.fix is None or view.auto:
                            review.open += 1
                            review.open_seconds += seconds
                        if view.verdict == "other" and view.like:
                            likely[view.like] = likely.get(view.like, 0.0) + seconds
                review.units.append(view)
            review.seconds = round(review.seconds, 1)
            review.suspect_seconds = round(review.suspect_seconds, 1)
            review.open_seconds = round(review.open_seconds, 1)
            review.share = round(review.suspect_seconds / review.seconds, 3) if review.seconds else 0.0
            if likely:
                review.likely = max(likely, key=lambda p: likely[p])
                review.likely_name = names.get(review.likely)
        return result

    # ------------------------------------------------------------------ deciding

    def settle(self, recordings: set[str] | None = None) -> int:
        """Give speakers confirmed as the wrong person to the one they sound like (``REASSIGN_SHARE``), then leave
        every suspect stretch nobody has decided about out of the confirmed person's twin (``auto``), in
        ``recordings`` or all heard ones (all once a speaker is given away), and close the twins this changes. A
        decision of the owner's about a stretch is never replaced, and a stretch they kept stays theirs. Returns how
        many speakers were given away and segments left out."""
        from .team import Team

        moved = step = self._reassign(recordings)
        # A speaker given away takes their voice sample from the wrong person, so others confirmed as that person
        # on the strength of it may now sound unlike them too, in any recording: heard again until none moves.
        for _ in range(REASSIGN_ROUNDS):
            if not step:
                break
            recordings = None
            step = self._reassign(None)
            moved += step

        with self.library.read() as db:
            heard = sorted(
                row[0]
                for row in db.execute(
                    "SELECT DISTINCT v.recording_id FROM reviewed v JOIN recordings r ON r.id = v.recording_id "
                    "AND r.transcript_id = v.transcript_id WHERE v.error = ''"
                )
            )
        left = 0
        for recording_id in heard:
            if recordings is not None and recording_id not in recordings:
                continue
            recording = self.library.get(recording_id)
            if recording is None or recording.transcript_id is None:
                continue
            rows = [
                (segment, review.person_id)
                for review in self._reviews(recording, None, text=False)
                if review.status == "ready"
                for unit in review.units
                if unit.verdict and unit.fix is None
                for segment in unit.segments
            ]
            if not rows:
                continue
            now = dt.datetime.now(dt.UTC).isoformat()
            with self.library.transaction() as db:
                current = db.execute("SELECT transcript_id FROM recordings WHERE id = ?", (recording_id,)).fetchone()
                if current is None or current[0] != recording.transcript_id:
                    continue
                # Whoever was given a segment there before, should a stale decision about it give way.
                given = {
                    row[0]
                    for row in db.execute(
                        "SELECT to_person FROM segment_fixes WHERE recording_id = ? AND action = 'move'",
                        (recording_id,),
                    )
                    if row[0]
                }
                added = 0
                for segment, person_id in rows:
                    # A decision about the person, made meanwhile, wins; one about whom the speaker used to be
                    # confirmed as no longer holds and gives way.
                    added += db.execute(
                        "INSERT INTO segment_fixes (recording_id, transcript_id, segment, from_person, action, "
                        "to_person, updated_at, auto, version) VALUES (?, ?, ?, ?, 'exclude', NULL, ?, 1, ?) "
                        "ON CONFLICT (recording_id, transcript_id, segment) DO UPDATE SET from_person = "
                        "excluded.from_person, action = 'exclude', to_person = NULL, updated_at = excluded.updated_at, "
                        "auto = 1, version = excluded.version WHERE segment_fixes.from_person != excluded.from_person",
                        (recording_id, recording.transcript_id, segment, person_id, now, CLEANUP_VERSION),
                    ).rowcount
                if added:
                    Team._reopen(db, recording_id, {person_id for _, person_id in rows} | given)
                left += added
        return moved + left

    def refresh(self) -> int:
        """Judge again the stretches left out under other review rules (``collector.CLEANUP_VERSION``): one the
        current rules still leave out keeps its place under the new version, and the others go back into the
        person's twin. ``settle`` then leaves out what the current rules newly find. A speaker the review gave to
        someone else stays given: that also withdrew a voice sample, and the owner can undo it. Returns how many
        stretches went back."""
        stale = "auto = 1 AND action = 'exclude' AND COALESCE(version, ?) != ?"
        with self.library.read() as db:
            waiting = [
                row[0]
                for row in db.execute(
                    f"SELECT DISTINCT recording_id FROM segment_fixes WHERE {stale} ORDER BY recording_id",
                    (LEGACY_CLEANUP, CLEANUP_VERSION),
                )
            ]
        back = 0
        for recording_id in waiting:
            recording = self.library.get(recording_id)
            if recording is None or recording.transcript_id is None:
                continue
            still = {
                (segment, review.person_id)
                for review in self._reviews(recording, None, text=False)
                if review.status == "ready"
                for unit in review.units
                if unit.verdict
                for segment in unit.segments
            }
            with self.library.transaction() as db:
                current = db.execute("SELECT transcript_id FROM recordings WHERE id = ?", (recording_id,)).fetchone()
                if current is None or current[0] != recording.transcript_id:
                    continue
                rows = db.execute(
                    f"SELECT segment, from_person FROM segment_fixes WHERE recording_id = ? AND transcript_id = ? "
                    f"AND {stale}",
                    (recording_id, recording.transcript_id, LEGACY_CLEANUP, CLEANUP_VERSION),
                ).fetchall()
                returned: set[str] = set()
                for segment, person_id in rows:
                    key = (recording_id, recording.transcript_id, segment)
                    if (segment, person_id) in still:
                        db.execute(
                            "UPDATE segment_fixes SET version = ? WHERE recording_id = ? AND transcript_id = ? "
                            "AND segment = ?",
                            (CLEANUP_VERSION, *key),
                        )
                        continue
                    db.execute(
                        "DELETE FROM segment_fixes WHERE recording_id = ? AND transcript_id = ? AND segment = ?", key
                    )
                    returned.add(person_id)
                    back += 1
                if returned:
                    from .team import Team

                    Team._reopen(db, recording_id, returned)
        return back

    def _reassign(self, recordings: set[str] | None) -> int:
        """``settle``'s first step: speakers nearly all unlike their person and like one other, given to them."""
        from .team import Team

        team = Team(self.library)
        moved = 0
        for review in self.suspects(recordings, units=True):
            if review.share < REASSIGN_SHARE or not review.likely or not review.suspect_seconds:
                continue
            # The owner has started deciding about its stretches: theirs to finish.
            if any(unit.fix and not unit.auto for unit in review.units):
                continue
            toward = sum(u.seconds for u in review.units if u.verdict == "other" and u.like == review.likely)
            if toward / review.suspect_seconds < REASSIGN_LEAD:
                continue
            moved += team.reassign(
                review.recording_id, review.transcript_id, review.speaker_id, review.person_id, review.likely
            )
        return moved

    def fix(
        self,
        recording_id: str,
        transcript_id: str,
        revision: int,
        speaker_id: str,
        indices: list[int],
        action: FixAction | Literal["clear"],
        to_person: str | None = None,
    ) -> int:
        """The owner's decision about stretches of a confirmed speaker, for each of their segments: not the person
        (``exclude``), ``to_person``'s (``move``), the person's indeed (``keep``), or undecided again (``clear``).
        Closes the twins it changes (``Team._reopen``); returns the recording's new revision. ``Stale`` when the page
        decided on another transcript or revision; ``ValueError`` for an unknown stretch or person."""
        from .team import Stale, Team

        if not indices:
            raise ValueError("没有选中片段")
        if action == "move" and not to_person:
            raise ValueError("需要指定是谁")
        with self.library.transaction() as db:
            current = db.execute(
                "SELECT transcript_id, revision FROM recordings WHERE id = ?", (recording_id,)
            ).fetchone()
            if current is None or current["transcript_id"] != transcript_id or current["revision"] != revision:
                raise Stale()
            row = db.execute(
                "SELECT person_id FROM attributions WHERE recording_id = ? AND transcript_id = ? AND speaker_id = ? "
                "AND decision = 'confirmed'",
                (recording_id, transcript_id, speaker_id),
            ).fetchone()
            if row is None or not row[0]:
                raise ValueError("这个说话人还没有确认是谁")
            person_id = str(row[0])
            if action == "move":
                if to_person == person_id:
                    raise ValueError("改给的人和原来是同一个人")
                if not db.execute("SELECT 1 FROM people WHERE id = ?", (to_person,)).fetchone():
                    raise ValueError("找不到这个人")
            stored = {
                r[0]: json.loads(r[1])
                for r in db.execute(
                    "SELECT unit, segments FROM review_units WHERE recording_id = ? AND transcript_id = ? "
                    "AND speaker_id = ?",
                    (recording_id, transcript_id, speaker_id),
                )
            }
            if any(index not in stored for index in indices):
                raise ValueError("这个说话人没有这个片段")
            segments = sorted({segment for index in indices for segment in stored[index]})
            marks = ",".join("?" * len(segments))
            before = db.execute(
                f"SELECT action, to_person FROM segment_fixes WHERE recording_id = ? AND transcript_id = ? "
                f"AND segment IN ({marks}) AND from_person = ?",
                (recording_id, transcript_id, *segments, person_id),
            ).fetchall()
            affected = {person_id} | {r[1] for r in before if r[1]}
            db.execute(
                f"DELETE FROM segment_fixes WHERE recording_id = ? AND transcript_id = ? AND segment IN ({marks})",
                (recording_id, transcript_id, *segments),
            )
            if action != "clear":
                now = dt.datetime.now(dt.UTC).isoformat()
                db.executemany(
                    "INSERT INTO segment_fixes (recording_id, transcript_id, segment, from_person, action, "
                    "to_person, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    [
                        (
                            recording_id,
                            transcript_id,
                            s,
                            person_id,
                            action,
                            to_person if action == "move" else None,
                            now,
                        )
                        for s in segments
                    ],
                )
            if to_person and action == "move":
                affected.add(to_person)
            # Keeping what was the person's anyway changes nothing a twin reads.
            if action in {"exclude", "move"} or any(r[0] != "keep" for r in before):
                Team._reopen(db, recording_id, affected)
            db.execute("UPDATE recordings SET revision = revision + 1 WHERE id = ?", (recording_id,))
            return revision + 1
