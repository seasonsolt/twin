"""What a conversation may draw on, by the tier it answers from (``persona.tiers``): every item and word for the person
themself, the colleague tier and the words it stands on for anyone else."""

from __future__ import annotations

from collections.abc import Iterable

from .items import PersonaItem
from .store import PersonaStore
from .tiers import SELF, Audience, PrivateWords, for_audience, private_words


def usable_items(store: PersonaStore, items: Iterable[PersonaItem], audience: Audience) -> list[PersonaItem]:
    """The items a conversation of ``audience`` may use."""
    return for_audience(items, store.item_tiers(), audience)


def hidden_words(store: PersonaStore, audience: Audience) -> PrivateWords:
    """The words a conversation of ``audience`` may not be shown: none for the person, those only items of the
    person's own tier or a note they kept to themself stand on for anyone else (``tiers.private_words``)."""
    if audience == SELF:
        return PrivateWords()
    return private_words(store.list_items(include_rejected=True), store.item_tiers(), store.private_note_sources())
