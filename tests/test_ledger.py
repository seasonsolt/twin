from __future__ import annotations

import datetime as dt
import json
import re
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from twin.llm import FakeLLM
from twin.persona import ledger as lg
from twin.persona import store as storage
from twin.persona.schema import ReviewStatus, Source, SourceKind
from twin.persona.sources import parse_media
from twin.persona.store import PersonaStore

NAME = "张总"


def meeting(store: PersonaStore, source_id: str, day: str, lines: list[tuple[str, str]]) -> Source:
    """Store a claimed recording the way the upload pipeline does: the person under their name, others as 其他人N."""
    source = Source(
        source_id=source_id,
        kind=SourceKind.AUDIO,
        title=f"会议{source_id}",
        origin=f"{source_id}.m4a",
        imported_at="now",
        n_expressions=0,
        n_target=0,
        creation_time=f"{day}T09:00:00",
        media_status="ready",
        text_state="raw",
    )
    parsed = parse_media(
        source,
        [
            (NAME if who == "本人" else who, f"[00:{i:02d}] {text}", who == "本人")
            for i, (who, text) in enumerate(lines)
        ],
    )
    store.put_source(parsed)
    return parsed.source


def item(line: int, quote: str, kind: str = "承诺", **extra: Any) -> dict[str, Any]:
    return {"kind": kind, "line": line, "quote": quote, "owner": "老王", "what": quote, "confidence": 0.9, **extra}


def ledger_ids(user: str) -> list[str]:
    block = user.split("已有账本：\n", 1)[1].split("\n\n转写", 1)[0]
    return [] if block == "（空）" else [row["id"] for row in json.loads(block)]


@pytest.fixture
def store(tmp_path: Path) -> PersonaStore:
    return PersonaStore(tmp_path / "twin.db")


