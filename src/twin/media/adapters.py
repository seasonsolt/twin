"""Adapt validated runtime answers to the stable presentation boundary."""

from __future__ import annotations

from ..persona.schema import ChatReply
from ..util import fingerprint
from .schema import MediaCitation, PresentableAnswer


def presentable_from_chat_reply(reply: ChatReply) -> PresentableAnswer:
    """Preserve chat references without inventing citation reasons."""
    return PresentableAnswer(
        source_kind="chat_reply",
        source_fingerprint=fingerprint(reply.model_dump(mode="json")),
        text=reply.reply,
        abstain=reply.abstain,
        abstain_reason=reply.abstain_reason,
        confidence=reply.confidence,
        as_of=reply.as_of,
        citations=[MediaCitation(ref_id=ref, reason="") for ref in reply.citations],
    )


def presentable_from_payload(kind: str, data: object) -> PresentableAnswer:
    """Validate a raw JSON value through its upstream contract before adapting it."""
    if kind == "chat_reply":
        return presentable_from_chat_reply(ChatReply.model_validate(data))
    raise ValueError("来源应为 chat_reply")
