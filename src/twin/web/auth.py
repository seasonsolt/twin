"""Email-code authentication and hashed, revocable cookie sessions."""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import smtplib
import sqlite3
import ssl
import threading
import time
from collections import deque
from collections.abc import Iterator
from contextlib import closing, contextmanager
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from starlette.types import ASGIApp, Receive, Scope, Send

from ..config import AuthSettings, SMTPSettings
from ..util import private_directory

COOKIE = "twin_session"


def normalize_email(value: str) -> str:
    email = value.strip().lower()
    if (
        len(email) > 254
        or re.fullmatch(
            r"[a-z0-9!#$%&'*+/=?^_`{|}~.-]+@[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+",
            email,
        )
        is None
    ):
        raise HTTPException(400, "请输入有效的邮箱地址")
    local = email.rsplit("@", 1)[0]
    if len(local) > 64 or local.startswith(".") or local.endswith(".") or ".." in local:
        raise HTTPException(400, "请输入有效的邮箱地址")
    return email


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def send_code(smtp: SMTPSettings, email: str, code: str) -> None:
    message = EmailMessage()
    message["Subject"] = "你的 twin 登录验证码"
    message["From"] = formataddr((smtp.from_name, smtp.from_address))
    message["To"] = email
    message.set_content(f"你的 twin 登录验证码：{code}\n10 分钟内有效。若不是你本人操作，请忽略此邮件。")
    message.add_alternative(
        f"<p>你的 twin 登录验证码：</p><p><strong>{code}</strong></p>"
        "<p>10 分钟内有效。若不是你本人操作，请忽略此邮件。</p>",
        subtype="html",
    )
    context = ssl.create_default_context()
    client = (
        smtplib.SMTP_SSL(smtp.host, smtp.port, timeout=15, context=context)
        if smtp.port == 465
        else smtplib.SMTP(smtp.host, smtp.port, timeout=15)
    )
    with client:
        if smtp.port == 587:
            client.starttls(context=context)
        client.login(smtp.username, os.environ[smtp.password_env])
        client.send_message(message)


class EmailBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(max_length=254)


class VerifyBody(EmailBody):
    code: str = Field(max_length=64)


