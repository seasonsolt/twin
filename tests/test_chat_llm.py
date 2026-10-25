from __future__ import annotations

import asyncio
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import httpx
import openai
import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel, ValidationError

from twin import api
from twin.config import LLMSettings, Settings, load_settings, make_llm, with_fallback
from twin.egress import egress_status
from twin.embed import HashingEmbedder
from twin.llm import FakeLLM, FallbackLLM, LimitedLLM, LLMError, LLMInvalidOutput, LLMRefusal, failure_kind
from twin.persona.items import PersonaItem
from twin.persona.schema import ChatDraft
from twin.persona.store import PersonaStore
from twin.web import create_app
from twin.web.backends import Backends
from twin.web.system import SystemSettings


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in tuple(os.environ):
        if name.startswith(("TWIN_", "DTWIN_", "OPENAI_", "ANTHROPIC_")):
            monkeypatch.delenv(name)


@pytest.mark.parametrize("configured", [False, True])
def test_config_parses_chat_model_and_extra_body(tmp_path: Path, configured: bool) -> None:
    path = tmp_path / "twin.toml"
    text = '[llm]\nmodel = "build"\nextra_body = { nested = { enabled = true }, flags = [1, "x"] }\n'
    if configured:
        example = Path("twin.toml.example").read_text()
        start = example.index("# [chat_llm]\n")
        end = example.index("\n\n[embed]", start)
        settings_lines = [line for line in example[start:end].splitlines() if re.match(r"# (\[|\w+ = )", line)]
        text += "\n" + "\n".join(line.removeprefix("# ") for line in settings_lines)
    path.write_text(text)
    settings = load_settings(path)
    assert settings.llm.extra_body == {"nested": {"enabled": True}, "flags": [1, "x"]}
    if configured:
        chat = settings.effective_chat_llm
        assert chat is settings.chat_llm
        assert (chat.provider, chat.model, chat.base_url, chat.api_key_env, chat.json_mode) == (
            "openai_compat",
            "deepseek-flash",
            "https://api.deepseek.com",
            "TWIN_LLM_KEY_DEEPSEEK",
            "json_object",
        )
        assert chat.extra_body == {"thinking": {"type": "disabled"}}
        assert chat.reasoning_effort is None
        row = next(row for row in egress_status(settings, external_only=True) if row["kind"] == "chat_llm")
        assert row["host"] == "api.deepseek.com" and row["external"]
        fallback = settings.llm_fallback
        assert fallback is not None and (fallback.model, fallback.api_key_env) == ("glm-5.3", "TWIN_LLM_FALLBACK_KEY")
        assert fallback.extra_body == {"thinking": {"type": "disabled"}}
    else:
        assert settings.chat_llm is None and settings.effective_chat_llm is settings.llm
        assert not any(row["kind"] == "chat_llm" for row in egress_status(settings))


@pytest.mark.parametrize("table", ["llm", "chat_llm"])
@pytest.mark.parametrize(
    "field,value", [("timeout", 0), ("max_retries", -1), ("json_mode", "invalid"), ("extra_body", [])]
)
def test_chat_config_validates_like_main_llm(table: str, field: str, value: Any) -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate({table: {field: value}})


def test_extra_body_reaches_openai_request_and_json_repair(monkeypatch: pytest.MonkeyPatch) -> None:
    bodies: list[dict[str, Any]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        content = (
            "invalid"
            if len(bodies) == 1
            else json.dumps({"reply": "未知", "citations": [], "confidence": 0.1, "abstain": True})
        )
        return httpx.Response(
            200,
            json={
                "id": "offline",
                "object": "chat.completion",
                "created": 0,
                "model": "deepseek-flash",
                "choices": [
                    {"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": content}}
                ],
            },
        )

    original = openai.OpenAI
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        monkeypatch.setattr(openai, "OpenAI", lambda **kwargs: original(**kwargs, http_client=client))
        config = LLMSettings(
            model="deepseek-flash", base_url="https://api.deepseek.com", extra_body={"thinking": {"type": "disabled"}}
        )
        llm = make_llm(config, "chat_llm")
        assert llm.structured(system="s", user="u", schema=ChatDraft).abstain
    assert len(bodies) == 2
    for body in bodies:
        assert body["thinking"] == {"type": "disabled"}
        assert body["response_format"] == {"type": "json_object"}
        assert "reasoning_effort" not in body
    assert config.extra_body == {"thinking": {"type": "disabled"}}


