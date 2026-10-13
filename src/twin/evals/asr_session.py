"""Whole-meeting ASR benchmark (layers L2, L3 and L5 of docs/ASR_EVAL.md): run the twin transcription command on
labelled sessions, then score segmentation, speakers and what the twin keeps as the person's words.

An engine is a twin `[asr] command` and is driven by the same `CommandTranscriber` and `analyse()` the upload path
uses, so the program under test is the one that runs in production. A reference voice changes only the
similarities, so each session is transcribed once with every evaluated person's voice (asr-funasr 1.2.1+ compares
them all in one run); a command that ignores the extra voices is run again per person. The first person's run serves
L2/L3. Results are cached per engine identity like eval-asr, so an interrupted run resumes and an unchanged engine
only rescores.
"""

from __future__ import annotations

import datetime as dt
import json
import platform
import time
import tomllib
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from ..media.claim import analyse
from ..media.ingest import CommandTranscriber, Segment, Speaker
from ..util import fingerprint, open_private, private_directory
from .asr import _NAME, MODES, _open_append, _processor, _sha256, bootstrap_ratio
from .diarization import (
    Utterance,
    attributed_counts,
    claim_outcome,
    cp_counts,
    diarization_error,
    majority_speaker,
    session_counts,
    speech_activity,
)
from .stats import mcnemar_exact_p

COLLARS = (0.25, 0.0)
Progress = Callable[[str, int, int], None]


@dataclass(frozen=True)
class Session:
    id: str
    audio: Path
    duration: float
    reference: list[Utterance]
    voices: dict[str, Path]  # speaker → reference voice; these speakers are evaluated as "the person"


@dataclass(frozen=True)
class SessionEngine:
    name: str
    command: str
    language: str = "zh"
    files: list[Path] = field(default_factory=list)  # hashed into the identity, e.g. the pack's pack.toml


@dataclass(frozen=True)
class Run:
    segments: list[Utterance]
    speakers: list[Speaker]
    seconds: float


def load_sessions(path: Path) -> list[Session]:
    """JSON lines of {id, audio, duration, reference, references?}; paths relative to the manifest."""
    sessions: list[Session] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict) or not all(isinstance(row.get(k), str) for k in ("id", "audio", "reference")):
            raise ValueError(f"场次清单第 {number} 行缺少 id/audio/reference")
        if any(s.id == row["id"] for s in sessions):
            raise ValueError(f"场次清单第 {number} 行 id 重复")
        duration = row.get("duration")
        if not isinstance(duration, int | float) or isinstance(duration, bool) or not duration > 0:
            raise ValueError(f"场次清单第 {number} 行 duration 无效")
        audio, reference = path.parent / row["audio"], path.parent / row["reference"]
        if not audio.is_file() or not reference.is_file():
            raise ValueError(f"场次清单第 {number} 行的音频或参考文件不存在")
        segments = json.loads(reference.read_text(encoding="utf-8")).get("segments")
        if not isinstance(segments, list):
            raise ValueError(f"{reference.name} 缺少 segments")
        utterances = [
            Utterance(float(s["start"]), float(s["end"]), str(s["speaker"]), str(s.get("text", ""))) for s in segments
        ]
        voices: dict[str, Path] = {}
        for speaker, voice in (row.get("references") or {}).items():
            file = path.parent / str(voice)
            if not file.is_file():
                raise ValueError(f"场次清单第 {number} 行的参考声音不存在：{voice}")
            if not any(u.speaker == speaker for u in utterances):
                raise ValueError(f"场次清单第 {number} 行：{speaker} 不在参考说话人中")
            voices[str(speaker)] = file.resolve()
        sessions.append(Session(row["id"], audio.resolve(), float(duration), utterances, voices))
    if not sessions:
        raise ValueError("场次清单为空")
    return sessions


