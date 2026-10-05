"""Official FastMCP stdio entry point; no listeners or personal-text logging."""

from __future__ import annotations

import datetime as dt
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import CallToolResult, TextContent

from .api import BACKEND_UNAVAILABLE, ChatFactory, ServiceBackend
from .config import Settings
from .service import MAX_QUESTION_CHARS, QUESTION_TOO_LONG, ServiceAnswer, ServiceIdentity, public_identity

ASK_DESCRIPTION = (
    "询问此人的数字分身：答案是依据本人资料的 AI 模拟，不代表本人意见，依据不足时可能弃权。"
    " Answers are AI simulations grounded in the person's material and may abstain."
)
IDENTITY_DESCRIPTION = (
    "查看分身的名字、预置形象、音色和 AI 标识，不返回授权或备注；回答是本人资料支撑的 AI 模拟，可能弃权。"
    " This twin provides AI simulations grounded in the person's material and may abstain."
)


class TwinTools:
    def __init__(self, settings: Settings, chat_factory: ChatFactory | None = None) -> None:
        self.settings = settings
        self.backend = ServiceBackend(settings, chat_factory)

    def ask_twin(self, question: str, as_of: str | None = None) -> Annotated[CallToolResult, ServiceAnswer]:
        if len(question) > MAX_QUESTION_CHARS:
            raise ToolError(QUESTION_TOO_LONG)
        try:
            horizon = dt.date.fromisoformat(as_of) if as_of is not None else None
        except ValueError:
            raise ToolError("as_of 日期格式应为 YYYY-MM-DD") from None
        try:
            answer = self.backend.ask(question, horizon)
        except Exception:
            raise ToolError(BACKEND_UNAVAILABLE) from None
        text = f"{answer.label}\n{answer.answer}"
        if answer.abstain:
            text += f"\n弃权：{answer.abstain_reason}"
        return CallToolResult(
            content=[TextContent(type="text", text=text)], structuredContent=answer.model_dump(mode="json")
        )

    def twin_identity(self) -> Annotated[CallToolResult, ServiceIdentity]:
        identity = public_identity(self.settings)
        return CallToolResult(
            content=[TextContent(type="text", text=f"{identity.label}\n{identity.name}")],
            structuredContent=identity.model_dump(mode="json"),
        )


def create_mcp_server(settings: Settings, chat_factory: ChatFactory | None = None) -> FastMCP:
    # SDK stream-error logging can include invalid payloads; keep it off stderr.
    server = FastMCP("twin", log_level="CRITICAL")
    tools = TwinTools(settings, chat_factory)
    server.tool(name="ask_twin", description=ASK_DESCRIPTION)(tools.ask_twin)
    server.tool(name="twin_identity", description=IDENTITY_DESCRIPTION)(tools.twin_identity)
    return server
