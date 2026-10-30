"""Web routes of 剖析观察 (``/api/persona/observations``, see ``persona.observations``): the observations made last,
making them again, and the person's mark on each. For the person alone."""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from ..config import Settings
from ..llm import LLMError
from ..persona import observations
from ..persona.sources import ExpressionView
from ..persona.store import PersonaStore
from .backends import Backends
from .handoffs import person


class MarkBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # None takes the mark back.
    mark: observations.Mark | None


def view(state: observations.ObservationState) -> dict[str, Any]:
    return {
        "made_at": state.made_at,
        "kinds": [{"id": k, "label": label} for k, label in observations.KINDS],
        "observations": [
            {
                "id": o.observation_id,
                "kind": o.kind,
                "kind_label": observations.KIND_LABELS[o.kind],
                "text": o.text,
                "quotes": [
                    {"quote": q.quote, "date": q.date.isoformat() if q.date else None, "dream": q.item_id is None}
                    for q in o.quotes
                ],
                "mark": o.mark,
            }
            for o in state.observations
        ],
    }


def register(
    app: FastAPI,
    settings: Settings,
    backends: Backends,
    lock: AbstractContextManager[Any],
    open_store: Callable[[], AbstractContextManager[PersonaStore]],
) -> None:
    @app.get("/api/persona/observations")
    def latest(request: Request) -> dict[str, Any]:
        """The observations made last, with the person's marks."""
        person(request)
        with open_store() as store:
            return view(observations.load_state(store))

    @app.post("/api/persona/observations")
    def make(request: Request) -> dict[str, Any]:
        """Make the observations again from the memories and the dreams the person wrote down."""
        person(request)
        llm = backends.llm()
        with open_store() as store:
            items = store.list_items()
            expressions = ExpressionView(store, settings)
            dreams = [
                (e.text, e.date) for e in expressions.select(target_only=True, mirror=True) if e.mirror == "dream"
            ]
        dreams.sort(key=lambda d: d[1] or dt.date.min, reverse=True)
        try:
            with lock, open_store() as store:
                state = observations.make(
                    store, llm, items, dreams, expressions.mask, expressions.restore, dt.datetime.now()
                )
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        except LLMError:
            # What a model backend says can hold prompts or addresses: not passed on.
            raise HTTPException(502, "暂时没能生成观察，请重试") from None
        return view(state)

    @app.put("/api/persona/observations/{observation_id}/mark")
    def mark(observation_id: str, body: MarkBody, request: Request) -> dict[str, Any]:
        """Mark an observation 对, 不对 or 对但没用, or take the mark back."""
        person(request)
        try:
            with lock, open_store() as store:
                state = observations.mark(store, observation_id, body.mark, dt.datetime.now())
        except KeyError:
            raise HTTPException(404, "找不到这条观察，请刷新后重试") from None
        return view(state)
