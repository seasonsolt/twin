"""Meeting minutes (会议纪要): what one meeting settled, read from its whole transcript.

Minutes belong to the meeting, not to a person: every twin made from the recording reads the same ones. A meeting
may have two: the model's (``auto``), and the minutes someone wrote and brought in (``human``), which come first where
there are both. The model's are
read once per version (``MINUTES_VERSION``), one structured call per window of lines like the commitment ledger
(``persona.ledger``), and a long meeting's windows are merged in one more call. The model names the numbered lines
each point rests on and quotes one of them; code keeps a point only when the quote is found in those lines, so every
point can be cited as what was said there. See docs/PLAN_MEETING_MINUTES.md.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import json
import re
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
# How written minutes are cut into points and tied to the transcript's lines (``read_written``).
WRITTEN_VERSION = "written-v1"
Origin = Literal["auto", "human"]
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
    origin: Origin = "auto"


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


def read_minutes(library_db: Path, recording_ids: Collection[str]) -> dict[str, list[Minutes]]:
    """The minutes of each of ``recording_ids`` that has some for its current transcript, written ones first, read
    from its library without writing to it (``persona.chat`` reads them for twins). Minutes read from an earlier
    transcript, or written ones not cut into points yet, are left out; a library that cannot be read has none."""
    if not recording_ids:
        return {}
    marks = ",".join("?" * len(recording_ids))
    try:
        with closing(sqlite3.connect(f"{library_db.resolve().as_uri()}?mode=ro", uri=True, timeout=10)) as db:
            rows = db.execute(
                "SELECT m.recording_id, m.origin, m.version, m.points, m.dropped FROM minutes m JOIN recordings r "
                "ON r.id = m.recording_id AND r.transcript_id = m.transcript_id "
                f"WHERE m.version != '' AND m.recording_id IN ({marks}) ORDER BY m.origin DESC",
                list(recording_ids),
            ).fetchall()
    except sqlite3.Error:
        return {}
    found: dict[str, list[Minutes]] = {}
    for recording_id, origin, version, points, dropped in rows:
        try:
            parsed = [MinutesPoint.model_validate(p) for p in json.loads(points)]
        except ValueError:
            continue
        found.setdefault(str(recording_id), []).append(
            Minutes(parsed, int(dropped), str(version), "human" if origin == "human" else "auto")
        )
    return found


# ---------------------------------------------------------------- minutes someone wrote

# A file of minutes is read for its day in its name, else in its first lines; a line this short that names a day is
# a heading, and a file with headings of two days or more holds a meeting under each.
HEAD_LINES = 12
HEADING_CHARS = 40
# Written minutes are cut into points from at most this much of their text.
WRITTEN_CHARS = 40_000
# A meeting whose day has several recordings is matched by its time when the minutes say it, within this much.
CLOCK_SLACK = dt.timedelta(minutes=90)
# ... else by what it says: the best-matching recording's share of the minutes' character pairs must be this much,
# and this many times the runner-up's.
CONTENT_SHARE = 0.2
CONTENT_LEAD = 1.2
# A point of written minutes rests on the transcript line (or two in a row) holding this share of its character pairs.
LINE_SHARE = 0.4

_MONTH_DAY = re.compile(r"(?<!\d)(?P<m>\d{1,2})\s*月\s*(?P<d>\d{1,2})\s*[日号]")
_CLOCK = re.compile(r"(?<!\d)(?P<h>[01]?\d|2[0-3])\s*[:：点]\s*(?P<min>[0-5]\d)(?!\d)")
_NAME_CLOCK = re.compile(r"(?<!\d)\d{6}[_-](?P<h>[01]\d|2[0-3])(?P<min>[0-5]\d)(?!\d)")
_YEAR = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")
_PAIR_CHARS = re.compile(r"[\W_]+")


@dataclass(frozen=True)
class WrittenPart:
    """The minutes of one meeting in a file someone wrote: the whole file, or one of the meetings it holds under
    headings of their days (``part`` of ``parts``, from 1)."""

    title: str
    day: dt.date | None
    clock: dt.time | None
    text: str
    part: int = 1
    parts: int = 1


@dataclass(frozen=True)
class Candidate:
    """A recording minutes could be of: its day and time when known, and its words (only needed where its day has
    other recordings)."""

    recording_id: str
    day: dt.date | None
    clock: dt.time | None
    text: str = ""
    # It has written minutes already: new ones are not put on it without someone saying so.
    written: bool = False


@dataclass(frozen=True)
class Match:
    """Which recording minutes are of, and how that was found: ``当天唯一``, ``时刻相近`` or ``内容最像``; or none, and
    why: ``没有日期``, ``当天没有录音``, ``分不出是哪场`` or ``已有纪要`` (``recording_id`` then names that one)."""

    recording_id: str | None
    how: str


def _day_in(line: str, year: int | None) -> dt.date | None:
    found = date_from_name(line)
    if found is not None or year is None:
        return found
    if (m := _MONTH_DAY.search(line)) is None:
        return None
    with contextlib.suppress(ValueError):
        return dt.date(year, int(m["m"]), int(m["d"]))
    return None


def _clock_in(text: str, pattern: re.Pattern[str] = _CLOCK) -> dt.time | None:
    m = pattern.search(text)
    return dt.time(int(m["h"]), int(m["min"])) if m else None


def recording_clock(creation_time: str | None, filename: str) -> dt.time | None:
    """The time a recording began: in its name (``190708_1834``), else when its file says it was made."""
    if (found := _clock_in(filename, _NAME_CLOCK)) is not None:
        return found
    if creation_time and "T" in creation_time:
        with contextlib.suppress(ValueError):
            return dt.datetime.fromisoformat(creation_time).time()
    return None


def written_parts(filename: str, text: str) -> list[WrittenPart]:
    """The meetings a file of minutes holds, with the day and time of each when it says them: the day in its name,
    else in its first lines; a file with short headings of two days or more is cut at each, the text before the first
    going with it."""
    stem = filename.rsplit(".", 1)[0]
    lines = text.splitlines()
    head = "\n".join(lines[:HEAD_LINES])
    day = date_from_name(stem) or date_from_name(head)
    # Headings may give the month and day alone ("7月8日周会"), of the year the file is of ("2019年7月纪要汇总").
    said = _YEAR.search(stem) or _YEAR.search(head)
    year = day.year if day else int(said[0]) if said else None
    headings = [
        (n, found)
        for n, line in enumerate(lines)
        if 0 < len(line.strip().lstrip("#").strip()) <= HEADING_CHARS
        and (found := _day_in(line.strip().lstrip("#"), year)) is not None
    ]
    if len({found for _, found in headings}) < 2:
        clock = _clock_in(stem, _NAME_CLOCK) or _clock_in(head)
        return [WrittenPart(stem, day, clock, text.strip())]
    # A day said twice in a row (a heading, then the date line under it) is one meeting.
    starts = [h for k, h in enumerate(headings) if k == 0 or h[1] != headings[k - 1][1]]
    parts = []
    for k, (n, found) in enumerate(starts):
        end = starts[k + 1][0] if k + 1 < len(starts) else len(lines)
        body = "\n".join(lines[0 if k == 0 else n : end]).strip()
        heading = lines[n].strip().lstrip("#").strip()
        parts.append(WrittenPart(heading, found, _clock_in("\n".join(lines[n : n + 3])), body, k + 1, len(starts)))
    return parts


def _pairs(text: str) -> set[str]:
    plain = _PAIR_CHARS.sub("", normalize_for_match(text))
    return {plain[i : i + 2] for i in range(len(plain) - 1)}


def _share(needle: set[str], hay: set[str]) -> float:
    return len(needle & hay) / len(needle) if needle else 0.0


def match_recording(part: WrittenPart, candidates: Sequence[Candidate]) -> Match:
    """The recording the minutes are of, by their day, then their time, then what they say; none where that does not
    settle it, for someone to choose."""
    if part.day is None:
        return Match(None, "没有日期")
    same = [c for c in candidates if c.day == part.day]
    if not same:
        return Match(None, "当天没有录音")
    found: Match | None = None
    if len(same) == 1:
        found = Match(same[0].recording_id, "当天唯一")
    if found is None and part.clock is not None:
        at = dt.datetime.combine(part.day, part.clock)
        timed = sorted(
            (abs(dt.datetime.combine(part.day, c.clock) - at), c.recording_id) for c in same if c.clock is not None
        )
        if timed and timed[0][0] <= CLOCK_SLACK:
            found = Match(timed[0][1], "时刻相近")
    if found is None:
        words = _pairs(part.text)
        scored = sorted(((_share(words, _pairs(c.text)), c.recording_id) for c in same), reverse=True)
        best, second = scored[0][0], scored[1][0] if len(scored) > 1 else 0.0
        if best >= CONTENT_SHARE and best >= CONTENT_LEAD * second:
            found = Match(scored[0][1], "内容最像")
    if found is None:
        return Match(None, "分不出是哪场")
    if any(c.written for c in same if c.recording_id == found.recording_id):
        return Match(found.recording_id, "已有纪要")
    return found


class WrittenPoint(BaseModel):
    kind: PointKind
    text: str = Field(description="纪要里的一条，意思不变；可以去掉编号和客套话")
    owner: str = Field(default="", description="负责的人；纪要里没写留空")
    due: str = Field(default="", description="期限，YYYY-MM-DD；纪要里没写留空")


class WrittenDraft(BaseModel):
    points: list[WrittenPoint] = Field(default_factory=list)


WRITTEN = """下面是一份人写的会议纪要。把它拆成一条一条定下来的事：

