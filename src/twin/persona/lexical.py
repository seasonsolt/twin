"""Personal-scale BM25 with Unicode words and overlapping CJK character bigrams."""

from __future__ import annotations

import hashlib
import math
import re
import threading
import unicodedata
from collections import Counter, OrderedDict
from collections.abc import Mapping

import numpy as np

_CJK = (
    "㐀-䶿一-鿿豈-﫿\U00020000-\U0002ffff\U00030000-\U000323af"
    "ぁ-ゖゝ-ゟァ-ヺー-ヿㇰ-ㇿ\U0001b000-\U0001b16f"
    "ᄀ-ᇿㄱ-ㆎꥠ-ꥼ가-힣ힰ-ퟻ"
)
_RUNS = re.compile(f"([{_CJK}]+)|([^\\W_{_CJK}]+)")

# Postings the indexes kept by ``cached`` may hold together, about 12 bytes each: a person with a hundred thousand
# expressions has some four million.
CACHED_POSTINGS = 16_000_000


def _singular(word: str) -> str:
    """Fold a regular English plural onto its singular ("trips" finds "trip"); short and -ss/-us/-is words stay."""
    if len(word) <= 3 or not word.isascii() or not word.endswith("s") or word.endswith(("ss", "us", "is")):
        return word
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith(("ches", "shes", "xes", "sses")):
        return word[:-2]
    return word[:-1]


def tokenize(text: str) -> list[str]:
    """Normalize words and split CJK runs into bigrams, keeping isolated characters."""
    tokens: list[str] = []
    for match in _RUNS.finditer(unicodedata.normalize("NFKC", text).casefold()):
        cjk, word = match.groups()
        if cjk and len(cjk) > 1:
            tokens.extend(cjk[i : i + 2] for i in range(len(cjk) - 1))
        else:
            tokens.append(cjk or _singular(word))
    return tokens


class BM25:
    """Build an in-memory inverted index; score only documents with keyword hits.

    Each term's postings are kept as arrays of document numbers and their precomputed term weights, so an index of a
    large corpus stays compact enough for ``cached`` to keep between questions."""

    def __init__(self, docs: Mapping[str, str], k1: float = 1.2, b: float = 0.75) -> None:
        self._refs = list(docs)
        terms: dict[str, int] = {}
        doc_of: list[int] = []
        term_of: list[int] = []
        frequency_of: list[int] = []
        lengths: list[int] = []
        for number, text in enumerate(docs.values()):
            counts = Counter(tokenize(text))
            lengths.append(counts.total())
            doc_of.extend([number] * len(counts))
            term_of.extend(terms.setdefault(term, len(terms)) for term in counts)
            frequency_of.extend(counts.values())
        self._terms = terms
        average = sum(lengths) / len(docs) if docs else 0.0
        order = np.argsort(np.asarray(term_of, dtype=np.int64), kind="stable")
        self._docs = np.asarray(doc_of, dtype=np.int32)[order]
        frequencies = np.asarray(frequency_of, dtype=np.float64)[order]
        document_frequency = np.bincount(np.asarray(term_of, dtype=np.int64), minlength=len(terms))
        self._starts = np.concatenate(([0], np.cumsum(document_frequency))).astype(np.int64)
        idf = np.array(
            [math.log(1 + (len(docs) - n + 0.5) / (n + 0.5)) for n in document_frequency.tolist()], dtype=np.float64
        )
        norms = k1 * (1 - b + b * np.asarray(lengths, dtype=np.float64) / average) if average else np.zeros(0)
        posting_terms = np.repeat(np.arange(len(terms)), document_frequency)
        self._weights = (
            idf[posting_terms] * frequencies * (k1 + 1) / (frequencies + norms[self._docs])
            if len(self._docs)
            else np.zeros(0)
        )

    @property
    def postings(self) -> int:
        return len(self._docs)

    def scores(self, query: str) -> dict[str, float]:
        spans = [
            (int(self._starts[t]), int(self._starts[t + 1]))
            for term in dict.fromkeys(tokenize(query))
            if (t := self._terms.get(term)) is not None
        ]
        if not spans:
            return {}
        docs = np.concatenate([self._docs[start:end] for start, end in spans])
        weights = np.concatenate([self._weights[start:end] for start, end in spans])
        # bincount adds each document's weights in query-term order, as summing term by term would.
        totals = np.bincount(docs, weights, minlength=len(self._refs))
        refs = self._refs
        return {refs[n]: float(totals[n]) for n in np.flatnonzero(totals > 0).tolist()}


_cache: OrderedDict[bytes, BM25] = OrderedDict()
_building: dict[bytes, threading.Lock] = {}
_cache_lock = threading.Lock()


def cached(docs: Mapping[str, str], k1: float = 1.2, b: float = 0.75) -> BM25:
    """``BM25(docs)``, kept by content: asking again with the same documents (the same twin's memory, from any store
    connection) returns the index already built, and any change to a document builds a new one. The least recently
    used indexes are dropped beyond ``CACHED_POSTINGS``."""
    digest = hashlib.blake2b(f"{k1}\x1d{b}".encode(), digest_size=20)
    digest.update("\x1d".join(f"{ref}\x1e{text}" for ref, text in docs.items()).encode())
    key = digest.digest()
    with _cache_lock:
        if (index := _cache.get(key)) is not None:
            _cache.move_to_end(key)
            return index
        building = _building.setdefault(key, threading.Lock())
    # One build per corpus: a second question about the same twin waits for it instead of building it again.
    with building:
        with _cache_lock:
            if (index := _cache.get(key)) is not None:
                return index
        try:
            index = BM25(docs, k1, b)
            with _cache_lock:
                _cache[key] = index
                while len(_cache) > 1 and sum(i.postings for i in _cache.values()) > CACHED_POSTINGS:
                    _cache.popitem(last=False)
        finally:
            with _cache_lock:
                _building.pop(key, None)
    return index
