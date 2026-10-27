"""Meeting minutes (会议纪要): what one meeting settled, read from its whole transcript.

Minutes belong to the meeting, not to a person: every twin made from the recording reads the same ones. They are
read once per version (``MINUTES_VERSION``), one structured call per window of lines like the commitment ledger
(``persona.ledger``), and a long meeting's windows are merged in one more call. The model names the numbered lines
each point rests on and quotes one of them; code keeps a point only when the quote is found in those lines, so every
point can be cited as what was said there. See docs/PLAN_MEETING_MINUTES.md.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import json
import sqlite3
from collections.abc import Collection, Sequence
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from ..llm import LLM, Effort
from ..usage import default_stage
from ..util import date_from_name, normalize_for_match

MINUTES_VERSION = "minutes-v1"
# Twin sources made from a library (``media.team``); the rest of the id names the recording and the person's own
# segments, so a twin's meeting finds its recording's minutes.
SOURCE_PREFIX = "src_lib_"
# Lines per call are capped by characters, as the ledger's windows are.
WINDOW_CHARS = 40_000
# Points one window or one merge may give: a three-hour meeting settles a dozen or two things, not fifty.
MAX_POINTS = 20
# A due date this far before the meeting or after it is a misread, not a deadline.
DUE_BEFORE = dt.timedelta(days=31)
DUE_AFTER = dt.timedelta(days=730)

PointKind = Literal["决定", "安排", "要求", "待定"]


@dataclass(frozen=True)
class Line:
    """One numbered line of a meeting's transcript: its number there (the segment, as a twin's ``src#00012`` cites
    it), who said it and what."""

    idx: int
    speaker: str
    text: str


class MinutesPoint(BaseModel):
    kind: PointKind
    text: str
    owner: str = ""
    due: dt.date | None = None
    # The transcript's line numbers the point rests on, the quoted one first.
    lines: list[int] = Field(default_factory=list)


@dataclass
class Minutes:
    points: list[MinutesPoint] = field(default_factory=list)
    # Points the model gave that were dropped: no line named, or the quote not found in the lines named.
    dropped: int = 0
    version: str = MINUTES_VERSION


class DraftPoint(BaseModel):
    kind: PointKind
    text: str = Field(description="一句话，具体到人和事，例如「王总二月底前把季度预算方案报给管理层」")
    owner: str = Field(default="", description="负责的人；没有具体负责人留空")
    due: str = Field(default="", description="期限，YYYY-MM-DD；会上没说期限留空")
    lines: list[int] = Field(description="这件事在转写里的行号，最能说明它的那一行放第一个")
    quote: str = Field(description="从 lines 第一个行号那一行逐字摘录的一段，不改字")


class Draft(BaseModel):
    points: list[DraftPoint] = Field(default_factory=list, description="这段转写里定下来的事；没有就为空列表")


class MergedPoint(BaseModel):
    kind: PointKind
    text: str
    owner: str = ""
    due: str = ""
    sources: list[int] = Field(description="合并自哪些编号的条目")


class MergedDraft(BaseModel):
    points: list[MergedPoint] = Field(default_factory=list)


SYSTEM = f"""你在为一次会议整理纪要。从会议转写中列出这次会上定下来的事：

- 决定：会上拍板的事，例如「这个方案就这么定」「先停掉这两个产品」。
- 安排：谁去做什么、什么时候做完。
- 要求：会上提出、以后都要照做的规则或标准。
- 待定：明确说了留到以后再定、再讨论的事，写清楚待定的是什么。

规则：
- 只列定下来的事。讨论过程、汇报的数字、闲聊、玩笑和假设都不列。
- 每条一句话，具体到人和事。负责人按转写里的称呼写，例如「王总」「小强」；推断不出就留空，不要猜。
- 期限按会议日期换算成具体日期：「周五」指本周五，「下周X」指下一周的周X，「月底」指当月最后一天；没说期限就留空。
- 同一件事只列一条。最多 {MAX_POINTS} 条，按会上说到的先后排。
- lines 写这件事所在的行号，第一个是最能说明它的那一行；quote 从那一行逐字摘录，不改字、不拼接。
- 转写由语音识别得到，可能有错字；按上下文理解，但 quote 照原文抄。"""

MERGE = f"""下面是同一次会议分段整理出的纪要条目，每条前面是编号。把它们合并成这次会的完整纪要：