def load_session_engines(path: Path) -> list[SessionEngine]:
    """TOML [[engine]] tables: name, command (a twin [asr] command), language?, files?; the first is the baseline."""
    rows = tomllib.loads(path.read_text(encoding="utf-8")).get("engine")
    if not isinstance(rows, list) or not rows:
        raise ValueError("引擎配置需要至少一个 [[engine]]")
    engines: list[SessionEngine] = []
    for row in rows:
        name, command = row.get("name"), row.get("command")
        if not isinstance(name, str) or not _NAME.fullmatch(name) or any(e.name == name for e in engines):
            raise ValueError(f"引擎名称无效或重复：{name!r}")
        if not isinstance(command, str) or not command.strip():
            raise ValueError(f"引擎 {name} 需要 command（twin [asr] command 的写法）")
        language = row.get("language", "zh")
        files = row.get("files", [])
        if not isinstance(language, str) or not isinstance(files, list) or not all(isinstance(f, str) for f in files):
            raise ValueError(f"引擎 {name} 的 language 必须是字符串，files 必须是路径列表")
        paths = [Path(f).expanduser().resolve() for f in files]
        missing = [str(p) for p in paths if not p.is_file()]
        if missing:
            raise ValueError(f"引擎 {name} 的 files 不存在：{', '.join(missing)}")
        engines.append(SessionEngine(name, command, language, paths))
    return engines


def engine_identity(engine: SessionEngine) -> dict[str, Any]:
    return {
        "command": engine.command,
        "language": engine.language,
        "files": {str(p): _sha256(p) for p in engine.files},
        "wire_version": 1,
    }


def _key(session: str, target: str) -> str:
    return f"{session}\x1f{target}"


def _read_runs(path: Path) -> dict[str, Run]:
    runs: dict[str, Run] = {}
    if not path.is_file():
        return runs
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
            run = Run(
                [Utterance(s["start"], s["end"], s["speaker"], s["text"]) for s in row["segments"]],
                [Speaker.model_validate(s) for s in row["speakers"]],
                float(row["seconds"]),
            )
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            continue  # a run killed mid-write leaves at most one partial last line
        runs[_key(row["session"], row["target"])] = run
    return runs


def _plan(session: Session) -> list[str]:
    """Targets to run: each evaluated person, or one run without a reference voice when there is none."""
    return sorted(session.voices) or [""]


def transcribe_sessions(
    engine: SessionEngine,
    sessions: Sequence[Session],
    cache_dir: Path,
    progress: Progress | None = None,
    transcriber: CommandTranscriber | None = None,
) -> tuple[dict[str, Run], dict[str, Any]]:
    """Return {key(session, target): Run}, running the command only for pairs missing from the engine's cache."""
    identity = engine_identity(engine)
    private_directory(cache_dir)
    cache = cache_dir / f"session-{engine.name}-{fingerprint(identity)[:12]}.jsonl"
    done = _read_runs(cache)
    wanted = [(s, t) for s in sessions for t in _plan(s)]
    todo = [(s, t) for s, t in wanted if _key(s.id, t) not in done]
    finished = len(wanted) - len(todo)
    if progress is not None:
        progress(engine.name, finished, len(wanted))
    if todo:
        runner = transcriber or CommandTranscriber(engine.command, engine.language)
        with _open_append(cache) as sink:

            def keep(session: Session, target: str, run: Run) -> None:
                nonlocal finished
                row = {
                    "session": session.id,
                    "target": target,
                    "segments": [u.__dict__ for u in run.segments],
                    "speakers": [s.model_dump() for s in run.speakers],
                    "seconds": run.seconds,
                }
                sink.write(json.dumps(row, ensure_ascii=False) + "\n")
                sink.flush()
                done[_key(session.id, target)] = run
                finished += 1
                if progress is not None:
                    progress(engine.name, finished, len(wanted))

            for session in sessions:
                pending = [t for s, t in todo if s is session]
                while pending:
                    target, others = pending[0], pending[1:]
                    runner.diarize = True
                    runner.reference = session.voices.get(target) if target else None
                    runner.references = {t: session.voices[t] for t in others}
                    began = time.monotonic()
                    try:
                        segments = runner.transcribe(session.audio, session.duration, lambda _done, _total: None)
                    except RuntimeError as error:
                        raise RuntimeError(f"引擎 {engine.name} 转写 {session.id} 失败：{error}") from None
                    utterances = [Utterance(s.start, s.end, s.speaker, s.text) for s in segments]
                    seconds = time.monotonic() - began
                    keep(session, target, Run(utterances, list(runner.speakers), seconds))
                    pending = others
                    for other in others:
                        # The same run seen from another person's voice; only the similarities differ.
                        values = [runner.similarities.get(s.id, {}) for s in runner.speakers]
                        if runner.speakers and all(other in v for v in values):
                            speakers = [
                                s.model_copy(update={"similarity": v[other]})
                                for s, v in zip(runner.speakers, values, strict=True)
                            ]
                            keep(session, other, Run(utterances, speakers, seconds))
                            pending = [t for t in pending if t != other]
    return {_key(s.id, t): done[_key(s.id, t)] for s, t in wanted}, identity


