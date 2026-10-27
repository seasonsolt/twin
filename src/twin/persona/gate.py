"""Which build of a recording library a twin made from it answers from.

Its row in the owner's ``library.db`` (``personas_sync``) counts the library's decisions: every decision that changes
the twin's recordings raises ``wanted`` in the same transaction, and a build of exactly that state sets ``done``. The
twin always answers from what it holds, the last build (``done``), also while a newer one is wanted or being made
(``updating``): a rebuild that waits on a model or GPU service that is down must not stop people talking to it. Only a
twin whose library cannot be read does not answer. Twins not made from a library are unaffected.
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
    """The library the twin is made from cannot be read, so which of its memory is current is not known."""

    def __init__(self) -> None:
        super().__init__("记忆暂时读不到：录音库打不开，稍后再试")


def link(store: PersonaStore, library_db: Path, persona_id: str) -> None:
    """Make the twin follow ``library_db``; the path is kept relative so a restored data folder still works."""
    relative = os.path.relpath(library_db.resolve(), store.path.resolve().parent)
    store.set_meta(LINK, json.dumps({"db": relative, "persona": persona_id}))
    store.set_meta(MODE, MEETING_RECORD)


def library_db(store: PersonaStore) -> Path | None:
    """The library the twin is made from; None for a twin not made from one."""
    linked = store.get_meta(LINK)
    if not linked:
        return None
    try:
        return (store.path.resolve().parent / str(json.loads(linked)["db"])).resolve()
    except (ValueError, KeyError, TypeError):
        return None


def version(store: PersonaStore) -> int | None:
    """The memory version the twin answers from, its last build; None for a twin not made from a library.
    ``MemoryUpdating`` when the library cannot be read."""
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


def updating(db_path: Path) -> bool:
    """Whether the twin at ``db_path`` is made from a library whose latest decisions its memory does not hold yet
    (or whose library cannot be read): it answers from its last build meanwhile."""
    linked = _linked(db_path)
    if not linked:
        return False
    row = _sync_row(db_path, linked)
    return row is None or row[0] != row[1]


def _sync_row(db_path: Path, linked: str) -> tuple[int, int] | None:
    """(wanted, done) of the twin in its library; None when the library cannot be read."""
    try:
        info = json.loads(linked)
        path = (db_path.resolve().parent / info["db"]).resolve()
        with closing(sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=10)) as db:
            row = db.execute(
                "SELECT wanted, done FROM personas_sync WHERE persona_id = ?", (info["persona"],)
            ).fetchone()
    except (ValueError, KeyError, TypeError, sqlite3.Error):
        return None
    return (int(row[0]), int(row[1])) if row else None


def _version(db_path: Path, linked: str | None) -> int | None:
    if not linked:
        return None
    row = _sync_row(db_path, linked)
    if row is None:
        raise MemoryUpdating()
    return row[1]


def meeting_record(store: PersonaStore) -> bool:
    return store.get_meta(MODE) == MEETING_RECORD
