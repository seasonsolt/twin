"""Web routes of the handoffs (``/api/persona/handoffs...``): what a colleague's question left to the person, for the
person alone. A manager, a visitor or anyone who is not the person the twin is made for gets nothing here."""

from __future__ import annotations

import datetime as dt
import sqlite3
from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from ..config import Settings
from ..embed import Embedder
from ..handoffs import AWAY_DAYS, GROUP_MAX, KIND_LABELS, STATUS_LABELS, HandoffDesk, HandoffRefused
from ..llm import LLMError
from ..persona.store import PersonaStore
from ..persona.tiers import SELF
from ..teamanswers import BODY_MAX, TITLE_MAX, TeamAnswerRefused, TeamAnswers, clean, summary_title
from ..teamdb import Handoff, ReplyTier
from .backends import Backends, BackendUnavailable
from .conversations import owner, request_audience


class ReplyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=4000)
    # Keep the reply as a memory too; False writes it into the conversation only.
    remember: bool = True
    # Who may use it as a memory: ``colleague`` (by the defaults of the facets it falls under), ``self`` (only the
    # person themself) or ``none`` (not kept). Left out, ``remember`` says.
    tier: ReplyTier | None = None


class AcceptBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # A new date for the promise (改时间); the asker's own is kept when it is left out.
    due: dt.date | None = None


class CorrectBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=4000)


class AnswerBody(BaseModel):
    """What to make a team answer of: its title (the question, summed up) and words. Left out, they are the first
    question and the reply."""

    model_config = ConfigDict(extra="forbid")
    title: str = Field(default="", max_length=TITLE_MAX)
    body: str = Field(default="", max_length=BODY_MAX)


class ReplyManyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ids: list[str] = Field(min_length=1, max_length=GROUP_MAX)
    text: str = Field(min_length=1, max_length=4000)
    remember: bool = True
    tier: ReplyTier | None = None
    # 同时设为团队答案: the reply, once it is sent, for the whole team to quote.
    team_answer: AnswerBody | None = None


class DraftBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # The other questions of the same matter, answered with one reply (a card of several askers).
    also: list[str] = Field(default_factory=list, max_length=GROUP_MAX)


class MakeAnswerBody(AnswerBody):
    handoff_id: str = Field(min_length=1, max_length=100)


class ReviseBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=TITLE_MAX)
    body: str = Field(min_length=1, max_length=BODY_MAX)


def person(request: Request) -> str | None:
    """The person the twin is made for, who alone may read and settle its handoffs (any other signed-in person,
    managers included, is refused); returns their account."""
    if request_audience(request) != SELF or request.scope.get("twin_visitor"):
        raise HTTPException(403, "这些只有本人看得到")
    return owner(request)


