"""Persistence of the general persona core: sources and their expressions, extraction candidates and the profile.

The tables live in ``settings.db_path`` under a ``p_`` prefix.
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import numpy as np

from ..embed import Matrix
from ..util import prepare_private_file
from .items import PersonaCandidate, PersonaItem, PReview, apply_review, carry_reviews
from .schema import ChatReply, Expression, ParsedSource, ReviewStatus, Source, SourceKind

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
CREATE TABLE IF NOT EXISTS p_vectors (
    namespace TEXT NOT NULL, ref_id TEXT NOT NULL, text_sha TEXT NOT NULL, vec BLOB NOT NULL,
    PRIMARY KEY (namespace, ref_id));
"""


def stored_identity(path: Path) -> tuple[str | None, str]:
    if not path.is_file():
        return None, ""
    with PersonaStore(path) as store:
        return store.get_meta("identity:name") or None, store.get_meta("identity:about") or ""


class PersonaStore:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        if str(path) not in ("", ":memory:"):
            prepare_private_file(self.path)
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(_SCHEMA)
        self._lock = threading.RLock()

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
            db.execute("INSERT OR REPLACE INTO p_meta VALUES (?, '1')", (f"source_pending:{source.source_id}",))
        return existed is None

    def list_sources(self, kind: SourceKind | None = None) -> list[Source]:
        with self._lock:
            rows = self._db.execute("SELECT json FROM p_sources ORDER BY first_date, source_id").fetchall()
        sources = [Source.model_validate_json(r[0]) for r in rows]
        return [source for source in sources if kind is None or source.kind is kind]

    def get_source(self, source_id: str) -> Source | None:
        with self._lock:
            row = self._db.execute("SELECT json FROM p_sources WHERE source_id = ?", (source_id,)).fetchone()
        return Source.model_validate_json(row[0]) if row else None

    def delete_source(self, source_id: str) -> bool:
        """Remove a source, its expressions and the candidates extracted from it (the profile is rebuilt from the
        remaining candidates on the next build)."""
        with self._tx() as db:
            chunks = [r[0] for r in db.execute("SELECT chunk_id FROM p_chunks WHERE source_id = ?", (source_id,))]
            db.executemany("DELETE FROM p_candidates WHERE chunk_id = ?", [(c,) for c in chunks])
            db.execute("DELETE FROM p_chunks WHERE source_id = ?", (source_id,))
            db.execute("DELETE FROM p_expressions WHERE source_id = ?", (source_id,))
            deleted = db.execute("DELETE FROM p_sources WHERE source_id = ?", (source_id,)).rowcount > 0
            if deleted:
                self._sources_changed(db)
                db.execute("DELETE FROM p_meta WHERE key = ?", (f"source_pending:{source_id}",))
            return deleted

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

    def put_chunk(self, chunk_id: str, source_id: str, candidates: list[PersonaCandidate]) -> None:
        """Record a processed chunk with its candidates (possibly none), replacing an earlier run of it."""
        with self._tx() as db:
            db.execute("DELETE FROM p_candidates WHERE chunk_id = ?", (chunk_id,))
            db.execute("INSERT OR REPLACE INTO p_chunks VALUES (?, ?)", (chunk_id, source_id))
            db.executemany(
                "INSERT INTO p_candidates VALUES (?, ?, ?, ?)",
                [(c.candidate_id, c.chunk_id, c.facet_id, c.model_dump_json()) for c in candidates],
            )

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
        """Replace a facet's items, carrying the person's reviews over to the items that still contain the reviewed
        ones' candidates; reviews of items that disappear are dropped."""
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

    def mark_profile_built(self, built_at: str, sources_changed_at: str | None) -> None:
        """Acknowledge a successful build only if its input version is still current."""
        with self._tx() as db:
            saved = db.execute(
                "INSERT OR REPLACE INTO p_meta SELECT 'built_at', ? "
                "WHERE (SELECT value FROM p_meta WHERE key = 'sources_changed_at') IS ?",
                (built_at, sources_changed_at),
            )
            if saved.rowcount:
                db.execute("DELETE FROM p_meta WHERE key LIKE 'source_pending:%'")

    def source_status(self, source_id: str, remembered: int) -> str:
        if self.get_meta(f"source_error:{source_id}"):
            return "failed"
        if self.get_meta("built_at") is None or self.get_meta(f"source_pending:{source_id}") is not None:
            return "processing"
        return "remembered" if remembered else "nothing_found"

    def processing_result(self, source_ids: list[str], version: str | None, error: str | None) -> None:
        """Do not assign an old build's failure to memories added while it ran."""
        with self._tx() as db:
            db.execute(
                "INSERT OR REPLACE INTO p_meta VALUES ('processing_last_finished_at', ?)",
                (dt.datetime.now(dt.UTC).isoformat(),),
            )
            db.execute("INSERT OR REPLACE INTO p_meta VALUES ('processing_last_error', ?)", (error or "",))
            if self.get_meta("sources_changed_at") == version:
                for source_id in source_ids:
                    db.execute(
                        "INSERT OR REPLACE INTO p_meta VALUES (?, ?)", (f"source_error:{source_id}", error or "")
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

    # ------------------------------------------------------------ chat log (what people ask, where the twin abstains)

    def log_chat(self, question: str, reply: ChatReply) -> None:
        entry = {
            "question": question[:2000],
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

    def chat_demand(self) -> dict[str, tuple[int, int]]:
        """Per facet: how many logged questions touched it and how many of those the twin abstained on."""
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
                counts[1] += int(abstain)
        return {f: (asked, abstained) for f, (asked, abstained) in demand.items()}
