"""告别一种陪伴 (docs/PRODUCT_PERSONA_AGENT.md P3.6): the person can say "先到这里" to one of the ways of looking at
themself (照镜子, 随便说, 记梦, 内在声音); the twin closes it with a few words and one or two things the person said
themself, and the way is put away until they open it again.

The closing words are fixed, not a model's, so they hold no advice and nothing that asks the person to come back. The
words of theirs are what they said of what they value and how they decide (``reflection.VOICE_DIMENSIONS``), quoted as
written and dated; ``own_words`` also lists them for the will's goodbye (``retirement``). Which ways are put away is
kept in ``p_meta``.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Sequence
from typing import NamedTuple

from .items import PersonaItem
from .reflection import REFLECTION_LABELS, VOICE_DIMENSIONS, Reflection
from .schema import ChatReply
from .store import PersonaStore

CLOSED_KEY = "reflections:closed"
CLOSABLE: tuple[Reflection, ...] = ("mirror", "free", "dream", "voice")
CLOSING_WORDS = 2
QUOTE_CHARS = 120
SAID = "先到这里"


class OwnWords(NamedTuple):
    """Something the person said themself, as an item of theirs quotes it."""

    expression_id: str
    quote: str
    date: dt.date | None

    def line(self) -> str:
        """The words as they are said back to the person: quoted and dated."""
        return f"“{self.quote}”" + (f"（{self.date.isoformat()}）" if self.date else "")


def closed(store: PersonaStore) -> list[Reflection]:
    """The ways put away, in the order of ``CLOSABLE``."""
    raw = store.get_meta(CLOSED_KEY)
    kept = set(json.loads(raw)) if raw else set()
    return [r for r in CLOSABLE if r in kept]


def _keep(store: PersonaStore, ways: Sequence[Reflection]) -> None:
    store.set_meta(CLOSED_KEY, json.dumps([r for r in CLOSABLE if r in ways]))


def close(store: PersonaStore, reflection: Reflection) -> None:
    if reflection not in CLOSABLE:
        raise ValueError("这种用法不能收起")
    _keep(store, [*closed(store), reflection])


def reopen(store: PersonaStore, reflection: Reflection) -> None:
    _keep(store, [r for r in closed(store) if r != reflection])


def own_words(items: Sequence[PersonaItem], limit: int | None = None) -> list[OwnWords]:
    """The person's own words behind what they value and how they decide: the latest of each item's quotes that are
    their own, items said most often first, then the latest; one per expression."""
    principles = [i for i in items if f"D{i.facet_id.split('.', 1)[0]}" in VOICE_DIMENSIONS]
    found: list[tuple[int, dt.date, OwnWords]] = []
    for item in principles:
        own = [e for e in item.evidence if e.own_words]
        if not own:
            continue
        last = own[-1]
        quote = last.quote.strip()
        if len(quote) > QUOTE_CHARS:
            quote = quote[: QUOTE_CHARS - 1] + "…"
        found.append((len(own), last.date or dt.date.min, OwnWords(last.expression_id, quote, last.date)))
    found.sort(key=lambda f: (f[0], f[1]), reverse=True)
    words: list[OwnWords] = []
    seen: set[str] = set()
    for _, _, w in found:
        if w.expression_id not in seen:
            seen.add(w.expression_id)
            words.append(w)
    return words[:limit] if limit is not None else words


def closing_reply(store: PersonaStore, reflection: Reflection) -> ChatReply:
    """What the twin says when the person puts ``reflection`` away: that it stops here, and up to two things they said
    themself, left with them. Nothing was looked up for it, so it rests on nothing."""
    words = own_words(store.list_items(), CLOSING_WORDS)
    lines = [f"{REFLECTION_LABELS[reflection]}就先到这里。"]
    if words:
        lines += ["你自己说过的话，留给你：", *(f"- {w.line()}" for w in words)]
    return ChatReply(
        reply="\n".join(lines),
        citations=[],
        confidence=1.0,
        abstain=False,
        abstain_reason="",
        mode="general",
        retrieved_ids=[],
        verified=True,
    )
