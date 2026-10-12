from __future__ import annotations

import datetime as dt
import hashlib
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from twin.cli import app
from twin.config import KernelSettings, Settings
from twin.embed import HashingEmbedder
from twin.llm import FakeLLM
from twin.persona import profile
from twin.persona import store as storage
from twin.persona.kernel import KERNEL, LEGACY_KERNEL, PROMPT_VERSION, KernelVersion, kernel_json, rebuild_scope
from twin.persona.sources import parse_note
from twin.persona.store import NewerStoreError, PersonaStore
from twin.web.app import create_app
from twin.web.jobs import PersonaProcessing


def test_store_migration_and_reopen(tmp_path: Path) -> None:
    path = tmp_path / "twin.db"
    with sqlite3.connect(path) as db:
        db.executescript(storage._SCHEMA)
        db.execute("INSERT INTO p_meta VALUES ('identity:name', '本人')")
    for _ in range(2):
        with PersonaStore(path) as store:
            assert store.get_meta("identity:name") == "本人"
        with sqlite3.connect(path) as db:
            assert db.execute("PRAGMA user_version").fetchone()[0] == len(storage._MIGRATIONS)
    with PersonaStore(tmp_path / "new.db"):
        pass
    with sqlite3.connect(tmp_path / "new.db") as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == KERNEL.schema


def test_newer_and_failed_migration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "twin.db"
    with PersonaStore(path) as store:
        store.set_meta("saved", "yes")
    monkeypatch.setattr(storage, "_MIGRATIONS", (*storage._MIGRATIONS, "CREATE TABLE extra (id); INVALID SQL;"))
    with pytest.raises(sqlite3.Error):
        PersonaStore(path)
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 1
        assert db.execute("SELECT name FROM sqlite_master WHERE name='extra'").fetchone() is None
        assert db.execute("SELECT value FROM p_meta WHERE key='saved'").fetchone()[0] == "yes"
        db.execute("PRAGMA user_version=99")
    with pytest.raises(NewerStoreError, match="schema 99"):
        PersonaStore(path)


@pytest.mark.parametrize(
    "old,new,expected",
    [
        (None, LEGACY_KERNEL, "none"),
        (None, KERNEL, "none"),
        (None, replace(KERNEL, prompt="next"), "full"),
        (KERNEL, KERNEL, "none"),
        (KERNEL, replace(KERNEL, schema=2), "none"),
        (KERNEL, replace(KERNEL, taxonomy="v2"), "merge"),
        (KERNEL, replace(KERNEL, prompt="next"), "full"),
        (KERNEL, replace(KERNEL, prompt="next", taxonomy="v2"), "full"),
    ],
)
def test_scopes(old: KernelVersion | None, new: KernelVersion, expected: str) -> None:
    assert rebuild_scope(old, new) == expected
    assert kernel_json(KERNEL) == kernel_json(replace(KERNEL))


def test_build_and_prompt_pending(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(db_path=tmp_path / "twin.db")
    llm = FakeLLM(lambda *_: {"items": []})
    with PersonaStore(settings.db_path) as store:
        store.put_source(parse_note("我喜欢写程序", settings))
        assert profile.pending_chunks(store, settings) == 1
        profile.build_profile(store, llm, settings)
        assert store.kernel_built() == KERNEL
        assert profile.pending_chunks(store, settings) == 0
        assert not profile.profile_stale(store)
        changed = replace(KERNEL, prompt="next")
        monkeypatch.setattr(profile, "KERNEL", changed)
        assert profile.profile_stale(store)
        assert profile.stale_reason(store) == "kernel"
        assert profile.pending_chunks(store, settings) == 1
        report = profile.build_profile(store, llm, settings)
        assert report.chunks_extracted == 1
        assert store.kernel_built() == changed
        store.put_source(parse_note("第二条", settings))
        store.mark_profile_built(dt.datetime.now(dt.UTC).isoformat(), "wrong", KERNEL)
        assert store.kernel_built() == changed


@pytest.mark.parametrize("enabled,limit,queued", [(True, 1, True), (True, 0, False), (False, 1, False)])
def test_resume_gate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, enabled: bool, limit: int, queued: bool) -> None:
    settings = Settings(
        db_path=tmp_path / "twin.db", kernel=KernelSettings(auto_rebuild=enabled, max_auto_rebuild_chunks=limit)
    )
    with PersonaStore(settings.db_path) as store:
        store.put_source(parse_note("我喜欢写程序", settings))
        store.mark_profile_built(
            dt.datetime.now(dt.UTC).isoformat(), store.get_meta("sources_changed_at"), replace(KERNEL, prompt="old")
        )
    calls: list[bool] = []
    monkeypatch.setattr(PersonaProcessing, "queue", lambda self: calls.append(True))
    application = create_app(
        settings, llm_factory=lambda: FakeLLM(lambda *_: {"items": []}), embedder_factory=HashingEmbedder
    )
    with TestClient(application, base_url="http://localhost") as client:
        assert bool(calls) == queued
        kernel = client.get("/api/status").json()["kernel"]
        assert kernel["pending_chunks"] == 1
        assert kernel["scope"] == "full"
        processing = client.get("/api/persona/processing").json()
        if not queued:
            assert kernel["state"] == "awaiting_confirmation"
            assert processing["notice"] == profile.KERNEL_AWAITING_NOTICE
        else:
            assert processing["notice"] == profile.KERNEL_STALE_NOTICE
        assert client.post("/api/kernel/rebuild").status_code == 403
        assert client.post("/api/kernel/rebuild", headers={"X-Twin": "1"}).status_code == 202


