from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import openai
import pytest
from fastapi.testclient import TestClient

from twin.config import LLMSettings, Settings
from twin.embed import HashingEmbedder
from twin.llm import FakeLLM, OpenAICompatLLM, hedged_stream
from twin.persona.chat import ChatStreamParser, PersonaChat, chat_system_prompt, index_persona
from twin.persona.items import PersonaItem
from twin.persona.store import PersonaStore
from twin.web import create_app

META = {
    "citations": ["pi_test", "invalid"],
    "confidence": 0.9,
    "mode": "grounded",
    "abstain": False,
    "abstain_reason": "",
    "topic_facets": ["2.1", "bad"],
}
BODY = "先“核对数据”。\n<<<META>>>\n" + json.dumps(META, ensure_ascii=False)


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_parser_all_chunk_boundaries(newline: str) -> None:
    body = BODY.replace("\n", newline)
    for split in range(len(body) + 1):
        parser = ChatStreamParser()
        visible = parser.feed(body[:split]) + parser.feed(body[split:]) + parser.finish()
        assert visible == "先“核对数据”。" + newline
        assert parser.draft().reply == "先“核对数据”。"
        assert parser.draft().citations == META["citations"]
    parser = ChatStreamParser()
    visible = "".join(parser.feed(ch) for ch in body) + parser.finish()
    assert "META" not in visible and "citations" not in visible


@pytest.mark.parametrize(
    "body,visible",
    [
        ("回答正文", "回答正文"),
        ("回答\n<<<ME", "回答\n<<<ME"),
        ("回答\n<<<META>>>\n{broken", "回答\n"),
        ("回答\n<<<META>>>\n[]", "回答\n"),
        ('回答\n<<<META>>>\n{"confidence":NaN,"citations":[],"mode":"grounded"}', "回答\n"),
        ("回答\n<<<META>>>", "回答\n"),
        ("正文提到 <<<META>>> 不是分隔符", "正文提到 <<<META>>> 不是分隔符"),
    ],
)
def test_parser_conservative_fallback_keeps_text(body: str, visible: str) -> None:
    parser = ChatStreamParser()
    assert parser.feed(body) + parser.finish() == visible
    draft = parser.draft()
    assert draft.reply == visible
    assert draft.abstain and draft.confidence == 0 and draft.citations == []


@pytest.mark.parametrize(
    "delays,hedge,expected,calls",
    [
        ([0.1, 0.001], 0.02, "1", 2),
        ([0.025, 0.1], 0.02, "0", 2),
        ([0.001], 0.02, "0", 1),
        ([0.03], 0, "0", 1),
    ],
)
def test_hedge_first_token_and_loser_closed(delays: list[float], hedge: float, expected: str, calls: int) -> None:
    async def run() -> None:
        opened: list[int] = []
        closed: list[int] = []
        starts: list[float] = []

        async def stream(index: int) -> AsyncIterator[str]:
            opened.append(index)
            starts.append(time.monotonic())
            try:
                yield ""
                await asyncio.sleep(delays[index])
                yield str(index)
                yield "end"
            finally:
                closed.append(index)

        def factory() -> AsyncIterator[str]:
            return stream(len(opened))

        output = [chunk async for chunk in hedged_stream(factory, hedge)]
        assert output == [expected, "end"]
        assert len(opened) == calls and sorted(closed) == list(range(calls))
        if calls == 2:
            assert starts[1] - starts[0] >= hedge * 0.9

    asyncio.run(run())


def test_hedge_preserves_arrival_order_when_both_tasks_are_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    original_wait = asyncio.wait

    async def delayed_wait(*args: Any, **kwargs: Any) -> Any:
        if len(args[0]) == 2:
            await asyncio.sleep(0.04)
        return await original_wait(*args, **kwargs)

    monkeypatch.setattr(asyncio, "wait", delayed_wait)

    async def run() -> None:
        started = 0

        async def stream(index: int) -> AsyncIterator[str]:
            await asyncio.sleep(0.03 if index == 0 else 0.001)
            yield str(index)

        def factory() -> AsyncIterator[str]:
            nonlocal started
            result = stream(started)
            started += 1
            return result

        assert [text async for text in hedged_stream(factory, 0.01)] == ["1"]

    asyncio.run(run())


