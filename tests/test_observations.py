"""剖析观察: observations held up to the person, each resting on their memories and their own words quoted as they
were said; what does not hold is dropped, the person's marks are kept and heard the next time, and only they see it."""

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
from twin.persona import observations
from twin.persona.items import PersonaItem, PEvidence
from twin.persona.schema import EvidenceClass, SourceKind
from twin.persona.sources import parse_diary
from twin.persona.store import PersonaStore
from twin.web import create_app
from twin.web.jobs import PersonaProcessing

CSRF = {"X-Twin": "1"}
PERSON = "person@xjjk.com"
OTHER = "other@xjjk.com"
NOW = dt.datetime(2026, 10, 30, 12, 0)
D = dt.date


def item(item_id: str, facet: str, statement: str, *quotes: tuple[str, dt.date | None]) -> PersonaItem:
    return PersonaItem(
        item_id=item_id,
        facet_id=facet,
        statement=statement,
        evidence=[
            PEvidence(
                expression_id=f"{item_id}_{n}",
                source_id="s1",
                source_kind=SourceKind.DIARY,
                evidence_class=EvidenceClass.BEHAVIOR,
                date=date,
                quote=quote,
            )
            for n, (quote, date) in enumerate(quotes)
        ],
    )


FATHER = item(
    "pi_father", "10.2", "父亲走后很久不提这件事", ("那件事就别说了", D(2019, 6, 1)), ("忙起来就好了", D(2022, 1, 3))
)
WORK = item("pi_work", "10.3", "做成事才觉得自己有用", ("项目成了我才睡得着", D(2021, 3, 2)))
QUIT = item("pi_quit", "3.4", "难的时候先走开", ("我又一次选择了离开", D(2015, 5, 1)), ("还是走吧", D(2023, 8, 8)))
HABIT = item("pi_habit", "5.1", "说话很直", ("我就直说了", D(2020, 1, 1)))
ITEMS = [FATHER, WORK, QUIT, HABIT]
DREAM = "我在一座没有门的房子里找人。"


def ref_of(user: str, words: str) -> str:
    shown = re.split(r"^(?=\[)", user, flags=re.MULTILINE)
    return next(re.match(r"\[(\w+)\]", block).group(1) for block in shown if words in block)  # type: ignore[union-attr]


