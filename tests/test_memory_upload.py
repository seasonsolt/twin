"""Offline memory-upload summaries, build diffs and stale-profile contracts."""

from __future__ import annotations

import datetime as dt
import re
import sqlite3
import threading
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel
from typer.testing import CliRunner

from twin import cli
from twin.config import Settings
from twin.embed import HashingEmbedder
from twin.llm import CallTally, FakeLLM
from twin.persona import profile as pf
from twin.persona.items import ExtractStats, PersonaCandidate, PersonaItem, PEvidence, PReview
from twin.persona.schema import ChatDraft, EvidenceClass, ReviewStatus, SourceKind
from twin.persona.sources import parse_text
from twin.persona.store import PersonaStore
from twin.web import create_app
from twin.web.persona import run_persona_build

HEADERS = {"X-Twin": "1"}


@pytest.fixture
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.delenv("TWIN_CONFIG", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    return Settings(target_name="合成人物", db_path=tmp_path / "memory.db", max_workers=1, pseudonymize_others=False)


def handler(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
    if schema is pf.ExtractDraft:
        return {"items": [{"facet_id": "2.1", "statement": "他核对测试数据", "quotes": [{"n": 1, "quote": "核对"}]}]}
    if schema is ChatDraft:
        return {"reply": "合成测试回复", "citations": [], "confidence": 0.2, "abstain": False}
    raise AssertionError(schema)


def imported(store: PersonaStore, settings: Settings, title: str = "测试甲.md") -> str:
    parsed = parse_text(SourceKind.DOCUMENT, title, "先核对测试数据。", settings)
    store.put_source(parsed)
    return parsed.source.source_id


def item(iid: str, facet: str, *eids: str, statement: str = "合成条目") -> PersonaItem:
    return PersonaItem(
        item_id=iid,
        facet_id=facet,
        statement=statement,
        evidence=[
            PEvidence(
                expression_id=eid,
                source_id="deliberately_not_the_owner",
                source_kind=SourceKind.DOCUMENT,
                evidence_class=EvidenceClass.BEHAVIOR,
                quote="合成引文",
            )
            for eid in eids
        ],
    )


def test_source_support_is_deduplicated_and_joins_expression_ids(settings: Settings) -> None:
    with PersonaStore(":memory:") as store:
        a = imported(store, settings)
        b = imported(store, settings, "测试乙.md")
        chat = parse_text(
            SourceKind.CHAT, "群聊.txt", "2026-01-01 10:00 配角：测试\n2026-01-01 10:01 合成人物：核对", settings
        )
        store.put_source(chat)
        c = chat.source.source_id
        ea, eb = store.list_expressions(a)[0].expression_id, store.list_expressions(b)[0].expression_id
        shared = item("shared", "2.1", ea, ea, eb, "missing")
        rejected = item("rejected", "4.2", ea)
        store.replace_facet_items("2.1", [shared])
        store.replace_facet_items("4.2", [item("second", "4.2", ea), rejected])
        store.set_review("rejected", PReview(status=ReviewStatus.REJECTED, reviewed_at="2026-01-01"))
        memories = pf.source_memories(store)
        assert memories[a].items_supported == 2 and memories[b].items_supported == 1
        assert {f["facet_id"] for f in memories[a].facets} == {"2.1", "4.2"}
        assert all(f["name"] for f in memories[a].facets)
        assert not memories[a].contributes_nothing
        assert asdict(memories[c]) == {
            "expressions_total": 2,
            "expressions_target": 1,
            "expressions_others": 1,
            "items_supported": 0,
            "facets": [],
            "contributes_nothing": True,
            "build_status": "not_built",
            "chunks_extracted": 0,
            "extraction": None,
            "nothing_found_reason": "",
        }
        before = store.get_meta("sources_changed_at")
        pf.source_memories(store)
        assert store.get_meta("built_at") is None and store.get_meta("sources_changed_at") == before
        store.mark_profile_built(dt.datetime.now(dt.UTC).isoformat(), before)
        assert pf.source_memories(store)[c].build_status == "no_items"
        assert pf.source_memories(store)[a].build_status == "remembered"


def test_stale_lifecycle_empty_build_and_replaced_source(settings: Settings) -> None:
    with PersonaStore(":memory:") as store:
        assert not pf.profile_stale(store)
        parsed = parse_text(SourceKind.DOCUMENT, "空结论.md", "合成测试数据", settings)
        store.put_source(parsed)
        sid = parsed.source.source_id
        assert pf.profile_stale(store)
        pf.build_profile(store, FakeLLM(lambda *_: {"items": []}), settings)
        assert not pf.profile_stale(store)
        assert pf.source_memories(store)[sid].build_status == "no_items"
        built = store.get_meta("built_at")
        assert not store.put_source(parsed)
        assert pf.profile_stale(store)
        assert pf.source_memories(store)[sid].build_status == "not_built"
        assert store.get_meta("built_at") == built
        pf.build_profile(store, FakeLLM(lambda *_: {"items": []}), settings)
        assert not pf.profile_stale(store)
        assert store.delete_source(sid)
        assert pf.profile_stale(store)  # deletion of the last source must also require rebuilding
        changed = store.get_meta("sources_changed_at")
        assert not store.delete_source(sid)
        assert store.get_meta("sources_changed_at") == changed
        pf.build_profile(store, FakeLLM(lambda *_: {"items": []}), settings)
        assert not pf.profile_stale(store)


def test_source_without_target_expressions_is_built_without_llm_calls(settings: Settings) -> None:
    with PersonaStore(":memory:") as store:
        parsed = parse_text(SourceKind.DOCUMENT, "2026-01-01_其他人.txt", "合成数据", settings)
        parsed.expressions[0].speaker = "配角"
        parsed.expressions[0].is_target = False
        parsed.source.n_target = 0
        store.put_source(parsed)
        llm = FakeLLM(handler)
        report = pf.build_profile(store, llm, settings)
        assert report.chunks_total == 0 and llm.calls == [] and not pf.profile_stale(store)
        memory = pf.source_memories(store)[parsed.source.source_id]
        assert memory.expressions_target == 0 and memory.expressions_others == 1
        assert memory.build_status == "no_items" and memory.contributes_nothing


def test_stale_timestamp_compatibility(settings: Settings) -> None:
    with PersonaStore(":memory:") as store:
        imported(store, settings)
        pf.build_profile(store, FakeLLM(handler), settings)
        assert not pf.profile_stale(store)
        store.set_meta("built_at", "2026-01-01T01:00:00+01:00")
        store.set_meta("sources_changed_at", "2026-01-01T00:00:00+00:00")
        assert not pf.profile_stale(store)  # equal instants, different ISO strings
        store.set_meta("sources_changed_at", "2026-01-01T00:00:00.000001+00:00")
        assert pf.profile_stale(store)
        naive = dt.datetime(2026, 1, 1)
        store.set_meta("built_at", naive.isoformat())
        store.set_meta("sources_changed_at", naive.astimezone(dt.UTC).isoformat())
        assert not pf.profile_stale(store)


def test_source_change_metadata_rolls_back_with_failed_import(settings: Settings) -> None:
    with PersonaStore(":memory:") as store:
        imported(store, settings)
        original = store.get_meta("sources_changed_at")
        parsed = parse_text(SourceKind.DOCUMENT, "重复.md", "合成测试数据", settings)
        parsed.expressions.append(parsed.expressions[0])
        with pytest.raises(sqlite3.IntegrityError):
            store.put_source(parsed)
        assert store.get_meta("sources_changed_at") == original
        assert store.get_source(parsed.source.source_id) is None


def test_build_diffs_compare_raw_ids_and_statements_and_noop(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    with PersonaStore(":memory:") as store:
        sid = imported(store, settings)
        eid = store.list_expressions(sid)[0].expression_id
        store.replace_facet_items("2.1", [item("same", "2.1", eid), item("gone", "2.1", eid)])
        store.replace_facet_items("2.2", [item("removed_facet", "2.2", eid)])
        store.replace_facet_items("4.2", [item("evidence_only", "4.2", eid)])
        store.set_review("same", PReview(status=ReviewStatus.EDITED, statement="人工表述", reviewed_at="2026-01-01"))
        candidates = [
            PersonaCandidate(candidate_id=f"c{fid}", chunk_id="test", facet_id=fid, statement="测试", evidence=[])
            for fid in ("2.1", "4.2")
        ]
        monkeypatch.setattr(pf, "extract_chunk", lambda *args: pf.Extraction(candidates, ExtractStats()))
        outcomes = {
            "2.1": [item("same", "2.1", eid, statement="修改后的测试表述"), item("added", "2.1", eid)],
            "4.2": [item("evidence_only", "4.2", "changed_evidence")],
        }
        monkeypatch.setattr(pf, "merge_facet", lambda llm, fid, members, settings, **_: outcomes[fid])
        report = pf.build_profile(store, FakeLLM(handler), settings)
        assert report.facet_diffs["2.1"] == pf.FacetItemDiff(added=1, changed=1, removed=1)
        assert report.facet_diffs["2.2"] == pf.FacetItemDiff(removed=1)
        assert report.facet_diffs["4.2"] == pf.FacetItemDiff()
        assert (report.items_added, report.items_changed, report.items_removed, report.facets_changed) == (1, 1, 2, 2)
        assert report.change_summary() == "新增 1 条、修改 1 条、删除 2 条，涉及 2 个细项"
        again = pf.build_profile(store, FakeLLM(handler), settings)
        assert again.facet_diffs == {} and again.facets_changed == 0


def test_failures_and_midbuild_changes_do_not_acknowledge_stale_input(settings: Settings) -> None:
    with PersonaStore(":memory:") as store:
        sid = imported(store, settings)
        logs: list[str] = []

        def fail(*args: Any) -> Any:
            raise RuntimeError("secret personal text must not be logged")

        report = pf.build_profile(store, FakeLLM(fail), settings, logs.append)
        assert report.failures and store.get_meta("built_at") is None and pf.profile_stale(store)
        assert all("secret" not in line and "测试甲" not in line for line in [*logs, *report.failures])
        assert pf.source_memories(store)[sid].build_status == "not_built"

        def mutate(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
            imported(store, settings)
            return handler(system, user, schema)

        report = pf.build_profile(store, FakeLLM(mutate), settings)
        # The build is recorded as of its start, so the change made while it ran still shows as stale and pending.
        assert not report.failures and pf.profile_stale(store) and store.get_meta("built_at") is not None
        assert store.source_status(sid, 0) == "processing"
        pf.build_profile(store, FakeLLM(handler), settings)
        assert not pf.profile_stale(store)


def test_a_failed_source_does_not_hold_back_the_others(settings: Settings) -> None:
    with PersonaStore(":memory:") as store:
        good = imported(store, settings, "测试乙.md")
        parsed = parse_text(SourceKind.DOCUMENT, "测试丙.md", "坏的一段：先核对测试数据。", settings)
        store.put_source(parsed)
        bad = parsed.source.source_id
        seen: list[tuple[str, dict[str, tuple[int, int]]] | None] = []
        fail = True

        def flaky(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
            seen.append(store.build_progress())
            if schema is pf.MergeDraft:
                return {
                    "items": [{"statement": "核对测试数据", "candidate_ids": re.findall(r"\[(pc_[0-9a-f]+)\]", user)}]
                }
            if "坏的" in user and fail:
                raise RuntimeError("timeout")
            return handler(system, user, schema)

        report = pf.build_profile(store, FakeLLM(flaky), settings)
        assert report.failed_sources == {bad} and not report.merge_failed
        assert seen and all(p is not None and p[0] == "extract" and p[1][good][1] == 1 for p in seen)
        seen.clear()
        assert store.build_progress() is None
        assert store.source_status(good, 1) == "remembered" and store.source_status(bad, 0) == "processing"
        store.processing_result([good, bad], store.get_meta("sources_changed_at"), None, sorted(report.failed_sources))
        assert store.source_status(good, 1) == "remembered" and store.source_status(bad, 0) == "failed"
        assert store.get_meta("processing_last_error") == "1 条记忆处理失败，可点重试"

        store.clear_source_errors()
        fail = False
        assert not pf.build_profile(store, FakeLLM(flaky), settings).failures
        assert seen[-1] is not None and seen[-1][0] == "merge" and seen[-1][1][good] == (1, 1)
        assert store.source_status(bad, 1) == "remembered" and not pf.profile_stale(store)


def test_web_sources_state_and_build_result_are_additive(settings: Settings) -> None:
    app = create_app(settings, llm_factory=lambda: FakeLLM(handler), embedder_factory=HashingEmbedder)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert client.get("/api/persona/sources").json()["items"] == []
        assert client.get("/api/persona/state").json() == {"stale": False, "built_at": None, "sources_changed_at": None}
        response = client.post(
            "/api/persona/import?kind=document",
            files={"files": ("测试.md", "先核对测试数据。".encode())},
            headers=HEADERS,
        )
        assert response.status_code == 200
        original = response.json()["imported"][0]
        [source] = client.get("/api/persona/sources").json()["items"]
        assert all(source[key] == value for key, value in original.items() if key not in ("new", "skipped_lines"))
        assert source["build_status"] == "not_built" and source["expressions_target"] == 1
        assert client.get("/api/persona/state").json()["stale"]
        logs: list[str] = []
        result = run_persona_build(settings, FakeLLM(handler), HashingEmbedder(), logs.append)
        assert result["facet_diffs"]["2.1"] == {"added": 1, "changed": 0, "removed": 0}
        assert result["items_added"] == 1 and result["facets_changed"] == 1
        assert "items" in result and "failures" in result
        assert not any("他核对测试数据" in line for line in logs)
        [source] = client.get("/api/persona/sources").json()["items"]
        assert source["items_supported"] == 1 and source["facets"][0]["facet_id"] == "2.1"
        assert source["build_status"] == "remembered"
        state = client.get("/api/persona/state").json()
        assert not state["stale"]
        assert client.delete(f"/api/persona/sources/{source['source_id']}", headers=HEADERS).status_code == 200
        # The deletion is a change since that build. Deleting queues a rebuild, which may already have caught up, so
        # the change is checked, not that the state still reads stale.
        after = client.get("/api/persona/state").json()
        assert dt.datetime.fromisoformat(after["sources_changed_at"]) > dt.datetime.fromisoformat(state["built_at"])
        rebuild = client.post("/api/persona/build", headers=HEADERS)
        assert rebuild.status_code == 202  # rebuild after deleting the last source is still allowed
        job_id = rebuild.json()["job_id"]
        deadline = time.monotonic() + 5
        while True:
            job = client.get(f"/api/jobs/{job_id}").json()
            if job["status"] in ("done", "failed"):
                break
            assert time.monotonic() < deadline
            time.sleep(0.01)
        assert job["status"] == "done" and job["result"]["items_removed"] == 1
        assert job["result"]["facet_diffs"]["2.1"] == {"added": 0, "changed": 0, "removed": 1}
        assert not client.get("/api/persona/state").json()["stale"]
        assert client.get("/api/persona/items").json()["items"] == []
        assert pf.STALE_PROFILE_NOTICE == "资料有变化，尚未重新构建；档案和聊天仍基于上次构建"


def test_cli_sources_build_and_stale_chat(settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config = tmp_path / "twin.toml"
    config.write_text('target_name = "合成人物"\n', encoding="utf-8")
    monkeypatch.setattr(cli, "_settings", lambda ctx: settings)
    monkeypatch.setattr(cli, "_llm", lambda settings, **kwargs: CallTally(FakeLLM(handler)))
    monkeypatch.setattr(cli, "_embedder", lambda settings: HashingEmbedder())
    runner = CliRunner()
    args = ["--config", str(config), "persona"]
    with PersonaStore(settings.db_path) as store:
        imported(store, settings)
    sources = runner.invoke(cli.app, [*args, "sources"])
    assert sources.exit_code == 0 and "尚未构建" in sources.stdout and "支撑档案 0 条" in sources.stdout
    build = runner.invoke(cli.app, [*args, "build"])
    assert build.exit_code == 0, build.output
    assert pf.STALE_PROFILE_NOTICE in build.stderr
    assert "新增 1 条、修改 0 条、删除 0 条，涉及 1 个细项" in build.stdout
    assert "2.1：新增 1 条" in build.stdout
    assert "支撑档案 1 条" in runner.invoke(cli.app, [*args, "sources"]).stdout
    assert pf.STALE_PROFILE_NOTICE not in runner.invoke(cli.app, [*args, "chat", "合成问题"]).stderr
    with PersonaStore(settings.db_path) as store:
        imported(store, settings, "新增.md")
    chat = runner.invoke(cli.app, [*args, "chat", "合成问题"])
    assert chat.exit_code == 0 and pf.STALE_PROFILE_NOTICE in chat.stderr
    assert "合成测试回复" in chat.stdout


def test_web_shows_chunk_progress_while_a_build_runs(settings: Settings) -> None:
    started, release = threading.Event(), threading.Event()

    def slow(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
        if schema is pf.ExtractDraft:
            started.set()
            assert release.wait(5)
        return handler(system, user, schema)

    app = create_app(settings, llm_factory=lambda: FakeLLM(slow), embedder_factory=HashingEmbedder)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        client.post(
            "/api/persona/import?kind=document",
            files={"files": ("测试.md", "先核对测试数据。".encode())},
            headers=HEADERS,
        )
        job = client.post("/api/persona/build", headers=HEADERS).json()["job_id"]
        assert started.wait(5)
        assert client.get("/api/persona/processing").json()["progress"] == {"phase": "extract", "done": 0, "total": 1}
        # The team's card reads the same progress.
        registry = app.state.personas
        status = registry.build_status(registry.data["default"])
        assert status["state"] == "running" and status["progress"] == {"phase": "extract", "done": 0, "total": 1}
        [source] = client.get("/api/persona/sources").json()["items"]
        assert (source["status"], source["chunks_done"], source["chunks_total"]) == ("processing", 0, 1)
        release.set()
        for _ in range(200):
            if client.get(f"/api/jobs/{job}").json()["status"] in {"done", "failed"}:
                break
            time.sleep(0.02)
        assert "progress" not in client.get("/api/persona/processing").json()
        [source] = client.get("/api/persona/sources").json()["items"]
        assert source["status"] == "remembered" and "chunks_total" not in source


def test_a_source_that_found_nothing_is_extracted_again(settings: Settings) -> None:
    with PersonaStore(":memory:") as store:
        empty, other = imported(store, settings), imported(store, settings, "测试乙.md")
        llm = FakeLLM(lambda system, user, schema: {"items": []})
        pf.build_profile(store, llm, settings)
        assert pf.source_memories(store)[empty].build_status == "no_items"
        assert pf.build_profile(store, llm, settings).chunks_extracted == 0  # done chunks are never asked again

        assert store.reextract_source("src_missing") is None
        assert store.reextract_source(empty) == 1
        assert pf.profile_stale(store) and store.source_status(empty, 0) == "processing"
        assert pf.source_memories(store)[empty].chunks_extracted == 0
        report = pf.build_profile(store, FakeLLM(handler), settings)
        assert report.chunks_extracted == 1  # only the source asked for, not the other unchanged one
        memories = pf.source_memories(store)
        assert memories[empty].build_status == "remembered" and memories[other].build_status == "no_items"
        assert not pf.profile_stale(store)


def test_web_and_cli_reextract(settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    with PersonaStore(settings.db_path) as store:
        sids = [imported(store, settings, f"测试{n}.md") for n in range(3)]
        pf.build_profile(store, FakeLLM(lambda system, user, schema: {"items": []}), settings)
    app = create_app(settings, llm_factory=lambda: FakeLLM(handler), embedder_factory=HashingEmbedder)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert client.post("/api/persona/sources/src_missing/reextract", headers=HEADERS).status_code == 404
        response = client.post(f"/api/persona/sources/{sids[0]}/reextract", headers=HEADERS)
        assert response.status_code == 202 and response.json() == {"chunks": 1}
        deadline = time.monotonic() + 5
        while (
            client.get("/api/persona/processing").json()["state"] != "idle"
            or client.get("/api/persona/state").json()["stale"]
        ):
            assert time.monotonic() < deadline
            time.sleep(0.01)
        rows = {s["source_id"]: s for s in client.get("/api/persona/sources").json()["items"]}
        assert rows[sids[0]]["status"] == "remembered" and rows[sids[1]]["status"] == "nothing_found"
        assert rows[sids[1]]["nothing_found_reason"] == "模型没有从中提炼出结论"
        assert rows[sids[1]]["extraction"]["returned"] == 0

    config = tmp_path / "twin.toml"
    config.write_text('target_name = "合成人物"\n', encoding="utf-8")
    monkeypatch.setattr(cli, "_settings", lambda ctx: settings)
    runner = CliRunner()
    args = ["--config", str(config), "persona", "reextract"]
    assert runner.invoke(cli.app, args).exit_code != 0
    missing = runner.invoke(cli.app, [*args, "src_missing"])
    assert missing.exit_code != 0 and "找不到资料：src_missing" in missing.output
    settings.kernel.max_auto_rebuild_chunks = 1
    gated = runner.invoke(cli.app, [*args, "--nothing-found"])
    assert gated.exit_code != 0 and "将重抽 2 份资料的 2 个分段，超过费用闸" in gated.output
    with PersonaStore(settings.db_path) as store:
        assert not pf.profile_stale(store)
    done = runner.invoke(cli.app, [*args, "--nothing-found", "--yes"])
    assert done.exit_code == 0 and "已标记 2 份资料（2 个分段）重新抽取" in done.output
    with PersonaStore(settings.db_path) as store:
        memories = pf.source_memories(store)
        assert [memories[s].chunks_extracted for s in sids] == [1, 0, 0] and pf.profile_stale(store)


def test_cli_reextracts_only_empty_chunks(settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    with PersonaStore(settings.db_path) as store:
        found, empty = imported(store, settings, "有结论.md"), imported(store, settings, "无结论.md")
        pf.build_profile(store, FakeLLM(lambda s, u, schema: {"items": []}), settings)
        store.reextract_source(found)
        pf.build_profile(store, FakeLLM(handler), settings)
        assert store.empty_chunks() == {empty: 1}
    config = tmp_path / "twin.toml"
    config.write_text('target_name = "合成人物"\n', encoding="utf-8")
    monkeypatch.setattr(cli, "_settings", lambda ctx: settings)
    runner = CliRunner()
    args = ["--config", str(config), "persona", "reextract", "--empty-chunks"]
    none = runner.invoke(cli.app, [*args, found])
    assert none.exit_code != 0 and "没有一条结论也没抽出的分段" in none.output
    settings.kernel.max_auto_rebuild_chunks = 0
    gated = runner.invoke(cli.app, args)
    assert gated.exit_code != 0 and "将重抽 1 份资料的 1 个分段，超过费用闸" in gated.output
    done = runner.invoke(cli.app, [*args, "--yes"])
    assert done.exit_code == 0 and "已标记 1 份资料（1 个分段）重新抽取" in done.output
    with PersonaStore(settings.db_path) as store:
        assert store.empty_chunks() == {} and pf.profile_stale(store)
        assert pf.source_memories(store)[found].chunks_extracted == 1


def test_a_build_finishes_without_the_embedding_service_and_its_vectors_follow_once_it_answers(
    settings: Settings,
) -> None:
    from types import SimpleNamespace

    from twin.embed import EmbedError
    from twin.persona import chat as pc
    from twin.web.index_retry import IndexRetry

    down = {"on": True}

    class Unreachable(HashingEmbedder):
        def embed(self, texts: list[str]) -> Any:
            if down["on"]:
                raise EmbedError("connection refused")
            return super().embed(texts)

    app = create_app(settings, llm_factory=lambda: FakeLLM(handler), embedder_factory=Unreachable)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        client.post(
            "/api/persona/import?kind=document",
            files={"files": ("测试.md", "先核对测试数据。".encode())},
            headers=HEADERS,
        )
        logs: list[str] = []
        result = run_persona_build(settings, FakeLLM(handler), Unreachable(), logs.append)
        assert result["index_pending"] and result["items_added"] == 1
        assert "向量服务暂时连不上：先按关键词检索，服务恢复后自动补齐" in logs
        assert not client.get("/api/persona/state").json()["stale"]  # the memory is built all the same
        with PersonaStore(settings.db_path) as store:
            assert pc.index_stale(store, Unreachable())

        retry = IndexRetry(app.state.personas, SimpleNamespace(embedder=Unreachable))  # type: ignore[arg-type]
        assert retry.tick() == 0  # still unreachable: nothing is started
        down["on"] = False
        assert retry.tick() == 1
        deadline = time.monotonic() + 10
        while True:
            with PersonaStore(settings.db_path) as store:
                if not pc.index_stale(store, Unreachable()):
                    break
            assert time.monotonic() < deadline
            time.sleep(0.05)
        assert retry.tick() == 0  # nothing is behind any more
