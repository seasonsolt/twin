from __future__ import annotations

import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from twin.config import Settings
from twin.embed import HashingEmbedder
from twin.llm import FakeLLM
from twin.persona.schema import ChatReply
from twin.persona.store import PersonaStore
from twin.web import create_app
from twin.web.jobs import PersonaProcessing


def abstained(db: Path, question: str, previous: str = "") -> None:
    reply = ChatReply(
        reply="这得问我本人", citations=[], confidence=0.1, abstain=True, abstain_reason="资料里没有", retrieved_ids=[]
    )
    with PersonaStore(db) as store:
        store.log_chat(question, reply, previous)


@pytest.fixture
def web(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[TestClient, Path]]:
    # Processing stays queued: the timer that would start a build never fires.
    monkeypatch.setattr(PersonaProcessing, "_timer", staticmethod(lambda delay, fn: threading.Timer(3600, fn)))
    settings = Settings(target_name="张总", db_path=tmp_path / "persona.db")
    llm = FakeLLM(lambda *_: pytest.fail("answering a question calls no model"))
    app = create_app(settings, llm_factory=lambda: llm, embedder_factory=HashingEmbedder)
    with TestClient(app, base_url="http://127.0.0.1", headers={"X-Twin": "1"}) as client:
        yield client, settings.db_path


def test_answer_turns_the_question_into_a_memory_and_queues_processing(web: tuple[TestClient, Path]) -> None:
    client, db = web
    assert client.get("/api/persona/followups").json() == {"items": [], "pending": 0}
    abstained(db, "你怎么看远岚的报价？")
    abstained(db, "你怎么看远岚的报价", previous="上周经营会你在吗")
    abstained(db, "你几点睡？")
    queue = client.get("/api/persona/followups").json()
    assert queue["pending"] == 2
    latest, price = queue["items"]
    assert latest["question"] == "你几点睡？"
    assert price["asked"] == 2 and price["previous"] == "上周经营会你在吗" and price["reason"] == "资料里没有"

    url = f"/api/persona/followups/{price['followup_id']}"
    assert client.post(f"{url}/answer", json={"text": ""}).status_code == 400
    assert client.post(f"{url}/answer", json={"text": "   "}).status_code == 400
    assert client.post("/api/persona/followups/nope/answer", json={"text": "好"}).status_code == 404
    done = client.post(f"{url}/answer", json={"text": "报价只认实施费打包，不单列。"}).json()
    assert done["followup"]["status"] == "answered" and done["source_title"] == "回答：你怎么看远岚的报价"

    sources = client.get("/api/persona/sources").json()["items"]
    (source,) = [s for s in sources if s["source_id"] == done["source_id"]]
    assert source["kind_label"] == "访谈" and source["evidence_class"] == "self_report"
    assert client.get("/api/persona/processing").json()["state"] == "queued"
    after = client.get("/api/persona/followups").json()
    assert after["pending"] == 1 and [f["status"] for f in after["items"]] == ["pending", "answered"]

    # Deleting the answer puts the question back.
    assert client.delete(f"/api/persona/sources/{done['source_id']}").status_code == 200
    assert client.get("/api/persona/followups").json()["pending"] == 2


def test_set_aside_and_put_back(web: tuple[TestClient, Path]) -> None:
    client, db = web
    abstained(db, "你家住哪？")
    (item,) = client.get("/api/persona/followups").json()["items"]
    url = f"/api/persona/followups/{item['followup_id']}/status"
    assert client.post(url, json={"status": "dismissed"}).json()["status"] == "dismissed"
    assert client.get("/api/persona/followups").json()["pending"] == 0
    assert client.post(url, json={"status": "answered"}).status_code == 400
    assert client.post(url, json={"status": "pending"}).json()["status"] == "pending"
    assert client.post("/api/persona/followups/nope/status", json={"status": "pending"}).status_code == 404
