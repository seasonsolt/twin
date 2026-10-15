"""Disconnect cleanup keeps workers alive, and admission never holds a lock while writing input."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

import httpx
import pytest
from starlette.requests import ClientDisconnect
from starlette.types import Message, Scope
from test_chat_streaming import StreamingLLM, seed

from twin.config import Settings
from twin.embed import HashingEmbedder
from twin.persona.chat import PersonaChat, open_store_off_loop
from twin.persona.store import PersonaStore
from twin.web import create_app, persona
from twin.web.jobs import AdmittedStream, JobConflict, JobManager, TooManyJobs, describe_error

HEADERS = {"X-Twin": "1"}
BODY = {"messages": [{"role": "user", "content": "问题"}]}


@pytest.mark.parametrize("phase", ["_search", "_derive", "_finalize"])
def test_disconnect_drains_the_worker_before_closing_the_store_and_releasing_admission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    settings = Settings(db_path=tmp_path / "twin.db", max_workers=1)
    seed(settings.db_path)
    app = create_app(settings, llm_factory=lambda: StreamingLLM(lambda *_: {}), embedder_factory=HashingEmbedder)
    manager = app.state.personas.jobs
    started, release = threading.Event(), threading.Event()
    errors: list[Exception] = []
    original = getattr(PersonaChat, phase)

    def blocked(self: PersonaChat, *args: Any, **kwargs: Any) -> Any:
        started.set()
        try:
            assert release.wait(5)
            self.store.get_meta("built_at")  # The store must still be open after the browser disconnects.
            return original(self, *args, **kwargs)
        except Exception as error:
            errors.append(error)
            raise

    monkeypatch.setattr(PersonaChat, phase, blocked)

    async def run() -> None:
        disconnected, delivered = asyncio.Event(), asyncio.Event()
        sent_body = False
        scope: Scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "scheme": "http",
            "method": "POST",
            "path": "/api/persona/chat/stream",
            "root_path": "",
            "query_string": b"",
            "server": ("localhost", 80),
            "client": ("127.0.0.1", 1234),
            "headers": [(b"host", b"localhost"), (b"content-type", b"application/json"), (b"x-twin", b"1")],
        }

        async def receive() -> Message:
            nonlocal sent_body
            if not sent_body:
                sent_body = True
                return {"type": "http.request", "body": json.dumps(BODY).encode(), "more_body": False}
            await disconnected.wait()
            delivered.set()
            return {"type": "http.disconnect"}

        async def send(message: Message) -> None:
            pass

        request = asyncio.create_task(app(scope, receive, send))
        job = None
        queued = threading.Event()
        try:
            assert await asyncio.to_thread(started.wait, 3)
            disconnected.set()
            await asyncio.wait_for(delivered.wait(), 1)
            await asyncio.sleep(0.02)
            assert not request.done()
            assert manager._streams == [1]
            assert manager._answer_slots._free == 0
            job = manager.submit("chat", "queued", lambda log: queued.set())
            assert not await asyncio.to_thread(queued.wait, 0.05)
        finally:
            release.set()
            await asyncio.wait_for(request, 3)
            if job is not None:
                assert await asyncio.to_thread(manager.wait, job.job_id, 3)
        assert errors == []
        assert manager._streams == [0] and manager._answer_slots._free == 1
        assert app.state.personas.in_flight("default") == 0

    asyncio.run(run())


def test_failed_send_closes_the_suspended_iterator_before_releasing_admission() -> None:
    manager = JobManager(1, describe_error)

    async def run() -> None:
        ticket = manager.admit_stream()
        closed = asyncio.Event()

        async def content() -> Any:
            try:
                async with ticket.running():
                    yield "synthetic"
            finally:
                closed.set()

        async def receive() -> Message:
            raise AssertionError("ASGI 2.4 handles disconnects through send")

        async def send(message: Message) -> None:
            if message["type"] == "http.response.body":
                raise OSError("client disconnected")

        response = AdmittedStream(content(), ticket)
        with pytest.raises(ClientDisconnect):
            await response({"type": "http", "asgi": {"spec_version": "2.4"}}, receive, send)
        assert closed.is_set()
        assert manager._streams == [0] and manager._answer_slots._free == 1

    asyncio.run(run())


def test_sqlite_acceptance_does_not_block_a_stream_finishing_or_other_requests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(db_path=tmp_path / "twin.db", max_workers=1)
    seed(settings.db_path)
    with PersonaStore(settings.db_path) as store:
        cid = store.create_conversation(None)
    app = create_app(settings, llm_factory=lambda: StreamingLLM(lambda *_: {}), embedder_factory=HashingEmbedder)
    entered = threading.Event()
    original = persona.append_user

    def accepting(*args: Any, **kwargs: Any) -> None:
        entered.set()
        original(*args, **kwargs)

    monkeypatch.setattr(persona, "run_chat", lambda *args: {})

    async def run() -> None:
        started, finish = asyncio.Event(), asyncio.Event()

        async def stream(self: PersonaChat, *args: Any, **kwargs: Any) -> Any:
            started.set()
            await finish.wait()
            yield "synthetic"

        monkeypatch.setattr(PersonaChat, "stream_reply", stream)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://localhost", headers=HEADERS
        ) as client:
            streaming = asyncio.create_task(client.post("/api/persona/chat/stream", json=BODY))
            await asyncio.wait_for(started.wait(), 3)
            writer = sqlite3.connect(settings.db_path, check_same_thread=False)
            writer.execute("BEGIN IMMEDIATE")
            # A regression must fail without hanging the event loop for SQLite's full five-second busy timeout.
            emergency = threading.Timer(2, writer.rollback)
            emergency.start()
            chat = None
            try:
                monkeypatch.setattr(persona, "append_user", accepting)
                chat = asyncio.create_task(client.post("/api/persona/chat", json={**BODY, "conversation_id": cid}))
                assert await asyncio.to_thread(entered.wait, 3)
                before = time.monotonic()
                finish.set()
                response = await asyncio.wait_for(streaming, 1)
                assert response.status_code == 200
                assert (await client.get("/api/whoami")).status_code == 200
                assert time.monotonic() - before < 1
                assert not chat.done()
            finally:
                emergency.cancel()
                emergency.join(3)
                writer.rollback()
                writer.close()
                await streaming
                if chat is not None:
                    assert (await chat).status_code == 202
            with PersonaStore(settings.db_path) as store:
                assert [turn["role"] for turn in store.get_conversation(cid, None)["turns"]] == ["user"]

    asyncio.run(run())


@pytest.mark.parametrize("kind", ["chat", "persona_build"])
def test_preparation_reserves_admission_and_rolls_it_back_on_failure(
    monkeypatch: pytest.MonkeyPatch, kind: Any
) -> None:
    monkeypatch.setattr("twin.web.jobs.MAX_PENDING_ANSWERS", 1)
    manager = JobManager(1, describe_error)
    entered, release = threading.Event(), threading.Event()
    errors: list[Exception] = []

    def prepare(job: Any) -> None:
        entered.set()
        assert release.wait(3)
        raise ValueError("synthetic preparation failure")

    def submit() -> None:
        try:
            manager.submit(kind, "preparing", lambda log: pytest.fail("worker ran before preparation"), prepare=prepare)
        except Exception as error:
            errors.append(error)

    submitting = threading.Thread(target=submit)
    submitting.start()
    try:
        assert entered.wait(3)
        assert manager.has_active("default")
        if kind == "chat":
            with pytest.raises(TooManyJobs):
                manager.admit_stream()
        else:
            with pytest.raises(JobConflict):
                manager.submit("persona_build", "conflicting", lambda log: None)
    finally:
        release.set()
        submitting.join(3)
    assert len(errors) == 1 and isinstance(errors[0], ValueError)
    assert not manager.has_active("default") and manager.recent() == []
    assert manager.active_exclusive() is None
    job = manager.submit(kind, "accepted", lambda log: "done")
    assert manager.wait(job.job_id, 3)
    assert manager.snapshot(job.job_id)["status"] == "done"


def test_a_store_opened_for_a_cancelled_caller_is_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    opening, release = threading.Event(), threading.Event()
    closed: list[PersonaStore] = []
    init, close = PersonaStore.__init__, PersonaStore.close

    def slow_init(self: PersonaStore, path: Path | str) -> None:
        opening.set()
        release.wait(5)
        init(self, path)

    def counted_close(self: PersonaStore) -> None:
        closed.append(self)
        close(self)

    monkeypatch.setattr(PersonaStore, "__init__", slow_init)
    monkeypatch.setattr(PersonaStore, "close", counted_close)

    async def scenario() -> None:
        task = asyncio.create_task(open_store_off_loop(tmp_path / "twin.db"))
        await asyncio.to_thread(opening.wait, 5)
        task.cancel()
        await asyncio.sleep(0)
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert len(closed) == 1