def test_entries_rest_on_numbered_lines_with_checked_quotes_and_dates(store: PersonaStore) -> None:
    meeting(store, "m1", "2026-10-12", [("本人", "老王你说说。"), ("其他人1", "我周五前给您一版新报价方案。")])
    seen: list[str] = []

    def handler(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
        seen.append(user)
        return {
            "speakers": [{"label": "其他人1", "name": "老王", "basis": "被点名后回答"}],
            "items": [
                item(2, "我周五前给您一版新报价方案", due="2026-10-16", due_text="周五前"),
                item(2, "周五给方案", kind="决定", owner=""),
                item(1, "老王你说说", kind="异议", due="1999-01-01"),
                item(9, "不存在的行"),
            ],
        }

    report = lg.build_ledger(store, FakeLLM(handler), NAME)
    assert (report.sources, report.entries, report.dropped) == (1, 3, 1)
    assert "会议日期：2026-10-12（周一）" in seen[0]
    assert "1. 本人：[00:00] 老王你说说。" in seen[0] and "2. 其他人1：[00:01] 我周五前" in seen[0]
    by_kind = {e.kind: e for e in store.list_ledger()}
    promise, decision, objection = by_kind["commitment"], by_kind["decision"], by_kind["objection"]
    assert promise.expression_id == "m1#00001" and promise.quote_exact and promise.due == dt.date(2026, 10, 16)
    assert promise.speaker == "其他人1" and promise.meeting_date == dt.date(2026, 10, 12)
    assert not decision.quote_exact and decision.quote == "[00:01] 我周五前给您一版新报价方案。"
    assert decision.owner == lg.UNKNOWN_OWNER
    assert objection.speaker == lg.SELF and objection.due is None
    assert all(e.review is ReviewStatus.UNREVIEWED and e.visibility == "private" for e in store.list_ledger())


def test_progress_links_back_across_meetings_and_sets_status(store: PersonaStore) -> None:
    meeting(store, "m1", "2026-10-12", [("本人", "陈工报表呢？"), ("其他人1", "周四上线修复。")])
    meeting(store, "m2", "2026-10-19", [("本人", "报表怎么样了？"), ("其他人1", "修好了，但客户又报了。")])

    def handler(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
        ids = ledger_ids(user)
        if not ids:
            return {"items": [item(2, "周四上线修复", owner="陈工", due="2026-10-15")]}
        return {
            "items": [
                item(2, "客户又报了", kind="进展", relates_to=ids[0], status="重新打开"),
                item(2, "修好了", kind="进展", relates_to="不存在", status="本人称已完成"),
            ]
        }

    lg.build_ledger(store, FakeLLM(handler), NAME)
    fix, *reports = store.list_ledger()
    (reopened,) = [e for e in reports if e.status == "reopened"]
    (unlinked,) = [e for e in reports if e.status == "claimed_done"]
    assert reopened.relates_to == fix.entry_id and unlinked.relates_to is None
    assert lg.current_status(fix, store.list_ledger()) == "reopened"
    assert lg.current_status(reopened, store.list_ledger()) == "reopened"
    lg.review_entry(store, reopened.entry_id, "reject")
    assert lg.current_status(fix, store.list_ledger()) == "open"


def test_rebuild_keeps_reviewed_entries_and_skips_read_meetings(store: PersonaStore) -> None:
    meeting(
        store, "m1", "2026-10-12", [("本人", "就这么定。"), ("其他人1", "我周五给方案。"), ("其他人2", "我不同意。")]
    )
    llm = FakeLLM(
        lambda s, u, schema: {
            "items": [item(1, "就这么定", kind="决定"), item(2, "我周五给方案"), item(3, "我不同意", kind="异议")]
        }
    )
    lg.build_ledger(store, llm, NAME)
    decision, promise, objection = store.list_ledger()
    lg.review_entry(store, promise.entry_id, "confirm")
    lg.review_entry(store, objection.entry_id, "reject")
    assert lg.build_ledger(store, llm, NAME).sources == 0 and len(llm.calls) == 1
    report = lg.build_ledger(store, llm, NAME, force=True)
    assert (report.entries, report.dropped) == (1, 2)
    after = {e.expression_id: e for e in store.list_ledger()}
    assert len(after) == 3
    assert after[promise.expression_id].entry_id == promise.entry_id
    assert after[promise.expression_id].review is ReviewStatus.CONFIRMED
    assert after[objection.expression_id].review is ReviewStatus.REJECTED
    assert after[decision.expression_id].entry_id != decision.entry_id


def test_long_meeting_is_read_in_windows_that_see_earlier_entries(
    store: PersonaStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(lg, "WINDOW_CHARS", 40)
    meeting(store, "m1", "2026-10-12", [("本人", "第一件事要做。"), ("其他人1", "第二件事我来做。"), ("本人", "好。")])
    contexts: list[list[str]] = []

    def handler(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
        contexts.append(ledger_ids(user))
        n = int(re.findall(r"^(\d+)\. ", user, re.M)[0])
        return {"items": [item(n, "事")]} if n < 3 else {"items": []}

    lg.build_ledger(store, FakeLLM(handler), NAME)
    assert len(contexts) == 3 and len(contexts[0]) == 0 and len(contexts[2]) == 2
    assert [e.expression_id for e in store.list_ledger()] == ["m1#00000", "m1#00001"]


def test_review_edits_only_editable_fields_and_bumps_version(store: PersonaStore) -> None:
    meeting(store, "m1", "2026-10-12", [("本人", "说说。"), ("其他人1", "我周五给新报价方案。")])
    lg.build_ledger(store, FakeLLM(lambda s, u, schema: {"items": [item(2, "我周五给新报价方案")]}), NAME)
    (entry,) = store.list_ledger()
    edited = lg.review_entry(
        store, entry.entry_id, "edit", {"owner": "王强", "due": "2026-10-16", "status": "evidenced"}
    )
    assert (edited.owner, edited.due, edited.status) == ("王强", dt.date(2026, 10, 16), "evidenced")
    assert edited.review is ReviewStatus.EDITED and edited.version == entry.version + 1
    assert store.get_ledger_entry(entry.entry_id) == edited
    assert lg.current_status(edited, [edited]) == "evidenced"
    with pytest.raises(ValueError, match="quote"):
        lg.review_entry(store, entry.entry_id, "edit", {"quote": "改写原话"})
    with pytest.raises(KeyError):
        lg.review_entry(store, "missing", "confirm")
    assert (
        lg.confirmation_message(edited)
        == "王强，确认一下10月12日会议m1上说的：我周五给新报价方案，10月16日前。有出入直接回我。"
    )
    assert lg.confirmation_message(edited.model_copy(update={"owner": lg.SELF})) is None
    assert lg.confirmation_message(edited.model_copy(update={"kind": "decision"})) is None


def test_deleting_a_meeting_drops_its_entries_and_links(store: PersonaStore) -> None:
    meeting(store, "m1", "2026-10-12", [("本人", "说说。"), ("其他人1", "周四上线。")])
    meeting(store, "m2", "2026-10-19", [("本人", "怎样？"), ("其他人1", "上线了。")])

    def handler(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
        ids = ledger_ids(user)
        return {"items": [item(2, "上线", kind="进展" if ids else "承诺", relates_to=ids[0] if ids else "")]}

    lg.build_ledger(store, FakeLLM(handler), NAME)
    first, report = store.list_ledger()
    assert report.relates_to == first.entry_id
    lg.review_entry(store, first.entry_id, "confirm")
    assert store.delete_source(first.source_id)
    (left,) = store.list_ledger()
    assert left.entry_id == report.entry_id and left.relates_to is None
    assert store.ledger_done(first.source_id) is None


def test_only_meetings_with_the_person_and_others_are_read(store: PersonaStore) -> None:
    meeting(store, "solo", "2026-10-12", [("本人", "自言自语。")])
    meeting(store, "others", "2026-10-12", [("其他人1", "我们聊。"), ("其他人2", "好。")])
    llm = FakeLLM(lambda s, u, schema: {"items": []})
    assert lg.build_ledger(store, llm, NAME).sources == 0 and llm.calls == []


def test_schema_one_store_gains_the_ledger_table(tmp_path: Path) -> None:
    path = tmp_path / "twin.db"
    with sqlite3.connect(path) as db:
        db.executescript(storage._SCHEMA)
        db.execute("INSERT INTO p_meta VALUES ('identity:name', '张总')")
        db.execute("PRAGMA user_version = 1")
    with PersonaStore(path) as store:
        assert store.get_meta("identity:name") == "张总"
        assert store.list_ledger() == [] and store.schema_version() == 2


def test_restated_commitment_shares_its_thread_status(store: PersonaStore) -> None:
    meeting(store, "m1", "2026-10-12", [("本人", "报价呢？"), ("其他人1", "我周五前给方案。")])
    meeting(store, "m2", "2026-10-14", [("本人", "报价呢？"), ("其他人1", "老王说今天下班前发。")])
    meeting(store, "m3", "2026-10-19", [("本人", "报价呢？"), ("其他人1", "周三发过去了。")])

    def handler(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
        ids = ledger_ids(user)
        if "会议m1" in user:
            return {"items": [item(2, "我周五前给方案")]}
        if "会议m3" in user:
            return {"items": [item(2, "周三发过去了", kind="进展", relates_to=ids[0], status="本人称已完成")]}
        return {"items": [item(2, "发", relates_to=ids[-1])]}

    llm = FakeLLM(handler)
    assert lg.build_ledger(store, llm, NAME).sources == 3
    first, restated, done = store.list_ledger()
    entries = store.list_ledger()
    assert restated.relates_to == first.entry_id and done.relates_to == first.entry_id
    assert lg.current_status(first, entries) == lg.current_status(restated, entries) == "claimed_done"
    meeting(store, "m4", "2026-10-21", [("本人", "报价呢？"), ("其他人1", "客户要改，老王说周五再发一版。")])
    assert lg.build_ledger(store, llm, NAME).sources == 1
    entries = store.list_ledger()
    assert entries[-1].relates_to == restated.entry_id
    assert {lg.current_status(e, entries) for e in entries if e.kind == "commitment"} == {"open"}


def test_another_owners_follow_up_does_not_reopen_the_commitment(store: PersonaStore) -> None:
    meeting(store, "m1", "2026-10-12", [("本人", "报表呢？"), ("其他人1", "我周四上线修复。")])
    meeting(
        store,
        "m2",
        "2026-10-19",
        [("本人", "客户又报了？"), ("其他人1", "是，又报了。"), ("其他人2", "好的，我去确认。")],
    )

    def handler(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
        ids = ledger_ids(user)
        if not ids:
            return {"items": [item(2, "我周四上线修复", owner="陈工")]}
        return {
            "items": [
                item(2, "又报了", kind="进展", relates_to=ids[0], status="重新打开"),
                item(3, "我去确认", owner="周敏", relates_to=ids[0]),
            ]
        }

    lg.build_ledger(store, FakeLLM(handler), NAME)
    entries = store.list_ledger()
    fix, check = [e for e in entries if e.kind == "commitment"]
    assert check.relates_to == fix.entry_id
    assert lg.current_status(fix, entries) == "reopened" and lg.current_status(check, entries) == "open"
