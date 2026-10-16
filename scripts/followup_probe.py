"""Run the abstention loop (弃权回流, ``twin.persona.followups``) once against a real model.

Run with: uv run python scripts/followup_probe.py [--out DIR] [--model NAME]

A fictional person writes a short note, the profile is built, and the twin is asked something the note does not cover:
it should abstain and the question should wait in the queue. The person answers it, the profile is built again, and the
same question is asked again: now the twin should answer, citing what came from the answer, and the question should stay
answered. Uses the locally logged-in Claude Code CLI (about six calls), so no key is needed. The store, ``report.md``
and ``result.json`` land in ``data/followup-probe/<time>/``.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from twin.config import LLMSettings, Settings, make_embedder, make_llm
from twin.embed import Embedder
from twin.llm import LLM
from twin.persona.chat import PersonaChat, index_persona
from twin.persona.followups import Followup, answer_followup, list_followups
from twin.persona.items import PersonaItem
from twin.persona.profile import build_profile
from twin.persona.schema import ChatReply, ChatTurn
from twin.persona.sources import parse_note
from twin.persona.store import PersonaStore

ROOT = Path(__file__).resolve().parent.parent
NAME = "张总"
NOTE = """我做决定先看回款，钱没进账户的单子不算成交。

客户的问题当周必须解决，不能拖到下周。

开会我只要结论和下一步，谁负责、什么时候交，说清楚就散会。"""
QUESTION = "华澜二期的报价底线是多少？"
ANSWER = "华澜是老客户，二期报价最低可以比标准价低一成，再低就不做了；实施费照样打包，不单列。"


class Counting:
    """An LLM that records the schema and duration of every structured call."""

    def __init__(self, llm: LLM) -> None:
        self.llm = llm
        self.calls: list[tuple[str, float]] = []

    def structured(self, *, schema: type[BaseModel], **kwargs: Any) -> Any:
        started = time.monotonic()
        result = self.llm.structured(schema=schema, **kwargs)
        self.calls.append((schema.__name__, round(time.monotonic() - started, 1)))
        return result

    def __getattr__(self, name: str) -> Any:
        return getattr(self.llm, name)


@dataclass
class LoopResult:
    first: ChatReply
    queued: list[Followup]
    source_title: str = ""
    answer_items: list[PersonaItem] = field(default_factory=list)
    second: ChatReply | None = None
    # Citations of the second reply that come from the answer: its items or its expression.
    cited: list[str] = field(default_factory=list)
    status_after: str = ""
    calls: list[tuple[str, float]] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return (
            self.first.abstain
            and self.second is not None
            and not self.second.abstain
            and bool(self.cited)
            and self.status_after == "answered"
        )


def run_loop(
    store: PersonaStore, llm: LLM, embedder: Embedder, settings: Settings, log: Callable[[str], None] = print
) -> LoopResult:
    """Build, ask, answer, build, ask again on an empty ``store``."""
    counting = Counting(llm)
    model: LLM = counting
    steps: list[str] = []

    def note(line: str) -> None:
        steps.append(line)
        log(line)

    def build(label: str) -> None:
        before = len(counting.calls)
        report = build_profile(store, model, settings, lambda line: None)
        index_persona(store, embedder, settings)
        failed = f"，失败 {len(report.failures)} 处" if report.failures else ""
        note(f"{label}：整理出 {report.items} 条档案{failed}（模型调用 {len(counting.calls) - before} 次）")

    def ask(label: str) -> ChatReply:
        before = len(counting.calls)
        reply = PersonaChat(store, model, embedder, settings).reply([ChatTurn(role="user", content=QUESTION)])
        verdict = f"弃权（{reply.abstain_reason}）" if reply.abstain else f"回答，把握 {reply.confidence}"
        note(f"{label}：{verdict}（模型调用 {len(counting.calls) - before} 次）\n\n> {reply.reply}")
        return reply

    store.put_source(parse_note(NOTE, settings, "工作习惯"))
    build("1. 用一段工作习惯笔记建档案")
    first = ask(f"2. 问「{QUESTION}」")
    queued = list_followups(store)
    result = LoopResult(first=first, queued=queued, calls=counting.calls, steps=steps)
    if not first.abstain or not queued:
        note("分身没有弃权或问题没有进队列，闭环无法继续")
        return result
    note(f"3. 进入待回答：{queued[0].question}，原因：{queued[0].reason or '（无）'}")
    followup, source = answer_followup(store, queued[0].followup_id, ANSWER, NAME)
    result.source_title = source.title
    note(f"4. 本人回答，存为资料「{source.title}」：{ANSWER}")
    build("5. 重新整理档案")
    result.answer_items = [i for i in store.list_items() if any(e.source_id == source.source_id for e in i.evidence)]
    for item in result.answer_items:
        note(f"   由回答生成：{item.statement}")
    result.second = ask(f"6. 再问「{QUESTION}」")
    from_answer = {i.item_id for i in result.answer_items} | {
        e.expression_id for e in store.list_expressions(source.source_id)
    }
    result.cited = [c for c in result.second.citations if c in from_answer]
    result.status_after = next(f.status for f in list_followups(store) if f.followup_id == followup.followup_id)
    note(f"7. 第二次回答引用了回答里的 {len(result.cited)} 处依据；队列里这条现在是 {result.status_after}")
    return result


def report(result: LoopResult, model: str) -> str:
    seconds = sum(s for _, s in result.calls)
    verdict = "闭环成立" if result.ok else "闭环没有完全成立"
    return "\n".join(
        [
            f"# 弃权回流闭环 · {model}",
            "",
            f"结论：{verdict}。模型调用 {len(result.calls)} 次，共 {seconds:.0f} 秒。",
            "",
            *(f"{step}\n" for step in result.steps),
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--model", default="claude-opus-5-5")
    args = parser.parse_args()
    out: Path = args.out or ROOT / "data" / "followup-probe" / dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True, exist_ok=True)
    db = out / "twin.db"
    if db.exists():
        raise SystemExit(f"{out} 里已有一次运行，换一个 --out 目录")
    settings = Settings(target_name=NAME, db_path=db, llm=LLMSettings(provider="claude_cli", model=args.model))
    with PersonaStore(db) as store:
        result = run_loop(store, make_llm(settings.llm), make_embedder(settings.embed), settings)
    text = report(result, f"claude_cli:{args.model}")
    (out / "report.md").write_text(text, encoding="utf-8")
    (out / "result.json").write_text(
        json.dumps(
            {
                "ok": result.ok,
                "first": result.first.model_dump(mode="json"),
                "second": result.second.model_dump(mode="json") if result.second else None,
                "answer_items": [i.model_dump(mode="json") for i in result.answer_items],
                "cited": result.cited,
                "status_after": result.status_after,
                "calls": result.calls,
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    print(f"\n{text}\n结果在 {out}")
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
