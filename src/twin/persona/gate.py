"""Whether a twin made from a recording library may answer right now.

Such a twin answers only from a complete build of the library's current decisions: its row in the owner's
``library.db`` (``personas_sync``) has ``done == wanted``. Every decision that changes the twin's recordings raises
``wanted`` in the same transaction, so from that moment until a build of exactly that state succeeds, nothing of the
twin's memory is used: its own words, its profile and the meeting record alike. One exception: while the rebuild is
held (quota spent, automatic rebuild switched off), a change found to only add recordings to the last build
(``answerable == wanted``) leaves the twin answering from that build, since nothing it holds was taken away; any
further change closes it until checked again. Twins not made from a library are unaffected.
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path

from .store import PersonaStore

LINK = "library_sync"
# The library version whose sources were last written into the twin; a build that started from it can open it.
SYNCED = "library_synced"
# A twin made from a library answers as a meeting record: dated statements and what was decided, not a portrait.
MODE = "answer_mode"
MEETING_RECORD = "meeting_record"


class MemoryUpdating(Exception):
    """The twin's memory is being brought in line with changed recordings; it must not answer yet."""

    def __init__(self) -> None:
        super().__init__("记忆更新中：录音的说话人归属刚有变化，整理完成后就能回答")


def link(store: PersonaStore, library_db: Path, persona_id: str) -> None:
    """Make the twin follow ``library_db``; the path is kept relative so a restored data folder still works."""
    relative = os.path.relpath(library_db.resolve(), store.path.resolve().parent)
    store.set_meta(LINK, json.dumps({"db": relative, "persona": persona_id}))
    store.set_meta(MODE, MEETING_RECORD)


def version(store: PersonaStore) -> int | None:
    """The memory version the twin answers from; None for a twin not made from a library. ``MemoryUpdating``
    while a change is waiting for its build (or the library cannot be read)."""
    return _version(store.path, store.get_meta(LINK))


def version_at(db_path: Path) -> int | None:
    """``version`` without opening the twin's store (for checking every request)."""
    return _version(db_path, _linked(db_path))


def linked(db_path: Path) -> bool:
    """Whether the twin at ``db_path`` is made from a recording library."""
    return _linked(db_path) is not None


def _linked(db_path: Path) -> str | None:
    try:
        with closing(sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True, timeout=10)) as db:
            row = db.execute("SELECT value FROM p_meta WHERE key = ?", (LINK,)).fetchone()
    except sqlite3.Error:
        return None
    return str(row[0]) if row and row[0] else None


def _version(db_path: Path, linked: str | None) -> int | None:
    if not linked:
        return None
    try:
        info = json.loads(linked)
        path = (db_path.resolve().parent / info["db"]).resolve()
        with closing(sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=10)) as db:
            row = db.execute(
                "SELECT wanted, done, answerable FROM personas_sync WHERE persona_id = ?", (info["persona"],)
            ).fetchone()
    except (ValueError, KeyError, TypeError, sqlite3.Error):
        row = None
    if row is None or (row[0] != row[1] and row[2] != row[0]):
        raise MemoryUpdating()
    return int(row[1])


def current(store: PersonaStore, expected: int | None) -> bool:
    """Whether the twin still answers from ``expected``, the version it started an answer with."""
    try:
        return version(store) == expected
    except MemoryUpdating:
        return False


def meeting_record(store: PersonaStore) -> bool:
    return store.get_meta(MODE) == MEETING_RECORD