def test_cli_status_and_gate(tmp_path: Path) -> None:
    config = tmp_path / "twin.toml"
    config.write_text('db_path = "twin.db"\n[kernel]\nmax_auto_rebuild_chunks = 0\n')
    settings = Settings(db_path=tmp_path / "twin.db")
    with PersonaStore(settings.db_path) as store:
        store.put_source(parse_note("我喜欢写程序", settings))
    runner = CliRunner()
    result = runner.invoke(app, ["--config", str(config), "kernel", "status"])
    assert result.exit_code == 0, result.output
    assert "default" in result.output and "待重抽分段：0" in result.output

    result = runner.invoke(app, ["--config", str(config), "kernel", "rebuild"])
    assert result.exit_code == 1 and "--yes" in result.output


def test_member_cannot_rebuild(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    application = create_app(Settings(db_path=tmp_path / "twin.db"))
    monkeypatch.setattr(
        application.state.auth,
        "identity",
        lambda email: {"email": "member@example.com", "admin": False, "auth_enabled": False},
    )
    with TestClient(application, base_url="http://localhost", headers={"X-Twin": "1"}) as client:
        created = client.post("/api/personas", json={"name": "成员"})
        assert created.status_code == 201
        response = client.post("/api/kernel/rebuild", headers={"X-Twin-Persona": created.json()["id"]})
        assert response.status_code == 403
        assert "管理员" in response.json()["detail"]


def test_newer_web_and_cli_startup(tmp_path: Path) -> None:
    path = tmp_path / "twin.db"
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA user_version=99")
    with pytest.raises(NewerStoreError, match="请升级或从备份恢复"):
        create_app(Settings(db_path=path))
    config = tmp_path / "twin.toml"
    config.write_text('db_path = "twin.db"\n')
    result = CliRunner().invoke(app, ["--config", str(config), "ui"])
    assert result.exit_code == 1
    assert "schema 99" in result.output


def test_taxonomy_merges_without_extracting(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(db_path=tmp_path / "twin.db")
    llm = FakeLLM(lambda *_: {"items": []})
    with PersonaStore(settings.db_path) as store:
        store.put_source(parse_note("我喜欢写程序", settings))
        profile.build_profile(store, llm, settings)
        monkeypatch.setattr(profile, "KERNEL", replace(KERNEL, taxonomy="next"))
        assert profile.pending_chunks(store, settings) == 0
        report = profile.build_profile(store, llm, settings)
        assert report.chunks_extracted == 0 and report.facets_merged > 0
        assert len(llm.calls) == 1


def test_merge_key_v1_keeps_legacy_formula(monkeypatch: pytest.MonkeyPatch) -> None:
    candidates = [
        profile.PersonaCandidate.model_construct(candidate_id="b"),
        profile.PersonaCandidate.model_construct(candidate_id="a"),
    ]
    ids = [c.candidate_id for c in candidates]
    expected = hashlib.sha256("\x1f".join([PROMPT_VERSION, *sorted(ids)]).encode()).hexdigest()
    assert profile._merge_key(candidates) == expected
    monkeypatch.setattr(profile, "KERNEL", replace(KERNEL, taxonomy="v2"))
    assert profile._merge_key(candidates) != expected


def test_latest_store_opens_while_other_connection_writes(tmp_path: Path) -> None:
    path = tmp_path / "twin.db"
    with PersonaStore(path):
        pass
    with sqlite3.connect(path) as other:
        other.execute("BEGIN IMMEDIATE")
        with PersonaStore(path) as store:
            assert store.schema_version() == len(storage._MIGRATIONS)


@pytest.mark.parametrize("recorded", [False, True])
def test_current_kernel_skips_rebuild_and_chunk_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recorded: bool
) -> None:
    settings = Settings(db_path=tmp_path / "twin.db")
    with PersonaStore(settings.db_path) as store:
        store.put_source(parse_note("我喜欢写程序", settings))
        store.set_meta("built_at", dt.datetime.now(dt.UTC).isoformat())
        if recorded:
            store.mark_kernel_built(KERNEL)
        assert not profile.profile_stale(store)

    def unexpected(*args: object) -> None:
        pytest.fail("当前内核不应排队或重新分段")

    monkeypatch.setattr(profile, "chunks_for", unexpected)
    monkeypatch.setattr(PersonaProcessing, "queue", unexpected)
    application = create_app(settings)
    with TestClient(application, base_url="http://localhost") as client:
        kernel = client.get("/api/status").json()["kernel"]
        assert kernel["scope"] == "none"
        assert kernel["pending_chunks"] == 0
        assert kernel["state"] == "ready"
        assert client.get("/api/persona/processing").json()["notice"] is None
    config = tmp_path / "twin.toml"
    config.write_text('db_path = "twin.db"\n')
    result = CliRunner().invoke(app, ["--config", str(config), "kernel", "status"])
    assert result.exit_code == 0, result.output
    assert "范围：none  待重抽分段：0" in result.output


def test_cli_reports_database_schema(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(storage, "_MIGRATIONS", (*storage._MIGRATIONS, "CREATE TABLE extra (id);"))
    config = tmp_path / "twin.toml"
    config.write_text('db_path = "twin.db"\n')
    result = CliRunner().invoke(app, ["--config", str(config), "kernel", "status"])
    assert result.exit_code == 0, result.output
    assert "schema：2" in result.output
    assert KERNEL.schema == 1


def test_failed_build_keeps_kernel(tmp_path: Path) -> None:
    settings = Settings(db_path=tmp_path / "twin.db")
    with PersonaStore(settings.db_path) as store:
        previous = replace(KERNEL, prompt="old")
        store.mark_kernel_built(previous)
        store.put_source(parse_note("我喜欢写程序", settings))

        def fail(*args: object) -> dict[str, object]:
            raise RuntimeError("failed")

        assert profile.build_profile(store, FakeLLM(fail), settings).failures
        assert store.kernel_built() == previous