def _ratio(numerator: Sequence[float], denominator: Sequence[float], seed: str) -> dict[str, Any]:
    num, den = np.asarray(numerator, dtype=np.float64), np.asarray(denominator, dtype=np.float64)
    low, high = bootstrap_ratio(num, den, seed)
    return {"rate": float(num.sum() / den.sum()) if den.sum() else 0.0, "ci95": [low, high]}


@dataclass
class _Rows:
    """Per-session (or per session × person) numerators and denominators, kept for intervals and pairing."""

    values: dict[str, list[float]] = field(default_factory=dict)

    def add(self, name: str, value: float) -> None:
        self.values.setdefault(name, []).append(value)

    def get(self, name: str) -> list[float]:
        return self.values.get(name, [])


def _session_rows(sessions: Sequence[Session], runs: dict[str, Run]) -> _Rows:
    rows = _Rows()
    for session in sessions:
        run = runs[_key(session.id, _plan(session)[0])]
        hyp = run.segments
        for mode in MODES:
            counts = session_counts(session.reference, hyp, mode)
            rows.add(f"l2_errors_{mode}", counts["substitution"] + counts["deletion"] + counts["insertion"])
            rows.add(f"l2_sub_{mode}", counts["substitution"])
            rows.add(f"l2_del_{mode}", counts["deletion"])
            rows.add(f"l2_ins_{mode}", counts["insertion"])
            rows.add(f"tokens_{mode}", counts["reference_tokens"])
            cp = cp_counts(session.reference, hyp, mode)
            rows.add(f"cp_errors_{mode}", cp["errors"])
        activity = speech_activity(session.reference, hyp)
        rows.add("speech", activity["reference_speech"])
        rows.add("vad_missed", activity["missed"])
        rows.add("vad_false_alarm", activity["false_alarm"])
        rows.add("segments", len(hyp))
        rows.add("segment_seconds", sum(u.end - u.start for u in hyp))
        for collar in COLLARS:
            der = diarization_error(session.reference, hyp, collar)
            tag = f"{collar:g}"
            rows.add(f"der_errors_{tag}", der["missed"] + der["false_alarm"] + der["confusion"])
            rows.add(f"der_missed_{tag}", der["missed"])
            rows.add(f"der_false_alarm_{tag}", der["false_alarm"])
            rows.add(f"der_confusion_{tag}", der["confusion"])
            rows.add(f"der_speech_{tag}", der["reference_speech"])
        rows.add(
            "speaker_count_error", abs(len({u.speaker for u in hyp}) - len({u.speaker for u in session.reference}))
        )
        rows.add("seconds", run.seconds)
        rows.add("audio", session.duration)
    return rows


def _person_rows(sessions: Sequence[Session], runs: dict[str, Run]) -> tuple[_Rows, dict[str, int]]:
    rows, outcomes = _Rows(), {"correct": 0, "wrong": 0, "none": 0, "suggested_correct": 0, "people": 0}
    for session in sessions:
        for target in sorted(session.voices):
            run = runs[_key(session.id, target)]
            segments = [Segment(start=u.start, end=u.end, text=u.text, speaker=u.speaker) for u in run.segments]
            analysis = analyse(segments, run.speakers, has_reference=True)
            outcome = claim_outcome(session.reference, run.segments, analysis.claimed, target)
            outcomes[outcome] += 1
            outcomes["people"] += 1
            if analysis.suggested and majority_speaker(session.reference, run.segments, analysis.suggested) == target:
                outcomes["suggested_correct"] += 1
            # Not claimed automatically: the person picks their own speaker(s) by hand in the web UI.
            claimed = analysis.claimed or [
                s.id for s in run.speakers if majority_speaker(session.reference, run.segments, s.id) == target
            ]
            for mode in MODES:
                counts = attributed_counts(session.reference, run.segments, claimed, target, mode)
                rows.add(f"errors_{mode}", counts["errors"])
                rows.add(f"tokens_{mode}", counts["reference_tokens"])
                rows.add(f"claimed_{mode}", counts["claimed_tokens"])
                rows.add(f"misattributed_{mode}", counts["misattributed_tokens"])
            rows.add("auto", 1.0 if analysis.claimed else 0.0)
    return rows, outcomes


