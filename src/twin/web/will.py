"""Web routes of 数字遗嘱 (``/api/persona/will``, see ``persona.will``): the person reads their will, names, changes
and takes out heirs, and reads every change made to it. For the person alone; the word that opens the twin to an heir
comes in with the request that sets it and is never sent back, nor its hash."""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from pydantic import Field

from ..persona import companion, lifecycle, will
from ..persona.store import PersonaStore
from .handoffs import person

# Who changed the will, where the twin knows no account for its person (the persona edition on one's own machine).
SELF_ACTOR = "self"
# How many of the person's own words are offered to choose from for an heir's goodbye.
WORDS_OFFERED = 30


class HeirBody(will.HeirDraft):
    # The word that opens the twin to this heir: required when naming them; None keeps theirs on a change.
    password: str | None = Field(default=None, max_length=will.MAX_PASSWORD_CHARS)


def _draft(body: HeirBody) -> will.HeirDraft:
    return will.HeirDraft.model_validate(body.model_dump(exclude={"password"}))


def register(
    app: FastAPI,
    lock: AbstractContextManager[Any],
    open_store: Callable[[], AbstractContextManager[PersonaStore]],
) -> None:
    @app.get("/api/persona/will")
    def read(request: Request) -> dict[str, Any]:
        """The will as it stands: its heirs, without anything of their words, and whether the memory is sealed (when
        nothing in it can be changed any more)."""
        person(request)
        with open_store() as store:
            heirs = will.load(store)
            sealed = lifecycle.sealed(store)
        return {"heirs": [h.model_dump(mode="json") for h in heirs], "sealed": sealed}

    @app.get("/api/persona/will/words")
    def words(request: Request) -> dict[str, Any]:
        """What the person can choose to leave with an heir after the goodbye: things they said themself of what they
        value and how they decide, most said first."""
        person(request)
        with open_store() as store:
            found = companion.own_words(store.list_items(), WORDS_OFFERED)
        return {"words": [{"id": w.expression_id, "quote": w.quote, "date": w.date} for w in found]}

    @app.post("/api/persona/will/heirs")
    def add(body: HeirBody, request: Request) -> dict[str, Any]:
        """Name an heir, with the word that will open the twin to them."""
        actor = person(request) or SELF_ACTOR
        if body.password is None:
            raise HTTPException(400, "请设置这位继承人开启用的口令")
        try:
            with lock, open_store() as store:
                heir = will.add(store, _draft(body), body.password, actor, dt.datetime.now())
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        return {"heir": heir.model_dump(mode="json")}

    @app.put("/api/persona/will/heirs/{heir_id}")
    def update(heir_id: str, body: HeirBody, request: Request) -> dict[str, Any]:
        """Write an heir anew; their word is set again only when the request carries one."""
        actor = person(request) or SELF_ACTOR
        try:
            with lock, open_store() as store:
                heir = will.update(store, heir_id, _draft(body), body.password, actor, dt.datetime.now())
        except KeyError:
            raise HTTPException(404, "找不到这位继承人，请刷新后重试") from None
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        return {"heir": heir.model_dump(mode="json")}

    @app.delete("/api/persona/will/heirs/{heir_id}")
    def remove(heir_id: str, request: Request) -> dict[str, Any]:
        """Take an heir out of the will; the history keeps what it gave them."""
        actor = person(request) or SELF_ACTOR
        try:
            with lock, open_store() as store:
                will.remove(store, heir_id, actor, dt.datetime.now())
        except KeyError:
            raise HTTPException(404, "找不到这位继承人，请刷新后重试") from None
        return {"ok": True}

    @app.get("/api/persona/will/history")
    def changes(request: Request) -> dict[str, Any]:
        """Every change to the will, oldest first, each with the whole will after it."""
        person(request)
        with open_store() as store:
            kept = will.history(store)
        return {"changes": [c.model_dump(mode="json") for c in kept]}
