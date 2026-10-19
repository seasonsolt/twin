"""``/api/library/voice``: someone signed in through the company login finds themselves, by voice, in the meetings
colleagues uploaded, and makes their twin from them (员工 1b).

Only an account with a work e-mail may (an enterprise sign-in fixes it, so it says who someone is). They record a
sentence, and are offered the voices of the team's library nobody has said who they are, closest first
(``media.voice``). Of each they see one sentence and hear five seconds, with the meeting's title and date; never the
recording, its transcript, its uploader or anyone else's words, and only voices offered to them can be heard or
answered. "是我" is written to the library as a decision with a voice sample, so later meetings know them too, and
makes them one of the people identified there, who may read those meetings (``web.library``). The twin made from
it is the person's own (its owner and member, ``by_voice`` in its registry entry) without the meetings' uploaders
being able to open it, and answers colleagues only once they have looked at it and said it is all right
(``Personas.approve``). Whoever uploaded a meeting keeps the last word over it, and the person can take back what
they confirmed.
"""

from __future__ import annotations

import datetime as dt
import tempfile
import threading
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict
from starlette.concurrency import run_in_threadpool

from ..config import Settings
from ..media.ingest import CommandTranscriber, make_transcriber
from ..media.library import TEAM, owner_key
from ..media.team import Stale, Team
from ..media.voice import LIKELY, Claim, Offer, SelfVoice, offers
from ..persona import gate
from ..persona.store import PersonaStore
from .assets import VOICEPRINT_LIMIT, read_upload, voice
from .library import Libraries
from .personas import Personas

PATH = "/api/library/voice"


class VerdictBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    verdict: Literal["me", "not"]


