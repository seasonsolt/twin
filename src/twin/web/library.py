"""``/api/library``: the team's recording library, outside any one twin.

The meetings are the team's, but not everyone sees every one. Whoever uploaded a recording, and administrators,
see all of it and decide who speaks there; the people identified in it (``Viewer``) can read and hear it, and say
that a speaker given to them is not them; everyone else sees nothing of it, and may only hear the one sentence of a
voice like theirs they are offered (``web.voice``). Recordings are transcribed one after another in the shared
media slot (so a library batch and a twin's own recordings take turns on the transcription service); the queue
lives in ``library.db``, so a restart picks up where it stopped.

The owner then says who each speaker is, and creates twins of those people. A twin made from the library is kept
in line with it by ``sync``: its recording sources are rewritten from the library's current decisions and an
ordinary build follows; the twin answers again only once a build of exactly that state has succeeded
(``persona.gate``).

Every transcript is first read by the language model for the names its meeting calls the speakers by
(``media.cues``), once, as suggestions for the owner. Once someone in a recording is identified, its transcript is
proofread by the language model, once, in the same media slot; the corrected words then replace the recognized ones
in every twin it feeds, which are rebuilt. What the library spends on the model (naming, proofreading, and the builds
of its twins) counts against a batch quota (``LibrarySettings.batch_tokens`` per ``batch_hours``); once it is spent,
naming, proofreading and rebuilds wait, and the
library's status says so.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import json
import logging
import math
import shutil
import subprocess
import threading
import time
import unicodedata
import uuid
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Annotated, Any, Literal, NamedTuple

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, ValidationError
from starlette.concurrency import run_in_threadpool

from ..config import Settings
from ..llm import LLM
from ..media import denoise, merge, recollect
from ..media.claim import Analysis, cut, sample_windows
from ..media.clean import BATCH, clean_segments
from ..media.cues import Named, name_speakers
from ..media.ingest import CommandTranscriber, make_transcriber, probe_seconds
from ..media.library import TEAM, Cleaned, Library, Recording, TranscriptionError, owner_key
from ..media.review import Reviews, cut_parts
from ..media.schema import AVATAR_GENDERS, default_avatar
from ..media.team import SOURCE_PREFIX, Gender, Stale, Team, TwinSource
from ..persona import gate
from ..persona.schema import ParsedSource, Source, SourceKind
from ..persona.sources import TurnsFile, is_generic_speaker, parse_media, parse_turns
from ..persona.store import PersonaStore, stored_avatar, stored_identity
from ..teamdb import TeamDB
from ..usage import CallRow, collect_calls, model_tokens
from .jobs import Job, JobError, JobManager, Log, TooManyJobs
from .personas import ClaimBody, Personas, claim_key
from .review_queue import ReviewQueue, page
from .uploads import UploadBody, Uploads, upload_routes

logger = logging.getLogger(__name__)

GIB = 1024**3
# Waits before rewriting a twin's sources again after a failed attempt; after the last, the twin stays closed until
# the next change or restart.
SYNC_RETRY_SECONDS = (5.0, 30.0, 120.0, 600.0)
# Waits before building a twin again after only the model's rate limit stopped its build; after the last, its card
# shows the failure until someone retries it or the next change.
REBUILD_RETRY_SECONDS = (300.0, 900.0, 1800.0, 3600.0)
# How often every library is woken without anyone looking: twins held for the quota are rebuilt and proofreading
# goes on once the quota frees up, even if nobody opens the library page.
WAKE_SECONDS = 60.0
SWEEP_SECONDS = 3600.0
# ``meta`` key (in the team database) of a twin made by hand that its keeper said is not the person of its name.
APART = "people:apart:"
# How often the transcription service is asked again whether it can denoise (``media.denoise``), while some
# recording waits for a denoised copy.
DENOISE_ASK_SECONDS = 600.0
# Jobs of one library on the transcription service at once: the one being heard and the next recording, decoded
# and uploaded meanwhile so the service takes it straight after (``Libraries.kick``).
TRANSCRIPTION_SLOTS = 2
# 16 kHz mono 16-bit: the decoded audio of a second of a recording before transcription.
DECODED_BYTES_PER_SECOND = 16000 * 2
# The most of one list of the review queue a page may ask for at once (``get_review``).
MAX_REVIEW_PAGE = 10000


class Viewer(NamedTuple):
    """Who is asking: their account (``owner_key``, what recordings remember as their uploader), the account's
    key in the registry, and whether they administer the deployment (everyone does without login)."""

    key: str
    email: str | None
    admin: bool


class Access(NamedTuple):
    """What a viewer may do with a recording: hear and read it (any recording in the map), and decide about it."""

    edit: bool


class PersonBody(BaseModel):
    name: str = Field(min_length=1, max_length=40)


ABOUT_CHARS = 40


def self_introduction(registry: Personas | None, persona_id: str | None) -> str | None:
    """The first line of what a twin says about its person (their position, for one who wrote it that way), cut
    short; None when there is none."""
    if registry is None or not persona_id:
        return None
    try:
        about = stored_identity(registry.settings_for(persona_id).db_path)[1]
    except HTTPException:
        return None
    line = next((line.strip() for line in about.splitlines() if line.strip()), "")
    return (line[: ABOUT_CHARS - 1] + "…" if len(line) > ABOUT_CHARS else line) or None


class SameBody(BaseModel):
    persona_id: str = Field(max_length=100)
    same: bool


class PersonPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=40)
    gender: Gender | None = None


class MergeBody(BaseModel):
    # The person to keep; the other is folded into them.
    into: str


class RecollectBody(BaseModel):
    # The recordings to transcribe again; None: every one the viewer decides about that the current service would.
    recordings: list[str] | None = Field(default=None, max_length=10000)


class ApartBody(BaseModel):
    other: str


class SamplesApartBody(BaseModel):
    samples: tuple[int, int]


class ClashRemoveBody(BaseModel):
    sample_id: int


class ResolveBody(BaseModel):
    # The known person the unnamed voice is; ``None`` for nobody known.
    into: str | None = None


class DecisionBody(BaseModel):
    transcript_id: str
    revision: int
    action: Literal["confirm", "unknown", "mixed", "reject", "clear"]
    person_id: str | None = None
    # Confirm as a new person of this name instead of ``person_id``.
    new_person: str | None = Field(default=None, max_length=40)
    # Also keep this speaker's voice as one of the person's samples.
    sample: bool = False


class UnitsBody(BaseModel):
    """The owner's decision about stretches of a confirmed speaker (``media.review``)."""

    transcript_id: str
    revision: int
    units: list[int] = Field(min_length=1, max_length=5000)
    action: Literal["exclude", "move", "keep", "clear"]
    # Whose they are, for ``move``; or a new person of this name.
    person_id: str | None = None
    new_person: str | None = Field(default=None, max_length=40)


class VoiceMemberRef(BaseModel):
    recording_id: str
    transcript_id: str
    speaker_id: str


class VoiceBody(BaseModel):
    """Who a voice heard across recordings is (``Team.decide_voice``): the speakers as the page grouped them."""

    members: list[VoiceMemberRef] = Field(min_length=1, max_length=2000)
    action: Literal["confirm", "unknown", "mixed"]
    person_id: str | None = None
    # Confirm as a new person of this name instead of ``person_id``.
    new_person: str | None = Field(default=None, max_length=40)
    # Keep the longest speakers as the person's voice samples; off for fragments, too short to recognise anyone by.
    sample: bool = True


# The largest transcript file taken as text; a meeting's words are far below it.
MAX_TRANSCRIPT_BYTES = 20 * 1024 * 1024
SAMPLE_CHARS = 40


class SpeakerChoice(BaseModel):
    """Who a speaker of an imported transcript is: someone in the team, or nobody in it (``outsider``). Neither
    leaves the speaker undecided, even where the name is a member's."""

    person_id: str | None = Field(default=None, max_length=100)
    outsider: bool = False


class TranscriptBody(BaseModel):
    title: str | None = Field(default=None, max_length=100)
    date: dt.date | None = None
    # By the label the transcript writes the speaker as. A speaker not listed is the member of that name, if there is
    # one, and undecided otherwise.
    speakers: dict[str, SpeakerChoice] = Field(default_factory=dict, max_length=500)


def name_key(value: str) -> str:
    """A name as it is compared: width, case and spacing ignored."""
    return unicodedata.normalize("NFKC", " ".join(value.split())).casefold()


