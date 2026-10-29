"""人生回顾: a life told stage by stage, a question or two at a sitting, going on where the last sitting stopped; an
answer goes the way of 补一补, and only the person is asked."""

from __future__ import annotations

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
from twin.persona import life_review
from twin.persona.dimensions import FACET_BY_ID
from twin.persona.store import PersonaStore
from twin.persona.tiers import SELF
from twin.web import create_app
from twin.web.jobs import PersonaProcessing

CSRF = {"X-Twin": "1"}
PERSON = "person@xjjk.com"
OTHER = "other@xjjk.com"
ANSWER = "最早记得外婆家的院子，那年大概四岁。外婆一直是我心里最踏实的人。"
MEMORY = "最早的记忆是四岁时外婆家的院子"
RELIANCE = "外婆是他心里最踏实的人"


def model(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
    """Reads the answer into what it remembers first and on whom it rests; merges what it is shown."""
    if schema.__name__ == "ExtractDraft":
        n = int(re.findall(r"\[(\d+)\]", user)[0])
        said = [("1.3", MEMORY, "外婆家的院子"), ("10.4", RELIANCE, "最踏实的人")]
        return {
            "items": [
                {"facet_id": facet, "statement": statement, "quotes": [{"n": n, "quote": quote}]}
                for facet, statement, quote in said
                if quote in user and re.search(rf"^\s*{re.escape(facet)}\s", system, re.MULTILINE)
            ]
        }
    lines = re.findall(r"\[(pc_[0-9a-f]+)\][^\n]*?：([^\n（]+)", user)
    return {"items": [{"statement": statement, "candidate_ids": [candidate]} for candidate, statement in lines]}


def test_every_question_is_for_facets_that_exist_and_every_stage_is_asked() -> None:
    assert len({q.question_id for q in life_review.QUESTIONS}) == len(life_review.QUESTIONS)
    assert all(len(q.question_id) <= 8 and q.facets for q in life_review.QUESTIONS)
    assert all(f in FACET_BY_ID for q in life_review.QUESTIONS for f in q.facets)
    assert {q.stage for q in life_review.QUESTIONS} == set(life_review.STAGE_LABELS)
    # Told in the order of a life: no question of a later stage before one of an earlier.
    order = [s for s, _ in life_review.STAGES]
    stages = [order.index(q.stage) for q in life_review.QUESTIONS]
    assert stages == sorted(stages)


def test_a_sitting_goes_on_where_the_last_stopped_and_a_question_passed_over_comes_back_last(tmp_path: Path) -> None:
    with PersonaStore(tmp_path / "twin.db") as store:
        state = life_review.load_state(store)
        assert [q.question_id for q in life_review.next_questions(state)] == ["L01", "L02"]
        life_review.mark(store, "L01", answered=True)
        life_review.mark(store, "L02", answered=False)
    with PersonaStore(tmp_path / "twin.db") as store:
        state = life_review.load_state(store)
        # One stage at a time: what is left of childhood, then school.
        assert [q.question_id for q in life_review.next_questions(state)] == ["L03"]
        for q in life_review.QUESTIONS:
            if q.question_id != "L02":
                life_review.mark(store, q.question_id, answered=True)
        state = life_review.load_state(store)
        assert [q.question_id for q in life_review.next_questions(state)] == ["L02"]
        # Answered at last, it is no longer passed over; answered twice, counted once.
        life_review.mark(store, "L02", answered=True)
        life_review.mark(store, "L02", answered=True)
        life_review.mark(store, "L02", answered=False)
        state = life_review.load_state(store)
        assert life_review.next_questions(state) == []
        assert state.skipped == []
        assert all(s["answered"] == s["total"] for s in life_review.progress(state))


def test_a_question_no_longer_asked_is_forgotten(tmp_path: Path) -> None:
    with PersonaStore(tmp_path / "twin.db") as store:
        store.set_meta(life_review.STATE_KEY, '{"answered": ["L01", "L99"], "skipped": ["L01", "L98", "L02"]}')
        state = life_review.load_state(store)
        assert (state.answered, state.skipped) == (["L01"], ["L02"])
        # An unknown question is not remembered.
        assert life_review.mark(store, "L99", answered=True).answered == ["L01"]


@pytest.fixture
def web(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("TWIN_SMTP_PASSWORD", "test-only")
    monkeypatch.setattr(PersonaProcessing, "queue", MagicMock())
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
        yield client


def login(web: TestClient, email: str) -> None:
    web.post("/api/auth/request", json={"email": email}, headers=CSRF)
    code = str(web.app.state.sender.call_args.args[2])  # type: ignore[attr-defined]
    assert web.post("/api/auth/verify", json={"email": email, "code": code}, headers=CSRF).status_code == 200


def test_the_person_tells_their_life_stage_by_stage_and_keeps_what_they_choose(web: TestClient, tmp_path: Path) -> None:
    login(web, PERSON)
    persona = web.post("/api/personas", json={"name": "林舟"}, headers=CSRF).json()["id"]
    assert web.put(f"/api/personas/{persona}/claim", json={"claim": PERSON}, headers=CSRF).status_code == 200
    assert [p["mine"] for p in web.get("/api/personas").json()] == [True]  # Taken: made for them
    assert web.post(f"/api/personas/{persona}/approve", json={"public": True}, headers=CSRF).status_code == 200
    mine = {**CSRF, "X-Twin-Persona": persona}

    asked = web.get("/api/persona/life-review", headers=mine)
    assert asked.status_code == 200, asked.text
    first, second = asked.json()["questions"]
    assert second["id"] == "L02"
    assert (first["id"], first["stage_label"], first["facet"]) == ("L01", "童年", "1.3")
    assert [s["label"] for s in asked.json()["stages"]] == ["童年", "求学", "工作", "家庭", "失去", "意义"]

    # Passed over: the next sitting starts with the one after it.
    assert web.post("/api/persona/life-review/skip", json={"question": "L01"}, headers=mine).status_code == 200
    assert web.get("/api/persona/life-review", headers=mine).json()["questions"][0]["id"] == "L02"

    # The answer is read for every facet the question is about, not only the one it is asked for.
    body = {"question": "L01", "facet": "1.3"}
    read = web.post("/api/persona/fill/draft", json={**body, "answer": ANSWER}, headers=mine)
    assert read.status_code == 200, read.text
    drafts = read.json()["drafts"]
    assert [(d["facet"], d["statement"]) for d in drafts] == [("1.3", MEMORY), ("10.4", RELIANCE)]
    # What one tells of one's life is kept for oneself unless one says otherwise.
    assert [d["tier"] for d in drafts] == ["self", "self"]
    items = [{"facet": d["facet"], "statement": d["statement"], "choice": d["tier"]} for d in drafts]
    kept = web.post("/api/persona/fill/keep", json={**body, "items": items}, headers=mine)
    assert kept.status_code == 200 and kept.json()["saved"] == 1
    with PersonaStore(tmp_path / "personas" / persona / "twin.db") as store:
        assert list(store.note_tiers().values()) == [SELF]

    # Answered, it is not asked again, and childhood shows it.
    told = web.get("/api/persona/life-review", headers=mine).json()
    assert [q["id"] for q in told["questions"]] == ["L02", "L03"]
    assert told["stages"][0] == {"id": "childhood", "label": "童年", "answered": 1, "total": 3}
    # A question asked for a facet it is not about, or not asked at all, is refused.
    for wrong in ({"question": "L01", "facet": "8.1"}, {"question": "L99", "facet": "1.3"}):
        assert web.post("/api/persona/fill/draft", json={**wrong, "answer": ANSWER}, headers=mine).status_code == 404
    assert web.post("/api/persona/life-review/skip", json={"question": "L99"}, headers=mine).status_code == 404

    # Someone who only talks to the twin is not asked about the person's life.
    login(web, OTHER)
    theirs = {**CSRF, "X-Twin-Persona": persona}
    assert web.get("/api/persona/life-review", headers=theirs).status_code == 403
    assert web.post("/api/persona/life-review/skip", json={"question": "L02"}, headers=theirs).status_code == 403
