"""Library-path evaluation: what the team recording library does with a meeting after the transcription service.

``eval-asr-session`` drives the personal-upload path (one reference voice, ``analyse()``). The team library takes a
different one, and this module runs that one with the production code, in a throwaway library: ``Library.transcribe``
(diarize, no reference voice), ``Team.classify`` (voice alone, against people's voice samples), the owner's decisions,
``Reviews.run`` (every confirmed speaker heard again stretch by stretch) and ``segment_owners`` (whose words a twin
keeps). Each stage is scored against the human reference:

* classify: share of speech (seconds of hypothesis speakers) taken by voice alone, right, wrong or left to the owner;
* review: stretches flagged as someone else's or a stranger's against who really spoke in them;
* twin: the share of a person's words that were spoken by someone else, and the person's own words kept, before the
  review, after an owner who hears every flagged stretch and judges it right, and after one who follows every flag.

The owner is simulated by an oracle: an undecided speaker is confirmed as whoever speaks most in it. A person's voice
samples are the near-field clips of ``voices/`` (``sessions.jsonl`` ``references``), embedded by the same service and
filed as samples of a recording that is not the one being classified, so ``Team`` and ``Reviews`` use them as they use
samples from other meetings. AliMeeting people attend one meeting each, so a sample comes from the same room and meeting
as its person's speech, only through another microphone: the results are an upper bound for that reason.
"""

from __future__ import annotations

import datetime as dt
import json
import shutil
import tempfile
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from ..media import review as review_rules
from ..media import team as team_rules
from ..media.ingest import CommandTranscriber
from ..media.library import Library, Recording, Transcript
from ..media.review import Reviews, SpeakerReview
from ..media.team import Team, segment_owners
from ..util import fingerprint, open_private, private_directory
from .asr import MODES, _sha256, bootstrap_ratio
from .asr_session import Session, SessionEngine, engine_identity, load_session_engines, load_sessions
from .diarization import Utterance, attributed_counts, majority_speaker, spoken_by

SAMPLE_PREFIX = "sample:"
# Acceptance set by the owner (2026-10-20): at most this share of the words in a twin are someone else's, after the
# review as the owner settles it; at most this share of the speech needs the owner's hand (speakers voice alone left
# undecided, and speakers the review puts to them); and nobody taken by voice alone as the wrong person.
GATE_FOREIGN = 0.05
GATE_MANUAL = 0.10
# The thresholds a run may try without editing code (``--set team.AUTO=0.6``): whatever the library flow reads at
# run time from these modules.
TUNABLE = {
    **{f"team.{n}": (team_rules, n) for n in ("SHOW", "AUTO", "AUTO_MARGIN", "AUTO_MIN_SECONDS", "NEW_MIN_SECONDS")},
    **{
        f"review.{n}": (review_rules, n)
        for n in ("MIN_SECONDS", "MAX_GAP", "JUDGE_SECONDS", "MARGIN", "STRANGER", "STRANGER_SECONDS", "FLAG_SHARE")
    },
}


def parse_overrides(items: Sequence[str]) -> dict[str, float]:
    """``NAME=VALUE`` pairs naming ``TUNABLE`` thresholds."""
    found: dict[str, float] = {}
    for item in items:
        name, _, value = item.partition("=")
        if name not in TUNABLE:
            raise ValueError(f"不能覆盖 {name!r}；可选：{', '.join(sorted(TUNABLE))}")
        try:
            found[name] = float(value)
        except ValueError:
            raise ValueError(f"{name} 的值不是数字：{value!r}") from None
    return found


@contextmanager
def overridden(values: Mapping[str, float]) -> Iterator[None]:
    """The thresholds set for the duration of a run, and put back after it."""
    before = {name: getattr(*TUNABLE[name]) for name in values}
    try:
        for name, value in values.items():
            setattr(*TUNABLE[name], value)
        yield
    finally:
        for name, value in before.items():
            setattr(*TUNABLE[name], value)


Progress = Callable[[str, str], None]
STAGES = ("classify", "owner", "review", "follow")


