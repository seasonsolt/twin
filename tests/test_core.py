from __future__ import annotations

import copy
import json
import os
import sqlite3
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import anthropic
import httpx2
import numpy as np
import openai
import pytest
from pydantic import BaseModel, ValidationError

from twin.config import (
    EmbedSettings,
    LLMSettings,
    Settings,
    load_settings,
    make_embedder,
    make_llm,
)
from twin.embed import EmbedError, HashingEmbedder, OpenAICompatEmbedder
from twin.llm import (
    AnthropicLLM,
    ClaudeCLILLM,
    FakeLLM,
    LLMError,
    LLMInvalidOutput,
    LLMRefusal,
    LLMTruncated,
    OpenAICompatLLM,
    inline_schema,
)
from twin.persona.schema import SourceKind
from twin.util import escape_csv_cell, normalize_for_match, open_private, run_parallel, stable_id


class StructuredEntry(BaseModel):
    start_idx: int
    end_idx: int
    topic: str


class StructuredResult(BaseModel):
    episodes: list[StructuredEntry]


VALID_RESULT = {"episodes": [{"start_idx": 0, "end_idx": 3, "topic": "预算"}]}


class _Child(BaseModel):
    title: str
    score: float


class _Doc(BaseModel):
    title: str
    default: str
    kind: SourceKind
    child: _Child | None
    children: list[_Child]
    note: str | None = None


def test_inline_schema_keeps_properties_named_like_keywords() -> None:
    out = inline_schema(_Doc)
    assert list(out["properties"]) == ["title", "default", "kind", "child", "children", "note"]
    assert out["required"] == ["title", "default", "kind", "child", "children", "note"]
    assert out["properties"]["title"] == {"type": "string"}
    assert out["properties"]["default"] == {"type": "string"}
    assert out["properties"]["kind"] == {"enum": [k.value for k in SourceKind], "type": "string"}
    assert out["properties"]["note"] == {"anyOf": [{"type": "string"}, {"type": "null"}]}
    child_object, null = out["properties"]["child"]["anyOf"]
    assert null == {"type": "null"}
    assert child_object["properties"] == {"title": {"type": "string"}, "score": {"type": "number"}}
    assert child_object["required"] == ["title", "score"]
    assert child_object["additionalProperties"] is False
    assert out["properties"]["children"]["items"] == child_object


# ---------------------------------------------------------------- FakeLLM


def test_fake_llm_validates_dicts_and_records_calls() -> None:
    fake = FakeLLM(lambda system, user, schema: VALID_RESULT)
    out = fake.structured(system="系统", user="用户", schema=StructuredResult)
    assert isinstance(out, StructuredResult)
    assert out.episodes[0].topic == "预算"
    assert fake.calls == [("StructuredResult", "系统", "用户")]
    assert fake.name == "fake"


def test_fake_llm_returns_instances_and_converts_other_models() -> None:
    instance = StructuredResult.model_validate(VALID_RESULT)
    same = FakeLLM(lambda s, u, schema: instance).structured(system="", user="", schema=StructuredResult)
    assert same is instance

    class _Mirror(BaseModel):
        episodes: list[StructuredEntry]

    mirror = _Mirror.model_validate(VALID_RESULT)
    converted = FakeLLM(lambda s, u, schema: mirror).structured(system="", user="", schema=StructuredResult)
    assert isinstance(converted, StructuredResult)
    assert converted.episodes == instance.episodes


def test_fake_llm_rejects_invalid_output() -> None:
    fake = FakeLLM(lambda s, u, schema: {"episodes": [{"start_idx": "x"}]})
    with pytest.raises(ValidationError):
        fake.structured(system="", user="", schema=StructuredResult)


# ---------------------------------------------------------------- AnthropicLLM (fake client)


@dataclass
class _Block:
    type: str
    text: str = ""


@dataclass
class _Message:
    stop_reason: str
    content: list[_Block] = field(default_factory=list)
    parsed_output: object = None
    stop_details: object = None


class _FakeStream:
    def __init__(self, message: _Message) -> None:
        self._message = message
        self.entered = False
        self.exited = False

    def __enter__(self) -> _FakeStream:
        self.entered = True
        return self

    def __exit__(self, *exc: object) -> None:
        self.exited = True

    def get_final_message(self) -> _Message:
        assert self.entered and not self.exited
        return self._message


class _FakeBetaMessages:
    """Replies in order; the last reply repeats. An exception reply is raised when the stream is opened."""

    def __init__(self, replies: list[_Message | Exception]) -> None:
        self.replies = replies
        self.calls: list[dict[str, Any]] = []
        self.streams: list[_FakeStream] = []

    def stream(self, **kwargs: Any) -> _FakeStream:
        self.calls.append(kwargs)
        reply = self.replies[min(len(self.calls), len(self.replies)) - 1]
        if isinstance(reply, Exception):
            raise reply
        self.streams.append(_FakeStream(reply))
        return self.streams[-1]


class _FakeAnthropic:
    def __init__(self, message: _Message, *more: _Message | Exception) -> None:
        self.messages = _FakeBetaMessages([message, *more])
        self.beta = SimpleNamespace(messages=self.messages)


def test_anthropic_llm_request_parameters() -> None:
    parsed = StructuredResult.model_validate(VALID_RESULT)
    client = _FakeAnthropic(_Message(stop_reason="end_turn", parsed_output=parsed))
    llm = AnthropicLLM(model="claude-opus-5-5", client=client)

    out = llm.structured(system="系统提示", user="会议内容", schema=StructuredResult, effort="high", max_tokens=321)

    assert out is parsed
    assert llm.name == "anthropic:claude-opus-5-5"
    (kwargs,) = client.messages.calls
    assert kwargs["model"] == "claude-opus-5-5"
    assert kwargs["max_tokens"] == 321
    assert kwargs["system"] == [{"type": "text", "text": "系统提示", "cache_control": {"type": "ephemeral"}}]
    assert kwargs["messages"] == [{"role": "user", "content": "会议内容"}]
    assert "server-side-fallback-2026-07-01" in kwargs["betas"]
    assert kwargs["fallbacks"] == "default"
    assert kwargs["output_config"]["effort"] == "high"
    assert kwargs["output_config"]["format"] == {
        "type": "json_schema",
        "schema": anthropic.transform_schema(StructuredResult),
    }
    assert "output_format" not in kwargs
    assert client.messages.streams[0].exited