class MemberVoice:
    def __init__(self, settings: Settings, libraries: Libraries, registry: Personas) -> None:
        self.settings, self.libraries, self.registry = settings, libraries, registry
        # One decision at a time: each reads a library, writes it back and may create a twin.
        self.lock = threading.Lock()

    # ------------------------------------------------------------ who may, and where their voice is kept

    @staticmethod
    def address(identity: dict[str, Any]) -> str:
        address = identity.get("address")
        if not address or not identity.get("email"):
            raise HTTPException(404, "用企业账号登录后才能在会议里找自己的声音")
        return str(address)

    def store(self, identity: dict[str, Any]) -> SelfVoice:
        self.address(identity)
        return SelfVoice(self.libraries.member(owner_key(identity["email"])))

    def transcriber(self) -> CommandTranscriber | None:
        found = make_transcriber(self.settings.asr)
        return found if isinstance(found, CommandTranscriber) else None

    def libraries_heard(self) -> dict[str, Team]:
        """Where voices are offered from: the team's library."""
        return {TEAM: self.libraries.team(TEAM)}

    # ------------------------------------------------------------ the page

    def state(self, identity: dict[str, Any]) -> dict[str, Any]:
        """The person's voice, what they confirmed, and the voices offered to them now (compared afresh)."""
        store = self.store(identity)
        embedding = store.embedding()
        claims = store.claims()
        found = offers(embedding, self.libraries_heard(), claims) if embedding else []
        store.set_offers(found)
        mine = [claim for claim in claims if claim.verdict == "me"]
        twin = self.twin(identity)
        return {
            "available": self.transcriber() is not None,
            "enrolled": embedding is not None,
            "items": [self.item(claim.id, claim.offer, "mine") for claim in mine]
            + [self.item(offer.id, offer, "offered") for offer in found],
            "persona_id": twin["id"] if twin else None,
        }

    @staticmethod
    def item(item_id: str, offer: Offer, state: str) -> dict[str, Any]:
        return {
            "id": item_id,
            "state": state,
            "quote": offer.quote,
            "title": offer.title,
            "date": offer.date,
            "more": len(offer.speakers) - 1,
            "unsure": offer.score < LIKELY,
            "sample_url": f"{PATH}/items/{item_id}/sample",
        }

    def twin(self, identity: dict[str, Any]) -> dict[str, Any] | None:
        """The person's twin made from a colleague's meetings by their voice, if any."""
        with self.registry.lock:
            return next(
                (
                    dict(entry)
                    for entry in self.registry.data["personas"]
                    if entry.get("by_voice")
                    and entry.get("member") == identity["email"]
                    and not entry.get("deleted_at")
                    and entry["id"] not in self.registry.removing
                ),
                None,
            )

    # ------------------------------------------------------------ their voice

    def enroll(self, identity: dict[str, Any], upload: Path) -> dict[str, Any]:
        store = self.store(identity)
        transcriber = self.transcriber()
        if transcriber is None:
            raise HTTPException(503, "没有配置录音转写服务，暂时不能用声音找自己")
        directory = store.db_path.parent
        content, _ = voice(upload, directory)
        # Only the voiceprint is kept; the recording is gone when this returns.
        with tempfile.NamedTemporaryFile(dir=directory, suffix=".wav") as clip:
            clip.write(content)
            clip.flush()
            embedding = transcriber.embed(Path(clip.name))
        if embedding is None:
            raise HTTPException(503, "录音转写服务算不出声纹（需要 asr-funasr 1.3.0 以上），暂时不能用声音找自己")
        store.set_embedding(embedding)
        return self.state(identity)

    def forget(self, identity: dict[str, Any]) -> dict[str, Any]:
        self.store(identity).forget()
        return self.state(identity)

    def sample(self, identity: dict[str, Any], item_id: str) -> FileResponse:
        """The five seconds of an offered or confirmed voice, and nothing else of its recording."""
        store = self.store(identity)
        found = store.offer(item_id) or (claim.offer if (claim := store.claim(item_id)) else None)
        if found is None:
            raise HTTPException(404, "找不到这段声音，请刷新")
        recording_id, transcript_id, speaker_id = found.heard
        recording = self.libraries.library(found.library).get(recording_id)
        if recording is None or recording.transcript_id != transcript_id:
            raise HTTPException(404, "这段录音刚被修改过，请刷新")
        return self.libraries.sample(found.library, recording_id, speaker_id, 0)

    # ------------------------------------------------------------ what they say of a voice

    def answer(self, identity: dict[str, Any], offer_id: str, verdict: Literal["me", "not"]) -> dict[str, Any]:
        store = self.store(identity)
        with self.lock:
            offer = store.offer(offer_id)
            if offer is None:
                raise HTTPException(404, "这段声音已经变了，请刷新")
            if verdict == "not":
                store.add_claim(offer, "not")
            else:
                self.confirm(identity, store, offer)
        return self.state(identity)

    def confirm(self, identity: dict[str, Any], store: SelfVoice, offer: Offer) -> None:
        """Write "是我" back to the voice's library, then give the person's twin those meetings."""
        team = self.libraries.team(offer.library)
        still = {(v.recording.id, v.recording.transcript_id, v.speaker_id): v.person_id for v in team.open_voices()}
        if any(still.get(heard, "") != offer.person_id for heard in offer.speakers):
            raise HTTPException(409, "这段录音刚被修改过，请刷新后再确认")
        person_id, made = self.person(identity, offer.library, team, store)
        try:
            if offer.person_id:
                # Every voice the unnamed person was made of is theirs, with the voice samples it was known by.
                team.resolve(offer.person_id, person_id)
            else:
                recording_id, transcript_id, speaker_id = offer.heard
                recording = team.library.get(recording_id)
                if recording is None:
                    raise Stale()
                team.decide(recording_id, transcript_id, recording.revision, speaker_id, "confirm", person_id, True)
        except (Stale, ValueError):
            if made:
                team.delete_person(person_id)
            raise HTTPException(409, "这段录音刚被修改过，请刷新后再确认") from None
        team.set_account(person_id, owner_key(identity["email"]))
        store.add_claim(offer, "me", person_id)
        # Their voice sample can settle them in the library's other meetings.
        team.classify_all()
        self.attach(identity, offer.library, team, person_id)
        self.libraries.changed(offer.library)
        self.libraries.proofread(offer.library)

    def person(self, identity: dict[str, Any], key: str, team: Team, store: SelfVoice) -> tuple[str, bool]:
        """Who the person is in library ``key``, and whether they were just added to it: the one they said they
        are, or whose twin they have taken, or they confirmed voices as before, else a new person by the name they
        signed in with."""
        known = {person.id: person for person in team.people()}
        account = owner_key(identity["email"])
        for person in known.values():
            if person.account == account:
                return person.id, False
        for person in known.values():
            entry = self.registry.entry(person.persona_id) if person.persona_id else None
            if entry is not None and entry.get("member") == identity["email"]:
                return person.id, False
        for claim in store.claims():
            if claim.verdict == "me" and claim.offer.library == key and claim.person_id in known:
                return claim.person_id, False
        local = self.address(identity).split("@")[0]
        name = " ".join(str(identity.get("name") or local).split())[:20] or local
        for candidate in (name, f"{name}（{local}）"):
            try:
                return team.add_person(candidate).id, True
            except ValueError:
                continue
        raise HTTPException(409, f"录音库里已经有叫「{name}」的人，请联系上传会议的同事")

    def attach(self, identity: dict[str, Any], key: str, team: Team, person_id: str) -> None:
        """Make the person's twin follow library ``key`` as ``person_id``: the twin already made of them there,
        else a twin of theirs with nothing in it yet, else a new one. Nothing is attached while they have a twin of
        meetings already (made for them by a colleague, perhaps as someone else of their name) or one with
        materials of its own."""
        person = team.person(person_id)
        if person is None or (person.persona_id and self.registry.entry(person.persona_id) is not None):
            return
        email = identity["email"]
        with self.registry.lock:
            mine = [
                entry
                for entry in self.registry.data["personas"]
                if not entry.get("deleted_at")
                and entry["id"] not in self.registry.removing
                and email in (entry.get("owner"), entry.get("member"))
            ]
            linked = {entry["id"]: gate.linked(self.registry.settings_for(entry["id"]).db_path) for entry in mine}
            if any(linked.values()):
                return
            empty = None
            for entry in mine:
                if entry.get("owner") == email:
                    with PersonaStore(self.registry.settings_for(entry["id"]).db_path) as store:
                        if store.count_sources():
                            return
                    empty = empty or entry
            try:
                entry = empty or self.registry.create(person.name, identity, onboarding=False)
            except HTTPException:
                return  # At their limit of twins: the voices stay theirs in the library, outside any twin.
            entry.update(member=email, claimed_at=dt.datetime.now(dt.UTC).isoformat(), by_voice=True, public=False)
            entry.pop("approved_at", None)
            self.registry.save()
            with PersonaStore(self.registry.settings_for(entry["id"]).db_path) as store:
                gate.link(store, team.library.db_path, entry["id"])
                store.set_meta("onboarding_pending", "0")
            team.link(person_id, entry["id"])
            persona_id = entry["id"]
        self.libraries.sync(key, persona_id)

    def take_back(self, identity: dict[str, Any], claim_id: str) -> dict[str, Any]:
        """Undo what the person said of a voice. "是我" taken back clears every speaker of it still theirs in that
        library (whatever its owner decided since stays) and counts as "不是" from then on."""
        store = self.store(identity)
        with self.lock:
            claim = store.claim(claim_id)
            if claim is None:
                raise HTTPException(404, "找不到这条确认，请刷新")
            if claim.verdict == "not":
                store.drop_claim(claim_id)
            else:
                self.clear(claim)
                store.set_verdict(claim_id, "not")
                self.libraries.changed(claim.offer.library)
        return self.state(identity)

    def clear(self, claim: Claim) -> None:
        team = self.libraries.team(claim.offer.library)
        for recording_id, transcript_id, speaker_id in claim.offer.speakers:
            recording = team.library.get(recording_id)
            if recording is None or recording.transcript_id != transcript_id:
                continue
            view = next((s for s in team.speakers(recording) if s.id == speaker_id), None)
            if view is None or view.decision != "confirmed" or view.person_id != claim.person_id:
                continue
            try:
                team.decide(recording_id, transcript_id, recording.revision, speaker_id, "clear")
            except (Stale, ValueError):
                continue


