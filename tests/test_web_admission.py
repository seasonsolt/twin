"""Admission of chats and requests: streamed chats share the chat limits with chat jobs, a rejected chat saves nothing,
and waiting on a lock never stalls the event loop."""

from __future__ import annotations

import asyncio
import datetime as dt
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_chat_streaming import StreamingLLM, parse_events, seed

from twin.config import Settings
from twin.embed import HashingEmbedder
from twin.media.tts import SilentSynthesizer
from twin.persona import chat as pc
from twin.persona.items import PersonaItem, PEvidence
from twin.persona.profile import chunks_for, consented_facets, corpus_chunks, pending_chunks
from twin.persona.schema import EvidenceClass, SourceKind
from twin.persona.sources import parse_chat, pseudonym
from twin.persona.store import PersonaStore
from twin.web import create_app, jobs, personas
from twin.web.jobs import JobManager, Slots, TooManyJobs, describe_error

HEADERS = {"X-Twin": "1"}
QUESTION = [{"role": "user", "content": "问题"}]
SPEECH = {"citations": [], "confidence": 0.8, "abstain": False, "abstain_reason": "", "retrieved_ids": []}


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
        pc.index_persona(store, HashingEmbedder(), Settings())
        chat = pc.PersonaChat(store, StreamingLLM(lambda *_: {}), HashingEmbedder(), Settings())
        chat.retrieve("上周六怎么安排？", hints="回款", alternatives=["数据", "核对", "计划"])
    assert len(loads) == len(set(loads)) and {pc.ITEMS_NS, pc.EXPRESSIONS_NS} <= set(loads)


CHAT = "\n".join(
    f"2026-09-0{day} 10:{minute:02d} {'张三' if minute % 2 else '李四'}：第{day}天第{minute}句，李四说先核对数据再决定"
    for day in range(1, 4)
    for minute in range(40)
)


def corpus(path: Path, settings: Settings) -> None:
    with PersonaStore(path) as store:
        for day in range(1, 4):
            store.put_source(parse_chat(f"chat{day}.txt", CHAT.replace("第", f"{day}号第"), settings))


def count_corpus_reads(monkeypatch: pytest.MonkeyPatch, reads: list[None]) -> None:
    """Each read of the expressions, alone or with their sources, adds to ``reads``."""
    for name in ("list_expressions", "read_corpus"):
        original = getattr(PersonaStore, name)

        def counted(self: PersonaStore, *args: Any, _original: Any = original, **kwargs: Any) -> Any:
            reads.append(None)
            return _original(self, *args, **kwargs)

        monkeypatch.setattr(PersonaStore, name, counted)


def test_pending_chunks_read_the_corpus_once_with_the_same_chunks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(target_name="张三", pseudonymize_others=True)
    corpus(tmp_path / "twin.db", settings)
    reads: list[None] = []
    with PersonaStore(tmp_path / "twin.db") as store:
        allowed = consented_facets(store)
        sources = store.list_sources()
        one_by_one = [c for s in sources for c in chunks_for(store, s, allowed, settings)]
        count_corpus_reads(monkeypatch, reads)
        together = corpus_chunks(store, sources, allowed, settings)
        assert len(reads) == 1
        assert [(c.chunk_id, c.text) for c in together] == [(c.chunk_id, c.text) for c in one_by_one]
        assert len(together) >= 3 and pseudonym("李四") in together[0].text
        reads.clear()
        assert pending_chunks(store, settings) == len(together)
        assert len(reads) == 1


def test_retrieval_reads_the_corpus_once_and_no_expression_one_by_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(target_name="张三", pseudonymize_others=True)
    corpus(tmp_path / "twin.db", settings)
    with PersonaStore(tmp_path / "twin.db") as store:
        said = next(e for e in store.list_expressions() if e.is_target)
        evidence = PEvidence(
            expression_id=said.expression_id,
            source_id=said.source_id,
            source_kind=SourceKind.CHAT,
            evidence_class=EvidenceClass.SELF_REPORT,
            quote="李四说先核对数据",
        )
        store.replace_facet_items(
            "2.1", [PersonaItem(item_id="pi_q", facet_id="2.1", statement="先核对", evidence=[evidence])]
        )
        reads: list[None] = []
        count_corpus_reads(monkeypatch, reads)
        monkeypatch.setattr(PersonaStore, "get_expression", lambda *_: pytest.fail("read one by one"))
        ctx = pc.PersonaChat(store, StreamingLLM(lambda *_: {}), HashingEmbedder(), settings).retrieve("核对数据")
    assert len(reads) == 1
    quoted = [ev.quote for item, _ in ctx.items for ev in item.evidence] + [
        ev.quote for i in ctx.core for ev in i.evidence
    ]
    assert quoted and all("李四" not in quote and pseudonym("李四") in quote for quote in quoted)


