"""The recording review queue, reused until the library changes.

The observer connection never writes or holds a transaction. SQLite's ``data_version`` on that same connection
notices commits from request threads, background jobs and other processes, including changes to voice samples
that affect recordings elsewhere. A viewer's editable recording set is part of the key; permissions are still
checked on every request. Concurrent readers share one calculation, without holding the library's write lock.
"""

from __future__ import annotations

import sqlite3
import threading
from collections import OrderedDict
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from ..media.library import Library
from ..media.review import Reviews
from ..media.team import Team

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
        self._version: tuple[int, int, int] | None = None
        # Bound the number of permission scopes kept, however many accounts use the deployment.
        self._entries: OrderedDict[frozenset[str], dict[str, Any]] = OrderedDict()

    def close(self) -> None:
        with self._lock:
            if self._observer is not None:
                self._observer.close()
                self._observer = None
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
            self._entries.clear()
        return (*identity, int(self._observer.execute("PRAGMA data_version").fetchone()[0]))

    def get(self, recordings: set[str]) -> dict[str, Any]:
        key = frozenset(recordings)
        with self._lock:
            version = self._stamp()
            if self._version != version:
                self._entries.clear()
                self._version = version
            if key not in self._entries:
                result = self._build(set(key))
                # A write during calculation must not make a mixed reading reusable.
                if self._stamp() != version:
                    return result
                self._entries[key] = result
                if len(self._entries) > 16:
                    self._entries.popitem(last=False)
            self._entries.move_to_end(key)
            # Callers may serialize or change their response without changing the cached reading.
            return deepcopy(self._entries[key])

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
