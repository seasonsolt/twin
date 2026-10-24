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

The organisation's layer is here as well: team answers (what a person confirmed once, for every twin to quote as it
stands, with the vector that finds them by meaning), the cache of how well each twin knows each facet (for finding
who knows about a matter), delegations (the person's assistant asking colleagues' twins in their name, one hop
from the person, which ``create_delegation`` and ``record_conversation`` check as they write) and lenses (a person
lending their judgement, with what each use was: the question and what was said, never who asked).
"""

from __future__ import annotations

import datetime as dt
import json
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
# A team answer: in force, possibly out of date (the person said something different since), or taken back.
AnswerStatus = Literal["valid", "stale", "withdrawn"]
# How many colleagues' twins one delegation asks, at most.
MAX_DELEGATES = 3
# A lens is in force, held for the moment by the person, or taken back for good.
LensStatus = Literal["active", "paused", "withdrawn"]
# ``conversations(asked_by=...)`` left out: everyone's (None is a real value there, the asker of a service without
# sign-in).
_ANYONE = object()
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
    # 3: team answers, and the vectors that find them by meaning.
    """
    CREATE TABLE team_answers (
        id TEXT PRIMARY KEY,
        persona_id TEXT NOT NULL,
        owner TEXT,
        title TEXT NOT NULL,
        body TEXT NOT NULL,
        handoff_id TEXT,
        item_id TEXT,
        source_id TEXT,
        status TEXT NOT NULL CHECK (status IN ('valid', 'stale', 'withdrawn')),
        stale_note TEXT NOT NULL DEFAULT '',
        judged TEXT NOT NULL DEFAULT '',
        confirmed_at TEXT NOT NULL,
        withdrawn_at TEXT);
    CREATE INDEX team_answers_persona ON team_answers(persona_id, status);
    CREATE UNIQUE INDEX team_answers_handoff ON team_answers(handoff_id)
        WHERE handoff_id IS NOT NULL AND status != 'withdrawn';
    CREATE TABLE team_answer_vectors (
        answer_id TEXT PRIMARY KEY REFERENCES team_answers(id) ON DELETE CASCADE,
        model TEXT NOT NULL,
        vector BLOB NOT NULL);
    """,
    # 4: how well each twin knows each facet, as colleagues may use its memories (a cache; deleting it loses nothing).
    """
    CREATE TABLE facet_coverage (
        persona_id TEXT NOT NULL,
        facet_id TEXT NOT NULL,
        level INTEGER NOT NULL,
        occasions INTEGER NOT NULL,
        last_seen TEXT,
        kernel TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (persona_id, facet_id));
    """,
    # 5: delegations, the person's assistant asking colleagues' twins in their name.
    """
    CREATE TABLE delegations (
        id TEXT PRIMARY KEY,
        initiator TEXT NOT NULL,
        persona_id TEXT NOT NULL,
        conversation_id TEXT NOT NULL,
        question TEXT NOT NULL,
        created_at TEXT NOT NULL);
    CREATE INDEX delegations_conversation ON delegations(conversation_id);
    """,
    # 6: lenses, a person lending their judgement to colleagues, and what each lens was used for. A use holds the
    # question and what the lens said and nothing of who asked: no asker, no conversation, no handoff.
    """
    CREATE TABLE lenses (
        id TEXT PRIMARY KEY,
        persona_id TEXT NOT NULL,
        name TEXT NOT NULL,
        facets TEXT NOT NULL,
        audience TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('active', 'paused', 'withdrawn')),
        forgiven TEXT NOT NULL DEFAULT '{}',
        published_at TEXT NOT NULL,
        ended_at TEXT);
    CREATE INDEX lenses_persona ON lenses(persona_id, status);
    CREATE TABLE lens_uses (
        id TEXT PRIMARY KEY,
        lens_id TEXT NOT NULL REFERENCES lenses(id) ON DELETE CASCADE,
        question TEXT NOT NULL,
        said TEXT NOT NULL,
        facets TEXT NOT NULL,
        corrected INTEGER NOT NULL DEFAULT 0,
        at TEXT NOT NULL);
    CREATE INDEX lens_uses_lens ON lens_uses(lens_id, at);
    """,
)

SNAPSHOT_DIR = "snapshots"
SNAPSHOT_KEEP = 3
# ``meta`` keys.
COVERAGE_SIGNATURE = "coverage:signature:"
RECONCILED_AT = "conversations:reconciled_at"
INDEXED_LEGACY = "conversations:legacy_indexed"


class NewerTeamError(RuntimeError):
    pass


class DelegationRefused(RuntimeError):
    """A write that would take delegation beyond one hop from the person (or past its limits); the message says why."""


class LensUnavailable(RuntimeError):
    """The lens is not in a state the change needs (taken back, or not in force for a use)."""

    def __init__(self, lens_id: str, status: LensStatus | None) -> None:
        super().__init__(f"lens {lens_id} is {status or 'unknown'}")
        self.lens_id, self.status = lens_id, status


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


@dataclass(frozen=True)
class TeamAnswer:
    """What a person confirmed once, for every twin to quote as it stands."""

    id: str
    persona_id: str
    owner: str | None
    title: str
    body: str
    handoff_id: str | None
    item_id: str | None
    source_id: str | None
    status: AnswerStatus
    stale_note: str
    # What the last check of "has the person said otherwise since" looked at, so that it is not judged again.
    judged: str
    confirmed_at: str
    withdrawn_at: str | None


_ANSWER_COLUMNS = (
    "id, persona_id, owner, title, body, handoff_id, item_id, source_id, status, stale_note, judged, confirmed_at, "
    "withdrawn_at"
)


@dataclass(frozen=True)
class CoverageRow:
    """How well one twin knows one facet, from the memories colleagues may use."""

    persona_id: str
    facet_id: str
    level: int
    occasions: int
    last_seen: str | None
    kernel: str
    updated_at: str


@dataclass(frozen=True)
class Delegation:
    """The person's assistant asking colleagues' twins in their name: asked from the person's own conversation with
    their assistant (``conversation_id``, of the twin ``persona_id``)."""

    id: str
    initiator: str
    persona_id: str
    conversation_id: str
    question: str
    created_at: str


@dataclass(frozen=True)
class Lens:
    """The judgement a person lends: the facets they opened, and to whom. ``audience`` is JSON (``lenses``);
    ``forgiven`` counts, per facet, the corrections that were put right when the facet was opened again."""

    id: str
    persona_id: str
    name: str
    facets: tuple[str, ...]
    audience: str
    status: LensStatus
    forgiven: dict[str, int]
    published_at: str
    ended_at: str | None


@dataclass(frozen=True)
class LensUse:
    """What a lens was asked and said. Nothing of who asked, and nothing that leads to the conversation or the handoff
    the question was in: the person sees what their judgement was used for, never by whom."""

    id: str
    lens_id: str
    question: str
    said: str
    facets: tuple[str, ...]
    corrected: bool
    at: str


_LENS_COLUMNS = "id, persona_id, name, facets, audience, status, forgiven, published_at, ended_at"
_LENS_USE_COLUMNS = "id, lens_id, question, said, facets, corrected, at"


def _lens(row: Sequence[object]) -> Lens:
    return Lens(
        str(row[0]),
        str(row[1]),
        str(row[2]),
        tuple(json.loads(str(row[3]))),
        str(row[4]),
        row[5],  # type: ignore[arg-type]
        {str(k): int(v) for k, v in json.loads(str(row[6])).items()},
        str(row[7]),
        None if row[8] is None else str(row[8]),
    )


def _lens_use(row: Sequence[object]) -> LensUse:
    return LensUse(
        str(row[0]), str(row[1]), str(row[2]), str(row[3]), tuple(json.loads(str(row[4]))), bool(row[5]), str(row[6])
    )


_HANDOFF_COLUMNS = (
    "id, persona_id, owner, conversation_id, turn, asker, asker_name, via, kind, question, context, ask, "
    "commit_what, commit_due, status, outcome, reply, reply_tier, reply_turn, ledger_id, group_key, created_at, "
    "expires_at, replied_at"
)


def _handoff(row: Sequence[object]) -> Handoff:
    return Handoff(*row)  # type: ignore[arg-type]


def _like(prefix: str) -> str:
    return prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


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

    def delete_meta(self, key: str) -> None:
        with self._tx() as db:
            db.execute("DELETE FROM meta WHERE key = ?", (key,))

    def meta_keys(self, prefix: str) -> set[str]:
        """The keys of the records that start with ``prefix``."""
        with self._lock:
            rows = self._db.execute(
                "SELECT key FROM meta WHERE key LIKE ? ESCAPE '\\'", (_like(prefix) + "%",)
            ).fetchall()
        return {r[0] for r in rows}

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
        was created with, whatever is asked now. ``asker_name``: what the person is called where they are shown.

        A conversation asked in the person's name by their assistant (``via="delegate"``) is checked as it is written:
        it must belong to a delegation, answer from the colleague tier, be the delegation's person's own, be a twin
        other than the person's, and be at most ``MAX_DELEGATES`` of the delegation's. Only a conversation the person
        has with their assistant themself can start a delegation (``create_delegation``), so a twin that was asked by
        an assistant never asks another: one hop, held here and not left to the prompts.

        A conversation id is indexed under one twin only. An id another twin's conversation already holds (a twin's
        database copied from another's, or an id a client chose) is left as it is and not indexed for this twin:
        neither renamed, brought back from deleted nor given another tier."""
        with self._tx() as db:
            if self._taken(db, conversation_id, persona_id):
                return
            self._check_delegate(db, conversation_id, persona_id, asker, audience, via, delegation_id)
            db.execute(
                "INSERT INTO conversations "
                "(id, persona_id, asker, audience, via, delegation_id, title, updated_at, asker_name) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET title = excluded.title, updated_at = excluded.updated_at, "
                "deleted_at = NULL WHERE conversations.persona_id = excluded.persona_id",
                (conversation_id, persona_id, asker, audience, via, delegation_id, title, updated_at, asker_name),
            )

    @staticmethod
    def _taken(db: sqlite3.Connection, conversation_id: str, persona_id: str) -> bool:
        """Whether another twin's conversation holds this id in the index (logged: it is not indexed for this one)."""
        row = db.execute("SELECT persona_id FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
        if row is None or row[0] == persona_id:
            return False
        logger.warning(
            "conversation %s of twin %s is not indexed: twin %s's conversation has the same id",
            conversation_id,
            persona_id,
            row[0],
        )
        return True

    @staticmethod
    def _check_delegate(
        db: sqlite3.Connection,
        conversation_id: str,
        persona_id: str,
        asker: str | None,
        audience: Audience,
        via: Via,
        delegation_id: str | None,
    ) -> None:
        if via != "delegate":
            if delegation_id is not None:
                raise DelegationRefused("不是代问的对话，不能属于某次代问")
            return
        row = (
            db.execute("SELECT initiator, persona_id FROM delegations WHERE id = ?", (delegation_id,)).fetchone()
            if delegation_id
            else None
        )
        if row is None:
            raise DelegationRefused("代问的对话要属于一次代问")
        if audience != COLLEAGUE:
            raise DelegationRefused("代问只按同事能用的记忆回答")
        if asker != row[0]:
            raise DelegationRefused("代问的对话归发起代问的人")
        if persona_id == row[1]:
            raise DelegationRefused("不能代问自己的分身")
        if not db.execute("SELECT 1 FROM conversations WHERE id = ?", (conversation_id,)).fetchone() and (
            db.execute(
                "SELECT COUNT(*) FROM conversations WHERE delegation_id = ? AND deleted_at IS NULL", (delegation_id,)
            ).fetchone()[0]
            >= MAX_DELEGATES
        ):
            raise DelegationRefused(f"一次最多问 {MAX_DELEGATES} 位同事")

    def refresh_conversation(
        self, conversation_id: str, title: str, updated_at: str, *, persona_id: str | None = None
    ) -> None:
        """``persona_id``: only when the conversation is that twin's."""
        with self._tx() as db:
            db.execute(
                "UPDATE conversations SET title = ?, updated_at = ? "
                "WHERE id = ? AND persona_id = COALESCE(?, persona_id)",
                (title, updated_at, conversation_id, persona_id),
            )

    def delete_conversation(self, conversation_id: str, *, persona_id: str | None = None) -> None:
        """Mark a conversation deleted, and withdraw the handoffs in it that nobody has settled. ``persona_id``: only
        when the conversation is that twin's, and only that twin's handoffs; left out, the twin the index has it
        under."""
        with self._tx() as db:
            if persona_id is None:
                row = db.execute("SELECT persona_id FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
                persona_id = None if row is None else str(row[0])
            db.execute(
                "UPDATE conversations SET deleted_at = ? WHERE id = ? AND persona_id = COALESCE(?, persona_id) "
                "AND deleted_at IS NULL",
                (dt.datetime.now(dt.UTC).isoformat(), conversation_id, persona_id),
            )
            self._withdraw(db, conversation_id, persona_id)

    @staticmethod
    def _withdraw(db: sqlite3.Connection, conversation_id: str, persona_id: str | None) -> int:
        """Withdraw the unsettled handoffs of one twin's conversation (of any twin's with that id when None: a
        conversation the index does not have)."""
        marks = ",".join("?" * len(UNSETTLED))
        return db.execute(
            "UPDATE handoffs SET status = 'withdrawn' "
            f"WHERE conversation_id = ? AND persona_id = COALESCE(?, persona_id) AND status IN ({marks})",
            (conversation_id, persona_id, *UNSETTLED),
        ).rowcount

    def audience_of(self, conversation_id: str, *, persona_id: str | None = None) -> Audience | None:
        """The tier a conversation answers from; None when it is not indexed (``persona_id``: for that twin)."""
        with self._lock:
            row = self._db.execute(
                "SELECT audience FROM conversations WHERE id = ? AND persona_id = COALESCE(?, persona_id)",
                (conversation_id, persona_id),
            ).fetchone()
        return None if row is None else (SELF if row[0] == SELF else COLLEAGUE)

    def conversations(
        self,
        *,
        persona_id: str | None = None,
        asker: str | None = None,
        personas: Collection[str] | None = None,
        include_deleted: bool = False,
        asked_by: object = _ANYONE,
        self_tier_of: Collection[str] | None = None,
        not_self_tier_of: Collection[str] | None = None,
        delegation_id: str | None = None,
        via: Via | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[IndexedConversation]:
        """Indexed conversations, newest first. ``personas`` limits them to those twins (the ones not in the trash).
        ``asked_by`` limits them to one person's own, where None is the one without an account (no sign-in); leave it
        out for everyone's. ``self_tier_of``: only those of the self tier with one of these twins (the person's own
        with their assistant); ``not_self_tier_of``: all but those. ``delegation_id``: only those one delegation
        asked; ``via``: only those asked directly, or only those the person's assistant asked in their name.
        ``limit`` and ``offset`` page the list."""
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
        if asked_by is not _ANYONE:
            where.append("asker IS ?")
            params.append(asked_by)
        if self_tier_of is not None:
            where.append(
                f"(audience = 'self' AND persona_id IN ({','.join('?' * len(self_tier_of))}))" if self_tier_of else "0"
            )
            params.extend(self_tier_of)
        if not_self_tier_of:
            where.append(f"NOT (audience = 'self' AND persona_id IN ({','.join('?' * len(not_self_tier_of))}))")
            params.extend(not_self_tier_of)
        if delegation_id is not None:
            where.append("delegation_id = ?")
            params.append(delegation_id)
        if via is not None:
            where.append("via = ?")
            params.append(via)
        sql = "SELECT * FROM conversations" + (f" WHERE {' AND '.join(where)}" if where else "")
        # What one delegation asked is in the order it was asked; anything else, the newest first.
        sql += " ORDER BY rowid" if delegation_id is not None else " ORDER BY updated_at DESC, id"
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            params += [limit, offset]
        with self._lock:
            self._db.row_factory = sqlite3.Row
            try:
                rows = self._db.execute(sql, params).fetchall()
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
        """Drop everything indexed for a twin that is gone for good (its purge from the trash: nothing of it is kept).
        Other twins' conversations stay; those its person's assistant asked in their name no longer belong to a
        delegation, as the delegation goes."""
        with self._tx() as db:
            db.execute(
                "DELETE FROM answer_checks WHERE conversation_id IN "
                "(SELECT id FROM conversations WHERE persona_id = ?)",
                (persona_id,),
            )
            db.execute("DELETE FROM handoffs WHERE persona_id = ?", (persona_id,))
            # What the person confirmed goes with them, words and all (what to do when someone leaves and their answers
            # should stay is left for later). Conversations that showed one keep their copy of the card; a card whose
            # answer is gone is shown as it was.
            db.execute(
                "DELETE FROM team_answer_vectors WHERE answer_id IN (SELECT id FROM team_answers WHERE persona_id = ?)",
                (persona_id,),
            )
            db.execute("DELETE FROM team_answers WHERE persona_id = ?", (persona_id,))
            db.execute("DELETE FROM facet_coverage WHERE persona_id = ?", (persona_id,))
            db.execute("DELETE FROM meta WHERE key = ?", (f"{COVERAGE_SIGNATURE}{persona_id}",))
            # Colleagues' twins' conversations its delegations asked are theirs and stay, still marked as asked by the
            # assistant, but point at no delegation that no longer exists.
            db.execute(
                "UPDATE conversations SET delegation_id = NULL WHERE persona_id != ? AND delegation_id IN "
                "(SELECT id FROM delegations WHERE persona_id = ?)",
                (persona_id, persona_id),
            )
            db.execute("DELETE FROM delegations WHERE persona_id = ?", (persona_id,))
            db.execute("DELETE FROM lenses WHERE persona_id = ?", (persona_id,))
            db.execute("DELETE FROM conversations WHERE persona_id = ?", (persona_id,))

    def reconcile_persona(self, persona_id: str, rows: Iterable[tuple[str, str | None, str, str]]) -> Reconciled:
        """Bring the index of one twin in line with the conversations in its database (``rows``: id, asker, title,
        updated at): add the ones it lacks, as the colleague tier, which is what a conversation from before the
        index was; refresh titles and times; mark the ones that are gone as deleted. Conversations the twin's
        database does not have are the index's to forget, never the other way round. One whose id another twin's
        conversation holds in the index is left out (and logged), never taken from it."""
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
                    if self._taken(db, conversation_id, persona_id):
                        continue
                    db.execute(
                        "INSERT INTO conversations (id, persona_id, asker, audience, via, title, updated_at) "
                        "VALUES (?, ?, ?, 'colleague', 'direct', ?, ?)",
                        (conversation_id, persona_id, asker, title, updated_at),
                    )
                    added += 1
                elif current != (title, updated_at, None):
                    db.execute(
                        "UPDATE conversations SET title = ?, updated_at = ?, deleted_at = NULL "
                        "WHERE id = ? AND persona_id = ?",
                        (title, updated_at, conversation_id, persona_id),
                    )
                    updated += 1
            gone = [
                (dt.datetime.now(dt.UTC).isoformat(), i, persona_id)
                for i, v in known.items()
                if i not in wanted and not v[2]
            ]
            db.executemany("UPDATE conversations SET deleted_at = ? WHERE id = ? AND persona_id = ?", gone)
            for _, conversation_id, _ in gone:
                self._withdraw(db, conversation_id, persona_id)
            removed = len(gone)
            stamp = dt.datetime.now(dt.UTC).isoformat()
            db.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (RECONCILED_AT, stamp))
            db.execute("INSERT OR IGNORE INTO meta VALUES (?, ?)", (INDEXED_LEGACY, stamp))
        return Reconciled(added, updated, removed)

    def rebuild_conversations(self, by_persona: Mapping[str, Sequence[tuple[str, str | None, str, str]]]) -> Reconciled:
        """Index the conversations of these twins again from their databases (``by_persona``: id, asker, title,
        updated at), dropping what the index held for them. The tier a conversation answers from is not in the
        twin's database, so a conversation the index already knew keeps it and the others are the colleague tier. An
        id another twin's conversation holds in the index stays that twin's (logged, not counted)."""
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
                indexed = set()
                for conversation_id, asker, title, updated_at in rows:
                    if self._taken(db, conversation_id, persona_id):
                        continue
                    indexed.add(conversation_id)
                    audience, via, delegation_id, name = kept.get(conversation_id, (COLLEAGUE, "direct", None, ""))
                    db.execute(
                        "INSERT INTO conversations (id, persona_id, asker, audience, via, delegation_id, title, "
                        "updated_at, asker_name) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (conversation_id, persona_id, asker, audience, via, delegation_id, title, updated_at, name),
                    )
                    added += 1
                # What the twin no longer has is no longer asked about: its handoffs wait for no one (as in reconcile).
                for conversation_id in kept.keys() - indexed:
                    self._withdraw(db, conversation_id, persona_id)
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
                # What a delegate conversation hands on is the person's to start (``via="delegate"``, from the card
                # they pressed), never a twin's own doing; and nothing but such a conversation is handed on as one.
                kind_of = db.execute(
                    "SELECT via, asker FROM conversations WHERE id = ? AND persona_id = ?",
                    (conversation_id, persona_id),
                ).fetchone()
                if (kind_of is not None and (kind_of[0] == "delegate") != (via == "delegate")) or (
                    kind_of is None and via == "delegate"
                ):
                    raise DelegationRefused("代问的对话只能由发起人点“转给本人”才转交")
                if via == "delegate" and kind_of is not None and kind_of[1] != asker:
                    raise DelegationRefused("代问的转交以发起人的名义")
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

    def handoff_states(self, conversation_ids: Collection[str]) -> dict[str, HandoffStatus]:
        """Where what a conversation's answers left to the person stands, for the conversations that have such a thing:
        the newest handoff of each (the person's verdicts on guessed answers are not handed anything on)."""
        found: dict[str, HandoffStatus] = {}
        ids = list(conversation_ids)
        for start in range(0, len(ids), 400):
            batch = ids[start : start + 400]
            with self._lock:
                rows = self._db.execute(
                    "SELECT conversation_id, status FROM handoffs WHERE kind != 'inferred' "
                    f"AND conversation_id IN ({','.join('?' * len(batch))}) ORDER BY created_at, id",
                    batch,
                ).fetchall()
            found.update((r[0], r[1]) for r in rows)
        return found

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

    def withdraw_conversation(self, conversation_id: str, *, persona_id: str | None = None) -> int:
        """Withdraw the handoffs of a conversation that nobody has settled (``persona_id``: only that twin's); how
        many."""
        with self._tx() as db:
            return self._withdraw(db, conversation_id, persona_id)

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

    # ------------------------------------------------------------ team answers

    def create_team_answer(
        self,
        *,
        persona_id: str,
        owner: str | None,
        title: str,
        body: str,
        handoff_id: str | None = None,
        source_id: str | None = None,
        item_id: str | None = None,
        answer_id: str | None = None,
        now: dt.datetime | None = None,
    ) -> TeamAnswer | None:
        """Keep what a person confirmed as a team answer, in force from now. None when the handoff it comes from is
        already a team answer that stands (one handoff, one answer)."""
        new_id = answer_id or uuid.uuid4().hex[:16]
        with self._tx() as db:
            added = db.execute(
                f"INSERT OR IGNORE INTO team_answers ({_ANSWER_COLUMNS}) VALUES ({','.join('?' * 13)})",
                (
                    new_id,
                    persona_id,
                    owner,
                    title,
                    body,
                    handoff_id,
                    item_id,
                    source_id,
                    "valid",
                    "",
                    "",
                    _stamp(now),
                    None,
                ),
            ).rowcount
        return self.get_team_answer(new_id) if added else None

    def get_team_answer(self, answer_id: str) -> TeamAnswer | None:
        with self._lock:
            row = self._db.execute(f"SELECT {_ANSWER_COLUMNS} FROM team_answers WHERE id = ?", (answer_id,)).fetchone()
        return None if row is None else TeamAnswer(*row)

    def team_answers(
        self,
        *,
        persona_id: str | None = None,
        statuses: Collection[str] | None = None,
        personas: Collection[str] | None = None,
    ) -> list[TeamAnswer]:
        """Team answers, the newest confirmed first. ``personas`` limits them to those twins (the ones not in the
        trash)."""
        where: list[str] = []
        params: list[object] = []
        if persona_id is not None:
            where.append("persona_id = ?")
            params.append(persona_id)
        if statuses is not None:
            where.append(f"status IN ({','.join('?' * len(statuses))})" if statuses else "0")
            params.extend(statuses)
        if personas is not None:
            where.append(f"persona_id IN ({','.join('?' * len(personas))})" if personas else "0")
            params.extend(personas)
        sql = f"SELECT {_ANSWER_COLUMNS} FROM team_answers" + (f" WHERE {' AND '.join(where)}" if where else "")
        with self._lock:
            rows = self._db.execute(sql + " ORDER BY confirmed_at DESC, id", params).fetchall()
        return [TeamAnswer(*r) for r in rows]

    def answered_handoffs(self, persona_id: str) -> set[str]:
        """Ids of the handoffs of a twin that are a team answer that stands."""
        with self._lock:
            rows = self._db.execute(
                "SELECT handoff_id FROM team_answers WHERE persona_id = ? AND handoff_id IS NOT NULL "
                "AND status != 'withdrawn'",
                (persona_id,),
            ).fetchall()
        return {r[0] for r in rows}

    def revise_team_answer(self, answer_id: str, title: str, body: str, now: dt.datetime | None = None) -> TeamAnswer:
        """The person put the answer right: it stands again from now, whatever doubt there was (a withdrawn one cannot
        be revised). Its vector was made from the old words, so it goes with them and the answer is embedded again."""
        with self._tx() as db:
            moved = db.execute(
                "UPDATE team_answers SET title = ?, body = ?, status = 'valid', stale_note = '', judged = '', "
                "confirmed_at = ? WHERE id = ? AND status != 'withdrawn'",
                (title, body, _stamp(now), answer_id),
            ).rowcount
            if moved:
                db.execute("DELETE FROM team_answer_vectors WHERE answer_id = ?", (answer_id,))
        found = self.get_team_answer(answer_id)
        if not moved or found is None:
            raise KeyError(answer_id)
        return found

    def mark_team_answer_stale(self, answer_id: str, note: str, judged: str) -> bool:
        """The person said something else since: the answer is shown as possibly out of date, with what they said."""
        with self._tx() as db:
            return (
                db.execute(
                    "UPDATE team_answers SET status = 'stale', stale_note = ?, judged = ? "
                    "WHERE id = ? AND status != 'withdrawn'",
                    (note, judged, answer_id),
                ).rowcount
                > 0
            )

    def keep_team_answer(self, answer_id: str, judged: str) -> TeamAnswer:
        """仍然有效: the person looked at what they said since and the answer stands; those sayings are not raised
        again."""
        with self._tx() as db:
            moved = db.execute(
                "UPDATE team_answers SET status = 'valid', stale_note = '', judged = ? "
                "WHERE id = ? AND status != 'withdrawn'",
                (judged, answer_id),
            ).rowcount
        found = self.get_team_answer(answer_id)
        if not moved or found is None:
            raise KeyError(answer_id)
        return found

    def set_team_answer_judged(self, answer_id: str, judged: str) -> None:
        with self._tx() as db:
            db.execute("UPDATE team_answers SET judged = ? WHERE id = ?", (judged, answer_id))

    def withdraw_team_answer(self, answer_id: str, now: dt.datetime | None = None) -> TeamAnswer:
        """Take the answer back: it is no longer quoted. Conversations it already appeared in are not touched."""
        with self._tx() as db:
            moved = db.execute(
                "UPDATE team_answers SET status = 'withdrawn', withdrawn_at = ? WHERE id = ? AND status != 'withdrawn'",
                (_stamp(now), answer_id),
            ).rowcount
            db.execute("DELETE FROM team_answer_vectors WHERE answer_id = ?", (answer_id,))
        found = self.get_team_answer(answer_id)
        if found is None or not moved:
            raise KeyError(answer_id)
        return found

    def put_answer_vector(self, answer_id: str, model: str, vector: bytes) -> None:
        with self._tx() as db:
            if db.execute("SELECT 1 FROM team_answers WHERE id = ? AND status != 'withdrawn'", (answer_id,)).fetchone():
                db.execute("INSERT OR REPLACE INTO team_answer_vectors VALUES (?, ?, ?)", (answer_id, model, vector))

    def answer_vectors(self, statuses: Collection[str] = ("valid", "stale")) -> dict[str, tuple[str, bytes]]:
        """``answer id -> (model, vector)`` of the team answers in these states that have one."""
        with self._lock:
            rows = self._db.execute(
                "SELECT v.answer_id, v.model, v.vector FROM team_answer_vectors v JOIN team_answers a "
                f"ON a.id = v.answer_id WHERE a.status IN ({','.join('?' * len(statuses))})",
                tuple(statuses),
            ).fetchall()
        return {r[0]: (r[1], bytes(r[2])) for r in rows}

    # ------------------------------------------------------------ how well each twin knows each facet

    def replace_coverage(self, persona_id: str, rows: Iterable[CoverageRow]) -> None:
        """Keep these as the twin's coverage, in place of what was cached for it."""
        with self._tx() as db:
            db.execute("DELETE FROM facet_coverage WHERE persona_id = ?", (persona_id,))
            db.executemany(
                "INSERT INTO facet_coverage VALUES (?, ?, ?, ?, ?, ?, ?)",
                [(r.persona_id, r.facet_id, r.level, r.occasions, r.last_seen, r.kernel, r.updated_at) for r in rows],
            )

    def coverage(self, personas: Collection[str] | None = None) -> list[CoverageRow]:
        where, params = "", []
        if personas is not None:
            where = f" WHERE persona_id IN ({','.join('?' * len(personas))})" if personas else " WHERE 0"
            params = list(personas)
        with self._lock:
            rows = self._db.execute("SELECT * FROM facet_coverage" + where, params).fetchall()
        return [CoverageRow(*r) for r in rows]

    def coverage_state(self) -> dict[str, tuple[str, str]]:
        """``persona -> (kernel, updated at)`` of the twins that have a cached coverage."""
        with self._lock:
            rows = self._db.execute(
                "SELECT persona_id, MIN(kernel), MIN(updated_at) FROM facet_coverage GROUP BY persona_id"
            ).fetchall()
        return {r[0]: (r[1], r[2]) for r in rows}

    def forget_coverage(self, persona_id: str | None = None) -> None:
        """Drop the cached coverage (of one twin, or all), with the marks of what it was made from: the next question
        makes it again."""
        with self._tx() as db:
            if persona_id is None:
                db.execute("DELETE FROM facet_coverage")
                db.execute("DELETE FROM meta WHERE key LIKE ?", (f"{COVERAGE_SIGNATURE}%",))
            else:
                db.execute("DELETE FROM facet_coverage WHERE persona_id = ?", (persona_id,))
                db.execute("DELETE FROM meta WHERE key = ?", (f"{COVERAGE_SIGNATURE}{persona_id}",))

    # ------------------------------------------------------------ delegations

    def create_delegation(
        self,
        *,
        initiator: str,
        persona_id: str,
        conversation_id: str,
        question: str,
        delegation_id: str | None = None,
    ) -> Delegation:
        """Record that the person's assistant asks colleagues' twins in their name, from the person's own conversation
        with their assistant. Refused unless that conversation is the person's own, of the self tier, asked directly:
        a conversation that was itself asked by an assistant (``via="delegate"``), or any colleague's, cannot start
        another, which is what keeps delegation to one hop."""
        new_id = delegation_id or uuid.uuid4().hex[:16]
        with self._tx() as db:
            row = db.execute(
                "SELECT persona_id, asker, audience, via, deleted_at FROM conversations WHERE id = ?",
                (conversation_id,),
            ).fetchone()
            if row is None or row[4] is not None:
                raise DelegationRefused("找不到这段对话")
            if row[0] != persona_id or row[1] != initiator or row[2] != SELF or row[3] != "direct":
                raise DelegationRefused("只有本人和自己的分身的对话可以发起代问")
            db.execute(
                "INSERT INTO delegations VALUES (?, ?, ?, ?, ?, ?)",
                (new_id, initiator, persona_id, conversation_id, question, _stamp()),
            )
        found = self.get_delegation(new_id)
        assert found is not None
        return found

    def get_delegation(self, delegation_id: str) -> Delegation | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM delegations WHERE id = ?", (delegation_id,)).fetchone()
        return None if row is None else Delegation(*row)

    def delegation_counts(self, conversation_ids: Collection[str]) -> dict[str, int]:
        """How many colleagues' twins each of these conversations (the person's own with their assistant) asked."""
        found: dict[str, int] = {}
        ids = list(conversation_ids)
        for start in range(0, len(ids), 400):
            batch = ids[start : start + 400]
            with self._lock:
                rows = self._db.execute(
                    "SELECT d.conversation_id, COUNT(c.id) FROM delegations d JOIN conversations c "
                    "ON c.delegation_id = d.id AND c.deleted_at IS NULL "
                    f"WHERE d.conversation_id IN ({','.join('?' * len(batch))}) GROUP BY d.conversation_id",
                    batch,
                ).fetchall()
            found.update((r[0], int(r[1])) for r in rows)
        return found

    # ------------------------------------------------------------ lenses

    def create_lens(
        self,
        *,
        persona_id: str,
        name: str,
        facets: Sequence[str],
        audience: str,
        lens_id: str | None = None,
        now: dt.datetime | None = None,
    ) -> Lens:
        """Publish a lens, in force from now."""
        new_id = lens_id or uuid.uuid4().hex[:16]
        with self._tx() as db:
            db.execute(
                f"INSERT INTO lenses ({_LENS_COLUMNS}) VALUES (?, ?, ?, ?, ?, 'active', '{{}}', ?, NULL)",
                (new_id, persona_id, name, json.dumps(list(facets)), audience, _stamp(now)),
            )
        found = self.get_lens(new_id)
        assert found is not None
        return found

    def get_lens(self, lens_id: str) -> Lens | None:
        with self._lock:
            row = self._db.execute(f"SELECT {_LENS_COLUMNS} FROM lenses WHERE id = ?", (lens_id,)).fetchone()
        return None if row is None else _lens(row)

    def lenses(self, *, persona_id: str | None = None, statuses: Collection[str] | None = None) -> list[Lens]:
        """Lenses, the newest published first; of one twin, in some states."""
        where: list[str] = []
        params: list[object] = []
        if persona_id is not None:
            where.append("persona_id = ?")
            params.append(persona_id)
        if statuses is not None:
            where.append(f"status IN ({','.join('?' * len(statuses))})")
            params.extend(statuses)
        sql = f"SELECT {_LENS_COLUMNS} FROM lenses" + (f" WHERE {' AND '.join(where)}" if where else "")
        with self._lock:
            rows = self._db.execute(sql + " ORDER BY published_at DESC, id", params).fetchall()
        return [_lens(r) for r in rows]

    def update_lens(
        self,
        lens_id: str,
        *,
        name: str | None = None,
        facets: Sequence[str] | None = None,
        audience: str | None = None,
        forgiven: dict[str, int] | None = None,
    ) -> Lens:
        """Change a lens that has not been taken back: its name, the facets it opens, to whom, and which corrections
        no longer count."""
        with self._tx() as db:
            row = db.execute("SELECT status FROM lenses WHERE id = ?", (lens_id,)).fetchone()
            if row is None or row[0] == "withdrawn":
                raise LensUnavailable(lens_id, None if row is None else row[0])
            changes: dict[str, object] = {}
            if name is not None:
                changes["name"] = name
            if facets is not None:
                changes["facets"] = json.dumps(list(facets))
            if audience is not None:
                changes["audience"] = audience
            if forgiven is not None:
                changes["forgiven"] = json.dumps(forgiven)
            if changes:
                db.execute(
                    f"UPDATE lenses SET {', '.join(f'{k} = ?' for k in changes)} WHERE id = ?",
                    (*changes.values(), lens_id),
                )
        found = self.get_lens(lens_id)
        assert found is not None
        return found

    def set_lens_status(self, lens_id: str, status: LensStatus, now: dt.datetime | None = None) -> Lens:
        """Hold a lens (``paused``), put it back in force (``active``) or take it back for good (``withdrawn``, from
        which there is no way back: a new lens is published instead). Withdrawing twice, or holding one that was
        taken back, is refused."""
        with self._tx() as db:
            row = db.execute("SELECT status FROM lenses WHERE id = ?", (lens_id,)).fetchone()
            if row is None or row[0] == "withdrawn":
                raise LensUnavailable(lens_id, None if row is None else row[0])
            db.execute(
                "UPDATE lenses SET status = ?, ended_at = ? WHERE id = ?",
                (status, _stamp(now) if status == "withdrawn" else None, lens_id),
            )
        found = self.get_lens(lens_id)
        assert found is not None
        return found

    def record_lens_use(
        self, lens_id: str, question: str, said: str, facets: Sequence[str], today: dt.date | None = None
    ) -> LensUse:
        """Keep what a lens was asked and said, on the day it was (the hour is not kept). Refused unless the lens is
        in force at this moment, which is what makes a held or taken-back lens stop at once."""
        use_id = uuid.uuid4().hex[:16]
        with self._tx() as db:
            row = db.execute("SELECT status FROM lenses WHERE id = ?", (lens_id,)).fetchone()
            if row is None or row[0] != "active":
                raise LensUnavailable(lens_id, None if row is None else row[0])
            db.execute(
                f"INSERT INTO lens_uses ({_LENS_USE_COLUMNS}) VALUES (?, ?, ?, ?, ?, 0, ?)",
                (
                    use_id,
                    lens_id,
                    question,
                    said,
                    json.dumps(list(facets)),
                    (today or dt.datetime.now(dt.UTC).date()).isoformat(),
                ),
            )
        found = self.get_lens_use(use_id)
        assert found is not None
        return found

    def get_lens_use(self, use_id: str) -> LensUse | None:
        with self._lock:
            row = self._db.execute(f"SELECT {_LENS_USE_COLUMNS} FROM lens_uses WHERE id = ?", (use_id,)).fetchone()
        return None if row is None else _lens_use(row)

    def lens_uses(self, lens_id: str, *, limit: int = 50, facet: str | None = None) -> list[LensUse]:
        """The uses of a lens, newest first; those that touched one facet."""
        with self._lock:
            rows = self._db.execute(
                f"SELECT {_LENS_USE_COLUMNS} FROM lens_uses WHERE lens_id = ? ORDER BY at DESC, rowid DESC",
                (lens_id,),
            ).fetchall()
        found = [_lens_use(r) for r in rows]
        if facet is not None:
            found = [u for u in found if facet in u.facets]
        return found[:limit]

    def count_lens_uses(self, lens_id: str, since: dt.date) -> int:
        with self._lock:
            return int(
                self._db.execute(
                    "SELECT COUNT(*) FROM lens_uses WHERE lens_id = ? AND at >= ?", (lens_id, since.isoformat())
                ).fetchone()[0]
            )

    def correct_lens_use(self, use_id: str) -> LensUse | None:
        """Mark a use as put right by the person; None when there is no such use."""
        with self._tx() as db:
            db.execute("UPDATE lens_uses SET corrected = 1 WHERE id = ?", (use_id,))
        return self.get_lens_use(use_id)

    def corrections(self, lens_id: str) -> dict[str, int]:
        """How many corrected uses touched each facet, over the life of the lens."""
        with self._lock:
            rows = self._db.execute(
                "SELECT facets FROM lens_uses WHERE lens_id = ? AND corrected = 1", (lens_id,)
            ).fetchall()
        counts: dict[str, int] = {}
        for (facets,) in rows:
            for facet in json.loads(facets):
                counts[facet] = counts.get(facet, 0) + 1
        return counts
