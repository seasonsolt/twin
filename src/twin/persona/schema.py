"""Data contracts for persona sources and chat."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class SourceKind(StrEnum):
    QUESTIONNAIRE = "questionnaire"
    INTERVIEW = "interview"
    CHAT = "chat"
    DOCUMENT = "document"
    BIOGRAPHY = "biography"
    MEETING = "meeting"


class EvidenceClass(StrEnum):
    BEHAVIOR = "behavior"
    SELF_REPORT = "self_report"


SOURCE_KIND_LABELS: dict[SourceKind, str] = {
    SourceKind.QUESTIONNAIRE: "问卷",
    SourceKind.INTERVIEW: "访谈",
    SourceKind.CHAT: "聊天记录",
    SourceKind.DOCUMENT: "文档与邮件",
    SourceKind.BIOGRAPHY: "传记与他人记述",
    SourceKind.MEETING: "会议转写",
}

_SELF_REPORT = frozenset({SourceKind.QUESTIONNAIRE, SourceKind.INTERVIEW})


def evidence_class(kind: SourceKind) -> EvidenceClass:
    return EvidenceClass.SELF_REPORT if kind in _SELF_REPORT else EvidenceClass.BEHAVIOR


class Expression(BaseModel):
    expression_id: str
    source_id: str
    idx: int
    date: dt.date | None = None
    speaker: str
    is_target: bool
    text: str
    # What the words answer: the question asked, or the other people's messages just before.
    context: str = ""
    # Chat or group name, document title, questionnaire section.
    channel: str = ""
    # Facet ids a questionnaire question was written for (a hint, not a verdict).
    facets_hint: list[str] = Field(default_factory=list)
    # A questionnaire test question: kept for testing the twin, never used as profile evidence.
    held_out: bool = False
    # Someone else's account of the person (a biography paragraph), not the person's own words.
    narrated: bool = False
    # Original meeting utterance index, independent of this expression's position.
    utterance_idx: int | None = None
    # Seconds from the start of a recorded meeting.
    start: float | None = None
    end: float | None = None


class Source(BaseModel):
    source_id: str
    kind: SourceKind
    title: str
    origin: str
    first_date: dt.date | None = None
    last_date: dt.date | None = None
    imported_at: str
    n_expressions: int
    n_target: int
    # Facets the person declined by skipping their questions (questionnaire only).
    declined_facets: list[str] = Field(default_factory=list)
    meeting_id: str | None = None
    # Missing on legacy rows: their names may already be irreversibly pseudonymized.
    text_state: Literal["raw", "pseudonymized"] = "pseudonymized"


@dataclass
class ParsedSource:
    source: Source
    expressions: list[Expression]
    skipped_lines: list[str] = field(default_factory=list)


MAX_TOPIC_FACETS = 2


class ChatTurn(BaseModel):
    role: Literal["user", "twin"]
    content: str


class ChatDraft(BaseModel):
    reply: str = Field(description="以本人身份、第一人称、他平时的说话方式写的回复")
    citations: list[str] = Field(description="回复依据的资料编号，原样复制方括号里的编号；没有依据时为空列表")
    confidence: float = Field(description="0 到 1：你对“本人会这样回答”的把握")
    abstain: bool = Field(description="资料里没有依据、只能回答不知道或需要本人确认时为 true")
    abstain_reason: str = Field(default="", description="abstain 为 true 时写明原因")
    topic_facets: list[str] = Field(
        default_factory=list, description=f"对方这句话涉及的细项编号，最多 {MAX_TOPIC_FACETS} 个，从【细项列表】里选"
    )


class ChatReply(BaseModel):
    reply: str
    citations: list[str]
    confidence: float
    abstain: bool
    abstain_reason: str
    topic_facets: list[str] = Field(default_factory=list)
    retrieved_ids: list[str]
    as_of: dt.date | None = None


class ReviewStatus(StrEnum):
    UNREVIEWED = "unreviewed"
    CONFIRMED = "confirmed"
    EDITED = "edited"
    REJECTED = "rejected"
