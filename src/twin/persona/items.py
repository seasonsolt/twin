"""Persona profile records: candidates extracted from one chunk of expressions, and the items they merge into."""

from __future__ import annotations

import datetime as dt

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
    still contains (the same trait, possibly with more evidence). A new item covering several reviewed old ones takes
    a rejection first, then an edit, then a confirmation; anything else starts unreviewed."""
    rank = {ReviewStatus.REJECTED: 0, ReviewStatus.EDITED: 1, ReviewStatus.CONFIRMED: 2}
    carried: dict[str, PReview] = {}
    for item in new:
        members = set(item.member_candidate_ids)
        inherited = [
            reviews[o.item_id]
            for o in old
            if o.item_id in reviews and o.member_candidate_ids and set(o.member_candidate_ids) <= members
        ]
        if inherited:
            carried[item.item_id] = min(inherited, key=lambda r: rank.get(r.status, 3))
    return carried


def item_as_of(item: PersonaItem, as_of: dt.date) -> PersonaItem | None:
    """The item as known on ``as_of``: evidence dated later (or undated) is dropped; None when nothing is left."""
    evidence = [e for e in item.evidence if e.date is not None and e.date <= as_of]
    if not evidence:
        return None
    return item.model_copy(update={"evidence": evidence})
