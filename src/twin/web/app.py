"""Local personal-twin application factory with loopback/CSRF/body guards."""

from __future__ import annotations

import mimetypes
from collections import deque
from collections.abc import AsyncIterator, Callable, Iterable
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path
from typing import Any

import anyio
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.datastructures import Headers, MutableHeaders
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ..channels.wecom import WeComHub
from ..config import Settings
from ..egress import egress_status
from ..finder import Finder, refresh_coverage
from ..handoffs import HandoffDesk, run_all
from ..lenses import Lenses
from ..media.tts import SpeechSynthesizer
from ..persona import gate
from ..persona.gate import MemoryUpdating
from ..persona.kernel import KERNEL, rebuild_scope
from ..persona.profile import pending_chunks
from ..persona.store import PersonaStore, stored_avatar, stored_identity
from ..teamanswers import TeamAnswers
from ..teamdb import TeamDB, team_path
from ..usage import UsageLedger, UsageRecorder, install_default
from . import ask as ask_routes
from . import assets, gpu, library, media, persona, system, team_answers, voice
from . import delegation as delegation_routes
from . import lenses as lens_routes
from .auth import Auth, AuthMiddleware, forwarded_prefix
from .backends import Backends, BackendUnavailable, EmbedderFactory, LLMFactory, WorkModelFactory
from .commitments import register_all as register_all_commitments
from .conversations import ConversationIndex, request_asker_name
from .conversations import register_all as register_all_conversations
from .delegation import Delegations
from .jobs import JobConflict, JobManager, TooManyJobs, describe_error
from .personas import PersonaMiddleware, Personas

STATIC_DIR = Path(__file__).with_name("static")
# `git archive` writes the commit into this file (export-subst in .gitattributes); a checkout keeps the placeholder.
RELEASE_FILE = Path(__file__).with_name("RELEASE")
# StaticFiles takes content types from the platform's mimetypes table, which on Windows comes from the registry and can
# map .js to text/plain; with nosniff the browser then refuses to run the page's module scripts.
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/css", ".css")
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "[::1]"})
CSRF_HEADER = "x-twin"
SAFE_METHODS = frozenset({"GET", "HEAD"})
MAX_TEXT_CHARS = 100_000
MAX_STATEMENT_CHARS = 1_000
MAX_NOTE_CHARS = 2_000
MAX_JSON_BYTES = 1024 * 1024
UPLOAD_PATH = "/api/persona/import"
TITLE_CHARS = 40

_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
        "font-src 'self'; connect-src 'self'; media-src 'self' blob:; object-src 'none'; base-uri 'none'; "
        "frame-ancestors 'none'; "
        "form-action 'self'"
    ),
}


def security_headers(form_action: str = "") -> dict[str, str]:
    """The hardening headers, letting forms also lead to ``form_action`` (an origin), if given."""
    if not form_action:
        return _SECURITY_HEADERS
    policy = _SECURITY_HEADERS["Content-Security-Policy"].replace(
        "form-action 'self'", f"form-action 'self' {form_action}"
    )
    return {**_SECURITY_HEADERS, "Content-Security-Policy": policy}


