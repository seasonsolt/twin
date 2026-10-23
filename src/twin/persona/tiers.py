"""Two tiers of memory: what colleagues' conversations may use, and what only the person themself may.

The tier of an item is its facet's default (``DEFAULT_TIERS``) unless the person changed it; only the changes are
stored (``PersonaStore.item_tiers``). The defaults live here, apart from ``dimensions.py`` and outside the kernel's
fingerprints on purpose: moving a facet to another tier changes nothing that was extracted, so it must not make every
store rebuild its memories. ``audience`` is the tier a conversation answers from, fixed when it is created: a
conversation of the person themself ("self") may use every item, any other ("colleague") only the colleague tier,
and not the words only such items stand on (``private_expressions``).
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from typing import Literal

from .dimensions import FACETS
from .items import PersonaItem
from .schema import ReviewStatus

Tier = Literal["colleague", "self"]
Audience = Literal["colleague", "self"]
COLLEAGUE: Tier = "colleague"
SELF: Tier = "self"
TIERS: tuple[Tier, ...] = (COLLEAGUE, SELF)
TIER_LABELS: dict[Tier, str] = {COLLEAGUE: "同事能用", SELF: "只有本人能用"}

# Work views, abilities, speech and how the person deals with people are fair for a colleague to ask about; family,
# health, daily habits, tastes and what is still on the person's mind are theirs. Hobbies and tastes (9.1, 9.5) are
# not settled yet: they start private, and the person can open them item by item.
_SELF_FACETS = frozenset({"1.3", "7.5", "8.3", "9.1", "9.2", "9.3", "9.4", "9.5"})
DEFAULT_TIERS: dict[str, Tier] = {f.facet_id: SELF if f.facet_id in _SELF_FACETS else COLLEAGUE for f in FACETS}


def default_tier(facet_id: str) -> Tier:
    """The tier of the items of a facet; an unknown facet is the person's own."""
    return DEFAULT_TIERS.get(facet_id, SELF)


def item_tier(item: PersonaItem, overrides: Mapping[str, str]) -> Tier:
    """The item's tier: the person's change when there is one, else its facet's default."""
    chosen = overrides.get(item.item_id)
    if chosen in TIERS:
        return chosen
    return default_tier(item.facet_id)


def usable(tier: Tier, audience: Audience) -> bool:
    """Whether a conversation of ``audience`` may use an item of ``tier``."""
    return audience == SELF or tier == COLLEAGUE


def for_audience(items: Iterable[PersonaItem], overrides: Mapping[str, str], audience: Audience) -> list[PersonaItem]:
    """The items a conversation of ``audience`` may use."""
    if audience == SELF:
        return list(items)
    return [i for i in items if item_tier(i, overrides) == COLLEAGUE]


def private_expressions(items: Iterable[PersonaItem], overrides: Mapping[str, str]) -> set[str]:
    """Ids of the expressions only items of the person's own tier stand on. An item's evidence is the person's own
    words (or what others said to them), which the twin can also find as they are: leaving the item out while its
    quote stays retrievable would show a colleague the very thing the item keeps from them. An expression an item of
    the colleague tier stands on too stays, as it is not only the person's private matter. Pass the rejected items
    too: rejecting an item of the person's own tier does not open its words, and a rejected item opens none."""
    shared: set[str] = set()
    private: set[str] = set()
    for item in items:
        if item_tier(item, overrides) != COLLEAGUE:
            private.update(e.expression_id for e in item.evidence)
        elif item.review is not ReviewStatus.REJECTED:
            shared.update(e.expression_id for e in item.evidence)
    return private - shared


@dataclass(frozen=True)
class PrivateWords:
    """The words a conversation of the colleague tier may not be shown: expressions only the person's own items stand
    on (``private_expressions``), and every expression of a note the person kept to themself (``note_tier``), found
    or not yet standing under any item. An expression's id starts with its source's id."""

    ids: frozenset[str] = frozenset()
    sources: frozenset[str] = frozenset()

    def __contains__(self, ref: object) -> bool:
        return isinstance(ref, str) and (ref in self.ids or ref.split("#", 1)[0] in self.sources)

    def __bool__(self) -> bool:
        return bool(self.ids or self.sources)


def private_words(
    items: Iterable[PersonaItem], overrides: Mapping[str, str], private_sources: Collection[str] = ()
) -> PrivateWords:
    return PrivateWords(frozenset(private_expressions(items, overrides)), frozenset(private_sources))


def note_item_tier(item: PersonaItem, notes: Mapping[str, str]) -> Tier | None:
    """The tier the notes an item stands on give it: the person's own if any of them was kept to themself, the
    colleague tier if they all were opened, None where it stands on no note (its facet's default then)."""
    chosen = {notes[e.source_id] for e in item.evidence if e.source_id in notes}
    if SELF in chosen:
        return SELF
    return COLLEAGUE if COLLEAGUE in chosen else None


def carry_tiers(old: list[PersonaItem], new: list[PersonaItem], tiers: Mapping[str, str]) -> dict[str, Tier]:
    """Tiers the person set, for a facet's re-merged items: a new item takes the tier of an old item whose candidates
    it all still contains (the same trait, possibly with more evidence); where it covers several, the stricter wins.
    An item the person kept private whose candidates do not survive (a new prompt re-extracts them all) must not turn
    public by being rebuilt: every new item quoting any expression it stood on stays private. A tier the person
    opened is carried only along candidates, never by a guess."""
    by_candidate: dict[str, list[PersonaItem]] = {}
    by_expression: dict[str, list[PersonaItem]] = {}
    for item in new:
        for candidate in item.member_candidate_ids:
            by_candidate.setdefault(candidate, []).append(item)
        for expression in {e.expression_id for e in item.evidence}:
            by_expression.setdefault(expression, []).append(item)
    carried: dict[str, Tier] = {}

    def give(item_id: str, tier: Tier) -> None:
        if carried.get(item_id) != SELF:
            carried[item_id] = tier

    for o in old:
        tier = tiers.get(o.item_id)
        if tier not in TIERS:
            continue
        members = set(o.member_candidate_ids)
        heirs = {
            i.item_id: i for c in members for i in by_candidate.get(c, []) if members <= set(i.member_candidate_ids)
        }
        if heirs:
            for item_id in heirs:
                give(item_id, tier)
        elif tier == SELF:
            for expression in {e.expression_id for e in o.evidence}:
                for i in by_expression.get(expression, []):
                    give(i.item_id, SELF)
    return carried
