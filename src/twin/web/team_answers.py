"""``POST /api/personas/team-answers/{id}/ask``: the asker is not satisfied with a team answer and asks the person who
gave it.

The card under a twin's reply has 问某某本人. Pressing it opens a conversation of the asker's with the person's
twin, in the asker's name, that holds their question and one answer of the twin's, which says the question was handed
on, and makes the handoff of it: the person finds it on their 你不在时 page as any colleague's question, and their reply
comes back into that conversation. It is the asker who decides to bother the person; nothing here happens on its own.
Asking twice about the same thing, while the person has not answered, is one handoff: the second press is told where
the first one went.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Callable

import anyio
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from ..handoffs import HandoffDesk
from ..persona.followups import followup_id
from ..persona.store import PersonaStore
from ..persona.tiers import COLLEAGUE
from ..teamanswers import card
from ..teamdb import TeamDB
from .conversations import ConversationIndex, request_asker_name
from .personas import Personas


class AskBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # What the asker wants to know now; the answer's own title when left out.
    question: str = Field(default="", max_length=2000)


def register_all(
    app: FastAPI,
    registry: Personas,
    team: TeamDB,
    desk_for: Callable[[str], HandoffDesk],
    name_of: Callable[[str], str],
) -> None:
    # Two presses at once are told apart by looking at what the first one made, so they go one after the other.
    one_at_a_time = threading.Lock()

    def ask_owner(request: Request, answer_id: str, question: str) -> dict[str, object]:
        with one_at_a_time:
            return _ask_owner(request, answer_id, question)

    def _ask_owner(request: Request, answer_id: str, question: str) -> dict[str, object]:
        identity = request.scope["twin_identity"]
        asker = identity["email"]
        answer = team.get_team_answer(answer_id)
        if answer is None or answer.status == "withdrawn":
            raise HTTPException(404, "这条团队答案已经撤回了")
        entry = registry.entry(answer.persona_id)
        name = name_of(answer.persona_id)
        if entry is None or entry["id"] in registry.removing:
            raise HTTPException(404, "找不到这条团队答案的主人")
        member = entry.get("member")
        if not member:
            raise HTTPException(409, f"{name}还没认领分身，请直接联系本人")
        if asker is None or member == asker:
            raise HTTPException(400, "这是你自己确认的答案")
        if not registry.visible(entry, identity):
            # The conversation would be in a twin the asker cannot open: the person's reply could not reach them.
            raise HTTPException(409, f"{name}的分身没有对你开放，请直接联系本人")
        desk = desk_for(answer.persona_id)
        asked = " ".join((question or answer.title).split())
        try:
            waiting = next(
                (
                    h
                    for h in team.handoffs(persona_id=answer.persona_id, statuses=("delivered", "writing"))
                    if h.asker == asker and h.conversation_id is not None and h.group_key == followup_id(asked)
                ),
                None,
            )
        except sqlite3.Error as e:
            raise HTTPException(503, "团队库暂时读不了，请稍后重试") from e
        if waiting is not None:
            # Pressed before (the page was reloaded since, or in another window): it is on its way already.
            return {
                "persona_id": answer.persona_id,
                "conversation_id": waiting.conversation_id,
                "handoff": desk.asker_view(waiting),
            }
        reply = f"团队答案你还有疑问，已转给{name}本人，等他回复。"
        payload = {
            "reply": reply,
            "citations": [],
            "confidence": 1.0,
            "abstain": False,
            "abstain_reason": "",
            "mode": "general",
            "retrieved_ids": [],
            "verified": True,
            "team_answers": [card(answer, name)],
        }
        index = ConversationIndex(team, answer.persona_id)
        try:
            with PersonaStore(registry.db_path_of(answer.persona_id)) as store:
                conversation_id = store.create_conversation(asker)
                index.created(store, conversation_id, asker, COLLEAGUE, request_asker_name(request))
                store.append_conversation_turn(conversation_id, asker, "user", asked)
                store.append_conversation_turn(conversation_id, asker, "twin", reply, payload)
                index.touched(store, conversation_id)
                handoff = desk.hand_over(
                    store,
                    conversation_id,
                    asker,
                    request_asker_name(request),
                    f"对团队答案「{answer.title}」还有疑问：{asked}",
                )
        except sqlite3.Error as e:
            raise HTTPException(503, "团队库暂时读不了，请稍后重试") from e
        if handoff is None:
            raise HTTPException(409, f"没能转给{name}本人，请直接联系他")
        return {"persona_id": answer.persona_id, "conversation_id": conversation_id, "handoff": handoff}

    @app.post("/api/personas/team-answers/{answer_id}/ask")
    async def ask(answer_id: str, request: Request, body: AskBody | None = None) -> dict[str, object]:
        """还有疑问，问某某: hand the asker's question to the person who confirmed the answer, in the asker's name."""
        return await anyio.to_thread.run_sync(ask_owner, request, answer_id, body.question if body else "")
