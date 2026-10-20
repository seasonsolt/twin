from __future__ import annotations

import asyncio
import datetime as dt
import json
import sqlite3
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import httpx
import openai
import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from twin import usage
from twin.config import Settings
from twin.llm import OpenAICompatLLM, hedged_stream
from twin.persona.work import _usage_callback
from twin.usage import (
    CallRow,
    UsageLedger,
    UsageRecorder,
    call_stage,
    collect_calls,
    current_stage,
    install_default,
)
from twin.web import create_app

NOW = dt.datetime(2026, 10, 20, 9, 30, tzinfo=dt.UTC)


@pytest.fixture
def recorder(tmp_path: Path) -> Iterator[UsageRecorder]:
    """A process-wide recorder with a ledger, as ``twin ui`` installs; the previous one comes back afterwards."""
    installed = UsageRecorder(ledger=UsageLedger(tmp_path / "usage.db"), keep_rows=False)
    previous = install_default(installed)
    try:
        yield installed
    finally:
        install_default(previous)


def row(stage: str, model: str = "chat", **tokens: Any) -> CallRow:
    return CallRow(stage, "openai_compat", model, "", success=True, **tokens)


def test_ledger_sums_calls_per_stage_over_the_last_hours_and_keeps_no_text(tmp_path: Path) -> None:
    clock = [NOW]
    ledger = UsageLedger(tmp_path / "usage.db", clock=lambda: clock[0])
    ledger.add(row("chat.answer", input_tokens=1000, output_tokens=50, cached_tokens=800))
    ledger.add(row("chat.answer", input_tokens=500, output_tokens=20))
    ledger.add(row("proofread", input_tokens=90_000, output_tokens=100))
    failed = row("chat.answer.hedge", unknown_usage_attempts=1)
    failed.success = False
    ledger.add(failed)
    # An embedding batch is not a language model's token.
    ledger.add(CallRow("chat.answer", "openai_compat_embed", "bge-m3", "", input_tokens=10**6, success=True))
    clock[0] = NOW - dt.timedelta(hours=30)
    ledger.add(row("proofread", input_tokens=10**6, output_tokens=1))
    clock[0] = NOW

    assert ledger.since(24) == [
        {
            "stage": "proofread",
            "calls": 1,
            "failures": 0,
            "input_tokens": 90_000,
            "output_tokens": 100,
            "cached_tokens": 0,
            "unknown_calls": 0,
        },
        {
            "stage": "chat.answer",
            "calls": 2,
            "failures": 0,
            "input_tokens": 1500,
            "output_tokens": 70,
            "cached_tokens": 800,
            "unknown_calls": 0,
        },
        {
            "stage": "chat.answer.hedge",
            "calls": 1,
            "failures": 1,
            "input_tokens": 0,
            "output_tokens": 0,
            "cached_tokens": 0,
            "unknown_calls": 1,
        },
    ]
    assert ledger.since(48)[0]["input_tokens"] == 10**6 + 90_000
    with sqlite3.connect(tmp_path / "usage.db") as db:
        columns = [r[1] for r in db.execute("PRAGMA table_info(hours)")]
    assert columns == [
        "hour",
        "stage",
        "model",
        "calls",
        "failures",
        "input_tokens",
        "output_tokens",
        "cached_tokens",
        "unknown_calls",
    ]


def test_ledger_drops_hours_older_than_it_keeps_when_it_opens(tmp_path: Path) -> None:
    old = UsageLedger(tmp_path / "usage.db", clock=lambda: NOW - dt.timedelta(days=UsageLedger.KEEP_DAYS + 1))
    old.add(row("proofread", input_tokens=5, output_tokens=1))
    reopened = UsageLedger(tmp_path / "usage.db", clock=lambda: NOW)
    assert reopened.since(24 * 365) == []


def test_a_process_wide_recorder_keeps_no_rows_but_still_counts_and_collects(recorder: UsageRecorder) -> None:
    with collect_calls() as collected:
        usage.current_recorder().add(row("chat.rewrite", input_tokens=10, output_tokens=2), False)
    assert recorder.rows == [] and len(collected) == 1
    assert recorder.ledger is not None and recorder.ledger.since(1)[0]["stage"] == "chat.rewrite"


def _openai(chunks: list[dict[str, Any]], bodies: list[dict[str, Any]], reject_options: bool = False) -> Any:
    def respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        bodies.append(body)
        if reject_options and "stream_options" in body:
            return httpx.Response(400, json={"error": {"message": "unknown field stream_options"}})
        content = "".join("data: " + json.dumps(c) + "\n\n" for c in chunks) + "data: [DONE]\n\n"
        return httpx.Response(200, text=content, headers={"Content-Type": "text/event-stream"})

    return respond


