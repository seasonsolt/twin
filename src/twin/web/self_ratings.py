"""Web routes of 自评记录 (``/api/persona/self-ratings``, see ``persona.self_ratings``): the person marks an answer of
their twin's in their own conversation 像我 or 不像我, and the marks are read back for evaluation. For the person
alone."""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from ..persona import self_ratings
from ..persona.store import PersonaStore
from .handoffs import person


class RateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conversation_id: str = Field(min_length=1, max_length=64)
    # The answer as the twin gave it; found among the turns the conversation saved.
    reply: str = Field(min_length=1, max_length=20000)
    # None takes the mark back.
    rating: self_ratings.Rating | None


def register(
    app: FastAPI,
    lock: AbstractContextManager[Any],
    open_store: Callable[[], AbstractContextManager[PersonaStore]],
) -> None:
    @app.put("/api/persona/self-ratings")
    def rate(body: RateBody, request: Request) -> dict[str, Any]:
        """Mark an answer of the twin's in the person's own conversation 像我 or 不像我, or take the mark back."""
        me = person(request)
        try:
            with lock, open_store() as store:
                conversation = store.get_conversation(body.conversation_id, me)
                rating = self_ratings.rate(store, conversation, body.reply, body.rating, dt.datetime.now())
        except KeyError:
            raise HTTPException(404, "找不到这条回答，请刷新后重试") from None
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        return {"rating": rating}

    @app.get("/api/persona/self-ratings")
    def ratings(request: Request) -> dict[str, Any]:
        """Every mark kept, oldest first, with what was asked and answered: the material of the evaluation."""
        person(request)
        with open_store() as store:
            kept = self_ratings.load(store)
        return {"labels": self_ratings.RATING_LABELS, "ratings": [r.model_dump() for r in kept]}