class Libraries:
    def __init__(
        self,
        settings: Settings,
        jobs: JobManager,
        registry: Personas | None = None,
        llm: Callable[[], LLM] | None = None,
        limits: Callable[[], tuple[int, float]] | None = None,
        teamdb: TeamDB | None = None,
    ) -> None:
        self.settings, self.jobs, self.registry, self.llm = settings, jobs, registry, llm
        # The team's own database: where it is kept that a twin made by hand is not the person of the same name.
        self.teamdb = teamdb
        # The token quota (tokens per window of hours); an administrator can change it while the server runs.
        self.limits = limits or (lambda: (settings.library.batch_tokens, settings.library.batch_hours))
        self.root = settings.db_path.parent / "library"
        self.lock = threading.RLock()
        self.opened: dict[str, Library] = {}
        self.review_queues: dict[str, ReviewQueue] = {}
        # Each owner's jobs on the transcription service by recording: one at a time, but for a second
        # transcription decoding and uploading while the first is heard (``kick``).
        self.running: dict[str, dict[str, Job]] = {}
        # Bytes a queued recording's decoded audio may take (``_room_ahead``), measured once per recording.
        self._decoded_bytes: dict[str, int] = {}
        # How far each recording being transcribed has come, in seconds: kept here, since every step written to the
        # library would make the review queue read everything again (``ReviewQueue``).
        self.progress: dict[str, float] = {}
        # Twins whose sources are being rewritten, and those changed again meanwhile (rewritten once more after).
        self.syncing: set[str] = set()
        self.again: set[str] = set()
        # The proofreading job of each owner, and per owner the twins whose rebuild waits: for the quota, or while
        # the automatic rebuild is switched off (``LibrarySettings.auto_build``).
        self.proofreading: dict[str, Job] = {}
        # The recording each owner's proofreading job is on, shown first as 校对中 among those waiting.
        self.proofreading_now: dict[str, str] = {}
        self.paused: dict[str, set[str]] = {}
        # Twins someone asked to rebuild now: built even while the automatic rebuild is switched off.
        self.forced: set[str] = set()
        # Twins whose build the model's rate limit stopped: tries so far, and when the next is due (None while it runs).
        self.rebuilds: dict[str, tuple[int, float | None]] = {}
        self._stop = threading.Event()
        self._waker: threading.Thread | None = None
        # Whether the transcription service can denoise, and when it was last asked (``_denoises``).
        self._can_denoise = False
        self._denoise_asked = -math.inf

    def owner(self, request: Request) -> str:
        """The library a request works in: the team's (the one library of a deployment)."""
        return TEAM

    def library(self, owner: str) -> Library:
        with self.lock:
            if owner not in self.opened:
                self.opened[owner] = Library(self.root / owner)
            return self.opened[owner]

    def member(self, key: str) -> Path:
        """A member's own corner of the team's library: their uploads still arriving and their voice."""
        return self.library(TEAM).root / "members" / key

    def review(self, owner: str, editable: set[str], stale: bool = False) -> tuple[dict[str, Any], bool]:
        """The review queue of these recordings, and whether it is an earlier reading: with ``stale``, the latest
        one at once while the current one is worked out (``ReviewQueue.peek``)."""
        with self.lock:
            if owner not in self.review_queues:
                self.review_queues[owner] = ReviewQueue(self.library(owner))
            queue = self.review_queues[owner]
        if stale and (found := queue.peek(editable)) is not None:
            reading, current = found
            return reading, not current
        return queue.get(editable), False

    def uploads(self, viewer: Viewer) -> Uploads:
        return Uploads(self.member(viewer.key))

    def view(self, recording: Recording) -> dict[str, Any]:
        """The recording as pages show it, with how far its transcription has come (``progress``)."""
        shown = view(recording)
        with self.lock:
            done = self.progress.get(recording.id)
        if done is not None and recording.status == "transcribing":
            shown["transcribed_s"] = done
        return shown

    # ------------------------------------------------------------ who may see what

    @staticmethod
    def viewer(request: Request) -> Viewer:
        identity = request.scope["twin_identity"]
        return Viewer(owner_key(identity["email"]), identity["email"], bool(identity.get("admin")))

    def people_of(self, viewer: Viewer) -> set[str]:
        """The people in the library who are the viewer: whom they said a voice of theirs is (``web.voice``), and
        those whose twin they took as theirs."""
        team = self.team(TEAM)
        found = {person.id for person in team.people() if person.account == viewer.key}
        if self.registry is not None and viewer.email:
            for persona_id, person_id, _, _ in team.synced():
                entry = self.registry.entry(persona_id)
                if entry is not None and entry.get("member") == viewer.email:
                    found.add(person_id)
        return found

    def access(self, viewer: Viewer) -> dict[str, Access]:
        """The recordings the viewer may see: those they uploaded (or all, for an administrator), which they also
        decide about, and those they were identified in."""
        library = self.library(TEAM)
        recordings = library.list()
        if viewer.admin:
            return {r.id: Access(True) for r in recordings}
        attended = self.team(TEAM).attendance()
        mine = self.people_of(viewer)
        found = {}
        for recording in recordings:
            if recording.uploader == viewer.key:
                found[recording.id] = Access(True)
            elif attended.get(recording.id, set()) & mine:
                found[recording.id] = Access(False)
        return found

    def allowed(self, viewer: Viewer, recording_id: str, edit: bool = False) -> Access:
        """What the viewer may do with the recording; 404 when they may not see it (as if it were not there), 403
        when they may see but not decide."""
        access = self.access(viewer).get(recording_id)
        if access is None:
            raise HTTPException(404, "找不到这段录音")
        if edit and not access.edit:
            raise HTTPException(403, "这段录音由上传的同事或管理员整理，你可以在自己的发言上点「不是我」")
        return access

    def managed(self, viewer: Viewer) -> set[str] | None:
        """The people the viewer may name, merge into others or make twins of: those identified in a recording
        they decide about, and those identified nowhere yet; ``None`` for everyone (an administrator)."""
        if viewer.admin:
            return None
        team = self.team(TEAM)
        editable = {rid for rid, access in self.access(viewer).items() if access.edit}
        attended = team.attendance()
        heard = set().union(*attended.values()) if attended else set()
        people = team.people()
        found = {person.id for person in people if person.id not in heard}
        for recording_id in editable:
            found |= attended.get(recording_id, set())
        # A twin made by hand is its maker's to speak for, not the library's: whoever keeps the recordings does not
        # rename its person (which renames the twin) or delete it with them.
        made = {person.id: person.persona_id for person in people if person.persona_id}
        if made and self.registry is not None:
            built = {persona_id for persona_id, _, _, _ in team.synced()}
            for person_id, persona_id in made.items():
                entry = self.registry.entry(persona_id)
                if (
                    persona_id not in built
                    and entry is not None
                    and viewer.email
                    not in (
                        entry.get("owner"),
                        entry.get("member"),
                    )
                ):
                    found.discard(person_id)
        return found

    def manage(self, viewer: Viewer, person_id: str) -> None:
        managed = self.managed(viewer)
        if managed is not None and person_id not in managed:
            raise HTTPException(403, "只有上传了 TA 所在录音的同事或管理员可以整理这个人")

    def live_twins(self) -> list[dict[str, Any]]:
        """The registry's twins that are not deleted, as copies."""
        assert self.registry is not None
        with self.registry.lock:
            return [dict(entry) for entry in self.registry.data["personas"] if not entry.get("deleted_at")]

    def twin_name(self, persona_id: str) -> str | None:
        """What the twin has been named, or None when it has not been (it still answers to the placeholder) or is
        gone meanwhile."""
        assert self.registry is not None
        try:
            settings = self.registry.settings_for(persona_id)
        except HTTPException:
            return None
        return " ".join((stored_identity(settings.db_path)[0] or "").split()) or None

    def adopt_personas(self) -> int:
        """Give every twin the library has no person for (made by hand, or by someone for themself) a person of its
        own, so the team's table has one row for each. A twin whose name is already a person's is not joined to them
        by the name: whoever keeps the twin says whether they are the same (``twin_matches``). Returns how many
        persons were added."""
        if self.registry is None:
            return 0
        team = self.team(TEAM)
        added = 0
        # The registry is read before this lock is taken: a twin forgotten for good takes the two in the other order.
        built = {twin for twin, _, _, _ in team.synced()}
        named = {entry["id"]: self.twin_name(entry["id"]) for entry in self.live_twins() if entry["id"] not in built}
        with self.lock:
            roster = team.roster()
            linked = {twin for _, _, twin in roster if twin}
            names = {name for _, name, _ in roster}
            heard = set().union(*team.attendance().values())
            # A person only made for their twin keeps its name, as the person (who is not in any meeting) is not
            # named anywhere else; one heard in meetings keeps the name the meetings call them.
            for person_id, person_name, twin in roster:
                name = named.get(twin) if twin else None
                if name and name != person_name and name not in names and person_id not in heard:
                    try:
                        team.rename(person_id, name)
                    except ValueError:
                        continue
                    names.discard(person_name)
                    names.add(name)
            for persona_id, name in named.items():
                if persona_id in linked or name is None or name in names:
                    continue
                try:
                    team.add_person(name, persona_id)
                except ValueError:
                    continue
                names.add(name)
                added += 1
        return added

    def twin_purged(self, persona_id: str) -> None:
        """A twin was forgotten for good (a week in the trash). The person made for a twin made by hand, whom no
        meeting has them in, goes with it; anyone else keeps their place and simply has no twin."""
        team = self.team(TEAM)
        with self.lock:
            built = {twin for twin, _, _, _ in team.synced()}
            heard = set().union(*team.attendance().values())
            for person_id, _, twin in team.roster():
                if twin == persona_id and persona_id not in built and person_id not in heard:
                    team.unlink(persona_id)
                    team.delete_person(person_id)

    def twin_matches(self, identity: dict[str, Any], managed: set[str] | None) -> list[dict[str, str]]:
        """Twins made by hand that the identity keeps and whose name a person of the library has, with no twin yet:
        for them to say whether it is the same person. Only people the identity may make a twin of (``managed``, as
        ``create_twin`` asks): a name alone does not let anyone speak for someone in others' meetings."""
        if self.registry is None:
            return []
        roster = self.team(TEAM).roster()
        linked = {twin for _, _, twin in roster if twin}
        free = {
            name: person_id
            for person_id, name, twin in roster
            if not twin and (managed is None or person_id in managed)
        }
        found = []
        for entry in self.live_twins():
            persona_id = entry["id"]
            if persona_id in linked or not self.registry.accessible(entry, identity):
                continue
            if self.teamdb is not None and self.teamdb.get_meta(f"{APART}{persona_id}"):
                continue
            name = self.twin_name(persona_id)
            if name in free:
                found.append({"persona_id": persona_id, "person_id": free[name], "name": name})
        return found

    def resume(self) -> None:
        """At start-up: libraries of one account each are merged into the team's (once), recordings cut off by the
        last shutdown are queued again, every queue starts, and twins still waiting for a change are brought in
        line."""
        if not self.root.is_dir():
            return
        if merge.legacy(self.root):
            try:
                merge.merge_all(self.root, self.same_person)
            except Exception:
                # What was not merged stays where it was, whole; the next start tries again.
                logger.exception("recording libraries could not be merged into the team's")
            with self.lock:
                self.opened.clear()
        self.relink()
        self.adopt_personas()
        owners = []
        for folder in sorted(self.root.iterdir()):
            if folder.name.startswith(".") or not (folder / "library.db").is_file():
                continue
            if self.library(folder.name).resume():
                self.kick(folder.name)
            owners.append(folder.name)
        # Reading every transcript of years of meetings must not hold up start-up.
        threading.Thread(target=self._settle, args=(owners,), name="library-settle", daemon=True).start()

    def same_person(self, old: Any, kept: Any) -> bool:
        """Whether two people of one name from two libraries are one: they said a voice of theirs is them from
        the same account, or their twins were made for, or taken by, the same colleague."""

        def marks(row: Any) -> set[tuple[str, str]]:
            found = {("account", str(row["account"]))} if row["account"] else set()
            entry = self.registry.entry(row["persona_id"]) if row["persona_id"] and self.registry else None
            for field in ("member", "claim"):
                if entry is not None and entry.get(field):
                    found.add((field, str(entry[field]).lower()))
            return found

        return bool(marks(old) & marks(kept))

    def relink(self) -> None:
        """Make every twin made from the team's library follow it (twins made before the merge followed their
        maker's own library)."""
        if self.registry is None:
            return
        library = self.library(TEAM)
        for persona_id, _, _, _ in Team(library).synced():
            if self.registry.entry(persona_id) is None:
                continue
            db_path = self.registry.settings_for(persona_id).db_path
            if not db_path.is_file():
                continue
            with PersonaStore(db_path) as store:
                try:
                    current = json.loads(store.get_meta(gate.LINK) or "{}")
                    followed = (db_path.resolve().parent / current["db"]).resolve()
                except (ValueError, KeyError, TypeError):
                    followed = None
                if followed != library.db_path.resolve():
                    gate.link(store, library.db_path, persona_id)

    def start(self) -> None:
        """Wake every library every ``WAKE_SECONDS`` in the background (see ``wake``)."""
        if self._waker is not None:
            return
        self._stop.clear()
        self._waker = threading.Thread(target=self._wake_all, name="library-wake", daemon=True)
        self._waker.start()

    def stop(self) -> None:
        self._stop.set()
        if self._waker is not None:
            self._waker.join(5)
            self._waker = None
        for queue in self.review_queues.values():
            queue.close()

    def sweep(self) -> int:
        """Give back disk nobody is using: every member's abandoned uploads (which otherwise count as arriving
        bytes and hold disk back from everyone until that member uploads again), and the originals of recordings
        that failed long ago. Returns how many files went."""
        removed = 0
        members = self.root / TEAM / "members"
        for folder in sorted(members.iterdir()) if members.is_dir() else ():
            try:
                removed += Uploads(folder).sweep()
            except OSError:
                logger.exception("uploads of %s could not be swept", folder.name)
        if (self.root / TEAM / "library.db").is_file():
            removed += self.library(TEAM).expire_failed(self.settings.library.failed_keep_days)
        return removed

    def _wake_all(self) -> None:
        swept = -SWEEP_SECONDS
        while not self._stop.wait(WAKE_SECONDS):
            if time.monotonic() - swept >= SWEEP_SECONDS:
                swept = time.monotonic()
                try:
                    self.sweep()
                except Exception:
                    logger.exception("unused files could not be swept")
            with self.lock:
                owners = sorted(self.opened)
            for owner in owners:
                try:
                    self.wake(owner)
                except Exception:
                    logger.exception("library of %s could not be woken", owner)

    def wake(self, owner: str) -> None:
        """Carry on with what waits: once the quota has room and the automatic rebuild is on, the twins held are
        rebuilt, and so are those whose wait after the rate limit is over; the next recording is transcribed and the
        next proofread."""
        if not self.quota(owner)["exhausted"] and self.settings.library.auto_build:
            with self.lock:
                held = self.paused.pop(owner, set())
            for persona_id in sorted(held):
                self.sync(owner, persona_id)
        now = time.time()
        with self.lock:
            due = sorted(p for p, (_, at) in self.rebuilds.items() if at is not None and at <= now)
            for persona_id in due:
                self.rebuilds[persona_id] = (self.rebuilds[persona_id][0], None)
        for persona_id in due:
            self.sync(owner, persona_id)
        self.kick(owner)

    def _settle(self, owners: list[str]) -> None:
        """Move voice samples left on older transcripts to their current speakers, or retire them
        (``recollect.settle_samples``); classify recordings transcribed before a crash (or before automatic
        classification existed), and decide again what was decided by voice under other rules (``media.collector``);
        judge again the stretches left out under other review rules and leave the suspect stretches of confirmed
        speakers out of their twins (``Reviews.settle``); then bring every waiting twin in line. Recordings a newer
        transcription service would transcribe anew are only counted: the owner decides whether to."""
        for owner in owners:
            try:
                recollect.settle_samples(self.library(owner))
                self.team(owner).classify_all()
                reviews = Reviews(self.library(owner))
                reviews.refresh()
                reviews.settle()
                self.changed(owner)
                if waiting := len(self.library(owner).recollectable()):
                    logger.info("%d recordings of %s could be transcribed again by the current service", waiting, owner)
            except Exception:
                logger.exception("library of %s could not be settled after start-up", owner)

    # ------------------------------------------------------------ twins

    def team(self, owner: str) -> Team:
        return Team(self.library(owner))

    def resettle(self, owner: str, recordings: set[str]) -> None:
        """A speaker there was confirmed as someone else: what sounds unlike that person leaves their twin
        (``Reviews.settle``), in the background since it reads every stretch; the twins it changes catch up."""

        def run() -> None:
            try:
                if Reviews(self.library(owner)).settle(recordings):
                    self.changed(owner)
            except Exception:
                logger.exception("stretches of %s could not be settled", sorted(recordings))

        threading.Thread(target=run, name="library-resettle", daemon=True).start()

    def changed(self, owner: str) -> None:
        """A decision changed some twins' wanted version: bring every waiting twin of the owner in line."""
        self.team(owner).prune()
        for persona_id, _, wanted, done in self.team(owner).synced():
            # A deleted twin (perhaps in the trash) is brought in line if it is restored and changed again.
            if wanted != done and self.registry is not None and self.registry.entry(persona_id) is not None:
                self.sync(owner, persona_id)

    def sync(self, owner: str, persona_id: str) -> None:
        """Rewrite the twin's library sources in the background and queue its build; a twin already being
        rewritten is rewritten once more afterwards."""
        with self.lock:
            if persona_id in self.syncing:
                self.again.add(persona_id)
                return
            self.syncing.add(persona_id)
        threading.Thread(
            target=self._sync, args=(owner, persona_id), name=f"twin-sync-{persona_id}", daemon=True
        ).start()

    def _sync(self, owner: str, persona_id: str) -> None:
        failures = 0
        while True:
            try:
                self.write_sources(owner, persona_id)
            except Exception:
                # The twin stays closed meanwhile; the rewrite reads the library afresh, so it covers any change
                # made during the wait.
                logger.exception("library sync of %s failed", persona_id)
                if failures < len(SYNC_RETRY_SECONDS):
                    time.sleep(SYNC_RETRY_SECONDS[failures])
                    failures += 1
                    with self.lock:
                        self.again.discard(persona_id)
                    continue
            with self.lock:
                if persona_id not in self.again:
                    self.syncing.discard(persona_id)
                    return
                self.again.discard(persona_id)

    def write_sources(self, owner: str, persona_id: str) -> bool:
        """Write the twin's sources for the library's current wanted version and queue a build; False when the
        twin is no longer made from this library."""
        team = self.team(owner)
        row = next((r for r in team.synced() if r[0] == persona_id), None)
        if row is None or self.registry is None or self.registry.entry(persona_id) is None:
            return False
        _, person_id, wanted, done = row
        exhausted = self.quota(owner)["exhausted"]
        with self.lock:
            held = exhausted or not (self.settings.library.auto_build or persona_id in self.forced)
        db_path = self.registry.settings_for(persona_id).db_path
        person = team.person(person_id)
        name = stored_identity(db_path)[0] or (person.name if person else self.settings.target_name)
        wanted_sources = {source.source_id: parsed_source(source) for source in team.sources(person_id, name)}
        if held:
            # Left as it was built; ``wake`` rewrites it once the quota frees up and the automatic rebuild is on.
            # Meanwhile it answers from that memory only if the change merely adds to what it was built from.
            with PersonaStore(db_path) as store:
                if only_adds(store, wanted_sources, done):
                    team.answer_behind(persona_id, wanted)
            with self.lock:
                self.paused.setdefault(owner, set()).add(persona_id)
            return False
        with self.lock:
            self.forced.discard(persona_id)
        with PersonaStore(db_path) as store:
            for source in store.list_sources():
                if source.source_id.startswith(SOURCE_PREFIX) and source.source_id not in wanted_sources:
                    store.delete_source(source.source_id)
            for parsed in wanted_sources.values():
                # A change usually touches one or two recordings: rewriting every source would mark them all for
                # the build again and hold the database while a build is writing to it.
                if not store.holds(parsed):
                    store.put_source(parsed)
            store.clear_source_errors()
            # After the sources: a build that reads this version has read these sources.
            store.set_meta(gate.SYNCED, str(wanted))
        self.registry.application(persona_id).state.processing.queue()
        return True

    def built(self, persona_id: str, version: int) -> None:
        """A twin's build from ``version`` completed: open it, or rewrite it when something changed meanwhile."""
        with self.lock:
            self.rebuilds.pop(persona_id, None)
        entry = self.registry.entry(persona_id) if self.registry is not None else None
        if entry is None:
            return
        owner = TEAM
        team = self.team(owner)
        if team.wanted(persona_id) is not None and not team.built(persona_id, version):
            self.sync(owner, persona_id)

    def unbuilt(self, persona_id: str, rate_limited: bool) -> None:
        """A twin's build did not complete, and the twin stays closed. Stopped only by the model's rate limit, it is
        built again after a wait (``wake``), longer each time; otherwise it waits for someone to retry it."""
        if Team(self.library(TEAM)).wanted(persona_id) is None:
            return
        with self.lock:
            tries, _ = self.rebuilds.pop(persona_id, (0, None))
            if not rate_limited or tries >= len(REBUILD_RETRY_SECONDS):
                return
            self.rebuilds[persona_id] = (tries + 1, time.time() + REBUILD_RETRY_SECONDS[tries])
        logger.warning(
            "model rate limit stopped the build of %s; trying again in %.0f s", persona_id, REBUILD_RETRY_SECONDS[tries]
        )

    def rebuild(self, persona_id: str) -> None:
        """Someone retries a twin whose build did not complete, or rebuilds one the switched-off automatic rebuild
        holds: now, and with the waits after a rate limit afresh."""
        with self.lock:
            self.rebuilds.pop(persona_id, None)
            self.forced.add(persona_id)
            self.paused.get(TEAM, set()).discard(persona_id)
        self.sync(TEAM, persona_id)

    def held(self, owner: str, persona_id: str) -> bool:
        """Whether the twin's rebuild waits while the automatic rebuild is switched off."""
        with self.lock:
            return not self.settings.library.auto_build and persona_id in self.paused.get(owner, set())

    def build_status(self, persona_id: str) -> dict[str, Any] | None:
        """How far the twin's build has gone, for its card while it cannot talk; with when it is tried again by
        itself after the rate limit stopped it."""
        status = self.registry.build_status(persona_id) if self.registry is not None else None
        with self.lock:
            _, at = self.rebuilds.get(persona_id, (0, None))
            syncing = persona_id in self.syncing
        if status is not None and status["state"] == "idle" and syncing:
            # Its sources are being written and the build is queued right after (a retry, say): already on its way.
            return {"state": "queued"}
        if status is not None and status["state"] == "idle" and at is not None:
            status["retry_at"] = dt.datetime.fromtimestamp(at, dt.UTC).isoformat()
        return status

    def spent_building(self, persona_id: str, tokens: int) -> None:
        """A build of a twin made from a library ended: what it spent counts against that library's quota."""
        entry = self.registry.entry(persona_id) if self.registry is not None else None
        if entry is None:
            return
        library = self.library(TEAM)
        if Team(library).wanted(persona_id) is not None:
            library.spend("rebuild", tokens)

    # ------------------------------------------------------------ quota and proofreading

    def quota(self, owner: str) -> dict[str, Any]:
        """The owner's batch quota: tokens spent in the last ``batch_hours``, and whether that leaves none, in
        which case ``resets_at`` says when the oldest of them leaves the window."""
        limit, hours = self.limits()
        window = dt.timedelta(hours=hours)
        used, oldest = self.library(owner).spent(dt.datetime.now(dt.UTC) - window)
        exhausted = bool(limit) and used >= limit
        resets_at = (dt.datetime.fromisoformat(oldest) + window).isoformat() if exhausted and oldest else None
        return {"limit": limit, "hours": hours, "used": used, "exhausted": exhausted, "resets_at": resets_at}

    def proofread(self, owner: str) -> None:
        """Start proofreading the owner's next recording that needs it, unless one is being proofread, no
        language model is configured or the quota is spent (``status`` tries again)."""
        if self.llm is None:
            return
        with self.lock:
            job = self.proofreading.get(owner)
            if job is not None and job.active:
                return
            unnamed = self.library(owner).unnamed()
            waiting = unnamed or self.library(owner).unproofread()
            if not waiting or self.quota(owner)["exhausted"]:
                return
            try:
                self.llm()
            except Exception:
                return
            recording = waiting[0]
            if unnamed:
                title, run = f"辨认说话人 {recording.filename}", self.run_naming
            else:
                title, run = f"校对 {recording.filename}", self.run_proofread
            with contextlib.suppress(TooManyJobs):
                self.proofreading[owner] = self.jobs.scoped(f"library:{owner}").submit(
                    "media_ingest", title, lambda log: run(owner, recording.id, log)
                )
                if not unnamed:
                    self.proofreading_now[owner] = recording.id

    def run_naming(self, owner: str, recording_id: str, log: Log) -> dict[str, Any]:
        """Ask the model, once per transcript, what the meeting calls its speakers, filing the names next to it as
        suggestions for the owner. A model that fails on every window files nothing; the recording is not asked
        again either way."""
        library = self.library(owner)
        try:
            recording = library.get(recording_id)
            if recording is None or recording.transcript_id is None or recording.named == recording.transcript_id:
                return {"skipped": True}
            transcript = library.cleaned(recording)
            if transcript is None:
                library.asked_names(recording_id, recording.transcript_id)
                return {"skipped": True}
            if self.quota(owner)["exhausted"]:
                log("录音库本批次的大模型额度已用完，辨认说话人暂停")
                return {"paused": True}
            assert self.llm is not None
            llm = self.llm()
            # Only people heard in meetings: others (a test twin, a colleague never recorded) are no one to call on.
            roster = [person.name for person in self.team(owner).people() if not person.auto and person.speakers]
            log("[1/1] 从会议内容辨认说话人")
            rows: list[CallRow] = []
            try:
                with collect_calls() as rows:
                    cues, failed = name_speakers(llm, transcript.segments, roster)
            finally:
                library.spend("naming", model_tokens(rows))
            if failed and not cues:
                log("辨认说话人失败，不影响按声音确认")
            else:
                named = Named(
                    transcript_id=transcript.id,
                    created_at=dt.datetime.now(dt.UTC).isoformat(),
                    speakers=cues,
                    failed_windows=failed,
                )
                try:
                    library.write_names(recording, named)
                except (OSError, ValueError):
                    logger.warning("speaker names of %s could not be filed", recording_id, exc_info=True)
                log(f"辨认完成：会上叫到了 {len(cues)} 位说话人的名字")
            library.asked_names(recording_id, transcript.id)
            return {"recording_id": recording_id, "named": len(cues)}
        finally:
            with self.lock:
                self.proofreading.pop(owner, None)
            self.proofread(owner)

    def run_proofread(self, owner: str, recording_id: str, log: Log) -> dict[str, Any]:
        """Proofread one recording's transcript once, filing the corrections next to it; when words changed, the
        twins of everyone identified in it are closed and rebuilt from them. A model that fails on every batch
        leaves the transcript as recognized."""
        library = self.library(owner)
        team = self.team(owner)
        try:
            recording = library.get(recording_id)
            if recording is None or recording.transcript_id is None or recording.proofread == recording.transcript_id:
                return {"skipped": True}
            transcript = library.transcript(recording)
            if transcript is None:
                team.proofread(recording_id, recording.transcript_id, False)
                return {"skipped": True}
            if self.quota(owner)["exhausted"]:
                log("录音库本批次的大模型额度已用完，校对暂停")
                return {"paused": True}
            assert self.llm is not None
            llm = self.llm()
            batches = math.ceil(len(transcript.segments) / BATCH)
            rows: list[CallRow] = []
            try:
                with collect_calls() as rows:
                    result = clean_segments(
                        llm, transcript.segments, lambda done, total: log(f"[1/1] 校对转写（{done} / {total} 批）")
                    )
            finally:
                library.spend("proofread", model_tokens(rows))
            changed = False
            if batches and result.failed_batches == batches:
                log("校对失败，保留识别原文")
            else:
                clean = Cleaned(
                    transcript_id=transcript.id,
                    created_at=dt.datetime.now(dt.UTC).isoformat(),
                    changed=result.changed,
                    failed_batches=result.failed_batches,
                    segments=result.segments,
                )
                try:
                    changed = library.write_cleaned(recording, clean) and result.changed > 0
                except (OSError, ValueError):
                    logger.warning("proofreading of %s could not be filed", recording_id, exc_info=True)
                note = f"，{result.failed_batches} 批失败保留原文" if result.failed_batches else ""
                log(f"校对完成：修正 {result.changed} 段{note}")
            if team.proofread(recording_id, transcript.id, changed) and changed:
                self.changed(owner)
            return {"recording_id": recording_id, "changed": result.changed}
        finally:
            with self.lock:
                self.proofreading.pop(owner, None)
                self.proofreading_now.pop(owner, None)
            self.proofread(owner)

    def proofread_state(self, library: Library, recording: Recording, waiting: set[str]) -> str:
        """``done`` (corrections filed), ``failed`` (the model was asked and gave none), ``waiting`` (someone is
        identified and proofreading is still to come) or empty."""
        if recording.kind == "transcript":
            return ""  # Its words are the transcript's own: nothing is proofread.
        path = library.clean_path(recording)
        if path is not None and path.is_file():
            return "done"
        if recording.transcript_id and recording.proofread == recording.transcript_id:
            return "failed"
        return "waiting" if recording.id in waiting else ""

    def proofread_view(
        self, library: Library, recording: Recording, waiting: set[str], now: str | None
    ) -> dict[str, Any]:
        """``proofread`` (``proofread_state``) and ``proofreading``: the recording is the one being proofread
        (``now``) and nothing is filed yet; once the corrections are, it is done while the job still ends."""
        state = self.proofread_state(library, recording, waiting)
        return {"proofread": state, "proofreading": state == "waiting" and recording.id == now}

    def create_twin(
        self, owner: str, person_id: str, identity: dict[str, Any], claim: str | None = None
    ) -> dict[str, Any]:
        """The person's twin, created on first call: private, owned by the account, answering as a meeting record
        once its first build completes. ``claim``: the person's work e-mail or employee number, by which they take the
        twin when they sign in."""
        assert self.registry is not None
        team = self.team(owner)
        with self.lock:
            person = team.person(person_id)
            if person is None:
                raise HTTPException(404, "找不到这个人")
            existing = self.registry.entry(person.persona_id) if person.persona_id else None
            if existing is not None:
                if existing.get("by_voice"):
                    raise HTTPException(409, "这个人已经用自己的声音认领了分身")
                if not self.registry.accessible(existing, identity):
                    raise HTTPException(409, "已经有同事为 TA 建了分身")
                return {"persona_id": person.persona_id, "new": False}
            entry = self.registry.create(person.name, identity, onboarding=False, claim=claim)
            with PersonaStore(self.registry.settings_for(entry["id"]).db_path) as store:
                gate.link(store, self.library(owner).db_path, entry["id"])
            team.link(person_id, entry["id"])
            self.dress(entry["id"], person.gender)
        self.sync(owner, entry["id"])
        return {"persona_id": entry["id"], "new": True}

    def decide(self, owner: str, recording_id: str, speaker_id: str, body: DecisionBody) -> dict[str, Any]:
        team = self.team(owner)
        person_id = body.person_id
        if body.action == "confirm" and body.new_person:
            try:
                person_id = team.add_person(body.new_person).id
            except ValueError as e:
                raise HTTPException(409, str(e)) from None
        # Said before deciding: once settled, the speaker's own sample would match them.
        unlike = (
            team.unlike([(recording_id, speaker_id)], person_id) if body.action == "confirm" and person_id else None
        )
        try:
            revision = team.decide(
                recording_id, body.transcript_id, body.revision, speaker_id, body.action, person_id, body.sample
            )
        except Stale:
            if body.action == "confirm" and body.new_person and person_id:
                team.delete_person(person_id)  # Made for this decision only.
            raise HTTPException(409, "这段录音刚被修改过，请刷新后再确认") from None
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        if body.action == "confirm" and body.sample:
            # A new voice sample can settle speakers in every other recording.
            team.classify_all()
        self.changed(owner)
        self.resettle(owner, {recording_id})
        self.proofread(owner)
        return {"revision": revision, "person_id": person_id, "unlike": unlike.model_dump() if unlike else None}

    def decide_voice(self, owner: str, body: VoiceBody) -> dict[str, Any]:
        team = self.team(owner)
        person_id = body.person_id
        if body.action == "confirm" and body.new_person:
            try:
                person_id = team.add_person(body.new_person).id
            except ValueError as e:
                raise HTTPException(409, str(e)) from None
        members = [(m.recording_id, m.transcript_id, m.speaker_id) for m in body.members]
        heard = [(m.recording_id, m.speaker_id) for m in body.members]
        unlike = team.unlike(heard, person_id) if body.action == "confirm" and person_id else None
        try:
            team.decide_voice(members, body.action, person_id, sample=body.sample)
        except Stale:
            if body.action == "confirm" and body.new_person and person_id:
                team.delete_person(person_id)  # Made for this decision only.
            raise HTTPException(409, "这些录音刚被修改过，请刷新后再确认") from None
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        # The new voice samples can settle speakers in every other recording: the owner hears how many.
        recognised = team.classify_all() if body.action == "confirm" else 0
        self.changed(owner)
        self.resettle(owner, {m.recording_id for m in body.members})
        self.proofread(owner)
        return {
            "person_id": person_id,
            "recognised": recognised,
            "unlike": unlike.model_dump() if unlike else None,
        }

    def update(self, owner: str, person_id: str, body: PersonPatch) -> dict[str, Any]:
        team = self.team(owner)
        try:
            if body.gender is not None:
                persona_id = team.set_gender(person_id, body.gender)
                if persona_id:
                    self.dress(persona_id, body.gender)
            if body.name is not None:
                persona_id = team.rename(person_id, body.name)
                if persona_id and self.own_twin(persona_id):
                    assert self.registry is not None
                    with PersonaStore(self.registry.settings_for(persona_id).db_path) as store:
                        store.set_meta("identity:name", " ".join(body.name.split()))
                self.changed(owner)
        except ValueError as e:
            raise HTTPException(409 if "已经有" in str(e) else 400, str(e)) from None
        return {"updated": True}

    def own_twin(self, persona_id: str) -> bool:
        """Whether those who keep the library speak for the twin: it is live and not one the person made of
        themselves (``web.voice``), whose name and look are theirs to choose."""
        entry = self.registry.entry(persona_id) if self.registry is not None else None
        return entry is not None and not entry.get("by_voice")

    def dress(self, persona_id: str, gender: str) -> None:
        """Give the twin an illustration of the person's gender, unless the one it shows already is."""
        if not gender or self.registry is None or not self.own_twin(persona_id):
            return
        settings = self.registry.settings_for(persona_id)
        if AVATAR_GENDERS[stored_avatar(settings.db_path, settings.avatar.preset)] != gender:
            with PersonaStore(settings.db_path) as store:
                store.set_meta("identity:avatar_preset", default_avatar(persona_id, gender))

    def detail(self, owner: str, recording_id: str, viewer: Viewer) -> dict[str, Any]:
        """The recording with its transcript and speakers. ``can_edit``: the viewer decides about it; otherwise
        they see the decisions without the voices they were matched with, and ``mine`` says which speakers are
        given to them (they may say those are not)."""
        access = self.allowed(viewer, recording_id)
        library = self.library(owner)
        recording = library.get(recording_id)
        if recording is None:
            raise HTTPException(404, "找不到这段录音")
        transcript = library.cleaned(recording)
        analysis = Analysis(segments=transcript.segments, speakers=transcript.speakers) if transcript else None
        waiting = {r.id for r in library.unproofread()}
        speakers = self.team(owner).speakers(recording)
        people = self.people_of(viewer)
        heard = recording.kind != "transcript"
        return {
            **self.view(recording),
            **self.proofread_view(library, recording, waiting, self.proofreading_now.get(owner)),
            "denoised": denoise.denoised(library, recording.id),
            "timed": transcript.timed if transcript else True,
            "can_edit": access.edit,
            "mine": [s.id for s in speakers if s.decision == "confirmed" and s.person_id in people],
            "speakers": [
                {
                    **s.model_dump(exclude=set() if access.edit else {"candidates", "rejected", "near"}),
                    "samples": len(sample_windows(analysis, s.id)) if analysis and heard else 0,
                }
                for s in speakers
            ],
            "segments": [
                {"start": s.start, "end": s.end, "text": s.text, "speaker": s.speaker}
                for s in (transcript.segments if transcript else [])
            ],
        }

    def sample(
        self,
        owner: str,
        recording_id: str,
        speaker_id: str,
        index: int,
        viewer: Viewer | None = None,
        original: bool = False,
    ) -> FileResponse:
        """A short WAV of the speaker (up to three, at different moments), cut from what people hear of the
        recording (``media.denoise.listening``; ``original``: the audio as recorded) and kept in the library's
        media cache, which backups skip. ``viewer``: only if they may see the recording (``web.voice`` checks its
        own way)."""
        if viewer is not None:
            self.allowed(viewer, recording_id)
        library = self.library(owner)
        recording = library.get(recording_id)
        transcript = library.transcript(recording) if recording else None
        if recording is None or transcript is None:
            raise HTTPException(404, "找不到这段录音")
        if recording.kind == "transcript":
            raise HTTPException(404, "转写稿没有声音可以试听")
        windows = sample_windows(Analysis(segments=transcript.segments, speakers=transcript.speakers), speaker_id)
        if not 0 <= index < len(windows):
            raise HTTPException(404, "没有这段试听")
        cache = library.root / "media-cache" / recording.id
        # Named by its times, not its place in the list: choosing the moments differently never plays an old cut.
        start, end = windows[index]
        audio = denoise.listening(library, recording.id, original)
        heard = "" if audio.name == "playback.flac" else "-denoised"
        target = cache / f"{transcript.id}-{speaker_id}-{round(start * 1000)}-{round(end * 1000)}{heard}.wav"
        if not target.is_file():
            cache.mkdir(parents=True, mode=0o700, exist_ok=True)
            # ffmpeg picks the format from the suffix; a name of its own keeps two plays from sharing one file.
            temporary = target.with_name(f".{uuid.uuid4().hex}.tmp.wav")
            try:
                cut(audio, temporary, *windows[index])
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
        return FileResponse(target, media_type="audio/wav", headers={"Cache-Control": "private, max-age=3600"})

    def kick(self, owner: str) -> None:
        """Start transcribing the owner's next queued recording unless one is already running; with none queued,
        hear the confirmed speakers of the next recording again (``media.review``), and with none of those either,
        transcribe again the next recording the owner asked to (``media.recollect``), all in the same slot of the
        transcription service, one at a time. With a service that takes requests in turn (``takes_turns``), one more
        queued recording may start beside a running job when its decoded audio leaves the headroom free
        (``_room_ahead``): it decodes and uploads while the service is busy, which takes it next, so the service
        does not sit idle between recordings. Without a diarizing
        transcription service, or with the job queue full, recordings stay queued; the next status poll tries
        again. Proofreading waiting for its turn starts too."""
        self.proofread(owner)
        with self.lock:
            jobs = {rid: job for rid, job in self.running.get(owner, {}).items() if job.active}
            self.running[owner] = jobs
            # A command that runs the models itself is never started twice: it would load them twice.
            ahead = self.settings.asr.takes_turns()
            # Stopping: what is waiting starts after the restart, not while the service goes down.
            if len(jobs) >= (TRANSCRIPTION_SLOTS if ahead else 1) or self._stop.is_set():
                return
            if not isinstance(make_transcriber(self.settings.asr), CommandTranscriber):
                return
            library = self.library(owner)
            recording = library.next_queued(skip=jobs)
            if jobs:
                if recording is None or not self._room_ahead(library, recording):
                    return
                title, run = recording.filename, self.run
            elif recording is not None:
                title, run = recording.filename, self.run
            elif waiting := Reviews(library).waiting():
                recording = waiting[0]
                title, run = f"复核说话人 {recording.filename}", self.run_review
            elif again := recollect.waiting(library):
                recording = again[0]
                title, run = f"重新转写 {recording.filename}", self.run_recollect
            elif (quiet := denoise.waiting(library)) and self._denoises(owner):
                recording = quiet[0]
                title, run = f"降噪 {recording.filename}", self.run_denoise
            else:
                return
            target = recording.id
            with contextlib.suppress(TooManyJobs):
                # The service takes them in turn; the job queue's single media slot would hold the second back.
                jobs[target] = self.jobs.scoped(f"library:{owner}").submit(
                    "media_ingest", title, lambda log: run(owner, target, log), slotted=not ahead
                )

    def _room_ahead(self, library: Library, recording: Recording) -> bool:
        """Whether the recording's decoded audio fits above the headroom with every upload still arriving in:
        counted at the size of its 16 kHz 16-bit samples, which the FLAC kept stays under."""
        size = self._decoded_bytes.get(recording.id)
        if size is None:
            original = library.original(recording.id)
            try:
                seconds = probe_seconds(original) if original is not None else None
            except (subprocess.SubprocessError, OSError, ValueError, KeyError):
                seconds = None
            if seconds is None:
                return False  # Not measured: it waits for its turn alone, as before.
            size = self._decoded_bytes[recording.id] = math.ceil(seconds * DECODED_BYTES_PER_SECOND)
        capacity = self.capacity()
        return capacity["free_bytes"] - capacity["arriving_bytes"] - size >= capacity["headroom_bytes"]

    def run_review(self, owner: str, recording_id: str, log: Log) -> dict[str, Any]:
        """Hear the recording's confirmed speakers again, stretch by stretch; a failure is noted and tried again
        later (``media.review.RETRY``), so the next recording's turn comes."""
        try:
            transcriber = make_transcriber(self.settings.asr)
            if not isinstance(transcriber, CommandTranscriber):
                return {"skipped": True}
            log("[1/1] 逐段计算已确认说话人的声纹")
            try:
                heard = Reviews(self.library(owner)).run(recording_id, transcriber)
            except (RuntimeError, OSError, ValueError) as exc:
                raise JobError(f"复核没有完成：{exc}") from None
            # What the review left out of the confirmed people's twins (``Reviews.settle``) reaches them.
            self.changed(owner)
            log(f"完成：复核了 {heard} 位说话人")
            return {"recording_id": recording_id, "speakers": heard}
        finally:
            with self.lock:
                self.running.get(owner, {}).pop(recording_id, None)
            self.kick(owner)

    def _denoises(self, owner: str) -> bool:
        """Whether the transcription service can denoise, as it last said: asked again in the background at most
        every ``DENOISE_ASK_SECONDS``, so a status poll never waits on it; a yes starts the waiting recordings."""
        now = time.monotonic()
        if now - self._denoise_asked >= DENOISE_ASK_SECONDS:
            self._denoise_asked = now

            def ask() -> None:
                transcriber = make_transcriber(self.settings.asr)
                self._can_denoise = isinstance(transcriber, CommandTranscriber) and transcriber.can_denoise()
                if self._can_denoise:
                    self.kick(owner)

            threading.Thread(target=ask, name="library-denoise-ask", daemon=True).start()
        return self._can_denoise

    def run_denoise(self, owner: str, recording_id: str, log: Log) -> dict[str, Any]:
        """Make a recording's denoised copy for listening (``media.denoise``); a failure is noted and tried again
        later, so the next recording's turn comes."""
        library = self.library(owner)
        try:
            transcriber = make_transcriber(self.settings.asr)
            if not isinstance(transcriber, CommandTranscriber):
                return {"skipped": True}

            def progress(done: float, total: float) -> None:
                log(f"[1/1] 降噪（已完成 {done / 60:.1f} / {total / 60:.1f} 分钟）")

            log("[1/1] 生成降噪后的试听音频")
            try:
                made = denoise.run(library, recording_id, transcriber, progress)
            except RuntimeError as exc:
                raise JobError(f"降噪没有完成：{exc}") from None
            log("完成" if made else "已有降噪后的试听音频")
            return {"recording_id": recording_id, "denoised": made}
        finally:
            with self.lock:
                self.running.get(owner, {}).pop(recording_id, None)
            self.kick(owner)

    def run_recollect(self, owner: str, recording_id: str, log: Log) -> dict[str, Any]:
        """Transcribe a recording again with the current service, carrying the owner's decisions over
        (``media.recollect``); the twins whose speech in it changed catch up."""
        library = self.library(owner)
        try:
            transcriber = make_transcriber(self.settings.asr)
            if not isinstance(transcriber, CommandTranscriber):
                return {"skipped": True}

            def progress(done: float, total: float) -> None:
                log(f"[1/2] 重新转写（已完成 {done / 60:.1f} / {total / 60:.1f} 分钟）")

            log("[1/2] 重新转写")
            try:
                report = recollect.run(library, recording_id, transcriber, progress)
            except TranscriptionError as exc:
                raise JobError(str(exc)) from None
            self.changed(owner)
            log(f"[2/2] 完成：沿用 {report.carried} 位说话人的决定，{len(report.unsettled)} 位需要重新确认")
            return {"recording_id": recording_id, "carried": report.carried, "unsettled": len(report.unsettled)}
        finally:
            with self.lock:
                self.running.get(owner, {}).pop(recording_id, None)
            self.kick(owner)

    def recollection(self, owner: str, viewer: Viewer) -> dict[str, Any]:
        """The recordings the viewer decides about that the current service would transcribe anew, and what each
        transcription again carried over."""
        library = self.library(owner)
        editable = {rid for rid, access in self.access(viewer).items() if access.edit}
        return {
            "service": library.collector().asr,
            "recordings": [
                {"id": r.id, "filename": r.filename, "asr": r.asr, "asked": r.recollect}
                for r in library.recollectable()
                if r.id in editable
            ],
            "done": [
                {"recording_id": recording_id, "rolled_back": rolled_back, **report.model_dump()}
                for recording_id, report, rolled_back in recollect.reports(library)
                if recording_id in editable
            ],
        }

    def units(self, owner: str, recording_id: str, speaker_id: str) -> dict[str, Any]:
        """A confirmed speaker's stretches with whom each sounds like (``media.review``)."""
        library = self.library(owner)
        recording = library.get(recording_id)
        review = Reviews(library).speaker(recording, speaker_id) if recording else None
        if review is None:
            raise HTTPException(404, "这个说话人还没有确认是谁")
        return review.model_dump()

    def fix(self, owner: str, recording_id: str, speaker_id: str, body: UnitsBody) -> dict[str, Any]:
        team = self.team(owner)
        person_id = body.person_id
        if body.action == "move" and body.new_person:
            try:
                person_id = team.add_person(body.new_person).id
            except ValueError as e:
                raise HTTPException(409, str(e)) from None
        try:
            revision = Reviews(self.library(owner)).fix(
                recording_id, body.transcript_id, body.revision, speaker_id, body.units, body.action, person_id
            )
        except Stale:
            if body.action == "move" and body.new_person and person_id:
                team.delete_person(person_id)  # Made for this decision only.
            raise HTTPException(409, "这段录音刚被修改过，请刷新后再操作") from None
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        self.changed(owner)
        return {"revision": revision, "person_id": person_id}

    def unit_clip(
        self, owner: str, recording_id: str, speaker_id: str, index: int, original: bool = False
    ) -> FileResponse:
        """One stretch of a confirmed speaker as WAV, its segments one after another, kept in the media cache; from
        the denoised copy unless ``original``, like ``sample``."""
        library = self.library(owner)
        recording = library.get(recording_id)
        review = Reviews(library).speaker(recording, speaker_id, text=False) if recording else None
        unit = next((u for u in review.units if u.index == index), None) if review else None
        if recording is None or unit is None:
            raise HTTPException(404, "没有这个片段")
        transcript = library.transcript(recording)
        if transcript is None:
            raise HTTPException(404, "找不到这段录音")
        parts = [(transcript.segments[i].start, transcript.segments[i].end) for i in unit.segments]
        cache = library.root / "media-cache" / recording.id
        audio = denoise.listening(library, recording.id, original)
        heard = "" if audio.name == "playback.flac" else "-denoised"
        target = cache / f"{transcript.id}-{speaker_id}-unit-{'-'.join(map(str, unit.segments))}{heard}.wav"
        if not target.is_file():
            cache.mkdir(parents=True, mode=0o700, exist_ok=True)
            temporary = target.with_name(f".{uuid.uuid4().hex}.tmp.wav")
            try:
                cut_parts(audio, temporary, parts)
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
        return FileResponse(target, media_type="audio/wav", headers={"Cache-Control": "private, max-age=3600"})

    def run(self, owner: str, recording_id: str, log: Log) -> dict[str, Any]:
        library = self.library(owner)
        transcriber = make_transcriber(self.settings.asr)

        def progress(done: float, total: float) -> None:
            with self.lock:
                self.progress[recording_id] = done
            log(f"[1/2] 转写（已完成 {done / 60:.1f} / {total / 60:.1f} 分钟）")

        try:
            if not isinstance(transcriber, CommandTranscriber):
                raise TranscriptionError("录音库需要能区分说话人的转写服务（asr-funasr）")
            log("[1/2] 提取音频")
            recording = library.transcribe(recording_id, transcriber, progress)
            log(f"[2/2] 完成：{recording.segments} 段，{recording.speakers} 位说话人")
            # Known voices go to their people and new long voices become unnamed people, without asking.
            if self.team(owner).classify(recording_id):
                self.changed(owner)
            return {"recording_id": recording_id, "status": recording.status}
        except TranscriptionError as exc:
            raise JobError(str(exc)) from None
        finally:
            with self.lock:
                self.running.get(owner, {}).pop(recording_id, None)
                self._decoded_bytes.pop(recording_id, None)
                self.progress.pop(recording_id, None)
            self.kick(owner)

    # ------------------------------------------------------------ transcripts brought in as text

    @staticmethod
    def read_transcript(filename: str, data: bytes) -> TurnsFile:
        try:
            return parse_turns(filename, data)
        except ValueError as e:
            raise HTTPException(400, str(e)) from None

    def members_named(self, owner: str, labels: Iterable[str]) -> dict[str, tuple[str, str]]:
        """The member each label is the name of, ``(id, name)``: written as the member's name (width, case and spacing
        aside) and of nobody else. A label such as ``发言人1`` names no one."""
        by_name: dict[str, list[tuple[str, str]]] = {}
        for person_id, name, _ in self.team(owner).roster():
            by_name.setdefault(name_key(name), []).append((person_id, name))
        found: dict[str, tuple[str, str]] = {}
        for label in labels:
            hits = [] if is_generic_speaker(label) else by_name.get(name_key(label), [])
            if len(hits) == 1:
                found[label] = hits[0]
        return found

    def transcript_preview(self, owner: str, viewer: Viewer, filename: str, data: bytes) -> dict[str, Any]:
        """What importing the file would bring in, to look at first: the title and day, and each speaker with how
        much they say, a line of it, and the member the name is, if any. Nothing is stored. A file the import would
        refuse (the queue or the disk is full) is refused here, before the importer has filled anything in."""
        parsed = self.read_transcript(filename, data)
        self.admit(viewer, UploadBody(filename=filename, size=len(data)), transcript=True)
        found = self.members_named(owner, {turn.speaker for turn in parsed.turns})
        counts: dict[str, int] = {}
        sample: dict[str, str] = {}
        for turn in parsed.turns:
            counts[turn.speaker] = counts.get(turn.speaker, 0) + 1
            line = " ".join(turn.text.split())
            sample.setdefault(turn.speaker, line if len(line) <= SAMPLE_CHARS else line[: SAMPLE_CHARS - 1] + "…")
        return {
            "title": parsed.title,
            "date": parsed.date.isoformat() if parsed.date else None,
            "speakers": [
                {
                    "label": label,
                    "segments": count,
                    "sample": sample[label],
                    "person": {"id": found[label][0], "name": found[label][1]} if label in found else None,
                }
                for label, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
            ],
        }

    def import_transcript(
        self, owner: str, viewer: Viewer, filename: str, data: bytes, body: TranscriptBody
    ) -> dict[str, Any]:
        """File the transcript as a recording of the team's library that is ready at once, and give its speakers to
        the members they are: those the importer chose, else the member whose name the label is. A speaker not
        given to anyone waits to be settled like any other (``Team.unvoiced``)."""
        parsed = self.read_transcript(filename, data)
        # Held to what an upload is: no more queued than ``max_pending`` and the disk's headroom kept.
        self.admit(viewer, UploadBody(filename=filename, size=len(data)), transcript=True)
        team = self.team(owner)
        known = {person_id for person_id, _, _ in team.roster()}
        labels = list(dict.fromkeys(turn.speaker for turn in parsed.turns))
        for label, choice in body.speakers.items():
            if label not in labels:
                raise HTTPException(400, f"转写稿里没有叫「{label}」的说话人")
            if choice.person_id and (choice.outsider or choice.person_id not in known):
                raise HTTPException(400, "找不到这个人")
        title = " ".join((body.title or parsed.title).split()) or parsed.title
        suffix = Path(filename).suffix.lower()
        name = title if title.lower().endswith(suffix) else title + suffix
        day = body.date or parsed.date
        sha = hashlib.sha256(data).hexdigest()
        library = self.library(owner)
        recording, new = library.add_transcript(
            name,
            [(turn.speaker, turn.text, turn.clock) for turn in parsed.turns],
            sha=sha,
            size=len(data),
            uploader=viewer.key,
            date=day.isoformat() if day else None,
        )
        if not new:
            return self.filed(viewer, recording, False)
        found = self.members_named(owner, labels)
        decided = 0
        revision = recording.revision
        assert recording.transcript_id is not None
        for label in labels:
            chosen = body.speakers.get(label)
            person_id = chosen.person_id if chosen else (found[label][0] if label in found else None)
            outsider = bool(chosen and chosen.outsider)
            if not person_id and not outsider:
                continue
            revision = team.decide(
                recording.id,
                recording.transcript_id,
                revision,
                label,
                "confirm" if person_id else "unknown",
                person_id,
            )
            decided += 1
        self.changed(owner)
        settled = library.get(recording.id) or recording
        return {**self.filed(viewer, settled, True), "decided": decided, "unsettled": len(labels) - decided}

    def capacity(self) -> dict[str, int]:
        self.root.mkdir(parents=True, mode=0o700, exist_ok=True)
        arriving = count = 0
        members = self.root / TEAM / "members"
        for folder in members.iterdir() if members.is_dir() else ():
            n, remaining = Uploads(folder).arriving()
            count, arriving = count + n, arriving + remaining
        return {
            "free_bytes": shutil.disk_usage(self.root).free,
            "arriving_bytes": arriving,
            "arriving": count,
            "headroom_bytes": int(self.settings.library.headroom_gb * GIB),
        }

    def admit(self, viewer: Viewer, body: UploadBody, transcript: bool = False) -> None:
        """Refuse an upload that would leave less than the headroom free once every upload still arriving is in,
        or that would queue more than ``max_pending`` of the member's recordings. Transcription decodes one
        recording at a time, and a second only with room for its audio above the headroom (``kick``). A transcript
        is held to the same rules but is not transcribed itself: what it waits for is the member's other files."""
        library = self.library(TEAM)
        waiting = library.pending(viewer.key) + self.uploads(viewer).arriving()[0]
        limit = self.settings.library.max_pending
        if waiting >= limit:
            if transcript:
                raise HTTPException(
                    409, f"你已有 {waiting} 个文件在排队转写（上限 {limit} 个），等它们转完再导入转写稿"
                )
            raise HTTPException(409, f"最多同时排队 {limit} 个文件，请等前面的转写完成后再添加")
        capacity = self.capacity()
        left = capacity["free_bytes"] - capacity["arriving_bytes"] - body.size
        if left < capacity["headroom_bytes"]:
            raise HTTPException(
                507,
                f"磁盘空间不足：添加后可用空间会低于 {self.settings.library.headroom_gb:g} GB 的安全余量，"
                "请联系管理员扩容",
            )

    def finish(self, viewer: Viewer, upload_id: str) -> dict[str, Any]:
        """File a finished upload. The same meeting uploaded before by someone else stays theirs to decide about
        (``mine`` is false)."""
        owner = TEAM
        uploads = self.uploads(viewer)
        info = uploads.load(upload_id)
        if info["offset"] != info["size"]:
            raise HTTPException(400, "文件尚未上传完成")
        library = self.library(owner)
        if info.get("recording_id"):
            existing = library.get(info["recording_id"])
            if existing is None:
                raise HTTPException(404, "这段录音已删除，请重新上传")
            return self.filed(viewer, existing, False)
        _, part = uploads.paths(upload_id)
        recording, new = library.add(part, info["filename"], uploader=viewer.key, sha=uploads.digest(upload_id))
        info["recording_id"] = recording.id
        uploads.save(upload_id, info)
        self.kick(owner)
        return self.filed(viewer, library.get(recording.id) or recording, new)

    def filed(self, viewer: Viewer, recording: Recording, new: bool) -> dict[str, Any]:
        if viewer.admin or recording.uploader == viewer.key:
            return {**view(recording), "new": new, "mine": True}
        # A colleague's: the uploader learns no more of it than that it is there.
        return {"id": recording.id, "filename": recording.filename, "new": False, "mine": False}

    def status(self, owner: str, viewer: Viewer) -> dict[str, Any]:
        """The recordings the viewer may see, with what is still waiting (``max_pending`` limits each member's own
        uploads)."""
        self.wake(owner)
        quota = self.quota(owner)
        library = self.library(owner)
        access = self.access(viewer)
        recordings = [r for r in library.list() if r.id in access]
        identities = self.team(owner).identities()
        waiting = {r.id for r in library.unproofread()}
        with self.lock:
            now = self.proofreading_now.get(owner)
            held_twins = len(self.paused.get(owner, ())) if quota["exhausted"] else 0
        synced = self.team(owner).synced()
        return {
            "recordings": [
                {
                    **self.view(r),
                    # Who was recognised, and how many speakers still wait for the owner.
                    "people": identities.get(r.id, ([], 0))[0],
                    "unsettled": max(0, r.speakers - identities.get(r.id, ([], 0))[1]) if r.status == "ready" else 0,
                    **self.proofread_view(library, r, waiting, now),
                    "can_edit": access[r.id].edit,
                    # A failed one: whether it can be retried, and whether its file wants uploading again.
                    **(
                        {"retryable": library.retryable(r), "reupload": library.reupload(r)}
                        if r.status == "failed"
                        else {}
                    ),
                }
                for r in recordings
            ],
            "pending": sum(r.status in {"queued", "transcribing"} for r in recordings),
            "max_pending": self.settings.library.max_pending,
            "asr": isinstance(make_transcriber(self.settings.asr), CommandTranscriber),
            "capacity": self.capacity(),
            # What waits for the quota: recordings to proofread and twins to rebuild.
            "quota": {**quota, "waiting_proofread": len(waiting), "waiting_twins": held_twins},
            # Twins being rebuilt, and a number that moves whenever one starts or finishes: a rebuild started by
            # someone else or at start-up changes no recording, and the team page would not ask for people again.
            "twins": {
                "updating": sum(wanted != done for _, _, wanted, done in synced),
                "revision": sum(wanted + done for _, _, wanted, done in synced),
            },
        }