def _chunk(text: str | None, usage_: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "id": "t",
        "created": 0,
        "model": "chat",
        "object": "chat.completion.chunk",
        "choices": [] if text is None else [{"index": 0, "delta": {"content": text}, "finish_reason": None}],
        **({"usage": usage_} if usage_ else {}),
    }


def _stream(respond: Any, *, stage: str = "chat.answer", times: int = 1) -> list[str]:
    async def run() -> list[str]:
        async with (
            httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http,
            openai.AsyncOpenAI(api_key="test", http_client=http) as client,
        ):
            llm = OpenAICompatLLM("chat", async_client=client)
            texts: list[str] = []
            for _ in range(times):
                with call_stage(stage):
                    texts.append("".join([t async for t in llm.stream(system="s", user="question")]))
            return texts

    return asyncio.run(run())


def test_a_streamed_answer_asks_for_its_usage_and_counts_it_under_its_stage(recorder: UsageRecorder) -> None:
    bodies: list[dict[str, Any]] = []
    reported = {"prompt_tokens": 1200, "completion_tokens": 30, "prompt_tokens_details": {"cached_tokens": 1000}}
    respond = _openai([_chunk("回"), _chunk("答"), _chunk(None, reported)], bodies)
    assert _stream(respond) == ["回答"]
    assert bodies[0]["stream_options"] == {"include_usage": True}
    assert recorder.ledger is not None
    assert recorder.ledger.since(1) == [
        {
            "stage": "chat.answer",
            "calls": 1,
            "failures": 0,
            "input_tokens": 1200,
            "output_tokens": 30,
            "cached_tokens": 1000,
            "unknown_calls": 0,
        }
    ]


def test_a_server_refusing_stream_options_still_answers_and_is_not_asked_again(recorder: UsageRecorder) -> None:
    bodies: list[dict[str, Any]] = []
    assert _stream(_openai([_chunk("好")], bodies, reject_options=True), times=2) == ["好", "好"]
    assert ["stream_options" in b for b in bodies] == [True, False, False]
    assert recorder.ledger is not None
    [answer] = recorder.ledger.since(1)
    assert answer["calls"] == 2 and answer["failures"] == 0 and answer["unknown_calls"] == 2


def test_the_hedged_second_request_runs_under_its_own_stage() -> None:
    async def run() -> list[str]:
        stages: list[str] = []

        async def stream(delay: float) -> AsyncIterator[str]:
            stages.append(current_stage())
            await asyncio.sleep(delay)
            yield "x"

        delays = iter([0.2, 0.0])
        assert [t async for t in hedged_stream(lambda: stream(next(delays)), 0.02, stage="chat.answer")] == ["x"]
        return stages

    assert asyncio.run(run()) == ["chat.answer", "chat.answer.hedge"]


def test_the_work_agent_counts_each_model_call_with_its_usage(recorder: UsageRecorder) -> None:
    class Model:
        model_name = "work-model"

    callback = _usage_callback(Model())
    message = AIMessage("好", usage_metadata={"input_tokens": 3000, "output_tokens": 40, "total_tokens": 3040})
    callback.on_llm_end(LLMResult(generations=[[ChatGeneration(message=message)]]))
    callback.on_llm_end(LLMResult(generations=[[ChatGeneration(message=AIMessage("没有用量"))]]))
    callback.on_llm_error(RuntimeError("boom"))
    assert recorder.ledger is not None
    [work] = recorder.ledger.since(1)
    assert work["stage"] == "work.agent" and work["calls"] == 3 and work["failures"] == 1
    assert work["input_tokens"] == 3000 and work["output_tokens"] == 40 and work["unknown_calls"] == 2


def test_the_system_view_shows_the_last_day_of_usage(tmp_path: Path) -> None:
    previous = usage._default
    try:
        ledger = UsageLedger(tmp_path / "usage.db")
        app = create_app(Settings(db_path=tmp_path / "twin.db"), usage=ledger)
        usage.current_recorder().add(row("chat.answer", input_tokens=7, output_tokens=3), False)
        body = TestClient(app, base_url="http://localhost").get("/api/admin/system").json()
    finally:
        install_default(previous)
    assert [(u["stage"], u["input_tokens"], u["output_tokens"]) for u in body["usage"]] == [("chat.answer", 7, 3)]
