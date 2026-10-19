"""Text transcripts in which the person is not recognised wait, and are claimed by name across files at once."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from twin.config import Settings
from twin.embed import HashingEmbedder
from twin.llm import FakeLLM
from twin.persona import profile as pf
from twin.persona.store import PersonaStore
from twin.persona.transcripts import _similar
from twin.web import create_app
from twin.web.persona import run_persona_build

HEADERS = {"X-Twin": "1"}

MINE = "林沐：先核对测试数据。\n小明：好的。\n林沐：再定排期。\n小明：行。\n"
# The person goes by another name here; 小明 says the most of anyone.
NICKNAME_1 = (
    "林沐老师：这周先核对测试数据，因为客户下周要看。\n"
    "小明：我觉得排期太紧了，接口还没联调完，测试环境也没准备好，要不要往后挪一周？\n"
    "林沐老师：不挪，先核对。\n"
    "小明：那我今晚把联调做完，明天上午给你结果，下午再一起过一遍测试数据。\n"
)
NICKNAME_2 = "小张：上线前要回归吗？\n林沐老师：要，核对完再上线。\n小张：好。\n林沐老师：辛苦。\n"
ANONYMOUS = "发言人1：方案先这么定。\n发言人2：同意，我来写文档。\n发言人1：周五前给我。\n发言人2：没问题。\n"
ANONYMOUS_2 = "发言人1：今天聊聊招聘。\n发言人2：先招后端。\n发言人1：好。\n发言人2：我去发需求。\n"
LATER_MINE = "林沐老师：明天复盘。\n小王：几点？\n林沐老师：十点。\n小王：好。\n"
LATER_OTHERS = "小明：周报发了吗？\n小张：发了。\n小明：好。\n小张：嗯。\n"


@pytest.fixture
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.delenv("TWIN_CONFIG", raising=False)
    return Settings(target_name="林沐", db_path=tmp_path / "memory.db", max_workers=1, pseudonymize_others=False)


def handler(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
    if schema is pf.ExtractDraft:
        return {"items": [{"facet_id": "2.1", "statement": "他先核对数据", "quotes": [{"n": 1, "quote": "核对"}]}]}
    raise AssertionError(schema)


def upload(client: TestClient, files: dict[str, str]) -> dict[str, Any]:
    response = client.post(
        "/api/persona/import?kind=interview",
        files=[("files", (name, text.encode())) for name, text in files.items()],
        headers=HEADERS,
    )
    assert response.status_code == 200, response.text
    return response.json()


def by_title(client: TestClient) -> dict[str, dict[str, Any]]:
    return {s["title"]: s for s in client.get("/api/persona/sources").json()["items"]}


def targets(settings: Settings) -> dict[str, set[str]]:
    """Per source title, the speakers whose lines count as the person's."""
    with PersonaStore(settings.db_path) as store:
        titles = {s.source_id: s.title for s in store.list_sources()}
        found: dict[str, set[str]] = {}
        for e in store.list_expressions(target_only=True):
            found.setdefault(titles[e.source_id], set()).add(e.speaker)
        return found


