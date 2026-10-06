"""Shared verbatim-quote extraction and deterministic reply guard."""

from __future__ import annotations

import unicodedata
from collections.abc import Sequence


def normalize_quote(text: str) -> str:
    """NFKC, no whitespace/punctuation, and case-insensitive Latin letters."""
    return "".join(
        char.lower() if "LATIN" in unicodedata.name(char, "") else char
        for char in unicodedata.normalize("NFKC", text)
        if not char.isspace() and not unicodedata.category(char).startswith("P")
    )


def _quote_spans(text: str) -> list[tuple[int, int]]:
    pairs = {"「": "」", "『": "』", "“": "”", '"': '"'}
    stack: list[tuple[str, int]] = []
    spans: list[tuple[int, int]] = []
    backslashes = 0
    for index, char in enumerate(text):
        escaped = char == '"' and backslashes % 2 == 1
        backslashes = backslashes + 1 if char == "\\" else 0
        if escaped:
            continue
        if stack and char == pairs[stack[-1][0]]:
            _, start = stack.pop()
            spans.append((start + 1, index))
        elif char in pairs:
            stack.append((char, index))
    return [(start, end) for start, end in sorted(spans) if len(normalize_quote(text[start:end])) >= 4]


def extract_quotes(text: str) -> list[str]:
    """Return balanced spans in source order, including nested spans and repeated occurrences.

    Mismatched closers and unfinished pairs are ignored; balanced inner pairs still count.
    Backslash-escaped ASCII quotes are not delimiters. Terms under four normalized characters
    are ignored. Returned text is transient only, never prediction metadata.
    """
    return [text[start:end] for start, end in _quote_spans(text)]


def remove_unverified_quotes(text: str, materials: Sequence[str]) -> tuple[str, int]:
    """Remove only delimiters of unsupported spans, checking all pairs against the original text."""
    normalized = [normalize_quote(material) for material in materials]
    removed: set[int] = set()
    count = 0
    for start, end in _quote_spans(text):
        span = normalize_quote(text[start:end])
        if not any(span in material for material in normalized):
            removed.update((start - 1, end))
            count += 1
    return "".join(char for index, char in enumerate(text) if index not in removed), count