_PLACEHOLDER_PAGE = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>twin</title></head>
<body><h1>twin 本地服务已启动</h1>
<p>没有找到网页界面的前端文件（twin/web/static/index.html）。请运行 <code>pnpm -C frontend build</code>。</p>
<p>接口仍然可用，例如 <a href="/api/status">/api/status</a>。</p>
</body></html>
"""


def release_commit() -> str | None:
    """The commit a `git archive` release was built from; None when running from a checkout."""
    text = RELEASE_FILE.read_text().strip() if RELEASE_FILE.is_file() else ""
    return text if len(text) == 40 and all(char in "0123456789abcdef" for char in text) else None


# ---------------------------------------------------------------- security


def host_name(value: str) -> str:
    """The host part of a Host header, lower-cased, IPv6 literals kept in brackets."""
    value = value.strip().lower()
    if value.startswith("["):
        end = value.find("]")
        return value[: end + 1] if end != -1 else ""
    return value.rsplit(":", 1)[0] if value.count(":") == 1 else value


def _allowed_form(host: str) -> str:
    host = host.strip().lower()
    return f"[{host}]" if ":" in host and not host.startswith("[") else host


_HOST_DETAIL = "请求的主机名不被允许：请用 twin ui 打印的地址（http://127.0.0.1:端口 或 http://localhost:端口）打开"
_BODY_DETAIL = f"请求内容太大（上限 {MAX_JSON_BYTES // (1024 * 1024)} MB），请删减后再提交"
_CHAT_ATTACHMENT_BODY_DETAIL = "聊天附件请求超过 52 MB，请减少附件后重试"


async def _read_body(receive: Receive, limit: int) -> tuple[list[Message], bool]:
    """The request's messages up to the end of its body, and whether the body exceeded ``limit`` bytes (reading stops
    there)."""
    messages: list[Message] = []
    size = 0
    while True:
        message = await receive()
        messages.append(message)
        if message["type"] != "http.request":
            return messages, False
        size += len(message.get("body", b""))
        if size > limit:
            return messages, True
        if not message.get("more_body", False):
            return messages, False


class SecurityMiddleware:
    """Rejects requests addressed to another host name (DNS rebinding), non-GET requests without ``X-Twin: 1``
    (cross-site request forgery), request bodies over ``MAX_JSON_BYTES`` (except uploads) and every websocket or other
    non-HTTP connection, and adds hardening headers to every response, including the 500 of an unhandled error."""

    def __init__(self, app: ASGIApp, allowed_hosts: frozenset[str], form_action: str = "") -> None:
        self.app = app
        self.allowed_hosts = allowed_hosts
        self.headers = security_headers(form_action)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            await self.app(scope, receive, send)
            return
        if scope["type"] != "http":
            await self._refuse(scope, receive, send)
            return
        is_api = str(scope.get("path", "")).startswith("/api/")
        started = False

        async def send_hardened(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                response_headers = MutableHeaders(scope=message)
                for name, value in self.headers.items():
                    response_headers.setdefault(name, value)
                if response_headers.get("content-type", "").startswith("text/event-stream"):
                    response_headers["Cache-Control"] = "no-cache"
                elif is_api or int(message.get("status", 200)) >= 500:
                    response_headers["Cache-Control"] = "no-store"
                else:
                    # Revalidate the page and its assets on every load after an upgrade.
                    response_headers.setdefault("Cache-Control", "no-cache")
            await send(message)

        headers = Headers(scope=scope)
        if host_name(headers.get("host", "")) not in self.allowed_hosts:
            await JSONResponse({"detail": _HOST_DETAIL}, status_code=403)(scope, receive, send_hardened)
            return
        if scope["method"] not in SAFE_METHODS and headers.get(CSRF_HEADER) != "1":
            detail = "缺少请求头 X-Twin: 1（用于防止跨站请求伪造），请在本服务的页面上操作"
            await JSONResponse({"detail": detail}, status_code=403)(scope, receive, send_hardened)
            return
        if scope["method"] == "PUT" and scope.get("path") in assets.UPLOAD_PATHS:
            limit = assets.upload_limit(scope["path"])
            declared = headers.get("content-length", "")
            if declared.isdigit() and int(declared) > limit + 16384:
                detail = "照片不能超过 15 MB" if scope["path"] == "/api/me/portrait" else "文件太大，请选择较小的文件"
                await JSONResponse({"detail": detail}, status_code=413)(scope, receive, send_hardened)
                return
        # Chunks of a twin's or the account library's uploads: their routes cap each chunk themselves.
        media_chunk = scope["method"] == "PUT" and str(scope.get("path", "")).startswith(
            ("/api/uploads/", "/api/library/uploads/")
        )
        chat_attachment = scope["method"] == "POST" and scope.get("path") == persona.CHAT_ATTACHMENT_PATH
        if chat_attachment:
            limit = persona.MAX_CHAT_ATTACHMENT_REQUEST_BYTES
            declared = headers.get("content-length", "")
            if declared.isdigit() and int(declared) > limit:
                await JSONResponse({"detail": _CHAT_ATTACHMENT_BODY_DETAIL}, status_code=413)(
                    scope, receive, send_hardened
                )
                return
            messages, too_large = await _read_body(receive, limit)
            if too_large:
                await JSONResponse({"detail": _CHAT_ATTACHMENT_BODY_DETAIL}, status_code=413)(
                    scope, receive, send_hardened
                )
                return
            pending = deque(messages)
            del messages
            upstream_receive = receive

            async def buffered_attachment_receive() -> Message:
                return pending.popleft() if pending else await upstream_receive()

            receive = buffered_attachment_receive
        if (
            scope["method"] not in SAFE_METHODS
            and scope.get("path") not in {UPLOAD_PATH, persona.CHAT_ATTACHMENT_PATH, *assets.UPLOAD_PATHS}
            and not media_chunk
        ):
            declared = headers.get("content-length", "")
            too_large = declared.isdigit() and int(declared) > MAX_JSON_BYTES
            if not too_large:
                messages, too_large = await _read_body(receive, MAX_JSON_BYTES)
                pending = deque(messages)

                upstream_receive = receive

                async def buffered_receive() -> Message:
                    return pending.popleft() if pending else await upstream_receive()

                receive = buffered_receive
            if too_large:
                await JSONResponse({"detail": _BODY_DETAIL}, status_code=413)(scope, receive, send_hardened)
                return
        try:
            await self.app(scope, receive, send_hardened)
        except Exception as e:
            # Unhandled errors reach Starlette's outermost error middleware, outside this one, whose 500 would lack the
            # headers above; answer here and re-raise so the server still logs the traceback.
            if not started:
                detail = f"服务器内部错误：{describe_error(e)}"
                await JSONResponse({"detail": detail}, status_code=500)(scope, receive, send_hardened)
            raise

    async def _refuse(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Close a websocket (there are none here; one from another host name is refused all the more) and ignore any
        other kind of connection."""
        if scope["type"] != "websocket":
            return
        allowed = host_name(Headers(scope=scope).get("host", "")) in self.allowed_hosts
        await receive()
        reason = "websocket connections are not supported" if allowed else "host name not allowed"
        await send({"type": "websocket.close", "code": 1008, "reason": reason})