def model(seen: list[str]) -> Any:
    def handle(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
        seen.append(user)
        q = lambda words: {"ref": ref_of(user, words), "quote": words}  # noqa: E731
        return {
            "observations": [
                # Holds: a quote under its number.
                {
                    "kind": "defense",
                    "text": "你在痛的时候让自己忙起来",
                    "quotes": [q("那件事就别说了"), q("忙起来就好了")],
                },
                # Holds across two years.
                {"kind": "repetition", "text": "难的时候你会走开", "quotes": [q("我又一次选择了离开"), q("还是走吧")]},
                # A dream may be quoted.
                {"kind": "reliance", "text": "你在梦里一直在找一个人", "quotes": [q(DREAM)]},
                # Dropped: a repetition from one year only.
                {"kind": "repetition", "text": "你总想证明自己", "quotes": [q("项目成了我才睡得着")]},
                # Dropped: words never said.
                {"kind": "worth", "text": "你靠成就感活着", "quotes": [{"ref": "i1", "quote": "我只为成就活着"}]},
                # Dropped: a kind that is not one of the six; and memories not shown (5.1) cannot be cited.
                {"kind": "diagnosis", "text": "你有回避型人格", "quotes": [q("那件事就别说了")]},
            ]
        }

    return handle


def test_only_observations_quoting_what_was_shown_word_for_word_are_kept(tmp_path: Path) -> None:
    seen: list[str] = []
    with PersonaStore(tmp_path / "twin.db") as store:
        state = observations.make(store, FakeLLM(model(seen)), ITEMS, [(DREAM, D(2024, 3, 2))], str, str, NOW)
    assert "说话很直" not in seen[0]  # Not one of the facets observations are read from.
    assert [(o.kind, o.text) for o in state.observations] == [
        ("defense", "你在痛的时候让自己忙起来"),
        ("repetition", "难的时候你会走开"),
        ("reliance", "你在梦里一直在找一个人"),
    ]
    defense, _, dream = state.observations
    assert [(q.item_id, q.quote, q.date) for q in defense.quotes] == [
        ("pi_father", "那件事就别说了", D(2019, 6, 1)),
        ("pi_father", "忙起来就好了", D(2022, 1, 3)),
    ]
    assert (dream.quotes[0].item_id, dream.quotes[0].date) == (None, D(2024, 3, 2))


def test_marks_are_kept_and_heard_the_next_time(tmp_path: Path) -> None:
    seen: list[str] = []
    llm = FakeLLM(model(seen))
    with PersonaStore(tmp_path / "twin.db") as store:
        first = observations.make(store, llm, ITEMS, [(DREAM, None)], str, str, NOW)
        defense, repetition, dream = (o.observation_id for o in first.observations)
        observations.mark(store, defense, "wrong", NOW)
        observations.mark(store, repetition, "useless", NOW)
        observations.mark(store, dream, "right", NOW)
        observations.mark(store, dream, None, NOW)  # Taken back.
        with pytest.raises(KeyError):
            observations.mark(store, "ob_unknown", "right", NOW)
        again = observations.make(store, llm, ITEMS, [(DREAM, None)], str, str, NOW)
    # Made again as it was, an observation keeps its mark; one taken back has none.
    assert [o.mark for o in again.observations] == ["wrong", "useless", None]
    assert [(m.text, m.mark) for m in again.marks] == [
        ("你在痛的时候让自己忙起来", "wrong"),
        ("难的时候你会走开", "useless"),
    ]
    # The model is told what was wrong or of no use, not what was right.
    assert "不对：你在痛的时候让自己忙起来" in seen[1] and "对但没用：难的时候你会走开" in seen[1]
    assert "本人看过的观察" not in seen[0]


def test_too_little_to_look_at_asks_nothing_of_the_model(tmp_path: Path) -> None:
    llm = FakeLLM(model([]))
    with PersonaStore(tmp_path / "twin.db") as store, pytest.raises(ValueError, match="太少"):
        observations.make(store, llm, [FATHER, HABIT], [], str, str, NOW)
    assert llm.calls == []


def test_other_peoples_names_go_to_the_model_as_codes_and_come_back_as_names(tmp_path: Path) -> None:
    seen: list[str] = []

    def handle(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
        seen.append(user)
        quote = {"ref": ref_of(user, "他人AB12说好"), "quote": "他人AB12说好"}
        return {"observations": [{"kind": "reliance", "text": "你一直在等他人AB12的认可", "quotes": [quote]}]}

    named = item("pi_mentor", "10.4", "很看重老周的评价", ("老周说好", D(2020, 1, 1)))
    with PersonaStore(tmp_path / "twin.db") as store:
        state = observations.make(
            store,
            FakeLLM(handle),
            [named, FATHER, WORK],
            [],
            lambda t: t.replace("老周", "他人AB12"),
            lambda t: t.replace("他人AB12", "老周"),
            NOW,
        )
    assert "老周" not in seen[0]
    assert state.observations[0].text == "你一直在等老周的认可"
    assert state.observations[0].quotes[0].quote == "老周说好"


@pytest.fixture
def web(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[TestClient, list[str]]]:
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
    seen: list[str] = []
    app = create_app(config, llm_factory=lambda: FakeLLM(model(seen)), embedder_factory=HashingEmbedder)
    with TestClient(app, base_url="http://localhost") as client:
        client.app.state.sender = sender  # type: ignore[attr-defined]
        yield client, seen


def login(web: TestClient, email: str) -> None:
    web.post("/api/auth/request", json={"email": email}, headers=CSRF)
    code = str(web.app.state.sender.call_args.args[2])  # type: ignore[attr-defined]
    assert web.post("/api/auth/verify", json={"email": email, "code": code}, headers=CSRF).status_code == 200


def test_the_person_alone_asks_for_observations_and_marks_them(
    web: tuple[TestClient, list[str]], tmp_path: Path
) -> None:
    client, seen = web
    login(client, PERSON)
    persona = client.post("/api/personas", json={"name": "林舟"}, headers=CSRF).json()["id"]
    assert client.put(f"/api/personas/{persona}/claim", json={"claim": PERSON}, headers=CSRF).status_code == 200
    assert [p["mine"] for p in client.get("/api/personas").json()] == [True]
    assert client.post(f"/api/personas/{persona}/approve", json={"public": True}, headers=CSRF).status_code == 200
    mine = {**CSRF, "X-Twin-Persona": persona}

    nothing = client.get("/api/persona/observations", headers=mine).json()
    assert (nothing["made_at"], nothing["observations"]) == (None, [])
    assert [k["label"] for k in nothing["kinds"]] == [
        "不朽工程",
        "对死亡的态度",
        "价值感来源",
        "寄托对象",
        "防御",
        "重复模式",
    ]
    # Too little to look at yet.
    assert client.post("/api/persona/observations", headers=mine).status_code == 400

    with PersonaStore(tmp_path / "personas" / persona / "twin.db") as store:
        for each in ITEMS:
            store.replace_facet_items(each.facet_id, [each])
        store.put_source(
            parse_diary("日记.md", f"# 2024-03-02 梦\n{DREAM}\n\n# 2024-03-03\n早上去跑步。\n", Settings())
        )
    made = client.post("/api/persona/observations", headers=mine)
    assert made.status_code == 200, made.text
    # The dreams the person wrote down are read; the rest of the diary is not.
    assert DREAM in seen[-1] and "早上去跑步" not in seen[-1]
    shown = made.json()["observations"]
    assert [o["kind_label"] for o in shown] == ["防御", "重复模式", "寄托对象"]
    assert shown[2]["quotes"] == [{"quote": DREAM, "date": "2024-03-02", "dream": True}]

    first = shown[0]["id"]
    marked = client.put(f"/api/persona/observations/{first}/mark", json={"mark": "useless"}, headers=mine)
    assert marked.status_code == 200 and marked.json()["observations"][0]["mark"] == "useless"
    assert client.get("/api/persona/observations", headers=mine).json()["observations"][0]["mark"] == "useless"
    assert client.put("/api/persona/observations/ob_x/mark", json={"mark": "right"}, headers=mine).status_code == 404
    assert (
        client.put(f"/api/persona/observations/{first}/mark", json={"mark": "maybe"}, headers=mine).status_code == 400
    )

    login(client, OTHER)
    theirs = {**CSRF, "X-Twin-Persona": persona}
    assert client.get("/api/persona/observations", headers=theirs).status_code == 403
    assert client.post("/api/persona/observations", headers=theirs).status_code == 403
    assert (
        client.put(f"/api/persona/observations/{first}/mark", json={"mark": "right"}, headers=theirs).status_code == 403
    )
