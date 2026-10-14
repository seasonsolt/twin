"""Admission of chats and requests: streamed chats share the chat limits with chat jobs, a rejected chat saves nothing,
and waiting on a lock never stalls the event loop."""

from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_chat_streaming import StreamingLLM, parse_events, seed

from twin.config import Settings
from twin.embed import HashingEmbedder
from twin.persona import chat as pc
from twin.persona.store import PersonaStore
from twin.web import create_app, jobs
from twin.web.jobs import JobManager, Slots, TooManyJobs, describe_error

HEADERS = {"X-Twin": "1"}
QUESTION = [{"role": "user", "content": "问题"}]


def test_slots_are_handed_over_in_arrival_order_to_threads_and_coroutines() -> None:
    slots = Slots(1)
    slots.acquire()
    order: list[str] = []

    async def run() -> None:
        thread = threading.Thread(target=lambda: (slots.acquire(), order.append("thread"), slots.release()))
        thread.start()
        while not slots._waiters:
            await asyncio.sleep(0.001)
        waiting = asyncio.create_task(slots.acquire_async())
        await asyncio.sleep(0.01)
        slots.release()
        await waiting
        order.append("coroutine")
        slots.release()
        await asyncio.to_thread(thread.join, 5)

    asyncio.run(run())
    assert order == ["thread", "coroutine"]
    assert slots._free == 1 and not slots._waiters


def test_a_cancelled_coroutine_passes_its_slot_on() -> None:
    async def run() -> None:
        slots = Slots(1)
        await slots.acquire_async()
        first = asyncio.create_task(slots.acquire_async())
        second = asyncio.create_task(slots.acquire_async())
        await asyncio.sleep(0.01)
        # Granted and cancelled in the same loop turn: the slot must reach the next waiter, not vanish.
        slots.release()
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        await asyncio.wait_for(second, 1)
        slots.release()
        # Cancelled before any grant: it simply leaves the queue.
        await slots.acquire_async()
        third = asyncio.create_task(slots.acquire_async())
        await asyncio.sleep(0.01)
        third.cancel()
        with pytest.raises(asyncio.CancelledError):
            await third
        slots.release()
        assert slots._free == 1 and not slots._waiters

    asyncio.run(run())


def test_streams_count_against_the_pending_limit_and_hold_a_chat_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(jobs, "MAX_PENDING_ANSWERS", 2)
    manager = JobManager(1, describe_error)
    ran = threading.Event()

    async def run() -> None:
        ticket = manager.admit_stream()
        async with ticket.running():
            job = manager.submit("chat", "聊天", lambda log: ran.set())
            with pytest.raises(TooManyJobs):
                manager.admit_stream()
            # The only chat worker is the stream's, so the job waits for it.
            assert not await asyncio.to_thread(ran.wait, 0.05)
        assert await asyncio.to_thread(ran.wait, 5)
        assert await asyncio.to_thread(manager.wait, job.job_id, 5)
        ticket.close()
        ticket.close()
        manager.admit_stream().close()
        manager.admit_stream().close()

    asyncio.run(run())


def turns(web: TestClient, cid: str) -> list[dict[str, Any]]:
    return list(web.get(f"/api/conversations/{cid}").json()["turns"])


@pytest.mark.parametrize("endpoint", ["/api/persona/chat/stream", "/api/persona/chat"])
def test_a_rejected_chat_saves_no_user_turn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, endpoint: str) -> None:
    settings = Settings(db_path=tmp_path / "twin.db")
    seed(settings.db_path)
    broken = {"llm": True}

    def llm() -> StreamingLLM:
        if broken["llm"]:
            raise RuntimeError("no key")
        return StreamingLLM(lambda *_: {})

    app = create_app(settings, llm_factory=llm, embedder_factory=HashingEmbedder)
    with TestClient(app, base_url="http://localhost") as web:
        cid = web.post("/api/conversations", headers=HEADERS).json()["id"]
        body = {"conversation_id": cid, "messages": QUESTION}
        assert web.post(endpoint, json=body, headers=HEADERS).status_code == 503
        assert turns(web, cid) == []
        broken["llm"] = False
        monkeypatch.setattr(jobs, "MAX_PENDING_ANSWERS", 0)
        assert web.post(endpoint, json=body, headers=HEADERS).status_code == 429
        assert turns(web, cid) == []
        monkeypatch.setattr(jobs, "MAX_PENDING_ANSWERS", 20)
        response = web.post(endpoint, json=body, headers=HEADERS)
        assert response.status_code in (200, 202)
        assert turns(web, cid)[0]["content"] == "问题"


def test_a_finished_stream_gives_its_place_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(jobs, "MAX_PENDING_ANSWERS", 1)
    settings = Settings(db_path=tmp_path / "twin.db", max_workers=1)
    seed(settings.db_path)
    app = create_app(settings, llm_factory=lambda: StreamingLLM(lambda *_: {}), embedder_factory=HashingEmbedder)
    with TestClient(app, base_url="http://localhost") as web:
        for _ in range(3):
            response = web.post("/api/persona/chat/stream", json={"messages": QUESTION}, headers=HEADERS)
            assert parse_events(response)[-1][0] == "final"
        # A conversation that does not exist is refused after admission, which must not keep the place either.
        missing = {"conversation_id": "missing", "messages": QUESTION}
        assert web.post("/api/persona/chat/stream", json=missing, headers=HEADERS).status_code == 404
        response = web.post("/api/persona/chat/stream", json={"messages": QUESTION}, headers=HEADERS)
        assert parse_events(response)[-1][0] == "final"


def test_requests_waiting_for_the_persona_registry_do_not_stall_others(tmp_path: Path) -> None:
    app = create_app(Settings(db_path=tmp_path / "twin.db"), embedder_factory=HashingEmbedder)
    registry = app.state.personas
    with TestClient(app, base_url="http://localhost") as web:
        held, release = threading.Event(), threading.Event()

        def hold() -> None:
            with registry.lock:
                held.set()
                release.wait(5)

        holder = threading.Thread(target=hold)
        holder.start()
        assert held.wait(5)
        waiting: list[int] = []
        waiter = threading.Thread(target=lambda: waiting.append(web.get("/api/persona/state").status_code))
        waiter.start()
        try:
            time.sleep(0.05)
            started = time.monotonic()
            assert web.get("/api/whoami").status_code == 200
            assert time.monotonic() - started < 1
            assert not waiting
        finally:
            release.set()
            holder.join(5)
            waiter.join(5)
        assert waiting == [200]
        assert registry.in_flight("default") == 0


def test_retrieval_loads_each_namespace_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seed(tmp_path / "twin.db")
    loads: list[str] = []
    get_vectors = PersonaStore.get_vectors

    def counted(self: PersonaStore, namespace: str) -> Any:
        loads.append(namespace)
        return get_vectors(self, namespace)

    monkeypatch.setattr(PersonaStore, "get_vectors", counted)
    with PersonaStore(tmp_path / "twin.db") as store:
        chat = pc.PersonaChat(store, StreamingLLM(lambda *_: {}), HashingEmbedder(), Settings())
        chat.retrieve("上周六怎么安排？", hints="回款", alternatives=["数据", "核对", "计划"])
    assert len(loads) == len(set(loads)) and {pc.ITEMS_NS, pc.EXPRESSIONS_NS} <= set(loads)
