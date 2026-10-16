"""Paged, filtered profile items and memories: the store's SQL filters agree with the full lists, and the web routes
page, count and search without the browser ever holding every row."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from twin.config import Settings
from twin.persona.dimensions import FACET_BY_ID
from twin.persona.items import PersonaItem, PEvidence, PReview
from twin.persona.schema import EvidenceClass, ReviewStatus, SourceKind
from twin.persona.sources import parse_text
from twin.persona.store import PersonaStore
from twin.web import create_app

HEADERS = {"X-Twin": "1"}
FACETS = ("1.1", "2.1", "2.2", "6.1")


def evidence(source_id: str, quote: str) -> PEvidence:
    return PEvidence(
        expression_id=f"e_{source_id}",
        source_id=source_id,
        source_kind=SourceKind.DOCUMENT,
        evidence_class=EvidenceClass.BEHAVIOR,
        quote=quote,
    )


def seed_items(store: PersonaStore) -> None:
    """24 items over four facets; item ``n`` has ``n % 4 + 1`` evidence, every third is reviewed and every fifth has
    conflicting evidence."""
    by_facet: dict[str, list[PersonaItem]] = {}
    for n in range(24):
        facet = FACETS[n % 4]
        quotes = [evidence(f"s{k}", f"原话{n}-{k}") for k in range(n % 4 + 1)]
        by_facet.setdefault(facet, []).append(
            PersonaItem(
                item_id=f"pi_{n:02d}",
                facet_id=facet,
                statement=f"合成条目{n}",
                evidence=quotes,
                conflict="说的和做的不一样" if n % 5 == 0 else "",
            )
        )
    for facet, items in by_facet.items():
        store.replace_facet_items(facet, items)
    statuses = (ReviewStatus.CONFIRMED, ReviewStatus.REJECTED, ReviewStatus.EDITED)
    for n in range(0, 24, 3):
        status = statuses[(n // 3) % 3]
        store.set_review(
            f"pi_{n:02d}",
            PReview(
                status=status,
                statement=f"改写{n}" if status is ReviewStatus.EDITED else None,
                reviewed_at="2026-01-01T00:00:00",
            ),
        )


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(target_name="合成人物", db_path=tmp_path / "twin.db")


@pytest.fixture
def client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings), base_url="http://127.0.0.1")


def test_query_items_matches_the_full_list_under_every_filter() -> None:
    with PersonaStore(":memory:") as store:
        seed_items(store)
        everything = store.list_items(include_rejected=True)
        cases: list[tuple[dict[str, Any], list[PersonaItem]]] = [
            ({}, [i for i in everything if i.review is not ReviewStatus.REJECTED]),
            ({"include_rejected": True}, everything),
            ({"review": ReviewStatus.UNREVIEWED}, [i for i in everything if i.review is ReviewStatus.UNREVIEWED]),
            ({"review": ReviewStatus.REJECTED}, [i for i in everything if i.review is ReviewStatus.REJECTED]),
            ({"facet_ids": ["2.1", "2.2"]}, [i for i in everything if i.facet_id[0] == "2" and i.review != "rejected"]),
            ({"facet_ids": []}, []),
            # pi_15 was edited to 改写15: the search matches the statement shown, not the one it replaced.
            ({"text": "合成条目1"}, [i for i in everything if "合成条目1" in i.statement and i.review != "rejected"]),
            ({"text": "改写6"}, [i for i in everything if i.item_id == "pi_06"]),
            ({"text": "原话7-3"}, [i for i in everything if i.item_id == "pi_07"]),
            ({"source_id": "s3"}, [i for i in everything if len(i.evidence) == 4 and i.review != "rejected"]),
            ({"conflict": True}, [i for i in everything if i.conflict and i.review != "rejected"]),
        ]
        for filters, expected in cases:
            items, total = store.query_items(**filters)
            assert [i.item_id for i in items] == [i.item_id for i in expected], filters
            assert total == len(expected), filters
        # Reviews are applied to the page exactly as list_items applies them.
        [edited], _ = store.query_items(text="改写6")
        assert edited.statement == "改写6" and edited.extracted_statement == "合成条目6"


def test_query_items_pages_and_sorts_by_evidence() -> None:
    with PersonaStore(":memory:") as store:
        seed_items(store)
        pages = [store.query_items(limit=5, offset=offset) for offset in range(0, 25, 5)]
        assert all(total == len(store.list_items()) for _, total in pages)
        paged = [i.item_id for items, _ in pages for i in items]
        assert paged == [i.item_id for i in store.list_items()]
        ranked, _ = store.query_items(by_evidence=True, limit=4)
        assert [len(i.evidence) for i in ranked] == [4, 4, 4, 4]


def test_item_counts_and_dimension_ids() -> None:
    with PersonaStore(":memory:") as store:
        seed_items(store)
        counts = store.item_counts()
        everything = store.list_items(include_rejected=True)
        assert counts == {
            (facet, status): n
            for facet in FACETS
            for status in ReviewStatus
            if (n := sum(i.facet_id == facet and i.review is status for i in everything))
        }
        assert store.count_items() == len(store.list_items()) == 21 and store.has_items()
        assert set(store.get_items(["pi_00", "pi_missing"])) == {"pi_00"}


def test_items_route_pages_filters_and_summarises(settings: Settings, client: TestClient) -> None:
    with PersonaStore(settings.db_path) as store:
        seed_items(store)
    first = client.get("/api/persona/items", params={"limit": 5}, headers=HEADERS).json()
    assert first["total"] == 21 and len(first["items"]) == 5
    rest = client.get("/api/persona/items", params={"limit": 50, "offset": 5}, headers=HEADERS).json()
    assert len(rest["items"]) == 16
    d2 = client.get("/api/persona/items", params={"dimension": "D2", "review": "unreviewed"}, headers=HEADERS)
    assert {i["dimension_id"] for i in d2.json()["items"]} == {"D2"} and d2.json()["total"] == 8
    both = client.get("/api/persona/items", params=[("dimension", "D1"), ("dimension", "D6")], headers=HEADERS)
    assert {i["dimension_id"] for i in both.json()["items"]} == {"D1", "D6"}
    cited = client.get("/api/persona/items", params={"source_id": "s3", "with_sources": "true"}, headers=HEADERS)
    assert cited.json()["total"] == 5 and cited.json()["sources"] == {}
    assert client.get("/api/persona/items", params={"dimension": "D99"}, headers=HEADERS).status_code == 400
    assert client.get("/api/persona/items", params={"limit": 501}, headers=HEADERS).status_code == 400

    summary = client.get("/api/persona/items/summary", headers=HEADERS).json()
    assert summary["total"] == 21 and summary["conflicts"] == 5 and "unreviewed" not in summary
    by_dimension = {d["dimension_id"]: d["total"] for d in summary["dimensions"]}
    expected: dict[str, int] = {}
    with PersonaStore(settings.db_path) as store:
        for item in store.list_items():
            dimension_id = FACET_BY_ID[item.facet_id].dimension_id
            expected[dimension_id] = expected.get(dimension_id, 0) + 1
    assert by_dimension == expected
    assert [d["dimension_id"] for d in summary["dimensions"]] == sorted(by_dimension)


def test_search_finds_items_by_statement_or_quote_and_never_a_rejected_one(
    settings: Settings, client: TestClient
) -> None:
    with PersonaStore(settings.db_path) as store:
        seed_items(store)

    def search(q: str, **params: Any) -> list[str]:
        response = client.get("/api/persona/items/search", params={"q": q, **params}, headers=HEADERS)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["total"] == len(body["items"])
        return [i["item_id"] for i in body["items"]]

    assert search("原话7-3")[0] == "pi_07"  # only pi_07 has a fourth quote 7-3
    assert search("改写6")[0] == "pi_06"  # the statement as the person edited it
    assert "pi_03" not in search("合成条目3")  # rejected
    assert len(search("合成条目", limit=3)) == 3
    assert client.get("/api/persona/items/search", params={"q": "  "}, headers=HEADERS).status_code == 400
    assert client.get("/api/persona/items/search", headers=HEADERS).status_code == 400
    assert client.get("/api/persona/items/search", params={"q": "x", "limit": 0}, headers=HEADERS).status_code == 400


def test_sources_route_pages_with_summary_attention_and_filters(settings: Settings, client: TestClient) -> None:
    with PersonaStore(settings.db_path) as store:
        ids = []
        for n in range(7):
            parsed = parse_text(SourceKind.DOCUMENT, f"资料{n}.md", f"第{n}份资料。", settings, dt.date(2026, 1, n + 1))
            store.put_source(parsed)
            ids.append(parsed.source.source_id)
        speaker = store.get_source(ids[2])
        assert speaker is not None
        store.update_source(speaker.model_copy(update={"media_status": "needs_speaker", "duration_s": 90.0}))
        voiced = store.get_source(ids[4])
        assert voiced is not None
        store.update_source(voiced.model_copy(update={"voice_candidates": 2, "duration_s": 30.0}))
    page = client.get("/api/persona/sources", params={"limit": 3}, headers=HEADERS).json()
    assert [row["source_id"] for row in page["items"]] == ids[:3] and page["total"] == 7
    assert page["summary"] == {
        "total": 7,
        "duration_s": 120.0,
        "needs_speaker": 1,
        "remembered": 0,
        "nothing_found": 0,
        "failed": 0,
        "busy": 6,
    }
    assert "attention" not in page
    rest = client.get("/api/persona/sources", params={"limit": 3, "offset": 6}, headers=HEADERS).json()
    assert [row["source_id"] for row in rest["items"]] == ids[6:]
    counts = client.get("/api/persona/sources", params={"limit": 0, "attention": "true"}, headers=HEADERS).json()
    assert counts["items"] == [] and [row["source_id"] for row in counts["attention"]] == [ids[2]]
    waiting = client.get("/api/persona/sources", params={"status": "needs_speaker"}, headers=HEADERS).json()
    assert [row["source_id"] for row in waiting["items"]] == [ids[2]] and waiting["total"] == 1
    voices = client.get("/api/persona/sources", params={"candidates": "true"}, headers=HEADERS).json()
    assert [row["source_id"] for row in voices["items"]] == [ids[4]]
