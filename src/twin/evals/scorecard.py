"""Scorecard for the benchmark iteration loop: aggregate repeated runs, classify misses, compare with a baseline.

A suite directory holds ``<benchmark>/r<n>/`` run directories written by the benchmark adapters. The scorecard keeps
only question identifiers, question types, scores and outcome labels, never replies or histories, so it can be
compared across code changes without re-reading private run artifacts.
"""

from __future__ import annotations

import json
import math
import statistics
from pathlib import Path
from typing import Any

from ..util import open_private

BENCHMARKS = ("longmemeval", "personamem", "twin2k500")
HEADLINES = {
    "longmemeval": "评委判定准确率",
    "personamem": "选择题准确率",
    "twin2k500": "分类题精确匹配",
}
# Outcome labels point at the layer to inspect: preparation (profile build), answer rules (format), memory and
# retrieval (abstained or wrong while grounded), persona inference (wrong while inferred).
OUTCOMES = (
    "correct",
    "abstained",
    "wrong_grounded",
    "wrong_inferred",
    "wrong_general",
    "format",
    "preparation",
    "failed",
)


def _records(run: Path) -> list[dict[str, Any]]:
    with (run / "records.jsonl").open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def _item(benchmark: str, row: dict[str, Any]) -> tuple[str, str, float] | None:
    """(key, type, score) for a headline item, or ``None`` when the item is outside the headline metric."""
    ok = row.get("status") == "ok"
    if benchmark == "longmemeval":
        score = row.get("score")
        return row["question_id"], row["question_type"], float(score) if ok and score is not None else 0.0
    if benchmark == "personamem":
        return row["question_id"], row["question_type"], 1.0 if ok and row.get("score") is True else 0.0
    if row.get("kind") != "categorical" or row.get("gold_missing"):
        return None
    key = f"{row['participant'][:12]}:{row['question_id']}:{row['item_id']}"
    return key, row["question_id"], 1.0 if ok and (row.get("scores") or {}).get("exact_match") == 1 else 0.0


def _outcome(row: dict[str, Any], score: float) -> str:
    status = row.get("status")
    if status == "preparation_failed":
        return "preparation"
    if status != "ok":
        return "failed"
    if score >= 0.5:
        return "correct"
    persona = row.get("persona") or {}
    mode = persona.get("mode")
    # An abstention also lacks a valid label, so it is checked before format failures.
    if persona.get("abstain") or mode == "abstain":
        return "abstained"
    if row.get("format_failure"):
        return "format"
    return f"wrong_{mode}" if mode in ("grounded", "inferred", "general") else "failed"


def _run_summary(benchmark: str, run: Path) -> dict[str, Any]:
    items: dict[str, dict[str, Any]] = {}
    for row in _records(run):
        found = _item(benchmark, row)
        if found is not None:
            key, item_type, score = found
            items[key] = {"type": item_type, "score": score, "outcome": _outcome(row, score)}
    report = json.loads((run / "report.json").read_text(encoding="utf-8"))
    if report.get("pending") or report.get("dry_run"):
        raise ValueError(f"{run} is incomplete or a dry run")
    if len(items) == 0:
        raise ValueError(f"{run} has no headline items")
    summary: dict[str, Any] = {
        "headline": sum(i["score"] for i in items.values()) / len(items),
        "items": items,
        "fingerprints": report.get("fingerprints", {}),
    }
    if benchmark == "twin2k500":
        human = report.get("human_test_retest", {})
        summary["human_test_retest"] = human.get("categorical_accuracy")
        summary["numeric_scored"] = report.get("bounded_numeric_scored")
        summary["numeric_error"] = report.get("mean_normalized_absolute_error")
    if benchmark == "longmemeval":
        summary["judges"] = len(report.get("judges", []))
    return summary


def _spread(values: list[float]) -> dict[str, float]:
    return {
        "mean": statistics.fmean(values),
        "min": min(values),
        "max": max(values),
        "stdev": statistics.stdev(values) if len(values) > 1 else 0.0,
    }


