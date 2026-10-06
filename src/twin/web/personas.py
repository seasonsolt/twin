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

from fastapi import FastAPI, HTTPException
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
                    "personas": [{"id": "default", "created_at": dt.datetime.now(dt.UTC).isoformat()}],
                }
                self.save()
            else:
                self.data = json.loads(self.path.read_text(encoding="utf-8"))

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

    def register(self, app: FastAPI) -> None:
        @app.get("/api/personas")
        def list_personas() -> list[dict[str, Any]]:
            with self.lock:
                return [self.view(entry) for entry in self.data["personas"]]

        @app.post("/api/personas", status_code=201)
        def create_persona(body: NameBody) -> dict[str, Any]:
            with self.lock:
                persona_id = "p-" + secrets.token_hex(5)
                directory = self.root / "personas" / persona_id
                private_directory(directory.parent)
                directory.parent.chmod(0o700)
                directory.mkdir(mode=0o700)
                with PersonaStore(directory / "twin.db") as store:
                    store.set_identity(body.name, "", None)
                    store.set_meta("onboarding_pending", "1")
                entry = {"id": persona_id, "created_at": dt.datetime.now(dt.UTC).isoformat()}
                self.data["personas"].append(entry)
                self.save()
                return self.view(entry)

        @app.delete("/api/personas/{persona_id}")
        def delete_persona(persona_id: str) -> dict[str, bool]:
            with self.lock:
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
        # Headers take precedence; queries support media elements that cannot send headers.
        persona_id = Headers(scope=scope).get("x-twin-persona")
        if persona_id is None and scope["method"] in {"GET", "HEAD"}:
            persona_id = parse_qs(scope.get("query_string", b"").decode(), keep_blank_values=True).get(
                "persona", [None]
            )[0]
        persona_id = persona_id if persona_id is not None else self.registry.data["default"]
        management = path == "/api/personas" or path.startswith("/api/personas/")
        try:
            with self.registry.lock:
                context = self.registry.application(persona_id)
                if not management:
                    self.registry.requests[persona_id] = self.registry.requests.get(persona_id, 0) + 1
        except HTTPException as exc:
            await JSONResponse({"detail": exc.detail}, status_code=exc.status_code)(scope, receive, send)
            return
        if management:
            await self.app(scope, receive, send)
        else:
            try:
                await context(scope, receive, send)
            finally:
                with self.registry.lock:
                    self.registry.requests[persona_id] -= 1
