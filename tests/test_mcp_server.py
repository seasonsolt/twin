from __future__ import annotations

import asyncio
import datetime as dt
import secrets
from collections.abc import Iterator
from pathlib import Path

import pytest
from mcp.server.fastmcp.exceptions import ToolError
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import TextContent
from typer.testing import CliRunner

from twin import cli
from twin.api import BACKEND_UNAVAILABLE
from twin.config import EmbedSettings, LLMSettings, Settings
from twin.embed import HashingEmbedder
from twin.llm import FakeLLM
from twin.mcp_server import TwinTools, create_mcp_server
from twin.persona.chat import PersonaChat
from twin.persona.store import PersonaStore
from twin.service import ServiceAnswer, answer_question


@pytest.fixture
def chat() -> Iterator[PersonaChat]:
    with PersonaStore(":memory:") as store:
        yield PersonaChat(
            store,
            FakeLLM(
                lambda *args: {
                    "reply": "需要本人确认。",
                    "citations": [],
                    "confidence": 0.2,
                    "abstain": True,
                    "abstain_reason": "没有依据",
                    "topic_facets": ["2.1"],
                }
            ),
            HashingEmbedder(),
            Settings(target_name="张三"),
        )


def test_direct_tools_match_service_contract(chat: PersonaChat) -> None:
    tools = TwinTools(chat.settings, lambda: chat)
    result = tools.ask_twin("未知问题", "2025-01-01")
    answer = ServiceAnswer.model_validate(result.structuredContent)
    expected = answer_question(chat, "未知问题", answer.as_of)
    assert answer.model_dump(exclude={"generated_at"}) == expected.model_dump(exclude={"generated_at"})
    assert isinstance(result.content[0], TextContent) and result.content[0].text.startswith(answer.answer)
    identity = tools.twin_identity()
    assert identity.structuredContent == {
        "name": "张三",
        "avatar": "chestnut",
        "voice": "default",
    }
    assert chat.store.chat_demand() == {}
    assert tools.backend.usage.summary()["totals"]["calls"] == 2


def test_direct_validation_and_backend_errors_are_private(
    chat: PersonaChat, capsys: pytest.CaptureFixture[str]
) -> None:
    tools = TwinTools(chat.settings, lambda: chat)
    with pytest.raises(ToolError, match="2000"):
        tools.ask_twin("私" * 2001)
    with pytest.raises(ToolError, match="YYYY-MM-DD") as error:
        tools.ask_twin("私密问题", "私密日期")
    assert "私" not in str(error.value)
    secret = secrets.token_urlsafe(32)

    def broken() -> PersonaChat:
        raise RuntimeError(f"私密问题 {secret}")

    with pytest.raises(ToolError, match=BACKEND_UNAVAILABLE) as error:
        TwinTools(chat.settings, broken).ask_twin("私密问题")
    assert "私" not in str(error.value) and secret not in str(error.value)
    assert not capsys.readouterr().err


def test_memory_session_round_trip(chat: PersonaChat, capsys: pytest.CaptureFixture[str]) -> None:
    async def run() -> None:
        server = create_mcp_server(chat.settings, lambda: chat)
        async with create_connected_server_and_client_session(server) as session:
            tools = (await session.list_tools()).tools
            assert {tool.name for tool in tools} == {"ask_twin", "twin_identity"}
            assert all(tool.description for tool in tools)
            assert all(tool.outputSchema for tool in tools)
            result = await session.call_tool("ask_twin", {"question": "私密问题", "as_of": "2025-01-01"})
            assert not result.isError and result.structuredContent
            assert result.structuredContent["as_of"] == "2025-01-01"
            assert isinstance(result.content[0], TextContent) and result.content[0].text.startswith(
                result.structuredContent["answer"]
            )
            identity = await session.call_tool("twin_identity", {})
            assert identity.structuredContent and set(identity.structuredContent) == {
                "name",
                "avatar",
                "voice",
            }
            bad = await session.call_tool("ask_twin", {"question": "私密问题", "as_of": "私密日期"})
            assert bad.isError and "私" not in str(bad)

    asyncio.run(run())
    assert "私密问题" not in capsys.readouterr().err
    assert chat.store.chat_demand() == {}


def test_inferred_answer_is_marked_in_the_text_result(chat: PersonaChat, monkeypatch: pytest.MonkeyPatch) -> None:
    tools = TwinTools(chat.settings, lambda: chat)
    inferred = ServiceAnswer(
        answer="我没直接说过，但大概会先问清楚。",
        abstain=False,
        abstain_reason="",
        confidence=0.5,
        citations=[],
        as_of=None,
        persona_name="张三",
        generated_at=dt.datetime.now(dt.UTC),
        mode="inferred",
    )
    monkeypatch.setattr(tools.backend, "ask", lambda *_: inferred)
    result = tools.ask_twin("如果被临时拉进会议你会怎么做？")
    assert isinstance(result.content[0], TextContent)
    assert result.content[0].text == f"{inferred.answer}\n（推测，非本人表达）"
    assert result.structuredContent is not None and result.structuredContent["mode"] == "inferred"


def test_external_backends_construct_without_grant(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(
        db_path=tmp_path / "twin.db",
        llm=LLMSettings(egress="external", base_url="https://external.invalid"),
        embed=EmbedSettings(provider="openai_compat", base_url="https://external.invalid"),
    )
    constructed: list[str] = []
    monkeypatch.setattr(
        "twin.api.make_llm",
        lambda _: (
            constructed.append("llm")
            or FakeLLM(
                lambda *_: {
                    "reply": "需要本人确认。",
                    "citations": [],
                    "confidence": 0.2,
                    "abstain": True,
                    "abstain_reason": "没有依据",
                }
            )
        ),
    )
    monkeypatch.setattr("twin.api.make_embedder", lambda _: constructed.append("embed") or HashingEmbedder())
    tools = TwinTools(settings)
    assert not settings.db_path.exists() and not constructed
    assert tools.ask_twin("私密问题").structuredContent
    assert constructed == ["llm", "embed"]

    async def run() -> None:
        async with create_connected_server_and_client_session(create_mcp_server(settings)) as session:
            result = await session.call_tool("ask_twin", {"question": "私密问题"})
            assert not result.isError and result.structuredContent
            assert "私密问题" not in str(result)

    asyncio.run(run())
    assert constructed == ["llm", "embed", "llm", "embed"]
    assert "私密问题" not in capsys.readouterr().err


def test_cli_runs_stdio_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import twin.mcp_server as module

    config = tmp_path / "twin.toml"
    config.write_text("", encoding="utf-8")
    monkeypatch.delenv("TWIN_API_TOKEN", raising=False)
    calls: list[str] = []

    class Server:
        def run(self, *, transport: str) -> None:
            calls.append(transport)

    monkeypatch.setattr(module, "create_mcp_server", lambda settings: Server())
    result = CliRunner().invoke(cli.app, ["--config", str(config), "mcp"])
    assert result.exit_code == 0 and calls == ["stdio"] and result.stdout == ""
