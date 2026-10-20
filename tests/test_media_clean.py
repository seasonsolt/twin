"""LLM proofreading of media transcripts: fixes words in place and never loses or moves speech."""

from __future__ import annotations

import json
from typing import Any

import pytest

from twin.llm import FakeLLM
from twin.media import clean
from twin.media.clean import Edits, clean_segments
from twin.media.ingest import Segment

SEGMENTS = [
    Segment(start=0, end=2, text="今天讲领域驱动设计。", speaker="S1"),
    Segment(start=2, end=3, text="嗯。", speaker="S2"),
    Segment(start=3, end=6, text="第一个概念是涨号上下文。", speaker="S1"),
    Segment(start=6, end=9, text="然后我们看聚合根。", speaker="S1"),
]


def _llm(edits: dict[int, list[dict[str, Any]]], calls: list[list[int]] | None = None) -> FakeLLM:
    """Answers each batch with the edits listed for its first editable id."""

    def handler(system: str, user: str, schema: type) -> dict[str, Any]:
        assert schema is Edits and system == clean.PROMPT
        request = json.loads(user)
        if calls is not None:
            calls.append(request["editable_ids"])
        assert [row["id"] for row in request["meeting"]] == list(range(len(SEGMENTS)))  # a short meeting is all context
        return {"edits": edits.get(request["editable_ids"][0], [])}

    return FakeLLM(handler)


def test_edits_replace_text_but_keep_times_and_speakers() -> None:
    result = clean_segments(_llm({0: [{"id": 2, "text": "第一个概念是限界上下文。"}]}), SEGMENTS)
    assert result.segments[2] == SEGMENTS[2].model_copy(update={"text": "第一个概念是限界上下文。"})
    assert result.segments[:2] + result.segments[3:] == SEGMENTS[:2] + SEGMENTS[3:]
    assert (result.changed, result.rejected, result.failed_batches) == (1, 0, 0)


def test_rewrites_and_edits_outside_the_batch_are_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(clean, "BATCH", 2)
    edits = {
        0: [
            {"id": 0, "text": "今天我们换个话题聊聊别的。"},  # a rewrite, not a fix
            {"id": 1, "text": ""},  # speech is never deleted
            {"id": 2, "text": "第一个概念是限界上下文。"},  # belongs to the next batch
        ],
        2: [{"id": 2, "text": "第一个概念是限界上下文。"}, {"id": 2, "text": "第一个概念是界限上下文。"}],
    }
    calls: list[list[int]] = []
    result = clean_segments(_llm(edits, calls), SEGMENTS)
    assert sorted(calls) == [[0, 1], [2, 3]]
    assert [s.text for s in result.segments] == [SEGMENTS[0].text, "嗯。", "第一个概念是限界上下文。", SEGMENTS[3].text]
    assert (result.changed, result.rejected) == (1, 4)


def test_a_failed_batch_keeps_its_text_and_others_still_apply(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(clean, "BATCH", 2)

    def handler(system: str, user: str, schema: type) -> dict[str, Any]:
        if json.loads(user)["editable_ids"][0] == 0:
            raise RuntimeError("upstream quoted 涨号上下文")
        return {"edits": [{"id": 2, "text": "第一个概念是限界上下文。"}]}

    progress: list[tuple[int, int]] = []
    result = clean_segments(FakeLLM(handler), SEGMENTS, lambda done, total: progress.append((done, total)))
    assert result.segments[:2] == SEGMENTS[:2] and result.segments[2].text == "第一个概念是限界上下文。"
    assert (result.changed, result.failed_batches) == (1, 1)
    assert progress == [(1, 2), (2, 2)]


def test_each_batch_sees_a_bounded_neighbourhood_however_long_the_meeting() -> None:
    """Proofreading costs tokens in proportion to a meeting's length: no batch's request grows with the meeting."""

    def requests(count: int) -> list[dict[str, Any]]:
        sent: list[dict[str, Any]] = []

        def handler(system: str, user: str, schema: type) -> dict[str, Any]:
            sent.append({**json.loads(user), "length": len(user)})
            return {"edits": []}

        segments = [Segment(start=i, end=i + 1, text="这一段讲领域驱动设计。", speaker="S1") for i in range(count)]
        clean_segments(FakeLLM(handler), segments)
        return sorted(sent, key=lambda request: request["editable_ids"][0])

    short, long = requests(4 * clean.BATCH), requests(40 * clean.BATCH)
    assert len(long) == 40
    limit = clean.BATCH + 2 * clean.CONTEXT
    for request in long:
        editable, shown = request["editable_ids"], [row["id"] for row in request["meeting"]]
        # Its own segments with up to CONTEXT neighbours on either side, numbered as in the whole meeting.
        assert shown == list(
            range(max(0, editable[0] - clean.CONTEXT), min(len(long) * clean.BATCH, editable[-1] + clean.CONTEXT + 1))
        )
        assert len(shown) <= limit
    # Same per-batch size, short meeting or long (longer ids aside), so ten times the meeting costs about ten times
    # as much; with the whole meeting in every batch it would cost a hundred times.
    assert max(r["length"] for r in long) < 1.1 * max(r["length"] for r in short)
    assert sum(r["length"] for r in long) < 12 * sum(r["length"] for r in short)