def _validation_detail(exc: RequestValidationError) -> str:
    problems: list[str] = []
    for error in exc.errors():
        kind = str(error.get("type", ""))
        if kind == "json_invalid":
            problems.append("请求体不是合法的 JSON")
            continue
        where = ".".join(str(p) for p in error.get("loc", ()) if p not in ("body", "query", "path"))
        message = _VALIDATION_MESSAGES.get(kind, str(error.get("msg", "")))
        context = error.get("ctx") or {}
        if kind == "enum" and "expected" in context:
            message += f"，可选值：{context['expected']}"
        elif kind in ("greater_than_equal", "less_than_equal"):
            bound = context.get("ge", context.get("le"))
            message = f"{'不能小于' if kind == 'greater_than_equal' else '不能大于'} {bound}"
        problems.append(f"{where or '请求体'}：{message}")
    return "请求参数有误：" + "；".join(problems)


_HTTP_DETAILS = {404: "找不到请求的资源", 405: "不支持该请求方法"}


_VALIDATION_MESSAGES = {
    "missing": "缺少该字段",
    "json_invalid": "不是合法的 JSON",
    "int_parsing": "应为整数",
    "int_type": "应为整数",
    "int_from_float": "应为整数",
    "bool_parsing": "应为 true 或 false",
    "bool_type": "应为 true 或 false",
    "string_type": "应为文本",
    "string_too_short": "文本太短，不能为空",
    "string_too_long": "文本太长",
    "string_pattern_mismatch": "仅支持字母、数字、下划线和连字符",
    "enum": "取值无效",
    "model_attributes_type": "应为 JSON 对象",
    "dict_type": "应为 JSON 对象",
    "greater_than_equal": "数值太小",
    "less_than_equal": "数值太大",
}


