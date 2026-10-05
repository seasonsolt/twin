"""Read-only configured identity endpoint."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from ..config import Settings
from ..egress import egress_status
from ..identity import Identity


def register(app: FastAPI, settings: Settings) -> None:
    @app.get("/api/identity")
    def get_identity() -> dict[str, Any]:
        identity = Identity(
            name=settings.target_name,
            aliases=settings.target_aliases,
            voice=settings.tts.voice,
            avatar=settings.avatar.preset,
        )
        return {**identity.model_dump(), "egress": egress_status(settings)}
