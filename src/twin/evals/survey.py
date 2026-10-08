"""Questionnaire evaluation: the twin answers a fixed multiple-choice survey, the person grades it.

Adapted from the normalized-accuracy protocol of Park et al. (arXiv:2411.10109): the person's own choices are
the gold answers, and a second, later grading of the same survey measures how consistently the person answers
themself; twin accuracy divided by that consistency is the normalized accuracy. Differences from the paper: the
twin may abstain (reported separately as coverage), and the person grades blind, choosing their own answer
before the twin's is shown.

Sheets hold the person's answers about themself: they are written owner-only and must stay out of memories,
or later twins would be graded on material copied from the key.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from importlib import resources
from pathlib import Path
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from ..persona.chat import PersonaChat
from ..persona.schema import ChatTurn
from ..util import open_private, private_directory, run_parallel
from .stats import _rng, bootstrap_grouped

SHEET_VERSION: Literal[1] = 1
LETTERS = "ABCDEFGH"
BOOTSTRAP_ROUNDS = 2000

_ASK = "请按你自己的真实情况，从上面选一个最接近的。第一行只写选项字母，比如「B」；第二行用一两句话说为什么。"
_ABSTAIN_OK = "如果你的资料里看不出来，就直接说不知道，不要猜。"
_FORCE = "资料不够时，也请选一个你认为最可能的，并说明是猜的。"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SurveyItem(_Model):
    id: str = Field(min_length=1)
    domain: str = Field(min_length=1)
    facet: str | None = None
    question: str = Field(min_length=1)
    options: list[str] = Field(min_length=2, max_length=len(LETTERS))
    # Ordered options (agreement or "like me" scales) also report how far off a miss is.
    ordinal: bool = False


class Instrument(_Model):
    version: str
    title: str
    items: list[SurveyItem] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique(self) -> Instrument:
        if len({item.id for item in self.items}) != len(self.items):
            raise ValueError("题目 id 重复")
        return self


class TwinAnswer(_Model):
    choice: int | None
    choices: list[int | None]
    modes: list[str]
    reply: str
    confidence: float
    citations: list[str] = Field(default_factory=list)


class PersonGrade(_Model):
    choice: int | None = None
    skipped: bool = False
    # 1-5: does the twin's stated reason sound like the person and hold for them.
    rating: int | None = Field(default=None, ge=1, le=5)
    note: str = ""


class SheetItem(_Model):
    item: SurveyItem
    twin: TwinAnswer | None = None
    person: PersonGrade = Field(default_factory=PersonGrade)

    @model_validator(mode="after")
    def _in_range(self) -> SheetItem:
        n = len(self.item.options)
        picks = [self.person.choice] + ([self.twin.choice, *self.twin.choices] if self.twin else [])
        if any(p is not None and not 0 <= p < n for p in picks):
            raise ValueError(f"题目 {self.item.id}：选项超出范围")
        return self


class Sheet(_Model):
    sheet_version: Literal[1] = SHEET_VERSION
    instrument: str
    created: dt.date
    as_of: dt.date | None = None
    repeats: int = Field(default=0, ge=0)
    force_choice: bool = False
    items: list[SheetItem]


def load_instrument(path: Path | None = None) -> Instrument:
    try:
        if path is None:
            raw = resources.files(__package__).joinpath("instruments/survey_zh_v1.json").read_bytes()
        else:
            raw = path.read_bytes()
        return Instrument.model_validate(json.loads(raw))
    except (OSError, ValueError, ValidationError) as e:
        raise ValueError(f"问卷无法读取或格式不对：{type(e).__name__}") from None


def item_prompt(item: SurveyItem, *, force_choice: bool = False) -> str:
    options = "\n".join(f"{LETTERS[i]}. {text}" for i, text in enumerate(item.options))
    return f"{item.question}\n{options}\n\n{_ASK}{_FORCE if force_choice else _ABSTAIN_OK}"


_LEAD = re.compile(r"^[\s「『“\"'（(【\[*]*([A-H])(?![A-Za-z])")


def parse_choice(text: str, n_options: int) -> int | None:
    """The option letter the reply leads with, else the single option quoted in full; otherwise None."""
    first = next((line for line in text.splitlines() if line.strip()), "")
    match = _LEAD.match(first)
    if match:
        index = LETTERS.index(match.group(1))
        return index if index < n_options else None
    return None


def _option_text_choice(text: str, options: Sequence[str]) -> int | None:
    hits = [i for i, option in enumerate(options) if option in text]
    return hits[0] if len(hits) == 1 else None


def _modal(choices: Sequence[int | None]) -> int | None:
    counts = Counter(c for c in choices if c is not None)
    if not counts:
        return None
    top = max(counts.values())
    # Ties go to the earliest repeat, so the result does not depend on option order.
    return next(c for c in choices if c is not None and counts[c] == top)


def ask_survey(
    chat: PersonaChat,
    instrument: Instrument,
    *,
    repeats: int = 1,
    as_of: dt.date | None = None,
    force_choice: bool = False,
    max_workers: int = 1,
    progress: Callable[[str], None] | None = None,
) -> Sheet:
    """Each repeat is an independent single turn that is never persisted to the chat log."""
    if repeats < 1:
        raise ValueError("repeats 必须为正数")
    jobs = [(item, r) for item in instrument.items for r in range(repeats)]

    def one(job: tuple[SurveyItem, int]) -> tuple[int | None, str, str, float, list[str]]:
        item, _ = job
        reply = chat.reply(
            [ChatTurn(role="user", content=item_prompt(item, force_choice=force_choice))], as_of=as_of, persist=False
        )
        choice = parse_choice(reply.reply, len(item.options))
        if choice is None:
            choice = _option_text_choice(reply.reply, item.options)
        if reply.mode == "abstain" and not force_choice:
            choice = None
        return choice, reply.mode, reply.reply, reply.confidence, list(reply.citations)

    results = run_parallel(one, jobs, max_workers)
    if any(isinstance(r, Exception) for r in results):
        raise RuntimeError("分身作答失败（详情已隐藏）")
    by_item: dict[str, list[tuple[int | None, str, str, float, list[str]]]] = defaultdict(list)
    for (item, _), result in zip(jobs, results, strict=True):
        assert not isinstance(result, Exception)
        by_item[item.id].append(result)
    rows: list[SheetItem] = []
    for item in instrument.items:
        answers = by_item[item.id]
        choices = [a[0] for a in answers]
        modal = _modal(choices)
        # Show the reply of the first repeat that agrees with the modal choice, so the reason fits the answer.
        shown = next((a for a in answers if a[0] == modal), answers[0])
        rows.append(
            SheetItem(
                item=item,
                twin=TwinAnswer(
                    choice=modal,
                    choices=choices,
                    modes=[a[1] for a in answers],
                    reply=shown[2],
                    confidence=shown[3],
                    citations=shown[4],
                ),
            )
        )
        if progress:
            progress(f"已答 {len(rows)}/{len(instrument.items)}")
    return Sheet(
        instrument=instrument.version,
        created=dt.date.today(),
        as_of=as_of,
        repeats=repeats,
        force_choice=force_choice,
        items=rows,
    )


def blank_sheet(instrument: Instrument) -> Sheet:
    """A sheet without twin answers, for the person's retest round."""
    items = [SheetItem(item=item) for item in instrument.items]
    return Sheet(instrument=instrument.version, created=dt.date.today(), items=items)