def test_names_are_claimed_across_files_and_labels_per_file(settings: Settings) -> None:
    app = create_app(settings, llm_factory=lambda: FakeLLM(handler), embedder_factory=HashingEmbedder)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        result = upload(
            client,
            {
                "mine.txt": MINE,
                "n1.txt": NICKNAME_1,
                "n2.txt": NICKNAME_2,
                "anon.txt": ANONYMOUS,
                "anon2.txt": ANONYMOUS_2,
            },
        )
        # Nothing is refused: the transcripts without the person wait, with no line counted as theirs.
        assert result["skipped"] == [] and len(result["imported"]) == 5
        sources = by_title(client)
        assert sources["mine"]["status"] != "needs_name"
        assert {t for t, s in sources.items() if s["status"] == "needs_name"} == {"n1", "n2", "anon", "anon2"}
        assert client.get("/api/persona/sources").json()["summary"]["needs_name"] == 4
        assert targets(settings) == {"mine": {"林沐"}}

        # A build reads only the transcript the person is known in.
        run_persona_build(settings, FakeLLM(handler), HashingEmbedder(), lambda _: None)
        with sqlite3.connect(settings.db_path) as db:
            read = {r[0] for r in db.execute("SELECT DISTINCT source_id FROM p_chunks")}
        assert read == {sources["mine"]["source_id"]}

        roster = client.get("/api/persona/transcripts/speakers").json()
        assert roster["pending"] == 4
        names = {row["name"]: row for row in roster["names"]}
        assert [row["name"] for row in roster["names"]] == ["小明", "林沐老师", "小张"]  # most words first
        assert names["林沐老师"]["files"] == 2 and names["林沐老师"]["segments"] == 4
        assert names["林沐老师"]["likely"] == "和你的名字相近" and names["小明"]["likely"] == "说得最多"
        assert names["小张"]["likely"] is None
        samples = names["小明"]["samples"]
        assert len(samples) == 2 and samples[0].startswith("我觉得排期太紧了")  # longest first
        # Files with names wait for the names; only label-only files are asked about one by one.
        assert {f["title"] for f in roster["files"]} == {"anon", "anon2"}
        anon = next(f for f in roster["files"] if f["title"] == "anon")
        assert [s["label"] for s in anon["speakers"]] == ["发言人1", "发言人2"]  # equal words: by label

        answer = client.post(
            "/api/persona/transcripts/names", json={"mine": ["林沐老师"], "others": ["小明", "小张"]}, headers=HEADERS
        ).json()
        assert answer["pending"] == 2 and answer["names"] == [] and answer["aliases"] == ["林沐老师"]
        assert targets(settings) == {"mine": {"林沐"}, "n1": {"林沐老师"}, "n2": {"林沐老师"}}
        assert {t for t, s in by_title(client).items() if s["status"] == "needs_name"} == {"anon", "anon2"}

        # Later uploads are attributed by what was said: the alias is the person, names said not to be stay others.
        upload(client, {"later.txt": LATER_MINE, "others.txt": LATER_OTHERS})
        sources = by_title(client)
        assert sources["later"]["status"] != "needs_name" and sources["others"]["status"] != "needs_name"
        assert targets(settings)["later"] == {"林沐老师"} and "others" not in targets(settings)

        # A label is picked in its file alone, never kept as a name.
        anon_id = sources["anon"]["source_id"]
        assert (
            client.put(
                f"/api/persona/transcripts/{anon_id}/speakers", json={"speakers": ["发言人9"]}, headers=HEADERS
            ).status_code
            == 400
        )
        answer = client.put(
            f"/api/persona/transcripts/{anon_id}/speakers", json={"speakers": ["发言人1"]}, headers=HEADERS
        ).json()
        assert answer["aliases"] == ["林沐老师"] and [f["title"] for f in answer["files"]] == ["anon2"]
        assert targets(settings)["anon"] == {"发言人1"} and "anon2" not in targets(settings)
        refused = client.post("/api/persona/transcripts/names", json={"mine": ["发言人2"]}, headers=HEADERS)
        assert refused.status_code == 400

        answer = client.post(
            "/api/persona/transcripts/not-mine", json={"source_ids": [sources["anon2"]["source_id"]]}, headers=HEADERS
        ).json()
        assert answer["pending"] == 0 and answer["files"] == []
        assert "anon2" not in targets(settings)
        assert client.get("/api/persona/sources").json()["summary"]["needs_name"] == 0

        # No one else's line was ever counted as the person's.
        assert targets(settings) == {
            "mine": {"林沐"},
            "n1": {"林沐老师"},
            "n2": {"林沐老师"},
            "later": {"林沐老师"},
            "anon": {"发言人1"},
        }


def test_removing_an_alias_gives_its_lines_back_and_forgets_what_was_read(settings: Settings) -> None:
    app = create_app(settings, llm_factory=lambda: FakeLLM(handler), embedder_factory=HashingEmbedder)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        upload(client, {"n1.txt": NICKNAME_1})
        client.post("/api/persona/aliases", json={"name": " 林沐老师 "}, headers=HEADERS)
        assert client.get("/api/persona/aliases").json() == {"aliases": ["林沐老师"], "fixed": ["林沐"], "not_me": 0}
        source_id = by_title(client)["n1"]["source_id"]
        run_persona_build(settings, FakeLLM(handler), HashingEmbedder(), lambda _: None)
        with sqlite3.connect(settings.db_path) as db:
            assert db.execute("SELECT COUNT(*) FROM p_chunks WHERE source_id = ?", (source_id,)).fetchone()[0] > 0

        assert client.delete("/api/persona/aliases/林沐老师", headers=HEADERS).json()["changed"] == 1
        assert client.delete("/api/persona/aliases/林沐老师", headers=HEADERS).status_code == 404
        assert targets(settings) == {}
        assert client.get("/api/persona/aliases").json() == {"aliases": [], "fixed": ["林沐"], "not_me": 1}
        with sqlite3.connect(settings.db_path) as db:
            assert db.execute("SELECT COUNT(*) FROM p_chunks WHERE source_id = ?", (source_id,)).fetchone()[0] == 0
        # Removed means "not me": the name is not asked about again, but 小明, never answered for, still is.
        assert by_title(client)["n1"]["status"] == "needs_name"
        assert [row["name"] for row in client.get("/api/persona/transcripts/speakers").json()["names"]] == ["小明"]


def test_a_new_name_attributes_waiting_transcripts(settings: Settings) -> None:
    app = create_app(settings, llm_factory=lambda: FakeLLM(handler), embedder_factory=HashingEmbedder)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        upload(client, {"n2.txt": NICKNAME_2})
        assert by_title(client)["n2"]["status"] == "needs_name"
        client.put("/api/identity", json={"name": "林沐老师", "about": ""}, headers=HEADERS)
        assert targets(settings) == {"n2": {"林沐老师"}}
        assert by_title(client)["n2"]["status"] != "needs_name"


def test_similar_names() -> None:
    assert _similar("林沐老师", ["林沐"]) and _similar("Lin Mu", ["LinMu"])
    assert not _similar("小明", ["林沐"]) and not _similar("林", ["林沐"])
