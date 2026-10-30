"""继承人开启 (P2.7): an heir opens the twin with their name and word. A wrong name and a wrong word are refused alike
and, too many in a row, make the door wait; the first opening asks, then seals the memory after a snapshot; each heir
enters into a session of their own, whose cookie reaches only their tier and their own conversations; every opening
and entry is logged, never the word."""

from __future__ import annotations

import datetime as dt
import logging
import sqlite3
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_heirs import FAMILY, WITHHELD, WORK, Recorder, markers, name_heir, seed

from twin.config import Settings
from twin.embed import HashingEmbedder
from twin.persona import heir_door, lifecycle, will
from twin.persona import store as storage
from twin.persona.store import PersonaStore, list_snapshots
from twin.web import create_app
from twin.web.heir_door import COOKIE, WRONG
from twin.web.jobs import PersonaProcessing

NOW = dt.datetime(2026, 10, 30, 9, 0, tzinfo=dt.UTC)
CSRF = {"X-Twin": "1"}
WORD = "开启口令123"  # what ``name_heir`` sets
OTHER_WORD = "另一位的口令456"


def raw_dump(path: Path) -> str:
    with closing(sqlite3.connect(path)) as db:
        return "\n".join(db.iterdump())


# ---------------------------------------------------------------- the door itself


@pytest.fixture
def door(tmp_path: Path) -> Iterator[tuple[PersonaStore, str, Path]]:
    path = tmp_path / "twin.db"
    with PersonaStore(path) as store:
        seed(store)
        yield store, name_heir(store), path


def test_a_wrong_name_and_a_wrong_word_are_refused_alike_and_change_nothing(
    door: tuple[PersonaStore, str, Path],
) -> None:
    store, _, _ = door
    for name, word in (("没这个人", WORD), ("小明", "不对的口令"), ("", WORD), ("小明", "")):
        with pytest.raises(heir_door.WrongWord):
            heir_door.open_door(store, name, word, confirm=True, now=NOW)
    assert not lifecycle.sealed(store)
    # The log keeps only that a try was wrong: not whom it named.
    assert store.heir_log() == [(NOW.isoformat(), "", heir_door.FAIL)] * 4


def test_too_many_wrong_tries_make_the_door_wait_longer_each_time(door: tuple[PersonaStore, str, Path]) -> None:
    store, heir_id, path = door
    for _ in range(heir_door.MAX_TRIES - 1):
        with pytest.raises(heir_door.WrongWord):
            heir_door.open_door(store, "小明", "不对的口令", confirm=True, now=NOW)
    with pytest.raises(heir_door.CoolingDown) as waited:
        heir_door.open_door(store, "小明", "不对的口令", confirm=True, now=NOW)
    assert waited.value.seconds == heir_door.FIRST_COOLDOWN
    # While it waits even the right word is not checked, nor counted.
    later = NOW + dt.timedelta(seconds=30)
    with pytest.raises(heir_door.CoolingDown) as waited:
        heir_door.open_door(store, "小明", WORD, confirm=True, now=later)
    assert waited.value.seconds == 30 and not lifecycle.sealed(store)
    assert len(store.heir_log()) == heir_door.MAX_TRIES
    # Restarting does not clear it: the count is in the database.
    with PersonaStore(path) as again:
        assert heir_door.cooldown(again, later) == 30
    # One more wrong try after the wait: twice as long.
    after = NOW + dt.timedelta(seconds=heir_door.FIRST_COOLDOWN)
    with pytest.raises(heir_door.CoolingDown) as waited:
        heir_door.open_door(store, "没这个人", WORD, confirm=True, now=after)
    assert waited.value.seconds == 2 * heir_door.FIRST_COOLDOWN
    # The right word after the wait opens, and the count starts again.
    opened = heir_door.open_door(
        store, "小明", WORD, confirm=True, now=after + dt.timedelta(seconds=2 * heir_door.FIRST_COOLDOWN)
    )
    assert opened is not None and opened.heir.heir_id == heir_id
    assert heir_door.cooldown(store, after + dt.timedelta(seconds=2 * heir_door.FIRST_COOLDOWN)) == 0
    # It never waits more than an hour.
    for _ in range(20):
        store.log_heir(after.isoformat(), "", heir_door.FAIL)
    assert heir_door.cooldown(store, after) == heir_door.MAX_COOLDOWN


