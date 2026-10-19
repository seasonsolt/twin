"""Endpoints for saying which speaker of the waiting text transcripts is the person (see ``persona.transcripts``)."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from ..config import Settings
from ..persona import transcripts
from ..persona.store import PersonaStore

Name = Annotated[str, Field(min_length=1, max_length=transcripts.MAX_NAME_CHARS)]


class NamesBody(BaseModel):
    mine: list[Name] = Field(default_factory=list, max_length=transcripts.MAX_NAMES)
    others: list[Name] = Field(default_factory=list, max_length=transcripts.MAX_NAMES)


class AliasBody(BaseModel):
    name: Name


class LabelsBody(BaseModel):
    speakers: list[Name] = Field(max_length=50)


class NotMineBody(BaseModel):
    source_ids: list[Annotated[str, Field(min_length=1, max_length=80)]] = Field(
        min_length=1, max_length=transcripts.MAX_FILES
    )


def register(app: FastAPI, settings: Settings, queue_build: Callable[[], None]) -> None:
    # One answer at a time: each attributes every transcript again from what was said before it.
    lock = threading.Lock()

    def answer(change: Callable[[PersonaStore], list[str] | None]) -> dict[str, Any]:
        with lock, PersonaStore(settings.db_path) as store:
            try:
                changed = change(store)
            except ValueError as e:
                raise HTTPException(400, str(e)) from e
            if changed is None:
                raise HTTPException(404, "找不到这份文字记录或这个称呼，请刷新后重试")
            view = transcripts.roster(store, settings)
        if changed:
            queue_build()
        return {**view, "changed": len(changed)}

    @app.get("/api/persona/transcripts/speakers")
    def speakers() -> dict[str, Any]:
        with PersonaStore(settings.db_path) as store:
            return transcripts.roster(store, settings)

    @app.post("/api/persona/transcripts/names")
    def claim_names(body: NamesBody) -> dict[str, Any]:
        return answer(lambda store: transcripts.claim_names(store, settings, body.mine, body.others))

    @app.put("/api/persona/transcripts/{source_id}/speakers")
    def claim_labels(source_id: str, body: LabelsBody) -> dict[str, Any]:
        return answer(lambda store: transcripts.claim_labels(store, settings, source_id, body.speakers))

    @app.post("/api/persona/transcripts/not-mine")
    def not_mine(body: NotMineBody) -> dict[str, Any]:
        def change(store: PersonaStore) -> list[str] | None:
            changed: list[str] = []
            for source_id in dict.fromkeys(body.source_ids):
                done = transcripts.claim_labels(store, settings, source_id, [])
                if done is None:
                    return None
                changed += done
            return changed

        return answer(change)

    @app.get("/api/persona/aliases")
    def aliases() -> dict[str, Any]:
        with PersonaStore(settings.db_path) as store:
            return transcripts.aliases_view(store.speaker_names(), settings)

    @app.post("/api/persona/aliases")
    def add_alias(body: AliasBody) -> dict[str, Any]:
        return answer(lambda store: transcripts.claim_names(store, settings, [body.name], []))

    @app.delete("/api/persona/aliases/{name}")
    def remove_alias(name: str) -> dict[str, Any]:
        return answer(lambda store: transcripts.remove_alias(store, settings, name))
