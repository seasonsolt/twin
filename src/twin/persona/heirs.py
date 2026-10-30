"""继承人受众档 (docs/PRODUCT_PERSONA_AGENT.md P2.4): what an heir's conversation may draw on, read from the will.

An heir is given the facets the will names (``tiers.HeirGrant``), nothing else: an heir the will no longer names, or
a will that cannot be read, is given nothing at all. The topics the person said never to talk about with them stop a
question before anything is looked up or any model asked (``avoided``), like the crisis guard, which still comes
first; what is found that speaks of them is left out too (``mentions``). A topic is matched by its words first, more
than less (``topic_terms``), then by meaning when the embedding service answers (``close_to``).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Sequence

import numpy as np

from ..embed import Embedder, EmbedError
from .items import PersonaItem
from .schema import ChatReply
from .store import PersonaStore
from .tiers import (
    COLLEAGUE,
    NOTHING,
    SELF,
    Audience,
    HeirGrant,
    PrivateWords,
    for_audience,
    heir_of,
    heir_words,
    private_words,
)
from .will import allowed_facets, get

logger = logging.getLogger(__name__)

# How close in meaning (cosine of the embeddings) a question or a record must be to a topic to count as about it.
# Kept low on purpose: a topic missed is worse than a question answered with "不谈".
TOPIC_SIMILARITY = 0.6
# Words that only frame a topic ("公司的事", "关于前一段婚姻"), not what it is about; a topic is split at them.
_FRAME = re.compile(
    r"关于|有关|涉及|这件事|那件事|这些事|那些事|的事情|的事|事情|方面|问题|话题|的|和|与|及|跟|或|以及|"
    r"他们|她们|我们|你们|他|她|它|我|你|[\s\W_]+"
)
_LATIN = re.compile(r"^[a-z0-9]+$")
AVOIDED_REPLY = "这件事{name}生前交代过，不和你谈。我们聊点别的吧。"


def grant(store: PersonaStore, audience: Audience) -> HeirGrant | None:
    """What the will gives the heir a conversation of ``audience`` is of; None for the person and their colleagues.
    The empty grant when the will names no such heir or cannot be read: nothing is given that the will does not name."""
    heir_id = heir_of(audience)
    if heir_id is None:
        return None
    try:
        heir = get(store, heir_id)
    except KeyError:
        return NOTHING
    except Exception:  # a will that cannot be read gives nothing, whatever went wrong
        logger.warning("could not read the will for heir %s; giving nothing", heir_id, exc_info=True)
        return NOTHING
    return HeirGrant(facets=allowed_facets(heir), single=frozenset(heir.facets), avoid=tuple(heir.avoid))


def usable_items(store: PersonaStore, items: Iterable[PersonaItem], audience: Audience) -> list[PersonaItem]:
    """The items a conversation of ``audience`` may use; an heir's also without those about a topic not to be talked
    about (by words; ``PersonaChat`` adds meaning)."""
    given = grant(store, audience)
    found = for_audience(items, store.item_tiers(), audience, given)
    if given is None or not given.avoid:
        return found
    return [i for i in found if not mentions(item_words(i), given.avoid)]


def hidden_words(store: PersonaStore, audience: Audience) -> PrivateWords:
    """The words a conversation of ``audience`` may not be shown: none for the person, those only items of the
    person's own tier or a note they kept to themself stand on for a colleague (``tiers.private_words``), all but
    those the will gives for an heir (``tiers.heir_words``)."""
    if audience == SELF:
        return PrivateWords()
    items = store.list_items(include_rejected=True)
    if (given := grant(store, audience)) is not None:
        return heir_words(items, store.item_tiers(), given, store.private_note_sources())
    return private_words(items, store.item_tiers(), store.private_note_sources())


def tier_only(audience: Audience) -> Audience:
    """The tier kept for a conversation in the team's index, which knows the person's and colleagues' alone: an
    heir's is kept as a colleague's (it is never answered from that, ``ConversationIndex.audience``)."""
    return SELF if audience == SELF else COLLEAGUE


def topic_terms(topic: str) -> list[str]:
    """The words a topic is matched by: its parts between framing words, and for a Chinese part of three or more
    characters also its last two, which name what it is about ("前一段婚姻" → "婚姻"). A part of one Chinese character
    counts only when it is all there is. Lowercased."""
    parts = [p for p in _FRAME.split(topic.lower()) if p]
    long = [p for p in parts if len(p) >= 2]
    terms: list[str] = []
    for part in long or parts:
        terms.append(part)
        if len(part) >= 3 and not _LATIN.match(part):
            terms.append(part[-2:])
    return list(dict.fromkeys(terms))


def mentions(text: str, topics: Sequence[str]) -> bool:
    """Whether ``text`` speaks of any of ``topics`` by their words (``topic_terms``): a whole word for a Latin one, the
    characters anywhere for a Chinese one."""
    lowered = text.lower()
    for topic in topics:
        for term in topic_terms(topic):
            if _LATIN.match(term):
                if re.search(rf"\b{re.escape(term)}\b", lowered):
                    return True
            elif term in lowered:
                return True
    return False


def close_to(vectors: np.ndarray, topic_vectors: np.ndarray) -> np.ndarray:
    """For each row of ``vectors``, whether it is within ``TOPIC_SIMILARITY`` of any topic."""
    if vectors.size == 0 or topic_vectors.size == 0:
        return np.zeros(len(vectors), dtype=bool)
    a = vectors / np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-12)
    b = topic_vectors / np.maximum(np.linalg.norm(topic_vectors, axis=1, keepdims=True), 1e-12)
    return np.asarray((a @ b.T).max(axis=1) >= TOPIC_SIMILARITY)


def embed_topics(embedder: Embedder | None, topics: Sequence[str]) -> np.ndarray | None:
    """The topics' vectors; None with no embedder, no topics, or the embedding service down (words alone then)."""
    if embedder is None or not topics:
        return None
    try:
        return np.asarray(embedder.embed(list(topics)), dtype=np.float32)
    except (EmbedError, ValueError):
        return None


def avoided(text: str, topics: Sequence[str], embedder: Embedder | None) -> bool:
    """Whether a question speaks of a topic not to be talked about: by its words, else by its meaning."""
    if not topics:
        return False
    if mentions(text, topics):
        return True
    topic_vectors = embed_topics(embedder, topics)
    if topic_vectors is None:
        return False
    try:
        question = np.asarray(embedder.embed([text[:2000]]), dtype=np.float32) if embedder is not None else None
    except (EmbedError, ValueError):
        return False
    return question is not None and bool(close_to(question, topic_vectors).any())


def avoided_reply(name: str) -> ChatReply:
    """The fixed reply to a question about a topic not to be talked about: nothing was looked up, so it rests on
    nothing and is not logged as a question asked; it does not say which topic."""
    return ChatReply(
        reply=AVOIDED_REPLY.format(name=name or "他"),
        citations=[],
        confidence=1.0,
        abstain=False,
        abstain_reason="",
        mode="general",
        retrieved_ids=[],
        verified=True,
    )


def item_words(item: PersonaItem) -> str:
    """An item as a topic is looked for in it: its statement and its quotes."""
    return "\n".join([item.statement, *(e.quote for e in item.evidence)])
