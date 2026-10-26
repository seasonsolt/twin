"""The team's commitments: every twin's ledger read together, one entry for what was said once."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from twin.config import AuthSettings, Settings, SMTPSettings
from twin.embed import HashingEmbedder
from twin.llm import FakeLLM
from twin.media.library import Library
from twin.media.team import SOURCE_PREFIX
from twin.persona import gate
from twin.persona import ledger as lg
from twin.persona.schema import ReviewStatus, Source, SourceKind
from twin.persona.sources import parse_media
from twin.persona.store import PersonaStore
from twin.web import create_app
from twin.web.jobs import PersonaProcessing

CSRF = {"X-Twin": "1"}
MEMBER = "member@xjjk.com"
OTHER = "other@xjjk.com"
MEETING = "rec_0123456789abcdef0123"


def entry(
    entry_id: str, source: str, line: int, owner: str, what: str, kind: str = "commitment", **extra: Any
) -> lg.LedgerEntry:
    return lg.LedgerEntry(
        entry_id=entry_id,
        source_id=source,
        expression_id=f"{source}#{line:05d}",
        meeting_date=dt.date(2026, 10, 12),
        meeting_title="周一经营会",
        kind=kind,  # type: ignore[arg-type]
        speaker=owner,
        quote=f"{what}，没问题",
        owner=owner,
        what=what,
        confidence=0.9,
        extractor=lg.LEDGER_VERSION,
        created_at="now",
        updated_at="now",
        **extra,
    )


def library_source(digest: str) -> str:
    """What the library makes of one meeting for one person: the id differs with the person's own lines."""
    return f"{SOURCE_PREFIX}{MEETING}_{digest}"


def seed(path: Path, entries: list[lg.LedgerEntry]) -> None:
    with PersonaStore(path) as store:
        for e in entries:
            store.put_ledger_entry(e)


def read_meeting(path: Path, source_id: str, name: str, done: bool = False) -> None:
    """A recording the twin of ``name`` was in and the other person spoke in, read for its ledger or not yet."""
    source = Source(
        source_id=source_id,
        kind=SourceKind.AUDIO,
        title="周一经营会",
        origin="meeting.m4a",
        imported_at="now",
        n_expressions=0,
        n_target=0,
        creation_time="2026-10-12T09:00:00",
        media_status="ready",
        text_state="raw",
    )
    lines = [(name, "[00:00] 我周五前给华澜新报价方案。", True), ("其他人1", "[00:01] 好的，周五等你。", False)]
    with PersonaStore(path) as store:
        store.put_source(parse_media(source, lines))
        if done:
            store.replace_ledger_source(source_id, [], lg.LEDGER_VERSION)


def keep(path: Path, name: str) -> None:
    with PersonaStore(path) as store:
        store.set_meta("identity:name", name)


