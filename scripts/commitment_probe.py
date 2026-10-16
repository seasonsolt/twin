"""Validate the commitment ledger (``twin.persona.ledger``) on fictional meetings with known answers.

Run with: uv run python scripts/commitment_probe.py [--examples DIR] [--out DIR] [--model NAME] [--effort LEVEL]

Each transcript in ``examples/commitments`` is stored the way a claimed recording is (the person under their name,
the others as 其他人N, every line starting with its time), then ``build_ledger`` reads the meetings in date order and
the entries are graded against ``gold.json``. Uses the locally logged-in Claude Code CLI, so no key is needed.
Results, including the store, land in ``data/commitment-probe/<time>/``; ``--rescore DIR`` grades a saved store again
without calling the model.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import Any

from twin.llm import ClaudeCLILLM
from twin.persona.ledger import KIND_LABELS, STATUS_LABELS, build_ledger, current_status
from twin.persona.schema import Source, SourceKind
from twin.persona.sources import parse_media
from twin.persona.store import PersonaStore

ROOT = Path(__file__).resolve().parent.parent
LINE = re.compile(r"^\[(\d{2}:\d{2})\] (\S+?)：(.*)$")
NAME = "张总"


def store_meeting(store: PersonaStore, path: Path) -> str:
    """Store one transcript as a claimed recording and return its source id."""
    text = path.read_text(encoding="utf-8")
    title = re.search(r"会议：(.+)", text)
    day = re.search(r"日期：(\d{4}-\d{2}-\d{2})", text)
    if not title or not day:
        raise ValueError(f"{path.name} 缺少会议或日期行")
    lines = [m.groups() for raw in text.splitlines() if (m := LINE.match(raw))]
    source = Source(
        source_id=path.stem,
        kind=SourceKind.AUDIO,
        title=title.group(1).strip(),
        origin=path.name,
        imported_at=dt.datetime.now().isoformat(timespec="seconds"),
        n_expressions=0,
        n_target=0,
        creation_time=f"{day.group(1)}T09:00:00",
        media_status="ready",
        text_state="raw",
    )
    parsed = parse_media(
        source, [(NAME if who == "本人" else who, f"[{at}] {words}", who == "本人") for at, who, words in lines]
    )
    store.put_source(parsed)
    return source.source_id


def predictions(store: PersonaStore, files: dict[str, str]) -> list[dict[str, Any]]:
    """The stored entries in the shape the grader reads: the meeting file, Chinese labels and the line's time."""
    rows = []
    entries = store.list_ledger()
    for e in entries:
        expression = store.get_expression(e.expression_id)
        at = LINE_TIME.match(expression.text) if expression else None
        rows.append(
            {
                "id": e.entry_id,
                "meeting": files[e.source_id],
                "kind": KIND_LABELS[e.kind],
                "at": at.group(1) if at else "",
                "quote": e.quote,
                "quote_exact": e.quote_exact,
                "owner": e.owner,
                "what": e.what,
                "due": e.due,
                "condition": e.condition,
                "relates_to": e.relates_to,
                "status": STATUS_LABELS[e.status] if e.status else "",
                "current": STATUS_LABELS[current_status(e, entries)],
                "confidence": e.confidence,
            }
        )
    return rows


LINE_TIME = re.compile(r"^\[(\d{2}:\d{2})\]")


def due_ok(gold: dict[str, Any], due: dt.date | None) -> bool | None:
    if "due_range" in gold:
        if due is None:
            return bool(gold.get("due_optional"))
        low, high = (dt.date.fromisoformat(d) for d in gold["due_range"])
        return low <= due <= high
    if "dues" in gold:
        allowed = {None if d is None else dt.date.fromisoformat(d) for d in gold["dues"]}
        return due in allowed
    return None


def checks(p: dict[str, Any], g: dict[str, Any], matched: dict[str, str]) -> dict[str, bool | None]:
    """Each attribute check of prediction ``p`` against gold item ``g``; None where the gold item does not grade it."""
    return {
        "owner": p["owner"] in g["owners"] if g["owners"] else None,
        "due": due_ok(g, p["due"]),
        "condition": bool(p["condition"]) if g.get("condition") else None,
        "status": p["status"] in g["status"] if "status" in g else None,
        "relates": matched.get(p["relates_to"] or "") in g["relates_to"] if "relates_to" in g else None,
        "current": p["current"] == g["current"] if "current" in g else None,
    }


