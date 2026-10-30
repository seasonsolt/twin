"""数字遗嘱: the person alone names heirs, gives each what the will names and nothing else, keeps only the hash of the
word that opens the twin to them, and every change stays in a history that is only ever appended to."""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from twin.config import AuthSettings, Settings, SMTPSettings
from twin.embed import HashingEmbedder
from twin.llm import FakeLLM
from twin.persona import kernel, will
from twin.persona import store as storage
from twin.persona.dimensions import facets_of
from twin.persona.kernel import TAXONOMY_FACET_IDS, TAXONOMY_MIGRATIONS, TAXONOMY_VERSION
from twin.persona.store import TAXONOMY_META, PersonaStore, list_snapshots
from twin.web import create_app
from twin.web.jobs import PersonaProcessing

CSRF = {"X-Twin": "1"}
PERSON = "person@xjjk.com"
OTHER = "other@xjjk.com"
NOW = dt.datetime(2026, 10, 30, 12, 0)
WORD = "春天里的那棵树"
OTHER_WORD = "秋天的另一句话"


def draft(name: str, **fields: object) -> will.HeirDraft:
    return will.HeirDraft.model_validate({"name": name, **fields})


def raw_dump(path: Path) -> str:
    with sqlite3.connect(path) as db:
        return "\n".join(db.iterdump())


def test_an_older_store_upgrades_to_the_will_after_a_snapshot(tmp_path: Path) -> None:
    path = tmp_path / "twin.db"
    with sqlite3.connect(path) as db:
        for migration in storage._MIGRATIONS[:8]:  # the database as it was before the will
            db.executescript(migration)
        db.execute("PRAGMA user_version = 8")
        db.execute("INSERT INTO p_meta VALUES ('identity:name', '本人')")
    with PersonaStore(path) as store:
        assert store.schema_version() == len(storage._MIGRATIONS) == kernel.KERNEL.schema
        assert store.get_meta("identity:name") == "本人"
        assert will.load(store) == [] and will.history(store) == []
    with sqlite3.connect(path) as db:
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"p_will_heirs", "p_will_history"} <= tables
    assert [p.name for p in list_snapshots(path)][-1].endswith("-schema8.db")


def test_an_heir_is_given_nothing_the_will_does_not_name(tmp_path: Path) -> None:
    with PersonaStore(tmp_path / "twin.db") as store:
        bare = will.add(store, draft("小满"), WORD, "self", NOW)
        assert (bare.aspects, bare.facets, bare.avoid, bare.voice, bare.likeness) == ([], [], [], False, False)
        assert (bare.retire_on, bare.farewell) == (None, None)
        assert will.allowed_facets(bare) == frozenset()

        given = will.add(
            store,
            draft("阿禾", relation="女儿", aspects=["D9", "D2", "D9"], facets=["10.1"], avoid=[" 前一段婚姻 ", ""]),
            OTHER_WORD,
            "self",
            NOW,
        )
        assert given.aspects == ["D2", "D9"] and given.avoid == ["前一段婚姻"]
        expected = {f.facet_id for d in ("D2", "D9") for f in facets_of(d)} | {"10.1"}
        assert will.allowed_facets(given) == expected
        assert [h.name for h in will.load(store)] == ["小满", "阿禾"]


def test_only_the_hash_of_the_word_is_kept_and_it_is_checked(tmp_path: Path) -> None:
    path = tmp_path / "twin.db"
    with PersonaStore(path) as store:
        first = will.add(store, draft("小满"), WORD, "self", NOW)
        second = will.add(store, draft("阿禾"), WORD, "self", NOW)
        assert will.verify(store, first.heir_id, WORD)
        assert not will.verify(store, first.heir_id, OTHER_WORD)
        assert not will.verify(store, first.heir_id, "")
        assert not will.verify(store, "heir_nobody", WORD)
        kept = [json.loads(store.will_secret(h.heir_id) or "") for h in (first, second)]
        shown = json.dumps([h.model_dump(mode="json") for h in will.load(store)])
    assert {k["kdf"] for k in kept} == {"scrypt"} and all(k["n"] >= 2**15 for k in kept)
    # A fresh salt each time: the same word never hashes the same twice.
    assert kept[0]["salt"] != kept[1]["salt"] and kept[0]["hash"] != kept[1]["hash"]
    dump = raw_dump(path)
    assert WORD not in dump and WORD.encode().hex() not in dump
    # The hash lives apart from what is shown and from the history.
    assert kept[0]["hash"] not in shown and "salt" not in shown
    with sqlite3.connect(path) as db:
        assert all(kept[0]["hash"] not in r[0] for r in db.execute("SELECT json FROM p_will_history"))


