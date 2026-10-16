"""Ephemeral, query-focused excerpts from chat attachments."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from .lexical import tokenize

MAX_CHAT_ATTACHMENT_COUNT = 5
MAX_CHAT_ATTACHMENT_BYTES = 50 * 1024 * 1024
MAX_CHAT_EXTRACTED_CHARS = 2_000_000
MAX_ATTACHMENT_PASSAGES = 8
MAX_ATTACHMENT_CONTEXT_CHARS = 12_000
PASSAGE_CHARS = 1_200


@dataclass(frozen=True)
class AttachmentPassage:
    citation_id: str
    file_name: str
    locator: str
    text: str


def _passages(file_index: int, file_name: str, text: str) -> list[AttachmentPassage]:
    passages: list[AttachmentPassage] = []
    for paragraph in re.split(r"\n\s*\n", text.replace("\r\n", "\n")):
        paragraph = " ".join(paragraph.split())
        if not paragraph:
            continue
        for start in range(0, len(paragraph), PASSAGE_CHARS):
            excerpt = paragraph[start : start + PASSAGE_CHARS].strip()
            if not excerpt:
                continue
            index = len(passages) + 1
            passages.append(
                AttachmentPassage(
                    citation_id=f"file_{file_index + 1}_p{index:04d}",
                    file_name=file_name,
                    locator=f"摘录 {index}",
                    text=excerpt,
                )
            )
    return passages


def select_attachment_passages(documents: Sequence[tuple[str, str]], query: str) -> list[AttachmentPassage]:
    """Pick a bounded set of passages, ensuring every attached file has at least one citation candidate."""
    total_chars = sum(len(text) for _, text in documents)
    if total_chars > MAX_CHAT_EXTRACTED_CHARS:
        raise ValueError(f"文件提取出的文字超过 {MAX_CHAT_EXTRACTED_CHARS // 10_000} 万字，请拆分后上传")

    grouped = [_passages(file_index, name, text) for file_index, (name, text) in enumerate(documents)]
    if any(not passages for passages in grouped):
        raise ValueError("有文件没有可提取的文字")

    query_terms = set(tokenize(query))
    scored: list[tuple[int, int, AttachmentPassage]] = []
    for order, passage in enumerate(passage for group in grouped for passage in group):
        terms = set(tokenize(passage.text))
        scored.append((len(query_terms & terms), order, passage))

    if not any(score for score, _, _ in scored):
        samples: list[AttachmentPassage] = []
        selected_positions: dict[str, set[int]] = {}
        passage_positions = {
            p.citation_id: (p.citation_id.rsplit("_p", 1)[0], i) for group in grouped for i, p in enumerate(group)
        }
        for group in grouped:
            first = group[0]
            samples.append(first)
            selected_positions[first.citation_id.rsplit("_p", 1)[0]] = {0}
        while len(samples) < min(MAX_ATTACHMENT_PASSAGES, len(scored)):
            best_entry: tuple[int, int, AttachmentPassage] | None = None
            best_gap = -1
            for order, (_, _, passage) in enumerate(scored):
                if passage in samples:
                    continue
                file_key, position = passage_positions[passage.citation_id]
                chosen = selected_positions.get(file_key, set())
                gap = min((abs(position - previous) for previous in chosen), default=position + 1)
                if gap > best_gap:
                    best_entry = (0, order, passage)
                    best_gap = gap
            if best_entry is None:
                break
            passage = best_entry[2]
            samples.append(passage)
            file_key, position = passage_positions[passage.citation_id]
            selected_positions.setdefault(file_key, set()).add(position)
        return samples

    # Reserve one passage per file; if the question has no matching terms, use each file's opening excerpt.
    selected: list[AttachmentPassage] = []
    selected_ids: set[str] = set()
    for group in grouped:
        candidates = [(score, order, passage) for score, order, passage in scored if passage in group]
        _, _, best = max(candidates, key=lambda row: (row[0], -row[1]))
        selected.append(best)
        selected_ids.add(best.citation_id)

    ranked = sorted(scored, key=lambda row: (-row[0], row[1]))
    for _, _, passage in ranked:
        if len(selected) >= MAX_ATTACHMENT_PASSAGES:
            break
        if passage.citation_id in selected_ids:
            continue
        if sum(len(item.text) for item in selected) + len(passage.text) > MAX_ATTACHMENT_CONTEXT_CHARS:
            continue
        selected.append(passage)
        selected_ids.add(passage.citation_id)
    return selected
