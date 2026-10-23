"""Every twin is a row of the team table: twins made by hand get a person in the library, a name already there is
joined only when the twin's keeper says so, and each person shows the latest meeting they were heard in."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_member_voice import ADMIN, CSRF, OTHER, UPLOADER, as_, meeting, sso_app, team_library

from twin.media.team import Team

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg required")


@pytest.fixture
def web(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    yield from sso_app(tmp_path, monkeypatch)


def people(web: TestClient) -> dict[str, dict[str, Any]]:
    return {p["name"]: p for p in web.get("/api/library/people").json()["items"]}


def matches(web: TestClient) -> list[dict[str, str]]:
    return web.get("/api/library/people").json()["matches"]  # type: ignore[no-any-return]


def make_twin(web: TestClient, cookie: str, name: str) -> str:
    response = as_(web, cookie).post("/api/personas", json={"name": name}, headers=CSRF)
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def heard_zhang(tmp_path: Path) -> str:
    """王五 uploaded a meeting in which S1 is confirmed as 张三, who has no twin."""
    library = team_library(tmp_path)
    meeting(library)
    team = Team(library)
    [unnamed] = team.people()
    zhang = team.add_person("张三")
    team.resolve(unnamed.id, zhang.id)
    return zhang.id


def test_a_twin_made_by_hand_is_a_person_of_the_team_whose_twin_only_its_maker_keeps(
    web: TestClient, tmp_path: Path
) -> None:
    persona = make_twin(web, UPLOADER, "新同事")
    row = people(as_(web, UPLOADER))["新同事"]
    assert (row["persona_id"], row["talk"], row["speakers"], row["last_meeting"]) == (persona, persona, 0, None)
    assert row["can_manage"] is True and not row["auto"]
    assert len([p for p in web.get("/api/library/people").json()["items"] if p["name"] == "新同事"]) == 1
    # It is not a twin the library builds or follows: nothing waits for recordings.
    assert Team(team_library(tmp_path)).synced() == []

    assert row["about"] is None
    named = web.put(
        "/api/identity",
        json={"name": "新同事", "about": "产品负责人\n带八人小团队"},
        headers={**CSRF, "X-Twin-Persona": persona},
    )
    assert named.status_code == 200, named.text
    assert people(web)["新同事"]["about"] == "产品负责人"  # the first line of the introduction

    # Another colleague sees the person, but the twin is private and not theirs to rename or delete.
    other = people(as_(web, OTHER))["新同事"]
    assert (other["persona_id"], other["talk"], other["can_manage"], other["about"]) == (None, None, False, None)
    assert web.patch(f"/api/library/people/{row['id']}", json={"name": "改名"}, headers=CSRF).status_code == 403
    assert web.delete(f"/api/library/people/{row['id']}", headers=CSRF).status_code == 403
    # Made public, they can talk to it, still without keeping it.
    assert as_(web, UPLOADER).patch(f"/api/personas/{persona}", json={"public": True}, headers=CSRF).status_code == 200
    other = people(as_(web, OTHER))["新同事"]
    assert (other["persona_id"], other["talk"], other["twin_elsewhere"], other["can_manage"]) == (
        None,
        persona,
        True,
        False,
    )
    assert other["about"] == "产品负责人"
    # An administrator keeps every twin.
    assert people(as_(web, ADMIN))["新同事"]["can_manage"] is True


def test_a_twin_renamed_renames_the_person_made_for_it_unless_the_meetings_have_that_person(
    web: TestClient, tmp_path: Path
) -> None:
    zhang = heard_zhang(tmp_path)
    persona = make_twin(web, UPLOADER, "新同事")
    row = people(web)["新同事"]
    renamed = web.put(
        "/api/identity", json={"name": "新搭档", "about": ""}, headers={**CSRF, "X-Twin-Persona": persona}
    )
    assert renamed.status_code == 200, renamed.text
    found = people(web)
    assert "新同事" not in found and found["新搭档"]["id"] == row["id"] and found["新搭档"]["persona_id"] == persona
    # A person the meetings know keeps the name they call them, whatever the twin they said was theirs is named.
    kept = make_twin(web, UPLOADER, "张三")
    assert web.post(f"/api/library/people/{zhang}/same", json={"persona_id": kept, "same": True}, headers=CSRF)
    web.put("/api/identity", json={"name": "小张", "about": ""}, headers={**CSRF, "X-Twin-Persona": kept})
    found = people(web)
    assert found["张三"]["id"] == zhang and "小张" not in found


def test_a_twin_without_a_name_yet_is_not_a_person(web: TestClient) -> None:
    as_(web, UPLOADER).get("/api/library/people")
    assert [p["name"] for p in web.get("/api/library/people").json()["items"]] == []


def test_a_twin_named_like_a_person_is_joined_only_when_its_keeper_says_they_are_the_same(
    web: TestClient, tmp_path: Path
) -> None:
    zhang = heard_zhang(tmp_path)
    persona = make_twin(web, UPLOADER, "张三")
    row = people(web)["张三"]
    assert row["id"] == zhang and row["persona_id"] is None and row["speakers"] > 0  # not joined by the name
    expected = [{"persona_id": persona, "person_id": zhang, "name": "张三"}]
    assert matches(web) == expected
    assert matches(as_(web, OTHER)) == []  # not theirs to say
    assert (
        as_(web, OTHER)
        .post(f"/api/library/people/{zhang}/same", json={"persona_id": persona, "same": True}, headers=CSRF)
        .status_code
        == 404
    )
    assert matches(as_(web, ADMIN)) == expected  # whoever keeps it

    as_(web, UPLOADER)
    wrong = web.post(f"/api/library/people/{zhang}x/same", json={"persona_id": persona, "same": True}, headers=CSRF)
    assert wrong.status_code == 409
    joined = web.post(f"/api/library/people/{zhang}/same", json={"persona_id": persona, "same": True}, headers=CSRF)
    assert joined.status_code == 200 and joined.json() == {"same": True}
    assert people(web)["张三"]["persona_id"] == persona and matches(web) == []
    assert Team(team_library(tmp_path)).synced() == []  # the library still does not build it


def test_a_twin_said_not_to_be_the_person_stays_a_twin_of_its_own_and_is_not_asked_about_again(
    web: TestClient, tmp_path: Path
) -> None:
    zhang = heard_zhang(tmp_path)
    persona = make_twin(web, UPLOADER, "张三")
    said = web.post(f"/api/library/people/{zhang}/same", json={"persona_id": persona, "same": False}, headers=CSRF)
    assert said.status_code == 200 and said.json() == {"same": False}
    assert matches(web) == [] and people(web)["张三"]["persona_id"] is None
    assert web.app.state.team.get_meta(f"people:apart:{persona}") == zhang  # type: ignore[attr-defined]
    # Said again, once it is no longer a question.
    assert (
        web.post(
            f"/api/library/people/{zhang}/same", json={"persona_id": persona, "same": True}, headers=CSRF
        ).status_code
        == 409
    )


def test_each_person_shows_the_latest_meeting_among_those_the_viewer_may_see(web: TestClient, tmp_path: Path) -> None:
    zhang = heard_zhang(tmp_path)
    for cookie in (UPLOADER, ADMIN):
        found = people(as_(web, cookie))["张三"]
        assert found["id"] == zhang
        assert found["last_meeting"] == {
            "recording_id": found["last_meeting"]["recording_id"],
            "title": "2026-10-12 周一经营会",
            "date": "2026-10-12",
        }
    # 赵六 may not see the recording, so is not told of the meeting.
    assert people(as_(web, OTHER))["张三"]["last_meeting"] is None


def test_a_twin_forgotten_for_good_takes_its_person_and_its_conversations_unless_meetings_have_the_person(
    web: TestClient, tmp_path: Path
) -> None:
    import datetime as dt

    zhang = heard_zhang(tmp_path)
    kept = make_twin(web, UPLOADER, "张三")
    web.post(f"/api/library/people/{zhang}/same", json={"persona_id": kept, "same": True}, headers=CSRF)
    lone = make_twin(web, UPLOADER, "新同事")
    assert {"张三", "新同事"} <= set(people(web))
    headers = {**CSRF, "X-Twin-Persona": lone}
    conversation = web.post("/api/conversations", json={}, headers=headers).json()["id"]
    team = web.app.state.team  # type: ignore[attr-defined]
    assert team.audience_of(conversation) == "colleague"
    for persona in (kept, lone):
        assert web.delete(f"/api/personas/{persona}", headers=CSRF).status_code == 200
    assert team.conversations(personas=[lone]) != []  # in the trash for a week, they come back with the twin
    registry = web.app.state.personas  # type: ignore[attr-defined]
    registry.clock = lambda: dt.datetime.now(dt.UTC) + dt.timedelta(days=8)
    with registry.lock:
        registry.remove_trash(registry.purge_trash())
    assert team.conversations(include_deleted=True, persona_id=lone) == []
    found = people(web)
    assert "新同事" not in found  # nothing but a twin made it a person
    assert found["张三"]["persona_id"] is None and found["张三"]["speakers"] > 0  # the meetings keep theirs
