"""Web routes of the questions the twin could not answer (``/api/persona/followups...``): the queue, the person's
answers, which become new memories, and setting a question aside."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from ..config import Settings
from ..persona.followups import answer_followup, list_followups, set_followup
from ..persona.store import PersonaStore, stored_identity


class AnswerBody(BaseModel):
    text: str = Field(min_length=1, max_length=20000)


class FollowupStatusBody(BaseModel):
    status: Literal["pending", "dismissed"]


def register(app: FastAPI, settings: Settings, queue_build: Callable[[], None]) -> None:
    @app.get("/api/persona/followups")
    def list_all() -> dict[str, Any]:
        with PersonaStore(settings.db_path) as store:
            items = list_followups(store)
        return {"items": [asdict(f) for f in items], "pending": sum(1 for f in items if f.status == "pending")}

    @app.post("/api/persona/followups/{followup_id}/answer")
    def answer(followup_id: str, body: AnswerBody) -> dict[str, Any]:
        """Keep the answer as a new memory in the person's own words, then process it like any new memory."""
        name = stored_identity(settings.db_path)[0] or settings.target_name
        with PersonaStore(settings.db_path) as store:
            try:
                followup, source = answer_followup(store, followup_id, body.text, name)
            except KeyError as e:
                raise HTTPException(404, "找不到这个问题，请刷新后重试") from e
            except ValueError as e:
                raise HTTPException(400, str(e)) from e
        queue_build()
        return {"followup": asdict(followup), "source_id": source.source_id, "source_title": source.title}

    @app.post("/api/persona/followups/{followup_id}/status")
    def set_status(followup_id: str, body: FollowupStatusBody) -> dict[str, Any]:
        with PersonaStore(settings.db_path) as store:
            try:
                return asdict(set_followup(store, followup_id, body.status))
            except KeyError as e:
                raise HTTPException(404, "找不到这个问题，请刷新后重试") from e
