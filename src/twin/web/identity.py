"""Editable identity backed by persona metadata."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, Request
from pydantic import BaseModel, ConfigDict, Field

from ..config import Settings
from ..egress import egress_status
from ..identity import Identity
from ..persona.sources import parse_note
from ..persona.store import PersonaStore, stored_identity


class IdentityBody(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str = Field(min_length=1, max_length=20)
    about: str = Field(max_length=200)


def register(app: FastAPI, settings: Settings, queue_build: Callable[[], None]) -> None:
    @app.get("/api/identity")
    def get_identity(request: Request) -> dict[str, Any]:
        name, about = stored_identity(settings.db_path)
        identity = Identity(
            name=name or settings.target_name,
            aliases=settings.target_aliases,
            about=about,
            name_source="user" if name else "config",
            voice=settings.tts.voice,
            avatar=settings.avatar.preset,
        )
        visitor = bool(request.scope.get("twin_visitor"))
        onboarding_pending = False
        if not visitor and settings.db_path.is_file():
            with PersonaStore(settings.db_path) as store:
                onboarding_pending = store.get_meta("onboarding_pending") == "1"
        return {
            **identity.model_dump(),
            "egress": egress_status(settings, external_only=True),
            **({"onboarding_pending": True} if onboarding_pending else {}),
            **({"visitor": True} if visitor else {}),
        }

    @app.post("/api/identity/onboarding-complete")
    def complete_onboarding() -> dict[str, bool]:
        with PersonaStore(settings.db_path) as store:
            store.set_meta("onboarding_pending", "0")
        return {"completed": True}

    @app.put("/api/identity")
    def put_identity(body: IdentityBody, request: Request) -> dict[str, Any]:
        named = settings.model_copy(update={"target_name": body.name})
        note = parse_note(body.about, named, "自我介绍") if body.about else None
        with PersonaStore(settings.db_path) as store:
            changed = store.set_identity(body.name, body.about, note)
        if changed:
            queue_build()
        return get_identity(request)
