"""生命叙事: what the person has told of their life, year by year; a year only from the words themselves, gaps kept as
gaps, nothing guessed, and only the person sees it."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from twin.config import AuthSettings, Settings, SMTPSettings
from twin.embed import HashingEmbedder
from twin.llm import FakeLLM
from twin.persona import life_story
from twin.persona.items import PersonaItem, PEvidence
from twin.persona.schema import EvidenceClass, SourceKind
from twin.persona.store import PersonaStore
from twin.web import create_app
from twin.web.jobs import PersonaProcessing

CSRF = {"X-Twin": "1"}
PERSON = "person@xjjk.com"
OTHER = "other@xjjk.com"
TODAY = dt.date(2026, 10, 30)


def item(item_id: str, facet: str, statement: str, *quotes: tuple[str, dt.date | None, SourceKind]) -> PersonaItem:
    return PersonaItem(
        item_id=item_id,
        facet_id=facet,
        statement=statement,
        evidence=[
            PEvidence(
                expression_id=f"{item_id}_{n}",
                source_id="s1",
                source_kind=kind,
                evidence_class=EvidenceClass.SELF_REPORT
                if kind in (SourceKind.INTERVIEW, SourceKind.QUESTIONNAIRE)
                else EvidenceClass.BEHAVIOR,
                date=date,
                quote=quote,
            )
            for n, (quote, date, kind) in enumerate(quotes)
        ],
    )


# The year is in its words; the earliest one written counts.
QUIT = item(
    "pi_quit", "1.2", "2015年辞职去了大理，2016 年回来", ("那年辞了职", dt.date(2024, 5, 1), SourceKind.INTERVIEW)
)
# The year is in what it rests on, not in the statement.
FATHER = item("pi_father", "10.2", "父亲走后很久不提这件事", ("2019年父亲走了", None, SourceKind.CHAT))
# Dated as it happened: a diary.
PROUD = item(
    "pi_proud", "10.3", "第一次独立带完一个项目，很自豪", ("今天项目上线了", dt.date(2021, 3, 2), SourceKind.DIARY)
)
# Told looking back, undated by its words: no year is guessed.
GRANNY = item(
    "pi_granny", "1.3", "最早的记忆是外婆家的院子", ("四岁时在外婆家", dt.date(2026, 10, 1), SourceKind.INTERVIEW)
)
# Not part of the story.
HABIT = item("pi_habit", "2.1", "2018年起每天跑步", ("2018年开始跑步", dt.date(2018, 1, 1), SourceKind.DIARY))


def when(each: PersonaItem) -> tuple[int | None, str | None]:
    placed = life_story.place(each, TODAY)
    return placed.year, placed.basis


def test_a_year_comes_only_from_the_words_and_their_dates_as_they_happened() -> None:
    assert when(QUIT) == (2015, "written")
    assert when(FATHER) == (2019, "written")
    assert when(PROUD) == (2021, "dated")
    assert when(GRANNY) == (None, None)
    # Four digits are a year only when written as one, and only a year that could have been lived.
    assert life_story.written_year("工号 2015，住 1203 室", TODAY) is None
    assert life_story.written_year("计划 2035年退休，1880年的老房子", TODAY) is None


def test_the_years_run_to_this_one_with_each_gap_kept_as_one_blank() -> None:
    spans, undated = life_story.story([HABIT, GRANNY, PROUD, FATHER, QUIT], TODAY)
    assert [(s.year, s.until, [p.item.item_id for p in s.items]) for s in spans] == [
        (2015, 2015, ["pi_quit"]),
        (2016, 2018, []),
        (2019, 2019, ["pi_father"]),
        (2020, 2020, []),
        (2021, 2021, ["pi_proud"]),
        (2022, 2026, []),
    ]
    assert [p.item.item_id for p in undated] == ["pi_granny"]
    assert life_story.story([GRANNY, HABIT], TODAY) == ([], [life_story.place(GRANNY, TODAY)])


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
    app = create_app(config, llm_factory=lambda: FakeLLM(lambda *_: {}), embedder_factory=HashingEmbedder)
    with TestClient(app, base_url="http://localhost") as client:
        client.app.state.sender = sender  # type: ignore[attr-defined]
        yield client


def login(web: TestClient, email: str) -> None:
    web.post("/api/auth/request", json={"email": email}, headers=CSRF)
    code = str(web.app.state.sender.call_args.args[2])  # type: ignore[attr-defined]
    assert web.post("/api/auth/verify", json={"email": email, "code": code}, headers=CSRF).status_code == 200


def test_the_person_alone_sees_their_life_by_year(web: TestClient, tmp_path: Path) -> None:
    login(web, PERSON)
    persona = web.post("/api/personas", json={"name": "林舟"}, headers=CSRF).json()["id"]
    assert web.put(f"/api/personas/{persona}/claim", json={"claim": PERSON}, headers=CSRF).status_code == 200
    assert [p["mine"] for p in web.get("/api/personas").json()] == [True]
    assert web.post(f"/api/personas/{persona}/approve", json={"public": True}, headers=CSRF).status_code == 200
    with PersonaStore(tmp_path / "personas" / persona / "twin.db") as store:
        for each in (QUIT, FATHER, GRANNY, HABIT):
            store.replace_facet_items(each.facet_id, [each])
    mine = {**CSRF, "X-Twin-Persona": persona}

    told = web.get("/api/persona/life-story", headers=mine)
    assert told.status_code == 200, told.text
    years = told.json()["years"]
    assert years[0] == {
        "year": 2015,
        "until": 2015,
        "items": [
            {
                "item_id": "pi_quit",
                "facet_id": "1.2",
                "facet_name": "重要经历与转折",
                "statement": QUIT.statement,
                "basis": "written",
            }
        ],
    }
    assert [(y["year"], y["until"], len(y["items"])) for y in years[1:3]] == [(2016, 2018, 0), (2019, 2019, 1)]
    assert years[-1]["until"] == dt.date.today().year
    assert [i["item_id"] for i in told.json()["undated"]] == ["pi_granny"]

    login(web, OTHER)
    assert web.get("/api/persona/life-story", headers={**CSRF, "X-Twin-Persona": persona}).status_code == 403
