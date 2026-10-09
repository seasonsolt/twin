"""Service contracts and the sole ChatReply adapter for API/MCP."""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from .config import Settings
from .identity import Identity
from .persona.chat import QUOTE_CHARS, TEXT_CHARS, PersonaChat, _clip, _visible_items
from .persona.schema import ChatTurn
from .persona.sources import expression_view
from .persona.store import PersonaStore, stored_identity

MAX_QUESTION_CHARS = 2000
QUESTION_TOO_LONG = "问题不能超过 2000 个字符"


class ServiceCitation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    ref_id: str
    kind: Literal["item", "expression"]
    quote: str
    date: dt.date | None = None
    source_kind: str | None = None


class ServiceAnswer(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    answer: str
    abstain: bool
    abstain_reason: str
    confidence: float
    citations: list[ServiceCitation]
    as_of: dt.date | None
    persona_name: str
    generated_at: dt.datetime
    mode: Literal["grounded", "general", "inferred", "abstain"] = "grounded"

    @model_validator(mode="before")
    @classmethod
    def ignore_legacy_label(cls, value: object) -> object:
        if isinstance(value, dict):
            return {key: val for key, val in value.items() if key != "label"}
        return value

    @field_validator("generated_at")
    @classmethod
    def utc_time(cls, value: dt.datetime) -> dt.datetime:
        if value.utcoffset() is None:
            raise ValueError("生成时间必须包含时区（UTC）")
        return value.astimezone(dt.UTC)


class ServiceIdentity(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    avatar: str | None
    voice: str | None

    @model_validator(mode="before")
    @classmethod
    def ignore_legacy_label(cls, value: object) -> object:
        if isinstance(value, dict):
            return {key: val for key, val in value.items() if key != "label"}
        return value


def public_identity(settings: Settings) -> ServiceIdentity:
    from .persona.store import stored_avatar

    identity = Identity(
        name=stored_identity(settings.db_path)[0] or settings.target_name,
        aliases=settings.target_aliases,
        voice=settings.tts.voice,
        avatar=stored_avatar(settings.db_path, settings.avatar.preset),
    )
    return ServiceIdentity(name=identity.name, avatar=identity.avatar, voice=identity.voice)


def resolve_citations(
    store: PersonaStore, settings: Settings, refs: Sequence[str], as_of: dt.date | None
) -> list[ServiceCitation]:
    items = {item.item_id: item for item in _visible_items(store, settings, as_of)}
    expressions = {e.expression_id: e for e in expression_view(store, settings, target_only=True, until=as_of)}
    sources = {source.source_id: source.kind.value for source in store.list_sources()}
    citations: list[ServiceCitation] = []
    for ref in refs:
        if ref in items:
            item = items[ref]
            evidence = item.evidence[-1] if item.evidence else None
            citations.append(
                ServiceCitation(
                    ref_id=ref,
                    kind="item",
                    quote=_clip(evidence.quote, QUOTE_CHARS) if evidence else "",
                    date=evidence.date if evidence else None,
                    source_kind=evidence.source_kind.value if evidence else None,
                )
            )
        elif ref in expressions:
            expression = expressions[ref]
            citations.append(
                ServiceCitation(
                    ref_id=ref,
                    kind="expression",
                    quote=_clip(expression.text, TEXT_CHARS),
                    date=expression.date,
                    source_kind=sources.get(expression.source_id),
                )
            )
    return citations


def answer_question(chat: PersonaChat, question: str, as_of: dt.date | None) -> ServiceAnswer:
    if len(question) > MAX_QUESTION_CHARS:
        raise ValueError(QUESTION_TOO_LONG)
    reply = chat.reply([ChatTurn(role="user", content=question)], as_of=as_of, persist=False)
    citations = resolve_citations(chat.store, chat.settings, reply.citations, as_of)
    return ServiceAnswer(
        answer=reply.reply,
        abstain=reply.abstain,
        abstain_reason=reply.abstain_reason,
        confidence=reply.confidence,
        citations=citations,
        as_of=reply.as_of,
        persona_name=chat.store.get_meta("identity:name") or chat.settings.target_name,
        generated_at=dt.datetime.now(dt.UTC),
        mode=reply.mode,
    )
