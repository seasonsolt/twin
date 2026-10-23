"""补一补: a few questions about what the twin does not know of its person yet, answered in a line or two.

Which facets are asked about comes from the coverage report: those the twin does not know (level 0) or only
mentions (level 1), in the order it suggests them to collect. Facets the person keeps to themself by default are not
asked about unprompted, only when they open one (``facet`` or ``dimension``). The questions are the questionnaire's
(``persona.questionnaire``); nothing new is asked of the model.

An answer is first read like any new memory is (the extraction of ``persona.profile``, the same prompt, run on that
answer alone and not stored): what it finds is a draft, the conclusions as they would become memories. The person
looks at the draft and says for each whether colleagues may use it, only they may, or it is not kept; only then is
anything stored. A kept conclusion is stored as a source in the person's words (``persona.sources.parse_answer``),
with the tier they chose (``PersonaStore.set_note_tier``), and the next build makes the memory of it like of any
other source.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Literal

from ..config import Settings
from ..llm import LLM
from .coverage import FacetCoverage, coverage_report, facet_coverage
from .dimensions import FACET_BY_ID, facets_of
from .items import PersonaItem, PEvidence
from .profile import chunks_of, consented_facets, extract_chunk
from .questionnaire import QUESTIONS, Question
from .schema import EvidenceClass, ParsedSource, SourceKind
from .sources import ExpressionView, parse_answer
from .store import PersonaStore
from .tiers import COLLEAGUE, SELF, Tier, default_tier

# How many questions one sitting asks, and how many conclusions an answer is read into at most.
QUESTIONS_PER_SITTING = 3
MAX_DRAFTS = 6
MAX_ANSWER_CHARS = 2000
MAX_STATEMENT_CHARS = 300
ORIGIN = "fill:"

Choice = Literal["colleague", "self", "none"]


@dataclass(frozen=True)
class Ask:
    """One question, asked for a facet."""

    question_id: str
    text: str
    facet_id: str
    facet_name: str
    dimension_id: str
    level: int
    # The tier a conclusion of this facet starts in.
    tier: Tier


@dataclass(frozen=True)
class Draft:
    """What an answer was read into: a conclusion for a facet, and the tier it starts in."""

    facet_id: str
    facet_name: str
    statement: str
    tier: Tier


@dataclass(frozen=True)
class Kept:
    """A conclusion the person looked at and chose a tier for."""

    facet_id: str
    statement: str
    choice: Choice


@dataclass(frozen=True)
class Change:
    """How well a facet is known now and once the conclusions that are kept are stored."""

    facet_id: str
    facet_name: str
    before: int
    after: int


def question_for(facet_id: str) -> Question | None:
    """The questionnaire's first question that is about the facet."""
    return next((q for q in QUESTIONS if facet_id in q.facets), None)


def _asking(facets: Iterable[FacetCoverage], limit: int) -> list[Ask]:
    asked: list[Ask] = []
    used: set[str] = set()
    for f in facets:
        question = question_for(f.facet_id)
        if question is None or question.qid in used:
            continue
        used.add(question.qid)
        asked.append(
            Ask(
                question.qid,
                question.text,
                f.facet_id,
                f.name,
                f.dimension_id,
                f.level,
                default_tier(f.facet_id),
            )
        )
        if len(asked) == limit:
            break
    return asked


def questions_for(
    items: Sequence[PersonaItem],
    consented: frozenset[str],
    *,
    facet: str | None = None,
    dimension: str | None = None,
    demand: dict[str, tuple[int, int]] | None = None,
    limit: int = QUESTIONS_PER_SITTING,
) -> list[Ask]:
    """The questions to ask next. By default for the facets the twin knows least, in the order it would collect them,
    leaving out those the person keeps to themself; for one ``facet`` or the facets of one ``dimension`` that the twin
    does not know enough of, whichever tier they are in, since the person asked."""
    report = coverage_report(items, consented, demand=demand)
    by_id = {f.facet_id: f for f in report.facets}
    if facet is not None:
        found = by_id.get(facet)
        return _asking([found], 1) if found is not None and found.consented else []
    if dimension is not None:
        known = {f.facet_id for f in facets_of(dimension)}
        wanted = [by_id[s.facet_id] for s in report.suggestions if s.facet_id in known]
        return _asking(wanted, limit)
    wanted = [by_id[s.facet_id] for s in report.suggestions if default_tier(s.facet_id) == COLLEAGUE]
    return _asking(wanted, limit)