def test_the_first_opening_asks_then_seals_after_a_snapshot(door: tuple[PersonaStore, str, Path]) -> None:
    store, heir_id, path = door
    # Right name and word, not yet confirmed: nothing happens.
    assert heir_door.open_door(store, " 小明 ", WORD, confirm=False, now=NOW) is None
    assert not lifecycle.sealed(store) and not list_snapshots(path) and store.heir_log() == []
    opened = heir_door.open_door(store, "小明", WORD, confirm=True, now=NOW)
    assert opened is not None and opened.sealed_now and opened.heir.name == "小明"
    assert lifecycle.sealed(store) and lifecycle.sealed_at(store) == NOW.isoformat()
    # The snapshot is the memory as it was just before: alive.
    [snapshot] = [p for p in list_snapshots(path) if p.name.endswith("-sealed.db")]
    with closing(sqlite3.connect(snapshot)) as db:
        assert db.execute("SELECT value FROM p_meta WHERE key = 'lifecycle'").fetchone() is None
    assert store.heir_log() == [(NOW.isoformat(), heir_id, heir_door.OPEN)]
    # The session's token is kept only as a hash.
    assert heir_door.session_at(path, opened.token, NOW.timestamp()) == heir_door.Session(heir_id, "小明", "张三")
    assert opened.token not in raw_dump(path)
    # Once sealed, an heir enters without being asked, and nothing is snapshotted again.
    other = name_heir_after_seal(path, "小红")
    later = NOW + dt.timedelta(minutes=5)
    entered = heir_door.open_door(store, "小红", OTHER_WORD, confirm=False, now=later)
    assert entered is not None and not entered.sealed_now and len(list_snapshots(path)) == 1
    assert store.heir_log()[-1] == (later.isoformat(), other, heir_door.ENTER)


def name_heir_after_seal(path: Path, name: str) -> str:
    """A second heir, written straight to the store (on the web the will takes no change once sealed)."""
    with PersonaStore(path) as store:
        return will.add(store, will.HeirDraft(name=name, aspects=["D9"]), OTHER_WORD, "person", NOW).heir_id


def test_a_session_ends_when_it_expires_or_is_left_and_opens_nothing_unsealed(
    door: tuple[PersonaStore, str, Path],
) -> None:
    store, _, path = door
    opened = heir_door.open_door(store, "小明", WORD, confirm=True, now=NOW)
    assert opened is not None
    assert heir_door.session_at(path, opened.token, NOW.timestamp() + heir_door.SESSION_SECONDS) is None
    assert heir_door.session_at(path, "0" * 64, NOW.timestamp()) is None
    assert heir_door.session_at(path, opened.token + "x", NOW.timestamp()) is None
    # Rolled back to before the seal (``docs/LOCAL_DEV.md``): no session opens anything.
    store.set_meta(lifecycle.LIFECYCLE, lifecycle.ALIVE)
    assert heir_door.session_at(path, opened.token, NOW.timestamp()) is None
    store.set_meta(lifecycle.LIFECYCLE, lifecycle.SEALED)
    heir_door.leave(store, opened.token)
    assert heir_door.session_at(path, opened.token, NOW.timestamp()) is None
    # A twin without a database or with an older one has no sessions.
    assert heir_door.session_at(path.with_name("missing.db"), opened.token, NOW.timestamp()) is None


def test_an_older_store_upgrades_to_the_heirs_log_after_a_snapshot(tmp_path: Path) -> None:
    path = tmp_path / "twin.db"
    with closing(sqlite3.connect(path)) as db, db:
        for migration in storage._MIGRATIONS[:9]:  # the database as it was before the heirs' door
            db.executescript(migration)
        db.execute("PRAGMA user_version = 9")
    with PersonaStore(path) as store:
        assert store.schema_version() == len(storage._MIGRATIONS)
        store.log_heir(NOW.isoformat(), "heir_x", heir_door.ENTER)
    assert [p.name for p in list_snapshots(path)][-1].endswith("-schema9.db")
    # The log is only ever added to.
    with closing(sqlite3.connect(path)) as db:
        for statement in ("UPDATE p_heir_log SET event = 'x'", "DELETE FROM p_heir_log"):
            with pytest.raises(sqlite3.IntegrityError, match="append-only"):
                db.execute(statement)


