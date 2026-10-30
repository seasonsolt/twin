"""Whether the person is alive or their memory is sealed (P2 延续, P2.5).

A twin starts ``alive``: the person grows its memory. Once their heir opens it (P2.7) it is ``sealed`` for good: no new
memory grows after them (Locke). Nothing is imported, built, filled in, reviewed or promised any more; conversations
still answer but leave no trace in the memory (no ``p_chat_log``, no promise, no coverage demand, no note). A newer
kernel only moves stored facet ids to its taxonomy, which calls no model (``PersonaStore._migrate_taxonomy``); it never
extracts or merges again, so a new prompt cannot rewrite them into someone else. Sealing snapshots the store first
(``PersonaStore.snapshot``), which a seal opened by mistake while the person lives is rolled back from
(``docs/LOCAL_DEV.md#回退记忆内核``).

The state is two ``p_meta`` keys, so it needs no migration and is copied with the database.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Literal

from .store import PersonaStore

LIFECYCLE = "lifecycle"
SEALED_AT = "lifecycle:sealed_at"
# The label of the snapshot taken as the memory is sealed; it is kept however many snapshots follow it.
SEAL_SNAPSHOT = "sealed"
ALIVE: Literal["alive"] = "alive"
SEALED: Literal["sealed"] = "sealed"
Lifecycle = Literal["alive", "sealed"]
# The ``code`` of a write refused because the memory is sealed (``docs/CONTRACTS.md``).
SEALED_CODE = "memory_sealed"


class MemorySealed(Exception):
    """A write to a memory that is sealed: nothing grows in it any more."""

    code = SEALED_CODE

    def __init__(self) -> None:
        super().__init__("记忆已冻结，不能再改动")


def state(store: PersonaStore) -> Lifecycle:
    return SEALED if store.get_meta(LIFECYCLE) == SEALED else ALIVE


def sealed(store: PersonaStore) -> bool:
    return state(store) == SEALED


def sealed_at(store: PersonaStore) -> str | None:
    """When the memory was sealed (ISO 8601, UTC); None while the person is alive."""
    return store.get_meta(SEALED_AT) if sealed(store) else None


def sealed_path(db_path: Path) -> bool:
    """``sealed`` without opening the twin's store, which would migrate it (for checking every request); a twin with
    no database yet is alive."""
    try:
        with closing(sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True, timeout=10)) as db:
            row = db.execute("SELECT value FROM p_meta WHERE key = ?", (LIFECYCLE,)).fetchone()
    except sqlite3.Error:
        return False
    return bool(row) and row[0] == SEALED


def refuse_if_sealed(store: PersonaStore) -> None:
    """``MemorySealed`` when the memory is sealed."""
    if sealed(store):
        raise MemorySealed


def seal(store: PersonaStore, now: dt.datetime | None = None) -> Path | None:
    """Seal the memory, once and for good: the store is snapshotted first, and the snapshot's path returned (None for
    a store with no file). Sealing a sealed memory changes nothing and returns None."""
    if sealed(store):
        return None
    snapshot = store.snapshot(SEAL_SNAPSHOT)
    when = (now or dt.datetime.now(dt.UTC)).isoformat(timespec="seconds")
    store.set_metas({SEALED_AT: when, LIFECYCLE: SEALED})
    return snapshot