def test_anthropic_llm_refusal() -> None:
    message = _Message(stop_reason="refusal", stop_details=SimpleNamespace(category="cyber"))
    with pytest.raises(LLMRefusal, match="cyber"):
        AnthropicLLM(client=_FakeAnthropic(message)).structured(system="s", user="u", schema=StructuredResult)


def test_anthropic_llm_max_tokens_after_one_doubled_retry() -> None:
    message = _Message(stop_reason="max_tokens", content=[_Block("text", '{"episodes": [')])
    client = _FakeAnthropic(message)
    with pytest.raises(LLMTruncated, match="max_tokens=198"):
        AnthropicLLM(client=client).structured(system="s", user="u", schema=StructuredResult, max_tokens=99)
    assert [c["max_tokens"] for c in client.messages.calls] == [99, 198]


def test_anthropic_llm_default_output_budget_is_64k_and_configurable() -> None:
    parsed = StructuredResult.model_validate(VALID_RESULT)
    default = _FakeAnthropic(_Message(stop_reason="end_turn", parsed_output=parsed))
    AnthropicLLM(client=default).structured(system="s", user="u", schema=StructuredResult)
    configured = _FakeAnthropic(_Message(stop_reason="end_turn", parsed_output=parsed))
    llm = AnthropicLLM(client=configured, max_tokens=20000)
    llm.structured(system="s", user="u", schema=StructuredResult)
    llm.structured(system="s", user="u", schema=StructuredResult, max_tokens=500)
    assert [c["max_tokens"] for c in default.messages.calls] == [64000]
    assert [c["max_tokens"] for c in configured.messages.calls] == [20000, 500]


def test_anthropic_llm_retries_truncation_once_with_doubled_budget() -> None:
    parsed = StructuredResult.model_validate(VALID_RESULT)
    client = _FakeAnthropic(
        _Message(stop_reason="max_tokens", content=[_Block("text", '{"episodes": [')]),
        _Message(stop_reason="end_turn", parsed_output=parsed),
    )
    out = AnthropicLLM(client=client).structured(system="s", user="u", schema=StructuredResult, effort="max")
    assert out is parsed
    assert [(c["max_tokens"], c["output_config"]["effort"]) for c in client.messages.calls] == [
        (64000, "max"),
        (128000, "max"),
    ]


def test_anthropic_llm_does_not_retry_truncation_at_output_cap() -> None:
    client = _FakeAnthropic(_Message(stop_reason="max_tokens"))
    with pytest.raises(LLMTruncated, match="max_tokens=128000"):
        AnthropicLLM(client=client, max_tokens=128000).structured(system="s", user="u", schema=StructuredResult)
    assert len(client.messages.calls) == 1


