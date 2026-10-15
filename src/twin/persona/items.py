"""Persona profile records: candidates extracted from one chunk of expressions, and the items they merge into."""

from __future__ import annotations

import datetime as dt
from difflib import SequenceMatcher

from pydantic import BaseModel, Field, field_validator

from .schema import EvidenceClass, ReviewStatus, SourceKind, document_kind


class PEvidence(BaseModel):
    expression_id: str
    source_id: str
    source_kind: SourceKind
    evidence_class: EvidenceClass
    date: dt.date | None = None
    # Verbatim text located in the expression: the person's words, or narration about them (``own_words`` False).
    quote: str
    own_words: bool = True

    _legacy_kind = field_validator("source_kind", mode="before")(document_kind)


class PersonaCandidate(BaseModel):
    candidate_id: str
    chunk_id: str
    facet_id: str
    statement: str
    applies_when: str = ""
    evidence: list[PEvidence]


class ExtractStats(BaseModel):
    """What extraction calls returned and why conclusions were dropped: counts only, never text. Kept per chunk, so a
    source that yields no memory can tell a model that found nothing from conclusions that failed verification."""

    returned: int = 0  # conclusions the model returned
    kept: int = 0  # conclusions kept as candidates
    off_facet: int = 0  # dropped: a facet not offered (before counts were split: or an empty statement)
    empty_statement: int = 0  # dropped: an empty statement
    unsupported: int = 0  # dropped: none of its quotes survived
    quotes_unmatched: int = 0  # quotes not found in the entry they name
    quotes_misnumbered: int = 0  # quotes naming an entry the chunk does not have
    quotes_narrated_style: int = 0  # style quotes taken from someone else's narration
    splits: int = 0  # times a chunk was halved because its reply was cut off twice
    # What the model wrote as the facet of each ``off_facet`` conclusion, cut to FACET_SAMPLE_CHARS, and how often.
    unknown_facets: dict[str, int] = Field(default_factory=dict)

    def __add__(self, other: ExtractStats) -> ExtractStats:
        merged: dict[str, object] = {}
        for name in ExtractStats.model_fields:
            mine, theirs = getattr(self, name), getattr(other, name)
            if isinstance(mine, dict):
                merged[name] = {k: mine.get(k, 0) + theirs.get(k, 0) for k in sorted(mine.keys() | theirs.keys())}
            else:
                merged[name] = mine + theirs
        return ExtractStats.model_validate(merged)


FACET_SAMPLE_CHARS = 16


class PersonaItem(BaseModel):
    item_id: str
    facet_id: str
    statement: str
    applies_when: str = ""
    evidence: list[PEvidence]
    member_candidate_ids: list[str] = Field(default_factory=list)
    # Non-empty when what the person says about themself contradicts what they do (or two behaviors disagree).
    conflict: str = ""
    # The person's review, applied when items are listed (an edited statement replaces the extracted one).
    review: ReviewStatus = ReviewStatus.UNREVIEWED
    review_note: str = ""
    extracted_statement: str = ""

    @property
    def verified(self) -> bool:
        return self.review in (ReviewStatus.CONFIRMED, ReviewStatus.EDITED)

    def occasions(self, until: dt.date | None = None) -> int:
        """Distinct occasions backing the item: one per source and day (an undated source counts once)."""
        return len({(e.source_id, e.date) for e in self.evidence if until is None or (e.date and e.date <= until)})

    def classes(self) -> set[EvidenceClass]:
        return {e.evidence_class for e in self.evidence}

    def last_seen(self) -> dt.date | None:
        return max((e.date for e in self.evidence if e.date), default=None)


class PReview(BaseModel):
    status: ReviewStatus
    statement: str | None = None
    note: str = ""
    reviewed_at: str


