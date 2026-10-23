"""Private persona registry and request routing to isolated settings/route contexts."""

from __future__ import annotations

import datetime as dt
import json
import logging
import re
import secrets
import shutil
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import Headers
from starlette.types import ASGIApp, Receive, Scope, Send

from ..assets import AssetStore
from ..config import Settings
from ..media.schema import default_avatar
from ..persona import gate
from ..persona.store import PersonaStore, stored_avatar, stored_identity
from ..persona.tiers import COLLEAGUE, SELF, Audience
from ..util import private_directory
from .assets import wear_photo
from .auth import normalize_email
from .jobs import JobManager

logger = logging.getLogger(__name__)


class NameBody(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    name: str = Field(min_length=1, max_length=20)


class VisibilityBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    public: bool


class ClaimBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # The colleague's work e-mail or employee number; None or "" forgets it.
    claim: str | None = Field(default=None, max_length=254)


# How long to wait before fetching again a company profile photo that could not be fetched.
PHOTO_RETRY_SECONDS = 600.0

EMPLOYEE_NUMBER = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")


def claim_key(value: str | None) -> str | None:
    """Who a twin is made for, as the company sign-in names them: a work e-mail, or an employee number (the SSO
    account, such as 77845). Compared without case."""
    value = (value or "").strip().lower()
    if not value:
        return None
    if "@" in value:
        return normalize_email(value)
    if EMPLOYEE_NUMBER.fullmatch(value) is None:
        raise HTTPException(400, "请输入企业邮箱或工号")
    return value


def claim_keys(identity: dict[str, Any]) -> set[str]:
    """The keys by which the signed-in person takes a twin made for them: their work e-mail and their account."""
    return {key.strip().lower() for key in (identity.get("address"), identity.get("account")) if key and key.strip()}


# Visitors of a public twin can only talk to it; its memories and settings stay with the owner.
VISITOR_ROUTES = [
    (method, re.compile(pattern))
    for method, pattern in [
        ("GET", r"/api/(status|identity|persona/state)"),
        ("GET", r"/api/media/(capabilities|avatar\.vrm|avatar-image)"),
        ("GET", r"/api/media/(audio|video|video/jobs)/[^/]+"),
        ("POST", r"/api/media/(audio|video)"),
        ("POST", r"/api/persona/chat/stream"),
        # A colleague asking a lens the person published (``web.lenses``).
        ("GET", r"/api/persona/lenses/available"),
        ("POST", r"/api/persona/lenses/(ask-owner|[^/]+/ask)"),
        ("GET|POST", r"/api/conversations"),
        ("GET|PATCH|DELETE", r"/api/conversations/[^/]+"),
        # Work mode: each visitor sees only their own tasks (``web.work``).
        ("GET|POST", r"/api/persona/work"),
        ("GET|DELETE", r"/api/persona/work/[^/]+"),
        ("GET", r"/api/persona/work/[^/]+/files/.+"),
        ("POST", r"/api/persona/work/[^/]+/stop"),
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
        # Requests in flight per persona; guarded by its own lock, held only for a count, so a finishing request
        # never waits for ``lock``. Counting up also takes ``lock``, which makes it atomic with deletion's check.
        self.requests: dict[str, int] = {}
        self.requests_lock = threading.Lock()
        self.removing: set[str] = set()
        # When each twin last tried each company profile photo (``offer_photo``), and the thread fetching it.
        self.photo_tries: dict[tuple[str, str], float] = {}
        self.photo_jobs: dict[str, threading.Thread] = {}
        self.make_app: Callable[[str, Settings], FastAPI]
        self.on_removed: Callable[[str], None] = lambda _: None
        self.on_restored: Callable[[str], None] = lambda _: None
        # A twin in the trash was forgotten for good (a week after it was deleted).
        self.on_purged: Callable[[str], None] = lambda _: None
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

    def purge_trash(self) -> list[Path]:
        """Forget personas deleted a week ago (under ``lock``); returns their directories, which the caller removes
        with ``remove_trash`` after letting go of ``lock``, as deleting many files can take long."""
        expired = [
            entry
            for entry in self.data["personas"]
            if entry.get("deleted_at")
            and dt.datetime.fromisoformat(entry["deleted_at"]) + dt.timedelta(days=7) <= self.clock()
        ]
        if expired:
            self.data["personas"] = [entry for entry in self.data["personas"] if entry not in expired]
            self.save()
            for entry in expired:
                self.on_purged(entry["id"])
        return [self.root / "trash" / entry["trash_directory"] for entry in expired]

    @staticmethod
    def remove_trash(directories: list[Path]) -> None:
        for directory in directories:
            try:
                shutil.rmtree(directory)
            except FileNotFoundError:
                pass
            except OSError:
                logger.warning("could not remove expired trash %s", directory.name, exc_info=True)

    def check_live(self, persona_id: str) -> None:
        if persona_id in self.removing or not any(
            p["id"] == persona_id and not p.get("deleted_at") for p in self.data["personas"]
        ):
            raise HTTPException(404, "分身不存在")

    def directory(self, persona_id: str) -> Path:
        """Where a live persona keeps its data, found without opening its database."""
        self.check_live(persona_id)
        return self._settings(persona_id, read_name=False).db_path.parent

    def settings_for(self, persona_id: str) -> Settings:
        self.check_live(persona_id)
        return self._settings(persona_id)

    def db_path_of(self, persona_id: str) -> Path:
        """Where a twin's database is, without reading anything of it."""
        return self._settings(persona_id, read_name=False).db_path

    def own_twins(self, identity: dict[str, Any]) -> list[dict[str, Any]]:
        """The twins the signed-in person is the person of: made for them, taken by them and said to be all right.
        None without accounts, where nobody is known to be the person."""
        if not identity.get("auth_enabled"):
            return []
        with self.lock:
            return [
                dict(entry)
                for entry in self.data["personas"]
                if not entry.get("deleted_at")
                and entry["id"] not in self.removing
                and self.audience(entry, identity) == SELF
            ]

    def _settings(self, persona_id: str, *, read_name: bool = True) -> Settings:
        """A persona's settings; without ``read_name``, its stored name is not read and ``target_name`` falls back
        to 本人."""
        if persona_id == self.data["default"]:
            return self.settings.model_copy()
        db_path = self.root / "personas" / persona_id / "twin.db"
        return self.settings.model_copy(
            update={
                "db_path": db_path,
                "target_name": (stored_identity(db_path)[0] if read_name else None) or "本人",
                "target_aliases": [],
                "avatar": self.settings.avatar.model_copy(
                    update={"image_path": None, "preset": default_avatar(persona_id)}
                ),
                "video": self.settings.video.model_copy(update={"require_assets": True}),
            }
        )

    def enter(self, persona_id: str) -> None:
        with self.lock, self.requests_lock:
            self.requests[persona_id] = self.requests.get(persona_id, 0) + 1

    def leave(self, persona_id: str) -> None:
        with self.requests_lock:
            self.requests[persona_id] -= 1

    def in_flight(self, persona_id: str) -> int:
        with self.requests_lock:
            return self.requests.get(persona_id, 0)

    def application(self, persona_id: str) -> FastAPI:
        with self.lock:
            # Every request comes through here: only a persona's first request reads its database.
            if persona_id in self.apps:
                self.check_live(persona_id)
            else:
                self.apps[persona_id] = self.make_app(persona_id, self.settings_for(persona_id))
            return self.apps[persona_id]

    def build_status(self, persona_id: str) -> dict[str, Any] | None:
        """How far the twin's build has gone; None when the twin is not open here yet, which waiting to show a
        card should not change."""
        with self.lock:
            app = self.apps.get(persona_id)
        return app.state.build_status() if app is not None else None

    def view(self, entry: dict[str, Any], identity: dict[str, Any]) -> dict[str, Any]:
        self.check_live(entry["id"])
        return self._view(entry, identity, self._settings(entry["id"], read_name=False), self.data["default"])

    def _view(
        self, entry: dict[str, Any], identity: dict[str, Any], settings: Settings, default: str
    ) -> dict[str, Any]:
        """Reads the persona's files; needs no ``lock`` given a copy of ``entry``, the persona counted as in flight."""
        persona_id = entry["id"]
        name, _ = stored_identity(settings.db_path)
        portrait = AssetStore(settings.db_path).path("portrait")
        with PersonaStore(settings.db_path) as store:
            sources = store.count_sources()
        return {
            **entry,
            "name": name or settings.target_name,
            "avatar_url": f"/api/media/avatar-image?persona={persona_id}"
            if portrait or settings.avatar.image_path
            else None,
            "avatar_preset": stored_avatar(settings.db_path, settings.avatar.preset),
            "sources": sources,
            "is_default": persona_id == default,
            "public": bool(entry.get("public")),
            "can_manage": self.accessible(entry, identity),
            **self.claim_view(entry, identity),
        }

    def claim_view(self, entry: dict[str, Any], identity: dict[str, Any]) -> dict[str, Any]:
        """Who the twin is made for. Those who manage it see the e-mail or employee number and whether that person has
        taken it; the
        person sees that it is theirs and whether they have said it is all right."""
        view: dict[str, Any] = {}
        if entry.get("member") and entry["member"] == identity["email"]:
            view["mine"] = True
            view["approved"] = bool(entry.get("approved_at"))
            view["made_by_other"] = entry.get("owner") != identity["email"]
            # They recognised their own voice in a colleague's meetings (``web.voice``): made from those meetings.
            view["from_meetings"] = bool(entry.get("by_voice"))
        if self.accessible(entry, identity):
            view["claim"] = entry.get("claim")
            view["claimed"] = bool(entry.get("member"))
            if entry.get("claim_rejected"):
                view["claim_rejected"] = entry["claim_rejected"]
        return view

    def claim(self, identity: dict[str, Any]) -> None:
        """Give the signed-in person the twins made for their work e-mail or employee number that nobody has taken
        yet (under ``lock``). The company sign-in fixes both, so they alone say whose a twin is."""
        keys = claim_keys(identity)
        if keys and identity.get("email"):
            changed = False
            for entry in self.data["personas"]:
                if entry.get("claim") in keys and not entry.get("member") and not entry.get("deleted_at"):
                    entry["member"] = identity["email"]
                    entry["claimed_at"] = self.clock().isoformat()
                    changed = True
            if changed:
                self.save()
        self.offer_photo(identity)

    def offer_photo(self, identity: dict[str, Any]) -> None:
        """Let the twins the signed-in person has taken wear the profile photo the company sign-in gives (under
        ``lock``). Each twin fetches it once, in the background; ``photo`` in its entry is the last one it was
        offered, so signing in again with the same photo does nothing."""
        url, email = identity.get("photo"), identity.get("email")
        if not url or not email:
            return
        now = time.monotonic()
        for entry in self.data["personas"]:
            persona_id = entry["id"]
            if (
                entry.get("member") != email
                or entry.get("deleted_at")
                or entry.get("photo") == url
                or persona_id in self.removing
                or now < self.photo_tries.get((persona_id, url), -PHOTO_RETRY_SECONDS) + PHOTO_RETRY_SECONDS
            ):
                continue
            self.photo_tries[(persona_id, url)] = now
            job = threading.Thread(target=self.adopt_photo, args=(persona_id, url), name="twin-photo", daemon=True)
            self.photo_jobs[persona_id] = job
            job.start()

    def adopt_photo(self, persona_id: str, url: str) -> None:
        """``offer_photo``'s background work: the twin counts as in flight, so it is not moved to the trash while
        its portrait is written. A photo that cannot be fetched now is not recorded and is tried again later."""
        with self.lock:
            entry = self.entry(persona_id)
            if entry is None or persona_id in self.removing:
                return
            worn_before = bool(entry.get("photo"))
            settings = self._settings(persona_id, read_name=False)
            self.enter(persona_id)
        try:
            worn = wear_photo(settings, url, worn_before=worn_before)
        except OSError as error:
            logger.warning("取企业头像失败（%s），稍后再试", type(error).__name__)
            return
        finally:
            self.leave(persona_id)
        with self.lock:
            if (entry := self.entry(persona_id)) is not None:
                entry["photo"] = url
                self.save()
        if worn:
            logger.info("分身 %s 换上了企业头像", persona_id)

    def accessible(self, entry: dict[str, Any], identity: dict[str, Any]) -> bool:
        """Administrators, whoever made the twin, and the person it was made for and who has taken it."""
        email = identity["email"]
        return bool(identity["admin"] or (email and email in (entry.get("owner"), entry.get("member"))))

    @staticmethod
    def audience(entry: dict[str, Any] | None, identity: dict[str, Any]) -> Audience:
        """The tier of memory a conversation of this signed-in person with the twin answers from: all of it for the
        person the twin is made for, once they have taken it and said it is all right (and for whoever uses a
        service without sign-in, who is the only person there is); the colleague tier for everyone else, those who
        manage the twin included."""
        if not identity.get("auth_enabled"):
            return SELF
        email = identity.get("email")
        if entry and email and entry.get("member") == email and entry.get("approved_at"):
            return SELF
        return COLLEAGUE

    def own(self, persona_id: str, identity: dict[str, Any]) -> dict[str, Any]:
        """The live twin taken by the signed-in person, made for them by someone else or not."""
        entry = self.entry(persona_id)
        if (
            entry is None
            or persona_id in self.removing
            or not entry.get("member")
            or entry["member"] != identity["email"]
        ):
            raise HTTPException(404, "分身不存在")
        return entry

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

    def create(
        self, name: str, identity: dict[str, Any], *, onboarding: bool = True, claim: str | None = None
    ) -> dict[str, Any]:
        """A new private twin owned by ``identity``, within the member limit (admins are not limited); returns its
        registry entry. ``onboarding=False`` for a twin whose name and memory come from elsewhere; ``claim``: the
        work e-mail or employee number of the person it is made for, who takes it on signing in."""
        with self.lock:
            limit = self.settings.auth.max_personas_per_member
            if (
                not identity["admin"]
                and limit
                and sum(p.get("owner") == identity["email"] and not p.get("deleted_at") for p in self.data["personas"])
                >= limit
            ):
                raise HTTPException(409, f"最多可以建 {limit} 个分身")
            if claim and any(p.get("claim") == claim and not p.get("deleted_at") for p in self.data["personas"]):
                raise HTTPException(409, "这个邮箱或工号已经用在另一个分身上")
            persona_id = "p-" + secrets.token_hex(5)
            directory = self.root / "personas" / persona_id
            private_directory(directory.parent)
            directory.parent.chmod(0o700)
            directory.mkdir(mode=0o700)
            with PersonaStore(directory / "twin.db") as store:
                store.set_identity(name, "", None)
                if onboarding:
                    store.set_meta("onboarding_pending", "1")
            entry = {"id": persona_id, "owner": identity["email"], "created_at": dt.datetime.now(dt.UTC).isoformat()}
            if claim:
                entry["claim"] = claim
            self.data["personas"].append(entry)
            self.save()
            return entry

    def entry(self, persona_id: str) -> dict[str, Any] | None:
        """The registry entry of a twin that is not deleted."""
        with self.lock:
            return next((p for p in self.data["personas"] if p["id"] == persona_id and not p.get("deleted_at")), None)

    def register(self, app: FastAPI) -> None:
        @app.get("/api/personas")
        def list_personas(request: Request) -> list[dict[str, Any]]:
            identity = request.scope["twin_identity"]
            # Only the registry is read under the lock; each persona's files are read after letting go of it, so
            # requests to every persona do not wait for the listing. Each listed persona counts as in flight until
            # its files are read: opening the database of one moved to the trash meanwhile would create it again.
            with self.lock:
                expired = self.purge_trash()
                self.claim(identity)
                listed = [
                    (dict(entry), self._settings(entry["id"], read_name=False))
                    for entry in self.data["personas"]
                    if self.visible(entry, identity)
                ]
                default = self.data["default"]
                for entry, _ in listed:
                    self.enter(entry["id"])
            try:
                self.remove_trash(expired)
                return [self._view(entry, identity, settings, default) for entry, settings in listed]
            finally:
                for entry, _ in listed:
                    self.leave(entry["id"])

        @app.get("/api/personas/trash")
        def list_trash(request: Request) -> list[dict[str, Any]]:
            with self.lock:
                expired = self.purge_trash()
                identity = request.scope["twin_identity"]
                trash = [
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
            self.remove_trash(expired)
            return trash

        @app.post("/api/personas/{persona_id}/restore")
        def restore_persona(persona_id: str, request: Request) -> dict[str, Any]:
            expired: list[Path] = []
            try:
                with self.lock:
                    expired = self.purge_trash()
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
            finally:
                self.remove_trash(expired)
            self.on_restored(persona_id)
            return view

        @app.post("/api/personas", status_code=201)
        def create_persona(body: NameBody, request: Request) -> dict[str, Any]:
            identity = request.scope["twin_identity"]
            with self.lock:
                return self.view(self.create(body.name, identity), identity)

        @app.patch("/api/personas/{persona_id}")
        def set_visibility(persona_id: str, body: VisibilityBody, request: Request) -> dict[str, Any]:
            with self.lock:
                identity = request.scope["twin_identity"]
                self.check_owner(persona_id, identity)
                entry = next(p for p in self.data["personas"] if p["id"] == persona_id)
                if (
                    body.public
                    and not (entry.get("member") == identity["email"] and entry.get("approved_at"))
                    and gate.linked(self.settings_for(persona_id).db_path)
                ):
                    # Made from colleagues' meetings: it speaks for someone who did not choose to be public, until
                    # that person takes it and says it is all right.
                    raise HTTPException(409, "由录音库生成的分身只能私有，本人认领并确认后才能让同事问")
                entry["public"] = body.public
                self.save()
                return self.view(entry, identity)

        @app.put("/api/personas/{persona_id}/claim")
        def set_claim(persona_id: str, body: ClaimBody, request: Request) -> dict[str, Any]:
            """Say whose twin this is by their work e-mail or employee number: they take it when they sign in."""
            key = claim_key(body.claim)
            with self.lock:
                identity = request.scope["twin_identity"]
                self.check_owner(persona_id, identity)
                entry = next(p for p in self.data["personas"] if p["id"] == persona_id)
                if entry.get("member"):
                    raise HTTPException(409, "本人已经认领了这个分身")
                if key and any(
                    p is not entry and not p.get("deleted_at") and p.get("claim") == key for p in self.data["personas"]
                ):
                    raise HTTPException(409, "这个邮箱或工号已经用在另一个分身上")
                entry["claim"] = key
                entry.pop("claim_rejected", None)
                self.save()
                return self.view(entry, identity)

        @app.post("/api/personas/{persona_id}/approve")
        def approve(persona_id: str, body: VisibilityBody, request: Request) -> dict[str, Any]:
            """The person a twin was made for has looked at it and says it may answer; ``public``: colleagues may
            ask it too."""
            with self.lock:
                identity = request.scope["twin_identity"]
                entry = self.own(persona_id, identity)
                entry["approved_at"] = entry.get("approved_at") or self.clock().isoformat()
                entry["public"] = body.public
                self.save()
                return self.view(entry, identity)

        @app.post("/api/personas/{persona_id}/disown")
        def disown(persona_id: str, request: Request) -> dict[str, bool]:
            """ "这不是我": the twin goes back to whoever made it, who sees the e-mail or employee number was wrong."""
            with self.lock:
                identity = request.scope["twin_identity"]
                entry = self.own(persona_id, identity)
                if entry.get("owner") == identity["email"]:
                    raise HTTPException(409, "这是你自己建的分身")
                entry["claim_rejected"] = entry.pop("claim", None) or ""
                for key in ("member", "claimed_at", "approved_at"):
                    entry.pop(key, None)
                entry["public"] = False
                self.save()
                return {"disowned": True}

        @app.delete("/api/personas/{persona_id}")
        def delete_persona(persona_id: str, request: Request) -> dict[str, bool]:
            with self.lock:
                self.check_owner(persona_id, request.scope["twin_identity"])
                settings = self.settings_for(persona_id)
                if persona_id == self.data["default"]:
                    raise HTTPException(400, "默认分身不能删除")
                context = self.apps.get(persona_id)
                if (
                    self.in_flight(persona_id)
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
        if path.startswith(("/api/auth/", "/api/admin/", "/api/library/")) or path in {"/api/whoami", "/api/library"}:
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
            # The registry's thread lock can be held by a slow handler (listing every persona, emptying the trash);
            # waiting for it here on the event loop would stall every other request.
            if management:
                if persona_id is not None:
                    await run_in_threadpool(self.check_management, persona_id, identity, path)
            else:
                entered = await run_in_threadpool(self.enter, scope, identity, persona_id, path)
        except HTTPException as exc:
            await JSONResponse({"detail": exc.detail}, status_code=exc.status_code)(scope, receive, send)
            return
        if management:
            await self.app(scope, receive, send)
            return
        if entered is None:
            await JSONResponse({"detail": "先新建一个分身", "code": "no_persona"}, status_code=409)(
                scope, receive, send
            )
            return
        context, persona_id = entered
        try:
            await context(scope, receive, send)
        finally:
            self.registry.leave(persona_id)

    def check_management(self, persona_id: str, identity: dict[str, Any], path: str) -> None:
        with self.registry.lock:
            self.registry.check_owner(persona_id, identity, deleted=path.endswith("/restore"))

    def enter(
        self, scope: Scope, identity: dict[str, Any], persona_id: str | None, path: str
    ) -> tuple[FastAPI, str] | None:
        """The persona's route context, counted as in flight until ``leave``; None when there is no persona yet."""
        registry = self.registry
        with registry.lock:
            if persona_id is not None:
                scope["twin_visitor"] = registry.check_access(persona_id, identity, str(scope["method"]), path)
            else:
                registry.claim(identity)
                persona_id = (
                    registry.data["default"]
                    if identity["admin"]
                    else next(
                        (
                            p["id"]
                            for p in registry.data["personas"]
                            if not p.get("deleted_at") and registry.accessible(p, identity)
                        ),
                        None,
                    )
                )
                if persona_id is None:
                    return None
            context = registry.application(persona_id)
            scope["twin_audience"] = registry.audience(registry.entry(persona_id), identity)
            # The person the twin is made for, known to be who is asking: only where there are accounts to know it by.
            scope["twin_person"] = bool(identity.get("auth_enabled")) and scope["twin_audience"] == SELF
            registry.enter(persona_id)
            return context, persona_id
