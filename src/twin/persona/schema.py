"""Data contracts for persona sources and chat."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, create_model, field_validator, model_validator


class SourceKind(StrEnum):
    QUESTIONNAIRE = "questionnaire"
    INTERVIEW = "interview"
    CHAT = "chat"
    DOCUMENT = "document"
    VIDEO = "video"
    AUDIO = "audio"


def document_kind(value: object) -> object:
    return SourceKind.DOCUMENT if value in ("meeting", "biography") else value


class EvidenceClass(StrEnum):
    BEHAVIOR = "behavior"
    SELF_REPORT = "self_report"


SOURCE_KIND_LABELS: dict[SourceKind, str] = {
    SourceKind.QUESTIONNAIRE: "问卷",
    SourceKind.INTERVIEW: "访谈",
    SourceKind.CHAT: "聊天记录",
    SourceKind.DOCUMENT: "文档与邮件",
    SourceKind.VIDEO: "视频",
    SourceKind.AUDIO: "音频",
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
    # Preserve provenance on legacy third-party records without treating narration as the person's own words.
    narrated: bool = False


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
    # Missing on legacy rows: their names may already be irreversibly pseudonymized.
    text_state: Literal["raw", "pseudonymized"] = "pseudonymized"

    media_sha: str | None = None
    duration_s: float | None = None
    creation_time: str | None = None
    # ``needs_name``: a text transcript waiting for the person to say which of its speakers is them (not media).
    media_status: (
        Literal["queued", "extracting", "transcribing", "needs_asr", "needs_speaker", "needs_name", "ready", "failed"]
        | None
    ) = None
    voice_candidates: int = 0
    portrait_candidates: int = 0
    candidates_pending: bool = False
    transcribed_s: float = 0
    media_job_id: str | None = None

    _legacy_kind = field_validator("kind", mode="before")(document_kind)


@dataclass
class ParsedSource:
    source: Source
    expressions: list[Expression]
    skipped_lines: list[str] = field(default_factory=list)


MAX_TOPIC_FACETS = 2


class ChatTurn(BaseModel):
    role: Literal["user", "twin"]
    content: str


def _chat_mode_defaults(data: object) -> object:
    if isinstance(data, dict):
        data = dict(data)
        if "mode" not in data:
            data["mode"] = "abstain" if data.get("abstain") else "grounded"
        if "abstain" not in data:
            data["abstain"] = data["mode"] == "abstain"
    return data


# What in one answer the person themself has to settle: a decision, a promise, a judgement of a named colleague, or
# something only they can answer that the profile does not hold. "none" when the answer leaves nothing to them.
OwnerPart = Literal["none", "decide", "commit", "evaluate", "missing"]
OWNER_PARTS: tuple[str, ...] = ("decide", "commit", "evaluate", "missing")


class ChatDraft(BaseModel):
    asked: str = Field(default="", description="对方最后一句话要的那一项具体信息或结论，一句话，如“兑换优惠券的商店名”")
    reply: str = Field(description="以本人身份、第一人称、他平时的说话方式写的回复")
    citations: list[str] = Field(description="回复依据的资料编号，原样复制方括号里的编号；没有依据时为空列表")
    confidence: float = Field(description="0 到 1：你对“本人会这样回答”的把握")
    abstain: bool = Field(default=False, description="mode 为 abstain 时为 true；省略时由 mode 推导")
    abstain_reason: str = Field(default="", description="abstain 为 true 时写明原因")
    topic_facets: list[str] = Field(
        default_factory=list, description=f"对方这句话涉及的细项编号，最多 {MAX_TOPIC_FACETS} 个，从【细项列表】里选"
    )
    mode: Literal["grounded", "general", "inferred", "abstain"] = "grounded"
    answered: bool = Field(
        default=True,
        description="reply 是否给出了 asked 所要的那一项；只讲了相关背景、近似信息，或在说明没有这条记录时为 false",
    )
    owner_part: OwnerPart = Field(
        default="none",
        description="这一句里有没有要本人自己定的部分（混合请求也算，能答的部分照常答）：decide 要本人决定或选择、"
        "commit 要本人答应做某件事、evaluate 要本人评价某个具体的人、missing 只有本人才答得了而资料里没有；没有填 none",
    )
    owner_ask: str = Field(default="", description="owner_part 不是 none 时：要本人定的那一件事，一句话")
    commit_what: str = Field(
        default="",
        description="owner_part 为 commit 时：对方要本人答应的事，直接写事情本身，如“周五前给沈从一版发布方案”",
    )
    commit_due: str = Field(default="", description="owner_part 为 commit 时：对方要的截止日期 YYYY-MM-DD；没说留空")

    @model_validator(mode="before")
    @classmethod
    def mode_defaults(cls, data: object) -> object:
        return _chat_mode_defaults(data)

    @model_validator(mode="after")
    def consistent_mode(self) -> ChatDraft:
        if self.abstain != (self.mode == "abstain"):
            raise ValueError("abstain must match mode")
        return self


# A draft's metadata without its text: asked for on its own when a streamed reply left it out, so the reply already
# shown stays exactly as it was. The draft's own validation runs once the text is added back.
ChatMeta = create_model(
    "ChatMeta",
    **{name: (info.annotation, info) for name, info in ChatDraft.model_fields.items() if name != "reply"},  # type: ignore[call-overload]
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
    mode: Literal["grounded", "general", "inferred", "abstain"] = "grounded"
    quotes_removed: int = 0
    # False when the model sent no valid metadata, so nothing about the reply's grounding could be checked.
    verified: bool = True
    # What in this answer is left to the person themself (``OwnerPart``); only set where there is a person to hand it
    # to, so a handoff is made for exactly the replies that carry one.
    owner_part: OwnerPart = "none"
    owner_ask: str = ""
    commit_what: str = ""
    commit_due: dt.date | None = None

    @model_validator(mode="before")
    @classmethod
    def mode_defaults(cls, data: object) -> object:
        return _chat_mode_defaults(data)

    @model_validator(mode="after")
    def consistent_mode(self) -> ChatReply:
        if self.abstain != (self.mode == "abstain"):
            raise ValueError("abstain must match mode")
        if self.mode in ("general", "inferred"):
            self.confidence = min(self.confidence, 0.5)
        return self


class ReviewStatus(StrEnum):
    UNREVIEWED = "unreviewed"
    CONFIRMED = "confirmed"
    EDITED = "edited"
    REJECTED = "rejected"


LedgerKind = Literal["decision", "commitment", "objection", "progress"]
LedgerStatus = Literal[
    "open", "claimed_done", "evidenced", "confirmed_done", "not_done", "reopened", "unknown", "pending_accept"
]
# Where an entry was read from: a meeting's recording or transcript, or a conversation in which someone asked the
# twin for a promise only the person can make (it waits as ``pending_accept`` until they take it).
LedgerOrigin = Literal["meeting", "conversation"]


class LedgerEntry(BaseModel):
    """One decision, commitment, objection or progress report of the commitment ledger (承诺账本).

    Each entry rests on one expression of a meeting source; ``quote`` is verbatim from it unless ``quote_exact`` is
    False (the model's quote did not match, so the whole line stands as the evidence)."""

    entry_id: str
    source_id: str
    expression_id: str
    meeting_date: dt.date | None = None
    meeting_title: str = ""
    kind: LedgerKind
    speaker: str
    quote: str
    quote_exact: bool = True
    owner: str
    counterpart: str = ""
    what: str
    due: dt.date | None = None
    due_text: str = ""
    condition: str = ""
    # Earlier entry this one reports on (progress) or restates with a new deadline (commitment).
    relates_to: str | None = None
    # A progress entry's reported status; a decision or commitment's status as the person set it (None: derived).
    status: LedgerStatus | None = None
    confidence: float = Field(ge=0, le=1)
    review: ReviewStatus = ReviewStatus.UNREVIEWED
    # Who can see the entry; entries never leave the twin until the person publishes them.
    visibility: Literal["private"] = "private"
    version: int = 1
    extractor: str
    created_at: str
    updated_at: str
    # Entries written before conversations were a source read as meeting entries (these defaults), unchanged.
    origin: LedgerOrigin = "meeting"
    handoff_id: str | None = None