def score_engine(name: str, sessions: Sequence[Session], runs: dict[str, Run], seed: str) -> dict[str, Any]:
    s = _session_rows(sessions, runs)
    p, outcomes = _person_rows(sessions, runs)
    speech = sum(s.get("speech"))
    result: dict[str, Any] = {"engine": name, "segmentation": {}, "speakers": {}, "person": {}}
    for mode in MODES:
        tokens = s.get(f"tokens_{mode}")
        total = max(sum(tokens), 1)
        result["segmentation"][mode] = {
            "cer": _ratio(s.get(f"l2_errors_{mode}"), tokens, f"{seed}:{name}:l2:{mode}"),
            "substitution": sum(s.get(f"l2_sub_{mode}")) / total,
            "deletion": sum(s.get(f"l2_del_{mode}")) / total,
            "insertion": sum(s.get(f"l2_ins_{mode}")) / total,
            "reference_tokens": sum(tokens),
        }
        result["speakers"][mode] = {"cpcer": _ratio(s.get(f"cp_errors_{mode}"), tokens, f"{seed}:{name}:cp:{mode}")}
        if p.get(f"tokens_{mode}"):
            claimed = sum(p.get(f"claimed_{mode}"))
            result["person"][mode] = {
                "cer": _ratio(p.get(f"errors_{mode}"), p.get(f"tokens_{mode}"), f"{seed}:{name}:l5:{mode}"),
                "misattributed": sum(p.get(f"misattributed_{mode}")) / claimed if claimed else 0.0,
            }
    result["segmentation"]["speech_missed"] = sum(s.get("vad_missed")) / speech if speech else 0.0
    result["segmentation"]["speech_false_alarm"] = sum(s.get("vad_false_alarm")) / speech if speech else 0.0
    result["segmentation"]["segments"] = int(sum(s.get("segments")))
    result["segmentation"]["mean_segment_seconds"] = (
        sum(s.get("segment_seconds")) / sum(s.get("segments")) if sum(s.get("segments")) else 0.0
    )
    for collar in COLLARS:
        tag = f"{collar:g}"
        reference = s.get(f"der_speech_{tag}")
        denominator = max(sum(reference), 1e-9)
        result["speakers"][f"der_{tag}"] = {
            **_ratio(s.get(f"der_errors_{tag}"), reference, f"{seed}:{name}:der:{tag}"),
            "missed": sum(s.get(f"der_missed_{tag}")) / denominator,
            "false_alarm": sum(s.get(f"der_false_alarm_{tag}")) / denominator,
            "confusion": sum(s.get(f"der_confusion_{tag}")) / denominator,
        }
    result["speakers"]["speaker_count_error"] = sum(s.get("speaker_count_error")) / len(sessions)
    result["speakers"]["claims"] = outcomes
    result["person"]["auto_claimed"] = sum(p.get("auto")) / len(p.get("auto")) if p.get("auto") else None
    result["rtf"] = sum(s.get("seconds")) / sum(s.get("audio"))
    result["_rows"] = {"session": s.values, "person": p.values}
    return result


def _compare(baseline: dict[str, Any], candidate: dict[str, Any], seed: str) -> dict[str, Any]:
    """Per-session paired differences (candidate − baseline) for the headline rates, with a session sign test."""
    entry: dict[str, Any] = {"baseline": baseline["engine"], "candidate": candidate["engine"]}
    pairs = [
        ("segmentation_cer", "session", "l2_errors_strict", "tokens_strict"),
        ("cpcer", "session", "cp_errors_strict", "tokens_strict"),
        ("der_0.25", "session", "der_errors_0.25", "der_speech_0.25"),
        ("person_cer", "person", "errors_strict", "tokens_strict"),
    ]
    for label, level, numerator, denominator in pairs:
        a = baseline["_rows"][level].get(numerator, [])
        b = candidate["_rows"][level].get(numerator, [])
        if not a or len(a) != len(b):
            continue
        weight = baseline["_rows"][level][denominator]
        diff = [y - x for x, y in zip(a, b, strict=True)]
        low, high = bootstrap_ratio(
            np.asarray(diff, dtype=np.float64), np.asarray(weight, dtype=np.float64), f"{seed}:{label}"
        )
        better, worse = sum(x > y for x, y in zip(a, b, strict=True)), sum(x < y for x, y in zip(a, b, strict=True))
        entry[label] = {
            "difference": sum(diff) / max(sum(weight), 1e-9),
            "ci95": [low, high],
            "better": better,
            "worse": worse,
            "sign_test_p": mcnemar_exact_p(better, worse),
        }
    return entry


