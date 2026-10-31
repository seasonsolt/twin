"""告别一种陪伴 (P3.6): the person puts a way of looking at themself away with fixed closing words and up to two
things they said themself, and opens it again when they want."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from twin.config import Settings
from twin.embed import HashingEmbedder
from twin.llm import FakeLLM
from twin.persona import companion
from twin.persona.items import PersonaItem, PEvidence
from twin.persona.schema import EvidenceClass, SourceKind
from twin.persona.store import PersonaStore
from twin.web import create_app
from twin.web.jobs import PersonaProcessing

CSRF = {"X-Twin": "1"}


def said(expression_id: str, quote: str, day: int, own: bool = True) -> PEvidence:
    return PEvidence(
        expression_id=expression_id,
        source_id=expression_id.split("#", 1)[0],
        source_kind=SourceKind.CHAT,
        evidence_class=EvidenceClass.SELF_REPORT,
        quote=quote,
        date=dt.date(2026, 9, day),
        own_words=own,
    )


def item(item_id: str, facet: str, *evidence: PEvidence) -> PersonaItem:
    return PersonaItem(item_id=item_id, facet_id=facet, statement=item_id, evidence=list(evidence))


ITEMS = [
    item("pi_money", "2.1", said("s#1", "钱的事先说清楚", 1), said("s#4", "钱的事要先说清楚再谈感情", 4)),
    item("pi_night", "3.1", said("s#2", "大事睡一晚再定", 2)),
    item("pi_told", "3.2", said("s#5", "他说她做事很慢", 5, own=False)),
    item("pi_fish", "9.1", said("s#3", "周末钓鱼", 3), said("s#6", "又去钓鱼", 6)),
]


def test_the_words_left_are_the_person_s_own_of_what_they_value_and_how_they_decide() -> None:
    words = companion.own_words(ITEMS)
    # Said most often first, the latest of their own quotes; another's account of them and other dimensions are not.
    assert [w.quote for w in words] == ["钱的事要先说清楚再谈感情", "大事睡一晚再定"]
    assert words[0].line() == "“钱的事要先说清楚再谈感情”（2026-09-04）"
    assert companion.own_words(ITEMS, 1) == words[:1]


def test_closing_words_are_fixed_and_the_way_stays_away_until_opened(tmp_path: Path) -> None:
    with PersonaStore(tmp_path / "twin.db") as store:
        assert companion.closing_reply(store, "voice").reply == "内在声音就先到这里。"
        for i in ITEMS:
            store.replace_facet_items(i.facet_id, [i])
        reply = companion.closing_reply(store, "voice")
        assert reply.reply.splitlines() == [
            "内在声音就先到这里。",
            "你自己说过的话，留给你：",
            "- “钱的事要先说清楚再谈感情”（2026-09-04）",
            "- “大事睡一晚再定”（2026-09-02）",
        ]
        assert reply.mode == "general" and reply.citations == [] and not reply.abstain
        companion.close(store, "voice")
        companion.close(store, "mirror")
        assert companion.closed(store) == ["mirror", "voice"]
        companion.reopen(store, "voice")
        assert companion.closed(store) == ["mirror"]
        with pytest.raises(ValueError):
            companion.close(store, "")


def test_the_person_puts_a_way_away_in_their_conversation_and_opens_it_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TWIN_EDITION", "persona")
    monkeypatch.setattr(PersonaProcessing, "queue", lambda _: None)
    app = create_app(
        Settings(db_path=tmp_path / "twin.db"), llm_factory=lambda: FakeLLM(), embedder_factory=HashingEmbedder
    )
    with TestClient(app, base_url="http://localhost") as web:
        made = web.post("/api/conversations", json={}, headers=CSRF).json()["id"]
        closed = web.post("/api/persona/reflections/voice/close", json={"conversation_id": made}, headers=CSRF)
        assert closed.status_code == 200
        assert closed.json()["closed"] == ["voice"]
        assert closed.json()["reply"]["reflection"] == "voice"
        saved = web.get(f"/api/conversations/{made}", headers=CSRF).json()["turns"]
        assert [(t["role"], t["content"]) for t in saved] == [("user", "先到这里"), ("twin", "内在声音就先到这里。")]
        assert web.get("/api/persona/reflections").json() == {"closed": ["voice"]}
        # Without a conversation saved yet, the words come back and are kept nowhere.
        assert web.post("/api/persona/reflections/dream/close", json={}, headers=CSRF).json()["closed"] == [
            "dream",
            "voice",
        ]
        missing = web.post("/api/persona/reflections/free/close", json={"conversation_id": "nope"}, headers=CSRF)
        assert missing.status_code == 404
        assert web.post("/api/persona/reflections/voice/open", headers=CSRF).json() == {"closed": ["dream"]}
        assert web.post("/api/persona/reflections/ask/close", json={}, headers=CSRF).status_code == 400
