"""What a meeting calls its speakers (``media.cues``), and how the library files it."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel
from test_team import recording

from twin.llm import FakeLLM
from twin.media import cues
from twin.media.cues import Cue, Named, name_speakers
from twin.media.ingest import Segment, Speaker
from twin.media.library import Library

# A chair calls on 宋明, who answers; 王宁 introduces herself; someone says "梳理", which only sounds like 淑敏.
MEETING = [
    Segment(start=0, end=3, text="那宋明你跟老夏解释一下。", speaker="S1"),
    Segment(start=3, end=6, text="是这样，绿色负责两排人。", speaker="S2"),
    Segment(start=6, end=9, text="我是王宁，我补充一下。", speaker="S3"),
    Segment(start=9, end=12, text="梳理一下复购的排期。", speaker="S4"),
]


def answering(*answers: Any) -> FakeLLM:
    """A model answering each request with the next of ``answers`` (an exception is raised)."""
    queue = list(answers)

    def answer(system: str, user: str, schema: type[BaseModel]) -> Any:
        found = queue.pop(0)
        if isinstance(found, Exception):
            raise found
        return found

    return FakeLLM(answer)


def test_a_name_is_sure_only_when_it_was_said(tmp_path: Path) -> None:
    llm = answering(
        {
            "speakers": [
                {"speaker": "S2", "name": "宋明", "evidence": [0, 1], "sure": True},
                {"speaker": "S3", "name": "王宁", "evidence": [2], "sure": True},
                {"speaker": "S4", "name": "淑敏", "evidence": [3], "sure": True},
                # Not a speaker of this meeting, and a second answer for S2: both dropped.
                {"speaker": "S9", "name": "张总", "evidence": [0], "sure": True},
                {"speaker": "S2", "name": "老夏", "evidence": [0], "sure": True},
                {"speaker": "S1", "name": " ", "evidence": [0], "sure": False},
            ]
        }
    )
    found, failed = name_speakers(llm, MEETING, ["王宁", "艾总"])
    assert failed == 0
    assert [(c.speaker, c.name, c.sure, c.quote) for c in found] == [
        ("S2", "宋明", True, "那宋明你跟老夏解释一下。"),
        ("S3", "王宁", True, "我是王宁，我补充一下。"),
        ("S4", "淑敏", False, "梳理一下复购的排期。"),
    ]
    # The model reads the roster and the numbered meeting, never anything else.
    [(_, _, user)] = llm.calls
    sent = json.loads(user)
    assert sent["roster"] == ["王宁", "艾总"] and sent["meeting"].splitlines()[0] == "0|S1|那宋明你跟老夏解释一下。"


def test_a_long_meeting_is_read_in_windows_and_contradictions_name_nobody(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cues, "WINDOW", 3)
    monkeypatch.setattr(cues, "OVERLAP", 1)
    llm = answering(
        {"speakers": [{"speaker": "S2", "name": "宋明", "evidence": [0, 1, 3], "sure": True}]},
        {
            "speakers": [
                {"speaker": "S2", "name": "宋明", "evidence": [2], "sure": True},
                {"speaker": "S3", "name": "王宁"},
            ]
        },
    )
    found, failed = name_speakers(llm, MEETING, [])
    # Evidence outside a window is not the window's to give; a name said in one window is sure.
    assert [(c.speaker, c.name, c.evidence, c.sure) for c in found] == [
        ("S2", "宋明", [0, 1, 2], True),
        ("S3", "王宁", [], False),
    ]
    assert failed == 0 and len(llm.calls) == 2

    llm = answering(
        {"speakers": [{"speaker": "S2", "name": "宋明", "evidence": [0], "sure": True}]},
        {"speakers": [{"speaker": "S2", "name": "王宁", "evidence": [2], "sure": True}]},
    )
    assert name_speakers(llm, MEETING, []) == ([], 0)
    # A failed window is counted, not fatal.
    llm = answering(RuntimeError("boom"), {"speakers": [{"speaker": "S3", "name": "王宁", "evidence": [2]}]})
    found, failed = name_speakers(llm, MEETING, [])
    assert [c.name for c in found] == ["王宁"] and failed == 1


def test_a_long_quote_is_cut_around_the_name() -> None:
    long = [Segment(start=0, end=9, text="嗯" * 80 + "请宋明讲一下" + "啊" * 80, speaker="S1")]
    quote = cues._quote("宋明", [0], long)
    assert quote.startswith("…") and quote.endswith("…") and "宋明" in quote
    assert len(quote) == cues.QUOTE_CHARS + 2


def test_names_are_filed_once_for_the_current_transcript(tmp_path: Path) -> None:
    library = Library(tmp_path / "library" / "team")
    rec = recording(library, "周会.m4a", MEETING, [Speaker(id=f"S{i}", seconds=3) for i in range(1, 5)])
    current = library.get(rec)
    assert current is not None and current.transcript_id
    assert [r.id for r in library.unnamed()] == [rec] and library.names(current) == {}

    named = Named(
        transcript_id=current.transcript_id,
        created_at="2026-10-20T00:00:00+00:00",
        speakers=[Cue(speaker="S2", name="宋明", evidence=[0], sure=True, quote="那宋明你跟老夏解释一下。")],
    )
    with pytest.raises(ValueError):
        library.write_names(current, named.model_copy(update={"speakers": [Cue(speaker="S9", name="张总")]}))
    with pytest.raises(ValueError):
        library.write_names(current, named.model_copy(update={"transcript_id": "another"}))
    assert library.write_names(current, named) is True
    assert library.write_names(current, named.model_copy(update={"speakers": []})) is False
    assert library.names(current)["S2"].name == "宋明"
    assert [p.name for p in library.folder(rec).iterdir() if p.name.startswith(".")] == []

    # Asked once per transcript, whatever came of it.
    library.asked_names(rec, "another-transcript")
    assert [r.id for r in library.unnamed()] == [rec]
    library.asked_names(rec, current.transcript_id)
    assert library.unnamed() == ()
