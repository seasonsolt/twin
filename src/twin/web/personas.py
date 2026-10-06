"""Private persona registry and request routing to isolated settings/route contexts."""

from __future__ import annotations

import datetime as dt
import json
import secrets
import shutil
import threading
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.datastructures import Headers
from starlette.types import ASGIApp, Receive, Scope, Send

from ..assets import AssetStore
from ..config import Settings
from ..persona.store import PersonaStore, stored_identity
from ..util import private_directory
from .jobs import JobManager


class NameBody(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    name: str = Field(min_length=1, max_length=20)


class Personas:
    def __init__(self, settings: Settings, jobs: JobManager) -> None:
        self.settings, self.jobs = settings, jobs
        self.root = settings.db_path.parent
        self.path = self.root / "personas.json"
        self.lock = threading.RLock()
        self.apps: dict[str, FastAPI] = {}
        self.requests: dict[str, int] = {}
        self.make_app: Callable[[str, Settings], FastAPI]
        with self.lock:
            if not self.path.exists():
                self.data: dict[str, Any] = {
                    "default": "default",
                    "personas": [{"id": "default", "owner": None, "created_at": dt.datetime.now(dt.UTC).isoformat()}],
                }
                self.save()
            else:
                self.data = json.loads(self.path.read_text(encoding="utf-8"))
                if any("owner" not in entry for entry in self.data["personas"]):
                    for entry in self.data["personas"]:
                        entry.setdefault("owner", None)
                    self.save()

    def save(self) -> None:
        private_directory(self.root)
        AssetStore.write(self.path, json.dumps(self.data, ensure_ascii=False).encode())

    def settings_for(self, persona_id: str) -> Settings:
        if not any(p["id"] == persona_id for p in self.data["personas"]):
            raise HTTPException(404, "分身不存在")
        if persona_id == self.data["default"]:
            return self.settings.model_copy()
        return self.settings.model_copy(
            update={
                "db_path": self.root / "personas" / persona_id / "twin.db",
                "target_name": stored_identity(self.root / "personas" / persona_id / "twin.db")[0] or "本人",
                "target_aliases": [],
                "avatar": self.settings.avatar.model_copy(update={"image_path": None}),
                "video": self.settings.video.model_copy(update={"require_assets": True}),
            }
        )

    def application(self, persona_id: str) -> FastAPI:
        with self.lock:
            settings = self.settings_for(persona_id)
            if persona_id not in self.apps:
                self.apps[persona_id] = self.make_app(persona_id, settings)
            return self.apps[persona_id]

    def view(self, entry: dict[str, Any]) -> dict[str, Any]:
        persona_id = entry["id"]
        settings = self.settings_for(persona_id)
        name, _ = stored_identity(settings.db_path)
        portrait = AssetStore(settings.db_path).path("portrait")
        with PersonaStore(settings.db_path) as store:
            sources = len(store.list_sources())
        return {
            **entry,
            "name": name or settings.target_name,
            "avatar_url": f"/api/media/avatar-image?persona={persona_id}"
            if portrait or settings.avatar.image_path
            else None,
            "sources": sources,
            "is_default": persona_id == self.data["default"],
        }

    def accessible(self, entry: dict[str, Any], identity: dict[str, Any]) -> bool:
        return bool(identity["admin"] or (entry.get("owner") and entry["owner"] == identity["email"]))

    def check_owner(self, persona_id: str, identity: dict[str, Any]) -> None:
        if not any(p["id"] == persona_id and self.accessible(p, identity) for p in self.data["personas"]):
            raise HTTPException(404, "分身不存在")

    def register(self, app: FastAPI) -> None:
        @app.get("/api/personas")
        def list_personas(request: Request) -> list[dict[str, Any]]:
            with self.lock:
                return [
                    self.view(entry)
                    for entry in self.data["personas"]
                    if self.accessible(entry, request.scope["twin_identity"])
                ]

        @app.post("/api/personas", status_code=201)
        def create_persona(body: NameBody, request: Request) -> dict[str, Any]:
            with self.lock:
                identity = request.scope["twin_identity"]
                limit = self.settings.auth.max_personas_per_member
                if (
                    not identity["admin"]
                    and sum(p.get("owner") == identity["email"] for p in self.data["personas"]) >= limit
                ):
                    raise HTTPException(409, f"最多可以建 {limit} 个分身")
                persona_id = "p-" + secrets.token_hex(5)
                directory = self.root / "personas" / persona_id
                private_directory(directory.parent)
                directory.parent.chmod(0o700)
                directory.mkdir(mode=0o700)
                with PersonaStore(directory / "twin.db") as store:
                    store.set_identity(body.name, "", None)
                    store.set_meta("onboarding_pending", "1")
                entry = {
                    "id": persona_id,
                    "owner": identity["email"],
                    "created_at": dt.datetime.now(dt.UTC).isoformat(),
                }
                self.data["personas"].append(entry)
                self.save()
                return self.view(entry)

        @app.delete("/api/personas/{persona_id}")
        def delete_persona(persona_id: str, request: Request) -> dict[str, bool]:
            with self.lock:
                self.check_owner(persona_id, request.scope["twin_identity"])
                settings = self.settings_for(persona_id)
                if persona_id == self.data["default"]:
                    raise HTTPException(400, "默认分身不能删除")
                context = self.apps.get(persona_id)
                if (
                    self.requests.get(persona_id, 0)
                    or self.jobs.has_active(persona_id)
                    or (context is not None and not context.state.processing.close_if_idle())
                ):
                    raise HTTPException(409, "这个分身还有任务在运行，请等任务结束后再删除")
                self.apps.pop(persona_id, None)
                shutil.rmtree(settings.db_path.parent)
                self.data["personas"] = [p for p in self.data["personas"] if p["id"] != persona_id]
                self.save()
                return {"deleted": True}


class PersonaMiddleware:
    def __init__(self, app: ASGIApp, registry: Personas) -> None:
        self.app, self.registry = app, registry

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = str(scope.get("path", ""))
        if scope["type"] != "http" or not path.startswith("/api/"):
            await self.app(scope, receive, send)
            return
        if path.startswith("/api/auth/") or path == "/api/whoami" or path.startswith("/api/admin/"):
            await self.app(scope, receive, send)
            return
        identity = scope["twin_identity"]
        # Headers take precedence; queries support media elements that cannot send headers.
        persona_id = Headers(scope=scope).get("x-twin-persona")
        if persona_id is None:
            persona_id = parse_qs(scope.get("query_string", b"").decode(), keep_blank_values=True).get(
                "persona", [None]
            )[0]
        management = path == "/api/personas" or path.startswith("/api/personas/")
        try:
            with self.registry.lock:
                if persona_id is not None:
                    self.registry.check_owner(persona_id, identity)
                if management:
                    context = None
                else:
                    if persona_id is None:
                        persona_id = (
                            self.registry.data["default"]
                            if identity["admin"]
                            else next(
                                (
                                    p["id"]
                                    for p in self.registry.data["personas"]
                                    if self.registry.accessible(p, identity)
                                ),
                                None,
                            )
                        )
                    if persona_id is None:
                        await JSONResponse({"detail": "先新建一个分身", "code": "no_persona"}, status_code=409)(
                            scope, receive, send
                        )
                        return
                    context = self.registry.application(persona_id)
                    self.registry.requests[persona_id] = self.registry.requests.get(persona_id, 0) + 1
        except HTTPException as exc:
            await JSONResponse({"detail": exc.detail}, status_code=exc.status_code)(scope, receive, send)
            return
        if management:
            await self.app(scope, receive, send)
        else:
            assert context is not None and persona_id is not None
            try:
                await context(scope, receive, send)
            finally:
                with self.registry.lock:
                    self.registry.requests[persona_id] -= 1
