from __future__ import annotations

import datetime as dt
import re

import pytest
from pydantic import BaseModel

from twin.llm import FakeLLM
from twin.media import minutes as mm

DAY = dt.date(2019, 7, 8)


def _line(idx: int, text: str, speaker: str = "本人") -> mm.Line:
    return mm.Line(idx, speaker, text)


def test_a_point_is_kept_with_the_lines_it_rests_on_by_their_own_numbers() -> None:
    lines = [_line(0, ""), _line(3, "这个事情就这么定了，王总下周五之前把方案报给我。"), _line(4, "好的。", "王总")]

    def handler(system: str, user: str, schema: type[BaseModel]) -> dict[str, object]:
        # The empty line is left out: the numbered lines start at the one said first.
        assert "1. 本人：这个事情就这么定了" in user and "会议日期：2019-07-08（周一）" in user
        return {
            "points": [
                {
                    "kind": "安排",
                    "text": "王总下周五前把方案报给本人",
                    "owner": "王总",
                    "due": "2019-07-19",
                    "lines": [1, 2],
                    "quote": "王总下周五之前把方案报给我",
                },
                # Not said where it claims: dropped.
                {"kind": "决定", "text": "预算翻倍", "lines": [2], "quote": "预算翻倍"},
                {"kind": "决定", "text": "没有行号", "lines": [9], "quote": "好的"},
            ]
        }

    found = mm.summarize(FakeLLM(handler), "190708_1834", DAY, lines)
    assert [(p.kind, p.text, p.owner, p.due, p.lines) for p in found.points] == [
        ("安排", "王总下周五前把方案报给本人", "王总", dt.date(2019, 7, 19), [3, 4])
    ]
    assert (found.dropped, found.version) == (2, mm.MINUTES_VERSION)


@pytest.mark.parametrize(("due", "kept"), [("2019-07-19", True), ("2017-01-01", False), ("下周五", False)])
def test_a_due_date_far_from_the_meeting_or_not_a_date_is_left_out(due: str, kept: bool) -> None:
    def handler(system: str, user: str, schema: type[BaseModel]) -> dict[str, object]:
        return {"points": [{"kind": "安排", "text": "报方案", "due": due, "lines": [1], "quote": "报方案"}]}

    [point] = mm.summarize(FakeLLM(handler), "会", DAY, [_line(0, "下周五报方案")]).points
    assert (point.due is not None) == kept


def test_a_long_meeting_is_read_in_windows_and_merged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mm, "WINDOW_CHARS", 60)
    lines = [_line(i, f"第{i}件事交给小强月底做完") for i in range(6)]

    def handler(system: str, user: str, schema: type[BaseModel]) -> dict[str, object]:
        if schema is mm.MergedDraft:
            assert user.count("小强") == 3
            # The same thing said in two windows becomes one point, resting on both lines.
            return {
                "points": [{"kind": "安排", "text": "小强月底做完第0和第5件事", "owner": "小强", "sources": [0, 2]}]
            }
        first = int(re.search(r"^(\d+)\. ", user, re.M)[1])  # type: ignore[index]
        return {"points": [{"kind": "安排", "text": "小强做完", "lines": [first], "quote": "交给小强"}]}

    llm = FakeLLM(handler)
    found = mm.summarize(llm, "会", DAY, lines)
    windows = [c for c in llm.calls if c[0] == "Draft"]
    assert len(windows) == 3
    [point] = found.points
    assert (point.text, point.owner, point.lines) == ("小强月底做完第0和第5件事", "小强", [0, 4])


def test_a_merge_that_keeps_nothing_leaves_the_windows_points(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mm, "WINDOW_CHARS", 30)

    def handler(system: str, user: str, schema: type[BaseModel]) -> dict[str, object]:
        if schema is mm.MergedDraft:
            return {"points": [{"kind": "决定", "text": "编造的", "sources": [99]}]}
        first = int(re.search(r"^(\d+)\. ", user, re.M)[1])  # type: ignore[index]
        return {"points": [{"kind": "决定", "text": "定了", "lines": [first], "quote": "定了"}]}

    found = mm.summarize(FakeLLM(handler), "会", DAY, [_line(i, f"就这么定了{i}号") for i in range(2)])
    assert [p.lines for p in found.points] == [[0], [1]]


# ---------------------------------------------------------------- minutes someone wrote