def score(meetings: list[dict[str, Any]], ledger: list[dict[str, Any]]) -> dict[str, Any]:
    matched: dict[str, str] = {}  # predicted id -> gold id
    problems: list[str] = []
    counts = {k: [0, 0] for k in ("owner", "due", "relates", "status", "current", "condition", "quote")}
    required = found = predicted = traps = 0
    for meeting in meetings:
        preds = [row for row in ledger if row["meeting"] == meeting["file"]]
        predicted += len(preds)
        free = {g["id"]: g for g in meeting["items"]}
        # Pair each prediction with one gold item, required items and better-fitting pairs first, so that two items
        # anchored on the same line are not swapped (a swap would fail checks the prediction actually passes).
        pairs = [
            (not g["required"], -sum(ok is True for ok in checks(p, g, matched).values()), g["at"].index(p["at"]), p, g)
            for p in preds
            for g in meeting["items"]
            if p["kind"] in g["kinds"] and p["at"] in g["at"]
        ]
        for *_, p, g in sorted(pairs, key=lambda pair: pair[:3]):
            if p["id"] not in matched and g["id"] in free:
                del free[g["id"]]
                matched[p["id"]] = g["id"]
                p["gold"] = g["id"]
        for p in preds:
            if p["id"] in matched:
                continue
            if any(t["at"] == p["at"] for t in meeting["traps"]):
                traps += 1
                problems.append(f"{p['id']} 抽了不该抽的话（{p['at']}）：{p['quote']}")
            else:
                problems.append(f"{p['id']} 多抽：{p['kind']} {p['at']} {p['what']}")
        for g in meeting["items"]:
            if g["required"]:
                required += 1
                if g["id"] in free:
                    problems.append(f"{g['id']} 漏抽：{g['kinds'][0]} {g['at'][0]} {g['note']}")
                else:
                    found += 1
        golds = {g["id"]: g for g in meeting["items"]}
        for p in preds:
            counts["quote"][1] += 1
            if p["quote_exact"]:
                counts["quote"][0] += 1
            else:
                problems.append(f"{p['id']} 引文不是该行原文，已用整行代替：{p['at']} {p['quote']}")
            if p["id"] not in matched:
                continue
            g = golds[matched[p["id"]]]
            for key, ok in checks(p, g, matched).items():
                if ok is None:
                    continue
                counts[key][1] += 1
                counts[key][0] += ok
                if not ok:
                    value = {"relates": p["relates_to"], "owner": p["owner"]}.get(key, p.get(key))
                    problems.append(f"{p['id']}→{g['id']} {key} 不对：{value}（{g['note']}）")
    return {
        "required": required,
        "found": found,
        "predicted": predicted,
        "matched": len(matched),
        "traps": traps,
        "counts": counts,
        "problems": problems,
    }


def pct(a: int, b: int) -> str:
    return f"{a}/{b}（{a / b:.0%}）" if b else "—"


def report(result: dict[str, Any], ledger: list[dict[str, Any]], model: str) -> str:
    c = result["counts"]
    out = [
        f"# 承诺账本抽取探针 · {model}",
        "",
        "| 指标 | 结果 |",
        "| --- | --- |",
        f"| 召回（必抽条目） | {pct(result['found'], result['required'])} |",
        f"| 精确（抽出条目里有对应答案的） | {pct(result['matched'], result['predicted'])} |",
        f"| 抽了玩笑等不该抽的话 | {result['traps']} 条 |",
        f"| 负责人 | {pct(*c['owner'])} |",
        f"| 截止日期 | {pct(*c['due'])} |",
        f"| 前提条件 | {pct(*c['condition'])} |",
        f"| 进展关联到前序条目 | {pct(*c['relates'])} |",
        f"| 进展状态 | {pct(*c['status'])} |",
        f"| 承诺的当前状态 | {pct(*c['current'])} |",
        f"| 引文逐字匹配 | {pct(*c['quote'])} |",
        "",
        "## 问题",
        "",
        *(f"- {p}" for p in result["problems"] or ["无"]),
        "",
        "## 账本",
        "",
        "| id | 会议 | 类型 | 负责人 | 内容 | 截止 | 前提 | 关联 | 状态 | 置信 | 对应答案 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in ledger:
        cells = [
            r["id"],
            r["meeting"][:10],
            r["kind"],
            r["owner"],
            r["what"],
            r["due"] or "",
            r["condition"] or "",
            r["relates_to"] or "",
            r["status"] or "",
            f"{r['confidence']:.2f}",
            r.get("gold", "—"),
        ]
        out.append("| " + " | ".join(str(x).replace("|", "/") for x in cells) + " |")
    return "\n".join(out) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--examples", type=Path, default=ROOT / "examples" / "commitments")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--model", default="claude-opus-5-5")
    parser.add_argument("--effort", default="medium", choices=["low", "medium", "high", "xhigh", "max"])
    parser.add_argument("--rescore", type=Path, default=None, help="重新评分一次已保存的运行，不调用模型")
    args = parser.parse_args()
    out: Path = (
        args.rescore or args.out or ROOT / "data" / "commitment-probe" / dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    )
    out.mkdir(parents=True, exist_ok=True)
    gold = json.loads((args.examples / "gold.json").read_text(encoding="utf-8"))
    meetings: list[dict[str, Any]] = sorted(gold["meetings"], key=lambda m: m["file"])
    files = {Path(m["file"]).stem: m["file"] for m in meetings}
    with PersonaStore(out / "twin.db") as store:
        if args.rescore is None:
            if store.list_sources():
                raise SystemExit(f"{out} 里已有一次运行，换一个 --out 目录")
            for meeting in meetings:
                store_meeting(store, args.examples / meeting["file"])
            llm = ClaudeCLILLM(model=args.model)
            result = build_ledger(store, llm, NAME, effort=args.effort, log=lambda line: print(line, flush=True))
            print(f"读了 {result.sources} 场会议，记下 {result.entries} 条，丢弃 {result.dropped} 条")
        ledger = predictions(store, files)
    text = report(score(meetings, ledger), ledger, f"claude_cli:{args.model}")
    (out / "report.md").write_text(text, encoding="utf-8")
    print(text)
    print(f"结果在 {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
