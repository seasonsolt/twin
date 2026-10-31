"""Persona-scoped, private conversation history."""

from __future__ import annotations

import datetime as dt
import logging
import sqlite3
from contextlib import suppress
from typing import Any, Literal
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator

from ..config import Settings
from ..handoffs import HandoffDesk
from ..persona import retirement, self_ratings
from ..persona.assistant import annotate_notes, annotate_promises, record_promise
from ..persona.heirs import tier_only
from ..persona.store import PersonaStore
from ..persona.tiers import COLLEAGUE, SELF, Audience, heir_audience, is_heir
from ..persona.work import WorkStore, summary_view
from ..teamdb import HandoffStatus, TeamDB, Via
from .personas import Personas

logger = logging.getLogger(__name__)


class SavedTurn(BaseModel):
    """A turn of a conversation brought over from the browser. ``reply`` is accepted and dropped (``imported``)."""

    role: Literal["user", "twin"]
    content: str = Field(max_length=4000)
    timestamp: dt.datetime
    reply: dict[str, Any] | None = None

    def imported(self) -> dict[str, Any]:
        """The turn as it is saved: its text only. What a twin turn's metadata says (what it left to the person, a
        promise, how it answered, what it cited) is believed only where the twin wrote it, so a turn sent in by the
        asker cannot make handoffs, commitments or answers on the person's page (``handoffs``)."""
        return self.model_dump(mode="json", exclude={"reply"})


class CreateBody(BaseModel):
    turns: list[SavedTurn] = Field(default_factory=list, max_length=500)
    migration_id: UUID | None = None


