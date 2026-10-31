"""Web routes of 告别一种陪伴 (``/api/persona/reflections``, see ``persona.companion``): the person puts one of the ways
of looking at themself away with a few closing words, and opens it again when they want it. For the person alone."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from ..persona import companion
from ..persona.reflection import Reflection
from ..persona.store import PersonaStore
from .handoffs import person


class CloseBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # Where the person said it, to keep the closing words there; none for a conversation not saved yet.
    conversation_id: str | None = Field(default=None, min_length=1, max_length=64)


def register(
    app: FastAPI,
    lock: AbstractContextManager[Any],
    open_store: Callable[[], AbstractContextManager[PersonaStore]],
) -> None:
    @app.get("/api/persona/reflections")
    def ways(request: Request) -> dict[str, Any]:
        """The ways the person has put away."""
        person(request)
        with open_store() as store:
            return {"closed": companion.closed(store)}

    @app.post("/api/persona/reflections/{reflection}/close")
    def close(reflection: Reflection, body: CloseBody, request: Request) -> dict[str, Any]:
        """Put a way away: the twin's closing words, kept in the conversation after the person's "先到这里"."""
        me = person(request)
        if reflection not in companion.CLOSABLE:
            raise HTTPException(400, "这种用法不能收起")
        with lock, open_store() as store:
            reply = {**companion.closing_reply(store, reflection).model_dump(mode="json"), "reflection": reflection}
            if body.conversation_id is not None:
                try:
                    store.append_conversation_turn(body.conversation_id, me, "user", companion.SAID)
                except KeyError:
                    raise HTTPException(404, "找不到这段对话") from None
                store.append_conversation_turn(body.conversation_id, me, "twin", reply["reply"], reply)
            companion.close(store, reflection)
            return {"reply": reply, "closed": companion.closed(store)}

    @app.post("/api/persona/reflections/{reflection}/open")
    def reopen(reflection: Reflection, request: Request) -> dict[str, Any]:
        """Open a way put away again."""
        person(request)
        with lock, open_store() as store:
            companion.reopen(store, reflection)
            return {"closed": companion.closed(store)}
