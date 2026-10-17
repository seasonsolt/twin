"""``/api/library``: the signed-in account's recording library, outside any one twin.

Only the account that uploaded a recording can see it. Recordings are transcribed one after another in the shared
media slot (so a library batch and a twin's own recordings take turns on the transcription service); the queue
lives in ``library.db``, so a restart picks up where it stopped.

The owner then says who each speaker is, and creates twins of those people. A twin made from the library is kept
in line with it by ``sync``: its recording sources are rewritten from the library's current decisions and an
ordinary build follows; the twin answers again only once a build of exactly that state has succeeded
(``persona.gate``).

Once someone in a recording is identified, its transcript is proofread by the language model, once, in the same
media slot; the corrected words then replace the recognized ones in every twin it feeds, which are rebuilt. What
the library spends on the model (proofreading, and the builds of its twins) counts against a batch quota
(``LibrarySettings.batch_tokens`` per ``batch_hours``); once it is spent, proofreading and rebuilds wait, and the
library's status says so.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import logging
import math
import shutil
import threading
import time
import uuid
from collections.abc import Callable
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from ..config import Settings
from ..llm import LLM
from ..media.claim import Analysis, cut, sample_windows
from ..media.clean import BATCH, clean_segments
from ..media.ingest import CommandTranscriber, make_transcriber
from ..media.library import Cleaned, Library, Recording, TranscriptionError, owner_key
from ..media.schema import AVATAR_GENDERS, default_avatar
from ..media.team import SOURCE_PREFIX, Gender, Stale, Team, TwinSource
from ..persona import gate
from ..persona.schema import ParsedSource, Source, SourceKind
from ..persona.sources import parse_media
from ..persona.store import PersonaStore, stored_avatar, stored_identity
from ..usage import CallRow, collect_calls, model_tokens
from .jobs import Job, JobError, JobManager, Log, TooManyJobs
from .personas import Personas
from .uploads import UploadBody, Uploads, upload_routes

logger = logging.getLogger(__name__)

GIB = 1024**3
# Waits before rewriting a twin's sources again after a failed attempt; after the last, the twin stays closed until
# the next change or restart.
SYNC_RETRY_SECONDS = (5.0, 30.0, 120.0, 600.0)
# How often every library is woken without anyone looking: twins held for the quota are rebuilt and proofreading
# goes on once the quota frees up, even if nobody opens the library page.
WAKE_SECONDS = 60.0


class PersonBody(BaseModel):
    name: str = Field(min_length=1, max_length=40)


class PersonPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=40)
    gender: Gender | None = None


class DecisionBody(BaseModel):
    transcript_id: str
    revision: int
    action: Literal["confirm", "unknown", "mixed", "reject", "clear"]
    person_id: str | None = None
    # Confirm as a new person of this name instead of ``person_id``.
    new_person: str | None = Field(default=None, max_length=40)
    # Also keep this speaker's voice as one of the person's samples.
    sample: bool = False


class Libraries:
    def __init__(
        self,
        settings: Settings,
        jobs: JobManager,
        registry: Personas | None = None,
        llm: Callable[[], LLM] | None = None,
    ) -> None:
        self.settings, self.jobs, self.registry, self.llm = settings, jobs, registry, llm
        self.root = settings.db_path.parent / "library"
        self.lock = threading.RLock()
        self.opened: dict[str, Library] = {}
        # The transcription job of each owner; the next recording is queued when it ends.
        self.running: dict[str, Job] = {}
        # Twins whose sources are being rewritten, and those changed again meanwhile (rewritten once more after).
        self.syncing: set[str] = set()
        self.again: set[str] = set()
        # The proofreading job of each owner, and per owner the twins whose rebuild waits for the quota.
        self.proofreading: dict[str, Job] = {}
        self.paused: dict[str, set[str]] = {}
        self._stop = threading.Event()
        self._waker: threading.Thread | None = None

    def owner(self, request: Request) -> str:
        return owner_key(request.scope["twin_identity"]["email"])

    def library(self, owner: str) -> Library:
        with self.lock:
            if owner not in self.opened:
                self.opened[owner] = Library(self.root / owner)
            return self.opened[owner]

    def uploads(self, owner: str) -> Uploads:
        return Uploads(self.library(owner).root)

    def resume(self) -> None:
        """At start-up: recordings cut off by the last shutdown are queued again, every queue starts, and twins
        still waiting for a change are brought in line."""
        if not self.root.is_dir():
            return
        owners = []
        for folder in sorted(self.root.iterdir()):
            if not (folder / "library.db").is_file():
                continue
            if self.library(folder.name).resume():
                self.kick(folder.name)
            owners.append(folder.name)
        # Reading every transcript of years of meetings must not hold up start-up.
        threading.Thread(target=self._settle, args=(owners,), name="library-settle", daemon=True).start()

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

    def _wake_all(self) -> None:
        while not self._stop.wait(WAKE_SECONDS):
            with self.lock:
                owners = sorted(self.opened)
            for owner in owners:
                try:
                    self.wake(owner)
                except Exception:
                    logger.exception("library of %s could not be woken", owner)

    def wake(self, owner: str) -> None:
        """Carry on with what waits: once the quota has room, the twins held for it are rebuilt; the next
        recording is transcribed and the next proofread."""
        if not self.quota(owner)["exhausted"]:
            with self.lock:
                held = self.paused.pop(owner, set())
            for persona_id in sorted(held):
                self.sync(owner, persona_id)
        self.kick(owner)

    def _settle(self, owners: list[str]) -> None:
        """Classify recordings transcribed before a crash (or before automatic classification existed), then bring
        every waiting twin in line."""
        for owner in owners:
            try:
                self.team(owner).classify_all()
                self.changed(owner)
            except Exception:
                logger.exception("library of %s could not be settled after start-up", owner)

    # ------------------------------------------------------------ twins

    def team(self, owner: str) -> Team:
        return Team(self.library(owner))

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
        _, person_id, wanted, _ = row
        if self.quota(owner)["exhausted"]:
            # The twin stays closed; ``status`` rewrites it once the quota frees up.
            with self.lock:
                self.paused.setdefault(owner, set()).add(persona_id)
            return False
        db_path = self.registry.settings_for(persona_id).db_path
        person = team.person(person_id)
        name = stored_identity(db_path)[0] or (person.name if person else self.settings.target_name)
        wanted_sources = {source.source_id: parsed_source(source) for source in team.sources(person_id, name)}
        with PersonaStore(db_path) as store:
            for source in store.list_sources():
                if source.source_id.startswith(SOURCE_PREFIX) and source.source_id not in wanted_sources:
                    store.delete_source(source.source_id)
            for parsed in wanted_sources.values():
                store.put_source(parsed)
            store.clear_source_errors()
            # After the sources: a build that reads this version has read these sources.
            store.set_meta(gate.SYNCED, str(wanted))
        self.registry.application(persona_id).state.processing.queue()
        return True

    def built(self, persona_id: str, version: int) -> None:
        """A twin's build from ``version`` completed: open it, or rewrite it when something changed meanwhile."""
        entry = self.registry.entry(persona_id) if self.registry is not None else None
        if entry is None:
            return
        owner = owner_key(entry.get("owner"))
        team = self.team(owner)
        if team.wanted(persona_id) is not None and not team.built(persona_id, version):
            self.sync(owner, persona_id)

    def spent_building(self, persona_id: str, tokens: int) -> None:
        """A build of a twin made from a library ended: what it spent counts against that library's quota."""
        entry = self.registry.entry(persona_id) if self.registry is not None else None
        if entry is None:
            return
        library = self.library(owner_key(entry.get("owner")))
        if Team(library).wanted(persona_id) is not None:
            library.spend("rebuild", tokens)

    # ------------------------------------------------------------ quota and proofreading

    def quota(self, owner: str) -> dict[str, Any]:
        """The owner's batch quota: tokens spent in the last ``batch_hours``, and whether that leaves none, in
        which case ``resets_at`` says when the oldest of them leaves the window."""
        limit, hours = self.settings.library.batch_tokens, self.settings.library.batch_hours
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
            waiting = self.library(owner).unproofread()
            if not waiting or self.quota(owner)["exhausted"]:
                return
            try:
                self.llm()
            except Exception:
                return
            recording = waiting[0]
            with contextlib.suppress(TooManyJobs):
                self.proofreading[owner] = self.jobs.scoped(f"library:{owner}").submit(
                    "media_ingest",
                    f"校对 {recording.filename}",
                    lambda log: self.run_proofread(owner, recording.id, log),
                )

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
            self.proofread(owner)

    def proofread_state(self, library: Library, recording: Recording, waiting: set[str]) -> str:
        """``done`` (corrections filed), ``failed`` (the model was asked and gave none), ``waiting`` (someone is
        identified and proofreading is still to come) or empty."""
        path = library.clean_path(recording)
        if path is not None and path.is_file():
            return "done"
        if recording.transcript_id and recording.proofread == recording.transcript_id:
            return "failed"
        return "waiting" if recording.id in waiting else ""

    def create_twin(self, owner: str, person_id: str, identity: dict[str, Any]) -> dict[str, Any]:
        """The person's twin, created on first call: private, owned by the account, answering as a meeting record
        once its first build completes."""
        assert self.registry is not None
        team = self.team(owner)
        with self.lock:
            person = team.person(person_id)
            if person is None:
                raise HTTPException(404, "找不到这个人")
            if person.persona_id and self.registry.entry(person.persona_id) is not None:
                return {"persona_id": person.persona_id, "new": False}
            entry = self.registry.create(person.name, identity, onboarding=False)
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
        self.proofread(owner)
        return {"revision": revision, "person_id": person_id}

    def update(self, owner: str, person_id: str, body: PersonPatch) -> dict[str, Any]:
        team = self.team(owner)
        try:
            if body.gender is not None:
                persona_id = team.set_gender(person_id, body.gender)
                if persona_id:
                    self.dress(persona_id, body.gender)
            if body.name is not None:
                persona_id = team.rename(person_id, body.name)
                if persona_id and self.registry is not None and self.registry.entry(persona_id) is not None:
                    with PersonaStore(self.registry.settings_for(persona_id).db_path) as store:
                        store.set_meta("identity:name", " ".join(body.name.split()))
                self.changed(owner)
        except ValueError as e:
            raise HTTPException(409 if "已经有" in str(e) else 400, str(e)) from None
        return {"updated": True}

    def dress(self, persona_id: str, gender: str) -> None:
        """Give the twin an illustration of the person's gender, unless the one it shows already is."""
        if not gender or self.registry is None or self.registry.entry(persona_id) is None:
            return
        settings = self.registry.settings_for(persona_id)
        if AVATAR_GENDERS[stored_avatar(settings.db_path, settings.avatar.preset)] != gender:
            with PersonaStore(settings.db_path) as store:
                store.set_meta("identity:avatar_preset", default_avatar(persona_id, gender))

    def detail(self, owner: str, recording_id: str) -> dict[str, Any]:
        library = self.library(owner)
        recording = library.get(recording_id)
        if recording is None:
            raise HTTPException(404, "找不到这段录音")
        transcript = library.cleaned(recording)
        analysis = Analysis(segments=transcript.segments, speakers=transcript.speakers) if transcript else None
        waiting = {r.id for r in library.unproofread()}
        return {
            **view(recording),
            "proofread": self.proofread_state(library, recording, waiting),
            "speakers": [
                {**s.model_dump(), "samples": len(sample_windows(analysis, s.id)) if analysis else 0}
                for s in self.team(owner).speakers(recording)
            ],
            "segments": [
                {"start": s.start, "end": s.end, "text": s.text, "speaker": s.speaker}
                for s in (transcript.segments if transcript else [])
            ],
        }

    def sample(self, owner: str, recording_id: str, speaker_id: str, index: int) -> FileResponse:
        """A five-second WAV of the speaker (up to three, at different moments), cut from the playback copy and
        kept in the library's media cache, which backups skip."""
        library = self.library(owner)
        recording = library.get(recording_id)
        transcript = library.transcript(recording) if recording else None
        if recording is None or transcript is None:
            raise HTTPException(404, "找不到这段录音")
        windows = sample_windows(Analysis(segments=transcript.segments, speakers=transcript.speakers), speaker_id)
        if not 0 <= index < len(windows):
            raise HTTPException(404, "没有这段试听")
        cache = library.root / "media-cache" / recording.id
        target = cache / f"{transcript.id}-{speaker_id}-{index}.wav"
        if not target.is_file():
            cache.mkdir(parents=True, mode=0o700, exist_ok=True)
            # ffmpeg picks the format from the suffix; a name of its own keeps two plays from sharing one file.
            temporary = target.with_name(f".{uuid.uuid4().hex}.tmp.wav")
            try:
                cut(library.folder(recording.id) / "playback.flac", temporary, *windows[index])
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
        return FileResponse(target, media_type="audio/wav", headers={"Cache-Control": "private, max-age=3600"})

    def kick(self, owner: str) -> None:
        """Start transcribing the owner's next queued recording unless one is already running. Without a diarizing
        transcription service, or with the job queue full, recordings stay queued; the next status poll tries
        again. Proofreading waiting for its turn starts too."""
        self.proofread(owner)
        with self.lock:
            job = self.running.get(owner)
            if job is not None and job.active:
                return
            recording = self.library(owner).next_queued()
            if recording is None or not isinstance(make_transcriber(self.settings.asr), CommandTranscriber):
                return
            with contextlib.suppress(TooManyJobs):
                self.running[owner] = self.jobs.scoped(f"library:{owner}").submit(
                    "media_ingest", recording.filename, lambda log: self.run(owner, recording.id, log)
                )

    def run(self, owner: str, recording_id: str, log: Log) -> dict[str, Any]:
        library = self.library(owner)
        transcriber = make_transcriber(self.settings.asr)

        def progress(done: float, total: float) -> None:
            library.update(recording_id, transcribed_s=done)
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
                self.running.pop(owner, None)
            self.kick(owner)

    def capacity(self) -> dict[str, int]:
        self.root.mkdir(parents=True, mode=0o700, exist_ok=True)
        arriving = count = 0
        for folder in self.root.iterdir():
            if (folder / "library.db").is_file():
                n, remaining = Uploads(folder).arriving()
                count, arriving = count + n, arriving + remaining
        return {
            "free_bytes": shutil.disk_usage(self.root).free,
            "arriving_bytes": arriving,
            "arriving": count,
            "headroom_bytes": int(self.settings.library.headroom_gb * GIB),
        }

    def admit(self, owner: str, body: UploadBody) -> None:
        """Refuse an upload that would leave less than the headroom free once every upload still arriving is in,
        or that would queue more than ``max_pending`` recordings. Transcription works on one recording at a time,
        so its temporary audio fits in the headroom."""
        library = self.library(owner)
        waiting = library.pending() + self.uploads(owner).arriving()[0]
        limit = self.settings.library.max_pending
        if waiting >= limit:
            raise HTTPException(409, f"最多同时排队 {limit} 个文件，请等前面的转写完成后再添加")
        capacity = self.capacity()
        left = capacity["free_bytes"] - capacity["arriving_bytes"] - body.size
        if left < capacity["headroom_bytes"]:
            raise HTTPException(
                507,
                f"磁盘空间不足：添加后可用空间会低于 {self.settings.library.headroom_gb:g} GB 的安全余量，"
                "请联系管理员扩容",
            )

    def finish(self, owner: str, upload_id: str) -> dict[str, Any]:
        uploads = self.uploads(owner)
        info = uploads.load(upload_id)
        if info["offset"] != info["size"]:
            raise HTTPException(400, "文件尚未上传完成")
        library = self.library(owner)
        if info.get("recording_id"):
            existing = library.get(info["recording_id"])
            if existing is None:
                raise HTTPException(404, "这段录音已删除，请重新上传")
            return {**view(existing), "new": False}
        _, part = uploads.paths(upload_id)
        recording, new = library.add(part, info["filename"])
        info["recording_id"] = recording.id
        uploads.save(upload_id, info)
        self.kick(owner)
        return {**view(library.get(recording.id) or recording), "new": new}

    def status(self, owner: str) -> dict[str, Any]:
        self.wake(owner)
        quota = self.quota(owner)
        library = self.library(owner)
        recordings = library.list()
        identities = self.team(owner).identities()
        waiting = {r.id for r in library.unproofread()}
        with self.lock:
            held_twins = len(self.paused.get(owner, ()))
        return {
            "recordings": [
                {
                    **view(r),
                    # Who was recognised, and how many speakers still wait for the owner.
                    "people": identities.get(r.id, ([], 0))[0],
                    "unsettled": max(0, r.speakers - identities.get(r.id, ([], 0))[1]) if r.status == "ready" else 0,
                    "proofread": self.proofread_state(library, r, waiting),
                }
                for r in recordings
            ],
            "pending": sum(r.status in {"queued", "transcribing"} for r in recordings),
            "max_pending": self.settings.library.max_pending,
            "asr": isinstance(make_transcriber(self.settings.asr), CommandTranscriber),
            "capacity": self.capacity(),
            # What waits for the quota: recordings to proofread and twins to rebuild.
            "quota": {**quota, "waiting_proofread": len(waiting), "waiting_twins": held_twins},
        }


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
) -> Libraries:
    libraries = Libraries(settings, jobs, registry, llm)
    app.state.libraries = libraries

    @app.get("/api/library")
    def get_library(request: Request) -> dict[str, Any]:
        return libraries.status(libraries.owner(request))

    upload_routes(
        app,
        "/api/library/uploads",
        lambda request: libraries.uploads(libraries.owner(request)),
        lambda request, upload_id: libraries.finish(libraries.owner(request), upload_id),
        admit=lambda request, uploads, body: libraries.admit(libraries.owner(request), body),
    )

    @app.post("/api/library/recordings/{recording_id}/retry", status_code=202)
    def retry(recording_id: str, request: Request) -> dict[str, Any]:
        owner = libraries.owner(request)
        recording = libraries.library(owner).retry(recording_id)
        if recording is None:
            raise HTTPException(409, "只有转写失败、原始文件还在的录音可以重试")
        libraries.kick(owner)
        return view(recording)

    @app.delete("/api/library/recordings/{recording_id}")
    async def delete(recording_id: str, request: Request) -> dict[str, bool]:
        owner = libraries.owner(request)
        if not await run_in_threadpool(libraries.library(owner).delete, recording_id):
            raise HTTPException(409, "这段录音正在转写，请稍后再删除")
        libraries.changed(owner)
        return {"deleted": True}

    @app.get("/api/library/recordings/{recording_id}")
    def get_recording(recording_id: str, request: Request) -> dict[str, Any]:
        return libraries.detail(libraries.owner(request), recording_id)

    @app.get("/api/library/recordings/{recording_id}/speakers/{speaker_id}/samples/{index}")
    def get_sample(recording_id: str, speaker_id: str, index: int, request: Request) -> FileResponse:
        return libraries.sample(libraries.owner(request), recording_id, speaker_id, index)

    @app.put("/api/library/recordings/{recording_id}/speakers/{speaker_id}")
    def put_speaker(recording_id: str, speaker_id: str, body: DecisionBody, request: Request) -> dict[str, Any]:
        return libraries.decide(libraries.owner(request), recording_id, speaker_id, body)

    @app.get("/api/library/review")
    def get_review(request: Request) -> dict[str, Any]:
        return {"items": libraries.team(libraries.owner(request)).review()}

    @app.get("/api/library/people")
    def get_people(request: Request) -> dict[str, Any]:
        owner = libraries.owner(request)
        synced = {persona_id: (wanted, done) for persona_id, _, wanted, done in libraries.team(owner).synced()}
        people = []
        for person in libraries.team(owner).people():
            live = person.persona_id is not None and registry is not None and registry.entry(person.persona_id)
            state = synced.get(person.persona_id or "")
            people.append(
                {
                    **person.model_dump(),
                    "persona_id": person.persona_id if live else None,
                    "updating": bool(live and state and state[0] != state[1]),
                }
            )
        return {"items": people}

    @app.post("/api/library/people", status_code=201)
    def post_person(body: PersonBody, request: Request) -> dict[str, Any]:
        try:
            return libraries.team(libraries.owner(request)).add_person(body.name).model_dump()
        except ValueError as e:
            raise HTTPException(409, str(e)) from None

    @app.patch("/api/library/people/{person_id}")
    def patch_person(person_id: str, body: PersonPatch, request: Request) -> dict[str, Any]:
        return libraries.update(libraries.owner(request), person_id, body)

    @app.delete("/api/library/people/{person_id}")
    def delete_person(person_id: str, request: Request) -> dict[str, bool]:
        owner = libraries.owner(request)
        if not libraries.team(owner).delete_person(person_id):
            raise HTTPException(409, "这个人已经有分身，请先删除分身")
        libraries.changed(owner)
        return {"deleted": True}

    @app.post("/api/library/people/{person_id}/persona")
    def post_twin(person_id: str, request: Request) -> dict[str, Any]:
        if registry is None:
            raise HTTPException(503, "无法创建分身")
        owner = libraries.owner(request)
        return libraries.create_twin(owner, person_id, request.scope["twin_identity"])

    return libraries