def test_streamed_chats_use_the_store_off_the_event_loop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(db_path=tmp_path / "twin.db")
    seed(settings.db_path)
    on_loop: list[str] = []
    for name in (
        "__init__",
        "list_items",
        "get_meta",
        "list_expressions",
        "read_corpus",
        "append_conversation_turn",
        "log_chat",
    ):
        original = getattr(PersonaStore, name)

        def watched(self: PersonaStore, *args: Any, _name: str = name, _original: Any = original, **kwargs: Any) -> Any:
            try:
                asyncio.get_running_loop()
                on_loop.append(_name)
            except RuntimeError:
                pass
            return _original(self, *args, **kwargs)

        monkeypatch.setattr(PersonaStore, name, watched)
    app = create_app(settings, llm_factory=lambda: StreamingLLM(lambda *_: {}), embedder_factory=HashingEmbedder)
    with TestClient(app, base_url="http://localhost") as web:
        on_loop.clear()  # Startup checks the kernel once; requests are what other requests wait behind.
        cid = web.post("/api/conversations", headers=HEADERS).json()["id"]
        body = {"conversation_id": cid, "messages": QUESTION}
        assert parse_events(web.post("/api/persona/chat/stream", json=body, headers=HEADERS))[-1][0] == "final"
        assert [turn["role"] for turn in turns(web, cid)] == ["user", "twin"]
    assert on_loop == []


def test_requests_open_a_persona_database_only_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app = create_app(Settings(db_path=tmp_path / "twin.db"), embedder_factory=HashingEmbedder)
    with TestClient(app, base_url="http://localhost") as web:
        other = web.post("/api/personas", json={"name": "另一位"}, headers=HEADERS).json()["id"]
        persona = {**HEADERS, "X-Twin-Persona": other}
        assert web.get("/api/persona/state", headers=persona).status_code == 200
        monkeypatch.setattr(personas, "stored_identity", lambda *_: pytest.fail("read on every request"))
        assert web.get("/api/persona/state", headers=persona).status_code == 200


def test_listing_personas_reads_their_files_without_the_registry_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = create_app(Settings(db_path=tmp_path / "twin.db"), embedder_factory=HashingEmbedder)
    registry = app.state.personas
    view, rmtree = personas.Personas._view, personas.shutil.rmtree
    removed: list[str] = []

    def unlocked_view(self: personas.Personas, *args: Any) -> Any:
        assert not self.lock._is_owned()
        return view(self, *args)

    def unlocked_rmtree(path: Path, *args: Any, **kwargs: Any) -> None:
        assert not registry.lock._is_owned()
        removed.append(Path(path).name)
        rmtree(path, *args, **kwargs)

    with TestClient(app, base_url="http://localhost") as web:
        gone = web.post("/api/personas", json={"name": "旧的"}, headers=HEADERS).json()["id"]
        kept = web.post("/api/personas", json={"name": "留下"}, headers=HEADERS).json()["id"]
        assert web.delete(f"/api/personas/{gone}", headers=HEADERS).status_code == 200
        monkeypatch.setattr(personas.Personas, "_view", unlocked_view)
        monkeypatch.setattr(personas.shutil, "rmtree", unlocked_rmtree)
        registry.clock = lambda: dt.datetime.now(dt.UTC) + dt.timedelta(days=8)
        listed = web.get("/api/personas", headers=HEADERS).json()
        assert {p["id"] for p in listed} == {"default", kept}
        assert len(removed) == 1 and removed[0].startswith(gone)

        # A persona whose files are being read cannot be deleted meanwhile: reading it after its directory moved to
        # the trash would create its database again and block restoring it.
        refused: list[int] = []

        def delete_meanwhile(self: personas.Personas, entry: dict[str, Any], *args: Any) -> Any:
            if entry["id"] == kept:
                refused.append(web.delete(f"/api/personas/{kept}", headers=HEADERS).status_code)
            return view(self, entry, *args)

        monkeypatch.setattr(personas.Personas, "_view", delete_meanwhile)
        assert {p["id"] for p in web.get("/api/personas", headers=HEADERS).json()} == {"default", kept}
        assert refused == [409] and registry.in_flight(kept) == 0

        # One already being deleted is left out of the listing.
        registry.removing.add(kept)
        assert [p["id"] for p in web.get("/api/personas", headers=HEADERS).json()] == ["default"]
        registry.removing.discard(kept)

        def broken(self: personas.Personas, entry: dict[str, Any], *args: Any) -> Any:
            if entry["id"] == kept:
                raise sqlite3.OperationalError("disk I/O error")
            return view(self, entry, *args)

        monkeypatch.setattr(personas.Personas, "_view", broken)
        with pytest.raises(sqlite3.OperationalError):
            web.get("/api/personas", headers=HEADERS)


def test_speech_is_queued_for_shared_workers_and_refused_when_the_queue_is_full(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = create_app(Settings(db_path=tmp_path / "twin.db"), synthesizer_factory=SilentSynthesizer)
    manager = app.state.personas.jobs
    body = {"kind": "chat_reply", "answer": {**SPEECH, "reply": "先核对资料。"}, "persona_name": "合成人物"}
    with TestClient(app, base_url="http://localhost") as web:
        assert web.post("/api/media/audio", json=body, headers=HEADERS).status_code == 200
        assert web.post("/api/media/audio/stream", json=body, headers=HEADERS).status_code == 200
        assert manager._speech == [0] and manager._speech_slots._free == jobs.SPEECH_WORKERS
        monkeypatch.setattr(jobs, "MAX_PENDING_SPEECH", 0)
        for path in ("/api/media/audio", "/api/media/audio/stream", "/api/media/clip"):
            assert web.post(path, json=body, headers=HEADERS).status_code == 429
        assert manager._speech == [0]
