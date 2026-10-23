"""Web routes of the lenses (``/api/persona/lenses...``, see ``twin.lenses``).

For the person the twin is made for, and no one else (a manager, a visitor and the person's colleagues are refused):
the facets a lens can open, publishing one, adjusting, holding, resuming and taking it back, what it was used for and
correcting that. For a colleague: the lenses of this twin they may use, asking one in a conversation of their own, and
asking the person themself when the lens could not settle it, in their own name. A use of a lens keeps the question and
what the lens said and nothing of who asked, and the route that asks the person is another request with its own
handoff: nothing joins the two.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Collection
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from ..config import Settings
from ..embed import Embedder
from ..handoffs import HandoffDesk
from ..lenses import (
    LENS_FACETS,
    STOP_AFTER,
    LensAnswer,
    LensAudience,
    Lenses,
    LensRefused,
    in_use,
)
from ..persona import gate
from ..persona.store import PersonaStore
from ..persona.tiers import SELF
from ..teamdb import DelegationRefused, Lens, LensUnavailable
from .backends import Backends, BackendUnavailable
from .conversations import ConversationIndex, append_reply, append_user, owner, request_asker_name, request_audience
from .handoffs import person

NOT_NOW = "这个赋能现在不能用"
OWN_LENS = "这是你自己的赋能，发布前可以在“赋能”里预览"


class AudienceBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: Literal["team", "people"] = "team"
    # The twins of the colleagues it is for (``scope`` people).
    twins: list[str] = Field(default_factory=list, max_length=200)

    def audience(self) -> LensAudience:
        if self.scope == "people":
            return LensAudience("people", tuple(dict.fromkeys(t[:100] for t in self.twins)))
        return LensAudience()


class PublishBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    facets: list[str] = Field(max_length=len(LENS_FACETS) + 10)
    audience: AudienceBody = Field(default_factory=AudienceBody)


class AdjustBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=80)
    facets: list[str] | None = Field(default=None, max_length=len(LENS_FACETS) + 10)
    audience: AudienceBody | None = None


class PreviewBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    facets: list[str] = Field(max_length=len(LENS_FACETS) + 10)


class AskBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=2000)
    # The colleague's own conversation with the twin, which the question and the answer are written into.
    conversation_id: str | None = Field(default=None, max_length=100)


class AskOwnerBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conversation_id: str = Field(min_length=1, max_length=100)


def card(lens: Lens, owner_name: str, answer: LensAnswer) -> dict[str, Any]:
    """A lens's answer as the colleague is shown it: statements with the words they stand on, said to be inferred."""
    return {
        "id": lens.id,
        "name": lens.name,
        "owner_name": owner_name,
        "views": [v.view() for v in answer.views],
        "empty": not answer.views,
        "settled_by_person": answer.settled_by_person,
        "note": f"根据{owner_name}说过的话推测，不代表{owner_name}的意见",
    }


def reply_text(owner_name: str, answer: LensAnswer) -> str:
    """The words of the turn the answer is saved as, which the conversation lists and copies."""
    lines = [v.text for v in answer.views]
    if not lines:
        return f"这个赋能没有能回答的内容，可以直接问{owner_name}。"
    if answer.settled_by_person:
        lines.append(f"具体怎么定：未开放，可直接问{owner_name}。")
    return "\n".join(lines)


