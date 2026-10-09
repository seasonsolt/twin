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
    "询问此人的数字分身：答案依据本人资料，依据不足时可能弃权。"
    " Answers are grounded in the person's material and may abstain."
)
IDENTITY_DESCRIPTION = "查看分身的名字、预置形象和音色，不返回授权或备注。 View the twin's name, avatar and voice."


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
        text = answer.answer
        if answer.abstain:
            text += f"\n弃权：{answer.abstain_reason}"
        elif answer.mode == "inferred":
            text += "\n（推测，非本人表达）"
        return CallToolResult(
            content=[TextContent(type="text", text=text)], structuredContent=answer.model_dump(mode="json")
        )

    def twin_identity(self) -> Annotated[CallToolResult, ServiceIdentity]:
        identity = public_identity(self.settings)
        return CallToolResult(
            content=[TextContent(type="text", text=identity.name)],
            structuredContent=identity.model_dump(mode="json"),
        )


def create_mcp_server(settings: Settings, chat_factory: ChatFactory | None = None) -> FastMCP:
    # SDK stream-error logging can include invalid payloads; keep it off stderr.
    server = FastMCP("twin", log_level="CRITICAL")
    tools = TwinTools(settings, chat_factory)
    server.tool(name="ask_twin", description=ASK_DESCRIPTION)(tools.ask_twin)
    server.tool(name="twin_identity", description=IDENTITY_DESCRIPTION)(tools.twin_identity)
    return server
