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
from twin.persona import companion, retirement, will
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


# ------------------------------------------------------------ the will's goodbye with the person's own words


def test_an_heirs_goodbye_ends_with_the_things_the_person_chose_of_their_own_words(tmp_path: Path) -> None:
    now = dt.datetime(2026, 10, 31, 12, 0)
    with PersonaStore(tmp_path / "twin.db") as store:
        for i in ITEMS:
            store.replace_facet_items(i.facet_id, [i])
        draft = will.HeirDraft(name="小满", farewell="往后要好好的。", farewell_words=["s#4", "s#4", "s#2"])
        assert draft.farewell_words == ["s#4", "s#2"]
        with pytest.raises(ValueError, match="最多附 2 句"):
            will.HeirDraft(name="小满", farewell_words=["s#4", "s#2", "s#1"])
        # Only words of theirs: another's account of them, or anything else, is refused.
        with pytest.raises(ValueError, match="只能附你自己说过的话"):
            will.add(store, draft.model_copy(update={"farewell_words": ["s#5"]}), "open-the-door-1", "self", now)
        heir = will.add(store, draft, "open-the-door-1", "self", now)
        assert retirement.farewell_reply(heir, store).reply.splitlines() == [
            "往后要好好的。",
            "",
            retirement.LEFT_WORDS,
            "- “钱的事要先说清楚再谈感情”（2026-09-04）",
            "- “大事睡一晚再定”（2026-09-02）",
        ]
        # Rebuilt without one of them, what was chosen stays in the will, and the goodbye leaves out what is gone.
        store.replace_facet_items("3.1", [])
        kept = will.update(store, heir.heir_id, draft.model_copy(update={"relation": "女儿"}), None, "self", now)
        assert kept.farewell_words == ["s#4", "s#2"]
        assert retirement.farewell_reply(kept, store).reply.endswith("- “钱的事要先说清楚再谈感情”（2026-09-04）")
        # None chosen: the goodbye as it was.
        plain = will.update(store, heir.heir_id, draft.model_copy(update={"farewell_words": []}), None, "self", now)
        assert retirement.farewell_reply(plain, store).reply == "往后要好好的。"


def test_the_person_is_offered_their_own_words_to_leave_with_an_heir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TWIN_EDITION", "persona")
    monkeypatch.setattr(PersonaProcessing, "queue", lambda _: None)
    with PersonaStore(tmp_path / "twin.db") as store:
        for i in ITEMS:
            store.replace_facet_items(i.facet_id, [i])
    app = create_app(
        Settings(db_path=tmp_path / "twin.db"), llm_factory=lambda: FakeLLM(), embedder_factory=HashingEmbedder
    )
    with TestClient(app, base_url="http://localhost") as web:
        assert web.get("/api/persona/will/words").json()["words"] == [
            {"id": "s#4", "quote": "钱的事要先说清楚再谈感情", "date": "2026-09-04"},
            {"id": "s#2", "quote": "大事睡一晚再定", "date": "2026-09-02"},
        ]
        body = {"name": "小满", "farewell_words": ["s#2"], "password": "open-the-door-1"}
        made = web.post("/api/persona/will/heirs", json=body, headers=CSRF)
        assert made.status_code == 200 and made.json()["heir"]["farewell_words"] == ["s#2"]
        refused = web.post(
            "/api/persona/will/heirs", json={**body, "name": "阿禾", "farewell_words": ["x#1"]}, headers=CSRF
        )
        assert refused.status_code == 400