@pytest.mark.parametrize(
    ("name", "text", "day", "clock"),
    [
        ("190708_1834 周会纪要.docx", "一、预算", DAY, dt.time(18, 34)),
        ("周会纪要.txt", "周会纪要\n会议时间：2019年7月8日 18:30\n一、预算", DAY, dt.time(18, 30)),
        ("纪要.md", "一、预算\n二、人员", None, None),
    ],
    ids=["by its name", "by its first lines", "no day"],
)
def test_written_minutes_are_dated_by_their_name_else_their_first_lines(
    name: str, text: str, day: dt.date | None, clock: dt.time | None
) -> None:
    [part] = mm.written_parts(name, text)
    assert (part.day, part.clock, part.parts) == (day, clock, 1)


def test_a_file_of_several_meetings_is_cut_at_the_heading_of_each_day() -> None:
    text = "\n".join(
        [
            "2019年7月纪要汇总",
            "## 7月8日周会",
            "会议时间：7月8日 18:30",
            "一、预算按季度复盘。",
            "## 7月15日周会",
            "一、招聘先停。",
        ]
    )
    first, second = mm.written_parts("2019年7月纪要汇总.docx", text)
    assert (first.day, first.clock, first.part, first.parts) == (DAY, dt.time(18, 30), 1, 2)
    assert first.text.startswith("2019年7月纪要汇总") and "招聘" not in first.text
    assert (second.day, second.title, second.text) == (
        dt.date(2019, 7, 15),
        "7月15日周会",
        "## 7月15日周会\n一、招聘先停。",
    )


def _candidate(rid: str, day: dt.date | None, clock: dt.time | None = None, text: str = "") -> mm.Candidate:
    return mm.Candidate(rid, day, clock, text)


def _part(day: dt.date | None, clock: dt.time | None = None, text: str = "预算按季度复盘") -> mm.WrittenPart:
    return mm.WrittenPart("纪要", day, clock, text)


def test_minutes_are_matched_by_day_then_time_then_what_they_say() -> None:
    other = dt.date(2019, 7, 9)
    one = [_candidate("a", DAY), _candidate("b", other)]
    assert mm.match_recording(_part(DAY), one) == mm.Match("a", "当天唯一")
    assert mm.match_recording(_part(None), one) == mm.Match(None, "没有日期")
    assert mm.match_recording(_part(dt.date(2019, 7, 1)), one) == mm.Match(None, "当天没有录音")
    two = [
        _candidate("am", DAY, dt.time(9, 10), "上午讨论招聘和人员流失"),
        _candidate("pm", DAY, dt.time(18, 34), "晚上的会预算要按季度复盘"),
    ]
    assert mm.match_recording(_part(DAY, dt.time(18, 0)), two) == mm.Match("pm", "时刻相近")
    assert mm.match_recording(_part(DAY), two) == mm.Match("pm", "内容最像")
    # Too far from either, and like neither: someone chooses.
    alike = [_candidate("x", DAY, None, "别的事"), _candidate("y", DAY, None, "也是别的")]
    assert mm.match_recording(_part(DAY, dt.time(13, 0)), alike) == mm.Match(None, "分不出是哪场")
    written = [mm.Candidate("a", DAY, None, "", written=True)]
    assert mm.match_recording(_part(DAY), written) == mm.Match("a", "已有纪要")


def test_written_minutes_are_cut_into_points_each_tied_to_the_line_most_like_it() -> None:
    lines = [_line(0, "先看预算。"), _line(1, ""), _line(2, "那就按季度复盘，大家都同意。"), _line(3, "下一个。")]

    def handler(system: str, user: str, schema: type[BaseModel]) -> dict[str, object]:
        assert "纪要：\n一、预算按季度复盘" in user
        return {
            "points": [
                {"kind": "决定", "text": "预算按季度复盘"},
                {"kind": "安排", "text": "张三负责下季度招聘计划", "owner": "张三", "due": "2019-07-19"},
            ]
        }

    found = mm.read_written(FakeLLM(handler), "周会", DAY, "一、预算按季度复盘\n二、张三负责招聘", lines)
    assert (found.origin, found.version) == ("human", mm.WRITTEN_VERSION)
    assert [(p.text, p.owner, p.due, p.lines) for p in found.points] == [
        ("预算按季度复盘", "", None, [2]),
        # Said nowhere in the meeting: kept, but it cannot be cited.
        ("张三负责下季度招聘计划", "张三", dt.date(2019, 7, 19), []),
    ]
