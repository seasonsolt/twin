"""Lenses: a person lends their judgement to colleagues, one aspect at a time.

A lens is published by the person themself (``web.lenses`` refuses everyone else, managers included). It opens some of
four aspects, what they value, how they decide, how they think and what they are good at, and says to whom. An aspect
opens all its facets; it can be opened when at least one of them is well founded, and a lens speaks only from the facets
that are, so the others join as the twin comes to know them. A facet is well founded when the twin knows a good deal of
it (level 3 of ``persona.coverage``, which already asks for several occasions, the person's own words and more than one
kind of source) and nothing in it contradicts (``judge``). The person's own tier never counts: what they keep to
themself cannot be lent.

A lens answers with what the opened facets hold and nothing it makes up: the statements closest to the question, each
with the words it stands on, said to be inferred from what the person said and not their opinion. What it does not
open, and what only the person can settle (a price, a discount, an approval), it says is theirs to answer. It never
hands anything over to the person and never writes anything; a colleague who wants the person's own answer asks them,
which is another thing, in their own name.

What each use was is kept for the person (``lens_uses``): the question and what the lens said, on the day. Not who
asked, and not the conversation: the person sees what their judgement was used for, never by whom, and corrects what
was wrong. A facet corrected ``STOP_AFTER`` times is no longer used until the person opens it again. A lens held or
taken back is not used from that moment, and an opened facet that no longer passes (a contradiction came in, the person
made the memories private) stops with it.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np

from .config import Settings
from .embed import Embedder, EmbedError, embedder_fingerprint
from .persona import gate
from .persona.chat import ITEMS_NS, OWNER_CUE, _visible_items, item_text
from .persona.coverage import CHECKED_LABEL, LEVEL_LABELS, facet_coverage
from .persona.dimensions import DIMENSIONS, FACET_BY_ID, FACETS
from .persona.items import PersonaItem
from .persona.lexical import tokenize
from .persona.schema import SOURCE_KIND_LABELS
from .persona.store import PersonaStore
from .persona.tiers import COLLEAGUE, for_audience, private_words
from .teamdb import Lens, LensUnavailable, LensUse, TeamDB

# Judgement, not the person: what they value, how they decide, how they think, what they are good at. Experience, how
# they speak and their life are never lent.
LENS_DIMENSIONS: tuple[str, ...] = ("D2", "D3", "D4", "D5")
LENS_FACETS: tuple[str, ...] = tuple(f.facet_id for f in FACETS if f.dimension_id in LENS_DIMENSIONS)
ASPECT_NAMES: dict[str, str] = {d.dimension_id: d.name for d in DIMENSIONS if d.dimension_id in LENS_DIMENSIONS}
# Corrections of one facet after which it is no longer used.
STOP_AFTER = 3
NAME_MAX = 20
NAME_MIN = 1
# How many statements a lens answers with, and how much of the words behind each is shown.
ANSWER_VIEWS = 3
EVIDENCE_SHOWN = 2
QUOTE_CHARS = 120
# Items count as about the question when they share this many words with it (at least two) or are this near by meaning.
OVERLAP = 0.2
FLOOR_MARGIN = 0.3
FLOOR_MIN = 0.3
# A price, a discount, an approval: the person's to settle, whatever the lens holds.
SETTLED_BY_PERSON = re.compile(r"价格|报价|折扣|降价|让价|优惠|特批|审批|批准|签字|预算多少|降多少|多少钱")

Scope = Literal["team", "people"]


class LensRefused(ValueError):
    """The change cannot be made as asked; the message says why, for the person."""


# ---------------------------------------------------------------- who may use a lens


@dataclass(frozen=True)
class LensAudience:
    """Whom a lens is for: every colleague, or colleagues named by their twin (a person is known by the twin they
    took)."""

    scope: Scope = "team"
    twins: tuple[str, ...] = ()

    def encode(self) -> str:
        return json.dumps({"scope": self.scope, "twins": list(self.twins)}, ensure_ascii=False)

    @staticmethod
    def decode(text: str) -> LensAudience:
        try:
            data = json.loads(text)
            scope: Scope = "people" if data.get("scope") == "people" else "team"
            return LensAudience(scope, tuple(str(t) for t in data.get("twins", ())) if scope == "people" else ())
        except (ValueError, AttributeError):
            # An audience that cannot be read admits nobody.
            return LensAudience("people", ())

    def admits(self, viewer_twins: Collection[str]) -> bool:
        """Whether a colleague who has taken ``viewer_twins`` may use the lens."""
        return self.scope == "team" or bool(set(self.twins) & set(viewer_twins))


# ---------------------------------------------------------------- which facets can be opened


@dataclass(frozen=True)
class FacetVerdict:
    """One facet as a lens would open it: what colleagues may use of it, and whether that is well founded."""

    facet_id: str
    name: str
    dimension_id: str
    dimension: str
    items: int
    level: int
    label: str
    checked: bool
    occasions: int
    ok: bool
    # Why not, in a few words each; empty when it can be opened.
    reasons: tuple[str, ...]

    def view(self) -> dict[str, Any]:
        return {
            "facet_id": self.facet_id,
            "name": self.name,
            "dimension_id": self.dimension_id,
            "dimension": self.dimension,
            "level": self.level,
            "label": self.label,
            "checked": self.checked,
            "checked_label": CHECKED_LABEL if self.checked else "",
            "occasions": self.occasions,
            "ok": self.ok,
            "reasons": list(self.reasons),
        }


def judge(
    items: Sequence[PersonaItem],
    tiers: Mapping[str, str],
    as_of: dt.date | None = None,
) -> list[FacetVerdict]:
    """Every facet a lens may open, with whether it can be, from the memories colleagues may use (``items`` with the
    tiers the person set): the twin knows a good deal of it and nothing in it contradicts, one reason for each that
    fails."""
    day = as_of or dt.date.today()
    usable = for_audience(items, tiers, COLLEAGUE)
    everything: dict[str, int] = {}
    for item in items:
        everything[item.facet_id] = everything.get(item.facet_id, 0) + 1
    by_facet: dict[str, list[PersonaItem]] = {}
    for item in usable:
        by_facet.setdefault(item.facet_id, []).append(item)
    out: list[FacetVerdict] = []
    dimensions = {d.dimension_id: d.name for d in DIMENSIONS}
    for facet_id in LENS_FACETS:
        facet = FACET_BY_ID[facet_id]
        own = by_facet.get(facet_id, [])
        covered = facet_coverage(facet_id, own, day, True)
        reasons: list[str] = []
        if not own:
            reasons.append("只有本人能用" if everything.get(facet_id) else "还没有记忆")
        else:
            # The level already weighs the occasions, the person's own words and the kinds of source.
            if covered.level < 3:
                reasons.append("了解还不够多")
            if covered.conflicts:
                reasons.append("内容有矛盾")
        out.append(
            FacetVerdict(
                facet_id,
                facet.name,
                facet.dimension_id,
                dimensions[facet.dimension_id],
                len(own),
                covered.level,
                LEVEL_LABELS[covered.level],
                covered.checked,
                covered.occasions,
                not reasons,
                tuple(reasons),
            )
        )
    return out


def stopped(lens: Lens, corrections: Mapping[str, int]) -> list[str]:
    """The opened facets that were corrected ``STOP_AFTER`` times since they were last opened by the person."""
    return [f for f in lens.facets if corrections.get(f, 0) - lens.forgiven.get(f, 0) >= STOP_AFTER]


def in_use(lens: Lens, verdicts: Iterable[FacetVerdict], corrections: Mapping[str, int]) -> list[str]:
    """The facets a lens speaks from now: the ones opened that still pass and were not corrected out, in the order of
    the taxonomy."""
    passing = {v.facet_id for v in verdicts if v.ok}
    off = set(stopped(lens, corrections))
    return [f for f in LENS_FACETS if f in lens.facets and f in passing and f not in off]


# ---------------------------------------------------------------- what a lens says


@dataclass(frozen=True)
class Basis:
    """Words a statement stands on: what the person said, when, and where it was said."""

    quote: str
    date: str | None
    kind: str


@dataclass(frozen=True)
class LensView:
    facet_id: str
    facet: str
    text: str
    basis: tuple[Basis, ...]

    def view(self) -> dict[str, Any]:
        return {
            "facet_id": self.facet_id,
            "facet": self.facet,
            "text": self.text,
            "basis": [{"quote": b.quote, "date": b.date, "kind": b.kind} for b in self.basis],
        }


@dataclass(frozen=True)
class LensAnswer:
    """What a lens said to a question: statements with their basis, and whether part of the matter is the person's to
    settle (or nothing here speaks to it) so that the asker is pointed at them."""

    views: tuple[LensView, ...]
    settled_by_person: bool

    @property
    def facets(self) -> list[str]:
        return list(dict.fromkeys(v.facet_id for v in self.views))

    @property
    def said(self) -> str:
        """What the lens said, as text: the statements, one to a line."""
        return "\n".join(v.text for v in self.views)


def _basis(item: PersonaItem, hidden: Any) -> tuple[Basis, ...]:
    """The words an item stands on that may be shown to a colleague: the person's own first, then the newest."""
    shown = [e for e in item.evidence if e.expression_id not in hidden]
    shown.sort(key=lambda e: (not e.own_words, -(e.date.toordinal() if e.date else 0), e.expression_id))
    return tuple(
        Basis(
            " ".join(e.quote.split())[:QUOTE_CHARS],
            e.date.isoformat() if e.date else None,
            SOURCE_KIND_LABELS.get(e.source_kind, ""),
        )
        for e in shown[:EVIDENCE_SHOWN]
        if e.quote.strip()
    )