def only_adds(store: PersonaStore, wanted: Mapping[str, ParsedSource], done: int) -> bool:
    """Whether the twin holds the sources of its last complete build (``done``) and each of them is still wanted
    as it is: what changed since only adds recordings, so nothing it would answer from was taken away."""
    if not done or store.get_meta(gate.SYNCED) != str(done):
        return False
    return all(
        source.source_id in wanted and store.holds(wanted[source.source_id])
        for source in store.list_sources()
        if source.source_id.startswith(SOURCE_PREFIX)
    )


def parsed_source(source: TwinSource) -> ParsedSource:
    """A library recording as one of a twin's sources: numbered like the transcript (so evidence cites its
    segments), dated by the meeting."""
    return parse_media(
        Source(
            source_id=source.source_id,
            kind=SourceKind.VIDEO if source.kind == "video" else SourceKind.AUDIO,
            title=source.title,
            origin=source.origin,
            imported_at=dt.datetime.now(dt.UTC).isoformat(),
            n_expressions=0,
            n_target=0,
            text_state="raw",
            duration_s=source.duration_s,
            creation_time=source.date,
            media_status="ready",
        ),
        source.lines,
    )


def view(recording: Recording) -> dict[str, Any]:
    return recording.model_dump(mode="json", exclude={"sha256"})


