"""Web routes of 继承人开启 (``/api/heir``, see ``persona.heir_door``): an heir opens the twin with their name and word,
and leaves; and the middleware that knows an heir's request by their session cookie.

An heir's cookie names the twin and their session (``<twin>.<token>``) and lasts until the browser closes. While it
is live, every request from that browser is the heir's (``conversations.HEIR_SCOPE``), to that twin alone
(``personas.HEIR_PERSONA_SCOPE``), whatever else the browser could reach; ``persona.HeirMiddleware`` then lets it
reach only what is meant for an heir. ``/api/whoami`` tells the page who the heir is (``auth.HEIR_VIEW``)."""

from __future__ import annotations

import datetime as dt
import threading
import time
from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool
from starlette.types import ASGIApp, Receive, Scope, Send

from ..persona import heir_door, will
from ..persona.store import PersonaStore
from .auth import HEIR_VIEW, forwarded_prefix, secure_cookie
from .conversations import HEIR_SCOPE
from .personas import HEIR_PERSONA_SCOPE, Personas

COOKIE = "twin_heir"
WRONG = "称呼或口令不对"


class OpenBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(max_length=64)
    password: str = Field(max_length=will.MAX_PASSWORD_CHARS)
    # The heir has read that opening seals the memory for good; only the first opening asks.
    confirm: bool = False


def _cookie(request: Request) -> tuple[str, str] | None:
    """The twin and the session token an heir's cookie names."""
    persona_id, _, token = request.cookies.get(COOKIE, "").rpartition(".")
    return (persona_id, token) if persona_id and token else None


def _wait(seconds: int) -> JSONResponse:
    minutes = max(1, -(-seconds // 60))
    return JSONResponse(
        {"detail": f"试错太多次，请 {minutes} 分钟后再试", "code": "heir_cooldown", "retry_after": seconds},
        status_code=429,
        headers={"Retry-After": str(seconds)},
    )


def register(
    app: FastAPI,
    persona_id: str,
    lock: AbstractContextManager[Any],
    open_store: Callable[[], AbstractContextManager[PersonaStore]],
) -> None:
    # One try at a time, so tries that come together are counted one after the other.
    door = threading.Lock()

    def forget(request: Request, response: Response) -> None:
        path = forwarded_prefix(request) + "/"
        response.delete_cookie(COOKIE, path=path, httponly=True, secure=secure_cookie(request), samesite="strict")

    @app.post("/api/heir/open")
    def open_(body: OpenBody, request: Request, response: Response) -> Any:
        """Let an heir in by their name and word: ``confirm`` when the memory is not sealed yet and they have still to
        say opening may seal it; ``open`` with their session cookie once they are in."""
        try:
            with door, lock, open_store() as store:
                opened = heir_door.open_door(
                    store, body.name, body.password, confirm=body.confirm, now=dt.datetime.now(dt.UTC)
                )
        except heir_door.CoolingDown as e:
            return _wait(e.seconds)
        except heir_door.WrongWord:
            return JSONResponse({"detail": WRONG, "code": "heir_wrong"}, status_code=400)
        if opened is None:
            return {"status": "confirm"}
        response.set_cookie(
            COOKIE,
            f"{persona_id}.{opened.token}",
            httponly=True,
            secure=secure_cookie(request),
            samesite="strict",
            path=forwarded_prefix(request) + "/",
        )
        return {
            "status": "open",
            "heir": {"id": opened.heir.heir_id, "name": opened.heir.name},
            "sealed_now": opened.sealed_now,
        }

    @app.post("/api/heir/leave")
    def leave(request: Request, response: Response) -> dict[str, bool]:
        """End the heir's session on this browser, so the next one to sit here does not enter as them."""
        if (named := _cookie(request)) and named[0] == persona_id:
            with lock, open_store() as store:
                heir_door.leave(store, named[1])
        forget(request, response)
        return {"ok": True}


class HeirSessionMiddleware:
    """Know an heir's request by their live session cookie (``heir_door.session_at``) and mark it as theirs, to their
    twin; a cookie that opens nothing changes nothing. It sits inside sign-in and outside ``HeirMiddleware``."""

    def __init__(self, app: ASGIApp, registry: Personas) -> None:
        self.app, self.registry = app, registry

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and str(scope.get("path", "")).startswith("/api/"):
            named = _cookie(Request(scope))
            if named and (found := await run_in_threadpool(self.resolve, *named)):
                persona_id, session = found
                scope[HEIR_SCOPE] = session.heir_id
                scope[HEIR_PERSONA_SCOPE] = persona_id
                scope[HEIR_VIEW] = {
                    "id": session.heir_id,
                    "name": session.name,
                    "person": session.person,
                    "persona": persona_id,
                }
        await self.app(scope, receive, send)

    def resolve(self, persona_id: str, token: str) -> tuple[str, heir_door.Session] | None:
        # Only a twin the registry knows: the id becomes a path.
        if self.registry.entry(persona_id) is None:
            return None
        session = heir_door.session_at(self.registry.db_path_of(persona_id), token, time.time())
        return (persona_id, session) if session else None