@dataclass
class Tally:
    """Sums per session, kept apart so intervals can resample sessions."""

    rows: dict[str, dict[str, float]] = field(default_factory=dict)

    def add(self, session: str, name: str, value: float) -> None:
        row = self.rows.setdefault(session, {})
        row[name] = row.get(name, 0.0) + value

    def total(self, name: str) -> float:
        return sum(row.get(name, 0.0) for row in self.rows.values())

    def ratio(self, numerator: str, denominator: str, seed: str) -> dict[str, Any]:
        sessions = sorted(self.rows)
        num = np.asarray([self.rows[s].get(numerator, 0.0) for s in sessions])
        den = np.asarray([self.rows[s].get(denominator, 0.0) for s in sessions])
        low, high = bootstrap_ratio(num, den, seed) if den.sum() else (0.0, 0.0)
        return {"rate": float(num.sum() / den.sum()) if den.sum() else 0.0, "ci95": [low, high]}


def utterances(transcript: Transcript) -> list[Utterance]:
    return [Utterance(s.start, s.end, s.speaker, s.text) for s in transcript.segments]


def prepare_library(
    root: Path, engine: SessionEngine, sessions: Sequence[Session], transcriber: CommandTranscriber, say: Progress
) -> tuple[Library, dict[str, Recording]]:
    """File and transcribe every session through ``Library.transcribe``; a finished recording is not run again."""
    library = Library(root)
    recordings: dict[str, Recording] = {}
    staging = Path(tempfile.mkdtemp(prefix="upload-", dir=root))
    try:
        for session in sessions:
            name = f"{session.id}{session.audio.suffix}"
            copy = staging / name
            shutil.copyfile(session.audio, copy)
            recording, _ = library.add(copy, name)
            if recording.status == "queued":
                say(engine.name, f"转写 {session.id}")
                recording = library.transcribe(recording.id, transcriber, lambda _done, _total: None)
            if recording.status != "ready":
                raise RuntimeError(f"{session.id} 没有转写成功：{recording.error or recording.status}")
            recordings[session.id] = recording
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return library, recordings


def file_samples(
    library: Library, team: Team, sessions: Sequence[Session], transcriber: CommandTranscriber
) -> dict[str, str]:
    """One person per reference voice, with that voice as a sample from a recording of its own; {person: speaker}."""
    identity: dict[str, str] = {}
    with library.read() as db:
        existing = dict(db.execute("SELECT name, id FROM people").fetchall())
    for session in sessions:
        for speaker, voice in sorted(session.voices.items()):
            person_id = existing.get(speaker)
            if person_id is None:
                person_id = team.add_person(speaker).id
                vector = transcriber.embed(voice)
                if vector is None:
                    raise RuntimeError(f"转写服务没有给出 {speaker} 的声纹")
                with library.transaction() as db:
                    db.execute(
                        "INSERT INTO voiceprints (person_id, recording_id, transcript_id, speaker_id, embedding, "
                        "active, created_at) VALUES (?, ?, 'sample', ?, ?, 1, ?)",
                        (
                            person_id,
                            SAMPLE_PREFIX + speaker,
                            speaker,
                            json.dumps(vector),
                            dt.datetime.now(dt.UTC).isoformat(),
                        ),
                    )
            identity[person_id] = speaker
    return identity


def _decisions(library: Library, recording: Recording) -> dict[str, tuple[str, str | None, bool]]:
    with library.read() as db:
        return {
            row[0]: (row[1], row[2], bool(row[3]))
            for row in db.execute(
                "SELECT speaker_id, decision, person_id, auto FROM attributions WHERE recording_id = ? "
                "AND transcript_id = ?",
                (recording.id, recording.transcript_id),
            )
        }


def _truth(reference: Sequence[Utterance], transcript: Transcript) -> dict[str, str | None]:
    hypothesis = utterances(transcript)
    return {s.id: majority_speaker(reference, hypothesis, s.id) for s in transcript.speakers}


def score_classify(
    tally: Tally,
    session: Session,
    transcript: Transcript,
    truth: dict[str, str | None],
    decided: dict[str, tuple[str, str | None, bool]],
    identity: dict[str, str],
    known: set[str],
) -> set[str]:
    """Seconds of speech by what ``Team.classify`` did: a speaker whose person has a sample is 'known'. Returns the
    speakers left to the owner."""
    left: set[str] = set()
    for speaker in transcript.speakers:
        who = truth[speaker.id]
        if who is None:
            continue
        decision, person_id, auto = decided.get(speaker.id, ("none", None, False))
        kind = "known" if who in known else "unknown"
        if not (auto and decision == "confirmed" and person_id):
            outcome = "undecided"
        elif identity.get(person_id) == who:
            outcome = "right"
        elif person_id not in identity:
            outcome = "newperson"
            identity[person_id] = who
        else:
            outcome = "wrong"
        tally.add(session.id, f"classify_{kind}_{outcome}", speaker.seconds)
        tally.add(session.id, f"classify_{kind}", speaker.seconds)
        tally.add(session.id, "speech_seconds", speaker.seconds)
        if outcome == "undecided":
            tally.add(session.id, "manual_seconds", speaker.seconds)
            left.add(speaker.id)
    return left


