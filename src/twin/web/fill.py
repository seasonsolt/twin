"""Web routes of 补一补 (``/api/persona/fill...``): the questions to answer next, an answer read into draft memories,
what keeping them is worth, and keeping them in the tier the person chose (see ``persona.fill``). For the person alone:
what they keep is their own words."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Annotated, Any, Literal

from fastapi import FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from ..config import Settings
from ..llm import LLMError
from ..persona import fill
from ..persona.coverage import LEVEL_LABELS
from ..persona.dimensions import FACET_BY_ID
from ..persona.profile import consented_facets
from ..persona.questionnaire import QUESTIONS
from ..persona.store import PersonaStore, stored_identity
from ..persona.tiers import default_tier
from .backends import Backends
from .handoffs import person

FacetId = Annotated[str, Field(min_length=3, max_length=5)]


class AskBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # The question, and the facet it is asked for.
    question: str = Field(min_length=1, max_length=8)
    facet: FacetId


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
        if stored:
            queue_build()
        return {"saved": len(stored), "changes": expected}