def test_anthropic_llm_rejected_retry_still_reports_truncation() -> None:
    import httpx2

    response = httpx2.Response(400, request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages"))
    rejected = anthropic.BadRequestError("max_tokens: 128000 > 64000", response=response, body=None)
    client = _FakeAnthropic(_Message(stop_reason="max_tokens"), rejected)
    with pytest.raises(LLMTruncated, match="max_tokens=64000") as info:
        AnthropicLLM(client=client, model="claude-haiku").structured(system="s", user="u", schema=StructuredResult)
    assert info.value.__cause__ is rejected
    assert [c["max_tokens"] for c in client.messages.calls] == [64000, 128000]


def test_anthropic_llm_parses_text_when_parsed_output_missing() -> None:
    text = "```json\n" + json.dumps(VALID_RESULT, ensure_ascii=False) + "\n```"
    message = _Message(stop_reason="end_turn", content=[_Block("thinking"), _Block("text", text)], parsed_output=None)
    out = AnthropicLLM(client=_FakeAnthropic(message)).structured(system="s", user="u", schema=StructuredResult)
    assert out == StructuredResult.model_validate(VALID_RESULT)


def test_anthropic_llm_mid_stream_fallback_parses_only_the_fallback_models_text() -> None:
    # json_schema requests carry no prefill claim: the fallback model restarts the answer, while the declined model's
    # partial text stays in the message in front of the fallback block.
    blocks = [
        _Block("thinking"),
        _Block("text", _FULL_JSON[:25]),
        _Block("fallback"),
        _Block("text", _FULL_JSON),
    ]
    message = _Message(stop_reason="end_turn", content=blocks, parsed_output=None)
    out = AnthropicLLM(client=_FakeAnthropic(message)).structured(system="s", user="u", schema=StructuredResult)
    assert out == StructuredResult.model_validate(VALID_RESULT)


def test_anthropic_llm_invalid_text() -> None:
    message = _Message(stop_reason="end_turn", content=[_Block("text", "抱歉，无法回答")])
    with pytest.raises(LLMInvalidOutput):
        AnthropicLLM(client=_FakeAnthropic(message)).structured(system="s", user="u", schema=StructuredResult)


# ---------------------------------------------------------------- AnthropicLLM (real SDK, mocked transport)


def _sse(events: list[dict[str, Any]]) -> bytes:
    return "".join(f"event: {e['type']}\ndata: {json.dumps(e, ensure_ascii=False)}\n\n" for e in events).encode()


def _text_events(index: int, text: str) -> list[dict[str, Any]]:
    return [
        {"type": "content_block_start", "index": index, "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": index, "delta": {"type": "text_delta", "text": text}},
        {"type": "content_block_stop", "index": index},
    ]


def _fallback_events(index: int) -> list[dict[str, Any]]:
    block = {
        "type": "fallback",
        "from": {"model": "claude-opus-5-5"},
        "to": {"model": "claude-opus-4-8"},
        "trigger": {"type": "refusal", "category": "cyber"},
    }
    return [
        {"type": "content_block_start", "index": index, "content_block": block},
        {"type": "content_block_stop", "index": index},
    ]


def _stream_body(blocks: list[dict[str, Any]], stop_reason: str, stop_details: dict[str, Any] | None = None) -> bytes:
    start = {
        "type": "message_start",
        "message": {
            "id": "msg_test",
            "type": "message",
            "role": "assistant",
            "model": "claude-opus-5-5",
            "content": [],
            "stop_reason": None,
            "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 0},
        },
    }
    delta = {
        "type": "message_delta",
        "delta": {"stop_reason": stop_reason, "stop_sequence": None, "stop_details": stop_details},
        "usage": {"output_tokens": 5},
    }
    return _sse([start, *blocks, delta, {"type": "message_stop"}])


_FULL_JSON = json.dumps(VALID_RESULT, ensure_ascii=False)
_SDK_CASES: dict[str, tuple[bytes, type[Exception] | None]] = {
    "end_turn": (_stream_body(_text_events(0, _FULL_JSON), "end_turn"), None),
    "max_tokens": (_stream_body(_text_events(0, _FULL_JSON[:25]), "max_tokens"), LLMTruncated),
    "refusal": (
        _stream_body(_text_events(0, '{"episodes": [{"to'), "refusal", {"type": "refusal", "category": "cyber"}),
        LLMRefusal,
    ),
    "mid_stream_fallback": (
        _stream_body(
            [*_text_events(0, _FULL_JSON[:25]), *_fallback_events(1), *_text_events(2, _FULL_JSON)], "end_turn"
        ),
        None,
    ),
}


@pytest.mark.parametrize("case", list(_SDK_CASES))
def test_anthropic_llm_with_real_sdk_stream(case: str) -> None:
    httpx2 = pytest.importorskip("httpx2")
    body, expected_error = _SDK_CASES[case]
    requests: list[Any] = []

    def handler(request: Any) -> Any:
        requests.append(request)
        return httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=body)

    client = anthropic.Anthropic(
        api_key="test-key",
        max_retries=0,
        http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(handler)),
    )
    llm = AnthropicLLM(client=client)
    if expected_error is None:
        out = llm.structured(system="系统", user="用户", schema=StructuredResult, effort="low")
        assert out == StructuredResult.model_validate(VALID_RESULT)
    else:
        with pytest.raises(expected_error):
            llm.structured(system="系统", user="用户", schema=StructuredResult, effort="low")

    budgets = [64000, 128000] if case == "max_tokens" else [64000]
    assert len(requests) == len(budgets)
    for request, budget in zip(requests, budgets, strict=True):
        sent = json.loads(request.content)
        assert "server-side-fallback-2026-07-01" in request.headers["anthropic-beta"]
        assert sent["fallbacks"] == "default"
        assert sent["max_tokens"] == budget
        assert sent["output_config"] == {
            "effort": "low",
            "format": {"type": "json_schema", "schema": anthropic.transform_schema(StructuredResult)},
        }
        assert sent["system"] == [{"type": "text", "text": "系统", "cache_control": {"type": "ephemeral"}}]
        assert sent["messages"] == [{"role": "user", "content": "用户"}]
        assert sent["stream"] is True


# ---------------------------------------------------------------- OpenAICompatLLM


_Reply = tuple[str | None, str] | SimpleNamespace | Exception


class _FakeCompletions:
    """Replies are ``(content, finish_reason)``, a ready-made response, or an exception to raise."""

    def __init__(self, replies: list[_Reply]) -> None:
        self.replies = list(replies)
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(copy.deepcopy(kwargs))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        if isinstance(reply, SimpleNamespace):
            return reply
        content, finish_reason = reply
        message = SimpleNamespace(content=content)
        return SimpleNamespace(choices=[SimpleNamespace(finish_reason=finish_reason, message=message)])


class _FakeOpenAI:
    def __init__(self, replies: list[_Reply]) -> None:
        self.completions = _FakeCompletions(replies)
        self.chat = SimpleNamespace(completions=self.completions)


def _openai_request() -> Any:
    import httpx2

    return httpx2.Request("POST", "http://10.0.0.8:8000/v1/chat/completions")


def test_openai_compat_parses_json_object_mode() -> None:
    client = _FakeOpenAI([("```json\n" + _FULL_JSON + "\n```", "stop")])
    llm = OpenAICompatLLM(model="qwen-max", client=client)
    out = llm.structured(system="系统", user="用户", schema=StructuredResult, max_tokens=777)

    assert out == StructuredResult.model_validate(VALID_RESULT)
    assert llm.name == "openai_compat:qwen-max"
    (call,) = client.completions.calls
    assert call["model"] == "qwen-max"
    assert call["max_tokens"] == 777
    assert call["response_format"] == {"type": "json_object"}
    system, user = call["messages"]
    assert system["role"] == "system"
    assert system["content"].startswith("系统")
    assert json.dumps(inline_schema(StructuredResult), ensure_ascii=False) in system["content"]
    assert user == {"role": "user", "content": "用户"}


def test_openai_compat_retries_once_after_invalid_output() -> None:
    client = _FakeOpenAI([("这不是 JSON", "stop"), (_FULL_JSON, "stop")])
    out = OpenAICompatLLM(model="m", client=client).structured(system="s", user="u", schema=StructuredResult)

    assert out == StructuredResult.model_validate(VALID_RESULT)
    first, second = client.completions.calls
    assert len(first["messages"]) == 2
    assert [m["role"] for m in second["messages"]] == ["system", "user", "assistant", "user"]
    assert second["messages"][2]["content"] == "这不是 JSON"
    assert "schema" in second["messages"][3]["content"]


