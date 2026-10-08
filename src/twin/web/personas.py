"""Private persona registry and request routing to isolated settings/route contexts."""

from __future__ import annotations

import datetime as dt
import json
import re
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
from ..media.schema import default_avatar
from ..persona.store import PersonaStore, stored_avatar, stored_identity
from ..util import private_directory
from .jobs import JobManager


class NameBody(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    name: str = Field(min_length=1, max_length=20)


class VisibilityBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    public: bool


# Visitors of a public twin can only talk to it; its memories and settings stay with the owner.
VISITOR_ROUTES = [
    (method, re.compile(pattern))
    for method, pattern in [
        ("GET", r"/api/(status|identity|persona/state)"),
        ("GET", r"/api/media/(capabilities|avatar\.vrm|avatar-image)"),
        ("GET", r"/api/media/(audio|video|video/jobs)/[^/]+"),
        ("POST", r"/api/media/(audio|video)"),
        ("POST", r"/api/persona/chat/stream"),
        ("GET|POST", r"/api/conversations"),
        ("GET|PATCH|DELETE", r"/api/conversations/[^/]+"),
    ]
]


def visitor_route(method: str, path: str) -> bool:
    return any(method in methods.split("|") and pattern.fullmatch(path) for methods, pattern in VISITOR_ROUTES)


class Personas:
    def __init__(self, settings: Settings, jobs: JobManager, *, clock: Callable[[], dt.datetime] | None = None) -> None:
        self.settings, self.jobs = settings, jobs
        self.clock = clock or (lambda: dt.datetime.now(dt.UTC))
        self.root = settings.db_path.parent
        self.path = self.root / "personas.json"
        self.lock = threading.RLock()
        self.apps: dict[str, FastAPI] = {}
        self.requests: dict[str, int] = {}
        self.removing: set[str] = set()
        self.make_app: Callable[[str, Settings], FastAPI]
        self.on_removed: Callable[[str], None] = lambda _: None
        self.on_restored: Callable[[str], None] = lambda _: None
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

    def purge_trash(self) -> None:
        expired = [
            entry
            for entry in self.data["personas"]
            if entry.get("deleted_at")
            and dt.datetime.fromisoformat(entry["deleted_at"]) + dt.timedelta(days=7) <= self.clock()
        ]
        for entry in expired:
            directory = self.root / "trash" / entry["trash_directory"]
            if directory.exists():
                shutil.rmtree(directory)
        if expired:
            self.data["personas"] = [entry for entry in self.data["personas"] if entry not in expired]
            self.save()

    def settings_for(self, persona_id: str) -> Settings:
        if persona_id in self.removing or not any(
            p["id"] == persona_id and not p.get("deleted_at") for p in self.data["personas"]
        ):
            raise HTTPException(404, "分身不存在")
        if persona_id == self.data["default"]:
            return self.settings.model_copy()
        return self.settings.model_copy(
            update={
                "db_path": self.root / "personas" / persona_id / "twin.db",
                "target_name": stored_identity(self.root / "personas" / persona_id / "twin.db")[0] or "本人",
                "target_aliases": [],
                "avatar": self.settings.avatar.model_copy(
                    update={"image_path": None, "preset": default_avatar(persona_id)}
                ),
                "video": self.settings.video.model_copy(update={"require_assets": True}),
            }
        )

    def application(self, persona_id: str) -> FastAPI:
        with self.lock:
            settings = self.settings_for(persona_id)
            if persona_id not in self.apps:
                self.apps[persona_id] = self.make_app(persona_id, settings)
            return self.apps[persona_id]

    def view(self, entry: dict[str, Any], identity: dict[str, Any]) -> dict[str, Any]:
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
            "avatar_preset": stored_avatar(settings.db_path, settings.avatar.preset),
            "sources": sources,
            "is_default": persona_id == self.data["default"],
            "public": bool(entry.get("public")),
            "can_manage": self.accessible(entry, identity),
        }

    def accessible(self, entry: dict[str, Any], identity: dict[str, Any]) -> bool:
        return bool(identity["admin"] or (entry.get("owner") and entry["owner"] == identity["email"]))

    def visible(self, entry: dict[str, Any], identity: dict[str, Any]) -> bool:
        return (
            entry["id"] not in self.removing
            and not entry.get("deleted_at")
            and (bool(entry.get("public")) or self.accessible(entry, identity))
        )

    def check_owner(self, persona_id: str, identity: dict[str, Any], *, deleted: bool = False) -> None:
        if persona_id in self.removing or not any(
            p["id"] == persona_id and bool(p.get("deleted_at")) == deleted and self.accessible(p, identity)
            for p in self.data["personas"]
        ):
            raise HTTPException(404, "分身不存在")

    def check_access(self, persona_id: str, identity: dict[str, Any], method: str, path: str) -> bool:
        """Return whether the request comes from a visitor rather than someone who manages the twin."""
        entry = next((p for p in self.data["personas"] if p["id"] == persona_id), None)
        if entry is None or not self.visible(entry, identity):
            raise HTTPException(404, "分身不存在")
        if self.accessible(entry, identity):
            return False
        if not visitor_route(method, path):
            raise HTTPException(403, "这是别人的公开分身，只能聊天")
        return True

    def register(self, app: FastAPI) -> None:
        @app.get("/api/personas")
        def list_personas(request: Request) -> list[dict[str, Any]]:
            with self.lock:
                self.purge_trash()
                identity = request.scope["twin_identity"]
                return [self.view(entry, identity) for entry in self.data["personas"] if self.visible(entry, identity)]

        @app.get("/api/personas/trash")
        def list_trash(request: Request) -> list[dict[str, Any]]:
            with self.lock:
                self.purge_trash()
                identity = request.scope["twin_identity"]
                return [
                    {
                        "id": entry["id"],
                        "name": entry["name"],
                        "deleted_at": entry["deleted_at"],
                        "expires_at": (
                            dt.datetime.fromisoformat(entry["deleted_at"]) + dt.timedelta(days=7)
                        ).isoformat(),
                    }
                    for entry in self.data["personas"]
                    if entry.get("deleted_at") and self.accessible(entry, identity)
                ]

        @app.post("/api/personas/{persona_id}/restore")
        def restore_persona(persona_id: str, request: Request) -> dict[str, Any]:
            with self.lock:
                self.purge_trash()
                identity = request.scope["twin_identity"]
                self.check_owner(persona_id, identity, deleted=True)
                entry = next(p for p in self.data["personas"] if p["id"] == persona_id and p.get("deleted_at"))
                directory = self.root / "personas" / persona_id
                if directory.exists() or any(
                    p["id"] == persona_id and not p.get("deleted_at") for p in self.data["personas"]
                ):
                    raise HTTPException(409, "分身 ID 已存在，无法恢复")
                private_directory(directory.parent)
                (self.root / "trash" / entry["trash_directory"]).rename(directory)
                for key in ("deleted_at", "trash_directory", "name"):
                    entry.pop(key)
                self.save()
                view = self.view(entry, identity)
            self.on_restored(persona_id)
            return view

        @app.post("/api/personas", status_code=201)
        def create_persona(body: NameBody, request: Request) -> dict[str, Any]:
            with self.lock:
                identity = request.scope["twin_identity"]
                limit = self.settings.auth.max_personas_per_member
                if (
                    not identity["admin"]
                    and sum(
                        p.get("owner") == identity["email"] and not p.get("deleted_at") for p in self.data["personas"]
                    )
                    >= limit
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
                return self.view(entry, identity)

        @app.patch("/api/personas/{persona_id}")
        def set_visibility(persona_id: str, body: VisibilityBody, request: Request) -> dict[str, Any]:
            with self.lock:
                identity = request.scope["twin_identity"]
                self.check_owner(persona_id, identity)
                entry = next(p for p in self.data["personas"] if p["id"] == persona_id)
                entry["public"] = body.public
                self.save()
                return self.view(entry, identity)

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
                entry = next(p for p in self.data["personas"] if p["id"] == persona_id)
                name = stored_identity(settings.db_path)[0] or settings.target_name
                deleted_at = self.clock()
                trash_directory = f"{persona_id}-{deleted_at.strftime('%Y%m%dT%H%M%S%fZ')}"
                self.removing.add(persona_id)
            try:
                # Never hold the registry's thread lock while waiting for the channel loop.
                self.on_removed(persona_id)
                with self.lock:
                    private_directory(self.root / "trash")
                    settings.db_path.parent.rename(self.root / "trash" / trash_directory)
                    self.apps.pop(persona_id, None)
                    entry.update(name=name, deleted_at=deleted_at.isoformat(), trash_directory=trash_directory)
                    self.save()
                return {"deleted": True}
            finally:
                with self.lock:
                    self.removing.discard(persona_id)


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
                if persona_id is not None and not management:
                    scope["twin_visitor"] = self.registry.check_access(persona_id, identity, str(scope["method"]), path)
                elif persona_id is not None:
                    self.registry.check_owner(persona_id, identity, deleted=path.endswith("/restore"))
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
                                    if not p.get("deleted_at") and self.registry.accessible(p, identity)
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
