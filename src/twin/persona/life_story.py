"""生命叙事: the turning points, the stories the person tells and what their life has meant to them, laid out year by
year (docs/PRODUCT_PERSONA_AGENT.md P1.6). Read only, and nothing is guessed: a memory has a year only when its own
words write one ("2008年"), or else when the words it rests on were dated as they happened (a diary, a chat, a
document; not an answer looking back). Years with nothing are kept as gaps, never filled; memories without a year are
listed apart."""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import Literal

from .dimensions import FACETS
from .items import PersonaItem
from .schema import EvidenceClass

STORY_FACETS: tuple[str, ...] = ("1.2", "1.3", "10.1", "10.2", "10.3", "10.4")
EARLIEST_YEAR = 1900
# A year as it is written in Chinese: "2008年", "1998 年"; not a number that happens to have four digits.
_YEAR = re.compile(r"(?<!\d)((?:19|20)\d{2})(?=\s*年)")
_FACET_ORDER = {f.facet_id: n for n, f in enumerate(FACETS)}

# "written": the year is in its words; "dated": the year its earliest words were dated, as they happened.
Basis = Literal["written", "dated"]


@dataclass(frozen=True)
class Placed:
    item: PersonaItem
    year: int | None
    basis: Basis | None


@dataclass(frozen=True)
class Span:
    """A year of the story, or a run of years with nothing (``until`` its last year, ``items`` empty)."""

    year: int
    until: int
    items: list[Placed]


def written_year(text: str, today: dt.date) -> int | None:
    """The earliest year the text writes, if any is a year that could have been lived."""
    years = [int(y) for y in _YEAR.findall(text) if EARLIEST_YEAR <= int(y) <= today.year]
    return min(years, default=None)


def place(item: PersonaItem, today: dt.date) -> Placed:
    for text in (item.statement, *(e.quote for e in item.evidence)):
        if (year := written_year(text, today)) is not None:
            return Placed(item, year, "written")
    dated = [e.date for e in item.evidence if e.date and e.evidence_class is EvidenceClass.BEHAVIOR]
    if dated:
        return Placed(item, min(dated).year, "dated")
    return Placed(item, None, None)


def story(items: list[PersonaItem], today: dt.date) -> tuple[list[Span], list[Placed]]:
    """The years from the first one with a memory up to this one, a run of empty years as one gap, oldest first;
    and the memories of the story without a year."""
    placed = [place(i, today) for i in items if i.facet_id in STORY_FACETS and i.statement.strip()]
    placed.sort(key=lambda p: (_FACET_ORDER[p.item.facet_id], p.item.statement))
    by_year: dict[int, list[Placed]] = {}
    for p in placed:
        if p.year is not None:
            by_year.setdefault(p.year, []).append(p)
    spans: list[Span] = []
    if by_year:
        year, last = min(by_year), max(today.year, *by_year)
        while year <= last:
            if year in by_year:
                spans.append(Span(year, year, by_year[year]))
                year += 1
                continue
            until = year
            while until + 1 <= last and until + 1 not in by_year:
                until += 1
            spans.append(Span(year, until, []))
            year = until + 1
    return spans, [p for p in placed if p.year is None]


def known_since(items: list[PersonaItem]) -> int | None:
    """The first year the twin knows anything of the person as of (时间切片, P2.1): the earliest dated evidence of any
    memory. A conversation looking back to an earlier year has nothing to answer from (``item_as_of``); None when no
    evidence is dated."""
    return min((e.date.year for i in items for e in i.evidence if e.date is not None), default=None)