# ---------------------------------------------------------------- the web


@pytest.fixture
def web(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, Any]]:
    monkeypatch.setenv("TWIN_EDITION", "persona")
    monkeypatch.setattr(PersonaProcessing, "queue", lambda _: None)
    path = tmp_path / "twin.db"
    with PersonaStore(path) as store:
        seed(store)
        first = name_heir(store)
        second = will.add(store, will.HeirDraft(name="小红", aspects=["D9"]), OTHER_WORD, "person", NOW).heir_id
    llm = Recorder()
    app = create_app(
        Settings(db_path=path, target_name="张三"), llm_factory=lambda: llm, embedder_factory=HashingEmbedder
    )
    clients = [TestClient(app, base_url="http://localhost") for _ in range(3)]
    for client in clients:
        client.__enter__()
    try:
        yield {"path": path, "first": first, "second": second, "person": clients[0], "heirs": clients[1:]}
    finally:
        for client in clients:
            client.__exit__(None, None, None)


def open_(client: TestClient, name: str, word: str, **body: Any) -> Any:
    return client.post("/api/heir/open", json={"name": name, "password": word, **body}, headers=CSRF)


def test_on_the_web_a_wrong_try_says_nothing_of_which_was_wrong_and_too_many_wait(web: dict[str, Any]) -> None:
    client = web["heirs"][0]
    unknown, wrong = open_(client, "没这个人", WORD), open_(client, "小明", "不对的口令")
    assert unknown.status_code == wrong.status_code == 400
    assert unknown.json() == wrong.json() == {"detail": WRONG, "code": "heir_wrong"}
    for _ in range(heir_door.MAX_TRIES - 3):
        assert open_(client, "小明", "不对的口令").status_code == 400
    waited = open_(client, "小明", "不对的口令")
    assert waited.status_code == 429 and waited.json()["code"] == "heir_cooldown"
    assert waited.json()["retry_after"] == int(waited.headers["Retry-After"]) == heir_door.FIRST_COOLDOWN
    # The right word waits too, and nothing is sealed or given.
    assert open_(client, "小明", WORD, confirm=True).status_code == 429
    assert COOKIE not in client.cookies and not lifecycle.sealed_path(web["path"])


def test_on_the_web_the_first_opening_asks_then_seals_and_lets_the_heir_in(web: dict[str, Any]) -> None:
    person, client = web["person"], web["heirs"][0]
    asked = open_(client, "小明", WORD)
    assert asked.status_code == 200 and asked.json() == {"status": "confirm"}
    assert COOKIE not in client.cookies and not lifecycle.sealed_path(web["path"])
    opened = open_(client, "小明", WORD, confirm=True)
    assert opened.json() == {"status": "open", "heir": {"id": web["first"], "name": "小明"}, "sealed_now": True}
    cookie = opened.headers["set-cookie"]
    assert cookie.startswith(f"{COOKIE}=") and "HttpOnly" in cookie and "SameSite=strict" in cookie
    assert "Max-Age" not in cookie and "expires" not in cookie.lower()  # it ends with the browser
    assert lifecycle.sealed_path(web["path"])
    assert any(p.name.endswith("-sealed.db") for p in list_snapshots(web["path"]))
    # The page learns who is there, and that they manage nothing.
    me = client.get("/api/whoami").json()
    assert me["heir"] == {"id": web["first"], "name": "小明", "person": "张三", "persona": me["heir"]["persona"]}
    assert me["admin"] is False and me["heir"]["persona"] == client.cookies[COOKIE].rpartition(".")[0]
    # The person's browser is the person's, as before; the memory takes no more writes.
    assert "heir" not in person.get("/api/whoami").json()
    assert person.post("/api/persona/will/heirs", json={"name": "小刚"}, headers=CSRF).status_code == 423