def benchmark_scorecard(benchmark: str, directory: Path) -> dict[str, Any]:
    """Aggregate every ``r<n>`` run of one benchmark; all repeats must cover the same items."""
    runs = sorted(
        (path for path in directory.iterdir() if path.is_dir() and path.name[:1] == "r" and path.name[1:].isdigit()),
        key=lambda path: int(path.name[1:]),
    )
    if not runs:
        raise ValueError(f"{directory} has no r<n> run directories")
    summaries = [_run_summary(benchmark, run) for run in runs]
    keys = summaries[0]["items"].keys()
    if any(s["items"].keys() != keys for s in summaries):
        raise ValueError(f"{directory} repeats do not cover the same items")
    items = {
        key: {
            "type": summaries[0]["items"][key]["type"],
            "scores": [s["items"][key]["score"] for s in summaries],
            "outcomes": [s["items"][key]["outcome"] for s in summaries],
        }
        for key in sorted(keys)
    }
    types: dict[str, list[str]] = {}
    for key, item in items.items():
        types.setdefault(item["type"], []).append(key)
    outcomes = {name: 0 for name in OUTCOMES}
    for item in items.values():
        for outcome in item["outcomes"]:
            outcomes[outcome] += 1
    card: dict[str, Any] = {
        "metric": HEADLINES[benchmark],
        "repeats": len(runs),
        "items": len(items),
        "headline": _spread([s["headline"] for s in summaries]),
        "types": {
            name: statistics.fmean(statistics.fmean(items[k]["scores"]) for k in group)
            for name, group in sorted(types.items())
        }
        if benchmark != "twin2k500"
        else {},
        "outcomes": outcomes,
        "fingerprints": [s["fingerprints"] for s in summaries],
        "per_item": items,
    }
    for extra in ("human_test_retest", "numeric_scored", "numeric_error", "judges"):
        values = [s[extra] for s in summaries if s.get(extra) is not None]
        if values:
            card[extra] = _spread([float(v) for v in values])
    return card


def build_scorecard(suite: Path, metadata: dict[str, Any]) -> dict[str, Any]:
    benchmarks = {name: benchmark_scorecard(name, suite / name) for name in BENCHMARKS if (suite / name).is_dir()}
    if not benchmarks:
        raise ValueError(f"{suite} has no benchmark directories")
    return {"version": 1, **metadata, "benchmarks": benchmarks}


def sign_test(better: int, worse: int) -> float:
    """Two-sided exact sign test: how likely a split at least this uneven is when each moved item is a coin flip."""
    n = better + worse
    if n == 0:
        return 1.0
    tail: float = sum(math.comb(n, k) for k in range(min(better, worse) + 1)) / 2**n
    return min(1.0, 2 * tail)


