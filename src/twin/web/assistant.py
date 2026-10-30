"""Web side of the person's own assistant (``persona.assistant``): the notes they ask it to remember, what a colleague
would get for a question (看同事会得到什么), and the promises they say they make. Everything here is for the person
alone: a conversation of the colleague tier, a manager or a visitor is refused."""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from ..config import Settings
from ..embed import Embedder, EmbedError
from ..llm import LLM
from ..persona.assistant import DEFAULT_NOTE_TIER, NOTE_REPLY, NOTE_TITLE, SEALED_NOTE_REPLY
from ..persona.chat import PersonaChat, PersonaContext
from ..persona.dimensions import FACET_BY_ID
from ..persona.schema import ChatReply
from ..persona.sources import parse_note
from ..persona.store import PersonaStore
from ..persona.tiers import COLLEAGUE, SELF, Tier, item_tier

# How many of the items kept from colleagues a trial question names.
WITHHELD_SHOWN = 3
NoteTier = Literal["none", "colleague", "self"]


class NoteTierBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # ``none``: do not keep it (the note is removed); the others say who may use it.
    tier: NoteTier


def person_only(request: Request) -> None:
    """403 unless the request is from the person the twin is made for, known by their account: with no sign-in there
    is no knowing who asks, and nobody is the person."""
    if not request.scope.get("twin_person") or request.scope.get("twin_visitor"):
        raise HTTPException(403, "这只有本人可以用")


def keep_note(store: PersonaStore, settings: Settings, text: str, stamp: dt.datetime | None = None) -> dict[str, Any]:
    """Keep what the person asked to be remembered as a note, in the tier it has until they choose (theirs alone), and
    say what was kept, for the card under the reply. The memory is made from it by the next build."""
    when = stamp or dt.datetime.now()
    parsed = parse_note(text, settings, f"{NOTE_TITLE} {when:%m-%d %H:%M}")
    store.put_source(parsed)
    store.set_note_tier(parsed.source.source_id, DEFAULT_NOTE_TIER)
    return {"id": parsed.source.source_id, "text": text, "tier": DEFAULT_NOTE_TIER}


def note_reply(sealed: bool = False) -> ChatReply:
    """What the assistant says to a note: nothing was looked up, so it rests on nothing. ``sealed``: the memory is
    sealed, so the note was not kept."""
    return ChatReply(
        reply=SEALED_NOTE_REPLY if sealed else NOTE_REPLY,
        citations=[],
        confidence=1.0,
        abstain=False,
        abstain_reason="",
        mode="general",
        retrieved_ids=[],
        verified=True,
    )


def withheld(store: PersonaStore, context: PersonaContext) -> list[dict[str, str]]:
    """What the question's own retrieval found (the items it ranked and the core of the portrait) that is kept from
    colleagues, to show what a trial question left out: the facet and the item, a few at most."""
    tiers = store.item_tiers()
    found = {i.item_id: i for i in [*(i for i, _ in context.items), *context.core]}
    kept = [i for i in found.values() if item_tier(i, tiers) != COLLEAGUE]
    return [
        {"id": i.item_id, "facet": FACET_BY_ID[i.facet_id].name, "text": i.statement[:60]}
        for i in kept[:WITHHELD_SHOWN]
    ]


def trial_withheld(
    store: PersonaStore, llm: LLM, embedder: Embedder, settings: Settings, question: str
) -> list[dict[str, str]]:
    """The items a trial question would also have drawn on, had the person asked it themself, that a colleague does not
    get (``withheld``); empty when retrieval cannot run now."""
    own = PersonaChat(store, llm, embedder, settings, ledger=False, audience=SELF)
    try:
        return withheld(store, own.retrieve(question))
    except (EmbedError, ValueError):
        return []


def register(
    app: FastAPI,
    settings: Settings,
    queue_build: Callable[[], None],
    lock: AbstractContextManager[Any],
    open_store: Callable[[], AbstractContextManager[PersonaStore]],
) -> None:
    @app.put("/api/persona/notes/{source_id}/tier")
    def set_note_tier(source_id: str, body: NoteTierBody, request: Request) -> dict[str, Any]:
        """Say who may use a note the person asked to be remembered (``同事能用`` / ``只有我``), or with ``none`` do not
        keep it after all. Only notes made by 记一下 can be changed here."""
        person_only(request)
        with lock, open_store() as store:
            source = store.get_source(source_id)
            if source is None or not source.origin.startswith("note:") or not source.title.startswith(NOTE_TITLE):
                raise HTTPException(404, "找不到这条记下的内容")
            if body.tier == "none":
                store.delete_source(source_id)
                items: list[str] = []
            else:
                tier: Tier = COLLEAGUE if body.tier == "colleague" else SELF
                items = store.set_note_tier(source_id, tier)
        queue_build()
        return {"id": source_id, "tier": body.tier, "items": len(items)}