def confirm_by_oracle(
    library: Library,
    team: Team,
    recording_id: str,
    truth: dict[str, str | None],
    identity: dict[str, str],
) -> None:
    """The owner decides the speakers voice alone left: each is whoever speaks most in it (a person made if new)."""
    for speaker, who in sorted(truth.items()):
        recording = library.get(recording_id)
        assert recording is not None and recording.transcript_id is not None
        if who is None or speaker in _decisions(library, recording):
            continue
        by_speaker = {v: k for k, v in identity.items()}
        person_id = by_speaker.get(who)
        if person_id is None:
            person_id = team.add_person(who).id
            identity[person_id] = who
        team.decide(recording.id, recording.transcript_id, recording.revision, speaker, "confirm", person_id)


def score_review(
    tally: Tally,
    session: Session,
    reviews: Sequence[SpeakerReview],
    transcript: Transcript,
    identity: dict[str, str],
    handled: set[str],
) -> dict[str, list[int]]:
    """Flags against who really spoke; returns, per speaker, the indices of the truly foreign stretches. ``handled``:
    speakers the owner already decided by hand, whose speech counts once in the manual share."""
    reference = session.reference
    seconds = {s.id: s.seconds for s in transcript.speakers}
    foreign: dict[str, list[int]] = {}
    for review in reviews:
        target = identity.get(review.person_id)
        if review.status != "ready" or target is None:
            tally.add(session.id, "review_unready", 1)
            continue
        suspect = review.share >= review_rules.FLAG_SHARE and review.open > 0
        tally.add(session.id, "review_speakers", 1)
        tally.add(session.id, "review_put_to_owner", 1 if suspect else 0)
        if suspect:
            tally.add(session.id, "manual_review_seconds", seconds.get(review.speaker_id, 0.0))
            if review.speaker_id not in handled:
                tally.add(session.id, "manual_seconds", seconds.get(review.speaker_id, 0.0))
        impure = 0.0
        for unit in review.units:
            if unit.seconds < review_rules.JUDGE_SECONDS:
                continue
            parts = [(transcript.segments[i].start, transcript.segments[i].end) for i in unit.segments]
            own, others = spoken_by(reference, parts, target)
            bad = others > own
            flagged = bool(unit.verdict)
            name = ("foreign" if bad else "own") + ("_flagged" if flagged else "_kept")
            tally.add(session.id, f"review_{name}", unit.seconds)
            tally.add(session.id, f"review_{name}_n", 1)
            if bad:
                foreign.setdefault(review.speaker_id, []).append(unit.index)
                impure += unit.seconds
        tally.add(session.id, "review_impure_speakers", 1 if impure else 0)
        if suspect:
            tally.add(session.id, "review_put_impure", 1 if impure else 0)
    return foreign


def score_twin(
    tally: Tally,
    stage: str,
    session: Session,
    transcript: Transcript,
    speakers: dict[str, tuple[str, str | None]],
    fixes: dict[int, tuple[str, str, str | None]],
    identity: dict[str, str],
) -> None:
    """For each person with a known identity in this meeting: their words in a twin against what they really said."""
    hypothesis = utterances(transcript)
    owners = segment_owners(transcript, speakers, fixes)
    for person_id in sorted({o for o in owners if o}):
        target = identity.get(person_id)
        if target is None:
            continue
        mine = [
            Utterance(u.start, u.end, "X", u.text) for u, o in zip(hypothesis, owners, strict=True) if o == person_id
        ]
        for mode in MODES:
            counts = attributed_counts(session.reference, mine, ["X"], target, mode)
            tally.add(session.id, f"twin_{stage}_{mode}_errors", counts["errors"])
            tally.add(session.id, f"twin_{stage}_{mode}_tokens", counts["reference_tokens"])
            tally.add(session.id, f"twin_{stage}_{mode}_claimed", counts["claimed_tokens"])
            tally.add(session.id, f"twin_{stage}_{mode}_foreign", counts["misattributed_tokens"])