def write_sheet(path: Path, sheet: Sheet) -> None:
    private_directory(path.parent)
    with open_private(path) as handle:
        handle.write(sheet.model_dump_json(indent=1))


def read_sheet(path: Path) -> Sheet:
    try:
        return Sheet.model_validate_json(path.read_bytes())
    except (OSError, ValueError) as e:
        raise ValueError(f"答卷无法读取或格式不对：{type(e).__name__}") from None


def _rate(numerator: float, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _ci(values: dict[str, float], seed: str) -> tuple[float, float] | None:
    # Items are the independent units: one group per item.
    return bootstrap_grouped({key: [value] for key, value in values.items()}, seed)


def _block(rows: Sequence[SheetItem], seed: str) -> dict[str, Any]:
    graded = [r for r in rows if r.person.choice is not None]
    answered = [r for r in graded if r.twin is not None and r.twin.choice is not None]
    strict = {r.item.id: float(r.twin is not None and r.twin.choice == r.person.choice) for r in graded}
    hits = sum(strict.values())
    ordinal = [r for r in answered if r.item.ordinal]
    distance = [abs(r.twin.choice - r.person.choice) / (len(r.item.options) - 1) for r in ordinal if r.twin]  # type: ignore[operator]
    near = [abs(r.twin.choice - r.person.choice) <= 1 for r in ordinal if r.twin]  # type: ignore[operator]
    ratings = [r.person.rating for r in rows if r.person.rating is not None]
    repeated = [r.twin for r in rows if r.twin is not None and len(r.twin.choices) > 1 and r.twin.choice is not None]
    agreement = [sum(c == t.choice for c in t.choices) / len(t.choices) for t in repeated]
    return {
        "n_items": len(rows),
        "n_graded": len(graded),
        "n_answered": len(answered),
        "coverage": _rate(len(answered), len(graded)),
        "accuracy": _rate(hits, len(answered)),
        "strict_accuracy": _rate(hits, len(graded)),
        "strict_ci95": _ci(strict, seed),
        "chance": _rate(sum(1 / len(r.item.options) for r in graded), len(graded)),
        "ordinal_error": _rate(sum(distance), len(distance)),
        "ordinal_within_one": _rate(sum(near), len(near)),
        "reason_rating": _rate(sum(ratings), len(ratings)),
        "n_rated": len(ratings),
        "repeat_agreement": _rate(sum(agreement), len(agreement)),
    }


def _retest(first: Sheet, second: Sheet, seed: str) -> dict[str, Any]:
    """Consistency of the person with themself, and twin accuracy normalized by it (both on common items)."""
    later = {r.item.id: r.person.choice for r in second.items if r.person.choice is not None}
    common = [r for r in first.items if r.person.choice is not None and r.item.id in later]
    if not common:
        empty = ("consistency", "strict_accuracy", "normalized", "normalized_ci95")
        return {"n_common": 0, **dict.fromkeys(empty)}
    same = np.array([r.person.choice == later[r.item.id] for r in common], dtype=float)
    hit = np.array([r.twin is not None and r.twin.choice == r.person.choice for r in common], dtype=float)
    consistency = float(same.mean())
    accuracy = float(hit.mean())
    interval = None
    if len(common) >= 2:
        draws = _rng(seed).integers(0, len(common), size=(BOOTSTRAP_ROUNDS, len(common)))
        denominators = same[draws].mean(axis=1)
        ratios = hit[draws].mean(axis=1)[denominators > 0] / denominators[denominators > 0]
        if ratios.size:
            low, high = np.percentile(ratios, [2.5, 97.5])
            interval = (float(low), float(high))
    return {
        "n_common": len(common),
        "consistency": consistency,
        "strict_accuracy": accuracy,
        "normalized": accuracy / consistency if consistency else None,
        "normalized_ci95": interval,
    }


def score_sheet(sheet: Sheet, retest: Sheet | None = None) -> dict[str, Any]:
    if retest is not None and retest.instrument != sheet.instrument:
        raise ValueError("两份答卷不是同一版问卷")
    domains: dict[str, list[SheetItem]] = defaultdict(list)
    for row in sheet.items:
        domains[row.item.domain].append(row)
    return {
        "instrument": sheet.instrument,
        "repeats": sheet.repeats,
        "force_choice": sheet.force_choice,
        "as_of": sheet.as_of.isoformat() if sheet.as_of else None,
        "overall": _block(sheet.items, "survey:overall"),
        "domains": {name: _block(rows, f"survey:{name}") for name, rows in sorted(domains.items())},
        "retest": _retest(sheet, retest, "survey:retest") if retest is not None else None,
    }


DOMAIN_NAMES = {
    "values": "看重什么",
    "decision": "怎么做决定",
    "thinking": "怎么思考",
    "social": "和人相处",
    "expression": "说话方式",
    "personality": "性格",
    "life": "生活与喜好",
    "views": "看法",
}


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value:.0%}"


