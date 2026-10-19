"""A taxonomy change moves stored facet ids on open, keeps the profile answering, and carries reviews through the
rebuild (kernel.TAXONOMY_MIGRATIONS)."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import replace
from itertools import pairwise
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from twin.config import Settings
from twin.embed import HashingEmbedder
from twin.llm import FakeLLM
from twin.persona import kernel, profile
from twin.persona import store as storage
from twin.persona.chat import PersonaChat
from twin.persona.dimensions import FACETS
from twin.persona.items import PReview
from twin.persona.kernel import (
    KERNEL,
    TAXONOMY_FACET_IDS,
    TAXONOMY_FINGERPRINTS,
    TAXONOMY_MIGRATIONS,
    TAXONOMY_VERSION,
    kernel_json,
    taxonomy_plan,
)
from twin.persona.schema import ReviewStatus
from twin.persona.sources import parse_note
from twin.persona.store import PersonaStore
from twin.web.app import create_app


def test_every_taxonomy_declares_its_facets_and_moves() -> None:
    versions = list(TAXONOMY_FACET_IDS)
    assert versions == list(TAXONOMY_FINGERPRINTS), "每个分类版本都要在 TAXONOMY_FACET_IDS 里列出细项编号"
    assert TAXONOMY_FACET_IDS[TAXONOMY_VERSION] == tuple(f.facet_id for f in FACETS), (
        "细项编号变了：请在 kernel.TAXONOMY_FACET_IDS 加新版本，并在 TAXONOMY_MIGRATIONS 写明旧编号去向"
    )
    assert list(TAXONOMY_MIGRATIONS) == versions[1:]
    for previous, version in pairwise(versions):
        old, new = set(TAXONOMY_FACET_IDS[previous]), set(TAXONOMY_FACET_IDS[version])
        step = TAXONOMY_MIGRATIONS[version]
        assert step.keys() <= old, f"{version} 迁移了 {previous} 里没有的细项"
        assert old - new <= step.keys(), f"{version} 去掉了 {sorted(old - new - step.keys())}，没写去向"
        assert all(set(targets) <= new for targets in step.values()), f"{version} 迁移到了不存在的细项"


def test_plan_composes_steps(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        kernel, "TAXONOMY_FACET_IDS", {"t0": ("a", "k", "x"), "t1": ("b", "c", "k"), "t2": ("c", "d", "k")}
    )
    monkeypatch.setattr(kernel, "TAXONOMY_MIGRATIONS", {"t1": {"a": ("b", "c"), "x": ()}, "t2": {"b": ("d",)}})
    assert taxonomy_plan("t0", "t2") == {"a": ("d", "c"), "x": ()}
    assert taxonomy_plan("t1", "t2") == {"b": ("d",)}
    assert taxonomy_plan("t2", "t2") == {}
    assert taxonomy_plan("t2", "t0") is None  # never backwards
    assert taxonomy_plan("t9", "t2") is None  # a store from a newer twin


# The old taxonomy "t0" of the upgrade test: 2.9 splits into 2.1 and 2.2, 4.9 becomes 4.2, 6.9 is dropped.
OLD_IDS = {"2.1": "2.9", "4.2": "4.9", "6.1": "6.9"}
STEP = {"2.9": ("2.1", "2.2"), "4.9": ("4.2",), "6.9": ()}


def _declare_old_taxonomy(monkeypatch: pytest.MonkeyPatch) -> None:
    current = TAXONOMY_FACET_IDS[TAXONOMY_VERSION]
    old = tuple(OLD_IDS.get(f, f) for f in current if f not in {"2.2"})
    monkeypatch.setattr(kernel, "TAXONOMY_FACET_IDS", {"t0": old, **TAXONOMY_FACET_IDS})
    first = next(iter(TAXONOMY_FACET_IDS))  # the oldest real version now follows "t0"
    monkeypatch.setattr(kernel, "TAXONOMY_MIGRATIONS", {first: STEP, **TAXONOMY_MIGRATIONS})


def _rewrite(path: Path, facets: dict[str, str], taxonomy: str, absent: frozenset[str] = frozenset()) -> None:
    """Turn a store built today into one an older twin left behind: its rows, chunk records and merge keys under
    other facet ids, and nothing for the facets ``absent`` from that taxonomy."""
    with sqlite3.connect(path) as db:
        for table in ("p_items", "p_candidates"):
            for new, old in facets.items():
                db.execute(
                    f"UPDATE {table} SET facet_id = ?, json = json_set(json, '$.facet_id', ?) WHERE facet_id = ?",
                    (old, old, new),
                )
        for chunk_id, done in db.execute("SELECT chunk_id, facets FROM p_chunks").fetchall():
            old_ids = sorted(facets.get(f, f) for f in json.loads(done) if f not in absent)
            db.execute("UPDATE p_chunks SET facets = ? WHERE chunk_id = ?", (json.dumps(old_ids), chunk_id))
        for new in absent:
            db.execute("DELETE FROM p_meta WHERE key = ? OR key LIKE ?", (f"merge:{new}", f"merge_batch:{new}:%"))
        moved = {f"merge:{new}": f"merge:{old}" for new, old in facets.items()}
        for key, value in db.execute("SELECT key, value FROM p_meta WHERE key LIKE 'merge:%'").fetchall():
            if key in moved:
                db.execute("DELETE FROM p_meta WHERE key = ?", (key,))
                db.execute("INSERT OR REPLACE INTO p_meta VALUES (?, ?)", (moved[key], value))
        db.execute("INSERT OR REPLACE INTO p_meta VALUES (?, ?)", (storage.TAXONOMY_META, taxonomy))
        db.execute(
            "INSERT OR REPLACE INTO p_meta VALUES ('kernel:built', ?)",
            (kernel_json(replace(KERNEL, taxonomy=taxonomy)),),
        )


def test_taxonomy_upgrade_keeps_serving_and_carries_reviews(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    facet = {"回款": "2.1", "跑步": "4.2", "开会": "6.1"}
    wording = {"回款": "做事先看回款", "跑步": "每周跑步三次", "开会": "开会先听别人说"}

    def handler(system: str, user: str, schema: type) -> dict[str, object]:
        if schema is profile.ExtractDraft:
            found = re.findall(r"\[(\d+)\][^\n]*\n本人：([^\n]*)", user)
            return {
                "items": [
                    {"facet_id": facet[key], "statement": wording[key], "quotes": [{"n": int(n), "quote": text}]}
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
        ids = {i.statement: i.item_id for i in store.list_items()}
        at = "2026-10-19T10:00:00"
        store.set_review(ids["做事先看回款"], PReview(status=ReviewStatus.CONFIRMED, reviewed_at=at))
        store.set_review(
            ids["每周跑步三次"], PReview(status=ReviewStatus.EDITED, statement="一周跑三次步", reviewed_at=at)
        )
        store.set_review(ids["开会先听别人说"], PReview(status=ReviewStatus.REJECTED, reviewed_at=at))
    _rewrite(settings.db_path, OLD_IDS, "t0", absent=frozenset({"2.2"}))
    _declare_old_taxonomy(monkeypatch)

    # Opening moves the ids at once, without a model call: the profile keeps answering before any rebuild.
    with PersonaStore(settings.db_path) as store:
        assert store.get_meta(storage.TAXONOMY_META) == TAXONOMY_VERSION
        items = {i.statement: i for i in store.list_items(include_rejected=True)}
        assert set(items) == {"做事先看回款", "一周跑三次步"}  # the dropped facet's item is gone
        assert (items["做事先看回款"].facet_id, items["做事先看回款"].review) == ("2.1", ReviewStatus.CONFIRMED)
        assert (items["一周跑三次步"].facet_id, items["一周跑三次步"].review) == ("4.2", ReviewStatus.EDITED)
        # The split's candidates go, to be extracted again for 2.1 and 2.2; the renamed facet keeps its own.
        assert {c.facet_id for c in store.list_candidates()} == {"4.2"}
        assert len(store.reviews()) == 2
        assert PersonaChat(store, FakeLLM(handler), HashingEmbedder(), settings).portrait()[0]
    assert any("taxonomy-t0" in p.name for p in storage.list_snapshots(settings.db_path))
    application = create_app(settings, llm_factory=lambda: FakeLLM(handler), embedder_factory=HashingEmbedder)
    monkeypatch.setattr(profile, "pending_chunks", lambda *_: 10**6)  # above the gate: the rebuild waits
    with TestClient(application, base_url="http://localhost") as client:
        listed = client.get("/api/persona/items")
        assert listed.status_code == 200
        assert {i["facet_id"] for i in listed.json()["items"]} == {"2.1", "4.2"}
    monkeypatch.undo()
    _declare_old_taxonomy(monkeypatch)

    # The rebuild sends each chunk once, for the facets it lacks: the split's (2.1, 2.2) and the new 6.1. 4.2 is not
    # extracted again, so its item and edit stay as they were. 回款 now lands in 2.2, which inherits its confirmation.
    facet.update({"回款": "2.2", "开会": "6.1"})
    wording.update({"回款": "做事优先看回款", "跑步": "坚持每周跑步三次", "开会": "开会时先让别人说"})
    with PersonaStore(settings.db_path) as store:
        assert profile.pending_chunks(store, settings) == 1
        llm = FakeLLM(handler)
        report = profile.build_profile(store, llm, settings)
        assert not report.failures and report.chunks_extracted == 1
        [(_, system, _)] = [call for call in llm.calls if call[0] == "ExtractDraft"]
        assert re.findall(r"^  (\d+\.\d+) ", system, re.M) == ["2.1", "2.2", "6.1"]
        after = {i.extracted_statement or i.statement: i for i in store.list_items(include_rejected=True)}
        assert set(after) == {"做事优先看回款", "每周跑步三次", "开会时先让别人说"}
        assert (after["做事优先看回款"].facet_id, after["做事优先看回款"].review) == ("2.2", ReviewStatus.CONFIRMED)
        assert after["每周跑步三次"].item_id == ids["每周跑步三次"]
        assert (after["每周跑步三次"].review, after["每周跑步三次"].statement) == (ReviewStatus.EDITED, "一周跑三次步")
        # A dropped facet takes its reviews with it; declare a target instead to keep a rejection.
        assert (after["开会时先让别人说"].facet_id, after["开会时先让别人说"].review) == (
            "6.1",
            ReviewStatus.UNREVIEWED,
        )
        assert not store.meta_with_prefix(storage.INHERIT_META)
        assert profile.pending_chunks(store, settings) == 0


def test_store_from_a_newer_taxonomy_is_read_without_its_unknown_facets(tmp_path: Path) -> None:
    settings = Settings(db_path=tmp_path / "twin.db", target_name="本人")

    def handler(system: str, user: str, schema: type) -> dict[str, object]:
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

    with PersonaStore(settings.db_path) as store:
        store.put_source(parse_note("我做事先看回款。\n\n我每周跑步三次。", settings))
        profile.build_profile(store, FakeLLM(handler), settings)
        assert len(store.list_items()) == 2
    _rewrite(settings.db_path, {"4.2": "4.9"}, "v99")
    with PersonaStore(settings.db_path) as store:
        assert store.get_meta(storage.TAXONOMY_META) == "v99"  # left as the newer twin wrote it
        assert [i.facet_id for i in store.list_items()] == ["2.1"]
        assert sum(store.item_counts().values()) == 1
        hidden = store._db.execute("SELECT item_id FROM p_items WHERE facet_id = '4.9'").fetchone()[0]
        assert store.get_item(hidden) is None
    application = create_app(settings, llm_factory=lambda: FakeLLM(handler), embedder_factory=HashingEmbedder)
    with TestClient(application, base_url="http://localhost") as client:
        assert client.get("/api/persona/items").status_code == 200


def _life_handler(system: str, user: str, schema: type) -> dict[str, object]:
    if schema is profile.ExtractDraft:
        found = re.findall(r"\[(\d+)\][^\n]*\n本人：([^\n]*)", user)
        return {
            "items": [
                {
                    "facet_id": "9.1" if "爬山" in text else "2.1",
                    "statement": text,
                    "quotes": [{"n": int(n), "quote": text}],
                }
                for n, text in found
            ]
        }
    listed = re.findall(r"\[(pc_[0-9a-f]+)\][^：]*：(.*)", user)
    return {"items": [{"statement": s, "candidate_ids": [i]} for i, s in listed]}


def test_a_store_from_before_chunk_facets_is_not_extracted_again(tmp_path: Path) -> None:
    """Upgrading to chunk ids without the facet set takes the stored chunks over instead of extracting the corpus
    again: no model call, the same candidates and items."""
    settings = Settings(db_path=tmp_path / "twin.db", target_name="本人")
    with PersonaStore(settings.db_path) as store:
        store.put_source(parse_note("我做事先看回款。\n\n周末我常去爬山。", settings))
        profile.build_profile(store, FakeLLM(_life_handler), settings)
        items = {i.item_id for i in store.list_items()}
        [chunk] = profile.corpus_chunks(store, store.list_sources(), profile.consented_facets(store), settings)
    with sqlite3.connect(settings.db_path) as db:
        db.execute("UPDATE p_chunks SET chunk_id = ?, facets = NULL", (chunk.legacy_id,))
        db.execute(
            "UPDATE p_candidates SET chunk_id = ?, json = json_set(json, '$.chunk_id', ?)",
            (chunk.legacy_id, chunk.legacy_id),
        )
    with PersonaStore(settings.db_path) as store:
        assert profile.pending_chunks(store, settings) == 0
        llm = FakeLLM(_life_handler)
        report = profile.build_profile(store, llm, settings)
        assert (report.chunks_extracted, report.facets_merged, llm.calls) == (0, 0, [])
        assert {i.item_id for i in store.list_items()} == items
        assert store.chunk_facets() == {chunk.chunk_id: profile.consented_facets(store)}
        assert {c.chunk_id for c in store.list_candidates()} == {chunk.chunk_id}


@pytest.mark.usefixtures("gated_life_facets")
def test_consent_extracts_or_forgets_only_the_facets_it_changes(tmp_path: Path) -> None:
    settings = Settings(db_path=tmp_path / "twin.db", target_name="本人")
    with PersonaStore(settings.db_path) as store:
        store.put_source(parse_note("我做事先看回款。\n\n周末我常去爬山。", settings))
        profile.build_profile(store, FakeLLM(_life_handler), settings)
        assert {i.facet_id for i in store.list_items()} == {"2.1"}

        # Granting the life facets extracts them alone, from the chunk already stored.
        llm = FakeLLM(_life_handler)
        profile.build_profile(store, llm, settings, grant_gated=True)
        [(_, system, _)] = [call for call in llm.calls if call[0] == "ExtractDraft"]
        assert {f for f in re.findall(r"^  (\d+\.\d+) ", system, re.M)} == {"9.1", "9.2", "9.3", "9.4", "9.5"}
        assert {i.facet_id for i in store.list_items()} == {"2.1", "9.1"}

        # Without the grant again, what was extracted for them is forgotten, with no model call.
        llm = FakeLLM(_life_handler)
        profile.build_profile(store, llm, settings)
        assert not [call for call in llm.calls if call[0] == "ExtractDraft"]
        assert {c.facet_id for c in store.list_candidates()} == {"2.1"}
        assert {i.facet_id for i in store.list_items()} == {"2.1"}