def run_session_benchmark(
    manifest: Path,
    engines: Sequence[SessionEngine],
    out: Path,
    *,
    cache_dir: Path,
    seed: str = "asr-session-v1",
    progress: Progress | None = None,
    transcriber: CommandTranscriber | None = None,
) -> dict[str, Any]:
    sessions = load_sessions(manifest)
    results: list[dict[str, Any]] = []
    identities: dict[str, dict[str, Any]] = {}
    all_runs: dict[str, dict[str, Run]] = {}
    for engine in engines:
        runs, identities[engine.name] = transcribe_sessions(engine, sessions, cache_dir, progress, transcriber)
        all_runs[engine.name] = runs
        results.append(score_engine(engine.name, sessions, runs, seed))
    comparisons = [_compare(results[0], other, seed) for other in results[1:]]
    card = {
        "version": 1,
        "manifest": {"name": manifest.name, "sha256": _sha256(manifest)},
        "sessions": len(sessions),
        "people": sum(len(s.voices) for s in sessions),
        "audio_hours": sum(s.duration for s in sessions) / 3600,
        "host": {"machine": platform.machine(), "processor": _processor()},
        "date": dt.datetime.now(dt.UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "engines": [
            {**{k: v for k, v in r.items() if k != "_rows"}, "identity": fingerprint(identities[r["engine"]])[:12]}
            for r in results
        ],
        "comparisons": comparisons,
    }
    _write(out, card, sessions, engines, all_runs)
    return card


def _write(
    out: Path,
    card: dict[str, Any],
    sessions: Sequence[Session],
    engines: Sequence[SessionEngine],
    runs: dict[str, dict[str, Run]],
) -> None:
    """scorecard.json/.md hold aggregates only; items.jsonl holds references and transcripts and stays private."""
    private_directory(out)
    with open_private(out / "scorecard.json") as stream:
        stream.write(json.dumps(card, ensure_ascii=False, indent=2))
    with open_private(out / "scorecard.md") as stream:
        stream.write(render_markdown(card))
    with open_private(out / "items.jsonl") as stream:
        for session in sessions:
            row: dict[str, Any] = {
                "session": session.id,
                "reference": [u.__dict__ for u in session.reference],
                "engines": {
                    e.name: {
                        target or "-": {
                            "segments": [u.__dict__ for u in runs[e.name][_key(session.id, target)].segments],
                            "speakers": [s.model_dump() for s in runs[e.name][_key(session.id, target)].speakers],
                        }
                        for target in _plan(session)
                    }
                    for e in engines
                },
            }
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")


def _pct(value: float) -> str:
    return f"{100 * value:.2f}%"


def _ci(entry: dict[str, Any]) -> str:
    low, high = entry["ci95"]
    return f"{_pct(entry['rate'])}（{_pct(low)}–{_pct(high)}）"


def render_markdown(card: dict[str, Any]) -> str:
    engines = card["engines"]
    lines = [
        "# ASR 整场评测成绩单",
        "",
        f"清单 `{card['manifest']['name']}`（sha256 {card['manifest']['sha256'][:12]}），{card['sessions']} 场 / "
        f"{card['audio_hours']:.2f} 小时，评测本人 {card['people']} 人次，"
        f"{card['host']['processor']}，{card['date']}。",
        "",
        "## L2 切分层（不分说话人）",
        "",
        "| 引擎 | 整场 CER（95% 区间） | 去口头语 CER | 替换 / 删除 / 插入 | 漏检语音 | 误检语音 "
        "| 片段数 | 平均片段 | RTF |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for e in engines:
        seg, strict = e["segmentation"], e["segmentation"]["strict"]
        lines.append(
            f"| {e['engine']} | {_ci(strict['cer'])} | {_pct(seg['nofill']['cer']['rate'])} | "
            f"{_pct(strict['substitution'])} / {_pct(strict['deletion'])} / {_pct(strict['insertion'])} | "
            f"{_pct(seg['speech_missed'])} | {_pct(seg['speech_false_alarm'])} | {seg['segments']} | "
            f"{seg['mean_segment_seconds']:.1f} 秒 | {e['rtf']:.4f} |"
        )
    lines += [
        "",
        "## L3 说话人层",
        "",
        "| 引擎 | DER collar 0.25（95% 区间） | 漏检 / 误检 / 混淆 | DER collar 0 | cpCER（95% 区间） | 去口头语 cpCER "
        "| 说话人数误差（场均） | 自动认领 正确 / 认错 / 未认领 | 首选正确 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for e in engines:
        spk, der = e["speakers"], e["speakers"]["der_0.25"]
        claims = spk["claims"]
        lines.append(
            f"| {e['engine']} | {_ci(der)} | {_pct(der['missed'])} / {_pct(der['false_alarm'])} / "
            f"{_pct(der['confusion'])} | {_pct(spk['der_0']['rate'])} | {_ci(spk['strict']['cpcer'])} | "
            f"{_pct(spk['nofill']['cpcer']['rate'])} | {spk['speaker_count_error']:.2f} | "
            f"{claims['correct']} / {claims['wrong']} / {claims['none']}（共 {claims['people']}） | "
            f"{claims['suggested_correct']} |"
        )
    if card["people"]:
        lines += [
            "",
            "## L5 流程层（记到本人名下的文字）",
            "",
            "未自动认领时按用户手动选对说话人计算。误归属 = 本人名下的字里，只有别人在说话的时段所占的比例。",
            "",
            "| 引擎 | 本人话语 CER（95% 区间） | 去口头语 | 他人误归属 | 自动认领比例 |",
            "| --- | --- | --- | --- | --- |",
        ]
        for e in engines:
            person = e["person"]
            lines.append(
                f"| {e['engine']} | {_ci(person['strict']['cer'])} | {_pct(person['nofill']['cer']['rate'])} | "
                f"{_pct(person['strict']['misattributed'])} | {_pct(person['auto_claimed'] or 0)} |"
            )
    lines += [
        "",
        "## 层间损失",
        "",
        "同一批音频上相邻两层的差值。说话人损失 = cpCER − 整场 CER；流程损失 = 本人话语 CER − cpCER。"
        "模型与切分损失需要同一批音频的 eval-asr 片段成绩单（`manifest-far.jsonl`）对照。",
        "",
        "| 引擎 | 整场 CER | cpCER | 本人话语 CER | 说话人损失 | 流程损失 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for e in engines:
        l2 = e["segmentation"]["strict"]["cer"]["rate"]
        l3 = e["speakers"]["strict"]["cpcer"]["rate"]
        l5 = e["person"].get("strict", {}).get("cer", {}).get("rate")
        person = (_pct(l5), f"{100 * (l5 - l3):+.2f} 点") if l5 is not None else ("—", "—")
        lines.append(
            f"| {e['engine']} | {_pct(l2)} | {_pct(l3)} | {person[0]} | {100 * (l3 - l2):+.2f} 点 | {person[1]} |"
        )
    if card["comparisons"]:
        lines += [
            "",
            "## 与基线逐场配对比较",
            "",
            "差 = 候选 − 基线，负数表示候选更好；区间按场次 bootstrap；符号检验按场次（本人话语按场次 × 本人）。",
            "",
            "| 候选 | 指标 | 差 | 95% 区间 | 变好 / 变差 | 符号检验 p |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for c in card["comparisons"]:
            for label in ("segmentation_cer", "cpcer", "der_0.25", "person_cer"):
                if label in c:
                    v = c[label]
                    lines.append(
                        f"| {c['candidate']} | {label} | {100 * v['difference']:+.2f} 点 | "
                        f"{100 * v['ci95'][0]:+.2f}–{100 * v['ci95'][1]:+.2f} | {v['better']} / {v['worse']} | "
                        f"{v['sign_test_p']:.2g} |"
                    )
    return "\n".join(lines) + "\n"
