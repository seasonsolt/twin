"""Two tiers of memory: what colleagues' conversations may use, and what only the person themself may.

The tier of an item is its facet's default (``DEFAULT_TIERS``) unless the person changed it; only the changes are
stored (``PersonaStore.item_tiers``). The defaults live here, apart from ``dimensions.py`` and outside the kernel's
fingerprints on purpose: moving a facet to another tier changes nothing that was extracted, so it must not make every
store rebuild its memories. ``audience`` is the tier a conversation answers from, fixed when it is created: a
conversation of the person themself ("self") may use every item, a colleague's ("colleague") only the colleague tier,
and not the words only such items stand on (``private_expressions``). An heir's ("heir:<heir_id>", P2.4) uses what
the person's will gives that heir (``HeirGrant``, resolved by ``persona.heirs``): the tiers above are about
colleagues and do not decide it, except that an item the person themself marked as only theirs stays theirs unless
the will names its facet singly (``heir_usable``); with no grant, or an empty one, an heir is given nothing.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from typing import Literal

from .dimensions import FACETS
from .items import PersonaItem
from .schema import ReviewStatus

Tier = Literal["colleague", "self"]
# "colleague", "self", or "heir:" and the id of an heir in the person's will (``heir_audience``).
Audience = str
COLLEAGUE: Tier = "colleague"
SELF: Tier = "self"
TIERS: tuple[Tier, ...] = (COLLEAGUE, SELF)
TIER_LABELS: dict[Tier, str] = {COLLEAGUE: "同事能用", SELF: "只有本人能用"}
HEIR_PREFIX = "heir:"


def heir_audience(heir_id: str) -> Audience:
    """The audience of a conversation of the heir ``heir_id``."""
    return HEIR_PREFIX + heir_id


def heir_of(audience: Audience) -> str | None:
    """The heir an audience is of; None for the person and their colleagues."""
    return audience[len(HEIR_PREFIX) :] if audience.startswith(HEIR_PREFIX) else None


def is_heir(audience: Audience) -> bool:
    return heir_of(audience) is not None


@dataclass(frozen=True)
class HeirGrant:
    """What the will gives one heir (``persona.will``): every facet given (``facets``), those of them named singly
    (``single``), which also open the items the person marked as only theirs, and the topics never to be talked about
    (``avoid``). The empty grant gives nothing: an heir the will no longer names, or a will that cannot be read."""

    facets: frozenset[str] = frozenset()
    single: frozenset[str] = frozenset()
    avoid: tuple[str, ...] = ()


NOTHING = HeirGrant()

# Work views, abilities, speech and how the person deals with people are fair for a colleague to ask about; family,
# health, daily habits, tastes and what is still on the person's mind are theirs. Hobbies and tastes (9.1, 9.5) are
# not settled yet: they start private, and the person can open them item by item. What the person hopes to leave,
# how they meet death and loss, and where their worth and meaning lie (D10) are theirs alone.
_SELF_FACETS = frozenset({"1.3", "7.5", "8.3", "9.1", "9.2", "9.3", "9.4", "9.5", "10.1", "10.2", "10.3", "10.4"})
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
    """Whether a conversation of ``audience`` may use an item of ``tier``; an heir's is decided by the will
    (``heir_usable``), not by the tier, so this is never true for one."""
    return audience == SELF or (audience == COLLEAGUE and tier == COLLEAGUE)


def heir_usable(item: PersonaItem, overrides: Mapping[str, str], grant: HeirGrant) -> bool:
    """Whether an heir with ``grant`` may use the item: its facet is given, and the person did not mark the item as
    only theirs, unless the will names its facet singly. A facet's default tier is about colleagues and does not count:
    a will that gives family gives the family items, which are the person's own by default."""
    if item.facet_id not in grant.facets:
        return False
    return overrides.get(item.item_id) != SELF or item.facet_id in grant.single


def for_audience(
    items: Iterable[PersonaItem], overrides: Mapping[str, str], audience: Audience, grant: HeirGrant | None = None
) -> list[PersonaItem]:
    """The items a conversation of ``audience`` may use; an heir's those ``grant`` gives (none without one). Anything
    but the person themself, a colleague or an heir is given what a colleague is."""
    if audience == SELF:
        return list(items)
    if is_heir(audience):
        return [i for i in items if heir_usable(i, overrides, grant or NOTHING)]
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
    or not yet standing under any item. An expression's id starts with its source's id. ``allowed``, for an heir
    (``heir_words``), turns it around: every word not in it is hidden too."""

    ids: frozenset[str] = frozenset()
    sources: frozenset[str] = frozenset()
    allowed: frozenset[str] | None = None

    def __contains__(self, ref: object) -> bool:
        if not isinstance(ref, str):
            return False
        if ref in self.ids or ref.split("#", 1)[0] in self.sources:
            return True
        return self.allowed is not None and ref not in self.allowed

    def __bool__(self) -> bool:
        return bool(self.ids or self.sources) or self.allowed is not None


def private_words(
    items: Iterable[PersonaItem], overrides: Mapping[str, str], private_sources: Collection[str] = ()
) -> PrivateWords:
    return PrivateWords(frozenset(private_expressions(items, overrides)), frozenset(private_sources))


def heir_words(
    items: Iterable[PersonaItem], overrides: Mapping[str, str], grant: HeirGrant, private_sources: Collection[str] = ()
) -> PrivateWords:
    """The words an heir may be shown, as the only ones (``PrivateWords.allowed``): the evidence of the items the will
    gives them (``heir_usable``), rejected items opening none. Words standing under no such item, what other people
    said included, are not given: the will gives facets, and they are of none it names. A note the person kept to
    themself opens only through an item of a facet the will names singly."""
    allowed: set[str] = set()
    for item in items:
        if item.review is ReviewStatus.REJECTED or not heir_usable(item, overrides, grant):
            continue
        single = item.facet_id in grant.single
        allowed.update(e.expression_id for e in item.evidence if single or e.source_id not in private_sources)
    return PrivateWords(allowed=frozenset(allowed))


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
