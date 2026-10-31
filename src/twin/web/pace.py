"""Web routes of 节奏提醒 (``/api/persona/pace``, see ``persona.pace``): the pace the person sets for talking with their
twin, and the one line when it is reached. For the person alone."""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Any

from fastapi import FastAPI, Request

from ..persona import pace
from ..persona.store import PersonaStore
from .handoffs import person


def register(
    app: FastAPI,
    lock: AbstractContextManager[Any],
    open_store: Callable[[], AbstractContextManager[PersonaStore]],
) -> None:
    @app.get("/api/persona/pace")
    def read(request: Request) -> dict[str, Any]:
        """The pace, how long and how often the person talked, and the line to show now (null when none)."""
        me = person(request)
        with open_store() as store:
            return pace.state(store, me, dt.datetime.now().astimezone())

    @app.put("/api/persona/pace")
    def set_pace(body: pace.Pace, request: Request) -> dict[str, Any]:
        """Set the pace, or turn it off."""
        me = person(request)
        with lock, open_store() as store:
            pace.put(store, body)
            return pace.state(store, me, dt.datetime.now().astimezone())

    @app.post("/api/persona/pace/go-on")
    def go_on(request: Request) -> dict[str, Any]:
        """The person goes on talking: the line is not said again today."""
        me = person(request)
        now = dt.datetime.now().astimezone()
        with lock, open_store() as store:
            pace.go_on(store, now.date())
            return pace.state(store, me, now)