@pytest.fixture
def web(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setattr(PersonaProcessing, "queue", lambda _: None)
    app = create_app(
        Settings(db_path=tmp_path / "twin.db", target_name="默认"),
        llm_factory=lambda: FakeLLM(lambda *_: {}),
        embedder_factory=HashingEmbedder,
    )
    with TestClient(app, base_url="http://localhost") as client:
        yield client


def twin(web: TestClient, tmp_path: Path, name: str) -> tuple[str, Path]:
    persona = web.post("/api/personas", json={"name": name}, headers=CSRF).json()["id"]
    path = tmp_path / "personas" / persona / "twin.db"
    keep(path, name)
    return str(persona), path


def test_a_meeting_in_two_ledgers_is_counted_once_and_told_by_name(web: TestClient, tmp_path: Path) -> None:
    lin, lin_db = twin(web, tmp_path, "林舟")
    xu, xu_db = twin(web, tmp_path, "许清禾")
    a, b = library_source("aaaaaaaaaaaa"), library_source("bbbbbbbbbbbb")
    # 林舟 promised on line 3 and 许清禾 on line 7; both are in the meeting, so each ledger holds both, the other's
    # told by name. 许清禾 alone has an objection of their own, and a later meeting is only in 林舟's.
    seed(
        lin_db,
        [
            entry("lin_own_001", a, 3, lg.SELF, "周五前给华澜新报价方案"),
            entry("lin_xu_0001", a, 7, "许清禾", "周三前补齐渠道数据"),
            entry("lin_later01", "text_meeting", 2, lg.SELF, "月底前评审完新人手册"),
        ],
    )
    seed(
        xu_db,
        [
            entry("xu_lin_0001", b, 3, "林舟", "周五前给华澜新报价方案"),
            entry("xu_own_0001", b, 7, lg.SELF, "周三前补齐渠道数据"),
            entry("xu_object01", b, 9, lg.SELF, "渠道预算不够", kind="objection"),
        ],
    )
    singles = {
        persona: web.get("/api/persona/ledger", headers={"X-Twin-Persona": persona}).json()["entries"]
        for persona in (lin, xu)
    }
    assert [len(rows) for rows in singles.values()] == [3, 3]

    everyone = web.get("/api/personas/commitments")
    assert everyone.status_code == 200, everyone.text
    rows = everyone.json()["entries"]
    # Six lines in the two ledgers, two of them the same promises: four commitments and one objection are left.
    assert len(rows) == sum(len(r) for r in singles.values()) - 2 == 4
    assert {(r["meeting"], r["owner"], r["kind"], r["persona_name"]) for r in rows} == {
        (MEETING, "林舟", "commitment", "林舟"),
        (MEETING, "许清禾", "commitment", "许清禾"),
        (MEETING, "许清禾", "objection", "许清禾"),
        ("text_meeting", "林舟", "commitment", "林舟"),
    }
    # Each promise is kept where its owner's own ledger has it, so changing it there is changing the right entry.
    by_owner = {(r["owner"], r["kind"], r["meeting"]): r for r in rows}
    assert by_owner[("林舟", "commitment", MEETING)]["entry_id"] == "lin_own_001"
    assert by_owner[("林舟", "commitment", MEETING)]["persona_id"] == lin
    assert by_owner[("许清禾", "commitment", MEETING)]["entry_id"] == "xu_own_0001"
    assert by_owner[("许清禾", "commitment", MEETING)]["persona_id"] == xu
    # Nobody is "本人" in a list of several people.
    assert all(lg.SELF not in (r["owner"], r["speaker"], r["counterpart"]) for r in rows)
    assert everyone.json()["people"] == ["林舟", "许清禾"] or everyone.json()["people"] == ["许清禾", "林舟"]
    assert {t["name"] for t in everyone.json()["twins"]} == {"林舟", "许清禾"}


def test_a_meeting_not_yet_read_is_counted_once_however_many_twins_were_in_it(web: TestClient, tmp_path: Path) -> None:
    lin, lin_db = twin(web, tmp_path, "林舟")
    xu, xu_db = twin(web, tmp_path, "许清禾")
    read_meeting(lin_db, library_source("aaaaaaaaaaaa"), "林舟")
    read_meeting(xu_db, library_source("bbbbbbbbbbbb"), "许清禾")
    # One recording both were in: one meeting, and it is not read yet.
    data = web.get("/api/personas/commitments").json()
    assert data["meetings"] == {"total": 1, "pending": 1}
    assert {t["id"]: t["pending"] for t in data["twins"]} == {lin: 1, xu: 1}
    # Read for one of them only, it is still a meeting waiting, and the list says whose ledger has it to do.
    read_meeting(lin_db, library_source("aaaaaaaaaaaa"), "林舟", done=True)
    data = web.get("/api/personas/commitments").json()
    assert data["meetings"] == {"total": 1, "pending": 1}
    assert {t["id"]: t["pending"] for t in data["twins"]} == {lin: 0, xu: 1}
    read_meeting(xu_db, library_source("bbbbbbbbbbbb"), "许清禾", done=True)
    data = web.get("/api/personas/commitments").json()
    assert data["meetings"] == {"total": 1, "pending": 0}
    assert {t["pending"] for t in data["twins"]} == {0}


def test_a_twin_whose_memory_is_being_rebuilt_is_listed_from_its_last_build_and_said_to_be_updating(
    web: TestClient, tmp_path: Path
) -> None:
    lin, lin_db = twin(web, tmp_path, "林舟")
    _, xu_db = twin(web, tmp_path, "许清禾")
    seed(lin_db, [entry("lin_own_001", library_source("aaaaaaaaaaaa"), 3, lg.SELF, "周五前给华澜新报价方案")])
    seed(xu_db, [entry("xu_own_0001", library_source("bbbbbbbbbbbb"), 7, lg.SELF, "周三前补齐渠道数据")])
    # 林舟's twin is made from the team's library, which has decisions it has not been rebuilt from yet.
    library = Library(tmp_path / "library" / "team")
    with PersonaStore(lin_db) as store:
        gate.link(store, library.db_path, lin)
    with library.transaction() as db:
        db.execute("INSERT INTO personas_sync (persona_id, person_id, wanted, done) VALUES (?, 'per_x', 2, 1)", (lin,))
    assert web.get("/api/persona/ledger", headers={"X-Twin-Persona": lin}).status_code == 200
    everyone = web.get("/api/personas/commitments").json()
    assert {r["entry_id"] for r in everyone["entries"]} == {"lin_own_001", "xu_own_0001"}
    # Whose may change soon is said.
    assert everyone["updating"] == [{"id": lin, "name": "林舟"}]
    # The library says a rebuild is under way, so the team page asks for people again without a recording changing.
    started = web.get("/api/library").json()["twins"]
    assert started["updating"] == 1
    with library.transaction() as db:
        db.execute("UPDATE personas_sync SET done = wanted")
    finished = web.get("/api/library").json()["twins"]
    assert finished["updating"] == 0 and finished["revision"] != started["revision"]
    everyone = web.get("/api/personas/commitments").json()
    assert {r["entry_id"] for r in everyone["entries"]} == {"lin_own_001", "xu_own_0001"}
    assert everyone["updating"] == []


def test_a_rejected_entry_is_left_out_unless_asked_for_and_the_reviewed_copy_wins(
    web: TestClient, tmp_path: Path
) -> None:
    lin, lin_db = twin(web, tmp_path, "林舟")
    _, xu_db = twin(web, tmp_path, "许清禾")
    a, b = library_source("aaaaaaaaaaaa"), library_source("bbbbbbbbbbbb")
    # Neither copy is in 林舟's own ledger as "本人", so the one the person looked at is kept.
    seed(lin_db, [entry("lin_copy_001", a, 4, "许清禾", "整理周报", review=ReviewStatus.CONFIRMED)])
    seed(xu_db, [entry("xu_copy_0001", b, 4, "许清禾", "整理周报"), entry("xu_gone_001", b, 8, "林舟", "取消演示")])
    with PersonaStore(xu_db) as store:
        gone = store.get_ledger_entry("xu_gone_001")
        assert gone is not None
        store.put_ledger_entry(gone.model_copy(update={"review": ReviewStatus.REJECTED}))
    rows = web.get("/api/personas/commitments").json()["entries"]
    assert [(r["entry_id"], r["persona_id"]) for r in rows] == [("lin_copy_001", lin)]
    with_rejected = web.get("/api/personas/commitments?include_rejected=true").json()["entries"]
    assert {r["entry_id"] for r in with_rejected} == {"lin_copy_001", "xu_gone_001"}


@pytest.fixture
def accounts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("TWIN_SMTP_PASSWORD", "test-only")
    monkeypatch.setattr(PersonaProcessing, "queue", lambda _: None)
    sender = MagicMock()
    monkeypatch.setattr("twin.web.auth.send_code", sender)
    settings = Settings(
        db_path=tmp_path / "twin.db",
        auth=AuthSettings(
            enabled=True, smtp=SMTPSettings(host="smtp.example.com", username="test", from_address="t@example.com")
        ),
    )
    app = create_app(settings, llm_factory=lambda: FakeLLM(lambda *_: {}), embedder_factory=HashingEmbedder)
    with TestClient(app, base_url="http://localhost") as client:
        client.app.state.sender = sender  # type: ignore[attr-defined]
        yield client


def login(web: TestClient, email: str) -> None:
    web.post("/api/auth/request", json={"email": email}, headers=CSRF)
    code = str(web.app.state.sender.call_args.args[2])  # type: ignore[attr-defined]
    assert web.post("/api/auth/verify", json={"email": email, "code": code}, headers=CSRF).status_code == 200


def test_only_the_twins_a_person_looks_after_are_in_their_list(accounts: TestClient, tmp_path: Path) -> None:
    login(accounts, MEMBER)
    mine = accounts.post("/api/personas", json={"name": "林舟"}, headers=CSRF).json()["id"]
    mine_db = tmp_path / "personas" / mine / "twin.db"
    keep(mine_db, "林舟")
    seed(mine_db, [entry("lin_own_001", library_source("aaaaaaaaaaaa"), 3, lg.SELF, "周五前给华澜新报价方案")])
    login(accounts, OTHER)
    # A colleague who looks after no twin has nothing to see, and is told so rather than shown an empty team.
    assert accounts.get("/api/personas/commitments").status_code == 403
    theirs = accounts.post("/api/personas", json={"name": "许清禾"}, headers=CSRF).json()["id"]
    theirs_db = tmp_path / "personas" / theirs / "twin.db"
    keep(theirs_db, "许清禾")
    seed(theirs_db, [entry("xu_own_0001", library_source("bbbbbbbbbbbb"), 7, lg.SELF, "周三前补齐渠道数据")])
    rows = accounts.get("/api/personas/commitments").json()["entries"]
    assert [(r["entry_id"], r["owner"]) for r in rows] == [("xu_own_0001", "许清禾")]


def test_a_promise_asked_for_in_a_conversation_is_the_persons_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A commitment made from a handoff holds the asker's question and name, which only the person sees, as the
    handoff itself: an administrator looking after the twin neither lists, briefs on nor reviews it."""
    from teamkit import ADMIN, make_web

    for scene in make_web(tmp_path, monkeypatch):
        lin = scene.add_twin("lin", MEMBER, "林舟")
        asked = entry(
            "asked_00001",
            "conv_source",
            2,
            lg.SELF,
            "周五前给许清禾报价",
            origin="conversation",
            counterpart="许清禾",
            handoff_id="h1",
        )
        seed(lin.path, [asked, entry("meeting_001", "text_meeting", 3, lg.SELF, "月底前评审新人手册")])
        brief = "/api/persona/ledger/brief?person=许清禾"

        scene.as_(ADMIN)
        listed = scene.web.get("/api/persona/ledger", headers=lin.headers)
        assert listed.status_code == 200, listed.text
        assert [e["entry_id"] for e in listed.json()["entries"]] == ["meeting_001"]
        assert scene.web.get(brief, headers=lin.headers).json()["mine"] == []
        everyone = scene.web.get("/api/personas/commitments").json()["entries"]
        assert {e["entry_id"] for e in everyone} == {"meeting_001"}
        refused = scene.web.post(
            "/api/persona/ledger/asked_00001/review", json={"action": "reject"}, headers=lin.headers
        )
        assert refused.status_code == 403
        assert (
            scene.web.post(
                "/api/persona/ledger/meeting_001/review", json={"action": "confirm"}, headers=lin.headers
            ).status_code
            == 200
        )

        scene.as_(MEMBER)
        mine = scene.web.get("/api/persona/ledger", headers=lin.headers).json()["entries"]
        assert {e["entry_id"] for e in mine} == {"asked_00001", "meeting_001"}
        assert [e["entry_id"] for e in scene.web.get(brief, headers=lin.headers).json()["mine"]] == ["asked_00001"]
        assert "asked_00001" in {e["entry_id"] for e in scene.web.get("/api/personas/commitments").json()["entries"]}
        reviewed = scene.web.post(
            "/api/persona/ledger/asked_00001/review", json={"action": "confirm"}, headers=lin.headers
        )
        assert reviewed.status_code == 200, reviewed.text