def test_an_heirs_cookie_reaches_only_their_tier_and_their_own_conversations(web: dict[str, Any]) -> None:
    person, first, second = web["person"], *web["heirs"]
    assert open_(first, "小明", WORD, confirm=True).json()["status"] == "open"
    # Once sealed, the other heir enters straight away.
    entered = open_(second, "小红", OTHER_WORD)
    assert entered.json() == {"status": "open", "heir": {"id": web["second"], "name": "小红"}, "sealed_now": False}
    # Each reads what the will gives them, and nothing only the person may see.
    items = first.get("/api/persona/items").json()
    assert {i["item_id"] for i in items["items"]} == {"pi_work", "pi_family"}
    assert {WORK, FAMILY} <= markers(str(items)) and not markers(str(items)) & WITHHELD
    assert {i["item_id"] for i in second.get("/api/persona/items").json()["items"]} == {
        "pi_family",
        "pi_marriage",
        "pi_health",
    }
    for client in (first, second):
        refused = client.get("/api/persona/will")
        assert refused.status_code == 403 and refused.json()["code"] == "heir_forbidden"
        assert client.get("/api/personas").status_code == 403
    # A twin other than the one they opened is not theirs to reach.
    assert first.get("/api/persona/items", headers={"X-Twin-Persona": "another"}).status_code == 403
    # Conversations: each sees only their own.
    mine = person.post("/api/conversations", json={}, headers=CSRF).json()["id"]
    a = first.post("/api/conversations", json={}, headers=CSRF).json()
    b = second.post("/api/conversations", json={}, headers=CSRF).json()
    assert a["audience"] == f"heir:{web['first']}" and b["audience"] == f"heir:{web['second']}"
    for client, others in ((first, (mine, b["id"])), (second, (mine, a["id"])), (person, (a["id"], b["id"]))):
        for conversation in others:
            assert client.get(f"/api/conversations/{conversation}").status_code == 404
            assert client.delete(f"/api/conversations/{conversation}", headers=CSRF).status_code == 404
    listed = {c["id"] for c in first.get("/api/conversations").json()}
    assert listed == {a["id"]}


def test_a_cookie_that_was_left_forged_or_moved_opens_nothing(web: dict[str, Any]) -> None:
    client = web["heirs"][0]
    open_(client, "小明", WORD, confirm=True)
    value = client.cookies[COOKIE]
    persona_id, _, token = value.rpartition(".")
    assert client.post("/api/heir/leave", headers=CSRF).json() == {"ok": True}
    assert COOKIE not in client.cookies and "heir" not in client.get("/api/whoami").json()
    # The token left behind no longer opens anything; nor one made up, nor one named for a twin that is not there.
    for forged in (value, f"{persona_id}.{'0' * 64}", f"../../x.{token}", token, ""):
        client.cookies.set(COOKIE, forged)
        assert "heir" not in client.get("/api/whoami").json(), forged


def test_the_log_keeps_every_opening_and_entry_and_never_the_word(
    web: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    first, second = web["heirs"]
    caplog.set_level(logging.DEBUG)
    open_(first, "小明", "错的口令xyz")
    open_(first, "小明", WORD, confirm=True)
    open_(second, "小红", OTHER_WORD)
    open_(first, "小明", WORD)
    with PersonaStore(web["path"]) as store:
        log = store.heir_log()
    assert [(heir, event) for _, heir, event in log] == [
        ("", heir_door.FAIL),
        (web["first"], heir_door.OPEN),
        (web["second"], heir_door.ENTER),
        (web["first"], heir_door.ENTER),
    ]
    assert all(dt.datetime.fromisoformat(at).tzinfo is not None for at, _, _ in log)
    # Neither the words tried nor the session tokens are anywhere: not in the database, not in the server's log.
    dump, said = raw_dump(web["path"]), caplog.text
    for secret in (WORD, OTHER_WORD, "错的口令xyz", first.cookies[COOKIE].rpartition(".")[2]):
        assert secret not in dump and secret not in said