def follow_flags(reviews: Sequence[SpeakerReview]) -> dict[int, tuple[str, str, str | None]]:
    """Every flagged stretch of every heard speaker left out, as ``Reviews.settle`` does without asking anyone."""
    fixes: dict[int, tuple[str, str, str | None]] = {}
    for review in reviews:
        if review.status != "ready":
            continue
        for unit in review.units:
            if unit.verdict:
                for segment in unit.segments:
                    fixes[segment] = (review.person_id, "exclude", None)
    return fixes


class CachedService(CommandTranscriber):
    """The engine's command, remembering voiceprints: a voice sample's by its file, a stretch's by its recording and
    parts. Transcripts and these make a run of the library flow reach the service only for what is new."""

    def __init__(self, command: str, language: str, cache: Path) -> None:
        super().__init__(command, language)
        self.cache = cache
        self.found: dict[str, list[float] | None] = {}
        if cache.is_file():
            for line in cache.read_text(encoding="utf-8").splitlines():
                with suppress(ValueError, KeyError):
                    row = json.loads(line)
                    self.found[row["key"]] = row["embedding"]

    def _keep(self, key: str, vector: list[float] | None) -> None:
        self.found[key] = vector
        with self.cache.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"key": key, "embedding": vector}) + "\n")

    def embed(self, voice: Path) -> list[float] | None:
        key = "voice:" + _sha256(voice)
        if key not in self.found:
            vector = super().embed(voice)
            if vector is None:
                return None
            self._keep(key, vector)
        return self.found[key]

    def embed_spans(self, audio: Path, spans: list[list[tuple[float, float]]]) -> list[list[float] | None] | None:
        keys = [f"spans:{audio.parent.name}:{json.dumps(parts)}" for parts in spans]
        missing = [i for i, key in enumerate(keys) if key not in self.found]
        if missing:
            computed = super().embed_spans(audio, [spans[i] for i in missing])
            if computed is None:
                return None
            for i, vector in zip(missing, computed, strict=True):
                self._keep(keys[i], vector)
        return [self.found[key] for key in keys]


def evaluate_engine(
    engine: SessionEngine,
    sessions: Sequence[Session],
    base: Path,
    work: Path,
    say: Progress,
    transcriber: CommandTranscriber | None = None,
) -> dict[str, Any]:
    """``base`` keeps what the service computed (transcripts, voiceprints) and is only ever added to; ``work`` is a
    fresh copy of it for this run, so a change after the transcription (thresholds, review rules) is tried without
    reaching the service and without the last run's decisions."""
    private_directory(base)
    runner = transcriber or CachedService(engine.command, engine.language, base / "voiceprints.jsonl")
    prepare_library(base, engine, sessions, runner, say)
    shutil.rmtree(work, ignore_errors=True)
    private_directory(work.parent)
    shutil.copytree(base, work)
    library = Library(work)
    recordings = {
        s.id: r for s in sessions if (r := next((x for x in library.list() if x.filename.startswith(s.id)), None))
    }
    team, reviews = Team(library), Reviews(library)
    identity = file_samples(library, team, sessions, runner)
    known = set(identity.values())
    tally = Tally()
    items: list[dict[str, Any]] = []
    for session in sessions:
        say(engine.name, f"评估 {session.id}")
        recording = recordings[session.id]
        transcript = library.transcript(recording)
        assert transcript is not None and recording.transcript_id is not None
        truth = _truth(session.reference, transcript)
        team.classify(recording.id)
        decided = _decisions(library, library.get(recording.id) or recording)
        handled = score_classify(tally, session, transcript, truth, decided, identity, known)
        confirm_by_oracle(library, team, recording.id, truth, identity)
        recording = library.get(recording.id) or recording
        confirmed = {
            sid: (decision, person)
            for sid, (decision, person, _auto) in _decisions(library, recording).items()
            if decision == "confirmed"
        }
        score_twin(tally, "owner", session, transcript, confirmed, {}, identity)
        reviews.run(recording.id, runner)
        recording = library.get(recording.id) or recording
        heard = [h for sid in sorted(confirmed) if (h := reviews.speaker(recording, sid, text=False)) is not None]
        foreign = score_review(tally, session, heard, transcript, identity, handled)
        score_twin(tally, "follow", session, transcript, confirmed, follow_flags(heard), identity)
        for sid, indices in foreign.items():
            review = next(r for r in heard if r.speaker_id == sid)
            flagged = [u.index for u in review.units if u.verdict and u.index in set(indices)]
            if flagged and review.share >= review_rules.FLAG_SHARE and review.open:
                recording = library.get(recording.id) or recording
                assert recording.transcript_id is not None
                reviews.fix(recording.id, recording.transcript_id, recording.revision, sid, flagged, "exclude")
        with library.read() as db:
            fixes = {
                row[0]: (row[1], row[2], row[3])
                for row in db.execute(
                    "SELECT segment, from_person, action, to_person FROM segment_fixes WHERE recording_id = ?",
                    (recording.id,),
                )
            }
        score_twin(tally, "review", session, transcript, confirmed, fixes, identity)
        items.append(
            {
                "session": session.id,
                "speakers": {
                    s.id: {"seconds": round(s.seconds, 1), "truth": truth[s.id], "decision": decided.get(s.id)}
                    for s in transcript.speakers
                },
            }
        )
    return {"engine": engine.name, "tally": tally, "items": items}


