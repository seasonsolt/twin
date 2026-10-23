"""The team's own database (``data/team/team.db``): what connects people and belongs to none of them.

A person's memories stay in their twin's database, the recordings and the people heard in them in the recording
library. This holds what is between two people: for now the index of conversations (who asked whose twin, and which
tier of memory it answers from), later handoffs and shared answers. It copies no memory and no conversation text, and
the index can be rebuilt from the twins' databases (``rebuild_conversations``), so a conversation's text is always
the twin's.

Like a twin's database it migrates by appending to ``_MIGRATIONS`` only, snapshots itself before a migration, refuses
to open when written by a newer twin, and lives in an owner-only directory in WAL mode.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
import sqlite3
import threading
from collections.abc import Collection, Iterable, Iterator, Mapping, Sequence
from contextlib import closing, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .persona.tiers import COLLEAGUE, SELF, Audience
from .util import prepare_private_file

logger = logging.getLogger(__name__)

Via = Literal["direct", "delegate"]

_MIGRATIONS: tuple[str, ...] = (
    # 1: the index of conversations and the database's own records.
    """
    CREATE TABLE conversations (
        id TEXT PRIMARY KEY,
        persona_id TEXT NOT NULL,
        asker TEXT,
        audience TEXT NOT NULL CHECK (audience IN ('self', 'colleague')),
        via TEXT NOT NULL DEFAULT 'direct' CHECK (via IN ('direct', 'delegate')),
        delegation_id TEXT,
        title TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        deleted_at TEXT);
    CREATE INDEX conversations_persona ON conversations(persona_id, updated_at DESC);
    CREATE INDEX conversations_asker ON conversations(asker, updated_at DESC);
    CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    """,
)

SNAPSHOT_DIR = "snapshots"
SNAPSHOT_KEEP = 3
# ``meta`` keys.
RECONCILED_AT = "conversations:reconciled_at"
INDEXED_LEGACY = "conversations:legacy_indexed"


class NewerTeamError(RuntimeError):
    pass


@dataclass(frozen=True)
class IndexedConversation:
    id: str
    persona_id: str
    asker: str | None
    audience: Audience
    via: Via
    delegation_id: str | None
    title: str
    updated_at: str
    deleted_at: str | None


@dataclass(frozen=True)
class Reconciled:
    """What a pass over the twins' conversations changed in the index."""

    added: int = 0
    updated: int = 0
    removed: int = 0


def team_path(data_dir: Path) -> Path:
    return data_dir / "team" / "team.db"


