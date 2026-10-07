"""Persona-scoped, private conversation history."""

from __future__ import annotations

import datetime as dt
from contextlib import suppress
from typing import Any, Literal
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator

from ..config import Settings
from ..persona.store import PersonaStore


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


def append_user(store: PersonaStore, conversation_id: str | None, email: str | None, content: str) -> None:
    if conversation_id is not None:
        try:
            store.append_conversation_turn(conversation_id, email, "user", content)
        except KeyError:
            raise HTTPException(404, "找不到这段对话") from None


def append_reply(
    store: PersonaStore, conversation_id: str | None, email: str | None, payload: dict[str, Any]
) -> dict[str, Any]:
    if conversation_id is not None:
        # Deletion while a reply is running must not recreate the conversation.
        with suppress(KeyError):
            store.append_conversation_turn(conversation_id, email, "twin", payload["reply"], payload)
    return payload


def register(app: FastAPI, settings: Settings) -> None:
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
        return {"updated": True}

    @app.delete("/api/conversations/{conversation_id}")
    def delete_conversation(conversation_id: str, request: Request) -> dict[str, bool]:
        with PersonaStore(settings.db_path) as store:
            if not store.delete_conversation(conversation_id, owner(request)):
                raise HTTPException(404, "找不到这段对话")
        return {"deleted": True}
