"""Read-only identity contract. No I/O."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class Identity(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    aliases: list[str]
    voice: str | None = None
    avatar: str | None = None