def test_changing_an_heir_keeps_their_word_unless_a_new_one_is_given(tmp_path: Path) -> None:
    with PersonaStore(tmp_path / "twin.db") as store:
        heir = will.add(store, draft("小满"), WORD, "self", NOW)
        later = NOW + dt.timedelta(days=1)
        changed = will.update(
            store, heir.heir_id, draft("小满", aspects=["D6"], retire_on="2040-01-01"), None, "self", later
        )
        assert changed.created_at == heir.created_at and changed.updated_at == later.isoformat(timespec="seconds")
        assert will.verify(store, heir.heir_id, WORD)
        # Nothing changed: no row of history.
        assert will.update(store, heir.heir_id, draft("小满", aspects=["D6"], retire_on="2040-01-01"), None, "s", NOW)
        will.update(store, heir.heir_id, draft("小满", aspects=["D6"], retire_on="2040-01-01"), OTHER_WORD, "s", NOW)
        assert will.verify(store, heir.heir_id, OTHER_WORD) and not will.verify(store, heir.heir_id, WORD)
        assert [c.changes for c in will.history(store)][1:] == [["aspects", "retire_on"], ["password"]]
        with pytest.raises(KeyError):
            will.update(store, "heir_nobody", draft("x"), None, "self", NOW)
        with pytest.raises(KeyError):
            will.remove(store, "heir_nobody", "self", NOW)


@pytest.mark.parametrize(
    ("fields", "word", "message"),
    [
        ({"name": "  "}, WORD, "称呼"),
        ({"name": "小满"}, "短", "口令"),
        ({"name": "小满"}, "x" * 129, "口令"),
        ({"name": "小 满"}, WORD, None),  # spaces are folded, so this one is kept
    ],
)
def test_a_draft_that_will_not_do_is_refused(
    tmp_path: Path, fields: dict[str, object], word: str, message: str | None
) -> None:
    with PersonaStore(tmp_path / "twin.db") as store:
        if message is None:
            assert will.add(store, will.HeirDraft.model_validate(fields), word, "self", NOW).name == "小 满"
            return
        with pytest.raises(ValueError, match=message):
            will.add(store, will.HeirDraft.model_validate(fields), word, "self", NOW)
        assert will.load(store) == [] and will.history(store) == []


def test_a_draft_names_only_aspects_and_facets_that_exist() -> None:
    for fields in ({"aspects": ["D11"]}, {"facets": ["99.9"]}, {"avoid": ["话" * 61]}, {"secret": "x"}):
        with pytest.raises(ValueError):
            draft("小满", **fields)
    with PersonaStore(":memory:") as store:
        will.add(store, draft("小满"), WORD, "self", NOW)
        with pytest.raises(ValueError, match="已经有"):
            will.add(store, draft("小满"), WORD, "self", NOW)


def test_the_history_is_only_ever_appended_to(tmp_path: Path) -> None:
    path = tmp_path / "twin.db"
    with PersonaStore(path) as store:
        heir = will.add(store, draft("小满", avoid=["公司的事"]), WORD, PERSON, NOW)
        will.update(store, heir.heir_id, draft("小满", relation="朋友"), None, PERSON, NOW)
        will.remove(store, heir.heir_id, PERSON, NOW)
        kept = will.history(store)
    assert [(c.action, c.heir_id, c.actor) for c in kept] == [
        ("add", heir.heir_id, PERSON),
        ("update", heir.heir_id, PERSON),
        ("remove", heir.heir_id, PERSON),
    ]
    assert "password" in kept[0].changes and kept[1].changes == ["relation", "avoid"]
    # Each row is the whole will after the change: what it gave survives the heir's removal.
    assert kept[0].heirs[0].avoid == ["公司的事"] and kept[1].heirs[0].relation == "朋友" and kept[2].heirs == []
    with sqlite3.connect(path) as db:
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            db.execute("UPDATE p_will_history SET actor = 'someone'")
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            db.execute("DELETE FROM p_will_history")
        assert db.execute("SELECT count(*) FROM p_will_history").fetchone() == (3,)


