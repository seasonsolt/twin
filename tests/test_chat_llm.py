from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import httpx
import openai
import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel, ValidationError

from twin import api
from twin.config import LLMSettings, Settings, load_settings, make_llm
from twin.egress import egress_status
from twin.embed import HashingEmbedder
from twin.llm import FakeLLM
from twin.persona.items import PersonaItem
from twin.persona.schema import ChatDraft
from twin.persona.store import PersonaStore
from twin.web import create_app
from twin.web.backends import Backends


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
        text += "\n" + "\n".join(line.removeprefix("# ") for line in example[start:end].splitlines())
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