def _num(value: float | None) -> str:
    return "—" if value is None else f"{value:.2f}"


def _interval(value: tuple[float, float] | None) -> str:
    return "" if value is None else f"（{value[0]:.0%}–{value[1]:.0%}）"


def score_markdown(summary: dict[str, Any]) -> str:
    o = summary["overall"]
    lines = [
        f"# 问卷评测（{summary['instrument']}）",
        "",
        f"已阅 {o['n_graded']}/{o['n_items']} 题；分身作答 {o['n_answered']} 题，"
        f"每题 {summary['repeats']} 次{'，要求必选' if summary['force_choice'] else '，允许不知道'}。",
        "",
        "| 指标 | 数值 |",
        "| --- | --- |",
        f"| 准确率（弃权算错） | {_pct(o['strict_accuracy'])}{_interval(o['strict_ci95'])} |",
        f"| 准确率（只算作答的题） | {_pct(o['accuracy'])} |",
        f"| 作答率 | {_pct(o['coverage'])} |",
        f"| 随机猜的准确率 | {_pct(o['chance'])} |",
        f"| 量表题平均偏差（0–1） | {_num(o['ordinal_error'])} |",
        f"| 量表题差一档以内 | {_pct(o['ordinal_within_one'])} |",
        f"| 理由像不像你（1–5，{o['n_rated']} 题） | {_num(o['reason_rating'])} |",
        f"| 分身多次作答一致率 | {_pct(o['repeat_agreement'])} |",
    ]
    retest = summary.get("retest")
    if retest:
        lines += [
            "",
            "## 和你自己比",
            "",
            f"共同题目 {retest['n_common']} 题。",
            "",
            "| 指标 | 数值 |",
            "| --- | --- |",
            f"| 你两次作答的一致率（天花板） | {_pct(retest['consistency'])} |",
            f"| 分身准确率（同一批题） | {_pct(retest['strict_accuracy'])} |",
            f"| 归一化准确率 | {_num(retest['normalized'])}{_interval(retest['normalized_ci95'])} |",
        ]
    lines += ["", "## 分方面", "", "| 方面 | 已阅 | 准确率（弃权算错） | 作答率 | 随机猜 |"]
    lines.append("| --- | --- | --- | --- | --- |")
    for name, block in summary["domains"].items():
        lines.append(
            f"| {DOMAIN_NAMES.get(name, name)} | {block['n_graded']} | {_pct(block['strict_accuracy'])} | "
            f"{_pct(block['coverage'])} | {_pct(block['chance'])} |"
        )
    return "\n".join(lines) + "\n"