def test_openai_compat_gives_up_after_second_invalid_output() -> None:
    client = _FakeOpenAI([("{}", "stop"), (None, "stop")])
    with pytest.raises(LLMInvalidOutput):
        OpenAICompatLLM(model="m", client=client).structured(system="s", user="u", schema=StructuredResult)
    assert len(client.completions.calls) == 2


def test_openai_compat_json_schema_mode() -> None:
    client = _FakeOpenAI([(_FULL_JSON, "stop")])
    OpenAICompatLLM(model="m", json_mode="json_schema", client=client).structured(
        system="s", user="u", schema=StructuredResult
    )
    assert client.completions.calls[0]["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "StructuredResult", "schema": inline_schema(StructuredResult), "strict": True},
    }


def test_openai_compat_without_response_format() -> None:
    client = _FakeOpenAI([(_FULL_JSON, "stop")])
    OpenAICompatLLM(model="m", json_mode="none", client=client).structured(
        system="s", user="u", schema=StructuredResult
    )
    assert "response_format" not in client.completions.calls[0]


def test_openai_compat_length_is_truncation_without_retry() -> None:
    client = _FakeOpenAI([('{"episodes": [', "length"), (_FULL_JSON, "stop")])
    with pytest.raises(LLMTruncated):
        OpenAICompatLLM(model="m", client=client).structured(system="s", user="u", schema=StructuredResult)
    assert len(client.completions.calls) == 1


def test_openai_compat_output_budget_defaults_to_8k_and_is_configurable() -> None:
    default = _FakeOpenAI([(_FULL_JSON, "stop")])
    OpenAICompatLLM(model="m", client=default).structured(system="s", user="u", schema=StructuredResult)
    configured = _FakeOpenAI([(_FULL_JSON, "stop"), (_FULL_JSON, "stop")])
    llm = OpenAICompatLLM(model="m", client=configured, max_tokens=4096)
    llm.structured(system="s", user="u", schema=StructuredResult)
    llm.structured(system="s", user="u", schema=StructuredResult, max_tokens=300)
    assert [c["max_tokens"] for c in default.completions.calls] == [8192]
    assert [c["max_tokens"] for c in configured.completions.calls] == [4096, 300]


def test_openai_compat_bad_request_becomes_llm_error_with_hint() -> None:
    import httpx2
    import openai

    response = httpx2.Response(400, request=_openai_request())
    rejected = openai.BadRequestError(
        "This model's maximum context length is 32768 tokens. However, you requested 34000 tokens",
        response=response,
        body=None,
    )
    client = _FakeOpenAI([rejected])
    with pytest.raises(LLMError, match="maximum context length") as info:
        OpenAICompatLLM(model="qwen", client=client).structured(system="s", user="u", schema=StructuredResult)
    assert "max_tokens" in str(info.value)
    assert info.value.__cause__ is rejected
    assert len(client.completions.calls) == 1


def test_openai_compat_transport_errors_become_llm_error() -> None:
    import openai

    client = _FakeOpenAI([openai.APITimeoutError(request=_openai_request())])
    with pytest.raises(LLMError, match="timed out"):
        OpenAICompatLLM(model="qwen", client=client, max_retries=0).structured(
            system="s", user="u", schema=StructuredResult
        )


_WRAPPED_JSON = {
    "prose_then_fence": "以下是结果：\n```json\n" + _FULL_JSON + "\n```",
    "fence_then_prose": "```json\n" + _FULL_JSON + "\n```\n以上。",
    "think_prefix": '<think>\n草稿 {"episodes": []} 不对，漏了预算议题……\n</think>\n' + _FULL_JSON,
    "prose_around_bare_object": "结果如下 " + _FULL_JSON + " 请查收。",
    "bare_fence_without_language": "```\n" + _FULL_JSON + "\n```",
}


@pytest.mark.parametrize("case", list(_WRAPPED_JSON))
def test_openai_compat_extracts_json_from_wrapped_output_without_retry(case: str) -> None:
    client = _FakeOpenAI([(_WRAPPED_JSON[case], "stop")])
    out = OpenAICompatLLM(model="m", json_mode="none", client=client).structured(
        system="s", user="u", schema=StructuredResult
    )
    assert out == StructuredResult.model_validate(VALID_RESULT)
    assert len(client.completions.calls) == 1


def test_wrapped_json_is_also_extracted_for_the_anthropic_text_path() -> None:
    message = _Message(stop_reason="end_turn", content=[_Block("text", _WRAPPED_JSON["prose_then_fence"])])
    out = AnthropicLLM(client=_FakeAnthropic(message)).structured(system="s", user="u", schema=StructuredResult)
    assert out == StructuredResult.model_validate(VALID_RESULT)


def test_openai_compat_content_filter_is_refusal_without_retry() -> None:
    client = _FakeOpenAI([(None, "content_filter"), (_FULL_JSON, "stop")])
    with pytest.raises(LLMRefusal, match="content_filter"):
        OpenAICompatLLM(model="m", client=client).structured(system="s", user="u", schema=StructuredResult)
    assert len(client.completions.calls) == 1


def test_openai_compat_message_refusal_is_refusal_without_retry() -> None:
    message = SimpleNamespace(content=None, refusal="I can't help with that.")
    refused = SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop", message=message)])
    client = _FakeOpenAI([refused, (_FULL_JSON, "stop")])
    with pytest.raises(LLMRefusal, match="can't help"):
        OpenAICompatLLM(model="m", client=client).structured(system="s", user="u", schema=StructuredResult)
    assert len(client.completions.calls) == 1


def test_openai_compat_empty_choices_is_llm_error() -> None:
    client = _FakeOpenAI([SimpleNamespace(choices=[])])
    with pytest.raises(LLMError, match="no choices"):
        OpenAICompatLLM(model="m", client=client).structured(system="s", user="u", schema=StructuredResult)


# ---------------------------------------------------------------- ClaudeCLILLM


