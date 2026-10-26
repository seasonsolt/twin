"""Commitment ledger (承诺账本): the decisions, commitments, objections and progress reports said in meetings.

A meeting source is a claimed recording or a transcript in which the person and others speak. Each one is read once
per extractor version, in date order, one structured call per window of lines; every call sees the ledger built so
far, so a progress report can point back to the commitment it is about. The model only names a numbered line; code
maps it to the expression, keeps the quote only when it is verbatim (else the whole line stands as the evidence),
checks dates and links, and drops what it cannot place. Entries start unreviewed; the person confirms, corrects or
rejects them, and a rebuild never touches a reviewed entry.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..llm import LLM, Effort
from ..usage import default_stage
from .lexical import BM25
from .schema import Expression, LedgerEntry, LedgerKind, LedgerStatus, ReviewStatus, Source, SourceKind
from .store import PersonaStore

LEDGER_VERSION = "ledger-v1"
MEETING_KINDS = frozenset({SourceKind.AUDIO, SourceKind.VIDEO, SourceKind.INTERVIEW})
# Lines per call are capped by characters so a long meeting is read in a few windows, each seeing the entries the
# earlier windows produced.
WINDOW_CHARS = 40_000
# The newest entries the model sees as the existing ledger.
CONTEXT_ENTRIES = 200
# A due date this far before the meeting or after it is a misread, not a deadline.
DUE_BEFORE = dt.timedelta(days=31)
DUE_AFTER = dt.timedelta(days=730)

KIND_LABELS: dict[LedgerKind, str] = {"decision": "决定", "commitment": "承诺", "objection": "异议", "progress": "进展"}
STATUS_LABELS: dict[LedgerStatus, str] = {
    "open": "进行中",
    "claimed_done": "本人称已完成",
    "evidenced": "已有交付证据",
    "confirmed_done": "对方确认完成",
    "not_done": "未完成",
    "reopened": "重新打开",
    "unknown": "未知",
    "pending_accept": "待你接受",
}
_KINDS = {label: kind for kind, label in KIND_LABELS.items()}
_STATUSES = {label: status for status, label in STATUS_LABELS.items()}
SELF = "本人"
UNKNOWN_OWNER = "未知"

DraftKind = Literal["决定", "承诺", "异议", "进展"]
DraftStatus = Literal["进行中", "本人称已完成", "已有交付证据", "对方确认完成", "未完成", "重新打开", "未知", ""]


class SpeakerGuess(BaseModel):
    label: str = Field(description="转写里的说话人标签，例如 其他人1")
    name: str = Field(description="推断出的名字；推断不出写 未知")
    basis: str = Field(description="推断依据，例如 本人点名老王后紧接着回答")


class LedgerDraftItem(BaseModel):
    kind: DraftKind
    line: int = Field(description="所在行的行号，即转写里每行开头的数字")
    quote: str = Field(description="从该行逐字摘录的连续片段，一字不改")
    owner: str = Field(description="负责人名字；本人写 本人；推断不出写 未知")
    counterpart: str = Field(default="", description="对谁承诺或向谁汇报；不明确留空")
    what: str = Field(
        description="一句话说清要做的事、定下的事、反对的点或进展：直接写事情本身，不写负责人名字，不加括号说明来源"
        "或经过；提到本人时写「我」，例如「周五前给我一版新报价方案」"
    )
    due: str = Field(default="", description="换算后的截止日期 YYYY-MM-DD；没说期限留空")
    due_text: str = Field(default="", description="原话里的期限说法，例如 周五前")
    condition: str = Field(default="", description="承诺成立的前提条件；没有留空")
    relates_to: str = Field(default="", description="进展或复述对应的已有账本条目 id，原样复制；没有留空")
    status: DraftStatus = Field(default="", description="只有进展填写：对应条目的最新状态")
    confidence: float = Field(ge=0, le=1)


class LedgerDraft(BaseModel):
    speakers: list[SpeakerGuess] = Field(default_factory=list)
    items: list[LedgerDraftItem] = Field(default_factory=list, description="这段转写里的条目；没有就为空列表")


SYSTEM = """你在为「本人」整理会议承诺账本。从会议转写中找出四类条目：