class WeComBindingBody(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    bot_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    secret: str | None = Field(default=None, min_length=1, max_length=256, repr=False)


def create_app(
    settings: Settings,
    *,
    llm_factory: LLMFactory | None = None,
    embedder_factory: EmbedderFactory | None = None,
    work_model_factory: WorkModelFactory | None = None,
    synthesizer_factory: Callable[[], SpeechSynthesizer] | None = None,
    allowed_hosts: Iterable[str] = (),
    usage: UsageLedger | None = None,
) -> FastAPI:
    """The web UI application. ``llm_factory`` / ``embedder_factory`` default to ``config.make_llm(settings.llm)``
    and ``config.make_embedder(settings.embed)``; both are called lazily, once. ``synthesizer_factory`` defaults to
    ``config.make_synthesizer(settings.tts)`` and is also lazy, so speech failures do not affect other routes.
    ``work_model_factory`` defaults to work mode's LangChain model for the chat model settings.
    Injected factories are offline test seams. A model address or key an administrator changes in the system
    settings rebuilds the cached backends; other changes to twin.toml need a restart.
    ``allowed_hosts`` adds host names (besides localhost, 127.0.0.1 and [::1]) the server answers to, for
    ``twin ui --host <address>``. ``usage`` counts every model call the process makes outside a run of its own,
    per hour and stage, for the system settings; it replaces the process's default recorder."""
    app = FastAPI(title="twin", docs_url=None, redoc_url=None, openapi_url=None)
    if usage is not None:
        install_default(UsageRecorder(settings.pricing, ledger=usage, keep_rows=False))
    backends = Backends(settings, llm_factory, embedder_factory, work_model_factory)
    jobs = JobManager(settings.max_workers, describe_error)
    auth = Auth(settings.auth, settings.db_path.parent)
    registry = Personas(settings, jobs)
    team = TeamDB(team_path(settings.db_path.parent))
    app.state.team = team

    def twin_name(persona_id: str) -> str:
        """What a twin is called, for the cards that name whose answer it is."""
        path = registry.db_path_of(persona_id)
        return (stored_identity(path)[0] if path.is_file() else None) or "本人"

    def twins_in_use() -> list[str]:
        """The twins that are not in the trash or being removed: only their team answers are quoted."""
        with registry.lock:
            return [p["id"] for p in registry.data["personas"] if not p.get("deleted_at")]

    answers = TeamAnswers(team, twin_name, lambda: [i for i in twins_in_use() if i not in registry.removing])
    finder = Finder(team)
    lenses = Lenses(team)

    def member_twins(account: str | None) -> set[str]:
        """The twins a signed-in colleague has taken: how a lens meant for named people knows them."""
        if account is None:
            return set()
        with registry.lock:
            return {
                p["id"]
                for p in registry.data["personas"]
                if p.get("member") == account and not p.get("deleted_at") and p["id"] not in registry.removing
            }

    def claimed_twins() -> list[dict[str, str]]:
        """The twins colleagues have taken, with what each is called: whom a lens can be meant for (the account that
        took one is not shown)."""
        with registry.lock:
            taken = [
                p["id"]
                for p in registry.data["personas"]
                if p.get("member") and not p.get("deleted_at") and p["id"] not in registry.removing
            ]
        return [{"id": persona_id, "name": twin_name(persona_id)} for persona_id in taken]

    def twin_purged(persona_id: str) -> None:
        team.forget_persona(persona_id)
        finder.forget(persona_id)
        libraries.twin_purged(persona_id)

    registry.on_purged = twin_purged
    registry.on_disowned = lenses.withdraw_all

    def desk_for(persona_id: str) -> HandoffDesk:
        """The handoffs of one twin: where its database is, who it is made for now, what it is called."""
        resolved = registry.settings_for(persona_id)
        return HandoffDesk(
            team,
            persona_id,
            store_path=lambda: resolved.db_path,
            owner=lambda: (registry.entry(persona_id) or {}).get("member"),
            name=lambda: stored_identity(resolved.db_path)[0] or resolved.target_name,
            on_turn=ConversationIndex(team, persona_id).touched,
            answers=answers,
        )

    delegations = Delegations(registry, team, backends, desk_for, answers, twin_name)
    desks: list[HandoffDesk] = []
    for entry in registry.data["personas"]:
        if not entry.get("deleted_at"):
            path = registry.settings_for(entry["id"]).db_path
            if path.is_file():
                with PersonaStore(path) as store:
                    # What the twin's database has and the team's index lacks (conversations from before the index,
                    # or a write that did not make it) is added, as the colleague tier.
                    team.reconcile_persona(entry["id"], store.conversation_rows())
                desks.append(desk_for(entry["id"]))
    # The old 待你回答 become handoffs (once), replies that stopped halfway are finished, and handoffs that did not
    # make it into the team database are made.
    run_all(desks)
    hub = WeComHub(settings, registry, backends, jobs)
    registry.on_removed = lambda persona_id: anyio.from_thread.run(hub.persona_removed, persona_id)

    def restored(persona_id: str) -> None:
        run_all([desk_for(persona_id)])
        anyio.from_thread.run(hub.persona_restored, persona_id)

    registry.on_restored = restored
    app.state.channels = hub
    app.state.personas = registry
    app.state.auth = auth
    auth.register(app)
    system_settings = system.SystemSettings(settings)
    app.state.system = system_settings
    monitor = gpu.GpuMonitor(settings, active=lambda key: key != "tts" or system_settings.enabled("tts"))
    app.state.gpu = monitor

    def system_changed(what: str) -> None:
        """A model's address or a key changed: build every client again; a new embedding model re-embeds each
        twin's index (retrieval ranks by keywords meanwhile)."""
        backends.reset()
        monitor.retarget(settings)
        if what == "embed":
            for context in list(registry.apps.values()):
                if resume := getattr(context.state, "resume_index", None):
                    resume()

    system_settings.listeners.append(system_changed)
    auth.extra = lambda: {"features": system_settings.features(), "team_name": system_settings.team_name()}
    auth.public = lambda: {"team_name": system_settings.team_name()}
    app.add_middleware(PersonaMiddleware, registry=registry)
    # Between sign-in and the twin's own routes, which PersonaMiddleware calls directly.
    app.add_middleware(system.FeatureGate, system=system_settings)
    app.add_middleware(AuthMiddleware, auth=auth)
    app.add_middleware(
        SecurityMiddleware,
        allowed_hosts=LOOPBACK_HOSTS | {_allowed_form(h) for h in allowed_hosts if h.strip()},
        form_action=auth.form_action,
    )

    app.add_middleware(media.PrivateAudioMiddleware)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        if request.url.path in assets.UPLOAD_PATHS and any(error["loc"] == ("body", "file") for error in exc.errors()):
            return JSONResponse({"detail": "请上传文件，字段名为 file"}, status_code=400)
        return JSONResponse({"detail": _validation_detail(exc)}, status_code=400)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        detail = exc.detail
        if (
            request.url.path in assets.UPLOAD_PATHS
            and exc.status_code == 400
            and isinstance(detail, str)
            and detail.isascii()
        ):
            detail = "上传格式无效，请重新选择文件"
        if exc.status_code in _HTTP_DETAILS and detail in (None, "", "Not Found", "Method Not Allowed"):
            detail = _HTTP_DETAILS[exc.status_code]
        return JSONResponse({"detail": detail}, status_code=exc.status_code, headers=exc.headers)

    @app.exception_handler(BackendUnavailable)
    async def backend_unavailable(request: Request, exc: BackendUnavailable) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=503)

    @app.exception_handler(JobConflict)
    async def job_conflict(request: Request, exc: JobConflict) -> JSONResponse:
        return JSONResponse({"detail": str(exc), "job_id": exc.job.job_id}, status_code=409)

    @app.exception_handler(TooManyJobs)
    async def too_many_jobs(request: Request, exc: TooManyJobs) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=429)

    def persona_app(persona_id: str, resolved: Settings) -> FastAPI:
        context = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
        context.exception_handlers.update(app.exception_handlers)

        @context.exception_handler(Exception)
        async def internal_error(request: Request, exc: Exception) -> JSONResponse:
            return JSONResponse({"detail": f"服务器内部错误：{describe_error(exc)}"}, status_code=500)

        scoped_jobs = jobs.scoped(persona_id)
        context.add_middleware(persona.MemoryGateMiddleware, db_path=resolved.db_path)

        @context.exception_handler(MemoryUpdating)
        async def memory_updating(request: Request, exc: MemoryUpdating) -> JSONResponse:
            return JSONResponse({"detail": str(exc), "code": "memory_updating"}, status_code=409)

        @context.exception_handler(JobConflict)
        async def scoped_conflict(request: Request, exc: JobConflict) -> JSONResponse:
            if exc.job.persona_id != persona_id:
                return JSONResponse({"detail": "另一个分身正在处理记忆，请稍后重试"}, status_code=409)
            return await job_conflict(request, exc)

        def kernel_status(store: PersonaStore) -> dict[str, Any]:
            """The kernel the memories were built on, what upgrading to the running one redoes, and how far it is."""
            built = store.kernel_built()
            # A twin with no memories yet has nothing built on an older kernel, though it records none.
            scope = rebuild_scope(built, KERNEL) if store.count_sources() or store.count_items() else "none"
            kernel_pending = pending_chunks(store, resolved) if scope != "none" else 0
            state = context.state.processing.view()
            blocked = scope != "none" and (
                not resolved.kernel.auto_rebuild or kernel_pending > resolved.kernel.max_auto_rebuild_chunks
            )
            return {
                "version": KERNEL.__dict__,
                "built": built.__dict__ if built else None,
                "scope": scope,
                "pending_chunks": kernel_pending,
                "state": state["state"]
                if state["state"] != "idle"
                else "error"
                if store.get_meta("processing_last_error")
                else "awaiting_confirmation"
                if blocked
                else "ready"
                if scope == "none"
                else "pending",
            }

        def open_kernel_status() -> dict[str, Any]:
            with PersonaStore(resolved.db_path) as store:
                return kernel_status(store)

        # For the system settings, which list every twin's kernel.
        context.state.kernel_status = open_kernel_status

        @context.get("/api/status")
        def get_status() -> dict[str, Any]:
            with PersonaStore(resolved.db_path) as store:
                counts = {"sources": store.count_sources(), "items": store.count_items()}
                egress = egress_status(resolved, external_only=True)
                kernel = kernel_status(store)
            description = backends.describe()
            name = stored_identity(resolved.db_path)[0] or resolved.target_name
            try:
                updating = False
                gate.version_at(resolved.db_path)
            except MemoryUpdating:
                updating = True
            return {
                "target_name": name,
                # A twin made from the recording library while it is rebuilt after a change: it does not answer.
                "memory_updating": updating,
                "counts": counts,
                "kernel": kernel,
                "llm": {"provider": resolved.llm.provider, "model": resolved.llm.model, **description["llm"]},
                "embed": {"provider": resolved.embed.provider, **description["embed"]},
                "egress": egress,
            }

        @context.get("/api/channels")
        def get_channels() -> dict[str, Any]:
            return {"wecom": hub.status_for(persona_id)}

        @context.put("/api/channels/wecom")
        async def bind_wecom(body: WeComBindingBody) -> dict[str, Any]:
            return await hub.bind(persona_id, body.bot_id, body.secret)

        @context.delete("/api/channels/wecom")
        async def unbind_wecom() -> dict[str, bool]:
            await hub.unbind(persona_id)
            return {"deleted": True}

        @context.get("/api/jobs")
        def get_jobs() -> list[dict[str, Any]]:
            return scoped_jobs.recent()

        @context.get("/api/jobs/{job_id}")
        def get_job(job_id: str) -> dict[str, Any]:
            snapshot = scoped_jobs.snapshot(job_id)
            if snapshot is None:
                raise HTTPException(status_code=404, detail=f"找不到任务 {job_id}（服务重启后任务记录会清空）")
            return snapshot

        desk = desk_for(persona_id)

        def team_refresh(store: PersonaStore, llm: Any, embedder: Any) -> None:
            """After the twin's memories were built: what colleagues may use of them is counted again, for finding who
            knows a matter, and the team answers the person set are checked against what they said since."""
            refresh_coverage(team, persona_id, store)
            finder.forget(persona_id)
            answers.check_stale(persona_id, store, llm, embedder, resolved, desk.name())

        ingestion = persona.register(
            context,
            resolved,
            backends,
            scoped_jobs,
            persona.read_uploads,
            on_built=lambda version: libraries.built(persona_id, version),
            on_spent=lambda tokens: libraries.spent_building(persona_id, tokens),
            on_unbuilt=lambda limited: libraries.unbuilt(persona_id, limited),
            index=ConversationIndex(team, persona_id),
            desk=desk,
            after_build=team_refresh,
            delegations=delegations,
        )
        delegation_routes.register(context, delegations, desk, backends, request_asker_name, scoped_jobs)
        lens_routes.register(
            context,
            resolved,
            lenses,
            desk,
            backends,
            ConversationIndex(team, persona_id),
            persona_id,
            member_twins,
            claimed_twins,
        )
        assets.register(context, resolved, on_voice=ingestion.rescore)
        media.register(
            context,
            resolved,
            synthesizer_factory,
            jobs=scoped_jobs,
            name_factory=lambda: stored_identity(resolved.db_path)[0] or resolved.target_name,
            avatar_factory=lambda: stored_avatar(resolved.db_path, resolved.avatar.preset),
            tts_off=lambda: system_settings.off("tts"),
            video_off=lambda: system_settings.off("video"),
            generation=lambda: system_settings.generation,
        )
        return context

    registry.make_app = persona_app
    registry.register(app)
    register_all_conversations(app, registry, team)
    register_all_commitments(app, registry)
    libraries = library.register(app, settings, jobs, registry, backends.llm, system_settings.limits, team)
    ask_routes.register(app, registry, finder, answers, backends, libraries)
    team_answers.register_all(app, registry, team, desk_for, twin_name)
    voice.register(app, settings, libraries, registry)
    system.register(app, system_settings, monitor, libraries, registry, usage)
    previous_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        async with AsyncExitStack() as stack:
            await stack.enter_async_context(previous_lifespan(application))
            libraries.resume()
            for entry in registry.data["personas"]:
                if entry.get("deleted_at"):
                    continue
                context = registry.application(entry["id"])
                await stack.enter_async_context(context.router.lifespan_context(context))
            await hub.start()
            monitor.start()
            libraries.start()
            try:
                yield
            finally:
                await anyio.to_thread.run_sync(monitor.stop)
                await anyio.to_thread.run_sync(libraries.stop)
                await hub.stop()
                for context in list(registry.apps.values()):
                    context.state.processing.close()
                team.close()

    app.router.lifespan_context = lifespan

    # ------------------------------------------------------------ front end

    @app.api_route("/next", methods=["GET", "HEAD"])
    @app.api_route("/next/", methods=["GET", "HEAD"])
    def next_redirect(request: Request) -> RedirectResponse:
        return RedirectResponse(forwarded_prefix(request) + "/", status_code=308)

    # daw's deploy job reads it to tell whether the release it just shipped is the one running.
    release = release_commit()
    release_headers = {"X-Twin-Release": release} if release else None

    @app.api_route("/", methods=["GET", "HEAD"], response_class=HTMLResponse)
    def frontend_page() -> Response:
        index = STATIC_DIR / "index.html"
        if index.is_file():
            return FileResponse(index, media_type="text/html", headers=release_headers)
        return HTMLResponse(_PLACEHOLDER_PAGE)

    if (STATIC_DIR / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="frontend-assets")
    if (STATIC_DIR / "fonts").is_dir():
        app.mount("/fonts", StaticFiles(directory=STATIC_DIR / "fonts"), name="frontend-fonts")
    if (STATIC_DIR / "icons").is_dir():
        app.mount("/icons", StaticFiles(directory=STATIC_DIR / "icons"), name="frontend-icons")

        @app.api_route("/favicon.ico", methods=["GET", "HEAD"])
        def favicon() -> FileResponse:
            return FileResponse(STATIC_DIR / "icons" / "favicon-32.png", media_type="image/png")

    return app
