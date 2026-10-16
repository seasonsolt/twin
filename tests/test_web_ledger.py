from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from twin.config import Settings
from twin.embed import HashingEmbedder
from twin.llm import FakeLLM
from twin.persona.schema import Source, SourceKind
from twin.persona.sources import parse_media
from twin.persona.store import PersonaStore
from twin.web import create_app
from twin.web.jobs import PersonaProcessing

NAME = "张总"
LINES = [
    ("本人", "老王，报价什么时候能好？"),
    ("其他人1", "我周五前给您一版新报价方案。"),
    ("其他人1", "不过实施费单列像变相涨价。"),
]
Handler = Callable[[str, str, type[BaseModel]], dict[str, Any]]


def meeting(db: Path, source_id: str = "m1", day: str = "2026-10-12") -> None:
    source = Source(
        source_id=source_id,
        kind=SourceKind.AUDIO,
        title="经营会",
        origin=f"{source_id}.m4a",
        imported_at="now",
        n_expressions=0,
        n_target=0,
        creation_time=f"{day}T09:00:00",
        media_status="ready",
        text_state="raw",
    )
    lines = [
        (NAME if who == "本人" else who, f"[00:{i:02d}] {text}", who == "本人") for i, (who, text) in enumerate(LINES)
    ]
    with PersonaStore(db) as store:
        store.put_source(parse_media(source, lines))