class _FakeRun:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.calls: list[tuple[list[str], dict[str, Any]]] = []

    def __call__(self, cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append((list(cmd), kwargs))
        return subprocess.CompletedProcess(cmd, self.returncode, self.stdout, self.stderr)


def _cli(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, run: _FakeRun) -> ClaudeCLILLM:
    monkeypatch.setattr("twin.llm.tempfile.mkdtemp", lambda prefix="": str(tmp_path))
    monkeypatch.setattr("twin.llm.subprocess.run", run)
    monkeypatch.setattr("twin.llm.shutil.which", lambda binary: binary)
    return ClaudeCLILLM(model="claude-opus-5-5", binary="/usr/local/bin/claude", timeout=12.5)


def _opt(cmd: list[str], flag: str) -> str:
    return cmd[cmd.index(flag) + 1]


def test_claude_cli_command_line_and_structured_output(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    run = _FakeRun(stdout=json.dumps({"is_error": False, "structured_output": VALID_RESULT, "result": ""}))
    llm = _cli(monkeypatch, tmp_path, run)
    out = llm.structured(system="系统提示", user="会议内容", schema=StructuredResult, effort="xhigh")

    assert out == StructuredResult.model_validate(VALID_RESULT)
    assert llm.name == "claude_cli:claude-opus-5-5"
    ((cmd, kwargs),) = run.calls
    assert cmd[0] == "/usr/local/bin/claude"
    assert "-p" in cmd
    assert "--no-session-persistence" in cmd
    assert "--strict-mcp-config" in cmd
    assert _opt(cmd, "--output-format") == "json"
    assert _opt(cmd, "--tools") == ""
    assert _opt(cmd, "--setting-sources") == ""
    assert _opt(cmd, "--model") == "claude-opus-5-5"
    assert _opt(cmd, "--effort") == "xhigh"
    assert _opt(cmd, "--system-prompt") == "系统提示"
    assert json.loads(_opt(cmd, "--json-schema")) == inline_schema(StructuredResult)
    assert "会议内容" not in cmd
    assert kwargs == {"input": "会议内容", "capture_output": True, "text": True, "timeout": 12.5, "cwd": str(tmp_path)}


def test_claude_cli_falls_back_to_result_text(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    payload = {"is_error": False, "result": "```json\n" + _FULL_JSON + "\n```"}
    llm = _cli(monkeypatch, tmp_path, _FakeRun(stdout=json.dumps(payload)))
    assert llm.structured(system="s", user="u", schema=StructuredResult).episodes[0].topic == "预算"


def test_claude_cli_is_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    payload = {"is_error": True, "subtype": "error_during_execution", "result": "登录已过期"}
    llm = _cli(monkeypatch, tmp_path, _FakeRun(stdout=json.dumps(payload)))
    with pytest.raises(LLMError, match="登录已过期") as info:
        llm.structured(system="s", user="u", schema=StructuredResult)
    assert type(info.value) is LLMError


def test_claude_cli_nonzero_exit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    llm = _cli(monkeypatch, tmp_path, _FakeRun(returncode=2, stderr="unknown option --effort"))
    with pytest.raises(LLMError, match=r"exited 2: unknown option --effort"):
        llm.structured(system="s", user="u", schema=StructuredResult)


_API_ERROR = json.dumps(
    {"is_error": True, "terminal_reason": "api_error", "result": "Not logged in · Please run /login"}
)


class _SequenceRun:
    def __init__(self, results: list[tuple[int, str]]) -> None:
        self.results = results
        self.calls = 0

    def __call__(self, cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        code, stdout = self.results[min(self.calls, len(self.results) - 1)]
        self.calls += 1
        return subprocess.CompletedProcess(cmd, code, stdout, "")


def test_claude_cli_retries_api_errors_then_succeeds(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    ok = json.dumps({"is_error": False, "structured_output": VALID_RESULT})
    run = _SequenceRun([(1, _API_ERROR), (0, _API_ERROR), (0, ok)])
    llm = _cli(monkeypatch, tmp_path, _FakeRun())
    monkeypatch.setattr("twin.llm.subprocess.run", run)
    slept: list[float] = []
    llm._sleep = slept.append
    assert llm.structured(system="s", user="u", schema=StructuredResult).episodes
    assert run.calls == 3 and slept == [5.0, 20.0]


def test_claude_cli_gives_up_after_the_last_retry(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    run = _SequenceRun([(1, _API_ERROR)])
    llm = _cli(monkeypatch, tmp_path, _FakeRun())
    monkeypatch.setattr("twin.llm.subprocess.run", run)
    slept: list[float] = []
    llm._sleep = slept.append
    with pytest.raises(LLMError, match="Not logged in"):
        llm.structured(system="s", user="u", schema=StructuredResult)
    assert run.calls == 4 and slept == [5.0, 20.0, 60.0]


def test_claude_cli_non_json_stdout(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    llm = _cli(monkeypatch, tmp_path, _FakeRun(stdout="Error: not logged in"))
    with pytest.raises(LLMInvalidOutput):
        llm.structured(system="s", user="u", schema=StructuredResult)


def test_claude_cli_refusal_and_invalid_structured_output(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    refusal = _cli(monkeypatch, tmp_path, _FakeRun(stdout=json.dumps({"is_error": False, "stop_reason": "refusal"})))
    with pytest.raises(LLMRefusal):
        refusal.structured(system="s", user="u", schema=StructuredResult)
    invalid = _cli(monkeypatch, tmp_path, _FakeRun(stdout=json.dumps({"structured_output": {"episodes": "x"}})))
    with pytest.raises(LLMInvalidOutput):
        invalid.structured(system="s", user="u", schema=StructuredResult)


def test_claude_cli_timeout_is_an_llm_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def hang(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=kwargs["timeout"])

    llm = _cli(monkeypatch, tmp_path, _FakeRun())
    monkeypatch.setattr("twin.llm.subprocess.run", hang)
    with pytest.raises(LLMError, match=r"timed out after 12\.5s") as info:
        llm.structured(system="s", user="u", schema=StructuredResult)
    assert isinstance(info.value.__cause__, subprocess.TimeoutExpired)


def test_claude_cli_requires_the_executable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("twin.llm.shutil.which", lambda binary: None)
    with pytest.raises(LLMError, match="找不到可执行文件 claude"):
        ClaudeCLILLM()


# ---------------------------------------------------------------- HashingEmbedder


def test_hashing_embedder_is_deterministic_and_normalised() -> None:
    texts = ["外包成本必须压缩", "Budget overrun", ""]
    a = HashingEmbedder().embed(texts)
    b = HashingEmbedder().embed(texts)
    assert a.dtype == np.float32
    assert a.shape == (3, 4096)
    assert np.array_equal(a, b)
    norms = np.linalg.norm(a, axis=1)
    assert norms[:2] == pytest.approx([1.0, 1.0], abs=1e-6)
    assert norms[2] == 0.0
    assert HashingEmbedder(dim=64).embed([]).shape == (0, 64)


def test_hashing_embedder_ignores_case_whitespace_and_punctuation() -> None:
    emb = HashingEmbedder(dim=512)
    a, b = emb.embed(["Hello, 世界！", "hello 世界"])
    assert np.allclose(a, b)


def test_hashing_embedder_similar_texts_score_higher() -> None:
    emb = HashingEmbedder()
    base, similar, unrelated = emb.embed(
        ["这个项目的预算必须严格控制", "项目预算要严格控制住", "周末天气晴朗适合去郊游"]
    )
    assert float(base @ similar) > float(base @ unrelated) + 0.3
    assert emb.name == "hashing:4096"
    assert emb.cluster_threshold == 0.6


# ---------------------------------------------------------------- config


def test_load_settings_keeps_absolute_db_path_and_uses_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = tmp_path / "elsewhere" / "x.db"
    path = tmp_path / "custom.toml"
    path.write_text(f'db_path = "{db.as_posix()}"\n', encoding="utf-8")
    monkeypatch.setenv("TWIN_CONFIG", str(path))
    assert load_settings().db_path == db

    monkeypatch.setenv("TWIN_CONFIG", str(tmp_path / "missing.toml"))
    assert load_settings() == Settings()
    assert load_settings(tmp_path / "missing.toml").db_path == Path("data/twin.db")


def test_load_settings_expands_home_in_db_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    path = tmp_path / "cfg" / "twin.toml"
    path.parent.mkdir()
    path.write_text('db_path = "~/twin/twin.db"\n', encoding="utf-8")
    assert load_settings(path).db_path == home / "twin" / "twin.db"


@pytest.mark.parametrize(
    "toml",
    ['[llm]\nprovider = "gpt"\n', "[llm]\nmax_tokens = 0\n", "[llm]\ntimeout = 0\n", "[llm]\nmax_retries = -1\n"],
)
def test_load_settings_rejects_invalid_values(tmp_path: Path, toml: str) -> None:
    path = tmp_path / "twin.toml"
    path.write_text(toml, encoding="utf-8")
    with pytest.raises(ValidationError):
        load_settings(path)


def test_make_llm_variants(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    constructed: list[dict[str, Any]] = []

    class _NoNetworkAnthropic:
        api_key = "test-key"
        auth_token = None

        def __init__(self, **kwargs: Any) -> None:
            constructed.append(kwargs)

    monkeypatch.setattr(anthropic, "Anthropic", _NoNetworkAnthropic)
    a = make_llm(LLMSettings(provider="anthropic", model="claude-opus-5-5"))
    assert isinstance(a, AnthropicLLM)
    assert a.name == "anthropic:claude-opus-5-5"
    assert a.max_tokens == 64000
    assert constructed == [{"max_retries": 0}]  # Retries are explicit so accounting sees every attempt.
    a_budget = make_llm(LLMSettings(provider="anthropic", max_tokens=32000))
    assert isinstance(a_budget, AnthropicLLM)
    assert a_budget.max_tokens == 32000

    monkeypatch.delenv("TWIN_TEST_KEY", raising=False)
    o = make_llm(
        LLMSettings(
            provider="openai_compat",
            model="deepseek-chat",
            base_url="http://127.0.0.1:9/v1",
            api_key_env="TWIN_TEST_KEY",
            json_mode="none",
        )
    )
    assert isinstance(o, OpenAICompatLLM)
    assert (o.model, o.json_mode, o.name, o.max_tokens) == (
        "deepseek-chat",
        "none",
        "openai_compat:deepseek-chat",
        8192,
    )
    assert (o._client.timeout, o._client.max_retries, o.max_retries) == (600.0, 0, 2)

    tuned = make_llm(
        LLMSettings(
            provider="openai_compat",
            model="qwen",
            base_url="http://127.0.0.1:9/v1",
            max_tokens=4096,
            timeout=1800,
            max_retries=0,
        )
    )
    assert isinstance(tuned, OpenAICompatLLM)
    assert (tuned.max_tokens, tuned._client.timeout, tuned._client.max_retries) == (4096, 1800.0, 0)

    monkeypatch.setattr("twin.llm.tempfile.mkdtemp", lambda prefix="": str(tmp_path))
    monkeypatch.setattr("twin.llm.shutil.which", lambda binary: f"/usr/local/bin/{binary}")
    c = make_llm(LLMSettings(provider="claude_cli", model="claude-opus-5-5"))
    assert isinstance(c, ClaudeCLILLM)
    assert c.name == "claude_cli:claude-opus-5-5"
    for provider in ("anthropic", "claude_cli"):
        assert make_llm(LLMSettings(provider=provider)).name == f"{provider}:claude-opus-5-5"


def test_default_backend_is_openai_compat_and_needs_model_and_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    assert (Settings().llm.provider, Settings().llm.model, Settings().judges) == ("openai_compat", None, [])
    with pytest.raises(ValueError, match=r"\[llm\].*必须设置 model"):
        make_llm(LLMSettings())
    with pytest.raises(ValueError, match=r"\[judges #2\].*base_url.*api\.openai\.com"):
        make_llm(LLMSettings(model="qwen3.8-max"), "judges #2")


def test_anthropic_backend_checks_credentials_before_any_request(monkeypatch: pytest.MonkeyPatch) -> None:
    class _NoCredentials:
        api_key = None
        auth_token = None

    monkeypatch.setattr(anthropic, "Anthropic", lambda **kwargs: _NoCredentials())
    with pytest.raises(LLMError, match="ANTHROPIC_API_KEY"):
        AnthropicLLM()


@pytest.mark.parametrize(
    "error",
    [
        anthropic.APIConnectionError(request=httpx2.Request("POST", "http://127.0.0.1:9/v1/messages")),
        anthropic.RateLimitError(
            "rate limited",
            response=httpx2.Response(429, request=httpx2.Request("POST", "http://127.0.0.1:9/v1/messages")),
            body=None,
        ),
    ],
    ids=["connection", "429"],
)
def test_anthropic_sdk_errors_become_llm_errors(error: Exception) -> None:
    client = _FakeAnthropic(_Message(stop_reason="end_turn"))
    client.messages.replies = [error]
    llm = AnthropicLLM(client=client)
    with pytest.raises(LLMError, match=type(error).__name__) as info:
        llm.structured(system="s", user="u", schema=StructuredResult)
    assert info.value.__cause__ is error


def test_llm_refusal_keeps_its_category() -> None:
    message = _Message(stop_reason="refusal", stop_details=SimpleNamespace(category="cyber"))
    with pytest.raises(LLMRefusal) as info:
        AnthropicLLM(client=_FakeAnthropic(message)).structured(system="s", user="u", schema=StructuredResult)
    assert info.value.category == "cyber"


def test_make_embedder_variants() -> None:
    default = make_embedder(EmbedSettings())
    assert isinstance(default, HashingEmbedder)
    assert default.cluster_threshold == 0.6
    tuned = make_embedder(EmbedSettings(cluster_threshold=0.5))
    assert isinstance(tuned, HashingEmbedder)
    assert tuned.cluster_threshold == 0.5

    remote = make_embedder(EmbedSettings(provider="openai_compat", base_url="http://127.0.0.1:9/v1"))
    assert isinstance(remote, OpenAICompatEmbedder)
    assert (remote.name, remote.cluster_threshold) == ("openai_compat:BAAI/bge-m3", 0.82)
    remote_tuned = make_embedder(
        EmbedSettings(provider="openai_compat", base_url="http://127.0.0.1:9/v1", cluster_threshold=0.7)
    )
    assert remote_tuned.cluster_threshold == 0.7


def test_openai_compat_embedder_service_errors_are_embed_errors() -> None:
    request = httpx2.Request("POST", "http://127.0.0.1:9/v1/embeddings")

    class _DownEmbeddings:
        def create(self, **kwargs: Any) -> Any:
            raise openai.APIConnectionError(request=request)

    embedder = OpenAICompatEmbedder(model="bge-m3", client=SimpleNamespace(embeddings=_DownEmbeddings()))
    with pytest.raises(EmbedError, match="APIConnectionError") as info:
        embedder.embed(["文本"])
    assert isinstance(info.value.__cause__, openai.APIConnectionError)


def test_load_settings_reads_judge_panel(tmp_path: Path) -> None:
    path = tmp_path / "twin.toml"
    path.write_text(
        """
[llm]
model = "GLM-5.3-Flash"
base_url = "http://10.0.0.8:8000/v1"

[[judges]]
model = "deepseek-flash"
base_url = "https://api.deepseek.com"
api_key_env = "TWIN_JUDGE1_KEY"

[[judges]]
provider = "anthropic"
effort_extract = "high"
""",
        encoding="utf-8",
    )
    s = load_settings(path)
    assert [(j.provider, j.model, j.api_key_env) for j in s.judges] == [
        ("openai_compat", "deepseek-flash", "TWIN_JUDGE1_KEY"),
        ("anthropic", None, "TWIN_LLM_KEY"),
    ]
    assert s.judges[1].effort_extract == "high"
    assert (s.llm.provider, s.llm.model) == ("openai_compat", "GLM-5.3-Flash")


def test_openai_compat_backends_never_fall_back_to_the_public_openai_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    with pytest.raises(ValueError, match=r"\[llm\].*base_url"):
        make_llm(LLMSettings(provider="openai_compat", model="qwen"))
    with pytest.raises(ValueError, match=r"\[embed\].*base_url"):
        make_embedder(EmbedSettings(provider="openai_compat"))
    with pytest.raises(ValueError, match="base_url"):
        make_llm(LLMSettings(provider="openai_compat", model="qwen", base_url=""))

    monkeypatch.setenv("OPENAI_BASE_URL", "http://10.0.0.8:8000/v1")
    llm = make_llm(LLMSettings(provider="openai_compat", model="qwen"))
    embedder = make_embedder(EmbedSettings(provider="openai_compat"))
    assert isinstance(llm, OpenAICompatLLM)
    assert isinstance(embedder, OpenAICompatEmbedder)
    assert str(llm._client.base_url) == str(embedder._client.base_url) == "http://10.0.0.8:8000/v1/"


def test_openai_compat_key_env_defaults_do_not_reuse_openai_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    assert LLMSettings().api_key_env == "TWIN_LLM_KEY"
    assert EmbedSettings().api_key_env == "TWIN_EMBED_KEY"
    monkeypatch.setenv("OPENAI_API_KEY", "sk-personal")
    monkeypatch.delenv("TWIN_LLM_KEY", raising=False)
    monkeypatch.delenv("TWIN_EMBED_KEY", raising=False)
    llm = make_llm(LLMSettings(provider="openai_compat", model="qwen", base_url="http://10.0.0.8:8000/v1"))
    embedder = make_embedder(EmbedSettings(provider="openai_compat", base_url="http://10.0.0.9:8080/v1"))
    assert isinstance(llm, OpenAICompatLLM)
    assert isinstance(embedder, OpenAICompatEmbedder)
    assert llm._client.api_key == embedder._client.api_key == "EMPTY"


def test_normalize_for_match() -> None:
    assert normalize_for_match("ＡＢＣ　１２３") == "abc123"
    assert normalize_for_match("“这个，不行！” 先看数据……OK?") == "这个不行先看数据ok"
    assert normalize_for_match(" a_b-c\n\td ") == "abcd"
    once = normalize_for_match("预算（Budget）超了 20%。")
    assert once == "预算budget超了20"
    assert normalize_for_match(once) == once


def test_run_parallel_keeps_input_order_and_captures_failures() -> None:
    messages: list[str] = []
    completed: list[int] = []
    lock = threading.Lock()
    done = [threading.Event() for _ in range(5)]

    def progress(msg: str) -> None:
        with lock:
            messages.append(msg)

    def fn(i: int) -> int:
        if i < 4 and not done[i + 1].wait(timeout=5):
            raise TimeoutError(i)
        with lock:
            completed.append(i)
        done[i].set()
        if i % 2:
            raise ValueError(f"bad {i}")
        return i * 10

    results = run_parallel(fn, [0, 1, 2, 3, 4], max_workers=5, progress=progress, label=lambda i: f"item{i}")
    assert completed == [4, 3, 2, 1, 0]
    assert [results[i] for i in (0, 2, 4)] == [0, 20, 40]
    for i in (1, 3):
        error = results[i]
        assert isinstance(error, ValueError)
        assert str(error) == f"bad {i}"
    assert sorted(messages) == sorted(
        ["ok item0", "ok item2", "ok item4", "FAILED item1: ValueError: bad 1", "FAILED item3: ValueError: bad 3"]
    )
    assert run_parallel(fn, [], max_workers=2) == []
    assert run_parallel(lambda x: x + 1, [1, 2, 3], max_workers=0) == [2, 3, 4]


def test_run_parallel_reports_each_result_in_the_calling_thread_as_it_completes() -> None:
    caller = threading.get_ident()
    seen: list[tuple[int, int | str, int]] = []
    release = threading.Event()

    def fn(i: int) -> int:
        if i == 0 and not release.wait(timeout=5):
            raise TimeoutError
        if i == 2:
            raise ValueError("bad 2")
        return i * 10

    def on_result(item: int, outcome: int | Exception) -> None:
        seen.append((item, outcome if isinstance(outcome, int) else str(outcome), threading.get_ident()))
        if len(seen) == 2:
            release.set()

    results = run_parallel(fn, [0, 1, 2], max_workers=3, on_result=on_result)

    assert results[:2] == [0, 10] and isinstance(results[2], ValueError)
    assert sorted(seen) == [(0, 0, caller), (1, 10, caller), (2, "bad 2", caller)]
    assert seen[-1][0] == 0  # item 0 finished last, and was reported when it did


def test_run_parallel_interrupt_cancels_queued_items() -> None:
    started: list[int] = []
    reported: list[int] = []
    gate, after_gate = threading.Event(), threading.Event()

    def fn(i: int) -> int:
        started.append(i)
        if i == 2:
            raise KeyboardInterrupt
        if i == 3:  # keeps the only worker busy until the interrupt has been handled
            gate.wait(timeout=5)
            after_gate.set()
        return i

    with pytest.raises(KeyboardInterrupt):
        run_parallel(fn, list(range(10)), max_workers=1, on_result=lambda item, _: reported.append(item))
    gate.set()
    assert after_gate.wait(timeout=5)
    time.sleep(0.05)  # room for the worker to (wrongly) pick up another queued item

    assert started == [0, 1, 2, 3]
    assert sorted(reported) == [0, 1]  # finished before the interrupt: reported even if seen after it


def test_run_parallel_on_result_errors_propagate() -> None:
    def on_result(item: int, outcome: int | Exception) -> None:
        raise sqlite3.OperationalError("disk full")

    with pytest.raises(sqlite3.OperationalError, match="disk full"):
        run_parallel(lambda i: i, [1, 2, 3], max_workers=2, on_result=on_result)


def test_escape_csv_cell() -> None:
    for formula in ("=SUM(A1)", "+1", "-2", "@x", "  =1", "＝1"):
        assert escape_csv_cell(formula) == "'" + formula
    assert escape_csv_cell("本人认为=") == "本人认为="
    assert escape_csv_cell("") == ""


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits")
def test_open_private_creates_and_tightens_owner_only_files(tmp_path: Path) -> None:
    fresh = tmp_path / "fresh.md"
    with open_private(fresh) as f:
        f.write("会议原话")
    assert _mode(fresh) == 0o600 and fresh.read_text(encoding="utf-8") == "会议原话"

    existing = tmp_path / "existing.csv"
    existing.write_text("old content that is longer", encoding="utf-8")
    existing.chmod(0o644)
    with open_private(existing, encoding="utf-8-sig", newline="") as f:
        f.write("a,b\r\n")
    assert _mode(existing) == 0o600
    assert existing.read_bytes() == "a,b\r\n".encode("utf-8-sig")


def test_stable_id() -> None:
    a = stable_id("it", "m1#e00#c00", "m2#e01#c03")
    assert a == stable_id("it", "m1#e00#c00", "m2#e01#c03")
    assert a.startswith("it_")
    digest = a.removeprefix("it_")
    assert len(digest) == 12
    assert all(ch in "0123456789abcdef" for ch in digest)
    assert a != stable_id("it", "m2#e01#c03", "m1#e00#c00")
    assert stable_id("it", "ab", "c") != stable_id("it", "a", "bc")


def _mode(path: Path) -> int:
    return path.stat().st_mode & 0o777
