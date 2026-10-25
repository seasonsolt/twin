"""The recording library is the team's: who sees and decides what, "不是我", and the merge of the libraries earlier
versions kept per account."""

from __future__ import annotations

import datetime as dt
import json
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_library import upload, wav_bytes
from test_member_voice import ADMIN, CSRF, MEMBER, OTHER, UPLOADER, as_, meeting, open_twin, sso_app, uploaded
from test_team import recording, until

from twin.media import merge
from twin.media.ingest import Segment, Speaker
from twin.media.library import Library, owner_key
from twin.media.team import Team
from twin.persona import gate
from twin.persona.store import PersonaStore

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg required")

WANG, ZHANG = owner_key("sso:2001"), owner_key("sso:2002")


@pytest.fixture
def web(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    yield from sso_app(tmp_path, monkeypatch)


def team_of(tmp_path: Path) -> Library:
    return Library(tmp_path / "library" / "team")


def zhang_was_there(library: Library) -> tuple[str, str]:
    """王五's meeting, where S1 is confirmed as 张三, whose account said so."""
    rec = meeting(library)
    team = Team(library)
    [unnamed] = team.people()
    zhang = team.add_person("张三")
    team.resolve(unnamed.id, zhang.id)
    team.set_account(zhang.id, ZHANG)
    return rec, zhang.id


def detail(web: TestClient, rec: str) -> Any:
    return web.get(f"/api/library/recordings/{rec}")


def test_uploader_admin_attendee_and_everyone_else(web: TestClient, tmp_path: Path) -> None:
    library = team_of(tmp_path)
    rec, zhang = zhang_was_there(library)

    # Whoever uploaded it, and administrators, see it whole and decide about it.
    for cookie in (UPLOADER, ADMIN):
        as_(web, cookie)
        [row] = web.get("/api/library").json()["recordings"]
        assert row["id"] == rec and row["can_edit"] is True
        found = detail(web, rec).json()
        assert found["can_edit"] is True and any("candidates" in s for s in found["speakers"])

    # Someone identified in it reads and hears it, without deciding.
    as_(web, MEMBER)
    [row] = web.get("/api/library").json()["recordings"]
    assert row["can_edit"] is False
    found = detail(web, rec).json()
    assert found["can_edit"] is False and found["mine"] == ["S1"] and found["segments"]
    assert web.get(f"/api/library/recordings/{rec}/speakers/S2/samples/0").status_code == 200
    assert web.delete(f"/api/library/recordings/{rec}", headers=CSRF).status_code == 403
    assert web.post(f"/api/library/recordings/{rec}/retry", headers=CSRF).status_code == 403
    assert web.get("/api/library/review").json()["items"] == []

    # Everyone else sees nothing of it: not the recording, its sound, or where anyone speaks.
    as_(web, OTHER)
    assert web.get("/api/library").json()["recordings"] == []
    for path in (f"/api/library/recordings/{rec}", f"/api/library/recordings/{rec}/speakers/S1/samples/0"):
        assert web.get(path).status_code == 404
    assert web.delete(f"/api/library/recordings/{rec}", headers=CSRF).status_code == 404
    [person] = web.get("/api/library/people").json()["items"]
    assert person["name"] == "张三" and person["recording_id"] is None and person["can_manage"] is False
    assert "account" not in person
    assert web.patch(f"/api/library/people/{zhang}", json={"name": "张三丰"}, headers=CSRF).status_code == 403
    assert web.post(f"/api/library/people/{zhang}/persona", headers=CSRF).status_code == 403
    assert web.delete(f"/api/library/people/{zhang}", headers=CSRF).status_code == 403


def test_not_me_undoes_the_speaker_and_waits_for_the_uploader(web: TestClient, tmp_path: Path) -> None:
    library = team_of(tmp_path)
    rec, zhang = zhang_was_there(library)
    as_(web, MEMBER)
    # Only a speaker given to them.
    assert web.post(f"/api/library/recordings/{rec}/speakers/S2/not-me", headers=CSRF).status_code == 409
    said = web.post(f"/api/library/recordings/{rec}/speakers/S1/not-me", headers=CSRF)
    assert said.status_code == 200 and said.json() == {"disputed": True}
    view = {s.id: s for s in Team(library).speakers(library.get(rec))}  # type: ignore[arg-type]
    assert view["S1"].decision == "none" and view["S1"].disputed and view["S1"].rejected == [zhang]
    # No longer identified there, they no longer see it; voice matching never gives it back to them.
    assert detail(web, rec).status_code == 404
    Team(library).classify_all()
    assert Team(library).speakers(library.get(rec))[0].decision == "none"  # type: ignore[arg-type,index]

    # It waits at the top of the uploader's queue; what they decide stands, and settles the dispute.
    as_(web, UPLOADER)
    first = web.get("/api/library/review").json()["items"][0]
    assert (first["recording_id"], first["id"], first["disputed"]) == (rec, "S1", True)
    put = web.put(
        f"/api/library/recordings/{rec}/speakers/S1",
        json={
            "transcript_id": first["transcript_id"],
            "revision": first["revision"],
            "action": "confirm",
            "person_id": zhang,
        },
        headers=CSRF,
    )
    assert put.status_code == 200, put.text
    s1 = Team(library).speakers(library.get(rec))[0]  # type: ignore[arg-type]
    assert s1.decision == "confirmed" and s1.person_id == zhang and not s1.disputed
    assert all(item["id"] != "S1" for item in web.get("/api/library/review").json()["items"])


def test_the_same_meeting_uploaded_twice_stays_the_first_uploaders(web: TestClient, tmp_path: Path) -> None:
    first = upload(as_(web, UPLOADER), wav_bytes())
    assert first.status_code == 200 and first.json()["new"] is True and first.json()["mine"] is True
    again = upload(as_(web, OTHER), wav_bytes(), "我也有这段.wav")
    assert again.status_code == 200
    assert again.json() == {"id": first.json()["id"], "filename": "周会.wav", "new": False, "mine": False}
    assert web.get("/api/library").json()["recordings"] == []
    stored = team_of(tmp_path).get(first.json()["id"])
    assert stored is not None and stored.uploader == WANG


def test_max_pending_counts_each_members_own_uploads(tmp_path: Path) -> None:
    library = team_of(tmp_path)
    for i, uploader in enumerate((WANG, WANG, ZHANG)):
        part = library.root / f"{i}.part"
        part.write_bytes(bytes([i]))
        library.add(part, f"{i}.m4a", uploader=uploader)
    assert (library.pending(), library.pending(WANG), library.pending(ZHANG), library.pending("x")) == (3, 2, 1, 0)


def old_library(root: Path, key: str, created: str, names: list[str], meetings: list[str]) -> Library:
    """An old library of one account, as earlier versions kept it: each meeting has S1 confirmed as the first of
    ``names`` (with a voice sample) and S2 as the second, if any."""
    library = Library(root / key)
    team = Team(library)
    people = [team.add_person(name) for name in names]
    for title in meetings:
        rec = recording(
            library,
            title,
            [
                Segment(start=0, end=5, text=f"{title}：我先说。", speaker="S1"),
                Segment(start=5, end=9, text="好。", speaker="S2"),
            ],
            [Speaker(id="S1", seconds=30, embedding=[1.0, 0.0]), Speaker(id="S2", seconds=30, embedding=[0.0, 1.0])],
        )
        found = library.get(rec)
        assert found and found.transcript_id
        team.decide(rec, found.transcript_id, found.revision, "S1", "confirm", people[0].id, True)
        if len(people) > 1:
            found = library.get(rec)
            assert found and found.transcript_id
            team.decide(rec, found.transcript_id, found.revision, "S2", "confirm", people[1].id)
    with library.transaction() as db:
        db.execute("UPDATE recordings SET created_at = ?", (created,))
    library.spend("proofread", 100)
    return library


def test_old_libraries_merge_into_the_teams_once(tmp_path: Path) -> None:
    root = tmp_path / "library"
    # 王五 first uploaded 周会 and 周会-复盘; later 赵六 uploaded the same 周会 (by content) and a meeting of their own.
    wang = old_library(root, WANG, "2026-01-01", ["张三", "李四"], ["周会.m4a", "复盘.m4a"])
    zhao_key = owner_key("sso:2003")
    zhao = old_library(root, zhao_key, "2026-02-01", ["张三"], ["客户会.m4a"])
    shared = next(r for r in wang.list() if r.filename == "周会.m4a")
    shutil.copytree(wang.folder(shared.id), zhao.folder(shared.id))
    with wang.read() as source:
        row = dict(source.execute("SELECT * FROM recordings WHERE id = ?", (shared.id,)).fetchone())
    with zhao.transaction() as db:
        db.execute(
            f"INSERT INTO recordings ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})",
            (*row.values(),),
        )
    # 赵六 said otherwise about 周会's second speaker; the first upload's decisions stand.
    [zhao_zhang] = Team(zhao).people()
    Team(zhao).decide(shared.id, shared.transcript_id or "", row["revision"], "S2", "confirm", zhao_zhang.id)

    twins = merge.merge_all(root, lambda old, kept: False)
    assert twins == []
    assert sorted(p.name for p in root.iterdir()) == [".legacy", "team"]
    assert sorted(p.name for p in (root / ".legacy").iterdir()) == sorted([WANG, zhao_key])

    team = Library(root / "team")
    recordings = {r.filename: r for r in team.list()}
    assert sorted(recordings) == ["周会.m4a", "复盘.m4a", "客户会.m4a"]
    assert recordings["周会.m4a"].uploader == WANG and recordings["客户会.m4a"].uploader == zhao_key
    # The files are the old ones, hard-linked: the old library stays whole for going back.
    old = root / ".legacy" / WANG / "recordings" / shared.id
    for path in old.iterdir():
        assert (team.folder(shared.id) / path.name).stat().st_ino == path.stat().st_ino

    # Never one person by name alone: the second 张三 is told apart and left for an administrator.
    people = {p.name: p for p in Team(team).people()}
    assert sorted(people) == ["张三", "张三（2）", "李四"]
    assert Team(team).similar() == [(people["张三"].id, people["张三（2）"].id)]
    names = {r.filename: {s.id: s.person_id for s in Team(team).speakers(r)} for r in team.list()}
    assert names["周会.m4a"] == {"S1": people["张三"].id, "S2": people["李四"].id}
    assert names["客户会.m4a"]["S1"] == people["张三（2）"].id
    assert people["张三"].samples == 2 and people["张三（2）"].samples == 1
    assert team.spent(dt.datetime(2000, 1, 1, tzinfo=dt.UTC))[0] == 200

    # Run again (a restart): nothing is merged twice.
    assert merge.merge_all(root, lambda old, kept: False) == []
    assert len(team.list()) == 3 and len(Team(team).people()) == 3


def test_people_with_the_same_twin_address_are_one(tmp_path: Path) -> None:
    root = tmp_path / "library"
    old_library(root, WANG, "2026-01-01", ["张三"], ["周会.m4a"])
    old_library(root, owner_key("sso:2003"), "2026-02-01", ["张三"], ["客户会.m4a"])
    merge.merge_all(root, lambda old, kept: True)
    team = Library(root / "team")
    [zhang] = Team(team).people()
    assert zhang.name == "张三" and zhang.speakers == 2 and Team(team).similar() == []


def test_an_administrator_merges_or_keeps_apart(web: TestClient, tmp_path: Path) -> None:
    library = team_of(tmp_path)
    team = Team(library)
    rec = uploaded(
        library,
        recording(
            library,
            "周会.m4a",
            [
                Segment(start=0, end=5, text="我先说。", speaker="S1"),
                Segment(start=5, end=9, text="好。", speaker="S2"),
            ],
            [Speaker(id="S1", seconds=30, embedding=[1.0, 0.0]), Speaker(id="S2", seconds=30, embedding=[0.0, 1.0])],
        ),
        "2001",
    )
    one, two, three = team.add_person("张三"), team.add_person("张三（2）"), team.add_person("李四")
    found = library.get(rec)
    assert found and found.transcript_id
    team.decide(rec, found.transcript_id, found.revision, "S1", "confirm", two.id, True)
    team.add_similar(one.id, two.id)
    team.add_similar(one.id, three.id)

    as_(web, UPLOADER)
    assert web.post(f"/api/library/people/{two.id}/merge", json={"into": one.id}, headers=CSRF).status_code == 403
    items = {p["name"]: p for p in web.get("/api/library/people").json()["items"]}
    assert items["张三"]["similar"] == []

    as_(web, ADMIN)
    items = {p["name"]: p for p in web.get("/api/library/people").json()["items"]}
    assert sorted(items["张三"]["similar"]) == sorted([two.id, three.id]) and items["张三（2）"]["similar"] == [one.id]
    assert web.post(f"/api/library/people/{one.id}/apart", json={"other": three.id}, headers=CSRF).status_code == 200
    merged = web.post(f"/api/library/people/{two.id}/merge", json={"into": one.id}, headers=CSRF)
    assert merged.status_code == 200, merged.text
    people = {p.name: p for p in team.people()}
    assert sorted(people) == ["张三", "李四"] and people["张三"].samples == 1 and team.similar() == []
    assert team.speakers(library.get(rec))[0].person_id == one.id  # type: ignore[arg-type]


def test_twins_of_old_libraries_follow_the_teams_and_are_rebuilt(web: TestClient, tmp_path: Path) -> None:
    root = tmp_path / "library"
    old = old_library(root, WANG, "2026-01-01", ["张三"], ["周会.m4a"])
    [zhang] = Team(old).people()
    libraries = web.app.state.libraries  # type: ignore[attr-defined]
    registry = libraries.registry
    entry = registry.create("张三", {"email": "sso:2001", "name": "王五", "admin": False}, onboarding=False)
    db_path = registry.settings_for(entry["id"]).db_path
    with PersonaStore(db_path) as store:
        gate.link(store, old.db_path, entry["id"])
    Team(old).link(zhang.id, entry["id"])
    with old.transaction() as db:
        db.execute("UPDATE personas_sync SET wanted = 3, done = 3")

    libraries.resume()  # As at the next start.
    team = Library(root / "team")
    # Closed until rebuilt from the team's library: wanted was raised past what was built.
    [(persona_id, person_id, wanted, _)] = Team(team).synced()
    assert (persona_id, person_id) == (entry["id"], zhang.id) and wanted > 3
    with PersonaStore(db_path) as store:
        link = json.loads(store.get_meta(gate.LINK) or "{}")
    assert (db_path.parent / link["db"]).resolve() == team.db_path.resolve()
    as_(web, UPLOADER)
    until(lambda: open_twin(web, entry["id"]))
    with PersonaStore(db_path) as store:
        assert [e.text for e in store.list_expressions() if e.is_target] == ["[00:00] 周会.m4a：我先说。"]


def test_a_person_of_the_default_twin_can_be_deleted_once_that_empty_twin_is_deleted(
    web: TestClient, tmp_path: Path
) -> None:
    library = team_of(tmp_path)
    _, zhang = zhang_was_there(library)
    Team(library).link(zhang, "default")
    as_(web, ADMIN)
    [default] = web.get("/api/personas").json()
    assert default["is_default"] and "retirable" not in default
    assert web.delete("/api/personas/default", headers=CSRF).status_code == 400
    web.post("/api/personas", json={"name": "接替的人"}, headers=CSRF)
    [default, _] = web.get("/api/personas").json()
    assert default["retirable"] is True
    [person] = [p for p in web.get("/api/library/people").json()["items"] if p["id"] == zhang]
    assert person["persona_id"] == "default"
    assert web.delete(f"/api/library/people/{zhang}", headers=CSRF).status_code == 409
    assert web.delete("/api/personas/default", headers=CSRF).json() == {"deleted": True}
    [person] = [p for p in web.get("/api/library/people").json()["items"] if p["id"] == zhang]
    assert person["persona_id"] is None and person["twin_elsewhere"] is False
    assert web.delete(f"/api/library/people/{zhang}", headers=CSRF).json() == {"deleted": True}
    assert zhang not in {p["id"] for p in web.get("/api/library/people").json()["items"]}


def test_a_person_whose_twin_was_deleted_can_be_deleted(web: TestClient, tmp_path: Path) -> None:
    library = team_of(tmp_path)
    _, zhang = zhang_was_there(library)
    as_(web, ADMIN)
    persona = web.post(f"/api/library/people/{zhang}/persona", headers=CSRF).json()["persona_id"]
    assert web.delete(f"/api/library/people/{zhang}", headers=CSRF).status_code == 409
    until(lambda: web.delete(f"/api/personas/{persona}", headers=CSRF).status_code == 200)
    [person] = [p for p in web.get("/api/library/people").json()["items"] if p["id"] == zhang]
    assert person["persona_id"] is None
    assert web.delete(f"/api/library/people/{zhang}", headers=CSRF).json() == {"deleted": True}
    assert zhang not in {p["id"] for p in web.get("/api/library/people").json()["items"]}