class RenameBody(BaseModel):
    title: str = Field(min_length=1, max_length=200)

    @field_validator("title")
    @classmethod
    def trim_title(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("标题不能为空")
        return value.strip()


# The scope key naming the heir a request comes from (P2.7 sets it once an heir opens the twin); it wins over
# everything else the request says of who is asking.
HEIR_SCOPE = "twin_heir"


def request_heir(request: Request) -> str | None:
    """The heir the request comes from, if any (``HEIR_SCOPE``)."""
    heir_id = request.scope.get(HEIR_SCOPE)
    return heir_id if isinstance(heir_id, str) and heir_id else None


def owner(request: Request) -> str | None:
    """Whose conversations a request reads and writes: the signed-in account's, or an heir's own, which nobody else
    sees and which see nobody else's, whatever account the heir's browser is signed in with."""
    if (heir_id := request_heir(request)) is not None:
        return heir_audience(heir_id)
    return request.scope["twin_identity"]["email"]  # type: ignore[no-any-return]


def request_audience(request: Request) -> Audience:
    """The tier this signed-in person's conversations with the twin answer from (``Personas.audience``); an heir's
    (``heir:<id>``) for a request from an heir; the colleague tier where nothing says otherwise."""
    if (heir_id := request_heir(request)) is not None:
        return heir_audience(heir_id)
    return SELF if request.scope.get("twin_audience") == SELF else COLLEAGUE


def request_asker_name(request: Request) -> str:
    """What the signed-in person is called where they are shown to the person they asked: their name, else the part of
    their account before the @."""
    identity = request.scope["twin_identity"]
    name = str(identity.get("name") or "").strip()
    return name or str(identity.get("email") or "").split("@")[0]


class ConversationIndex:
    """One twin's conversations in the team database (``teamdb``): written right after the twin's own database, and
    mended at startup if a write did not make it, so a failure here never fails the conversation."""

    def __init__(self, team: TeamDB, persona_id: str) -> None:
        self.team, self.persona_id = team, persona_id

    def created(
        self,
        store: PersonaStore,
        conversation_id: str,
        asker: str | None,
        audience: Audience,
        asker_name: str = "",
        *,
        via: Via = "direct",
        delegation_id: str | None = None,
    ) -> None:
        """Index a conversation just made. ``via`` and ``delegation_id``: it was asked by the person's assistant in
        their name (``delegations``), which the team database checks as it writes it."""
        self._write(
            lambda team, head: team.record_conversation(
                conversation_id,
                self.persona_id,
                asker,
                tier_only(audience),
                head[1],
                head[2],
                asker_name=asker_name,
                via=via,
                delegation_id=delegation_id,
            ),
            store,
            conversation_id,
        )

    def touched(self, store: PersonaStore, conversation_id: str | None) -> None:
        if conversation_id is None:
            return
        self._write(
            lambda team, head: team.refresh_conversation(conversation_id, head[1], head[2], persona_id=self.persona_id),
            store,
            conversation_id,
        )

    def deleted(self, conversation_id: str) -> None:
        try:
            self.team.delete_conversation(conversation_id, persona_id=self.persona_id)
        except sqlite3.Error:
            logger.warning("could not mark conversation %s deleted in the team index", conversation_id, exc_info=True)

    def audience(self, conversation_id: str | None, current: Audience) -> Audience:
        """The tier a chat answers from: the one the conversation was created with, but never more than the asker may
        have now (a person who gave the twin back no longer sees their own tier in it). A conversation the index does
        not know, or any failure to read it, is the colleague tier. An heir's is always the heir's own, whatever
        conversation it names: the index keeps no more of it than the colleague tier (``heirs.tier_only``)."""
        if conversation_id is None or is_heir(current):
            return current
        try:
            stored = self.team.audience_of(conversation_id, persona_id=self.persona_id)
        except sqlite3.Error:
            logger.warning("could not read conversation %s from the team index", conversation_id, exc_info=True)
            return COLLEAGUE
        return SELF if stored == SELF and current == SELF else COLLEAGUE

    def _write(self, write: Any, store: PersonaStore, conversation_id: str) -> None:
        head = store.conversation_head(conversation_id)
        if head is None:
            return
        try:
            write(self.team, head)
        except sqlite3.Error:
            logger.warning("could not index conversation %s in the team", conversation_id, exc_info=True)


# The date the person's own conversation looks back to (时间切片, docs/PRODUCT_PERSONA_AGENT.md P2.1), by conversation.
AS_OF_PREFIX = "conversation_as_of:"


def conversation_as_of(store: PersonaStore, conversation_id: str) -> str | None:
    """The date the conversation last asked to be answered as of, ``YYYY-MM-DD``; None for the person as they are."""
    return store.get_meta(AS_OF_PREFIX + conversation_id)


def keep_as_of(store: PersonaStore, conversation_id: str | None, email: str | None, as_of: dt.date | None) -> None:
    """Remember the date ``email``'s own conversation is answered as of, for it to go on so when opened again; written
    only when it changes, since every write of ``p_meta`` makes the next answer read the memory afresh."""
    if conversation_id is None:
        return
    head = store.conversation_head(conversation_id)
    if head is None or head[0] != email:
        return
    value = as_of.isoformat() if as_of is not None else None
    if conversation_as_of(store, conversation_id) == value:
        return
    if value is None:
        store.delete_meta(AS_OF_PREFIX + conversation_id)
    else:
        store.set_meta(AS_OF_PREFIX + conversation_id, value)


def append_user(
    store: PersonaStore,
    conversation_id: str | None,
    email: str | None,
    content: str,
    index: ConversationIndex | None = None,
) -> None:
    if conversation_id is not None:
        try:
            store.append_conversation_turn(conversation_id, email, "user", content)
        except KeyError:
            raise HTTPException(404, "找不到这段对话") from None
        if index is not None:
            index.touched(store, conversation_id)


def append_reply(
    store: PersonaStore,
    conversation_id: str | None,
    email: str | None,
    payload: dict[str, Any],
    index: ConversationIndex | None = None,
    handoffs: tuple[HandoffDesk, str, Audience] | None = None,
    *,
    assistant: bool = False,
) -> dict[str, Any]:
    """Save the twin's reply in the conversation. ``handoffs``: the desk, what the asker is called and the tier the
    conversation answers from, to hand on what the reply left to the person; where it did, the payload says how the
    handoff stands (it is not saved with the reply: the state changes, and the conversation reads it afresh).
    ``assistant``: the conversation is the person's own, where a promise they said they make goes into their ledger."""
    if assistant:
        record_promise(store, conversation_id, payload)
    if conversation_id is not None:
        # Deletion while a reply is running must not recreate the conversation.
        with suppress(KeyError):
            store.append_conversation_turn(conversation_id, email, "twin", payload["reply"], payload)
            if index is not None:
                index.touched(store, conversation_id)
            if handoffs is not None:
                desk, asker_name, audience = handoffs
                if made := desk.raise_for(store, conversation_id, email, asker_name, audience, payload):
                    payload["handoff"] = made
    return payload


def refuse_if_gone(store: PersonaStore, request: Request) -> None:
    """403 when the twin has said goodbye to the heir asking (``persona.retirement``): their conversations are then
    only to read."""
    if (heir_id := request_heir(request)) is not None and retirement.gone(
        store, heir_audience(heir_id), dt.date.today()
    ):
        raise HTTPException(403, retirement.RETIRED)


def register(app: FastAPI, settings: Settings, index: ConversationIndex, desk: HandoffDesk) -> None:
    @app.get("/api/conversations")
    def list_conversations(request: Request, offset: int = Query(default=0, ge=0)) -> list[dict[str, Any]]:
        with PersonaStore(settings.db_path) as store:
            return store.list_conversations(owner(request), offset)

    @app.post("/api/conversations", status_code=201)
    def create_conversation(request: Request, body: CreateBody | None = None) -> dict[str, str]:
        body = body or CreateBody()
        with PersonaStore(settings.db_path) as store:
            refuse_if_gone(store, request)
            try:
                conversation_id = store.create_conversation(
                    owner(request),
                    [turn.imported() for turn in body.turns],
                    str(body.migration_id) if body.migration_id else None,
                )
            except KeyError:
                raise HTTPException(404, "找不到这段对话") from None
            # The tier is fixed here, once, and not worked out again at each question.
            index.created(
                store, conversation_id, owner(request), request_audience(request), request_asker_name(request)
            )
        return {"id": conversation_id, "audience": index.audience(conversation_id, request_audience(request))}

    @app.get("/api/conversations/{conversation_id}")
    def get_conversation(conversation_id: str, request: Request) -> dict[str, Any]:
        with PersonaStore(settings.db_path) as store:
            try:
                conversation = desk.annotate(store.get_conversation(conversation_id, owner(request)))
            except KeyError:
                raise HTTPException(404, "找不到这段对话") from None
            audience = index.audience(conversation_id, request_audience(request))
            # What the person said of an answer, 像我 or 不像我 (``persona.self_ratings``): only in their own.
            if audience == SELF and (rated := self_ratings.ratings_of(store, conversation_id)):
                for turn in conversation["turns"]:
                    if turn["id"] in rated:
                        turn["self_rating"] = rated[turn["id"]]
            # The date it looks back to (时间切片): only the person's own conversation has one.
            if audience == SELF and (as_of := conversation_as_of(store, conversation_id)):
                conversation["as_of"] = as_of
            # ``audience`` is the tier it answers from: the person's own conversation is with their assistant.
            return {**annotate_promises(store, annotate_notes(store, conversation)), "audience": audience}

    @app.patch("/api/conversations/{conversation_id}")
    def rename_conversation(conversation_id: str, body: RenameBody, request: Request) -> dict[str, bool]:
        with PersonaStore(settings.db_path) as store:
            refuse_if_gone(store, request)
            if not store.rename_conversation(conversation_id, owner(request), body.title):
                raise HTTPException(404, "找不到这段对话")
            index.touched(store, conversation_id)
        return {"updated": True}

    @app.delete("/api/conversations/{conversation_id}")
    def delete_conversation(conversation_id: str, request: Request) -> dict[str, bool]:
        with PersonaStore(settings.db_path) as store:
            refuse_if_gone(store, request)
            if not store.delete_conversation(conversation_id, owner(request)):
                raise HTTPException(404, "找不到这段对话")
            if conversation_as_of(store, conversation_id) is not None:
                store.delete_meta(AS_OF_PREFIX + conversation_id)
        index.deleted(conversation_id)
        return {"deleted": True}


# What the all-conversations list shows of how a handoff stands, beside the conversation it came from.
HANDOFF_TAGS: dict[HandoffStatus, str] = {
    "delivered": "等本人回复",
    "writing": "等本人回复",
    "replied": "本人已回",
    "accepted": "本人已答应",
    "declined": "本人没接",
    "dismissed": "本人不答",
    "expired": "本人没回",
    "withdrawn": "",
}
EVERYONE_PAGE = 50


def register_all(app: FastAPI, registry: Personas, team: TeamDB) -> None:
    """``GET /api/personas/conversations``: the signed-in person's own conversations with every twin they can see, in
    one list (the index of the team database), with the tasks they gave them. It is their own and nobody's else: what
    other people asked their twin is not in it. Their conversations with the twin of which they are the person are
    set apart (``mine``): the assistant's, which no one else has."""

    @app.get("/api/personas/conversations")
    def everyone(
        request: Request,
        offset: int = Query(default=0, ge=0),
        with_persona: str | None = Query(default=None, alias="with"),
        mine: bool = False,
        task_offset: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        """``with``: only that twin's. ``mine``: only those with the person's own twin; otherwise those are left out,
        since they are not conversations with someone else. Tasks come with the first page; ``task_offset`` asks for
        the next ones instead (and no conversations)."""
        identity = request.scope["twin_identity"]
        email = identity["email"]
        with registry.lock:
            visible = {e["id"]: dict(e) for e in registry.data["personas"] if registry.visible(e, identity)}
        own = {e["id"] for e in registry.own_twins(identity)}
        ids = [i for i in visible if i in own] if mine else list(visible)
        if with_persona is not None:
            ids = [i for i in ids if i == with_persona]
        rows: list[Any] = []
        try:
            if not task_offset:
                # A conversation with one's own twin that the colleague tier answered (from before the index knew the
                # difference, or with the twin not yet said to be all right) is an ordinary one.
                rows = team.conversations(
                    personas=ids,
                    asked_by=email,
                    self_tier_of=own if mine else None,
                    not_self_tier_of=None if mine else own,
                    limit=EVERYONE_PAGE + 1,
                    offset=offset,
                )
            page = rows[:EVERYONE_PAGE]
            # Where the next page of conversations begins: the ones added below are not part of the paging.
            next_offset = offset + len(page)
            # What the assistant asked colleagues' twins in the person's name belongs with the assistant's own list
            # (under 问同事); in the list of everything it is already among the rest.
            if mine and offset == 0 and not task_offset:
                page += team.conversations(
                    personas=[i for i in visible if i not in own],
                    asked_by=email,
                    via="delegate",
                    limit=EVERYONE_PAGE,
                )
            states = team.handoff_states([r.id for r in page])
            delegated = team.delegation_counts([r.id for r in page])
            team.expire_due()
            pending = sum(
                1
                for persona_id in own
                for h in team.handoffs(persona_id=persona_id, statuses=("delivered",))
                if h.owner is None or h.owner == email
            )
        except sqlite3.Error as e:
            logger.warning("could not read the index of conversations", exc_info=True)
            raise HTTPException(503, "对话列表暂时读不了，请稍后重试") from e
        # What was last said, for finding a conversation by it: read from the twins' own databases, which hold the text.
        previews: dict[str, str] = {}
        for persona_id in {r.persona_id for r in page}:
            path = registry.db_path_of(persona_id)
            if path.is_file():
                with PersonaStore(path) as store:
                    previews.update(
                        store.conversation_previews([r.id for r in page if r.persona_id == persona_id], email)
                    )
        conversations = [
            {
                "id": r.id,
                "persona_id": r.persona_id,
                "title": r.title,
                "preview": previews.get(r.id, ""),
                "updated_at": r.updated_at,
                "via": r.via,
                "handoff": (HANDOFF_TAGS[states[r.id]] or None) if r.id in states else None,
                # How many colleagues' twins the person's assistant asked in this conversation (代问).
                "delegated": delegated.get(r.id, 0),
            }
            for r in page
        ]
        tasks: list[dict[str, Any]] = []
        if offset == 0:
            for persona_id in ids:
                entry = visible[persona_id]
                path = registry.db_path_of(persona_id)
                work = WorkStore(path)
                if not work.root.is_dir():
                    continue
                visitor = not registry.accessible(entry, identity)
                tasks += [
                    {**summary_view(t), "persona_id": persona_id}
                    for t in work.list_tasks(email, visitor)
                    if (t.audience == SELF and persona_id in own) == mine
                ]
            tasks.sort(key=lambda t: t["updated_at"], reverse=True)
        return {
            "mine": {"persona_id": next(iter(sorted(own)), None), "pending": pending} if own else None,
            "conversations": conversations,
            "tasks": tasks[task_offset : task_offset + EVERYONE_PAGE],
            "more": len(rows) > EVERYONE_PAGE,
            "next": next_offset,
            "more_tasks": len(tasks) > task_offset + EVERYONE_PAGE,
        }
