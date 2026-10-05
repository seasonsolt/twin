"""Identity contracts are append-only: future changes add fields, never remove them. No I/O."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator, model_validator

from .persona.dimensions import FACET_BY_ID, requires_consent

BIOMETRIC_SCOPES = frozenset({"biometric:voice_clone", "biometric:face"})
_EGRESS_SCOPES = frozenset({"egress:llm", "egress:embed", "egress:tts", "egress:asr"})
_BIOMETRIC_ERROR = "本版本禁止授权生物特征：不支持本人声音复刻或照片驱动形象（M4 门槛）"


def _validate_scope(value: str) -> str:
    if value in _EGRESS_SCOPES or value in BIOMETRIC_SCOPES:
        return value
    if value.startswith("facet:"):
        facet = value.removeprefix("facet:")
        if facet in FACET_BY_ID and requires_consent(facet):
            return value
    raise ValueError(
        "无效授权范围：仅支持需授权的 facet:<细项编号>、egress:llm|embed|tts|asr、biometric:voice_clone|face"
    )


Scope = Annotated[str, AfterValidator(_validate_scope)]
Origin = Literal["questionnaire", "cli", "web"]


class Decision(StrEnum):
    GRANT = "grant"
    REVOKE = "revoke"
    DECLINE = "decline"


def _check_biometric(scope: str, decision: Decision) -> None:
    if scope in BIOMETRIC_SCOPES and decision is Decision.GRANT:
        raise ValueError(_BIOMETRIC_ERROR)


class ConsentEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    seq: int = Field(ge=1)
    scope: Scope
    decision: Decision
    at: dt.datetime
    origin: Origin
    note: str = Field(default="", max_length=200)

    @field_validator("at")
    @classmethod
    def utc_time(cls, value: dt.datetime) -> dt.datetime:
        if value.utcoffset() is None:
            raise ValueError("授权时间必须包含时区（UTC）")
        return value.astimezone(dt.UTC)

    @model_validator(mode="after")
    def biometric_gate(self) -> ConsentEvent:
        _check_biometric(self.scope, self.decision)
        return self


class Identity(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    aliases: list[str]
    consents: dict[Scope, Decision]

    @model_validator(mode="after")
    def biometric_gate(self) -> Identity:
        for scope, decision in self.consents.items():
            _check_biometric(scope, decision)
        return self

    def granted(self, scope: Scope) -> bool:
        return self.consents.get(_validate_scope(scope)) is Decision.GRANT

    @classmethod
    def from_parts(cls, name: str, aliases: Iterable[str], events: Iterable[ConsentEvent]) -> Identity:
        return cls(
            name=name,
            aliases=list(aliases),
            consents={event.scope: event.decision for event in sorted(events, key=lambda event: event.seq)},
        )
