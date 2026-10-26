"""Replay cached, real ASR voiceprints through the current team attribution rules.

Each meeting gets a fresh library and the same reference-voice enrollment. Human
annotations score the result; oracle decisions never become another meeting's
samples. This measures attribution only, without transcription or segment review.
"""

from __future__ import annotations

import hashlib
import json
import math
import tempfile
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from ..media.collector import ATTRIBUTION_VERSION
from ..media.ingest import Segment
from ..media.library import Library, Recording, Transcript
from ..media.team import Team
from ..util import fingerprint, open_private, private_directory
from .asr import _sha256
from .asr_library import TUNABLE, Tally, _decisions, _truth, score_classify, summarize
from .asr_session import Run, Session, _key, _read_runs, load_sessions
from .diarization import spoken_by

SPLIT_SEED = "attribution-meetings-v1"


def _ratio(tally: Tally, numerator: str, denominator: str, seed: str) -> dict[str, Any]:
    """Undefined quality rates stay unknown, rather than looking like zero errors."""
    den = tally.total(denominator)
    return {
        **(tally.ratio(numerator, denominator, seed) if den else {"rate": None, "ci95": None}),
        "numerator_seconds": tally.total(numerator),
        "denominator_seconds": den,
    }


def select_meetings(sessions: Sequence[Session], split: str, seed: str) -> list[Session]:
    """A meeting (or a declared correlated group) always stays wholly in one fold."""
    if split not in {"all", "dev", "formal"}:
        raise ValueError("split 必须是 all、dev 或 formal")
    return [
        session
        for session in sessions
        if split == "all"
        or ("dev" if hashlib.sha256(f"{seed}:{session.group or session.id}".encode()).digest()[0] % 2 else "formal")
        == split
    ]


def _file_run(library: Library, session: Session, run: Run) -> Recording:
    """File cached timing and voiceprints; no audio decoding, transcript text or ASR calls."""
    transcript = Transcript(
        id="cached",
        recording_id="meeting",
        created_at="2000-01-01T00:00:00+00:00",
        duration_s=session.duration,
        segments=[Segment(start=s.start, end=s.end, speaker=s.speaker, text="") for s in run.segments],
        speakers=run.speakers,
    )
    folder = library.folder("meeting")
    private_directory(folder)
    library.write_transcript(folder, transcript)
    recording = Recording(
        id="meeting",
        sha256="cached",
        filename="cached.wav",
        size=0,
        kind="audio",
        status="ready",
        transcript_id=transcript.id,
        segments=len(transcript.segments),
        speakers=len(transcript.speakers),
        created_at=transcript.created_at,
        updated_at=transcript.created_at,
    )
    values = recording.model_dump()
    with library.transaction() as db:
        db.execute(
            f"INSERT INTO recordings ({', '.join(values)}) VALUES ({', '.join('?' * len(values))})",
            tuple(values.values()),
        )
    return recording


