"""The team's own database (``data/team/team.db``): what connects people and belongs to none of them.

A person's memories stay in their twin's database, the recordings and the people heard in them in the recording
library. This holds what is between two people: for now the index of conversations (who asked whose twin, and which
tier of memory it answers from), later handoffs and shared answers. It copies no memory and no conversation text, and
the index can be rebuilt from the twins' databases (``rebuild_conversations``), so a conversation's text is always
the twin's.

Like a twin's database it migrates by appending to ``_MIGRATIONS`` only, snapshots itself before a migration, refuses
to open when written by a newer twin, and lives in an owner-only directory in WAL mode.

Handoffs are here too: when a twin's answer leaves something only the person can settle (a decision, a promise, a
judgement of a colleague, an answer the profile does not hold), one handoff per asker and conversation records what was
asked and where it stands, in seven states plus the moment the person's reply is being written back. The person's
reply reaches the asker's conversation in three steps (``begin_reply``, a ``self`` turn in the twin's database that
names the handoff and is written once, ``finish_reply``), so one that stopped halfway is finished at startup.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
import sqlite3
import threading
import uuid
from collections.abc import Collection, Iterable, Iterator, Mapping, Sequence
from contextlib import closing, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .persona.tiers import COLLEAGUE, SELF, Audience
from .util import prepare_private_file

logger = logging.getLogger(__name__)

Via = Literal["direct", "delegate"]
# What a handoff asks of the person: decide something, take on a promise, judge a colleague, answer what the profile
# does not hold, or (``inferred``) put right an answer the twin guessed.
HandoffKind = Literal["decide", "commit", "evaluate", "missing", "inferred"]
# The seven states an asker is told (已送达 已回复 已接受 已拒绝 不答 已过期 已撤回), and ``writing``: the person's
# reply is kept and is being written into the asker's conversation.
HandoffStatus = Literal["delivered", "writing", "replied", "accepted", "declined", "dismissed", "expired", "withdrawn"]
Outcome = Literal["replied", "accepted", "declined"]
# ``none``: the reply is not kept as a memory; ``colleague``: kept, its items taking their facets' tiers (``tiers``);
# ``self``: kept as the person's own only (chosen where a memory is written down, not yet in handoffs).
ReplyTier = Literal["none", "colleague", "self"]
HANDOFF_DAYS = 7
# A handoff that has not been settled and whose conversation is deleted is withdrawn.
UNSETTLED: tuple[HandoffStatus, ...] = ("delivered", "writing", "dismissed", "expired")

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
    # 2: handoffs, and the person's verdicts on answers the twin guessed; the name an asker is shown by.
    """
    ALTER TABLE conversations ADD COLUMN asker_name TEXT NOT NULL DEFAULT '';
    CREATE TABLE handoffs (
        id TEXT PRIMARY KEY,
        persona_id TEXT NOT NULL,
        owner TEXT,
        conversation_id TEXT,
        turn INTEGER,
        asker TEXT,
        asker_name TEXT NOT NULL DEFAULT '',
        via TEXT NOT NULL DEFAULT 'direct' CHECK (via IN ('direct', 'delegate')),
        kind TEXT NOT NULL CHECK (kind IN ('decide', 'commit', 'evaluate', 'missing', 'inferred')),
        question TEXT NOT NULL,
        context TEXT NOT NULL DEFAULT '',
        ask TEXT NOT NULL DEFAULT '',
        commit_what TEXT NOT NULL DEFAULT '',
        commit_due TEXT,
        status TEXT NOT NULL CHECK (status IN
            ('delivered', 'writing', 'replied', 'accepted', 'declined', 'dismissed', 'expired', 'withdrawn')),
        outcome TEXT CHECK (outcome IN ('replied', 'accepted', 'declined')),
        reply TEXT,
        reply_tier TEXT CHECK (reply_tier IN ('none', 'colleague', 'self')),
        reply_turn INTEGER,
        ledger_id TEXT,
        group_key TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        replied_at TEXT);
    CREATE UNIQUE INDEX handoffs_turn ON handoffs(conversation_id, turn) WHERE conversation_id IS NOT NULL;
    CREATE INDEX handoffs_persona ON handoffs(persona_id, status, expires_at);
    CREATE INDEX handoffs_conversation ON handoffs(conversation_id);
    CREATE TABLE answer_checks (
        conversation_id TEXT NOT NULL,
        turn INTEGER NOT NULL,
        verdict TEXT NOT NULL CHECK (verdict IN ('right', 'corrected')),
        handoff_id TEXT,
        checked_at TEXT NOT NULL,
        PRIMARY KEY (conversation_id, turn));
    """,
)

SNAPSHOT_DIR = "snapshots"
SNAPSHOT_KEEP = 3
# ``meta`` keys.
RECONCILED_AT = "conversations:reconciled_at"
INDEXED_LEGACY = "conversations:legacy_indexed"


class NewerTeamError(RuntimeError):
    pass


class HandoffUnavailable(RuntimeError):
    """The handoff is not in a state the change needs (already answered, withdrawn, written back by another request)."""

    def __init__(self, handoff_id: str, status: HandoffStatus | None) -> None:
        super().__init__(f"handoff {handoff_id} is {status or 'unknown'}")
        self.handoff_id, self.status = handoff_id, status


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
    asker_name: str = ""


@dataclass(frozen=True)
class Handoff:
    id: str
    persona_id: str
    owner: str | None
    # None for a question from before handoffs (the old 待你回答): its source is unknown, so it can be kept as a memory
    # but not written back.
    conversation_id: str | None
    turn: int | None
    asker: str | None
    asker_name: str
    via: Via
    kind: HandoffKind
    question: str
    context: str
    ask: str
    commit_what: str
    commit_due: str | None
    status: HandoffStatus
    outcome: Outcome | None
    reply: str | None
    reply_tier: ReplyTier | None
    reply_turn: int | None
    ledger_id: str | None
    group_key: str
    created_at: str
    expires_at: str
    replied_at: str | None

    @property
    def source_known(self) -> bool:
        return self.conversation_id is not None


_HANDOFF_COLUMNS = (
    "id, persona_id, owner, conversation_id, turn, asker, asker_name, via, kind, question, context, ask, "
    "commit_what, commit_due, status, outcome, reply, reply_tier, reply_turn, ledger_id, group_key, created_at, "
    "expires_at, replied_at"
)


def _handoff(row: Sequence[object]) -> Handoff:
    return Handoff(*row)  # type: ignore[arg-type]


def _stamp(now: dt.datetime | None = None) -> str:
    return (now or dt.datetime.now(dt.UTC)).isoformat()


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
        asker_name: str = "",
    ) -> None:
        """Index a conversation once, with the tier it answers from; a conversation already indexed keeps the tier it
        was created with, whatever is asked now. ``asker_name``: what the person is called where they are shown."""
        with self._tx() as db:
            db.execute(
                "INSERT INTO conversations "
                "(id, persona_id, asker, audience, via, delegation_id, title, updated_at, asker_name) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET title = excluded.title, updated_at = excluded.updated_at, "
                "deleted_at = NULL",
                (conversation_id, persona_id, asker, audience, via, delegation_id, title, updated_at, asker_name),
            )

    def refresh_conversation(self, conversation_id: str, title: str, updated_at: str) -> None:
        with self._tx() as db:
            db.execute(
                "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?", (title, updated_at, conversation_id)
            )

    def delete_conversation(self, conversation_id: str) -> None:
        """Mark a conversation deleted, and withdraw the handoffs in it that nobody has settled."""
        with self._tx() as db:
            db.execute(
                "UPDATE conversations SET deleted_at = ? WHERE id = ? AND deleted_at IS NULL",
                (dt.datetime.now(dt.UTC).isoformat(), conversation_id),
            )
            self._withdraw(db, conversation_id)

    @staticmethod
    def _withdraw(db: sqlite3.Connection, conversation_id: str) -> int:
        marks = ",".join("?" * len(UNSETTLED))
        return db.execute(
            f"UPDATE handoffs SET status = 'withdrawn' WHERE conversation_id = ? AND status IN ({marks})",
            (conversation_id, *UNSETTLED),
        ).rowcount

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
                r["asker_name"],
            )
            for r in rows
        ]

    def forget_persona(self, persona_id: str) -> None:
        """Drop everything indexed for a twin that is gone for good."""
        with self._tx() as db:
            db.execute(
                "DELETE FROM answer_checks WHERE conversation_id IN "
                "(SELECT id FROM conversations WHERE persona_id = ?)",
                (persona_id,),
            )
            db.execute("DELETE FROM handoffs WHERE persona_id = ?", (persona_id,))
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
            for _, conversation_id in gone:
                self._withdraw(db, conversation_id)
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
                    r[0]: (r[1], r[2], r[3], r[4])
                    for r in db.execute(
                        "SELECT id, audience, via, delegation_id, asker_name FROM conversations WHERE persona_id = ?",
                        (persona_id,),
                    )
                }
                removed += db.execute("DELETE FROM conversations WHERE persona_id = ?", (persona_id,)).rowcount
                for conversation_id, asker, title, updated_at in rows:
                    audience, via, delegation_id, name = kept.get(conversation_id, (COLLEAGUE, "direct", None, ""))
                    db.execute(
                        "INSERT INTO conversations (id, persona_id, asker, audience, via, delegation_id, title, "
                        "updated_at, asker_name) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (conversation_id, persona_id, asker, audience, via, delegation_id, title, updated_at, name),
                    )
                    added += 1
        self.set_meta(RECONCILED_AT, dt.datetime.now(dt.UTC).isoformat())
        return Reconciled(added=added, removed=removed)

    # ------------------------------------------------------------ handoffs

    def create_handoff(
        self,
        *,
        persona_id: str,
        owner: str | None,
        conversation_id: str | None,
        turn: int | None,
        asker: str | None,
        asker_name: str,
        kind: HandoffKind,
        question: str,
        context: str = "",
        ask: str = "",
        commit_what: str = "",
        commit_due: str | None = None,
        group_key: str = "",
        via: Via = "direct",
        handoff_id: str | None = None,
        status: HandoffStatus = "delivered",
        created_at: str | None = None,
        expires_at: str | None = None,
    ) -> Handoff | None:
        """Record one handoff, or None when it is already recorded: one per asker and conversation turn, and not a
        second while the same question is still waiting in the same conversation (the asker sending it again)."""
        now = dt.datetime.now(dt.UTC)
        created = created_at or _stamp(now)
        expires = expires_at or _stamp(now + dt.timedelta(days=HANDOFF_DAYS))
        new_id = handoff_id or uuid.uuid4().hex[:16]
        with self._tx() as db:
            if conversation_id is not None:
                if (
                    turn is not None
                    and db.execute(
                        "SELECT 1 FROM handoffs WHERE conversation_id = ? AND turn = ?", (conversation_id, turn)
                    ).fetchone()
                ):
                    return None
                if (
                    group_key
                    and db.execute(
                        "SELECT 1 FROM handoffs WHERE conversation_id = ? AND group_key = ? "
                        "AND status IN ('delivered', 'writing')",
                        (conversation_id, group_key),
                    ).fetchone()
                ):
                    return None
            inserted = db.execute(
                f"INSERT OR IGNORE INTO handoffs ({_HANDOFF_COLUMNS}) VALUES ({','.join('?' * 24)})",
                (
                    new_id,
                    persona_id,
                    owner,
                    conversation_id,
                    turn,
                    asker,
                    asker_name,
                    via,
                    kind,
                    question,
                    context,
                    ask,
                    commit_what,
                    commit_due,
                    status,
                    None,
                    None,
                    None,
                    None,
                    None,
                    group_key,
                    created,
                    expires,
                    None,
                ),
            ).rowcount
        return self.get_handoff(new_id) if inserted else None

    def get_handoff(self, handoff_id: str) -> Handoff | None:
        with self._lock:
            row = self._db.execute(f"SELECT {_HANDOFF_COLUMNS} FROM handoffs WHERE id = ?", (handoff_id,)).fetchone()
        return None if row is None else _handoff(row)

    def handoffs(
        self,
        *,
        persona_id: str | None = None,
        statuses: Collection[str] | None = None,
        conversation_id: str | None = None,
        personas: Collection[str] | None = None,
    ) -> list[Handoff]:
        """Handoffs, the soonest to expire first among those waiting and the newest first otherwise. ``personas``
        limits them to those twins (the ones not in the trash)."""
        where: list[str] = []
        params: list[object] = []
        if persona_id is not None:
            where.append("persona_id = ?")
            params.append(persona_id)
        if conversation_id is not None:
            where.append("conversation_id = ?")
            params.append(conversation_id)
        if statuses is not None:
            where.append(f"status IN ({','.join('?' * len(statuses))})" if statuses else "0")
            params.extend(statuses)
        if personas is not None:
            where.append(f"persona_id IN ({','.join('?' * len(personas))})" if personas else "0")
            params.extend(personas)
        sql = f"SELECT {_HANDOFF_COLUMNS} FROM handoffs" + (f" WHERE {' AND '.join(where)}" if where else "")
        with self._lock:
            rows = self._db.execute(sql + " ORDER BY created_at DESC, id", params).fetchall()
        found = [_handoff(r) for r in rows]
        waiting = sorted((h for h in found if h.status == "delivered"), key=lambda h: (h.expires_at, h.id))
        return waiting + [h for h in found if h.status != "delivered"]

    def count_handoffs(self, persona_id: str, status: HandoffStatus = "delivered") -> int:
        with self._lock:
            row = self._db.execute(
                "SELECT COUNT(*) FROM handoffs WHERE persona_id = ? AND status = ?", (persona_id, status)
            ).fetchone()
        return int(row[0])

    def expire_due(self, now: dt.datetime | None = None) -> int:
        """Mark the handoffs nobody answered in time as expired; the person can still answer or put them back."""
        with self._tx() as db:
            return db.execute(
                "UPDATE handoffs SET status = 'expired' WHERE status = 'delivered' AND expires_at <= ?", (_stamp(now),)
            ).rowcount

    def begin_reply(
        self, handoff_id: str, text: str, tier: ReplyTier, outcome: Outcome = "replied", now: dt.datetime | None = None
    ) -> Handoff:
        """Step one of a reply: keep it and mark the handoff as being written back. Only one reply wins: the handoff
        must be waiting, put aside or expired, and whichever request moves it first takes it; the others get
        ``HandoffUnavailable`` with the state it is in."""
        with self._tx() as db:
            moved = db.execute(
                "UPDATE handoffs SET status = 'writing', reply = ?, reply_tier = ?, outcome = ?, replied_at = ? "
                "WHERE id = ? AND status IN ('delivered', 'dismissed', 'expired')",
                (text, tier, outcome, _stamp(now), handoff_id),
            ).rowcount
        found = self.get_handoff(handoff_id)
        if not moved or found is None:
            raise HandoffUnavailable(handoff_id, found.status if found else None)
        return found

    def finish_reply(self, handoff_id: str, reply_turn: int | None) -> bool:
        """Step three: the reply stands in the conversation (at ``reply_turn``, None for a question whose source is
        unknown); the handoff takes the outcome it was given. False when it is no longer being written back (it was
        withdrawn meanwhile, or another pass finished it)."""
        with self._tx() as db:
            return (
                db.execute(
                    "UPDATE handoffs SET status = COALESCE(outcome, 'replied'), reply_turn = ? "
                    "WHERE id = ? AND status = 'writing'",
                    (reply_turn, handoff_id),
                ).rowcount
                > 0
            )

    def writing(self, persona_id: str | None = None) -> list[Handoff]:
        """The handoffs whose reply was kept and not yet written back, for finishing them after a stop."""
        return self.handoffs(persona_id=persona_id, statuses=("writing",))

    def set_handoff_status(
        self, handoff_id: str, status: HandoffStatus, allowed: Collection[str], *, renew: bool = False
    ) -> Handoff:
        """Move a handoff to ``status`` if it is in one of ``allowed``; ``renew`` gives it a new week to wait."""
        marks = ",".join("?" * len(allowed))
        renewal = ", expires_at = ?" if renew else ""
        extra = (_stamp(dt.datetime.now(dt.UTC) + dt.timedelta(days=HANDOFF_DAYS)),) if renew else ()
        with self._tx() as db:
            moved = db.execute(
                f"UPDATE handoffs SET status = ?{renewal} WHERE id = ? AND status IN ({marks})",
                (status, *extra, handoff_id, *allowed),
            ).rowcount
        found = self.get_handoff(handoff_id)
        if not moved or found is None:
            raise HandoffUnavailable(handoff_id, found.status if found else None)
        return found

    def set_handoff_ledger(self, handoff_id: str, ledger_id: str) -> None:
        with self._tx() as db:
            db.execute("UPDATE handoffs SET ledger_id = ? WHERE id = ?", (ledger_id, handoff_id))

    def withdraw_conversation(self, conversation_id: str) -> int:
        """Withdraw the handoffs of a conversation that nobody has settled; how many."""
        with self._tx() as db:
            return self._withdraw(db, conversation_id)

    # ------------------------------------------------------------ verdicts on guessed answers

    def check_answer(
        self, conversation_id: str, turn: int, verdict: Literal["right", "corrected"], handoff_id: str | None = None
    ) -> None:
        with self._tx() as db:
            db.execute(
                "INSERT OR REPLACE INTO answer_checks VALUES (?, ?, ?, ?, ?)",
                (conversation_id, turn, verdict, handoff_id, _stamp()),
            )

    def checked_answers(self, conversation_ids: Collection[str]) -> set[tuple[str, int]]:
        """``(conversation, turn)`` of the answers the person has looked at, of these conversations."""
        found: set[tuple[str, int]] = set()
        ids = list(conversation_ids)
        for start in range(0, len(ids), 400):
            batch = ids[start : start + 400]
            with self._lock:
                rows = self._db.execute(
                    "SELECT conversation_id, turn FROM answer_checks "
                    f"WHERE conversation_id IN ({','.join('?' * len(batch))})",
                    batch,
                ).fetchall()
            found.update((r[0], int(r[1])) for r in rows)
        return found
