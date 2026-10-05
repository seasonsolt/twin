"""Token-protected local HTTP entry point and shared lazy service runtime."""

from __future__ import annotations

import datetime as dt
import hmac
import math
import os
import threading
import time
from collections import deque
from collections.abc import Callable, Iterable

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .config import Settings, make_embedder, make_llm
from .egress import EgressDenied, require_configured_egress
from .embed import Embedder
from .llm import LLM
from .persona.chat import PersonaChat
from .persona.store import PersonaStore
from .service import MAX_QUESTION_CHARS, ServiceAnswer, ServiceIdentity, answer_question, public_identity
from .usage import UsageRecorder, call_stage, record_usage
from .web.app import _SECURITY_HEADERS, LOOPBACK_HOSTS, _allowed_form, _read_body, host_name

ChatFactory = Callable[[], PersonaChat]
BACKEND_UNAVAILABLE = "分身服务暂时不可用，请检查后端配置后重试"
MAX_BODY_BYTES = 16 * 1024


def api_token(settings: Settings, token: str | None = None) -> str:
    value = os.environ.get(settings.api.token_env, "") if token is None else token
    if not value.strip() or len(value) < 32:
        raise ValueError(
            f"请设置环境变量 {settings.api.token_env}，令牌至少 32 个字符；可用 "
            '`python -c "import secrets; print(secrets.token_urlsafe(32))"` 生成，勿写入配置或源码'
        )
    return value


class ServiceBackend:
    """Injected chat factories are trusted offline seams; configured backends are always gated."""

    def __init__(self, settings: Settings, chat_factory: ChatFactory | None = None) -> None:
        self.settings = settings
        self.chat_factory = chat_factory
        self._llm: LLM | None = None
        self._embedder: Embedder | None = None
        self._lock = threading.Lock()
        self.usage = UsageRecorder(settings.pricing, settings.budget.max_cost_usd)

    def ask(self, question: str, as_of: dt.date | None) -> ServiceAnswer:
        with record_usage(self.usage), call_stage("service"):
            if self.chat_factory is not None:
                return answer_question(self.chat_factory(), question, as_of)
            with self._lock:
                if self._llm is None or self._embedder is None:
                    require_configured_egress(self.settings, self.settings.llm)
                    require_configured_egress(self.settings, self.settings.embed)
                    llm = make_llm(self.settings.llm)
                    embedder = make_embedder(self.settings.embed)
                    self._llm, self._embedder = llm, embedder
            with PersonaStore(self.settings.db_path) as store:
                return answer_question(PersonaChat(store, self._llm, self._embedder, self.settings), question, as_of)


class ApiSecurityMiddleware:
    def __init__(self, app: ASGIApp, token: str, rate: int, allowed_hosts: frozenset[str]) -> None:
        self.app = app
        self.token = token.encode("utf-8")
        self.rate = rate
        self.allowed_hosts = allowed_hosts
        self._window: deque[float] = deque()
        self._lock = threading.Lock()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            await self.app(scope, receive, send)
            return
        if scope["type"] != "http":
            if scope["type"] == "websocket":
                await receive()
                await send({"type": "websocket.close", "code": 1008})
            return
        started = False

        async def hardened(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                headers = MutableHeaders(scope=message)
                for name, value in _SECURITY_HEADERS.items():
                    headers.setdefault(name, value)
                headers["Cache-Control"] = "no-store"
                headers["X-AI-Generated"] = "twin"
            await send(message)

        async def refuse(status: int, detail: str, headers: dict[str, str] | None = None) -> None:
            await JSONResponse({"detail": detail}, status_code=status, headers=headers)(scope, receive, hardened)

        headers = Headers(scope=scope)
        if host_name(headers.get("host", "")) not in self.allowed_hosts:
            await refuse(403, "请求的主机名不被允许，请使用本机地址或配置 --allow-host")
            return
        if scope.get("path") != "/v1/health":
            authorization = headers.get("authorization", "")
            scheme, _, supplied = authorization.partition(" ")
            if scheme.lower() != "bearer" or not hmac.compare_digest(supplied.encode("utf-8"), self.token):
                await refuse(401, "需要有效的 Bearer 令牌", {"WWW-Authenticate": "Bearer"})
                return
            now = time.monotonic()
            with self._lock:
                while self._window and self._window[0] <= now - 60:
                    self._window.popleft()
                retry = max(1, math.ceil(60 - (now - self._window[0]))) if len(self._window) >= self.rate else 0
                if not retry:
                    self._window.append(now)
            if retry:
                await refuse(429, "请求过于频繁，请稍后重试", {"Retry-After": str(retry)})
                return
        if scope["method"] not in {"GET", "HEAD"}:
            declared = headers.get("content-length", "")
            if declared.isdigit() and int(declared) > MAX_BODY_BYTES:
                await refuse(413, "请求内容太大")
                return
            messages, too_large = await _read_body(receive, MAX_BODY_BYTES)
            if too_large:
                await refuse(413, "请求内容太大")
                return
            pending = deque(messages)
            upstream = receive

            async def buffered() -> Message:
                return pending.popleft() if pending else await upstream()

            receive = buffered
        try:
            await self.app(scope, receive, hardened)
        except Exception:
            # Do not re-raise: server tracebacks can contain personal text or backend secrets.
            if not started:
                await refuse(503, BACKEND_UNAVAILABLE)


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(max_length=MAX_QUESTION_CHARS)
    as_of: dt.date | None = None


def create_api(
    settings: Settings,
    chat_factory: ChatFactory | None = None,
    *,
    token: str | None = None,
    allowed_hosts: Iterable[str] = (),
) -> FastAPI:
    app = FastAPI(title="twin service", docs_url=None, redoc_url=None, openapi_url=None)
    backend = ServiceBackend(settings, chat_factory)
    app.state.backend = backend
    app.add_middleware(
        ApiSecurityMiddleware,
        token=api_token(settings, token),
        rate=settings.api.rate_per_minute,
        allowed_hosts=LOOPBACK_HOSTS | {_allowed_form(h) for h in allowed_hosts if h.strip()},
    )

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse({"detail": "请求参数有误：question 最多 2000 字符，as_of 应为 YYYY-MM-DD"}, status_code=400)

    @app.get("/v1/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/v1/identity")
    def identity() -> ServiceIdentity:
        return public_identity(settings)

    @app.post("/v1/ask", response_model=ServiceAnswer)
    def ask(body: AskRequest) -> ServiceAnswer | JSONResponse:
        try:
            return backend.ask(body.question, body.as_of)
        except EgressDenied as exc:
            return JSONResponse({"detail": str(exc)}, status_code=403)
        except Exception:
            return JSONResponse({"detail": BACKEND_UNAVAILABLE}, status_code=503)

    return app