def summarize(result: dict[str, Any]) -> dict[str, Any]:
    tally: Tally = result["tally"]
    seed = f"library:{result['engine']}"

    def split(prefix: str, kinds: Sequence[str]) -> dict[str, Any]:
        return {kind: tally.ratio(f"{prefix}_{kind}", prefix, f"{seed}:{prefix}:{kind}") for kind in kinds}

    outcomes = ("right", "wrong", "newperson", "undecided")
    twin: dict[str, Any] = {}
    for stage in ("owner", "follow", "review"):
        twin[stage] = {
            mode: {
                "cer": tally.ratio(f"twin_{stage}_{mode}_errors", f"twin_{stage}_{mode}_tokens", f"{seed}:t:{stage}"),
                "foreign": tally.ratio(f"twin_{stage}_{mode}_foreign", f"twin_{stage}_{mode}_claimed", f"{seed}:f"),
                "claimed_tokens": tally.total(f"twin_{stage}_{mode}_claimed"),
            }
            for mode in MODES
        }
    own = tally.total("review_own_flagged") + tally.total("review_own_kept")
    foreign = tally.total("review_foreign_flagged") + tally.total("review_foreign_kept")
    flagged = {
        "own_seconds": own,
        "foreign_seconds": foreign,
        "own_flagged": tally.total("review_own_flagged") / own if own else 0.0,
        "foreign_found": tally.total("review_foreign_flagged") / foreign if foreign else 0.0,
        "speakers": tally.total("review_speakers"),
        "put_to_owner": tally.total("review_put_to_owner"),
        "put_impure": tally.total("review_put_impure"),
        "impure_speakers": tally.total("review_impure_speakers"),
        "unready": tally.total("review_unready"),
    }
    wrong = tally.total("classify_known_wrong") + tally.total("classify_unknown_wrong")
    manual = tally.ratio("manual_seconds", "speech_seconds", f"{seed}:manual")
    review_foreign = twin["review"]["strict"]["foreign"]
    gate = {
        "auto_wrong_seconds": wrong,
        "foreign": review_foreign["rate"],
        "manual": manual["rate"],
        "passed": wrong == 0 and review_foreign["rate"] <= GATE_FOREIGN and manual["rate"] <= GATE_MANUAL,
    }
    return {
        "engine": result["engine"],
        "gate": gate,
        "manual": {**manual, "review_seconds": tally.total("manual_review_seconds")},
        "classify": {
            "known": {**split("classify_known", outcomes), "seconds": tally.total("classify_known")},
            "unknown": {**split("classify_unknown", outcomes), "seconds": tally.total("classify_unknown")},
        },
        "review": flagged,
        "twin": twin,
    }


def _pct(value: float) -> str:
    return f"{100 * value:.2f}%"


def _cell(entry: dict[str, Any]) -> str:
    low, high = entry["ci95"]
    return f"{_pct(entry['rate'])}（{_pct(low)}–{_pct(high)}）"