- 决定：拍板的事。安排：谁去做什么、什么时候做完。要求：以后都要照做的规则或标准。待定：留到以后再定的事。
- 每条一句话，意思和纪要一致，不增不减；纪要里的背景介绍、参会人名单、汇报数字不列。
- 负责人和期限只写纪要里写了的；期限按会议日期换算成具体日期，没写就留空。
- 按纪要里的先后排。"""


def read_written(
    llm: LLM,
    title: str,
    day: dt.date | None,
    text: str,
    lines: Sequence[Line],
    effort: Effort = "medium",
    reasoning_effort: str | None = None,
) -> Minutes:
    """Written minutes cut into points by the model, as they are, each tied to the transcript line (or two in a row)
    most like it; a point like no line keeps none, and cannot be cited."""
    when = f"{day.isoformat()}（周{'一二三四五六日'[day.weekday()]}）" if day else "未知"
    with default_stage("minutes"):
        draft = llm.structured(
            system=WRITTEN,
            user=f"会议：{title}\n会议日期：{when}\n\n纪要：\n{text[:WRITTEN_CHARS]}",
            schema=WrittenDraft,
            effort=effort,
            reasoning_effort=reasoning_effort,
        )
    said = [line for line in lines if line.text.strip()]
    pairs = [_pairs(line.text) for line in said]
    points = []
    for item in draft.points:
        if not item.text.strip():
            continue
        words = _pairs(item.text)
        # One line like it, else two in a row: a point is often said across a line and the next.
        best, at = 0.0, None
        for width in (1, 2):
            for n in range(len(said) - width + 1):
                share = _share(words, set().union(*pairs[n : n + width]))
                if share > best + 1e-9:
                    best, at = share, [said[k].idx for k in range(n, n + width)]
            if best >= LINE_SHARE:
                break
        points.append(
            MinutesPoint(
                kind=item.kind,
                text=item.text.strip(),
                owner=item.owner.strip(),
                due=_due(item.due, day),
                lines=at if at is not None and best >= LINE_SHARE else [],
            )
        )
    return Minutes(points, 0, WRITTEN_VERSION, "human")
