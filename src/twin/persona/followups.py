"""Questions the twin could not answer, put to the person (弃权回流).

Every chat reply is logged; the questions it abstained on form a queue, the same question asked again counting once.
The person answers in their own words, and the answer becomes a new source (the question as its context), so the next
build turns it into memory the twin can quote. A question answered or set aside stays out of the queue, unless the
twin still abstains on it after a build that included the answer, or the answer was deleted.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

from .schema import Source
from .sources import parse_answer
from .store import PersonaStore

PREFIX = "followup:"
FollowupStatus = Literal["pending", "answered", "dismissed"]
_TRAILING = re.compile(r"[\s?？!！。.,，、~～…]+$")


class FollowupState(BaseModel):
    status: FollowupStatus
    at: str
    # How many times it had been asked when the person handled it; later asks count from here.
    asked: int = 0
    source_id: str | None = None


@dataclass
class Followup:
    followup_id: str
    question: str
    # The asker's turn before the latest ask, when the question follows up on it.
    previous: str
    reason: str
    asked: int
    first_at: str
    last_at: str
    status: FollowupStatus
    # When the person answered or set it aside, and how often it was asked since.
    handled_at: str | None
    asked_since: int
    source_id: str | None
    # Answered, built, and still not answered: the answer did not cover it.
    unresolved: bool


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def _time(text: str) -> dt.datetime:
    """An ISO time as an aware datetime; a naive one (the chat log, the states here) is local time."""
    value = dt.datetime.fromisoformat(text)
    return value if value.tzinfo else value.astimezone()


def normalize(question: str) -> str:
    """The form two asks of the same question share: case, whitespace and closing punctuation ignored."""
    return _TRAILING.sub("", "".join(question.split()).lower())


def followup_id(question: str) -> str:
    return hashlib.sha256(normalize(question).encode()).hexdigest()[:16]


def list_followups(store: PersonaStore) -> list[Followup]:
    """The questions the twin abstained on, pending ones first, the most recently asked first within each status."""
    groups: dict[str, list[tuple[str, dict[str, str]]]] = {}
    latest: dict[str, int] = {}  # position of each question's latest ask in the log
    for n, (at, entry) in enumerate(store.chat_abstentions()):
        question = str(entry.get("question", "")).strip()
        if question:
            fid = followup_id(question)
            groups.setdefault(fid, []).append((at, entry))
            latest[fid] = n
    states = {k: FollowupState.model_validate_json(v) for k, v in store.meta_with_prefix(PREFIX).items()}
    built_at = store.get_meta("built_at")
    built = _time(built_at) if built_at else None
    sources = {s.source_id for s in store.list_sources()}
    out: list[Followup] = []
    for fid, asks in groups.items():
        at, last = asks[-1]
        state = states.get(fid)
        status: FollowupStatus = state.status if state else "pending"
        since = [_time(a) for a, _ in asks[state.asked :]] if state else []
        unresolved = False
        if state and state.status == "answered":
            if state.source_id not in sources:
                status = "pending"  # the answer was deleted
            elif built and built > _time(state.at) and any(a > built for a in since):
                status, unresolved = "pending", True
        out.append(
            Followup(
                followup_id=fid,
                question=str(last.get("question", "")).strip(),
                previous=str(last.get("previous", "")).strip(),
                reason=str(last.get("reason", "")).strip(),
                asked=len(asks),
                first_at=asks[0][0],
                last_at=at,
                status=status,
                handled_at=state.at if state and state.status != "pending" else None,
                asked_since=len(since),
                source_id=state.source_id if state else None,
                unresolved=unresolved,
            )
        )
    order = {"pending": 0, "answered": 1, "dismissed": 2}
    out.sort(key=lambda f: (order[f.status], -latest[f.followup_id]))
    return out


def get_followup(store: PersonaStore, fid: str) -> Followup:
    found = next((f for f in list_followups(store) if f.followup_id == fid), None)
    if found is None:
        raise KeyError(fid)
    return found


def answer_followup(store: PersonaStore, fid: str, text: str, name: str) -> tuple[Followup, Source]:
    """Store the person's answer as a new source and mark the question answered. Raises KeyError for an unknown
    question and ValueError for an empty or overlong answer."""
    followup = get_followup(store, fid)
    parsed = parse_answer(followup.question, text, name, f"{PREFIX}{fid}", previous=followup.previous)
    store.put_source(parsed)
    state = FollowupState(status="answered", at=_now(), asked=followup.asked, source_id=parsed.source.source_id)
    store.set_meta(PREFIX + fid, state.model_dump_json())
    return get_followup(store, fid), parsed.source


def set_followup(store: PersonaStore, fid: str, status: Literal["pending", "dismissed"]) -> Followup:
    """Set a question aside, or put it back in the queue. An answer already given stays a memory either way."""
    followup = get_followup(store, fid)
    store.set_meta(PREFIX + fid, FollowupState(status=status, at=_now(), asked=followup.asked).model_dump_json())
    return get_followup(store, fid)
