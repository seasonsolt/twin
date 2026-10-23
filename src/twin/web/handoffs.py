"""Web routes of the handoffs (``/api/persona/handoffs...``): what a colleague's question left to the person, for the
person alone. A manager, a visitor or anyone who is not the person the twin is made for gets nothing here."""

from __future__ import annotations

import datetime as dt
import sqlite3
from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from ..config import Settings
from ..handoffs import AWAY_DAYS, KIND_LABELS, STATUS_LABELS, HandoffDesk, HandoffRefused
from ..llm import LLMError
from ..persona.store import PersonaStore
from ..persona.tiers import SELF
from ..teamdb import Handoff
from .backends import Backends
from .conversations import owner, request_audience


class ReplyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=4000)
    # Keep the reply as a memory too; False writes it into the conversation only.
    remember: bool = True


class AcceptBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # A new date for the promise (改时间); the asker's own is kept when it is left out.
    due: dt.date | None = None


class CorrectBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=4000)


def person(request: Request) -> str | None:
    """The person the twin is made for, who alone may read and settle its handoffs (any other signed-in person,
    managers included, is refused); returns their account."""
    if request_audience(request) != SELF or request.scope.get("twin_visitor"):
        raise HTTPException(403, "这些只有本人看得到")
    return owner(request)


def register(
    app: FastAPI, settings: Settings, desk: HandoffDesk, queue_build: Callable[[], None], backends: Backends
) -> None:
    def refused(failure: Exception) -> HTTPException:
        if isinstance(failure, KeyError):
            return HTTPException(404, "找不到这条，请刷新后重试")
        return HTTPException(409, str(failure))

    def settled(h: Handoff, me: str | None, *, remembered: bool = False) -> dict[str, Any]:
        with PersonaStore(settings.db_path) as store:
            view = desk.view(h, store)
        if remembered:
            queue_build()
        return {"handoff": view, "pending": desk.pending_count(me)}

    def team_ready() -> None:
        if desk.team is None:
            raise HTTPException(503, "团队库没有打开")

    @app.get("/api/persona/handoffs")
    def list_handoffs(request: Request) -> dict[str, Any]:
        """Everything on the person's 你不在时 page."""
        me = person(request)
        team_ready()
        try:
            away = desk.away(me)
        except sqlite3.Error as e:
            raise HTTPException(503, "团队库暂时读不了，请稍后重试") from e
        return {
            "waiting": away.waiting,
            "guessed": away.guessed,
            "sourced": away.sourced,
            "sourced_count": away.sourced_count,
            "answered": away.answered,
            "shelved": away.shelved,
            "settled": away.settled,
            "pending": len(away.waiting),
            "days": AWAY_DAYS,
            "kind_labels": KIND_LABELS,
            "status_labels": STATUS_LABELS,
        }

    @app.get("/api/persona/handoffs/count")
    def count_handoffs(request: Request) -> dict[str, int]:
        """How many wait for the person's decision: the number on their account."""
        me = person(request)
        team_ready()
        return {"pending": desk.pending_count(me)}

    @app.post("/api/persona/handoffs/{handoff_id}/reply")
    def reply(handoff_id: str, body: ReplyBody, request: Request) -> dict[str, Any]:
        """The person's own reply: it appears in the asker's conversation as theirs, and is kept as a memory."""
        me = person(request)
        team_ready()
        try:
            h = desk.reply(handoff_id, me, body.text, remember=body.remember)
        except (KeyError, HandoffRefused) as e:
            raise refused(e) from e
        return settled(h, me, remembered=body.remember)

    @app.post("/api/persona/handoffs/{handoff_id}/draft")
    def draft(handoff_id: str, request: Request) -> dict[str, str]:
        """请分身起草: words for the person to change and send; nothing is sent or kept."""
        me = person(request)
        team_ready()
        llm, embedder = backends.chat_llm(), backends.embedder()
        try:
            text = desk.draft(handoff_id, me, llm, embedder, settings)
        except (KeyError, HandoffRefused) as e:
            raise refused(e) from e
        except LLMError:
            # What a model backend says can hold prompts or addresses: not passed on.
            raise HTTPException(502, "分身暂时无法起草，请重试") from None
        return {"text": text}

    @app.post("/api/persona/handoffs/{handoff_id}/accept")
    def accept(handoff_id: str, request: Request, body: AcceptBody | None = None) -> dict[str, Any]:
        me = person(request)
        team_ready()
        try:
            h = desk.accept(handoff_id, me, body.due if body else None)
        except (KeyError, HandoffRefused) as e:
            raise refused(e) from e
        return settled(h, me)

    @app.post("/api/persona/handoffs/{handoff_id}/decline")
    def decline(handoff_id: str, request: Request) -> dict[str, Any]:
        me = person(request)
        team_ready()
        try:
            h = desk.decline(handoff_id, me)
        except (KeyError, HandoffRefused) as e:
            raise refused(e) from e
        return settled(h, me)

    @app.post("/api/persona/handoffs/{handoff_id}/dismiss")
    def dismiss(handoff_id: str, request: Request) -> dict[str, Any]:
        me = person(request)
        team_ready()
        try:
            h = desk.dismiss(handoff_id, me)
        except (KeyError, HandoffRefused) as e:
            raise refused(e) from e
        return settled(h, me)

    @app.post("/api/persona/handoffs/{handoff_id}/restore")
    def restore(handoff_id: str, request: Request) -> dict[str, Any]:
        me = person(request)
        team_ready()
        try:
            h = desk.restore(handoff_id, me)
        except (KeyError, HandoffRefused) as e:
            raise refused(e) from e
        return settled(h, me)

    @app.post("/api/persona/answers/{conversation_id}/{turn}/confirm")
    def confirm_answer(conversation_id: str, turn: int, request: Request) -> dict[str, bool]:
        """没错: an answer the twin guessed was right."""
        person(request)
        team_ready()
        try:
            desk.confirm_answer(conversation_id, turn)
        except KeyError as e:
            raise refused(e) from e
        return {"confirmed": True}

    @app.post("/api/persona/answers/{conversation_id}/{turn}/correct")
    def correct_answer(conversation_id: str, turn: int, body: CorrectBody, request: Request) -> dict[str, Any]:
        """更正: the person puts right an answer the twin guessed; the asker is told and the twin remembers it."""
        me = person(request)
        team_ready()
        try:
            h = desk.correct_answer(conversation_id, turn, me, body.text)
        except (KeyError, HandoffRefused) as e:
            raise refused(e) from e
        return settled(h, me, remembered=True)
