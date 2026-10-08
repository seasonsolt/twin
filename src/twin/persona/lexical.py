"""Personal-scale BM25 with Unicode words and overlapping CJK character bigrams."""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter

_CJK = (
    "\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\U00020000-\U0002ffff\U00030000-\U000323af"
    "\u3041-\u3096\u309d-\u309f\u30a1-\u30fa\u30fc-\u30ff\u31f0-\u31ff\U0001b000-\U0001b16f"
    "\u1100-\u11ff\u3131-\u318e\ua960-\ua97c\uac00-\ud7a3\ud7b0-\ud7fb"
)
_RUNS = re.compile(f"([{_CJK}]+)|([^\\W_{_CJK}]+)")


def tokenize(text: str) -> list[str]:
    """Normalize words and split CJK runs into bigrams, keeping isolated characters."""
    tokens: list[str] = []
    for match in _RUNS.finditer(unicodedata.normalize("NFKC", text).casefold()):
        cjk, word = match.groups()
        if cjk and len(cjk) > 1:
            tokens.extend(cjk[i : i + 2] for i in range(len(cjk) - 1))
        else:
            tokens.append(cjk or word)
    return tokens


class BM25:
    """Build an in-memory inverted index; score only documents with keyword hits."""

    def __init__(self, docs: dict[str, str], k1: float = 1.2, b: float = 0.75) -> None:
        self._k1 = k1
        self._postings: dict[str, dict[str, int]] = {}
        lengths: dict[str, int] = {}
        for ref, text in docs.items():
            counts = Counter(tokenize(text))
            lengths[ref] = counts.total()
            for term, frequency in counts.items():
                self._postings.setdefault(term, {})[ref] = frequency
        average = sum(lengths.values()) / len(docs) if docs else 0.0
        self._norms = {ref: k1 * (1 - b + b * length / average) for ref, length in lengths.items()} if average else {}
        self._idf = {
            term: math.log(1 + (len(docs) - len(postings) + 0.5) / (len(postings) + 0.5))
            for term, postings in self._postings.items()
        }

    def scores(self, query: str) -> dict[str, float]:
        scores: dict[str, float] = {}
        for term in dict.fromkeys(tokenize(query)):
            if term not in self._postings:
                continue
            for ref, frequency in self._postings[term].items():
                score = self._idf[term] * frequency * (self._k1 + 1) / (frequency + self._norms[ref])
                scores[ref] = scores.get(ref, 0.0) + score
        return {ref: score for ref, score in scores.items() if score > 0}
