"""Personal-scale BM25 with Unicode words and overlapping CJK character bigrams."""

from __future__ import annotations

import math
import re
import threading
import unicodedata
from collections import Counter, OrderedDict
from collections.abc import Hashable, Mapping
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

_CJK = (
    "㐀-䶿一-鿿豈-﫿\U00020000-\U0002ffff\U00030000-\U000323af"
    "ぁ-ゖゝ-ゟァ-ヺー-ヿㇰ-ㇿ\U0001b000-\U0001b16f"
    "ᄀ-ᇿㄱ-ㆎꥠ-ꥼ가-힣ힰ-ퟻ"
)
_RUNS = re.compile(f"([{_CJK}]+)|([^\\W_{_CJK}]+)")

# What the indexes kept by ``cached`` may take together, roughly; ``[ops] keyword_index_mb`` sets it for the web
# service. A person with a hundred thousand expressions takes some 70 MB.
KEPT_BYTES = 192 * 2**20
# A kept index takes changed documents in a small index of their own until they are this share of the documents it
# was built from; then it is built again from all of them.
COMPACT_SHARE = 0.2
# Rough bytes of Python objects per document and per term, besides the arrays (refs, lookups, fingerprints).
_DOC_BYTES = 240
_TERM_BYTES = 120

_NO_DOCS = np.zeros(0, dtype=np.int32)
_NO_FREQUENCIES = np.zeros(0, dtype=np.uint16)


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


class _Postings:
    """Each term's documents and how often it occurs in each, as slices of two arrays sorted by term, and each
    document's length in tokens."""

    def __init__(self, docs: Mapping[str, str]) -> None:
        self.refs = list(docs)
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
        self.terms = terms
        by_term = np.asarray(term_of, dtype=np.int64)
        order = np.argsort(by_term, kind="stable")
        self.docs: NDArray[np.int32] = np.asarray(doc_of, dtype=np.int32)[order]
        # Two bytes a count, unless a term occurs more often than that holds in some document.
        frequencies: NDArray[np.unsignedinteger] = (
            np.asarray(frequency_of, dtype=np.uint32)
            if max(frequency_of, default=0) > np.iinfo(np.uint16).max
            else np.asarray(frequency_of, dtype=np.uint16)
        )
        self.frequencies = frequencies[order]
        self.starts = np.concatenate(([0], np.cumsum(np.bincount(by_term, minlength=len(terms))))).astype(np.int64)
        self.lengths = np.asarray(lengths, dtype=np.int64)
        self.length_total = sum(lengths)
        self._numbers: dict[str, int] | None = None

    def postings(self, term: str) -> tuple[NDArray[np.int32], NDArray[np.unsignedinteger]]:
        t = self.terms.get(term)
        if t is None:
            return _NO_DOCS, _NO_FREQUENCIES
        start, end = int(self.starts[t]), int(self.starts[t + 1])
        return self.docs[start:end], self.frequencies[start:end]

    def number(self, ref: str) -> int | None:
        if self._numbers is None:
            self._numbers = {ref: n for n, ref in enumerate(self.refs)}
        return self._numbers.get(ref)

    @property
    def nbytes(self) -> int:
        arrays = self.docs.nbytes + self.frequencies.nbytes + self.starts.nbytes + self.lengths.nbytes
        return arrays + _DOC_BYTES * len(self.refs) + _TERM_BYTES * len(self.terms)