def evaluate_attribution(
    sessions: Sequence[Session], runs: Mapping[str, Run], enrollment: Mapping[str, list[float]]
) -> dict[str, Any]:
    """Score actual cached hypotheses against annotations, with no cross-meeting feedback."""
    tally = Tally()
    taken: list[dict[str, Any]] = []
    items: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="twin-attribution-") as temporary:
        for index, session in enumerate(sessions):
            library = Library(Path(temporary) / str(index))
            recording = _file_run(library, session, runs[session.id])
            team = Team(library)
            identity = {}
            for reference_id, vector in sorted(enrollment.items()):
                person = team.add_person(reference_id)
                identity[person.id] = reference_id
                with library.transaction() as db:
                    db.execute(
                        "INSERT INTO voiceprints (person_id, recording_id, transcript_id, speaker_id, embedding, "
                        "active, created_at) VALUES (?, ?, 'reference', ?, ?, 1, ?)",
                        (
                            person.id,
                            "reference:" + reference_id,
                            reference_id,
                            json.dumps(vector),
                            recording.created_at,
                        ),
                    )
            transcript = library.transcript(recording)
            assert transcript is not None
            truth = _truth(session.reference, transcript)
            tiers = team.voice_tiers(recording)
            team.classify(recording.id)
            decisions = _decisions(library, recording)
            # The legacy scorer gives newly created anonymous people an oracle label
            # for its own tallies. That must never turn them into enrolled identities.
            score_classify(
                tally, session, transcript, truth, decisions, dict(identity), set(enrollment), tiers, taken=taken
            )
            for speaker in transcript.speakers:
                if truth[speaker.id] is None:
                    tally.add(session.id, "unscored_hypothesis_seconds", speaker.seconds)
                    continue
                decision, person_id, auto = decisions.get(speaker.id, ("none", None, False))
                if not auto or decision != "confirmed" or not person_id:
                    continue
                target = identity.get(person_id)
                # Newly made unnamed people are not successful named-person recognition.
                if target is None or target not in enrollment:
                    tally.add(session.id, "new_unnamed_seconds", speaker.seconds)
                    continue
                tally.add(session.id, "auto_named_seconds", speaker.seconds)
                if target != truth[speaker.id]:
                    tally.add(session.id, "auto_wrong_cluster_seconds", speaker.seconds)
                parts = [(s.start, s.end) for s in transcript.segments if s.speaker == speaker.id]
                own, other = spoken_by(session.reference, parts, target)
                tally.add(session.id, "auto_reference_speech_seconds", own + other)
                tally.add(session.id, "auto_other_only_seconds", other)
            row = tally.rows[session.id]
            items.append({"session": session.id, "group": session.group or session.id, "counts": dict(row)})
    # Correlated groups, when declared, are bootstrap units; no individual speaker resampling.
    grouped = Tally()
    for item in items:
        for name, value in item["counts"].items():
            grouped.add(item["group"], name, value)
    previous = summarize({"engine": "cached-attribution", "tally": grouped, "taken": taken})
    questions = {
        **previous["asked"],
        "mean": tally.total("asked") / len(sessions) if sessions else 0.0,
        "max": max((row.get("asked", 0.0) for row in tally.rows.values()), default=0.0),
    }
    return {
        "stage": "attribution_only",
        "attribution_version": ATTRIBUTION_VERSION,
        "automatic_named_coverage": _ratio(grouped, "auto_named_seconds", "speech_seconds", "attribution:coverage"),
        "automatic_other_only_fraction": _ratio(
            grouped, "auto_other_only_seconds", "auto_reference_speech_seconds", "attribution:other"
        ),
        "automatic_wrong_cluster_fraction_proxy": _ratio(
            grouped, "auto_wrong_cluster_seconds", "auto_named_seconds", "attribution:wrong-cluster"
        ),
        "new_unnamed_speech_fraction": _ratio(grouped, "new_unnamed_seconds", "speech_seconds", "attribution:unnamed"),
        "automatic_wrong_cluster_seconds_proxy": previous["gate"]["auto_wrong_seconds"],
        "unscored_hypothesis_seconds": tally.total("unscored_hypothesis_seconds"),
        "classify": previous["classify"],
        "workload_proxy": {
            "unresolved_speech": _ratio(grouped, "manual_seconds", "speech_seconds", "attribution:manual"),
            "confirmation_questions": questions,
            "actual_human_seconds": None,
            "note": "语音时长和≥15秒的未决说话人数是工作量代理；"
            "不含未命名人物命名、跨会议声音分组、试听、抽查或逐段复核，不是人工工时。",
        },
        "items": items,
    }