def register(
    app: FastAPI,
    settings: Settings,
    lenses: Lenses,
    desk: HandoffDesk,
    backends: Backends,
    index: ConversationIndex,
    persona_id: str,
    member_twins: Callable[[str | None], Collection[str]],
) -> None:
    def team_ready() -> None:
        if desk.team is None:
            raise HTTPException(503, "团队库没有打开")

    def refused(failure: Exception) -> HTTPException:
        if isinstance(failure, KeyError):
            return HTTPException(404, "找不到这个赋能，请刷新后重试")
        if isinstance(failure, LensUnavailable):
            return HTTPException(409, "这个赋能已经撤回了" if failure.status == "withdrawn" else NOT_NOW)
        return HTTPException(400 if isinstance(failure, LensRefused) else 409, str(failure))

    def view_of(lens: Lens) -> dict[str, Any]:
        with PersonaStore(settings.db_path) as store:
            return lenses.view(lens, store)

    def embedder_or_none() -> Embedder | None:
        try:
            return backends.embedder()
        except BackendUnavailable:
            return None

    # ------------------------------------------------------------ the person

    @app.get("/api/persona/lenses")
    def list_lenses(request: Request) -> dict[str, Any]:
        """Their lenses, newest first, and what each facet a lens may open stands at."""
        person(request)
        team_ready()
        with PersonaStore(settings.db_path) as store:
            verdicts = lenses.verdicts(store)
            listed = [lenses.view(lens, store) for lens in lenses.team.lenses(persona_id=persona_id)]
        return {
            "lenses": [v for v in listed if v["status"] != "withdrawn"],
            "facets": [v.view() for v in verdicts],
            "stop_after": STOP_AFTER,
        }

    @app.post("/api/persona/lenses/preview")
    def preview(body: PreviewBody, request: Request) -> dict[str, Any]:
        """How a lens opening these facets reads, to look at; nothing is kept and nothing is used."""
        person(request)
        with PersonaStore(settings.db_path) as store:
            answer = lenses.preview(store, settings, body.facets)
        return {"views": [v.view() for v in answer.views], "settled_by_person": answer.settled_by_person}

    @app.post("/api/persona/lenses", status_code=201)
    def publish(body: PublishBody, request: Request) -> dict[str, Any]:
        """Publish a lens: the facets that cannot be opened (not well founded yet) are refused, all of them named."""
        person(request)
        team_ready()
        try:
            with PersonaStore(settings.db_path) as store:
                lens = lenses.publish(store, persona_id, body.name, body.facets, body.audience.audience())
                return lenses.view(lens, store)
        except sqlite3.Error as e:
            raise HTTPException(503, "团队库暂时读不了，请稍后重试") from e
        except LensRefused as e:
            raise refused(e) from e

    @app.patch("/api/persona/lenses/{lens_id}")
    def adjust(lens_id: str, body: AdjustBody, request: Request) -> dict[str, Any]:
        """Change the name, the facets (opening one that was corrected out opens it afresh) or whom it is for."""
        person(request)
        team_ready()
        try:
            with PersonaStore(settings.db_path) as store:
                lens = lenses.adjust(
                    store,
                    persona_id,
                    lens_id,
                    name=body.name,
                    facets=body.facets,
                    audience=body.audience.audience() if body.audience else None,
                )
                return lenses.view(lens, store)
        except (KeyError, LensUnavailable, LensRefused) as e:
            raise refused(e) from e

    def change(lens_id: str, action: Callable[[str, str], Lens]) -> dict[str, Any]:
        team_ready()
        try:
            lens = action(persona_id, lens_id)
        except (KeyError, LensUnavailable) as e:
            raise refused(e) from e
        return view_of(lens)

    @app.post("/api/persona/lenses/{lens_id}/pause")
    def pause(lens_id: str, request: Request) -> dict[str, Any]:
        """Hold it: from this moment it is not used, until it is resumed."""
        person(request)
        return change(lens_id, lenses.hold)

    @app.post("/api/persona/lenses/{lens_id}/resume")
    def resume(lens_id: str, request: Request) -> dict[str, Any]:
        person(request)
        return change(lens_id, lenses.resume)

    @app.post("/api/persona/lenses/{lens_id}/withdraw")
    def withdraw(lens_id: str, request: Request) -> dict[str, Any]:
        """Take it back for good: no one uses it from this moment, and there is no way back (publish another)."""
        person(request)
        return change(lens_id, lenses.withdraw)

    @app.get("/api/persona/lenses/{lens_id}/uses")
    def uses(lens_id: str, request: Request, facet: str | None = None) -> dict[str, Any]:
        """What the lens was asked and said, newest first: no word of who asked."""
        person(request)
        team_ready()
        lens = lenses.team.get_lens(lens_id)
        if lens is None or lens.persona_id != persona_id:
            raise refused(KeyError(lens_id))
        return {"uses": [lenses.use_view(u) for u in lenses.team.lens_uses(lens.id, facet=facet)]}

    @app.post("/api/persona/lenses/{lens_id}/uses/{use_id}/correct")
    def correct(lens_id: str, use_id: str, request: Request) -> dict[str, Any]:
        """Say what the lens said there was wrong. A facet corrected three times is no longer used."""
        person(request)
        team_ready()
        try:
            use = lenses.correct(persona_id, lens_id, use_id)
        except KeyError as e:
            raise refused(e) from e
        lens = lenses.team.get_lens(lens_id)
        assert lens is not None
        return {"use": lenses.use_view(use), "lens": view_of(lens)}

    # ------------------------------------------------------------ colleagues

    def viewer_lenses(request: Request) -> list[Lens]:
        """The lenses of this twin the signed-in colleague may use; none for the person themself."""
        if request_audience(request) == SELF or desk.team is None or desk.owner() is None:
            return []
        return lenses.available(persona_id, member_twins(owner(request)))

    @app.get("/api/persona/lenses/available")
    def available(request: Request) -> dict[str, Any]:
        """The lenses a colleague can ask here: name and what each speaks from."""
        found = viewer_lenses(request)
        if not found:
            return {"lenses": []}
        name = desk.name()
        with PersonaStore(settings.db_path) as store:
            verdicts = lenses.verdicts(store)
            counts = {lens.id: lenses.team.corrections(lens.id) for lens in found}
            return {
                "lenses": [
                    {
                        "id": lens.id,
                        "name": lens.name,
                        "owner_name": name,
                        "facets": [
                            {"facet_id": f, "name": v.name}
                            for f in in_use(lens, verdicts, counts[lens.id])
                            for v in verdicts
                            if v.facet_id == f
                        ],
                    }
                    for lens in found
                ]
            }

    @app.post("/api/persona/lenses/ask-owner")
    def ask_owner(body: AskOwnerBody, request: Request) -> dict[str, Any]:
        """The colleague wants the person's own answer after a lens: a handoff in their name, from their conversation.
        It is not joined to the use of the lens, which keeps no asker."""
        if request_audience(request) == SELF:
            raise HTTPException(403, OWN_LENS)
        team_ready()
        email = owner(request)
        name = desk.name()
        try:
            with PersonaStore(settings.db_path) as store:
                store.get_conversation(body.conversation_id, email)
                made = desk.hand_over(
                    store, body.conversation_id, email, request_asker_name(request), f"想听{name}本人怎么说"
                )
        except KeyError:
            raise HTTPException(404, "找不到这段对话") from None
        except DelegationRefused as e:
            # A conversation the colleague's assistant asked in their name is handed on from its own card.
            raise HTTPException(409, str(e)) from e
        except sqlite3.Error as e:
            raise HTTPException(503, "团队库暂时读不了，请稍后重试") from e
        if made is None:
            raise HTTPException(409, f"没能转给{name}本人，请直接联系他")
        return {"handoff": made}

    @app.post("/api/persona/lenses/{lens_id}/ask")
    def ask(lens_id: str, body: AskBody, request: Request) -> dict[str, Any]:
        """Ask a lens in a conversation of the colleague's own: the question and what the lens said are written into
        it, and the use is kept for the person without the asker. Held or taken back, it answers nothing."""
        if request_audience(request) == SELF:
            raise HTTPException(403, OWN_LENS)
        team_ready()
        usable = {lens.id: lens for lens in viewer_lenses(request)}
        lens = usable.get(lens_id)
        if lens is None:
            raise HTTPException(404, NOT_NOW)
        name = desk.name()
        email = owner(request)
        question = " ".join(body.question.split())
        try:
            with PersonaStore(settings.db_path) as store:
                if body.conversation_id is not None:
                    # The colleague's own conversation only.
                    store.get_conversation(body.conversation_id, email)
                answer = lenses.answer(lens, store, settings, question, embedder_or_none())
                payload = {
                    "reply": reply_text(name, answer),
                    "citations": [],
                    "confidence": 1.0,
                    "abstain": False,
                    "abstain_reason": "",
                    "mode": "general",
                    "retrieved_ids": [],
                    "verified": True,
                    "lens": card(lens, name, answer),
                }
                append_user(store, body.conversation_id, email, question, index)
                return append_reply(store, body.conversation_id, email, payload, index)
        except KeyError:
            raise HTTPException(404, "找不到这段对话") from None
        except gate.MemoryUpdating as e:
            raise HTTPException(409, "分身正在整理记忆，整理完才能回答，请稍后再问") from e
        except LensUnavailable as e:
            raise HTTPException(404, NOT_NOW) from e
        except sqlite3.Error as e:
            raise HTTPException(503, "团队库暂时读不了，请稍后重试") from e
