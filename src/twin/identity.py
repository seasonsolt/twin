"""Read-only identity contract. No I/O."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

from .media.schema import AVATAR_ALIASES


class Identity(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    aliases: list[str]
    about: str = ""
    name_source: Literal["config", "user"] = "config"
    voice: str | None = None
    avatar: str | None = None

    @field_validator("avatar")
    @classmethod
    def canonical_avatar(cls, value: str | None) -> str | None:
        return AVATAR_ALIASES.get(value, value) if value is not None else None
