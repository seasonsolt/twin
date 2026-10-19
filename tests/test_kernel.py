from __future__ import annotations

import datetime as dt
import hashlib
import sqlite3
import time
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from twin.cli import app
from twin.config import KernelSettings, Settings
from twin.embed import HashingEmbedder
from twin.llm import FakeLLM
from twin.persona import chat, profile
from twin.persona import store as storage
from twin.persona.items import PersonaItem
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
        db.execute("INSERT INTO p_chunks VALUES ('ch_old', 'src_old')")
    for _ in range(2):
        with PersonaStore(path) as store:
            assert store.get_meta("identity:name") == "本人"
            assert store.extraction_stats() == {"src_old": (1, None)}  # extracted before counts were kept
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
        assert db.execute("PRAGMA user_version").fetchone()[0] == len(storage._MIGRATIONS) - 1
        assert db.execute("SELECT name FROM sqlite_master WHERE name='extra'").fetchone() is None
        assert db.execute("SELECT value FROM p_meta WHERE key='saved'").fetchone()[0] == "yes"
        db.execute("PRAGMA user_version=99")
    with pytest.raises(NewerStoreError, match="schema 99"):
        PersonaStore(path)


@pytest.mark.parametrize(
    "old,new,expected",
    [
        # A database without a recorded kernel was built by the legacy one.
        (None, LEGACY_KERNEL, "none"),
        (None, KERNEL, "full"),
        (None, replace(LEGACY_KERNEL, taxonomy="next"), "merge"),
        (KERNEL, KERNEL, "none"),
        (KERNEL, replace(KERNEL, schema=2), "none"),
        (KERNEL, replace(KERNEL, taxonomy="next"), "merge"),
        (KERNEL, replace(KERNEL, prompt="next"), "full"),
        (KERNEL, replace(KERNEL, prompt="next", taxonomy="next"), "full"),
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
            assert processing["kernel_pending"] == 1
        else:
            assert processing["notice"] == profile.KERNEL_STALE_NOTICE
            assert processing["kernel_pending"] == 0
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
    # Nothing recorded means the legacy kernel, so the note waits to be extracted again; above the gate of 0.
    assert "default" in result.output and "范围：full  待重抽分段：1" in result.output

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


def _two_facet_handler(system: str, user: str, schema: type) -> dict[str, object]:
    import re

    if schema is profile.ExtractDraft:
        found = re.findall(r"\[(\d+)\][^\n]*\n本人：([^\n]*)", user)
        return {
            "items": [
                {
                    "facet_id": "2.1" if "回款" in text else "4.2",
                    "statement": text,
                    "quotes": [{"n": int(n), "quote": text}],
                }
                for n, text in found
            ]
        }
    listed = re.findall(r"\[(pc_[0-9a-f]+)\][^：]*：(.*)", user)
    return {"items": [{"statement": s, "candidate_ids": [i]} for i, s in listed]}


def test_taxonomy_change_merges_only_the_facets_it_redefines(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(db_path=tmp_path / "twin.db", target_name="本人")
    with PersonaStore(settings.db_path) as store:
        store.put_source(parse_note("我做事先看回款。\n\n我每周跑步三次。", settings))
        profile.build_profile(store, FakeLLM(_two_facet_handler), settings)
        before = {i.item_id for i in store.list_items()}
        assert len(before) == 2

        # A new taxonomy version whose facets read the same: nothing to extract or merge.
        monkeypatch.setattr(profile, "KERNEL", replace(KERNEL, taxonomy="next"))
        assert profile.pending_chunks(store, settings) == 0
        llm = FakeLLM(_two_facet_handler)
        report = profile.build_profile(store, llm, settings)
        assert (report.chunks_extracted, report.facets_merged, len(llm.calls)) == (0, 0, 0)

        # Redefining one facet re-merges that facet alone.
        facet = profile.FACET_BY_ID["2.1"]
        monkeypatch.setitem(profile.FACET_BY_ID, "2.1", replace(facet, description=facet.description + "（改写）"))
        llm = FakeLLM(_two_facet_handler)
        report = profile.build_profile(store, llm, settings)
        assert (report.chunks_extracted, report.facets_merged) == (0, 1)
        assert {i.item_id for i in store.list_items()} == before


def test_merge_key_from_before_facet_definitions_is_taken_over(tmp_path: Path) -> None:
    """A twin upgrading to keys that name the facet definition does not merge again: a stored key of the old formula
    was merged under the running taxonomy, so it is rewritten instead."""
    settings = Settings(db_path=tmp_path / "twin.db", target_name="本人")
    with PersonaStore(settings.db_path) as store:
        store.put_source(parse_note("我做事先看回款。\n\n我每周跑步三次。", settings))
        profile.build_profile(store, FakeLLM(_two_facet_handler), settings)
        for facet in profile.FACETS:
            members = store.list_candidates(facet.facet_id)
            store.set_meta(f"merge:{facet.facet_id}", profile._legacy_merge_key(members))
        llm = FakeLLM(_two_facet_handler)
        report = profile.build_profile(store, llm, settings)
        assert (report.facets_merged, len(llm.calls)) == (0, 0)
        members = store.list_candidates("2.1")
        assert store.get_meta("merge:2.1") == profile._merge_key("2.1", members)


def test_merge_key_v1_keeps_legacy_formula(monkeypatch: pytest.MonkeyPatch) -> None:
    candidates = [
        profile.PersonaCandidate.model_construct(candidate_id="b"),
        profile.PersonaCandidate.model_construct(candidate_id="a"),
    ]
    ids = [c.candidate_id for c in candidates]
    monkeypatch.setattr(profile, "KERNEL", replace(KERNEL, taxonomy="v1"))
    expected = hashlib.sha256("\x1f".join([PROMPT_VERSION, *sorted(ids)]).encode()).hexdigest()
    assert profile._legacy_merge_key(candidates) == expected
    monkeypatch.setattr(profile, "KERNEL", replace(KERNEL, taxonomy="v2"))
    assert (
        profile._legacy_merge_key(candidates)
        == hashlib.sha256("\x1f".join([PROMPT_VERSION, "v2", *sorted(ids)]).encode()).hexdigest()
    )


def test_latest_store_opens_while_other_connection_writes(tmp_path: Path) -> None:
    path = tmp_path / "twin.db"
    with PersonaStore(path):
        pass
    with sqlite3.connect(path) as other:
        other.execute("BEGIN IMMEDIATE")
        with PersonaStore(path) as store:
            assert store.schema_version() == len(storage._MIGRATIONS)


def test_current_kernel_skips_rebuild_and_chunk_scan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(db_path=tmp_path / "twin.db")
    with PersonaStore(settings.db_path) as store:
        store.put_source(parse_note("我喜欢写程序", settings))
        store.set_meta("built_at", dt.datetime.now(dt.UTC).isoformat())
        # Built without a recorded kernel means built by the legacy one, which the current kernel replaces.
        assert profile.profile_stale(store)
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
    assert f"schema：{len(storage._MIGRATIONS)}" in result.output
    assert KERNEL.schema == len(storage._MIGRATIONS) - 1


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


def test_kernel_content_changes_bump_versions() -> None:
    """Colleagues' stores only re-extract when the version moves, so content changes must bump it."""
    from twin.persona.dimensions import taxonomy_fingerprint
    from twin.persona.kernel import PROMPT_FINGERPRINTS, PROMPT_VERSION, TAXONOMY_FINGERPRINTS, TAXONOMY_VERSION
    from twin.persona.profile import prompt_fingerprint

    assert PROMPT_FINGERPRINTS.get(PROMPT_VERSION) == prompt_fingerprint(), (
        "抽取/合并提示词或输出结构变了：请提升 kernel.PROMPT_VERSION，"
        f'并在 PROMPT_FINGERPRINTS 记录 "{prompt_fingerprint()}"'
    )
    assert TAXONOMY_FINGERPRINTS.get(TAXONOMY_VERSION) == taxonomy_fingerprint(), (
        f'人格维度分类变了：请提升 kernel.TAXONOMY_VERSION，并在 TAXONOMY_FINGERPRINTS 记录 "{taxonomy_fingerprint()}"'
    )
    assert len(set(PROMPT_FINGERPRINTS.values())) == len(PROMPT_FINGERPRINTS)
    assert len(set(TAXONOMY_FINGERPRINTS.values())) == len(TAXONOMY_FINGERPRINTS)


def test_fingerprint_detects_prompt_edit(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from twin.persona import profile

    before = profile.prompt_fingerprint()
    monkeypatch.setattr(profile, "EXTRACT_SYSTEM", profile.EXTRACT_SYSTEM + "\n多一句要求。")
    assert profile.prompt_fingerprint() != before


def test_kernel_change_snapshots_once_and_restores(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(db_path=tmp_path / "twin.db")
    with PersonaStore(settings.db_path) as store:
        store.put_source(parse_note("我喜欢写程序", settings))
        profile.build_profile(store, FakeLLM(lambda *_: {"items": []}), settings)
        assert not storage.list_snapshots(settings.db_path)
        monkeypatch.setattr(profile, "KERNEL", replace(KERNEL, prompt="next"))

        def fail(*args: object) -> dict[str, object]:
            raise RuntimeError("failed")

        assert profile.build_profile(store, FakeLLM(fail), settings).failures
        profile.build_profile(store, FakeLLM(lambda *_: {"items": []}), settings)
        assert store.kernel_built() == replace(KERNEL, prompt="next")
    snapshots = storage.list_snapshots(settings.db_path)
    assert len(snapshots) == 1 and snapshots[0].name.endswith(f"-{KERNEL.prompt}-{KERNEL.taxonomy}.db")
    assert snapshots[0].stat().st_mode & 0o777 == 0o600 and snapshots[0].parent.stat().st_mode & 0o777 == 0o700
    storage.restore_snapshot(snapshots[0], settings.db_path)
    with PersonaStore(settings.db_path) as store:
        assert store.kernel_built() == KERNEL and store.has_extractions()
    with pytest.raises(ValueError):
        storage.restore_snapshot(settings.db_path, settings.db_path)


def test_migration_snapshots_existing_data_only(tmp_path: Path) -> None:
    path = tmp_path / "twin.db"
    with sqlite3.connect(path) as db:
        db.executescript(storage._SCHEMA)
        db.execute("INSERT INTO p_meta VALUES ('identity:name', '本人')")
    PersonaStore(path).close()
    PersonaStore(path).close()
    PersonaStore(tmp_path / "fresh.db").close()
    assert [p.name.endswith("-schema0.db") for p in storage.list_snapshots(path)] == [True]
    assert not storage.list_snapshots(tmp_path / "fresh.db")
    with sqlite3.connect(storage.list_snapshots(path)[0]) as db:
        assert db.execute("SELECT value FROM p_meta WHERE key = 'identity:name'").fetchone() == ("本人",)


def test_snapshots_keep_newest(tmp_path: Path) -> None:
    with PersonaStore(tmp_path / "twin.db") as store:
        made = [store.snapshot(f"step{i}") for i in range(storage.SNAPSHOT_KEEP + 2)]
    assert storage.list_snapshots(tmp_path / "twin.db") == sorted(made[-storage.SNAPSHOT_KEEP :])  # type: ignore[type-var]


def test_cli_snapshots_and_restore(tmp_path: Path) -> None:
    config = tmp_path / "twin.toml"
    config.write_text('db_path = "twin.db"\n')
    db = tmp_path / "twin.db"
    with PersonaStore(db) as store:
        store.set_meta("identity:name", "旧")
        saved = store.snapshot("persona-v4-v1")
        store.set_meta("identity:name", "新")
    runner = CliRunner()
    listed = runner.invoke(app, ["--config", str(config), "kernel", "snapshots"])
    assert listed.exit_code == 0 and str(saved) in listed.output
    refused = runner.invoke(app, ["--config", str(config), "kernel", "restore", str(saved)])
    assert refused.exit_code == 1 and "--yes" in refused.output
    stranger = tmp_path / "other.db"
    stranger.write_bytes(b"")
    wrong = runner.invoke(app, ["--config", str(config), "kernel", "restore", str(stranger), "--yes"])
    assert wrong.exit_code == 1
    restored = runner.invoke(app, ["--config", str(config), "kernel", "restore", str(saved), "--yes"])
    assert restored.exit_code == 0, restored.output
    with PersonaStore(db) as store:
        assert store.get_meta("identity:name") == "旧"
    assert any(p.name.endswith("before-restore.db") for p in storage.list_snapshots(db))


def test_reviews_survive_a_prompt_upgrade(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A new prompt re-extracts every chunk, so every candidate id changes; the person's reviews still follow the
    traits, matched by the expressions they quote and their wording."""
    import re

    from twin.persona.items import PReview
    from twin.persona.schema import ReviewStatus

    wording = {
        "old": {"回款": "做事先看回款", "跑步": "每周跑步三次", "开会": "开会先听别人说"},
        "new": {"回款": "做事优先看回款", "跑步": "坚持每周跑步三次", "开会": "开会时先让别人说"},
    }
    version = "old"

    def handler(system: str, user: str, schema: type) -> dict[str, object]:
        if schema is profile.ExtractDraft:
            found = re.findall(r"\[(\d+)\][^\n]*\n本人：([^\n]*)", user)
            facet = {"回款": "2.1", "跑步": "2.1", "开会": "4.2"}
            return {
                "items": [
                    {
                        "facet_id": facet[key],
                        "statement": wording[version][key],
                        "quotes": [{"n": int(n), "quote": text}],
                    }
                    for n, text in found
                    for key in facet
                    if key in text
                ]
            }
        if schema is profile.MergeDraft:
            listed = re.findall(r"\[(pc_[0-9a-f]+)\][^：]*：(.*)", user)
            return {"items": [{"statement": s, "candidate_ids": [i]} for i, s in listed]}
        raise AssertionError(schema)

    settings = Settings(db_path=tmp_path / "twin.db", target_name="本人")
    with PersonaStore(settings.db_path) as store:
        store.put_source(parse_note("我做事先看回款。\n\n我每周跑步三次。\n\n开会我习惯先听别人说。", settings))
        profile.build_profile(store, FakeLLM(handler), settings)
        by_text = {i.statement: i.item_id for i in store.list_items()}
        at = "2026-10-14T10:00:00"
        store.set_review(by_text["做事先看回款"], PReview(status=ReviewStatus.CONFIRMED, reviewed_at=at))
        store.set_review(
            by_text["每周跑步三次"], PReview(status=ReviewStatus.EDITED, statement="一周跑三次步", reviewed_at=at)
        )
        store.set_review(by_text["开会先听别人说"], PReview(status=ReviewStatus.REJECTED, reviewed_at=at))

        version = "new"
        monkeypatch.setattr(profile, "KERNEL", replace(KERNEL, prompt="next"))
        profile.build_profile(store, FakeLLM(handler), settings)
        after = {i.extracted_statement or i.statement: i for i in store.list_items(include_rejected=True)}
        assert set(after) == {"做事优先看回款", "坚持每周跑步三次", "开会时先让别人说"}
        assert not set(by_text.values()) & {i.item_id for i in after.values()}  # every item is new
        assert after["做事优先看回款"].review is ReviewStatus.CONFIRMED
        assert after["坚持每周跑步三次"].review is ReviewStatus.EDITED
        assert after["坚持每周跑步三次"].statement == "一周跑三次步"
        assert after["开会时先让别人说"].review is ReviewStatus.REJECTED
        assert len(store.reviews()) == 3


@pytest.mark.parametrize("old_model", [True, False])
def test_startup_reembeds_an_index_of_another_embedding_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, old_model: bool
) -> None:
    settings = Settings(db_path=tmp_path / "twin.db")
    embedder = HashingEmbedder()
    with PersonaStore(settings.db_path) as store:
        store.put_source(parse_note("我喜欢写程序", settings))
        store.mark_profile_built(dt.datetime.now(dt.UTC).isoformat(), store.get_meta("sources_changed_at"), KERNEL)
        item = PersonaItem(item_id="pi_000", facet_id="2.1", statement="喜欢写程序", evidence=[])
        store.replace_facet_items("2.1", [item])
        if old_model:
            store.update_vectors(chat.ITEMS_NS, "old-model", [("pi_000", "sha", np.ones(2, dtype=np.float32))], [])
        else:
            chat.index_persona(store, embedder, settings)

    def unexpected(self: PersonaProcessing) -> None:
        pytest.fail("档案已是最新，不应重新抽取")

    monkeypatch.setattr(PersonaProcessing, "queue", unexpected)
    application = create_app(settings, llm_factory=lambda: FakeLLM(lambda *_: {}), embedder_factory=HashingEmbedder)
    with TestClient(application, base_url="http://localhost") as client:
        jobs = client.get("/api/jobs").json()
        assert [job["title"] for job in jobs] == (["更新检索向量"] if old_model else [])
        for job in jobs:
            deadline = time.monotonic() + 10
            while (status := client.get(f"/api/jobs/{job['job_id']}").json()["status"]) in {"queued", "running"}:
                assert time.monotonic() < deadline
                time.sleep(0.05)
            assert status == "done"
    with PersonaStore(settings.db_path) as store:
        assert not chat.index_stale(store, embedder)
        ids, matrix = store.get_vectors(chat.ITEMS_NS)
        assert ids == ["pi_000"] and matrix.shape == (1, embedder.dim)