class TeamDB:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        prepare_private_file(self.path)
        self.path.parent.chmod(0o700)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(self.path, check_same_thread=False, timeout=30)
        try:
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA foreign_keys=ON")
            self._migrate()
        except Exception:
            self._db.close()
            raise

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def __enter__(self) -> TeamDB:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ------------------------------------------------------------ schema

    def schema_version(self) -> int:
        with self._lock:
            return int(self._db.execute("PRAGMA user_version").fetchone()[0])

    def _migrate(self) -> None:
        version = self.schema_version()
        newer = (
            f"团队库由更新版本的 twin 写入（schema {version}），当前版本只支持到 {len(_MIGRATIONS)}，请升级或从备份恢复"
        )
        if version > len(_MIGRATIONS):
            raise NewerTeamError(newer)
        if version == len(_MIGRATIONS):
            return
        if version:
            self.snapshot(f"schema{version}")
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                version = int(self._db.execute("PRAGMA user_version").fetchone()[0])
                if version > len(_MIGRATIONS):
                    raise NewerTeamError(newer)
                for number, migration in enumerate(_MIGRATIONS[version:], version + 1):
                    statement = ""
                    for char in migration:
                        statement += char
                        if char == ";" and sqlite3.complete_statement(statement):
                            self._db.execute(statement)
                            statement = ""
                    if statement.strip():
                        self._db.execute(statement)
                    self._db.execute(f"PRAGMA user_version = {number}")
                self._db.commit()
            except BaseException:
                self._db.rollback()
                raise

    def snapshot(self, label: str) -> Path:
        """Copy the database into ``snapshots/`` (0600) before a migration; keep the newest few."""
        directory = self.path.parent / SNAPSHOT_DIR
        directory.mkdir(mode=0o700, exist_ok=True)
        directory.chmod(0o700)
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", label)
        target = directory / f"{self.path.stem}-{stamp}-{safe}.db"
        number = 1
        while target.exists():
            number += 1
            target = directory / f"{self.path.stem}-{stamp}-{safe}-{number}.db"
        prepare_private_file(target)
        with self._lock, closing(sqlite3.connect(target)) as out:
            self._db.backup(out)
        for old in sorted(directory.glob(f"{self.path.stem}-*.db"))[:-SNAPSHOT_KEEP]:
            old.unlink(missing_ok=True)
        return target

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock, self._db:
            yield self._db

    # ------------------------------------------------------------ meta

    def get_meta(self, key: str) -> str | None:
        with self._lock:
            row = self._db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return None if row is None else str(row[0])

    def set_meta(self, key: str, value: str) -> None:
        with self._tx() as db:
            db.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, value))

    # ------------------------------------------------------------ conversation index

    def record_conversation(
        self,
        conversation_id: str,
        persona_id: str,
        asker: str | None,
        audience: Audience,
        title: str,
        updated_at: str,
        *,
        via: Via = "direct",
        delegation_id: str | None = None,
    ) -> None:
        """Index a conversation once, with the tier it answers from; a conversation already indexed keeps the tier it
        was created with, whatever is asked now."""
        with self._tx() as db:
            db.execute(
                "INSERT INTO conversations (id, persona_id, asker, audience, via, delegation_id, title, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET title = excluded.title, updated_at = excluded.updated_at, "
                "deleted_at = NULL",
                (conversation_id, persona_id, asker, audience, via, delegation_id, title, updated_at),
            )

    def refresh_conversation(self, conversation_id: str, title: str, updated_at: str) -> None:
        with self._tx() as db:
            db.execute(
                "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?", (title, updated_at, conversation_id)
            )

    def delete_conversation(self, conversation_id: str) -> None:
        with self._tx() as db:
            db.execute(
                "UPDATE conversations SET deleted_at = ? WHERE id = ? AND deleted_at IS NULL",
                (dt.datetime.now(dt.UTC).isoformat(), conversation_id),
            )

    def audience_of(self, conversation_id: str) -> Audience | None:
        """The tier a conversation answers from; None when it is not indexed."""
        with self._lock:
            row = self._db.execute("SELECT audience FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
        return None if row is None else (SELF if row[0] == SELF else COLLEAGUE)

    def conversations(
        self,
        *,
        persona_id: str | None = None,
        asker: str | None = None,
        personas: Collection[str] | None = None,
        include_deleted: bool = False,
    ) -> list[IndexedConversation]:
        """Indexed conversations, newest first. ``personas`` limits them to those twins (the ones not in the trash)."""
        where = [] if include_deleted else ["deleted_at IS NULL"]
        params: list[object] = []
        if persona_id is not None:
            where.append("persona_id = ?")
            params.append(persona_id)
        if personas is not None:
            where.append(f"persona_id IN ({','.join('?' * len(personas))})" if personas else "0")
            params.extend(personas)
        if asker is not None:
            where.append("asker = ?")
            params.append(asker)
        sql = "SELECT * FROM conversations" + (f" WHERE {' AND '.join(where)}" if where else "")
        with self._lock:
            self._db.row_factory = sqlite3.Row
            try:
                rows = self._db.execute(sql + " ORDER BY updated_at DESC, id", params).fetchall()
            finally:
                self._db.row_factory = None
        return [
            IndexedConversation(
                r["id"],
                r["persona_id"],
                r["asker"],
                SELF if r["audience"] == SELF else COLLEAGUE,
                r["via"],
                r["delegation_id"],
                r["title"],
                r["updated_at"],
                r["deleted_at"],
            )
            for r in rows
        ]

    def forget_persona(self, persona_id: str) -> None:
        """Drop everything indexed for a twin that is gone for good."""
        with self._tx() as db:
            db.execute("DELETE FROM conversations WHERE persona_id = ?", (persona_id,))

    def reconcile_persona(self, persona_id: str, rows: Iterable[tuple[str, str | None, str, str]]) -> Reconciled:
        """Bring the index of one twin in line with the conversations in its database (``rows``: id, asker, title,
        updated at): add the ones it lacks, as the colleague tier, which is what a conversation from before the
        index was; refresh titles and times; mark the ones that are gone as deleted. Conversations the twin's
        database does not have are the index's to forget, never the other way round."""
        wanted = {r[0]: r for r in rows}
        added = updated = removed = 0
        with self._tx() as db:
            known = {
                r[0]: (r[1], r[2], r[3])
                for r in db.execute(
                    "SELECT id, title, updated_at, deleted_at FROM conversations WHERE persona_id = ?", (persona_id,)
                )
            }
            for conversation_id, asker, title, updated_at in wanted.values():
                current = known.get(conversation_id)
                if current is None:
                    db.execute(
                        "INSERT INTO conversations (id, persona_id, asker, audience, via, title, updated_at) "
                        "VALUES (?, ?, ?, 'colleague', 'direct', ?, ?)",
                        (conversation_id, persona_id, asker, title, updated_at),
                    )
                    added += 1
                elif current != (title, updated_at, None):
                    db.execute(
                        "UPDATE conversations SET title = ?, updated_at = ?, deleted_at = NULL WHERE id = ?",
                        (title, updated_at, conversation_id),
                    )
                    updated += 1
            gone = [(dt.datetime.now(dt.UTC).isoformat(), i) for i, v in known.items() if i not in wanted and not v[2]]
            db.executemany("UPDATE conversations SET deleted_at = ? WHERE id = ?", gone)
            removed = len(gone)
            stamp = dt.datetime.now(dt.UTC).isoformat()
            db.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (RECONCILED_AT, stamp))
            db.execute("INSERT OR IGNORE INTO meta VALUES (?, ?)", (INDEXED_LEGACY, stamp))
        return Reconciled(added, updated, removed)

    def rebuild_conversations(self, by_persona: Mapping[str, Sequence[tuple[str, str | None, str, str]]]) -> Reconciled:
        """Index the conversations of these twins again from their databases (``by_persona``: id, asker, title,
        updated at), dropping what the index held for them. The tier a conversation answers from is not in the
        twin's database, so a conversation the index already knew keeps it and the others are the colleague tier."""
        added = removed = 0
        with self._tx() as db:
            for persona_id, rows in by_persona.items():
                kept = {
                    r[0]: (r[1], r[2], r[3])
                    for r in db.execute(
                        "SELECT id, audience, via, delegation_id FROM conversations WHERE persona_id = ?", (persona_id,)
                    )
                }
                removed += db.execute("DELETE FROM conversations WHERE persona_id = ?", (persona_id,)).rowcount
                for conversation_id, asker, title, updated_at in rows:
                    audience, via, delegation_id = kept.get(conversation_id, (COLLEAGUE, "direct", None))
                    db.execute(
                        "INSERT INTO conversations (id, persona_id, asker, audience, via, delegation_id, title, "
                        "updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (conversation_id, persona_id, asker, audience, via, delegation_id, title, updated_at),
                    )
                    added += 1
        self.set_meta(RECONCILED_AT, dt.datetime.now(dt.UTC).isoformat())
        return Reconciled(added=added, removed=removed)
