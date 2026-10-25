"""Roster reads stay bounded without changing meeting permissions or voice statistics."""

from __future__ import annotations

import sqlite3
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient
from test_team import decide, meeting

from twin.config import Settings
from twin.media.library import TEAM, Library, owner_key
from twin.media.team import Team
from twin.web.library import Access, Libraries, Viewer, register


def test_people_read_recordings_together_and_preserve_voice_statistics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    library = Library(tmp_path / "library")
    team = Team(library)
    first, second = meeting(library), meeting(library)
    person = team.add_person("同事")
    empty = team.add_person("尚未发言")
    decide(team, first, "S1", "confirm", person.id)
    decide(team, first, "S2", "confirm", person.id)
    decide(team, second, "S1", "confirm", person.id, sample=True)
    with library.transaction() as db:
        db.execute("UPDATE attributions SET auto = 1 WHERE recording_id = ? AND speaker_id = 'S2'", (first,))
    expected = [p.model_dump() for p in team.people()]
    counted = next(p for p in expected if p["id"] == person.id)
    assert (counted["speakers"], counted["samples"], counted["seconds"], counted["checks"]) == (3, 1, 19, 1)
    assert counted["recording_id"] == second  # An actual voice sample takes precedence over merely being heard.
    assert next(p for p in expected if p["id"] == empty.id)["seconds"] == 0
    connections = 0
    original = library.read

    @contextmanager
    def read() -> Iterator[Any]:
        nonlocal connections
        connections += 1
        with original() as db:
            yield db

    def individual_read(*args: Any) -> Any:
        pytest.fail("The roster must not open a separate connection for each recording")

    monkeypatch.setattr(library, "read", read)
    monkeypatch.setattr(library, "get", individual_read)
    assert [p.model_dump() for p in team.people()] == expected
    assert connections == 1
    # A superseded transcript no longer counts, including its representative voice sample; missing speaker
    # metadata still leaves the confirmation counted, but contributes no seconds.
    with library.transaction() as db:
        db.execute("UPDATE recordings SET transcript_id = 'new' WHERE id = ?", (second,))
        db.execute(
            "UPDATE attributions SET speaker_id = 'missing' WHERE recording_id = ? AND speaker_id = 'S2'", (first,)
        )
    counted = next(p for p in team.people() if p.id == person.id)
    assert (counted.speakers, counted.samples, counted.seconds, counted.checks) == (2, 1, 7, 1)
    assert counted.recording_id == first


def test_people_do_not_count_a_new_transcripts_speaker_for_an_old_confirmation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    library = Library(tmp_path / "library")
    team = Team(library)
    rec = meeting(library)
    person = team.add_person("同事")
    decide(team, rec, "S1", "confirm", person.id)
    recording = library.get(rec)
    assert recording is not None
    transcript = library.transcript(recording)
    assert transcript is not None
    newer = transcript.model_copy(
        update={
            "id": "new",
            "speakers": [s.model_copy(update={"seconds": 99}) if s.id == "S1" else s for s in transcript.speakers],
        }
    )
    Library.write_transcript(library.folder(rec), newer)
    switched = False
    original_read = library.read

    def switch_transcript(statement: str) -> None:
        nonlocal switched
        # The confirmed attribution has been read; a different connection commits a new transcript before
        # the bulk recording read. This exercises a real WAL commit, not fabricated rows or timings.
        if not switched and statement.startswith("SELECT * FROM recordings"):
            with sqlite3.connect(library.db_path) as writer:
                writer.execute("UPDATE recordings SET transcript_id = ? WHERE id = ?", (newer.id, rec))
            switched = True

    @contextmanager
    def read() -> Iterator[Any]:
        with original_read() as db:
            db.set_trace_callback(switch_transcript)
            yield db

    monkeypatch.setattr(library, "read", read)
    [counted] = team.people()
    assert switched
    assert counted.speakers == 1 and counted.seconds == 0
    current = library.get(rec)
    assert current is not None and current.transcript_id == newer.id


