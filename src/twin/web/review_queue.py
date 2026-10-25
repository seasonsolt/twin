"""The recording review queue, reused until the library changes.

The observer connection never writes or holds a transaction. SQLite's ``data_version`` on that same connection
notices commits from request threads, background jobs and other processes, including changes to voice samples
that affect recordings elsewhere. A viewer's editable recording set is part of the key; permissions are still
checked on every request. Concurrent readers share one calculation, without holding the library's write lock.

A reading is kept with the version it was made at, also after the library changes: ``peek`` answers with it at
once and works out the current one in the background, since a reading of a large library takes many seconds and
background jobs commit often. A reading of a database that was replaced is never answered with.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from collections import OrderedDict
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from ..media.library import Library
from ..media.review import Reviews
from ..media.team import Team

logger = logging.getLogger(__name__)

# The lists a page of the queue holds the first so many of: voices by when they are asked (``Team.voices`` sorts
# them so), speakers someone said are not them, recordings settled one by one, and suspect confirmed speakers.
# Fragments are one task, settled all at once, and always come whole.
PAGED = ("voices", "enough", "strangers", "items", "unsorted", "suspects")


def _group(voice: Mapping[str, Any]) -> str:
    """Which list a voice is in: like one the owner could not name, surely someone heard enough already, or asked."""
    return "strangers" if voice.get("stranger") else "enough" if voice.get("enough") else "voices"


def page(reading: Mapping[str, Any], limits: Mapping[str, int | None]) -> dict[str, Any]:
    """The first ``limits[name]`` of each list in ``PAGED`` (the whole list without a limit), and how many each holds
    in all (``totals``; with how long they speak, for voices). The page asks again for more from the start, not for
    the rest after an offset: every list on it is of one reading, so a task settled meanwhile is neither shown twice
    nor skipped."""
    voices: dict[str, list[dict[str, Any]]] = {"voices": [], "enough": [], "strangers": []}
    for voice in reading["voices"]:
        voices[_group(voice)].append(voice)
    lists = {**voices, **{name: reading[name] for name in ("items", "unsorted", "suspects")}}
    totals: dict[str, dict[str, float]] = {}
    for name in PAGED:
        totals[name] = {"count": len(lists[name])}
        if name in voices:
            totals[name]["seconds"] = round(sum(voice["seconds"] for voice in lists[name]), 1)
        limit = limits.get(name)
        if limit is not None:
            lists[name] = lists[name][:limit]
    return {
        **reading,
        "voices": [voice for name in voices for voice in lists[name]],
        **{name: lists[name] for name in ("items", "unsorted", "suspects")},
        "totals": totals,
    }


class ReviewQueue:
    def __init__(self, library: Library) -> None:
        self.library = library
        self._lock = threading.Lock()
        self._observer: sqlite3.Connection | None = None
        self._identity: tuple[int, int] | None = None
        # Each permission scope's latest reading and the version it was made at. Bound in number, however many
        # accounts use the deployment; ``_cached`` guards it, so ``peek`` never waits for a calculation.
        self._entries: OrderedDict[frozenset[str], tuple[tuple[int, int, int], dict[str, Any]]] = OrderedDict()
        self._cached = threading.Lock()
        # Scopes worked out in the background now (``peek``), one calculation each.
        self._refreshing: set[frozenset[str]] = set()

    def close(self) -> None:
        with self._lock:
            if self._observer is not None:
                self._observer.close()
                self._observer = None
            with self._cached:
                self._entries.clear()

    def _stamp(self) -> tuple[int, int, int]:
        stat = self.library.db_path.stat()
        identity = (stat.st_dev, stat.st_ino)
        if self._observer is None or self._identity != identity:
            if self._observer is not None:
                self._observer.close()
            self._observer = sqlite3.connect(
                self.library.db_path.resolve().as_uri() + "?mode=ro", uri=True, check_same_thread=False
            )
            self._identity = identity
            # Another database: none of its readings may be answered with, not even while a new one is made.
            with self._cached:
                self._entries.clear()
        return (*identity, int(self._observer.execute("PRAGMA data_version").fetchone()[0]))

    def get(self, recordings: set[str]) -> dict[str, Any]:
        """The current reading, worked out now when the library changed since the last one."""
        key = frozenset(recordings)
        with self._lock:
            version = self._stamp()
            with self._cached:
                entry = self._entries.get(key)
            if entry is None or entry[0] != version:
                result = self._build(set(key))
                # Kept with the version it began at: a write during calculation makes it a reading to show while
                # the next is made (``peek``), never a current one.
                entry = (version, result)
                self._keep(key, entry)
                if self._stamp() != version:
                    return deepcopy(result)
            with self._cached:
                if key in self._entries:
                    self._entries.move_to_end(key)
            # Callers may serialize or change their response without changing the cached reading.
            return deepcopy(entry[1])

    def peek(self, recordings: set[str]) -> tuple[dict[str, Any], bool] | None:
        """The latest reading at once, and whether it is current; a reading that is not is worked out anew in the
        background, for the next request. None when there is no reading of this scope yet (``get`` makes one)."""
        key = frozenset(recordings)
        if not self._lock.acquire(blocking=False):
            # A calculation is under way: the reading before it, if any.
            with self._cached:
                entry = self._entries.get(key)
            return (deepcopy(entry[1]), False) if entry is not None else None
        try:
            version = self._stamp()
            with self._cached:
                entry = self._entries.get(key)
        finally:
            self._lock.release()
        if entry is None:
            return None
        current = entry[0] == version
        if not current:
            self._refresh(key)
        return deepcopy(entry[1]), current

    def _keep(self, key: frozenset[str], entry: tuple[tuple[int, int, int], dict[str, Any]]) -> None:
        with self._cached:
            self._entries[key] = entry
            self._entries.move_to_end(key)
            if len(self._entries) > 16:
                self._entries.popitem(last=False)

    def _refresh(self, key: frozenset[str]) -> None:
        with self._cached:
            if key in self._refreshing:
                return
            self._refreshing.add(key)

        def run() -> None:
            try:
                self.get(set(key))
            except Exception:
                logger.exception("review queue could not be worked out in the background")
            finally:
                with self._cached:
                    self._refreshing.discard(key)

        threading.Thread(target=run, name="review-queue-refresh", daemon=True).start()

    def _build(self, recordings: set[str]) -> dict[str, Any]:
        team = Team(self.library)
        voices, fragments = team.voices(recordings)
        suspects = Reviews(self.library).suspects(recordings)
        settled, total = team.heard(recordings)
        return {
            "heard": {"settled": settled, "total": total},
            "items": team.review(recordings, disputed_only=True),
            "voices": [voice.model_dump() for voice in voices],
            "fragments": [
                {
                    **member.model_dump(),
                    "like": {"person_id": voice.candidates[0].person_id, "name": voice.candidates[0].name}
                    if voice.candidates
                    else None,
                }
                for voice in fragments
                for member in voice.members
            ],
            "unsorted": [
                {"recording_id": r.id, "filename": r.filename, "speakers": n, "total": r.speakers}
                for r, n in team.unvoiced(recordings)
            ],
            "suspects": [review.model_dump() for review in suspects],
        }