- 决定：有拍板权的人当场定下的事，例如「必须」「就这么定」「先冻结」。
- 承诺：某人答应在某个时间前做某件事。包括：替别人应承的（负责人写被安排的人）；\
被安排后口头接受的（「好的」「没问题」）；有前提的承诺（写进 condition）。\
不包括玩笑、假设和预测；含糊的「看看」「考虑」如果要记，confidence 低于 0.5。
- 异议：对决定或方案明确表示不同意或保留意见，哪怕随后话题被岔开。
- 进展：对「已有账本」里某条的状态更新，例如已完成、没完成、问题又出现。填 relates_to 和 status，\
不要再记成新承诺。只是转述别人的新期限时，记成承诺并填 relates_to。

规则：
- line 填所在行开头的行号；quote 从那一行逐字摘录连续片段，不改字、不拼接。
- 转写只区分本人和其他人N。按上下文推断其他人N是谁（例如本人点名某人后紧接着回答的人），在 speakers 里写依据；\
推断不出写「未知」，不要猜。owner 用推断出的名字。
- due 按会议日期换算成具体日期：「周五」指本周五，「下周X」指下一周的周X，\
「本周」「这周」指本周五，「今天」指会议当天，「明天」指次日。当场改口以最后的说法为准。没说期限就留空，不要编。
- 同一件事在多行提到时只记一条，选最能说明它的那一行。同一句话可以同时产生不同类型的条目。
- 「已有账本」里已经记过的同一件事不要重复记。"""


@dataclass
class LedgerReport:
    sources: int = 0
    entries: int = 0
    dropped: int = 0
    stopped: bool = False


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def _iso(text: str) -> dt.date | None:
    try:
        return dt.date.fromisoformat(text.strip()) if text.strip() else None
    except ValueError:
        return None


def is_meeting(source: Source) -> bool:
    """A source the ledger reads: a recording or transcript in which the person and at least one other person speak."""
    return source.kind in MEETING_KINDS and 0 < source.n_target < source.n_expressions


def thread_root(entry: LedgerEntry, by_id: dict[str, LedgerEntry]) -> str:
    """The first entry of the thread a decision or commitment restates (itself when it restates none). Only the same
    owner's entry is restated: another owner's linked commitment (checking on it, chasing it) is a task of its own."""
    seen = {entry.entry_id}
    while (
        (parent := by_id.get(entry.relates_to or ""))
        and parent.kind != "progress"
        and parent.owner == entry.owner
        and parent.entry_id not in seen
    ):
        seen.add(parent.entry_id)
        entry = parent
    return entry.entry_id


def current_status(entry: LedgerEntry, ledger: list[LedgerEntry]) -> LedgerStatus:
    """A decision or commitment's status: what the person set, else the latest event of its thread (the entry and
    the entries restating it): a progress report gives its status, a later restatement (a new deadline) reopens it."""
    if entry.kind == "progress":
        return entry.status or "unknown"
    if entry.status is not None:
        return entry.status
    live = [e for e in ledger if e.review is not ReviewStatus.REJECTED]
    by_id = {e.entry_id: e for e in live} | {entry.entry_id: entry}
    root = thread_root(entry, by_id)
    thread = {e.entry_id for e in live if e.kind != "progress" and thread_root(e, by_id) == root} | {entry.entry_id}
    events = [
        e
        for e in live
        if (e.kind == "progress" and e.relates_to in thread) or (e.entry_id in thread and e.entry_id != root)
    ]
    if not events:
        return "open"
    latest = max(events, key=lambda e: (e.meeting_date or dt.date.min, e.expression_id, e.kind == "progress"))
    return (latest.status or "unknown") if latest.kind == "progress" else "open"


def _context(ledger: list[LedgerEntry]) -> str:
    rows = [
        {
            "id": e.entry_id,
            "类型": KIND_LABELS[e.kind],
            "负责人": e.owner,
            "内容": e.what,
            "截止": e.due.isoformat() if e.due else "",
            "状态": STATUS_LABELS[current_status(e, ledger)],
            "会议日期": e.meeting_date.isoformat() if e.meeting_date else "",
        }
        for e in ledger
        if e.kind in ("decision", "commitment") and e.review is not ReviewStatus.REJECTED
    ][-CONTEXT_ENTRIES:]
    return json.dumps(rows, ensure_ascii=False, indent=1) if rows else "（空）"


def _label(expression: Expression) -> str:
    return SELF if expression.is_target else expression.speaker


def _windows(expressions: list[Expression]) -> list[list[tuple[int, Expression]]]:
    windows: list[list[tuple[int, Expression]]] = [[]]
    size = 0
    for n, expression in enumerate(expressions, 1):
        line = len(expression.text) + len(_label(expression)) + 8
        if windows[-1] and size + line > WINDOW_CHARS:
            windows.append([])
            size = 0
        windows[-1].append((n, expression))
        size += line
    return [w for w in windows if w]


def _user(source: Source, name: str, ledger: list[LedgerEntry], window: list[tuple[int, Expression]]) -> str:
    day = source.first_date
    when = f"{day.isoformat()}（周{'一二三四五六日'[day.weekday()]}）" if day else "未知"
    lines = "\n".join(f"{n}. {_label(e)}：{' '.join(e.text.split())}" for n, e in window)
    return (
        f"会议：{source.title}\n会议日期：{when}\n本人是{name}。\n\n"
        f"已有账本：\n{_context(ledger)}\n\n转写（每行开头是行号）：\n{lines}"
    )


def _entry(
    item: LedgerDraftItem, lines: dict[int, Expression], source: Source, known: set[str], now: str
) -> LedgerEntry | None:
    expression = lines.get(item.line)
    if expression is None:
        return None
    quote = item.quote.strip()
    exact = bool(quote) and quote in expression.text
    due = _iso(item.due)
    if due and source.first_date and not (source.first_date - DUE_BEFORE <= due <= source.first_date + DUE_AFTER):
        due = None
    kind = _KINDS[item.kind]
    return LedgerEntry(
        entry_id=uuid.uuid4().hex[:16],
        source_id=source.source_id,
        expression_id=expression.expression_id,
        meeting_date=source.first_date,
        meeting_title=source.title,
        kind=kind,
        speaker=_label(expression),
        quote=quote if exact else expression.text,
        quote_exact=exact,
        owner=item.owner.strip() or UNKNOWN_OWNER,
        counterpart=item.counterpart.strip(),
        what=item.what.strip(),
        due=due,
        due_text=item.due_text.strip(),
        condition=item.condition.strip(),
        relates_to=item.relates_to if item.relates_to in known else None,
        status=(_STATUSES.get(item.status) or "unknown") if kind == "progress" else None,
        confidence=item.confidence,
        extractor=LEDGER_VERSION,
        created_at=now,
        updated_at=now,
    )


def extract_meeting(
    llm: LLM,
    source: Source,
    expressions: list[Expression],
    ledger: list[LedgerEntry],
    name: str,
    effort: Effort = "medium",
    reasoning_effort: str | None = None,
) -> tuple[list[LedgerEntry], int]:
    """New entries of one meeting and the number of model items dropped. ``ledger`` is every entry already kept,
    including the reviewed entries of this meeting, which are neither repeated nor replaced."""
    kept = list(ledger)
    reviewed = {(e.expression_id, e.kind) for e in ledger if e.source_id == source.source_id}
    new: list[LedgerEntry] = []
    dropped = 0
    now = _now()
    for window in _windows(expressions):
        with default_stage("ledger"):
            draft = llm.structured(
                system=SYSTEM,
                user=_user(source, name, kept, window),
                schema=LedgerDraft,
                effort=effort,
                reasoning_effort=reasoning_effort,
            )
        lines = dict(window)
        known = {e.entry_id for e in kept}
        for item in draft.items:
            entry = _entry(item, lines, source, known, now)
            if entry is None or (entry.expression_id, entry.kind) in reviewed:
                dropped += 1
                continue
            new.append(entry)
            kept.append(entry)
    return new, dropped


def build_ledger(
    store: PersonaStore,
    llm: LLM,
    name: str,
    *,
    effort: Effort = "medium",
    reasoning_effort: str | None = None,
    force: bool = False,
    log: Callable[[str], None] | None = None,
    stopped: Callable[[], bool] | None = None,
) -> LedgerReport:
    """Read every meeting source the current extractor has not read yet (all of them with ``force``), oldest first.
    ``stopped`` is asked before each meeting; once it says yes the rest are left for a later build."""
    report = LedgerReport()
    meetings = [s for s in store.list_sources() if is_meeting(s)]
    meetings.sort(key=lambda s: (s.first_date or dt.date.min, s.source_id))
    todo = [s for s in meetings if force or store.ledger_done(s.source_id) != LEDGER_VERSION]
    for k, source in enumerate(todo, 1):
        if stopped is not None and stopped():
            report.stopped = True
            break
        if log:
            log(f"[{k}/{len(todo)}] 整理承诺：{source.title}")
        ledger = [
            e for e in store.list_ledger() if e.source_id != source.source_id or e.review is not ReviewStatus.UNREVIEWED
        ]
        expressions = store.list_expressions(source.source_id)
        entries, dropped = extract_meeting(llm, source, expressions, ledger, name, effort, reasoning_effort)
        if not store.replace_ledger_source(source.source_id, entries, LEDGER_VERSION):
            continue  # deleted while it was being read
        report.sources += 1
        report.entries += len(entries)
        report.dropped += dropped
    return report


EDITABLE = frozenset({"owner", "counterpart", "what", "due", "condition", "status"})


def review_entry(
    store: PersonaStore,
    entry_id: str,
    action: Literal["confirm", "edit", "reject", "reset"],
    changes: dict[str, Any] | None = None,
) -> LedgerEntry:
    """Confirm, correct, reject or reset an entry. Corrections take only the editable fields and bump the version."""
    entry = store.get_ledger_entry(entry_id)
    if entry is None:
        raise KeyError(entry_id)
    update: dict[str, Any] = {"updated_at": _now(), "version": entry.version + 1}
    if action == "edit":
        unknown = set(changes or {}) - EDITABLE
        if unknown:
            raise ValueError(f"不能修改的字段：{', '.join(sorted(unknown))}")
        update.update(changes or {})
        update["review"] = ReviewStatus.EDITED
    else:
        update["review"] = {
            "confirm": ReviewStatus.CONFIRMED,
            "reject": ReviewStatus.REJECTED,
            "reset": ReviewStatus.UNREVIEWED,
        }[action]
    revised = LedgerEntry.model_validate({**entry.model_dump(), **update})
    store.put_ledger_entry(revised)
    return revised


def confirmation_message(entry: LedgerEntry) -> str | None:
    """A message the person can send the owner to confirm a commitment; None when there is no one else to ask."""
    if entry.kind != "commitment" or entry.owner in (SELF, UNKNOWN_OWNER, ""):
        return None
    when = f"{entry.meeting_date.month}月{entry.meeting_date.day}日" if entry.meeting_date else ""
    meeting = f"{when}{entry.meeting_title}".strip()
    parts = [f"{entry.owner}，确认一下{meeting}上说的：{entry.what}"]
    if entry.due:
        parts.append(f"，{entry.due.month}月{entry.due.day}日前")
    if entry.condition:
        parts.append(f"（前提：{entry.condition}）")
    parts.append("。有出入直接回我。")
    return "".join(parts)


def latest_of_threads(ledger: list[LedgerEntry]) -> list[LedgerEntry]:
    """The latest entry of each decision or commitment thread (it carries the current deadline), rejected ones aside."""
    live = [e for e in ledger if e.review is not ReviewStatus.REJECTED]
    by_id = {e.entry_id: e for e in live}
    latest: dict[str, LedgerEntry] = {}
    for e in live:
        if e.kind not in ("decision", "commitment"):
            continue
        root = thread_root(e, by_id)
        if root not in latest or (e.meeting_date or dt.date.min, e.expression_id) > (
            latest[root].meeting_date or dt.date.min,
            latest[root].expression_id,
        ):
            latest[root] = e
    return list(latest.values())


@dataclass
class BriefQuestion:
    entry_id: str
    text: str


@dataclass
class Brief:
    """What to bring up with one person before meeting them, each line resting on a ledger entry."""

    person: str
    as_of: dt.date
    # Their commitments not yet confirmed done, overdue first.
    theirs: list[LedgerEntry]
    # What the person (本人) promised them.
    mine: list[LedgerEntry]
    # Latest progress reports on their commitments.
    progress: list[LedgerEntry]
    # Objections they raised.
    objections: list[LedgerEntry]
    questions: list[BriefQuestion]


BRIEF_PROGRESS = 10
BRIEF_OBJECTIONS = 5


def _day(d: dt.date) -> str:
    return f"{d.month}月{d.day}日"


def _question(entry: LedgerEntry, status: LedgerStatus, as_of: dt.date) -> str | None:
    what = f"「{entry.what}」"
    if status == "not_done":
        return f"{what}上次说还没完成，现在到哪一步了，新的时间是？"
    if status == "reopened":
        return f"{what}又出了问题，这次打算怎么处理、什么时候能好？"
    if status == "claimed_done":
        return f"{what}说已经完成了，能把结果发我看一下吗？"
    if status not in ("open", "unknown"):
        return None
    if entry.due and entry.due < as_of:
        return f"{what}原定{_day(entry.due)}前，现在进展如何？"
    if entry.due:
        return f"{what}{_day(entry.due)}前能按时完成吗？"
    return f"{what}现在进展如何，大概什么时候能完成？"


def brief(ledger: list[LedgerEntry], person: str, as_of: dt.date) -> Brief:
    """The pre-meeting brief for ``person`` as of ``as_of``: open commitments, what was promised to them, recent
    progress, their objections, and one question per commitment that needs following up."""
    live = [e for e in ledger if e.review is not ReviewStatus.REJECTED]
    by_id = {e.entry_id: e for e in live}
    status = {e.entry_id: current_status(e, live) for e in live}
    # A promise someone asked the person for in a conversation is not one until they take it.
    latest = [
        e
        for e in latest_of_threads(live)
        if e.kind == "commitment" and status[e.entry_id] not in ("confirmed_done", "pending_accept")
    ]

    def urgency(e: LedgerEntry) -> tuple[int, dt.date]:
        return (0 if e.due and e.due < as_of else 1 if e.due else 2, e.due or dt.date.max)

    theirs = sorted((e for e in latest if e.owner == person), key=urgency)
    mine = sorted((e for e in latest if e.owner == SELF and e.counterpart == person), key=urgency)
    threads = {thread_root(e, by_id) for e in live if e.kind == "commitment" and e.owner == person}
    progress = [
        e
        for e in live
        if e.kind == "progress"
        and (e.owner == person or (e.relates_to in by_id and thread_root(by_id[e.relates_to], by_id) in threads))
    ]
    progress.sort(key=lambda e: (e.meeting_date or dt.date.min, e.expression_id), reverse=True)
    objections = [e for e in live if e.kind == "objection" and e.owner == person]
    objections.sort(key=lambda e: (e.meeting_date or dt.date.min, e.expression_id), reverse=True)
    questions = [BriefQuestion(e.entry_id, text) for e in theirs if (text := _question(e, status[e.entry_id], as_of))]
    questions += [
        BriefQuestion(e.entry_id, f"上次你说「{e.quote}」，这个顾虑现在解决了吗？")
        for e in objections[:BRIEF_OBJECTIONS]
    ]
    return Brief(
        person=person,
        as_of=as_of,
        theirs=theirs,
        mine=mine,
        progress=progress[:BRIEF_PROGRESS],
        objections=objections[:BRIEF_OBJECTIONS],
        questions=questions,
    )


# Entries shown to the chat at most, and the share of the best keyword score an entry needs to be shown on keywords
# alone (without its person or a ledger word in the question).
CHAT_ENTRIES = 12
CHAT_KEYWORD_SHARE = 0.4
# Words that ask about the ledger itself: who promised what, what was decided, objected to, done, or due.
LEDGER_CUE = re.compile(
    r"答应|承诺|欠|待办|跟进|进展|进度|截止|到期|逾期|拖|决定|定了|定下|拍板|负责|谁来|交付|完成|做完|搞定|落实|"
    r"异议|反对|顾虑|意见|账本|会上|开会|周会|例会|评审|见面|追问|催|deadline|todo",
    re.IGNORECASE,
)


def for_chat(
    ledger: list[LedgerEntry], query: str, today: dt.date, as_of: dt.date | None = None
) -> list[tuple[LedgerEntry, LedgerStatus]]:
    """The entries a chat question is about, each with its current status, most relevant first: those of a person
    the question names, then, when the question asks about the ledger (a promise, a decision, a deadline), the open
    decisions and commitments by urgency, then entries sharing its keywords; a progress report follows the decision or
    commitment it is about. Only what was said by ``as_of`` counts, and statuses are worked out from that alone.
    Empty when the question touches none of it."""
    live = [
        e
        for e in ledger
        if e.review is not ReviewStatus.REJECTED and (as_of is None or (e.meeting_date or dt.date.min) <= as_of)
    ]
    if not live:
        return []
    status = {e.entry_id: current_status(e, live) for e in live}
    current = {e.entry_id for e in latest_of_threads(live)}
    # Earlier versions of a restated commitment are superseded by the latest one, which carries the deadline.
    candidates = [e for e in live if e.kind in ("objection", "progress") or e.entry_id in current]
    names = {n for e in live for n in (e.owner, e.counterpart) if n not in (SELF, UNKNOWN_OWNER, "")}
    named = {n for n in names if n in query}
    cue = bool(LEDGER_CUE.search(query))
    keywords = BM25({e.entry_id: f"{e.owner} {e.counterpart} {e.what} {e.quote} {e.meeting_title}" for e in candidates})
    scores = keywords.scores(query)
    best = max(scores.values(), default=0.0)

    def score(e: LedgerEntry) -> float:
        total = 2.0 if named & {e.owner, e.counterpart} else 0.0
        share = scores.get(e.entry_id, 0.0) / best if best else 0.0
        if share >= CHAT_KEYWORD_SHARE or total:
            total += share
        if cue and e.kind in ("decision", "commitment") and status[e.entry_id] != "confirmed_done":
            total += 0.5
        return total

    def urgency(e: LedgerEntry) -> tuple[int, dt.date]:
        return (0 if e.due and e.due < today else 1 if e.due else 2, e.due or dt.date.max)

    by_id = {e.entry_id: e for e in live}

    def thread(e: LedgerEntry) -> str:
        """The decision or commitment thread an entry belongs to; an objection or a loose report is its own."""
        about = by_id.get(e.relates_to or "") if e.kind == "progress" else e
        return thread_root(about, by_id) if about is not None and about.kind != "progress" else e.entry_id

    groups: dict[str, list[LedgerEntry]] = {}
    for e in candidates:
        groups.setdefault(thread(e), []).append(e)
    ranked: list[tuple[float, tuple[int, dt.date], str, LedgerEntry]] = []
    for root, members in groups.items():
        # A report shows when the entry it is about does, right behind it, so the two are read together.
        heads = [e for e in members if e.kind != "progress"] or members
        best_score = max(score(e) for e in heads)
        if best_score <= 0:
            continue
        head = min(heads, key=urgency)
        members.sort(key=lambda e: (e.kind == "progress", e.meeting_date or dt.date.min, e.expression_id))
        ranked.extend((best_score, urgency(head), root, e) for e in members)
    ranked.sort(key=lambda row: (-row[0], row[1], row[2]))
    return [(e, status[e.entry_id]) for *_, e in ranked[:CHAT_ENTRIES]]


def people(ledger: list[LedgerEntry]) -> list[str]:
    """Everyone other than the person who owns an entry, most entries first."""
    counts: dict[str, int] = {}
    for e in ledger:
        if e.review is not ReviewStatus.REJECTED and e.owner not in (SELF, UNKNOWN_OWNER, ""):
            counts[e.owner] = counts.get(e.owner, 0) + 1
    return sorted(counts, key=lambda name: (-counts[name], name))
