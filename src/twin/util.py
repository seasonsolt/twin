"""General-purpose helpers shared across layers."""

from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import json
import math
import os
import re
import unicodedata
from collections import Counter
from collections.abc import Callable, Sequence
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from contextvars import copy_context
from difflib import SequenceMatcher
from pathlib import Path
from typing import TextIO

Progress = Callable[[str], None]

# Spreadsheet apps evaluate a cell as a formula when its first non-blank character is one of these (full-width
# forms included because some IMEs/locales convert them).
FORMULA_TRIGGERS = frozenset("=+-@＝＋－＠")

_NON_WORD = re.compile(r"[\s\W_]+", re.UNICODE)

_DATE_PATTERNS = (
    re.compile(r"(?<!\d)(?P<y>\d{4})(?P<sep>[-_.])(?P<m>\d{1,2})(?P=sep)(?P<d>\d{1,2})(?!\d)"),
    re.compile(r"(?<!\d)(?P<y>(?:19|20)\d{2})(?P<m>\d{2})(?P<d>\d{2})(?:\d{4}|\d{6})?(?!\d)"),
    re.compile(r"(?<!\d)(?P<y>\d{4})\s*年\s*(?P<m>\d{1,2})\s*月\s*(?P<d>\d{1,2})(?!\d)"),
)

QUOTE_MIN_RATIO = 0.85
_SCAN_SLACK = 0.1
_MAX_REFINE = 8


class RenameError(ValueError):
    """An obsolete public name was found; safe to display without sanitizing credentials."""


def key_from_env(name: str) -> str | None:
    """Read credentials without accepting renamed variables or exposing their values."""
    renamed = {
        "DTWIN_LLM_KEY": "TWIN_LLM_KEY",
        "DTWIN_EMBED_KEY": "TWIN_EMBED_KEY",
        "DTWIN_TTS_KEY": "TWIN_TTS_KEY",
        "DTWIN_ASR_KEY": "TWIN_ASR_KEY",
    }
    if name in renamed:
        raise RenameError(f"环境变量 {name} 已改名为 {renamed[name]}，请更新配置和环境变量；旧名称不再支持")
    value = os.environ.get(name)
    for old, new in renamed.items():
        if name == new and not value and old in os.environ:
            raise RenameError(f"环境变量 {old} 已改名为 {new}，请设置 {new} 并移除 {old}；旧名称不再支持")
    return value


def fingerprint(value: object) -> str:
    """Hash a canonical JSON value, independent of dictionary key order."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha1("\x1f".join(parts).encode("utf-8")).hexdigest()[:12]
    return f"{prefix}_{digest}"


def normalize_for_match(text: str) -> str:
    """NFKC, lower-case, punctuation and whitespace removed. Used to compare quotes with source text."""
    return _NON_WORD.sub("", unicodedata.normalize("NFKC", text).lower())


def run_parallel[A, R](
    fn: Callable[[A], R],
    items: Sequence[A],
    max_workers: int,
    progress: Progress | None = None,
    label: Callable[[A], str] = str,
    on_result: Callable[[A, R | Exception], None] | None = None,
) -> list[R | Exception]:
    """Run ``fn`` over items in a thread pool. Results keep input order; an ``Exception`` raised by ``fn`` is
    returned in place of its result, not raised.

    ``on_result(item, outcome)`` runs in the calling thread as soon as each item finishes, so callers can persist
    paid-for results one by one. A ``BaseException`` that is not an ``Exception`` (``KeyboardInterrupt``), raised
    by ``fn`` or delivered while waiting, cancels the items not yet started, hands every item already finished to
    ``on_result`` and propagates; items still running finish in the background unreported. An exception raised by
    ``on_result`` cancels the items not yet started and propagates.
    """
    results: list[R | Exception] = [RuntimeError("not run")] * len(items)

    def call(i: int) -> R | Exception:
        try:
            result = fn(items[i])
        except Exception as e:
            if progress:
                progress(f"FAILED {label(items[i])}: {type(e).__name__}: {e}")
            return e
        if progress:
            progress(f"ok {label(items[i])}")
        return result

    pool = ThreadPoolExecutor(max_workers=max(1, max_workers))
    futures: dict[Future[R | Exception], int] = {}
    reported: set[int] = set()

    def report(future: Future[R | Exception]) -> None:
        i = futures[future]
        results[i] = future.result()
        if on_result is not None:
            on_result(items[i], results[i])
        reported.add(i)

    try:
        futures.update((pool.submit(copy_context().run, call, i), i) for i in range(len(items)))
        for future in as_completed(futures):
            report(future)
    except Exception:
        pool.shutdown(wait=False, cancel_futures=True)
        raise
    except BaseException:
        pool.shutdown(wait=False, cancel_futures=True)
        for future, i in futures.items():
            if i not in reported and future.done() and not future.cancelled() and future.exception() is None:
                report(future)
        raise
    pool.shutdown(wait=True)
    return results


def escape_csv_cell(value: str) -> str:
    """Spreadsheet-safe cell: a value a spreadsheet would evaluate as a formula gets a leading single quote."""
    return "'" + value if value.lstrip()[:1] in FORMULA_TRIGGERS else value


def private_directory(path: Path) -> None:
    """Create each missing output-directory component with owner-only permissions."""
    missing: list[Path] = []
    current = path
    while not current.exists():
        missing.append(current)
        current = current.parent
    for directory in reversed(missing):
        directory.mkdir(mode=0o700, exist_ok=True)


def open_private(path: Path, encoding: str = "utf-8", newline: str | None = None) -> TextIO:
    """Open ``path`` for writing as an owner-only (0600) file. Outputs quote personal memories, so they must not
    be readable by other local users whatever the umask; an existing file is truncated and tightened too."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.chmod(path, 0o600)
        return os.fdopen(fd, "w", encoding=encoding, newline=newline)
    except BaseException:
        os.close(fd)
        raise


