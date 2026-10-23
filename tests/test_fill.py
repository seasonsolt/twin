"""补一补: the questions come from what the twin knows least, an answer is read into drafts before anything is kept,
and what is kept goes into the memory in the tier the person chose."""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from twin.config import AuthSettings, Settings, SMTPSettings
from twin.embed import HashingEmbedder
from twin.llm import FakeLLM
from twin.persona import fill
from twin.persona.coverage import coverage_report
from twin.persona.dimensions import FACETS
from twin.persona.items import PersonaItem, PEvidence
from twin.persona.profile import build_profile, consented_facets
from twin.persona.schema import EvidenceClass, SourceKind
from twin.persona.store import PersonaStore
from twin.persona.tiers import COLLEAGUE, SELF, item_tier
from twin.web import create_app
from twin.web.jobs import PersonaProcessing

CSRF = {"X-Twin": "1"}
ANSWER = "在推知识库检索改版，月底前要把命中率提上去。另外在带两个新人熟悉评审。"
FIRST = "在推知识库检索改版，月底前要提高命中率"
SECOND = "在带两个新人熟悉评审流程"


def model(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
    """Reads the answer into two conclusions about what the person is working on, and merges what it is shown."""
    if schema.__name__ == "ExtractDraft":
        n = int(re.findall(r"\[(\d+)\]", user)[0])
        said = [("8.1", FIRST, "月底前要"), ("8.2", SECOND, "在带两个新人熟悉评审")]
        return {
            "items": [
                {"facet_id": facet, "statement": statement, "quotes": [{"n": n, "quote": quote}]}
                for facet, statement, quote in said
                if quote in user
            ]
        }
    lines = re.findall(r"\[(pc_[0-9a-f]+)\][^\n]*?：([^\n（]+)", user)
    return {"items": [{"statement": statement, "candidate_ids": [candidate]} for candidate, statement in lines]}


@pytest.fixture
def store(tmp_path: Path) -> Iterator[PersonaStore]:
    with PersonaStore(tmp_path / "twin.db") as opened:
        yield opened


def settings(tmp_path: Path) -> Settings:
    return Settings(target_name="林舟", db_path=tmp_path / "twin.db")


def item(item_id: str, facet: str, own: bool = True, source: str = "s1") -> PersonaItem:
    return PersonaItem(
        item_id=item_id,
        facet_id=facet,
        statement=f"说起过{facet}",
        evidence=[
            PEvidence(
                expression_id=f"{source}#0",
                source_id=source,
                source_kind=SourceKind.CHAT,
                evidence_class=EvidenceClass.BEHAVIOR,
                date=dt.date(2026, 10, 1),
                quote="原话",
                own_words=own,
            )
        ],
    )


def test_the_questions_are_for_what_is_least_known_and_leave_out_what_the_person_keeps_to_themself() -> None:
    consented = frozenset(f.facet_id for f in FACETS)
    # 1.1 is known well enough to stop asking about; 1.2 only mentioned, by someone else.
    known = [item("a", "1.1"), item("a2", "1.1", source="s2"), item("b", "1.2", own=False)]
    asked = fill.questions_for(known, consented)
    assert len(asked) == fill.QUESTIONS_PER_SITTING
    assert len({a.question_id for a in asked}) == len(asked)  # a question about two facets is asked once
    assert "1.1" not in {a.facet_id for a in asked}
    # What is not known at all comes before what is only mentioned.
    assert [(a.facet_id, a.level) for a in asked] == [("1.4", 0), ("2.1", 0), ("2.2", 0)]
    # Nothing the person keeps to themself by default is asked about unprompted (1.3, 8.3, 9.x ...).
    assert {a.tier for a in asked} == {COLLEAGUE}
    # Opened on purpose, one is asked whatever tier it is in.
    (own,) = fill.questions_for([], consented, facet="8.3")
    assert (own.facet_id, own.tier) == ("8.3", SELF)
    # An aspect opened asks for its facets, the one only mentioned too, a question once.
    opened = fill.questions_for(known, consented, dimension="D1")
    assert [(a.facet_id, a.question_id) for a in opened] == [("1.3", "q02"), ("1.4", "q01")]
    assert [a.level for a in fill.questions_for(known, consented, facet="1.2")] == [1]
    # A facet the person did not consent to is not asked.
    assert fill.questions_for([], frozenset(), facet="8.1") == []


def test_an_answer_is_read_into_drafts_that_are_not_kept_until_the_person_chooses(
    store: PersonaStore, tmp_path: Path
) -> None:
    (ask,) = fill.questions_for([], consented_facets(store), facet="8.1")
    assert ask.text.startswith("最近有什么事占了你比较多的时间")
    drafts = fill.draft(store, FakeLLM(model), settings(tmp_path), "林舟", ask, ANSWER)
    assert [(d.facet_id, d.statement, d.tier) for d in drafts] == [
        ("8.1", FIRST, COLLEAGUE),
        ("8.2", SECOND, COLLEAGUE),
    ]
    assert store.list_sources() == [] and store.list_items() == []  # nothing is kept by reading it
    with pytest.raises(ValueError):
        fill.draft(store, FakeLLM(model), settings(tmp_path), "林舟", ask, "  ")


def test_keeping_the_drafts_raises_what_the_twin_knows_and_each_goes_in_the_tier_chosen(
    store: PersonaStore, tmp_path: Path
) -> None:
    consented = consented_facets(store)
    (ask,) = fill.questions_for([], consented, facet="8.1")
    before = {f.facet_id: f.level for f in coverage_report([], consented).facets}
    assert before["8.1"] == before["8.2"] == 0
    kept = [fill.Kept("8.1", FIRST, "colleague"), fill.Kept("8.2", SECOND, "self")]
    # Told before anything is stored: both facets go from not known to mentioned.
    expected = {c.facet_id: (c.before, c.after) for c in fill.changes([], consented, ask, "林舟", kept)}
    assert expected == {"8.1": (0, 1), "8.2": (0, 1)}
    # What is not kept counts for nothing.
    dropped = fill.changes([], consented, ask, "林舟", [fill.Kept("8.1", FIRST, "none")])
    assert [(c.facet_id, c.before, c.after) for c in dropped] == [("8.1", 0, 0)]

    stored = fill.keep(store, ask, "林舟", [*kept, fill.Kept("8.2", "不存的一条", "none")])
    assert len(stored) == 2 and len(store.list_sources()) == 2
    (colleague_note,) = [s for s in store.list_sources() if store.list_expressions(s.source_id)[0].text == FIRST]
    expression = store.list_expressions(colleague_note.source_id)[0]
    assert (
        expression.is_target
        and expression.channel == "补一补"
        and "最近有什么事占了你比较多的时间" in expression.context
    )
    assert store.note_tiers()[colleague_note.source_id] == COLLEAGUE

    # The next build makes the memories, and they are as well known as told.
    build_profile(store, FakeLLM(model), settings(tmp_path))
    items = store.list_items()
    assert {i.facet_id: i.statement for i in items} == {"8.1": FIRST, "8.2": SECOND}
    tiers = store.item_tiers()
    assert {i.facet_id: item_tier(i, tiers) for i in items} == {"8.1": COLLEAGUE, "8.2": SELF}
    after = {f.facet_id: f.level for f in coverage_report(items, consented).facets}
    assert (after["8.1"], after["8.2"]) == (1, 1) and after["8.1"] > before["8.1"]
    # Keeping the same conclusions again is the same sources, not more.
    fill.keep(store, ask, "林舟", kept)
    assert len(store.list_sources()) == 2


def test_an_answer_on_a_second_occasion_of_another_kind_counts_with_what_was_known_before() -> None:
    consented = frozenset(f.facet_id for f in FACETS)
    (ask,) = fill.questions_for([], consented, facet="8.1")
    # Said once before, in the person's own words in a chat: the answer is a second occasion of another kind, so the
    # facet goes from mentioned to well known, as the coverage counts it.
    earlier = [item("early", "8.1", source="chat-1")]
    (change,) = [
        c
        for c in fill.changes(
            earlier, consented, ask, "林舟", [fill.Kept("8.1", FIRST, "colleague")], today=dt.date(2026, 10, 2)
        )
        if c.facet_id == "8.1"
    ]
    assert (change.before, change.after) == (1, 3)


# ---------------------------------------------------------------- the routes

PERSON = "person@xjjk.com"
OTHER = "other@xjjk.com"


@pytest.fixture
def web(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("TWIN_SMTP_PASSWORD", "test-only")
    queued = MagicMock()
    monkeypatch.setattr(PersonaProcessing, "queue", queued)
    sender = MagicMock()
    monkeypatch.setattr("twin.web.auth.send_code", sender)
    config = Settings(
        db_path=tmp_path / "twin.db",
        auth=AuthSettings(
            enabled=True, smtp=SMTPSettings(host="smtp.example.com", username="test", from_address="t@example.com")
        ),
    )
    app = create_app(config, llm_factory=lambda: FakeLLM(model), embedder_factory=HashingEmbedder)
    with TestClient(app, base_url="http://localhost") as client:
        client.app.state.sender = sender  # type: ignore[attr-defined]
        client.app.state.queued = queued  # type: ignore[attr-defined]
        yield client


def login(web: TestClient, email: str) -> None:
    web.post("/api/auth/request", json={"email": email}, headers=CSRF)
    code = str(web.app.state.sender.call_args.args[2])  # type: ignore[attr-defined]
    assert web.post("/api/auth/verify", json={"email": email, "code": code}, headers=CSRF).status_code == 200


def test_the_person_is_asked_reads_the_answer_and_keeps_it_while_a_colleague_cannot(
    web: TestClient, tmp_path: Path
) -> None:
    login(web, PERSON)
    persona = web.post("/api/personas", json={"name": "林舟"}, headers=CSRF).json()["id"]
    # Made for them, taken and said to be all right: they are the person.
    assert web.put(f"/api/personas/{persona}/claim", json={"claim": PERSON}, headers=CSRF).status_code == 200
    assert [p["mine"] for p in web.get("/api/personas").json()] == [True]
    assert web.post(f"/api/personas/{persona}/approve", json={"public": True}, headers=CSRF).status_code == 200
    mine = {**CSRF, "X-Twin-Persona": persona}
    asked = web.get("/api/persona/fill?facet=8.1", headers=mine)
    assert asked.status_code == 200, asked.text
    (question,) = asked.json()["questions"]
    assert (question["facet"], question["level_label"], question["tier"]) == ("8.1", "还不了解", "colleague")
    body = {"question": question["id"], "facet": "8.1"}
    read = web.post("/api/persona/fill/draft", json={**body, "answer": ANSWER}, headers=mine)
    assert read.status_code == 200, read.text
    drafts = read.json()["drafts"]
    assert [(d["facet"], d["statement"]) for d in drafts] == [("8.1", FIRST), ("8.2", SECOND)]
    assert {c["facet_id"]: (c["before_label"], c["after_label"]) for c in read.json()["changes"]} == {
        "8.1": ("还不了解", "提到过"),
        "8.2": ("还不了解", "提到过"),
    }
    with PersonaStore(tmp_path / "personas" / persona / "twin.db") as store:
        assert store.list_sources() == []
    items = [{"facet": d["facet"], "statement": d["statement"], "choice": "colleague"} for d in drafts]
    items[1]["choice"] = "none"
    web.app.state.queued.reset_mock()  # type: ignore[attr-defined]
    preview = web.post("/api/persona/fill/preview", json={**body, "items": items}, headers=mine)
    assert {c["facet_id"]: c["after"] for c in preview.json()["changes"]} == {"8.1": 1}
    kept = web.post("/api/persona/fill/keep", json={**body, "items": items}, headers=mine)
    assert kept.status_code == 200 and kept.json()["saved"] == 1
    web.app.state.queued.assert_called()  # type: ignore[attr-defined]
    with PersonaStore(tmp_path / "personas" / persona / "twin.db") as store:
        (source,) = store.list_sources()
        assert store.list_expressions(source.source_id)[0].text == FIRST
        assert store.note_tiers() == {source.source_id: COLLEAGUE}
    # Unknown questions and facets are refused.
    assert (
        web.post(
            "/api/persona/fill/draft", json={"question": "q99", "facet": "8.1", "answer": "x"}, headers=mine
        ).status_code
        == 404
    )

    # Someone who only talks to the twin has no part in what it learns of its person.
    login(web, OTHER)
    theirs = {**CSRF, "X-Twin-Persona": persona}
    for response in (
        web.get("/api/persona/fill", headers=theirs),
        web.post("/api/persona/fill/draft", json={**body, "answer": ANSWER}, headers=theirs),
        web.post("/api/persona/fill/keep", json={**body, "items": items}, headers=theirs),
    ):
        assert response.status_code == 403