class BM25:
    """Build an in-memory inverted index; score only documents with keyword hits.

    The postings are kept as arrays, compact enough for ``cached`` to keep between questions. A kept index takes
    changes (``changed``) without being built again: the documents it was built from that are gone or changed are
    left out, and the new and changed ones are in a small index of their own. Scores count both as one corpus, the
    same as an index built afresh from the documents as they are now."""

    def __init__(self, docs: Mapping[str, str], k1: float = 1.2, b: float = 0.75) -> None:
        self._k1, self._b = k1, b
        self._base = _Postings(docs)
        # Documents of ``_base`` that are gone or changed since it was built; None while there are none.
        self._dead: NDArray[np.bool_] | None = None
        # The documents added or changed since, and their own index.
        self._added_docs: dict[str, str] = {}
        self._added = _Postings({})
        self._count = len(self._base.refs)
        self._length_total = self._base.length_total

    @property
    def nbytes(self) -> int:
        dead = self._dead.nbytes if self._dead is not None else 0
        return self._base.nbytes + self._added.nbytes + dead

    def changed(self, docs: Mapping[str, str], removed: list[str], added: Mapping[str, str]) -> BM25:
        """The index of ``docs``, which are this index's documents without ``removed`` and with ``added`` (a changed
        document is in both). It shares this index's postings unless the changes since it was built have grown past
        ``COMPACT_SHARE`` of them; then it is built again from ``docs``."""
        base = self._base
        dead = np.zeros(len(base.refs), dtype=np.bool_) if self._dead is None else self._dead.copy()
        added_docs = dict(self._added_docs)
        for ref in removed:
            if added_docs.pop(ref, None) is None and (number := base.number(ref)) is not None:
                dead[number] = True
        added_docs.update(added)
        dead_count = int(np.count_nonzero(dead))
        if dead_count + len(added_docs) > COMPACT_SHARE * len(base.refs):
            return BM25(docs, self._k1, self._b)
        index = object.__new__(BM25)
        index._k1, index._b, index._base = self._k1, self._b, base
        index._dead = dead if dead_count else None
        index._added_docs = added_docs
        index._added = _Postings(added_docs)
        index._count = len(base.refs) - dead_count + len(added_docs)
        index._length_total = base.length_total - int(base.lengths[dead].sum()) + index._added.length_total
        return index

    def scores(self, query: str) -> dict[str, float]:
        if not self._count or not self._length_total:
            return {}
        k1, b = self._k1, self._b
        base, added, dead = self._base, self._added, self._dead
        average = self._length_total / self._count
        docs: list[NDArray[np.int64]] = []
        weights: list[NDArray[np.float64]] = []
        for term in dict.fromkeys(tokenize(query)):
            base_docs, base_frequencies = base.postings(term)
            if dead is not None and len(base_docs):
                live = ~dead[base_docs]
                base_docs, base_frequencies = base_docs[live], base_frequencies[live]
            added_docs, added_frequencies = added.postings(term)
            n = len(base_docs) + len(added_docs)
            if not n:
                continue
            idf = math.log(1 + (self._count - n + 0.5) / (n + 0.5))
            frequency = np.concatenate((base_frequencies, added_frequencies)).astype(np.float64)
            lengths = np.concatenate((base.lengths[base_docs], added.lengths[added_docs]))
            norm = k1 * (1 - b + b * lengths / average)
            weights.append(idf * frequency * (k1 + 1) / (frequency + norm))
            docs.append(np.concatenate((base_docs, added_docs.astype(np.int64) + len(base.refs))))
        if not docs:
            return {}
        # bincount adds each document's weights in query-term order, as summing term by term would.
        totals = np.bincount(np.concatenate(docs), np.concatenate(weights), minlength=len(base.refs) + len(added.refs))
        base_refs, added_refs, offset = base.refs, added.refs, len(base.refs)
        return {
            (base_refs[n] if n < offset else added_refs[n - offset]): float(totals[n])
            for n in np.flatnonzero(totals > 0).tolist()
        }


@dataclass
class _Kept:
    # None until the first build for the family finishes.
    index: BM25 | None
    # Each document's ``hash`` of its text, to tell which documents changed since.
    fingerprints: dict[str, int]
    lock: threading.Lock


_kept: OrderedDict[Hashable, _Kept] = OrderedDict()
_kept_lock = threading.Lock()


def keep_up_to(megabytes: int) -> None:
    """Let the indexes ``cached`` keeps take about ``megabytes`` together; the latest one is kept whatever its size."""
    global KEPT_BYTES
    KEPT_BYTES = megabytes * 2**20


def cached(docs: Mapping[str, str], family: Hashable, k1: float = 1.2, b: float = 0.75) -> BM25:
    """``BM25(docs)``, kept between calls for ``family`` (one twin's namespace in one view, from any store connection):
    the same documents again return the index already built, and changed ones update it (``BM25.changed``) instead of
    building it again. The least recently used families are dropped beyond ``KEPT_BYTES``."""
    fingerprints = {ref: hash(text) for ref, text in docs.items()}
    key = (family, k1, b)
    with _kept_lock:
        kept = _kept.get(key)
        if kept is None:
            kept = _kept[key] = _Kept(None, {}, threading.Lock())
        _kept.move_to_end(key)
    # One build or update at a time for a family: a second question about the same twin waits for it.
    with kept.lock:
        if kept.index is not None and kept.fingerprints == fingerprints:
            return kept.index
        if kept.index is None:
            index = BM25(docs, k1, b)
        else:
            old = kept.fingerprints
            removed = [ref for ref, fingerprint in old.items() if fingerprints.get(ref) != fingerprint]
            added = {ref: text for ref, text in docs.items() if old.get(ref) != fingerprints[ref]}
            index = kept.index.changed(docs, removed, added)
        kept.index, kept.fingerprints = index, fingerprints
    with _kept_lock:
        while len(_kept) > 1 and sum(k.index.nbytes for k in _kept.values() if k.index is not None) > KEPT_BYTES:
            _kept.popitem(last=False)
    return index