@pytest.mark.parametrize("configured", [False, True])
def test_web_and_service_chat_select_and_cache_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, configured: bool
) -> None:
    main = LLMSettings(model="build", effort_twin="low")
    chat = LLMSettings(model="chat", effort_twin="high") if configured else None
    settings = Settings(db_path=tmp_path / "twin.db", llm=main, chat_llm=chat)
    with PersonaStore(settings.db_path) as store:
        store.replace_facet_items(
            "2.1", [PersonaItem(item_id="pi_test", facet_id="2.1", statement="虚构条目", evidence=[])]
        )
        store.set_meta("built_at", "2026-01-01")
    calls: list[tuple[LLMSettings, str]] = []
    answers: list[str] = []

    def factory(config: LLMSettings, section: str = "llm") -> FakeLLM:
        calls.append((config, section))

        def answer(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
            assert schema is ChatDraft
            answers.append(config.model or "")
            return {"reply": config.model, "citations": [], "confidence": 0.1, "abstain": True}

        return FakeLLM(answer)

    monkeypatch.setattr("twin.web.backends.make_llm", factory)
    monkeypatch.setattr(api, "make_llm", factory)
    monkeypatch.setattr(api, "make_embedder", lambda _: HashingEmbedder())
    expected = settings.effective_chat_llm
    backends = Backends(settings, None, None)
    assert backends.chat_llm() is backends.chat_llm()
    if configured:
        assert backends.llm() is not backends.chat_llm()
        assert calls == [(expected, "chat_llm"), (main, "llm")]
    else:
        assert backends.chat_llm() is backends.llm()
        assert calls == [(main, "llm")]
    calls.clear()

    with TestClient(create_app(settings), base_url="http://127.0.0.1") as client:
        response = client.post(
            "/api/persona/chat", headers={"X-Twin": "1"}, json={"messages": [{"role": "user", "content": "问题"}]}
        )
        assert response.status_code == 202
        job_id = response.json()["job_id"]
        deadline = time.monotonic() + 5
        while True:
            job = client.get(f"/api/jobs/{job_id}").json()
            if job["status"] in {"done", "failed"} or time.monotonic() >= deadline:
                break
            time.sleep(0.01)
        assert job["status"] == "done", job
        assert job["result"]["reply"] == expected.model
    backend = api.ServiceBackend(settings)
    assert backend.ask("问题", None).answer == expected.model
    assert backend.ask("问题", None).answer == expected.model
    assert calls == [(expected, "chat_llm" if configured else "llm")] * 2
    assert answers == [expected.model] * 3


def test_failure_summary_names_fields_and_stop_reason_without_content() -> None:
    from twin.llm import LLMInvalidOutput, failure_summary

    class Shape(BaseModel):
        count: int
        names: list[str]

    try:
        Shape.model_validate_json('{"count": "SECRET"}')
    except ValidationError as cause:
        error = LLMInvalidOutput(f"model: {cause}", stop_reason="end_turn")
        error.__cause__ = cause
    summary = failure_summary(error)
    assert summary == "LLMInvalidOutput [stop=end_turn; int_parsing@count, missing@names]"
    assert "SECRET" not in summary
    assert failure_summary(ValueError("SECRET")) == "ValueError"


class _Status(Exception):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code


def _failing(cause: Exception) -> LLMError:
    try:
        raise LLMError("primary failed") from cause
    except LLMError as error:
        return error


def test_the_fallback_answers_while_the_main_model_is_out_of_quota() -> None:
    now = [0.0]
    tried: list[str] = []

    def primary_answer(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
        tried.append("primary")
        raise _failing(_Status(429))

    fallback = FakeLLM(lambda *_: {"reply": "备选", "citations": [], "confidence": 0.1, "abstain": True})
    llm = FallbackLLM(FakeLLM(primary_answer), fallback, rest=300, clock=lambda: now[0])
    assert llm.structured(system="s", user="u", schema=ChatDraft).reply == "备选"
    assert llm.structured(system="s", user="u", schema=ChatDraft).reply == "备选"
    assert tried == ["primary"]  # resting: the second call went straight to the fallback
    now[0] = 301
    llm.structured(system="s", user="u", schema=ChatDraft)
    assert tried == ["primary", "primary"]


@pytest.mark.parametrize("error", [LLMInvalidOutput("bad json"), _failing(_Status(400)), LLMError("no cause")])
def test_a_failure_of_the_request_itself_is_not_handed_to_the_fallback(error: LLMError) -> None:
    def primary_answer(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
        raise error

    used: list[str] = []
    fallback = FakeLLM(lambda *_: used.append("fallback") or {"reply": "x", "citations": [], "confidence": 0.1})
    with pytest.raises(LLMError):
        FallbackLLM(FakeLLM(primary_answer), fallback).structured(system="s", user="u", schema=ChatDraft)
    assert used == []


def test_a_chat_stream_falls_back_before_its_first_words() -> None:
    class Streaming(FakeLLM):
        def __init__(self, texts: list[str], error: Exception | None = None) -> None:
            super().__init__(lambda *_: {})
            self.texts, self.error = texts, error

        async def stream(self, **options: Any) -> Any:
            if self.error is not None:
                raise self.error
            for text in self.texts:
                yield text

    async def collect(llm: FallbackLLM) -> list[str]:
        return [text async for text in llm.stream(system="s", user="u")]

    down = Streaming([], _failing(openai.APIConnectionError(request=httpx.Request("POST", "http://x"))))
    assert asyncio.run(collect(FallbackLLM(down, Streaming(["你", "好"])))) == ["你", "好"]
    refused = Streaming([], LLMRefusal("refused"))
    with pytest.raises(LLMRefusal):
        asyncio.run(collect(FallbackLLM(refused, Streaming(["你"]))))


def test_the_web_backends_wrap_the_models_with_the_configured_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TWIN_LLM_KEY", "k")
    monkeypatch.setenv("TWIN_FALLBACK_KEY", "f")
    hosts: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        hosts.append(request.url.host)
        if request.url.host == "main.test":
            return httpx.Response(
                429, json={"error": {"message": "ApiKey已触发限额", "code": "apikey_quota_exhausted"}}
            )
        content = json.dumps({"reply": "备选回答", "citations": [], "confidence": 0.1, "abstain": True})
        return httpx.Response(
            200,
            json={
                "id": "offline",
                "object": "chat.completion",
                "created": 0,
                "model": "glm",
                "choices": [
                    {"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": content}}
                ],
            },
        )

    original = openai.OpenAI
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        monkeypatch.setattr(openai, "OpenAI", lambda **kwargs: original(**kwargs, http_client=client))
        settings = Settings(
            db_path=tmp_path / "twin.db",
            llm=LLMSettings(model="flash", base_url="https://main.test/v1", max_retries=0),
            llm_fallback=LLMSettings(
                model="glm", base_url="https://fallback.test/v1", api_key_env="TWIN_FALLBACK_KEY", max_retries=0
            ),
        )
        backends = Backends(settings, None, None)
        assert isinstance(backends.llm(), FallbackLLM) and isinstance(backends.chat_llm(), FallbackLLM)
        assert backends.llm().structured(system="s", user="u", schema=ChatDraft).reply == "备选回答"
    assert hosts == ["main.test", "fallback.test"]
    assert not isinstance(Backends(Settings(db_path=tmp_path / "twin.db"), None, None)._llm_factory, FallbackLLM)


def test_the_fallback_takes_only_so_many_calls_at_once() -> None:
    running, peak = [0], [0]
    lock = threading.Lock()

    def answer(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
        with lock:
            running[0] += 1
            peak[0] = max(peak[0], running[0])
        time.sleep(0.05)
        with lock:
            running[0] -= 1
        return {"reply": "备选", "citations": [], "confidence": 0.1, "abstain": True}

    def down(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
        raise _failing(_Status(429))

    llm = FallbackLLM(FakeLLM(down), FakeLLM(answer), concurrent=2)
    with ThreadPoolExecutor(8) as pool:
        replies = list(pool.map(lambda _: llm.structured(system="s", user="u", schema=ChatDraft).reply, range(8)))
    assert replies == ["备选"] * 8 and peak[0] == 2


def test_a_limited_backend_takes_only_so_many_calls_at_once_and_a_raised_limit_at_once() -> None:
    limit, running, peak = [1], [0], [0]
    lock = threading.Lock()

    def answer(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
        with lock:
            running[0] += 1
            peak[0] = max(peak[0], running[0])
        time.sleep(0.05)
        with lock:
            running[0] -= 1
        return {"reply": "主模型", "citations": [], "confidence": 0.1, "abstain": True}

    llm = LimitedLLM(FakeLLM(answer), lambda: limit[0])
    assert llm.name == "fake"
    ask = lambda _: llm.structured(system="s", user="u", schema=ChatDraft).reply  # noqa: E731
    with ThreadPoolExecutor(6) as pool:
        assert list(pool.map(ask, range(6))) == ["主模型"] * 6
    assert peak[0] == 1
    limit[0] = 3
    with ThreadPoolExecutor(6) as pool:
        assert list(pool.map(ask, range(6))) == ["主模型"] * 6
    assert peak[0] == 3


def test_a_failure_is_logged_by_kind_without_its_message() -> None:
    assert failure_kind(_failing(_Status(429))) == "LLMError(429)"
    timeout = _failing(openai.APITimeoutError(request=httpx.Request("POST", "http://x")))
    assert failure_kind(timeout) == "LLMError(APITimeoutError)"
    assert failure_kind(LLMInvalidOutput("会议原文")) == "LLMInvalidOutput"


def test_an_administrator_sets_how_many_calls_the_fallback_takes_at_once(tmp_path: Path) -> None:
    settings = Settings(
        db_path=tmp_path / "twin.db", llm_fallback=LLMSettings(model="glm", base_url="http://fallback.test/v1")
    )
    llm = with_fallback(FakeLLM(lambda *_: {}), settings)
    assert isinstance(llm, FallbackLLM) and llm._turns._limit() == 4
    system = SystemSettings(settings, tmp_path / "system.json", env_file=tmp_path / ".env")
    system.set_param("llm_fallback.max_concurrent", 2, "admin")
    assert llm._turns._limit() == 2
    with pytest.raises(ValueError):
        system.set_param("llm_fallback.max_concurrent", 0, "admin")
    unconfigured = SystemSettings(Settings(db_path=tmp_path / "t.db"), tmp_path / "s.json", env_file=tmp_path / ".e")
    assert "llm_fallback.max_concurrent" not in {p["key"] for p in unconfigured.params_view()}