def register(
    app: FastAPI,
    settings: Settings,
    jobs: JobManager,
    registry: Personas | None = None,
    llm: Callable[[], LLM] | None = None,
    limits: Callable[[], tuple[int, float]] | None = None,
    teamdb: TeamDB | None = None,
) -> Libraries:
    libraries = Libraries(settings, jobs, registry, llm, limits, teamdb)
    app.state.libraries = libraries

    @app.get("/api/library")
    def get_library(request: Request) -> dict[str, Any]:
        return libraries.status(libraries.owner(request), libraries.viewer(request))

    upload_routes(
        app,
        "/api/library/uploads",
        lambda request: libraries.uploads(libraries.viewer(request)),
        lambda request, upload_id: libraries.finish(libraries.viewer(request), upload_id),
        admit=lambda request, uploads, body: libraries.admit(libraries.viewer(request), body),
    )

    async def transcript_file(file: UploadFile) -> tuple[str, bytes]:
        name = (file.filename or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
        if not name or name.startswith("."):
            raise HTTPException(400, "文件名无效")
        data = await file.read(MAX_TRANSCRIPT_BYTES + 1)
        if len(data) > MAX_TRANSCRIPT_BYTES:
            raise HTTPException(413, "转写稿太大，请选择 20 MB 以内的文件")
        if not data:
            raise HTTPException(400, "这个文件是空的")
        return name, data

    @app.post("/api/library/transcripts/preview")
    async def preview_transcript(request: Request, file: Annotated[UploadFile, File()]) -> dict[str, Any]:
        """What a transcript file holds and who its speakers would be, before anything is brought in."""
        name, data = await transcript_file(file)
        return await run_in_threadpool(
            libraries.transcript_preview, libraries.owner(request), libraries.viewer(request), name, data
        )

    @app.post("/api/library/transcripts", status_code=201)
    async def import_transcript(
        request: Request, file: Annotated[UploadFile, File()], payload: Annotated[str, Form()] = "{}"
    ) -> dict[str, Any]:
        """Bring a transcript in as a recording that has no sound: its speakers are given to the members they are
        named for or the importer chose, and the rest wait to be settled."""
        try:
            body = TranscriptBody.model_validate_json(payload)
        except ValidationError:
            raise HTTPException(400, "导入内容格式无效") from None
        name, data = await transcript_file(file)
        owner, viewer = libraries.owner(request), libraries.viewer(request)
        return await run_in_threadpool(libraries.import_transcript, owner, viewer, name, data, body)

    @app.post("/api/library/recordings/{recording_id}/retry", status_code=202)
    def retry(recording_id: str, request: Request) -> dict[str, Any]:
        owner = libraries.owner(request)
        libraries.allowed(libraries.viewer(request), recording_id, edit=True)
        recording = libraries.library(owner).retry(recording_id)
        if recording is None:
            raise HTTPException(409, "只有转写失败、原始文件还在的录音可以重试")
        libraries.kick(owner)
        return view(recording)

    @app.get("/api/library/recollect")
    def get_recollect(request: Request) -> dict[str, Any]:
        return libraries.recollection(libraries.owner(request), libraries.viewer(request))

    @app.post("/api/library/recollect", status_code=202)
    def post_recollect(body: RecollectBody, request: Request) -> dict[str, Any]:
        """Ask for recordings to be transcribed again by the current service; all the viewer may, without a list."""
        owner, viewer = libraries.owner(request), libraries.viewer(request)
        editable = {rid for rid, access in libraries.access(viewer).items() if access.edit}
        wanted = editable if body.recordings is None else set(body.recordings) & editable
        asked = recollect.ask(libraries.library(owner), wanted)
        libraries.kick(owner)
        return {"asked": asked}

    @app.post("/api/library/recordings/{recording_id}/rollback")
    def rollback(recording_id: str, request: Request) -> dict[str, Any]:
        """Go back to the transcript before the recording was last transcribed again."""
        owner = libraries.owner(request)
        libraries.allowed(libraries.viewer(request), recording_id, edit=True)
        if not recollect.rollback(libraries.library(owner), recording_id):
            raise HTTPException(409, "这段录音没有可以回退的上一份转写")
        libraries.changed(owner)
        recording = libraries.library(owner).get(recording_id)
        assert recording is not None
        return view(recording)

    @app.delete("/api/library/recordings/{recording_id}")
    async def delete(recording_id: str, request: Request) -> dict[str, bool]:
        owner = libraries.owner(request)
        await run_in_threadpool(libraries.allowed, libraries.viewer(request), recording_id, True)
        if not await run_in_threadpool(libraries.library(owner).delete, recording_id):
            raise HTTPException(409, "这段录音正在转写，请稍后再删除")
        libraries.changed(owner)
        return {"deleted": True}

    @app.get("/api/library/recordings/{recording_id}")
    def get_recording(recording_id: str, request: Request) -> dict[str, Any]:
        return libraries.detail(libraries.owner(request), recording_id, libraries.viewer(request))

    @app.get("/api/library/recordings/{recording_id}/speakers/{speaker_id}/samples/{index}")
    def get_sample(
        recording_id: str, speaker_id: str, index: int, request: Request, original: bool = False
    ) -> FileResponse:
        return libraries.sample(
            libraries.owner(request), recording_id, speaker_id, index, libraries.viewer(request), original
        )

    @app.put("/api/library/recordings/{recording_id}/speakers/{speaker_id}")
    def put_speaker(recording_id: str, speaker_id: str, body: DecisionBody, request: Request) -> dict[str, Any]:
        # Whoever decides about the recording may give a speaker to anyone in the team.
        libraries.allowed(libraries.viewer(request), recording_id, edit=True)
        return libraries.decide(libraries.owner(request), recording_id, speaker_id, body)

    @app.get("/api/library/recordings/{recording_id}/speakers/{speaker_id}/units")
    def get_units(recording_id: str, speaker_id: str, request: Request) -> dict[str, Any]:
        libraries.allowed(libraries.viewer(request), recording_id, edit=True)
        return libraries.units(libraries.owner(request), recording_id, speaker_id)

    @app.put("/api/library/recordings/{recording_id}/speakers/{speaker_id}/units")
    def put_units(recording_id: str, speaker_id: str, body: UnitsBody, request: Request) -> dict[str, Any]:
        libraries.allowed(libraries.viewer(request), recording_id, edit=True)
        return libraries.fix(libraries.owner(request), recording_id, speaker_id, body)

    @app.get("/api/library/recordings/{recording_id}/speakers/{speaker_id}/units/{index}/clip")
    def get_unit_clip(
        recording_id: str, speaker_id: str, index: int, request: Request, original: bool = False
    ) -> FileResponse:
        libraries.allowed(libraries.viewer(request), recording_id, edit=True)
        return libraries.unit_clip(libraries.owner(request), recording_id, speaker_id, index, original)

    @app.post("/api/library/recordings/{recording_id}/speakers/{speaker_id}/not-me")
    def not_me(recording_id: str, speaker_id: str, request: Request) -> dict[str, bool]:
        """Someone identified in the recording says a speaker given to them is not them: it is undone and waits
        for whoever decides about the recording, at the top of their queue."""
        owner = libraries.owner(request)
        viewer = libraries.viewer(request)
        libraries.allowed(viewer, recording_id)
        try:
            libraries.team(owner).dispute(recording_id, speaker_id, libraries.people_of(viewer))
        except ValueError as e:
            raise HTTPException(409, str(e)) from None
        libraries.changed(owner)
        return {"disputed": True}

    @app.get("/api/library/review")
    def get_review(
        request: Request,
        voices: Annotated[int | None, Query(ge=0, le=MAX_REVIEW_PAGE)] = None,
        once: Annotated[int | None, Query(ge=0, le=MAX_REVIEW_PAGE)] = None,
        enough: Annotated[int | None, Query(ge=0, le=MAX_REVIEW_PAGE)] = None,
        strangers: Annotated[int | None, Query(ge=0, le=MAX_REVIEW_PAGE)] = None,
        items: Annotated[int | None, Query(ge=0, le=MAX_REVIEW_PAGE)] = None,
        unsorted: Annotated[int | None, Query(ge=0, le=MAX_REVIEW_PAGE)] = None,
        suspects: Annotated[int | None, Query(ge=0, le=MAX_REVIEW_PAGE)] = None,
        stale: bool = False,
    ) -> dict[str, Any]:
        """What the viewer settles about the recordings they decide about: speakers someone said are not them
        (``items``), undecided speakers grouped by voice across recordings so each colleague is asked about once
        (``voices``), the short voices like nobody, to set aside together (``fragments``), and recordings whose
        speakers have no voiceprint to group by, settled one by one (``unsorted``), with how much of their speech
        is settled (``heard``). All from one reading, so the page never infers a task from an older list of
        recordings. Each list is the first so many asked for (``review_queue.page``; all without a number), with how
        many it holds in all (``totals``): the page shows a few of each and asks for more as the owner scrolls.
        With ``stale`` the latest reading comes at once, marked ``stale`` when the library changed since: the page
        shows it and asks again without ``stale`` for the current one, which is meanwhile worked out."""
        editable = {rid for rid, access in libraries.access(libraries.viewer(request)).items() if access.edit}
        limits = {
            "voices": voices,
            "once": once,
            "enough": enough,
            "strangers": strangers,
            "items": items,
            "unsorted": unsorted,
            "suspects": suspects,
        }
        reading, earlier = libraries.review(libraries.owner(request), editable, stale)
        return {**page(reading, limits), "stale": earlier}

    @app.post("/api/library/voices")
    def post_voice(body: VoiceBody, request: Request) -> dict[str, Any]:
        viewer = libraries.viewer(request)
        for recording_id in {m.recording_id for m in body.members}:
            libraries.allowed(viewer, recording_id, edit=True)
        return libraries.decide_voice(libraries.owner(request), body)

    @app.get("/api/library/people")
    def get_people(request: Request) -> dict[str, Any]:
        """Everyone in the team's meetings, so whoever names a speaker can pick a colleague named elsewhere; where
        they speak only for recordings the viewer may see, and their twin only for those who manage it."""
        owner = libraries.owner(request)
        viewer = libraries.viewer(request)
        identity = request.scope["twin_identity"]
        team = libraries.team(owner)
        # Every twin is a row of the team's table: the ones nobody made from recordings get a person.
        libraries.adopt_personas()
        synced = {persona_id: (wanted, done) for persona_id, _, wanted, done in team.synced()}
        behind = team.answering_behind()
        visible = libraries.access(viewer)
        managed = libraries.managed(viewer)
        similar = team.similar()
        meetings = team.last_meetings(set(visible))
        # What the viewer may spot-check: speakers given by voice in recordings they decide about.
        checks = None if viewer.admin else team.check_counts({rid for rid, a in visible.items() if a.edit})
        people = []
        for person in team.people():
            entry = registry.entry(person.persona_id) if person.persona_id and registry is not None else None
            # The person found themselves here by voice: the twin is theirs, not the library's to open.
            theirs = bool(entry and entry.get("by_voice"))
            opens = bool(entry and not theirs and registry is not None and registry.accessible(entry, identity))
            state = synced.get(person.persona_id or "")
            updating = bool(opens and state and state[0] != state[1])
            heard = person.recording_id in visible
            listed = bool(entry and registry is not None and registry.visible(entry, identity))
            talks = bool(listed and not theirs)
            people.append(
                {
                    **person.model_dump(exclude={"account"}),
                    "recording_id": person.recording_id if heard else None,
                    "speaker_id": person.speaker_id if heard else None,
                    "persona_id": person.persona_id if opens else None,
                    # The twin the viewer may talk to: theirs to manage, or one made public.
                    "talk": person.persona_id if talks else None,
                    # The twin where the viewer's own list of twins has it, whether or not it is theirs to open or
                    # talk to (a person's own twin found by voice is neither): so that no twin has two rows.
                    "twin_id": person.persona_id if listed else None,
                    # Their introduction's first line, where the twin is one the viewer may talk to or look after.
                    "about": self_introduction(registry, person.persona_id) if talks or opens else None,
                    "updating": updating,
                    # While its rebuild waits: whether it answers from its last build (the change only adds
                    # recordings), and whether the switched-off automatic rebuild holds it.
                    "answers_behind": bool(updating and person.persona_id in behind),
                    "held": bool(updating and person.persona_id and libraries.held(owner, person.persona_id)),
                    # Where the update is (step and how far), shown on the card until the twin can talk.
                    "build": libraries.build_status(person.persona_id) if updating and person.persona_id else None,
                    # The latest meeting among the recordings the viewer may see.
                    "last_meeting": meetings[person.id].model_dump() if person.id in meetings else None,
                    "self_claimed": theirs,
                    # A twin someone else keeps: not the viewer's to make again or delete.
                    "twin_elsewhere": bool(entry and not theirs and not opens),
                    "can_manage": managed is None or person.id in managed,
                    "checks": person.checks if checks is None else checks.get(person.id, 0),
                    # Administrators settle who may be the same person.
                    "similar": [b if a == person.id else a for a, b in similar if person.id in (a, b)]
                    if viewer.admin
                    else [],
                }
            )
        return {"items": people, "matches": libraries.twin_matches(identity, managed)}

    @app.post("/api/library/people/{person_id}/same")
    def post_same(person_id: str, body: SameBody, request: Request) -> dict[str, bool]:
        """Whoever keeps a twin made by hand says whether it is the person of its name in the meetings: if so the two
        are joined; if not, the twin stays a row of its own and is not asked about again."""
        if registry is None:
            raise HTTPException(503, "无法确认")
        identity = request.scope["twin_identity"]
        entry = registry.entry(body.persona_id)
        if entry is None or not registry.accessible(entry, identity):
            raise HTTPException(404, "分身不存在")
        # Joining them makes the twin speak for the person: only whoever may make that person's twin may say so.
        managed = libraries.managed(libraries.viewer(request))
        match = next((m for m in libraries.twin_matches(identity, managed) if m["persona_id"] == body.persona_id), None)
        if match is None or match["person_id"] != person_id:
            if managed is not None and person_id not in managed and libraries.team(TEAM).person(person_id):
                raise HTTPException(403, "只有上传了 TA 所在录音的同事或管理员可以确认是不是同一个人")
            raise HTTPException(409, "这个分身和这个人对不上了，请刷新后再看")
        if body.same:
            if not libraries.team(TEAM).attach(person_id, body.persona_id):
                raise HTTPException(409, "这个人或这个分身已经有对应的了")
        elif libraries.teamdb is not None:
            libraries.teamdb.set_meta(f"{APART}{body.persona_id}", person_id)
        return {"same": body.same}

    @app.get("/api/library/people/{person_id}/voice")
    def get_person_voice(person_id: str, request: Request) -> dict[str, Any]:
        """The person's voice samples and the speakers given to them by voice alone, least sure first, in the
        recordings the viewer decides about (``Team.samples``, ``Team.checks``)."""
        viewer = libraries.viewer(request)
        libraries.manage(viewer, person_id)
        team = libraries.team(libraries.owner(request))
        if team.person(person_id) is None:
            raise HTTPException(404, "找不到这个人")
        editable = None if viewer.admin else {rid for rid, a in libraries.access(viewer).items() if a.edit}
        return {
            "samples": [s.model_dump() for s in team.samples(person_id, editable)],
            "checks": [c.model_dump() for c in team.checks(person_id, editable)],
        }

    @app.delete("/api/library/people/{person_id}/samples/{sample_id}")
    def delete_sample(person_id: str, sample_id: int, request: Request) -> dict[str, int]:
        """A voice sample does not stand for the person: what it gave them goes back to the owner."""
        owner = libraries.owner(request)
        viewer = libraries.viewer(request)
        libraries.manage(viewer, person_id)
        team = libraries.team(owner)
        sample = next((s for s in team.samples(person_id) if s.id == sample_id), None)
        if sample is None:
            raise HTTPException(404, "找不到这段声线")
        libraries.allowed(viewer, sample.recording_id, edit=True)
        back = team.remove_sample(person_id, sample_id)
        if back is None:
            raise HTTPException(404, "找不到这段声线")
        libraries.changed(owner)
        return {"returned": back}

    @app.post("/api/library/people", status_code=201)
    def post_person(body: PersonBody, request: Request) -> dict[str, Any]:
        try:
            person = libraries.team(libraries.owner(request)).add_person(body.name)
        except ValueError as e:
            raise HTTPException(409, str(e)) from None
        return person.model_dump(exclude={"account"})

    @app.patch("/api/library/people/{person_id}")
    def patch_person(person_id: str, body: PersonPatch, request: Request) -> dict[str, Any]:
        libraries.manage(libraries.viewer(request), person_id)
        return libraries.update(libraries.owner(request), person_id, body)

    @app.post("/api/library/people/{person_id}/resolve")
    def resolve_person(person_id: str, body: ResolveBody, request: Request) -> dict[str, bool]:
        owner = libraries.owner(request)
        libraries.manage(libraries.viewer(request), person_id)
        try:
            libraries.team(owner).resolve(person_id, body.into)
        except ValueError as e:
            raise HTTPException(409, str(e)) from None
        if body.into:
            # The voice samples they bring can settle speakers in other recordings.
            libraries.team(owner).classify_all()
        libraries.changed(owner)
        libraries.proofread(owner)
        return {"resolved": True}

    @app.post("/api/library/people/{person_id}/merge")
    def merge_person(person_id: str, body: MergeBody, request: Request) -> dict[str, bool]:
        """An administrator takes two people for one (``Team.merge``)."""
        owner = libraries.owner(request)
        if not libraries.viewer(request).admin:
            raise HTTPException(403, "只有管理员可以合并两个人")
        try:
            libraries.team(owner).merge(person_id, body.into)
        except ValueError as e:
            raise HTTPException(409, str(e)) from None
        libraries.team(owner).classify_all()
        libraries.changed(owner)
        return {"merged": True}

    @app.post("/api/library/people/{person_id}/apart")
    def keep_apart(person_id: str, body: ApartBody, request: Request) -> dict[str, bool]:
        """An administrator says two people who may be one are two."""
        if not libraries.viewer(request).admin:
            raise HTTPException(403, "只有管理员可以处理")
        libraries.team(libraries.owner(request)).keep_apart(person_id, body.other)
        return {"apart": True}

    @app.get("/api/library/voice-clashes")
    def get_voice_clashes(request: Request) -> list[dict[str, Any]]:
        """Voice samples of two people that sound nearly alike, for an administrator to hear
        (``Team.voice_clashes``)."""
        if not libraries.viewer(request).admin:
            raise HTTPException(403, "只有管理员可以核对声线")
        return [c.model_dump() for c in libraries.team(libraries.owner(request)).voice_clashes()]

    @app.post("/api/library/voice-clashes/apart")
    def voice_clash_apart(body: SamplesApartBody, request: Request) -> dict[str, bool]:
        """An administrator heard two clashing voice samples and both are right."""
        if not libraries.viewer(request).admin:
            raise HTTPException(403, "只有管理员可以核对声线")
        libraries.team(libraries.owner(request)).samples_apart(*body.samples)
        return {"apart": True}

    @app.post("/api/library/voice-clashes/remove")
    def voice_clash_remove(body: ClashRemoveBody, request: Request) -> dict[str, int]:
        """An administrator heard which of two clashing voice samples is someone else: it stops standing for its
        person, and the voices it held back are classified again (``Team.classify_all``)."""
        owner = libraries.owner(request)
        if not libraries.viewer(request).admin:
            raise HTTPException(403, "只有管理员可以核对声线")
        team = libraries.team(owner)
        with team.library.read() as db:
            row = db.execute(
                "SELECT person_id FROM voiceprints WHERE id = ? AND active = 1", (body.sample_id,)
            ).fetchone()
        back = team.remove_sample(row[0], body.sample_id) if row else None
        if back is None:
            raise HTTPException(404, "找不到这段声线")
        recognised = team.classify_all()
        libraries.changed(owner)
        return {"returned": back, "recognised": recognised}

    @app.delete("/api/library/people/{person_id}")
    def delete_person(person_id: str, request: Request) -> dict[str, bool]:
        owner = libraries.owner(request)
        libraries.manage(libraries.viewer(request), person_id)
        team = libraries.team(owner)
        person = team.person(person_id)
        # A deleted twin (in the trash) keeps its person only to come back to them if restored; deleting the
        # person lets it go, as the page offers once the twin is gone.
        if person and person.persona_id and libraries.registry and libraries.registry.entry(person.persona_id) is None:
            team.unlink(person.persona_id)
        if not team.delete_person(person_id):
            raise HTTPException(409, "这个人已经有分身，请先删除分身")
        libraries.changed(owner)
        return {"deleted": True}

    @app.post("/api/library/people/{person_id}/persona")
    def post_twin(person_id: str, request: Request, body: ClaimBody | None = None) -> dict[str, Any]:
        if registry is None:
            raise HTTPException(503, "无法创建分身")
        owner = libraries.owner(request)
        libraries.manage(libraries.viewer(request), person_id)
        claim = claim_key(body.claim if body else None)
        return libraries.create_twin(owner, person_id, request.scope["twin_identity"], claim)

    @app.post("/api/library/people/{person_id}/rebuild", status_code=202)
    def rebuild_twin(person_id: str, request: Request) -> dict[str, bool]:
        """Try again the twin of a person whose memory update did not complete, for whoever may open it."""
        person = libraries.team(libraries.owner(request)).person(person_id)
        entry = registry.entry(person.persona_id) if registry is not None and person and person.persona_id else None
        if (
            registry is None
            or person is None
            or person.persona_id is None
            or entry is None
            or entry.get("by_voice")
            or not registry.accessible(entry, request.scope["twin_identity"])
        ):
            raise HTTPException(404, "找不到这个分身")
        libraries.rebuild(person.persona_id)
        return {"queued": True}

    return libraries