def run_attribution_benchmark(
    sessions_path: Path,
    cache_path: Path,
    enrollment_path: Path,
    out: Path,
    *,
    provenance_path: Path,
    split: str = "all",
    seed: str = SPLIT_SEED,
) -> dict[str, Any]:
    """Use native eval-asr-session JSONL and voice:<audio SHA256> embedding cache; never reach a service."""
    sessions = select_meetings(load_sessions(sessions_path), split, seed)
    if not sessions:
        raise ValueError("所选会议划分为空")
    cached, _ = _read_runs(cache_path)
    runs = {}
    enrollment: dict[str, list[float]] = {}
    voice_cache = {
        row["key"]: row["embedding"]
        for line in enrollment_path.read_text().splitlines()
        if line.strip() and (row := json.loads(line))
    }
    voice_hashes: dict[str, str] = {}
    for session in sessions:
        # Different reference targets share timing and cluster embeddings in this cache format.
        key = _key(session.id, sorted(session.voices)[0] if session.voices else "")
        if key not in cached:
            raise ValueError(f"转写缓存缺少会议 {session.id}")
        runs[session.id] = cached[key]
        for speaker, voice in session.voices.items():
            digest = _sha256(voice)
            vector = voice_cache.get("voice:" + digest)
            if (
                not isinstance(vector, list)
                or not vector
                or any(not isinstance(v, int | float) or isinstance(v, bool) or not math.isfinite(v) for v in vector)
                or not any(vector)
            ):
                raise ValueError(f"参考声纹缓存缺少或无效：{speaker}")
            if speaker in voice_hashes and voice_hashes[speaker] != digest:
                raise ValueError(f"同一人物存在不同参考声音：{speaker}")
            voice_hashes[speaker] = digest
            enrollment[speaker] = vector
    widths = {len(v) for v in enrollment.values()}
    for run in runs.values():
        if not run.speakers or any(s.embedding is None or len(s.embedding) not in widths for s in run.speakers):
            raise ValueError("转写缓存缺少兼容的说话人声纹")
    origins = {}
    for line in sessions_path.read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            origins[row["id"]] = row.get("voice_from", {})
    source_counts: Counter[str] = Counter()
    for session in sessions:
        for speaker in session.voices:
            source = origins[session.id].get(speaker)
            source_counts["same_meeting" if source == session.id else "other_meeting" if source else "undeclared"] += 1
    provenance = json.loads(provenance_path.read_text())
    protocol = {
        "split": split,
        "seed": seed,
        "meetings": [s.id for s in sessions],
        "bootstrap_groups": sorted({s.group or s.id for s in sessions}),
        "audio_hours": sum(s.duration for s in sessions) / 3600,
        "manifest_sha256": _sha256(sessions_path),
        "transcription_cache_sha256": _sha256(cache_path),
        "enrollment_cache_sha256": _sha256(enrollment_path),
        "meeting_audio_sha256": {s.id: _sha256(s.audio) for s in sessions},
        "annotation_sha256": fingerprint(
            {s.id: [(u.start, u.end, u.speaker, u.text) for u in s.reference] for s in sessions}
        ),
        "reference_audio_sha256": voice_hashes,
        "attribution_rules": {
            name: getattr(module, attribute)
            for name, (module, attribute) in TUNABLE.items()
            if name.startswith("team.")
        },
        "code_sha256": {
            "evaluator": _sha256(Path(__file__)),
            "team": _sha256(Path(__file__).parent.parent / "media" / "team.py"),
            "library": _sha256(Path(__file__).parent.parent / "media" / "library.py"),
            "attribution": _sha256(Path(__file__).parent.parent / "media" / "attribution.py"),
            "library_scoring": _sha256(Path(__file__).with_name("asr_library.py")),
        },
        "reference_origins": dict(source_counts),
        "cross_meeting_enrollment_verified": False,
        "provenance": provenance,
        "limits": "同场参考声音会使认领偏乐观；划分只隔离会议/声明的group，不证明声纹跨会议泛化。"
        "数据有无人工金标由来源声明，工具不替来源背书。原文、向量不进入成绩单。",
    }
    result = evaluate_attribution(sessions, runs, enrollment)
    private_directory(out)
    card = {"protocol": protocol, **result}
    with open_private(out / "scorecard.json") as stream:
        json.dump(card, stream, ensure_ascii=False, indent=2)
    with open_private(out / "scorecard.md") as stream:

        def percent(metric: dict[str, Any]) -> str:
            return f"{metric['rate']:.2%}" if metric["rate"] is not None else "未测到可评分语音"

        stream.write(
            "# 缓存自动归属基线\n\n"
            f"{len(sessions)} 场，{protocol['audio_hours']:.3f} 小时；按会议/声明的组重采样。\n\n"
            f"自动认到已知人物：{percent(result['automatic_named_coverage'])}；"
            f"另有新建未命名人物语音：{percent(result['new_unnamed_speech_fraction'])}，命名工作未计。\n\n"
            f"自动认领区间内，仅其他人在说话的比例：{percent(result['automatic_other_only_fraction'])}"
            "（本人同时说话的重叠区不计错，静音不计分母）。\n\n"
            f"人工确认语音占比代理：{percent(result['workload_proxy']['unresolved_speech'])}；"
            f"未决说话人确认次数代理：{result['workload_proxy']['confirmation_questions']['total']:.0f}。"
            "实际人工工时未测。\n\n"
            "只运行当前归属规则；不重转写、不调模型、不做逐段复核，不代表当前端到端效果。"
            "参考声音来源及转写/声纹版本见 scorecard.json；同场取样不能称跨会议留出验证。\n"
        )
    return card
