"""自评记录: the person says of an answer of their twin's whether it is like them (docs/PRODUCT_PERSONA_AGENT.md
P1.8), kept on this machine with what was asked and how it was answered, for the evaluation of section 6 (自我认同,
grouped by the date an answer speaks as of). The marks on 剖析观察 are kept by ``persona.observations``.

An answer is found by its words among the twin's turns the person's own conversation saved, never taken from what the
page sends, so what is kept is what the twin said. Kept in ``p_meta``; the latest mark of each answer counts.
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any, Literal

from pydantic import BaseModel

from .store import PersonaStore

Rating = Literal["like", "unlike"]
RATING_LABELS: dict[str, str] = {"like": "像我", "unlike": "不像我"}
STATE_KEY = "self_ratings"
MAX_KEPT = 2000
MAX_QUESTION_CHARS = 2000


class SelfRating(BaseModel):
    turn_id: str
    question: str
    reply: str
    rating: Rating
    rated_at: str
    # How the twin answered (``ChatReply.mode``), the date it spoke as of, and the way the person was talking with it
    # (``persona.reflection``), for the evaluation to group by.
    mode: str = ""
    as_of: str | None = None
    reflection: str = ""


def load(store: PersonaStore) -> list[SelfRating]:
    raw = store.get_meta(STATE_KEY)
    return [SelfRating.model_validate(r) for r in json.loads(raw)] if raw else []


def ratings_of(store: PersonaStore, conversation_id: str) -> dict[str, Rating]:
    """The marks on the answers of one conversation, by turn."""
    return {r.turn_id: r.rating for r in load(store) if r.turn_id.rsplit(":", 1)[0] == conversation_id}


def _answer(conversation: dict[str, Any], reply: str) -> tuple[dict[str, Any], str]:
    """The twin's last turn of the conversation saying ``reply``, and the question it answers."""
    turns = conversation["turns"]
    for n in range(len(turns) - 1, -1, -1):
        turn = turns[n]
        if turn["role"] == "twin" and turn.get("reply") and turn["reply"].get("reply") == reply:
            question = next((t["content"] for t in reversed(turns[:n]) if t["role"] == "user"), "")
            return turn, question[:MAX_QUESTION_CHARS]
    raise KeyError(reply)


def rate(
    store: PersonaStore, conversation: dict[str, Any], reply: str, rating: Rating | None, now: dt.datetime
) -> Rating | None:
    """Mark the answer (or take the mark back). KeyError when the conversation has no such answer of the twin's;
    ValueError for what is not the twin speaking as the person (a note taken down, help when the person spoke of
    harming themself, a task handed on, saying it does not know)."""
    turn, question = _answer(conversation, reply)
    payload = turn["reply"]
    if payload.get("crisis") or payload.get("note") or payload.get("delegation") or payload.get("abstain"):
        raise ValueError("这条不是分身自己的回答")
    kept = [r for r in load(store) if r.turn_id != turn["id"]]
    if rating is not None:
        kept.append(
            SelfRating(
                turn_id=turn["id"],
                question=question,
                reply=reply,
                rating=rating,
                rated_at=now.isoformat(timespec="seconds"),
                mode=str(payload.get("mode") or ""),
                as_of=payload.get("as_of"),
                reflection=str(payload.get("reflection") or ""),
            )
        )
    store.set_meta(STATE_KEY, json.dumps([r.model_dump() for r in kept[-MAX_KEPT:]], ensure_ascii=False))
    return rating