def compare(candidate: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    """Headline and per-type deltas plus items that moved, on the benchmarks and items both scorecards share.

    A delta is ``beyond_noise`` when a two-sided exact sign test over the items whose mean score moved gives
    p < 0.05. Pairing by item keeps one or two items flipping back and forth, which a small set makes worth several
    points, from reading as a change.
    """
    if candidate.get("split") != baseline.get("split"):
        raise ValueError("Scorecards use different splits")
    result: dict[str, Any] = {}
    for name, cand in candidate["benchmarks"].items():
        base = baseline["benchmarks"].get(name)
        if base is None:
            continue
        shared = cand["per_item"].keys() & base["per_item"].keys()
        if shared != cand["per_item"].keys() or shared != base["per_item"].keys():
            raise ValueError(f"{name}: scorecards cover different items")
        ch, bh = cand["headline"], base["headline"]
        fixed, broken = [], []
        better = worse = 0
        for key in sorted(shared):
            before = statistics.fmean(base["per_item"][key]["scores"])
            after = statistics.fmean(cand["per_item"][key]["scores"])
            better += after > before
            worse += after < before
            if before < 0.5 <= after:
                fixed.append(key)
            elif after < 0.5 <= before:
                broken.append(key)
        p_value = sign_test(better, worse)
        result[name] = {
            "delta": ch["mean"] - bh["mean"],
            "better": better,
            "worse": worse,
            "p_value": p_value,
            "beyond_noise": p_value < 0.05,
            "types": {t: cand["types"][t] - base["types"].get(t, 0.0) for t in cand["types"] if t in base["types"]},
            "outcomes": {
                o: cand["outcomes"][o] / cand["repeats"] - base["outcomes"][o] / base["repeats"] for o in OUTCOMES
            },
            "fixed": fixed,
            "broken": broken,
        }
    return result


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def render_markdown(card: dict[str, Any], comparison: dict[str, Any] | None = None) -> str:
    lines = [
        f"# 评测成绩单（{card.get('split', '?')} 集）",
        "",
        f"代码 `{card.get('commit', '?')}` · {card.get('date', '?')} · 每个基准运行 {card.get('repeats', '?')} 次",
        "",
        "失败与弃权都计为错误。",
        "",
        "| 基准 | 指标 | 题数 | 平均 | 范围 | 与基线相比 |",
        "| :-- | :-- | --: | --: | :-: | :-- |",
    ]
    for name, bench in card["benchmarks"].items():
        h = bench["headline"]
        delta = ""
        if comparison and name in comparison:
            c = comparison[name]
            note = "超出波动" if c["beyond_noise"] else "在波动内"
            delta = (
                f"{c['delta'] * 100:+.1f} 个百分点（{note}：{c['better']} 题变好、{c['worse']} 题变差，"
                f"符号检验 p={c['p_value']:.2f}）"
            )
        lines.append(
            f"| {name} | {bench['metric']} | {bench['items']} | {_pct(h['mean'])} | "
            f"{_pct(h['min'])}–{_pct(h['max'])} | {delta} |"
        )
    for name, bench in card["benchmarks"].items():
        lines += ["", f"## {name}", ""]
        if "human_test_retest" in bench:
            lines.append(f"真人重测：{_pct(bench['human_test_retest']['mean'])}")
        if "numeric_error" in bench:
            lines.append(
                f"数值题：有界评分 {bench['numeric_scored']['mean']:.0f} 项，"
                f"平均归一化误差 {bench['numeric_error']['mean']:.3f}"
            )
        if "judges" in bench:
            lines.append(f"评委数：{bench['judges']['mean']:.0f}")
        if bench["types"]:
            lines += ["", "| 题型 | 平均 | 与基线相比 |", "| :-- | --: | --: |"]
            for item_type, value in bench["types"].items():
                d = (comparison or {}).get(name, {}).get("types", {}).get(item_type)
                lines.append(f"| {item_type} | {_pct(value)} | {'' if d is None else f'{d * 100:+.1f}'} |")
        lines += ["", "| 结果 | 每次平均题数 | 与基线相比 |", "| :-- | --: | --: |"]
        for outcome in OUTCOMES:
            d = (comparison or {}).get(name, {}).get("outcomes", {}).get(outcome)
            lines.append(
                f"| {outcome} | {bench['outcomes'][outcome] / bench['repeats']:.1f} | "
                f"{'' if d is None else f'{d:+.1f}'} |"
            )
        if comparison and name in comparison:
            c = comparison[name]
            lines += ["", f"由错变对 {len(c['fixed'])} 题，由对变错 {len(c['broken'])} 题。"]
            for label, keys in (("由错变对", c["fixed"]), ("由对变错", c["broken"])):
                if keys:
                    lines.append(
                        f"- {label}：" + "、".join(f"`{k}`" for k in keys[:30]) + (" 等" if len(keys) > 30 else "")
                    )
    return "\n".join(lines) + "\n"


def write_scorecard(suite: Path, card: dict[str, Any], comparison: dict[str, Any] | None) -> None:
    payload = {**card, **({"comparison": comparison} if comparison else {})}
    with open_private(suite / "scorecard.json") as stream:
        stream.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    with open_private(suite / "scorecard.md") as stream:
        stream.write(render_markdown(card, comparison))