def _relevant(
    question: str,
    items: Sequence[PersonaItem],
    vectors: tuple[list[str], np.ndarray],
    query: np.ndarray | None,
    floor: float,
) -> list[PersonaItem]:
    """The items about the question, the closest first: those that share enough words with it, or are near it by
    meaning when the stored vectors are in the space the question was embedded in."""
    wanted = set(tokenize(question))
    sims: dict[str, float] = {}
    if query is not None and vectors[0]:
        ids, matrix = vectors
        sims = dict(zip(ids, (float(s) for s in matrix @ query), strict=True))
    scored: list[tuple[float, int, str, PersonaItem]] = []
    for item in items:
        shared = len(wanted & set(tokenize(item_text(item)))) if wanted else 0
        by_words = shared >= 2 and shared / len(wanted) >= OVERLAP
        near = sims.get(item.item_id, 0.0)
        by_meaning = near >= floor
        if by_words or by_meaning:
            scored.append((near, shared, item.item_id, item))
    scored.sort(key=lambda row: (-row[0], -row[1], row[2]))
    return [row[3] for row in scored]


def speak(
    question: str,
    items: Sequence[PersonaItem],
    facets: Collection[str],
    *,
    hidden: Any = (),
    vectors: tuple[list[str], np.ndarray] = ([], np.zeros((0, 0), dtype=np.float32)),
    query: np.ndarray | None = None,
    floor: float = FLOOR_MIN,
) -> LensAnswer:
    """What a lens that speaks from ``facets`` says to ``question``: the statements of ``items`` (already only what
    colleagues may use, in the privacy view) nearest to it, at most two of a facet; nothing at all
    when none is about it. A matter of price, discount or approval is marked as the person's, whatever else is said."""
    pool = [i for i in items if i.facet_id in facets]
    found = _relevant(question, pool, vectors, query, floor)
    views: list[LensView] = []
    per_facet: dict[str, int] = {}
    for item in found:
        if per_facet.get(item.facet_id, 0) >= 2:
            continue
        per_facet[item.facet_id] = per_facet.get(item.facet_id, 0) + 1
        views.append(LensView(item.facet_id, FACET_BY_ID[item.facet_id].name, item.statement, _basis(item, hidden)))
        if len(views) >= ANSWER_VIEWS:
            break
    return LensAnswer(tuple(views), bool(SETTLED_BY_PERSON.search(question) or OWNER_CUE.search(question)))


