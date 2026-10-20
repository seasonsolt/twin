"""What a meeting calls its speakers (``media.cues``), and how the library files it."""

from __future__ import annotations

import json
import threading
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
    """A model answering the meeting's n-th window with the n-th of ``answers`` (an exception is raised), whatever
    order the windows, asked together, arrive in."""

    def answer(system: str, user: str, schema: type[BaseModel]) -> Any:
        first = int(json.loads(user)["meeting"].split("|", 1)[0])
        found = answers[[w.start for w in cues._windows(len(MEETING))].index(first)]
        if isinstance(found, Exception):
            raise found
        return found

    return FakeLLM(answer)


def test_only_a_name_said_in_the_meeting_is_a_cue(tmp_path: Path) -> None:
    llm = answering(
        {
            "speakers": [
                {"speaker": "S2", "name": "宋明", "evidence": [0, 1], "sure": True},
                {"speaker": "S3", "name": "王宁", "evidence": [2], "sure": False},
                # A word that only sounds like a name, and a roster name nobody said: both dropped.
                {"speaker": "S4", "name": "淑敏", "evidence": [3], "sure": True},
                {"speaker": "S1", "name": "zhangxun", "evidence": [1], "sure": False},
                # Not a speaker of this meeting, and a second answer for S2: both dropped.
                {"speaker": "S9", "name": "张总", "evidence": [0], "sure": True},
                {"speaker": "S2", "name": "老夏", "evidence": [0], "sure": True},
            ]
        }
    )
    found, failed = name_speakers(llm, MEETING, ["王宁", "艾总", "zhangxun"])
    assert failed == 0
    assert [(c.speaker, c.name, c.sure, c.quote) for c in found] == [
        ("S2", "宋明", True, "那宋明你跟老夏解释一下。"),
        ("S3", "王宁", False, "我是王宁，我补充一下。"),
    ]
    # Titles aside, every character of the name was said: a colleague sharing only a surname is not called.
    assert cues.said("夏总", "老夏你说") and cues.said("郭老师", "郭老师这边的")
    assert not cues.said("梁圣", "有请博丽佳梁修成为我们带来规划")
    # The model reads the roster and the numbered meeting, never anything else.
    [(_, _, user)] = llm.calls
    sent = json.loads(user)
    assert (
        sent["roster"] == ["王宁", "艾总", "zhangxun"]
        and sent["meeting"].splitlines()[0] == "0|S1|那宋明你跟老夏解释一下。"
    )


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
    # Evidence outside a window is not the window's to give, and a window that does not say the name gives none.
    assert [(c.speaker, c.name, c.evidence, c.sure) for c in found] == [("S2", "宋明", [0, 1], True)]
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
    assert (
        library.write_names(
            current,
            named.model_copy(
                update={
                    "speakers": [
                        *named.speakers,
                        Cue(speaker="S3", name="zhangxun", evidence=[1], quote="各位领导介绍一下工作总结。"),
                    ]
                }
            ),
        )
        is True
    )
    assert library.write_names(current, named.model_copy(update={"speakers": []})) is False
    # A name filed without being in its quote (as before ``said`` was required) is left out when read.
    assert {s: c.name for s, c in library.names(current).items()} == {"S2": "宋明"}
    assert [p.name for p in library.folder(rec).iterdir() if p.name.startswith(".")] == []

    # Asked once per transcript, whatever came of it.
    library.asked_names(rec, "another-transcript")
    assert [r.id for r in library.unnamed()] == [rec]
    library.asked_names(rec, current.transcript_id)
    assert library.unnamed() == ()


def test_the_windows_of_a_long_meeting_are_asked_together(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each window waits minutes on the model; a long meeting asks them at once, as proofreading does."""
    monkeypatch.setattr(cues, "WINDOW", 2)
    monkeypatch.setattr(cues, "OVERLAP", 1)
    windows = len(cues._windows(len(MEETING)))
    together = threading.Barrier(windows, timeout=10)

    def answer(system: str, user: str, schema: type[BaseModel]) -> Any:
        together.wait()  # Times out unless every window is waiting on the model at the same moment.
        return {"speakers": []}

    assert windows > 1 and name_speakers(FakeLLM(answer), MEETING, []) == ([], 0)
