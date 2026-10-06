"""Read-only identity contract. No I/O."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class Identity(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    aliases: list[str]
    about: str = ""
    name_source: Literal["config", "user"] = "config"
    voice: str | None = None
    avatar: str | None = None