def test_a_taxonomy_upgrade_gives_on_every_facet_a_given_one_became(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "twin.db"
    with PersonaStore(path) as store:
        heir = will.add(store, draft("小满", facets=["2.1", "4.2", "6.1", "9.1"]), WORD, "self", NOW)
    # An older taxonomy "t0": 2.9 split into 2.1 and 2.2, 4.9 became 4.2, 6.9 was dropped.
    current = TAXONOMY_FACET_IDS[TAXONOMY_VERSION]
    old_ids = {"2.1": "2.9", "4.2": "4.9", "6.1": "6.9"}
    monkeypatch.setattr(
        kernel,
        "TAXONOMY_FACET_IDS",
        {"t0": tuple(old_ids.get(f, f) for f in current if f != "2.2"), **TAXONOMY_FACET_IDS},
    )
    first = next(iter(TAXONOMY_FACET_IDS))
    step = {"2.9": ("2.1", "2.2"), "4.9": ("4.2",), "6.9": ()}
    monkeypatch.setattr(kernel, "TAXONOMY_MIGRATIONS", {first: step, **TAXONOMY_MIGRATIONS})
    with sqlite3.connect(path) as db:
        row = json.loads(db.execute("SELECT json FROM p_will_heirs").fetchone()[0])
        row["facets"] = ["2.9", "4.9", "6.9", "9.1"]
        db.execute("UPDATE p_will_heirs SET json = ?", (json.dumps(row),))
        db.execute("UPDATE p_meta SET value = 't0' WHERE key = ?", (TAXONOMY_META,))
    with PersonaStore(path) as store:
        assert will.get(store, heir.heir_id).facets == ["2.1", "2.2", "4.2", "9.1"]
        assert [(c.action, c.actor, c.changes) for c in will.history(store)][-1] == ("taxonomy", "twin", ["facets"])
        assert will.verify(store, heir.heir_id, WORD)


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


def test_the_person_alone_reads_and_writes_their_will_and_no_answer_carries_the_word(
    web: TestClient, tmp_path: Path
) -> None:
    login(web, PERSON)
    persona = web.post("/api/personas", json={"name": "林舟"}, headers=CSRF).json()["id"]
    assert web.put(f"/api/personas/{persona}/claim", json={"claim": PERSON}, headers=CSRF).status_code == 200
    assert [p["mine"] for p in web.get("/api/personas").json()] == [True]  # the claim is taken up on reading
    assert web.post(f"/api/personas/{persona}/approve", json={"public": True}, headers=CSRF).status_code == 200
    mine = {**CSRF, "X-Twin-Persona": persona}
    session = web.cookies.get("twin_session")
    answers: list[str] = []

    def call(method: str, url: str, **kwargs: object) -> dict:  # type: ignore[type-arg]
        response = web.request(method, url, headers=mine, **kwargs)  # type: ignore[arg-type]
        answers.append(response.text)
        assert response.status_code == 200, response.text
        return response.json()  # type: ignore[no-any-return]

    assert call("GET", "/api/persona/will") == {"heirs": []}
    # Naming an heir needs a word; a refused one is not echoed.
    refused = web.post("/api/persona/will/heirs", json={"name": "阿禾"}, headers=mine)
    assert refused.status_code == 400
    short = web.post("/api/persona/will/heirs", json={"name": "阿禾", "password": "春风"}, headers=mine)
    assert short.status_code == 400 and "春风" not in short.text
    unnamed = web.post("/api/persona/will/heirs", json={"password": WORD}, headers=mine)
    assert unnamed.status_code == 400 and WORD not in unnamed.text
    answers += [refused.text, short.text, unnamed.text]

    heir = call(
        "POST",
        "/api/persona/will/heirs",
        json={"name": "阿禾", "relation": "女儿", "aspects": ["D9"], "avoid": ["公司的事"], "password": WORD},
    )["heir"]
    assert (heir["name"], heir["aspects"], heir["voice"], heir["retire_on"]) == ("阿禾", ["D9"], False, None)
    heir_id = heir["heir_id"]
    changed = call(
        "PUT",
        f"/api/persona/will/heirs/{heir_id}",
        json={"name": "阿禾", "aspects": ["D9"], "voice": True, "retire_on": "2050-06-01", "farewell": "去吧"},
    )["heir"]
    assert (changed["voice"], changed["retire_on"], changed["farewell"], changed["relation"]) == (
        True,
        "2050-06-01",
        "去吧",
        "",
    )
    assert [h["heir_id"] for h in call("GET", "/api/persona/will")["heirs"]] == [heir_id]
    history = call("GET", "/api/persona/will/history")["changes"]
    assert [c["action"] for c in history] == ["add", "update"]
    assert web.put("/api/persona/will/heirs/heir_x", json={"name": "x"}, headers=mine).status_code == 404

    db = tmp_path / "personas" / persona / "twin.db"
    with PersonaStore(db) as store:
        assert will.verify(store, heir_id, WORD)  # a change without a word keeps it
        secret = json.loads(store.will_secret(heir_id) or "")
    for text in answers:
        assert WORD not in text and secret["hash"] not in text and secret["salt"] not in text and "scrypt" not in text

    login(web, OTHER)
    theirs = {**CSRF, "X-Twin-Persona": persona}
    for method, url, body in (
        ("GET", "/api/persona/will", None),
        ("GET", "/api/persona/will/history", None),
        ("POST", "/api/persona/will/heirs", {"name": "我", "password": WORD}),
        ("PUT", f"/api/persona/will/heirs/{heir_id}", {"name": "我"}),
        ("DELETE", f"/api/persona/will/heirs/{heir_id}", None),
    ):
        assert web.request(method, url, json=body, headers=theirs).status_code == 403, (method, url)

    web.cookies.set("twin_session", session or "")
    assert call("DELETE", f"/api/persona/will/heirs/{heir_id}") == {"ok": True}
    assert call("GET", "/api/persona/will") == {"heirs": []}
    assert [c["action"] for c in call("GET", "/api/persona/will/history")["changes"]] == ["add", "update", "remove"]
    with PersonaStore(db) as store:
        assert store.will_secret(heir_id) is None and not will.verify(store, heir_id, WORD)