def register(
    app: FastAPI, settings: Settings, desk: HandoffDesk, queue_build: Callable[[], None], backends: Backends
) -> None:
    def refused(failure: Exception) -> HTTPException:
        if isinstance(failure, KeyError):
            return HTTPException(404, "找不到这条，请刷新后重试")
        return HTTPException(409, str(failure))

    def kept(body: ReplyBody | ReplyManyBody) -> bool:
        """Whether the reply is also kept as a memory."""
        return body.tier != "none" if body.tier is not None else body.remember

    def settled(h: Handoff, me: str | None, *, remembered: bool = False) -> dict[str, Any]:
        with PersonaStore(settings.db_path) as store:
            view = desk.view(h, store)
        if remembered:
            queue_build()
        return {"handoff": view, "pending": desk.pending_count(me)}

    def team_ready() -> TeamAnswers:
        if desk.team is None or desk.answers is None:
            raise HTTPException(503, "团队库没有打开")
        return desk.answers

    def embedder_or_none() -> Embedder | None:
        """The embedding model, when it is set up: what tells questions of one matter apart works without it, only less
        well."""
        try:
            return backends.embedder()
        except BackendUnavailable:
            return None

    @app.get("/api/persona/handoffs")
    def list_handoffs(request: Request) -> dict[str, Any]:
        """Everything on the person's 你不在时 page."""
        me = person(request)
        team_ready()
        try:
            away = desk.away(me, embedder_or_none())
        except sqlite3.Error as e:
            raise HTTPException(503, "团队库暂时读不了，请稍后重试") from e
        return {
            "waiting": away.waiting,
            "guessed": away.guessed,
            "sourced": away.sourced,
            "sourced_count": away.sourced_count,
            "answered": away.answered,
            "shelved": away.shelved,
            "settled": away.settled,
            "groups": away.groups,
            "often": away.often,
            "answers": away.answers,
            "pending": len(away.waiting),
            "days": AWAY_DAYS,
            "kind_labels": KIND_LABELS,
            "status_labels": STATUS_LABELS,
        }

    @app.get("/api/persona/handoffs/count")
    def count_handoffs(request: Request) -> dict[str, int]:
        """How many wait for the person's decision: the number on their account."""
        me = person(request)
        team_ready()
        return {"pending": desk.pending_count(me)}

    @app.post("/api/persona/handoffs/{handoff_id}/reply")
    def reply(handoff_id: str, body: ReplyBody, request: Request) -> dict[str, Any]:
        """The person's own reply: it appears in the asker's conversation as theirs, and is kept as a memory."""
        me = person(request)
        team_ready()
        try:
            h = desk.reply(handoff_id, me, body.text, remember=body.remember, tier=body.tier)
        except (KeyError, HandoffRefused) as e:
            raise refused(e) from e
        return settled(h, me, remembered=kept(body))

    @app.post("/api/persona/handoffs/{handoff_id}/draft")
    def draft(handoff_id: str, request: Request, body: DraftBody | None = None) -> dict[str, str]:
        """请分身起草: words for the person to change and send; nothing is sent or kept. With ``also`` (the rest of a
        card of several askers), one reply for all of them, and their question summed up (``question``) for the card's
        title."""
        me = person(request)
        team_ready()
        llm, embedder = backends.chat_llm(), backends.embedder()
        try:
            drafted = desk.draft(handoff_id, me, llm, embedder, settings, body.also if body else ())
        except (KeyError, HandoffRefused) as e:
            raise refused(e) from e
        except LLMError:
            # What a model backend says can hold prompts or addresses: not passed on.
            raise HTTPException(502, "分身暂时无法起草，请重试") from None
        return {"text": drafted.text, **({"question": drafted.question} if drafted.question else {})}

    @app.post("/api/persona/handoffs/{handoff_id}/accept")
    def accept(handoff_id: str, request: Request, body: AcceptBody | None = None) -> dict[str, Any]:
        me = person(request)
        team_ready()
        try:
            h = desk.accept(handoff_id, me, body.due if body else None)
        except (KeyError, HandoffRefused) as e:
            raise refused(e) from e
        return settled(h, me)

    @app.post("/api/persona/handoffs/{handoff_id}/decline")
    def decline(handoff_id: str, request: Request) -> dict[str, Any]:
        me = person(request)
        team_ready()
        try:
            h = desk.decline(handoff_id, me)
        except (KeyError, HandoffRefused) as e:
            raise refused(e) from e
        return settled(h, me)

    @app.post("/api/persona/handoffs/{handoff_id}/dismiss")
    def dismiss(handoff_id: str, request: Request) -> dict[str, Any]:
        me = person(request)
        team_ready()
        try:
            h = desk.dismiss(handoff_id, me)
        except (KeyError, HandoffRefused) as e:
            raise refused(e) from e
        return settled(h, me)

    @app.post("/api/persona/handoffs/{handoff_id}/restore")
    def restore(handoff_id: str, request: Request) -> dict[str, Any]:
        me = person(request)
        team_ready()
        try:
            h = desk.restore(handoff_id, me)
        except (KeyError, HandoffRefused) as e:
            raise refused(e) from e
        return settled(h, me)

    @app.post("/api/persona/answers/{conversation_id}/{turn}/confirm")
    def confirm_answer(conversation_id: str, turn: int, request: Request) -> dict[str, bool]:
        """没错: an answer the twin guessed was right."""
        person(request)
        team_ready()
        try:
            desk.confirm_answer(conversation_id, turn)
        except KeyError as e:
            raise refused(e) from e
        return {"confirmed": True}

    @app.post("/api/persona/answers/{conversation_id}/{turn}/correct")
    def correct_answer(conversation_id: str, turn: int, body: CorrectBody, request: Request) -> dict[str, Any]:
        """更正: the person puts right an answer the twin guessed; the asker is told and the twin remembers it."""
        me = person(request)
        team_ready()
        try:
            h = desk.correct_answer(conversation_id, turn, me, body.text)
        except (KeyError, HandoffRefused) as e:
            raise refused(e) from e
        return settled(h, me, remembered=True)

    @app.post("/api/persona/handoffs/reply-many")
    def reply_many(body: ReplyManyBody, request: Request) -> dict[str, Any]:
        """One reply to several questions that are one matter: each asker gets it in their own conversation as the
        person's, each handoff is settled on its own. ``team_answer`` also makes it a team answer."""
        me = person(request)
        answers = team_ready()
        if body.team_answer is not None and body.tier in ("none", "self"):
            raise HTTPException(400, "设为团队答案的回复，同事要能用")
        try:
            if body.team_answer is not None:
                first = desk.handoff_of(body.ids[0], me)
                clean(body.team_answer.title or summary_title(first.question), body.team_answer.body or body.text)
            done, failed = desk.reply_many(body.ids, me, body.text, remember=body.remember, tier=body.tier)
        except TeamAnswerRefused as e:
            raise HTTPException(400, str(e)) from None
        except (KeyError, HandoffRefused) as e:
            raise refused(e) from e
        if not done:
            raise HTTPException(409, failed[0][1] if failed else "没有可以回复的")
        made = None
        team_answer_error: str | None = None
        if body.team_answer is not None:
            try:
                made = answers.view(
                    desk.make_team_answer(
                        done[0].id, me, body.team_answer.title, body.team_answer.body or body.text, embedder_or_none()
                    )
                )
            except (KeyError, HandoffRefused) as e:
                # The replies are sent; only the team answer did not come out, which the person can set again.
                team_answer_error = str(e) if not isinstance(e, KeyError) else "找不到这条回复，请刷新后重试"
        if kept(body) or made is not None:
            queue_build()
        return {
            "done": [h.id for h in done],
            "failed": [{"id": i, "detail": d} for i, d in failed],
            "team_answer": made,
            # Why the team answer was not made (the replies went out all the same); None when it was, or not asked for.
            "team_answer_error": team_answer_error,
            "pending": desk.pending_count(me),
        }

    @app.post("/api/persona/team-answers", status_code=201)
    def make_team_answer(body: MakeAnswerBody, request: Request) -> dict[str, Any]:
        """设为团队答案: the person's reply to a handoff, for the whole team to quote as it stands."""
        me = person(request)
        answers = team_ready()
        try:
            made = desk.make_team_answer(body.handoff_id, me, body.title, body.body, embedder_or_none())
        except (KeyError, HandoffRefused) as e:
            raise refused(e) from e
        queue_build()
        return {"team_answer": answers.view(made)}

    @app.post("/api/persona/handoffs/{handoff_id}/often/decline")
    def decline_often(handoff_id: str, request: Request) -> dict[str, bool]:
        """不用: do not offer to make this reply a team answer again."""
        me = person(request)
        team_ready()
        try:
            desk.decline_often(handoff_id, me)
        except KeyError as e:
            raise refused(e) from e
        return {"declined": True}

    @app.get("/api/persona/team-answers")
    def list_team_answers(request: Request) -> dict[str, Any]:
        """The team answers the person set, in force or possibly out of date first."""
        person(request)
        answers = team_ready()
        mine = answers.team.team_answers(persona_id=desk.persona_id, statuses=("valid", "stale"))
        # Those that may be out of date first; each group the newest confirmed first.
        mine.sort(key=lambda a: a.confirmed_at, reverse=True)
        mine.sort(key=lambda a: a.status != "stale")
        return {"team_answers": [answers.view(a) for a in mine]}

    def answer_change(answers: TeamAnswers, change: Callable[[], Any]) -> dict[str, Any]:
        try:
            return {"team_answer": answers.view(change())}
        except KeyError:
            raise HTTPException(404, "找不到这条团队答案，请刷新后重试") from None
        except TeamAnswerRefused as e:
            raise HTTPException(409, str(e)) from None

    @app.patch("/api/persona/team-answers/{answer_id}")
    def revise_team_answer(answer_id: str, body: ReviseBody, request: Request) -> dict[str, Any]:
        """The person puts the answer right: it stands again, with the new words, from today."""
        me = person(request)
        answers = team_ready()
        return answer_change(
            answers, lambda: answers.revise(answer_id, desk.persona_id, me, body.title, body.body, embedder_or_none())
        )

    @app.post("/api/persona/team-answers/{answer_id}/keep")
    def keep_team_answer(answer_id: str, request: Request) -> dict[str, Any]:
        """仍然有效: what the person said since does not change the answer."""
        me = person(request)
        answers = team_ready()

        def keep() -> Any:
            with PersonaStore(settings.db_path) as store:
                return answers.keep(answer_id, desk.persona_id, me, store, settings)

        return answer_change(answers, keep)

    @app.post("/api/persona/team-answers/{answer_id}/withdraw")
    def withdraw_team_answer(answer_id: str, request: Request) -> dict[str, Any]:
        """撤回: nobody's twin quotes the answer any more; conversations it already appeared in stay as they were."""
        me = person(request)
        answers = team_ready()
        return answer_change(answers, lambda: answers.withdraw(answer_id, desk.persona_id, me))