def prepare_private_file(path: Path) -> None:
    """Personal memories live here: create the database (and a new parent directory) owner-only, and tighten an
    existing database and its WAL files. SQLite gives -wal/-shm the database file's mode when it creates them, so a
    side file another connection deletes between the check and the chmod comes back owner-only and is skipped."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with contextlib.suppress(FileExistsError):
        os.close(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
    for p in (path, path.with_name(path.name + "-wal"), path.with_name(path.name + "-shm")):
        if p.is_file():
            vanished = (FileNotFoundError,) if p != path else ()
            with contextlib.suppress(PermissionError, *vanished):
                p.chmod(0o600)


def date_from_name(name: str) -> dt.date | None:
    best: tuple[int, dt.date] | None = None
    for pattern in _DATE_PATTERNS:
        for m in pattern.finditer(name):
            try:
                found = dt.date(int(m["y"]), int(m["m"]), int(m["d"]))
            except ValueError:
                continue
            if best is None or m.start() < best[0]:
                best = (m.start(), found)
            break
    return best[1] if best is not None else None


def _normalized_with_map(text: str) -> tuple[str, list[int]]:
    """``normalize_for_match`` applied per character, plus the source index of every normalised character."""
    chars: list[str] = []
    positions: list[int] = []
    for i, ch in enumerate(text):
        norm = normalize_for_match(ch)
        if norm:
            chars.append(norm)
            positions.extend([i] * len(norm))
    return "".join(chars), positions


def _best_window(needle: str, hay: str, min_ratio: float) -> tuple[int, int] | None:
    m, n = len(needle), len(hay)
    width = min(m, n)
    need = Counter(needle)
    have: Counter[str] = Counter()
    overlap = 0
    matcher = SequenceMatcher(autojunk=False)
    matcher.set_seq2(needle)
    floor = min_ratio - _SCAN_SLACK
    best_ratio, best_start = -1.0, -1
    for end in range(n):
        ch = hay[end]
        if have[ch] < need[ch]:
            overlap += 1
        have[ch] += 1
        start = end - width + 1
        if start < 0:
            continue
        if start > 0:
            out = hay[start - 1]
            have[out] -= 1
            if have[out] < need[out]:
                overlap -= 1
        bound = 2.0 * overlap / (m + width)
        if bound < floor or bound <= best_ratio:
            continue
        matcher.set_seq1(hay[start : end + 1])
        ratio = matcher.ratio()
        if ratio > best_ratio:
            best_ratio, best_start = ratio, start
    if best_start < 0:
        return None

    # A span of length L shares at most min(L, m) characters with the needle, so its ratio is at most
    # 2 * min(L, m) / (L + m): only spans in [shortest, longest] can reach min_ratio. The source span of a quote
    # whose speaker's fillers were left out is longer than the quote, so its ends can lie well beyond ``delta``.
    reach = min(max(min_ratio, 1e-6), 1.0)
    longest = min(n, math.floor(m * (2 / reach - 1)))
    shortest = max(1, math.ceil(m * reach / (2 - reach)))
    delta = min(_MAX_REFINE, max(2, m // 5))
    grow = max(delta, longest - width)
    shrink = max(delta, width - shortest)
    lo, hi = best_start, best_start + width
    best_key = (best_ratio, -width)
    for a in range(max(0, best_start - grow), min(n - 1, best_start + shrink) + 1):
        for b in range(a + shortest, min(n, a + longest) + 1):
            matcher.set_seq1(hay[a:b])
            bar = max(best_key[0], min_ratio)
            if matcher.real_quick_ratio() < bar or matcher.quick_ratio() < bar:
                continue
            key = (matcher.ratio(), a - b)
            if key > best_key:
                best_key, lo, hi = key, a, b
    return (lo, hi) if best_key[0] >= min_ratio else None


def _locate(needle: str, hay: str, min_ratio: float) -> tuple[int, int] | None:
    found = hay.find(needle)
    if found >= 0:
        return found, found + len(needle)
    return _best_window(needle, hay, min_ratio)


def verify_quote(quote: str, source: str, min_ratio: float = QUOTE_MIN_RATIO) -> str | None:
    """Locate ``quote`` in ``source`` ignoring case, width, whitespace and punctuation; tolerate small edits.

    Returns the verbatim ``source`` span that matches (from its first to its last matching character),
    or None when no span reaches ``min_ratio`` (``difflib`` ratio on the normalised forms).
    """
    needle, _ = _normalized_with_map(quote)
    hay, positions = _normalized_with_map(source)
    if not needle or not hay:
        return None
    window = _locate(needle, hay, min_ratio)
    if window is None:
        return None
    start, end = window
    return source[positions[start] : positions[end - 1] + 1]