def apply_review(item: PersonaItem, review: PReview | None) -> PersonaItem:
    if review is None:
        return item
    update: dict[str, object] = {"review": review.status, "review_note": review.note}
    if review.status is ReviewStatus.EDITED and review.statement:
        update |= {"statement": review.statement, "extracted_statement": item.statement}
    return item.model_copy(update=update)


def carry_reviews(old: list[PersonaItem], new: list[PersonaItem], reviews: dict[str, PReview]) -> dict[str, PReview]:
    """Reviews for a facet's re-merged items: a new item inherits the review of an old item whose candidates it all
    still contains (the same trait, possibly with more evidence). An old item none of whose candidates survive was
    re-extracted (a new prompt changes every candidate id): its review moves to the one new item that best matches it
    by quoted expressions and wording, if any is close enough. A new item covering several reviewed old ones takes a
    rejection first, then an edit, then a confirmation; anything else starts unreviewed."""
    rank = {ReviewStatus.REJECTED: 0, ReviewStatus.EDITED: 1, ReviewStatus.CONFIRMED: 2}
    by_candidate: dict[str, list[PersonaItem]] = {}
    by_expression: dict[str, list[PersonaItem]] = {}
    for item in new:
        for c in item.member_candidate_ids:
            by_candidate.setdefault(c, []).append(item)
        for e in {e.expression_id for e in item.evidence}:
            by_expression.setdefault(e, []).append(item)
    inherited: dict[str, list[PReview]] = {}
    for o in old:
        review = reviews.get(o.item_id)
        if review is None:
            continue
        members = set(o.member_candidate_ids)
        if members & by_candidate.keys():
            heirs = by_candidate.get(o.member_candidate_ids[0], [])
            for item in [i for i in heirs if members <= set(i.member_candidate_ids)]:
                inherited.setdefault(item.item_id, []).append(review)
        elif match := _re_extracted(o, review, by_expression):
            inherited.setdefault(match.item_id, []).append(review)
    return {i: min(found, key=lambda r: rank.get(r.status, 3)) for i, found in inherited.items()}


# How close a re-extracted item must be to a reviewed old one to take its review: shared quoted expressions
# (Jaccard) and wording similarity, weighted equally. Sharing no expression never matches.
_RE_EXTRACTED_MIN = 0.35


def _re_extracted(old: PersonaItem, review: PReview, by_expression: dict[str, list[PersonaItem]]) -> PersonaItem | None:
    """The new item that best continues ``old``, among those quoting at least one of its expressions."""
    quoted = {e.expression_id for e in old.evidence}
    # The old wordings are the fixed second sequence, which SequenceMatcher indexes once and reuses.
    matchers = [SequenceMatcher(None, b=w) for w in (old.statement, review.statement) if w]
    best: tuple[float, str] | None = None
    found: dict[str, PersonaItem] = {}
    for expression in quoted:
        for item in by_expression.get(expression, []):
            found[item.item_id] = item
    for item in found.values():
        theirs = {e.expression_id for e in item.evidence}
        overlap = len(quoted & theirs) / len(quoted | theirs)
        floor = max(_RE_EXTRACTED_MIN, best[0] if best else 0.0)
        wording = 0.0
        for matcher in matchers:
            matcher.set_seq1(item.statement)
            # quick_ratio bounds ratio from above: skip the exact comparison when even the bound cannot win.
            if (overlap + matcher.quick_ratio()) / 2 >= floor:
                wording = max(wording, matcher.ratio())
        score = (overlap + wording) / 2
        if score >= floor and (best is None or (score, item.item_id) > best):
            best = (score, item.item_id)
    return found[best[1]] if best else None


def item_as_of(item: PersonaItem, as_of: dt.date) -> PersonaItem | None:
    """The item as known on ``as_of``: evidence dated later (or undated) is dropped; None when nothing is left."""
    evidence = [e for e in item.evidence if e.date is not None and e.date <= as_of]
    if not evidence:
        return None
    return item.model_copy(update={"evidence": evidence})
