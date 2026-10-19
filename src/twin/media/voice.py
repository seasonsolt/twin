"""A colleague finding themselves in the meetings others uploaded, by their own voice.

Someone signed in with a work e-mail records a sentence; its voiceprint is kept in ``voice.db`` beside their own
library (the recording itself is not kept). It is compared with every speaker of the other libraries whom nobody
has said who they are (``Team.open_voices``), and the closest are offered to them, each as one sentence they can
hear. Only what the page was shown can be acted on: an offer is a row of their own ``voice.db`` with an id of its
own, never a path into someone else's library. What they say of an offer is kept here too (``claims``): "是我"
(written back to that library by ``web.voice``) or "不是", which is never offered again.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import json
import secrets
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import closing
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from ..util import date_from_name, prepare_private_file, private_directory
from .claim import Analysis, sample_windows
from .library import Library
from .team import SHOW, OpenVoice, Team, cosine

# At most this many voices are offered at once, closest first.
MAX_OFFERS = 5
# Offered as "拿不准" below this similarity (``SHOW`` is where offering starts).
LIKELY = 0.6
# A voice shorter than this cannot be heard well enough in one sentence.
MIN_SECONDS = 3.0
# The sentence shown of a voice is cut to this many characters.
QUOTE_CHARS = 60

Verdict = Literal["me", "not"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS voice (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    embedding TEXT NOT NULL,
    created_at TEXT NOT NULL
);
-- What the page was last shown; replaced every time the voices are compared again.
CREATE TABLE IF NOT EXISTS offers (
    id TEXT PRIMARY KEY,
    body TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS claims (
    id TEXT PRIMARY KEY,
    verdict TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

Heard = tuple[str, str, str]  # (recording, transcript, speaker)


class Offer(BaseModel):
    """A voice offered to someone: where it is (never shown to them) and what they may see of it."""

    id: str
    # The library the voice is in, its unnamed person if it was taken for one, and every speaker of it.
    library: str
    person_id: str | None
    speakers: list[Heard]
    # The speaker they hear and read, of ``speakers``.
    heard: Heard
    score: float
    quote: str
    title: str
    date: str | None


class Claim(BaseModel):
    id: str
    verdict: Verdict
    offer: Offer
    # For "是我": the person the voice was written back to in ``offer.library``.
    person_id: str | None = None
    created_at: str


def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat()


class SelfVoice:
    def __init__(self, root: Path) -> None:
        private_directory(root)
        self.db_path = root / "voice.db"
        prepare_private_file(self.db_path)
        with self._db() as db:
            db.executescript(_SCHEMA)

    @contextlib.contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        with closing(sqlite3.connect(self.db_path, timeout=30)) as db:
            db.row_factory = sqlite3.Row
            with db:
                yield db

    # ------------------------------------------------------------ the person's voice

    def embedding(self) -> list[float] | None:
        with self._db() as db:
            row = db.execute("SELECT embedding FROM voice WHERE id = 1").fetchone()
        return [float(x) for x in json.loads(row[0])] if row else None

    def set_embedding(self, embedding: list[float]) -> None:
        with self._db() as db:
            db.execute(
                "INSERT OR REPLACE INTO voice (id, embedding, created_at) VALUES (1, ?, ?)",
                (json.dumps(embedding), _now()),
            )
            db.execute("DELETE FROM offers")

    def forget(self) -> None:
        """Forget the voice (and what it was offered); what was said of earlier offers stays."""
        with self._db() as db:
            db.execute("DELETE FROM voice")
            db.execute("DELETE FROM offers")

    # ------------------------------------------------------------ offers and claims

    def set_offers(self, offers: Iterable[Offer]) -> None:
        with self._db() as db:
            db.execute("DELETE FROM offers")
            db.executemany("INSERT INTO offers (id, body) VALUES (?, ?)", [(o.id, o.model_dump_json()) for o in offers])

    def offer(self, offer_id: str) -> Offer | None:
        with self._db() as db:
            row = db.execute("SELECT body FROM offers WHERE id = ?", (offer_id,)).fetchone()
        return Offer.model_validate_json(row[0]) if row else None

    def claims(self) -> list[Claim]:
        with self._db() as db:
            rows = db.execute("SELECT * FROM claims ORDER BY created_at, id").fetchall()
        return [
            Claim(id=r["id"], verdict=r["verdict"], created_at=r["created_at"], **json.loads(r["body"])) for r in rows
        ]

    def claim(self, claim_id: str) -> Claim | None:
        return next((c for c in self.claims() if c.id == claim_id), None)

    def add_claim(self, offer: Offer, verdict: Verdict, person_id: str | None = None) -> Claim:
        """Keep what was said of ``offer``, which is no longer offered."""
        claim = Claim(
            id="vc_" + secrets.token_hex(8), verdict=verdict, offer=offer, person_id=person_id, created_at=_now()
        )
        with self._db() as db:
            db.execute(
                "INSERT INTO claims (id, verdict, body, created_at) VALUES (?, ?, ?, ?)",
                (
                    claim.id,
                    verdict,
                    json.dumps({"offer": offer.model_dump(mode="json"), "person_id": person_id}),
                    claim.created_at,
                ),
            )
            db.execute("DELETE FROM offers WHERE id = ?", (offer.id,))
        return claim

    def set_verdict(self, claim_id: str, verdict: Verdict) -> None:
        with self._db() as db:
            db.execute("UPDATE claims SET verdict = ? WHERE id = ?", (verdict, claim_id))

    def drop_claim(self, claim_id: str) -> None:
        with self._db() as db:
            db.execute("DELETE FROM claims WHERE id = ?", (claim_id,))


def offers(embedding: list[float], libraries: dict[str, Team], claims: Iterable[Claim]) -> list[Offer]:
    """The voices of ``libraries`` (by library key) closest to ``embedding``, from ``SHOW``, at most
    ``MAX_OFFERS``: one per unnamed person (with all their speakers) or undecided speaker. Nothing already said of
    is offered again, nor a recording already claimed (the same file uploaded by someone else has the same id)."""
    said: set[tuple[str, Heard]] = set()
    said_people: set[tuple[str, str]] = set()
    claimed_recordings: set[str] = set()
    for claim in claims:
        said.update((claim.offer.library, heard) for heard in claim.offer.speakers)
        if claim.offer.person_id:
            said_people.add((claim.offer.library, claim.offer.person_id))
        if claim.verdict == "me":
            claimed_recordings.update(heard[0] for heard in claim.offer.speakers)
    groups: dict[tuple[str, str], list[tuple[float, OpenVoice]]] = {}
    for key, team in libraries.items():
        for voice in team.open_voices():
            heard = (voice.recording.id, voice.recording.transcript_id or "", voice.speaker_id)
            if (key, heard) in said or (voice.person_id and (key, voice.person_id) in said_people):
                continue
            group = (key, voice.person_id or f"{voice.recording.id}/{voice.speaker_id}")
            groups.setdefault(group, []).append((cosine(embedding, voice.embedding), voice))
    ranked: list[tuple[float, str, list[tuple[float, OpenVoice]]]] = []
    for (key, _), voices in groups.items():
        audible = [(score, voice) for score, voice in voices if voice.seconds >= MIN_SECONDS]
        if not audible:
            continue
        best = max(score for score, _ in audible)
        if best >= SHOW:
            ranked.append((best, key, voices))
    ranked.sort(key=lambda entry: -entry[0])
    found: list[Offer] = []
    seen = set(claimed_recordings)
    for best, key, voices in ranked:
        recordings = {voice.recording.id for _, voice in voices}
        if recordings <= seen:
            continue
        _, voice = max(
            ((s, v) for s, v in voices if v.seconds >= MIN_SECONDS), key=lambda entry: (entry[0], entry[1].seconds)
        )
        offer = _offer(libraries[key].library, key, voice, voices, best)
        if offer is None:
            continue
        seen |= recordings
        found.append(offer)
        if len(found) >= MAX_OFFERS:
            break
    return found


def _offer(
    library: Library, key: str, voice: OpenVoice, voices: list[tuple[float, OpenVoice]], score: float
) -> Offer | None:
    recording = voice.recording
    transcript = library.cleaned(recording)
    if transcript is None:
        return None
    said = [s for s in transcript.segments if s.speaker == voice.speaker_id and s.text.strip()]
    windows = sample_windows(Analysis(segments=transcript.segments, speakers=transcript.speakers), voice.speaker_id)
    if not said or not windows:
        return None
    # The sentence heard in the first sample (``web.library.Libraries.sample``), so what is read is what is heard.
    start, end = windows[0]
    text = " ".join(max(said, key=lambda s: (min(s.end, end) - max(s.start, start), s.end - s.start)).text.split())
    found = date_from_name(recording.filename)
    return Offer(
        id="vo_" + secrets.token_hex(8),
        library=key,
        person_id=voice.person_id,
        speakers=sorted({(v.recording.id, v.recording.transcript_id or "", v.speaker_id) for _, v in voices}),
        heard=(recording.id, recording.transcript_id or "", voice.speaker_id),
        score=round(score, 3),
        quote=text if len(text) <= QUOTE_CHARS else text[: QUOTE_CHARS - 1] + "…",
        title=recording.filename.rsplit(".", 1)[0],
        date=(recording.creation_time or (found.isoformat() if found else None) or "")[:10] or None,
    )