def draft(store: PersonaStore, llm: LLM, settings: Settings, name: str, ask: Ask, answer: str) -> list[Draft]:
    """The conclusions the answer is read into, to be looked at before anything is kept. Nothing is stored. A name of
    another person the twin's sources know goes to the model as a code, as in every build, and comes back as the
    name."""
    answer = answer.strip()
    if not 1 <= len(answer) <= MAX_ANSWER_CHARS:
        raise ValueError(f"回答需要 1–{MAX_ANSWER_CHARS} 个字")
    parsed = parse_answer(ask.text, answer, name, f"{ORIGIN}{ask.question_id}", channel="补一补")
    view = ExpressionView(store, settings)
    shown = [
        e.model_copy(update={"text": view.mask(e.text), "context": view.mask(e.context)}) for e in parsed.expressions
    ]
    allowed = consented_facets(store) | {ask.facet_id}
    named = settings.model_copy(update={"target_name": name})
    drafts: list[Draft] = []
    seen: set[str] = set()
    for chunk in chunks_of(parsed.source, shown, allowed):
        for candidate in extract_chunk(llm, chunk, allowed, named).candidates:
            statement = " ".join(view.restore(candidate.statement).split())
            if not statement or statement in seen or candidate.facet_id not in FACET_BY_ID:
                continue
            seen.add(statement)
            facet = FACET_BY_ID[candidate.facet_id]
            drafts.append(
                Draft(facet.facet_id, facet.name, statement[:MAX_STATEMENT_CHARS], default_tier(facet.facet_id))
            )
    return drafts[:MAX_DRAFTS]


def _source_of(ask_text: str, name: str, ask_id: str, kept: Kept, today: dt.date) -> ParsedSource:
    digest = hashlib.sha256(f"{kept.facet_id}\x1f{kept.statement}".encode()).hexdigest()[:10]
    return parse_answer(ask_text, kept.statement, name, f"{ORIGIN}{ask_id}:{digest}", date=today, channel="补一补")


def _expected(parsed: ParsedSource, kept: Kept, today: dt.date) -> PersonaItem:
    """The item a kept conclusion becomes, as far as coverage can tell: the person's own words, on this day."""
    source = parsed.source
    return PersonaItem(
        item_id=f"fill_{source.source_id}",
        facet_id=kept.facet_id,
        statement=kept.statement,
        evidence=[
            PEvidence(
                expression_id=parsed.expressions[0].expression_id,
                source_id=source.source_id,
                source_kind=SourceKind.INTERVIEW,
                evidence_class=EvidenceClass.SELF_REPORT,
                date=today,
                quote=kept.statement,
                own_words=True,
            )
        ],
    )


def changes(
    items: Sequence[PersonaItem],
    consented: frozenset[str],
    ask: Ask,
    name: str,
    kept: Sequence[Kept],
    today: dt.date | None = None,
) -> list[Change]:
    """How well each facet the kept conclusions are about is known now, and once they are stored: the person is told
    what the answer is worth before they keep it."""
    today = today or dt.date.today()
    chosen = [k for k in kept if k.choice != "none"]
    facets = list(dict.fromkeys([ask.facet_id, *(k.facet_id for k in chosen)]))
    added = [_expected(_source_of(ask.text, name, ask.question_id, k, today), k, today) for k in chosen]
    found: list[Change] = []
    for facet in facets:
        own = [i for i in items if i.facet_id == facet]
        before = facet_coverage(facet, own, today, facet in consented).level
        after = facet_coverage(facet, [*own, *(i for i in added if i.facet_id == facet)], today, facet in consented)
        found.append(Change(facet, FACET_BY_ID[facet].name, before, after.level))
    return found


def keep(store: PersonaStore, ask: Ask, name: str, kept: Sequence[Kept], today: dt.date | None = None) -> list[str]:
    """Store the conclusions the person chose to keep, each as a source in its tier; returns the ids of the sources.
    The next build makes their memories."""
    today = today or dt.date.today()
    stored: list[str] = []
    for conclusion in kept:
        if conclusion.choice == "none":
            continue
        parsed = _source_of(ask.text, name, ask.question_id, conclusion, today)
        store.put_source(parsed)
        store.set_note_tier(parsed.source.source_id, SELF if conclusion.choice == "self" else COLLEAGUE)
        stored.append(parsed.source.source_id)
    return stored