@pytest.fixture
def roster_web(tmp_path: Path) -> Iterator[tuple[TestClient, Libraries]]:
    app = FastAPI()
    libraries = register(app, Settings(db_path=tmp_path / "twin.db"), MagicMock())

    @app.middleware("http")
    async def identity(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        request.scope["twin_identity"] = {
            "email": request.headers.get("X-Email", "uploader@example.com"),
            "admin": request.headers.get("X-Admin") == "1",
        }
        return await call_next(request)

    with TestClient(app) as web:
        yield web, libraries


def test_people_endpoint_counts_speech_once_and_reuses_permission_reading(
    roster_web: tuple[TestClient, Libraries], monkeypatch: pytest.MonkeyPatch
) -> None:
    web, libraries = roster_web
    library = libraries.library(TEAM)
    team = Team(library)
    rec = meeting(library)
    person = team.add_person("同事")
    decide(team, rec, "S1", "confirm", person.id)
    team.set_account(person.id, owner_key("attendee@example.com"))
    with library.transaction() as db:
        db.execute("UPDATE recordings SET uploader = ?", (owner_key("uploader@example.com"),))
    people_calls = access_calls = 0
    original_people, original_access = Team.people, libraries.access

    def people(self: Team) -> Any:
        nonlocal people_calls
        people_calls += 1
        return original_people(self)

    def access(viewer: Viewer) -> dict[str, Access]:
        nonlocal access_calls
        access_calls += 1
        return original_access(viewer)

    monkeypatch.setattr(Team, "people", people)
    monkeypatch.setattr(libraries, "access", access)
    for email, admin, seen, manage in (
        ("uploader@example.com", False, True, True),
        ("attendee@example.com", False, True, False),
        ("outsider@example.com", False, False, False),
        ("admin@example.com", True, True, True),
    ):
        people_calls = access_calls = 0
        response = web.get("/api/library/people", headers={"X-Email": email, "X-Admin": str(int(admin))})
        assert response.status_code == 200
        [row] = response.json()["items"]
        assert row["id"] == person.id and row["seconds"] == 7 and row["speakers"] == 1
        assert (row["recording_id"] == rec) is seen
        assert (row["last_meeting"] is not None) is seen
        assert row["can_manage"] is manage
        assert "account" not in row and row["persona_id"] is None and row["talk"] is None
        assert people_calls == 1 and access_calls == 1


def test_permission_queries_do_not_need_speech_and_keep_manual_twin_ownership(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = MagicMock()
    libraries = Libraries(Settings(db_path=tmp_path / "twin.db"), MagicMock(), registry)
    team = libraries.team(TEAM)
    account_person = team.add_person("认领声音")
    member_person = team.add_person("认领分身")
    handmade = team.add_person("手工分身", persona_id="handmade")
    unowned = team.add_person("未分配")
    team.set_account(account_person.id, "account")
    with team.library.transaction() as db:
        db.execute(
            "INSERT INTO personas_sync (persona_id, person_id, wanted, done) VALUES (?, ?, 1, 1)",
            ("member-twin", member_person.id),
        )
    registry.entry.side_effect = lambda pid: {
        "member-twin": {"member": "member@example.com"},
        "handmade": {"owner": "owner@example.com", "member": None},
    }.get(pid)

    def speech(*args: Any) -> Any:
        pytest.fail("Permission checks need identities, not full speech statistics")

    monkeypatch.setattr(Team, "people", speech)
    viewer = Viewer("account", "member@example.com", False)
    assert libraries.people_of(viewer) == {account_person.id, member_person.id}
    assert libraries.managed(viewer, {}) == {account_person.id, member_person.id, unowned.id}
    assert handmade.id in (libraries.managed(Viewer("owner", "owner@example.com", False), {}) or set())
    assert libraries.managed(Viewer("admin", "admin@example.com", True), {}) is None


def test_batch_voice_permission_check_reads_access_once_and_preserves_errors(
    roster_web: tuple[TestClient, Libraries], monkeypatch: pytest.MonkeyPatch
) -> None:
    web, libraries = roster_web
    library = libraries.library(TEAM)
    team = Team(library)
    recordings = [meeting(library), meeting(library)]
    person = team.add_person("同事")
    for rec in recordings:
        decide(team, rec, "S1", "confirm", person.id)
    team.set_account(person.id, owner_key("attendee@example.com"))
    with library.transaction() as db:
        db.execute("UPDATE recordings SET uploader = ?", (owner_key("uploader@example.com"),))
    calls = 0
    original = libraries.access

    def access(viewer: Viewer) -> dict[str, Access]:
        nonlocal calls
        calls += 1
        return original(viewer)

    decision = MagicMock(return_value={"done": True})
    monkeypatch.setattr(libraries, "access", access)
    monkeypatch.setattr(libraries, "decide_voice", decision)
    body = {
        "members": [
            {"recording_id": rec.id, "transcript_id": rec.transcript_id, "speaker_id": "S2"} for rec in library.list()
        ],
        "action": "unknown",
    }
    for email, status in (("uploader@example.com", 200), ("attendee@example.com", 403), ("outsider@example.com", 404)):
        calls = 0
        decision.reset_mock()
        response = web.post("/api/library/voices", json=body, headers={"X-Email": email})
        assert response.status_code == status
        assert calls == 1
        assert decision.called is (status == 200)

    hidden = meeting(library)
    hidden_recording = library.get(hidden)
    assert hidden_recording is not None
    # One editable recording must not let a batch also change a recording invisible to the uploader.
    mixed = {
        "members": [
            body["members"][0],
            {"recording_id": hidden, "transcript_id": hidden_recording.transcript_id, "speaker_id": "S2"},
        ],
        "action": "unknown",
    }
    calls = 0
    decision.reset_mock()
    response = web.post("/api/library/voices", json=mixed, headers={"X-Email": "uploader@example.com"})
    assert response.status_code == 404 and calls == 1
    decision.assert_not_called()
