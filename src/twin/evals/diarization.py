"""Session-level transcription and diarization metrics: whole-session CER, speech activity, DER, cpCER, speaker claims.

Pure functions over timed utterances, shared by `asr_session`. Text uses the eval-asr normalization (`score_tokens`,
`nofill` filler removal), so a session CER is comparable with clip CER on the same audio. Times are seconds.

Definitions follow the M2MeT challenge (arXiv 2110.07393): the session CER concatenates utterances in start-time order
(first-in first-out); DER counts missed, false-alarm and confused speaker time over the reference speaker time under
the best one-to-one speaker mapping, with a no-score collar around reference boundaries (0.25 s in the challenge);
cpCER concatenates each speaker's words and takes the speaker assignment with the fewest character errors.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from .asr import FILLERS, score_tokens

FRAME = 0.01  # seconds per frame for time-based metrics


@dataclass(frozen=True)
class Utterance:
    start: float
    end: float
    speaker: str
    text: str = ""


def tokens(text: str, mode: str = "strict") -> list[str]:
    found = score_tokens(text)
    return [t for t in found if t not in FILLERS] if mode == "nofill" else found


def _encode(ref: Sequence[str], hyp: Sequence[str]) -> tuple[np.ndarray, np.ndarray]:
    ids: dict[str, int] = {}
    a = np.fromiter((ids.setdefault(t, len(ids)) for t in ref), dtype=np.int32, count=len(ref))
    b = np.fromiter((ids.setdefault(t, len(ids)) for t in hyp), dtype=np.int32, count=len(hyp))
    return a, b


def _row(above: np.ndarray, cost: np.ndarray, first: int, offsets: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """One dynamic-programming row: diagonal and vertical candidates, then the horizontal (insertion) pass as a
    running minimum of ``candidate - j``. Returns the row and, per cell, 0 = diagonal, 1 = vertical, 2 = horizontal,
    preferring them in that order on ties (the same choice as `edit_counts`' backtrace)."""
    diagonal = above[:-1] + cost
    vertical = above[1:] + 1
    candidate = np.minimum(diagonal, vertical)
    joined = np.concatenate(([first], candidate))
    best = np.minimum.accumulate(joined - offsets) + offsets
    move = np.where(diagonal <= vertical, 0, 1).astype(np.uint8)
    move[best[1:] < candidate] = 2
    return best, move


def edit_distance(ref: Sequence[str], hyp: Sequence[str]) -> int:
    """Levenshtein distance in O(len(hyp)) memory, for scoring speaker assignments."""
    if not ref or not hyp:
        return max(len(ref), len(hyp))
    a, b = _encode(ref, hyp)
    offsets = np.arange(len(b) + 1, dtype=np.int64)
    row = offsets.copy()
    for i, token in enumerate(a, 1):
        row, _ = _row(row, (b != token).astype(np.int64), i, offsets)
    return int(row[-1])


def align_counts(ref: Sequence[str], hyp: Sequence[str]) -> tuple[int, int, int]:
    """(substitutions, deletions, insertions), identical to `asr.edit_counts` but vectorized per row, so a
    30-minute session (about 9000 characters a side) aligns in seconds; moves are kept as one byte per cell."""
    if not ref or not hyp:
        return 0, len(ref), len(hyp)
    a, b = _encode(ref, hyp)
    n, m = len(a), len(b)
    offsets = np.arange(m + 1, dtype=np.int64)
    moves = np.empty((n, m), dtype=np.uint8)
    row = offsets.copy()
    for i in range(n):
        row, moves[i] = _row(row, (b != a[i]).astype(np.int64), i + 1, offsets)
    sub = dele = ins = 0
    i, j = n, m
    while i and j:
        move = moves[i - 1, j - 1]
        if move == 0:
            sub += int(a[i - 1] != b[j - 1])
            i, j = i - 1, j - 1
        elif move == 1:
            dele += 1
            i -= 1
        else:
            ins += 1
            j -= 1
    return sub, dele + i, ins + j


def _joined(utterances: Sequence[Utterance], mode: str) -> list[str]:
    ordered = sorted(utterances, key=lambda u: (u.start, u.end))
    return [t for u in ordered for t in tokens(u.text, mode)]


def session_counts(reference: Sequence[Utterance], hypothesis: Sequence[Utterance], mode: str) -> dict[str, int]:
    """Speaker-agnostic whole-session alignment: both sides concatenated in start-time order."""
    ref, hyp = _joined(reference, mode), _joined(hypothesis, mode)
    sub, dele, ins = align_counts(ref, hyp)
    return {"substitution": sub, "deletion": dele, "insertion": ins, "reference_tokens": len(ref)}


def _assign(
    rows: Sequence[str], columns: Sequence[str], gain: Callable[[str, str], float]
) -> tuple[float, dict[str, str]]:
    """Best one-to-one partial assignment of columns to rows maximizing total gain; exact by dynamic programming
    over subsets of rows (meetings have at most a handful of reference speakers)."""
    if len(rows) > 16:
        raise ValueError("参考说话人过多")
    best: dict[int, tuple[float, dict[str, str]]] = {0: (0.0, {})}
    for column in columns:
        nxt = dict(best)
        for mask, (value, chosen) in best.items():
            for r, row in enumerate(rows):
                bit = 1 << r
                if mask & bit:
                    continue
                score = value + gain(row, column)
                if mask | bit not in nxt or score > nxt[mask | bit][0]:
                    nxt[mask | bit] = (score, {**chosen, column: row})
        best = nxt
    return max(best.values(), key=lambda entry: entry[0])


def _by_speaker(utterances: Sequence[Utterance], mode: str) -> dict[str, list[str]]:
    speakers = sorted({u.speaker for u in utterances})
    return {s: _joined([u for u in utterances if u.speaker == s], mode) for s in speakers}


def cp_counts(reference: Sequence[Utterance], hypothesis: Sequence[Utterance], mode: str) -> dict[str, Any]:
    """Concatenated minimum-permutation CER: each speaker's tokens joined in time order, hypothesis speakers matched
    one-to-one to reference speakers; an unmatched reference speaker is all deletions, an unmatched hypothesis
    speaker all insertions."""
    refs, hyps = _by_speaker(reference, mode), _by_speaker(hypothesis, mode)
    distance = {(r, h): edit_distance(refs[r], hyps[h]) for r in refs for h in hyps}
    # Pairing r with h saves len(r) + len(h) - distance errors against leaving both unmatched.
    saved, mapping = _assign(list(refs), list(hyps), lambda r, h: len(refs[r]) + len(hyps[h]) - distance[r, h])
    total = sum(len(t) for t in refs.values()) + sum(len(t) for t in hyps.values())
    return {
        "errors": round(total - saved),
        "reference_tokens": sum(len(t) for t in refs.values()),
        "mapping": mapping,
    }


def _frames(spans: Sequence[tuple[float, float]], count: int) -> np.ndarray:
    active = np.zeros(count, dtype=bool)
    for start, end in spans:
        active[max(0, round(start / FRAME)) : max(0, round(end / FRAME))] = True
    return active


def _activity(utterances: Sequence[Utterance], count: int) -> dict[str, np.ndarray]:
    speakers = sorted({u.speaker for u in utterances})
    return {s: _frames([(u.start, u.end) for u in utterances if u.speaker == s], count) for s in speakers}


def scored_frames(reference: Sequence[Utterance], count: int, collar: float) -> np.ndarray:
    """Frames that count: everything except ``collar`` seconds either side of each reference boundary."""
    keep = np.ones(count, dtype=bool)
    if collar > 0:
        width = round(collar / FRAME)
        for u in reference:
            for edge in (round(u.start / FRAME), round(u.end / FRAME)):
                keep[max(0, edge - width) : max(0, edge + width)] = False
    return keep


def _frame_count(reference: Sequence[Utterance], hypothesis: Sequence[Utterance]) -> int:
    return round(max((u.end for u in [*reference, *hypothesis]), default=0.0) / FRAME) + 1


def diarization_error(
    reference: Sequence[Utterance], hypothesis: Sequence[Utterance], collar: float = 0.25
) -> dict[str, Any]:
    """NIST-style DER with overlap: per frame, missed = max(|R| - |H|, 0), false alarm = max(|H| - |R|, 0),
    confusion = min(|R|, |H|) - matched, where matched counts hypothesis speakers mapped to an active reference
    speaker under the one-to-one mapping with the most shared time. Seconds are reported alongside the rate."""
    count = _frame_count(reference, hypothesis)
    keep = scored_frames(reference, count, collar)
    ref = {s: a & keep for s, a in _activity(reference, count).items()}
    hyp = {s: a & keep for s, a in _activity(hypothesis, count).items()}
    overlap = {(r, h): int((ref[r] & hyp[h]).sum()) for r in ref for h in hyp}
    _, mapping = _assign(list(ref), list(hyp), lambda r, h: float(overlap[r, h]))
    n_ref = np.sum(list(ref.values()), axis=0) if ref else np.zeros(count, dtype=np.int64)
    n_hyp = np.sum(list(hyp.values()), axis=0) if hyp else np.zeros(count, dtype=np.int64)
    matched = sum(overlap[r, h] for h, r in mapping.items())
    missed = int(np.maximum(n_ref - n_hyp, 0).sum())
    false_alarm = int(np.maximum(n_hyp - n_ref, 0).sum())
    confusion = int(np.minimum(n_ref, n_hyp).sum()) - matched
    total = int(n_ref.sum())
    return {
        "missed": missed * FRAME,
        "false_alarm": false_alarm * FRAME,
        "confusion": confusion * FRAME,
        "reference_speech": total * FRAME,
        "der": (missed + false_alarm + confusion) / total if total else 0.0,
        "mapping": mapping,
        "reference_speakers": len(ref),
        "hypothesis_speakers": len(hyp),
    }


def speech_activity(
    reference: Sequence[Utterance], hypothesis: Sequence[Utterance], collar: float = 0.25
) -> dict[str, float]:
    """Speaker-agnostic detection: reference speech the hypothesis misses, and hypothesis speech where nobody spoke,
    each in seconds and as a share of reference speech time."""
    count = _frame_count(reference, hypothesis)
    keep = scored_frames(reference, count, collar)
    ref = _frames([(u.start, u.end) for u in reference], count) & keep
    hyp = _frames([(u.start, u.end) for u in hypothesis], count) & keep
    speech = int(ref.sum())
    missed, false_alarm = int((ref & ~hyp).sum()), int((hyp & ~ref).sum())
    return {
        "reference_speech": speech * FRAME,
        "missed": missed * FRAME,
        "false_alarm": false_alarm * FRAME,
        "missed_rate": missed / speech if speech else 0.0,
        "false_alarm_rate": false_alarm / speech if speech else 0.0,
    }


def majority_speaker(reference: Sequence[Utterance], hypothesis: Sequence[Utterance], speaker: str) -> str | None:
    """The reference speaker who talks most during a hypothesis speaker's segments (None if nobody does)."""
    count = _frame_count(reference, hypothesis)
    mine = _frames([(u.start, u.end) for u in hypothesis if u.speaker == speaker], count)
    shared = {s: int((a & mine).sum()) for s, a in _activity(reference, count).items()}
    best = max(shared, key=lambda s: (shared[s], s), default=None)
    return best if best is not None and shared[best] > 0 else None


def spoken_by(reference: Sequence[Utterance], parts: Sequence[tuple[float, float]], target: str) -> tuple[float, float]:
    """Seconds inside ``parts`` where ``target`` speaks, and where only others do (silence is left out)."""
    count = _frame_count(reference, [])
    inside = _frames(parts, count)
    own = _frames([(u.start, u.end) for u in reference if u.speaker == target], count)
    others = _frames([(u.start, u.end) for u in reference if u.speaker != target], count) & ~own
    return float((inside & own).sum() * FRAME), float((inside & others).sum() * FRAME)


def claim_outcome(
    reference: Sequence[Utterance], hypothesis: Sequence[Utterance], claimed: Sequence[str], target: str
) -> str:
    """'none' when nothing was claimed, 'correct' when every claimed speaker is mostly the target, else 'wrong'."""
    if not claimed:
        return "none"
    owners = {majority_speaker(reference, hypothesis, speaker) for speaker in claimed}
    return "correct" if owners == {target} else "wrong"


def attributed_counts(
    reference: Sequence[Utterance], hypothesis: Sequence[Utterance], claimed: Sequence[str], target: str, mode: str
) -> dict[str, float]:
    """What the twin keeps as the target's words, scored against what the target said.

    ``errors``/``reference_tokens`` give the target-speaker CER: the target's reference utterances against the
    claimed hypothesis segments, both in time order. ``misattributed`` is the share of claimed tokens spoken while
    only other people talked: each claimed segment's tokens are split by its frames where the target speaks versus
    frames where only others do; frames with nobody speaking are left out of the split."""
    mine = [u for u in hypothesis if u.speaker in set(claimed)]
    ref_target = [u for u in reference if u.speaker == target]
    sub, dele, ins = align_counts(_joined(ref_target, mode), _joined(mine, mode))
    count = _frame_count(reference, hypothesis)
    target_frames = _frames([(u.start, u.end) for u in ref_target], count)
    others = _frames([(u.start, u.end) for u in reference if u.speaker != target], count) & ~target_frames
    claimed_tokens = other_tokens = 0.0
    for u in mine:
        n = len(tokens(u.text, mode))
        claimed_tokens += n
        lo, hi = max(0, round(u.start / FRAME)), max(0, round(u.end / FRAME))
        own, foreign = int(target_frames[lo:hi].sum()), int(others[lo:hi].sum())
        if own + foreign:
            other_tokens += n * foreign / (own + foreign)
    return {
        "errors": sub + dele + ins,
        "substitution": sub,
        "deletion": dele,
        "insertion": ins,
        "reference_tokens": len(_joined(ref_target, mode)),
        "claimed_tokens": claimed_tokens,
        "misattributed_tokens": other_tokens,
    }
