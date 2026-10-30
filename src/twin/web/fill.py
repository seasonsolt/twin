"""Web routes of 补一补 (``/api/persona/fill...``): the questions to answer next, an answer read into draft memories,
what keeping them is worth, and keeping them in the tier the person chose (see ``persona.fill``). For the person alone:
what they keep is their own words. 人生回顾 (``/api/persona/life-review...``, see ``persona.life_review``) asks its own
questions stage by stage and goes on through the same draft, preview and keep; 生命叙事 (``/api/persona/life-story``,
see ``persona.life_story``) lays out what was told year by year."""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Annotated, Any, Literal

from fastapi import FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from ..config import Settings
from ..llm import LLMError
from ..persona import fill, heirs, life_review, life_story
from ..persona.coverage import LEVEL_LABELS, coverage_report
from ..persona.dimensions import FACET_BY_ID
from ..persona.profile import consented_facets
from ..persona.questionnaire import QUESTIONS
from ..persona.store import PersonaStore, stored_identity
from ..persona.tiers import default_tier, is_heir
from .backends import Backends
from .conversations import request_audience
from .handoffs import person

FacetId = Annotated[str, Field(min_length=3, max_length=5)]


class AskBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # The question, and the facet it is asked for.
    question: str = Field(min_length=1, max_length=8)
    facet: FacetId


class SkipBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=8)


class DraftBody(AskBody):
    answer: str = Field(min_length=1, max_length=fill.MAX_ANSWER_CHARS)


class KeptBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    facet: FacetId
    statement: str = Field(min_length=1, max_length=fill.MAX_STATEMENT_CHARS)
    choice: Literal["colleague", "self", "none"]


class KeepBody(AskBody):
    items: list[KeptBody] = Field(max_length=fill.MAX_DRAFTS)