class Auth:
    def __init__(self, settings: AuthSettings, root: Path) -> None:
        self.settings = settings
        self.path = root / "auth.db"
        self.lock = threading.RLock()
        self.email_rates: dict[str, deque[float]] = {}
        self.ip_rates: dict[str, deque[float]] = {}
        if settings.enabled:
            if not os.environ.get(settings.smtp.password_env):
                raise ValueError(f"[auth.smtp] 缺少密码环境变量 {settings.smtp.password_env}")
            private_directory(root)
            fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
            os.close(fd)
            self.path.chmod(0o600)
            with closing(sqlite3.connect(self.path)) as db, db:
                db.executescript(
                    "CREATE TABLE IF NOT EXISTS codes (email TEXT PRIMARY KEY, salt TEXT NOT NULL, "
                    "hash TEXT NOT NULL, expires REAL NOT NULL, attempts INTEGER NOT NULL DEFAULT 0);"
                    "CREATE TABLE IF NOT EXISTS sessions (hash TEXT PRIMARY KEY, email TEXT NOT NULL, "
                    "expires REAL NOT NULL);"
                    "CREATE TABLE IF NOT EXISTS waitlist (email TEXT PRIMARY KEY, created_at REAL NOT NULL);"
                )

    @contextmanager
    def database(self) -> Iterator[sqlite3.Connection]:
        with self.lock, closing(sqlite3.connect(self.path)) as db, db:
            db.row_factory = sqlite3.Row
            db.execute("BEGIN IMMEDIATE")
            now = time.time()
            db.execute("DELETE FROM codes WHERE expires <= ?", (now,))
            db.execute("DELETE FROM sessions WHERE expires <= ?", (now,))
            yield db

    def allowed(self, email: str) -> bool:
        email = email.strip().lower()
        return email in self.settings.allowed_emails or email.rsplit("@", 1)[-1] in self.settings.allowed_domains

    def identity(self, email: str | None) -> dict[str, Any]:
        return {
            "email": email,
            "admin": not self.settings.enabled or email in self.settings.admin_emails,
            "auth_enabled": self.settings.enabled,
        }

    def session(self, token: str | None) -> dict[str, Any] | None:
        if not self.settings.enabled:
            return self.identity(None)
        if not token or len(token) > 256:
            return None
        with self.database() as db:
            row = db.execute("SELECT email FROM sessions WHERE hash = ?", (digest(token),)).fetchone()
        return self.identity(row["email"]) if row and self.allowed(row["email"]) else None

    def rate_limit(self, email: str | None, ip: str) -> None:
        now = time.monotonic()
        with self.lock:
            for rates in (self.email_rates, self.ip_rates):
                for key in list(rates):
                    while rates[key] and rates[key][0] <= now - 3600:
                        rates[key].popleft()
                    if not rates[key]:
                        del rates[key]
            emails = self.email_rates.setdefault(email, deque()) if email is not None else deque()
            ips = self.ip_rates.setdefault(ip, deque())
            if emails and now - emails[-1] < 60:
                raise HTTPException(429, "请等 60 秒后重新获取验证码")
            if len(emails) >= 5 or len(ips) >= 20:
                raise HTTPException(429, "获取验证码过于频繁，请稍后再试")
            if email is not None:
                emails.append(now)
            ips.append(now)

    def register(self, app: FastAPI) -> None:
        def enabled() -> None:
            if not self.settings.enabled:
                raise HTTPException(404, "未启用邮箱登录")

        @app.post("/api/auth/request")
        def request_code(body: EmailBody, request: Request) -> dict[str, str]:
            enabled()
            email = normalize_email(body.email)
            ip = request.headers.get("CF-Connecting-IP") or (request.client.host if request.client else "unknown")
            allowed = self.allowed(email)
            self.rate_limit(email if allowed else None, ip)
            if not allowed:
                with self.database() as db:
                    db.execute("INSERT OR IGNORE INTO waitlist VALUES (?, ?)", (email, time.time()))
                return {"status": "waitlist"}
            code = f"{secrets.randbelow(1_000_000):06d}"
            salt = secrets.token_hex(32)
            hashed = digest(salt + code)
            with self.database() as db:
                db.execute(
                    "INSERT OR REPLACE INTO codes VALUES (?, ?, ?, ?, 0)", (email, salt, hashed, time.time() + 600)
                )
            try:
                send_code(self.settings.smtp, email, code)
            except Exception:
                with self.database() as db:
                    db.execute("DELETE FROM codes WHERE email = ? AND hash = ?", (email, hashed))
                raise HTTPException(503, "验证码发送失败，请稍后重试") from None
            return {"status": "code_sent"}

        @app.post("/api/auth/verify")
        def verify(body: VerifyBody, request: Request, response: Response) -> dict[str, Any]:
            enabled()
            email = normalize_email(body.email)
            token = secrets.token_hex(32)
            valid = False
            with self.database() as db:
                row = db.execute("SELECT * FROM codes WHERE email = ?", (email,)).fetchone()
                valid = hmac.compare_digest(
                    digest((row["salt"] if row else "") + body.code), row["hash"] if row else "0" * 64
                )
                valid = valid and bool(row) and self.allowed(email)
                if valid:
                    db.execute("DELETE FROM codes WHERE email = ?", (email,))
                    db.execute(
                        "INSERT INTO sessions VALUES (?, ?, ?)",
                        (digest(token), email, time.time() + self.settings.session_days * 86400),
                    )
                elif row:
                    db.execute("UPDATE codes SET attempts = attempts + 1 WHERE email = ?", (email,))
                    db.execute("DELETE FROM codes WHERE email = ? AND attempts >= 5", (email,))
            if not valid:
                raise HTTPException(400, "验证码错误或已过期，请重新获取")
            response.set_cookie(
                COOKIE,
                token,
                max_age=self.settings.session_days * 86400,
                httponly=True,
                secure=secure_cookie(request),
                samesite="lax",
                path="/",
            )
            return {"email": email, "admin": email in self.settings.admin_emails}

        @app.post("/api/auth/logout")
        def logout(request: Request, response: Response) -> dict[str, bool]:
            if self.settings.enabled:
                with self.database() as db:
                    db.execute("DELETE FROM sessions WHERE hash = ?", (digest(request.cookies.get(COOKIE, "")),))
            response.delete_cookie(COOKIE, path="/", httponly=True, secure=secure_cookie(request), samesite="lax")
            return {"logged_out": True}

        @app.get("/api/whoami")
        def whoami(request: Request) -> Response:
            identity = request.scope.get("twin_identity")
            return JSONResponse(identity) if identity else login_required()

        @app.get("/api/admin/waitlist")
        def waitlist(request: Request) -> list[dict[str, Any]]:
            if not request.scope["twin_identity"]["admin"]:
                raise HTTPException(403, "仅管理员可查看等候名单")
            if not self.settings.enabled:
                return []
            with self.database() as db:
                return [dict(row) for row in db.execute("SELECT * FROM waitlist ORDER BY created_at")]


def secure_cookie(request: Request) -> bool:
    # A tunnel is HTTPS externally even if its loopback upstream uses HTTP.
    return not (
        request.url.scheme == "http"
        and request.headers.get("x-forwarded-proto", "http").lower() == "http"
        and request.url.hostname in {"localhost", "127.0.0.1", "::1"}
    )


def login_required() -> JSONResponse:
    return JSONResponse({"detail": "请先登录", "code": "login_required"}, status_code=401)


class AuthMiddleware:
    def __init__(self, app: ASGIApp, auth: Auth) -> None:
        self.app, self.auth = app, auth

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not str(scope.get("path", "")).startswith("/api/"):
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        # SQLite is small; use a worker so concurrent requests don't block the event loop.
        from starlette.concurrency import run_in_threadpool

        identity = await run_in_threadpool(self.auth.session, request.cookies.get(COOKIE))
        scope["twin_identity"] = identity
        if not identity and not request.url.path.startswith("/api/auth/") and request.url.path != "/api/whoami":
            await login_required()(scope, receive, send)
            return
        await self.app(scope, receive, send)