def test_hedge_closes_on_disconnect() -> None:
    async def run() -> None:
        closed = asyncio.Event()

        async def stream() -> AsyncIterator[str]:
            try:
                yield "first"
                await asyncio.sleep(60)
            finally:
                closed.set()

        chunks = hedged_stream(stream, 0.02)
        assert await anext(chunks) == "first"
        await chunks.aclose()
        assert closed.is_set()

    asyncio.run(run())


def test_openai_stream_plain_text_extra_body_and_close() -> None:
    bodies: list[dict[str, Any]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        chunks = [
            {
                "id": "test",
                "created": 0,
                "model": "chat",
                "object": "chat.completion.chunk",
                "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}],
            }
            for text in ["回", "答"]
        ]
        content = "".join("data: " + json.dumps(chunk) + "\n\n" for chunk in chunks) + "data: [DONE]\n\n"
        return httpx.Response(200, text=content, headers={"Content-Type": "text/event-stream"})

    async def run() -> None:
        async with (
            httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http,
            openai.AsyncOpenAI(api_key="test", http_client=http) as client,
        ):
            llm = OpenAICompatLLM(
                "chat",
                async_client=client,
                extra_body={"thinking": {"type": "disabled"}},
                reasoning_effort="none",
                json_mode="json_object",
            )
            assert [text async for text in llm.stream(system="stable", user="question")] == ["回", "答"]

    asyncio.run(run())
    assert len(bodies) == 1
    assert bodies[0]["stream"] is True and "response_format" not in bodies[0]
    assert bodies[0]["thinking"] == {"type": "disabled"} and bodies[0]["reasoning_effort"] == "none"


class StreamingLLM(FakeLLM):
    async def stream(self, **kwargs: Any) -> AsyncIterator[str]:
        assert "<<<META>>>" in kwargs["system"]
        self.calls.append(("stream", kwargs["system"], kwargs["user"]))
        for chunk in [BODY[:2], BODY[2:15], BODY[15:]]:
            yield chunk


def seed(path: Path) -> None:
    with PersonaStore(path) as store:
        store.set_meta("built_at", "2026-01-01")
        store.replace_facet_items(
            "2.1", [PersonaItem(item_id="pi_test", facet_id="2.1", statement="回款优先", evidence=[])]
        )


def parse_events(response: httpx.Response) -> list[tuple[str, dict[str, Any]]]:
    events = []
    for frame in response.text.split("\n\n"):
        if frame.startswith("event:"):
            name, data = frame.split("\n", 1)
            events.append((name[7:], json.loads(data[6:])))
    return events


def test_sse_headers_quote_guard_persistence_and_persona(tmp_path: Path) -> None:
    settings = Settings(db_path=tmp_path / "twin.db", chat_llm=LLMSettings(hedge_after_s=0))
    seed(settings.db_path)
    llm = StreamingLLM(lambda *_: {})
    app = create_app(settings, llm_factory=lambda: llm, embedder_factory=HashingEmbedder)
    body = {"messages": [{"role": "user", "content": "怎么看？"}]}
    with TestClient(app, base_url="http://localhost") as web:
        assert web.post("/api/persona/chat/stream", json=body).status_code == 403
        assert (
            web.post(
                "/api/persona/chat/stream", json=body, headers={"X-Twin": "1", "X-Twin-Persona": "missing"}
            ).status_code
            == 404
        )
        response = web.post("/api/persona/chat/stream", json=body, headers={"X-Twin": "1"})
        assert response.status_code == 200 and response.text.startswith(": connected\n\n")
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["cache-control"] == "no-cache"
        assert response.headers["x-accel-buffering"] == "no"
        assert response.headers["x-content-type-options"] == "nosniff"
        events = parse_events(response)
        assert all(name == "delta" for name, _ in events[:-1]) and events[-1][0] == "final"
        assert "".join(data["text"] for _, data in events[:-1]) == "先“核对数据”。\n"
        final = events[-1][1]
        assert final["reply"] == "先核对数据。" and final["quotes_removed"] == 1
        assert final["citations"] == ["pi_test"] and final["confidence"] == 0.6
        assert final["topic_facets"] == ["2.1"] and final["cited"][0]["text"] == "回款优先"
        with PersonaStore(settings.db_path) as store:
            entries = store._db.execute("SELECT json FROM p_chat_log").fetchall()
            assert len(entries) == 1
            assert json.loads(entries[0][0]) == {
                "question": "怎么看？",
                "mode": "grounded",
                "abstain": False,
                "confidence": 0.6,
                "topic_facets": ["2.1"],
                "as_of": None,
            }
        other = web.post("/api/personas", json={"name": "另一位"}, headers={"X-Twin": "1"}).json()["id"]
        empty = web.post("/api/persona/chat/stream", json=body, headers={"X-Twin": "1", "X-Twin-Persona": other})
        assert parse_events(empty)[-1][1]["abstain"] and len(llm.calls) == 1
        assert (
            web.post(
                "/api/persona/chat/stream",
                headers={"X-Twin": "1"},
                json={"messages": [{"role": "twin", "content": "x"}]},
            ).status_code
            == 400
        )


@pytest.mark.parametrize("body", ["保留完整回复。", "保留完整回复。\n<<<META>>>\n{broken"])
def test_sse_invalid_metadata_keeps_text_and_logs_once(tmp_path: Path, body: str) -> None:
    settings = Settings(db_path=tmp_path / "twin.db")
    seed(settings.db_path)

    class BrokenMetadataLLM(StreamingLLM):
        async def stream(self, **kwargs: Any) -> AsyncIterator[str]:
            yield body

    llm = BrokenMetadataLLM(lambda *_: pytest.fail("must not regenerate the streamed reply"))
    with TestClient(
        create_app(settings, llm_factory=lambda: llm, embedder_factory=HashingEmbedder), base_url="http://localhost"
    ) as web:
        response = web.post(
            "/api/persona/chat/stream",
            headers={"X-Twin": "1"},
            json={"messages": [{"role": "user", "content": "问题"}]},
        )
        events = parse_events(response)
        final = events[-1][1]
        assert events[-1][0] == "final"
        assert final["reply"].startswith("保留完整回复。") and final["citations"] == []
        assert final["confidence"] == 0 and final["mode"] == "abstain" and final["abstain"]
        with PersonaStore(settings.db_path) as store:
            assert store._db.execute("SELECT COUNT(*) FROM p_chat_log").fetchone()[0] == 1


def test_sse_error_is_sanitized(tmp_path: Path) -> None:
    settings = Settings(db_path=tmp_path / "twin.db")
    seed(settings.db_path)
    llm = FakeLLM(lambda *_: (_ for _ in ()).throw(RuntimeError("secret prompt")))
    with TestClient(
        create_app(settings, llm_factory=lambda: llm, embedder_factory=HashingEmbedder), base_url="http://localhost"
    ) as web:
        response = web.post(
            "/api/persona/chat/stream",
            headers={"X-Twin": "1"},
            json={"messages": [{"role": "user", "content": "问题"}]},
        )
        assert parse_events(response) == [("error", {"detail": "分身暂时无法回复，请重试"})]
        assert "secret" not in response.text


def test_sse_heartbeat_while_waiting_for_tokens(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(db_path=tmp_path / "twin.db", llm=LLMSettings(hedge_after_s=0))
    seed(settings.db_path)
    original_wait = asyncio.wait

    async def quick_wait(*args: Any, **kwargs: Any) -> Any:
        if kwargs.get("timeout") == 10:
            kwargs["timeout"] = 0.005
        return await original_wait(*args, **kwargs)

    class SlowLLM(StreamingLLM):
        async def stream(self, **kwargs: Any) -> AsyncIterator[str]:
            await asyncio.sleep(0.03)
            async for chunk in super().stream(**kwargs):
                yield chunk

    monkeypatch.setattr(asyncio, "wait", quick_wait)
    llm = SlowLLM(lambda *_: {})
    with TestClient(
        create_app(settings, llm_factory=lambda: llm, embedder_factory=HashingEmbedder), base_url="http://localhost"
    ) as web:
        response = web.post(
            "/api/persona/chat/stream",
            headers={"X-Twin": "1"},
            json={"messages": [{"role": "user", "content": "问题"}]},
        )
        assert response.text.startswith(": connected\n\n")
        assert ": heartbeat\n\n" in response.text
        assert parse_events(response)[-1][0] == "final"


def test_system_prompt_stable_across_retrieval(tmp_path: Path) -> None:
    settings = Settings(db_path=tmp_path / "twin.db")
    seed(settings.db_path)
    with PersonaStore(settings.db_path) as store:
        embedder = HashingEmbedder()
        index_persona(store, embedder, settings)
        chat = PersonaChat(store, FakeLLM(lambda *_: {}), embedder, settings)
        contexts = [chat.retrieve(question) for question in ["回款", "完全不同的问题"]]
        assert all(context.core for context in contexts)
        assert chat_system_prompt("本人", contexts[0]) == chat_system_prompt("本人", contexts[1])