def register(
    app: FastAPI,
    settings: Settings,
    backends: Backends,
    queue_build: Callable[[], None],
    lock: AbstractContextManager[Any],
    open_store: Callable[[], AbstractContextManager[PersonaStore]],
) -> None:
    def ask_of(body: AskBody) -> fill.Ask:
        life = life_review.QUESTION_BY_ID.get(body.question)
        if life is not None:
            if body.facet not in life.facets:
                raise HTTPException(404, "找不到这个问题")
            facet = FACET_BY_ID[body.facet]
            also = tuple(f for f in life.facets if f != facet.facet_id)
            return fill.Ask(
                life.question_id,
                life.text,
                facet.facet_id,
                facet.name,
                facet.dimension_id,
                0,
                default_tier(facet.facet_id),
                also,
            )
        question = next((q for q in QUESTIONS if q.qid == body.question), None)
        if question is None or body.facet not in FACET_BY_ID:
            raise HTTPException(404, "找不到这个问题")
        facet = FACET_BY_ID[body.facet]
        return fill.Ask(
            question.qid,
            question.text,
            facet.facet_id,
            facet.name,
            facet.dimension_id,
            0,
            default_tier(facet.facet_id),
        )

    def kept_of(items: list[KeptBody]) -> list[fill.Kept]:
        if any(i.facet not in FACET_BY_ID for i in items):
            raise HTTPException(400, "没有这个方面")
        kept = [fill.Kept(i.facet, " ".join(i.statement.split()), i.choice) for i in items]
        if any(not k.statement for k in kept):
            raise HTTPException(400, "结论不能是空的")
        return kept

    def worth(store: PersonaStore, ask: fill.Ask, kept: list[fill.Kept]) -> list[dict[str, Any]]:
        name = stored_identity(settings.db_path)[0] or settings.target_name
        found = fill.changes(store.list_items(), consented_facets(store), ask, name, kept)
        return [
            {
                "facet_id": c.facet_id,
                "facet": c.facet_name,
                "before": c.before,
                "after": c.after,
                "before_label": LEVEL_LABELS[c.before],
                "after_label": LEVEL_LABELS[c.after],
            }
            for c in found
        ]

    @app.get("/api/persona/fill")
    def questions(
        request: Request,
        facet: str | None = Query(default=None, max_length=5),
        dimension: str | None = Query(default=None, max_length=3),
    ) -> dict[str, Any]:
        """The next questions: for what the twin knows least, or for the one facet or aspect the person opened."""
        person(request)
        with open_store() as store:
            asked = fill.questions_for(
                store.list_items(),
                consented_facets(store),
                facet=facet,
                dimension=dimension,
                demand=store.chat_demand(),
            )
        return {
            "questions": [
                {
                    "id": a.question_id,
                    "text": a.text,
                    "facet": a.facet_id,
                    "facet_name": a.facet_name,
                    "level": a.level,
                    "level_label": LEVEL_LABELS[a.level],
                    "tier": a.tier,
                }
                for a in asked
            ]
        }

    @app.post("/api/persona/fill/draft")
    def read_answer(body: DraftBody, request: Request) -> dict[str, Any]:
        """The answer read into the memories it would become, to look at; nothing is kept."""
        person(request)
        ask = ask_of(body)
        name = stored_identity(settings.db_path)[0] or settings.target_name
        llm = backends.llm()
        try:
            with open_store() as store:
                drafts = fill.draft(store, llm, settings, name, ask, body.answer)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        except LLMError:
            # What a model backend says can hold prompts or addresses: not passed on.
            raise HTTPException(502, "暂时没能整理这段回答，请重试") from None
        kept = [fill.Kept(d.facet_id, d.statement, d.tier) for d in drafts]
        with open_store() as store:
            expected = worth(store, ask, kept)
        return {
            "drafts": [
                {"facet": d.facet_id, "facet_name": d.facet_name, "statement": d.statement, "tier": d.tier}
                for d in drafts
            ],
            "changes": expected,
        }

    @app.post("/api/persona/fill/preview")
    def preview(body: KeepBody, request: Request) -> dict[str, Any]:
        """How well each facet is known now and once the conclusions that are kept are stored."""
        person(request)
        ask, kept = ask_of(body), kept_of(body.items)
        with open_store() as store:
            return {"changes": worth(store, ask, kept)}

    @app.post("/api/persona/fill/keep")
    def keep(body: KeepBody, request: Request) -> dict[str, Any]:
        """Store the conclusions the person chose to keep, each in the tier they chose; the next build makes memories
        of them."""
        person(request)
        ask, kept = ask_of(body), kept_of(body.items)
        name = stored_identity(settings.db_path)[0] or settings.target_name
        with lock, open_store() as store:
            stored = fill.keep(store, ask, name, kept)
            expected = worth(store, ask, kept)
            # A question of 人生回顾 that was answered and looked at is not asked again, whatever was kept of it.
            life_review.mark(store, ask.question_id, answered=True)
        if stored:
            queue_build()
        return {"saved": len(stored), "changes": expected}

    @app.get("/api/persona/life-review")
    def life_questions(request: Request) -> dict[str, Any]:
        """人生回顾: the next questions, of the earliest stage of the person's life not yet told, and how far each stage
        has been told."""
        person(request)
        with open_store() as store:
            state = life_review.load_state(store)
            report = coverage_report(store.list_items(), consented_facets(store), demand=store.chat_demand())
        levels = {f.facet_id: f.level for f in report.facets}
        return {
            "questions": [
                {
                    "id": q.question_id,
                    "text": q.text,
                    "facet": q.facets[0],
                    "facet_name": FACET_BY_ID[q.facets[0]].name,
                    "level": levels.get(q.facets[0], 0),
                    "level_label": LEVEL_LABELS[levels.get(q.facets[0], 0)],
                    "tier": default_tier(q.facets[0]),
                    "stage": q.stage,
                    "stage_label": life_review.STAGE_LABELS[q.stage],
                }
                for q in life_review.next_questions(state)
            ],
            "stages": life_review.progress(state),
        }

    @app.post("/api/persona/life-review/skip")
    def skip_life_question(body: SkipBody, request: Request) -> dict[str, Any]:
        """Pass a question over: it is asked again once every other has been."""
        person(request)
        if body.question not in life_review.QUESTION_BY_ID:
            raise HTTPException(404, "找不到这个问题")
        with lock, open_store() as store:
            state = life_review.mark(store, body.question, answered=False)
        return {"stages": life_review.progress(state)}

    @app.get("/api/persona/life-story")
    def life_story_view(request: Request) -> dict[str, Any]:
        """生命叙事: the person's turning points, stories and what their life has meant, by year, gaps kept as gaps;
        and the ones whose year their words do not tell. The person's alone, and an heir's of what the will gives
        them (``persona.heirs``)."""
        audience = request_audience(request)
        if not is_heir(audience):
            person(request)
        with open_store() as store:
            items = heirs.usable_items(store, store.list_items(), audience)
        spans, undated = life_story.story(items, dt.date.today())

        def view(p: life_story.Placed) -> dict[str, Any]:
            facet = FACET_BY_ID[p.item.facet_id]
            return {
                "item_id": p.item.item_id,
                "facet_id": facet.facet_id,
                "facet_name": facet.name,
                "statement": p.item.statement,
                "basis": p.basis,
            }

        return {
            "years": [{"year": s.year, "until": s.until, "items": [view(p) for p in s.items]} for s in spans],
            "undated": [view(p) for p in undated],
            # The first year a conversation can look back to (时间切片): before it, nothing is known as of then.
            "since": life_story.known_since(items),
        }
