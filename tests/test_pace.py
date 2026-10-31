"""节奏提醒 (P3.6): off unless the person sets a pace; read from when they wrote, kept nowhere new; said once a day."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from twin.config import Settings
from twin.embed import HashingEmbedder
from twin.llm import FakeLLM
from twin.persona import pace
from twin.persona.store import PersonaStore
from twin.web import create_app
from twin.web.jobs import PersonaProcessing

CSRF = {"X-Twin": "1"}
TZ = dt.timezone(dt.timedelta(hours=8))
# A Wednesday evening on the machine's clock.
NOW = dt.datetime(2026, 10, 28, 21, 0, tzinfo=TZ)


def wrote(store: PersonaStore, conversation: str, owner: str | None, *times: dt.datetime) -> None:
    for at in times:
        store.append_conversation_turn(conversation, owner, "user", "嗯", timestamp=at.astimezone(dt.UTC).isoformat())
        store.append_conversation_turn(conversation, owner, "twin", "好", timestamp=at.astimezone(dt.UTC).isoformat())


@pytest.fixture
def store(tmp_path: Path) -> Iterator[PersonaStore]:
    with PersonaStore(tmp_path / "twin.db") as opened:
        yield opened


def test_how_long_and_how_often_are_read_from_when_the_person_wrote(store: PersonaStore) -> None:
    mine = store.create_conversation("me@x")
    other = store.create_conversation("someone@x")
    minute = dt.timedelta(minutes=1)
    # Monday: one time. Today: a run of 20 minutes that began just before midnight, and one of 10 this evening.
    wrote(store, mine, "me@x", dt.datetime(2026, 10, 26, 9, 0, tzinfo=TZ))
    late = dt.datetime(2026, 10, 27, 23, 55, tzinfo=TZ)
    wrote(store, mine, "me@x", late, late + 10 * minute, late + 20 * minute)
    evening = dt.datetime(2026, 10, 28, 20, 0, tzinfo=TZ)
    wrote(store, mine, "me@x", evening, evening + 5 * minute, evening + 10 * minute)
    # Last week, and someone else's conversation, are not the person's this week.
    wrote(store, mine, "me@x", dt.datetime(2026, 10, 25, 20, 0, tzinfo=TZ))
    wrote(store, other, "someone@x", evening)
    use = pace.used(store, "me@x", NOW)
    # Today: 15 minutes after midnight + 1, and 10 + 1.
    assert use == pace.Used(minutes_today=27, times_week=3)
    assert pace.due(pace.Pace(kind="daily_minutes", limit=27), use)
    assert not pace.due(pace.Pace(kind="daily_minutes", limit=28), use)
    assert pace.due(pace.Pace(kind="weekly_times", limit=2), use)
    assert not pace.due(pace.Pace(kind="weekly_times", limit=3), use)
    assert not pace.due(pace.Pace(), use)


def test_the_line_is_said_only_once_the_pace_is_set_and_reached_and_not_again_that_day(store: PersonaStore) -> None:
    mine = store.create_conversation("me@x")
    wrote(store, mine, "me@x", NOW - dt.timedelta(minutes=40), NOW - dt.timedelta(minutes=10))
    assert pace.state(store, "me@x", NOW) == {"pace": {"kind": "off", "limit": 30}, "used": None, "reminder": None}
    pace.put(store, pace.Pace(kind="daily_minutes", limit=30))
    assert pace.state(store, "me@x", NOW)["reminder"] == pace.REMINDER
    pace.go_on(store, NOW.date())
    assert pace.state(store, "me@x", NOW)["reminder"] is None
    assert pace.state(store, "me@x", NOW + dt.timedelta(days=1))["used"] == {"minutes_today": 0, "times_week": 1}


def test_the_person_sets_their_pace_and_goes_on_on_the_web(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TWIN_EDITION", "persona")
    monkeypatch.setattr(PersonaProcessing, "queue", lambda _: None)
    app = create_app(
        Settings(db_path=tmp_path / "twin.db"), llm_factory=lambda: FakeLLM(), embedder_factory=HashingEmbedder
    )
    with TestClient(app, base_url="http://localhost") as web:
        assert web.get("/api/persona/pace").json()["reminder"] is None
        made = web.post("/api/conversations", json={}, headers=CSRF).json()["id"]
        sent = {"messages": [{"role": "user", "content": "记一下，周五不上班"}], "conversation_id": made}
        web.post("/api/persona/chat/stream", json=sent, headers=CSRF)
        set_to = web.put("/api/persona/pace", json={"kind": "daily_minutes", "limit": 1}, headers=CSRF).json()
        assert set_to["pace"] == {"kind": "daily_minutes", "limit": 1} and set_to["used"]["minutes_today"] == 1
        assert set_to["reminder"] == pace.REMINDER
        assert web.post("/api/persona/pace/go-on", headers=CSRF).json()["reminder"] is None
        assert web.get("/api/persona/pace").json()["reminder"] is None
        assert web.put("/api/persona/pace", json={"kind": "weekly_times", "limit": 0}, headers=CSRF).status_code == 400
