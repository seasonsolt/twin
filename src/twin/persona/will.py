"""数字遗嘱 (docs/PRODUCT_PERSONA_AGENT.md P2.2): who may talk with the twin after the person, about which aspects,
what never to bring up, whether in their voice and likeness, and until when, decided by the person alone while alive.

Nothing is given that the will does not name: an heir starts with no aspect at all. Each heir opens the twin with a
word the person sets; only its scrypt hash and parameters are kept (``PersonaStore.will_secret``), apart from what is
shown, and the word itself is never stored, logged or returned. Every change keeps the whole will as it then stands
in ``p_will_history``, which is only ever appended to. Kept in ``p_will_heirs`` and ``p_will_history`` (schema 9).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import secrets
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .companion import own_words
from .dimensions import DIMENSIONS, FACET_BY_ID, FACETS
from .store import PersonaStore

Action = Literal["add", "update", "remove", "taxonomy"]
MIN_PASSWORD_CHARS = 6
MAX_PASSWORD_CHARS = 128
MAX_NAME_CHARS = 20
MAX_TOPICS = 20
MAX_TOPIC_CHARS = 60
MAX_FAREWELL_CHARS = 500
MAX_FAREWELL_WORDS = 2
MAX_HEIRS = 20
# scrypt at about 32 MiB and a few tens of milliseconds a try; the parameters are stored with each hash, so raising
# them later leaves the words already set working.
SCRYPT_N = 2**15
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_BYTES = 32
SCRYPT_MAXMEM = 64 * 1024 * 1024
SALT_BYTES = 16
_ASPECT_IDS = [d.dimension_id for d in DIMENSIONS]


class _HeirFields(BaseModel):
    # What the person calls them; how the heir names themself when opening the twin (P2.7), so unique in a will.
    name: str
    relation: str = ""
    # Whole aspects (``D1``…``D10``) given, and single facets given beyond them. Neither means nothing is given.
    aspects: list[str] = Field(default_factory=list)
    facets: list[str] = Field(default_factory=list)
    # Topics never to be talked about with this heir, a few words or a sentence each.
    avoid: list[str] = Field(default_factory=list)
    # Whether the twin may speak to them in the person's voice and show their likeness (P3; kept only for now).
    voice: bool = False
    likeness: bool = False
    # From this day the twin says goodbye to this heir and answers no more (P2.8); None never.
    retire_on: dt.date | None = None
    # The person's own words of goodbye, said instead of the default one (P2.8).
    farewell: str | None = None
    # Up to two things the person said themself, said after the goodbye (P3.6): expression ids from ``own_words``.
    farewell_words: list[str] = Field(default_factory=list)


class HeirDraft(_HeirFields):
    """What the person writes of one heir; checked and put in a fixed order before it is kept."""

    model_config = ConfigDict(extra="forbid")

    @field_validator("name", "relation")
    @classmethod
    def _short(cls, value: str) -> str:
        value = " ".join(value.split())
        if len(value) > MAX_NAME_CHARS:
            raise ValueError(f"不能超过 {MAX_NAME_CHARS} 个字")
        return value

    @field_validator("aspects")
    @classmethod
    def _aspects(cls, value: list[str]) -> list[str]:
        if unknown := [a for a in value if a not in _ASPECT_IDS]:
            raise ValueError(f"没有这个方面：{'、'.join(unknown[:3])}")
        return [a for a in _ASPECT_IDS if a in value]

    @field_validator("facets")
    @classmethod
    def _facets(cls, value: list[str]) -> list[str]:
        if unknown := [f for f in value if f not in FACET_BY_ID]:
            raise ValueError(f"没有这个细项：{'、'.join(unknown[:3])}")
        return [f.facet_id for f in FACETS if f.facet_id in value]

    @field_validator("avoid")
    @classmethod
    def _avoid(cls, value: list[str]) -> list[str]:
        topics = list(dict.fromkeys(t for t in (" ".join(v.split()) for v in value) if t))
        if len(topics) > MAX_TOPICS:
            raise ValueError(f"不谈的话题最多 {MAX_TOPICS} 条")
        if any(len(t) > MAX_TOPIC_CHARS for t in topics):
            raise ValueError(f"每条不谈的话题不能超过 {MAX_TOPIC_CHARS} 个字")
        return topics

    @field_validator("farewell_words")
    @classmethod
    def _farewell_words(cls, value: list[str]) -> list[str]:
        words = list(dict.fromkeys(value))
        if len(words) > MAX_FAREWELL_WORDS:
            raise ValueError(f"告别时最多附 {MAX_FAREWELL_WORDS} 句原话")
        return words

    @field_validator("farewell")
    @classmethod
    def _farewell(cls, value: str | None) -> str | None:
        value = (value or "").strip()
        if len(value) > MAX_FAREWELL_CHARS:
            raise ValueError(f"告别语不能超过 {MAX_FAREWELL_CHARS} 个字")
        return value or None


class Heir(_HeirFields):
    """One heir as the will keeps them, read as written (a later taxonomy's ids are moved by ``PersonaStore``).
    Never holds the word that opens the twin, nor its hash."""

    heir_id: str
    created_at: str
    updated_at: str


class WillChange(BaseModel):
    """One row of the will's history: when, by whom, what was done to which heir and which parts of them changed
    (``password`` when only the word was set again), and the whole will after it, without secrets."""

    at: str
    actor: str
    action: Action
    heir_id: str
    changes: list[str]
    heirs: list[Heir]


def allowed_facets(heir: Heir) -> frozenset[str]:
    """Every facet the will gives this heir: those of the aspects given whole, and the single ones. Empty unless the
    person gave something."""
    return frozenset(f.facet_id for f in FACETS if f.dimension_id in heir.aspects or f.facet_id in heir.facets)


def load(store: PersonaStore) -> list[Heir]:
    """The will as it stands: its heirs in the order they were named."""
    return [Heir.model_validate_json(raw) for raw in store.will_heirs()]


def get(store: PersonaStore, heir_id: str) -> Heir:
    """One heir; KeyError when the will has none by that id."""
    for heir in load(store):
        if heir.heir_id == heir_id:
            return heir
    raise KeyError(heir_id)


def history(store: PersonaStore) -> list[WillChange]:
    """Every change to the will, oldest first."""
    return [
        WillChange(at=at, actor=actor, action=action, heir_id=heir_id, **json.loads(raw))  # type: ignore[arg-type]
        for at, actor, action, heir_id, raw in store.will_history()
    ]


def _check_password(password: str) -> None:
    if not MIN_PASSWORD_CHARS <= len(password) <= MAX_PASSWORD_CHARS:
        raise ValueError(f"口令要 {MIN_PASSWORD_CHARS} 到 {MAX_PASSWORD_CHARS} 个字符")


def _scrypt(password: str, salt: bytes, n: int, r: int, p: int, length: int) -> bytes:
    return hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, dklen=length, maxmem=SCRYPT_MAXMEM)


def hash_password(password: str) -> str:
    """The stored form of an heir's word: scrypt of it with a fresh random salt, and the parameters used."""
    _check_password(password)
    salt = secrets.token_bytes(SALT_BYTES)
    digest = _scrypt(password, salt, SCRYPT_N, SCRYPT_R, SCRYPT_P, SCRYPT_BYTES)
    return json.dumps(
        {"kdf": "scrypt", "n": SCRYPT_N, "r": SCRYPT_R, "p": SCRYPT_P, "salt": salt.hex(), "hash": digest.hex()}
    )


def verify(store: PersonaStore, heir_id: str, password: str) -> bool:
    """Whether ``password`` is the word that opens the twin to this heir, compared in constant time."""
    return matches(store.will_secret(heir_id), password)


def matches(stored: str | None, password: str) -> bool:
    """Whether ``password`` is the word whose stored form (``hash_password``) is ``stored``, compared in constant
    time; False for no stored form."""
    if stored is None or not password or len(password) > MAX_PASSWORD_CHARS:
        return False
    kept = json.loads(stored)
    if kept.get("kdf") != "scrypt":
        return False
    expected = bytes.fromhex(kept["hash"])
    given = _scrypt(password, bytes.fromhex(kept["salt"]), kept["n"], kept["r"], kept["p"], len(expected))
    return hmac.compare_digest(given, expected)


def _check_unique(store: PersonaStore, draft: HeirDraft, heir_id: str | None) -> None:
    if not draft.name:
        raise ValueError("请写这位继承人的称呼")
    others = [h for h in load(store) if h.heir_id != heir_id]
    if any(h.name.casefold() == draft.name.casefold() for h in others):
        raise ValueError(f"已经有一位叫“{draft.name}”的继承人")
    if heir_id is None and len(others) >= MAX_HEIRS:
        raise ValueError(f"继承人最多 {MAX_HEIRS} 位")


def _check_words(store: PersonaStore, draft: HeirDraft, before: Heir | None) -> None:
    """Words newly chosen to be said after the goodbye must be the person's own (``companion.own_words``); those
    chosen before stay, whatever was rebuilt since."""
    new = [w for w in draft.farewell_words if before is None or w not in before.farewell_words]
    if new and set(new) - {w.expression_id for w in own_words(store.list_items())}:
        raise ValueError("只能附你自己说过的话")


def add(store: PersonaStore, draft: HeirDraft, password: str, actor: str, now: dt.datetime) -> Heir:
    """Name a new heir with the word that will open the twin to them. ValueError when the draft or word will not do."""
    _check_unique(store, draft, None)
    _check_words(store, draft, None)
    secret = hash_password(password)
    at = now.isoformat(timespec="seconds")
    heir = Heir(**draft.model_dump(), heir_id=f"heir_{uuid.uuid4().hex[:12]}", created_at=at, updated_at=at)
    store.write_will(
        heir.heir_id,
        heir.model_dump_json(),
        secret,
        action="add",
        actor=actor,
        at=at,
        changes=[*_HeirFields.model_fields, "password"],
    )
    return heir


def update(
    store: PersonaStore, heir_id: str, draft: HeirDraft, password: str | None, actor: str, now: dt.datetime
) -> Heir:
    """Write an heir anew from the draft; ``password`` None keeps their word. KeyError when there is no such heir,
    ValueError when the draft or word will not do."""
    before = get(store, heir_id)
    _check_unique(store, draft, heir_id)
    _check_words(store, draft, before)
    secret = None if password is None else hash_password(password)
    changes = [f for f in _HeirFields.model_fields if getattr(before, f) != getattr(draft, f)]
    if secret is not None:
        changes.append("password")
    if not changes:
        return before
    at = now.isoformat(timespec="seconds")
    heir = Heir(**draft.model_dump(), heir_id=heir_id, created_at=before.created_at, updated_at=at)
    store.write_will(heir_id, heir.model_dump_json(), secret, action="update", actor=actor, at=at, changes=changes)
    return heir


def remove(store: PersonaStore, heir_id: str, actor: str, now: dt.datetime) -> None:
    """Take an heir out of the will, with their word; the history keeps what the will gave them. KeyError when there
    is no such heir."""
    get(store, heir_id)
    store.write_will(
        heir_id, None, None, action="remove", actor=actor, at=now.isoformat(timespec="seconds"), changes=[]
    )
