"""退场 (docs/PRODUCT_PERSONA_AGENT.md P2.8): from the day the will gives an heir (``Heir.retire_on``) the twin says
goodbye to them once, in the person's own words when they wrote some, and answers them no more; what they talked
about stays theirs to read (已定 4). An heir the will gives no day never leaves.

The goodbye is said to the first question on or after that day, before anything is looked up or any model asked, and
is kept in their conversation like any reply; that it was said is kept in ``p_meta``, so it is said once whatever
conversation they open. A rehearsal (P2.6) of an heir past their day shows the goodbye and keeps nothing.
"""

from __future__ import annotations

import datetime as dt

from .schema import ChatReply
from .store import PersonaStore
from .tiers import Audience, heir_of
from .will import Heir, get

DEFAULT_FAREWELL = "到这里，我们该说再见了。谢谢你一直来和我说话。往后的日子，好好照顾自己。"
# Said to an heir who asks again after the goodbye; their conversations stay to read.
RETIRED = "这段延续已经结束，以前的对话还能翻看"
SAID_PREFIX = "heir_farewell:"


def leaving(store: PersonaStore, audience: Audience, today: dt.date) -> Heir | None:
    """The heir a conversation of ``audience`` is of, when their day to leave has come; None for anyone else."""
    heir_id = heir_of(audience)
    if heir_id is None:
        return None
    try:
        heir = get(store, heir_id)
    except KeyError:
        return None
    return heir if heir.retire_on is not None and heir.retire_on <= today else None


def said(store: PersonaStore, heir_id: str) -> bool:
    """Whether the twin has said goodbye to this heir."""
    return store.get_meta(SAID_PREFIX + heir_id) is not None


def gone(store: PersonaStore, audience: Audience, today: dt.date) -> bool:
    """Whether the twin has left this heir: their day has come and the goodbye was said. Their conversations are then
    only to read."""
    heir = leaving(store, audience, today)
    return heir is not None and said(store, heir.heir_id)


def farewell_reply(heir: Heir) -> ChatReply:
    """The goodbye: the person's own words when they wrote some, else the default. Nothing was looked up, so it rests on
    nothing and is not logged as a question asked."""
    return ChatReply(
        reply=heir.farewell or DEFAULT_FAREWELL,
        citations=[],
        confidence=1.0,
        abstain=False,
        abstain_reason="",
        mode="general",
        retrieved_ids=[],
        verified=True,
    )


def say_farewell(store: PersonaStore, heir_id: str, now: dt.datetime) -> None:
    """Keep that the goodbye was said to this heir, and when."""
    store.set_meta(SAID_PREFIX + heir_id, now.isoformat(timespec="seconds"))