def render(cards: Sequence[dict[str, Any]], sessions: int, overrides: Mapping[str, float] | None = None) -> str:
    changed = "、".join(f"`{k}={v:g}`" for k, v in sorted((overrides or {}).items())) or "无（生产默认值）"
    lines = [
        "# 团队录音库流程评测",
        "",
        f"{sessions} 场；样本声音是同场近讲麦克风（上限口径）；区间按场次 bootstrap。改过的阈值：{changed}。",
        "",
        "## 验收",
        "",
        f"自动认错为 0；复核后分身里别人的话 ≤ {GATE_FOREIGN:.0%}；需要主人亲手处理的说话时长 ≤ {GATE_MANUAL:.0%}"
        "（自动归属没决定的说话人，加进入复核队列的说话人）。",
        "",
        "| 引擎 | 自动认错秒数 | 复核后别人的话 | 手工处理率（95% 区间） | 结论 |",
        "| --- | --- | --- | --- | --- |",
        *(
            f"| {c['engine']} | {c['gate']['auto_wrong_seconds']:.0f} | {_pct(c['gate']['foreign'])} | "
            f"{_cell(c['manual'])} | {'通过' if c['gate']['passed'] else '未通过'} |"
            for c in cards
        ),
        "",
        "## 自动归属（Team.classify，只看声音）",
        "",
        "按说话人秒数加权。「已知」= 这个人有样本声音；「未知」= 没有样本声音，正确做法是留给主人或新建。",
        "",
        "| 引擎 | 人群 | 秒数 | 正确 | 认错 | 新建未命名 | 留给主人 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for card in cards:
        for kind, label in (("known", "已知"), ("unknown", "未知")):
            row = card["classify"][kind]
            lines.append(
                f"| {card['engine']} | {label} | {row['seconds']:.0f} | {_cell(row['right'])} | "
                f"{_cell(row['wrong'])} | {_cell(row['newperson'])} | {_cell(row['undecided'])} |"
            )
    lines += [
        "",
        "## 已确认说话人逐段复核（media.review）",
        "",
        "判断一段是「别人的」按参考标注里该段内谁说话更多。",
        "",
        "| 引擎 | 本人段误标 | 他人段标出 | 已确认说话人 | 进复核队列 | 其中确有别人的话 | 实际混入别人话的说话人 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for card in cards:
        r = card["review"]
        lines.append(
            f"| {card['engine']} | {_pct(r['own_flagged'])} | {_pct(r['foreign_found'])} | {r['speakers']:.0f} | "
            f"{r['put_to_owner']:.0f} | {r['put_impure']:.0f} | {r['impure_speakers']:.0f} |"
        )
    lines += [
        "",
        "## 分身里这个人的话（严格口径）",
        "",
        "「主人确认后」= 没有复核；「听并判断」= 主人听每个标出的段并判断对错（真实操作写入 segment_fixes）；"
        "「照单全排除」= 对进入队列的说话人排除所有标出的段。别人的话占比 = 记到此人名下的字里别人说的比例。",
        "",
        "| 引擎 | 阶段 | 别人的话占比 | 此人话语 CER | 记入字数 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for card in cards:
        for stage, label in (("owner", "主人确认后"), ("review", "听并判断"), ("follow", "疑似自动排除")):
            entry = card["twin"][stage]["strict"]
            lines.append(
                f"| {card['engine']} | {label} | {_cell(entry['foreign'])} | {_cell(entry['cer'])} | "
                f"{entry['claimed_tokens']:.0f} |"
            )
    return "\n".join(lines) + "\n"


def run_library_benchmark(
    sessions_path: Path,
    engines: Sequence[SessionEngine],
    out: Path,
    cache_dir: Path | None = None,
    progress: Progress | None = None,
    overrides: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    sessions = load_sessions(sessions_path)
    private_directory(out)
    cache_dir = cache_dir if cache_dir is not None else sessions_path.parent / "library-cache"
    say = progress or (lambda _engine, _what: None)
    cards = []
    items: list[dict[str, Any]] = []
    for engine in engines:
        base = cache_dir / f"{engine.name}-{fingerprint(engine_identity(engine))[:12]}"
        with overridden(overrides or {}):
            result = evaluate_engine(engine, sessions, base, out / "work" / engine.name, say)
        cards.append(summarize(result))
        items += [{"engine": engine.name, **item} for item in result["items"]]
    changed = dict(overrides or {})
    card = {"sessions": len(sessions), "overrides": changed, "engines": cards}
    with open_private(out / "scorecard.json") as stream:
        json.dump(card, stream, ensure_ascii=False, indent=2)
    with open_private(out / "scorecard.md") as stream:
        stream.write(render(cards, len(sessions), changed))
    with open_private(out / "items.jsonl") as stream:
        for item in items:
            stream.write(json.dumps(item, ensure_ascii=False) + "\n")
    return card


__all__ = ["load_session_engines", "run_library_benchmark"]
