"""Answer style: how often the person picks the strongest end of a graded answer.

Inferred answers drift to the moderate option, while people differ widely and consistently in how often they answer
"strongly" (on Twin-2K-500, the share in waves 1-3 correlates 0.57 with wave 4). Counting it from the person's own
questionnaire answers lets an inferred answer match their habit instead of the model's.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

MIN_GRADED = 20

STRONG = re.compile(
    r"\b(?:strongly|extremely|completely|totally|definitely|always|never|very much)\b"
    r"|非常|完全|极其|特别|总是|从不|从来不|一定|绝对|强烈",
    re.IGNORECASE,
)
MILD = re.compile(
    r"\b(?:a little|a bit|somewhat|slightly|moderately|fairly|sometimes|probably|neither)\b"
    r"|有点|有些|比较|稍微|一般|有时|可能|中立|说不清",
    re.IGNORECASE,
)


def extreme_rate(answers: Iterable[str]) -> float | None:
    """Share of graded answers at the strongest end, or ``None`` with fewer than ``MIN_GRADED`` graded answers.

    A matrix answer lists several graded parts, one per line or separated by semicolons; each counts once.
    """
    strong = mild = 0
    for answer in answers:
        for part in re.split(r"[;；\n]", answer):
            if STRONG.search(part):
                strong += 1
            elif MILD.search(part):
                mild += 1
    total = strong + mild
    return strong / total if total >= MIN_GRADED else None
