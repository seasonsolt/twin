"""Persona-scoped, private conversation history."""

from __future__ import annotations

import datetime as dt
import logging
import sqlite3
from contextlib import suppress
from typing import Any, Literal
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator

from ..config import Settings
from ..persona.store import PersonaStore
from ..persona.tiers import COLLEAGUE, SELF, Audience
from ..teamdb import TeamDB

logger = logging.getLogger(__name__)


class SavedTurn(BaseModel):
    role: Literal["user", "twin"]
    content: str = Field(max_length=4000)
    timestamp: dt.datetime
    reply: dict[str, Any] | None = None


class CreateBody(BaseModel):
    turns: list[SavedTurn] = Field(default_factory=list, max_length=500)
    migration_id: UUID | None = None


class RenameBody(BaseModel):
    title: str = Field(min_length=1, max_length=200)

    @field_validator("title")
    @classmethod
    def trim_title(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("标题不能为空")
        return value.strip()


def owner(request: Request) -> str | None:
    return request.scope["twin_identity"]["email"]  # type: ignore[no-any-return]


def request_audience(request: Request) -> Audience:
    """The tier this signed-in person's conversations with the twin answer from (``Personas.audience``); the colleague
    tier where nothing says otherwise."""
    return SELF if request.scope.get("twin_audience") == SELF else COLLEAGUE


class ConversationIndex:
    """One twin's conversations in the team database (``teamdb``): written right after the twin's own database, and
    mended at startup if a write did not make it, so a failure here never fails the conversation."""

    def __init__(self, team: TeamDB | None, persona_id: str) -> None:
        self.team, self.persona_id = team, persona_id

    def created(self, store: PersonaStore, conversation_id: str, asker: str | None, audience: Audience) -> None:
        self._write(
            lambda team, head: team.record_conversation(
                conversation_id, self.persona_id, asker, audience, head[1], head[2]
            ),
            store,
            conversation_id,
        )

    def touched(self, store: PersonaStore, conversation_id: str | None) -> None:
        if conversation_id is None:
            return
        self._write(
            lambda team, head: team.refresh_conversation(conversation_id, head[1], head[2]), store, conversation_id
        )

    def deleted(self, conversation_id: str) -> None:
        if self.team is None:
            return
        try:
            self.team.delete_conversation(conversation_id)
        except sqlite3.Error:
            logger.warning("could not mark conversation %s deleted in the team index", conversation_id, exc_info=True)

    def audience(self, conversation_id: str | None, current: Audience) -> Audience:
        """The tier a chat answers from: the one the conversation was created with, but never more than the asker may
        have now (a person who gave the twin back no longer sees their own tier in it). A conversation the index does
        not know, or any failure to read it, is the colleague tier."""
        if conversation_id is None:
            return current
        if self.team is None:
            return current
        try:
            stored = self.team.audience_of(conversation_id)
        except sqlite3.Error:
            logger.warning("could not read conversation %s from the team index", conversation_id, exc_info=True)
            return COLLEAGUE
        return SELF if stored == SELF and current == SELF else COLLEAGUE

    def _write(self, write: Any, store: PersonaStore, conversation_id: str) -> None:
        if self.team is None:
            return
        head = store.conversation_head(conversation_id)
        if head is None:
            return
        try:
            write(self.team, head)
        except sqlite3.Error:
            logger.warning("could not index conversation %s in the team", conversation_id, exc_info=True)


def append_user(
    store: PersonaStore,
    conversation_id: str | None,
    email: str | None,
    content: str,
    index: ConversationIndex | None = None,
) -> None:
    if conversation_id is not None:
        try:
            store.append_conversation_turn(conversation_id, email, "user", content)
        except KeyError:
            raise HTTPException(404, "找不到这段对话") from None
        if index is not None:
            index.touched(store, conversation_id)


def append_reply(
    store: PersonaStore,
    conversation_id: str | None,
    email: str | None,
    payload: dict[str, Any],
    index: ConversationIndex | None = None,
) -> dict[str, Any]:
    if conversation_id is not None:
        # Deletion while a reply is running must not recreate the conversation.
        with suppress(KeyError):
            store.append_conversation_turn(conversation_id, email, "twin", payload["reply"], payload)
            if index is not None:
                index.touched(store, conversation_id)
    return payload


def register(app: FastAPI, settings: Settings, index: ConversationIndex) -> None:
    @app.get("/api/conversations")
    def list_conversations(request: Request, offset: int = Query(default=0, ge=0)) -> list[dict[str, Any]]:
        with PersonaStore(settings.db_path) as store:
            return store.list_conversations(owner(request), offset)

    @app.post("/api/conversations", status_code=201)
    def create_conversation(request: Request, body: CreateBody | None = None) -> dict[str, str]:
        body = body or CreateBody()
        with PersonaStore(settings.db_path) as store:
            try:
                conversation_id = store.create_conversation(
                    owner(request),
                    [turn.model_dump(mode="json") for turn in body.turns],
                    str(body.migration_id) if body.migration_id else None,
                )
            except KeyError:
                raise HTTPException(404, "找不到这段对话") from None
            # The tier is fixed here, once, and not worked out again at each question.
            index.created(store, conversation_id, owner(request), request_audience(request))
        return {"id": conversation_id}

    @app.get("/api/conversations/{conversation_id}")
    def get_conversation(conversation_id: str, request: Request) -> dict[str, Any]:
        with PersonaStore(settings.db_path) as store:
            try:
                return store.get_conversation(conversation_id, owner(request))
            except KeyError:
                raise HTTPException(404, "找不到这段对话") from None

    @app.patch("/api/conversations/{conversation_id}")
    def rename_conversation(conversation_id: str, body: RenameBody, request: Request) -> dict[str, bool]:
        with PersonaStore(settings.db_path) as store:
            if not store.rename_conversation(conversation_id, owner(request), body.title):
                raise HTTPException(404, "找不到这段对话")
            index.touched(store, conversation_id)
        return {"updated": True}

    @app.delete("/api/conversations/{conversation_id}")
    def delete_conversation(conversation_id: str, request: Request) -> dict[str, bool]:
        with PersonaStore(settings.db_path) as store:
            if not store.delete_conversation(conversation_id, owner(request)):
                raise HTTPException(404, "找不到这段对话")
        index.deleted(conversation_id)
        return {"deleted": True}
