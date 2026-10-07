"""Local personal-twin application factory with loopback/CSRF/body guards."""

from __future__ import annotations

import mimetypes
from collections import deque
from collections.abc import AsyncIterator, Callable, Iterable
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import Headers, MutableHeaders
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ..config import Settings
from ..egress import egress_status
from ..media.tts import SpeechSynthesizer
from ..persona.store import PersonaStore, stored_identity
from . import assets, media, persona
from .auth import Auth, AuthMiddleware
from .backends import Backends, BackendUnavailable, EmbedderFactory, LLMFactory
from .jobs import JobConflict, JobManager, TooManyJobs, describe_error
from .personas import PersonaMiddleware, Personas

STATIC_DIR = Path(__file__).with_name("static")
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
MAX_UPLOAD_BYTES = 100 * 1024 * 1024
UPLOAD_PATH = "/api/persona/import"
MAX_UPLOAD_FILES = 500
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

_PLACEHOLDER_PAGE = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>twin</title></head>
<body><h1>twin 本地服务已启动</h1>
<p>没有找到网页界面的前端文件（twin/web/static/index.html）。请运行 <code>pnpm -C frontend build</code>。</p>
<p>接口仍然可用，例如 <a href="/api/status">/api/status</a>。</p>
</body></html>
"""

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

    def __init__(self, app: ASGIApp, allowed_hosts: frozenset[str]) -> None:
        self.app = app
        self.allowed_hosts = allowed_hosts

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
                for name, value in _SECURITY_HEADERS.items():
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
            limit = assets.PORTRAIT_LIMIT if scope["path"] == "/api/me/portrait" else assets.VOICE_LIMIT
            declared = headers.get("content-length", "")
            if declared.isdigit() and int(declared) > limit + 16384:
                detail = "文件太大，请选择较小的文件"
                await JSONResponse({"detail": detail}, status_code=413)(scope, receive, send_hardened)
                return
        media_chunk = scope["method"] == "PUT" and str(scope.get("path", "")).startswith("/api/uploads/")
        if (
            scope["method"] not in SAFE_METHODS
            and scope.get("path") not in {UPLOAD_PATH, *assets.UPLOAD_PATHS}
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
    "enum": "取值无效",
    "model_attributes_type": "应为 JSON 对象",
    "dict_type": "应为 JSON 对象",
    "greater_than_equal": "数值太小",
    "less_than_equal": "数值太大",
}


def create_app(
    settings: Settings,
    *,
    llm_factory: LLMFactory | None = None,
    embedder_factory: EmbedderFactory | None = None,
    synthesizer_factory: Callable[[], SpeechSynthesizer] | None = None,
    allowed_hosts: Iterable[str] = (),
) -> FastAPI:
    """The web UI application. ``llm_factory`` / ``embedder_factory`` default to ``config.make_llm(settings.llm)``
    and ``config.make_embedder(settings.embed)``; both are called lazily, once. ``synthesizer_factory`` defaults to
    ``config.make_synthesizer(settings.tts)`` and is also lazy, so speech failures do not affect other routes.
    Injected factories are offline test seams. All configured backends are used as configured;
    restart the web server to apply configuration changes to cached backends.
    ``allowed_hosts`` adds host names (besides localhost, 127.0.0.1 and [::1]) the server answers to, for
    ``twin ui --host <address>``."""
    app = FastAPI(title="twin", docs_url=None, redoc_url=None, openapi_url=None)
    backends = Backends(settings, llm_factory, embedder_factory)
    jobs = JobManager(settings.max_workers, describe_error)
    auth = Auth(settings.auth, settings.db_path.parent)
    registry = Personas(settings, jobs)
    app.state.personas = registry
    app.state.auth = auth
    auth.register(app)
    app.add_middleware(PersonaMiddleware, registry=registry)
    app.add_middleware(AuthMiddleware, auth=auth)
    app.add_middleware(
        SecurityMiddleware, allowed_hosts=LOOPBACK_HOSTS | {_allowed_form(h) for h in allowed_hosts if h.strip()}
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

        @context.exception_handler(JobConflict)
        async def scoped_conflict(request: Request, exc: JobConflict) -> JSONResponse:
            if exc.job.persona_id != persona_id:
                return JSONResponse({"detail": "另一个分身正在处理记忆，请稍后重试"}, status_code=409)
            return await job_conflict(request, exc)

        @context.get("/api/status")
        def get_status() -> dict[str, Any]:
            with PersonaStore(resolved.db_path) as store:
                counts = {"sources": len(store.list_sources()), "items": len(store.list_items())}
                egress = egress_status(resolved, external_only=True)
            description = backends.describe()
            name = stored_identity(resolved.db_path)[0] or resolved.target_name
            return {
                "target_name": name,
                "counts": counts,
                "llm": {"provider": resolved.llm.provider, "model": resolved.llm.model, **description["llm"]},
                "embed": {"provider": resolved.embed.provider, **description["embed"]},
                "egress": egress,
            }

        @context.get("/api/jobs")
        def get_jobs() -> list[dict[str, Any]]:
            return scoped_jobs.recent()

        @context.get("/api/jobs/{job_id}")
        def get_job(job_id: str) -> dict[str, Any]:
            snapshot = scoped_jobs.snapshot(job_id)
            if snapshot is None:
                raise HTTPException(status_code=404, detail=f"找不到任务 {job_id}（服务重启后任务记录会清空）")
            return snapshot

        persona.register(context, resolved, backends, scoped_jobs, persona.read_uploads)
        assets.register(context, resolved)
        media.register(
            context,
            resolved,
            synthesizer_factory,
            jobs=scoped_jobs,
            name_factory=lambda: stored_identity(resolved.db_path)[0] or resolved.target_name,
        )
        return context

    registry.make_app = persona_app
    registry.register(app)
    previous_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        async with AsyncExitStack() as stack:
            await stack.enter_async_context(previous_lifespan(application))
            for entry in registry.data["personas"]:
                context = registry.application(entry["id"])
                await stack.enter_async_context(context.router.lifespan_context(context))
            try:
                yield
            finally:
                for context in list(registry.apps.values()):
                    context.state.processing.close()

    app.router.lifespan_context = lifespan

    # ------------------------------------------------------------ front end

    @app.api_route("/next", methods=["GET", "HEAD"])
    @app.api_route("/next/", methods=["GET", "HEAD"])
    def next_redirect() -> RedirectResponse:
        return RedirectResponse("/", status_code=308)

    @app.api_route("/", methods=["GET", "HEAD"], response_class=HTMLResponse)
    def frontend_page() -> Response:
        index = STATIC_DIR / "index.html"
        if index.is_file():
            return FileResponse(index, media_type="text/html")
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