def sample(items: Sequence[PersonaItem], facets: Collection[str], hidden: Any = ()) -> LensAnswer:
    """How a lens that opens ``facets`` reads, for the person to see before publishing it: the best-founded statement
    of each facet, at most ``ANSWER_VIEWS``."""
    views: list[LensView] = []
    for facet_id in LENS_FACETS:
        if facet_id not in facets:
            continue
        own = sorted(
            (i for i in items if i.facet_id == facet_id), key=lambda i: (-i.occasions(), -len(i.evidence), i.item_id)
        )
        if own:
            views.append(LensView(facet_id, FACET_BY_ID[facet_id].name, own[0].statement, _basis(own[0], hidden)))
        if len(views) >= ANSWER_VIEWS:
            break
    return LensAnswer(tuple(views), True)


# ---------------------------------------------------------------- the service


def clean_name(name: str) -> str:
    cleaned = " ".join(name.split())
    if not NAME_MIN <= len(cleaned) <= NAME_MAX:
        raise LensRefused(f"名字请写 {NAME_MIN}–{NAME_MAX} 个字")
    return cleaned


class Lenses:
    """The lenses of the team: published, held and taken back by the person whose they are, and used by colleagues."""

    def __init__(self, team: TeamDB, clock: Callable[[], dt.datetime] | None = None) -> None:
        self.team = team
        self._clock = clock or (lambda: dt.datetime.now(dt.UTC))

    def today(self) -> dt.date:
        return self._clock().date()

    # -- the person's side

    def verdicts(self, store: PersonaStore) -> list[FacetVerdict]:
        return judge(store.list_items(), store.item_tiers(), self.today())

    def _own(self, persona_id: str, lens_id: str) -> Lens:
        lens = self.team.get_lens(lens_id)
        if lens is None or lens.persona_id != persona_id:
            raise KeyError(lens_id)
        return lens

    def _checked_facets(self, store: PersonaStore, facets: Sequence[str]) -> list[str]:
        """The facets to open, in the taxonomy's order; refused when one is not a facet a lens may open, or when no
        facet of an aspect they belong to passes (the others of a passing aspect wait until they do)."""
        chosen = list(dict.fromkeys(facets))
        if not chosen:
            raise LensRefused("请至少开放一个方面")
        unknown = [f for f in chosen if f not in LENS_FACETS]
        if unknown:
            raise LensRefused("这个方面不能开放：赋能只借看重什么、怎么做决定、怎么思考和擅长什么")
        passing = {v.facet_id for v in self.verdicts(store) if v.ok}
        aspects = list(dict.fromkeys(FACET_BY_ID[f].dimension_id for f in chosen))
        failing = [d for d in aspects if not any(FACET_BY_ID[f].dimension_id == d for f in chosen if f in passing)]
        if failing:
            raise LensRefused("还不能开放：" + "、".join(ASPECT_NAMES[d] for d in failing) + "（了解还不够多）")
        return [f for f in LENS_FACETS if f in chosen]

    def publish(
        self, store: PersonaStore, persona_id: str, name: str, facets: Sequence[str], audience: LensAudience
    ) -> Lens:
        label = clean_name(name)
        opened = self._checked_facets(store, facets)
        return self.team.create_lens(
            persona_id=persona_id, name=label, facets=opened, audience=audience.encode(), now=self._clock()
        )

    def adjust(
        self,
        store: PersonaStore,
        persona_id: str,
        lens_id: str,
        *,
        name: str | None = None,
        facets: Sequence[str] | None = None,
        audience: LensAudience | None = None,
        reopen: Collection[str] = (),
    ) -> Lens:
        """Change what a lens opens or to whom. A facet that was corrected out stays out, however often the lens is
        saved, until the person opens it afresh (``reopen``); one that was taken out and is put back also opens afresh.
        Either way the corrections so far stop counting."""
        lens = self._own(persona_id, lens_id)
        opened = None if facets is None else self._checked_facets(store, facets)
        forgiven = None
        if opened is not None:
            counts = self.team.corrections(lens.id)
            forgiven = dict(lens.forgiven)
            # Opened again: one corrected out that the person opens afresh, and one taken out and put back (whose
            # corrections would otherwise still count against it).
            again = [f for f in stopped(lens, counts) if f in reopen]
            for facet in [*again, *(f for f in opened if f not in lens.facets)]:
                if facet in opened:
                    forgiven[facet] = counts.get(facet, 0)
        return self.team.update_lens(
            lens.id,
            name=None if name is None else clean_name(name),
            facets=opened,
            audience=None if audience is None else audience.encode(),
            forgiven=forgiven,
        )

    def hold(self, persona_id: str, lens_id: str) -> Lens:
        return self.team.set_lens_status(self._own(persona_id, lens_id).id, "paused", self._clock())

    def resume(self, persona_id: str, lens_id: str) -> Lens:
        return self.team.set_lens_status(self._own(persona_id, lens_id).id, "active", self._clock())

    def withdraw(self, persona_id: str, lens_id: str) -> Lens:
        return self.team.set_lens_status(self._own(persona_id, lens_id).id, "withdrawn", self._clock())

    def withdraw_all(self, persona_id: str) -> None:
        """Take back every lens of a twin whose person said "这不是我": a lens is its person's own judgement lent out,
        and whoever claims the twin next has not lent it."""
        for lens in self.team.lenses(persona_id=persona_id, statuses=("active", "paused")):
            self.team.set_lens_status(lens.id, "withdrawn", self._clock())

    def correct(self, persona_id: str, lens_id: str, use_id: str) -> LensUse:
        lens = self._own(persona_id, lens_id)
        use = self.team.get_lens_use(use_id)
        if use is None or use.lens_id != lens.id:
            raise KeyError(use_id)
        found = self.team.correct_lens_use(use.id)
        assert found is not None
        return found

    def view(self, lens: Lens, store: PersonaStore) -> dict[str, Any]:
        """A lens as its person sees it: what it opens and what of that is in use, which facets were corrected out,
        and how much it was used this week."""
        counts = self.team.corrections(lens.id)
        verdicts = self.verdicts(store)
        speaking = in_use(lens, verdicts, counts)
        off = stopped(lens, counts)
        week = self.team.count_lens_uses(lens.id, self.today() - dt.timedelta(days=6))
        audience = LensAudience.decode(lens.audience)
        return {
            "id": lens.id,
            "name": lens.name,
            "status": lens.status,
            "published_at": lens.published_at,
            "audience": {"scope": audience.scope, "twins": list(audience.twins)},
            "facets": [
                {
                    "facet_id": f,
                    "name": FACET_BY_ID[f].name,
                    "dimension_id": FACET_BY_ID[f].dimension_id,
                    "dimension": ASPECT_NAMES[FACET_BY_ID[f].dimension_id],
                }
                for f in lens.facets
            ],
            "speaking": speaking,
            # Opened, and no longer passing (a contradiction, a tier changed): not used until they pass again.
            "failing": [f for f in lens.facets if f not in speaking and f not in off],
            "stopped": [{"facet_id": f, "name": FACET_BY_ID[f].name, "corrected": counts.get(f, 0)} for f in off],
            "uses_week": week,
        }

    def use_view(self, use: LensUse) -> dict[str, Any]:
        return {
            "id": use.id,
            "question": use.question,
            "said": use.said,
            "facets": [{"facet_id": f, "name": FACET_BY_ID[f].name} for f in use.facets if f in FACET_BY_ID],
            "corrected": use.corrected,
            "at": use.at,
        }

    # -- the colleague's side

    def available(self, persona_id: str, viewer_twins: Collection[str]) -> list[Lens]:
        """The lenses of one twin in force that a colleague who has taken ``viewer_twins`` may use."""
        return [
            lens
            for lens in self.team.lenses(persona_id=persona_id, statuses=("active",))
            if LensAudience.decode(lens.audience).admits(viewer_twins)
        ]

    def answer(
        self,
        lens: Lens,
        store: PersonaStore,
        settings: Settings,
        question: str,
        embedder: Embedder | None,
    ) -> LensAnswer:
        """What the lens says to a colleague's question, and the use kept (the question and what it said, on the day;
        not who asked). ``MemoryUpdating`` while the twin's memory is being rebuilt from changed recordings;
        ``LensUnavailable`` when the lens is held or taken back (checked as the use is written, so a pause takes
        hold at once)."""
        gate.version(store)
        items = store.list_items()
        tiers = store.item_tiers()
        verdicts = judge(items, tiers, self.today())
        facets = in_use(lens, verdicts, self.team.corrections(lens.id))
        hidden = private_words(store.list_items(include_rejected=True), tiers, store.private_note_sources())
        visible = for_audience(_visible_items(store, settings, None), tiers, COLLEAGUE)
        vectors: tuple[list[str], np.ndarray] = ([], np.zeros((0, 0), dtype=np.float32))
        query: np.ndarray | None = None
        floor = FLOOR_MIN
        if embedder is not None and facets:
            try:
                query = np.asarray(embedder.embed([question[:2000]])[0], dtype=np.float32)
                if store.get_meta(f"embedder:{ITEMS_NS}") == embedder_fingerprint(embedder):
                    vectors = store.get_vectors(ITEMS_NS)
                floor = max(FLOOR_MIN, float(embedder.cluster_threshold) - FLOOR_MARGIN)
            except EmbedError:
                query = None
        said = speak(question, visible, facets, hidden=hidden, vectors=vectors, query=query, floor=floor)
        self.team.record_lens_use(lens.id, question[:2000], said.said, said.facets, self.today())
        return said

    def preview(self, store: PersonaStore, settings: Settings, facets: Sequence[str]) -> LensAnswer:
        """How a lens opening ``facets`` would read, nothing kept: the best-founded statements of the ones that pass."""
        passing = {v.facet_id for v in self.verdicts(store) if v.ok}
        items = for_audience(_visible_items(store, settings, None), store.item_tiers(), COLLEAGUE)
        hidden = private_words(
            store.list_items(include_rejected=True), store.item_tiers(), store.private_note_sources()
        )
        return sample(items, [f for f in facets if f in passing], hidden)


__all__ = [
    "LENS_FACETS",
    "STOP_AFTER",
    "FacetVerdict",
    "Lens",
    "LensAnswer",
    "LensAudience",
    "LensRefused",
    "LensUnavailable",
    "Lenses",
    "judge",
    "speak",
]