- 同一件事只留一条，sources 写它合并自哪些编号；不同的事不要合并。
- 前后矛盾时以后面说的为准（会上改了主意）。
- 只用给出的条目，不要新增；措辞可以改得更清楚。
- 最多 {MAX_POINTS} 条，按会上说到的先后排。"""


def meeting_day(creation_time: str | None, filename: str) -> dt.date | None:
    """The day a recording was made: when its file says it was, else the one its name is dated with
    (``190708_1834``)."""
    if creation_time:
        with contextlib.suppress(ValueError):
            return dt.date.fromisoformat(creation_time[:10])
    return date_from_name(filename)


def recording_of(source_id: str) -> str | None:
    """The library recording a twin source was made from; None for a source not made from a library."""
    if not source_id.startswith(SOURCE_PREFIX):
        return None
    recording, _, _ = source_id.removeprefix(SOURCE_PREFIX).rpartition("_")
    return recording or None


def _windows(lines: Sequence[Line]) -> list[list[tuple[int, Line]]]:
    """``lines`` numbered from 1 and cut into windows of at most ``WINDOW_CHARS``."""
    windows: list[list[tuple[int, Line]]] = [[]]
    size = 0
    for n, line in enumerate(lines, 1):
        length = len(line.text) + len(line.speaker) + 8
        if windows[-1] and size + length > WINDOW_CHARS:
            windows.append([])
            size = 0
        windows[-1].append((n, line))
        size += length
    return [w for w in windows if w]


def _user(title: str, day: dt.date | None, window: list[tuple[int, Line]]) -> str:
    when = f"{day.isoformat()}（周{'一二三四五六日'[day.weekday()]}）" if day else "未知"
    text = "\n".join(f"{n}. {line.speaker}：{' '.join(line.text.split())}" for n, line in window)
    return f"会议：{title}\n会议日期：{when}\n\n转写（每行开头是行号）：\n{text}"


def _due(text: str, day: dt.date | None) -> dt.date | None:
    try:
        due = dt.date.fromisoformat(text.strip())
    except ValueError:
        return None
    if day is not None and not day - DUE_BEFORE <= due <= day + DUE_AFTER:
        return None
    return due


def _point(draft: DraftPoint, numbered: dict[int, Line], day: dt.date | None) -> MinutesPoint | None:
    """The point with its lines as the transcript's own numbers; None when it names no line of the window or its
    quote is not in the first one."""
    lines = [numbered[n] for n in dict.fromkeys(draft.lines) if n in numbered]
    quote = normalize_for_match(draft.quote)
    if not lines or not draft.text.strip() or not quote or quote not in normalize_for_match(lines[0].text):
        return None
    return MinutesPoint(
        kind=draft.kind,
        text=draft.text.strip(),
        owner=draft.owner.strip(),
        due=_due(draft.due, day),
        lines=[line.idx for line in lines],
    )


def summarize(
    llm: LLM,
    title: str,
    day: dt.date | None,
    lines: Sequence[Line],
    effort: Effort = "medium",
    reasoning_effort: str | None = None,
) -> Minutes:
    """The minutes of one meeting, from its transcript ``lines`` in order (empty ones left out)."""
    minutes = Minutes()
    found: list[MinutesPoint] = []
    windows = _windows([line for line in lines if line.text.strip()])
    for window in windows:
        with default_stage("minutes"):
            draft = llm.structured(
                system=SYSTEM,
                user=_user(title, day, window),
                schema=Draft,
                effort=effort,
                reasoning_effort=reasoning_effort,
            )
        numbered = dict(window)
        for item in draft.points:
            if (point := _point(item, numbered, day)) is None:
                minutes.dropped += 1
            else:
                found.append(point)
    minutes.points = found if len(windows) < 2 else _merge(llm, found, day, effort, reasoning_effort)
    return minutes


def _merge(
    llm: LLM, found: list[MinutesPoint], day: dt.date | None, effort: Effort, reasoning_effort: str | None
) -> list[MinutesPoint]:
    """One meeting's points from its several windows as one list, the same thing said in two windows once."""
    if len(found) < 2:
        return found
    listed = "\n".join(
        f"{n}. {p.kind}：{p.text}"
        + (f"（负责：{p.owner}）" if p.owner else "")
        + (f"（期限：{p.due}）" if p.due else "")
        for n, p in enumerate(found)
    )
    with default_stage("minutes"):
        merged = llm.structured(
            system=MERGE, user=listed, schema=MergedDraft, effort=effort, reasoning_effort=reasoning_effort
        )
    points = []
    for item in merged.points:
        parts = [found[n] for n in dict.fromkeys(item.sources) if 0 <= n < len(found)]
        if not parts or not item.text.strip():
            continue
        lines = list(dict.fromkeys(idx for p in parts for idx in p.lines))
        points.append(
            MinutesPoint(
                kind=item.kind, text=item.text.strip(), owner=item.owner.strip(), due=_due(item.due, day), lines=lines
            )
        )
    # A merge that lost every point (a malformed answer) leaves the windows' points as they were.
    return points or found


def read_minutes(library_db: Path, recording_ids: Collection[str]) -> dict[str, Minutes]:
    """The model's minutes of each of ``recording_ids`` that has some for its current transcript, read from its
    library without writing to it (``persona.chat`` reads them for twins). Minutes of an earlier transcript are not
    that meeting's any more; a library that cannot be read has none."""
    if not recording_ids:
        return {}
    marks = ",".join("?" * len(recording_ids))
    try:
        with closing(sqlite3.connect(f"{library_db.resolve().as_uri()}?mode=ro", uri=True, timeout=10)) as db:
            rows = db.execute(
                "SELECT m.recording_id, m.version, m.points, m.dropped FROM minutes m JOIN recordings r "
                "ON r.id = m.recording_id AND r.transcript_id = m.transcript_id "
                f"WHERE m.origin = 'auto' AND m.recording_id IN ({marks})",
                list(recording_ids),
            ).fetchall()
    except sqlite3.Error:
        return {}
    found = {}
    for recording_id, version, points, dropped in rows:
        try:
            parsed = [MinutesPoint.model_validate(p) for p in json.loads(points)]
        except ValueError:
            continue
        found[str(recording_id)] = Minutes(parsed, int(dropped), str(version))
    return found
