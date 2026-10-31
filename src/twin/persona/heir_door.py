"""继承人开启 (docs/PRODUCT_PERSONA_AGENT.md P2.7): an heir the will names opens the twin with their name and word.

The first opening seals the memory for good (``lifecycle.seal``, which snapshots the store first) once the heir has
confirmed it; there is no waiting time (已定 2). After that each heir enters with their word into a session of their
own, whose cookie token is kept only as a hash (``p_heir_sessions``), and talks through their own tier (``heir:<id>``).
A name the will does not know and a wrong word are refused alike, after the same scrypt work, so neither says which
it was. After ``MAX_TRIES`` wrong ones in a row, whoever they named, the door waits ``FIRST_COOLDOWN`` seconds, twice
as long after each further one, up to ``MAX_COOLDOWN``; the count is kept in the log, so restarting does not clear it.
Every opening, entry and wrong word is a line of ``p_heir_log`` (when, which heir), never the word.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import math
import secrets
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from . import lifecycle, will
from .store import PersonaStore

# How long an heir's session lasts on the server; the cookie itself ends with the browser.
SESSION_SECONDS = 12 * 3600
MAX_TRIES = 5
FIRST_COOLDOWN = 60
MAX_COOLDOWN = 3600
# What the heirs' log keeps: the first opening (which sealed the memory), an entry after it, a wrong name or word.
OPEN, ENTER, FAIL = "open", "enter", "fail"
logger = logging.getLogger("twin.heirs")


class WrongWord(Exception):
    """The name or the word is not right; which of them is not said."""


class CoolingDown(Exception):
    """Too many wrong tries in a row: the door opens again after ``seconds``."""

    def __init__(self, seconds: int) -> None:
        super().__init__(seconds)
        self.seconds = seconds


@dataclass(frozen=True)
class Opened:
    """An heir let in: who, the token of their new session (for their cookie alone), and whether this opening sealed
    the memory."""

    heir: will.Heir
    token: str
    sealed_now: bool


@dataclass(frozen=True)
class Session:
    """The heir a live session belongs to, and the name the twin keeps for its person."""

    heir_id: str
    name: str
    person: str | None


def digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@cache
def _decoy() -> str:
    """A stored word nobody knows, checked against when the name is not in the will, so that costs the same."""
    return will.hash_password(secrets.token_hex(16))


def _normal(name: str) -> str:
    return " ".join(name.split()).casefold()


def find(store: PersonaStore, name: str) -> will.Heir | None:
    """The heir the will names so, ignoring case and spacing as naming them did."""
    wanted = _normal(name)
    return next((h for h in will.load(store) if wanted and _normal(h.name) == wanted), None)


def _at(now: dt.datetime) -> str:
    return now.astimezone(dt.UTC).isoformat(timespec="seconds")


def cooldown(store: PersonaStore, now: dt.datetime) -> int:
    """Seconds until the door takes another try; 0 when it takes one now."""
    count, last = store.heir_failures((OPEN, ENTER))
    if count < MAX_TRIES or last is None:
        return 0
    span = min(FIRST_COOLDOWN << min(count - MAX_TRIES, 16), MAX_COOLDOWN)
    left = dt.datetime.fromisoformat(last).timestamp() + span - now.timestamp()
    return max(0, math.ceil(left))


def open_door(store: PersonaStore, name: str, password: str, *, confirm: bool, now: dt.datetime) -> Opened | None:
    """Let the heir of this name in with their word. While the person's memory is not yet sealed, the first opening
    seals it, but only with ``confirm``: without it a right name and word return None and change nothing. Raises
    ``CoolingDown`` while the door waits (nothing is checked then) and ``WrongWord`` for a wrong name or word, or
    ``CoolingDown`` when that wrong try starts a wait."""
    if wait := cooldown(store, now):
        raise CoolingDown(wait)
    heir = find(store, name)
    stored = store.will_secret(heir.heir_id) if heir else None
    right = will.matches(stored or _decoy(), password) and stored is not None
    if heir is None or not right:
        store.log_heir(_at(now), "", FAIL)
        logger.warning("继承人开启：称呼或口令不对")
        if wait := cooldown(store, now):
            raise CoolingDown(wait)
        raise WrongWord
    first = not lifecycle.sealed(store)
    if first and not confirm:
        return None
    if first:
        lifecycle.seal(store, now)
    token = secrets.token_hex(32)
    store.add_heir_session(digest(token), heir.heir_id, now.timestamp() + SESSION_SECONDS, now.timestamp())
    store.log_heir(_at(now), heir.heir_id, OPEN if first else ENTER)
    logger.info("继承人%s：%s", "开启，记忆已冻结" if first else "进入", heir.heir_id)
    return Opened(heir=heir, token=token, sealed_now=first)


def leave(store: PersonaStore, token: str) -> None:
    """End the heir session of this token, if there is one."""
    store.end_heir_session(digest(token))


def session_at(db_path: Path, token: str, now: float) -> Session | None:
    """The heir whose live session ``token`` opens, read without opening the twin's store (which would migrate it),
    for every request; None unless the memory is sealed and the will still names that heir."""
    if not token or len(token) > 128:
        return None
    try:
        with closing(sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True, timeout=10)) as db:
            meta = dict(
                db.execute(
                    "SELECT key, value FROM p_meta WHERE key IN (?, 'identity:name')", (lifecycle.LIFECYCLE,)
                ).fetchall()
            )
            if meta.get(lifecycle.LIFECYCLE) != lifecycle.SEALED:
                return None
            row = db.execute(
                "SELECT s.heir_id, h.json FROM p_heir_sessions s JOIN p_will_heirs h ON h.heir_id = s.heir_id"
                " WHERE s.hash = ? AND s.expires > ?",
                (digest(token), now),
            ).fetchone()
    except sqlite3.Error:
        return None
    if row is None:
        return None
    return Session(heir_id=row[0], name=str(json.loads(row[1])["name"]), person=meta.get("identity:name") or None)
