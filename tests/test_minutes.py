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
