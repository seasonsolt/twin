"""The team database: its migrations, files and the index of conversations."""

from __future__ import annotations

import sqlite3
import stat
from pathlib import Path

import pytest
from typer.testing import CliRunner

from twin import teamdb
from twin.cli import app
from twin.ops.backup import backup
from twin.ops.paths import TwinPaths
from twin.persona.store import PersonaStore
from twin.teamdb import NewerTeamError, TeamDB, team_path

STAMP = "2026-10-22T09:00:00+00:00"


def test_the_database_is_private_wal_and_versioned(tmp_path: Path) -> None:
    path = team_path(tmp_path / "data")
    with TeamDB(path) as team:
        assert team.schema_version() == len(teamdb._MIGRATIONS)
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700 and stat.S_IMODE(path.stat().st_mode) == 0o600
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")} >= {
            "conversations",
            "meta",
        }
    with TeamDB(path) as again:  # opens again without migrating
        assert again.schema_version() == len(teamdb._MIGRATIONS)
    assert not (path.parent / teamdb.SNAPSHOT_DIR).exists()


def test_meta_records_keep_what_was_written(tmp_path: Path) -> None:
    with TeamDB(tmp_path / "team.db") as team:
        assert team.get_meta("k") is None
        team.set_meta("k", "1")
        team.set_meta("k", "2")
        assert team.get_meta("k") == "2"


def test_a_migration_appended_later_runs_after_a_snapshot_and_a_newer_database_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "team" / "team.db"
    with TeamDB(path) as team:
        team.record_conversation("c1", "p1", "a@x.com", "colleague", "标题", STAMP)
    monkeypatch.setattr(teamdb, "_MIGRATIONS", (*teamdb._MIGRATIONS, "CREATE TABLE later (id TEXT);"))
    with TeamDB(path) as team:
        assert team.schema_version() == len(teamdb._MIGRATIONS)
        assert [c.id for c in team.conversations()] == ["c1"]
    [snapshot] = list((path.parent / teamdb.SNAPSHOT_DIR).glob("team-*.db"))
    assert stat.S_IMODE(snapshot.stat().st_mode) == 0o600
    with sqlite3.connect(snapshot) as old:  # the snapshot is the database as it was before
        assert old.execute("PRAGMA user_version").fetchone()[0] == len(teamdb._MIGRATIONS) - 1
        assert old.execute("SELECT id FROM conversations").fetchall() == [("c1",)]
    monkeypatch.setattr(teamdb, "_MIGRATIONS", teamdb._MIGRATIONS[:-1])
    with pytest.raises(NewerTeamError, match="更新版本"):
        TeamDB(path)


def test_a_failing_migration_changes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "team.db"
    with TeamDB(path):
        pass
    monkeypatch.setattr(teamdb, "_MIGRATIONS", (*teamdb._MIGRATIONS, "CREATE TABLE half (id); INVALID SQL;"))
    with pytest.raises(sqlite3.Error):
        TeamDB(path)
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == len(teamdb._MIGRATIONS) - 1
        assert db.execute("SELECT name FROM sqlite_master WHERE name = 'half'").fetchone() is None


def test_a_database_from_before_lenses_gains_them_after_a_snapshot(tmp_path: Path) -> None:
    path = tmp_path / "team" / "team.db"
    with TeamDB(path) as team:
        team.record_conversation("c1", "p1", "a@x.com", "colleague", "标题", STAMP)
    # Put it back as it was written by the version before lenses.
    with sqlite3.connect(path) as db:
        db.executescript("DROP TABLE lens_uses; DROP TABLE lenses; PRAGMA user_version = 5;")
    with TeamDB(path) as team:
        assert team.schema_version() == len(teamdb._MIGRATIONS)
        assert [c.id for c in team.conversations()] == ["c1"]
        lens = team.create_lens(persona_id="p1", name="视角", facets=["3.4"], audience="{}")
        team.record_lens_use(lens.id, "问", "答", ["3.4"])
        assert [u.said for u in team.lens_uses(lens.id)] == ["答"]
    [snapshot] = list((path.parent / teamdb.SNAPSHOT_DIR).glob("team-*schema5.db"))
    with sqlite3.connect(snapshot) as old:
        assert old.execute("SELECT name FROM sqlite_master WHERE name = 'lenses'").fetchone() is None