def register(app: FastAPI, settings: Settings, libraries: Libraries, registry: Personas) -> MemberVoice:
    member = MemberVoice(settings, libraries, registry)

    @app.get(PATH)
    def get_voice(request: Request) -> dict[str, Any]:
        return member.state(request.scope["twin_identity"])

    @app.put(PATH)
    async def put_voice(request: Request, file: Annotated[UploadFile, File()]) -> dict[str, Any]:
        identity = request.scope["twin_identity"]
        directory = (await run_in_threadpool(member.store, identity)).db_path.parent
        with tempfile.NamedTemporaryFile(dir=directory, suffix=".upload") as upload:
            await read_upload(file, upload, VOICEPRINT_LIMIT, "录音太大，读一句话、十秒左右就够了")
            return await run_in_threadpool(member.enroll, identity, Path(upload.name))

    @app.delete(PATH)
    def delete_voice(request: Request) -> dict[str, Any]:
        return member.forget(request.scope["twin_identity"])

    @app.get(PATH + "/items/{item_id}/sample")
    def get_sample(item_id: str, request: Request) -> FileResponse:
        return member.sample(request.scope["twin_identity"], item_id)

    @app.post(PATH + "/offers/{offer_id}")
    def post_answer(offer_id: str, body: VerdictBody, request: Request) -> dict[str, Any]:
        return member.answer(request.scope["twin_identity"], offer_id, body.verdict)

    @app.delete(PATH + "/claims/{claim_id}")
    def delete_claim(claim_id: str, request: Request) -> dict[str, Any]:
        return member.take_back(request.scope["twin_identity"], claim_id)

    return member
