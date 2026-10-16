"""Persistence of the general persona core: sources and their expressions, extraction candidates and the profile.

The tables live in ``settings.db_path`` under a ``p_`` prefix.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import shutil
import sqlite3
import threading
import uuid
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any

import numpy as np

from ..embed import Matrix
from ..media.schema import AVATAR_ALIASES, AVATAR_PRESETS
from ..util import prepare_private_file
from .items import ExtractStats, PersonaCandidate, PersonaItem, PReview, apply_review, carry_reviews
from .kernel import KERNEL, KernelVersion, kernel_json
from .schema import ChatReply, Expression, LedgerEntry, ParsedSource, ReviewStatus, Source, SourceKind

_SCHEMA = """
CREATE TABLE IF NOT EXISTS p_sources (
    source_id TEXT PRIMARY KEY, kind TEXT NOT NULL, first_date TEXT, json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS p_expressions (
    expression_id TEXT PRIMARY KEY, source_id TEXT NOT NULL, idx INTEGER NOT NULL, date TEXT,
    is_target INTEGER NOT NULL, held_out INTEGER NOT NULL, json TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS p_expressions_source ON p_expressions(source_id, idx);
CREATE TABLE IF NOT EXISTS p_chunks (chunk_id TEXT PRIMARY KEY, source_id TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS p_candidates (
    candidate_id TEXT PRIMARY KEY, chunk_id TEXT NOT NULL, facet_id TEXT NOT NULL, json TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS p_candidates_facet ON p_candidates(facet_id);
CREATE TABLE IF NOT EXISTS p_items (item_id TEXT PRIMARY KEY, facet_id TEXT NOT NULL, json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS p_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS p_reviews (item_id TEXT PRIMARY KEY, json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS p_chat_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, abstain INTEGER NOT NULL, json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY, owner TEXT, title TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS conversations_owner_updated ON conversations(owner, updated_at DESC);
CREATE TABLE IF NOT EXISTS conversation_turns (
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL, reply_json TEXT, created_at TEXT NOT NULL,
    PRIMARY KEY (conversation_id, seq));
CREATE TABLE IF NOT EXISTS p_vectors (
    namespace TEXT NOT NULL, ref_id TEXT NOT NULL, text_sha TEXT NOT NULL, vec BLOB NOT NULL,
    PRIMARY KEY (namespace, ref_id));
"""
_LEDGER = """
CREATE TABLE IF NOT EXISTS p_ledger (
    entry_id TEXT PRIMARY KEY, source_id TEXT NOT NULL, meeting_date TEXT, expression_id TEXT NOT NULL,
    review TEXT NOT NULL, json TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS p_ledger_source ON p_ledger(source_id);
"""
_MIGRATIONS: tuple[str, ...] = (
    _SCHEMA,
    # 2: per-chunk extraction counts (``ExtractStats`` JSON); NULL for chunks extracted before it.
    "ALTER TABLE p_chunks ADD COLUMN stats TEXT;",
    # 3: the commitment ledger (承诺账本).
    _LEDGER,
)


SNAPSHOT_DIR = "kernel-snapshots"
SNAPSHOT_KEEP = 3


def list_snapshots(db_path: Path) -> list[Path]:
    """Snapshots of one store, oldest first."""
    return sorted((db_path.parent / SNAPSHOT_DIR).glob(f"{db_path.stem}-*.db"))


def restore_snapshot(snapshot: Path, db_path: Path) -> Path | None:
    """Copy a snapshot of this store back over it through SQLite, so WAL side files stay consistent; the current
    state is snapshotted first and its path returned. Stop the web first."""
    if snapshot.resolve() not in [p.resolve() for p in list_snapshots(db_path)]:
        raise ValueError(f"请指定 {db_path.parent / SNAPSHOT_DIR} 中属于该分身的快照文件")
    with closing(sqlite3.connect(":memory:")) as copy:
        with closing(sqlite3.connect(f"{snapshot.resolve().as_uri()}?mode=ro", uri=True)) as source:
            source.backup(copy)
        before = None
        if db_path.is_file():
            with PersonaStore(db_path) as current:
                before = current.snapshot("before-restore")
        prepare_private_file(db_path)
        with closing(sqlite3.connect(db_path)) as target:
            copy.backup(target)
    return before


class NewerStoreError(RuntimeError):
    pass


def stored_identity(path: Path) -> tuple[str | None, str]:
    if not path.is_file():
        return None, ""
    with PersonaStore(path) as store:
        return store.get_meta("identity:name") or None, store.get_meta("identity:about") or ""


def stored_avatar(path: Path, configured: str = "chestnut") -> str:
    value = None
    if path.is_file():
        with PersonaStore(path) as store:
            value = store.get_meta("identity:avatar_preset")
    selected = AVATAR_ALIASES.get(value or configured, value or configured)
    return selected if selected in AVATAR_PRESETS else "chestnut"


class PersonaStore:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        if str(path) not in ("", ":memory:"):
            prepare_private_file(self.path)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        try:
            self._db.execute("PRAGMA foreign_keys=ON")
            version = int(self._db.execute("PRAGMA user_version").fetchone()[0])
            if version > len(_MIGRATIONS):
                raise NewerStoreError(
                    f"数据库由更新版本的 twin 写入（schema {version}），"
                    f"当前版本只支持到 {len(_MIGRATIONS)}，请升级或从备份恢复"
                )
            if version == len(_MIGRATIONS):
                self._db.execute("PRAGMA journal_mode=WAL")
                return
            if self._db.execute("SELECT 1 FROM sqlite_master WHERE type = 'table'").fetchone():
                self.snapshot(f"schema{version}")
            self._db.execute("BEGIN IMMEDIATE")
            version = int(self._db.execute("PRAGMA user_version").fetchone()[0])
            if version > len(_MIGRATIONS):
                raise NewerStoreError(
                    f"数据库由更新版本的 twin 写入（schema {version}），"
                    f"当前版本只支持到 {len(_MIGRATIONS)}，请升级或从备份恢复"
                )
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
            self._db.execute("PRAGMA journal_mode=WAL")
        except Exception:
            self._db.rollback()
            self._db.close()
            raise

    def snapshot(self, label: str) -> Path | None:
        """Copy the store into `kernel-snapshots/` (0600) before a migration or kernel rebuild; keep the newest few."""
        if str(self.path) in ("", ":memory:"):
            return None
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
        for old in list_snapshots(self.path)[:-SNAPSHOT_KEEP]:
            old.unlink(missing_ok=True)
        return target

    def has_extractions(self) -> bool:
        with self._lock:
            return self._db.execute("SELECT 1 FROM p_chunks LIMIT 1").fetchone() is not None

    def schema_version(self) -> int:
        with self._lock:
            return int(self._db.execute("PRAGMA user_version").fetchone()[0])

    def close(self) -> None:
        self._db.close()

    def __enter__(self) -> PersonaStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            if self._db.in_transaction:
                yield self._db
            else:
                with self._db:
                    yield self._db

    def set_identity(self, name: str, about: str, note: ParsedSource | None) -> bool:
        with self._tx() as db:
            db.execute("BEGIN IMMEDIATE")
            old_about = self.get_meta("identity:about") or ""
            self.set_meta("identity:name", name)
            self.set_meta("identity:about", about)
            if about == old_about:
                return False
            changed = False
            for source in self.list_sources():
                if source.title == "自我介绍" and source.origin.startswith("note:"):
                    self.delete_source(source.source_id)
                    changed = True
            if note is not None:
                self.put_source(note)
                changed = True
            return changed

    # ------------------------------------------------------------ sources

    def _sources_changed(self, db: sqlite3.Connection) -> None:
        db.execute(
            "INSERT OR REPLACE INTO p_meta VALUES ('sources_changed_at', ?)",
            (dt.datetime.now(dt.UTC).isoformat(),),
        )

    def put_source(self, parsed: ParsedSource) -> bool:
        """Store a parsed source and its expressions, replacing a source with the same id (the same file and
        content). Returns False when it was already stored."""
        source = parsed.source
        with self._tx() as db:
            existed = db.execute("SELECT 1 FROM p_sources WHERE source_id = ?", (source.source_id,)).fetchone()
            db.execute("DELETE FROM p_expressions WHERE source_id = ?", (source.source_id,))
            db.execute(
                "INSERT OR REPLACE INTO p_sources VALUES (?, ?, ?, ?)",
                (
                    source.source_id,
                    source.kind.value,
                    source.first_date.isoformat() if source.first_date else None,
                    source.model_dump_json(),
                ),
            )
            db.executemany(
                "INSERT INTO p_expressions VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        e.expression_id,
                        e.source_id,
                        e.idx,
                        e.date.isoformat() if e.date else None,
                        int(e.is_target),
                        0,
                        e.model_dump_json(),
                    )
                    for e in parsed.expressions
                ],
            )
            self._sources_changed(db)
            # A fresh value per change, so a build that read the old value cannot settle a change made while it ran.
            db.execute(
                "INSERT OR REPLACE INTO p_meta VALUES (?, ?)", (f"source_pending:{source.source_id}", uuid.uuid4().hex)
            )
        return existed is None

    def list_sources(self, kind: SourceKind | None = None) -> list[Source]:
        with self._lock:
            rows = self._db.execute("SELECT json FROM p_sources ORDER BY first_date, source_id").fetchall()
        sources = [Source.model_validate_json(r[0]) for r in rows]
        return [source for source in sources if kind is None or source.kind is kind]

    def count_sources(self) -> int:
        with self._lock:
            return int(self._db.execute("SELECT COUNT(*) FROM p_sources").fetchone()[0])

    def get_source(self, source_id: str) -> Source | None:
        with self._lock:
            row = self._db.execute("SELECT json FROM p_sources WHERE source_id = ?", (source_id,)).fetchone()
        return Source.model_validate_json(row[0]) if row else None

    def update_source(self, source: Source) -> bool:
        """Update metadata without marking transcript expressions as changed."""
        with self._tx() as db:
            return (
                db.execute(
                    "UPDATE p_sources SET json = ? WHERE source_id = ?", (source.model_dump_json(), source.source_id)
                ).rowcount
                > 0
            )

    def delete_source(self, source_id: str) -> bool:
        """Remove a source, its expressions and the candidates extracted from it (the profile is rebuilt from the
        remaining candidates on the next build)."""
        with self._tx() as db:
            source = self.get_source(source_id)
            chunks = [r[0] for r in db.execute("SELECT chunk_id FROM p_chunks WHERE source_id = ?", (source_id,))]
            db.executemany("DELETE FROM p_candidates WHERE chunk_id = ?", [(c,) for c in chunks])
            db.execute("DELETE FROM p_chunks WHERE source_id = ?", (source_id,))
            db.execute("DELETE FROM p_expressions WHERE source_id = ?", (source_id,))
            deleted = db.execute("DELETE FROM p_sources WHERE source_id = ?", (source_id,)).rowcount > 0
            if deleted:
                self._sources_changed(db)
                db.execute(
                    "DELETE FROM p_meta WHERE key IN (?, ?, ?)",
                    (f"source_pending:{source_id}", f"source_error:{source_id}", f"ledger_done:{source_id}"),
                )
                self._drop_ledger(db, source_id, reviewed=True)
                if source and source.media_sha and re.fullmatch(r"[0-9a-f]{64}", source.media_sha):
                    shutil.rmtree(self.path.parent / "media-sources" / source.media_sha, ignore_errors=True)
            return deleted

    # ------------------------------------------------------------ commitment ledger

    def list_ledger(self) -> list[LedgerEntry]:
        """Every ledger entry, in meeting order and, within a meeting, in the order the words were said."""
        with self._lock:
            rows = self._db.execute(
                "SELECT json FROM p_ledger ORDER BY meeting_date, source_id, expression_id, entry_id"
            ).fetchall()
        return [LedgerEntry.model_validate_json(r[0]) for r in rows]

    def get_ledger_entry(self, entry_id: str) -> LedgerEntry | None:
        with self._lock:
            row = self._db.execute("SELECT json FROM p_ledger WHERE entry_id = ?", (entry_id,)).fetchone()
        return LedgerEntry.model_validate_json(row[0]) if row else None

    def put_ledger_entry(self, entry: LedgerEntry) -> None:
        with self._tx() as db:
            self._insert_ledger(db, [entry])

    def replace_ledger_source(self, source_id: str, entries: list[LedgerEntry], done: str) -> bool:
        """Swap a source's unreviewed entries for ``entries``; entries the person reviewed stay. ``done`` records the
        extractor version that processed the source. False, writing nothing, when the source was deleted meanwhile."""
        with self._tx() as db:
            if db.execute("SELECT 1 FROM p_sources WHERE source_id = ?", (source_id,)).fetchone() is None:
                return False
            self._drop_ledger(db, source_id, reviewed=False)
            self._insert_ledger(db, entries)
            db.execute("INSERT OR REPLACE INTO p_meta VALUES (?, ?)", (f"ledger_done:{source_id}", done))
            return True

    def ledger_done(self, source_id: str) -> str | None:
        """The extractor version that last processed the source, None when it never was."""
        return self.get_meta(f"ledger_done:{source_id}")

    @staticmethod
    def _insert_ledger(db: sqlite3.Connection, entries: list[LedgerEntry]) -> None:
        db.executemany(
            "INSERT OR REPLACE INTO p_ledger VALUES (?, ?, ?, ?, ?, ?)",
            [
                (
                    e.entry_id,
                    e.source_id,
                    e.meeting_date.isoformat() if e.meeting_date else None,
                    e.expression_id,
                    e.review.value,
                    e.model_dump_json(),
                )
                for e in entries
            ],
        )

    @staticmethod
    def _drop_ledger(db: sqlite3.Connection, source_id: str, *, reviewed: bool) -> None:
        """Delete a source's entries (only the unreviewed ones unless ``reviewed``) and unlink entries that pointed
        at them."""
        query = "SELECT entry_id FROM p_ledger WHERE source_id = ?" + ("" if reviewed else " AND review = ?")
        params = (source_id,) if reviewed else (source_id, ReviewStatus.UNREVIEWED.value)
        gone = {r[0] for r in db.execute(query, params)}
        if not gone:
            return
        db.executemany("DELETE FROM p_ledger WHERE entry_id = ?", [(g,) for g in gone])
        linked = [LedgerEntry.model_validate_json(r[0]) for r in db.execute("SELECT json FROM p_ledger")]
        PersonaStore._insert_ledger(
            db, [e.model_copy(update={"relates_to": None}) for e in linked if e.relates_to in gone]
        )

    def empty_chunks(self) -> dict[str, int]:
        """Per source, how many of its extracted chunks yielded no candidate."""
        with self._lock:
            rows = self._db.execute(
                "SELECT source_id, COUNT(*) FROM p_chunks "
                "WHERE chunk_id NOT IN (SELECT chunk_id FROM p_candidates) GROUP BY source_id"
            ).fetchall()
        return {source_id: count for source_id, count in rows}

    def reextract_source(self, source_id: str, *, empty_only: bool = False) -> int | None:
        """Forget what was extracted from a source (with ``empty_only``, only its chunks that yielded no candidate),
        so the next build asks the model again even though those chunks are unchanged; the profile keeps the old
        items until that build merges. Returns the chunks forgotten, or None when there is no such source; a source
        with nothing to forget is left as it is."""
        with self._tx() as db:
            if db.execute("SELECT 1 FROM p_sources WHERE source_id = ?", (source_id,)).fetchone() is None:
                return None
            empty = " AND chunk_id NOT IN (SELECT chunk_id FROM p_candidates)" if empty_only else ""
            chunks = [
                r[0] for r in db.execute(f"SELECT chunk_id FROM p_chunks WHERE source_id = ?{empty}", (source_id,))
            ]
            if not chunks:
                return 0
            db.executemany("DELETE FROM p_candidates WHERE chunk_id = ?", [(c,) for c in chunks])
            db.executemany("DELETE FROM p_chunks WHERE chunk_id = ?", [(c,) for c in chunks])
            self._sources_changed(db)
            db.execute("DELETE FROM p_meta WHERE key = ?", (f"source_error:{source_id}",))
            db.execute("INSERT OR REPLACE INTO p_meta VALUES (?, ?)", (f"source_pending:{source_id}", uuid.uuid4().hex))
        return len(chunks)

    # ------------------------------------------------------------ expressions

    def list_expressions(
        self,
        source_id: str | None = None,
        *,
        target_only: bool = False,
        until: dt.date | None = None,
    ) -> list[Expression]:
        """Expressions in source order. ``until`` keeps the dated ones up to that day (undated ones are kept only
        without ``until``)."""
        clauses: list[str] = []
        params: list[object] = []
        if source_id is not None:
            clauses.append("source_id = ?")
            params.append(source_id)
        if target_only:
            clauses.append("is_target = 1")
        if until is not None:
            clauses.append("date IS NOT NULL AND date <= ?")
            params.append(until.isoformat())
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._lock:
            rows = self._db.execute(f"SELECT json FROM p_expressions{where} ORDER BY source_id, idx", params).fetchall()
        return [Expression.model_validate_json(r[0]) for r in rows]

    def expression_counts(self) -> dict[str, tuple[int, int]]:
        """Per source: (expressions, expressions by the target person)."""
        with self._lock:
            rows = self._db.execute(
                "SELECT source_id, COUNT(*), SUM(is_target) FROM p_expressions GROUP BY source_id"
            ).fetchall()
        return {r[0]: (int(r[1]), int(r[2] or 0)) for r in rows}

    def expression_owners(self) -> dict[str, str]:
        with self._lock:
            rows = self._db.execute("SELECT expression_id, source_id FROM p_expressions").fetchall()
        return {r[0]: r[1] for r in rows}

    def pending_source_ids(self) -> set[str]:
        with self._lock:
            rows = self._db.execute("SELECT key FROM p_meta WHERE key LIKE 'source_pending:%'").fetchall()
        return {r[0].removeprefix("source_pending:") for r in rows}

    def get_expression(self, expression_id: str) -> Expression | None:
        with self._lock:
            row = self._db.execute(
                "SELECT json FROM p_expressions WHERE expression_id = ?", (expression_id,)
            ).fetchone()
        return Expression.model_validate_json(row[0]) if row else None

    # ------------------------------------------------------------ extraction

    def has_chunk(self, chunk_id: str) -> bool:
        with self._lock:
            return self._db.execute("SELECT 1 FROM p_chunks WHERE chunk_id = ?", (chunk_id,)).fetchone() is not None

    def put_chunk(
        self, chunk_id: str, source_id: str, candidates: list[PersonaCandidate], stats: ExtractStats | None = None
    ) -> None:
        """Record a processed chunk with its candidates (possibly none) and extraction counts, replacing an earlier
        run of it."""
        with self._tx() as db:
            db.execute("DELETE FROM p_candidates WHERE chunk_id = ?", (chunk_id,))
            db.execute(
                "INSERT OR REPLACE INTO p_chunks (chunk_id, source_id, stats) VALUES (?, ?, ?)",
                (chunk_id, source_id, stats.model_dump_json() if stats else None),
            )
            db.executemany(
                "INSERT INTO p_candidates VALUES (?, ?, ?, ?)",
                [(c.candidate_id, c.chunk_id, c.facet_id, c.model_dump_json()) for c in candidates],
            )

    def extraction_stats(self) -> dict[str, tuple[int, ExtractStats | None]]:
        """Per source: its chunks extracted, and their summed counts (None when none was counted, i.e. every chunk
        was extracted before counts were kept)."""
        with self._lock:
            rows = self._db.execute("SELECT source_id, stats FROM p_chunks").fetchall()
        result: dict[str, tuple[int, ExtractStats | None]] = {}
        for source_id, value in rows:
            chunks, total = result.get(source_id, (0, None))
            if value is not None:
                stats = ExtractStats.model_validate_json(value)
                total = stats if total is None else total + stats
            result[source_id] = (chunks + 1, total)
        return result

    def drop_stale_chunks(self, live: set[str]) -> int:
        """Forget chunks (and their candidates) that the current sources no longer produce."""
        with self._tx() as db:
            stale = [r[0] for r in db.execute("SELECT chunk_id FROM p_chunks") if r[0] not in live]
            db.executemany("DELETE FROM p_candidates WHERE chunk_id = ?", [(c,) for c in stale])
            db.executemany("DELETE FROM p_chunks WHERE chunk_id = ?", [(c,) for c in stale])
        return len(stale)

    def list_candidates(self, facet_id: str | None = None) -> list[PersonaCandidate]:
        sql = "SELECT json FROM p_candidates" + (" WHERE facet_id = ?" if facet_id else "") + " ORDER BY candidate_id"
        with self._lock:
            rows = self._db.execute(sql, (facet_id,) if facet_id else ()).fetchall()
        return [PersonaCandidate.model_validate_json(r[0]) for r in rows]

    # ------------------------------------------------------------ profile

    def replace_facet_items(self, facet_id: str, items: list[PersonaItem]) -> None:
        """Replace a facet's items, carrying the person's reviews over to the items that continue the reviewed ones
        (see ``carry_reviews``); reviews of items that disappear are dropped."""
        old = self.list_items(facet_id, raw=True)
        carried = carry_reviews(old, items, self.reviews())
        with self._tx() as db:
            db.executemany("DELETE FROM p_reviews WHERE item_id = ?", [(o.item_id,) for o in old])
            db.executemany(
                "INSERT OR REPLACE INTO p_reviews VALUES (?, ?)", [(i, r.model_dump_json()) for i, r in carried.items()]
            )
            db.execute("DELETE FROM p_items WHERE facet_id = ?", (facet_id,))
            db.executemany(
                "INSERT INTO p_items VALUES (?, ?, ?)",
                [(i.item_id, i.facet_id, i.model_dump_json()) for i in items],
            )

    def list_items(
        self, facet_id: str | None = None, *, include_rejected: bool = False, raw: bool = False
    ) -> list[PersonaItem]:
        """Items with the person's reviews applied (rejected ones left out unless asked for); ``raw`` returns them as
        extracted, without reviews."""
        sql = "SELECT json FROM p_items" + (" WHERE facet_id = ?" if facet_id else "") + " ORDER BY facet_id, item_id"
        with self._lock:
            rows = self._db.execute(sql, (facet_id,) if facet_id else ()).fetchall()
        items = [PersonaItem.model_validate_json(r[0]) for r in rows]
        if raw:
            return items
        reviews = self.reviews()
        reviewed = [apply_review(i, reviews.get(i.item_id)) for i in items]
        return [i for i in reviewed if include_rejected or i.review is not ReviewStatus.REJECTED]

    def query_items(
        self,
        *,
        facet_ids: list[str] | None = None,
        review: ReviewStatus | None = None,
        text: str = "",
        source_id: str | None = None,
        conflict: bool = False,
        by_evidence: bool = False,
        include_rejected: bool = False,
        limit: int | None = None,
        offset: int = 0,
    ) -> tuple[list[PersonaItem], int]:
        """One page of items with reviews applied, filtered in SQL, and the number of items matching the filters.
        ``text`` matches the statement as shown (the edited one after an edit) and the evidence quotes;
        ``source_id`` keeps items with evidence from that source; ``conflict`` keeps items whose evidence disagrees;
        ``by_evidence`` puts the best-supported first."""
        status = f"COALESCE(json_extract(r.json, '$.status'), '{ReviewStatus.UNREVIEWED.value}')"
        clauses: list[str] = []
        params: list[object] = []
        if facet_ids is not None:
            clauses.append(f"i.facet_id IN ({','.join('?' * len(facet_ids))})" if facet_ids else "0")
            params += facet_ids
        if review is not None:
            clauses.append(f"{status} = ?")
            params.append(review.value)
        elif not include_rejected:
            clauses.append(f"{status} != ?")
            params.append(ReviewStatus.REJECTED.value)
        if needle := text.strip().lower():
            clauses.append(
                f"(instr(lower(CASE WHEN {status} = ? AND json_extract(r.json, '$.statement') != ''"
                " THEN json_extract(r.json, '$.statement') ELSE json_extract(i.json, '$.statement') END), ?)"
                " OR EXISTS (SELECT 1 FROM json_each(i.json, '$.evidence') e"
                " WHERE instr(lower(json_extract(e.value, '$.quote')), ?)))"
            )
            params += [ReviewStatus.EDITED.value, needle, needle]
        if source_id is not None:
            clauses.append(
                "EXISTS (SELECT 1 FROM json_each(i.json, '$.evidence') e"
                " WHERE json_extract(e.value, '$.source_id') = ?)"
            )
            params.append(source_id)
        if conflict:
            clauses.append("COALESCE(json_extract(i.json, '$.conflict'), '') != ''")
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        order = "json_array_length(i.json, '$.evidence') DESC, i.item_id" if by_evidence else "i.facet_id, i.item_id"
        base = f"FROM p_items i LEFT JOIN p_reviews r ON r.item_id = i.item_id{where}"
        with self._lock:
            total = int(self._db.execute(f"SELECT COUNT(*) {base}", params).fetchone()[0])
            rows = self._db.execute(
                f"SELECT i.json, r.json {base} ORDER BY {order} LIMIT ? OFFSET ?",
                [*params, -1 if limit is None else limit, offset],
            ).fetchall()
        items = [
            apply_review(PersonaItem.model_validate_json(item), PReview.model_validate_json(review) if review else None)
            for item, review in rows
        ]
        return items, total

    def item_counts(self) -> dict[tuple[str, ReviewStatus], int]:
        """Item counts per facet and review status (rejected items included)."""
        with self._lock:
            rows = self._db.execute(
                f"SELECT i.facet_id, COALESCE(json_extract(r.json, '$.status'), '{ReviewStatus.UNREVIEWED.value}'), "
                "COUNT(*) FROM p_items i LEFT JOIN p_reviews r ON r.item_id = i.item_id GROUP BY 1, 2"
            ).fetchall()
        return {(facet, ReviewStatus(status)): int(n) for facet, status, n in rows}

    def has_items(self) -> bool:
        """Whether any item is left after rejections."""
        with self._lock:
            row = self._db.execute(
                "SELECT 1 FROM p_items i LEFT JOIN p_reviews r ON r.item_id = i.item_id "
                "WHERE COALESCE(json_extract(r.json, '$.status'), '') != ? LIMIT 1",
                (ReviewStatus.REJECTED.value,),
            ).fetchone()
        return row is not None

    def count_items(self) -> int:
        """Items left after rejections."""
        return sum(n for (_, status), n in self.item_counts().items() if status is not ReviewStatus.REJECTED)

    def get_items(self, item_ids: list[str]) -> dict[str, PersonaItem]:
        """The named items that exist, with reviews applied."""
        if not item_ids:
            return {}
        with self._lock:
            rows = self._db.execute(
                f"SELECT i.item_id, i.json, r.json FROM p_items i LEFT JOIN p_reviews r ON r.item_id = i.item_id "
                f"WHERE i.item_id IN ({','.join('?' * len(item_ids))})",
                item_ids,
            ).fetchall()
        return {
            item_id: apply_review(
                PersonaItem.model_validate_json(item), PReview.model_validate_json(review) if review else None
            )
            for item_id, item, review in rows
        }

    def item_support(self) -> list[tuple[str, str, str]]:
        """(item_id, facet_id, expression_id) for every evidence of every item left after rejections, read without
        decoding the items."""
        with self._lock:
            rows = self._db.execute(
                "SELECT i.item_id, i.facet_id, json_extract(e.value, '$.expression_id') "
                "FROM p_items i LEFT JOIN p_reviews r ON r.item_id = i.item_id, json_each(i.json, '$.evidence') e "
                "WHERE COALESCE(json_extract(r.json, '$.status'), '') != ?",
                (ReviewStatus.REJECTED.value,),
            ).fetchall()
        return [(r[0], r[1], r[2]) for r in rows]

    def get_item(self, item_id: str, *, raw: bool = False) -> PersonaItem | None:
        with self._lock:
            row = self._db.execute("SELECT json FROM p_items WHERE item_id = ?", (item_id,)).fetchone()
        if row is None:
            return None
        item = PersonaItem.model_validate_json(row[0])
        return item if raw else apply_review(item, self.reviews().get(item_id))

    # ------------------------------------------------------------ reviews

    def reviews(self) -> dict[str, PReview]:
        with self._lock:
            rows = self._db.execute("SELECT item_id, json FROM p_reviews").fetchall()
        return {r[0]: PReview.model_validate_json(r[1]) for r in rows}

    def set_review(self, item_id: str, review: PReview | None) -> None:
        """Record the person's review of an item, or clear it (back to unreviewed) with None."""
        with self._tx() as db:
            if db.execute("SELECT 1 FROM p_items WHERE item_id = ?", (item_id,)).fetchone() is None:
                raise KeyError(item_id)
            if review is None:
                db.execute("DELETE FROM p_reviews WHERE item_id = ?", (item_id,))
            else:
                db.execute("INSERT OR REPLACE INTO p_reviews VALUES (?, ?)", (item_id, review.model_dump_json()))

    def get_meta(self, key: str) -> str | None:
        with self._lock:
            row = self._db.execute("SELECT value FROM p_meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def set_meta(self, key: str, value: str) -> None:
        with self._tx() as db:
            db.execute("INSERT OR REPLACE INTO p_meta VALUES (?, ?)", (key, value))

    def delete_meta(self, key: str) -> None:
        with self._tx() as db:
            db.execute("DELETE FROM p_meta WHERE key = ?", (key,))

    def meta_with_prefix(self, prefix: str) -> dict[str, str]:
        """Every meta value whose key starts with ``prefix``, by the rest of the key."""
        with self._lock:
            rows = self._db.execute(
                "SELECT key, value FROM p_meta WHERE substr(key, 1, ?) = ?", (len(prefix), prefix)
            ).fetchall()
        return {key[len(prefix) :]: value for key, value in rows}

    def kernel_built(self) -> KernelVersion | None:
        value = self.get_meta("kernel:built")
        if value is None:
            return None
        data = json.loads(value)
        return KernelVersion(schema=int(data["schema"]), prompt=str(data["prompt"]), taxonomy=str(data["taxonomy"]))

    def mark_kernel_built(self, kernel: KernelVersion) -> None:
        self.set_meta("kernel:built", kernel_json(kernel))

    def mark_profile_built(self, built_at: str, sources_changed_at: str | None, kernel: KernelVersion = KERNEL) -> None:
        """Acknowledge a successful build only if its input version is still current."""
        with self._tx() as db:
            saved = db.execute(
                "INSERT OR REPLACE INTO p_meta SELECT 'built_at', ? "
                "WHERE (SELECT value FROM p_meta WHERE key = 'sources_changed_at') IS ?",
                (built_at, sources_changed_at),
            )
            if saved.rowcount:
                db.execute("DELETE FROM p_meta WHERE key LIKE 'source_pending:%'")
                db.execute("INSERT OR REPLACE INTO p_meta VALUES ('kernel:built', ?)", (kernel_json(kernel),))
                db.execute("DELETE FROM p_meta WHERE key = 'kernel_rebuild'")

    def pending_versions(self, source_ids: list[str]) -> dict[str, str]:
        with self._lock:
            rows = self._db.execute("SELECT key, value FROM p_meta WHERE key LIKE 'source_pending:%'").fetchall()
        pending = {key.removeprefix("source_pending:"): value for key, value in rows}
        return {source_id: pending[source_id] for source_id in source_ids if source_id in pending}

    def finish_build(
        self,
        built_at: str,
        sources_changed_at: str | None,
        settled: dict[str, str],
        *,
        complete: bool,
        kernel: KernelVersion = KERNEL,
    ) -> None:
        """Record a build whose merge succeeded. ``settled`` maps each source the build fully extracted to the pending
        value it read; a source changed since then keeps its newer pending value. ``complete`` means no chunk failed,
        which is required before the kernel counts as rebuilt."""
        with self._tx() as db:
            db.execute("INSERT OR REPLACE INTO p_meta VALUES ('built_at', ?)", (built_at,))
            db.executemany(
                "DELETE FROM p_meta WHERE key = ? AND value = ?",
                [(f"source_pending:{source_id}", value) for source_id, value in settled.items()],
            )
            current = db.execute("SELECT value FROM p_meta WHERE key = 'sources_changed_at'").fetchone()
            if complete and (current[0] if current else None) == sources_changed_at:
                db.execute("INSERT OR REPLACE INTO p_meta VALUES ('kernel:built', ?)", (kernel_json(kernel),))
                db.execute("DELETE FROM p_meta WHERE key = 'kernel_rebuild'")

    def set_build_progress(self, phase: str, totals: dict[str, int]) -> None:
        self.set_meta("build_progress", json.dumps({"phase": phase, "totals": totals}))

    def clear_build_progress(self) -> None:
        with self._tx() as db:
            db.execute("DELETE FROM p_meta WHERE key = 'build_progress'")

    def build_progress(self) -> tuple[str, dict[str, tuple[int, int]]] | None:
        """The running build's phase and, per source, (chunks extracted, chunks to extract)."""
        value = self.get_meta("build_progress")
        if not value:
            return None
        plan = json.loads(value)
        with self._lock:
            rows = self._db.execute("SELECT source_id, COUNT(*) FROM p_chunks GROUP BY source_id").fetchall()
        done = dict(rows)
        totals: dict[str, int] = plan["totals"]
        return plan["phase"], {sid: (min(done.get(sid, 0), total), total) for sid, total in totals.items()}

    def source_status(self, source_id: str, remembered: int) -> str:
        source = self.get_source(source_id)
        if source and source.media_status not in (None, "ready"):
            return source.media_status
        if self.get_meta(f"source_error:{source_id}"):
            return "failed"
        if self.get_meta("built_at") is None or self.get_meta(f"source_pending:{source_id}") is not None:
            return "processing"
        return "remembered" if remembered else "nothing_found"

    def source_statuses(self, sources: list[Source], remembered: dict[str, int]) -> dict[str, str]:
        """``source_status`` for many sources, reading the per-source markers in one query."""
        with self._lock:
            rows = self._db.execute(
                "SELECT key FROM p_meta "
                "WHERE (key LIKE 'source_error:%' AND value != '') OR key LIKE 'source_pending:%'"
            ).fetchall()
        keys = {r[0] for r in rows}
        built = self.get_meta("built_at") is not None
        statuses: dict[str, str] = {}
        for source in sources:
            sid = source.source_id
            if source.media_status not in (None, "ready"):
                statuses[sid] = source.media_status
            elif f"source_error:{sid}" in keys:
                statuses[sid] = "failed"
            elif not built or f"source_pending:{sid}" in keys:
                statuses[sid] = "processing"
            else:
                statuses[sid] = "remembered" if remembered.get(sid) else "nothing_found"
        return statuses

    def processing_result(
        self, source_ids: list[str], version: str | None, error: str | None, failed: list[str] | None = None
    ) -> None:
        """``error`` failed the whole build: it goes to every source in it, unless memories were added while it ran.
        ``failed`` names the sources with a chunk that failed; only they are marked, the rest were remembered."""
        failed = failed or []
        summary = error or (f"{len(failed)} 条记忆处理失败，可点重试" if failed else "")
        with self._tx() as db:
            db.execute(
                "INSERT OR REPLACE INTO p_meta VALUES ('processing_last_finished_at', ?)",
                (dt.datetime.now(dt.UTC).isoformat(),),
            )
            db.execute("INSERT OR REPLACE INTO p_meta VALUES ('processing_last_error', ?)", (summary,))
            marked = source_ids if error and self.get_meta("sources_changed_at") == version else failed
            db.executemany(
                "INSERT OR REPLACE INTO p_meta VALUES (?, ?)",
                [(f"source_error:{source_id}", error or "部分内容处理失败") for source_id in marked],
            )

    def clear_source_errors(self) -> None:
        with self._tx() as db:
            db.execute("DELETE FROM p_meta WHERE key LIKE 'source_error:%'")

    # ------------------------------------------------------------ vectors

    def vector_shas(self, namespace: str) -> dict[str, str]:
        with self._lock:
            rows = self._db.execute("SELECT ref_id, text_sha FROM p_vectors WHERE namespace = ?", (namespace,))
            return {r[0]: r[1] for r in rows}

    def update_vectors(
        self,
        namespace: str,
        embedder: str,
        upserts: list[tuple[str, str, Matrix]] | None = None,
        deletes: list[str] | None = None,
    ) -> None:
        """Apply ``(ref_id, text_sha, vector)`` upserts and deletes and record the embedding space; a different
        space than the recorded one must replace the whole namespace (``clear_vectors`` first)."""
        with self._tx() as db:
            known = db.execute("SELECT value FROM p_meta WHERE key = ?", (f"embedder:{namespace}",)).fetchone()
            count = db.execute("SELECT COUNT(*) FROM p_vectors WHERE namespace = ?", (namespace,)).fetchone()[0]
            if known and known[0] != embedder and count:
                raise ValueError(f"cannot mix embedding spaces in {namespace!r}")
            db.executemany(
                "DELETE FROM p_vectors WHERE namespace = ? AND ref_id = ?", [(namespace, r) for r in deletes or []]
            )
            db.executemany(
                "INSERT OR REPLACE INTO p_vectors VALUES (?, ?, ?, ?)",
                [(namespace, r, sha, np.asarray(v, dtype=np.float32).tobytes()) for r, sha, v in upserts or []],
            )
            db.execute("INSERT OR REPLACE INTO p_meta VALUES (?, ?)", (f"embedder:{namespace}", embedder))

    def clear_vectors(self, namespace: str) -> None:
        with self._tx() as db:
            db.execute("DELETE FROM p_vectors WHERE namespace = ?", (namespace,))
            db.execute("DELETE FROM p_meta WHERE key = ?", (f"embedder:{namespace}",))

    def get_vectors(self, namespace: str) -> tuple[list[str], Matrix]:
        with self._lock:
            rows = self._db.execute(
                "SELECT ref_id, vec FROM p_vectors WHERE namespace = ? ORDER BY ref_id", (namespace,)
            ).fetchall()
        if not rows:
            return [], np.zeros((0, 0), dtype=np.float32)
        return [r[0] for r in rows], np.stack([np.frombuffer(r[1], dtype=np.float32) for r in rows])

    def create_conversation(
        self, owner: str | None, turns: list[dict[str, Any]] | None = None, migration_id: str | None = None
    ) -> str:
        conversation_id = migration_id or str(uuid.uuid4())
        now = dt.datetime.now(dt.UTC).isoformat()
        with self._tx() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM conversations WHERE id = ?", (conversation_id,)).fetchone():
                self.get_conversation(conversation_id, owner)
                return conversation_id
            created_at = turns[0].get("timestamp", now) if turns else now
            db.execute(
                "INSERT INTO conversations VALUES (?, ?, ?, ?, ?)", (conversation_id, owner, "新对话", created_at, now)
            )
            for turn in turns or []:
                self.append_conversation_turn(
                    conversation_id, owner, turn["role"], turn["content"], turn.get("reply"), turn.get("timestamp")
                )
            if turns:
                db.execute(
                    "UPDATE conversations SET updated_at = ? WHERE id = ?",
                    (turns[-1].get("timestamp", now), conversation_id),
                )
        return conversation_id

    def list_conversations(self, owner: str | None, offset: int = 0) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT c.id, c.title, c.updated_at, "
                "(SELECT COUNT(*) FROM conversation_turns WHERE conversation_id = c.id), "
                "(SELECT content FROM conversation_turns WHERE conversation_id = c.id ORDER BY seq DESC LIMIT 1) "
                "FROM conversations c WHERE owner IS ? ORDER BY updated_at DESC, id DESC LIMIT 50 OFFSET ?",
                (owner, offset),
            ).fetchall()
        return [
            {"id": r[0], "title": r[1], "updated_at": r[2], "turns": r[3], "preview": (r[4] or "")[:120]} for r in rows
        ]

    def get_conversation(self, conversation_id: str, owner: str | None) -> dict[str, Any]:
        with self._lock:
            row = self._db.execute(
                "SELECT title FROM conversations WHERE id = ? AND owner IS ?", (conversation_id, owner)
            ).fetchone()
            if row is None:
                raise KeyError(conversation_id)
            turns = self._db.execute(
                "SELECT seq, role, content, reply_json, created_at FROM conversation_turns "
                "WHERE conversation_id = ? ORDER BY seq",
                (conversation_id,),
            ).fetchall()
        return {
            "id": conversation_id,
            "title": row[0],
            "turns": [
                {
                    "id": f"{conversation_id}:{r[0]}",
                    "role": r[1],
                    "content": r[2],
                    "timestamp": r[4],
                    **({"reply": json.loads(r[3])} if r[3] else {}),
                }
                for r in turns
            ],
        }

    def append_conversation_turn(
        self,
        conversation_id: str,
        owner: str | None,
        role: str,
        content: str,
        reply: dict[str, Any] | None = None,
        timestamp: str | None = None,
    ) -> None:
        now = dt.datetime.now(dt.UTC).isoformat()
        with self._tx() as db:
            if not db.in_transaction:
                db.execute("BEGIN IMMEDIATE")
            if not db.execute(
                "SELECT 1 FROM conversations WHERE id = ? AND owner IS ?", (conversation_id, owner)
            ).fetchone():
                raise KeyError(conversation_id)
            seq = db.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 FROM conversation_turns WHERE conversation_id = ?", (conversation_id,)
            ).fetchone()[0]
            first_user = (
                role == "user"
                and not db.execute(
                    "SELECT 1 FROM conversation_turns WHERE conversation_id = ? AND role = 'user'", (conversation_id,)
                ).fetchone()
            )
            db.execute(
                "INSERT INTO conversation_turns VALUES (?, ?, ?, ?, ?, ?)",
                (
                    conversation_id,
                    seq,
                    role,
                    content,
                    json.dumps(reply, ensure_ascii=False) if reply else None,
                    timestamp or now,
                ),
            )
            db.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (now, conversation_id))
            if first_user:
                db.execute("UPDATE conversations SET title = ? WHERE id = ?", (content.strip()[:24], conversation_id))

    def rename_conversation(self, conversation_id: str, owner: str | None, title: str) -> bool:
        with self._tx() as db:
            return (
                db.execute(
                    "UPDATE conversations SET title = ? WHERE id = ? AND owner IS ?", (title, conversation_id, owner)
                ).rowcount
                > 0
            )

    def delete_conversation(self, conversation_id: str, owner: str | None) -> bool:
        with self._tx() as db:
            return (
                db.execute("DELETE FROM conversations WHERE id = ? AND owner IS ?", (conversation_id, owner)).rowcount
                > 0
            )

    # ------------------------------------------------------------ chat log (what people ask, where the twin abstains)

    def log_chat(self, question: str, reply: ChatReply, previous: str = "") -> None:
        """Log one answered question; ``previous`` is the asker's turn before it, for a follow-up like 「那他呢？」."""
        entry = {
            "question": question[:2000],
            "previous": previous[:500],
            "reason": reply.abstain_reason[:500],
            "abstain": reply.abstain,
            "mode": reply.mode,
            "confidence": reply.confidence,
            "topic_facets": reply.topic_facets,
            "as_of": reply.as_of.isoformat() if reply.as_of else None,
        }
        with self._tx() as db:
            db.execute(
                "INSERT INTO p_chat_log (at, abstain, json) VALUES (?, ?, ?)",
                (
                    dt.datetime.now().isoformat(timespec="seconds"),
                    int(reply.abstain),
                    json.dumps(entry, ensure_ascii=False),
                ),
            )

    def chat_abstentions(self) -> list[tuple[str, dict[str, Any]]]:
        """``(asked at, logged entry)`` of every question the twin abstained on, oldest first."""
        with self._lock:
            rows = self._db.execute("SELECT at, json FROM p_chat_log WHERE abstain = 1 ORDER BY id").fetchall()
        return [(at, json.loads(raw)) for at, raw in rows]

    def chat_demand(self) -> dict[str, tuple[int, int]]:
        """Per facet: how many logged questions touched it and how many of those it abstained on or could only infer."""
        with self._lock:
            rows = self._db.execute("SELECT abstain, json FROM p_chat_log").fetchall()
        demand: dict[str, list[int]] = {}
        for abstain, raw in rows:
            entry = json.loads(raw)
            if entry.get("mode") == "general":
                continue
            for facet in entry.get("topic_facets", []):
                counts = demand.setdefault(facet, [0, 0])
                counts[0] += 1
                counts[1] += int(abstain or entry.get("mode") == "inferred")
        return {f: (asked, abstained) for f, (asked, abstained) in demand.items()}