def test_the_index_keeps_the_tier_a_conversation_was_created_with(tmp_path: Path) -> None:
    with TeamDB(tmp_path / "team.db") as team:
        team.record_conversation("c1", "p1", "me@x.com", "self", "我的", STAMP)
        team.record_conversation("c2", "p1", "you@x.com", "colleague", "你的", STAMP)
        assert (team.audience_of("c1"), team.audience_of("c2"), team.audience_of("nope")) == ("self", "colleague", None)
        # Recording it again (a retried request) cannot move it to another tier.
        team.record_conversation("c1", "p1", "me@x.com", "colleague", "新标题", "2026-10-23T09:00:00+00:00")
        assert team.audience_of("c1") == "self"
        [mine] = [c for c in team.conversations() if c.id == "c1"]
        assert (mine.title, mine.updated_at, mine.via, mine.delegation_id) == (
            "新标题",
            "2026-10-23T09:00:00+00:00",
            "direct",
            None,
        )
        with pytest.raises(sqlite3.IntegrityError):  # only the two tiers exist
            team.record_conversation("c3", "p1", None, "admin", "x", STAMP)  # type: ignore[arg-type]
        team.refresh_conversation("c2", "改名了", "2026-10-24T09:00:00+00:00")
        team.delete_conversation("c1")
        assert [c.id for c in team.conversations()] == ["c2"]
        assert [c.id for c in team.conversations(include_deleted=True)] == ["c2", "c1"]
        assert [c.title for c in team.conversations(asker="you@x.com")] == ["改名了"]
        assert team.conversations(personas=[]) == [] and [c.id for c in team.conversations(personas=["p1"])] == ["c2"]
        assert team.conversations(persona_id="other") == []
        team.forget_persona("p1")
        assert team.conversations(include_deleted=True) == []


def test_reconcile_adds_old_conversations_as_colleague_tier_and_follows_the_twin(tmp_path: Path) -> None:
    with TeamDB(tmp_path / "team.db") as team:
        team.record_conversation("known", "p1", "me@x.com", "self", "旧标题", STAMP)
        team.record_conversation("gone", "p1", "me@x.com", "self", "已删", STAMP)
        done = team.reconcile_persona(
            "p1",
            [("known", "me@x.com", "新标题", "2026-10-23T00:00:00+00:00"), ("legacy", None, "老对话", STAMP)],
        )
        assert (done.added, done.updated, done.removed) == (1, 1, 1)
        assert team.audience_of("legacy") == "colleague" and team.audience_of("known") == "self"
        assert {c.id: c.title for c in team.conversations()} == {"known": "新标题", "legacy": "老对话"}
        assert [c.id for c in team.conversations(include_deleted=True) if c.deleted_at] == ["gone"]
        assert team.get_meta(teamdb.RECONCILED_AT) and team.get_meta(teamdb.INDEXED_LEGACY)
        # A second pass changes nothing.
        again = team.reconcile_persona(
            "p1", [("known", "me@x.com", "新标题", "2026-10-23T00:00:00+00:00"), ("legacy", None, "老对话", STAMP)]
        )
        assert (again.added, again.updated, again.removed) == (0, 0, 0)
        # A twin that has gone for good takes its conversations with it; others' are untouched.
        team.record_conversation("other", "p2", None, "colleague", "别人", STAMP)
        team.forget_persona("p1")
        assert [c.id for c in team.conversations()] == ["other"]


def test_rebuild_keeps_the_tier_of_conversations_it_knew(tmp_path: Path) -> None:
    with TeamDB(tmp_path / "team.db") as team:
        team.record_conversation("mine", "p1", "me@x.com", "self", "我的", STAMP)
        team.record_conversation("stale", "p1", "me@x.com", "self", "没了", STAMP)
        team.record_conversation("elsewhere", "p9", None, "self", "不动", STAMP)
        done = team.rebuild_conversations({"p1": [("mine", "me@x.com", "我的", STAMP), ("new", None, "新的", STAMP)]})
        assert (done.added, done.removed) == (2, 2)
        assert (team.audience_of("mine"), team.audience_of("new")) == ("self", "colleague")
        assert team.audience_of("stale") is None and team.audience_of("elsewhere") == "self"


def test_the_command_line_reconciles_and_rebuilds_the_index(tmp_path: Path) -> None:
    config = tmp_path / "twin.toml"
    config.write_text('db_path = "twin.db"\n')
    with PersonaStore(tmp_path / "twin.db") as store:
        first = store.create_conversation("me@x.com")
        second = store.create_conversation(None)
    with TeamDB(team_path(tmp_path)) as team:
        team.record_conversation(first, "default", "me@x.com", "self", "新对话", STAMP)
    runner = CliRunner()
    result = runner.invoke(app, ["--config", str(config), "team", "reconcile"])
    assert result.exit_code == 0, result.output
    assert "补 1" in result.output
    with TeamDB(team_path(tmp_path)) as team:
        assert {c.id for c in team.conversations()} == {first, second}
        assert team.audience_of(first) == "self" and team.audience_of(second) == "colleague"
    result = runner.invoke(app, ["--config", str(config), "team", "reindex"])
    assert result.exit_code == 0, result.output
    assert "已重建：2 段会话" in result.output
    with TeamDB(team_path(tmp_path)) as team:
        assert team.audience_of(first) == "self" and team.audience_of(second) == "colleague"


def test_a_backup_carries_the_team_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TWIN_HOME", str(tmp_path / "home"))
    paths = TwinPaths.from_env()
    with TeamDB(team_path(paths.data)) as team:
        team.record_conversation("c1", "p1", None, "colleague", "标题", STAMP)
    target = backup(paths, paths.data, paths.config)
    with sqlite3.connect(target / "data" / "team" / "team.db") as copy:
        assert copy.execute("SELECT id FROM conversations").fetchall() == [("c1",)]