def extract(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
    assert schema.__name__ == "LedgerDraft", schema
    return {
        "speakers": [{"label": "其他人1", "name": "老王", "basis": "被点名后回答"}],
        "items": [
            {
                "kind": "承诺",
                "line": 2,
                "quote": "我周五前给您一版新报价方案",
                "owner": "老王",
                "counterpart": "本人",
                "what": "周五前给我一版新报价方案",
                "due": "2026-10-16",
                "due_text": "周五前",
                "confidence": 0.9,
            },
            {
                "kind": "异议",
                "line": 3,
                "quote": "实施费单列像变相涨价",
                "owner": "老王",
                "what": "实施费单列像变相涨价",
                "confidence": 0.8,
            },
        ],
    }


@pytest.fixture
def web(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[[Handler], TestClient]]:
    # Profile builds stay queued: the timer that would start them never fires.
    monkeypatch.setattr(PersonaProcessing, "_timer", staticmethod(lambda delay, fn: threading.Timer(3600, fn)))
    settings = Settings(target_name=NAME, db_path=tmp_path / "persona.db")
    clients: list[TestClient] = []

    def make(handler: Handler) -> TestClient:
        app = create_app(settings, llm_factory=lambda: FakeLLM(handler), embedder_factory=HashingEmbedder)
        client = TestClient(app, base_url="http://127.0.0.1", headers={"X-Twin": "1"})
        client.__enter__()
        clients.append(client)
        return client

    yield make
    for client in clients:
        client.__exit__(None, None, None)


def finished(client: TestClient, job_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] not in ("queued", "running"):
            return job
        time.sleep(0.005)
    raise AssertionError("ledger build did not finish")


def test_build_lists_entries_with_status_labels_and_confirmation(
    web: Callable[[Handler], TestClient], tmp_path: Path
) -> None:
    client = web(extract)
    empty = client.get("/api/persona/ledger").json()
    assert empty["entries"] == [] and empty["meetings"] == {"total": 0, "pending": 0} and empty["job_id"] is None
    assert client.post("/api/persona/ledger/build").status_code == 400

    meeting(tmp_path / "persona.db")
    assert client.get("/api/persona/ledger").json()["meetings"] == {"total": 1, "pending": 1}
    started = client.post("/api/persona/ledger/build")
    assert started.status_code == 202
    job = finished(client, started.json()["job_id"])
    assert job["status"] == "done" and job["kind_label"] == "整理承诺账本", job

    data = client.get("/api/persona/ledger").json()
    assert data["meetings"] == {"total": 1, "pending": 0} and data["people"] == ["老王"]
    assert data["status_labels"]["claimed_done"] == "本人称已完成"
    promise, objection = sorted(data["entries"], key=lambda e: e["kind"])
    assert promise["kind_label"] == "承诺" and promise["current_status"] == "open"
    assert promise["current_status_label"] == "进行中" and promise["thread"] == promise["entry_id"]
    assert promise["due"] == "2026-10-16" and promise["quote"] == "我周五前给您一版新报价方案"
    assert promise["confirmation_message"] == (
        "老王，确认一下10月12日经营会上说的：周五前给我一版新报价方案，10月16日前。有出入直接回我。"
    )
    assert objection["kind"] == "objection" and objection["confirmation_message"] is None

    only = client.get("/api/persona/ledger", params={"kind": "commitment", "owner": "老王", "status": "open"}).json()
    assert [e["entry_id"] for e in only["entries"]] == [promise["entry_id"]]
    assert client.get("/api/persona/ledger", params={"status": "not_done"}).json()["entries"] == []
    assert client.get("/api/persona/ledger", params={"kind": "nonsense"}).status_code == 400

    again = client.post("/api/persona/ledger/build")
    assert again.status_code == 202 and again.json() == {"job_id": None, "notice": "所有会议都已整理过"}
    forced = client.post("/api/persona/ledger/build", json={"force": True})
    assert finished(client, forced.json()["job_id"])["status"] == "done"
    assert len(client.get("/api/persona/ledger").json()["entries"]) == 2


def test_review_corrects_rejects_and_resets_entries(web: Callable[[Handler], TestClient], tmp_path: Path) -> None:
    meeting(tmp_path / "persona.db")
    client = web(extract)
    finished(client, client.post("/api/persona/ledger/build").json()["job_id"])
    entries = client.get("/api/persona/ledger", params={"kind": "commitment"}).json()["entries"]
    entry_id = entries[0]["entry_id"]
    url = f"/api/persona/ledger/{entry_id}/review"

    edited = client.post(url, json={"action": "edit", "changes": {"due": "2026-10-17", "status": "claimed_done"}})
    assert edited.status_code == 200
    body = edited.json()
    assert body["review"] == "edited" and body["version"] == 2 and body["due"] == "2026-10-17"
    assert body["current_status_label"] == "本人称已完成" and body["owner"] == "老王"
    cleared = client.post(url, json={"action": "edit", "changes": {"status": None}}).json()
    assert cleared["status"] is None and cleared["current_status"] == "open" and cleared["version"] == 3
    emptied = client.post(url, json={"action": "edit", "changes": {"condition": None, "counterpart": None}}).json()
    assert emptied["condition"] == "" and emptied["counterpart"] == "" and emptied["version"] == 4

    assert client.post(url, json={"action": "edit"}).status_code == 400
    assert client.post(url, json={"action": "edit", "changes": {}}).status_code == 400
    assert client.post(url, json={"action": "edit", "changes": {"owner": None}}).status_code == 400
    assert client.post(url, json={"action": "confirm", "changes": {"what": "别的"}}).status_code == 400
    assert client.post(url, json={"action": "edit", "changes": {"quote": "改引文"}}).status_code == 400
    assert client.post(url, json={"action": "edit", "changes": {"status": "done"}}).status_code == 400
    assert client.post("/api/persona/ledger/nope/review", json={"action": "confirm"}).status_code == 404

    assert client.post(url, json={"action": "reject"}).json()["review"] == "rejected"
    visible = client.get("/api/persona/ledger").json()
    assert entry_id not in [e["entry_id"] for e in visible["entries"]]
    assert entry_id in [
        e["entry_id"] for e in client.get("/api/persona/ledger", params={"include_rejected": True}).json()["entries"]
    ]
    assert client.post(url, json={"action": "reset"}).json()["review"] == "unreviewed"

    # A rebuild replaces unreviewed entries only; the confirmed one survives with its id.
    assert client.post(url, json={"action": "confirm"}).json()["review"] == "confirmed"
    finished(client, client.post("/api/persona/ledger/build", json={"force": True}).json()["job_id"])
    after = client.get("/api/persona/ledger").json()["entries"]
    assert entry_id in [e["entry_id"] for e in after] and len(after) == 2


def test_brief_for_one_person(web: Callable[[Handler], TestClient], tmp_path: Path) -> None:
    meeting(tmp_path / "persona.db")
    client = web(extract)
    finished(client, client.post("/api/persona/ledger/build").json()["job_id"])
    brief = client.get("/api/persona/ledger/brief", params={"person": "老王", "as_of": "2026-10-19"}).json()
    assert brief["person"] == "老王" and brief["as_of"] == "2026-10-19"
    assert [e["kind"] for e in brief["theirs"]] == ["commitment"] and brief["mine"] == []
    assert [e["kind"] for e in brief["objections"]] == ["objection"]
    assert [q["text"] for q in brief["questions"]] == [
        "「周五前给我一版新报价方案」原定10月16日前，现在进展如何？",
        "上次你说「实施费单列像变相涨价」，这个顾虑现在解决了吗？",
    ]
    assert brief["questions"][0]["entry_id"] == brief["theirs"][0]["entry_id"]
    assert client.get("/api/persona/ledger/brief").status_code == 400
    assert client.get("/api/persona/ledger/brief", params={"person": "老王", "as_of": "昨天"}).status_code == 400


def test_a_second_build_waits_for_the_first(web: Callable[[Handler], TestClient], tmp_path: Path) -> None:
    meeting(tmp_path / "persona.db")
    entered, release = threading.Event(), threading.Event()

    def slow(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
        entered.set()
        assert release.wait(5)
        return extract(system, user, schema)

    client = web(slow)
    first = client.post("/api/persona/ledger/build").json()["job_id"]
    assert entered.wait(5)
    assert client.get("/api/persona/ledger").json()["job_id"] == first
    conflict = client.post("/api/persona/ledger/build", json={"force": True})
    assert conflict.status_code == 409 and "整理承诺账本" in conflict.json()["detail"]
    release.set()
    assert finished(client, first)["status"] == "done"
    assert client.get("/api/persona/ledger").json()["job_id"] is None


def test_model_failure_fails_the_job_and_keeps_meetings_pending(
    web: Callable[[Handler], TestClient], tmp_path: Path
) -> None:
    meeting(tmp_path / "persona.db")

    def broken(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
        raise ValueError("模型输出不合格")

    client = web(broken)
    job = finished(client, client.post("/api/persona/ledger/build").json()["job_id"])
    assert job["status"] == "failed" and job["error"].startswith("整理承诺账本失败")
    assert client.get("/api/persona/ledger").json()["meetings"] == {"total": 1, "pending": 1}
