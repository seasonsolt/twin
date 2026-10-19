"""Offline authentication boundary and ownership regression tests."""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from twin.assets import AssetStore
from twin.config import AuthSettings, Settings, SMTPSettings, SSOSettings
from twin.web import create_app
from twin.web.auth import Auth, digest, normalize_email, send_code
from twin.web.jobs import PersonaProcessing

CSRF = {"X-Twin": "1"}
ADMIN = "admin@example.com"
MEMBER = "member@xjjk.com"
OTHER = "other@xjjk.com"


@pytest.fixture
def web(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("TWIN_SMTP_PASSWORD", "test-only")
    monkeypatch.setattr(PersonaProcessing, "queue", lambda _: None)
    sender = MagicMock()
    monkeypatch.setattr("twin.web.auth.send_code", sender)
    settings = Settings(
        db_path=tmp_path / "twin.db",
        auth=AuthSettings(
            enabled=True,
            allowed_emails=[ADMIN],
            admin_emails=[ADMIN],
            smtp=SMTPSettings(host="smtp.example.com", username="test", from_address="twin@example.com"),
        ),
    )
    app = create_app(settings, allowed_hosts=["twin.example.com"])
    app.state.sender = sender
    with TestClient(app, base_url="http://localhost") as client:
        yield client


def auth(web: TestClient) -> Auth:
    return web.app.state.auth  # type: ignore[union-attr,no-any-return]


def sender(web: TestClient) -> MagicMock:
    return web.app.state.sender  # type: ignore[union-attr,no-any-return]


def request(web: TestClient, email: str = MEMBER) -> str:
    result = web.post("/api/auth/request", json={"email": email}, headers=CSRF)
    assert result.status_code == 200, result.text
    assert result.json() == {"status": "code_sent"}
    return str(sender(web).call_args.args[2])


def login(web: TestClient, email: str = MEMBER) -> str:
    code = request(web, email)
    result = web.post("/api/auth/verify", json={"email": email, "code": code}, headers=CSRF)
    assert result.status_code == 200, result.text
    return web.cookies["twin_session"]


def create(web: TestClient) -> str:
    result = web.post("/api/personas", json={"name": "测试分身"}, headers=CSRF)
    assert result.status_code == 201, result.text
    return str(result.json()["id"])


@pytest.mark.parametrize(
    "email,allowed",
    [
        ("A@XJJK.COM", True),
        ("seasonsolt@gmail.com", False),
        ("a@xjjk.com.evil.com", False),
        ("a@sub.xjjk.com", False),
        ("a@evilxjjk.com", False),
        ("ADMIN@EXAMPLE.COM", True),
    ],
)
def test_allowlist(web: TestClient, email: str, allowed: bool) -> None:
    assert normalize_email(email) == email.lower()
    assert auth(web).allowed(email) is allowed


@pytest.mark.parametrize("email", ["a", "a@@xjjk.com", "a@xjjk.com\nBcc:evil@xjjk.com", ".a@xjjk.com", "a..b@xjjk.com"])
def test_invalid_email(web: TestClient, email: str) -> None:
    assert web.post("/api/auth/request", json={"email": email}, headers=CSRF).status_code == 400
    sender(web).assert_not_called()


def test_waitlist_dedupes_and_admin_only(web: TestClient) -> None:
    for email in (" WAIT@EXAMPLE.COM ", "wait@example.com"):
        result = web.post("/api/auth/request", json={"email": email}, headers=CSRF)
        assert result.json() == {"status": "waitlist"}
    sender(web).assert_not_called()
    login(web)
    assert web.get("/api/admin/waitlist").status_code == 403
    login(web, ADMIN)
    entries = web.get("/api/admin/waitlist").json()
    assert len(entries) == 1 and entries[0]["email"] == "wait@example.com"
    assert entries[0]["created_at"] > 0


def test_hash_expiry_attempts_burn_and_replacement(web: TestClient) -> None:
    code = request(web)
    with auth(web).database() as db:
        row = db.execute("SELECT * FROM codes").fetchone()
        assert row["hash"] != code and row["hash"] == digest(row["salt"] + code)
        assert row["attempts"] == 0
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(5):
        assert web.post("/api/auth/verify", json={"email": MEMBER, "code": wrong}, headers=CSRF).status_code == 400
    assert web.post("/api/auth/verify", json={"email": MEMBER, "code": code}, headers=CSRF).status_code == 400
    with auth(web).database() as db:
        assert db.execute("SELECT count(*) FROM codes").fetchone()[0] == 0
    auth(web).email_rates.clear()
    code = request(web)
    with auth(web).database() as db:
        db.execute("UPDATE codes SET expires = 0")
    assert web.post("/api/auth/verify", json={"email": MEMBER, "code": code}, headers=CSRF).status_code == 400
    auth(web).email_rates.clear()
    old = request(web)
    auth(web).email_rates.clear()
    new = request(web)
    if old != new:
        assert web.post("/api/auth/verify", json={"email": MEMBER, "code": old}, headers=CSRF).status_code == 400
    assert web.post("/api/auth/verify", json={"email": MEMBER, "code": new}, headers=CSRF).status_code == 200
    assert web.post("/api/auth/verify", json={"email": MEMBER, "code": new}, headers=CSRF).status_code == 400


def test_rate_limits(web: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    now = [10000.0]
    monkeypatch.setattr("twin.web.auth.time.monotonic", lambda: now[0])
    request(web)
    assert web.post("/api/auth/request", json={"email": MEMBER.upper()}, headers=CSRF).status_code == 429
    for _ in range(4):
        now[0] += 61
        request(web)
    now[0] += 61
    assert web.post("/api/auth/request", json={"email": MEMBER}, headers=CSRF).status_code == 429
    now[0] += 3600
    request(web)
    auth(web).ip_rates.clear()
    for i in range(20):
        result = web.post(
            "/api/auth/request", json={"email": f"user{i}@xjjk.com"}, headers={**CSRF, "CF-Connecting-IP": "1.2.3.4"}
        )
        assert result.status_code == 200
    assert (
        web.post(
            "/api/auth/request", json={"email": OTHER}, headers={**CSRF, "CF-Connecting-IP": "1.2.3.4"}
        ).status_code
        == 429
    )
    assert (
        web.post(
            "/api/auth/request", json={"email": OTHER}, headers={**CSRF, "CF-Connecting-IP": "5.6.7.8"}
        ).status_code
        == 200
    )


@pytest.mark.parametrize(
    "base,secure",
    [
        ("http://localhost", False),
        ("https://localhost", True),
        ("https://twin.example.com", True),
        ("http://twin.example.com", True),
    ],
)
def test_session_cookie_flags(web: TestClient, base: str, secure: bool) -> None:
    web.base_url = base
    code = request(web)
    result = web.post("/api/auth/verify", json={"email": MEMBER, "code": code}, headers=CSRF)
    cookie = result.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie and "Path=/" in cookie
    assert "Max-Age=2592000" in cookie
    assert ("Secure" in cookie) is secure
    token = web.cookies["twin_session"]
    with auth(web).database() as db:
        row = db.execute("SELECT * FROM sessions").fetchone()
        assert row["hash"] == digest(token) and row["hash"] != token
    assert auth(web).path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize(
    "prefix,path",
    [
        ("/twin", "/twin/"),
        ("/twin/", "/twin/"),
        ("/a/b-c", "/a/b-c/"),
        ("", "/"),
        ("//evil", "/"),
        ("/..", "/"),
        ("/a b", "/"),
    ],
)
def test_session_cookie_is_scoped_to_the_proxy_prefix(web: TestClient, prefix: str, path: str) -> None:
    code = request(web)
    headers = {**CSRF, "X-Forwarded-Prefix": prefix}
    result = web.post("/api/auth/verify", json={"email": MEMBER, "code": code}, headers=headers)
    assert f"Path={path};" in result.headers["set-cookie"] + ";"
    logout = web.post("/api/auth/logout", headers=headers)
    assert "Max-Age=0" in logout.headers["set-cookie"] and f"Path={path};" in logout.headers["set-cookie"] + ";"


@pytest.mark.parametrize(
    "path",
    [
        "/api/status",
        "/api/identity",
        "/api/personas",
        "/api/persona/sources",
        "/api/me/assets",
        "/api/uploads/abc",
        "/api/jobs",
        "/api/media/avatar-image",
        "/api/media/avatar.vrm",
        "/api/media/audio/abc.wav",
        "/api/media/video/abc.mp4",
        "/api/me/voice/reference",
        "/api/admin/waitlist",
    ],
)
def test_protected_routes_and_access_headers_do_not_authenticate(web: TestClient, path: str) -> None:
    result = web.get(path, headers={"Cf-Access-Authenticated-User-Email": ADMIN})
    assert result.status_code == 401
    assert result.json() == {"detail": "请先登录", "code": "login_required"}
    assert result.headers["cache-control"] == "no-store"


def test_streaming_chat_requires_login_and_persona_ownership(web: TestClient) -> None:
    body = {"messages": [{"role": "user", "content": "问题"}]}
    result = web.post("/api/persona/chat/stream", json=body, headers=CSRF)
    assert result.status_code == 401 and result.json()["code"] == "login_required"
    login(web)
    own = create(web)
    response = web.post("/api/persona/chat/stream", json=body, headers={**CSRF, "X-Twin-Persona": own})
    assert response.status_code == 200 and "event: final" in response.text
    login(web, OTHER)
    denied = web.post("/api/persona/chat/stream", json=body, headers={**CSRF, "X-Twin-Persona": own})
    assert denied.status_code == 404 and denied.json() == {"detail": "分身不存在"}


def test_logout_expiration_csrf_and_static(web: TestClient) -> None:
    assert web.get("/").status_code == 200
    assert web.get("/api/whoami").status_code == 401
    assert web.post("/api/auth/request", json={"email": MEMBER}).status_code == 403
    token = login(web)
    assert web.get("/api/whoami").json() == {
        "email": MEMBER,
        "name": None,
        "address": MEMBER,
        "admin": False,
        "auth_enabled": True,
        "provider": "email",
        "features": {"work": True, "ledger": True},
    }
    assert web.post("/api/auth/logout").status_code == 403
    result = web.post("/api/auth/logout", headers=CSRF)
    assert result.status_code == 200 and "Max-Age=0" in result.headers["set-cookie"]
    assert web.get("/api/whoami").status_code == 401
    web.cookies.set("twin_session", token)
    assert web.get("/api/personas").status_code == 401
    auth(web).email_rates.clear()
    web.cookies.clear()
    login(web)
    with auth(web).database() as db:
        db.execute("UPDATE sessions SET expires = 0")
    assert web.get("/api/whoami").status_code == 401


def test_ownership_no_persona_limit_and_admin(web: TestClient) -> None:
    first_token = login(web)
    assert web.get("/api/personas").json() == []
    assert web.get("/api/status").json() == {"detail": "先新建一个分身", "code": "no_persona"}
    assert web.get("/api/status?persona=default").status_code == 404
    own = [create(web) for _ in range(3)]
    assert all(p["owner"] == MEMBER for p in web.get("/api/personas").json())
    assert web.post("/api/personas", json={"name": "超额"}, headers=CSRF).json()["detail"] == "最多可以建 3 个分身"
    assert web.get("/api/identity").status_code == 200
    assert web.put("/api/identity", json={"name": "改名", "about": ""}, headers=CSRF).status_code == 200
    login(web, OTHER)
    other = create(web)
    assert [p["id"] for p in web.get("/api/personas").json()] == [other]
    paths = [
        "/api/status",
        "/api/identity",
        "/api/persona/sources",
        "/api/persona/questionnaire",
        "/api/me/assets",
        "/api/media/avatar-image",
        "/api/media/avatar.vrm",
        "/api/media/audio/abc.wav",
        "/api/media/video/abc.mp4",
        "/api/me/voice/reference",
        "/api/uploads/abc",
        "/api/jobs/abc",
        "/api/personas",
    ]
    for path in paths:
        for url, headers in [(path + "?persona=" + own[0], CSRF), (path, {**CSRF, "X-Twin-Persona": own[0]})]:
            result = web.get(url, headers=headers)
            assert result.status_code == 404, (url, result.text)
            assert result.json() == {"detail": "分身不存在"}
    assert (
        web.put(
            "/api/identity", json={"name": "偷改", "about": ""}, headers={**CSRF, "X-Twin-Persona": own[0]}
        ).status_code
        == 404
    )
    assert (
        web.post("/api/persona/notes?persona=" + own[0], json={"text": "不能写入他人的记忆"}, headers=CSRF).status_code
        == 404
    )
    assert web.delete("/api/personas/" + own[0], headers=CSRF).status_code == 404
    login(web, ADMIN)
    assert len(web.get("/api/personas").json()) == 5
    assert web.get("/api/status?persona=" + own[0]).status_code == 200
    assert web.delete("/api/personas/" + other, headers=CSRF).status_code == 200
    web.cookies.clear()
    web.cookies.set("twin_session", first_token)
    assert web.delete("/api/personas/" + own[0], headers=CSRF).status_code == 200
    assert len(web.get("/api/personas").json()) == 2


def test_auth_disabled_and_config_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with TestClient(create_app(Settings(db_path=tmp_path / "twin.db")), base_url="http://localhost") as web:
        assert web.get("/api/whoami").json() == {
            "email": None,
            "name": None,
            "address": None,
            "admin": True,
            "auth_enabled": False,
            "provider": None,
            "features": {"work": True, "ledger": True},
        }
        assert web.get("/api/status").status_code == 200
        assert not (tmp_path / "auth.db").exists()
    with pytest.raises(ValidationError, match=r"auth\.smtp"):
        AuthSettings(enabled=True)
    monkeypatch.delenv("TWIN_SMTP_PASSWORD", raising=False)
    with pytest.raises(ValueError, match="TWIN_SMTP_PASSWORD"):
        create_app(
            Settings(
                db_path=tmp_path / "other.db",
                auth=AuthSettings(
                    enabled=True, smtp=SMTPSettings(host="smtp", username="user", from_address="a@b.com")
                ),
            )
        )


@pytest.mark.parametrize("port", [465, 587])
def test_smtp_sender(port: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TWIN_SMTP_PASSWORD", "test-only")
    client = MagicMock()
    client.__enter__.return_value = client
    ssl_factory, tls_factory = MagicMock(return_value=client), MagicMock(return_value=client)
    monkeypatch.setattr("twin.web.auth.smtplib.SMTP_SSL", ssl_factory)
    monkeypatch.setattr("twin.web.auth.smtplib.SMTP", tls_factory)
    send_code(SMTPSettings(host="smtp", port=port, username="user", from_address="a@b.com"), MEMBER, "012345")
    client.login.assert_called_once_with("user", "test-only")
    assert client.starttls.call_count == (1 if port == 587 else 0)
    message = client.send_message.call_args.args[0]
    assert str(message["Subject"]) == "你的 twin 登录验证码"
    assert "012345" in message.get_body(preferencelist=("plain",)).get_content()
    assert "012345" in message.get_body(preferencelist=("html",)).get_content()
    assert "href" not in message.as_string()


def test_code_can_only_be_consumed_once_concurrently(web: TestClient) -> None:
    code = request(web)

    def verify(_: int) -> int:
        return web.post("/api/auth/verify", json={"email": MEMBER, "code": code}, headers=CSRF).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(verify, range(2))) == [200, 400]
    with auth(web).database() as db:
        assert db.execute("SELECT count(*) FROM sessions").fetchone()[0] == 1


def test_media_get_uses_session_cookie_and_allowlist_revocation(web: TestClient) -> None:
    login(web)
    persona = create(web)
    directory = auth(web).path.parent / "personas" / persona
    AssetStore(directory / "twin.db").save("voice", b"private reference", 6)
    assert web.get("/api/me/voice/reference?persona=" + persona).content == b"private reference"
    auth(web).settings.allowed_domains = []
    assert web.get("/api/me/voice/reference?persona=" + persona).status_code == 401


def test_tunnel_cookie_stays_secure_with_a_loopback_upstream(web: TestClient) -> None:
    code = request(web)
    result = web.post(
        "/api/auth/verify", json={"email": MEMBER, "code": code}, headers={**CSRF, "X-Forwarded-Proto": "https"}
    )
    assert "Secure" in result.headers["set-cookie"]


def test_mail_failure_invalidates_code(web: TestClient) -> None:
    sender(web).side_effect = RuntimeError("sensitive backend error")
    result = web.post("/api/auth/request", json={"email": MEMBER}, headers=CSRF)
    assert result.status_code == 503 and "sensitive" not in result.text
    with sqlite3.connect(auth(web).path) as db:
        assert db.execute("SELECT count(*) FROM codes").fetchone()[0] == 0


def test_public_twin_can_be_talked_to_but_not_changed_by_other_members(web: TestClient) -> None:
    login(web)
    persona = create(web)
    as_owner = web.cookies["twin_session"]
    as_other = login(web, OTHER)
    assert web.get("/api/personas").json() == []
    assert web.patch("/api/personas/" + persona, json={"public": True}, headers=CSRF).status_code == 404
    web.cookies.set("twin_session", as_owner)
    result = web.patch("/api/personas/" + persona, json={"public": True}, headers=CSRF)
    assert result.status_code == 200 and result.json()["public"] is True and result.json()["can_manage"] is True
    assert web.get("/api/identity?persona=" + persona).json()["onboarding_pending"] is True
    web.cookies.set("twin_session", as_other)
    [listed] = web.get("/api/personas").json()
    assert (listed["id"], listed["public"], listed["can_manage"]) == (persona, True, False)
    headers = {**CSRF, "X-Twin-Persona": persona}
    identity = web.get("/api/identity", headers=headers).json()
    assert identity["visitor"] is True and "onboarding_pending" not in identity
    assert web.get("/api/status", headers=headers).status_code == 200
    conversation = web.post("/api/conversations", json={}, headers=headers)
    assert conversation.status_code == 201, conversation.text
    body = {"messages": [{"role": "user", "content": "问题"}], "conversation_id": conversation.json()["id"]}
    response = web.post("/api/persona/chat/stream", json=body, headers=headers)
    assert response.status_code == 200 and "event: final" in response.text
    for method, path, payload in [
        ("GET", "/api/persona/sources", None),
        ("GET", "/api/persona/items", None),
        ("GET", "/api/me/voice/reference", None),
        ("PUT", "/api/identity", {"name": "偷改", "about": ""}),
        ("PUT", "/api/identity/avatar-preset", {"preset": "silver"}),
        ("POST", "/api/persona/notes", {"text": "不能写入他人的记忆"}),
        ("POST", "/api/persona/chat", {"messages": [{"role": "user", "content": "问题"}]}),
    ]:
        denied = web.request(method, path, json=payload, headers=headers)
        assert denied.status_code == 403, (path, denied.text)
        assert denied.json() == {"detail": "这是别人的公开分身，只能聊天"}
    assert web.delete("/api/personas/" + persona, headers=CSRF).status_code == 404
    web.cookies.set("twin_session", as_owner)
    assert web.get("/api/conversations?persona=" + persona).json() == []
    assert web.patch("/api/personas/" + persona, json={"public": False}, headers=CSRF).json()["public"] is False
    web.cookies.set("twin_session", as_other)
    assert web.get("/api/personas").json() == []
    assert web.get("/api/identity", headers=headers).status_code == 404


def test_trash_and_restore_are_owner_scoped_even_for_public_twins(web: TestClient) -> None:
    owner_token = login(web)
    persona = create(web)
    assert web.patch(f"/api/personas/{persona}", json={"public": True}, headers=CSRF).status_code == 200
    assert web.delete(f"/api/personas/{persona}", headers=CSRF).status_code == 200
    assert [p["id"] for p in web.get("/api/personas/trash").json()] == [persona]
    assert web.get("/api/status").json()["code"] == "no_persona"
    other_token = login(web, OTHER)
    assert web.get("/api/personas").json() == []
    assert web.get("/api/personas/trash").json() == []
    assert web.post(f"/api/personas/{persona}/restore", headers=CSRF).status_code == 404
    assert web.get("/api/identity?persona=" + persona).status_code == 404
    login(web, ADMIN)
    assert [p["id"] for p in web.get("/api/personas/trash").json()] == [persona]
    assert web.post(f"/api/personas/{persona}/restore", headers=CSRF).status_code == 200
    assert web.delete(f"/api/personas/{persona}", headers=CSRF).status_code == 200
    web.cookies.set("twin_session", owner_token)
    assert web.post(f"/api/personas/{persona}/restore", headers=CSRF).status_code == 200
    assert [p["id"] for p in web.get("/api/personas").json()] == [persona]
    web.cookies.set("twin_session", other_token)
    assert web.get("/api/personas").json()[0]["can_manage"] is False
    assert web.get("/api/personas/trash").json() == []


class FakeLogin:
    """Stands in for the app that owns single sign-on (audio-studio's GET /api/auth/me)."""

    def __init__(self) -> None:
        self.sessions = {
            "cookie-a": {"authenticated": True, "subject": "1001", "display_name": "张三", "account": "zhangsan"},
            "cookie-b": {"authenticated": True, "subject": "1002", "display_name": "李四", "account": "lisi"},
        }
        self.calls = 0
        login = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_: Any) -> None:
                pass

            def do_GET(self) -> None:
                login.calls += 1
                cookies = SimpleCookie(self.headers.get("Cookie", ""))
                session = login.sessions.get(cookies["sso"].value) if "sso" in cookies else None
                body = json.dumps(session or {"detail": "请先登录"}).encode()
                self.send_response(200 if session else 401)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/api/auth/me"


@pytest.fixture
def sso(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[TestClient, FakeLogin]]:
    monkeypatch.delenv("TWIN_SMTP_PASSWORD", raising=False)  # SSO needs no mail account
    monkeypatch.setattr(PersonaProcessing, "queue", lambda _: None)
    login = FakeLogin()
    settings = Settings(
        db_path=tmp_path / "twin.db",
        auth=AuthSettings(
            enabled=True,
            provider="sso",
            admin_emails=["sso:1002"],
            sso=SSOSettings(me_url=login.url, cookie="sso", login_url="/login?next=/twin/"),
        ),
    )
    with TestClient(create_app(settings, allowed_hosts=["twin.example.com"]), base_url="http://localhost") as client:
        yield client, login
    login.server.shutdown()
    login.server.server_close()


def test_sso_borrows_the_other_apps_login(sso: tuple[TestClient, FakeLogin]) -> None:
    web, login = sso
    signed_out = web.get("/api/whoami")
    assert signed_out.status_code == 401
    assert signed_out.json() == {"detail": "请先登录", "code": "login_required", "login_url": "/login?next=/twin/"}
    assert web.get("/api/personas").json()["login_url"] == "/login?next=/twin/"
    web.cookies.set("sso", "forged")
    assert web.get("/api/whoami").status_code == 401
    web.cookies.set("sso", "cookie-a")
    assert web.get("/api/whoami").json() == {
        "email": "sso:1001",
        "name": "张三",
        "address": "zhangsan@xjjk.com",
        "admin": False,
        "auth_enabled": True,
        "provider": "sso",
        "features": {"work": True, "ledger": True},
    }
    own = create(web)
    calls = login.calls
    for _ in range(3):
        assert web.get("/api/personas").status_code == 200
    assert login.calls == calls  # cached for cache_seconds
    assert web.post("/api/auth/request", json={"email": MEMBER}, headers=CSRF).status_code == 404
    assert web.post("/api/auth/verify", json={"email": MEMBER, "code": "1"}, headers=CSRF).status_code == 404
    web.cookies.set("sso", "cookie-b")
    assert web.get("/api/whoami").json()["admin"] is True
    web.cookies.set("sso", "cookie-c")
    login.sessions["cookie-c"] = {"authenticated": True, "subject": "1003", "display_name": "王五"}
    denied = web.get("/api/persona/state", headers={"X-Twin-Persona": own})
    assert denied.status_code == 404 and denied.json() == {"detail": "分身不存在"}


def test_a_twin_made_for_a_work_address_is_taken_on_signing_in(sso: tuple[TestClient, FakeLogin]) -> None:
    web, login = sso
    login.sessions["cookie-a"]["email"] = "ZhangSan@acme.cn"
    web.cookies.set("sso", "cookie-b")  # the administrator makes 张三's twin
    persona = create(web)
    made = web.put(f"/api/personas/{persona}/claim", json={"email": " zhangsan@ACME.cn "}, headers=CSRF)
    assert made.status_code == 200 and made.json()["claim_email"] == "zhangsan@acme.cn"
    assert made.json()["claimed"] is False and "mine" not in made.json()
    other = create(web)
    taken = web.put(f"/api/personas/{other}/claim", json={"email": "zhangsan@acme.cn"}, headers=CSRF)
    assert taken.status_code == 409
    assert web.put(f"/api/personas/{other}/claim", json={"email": "not-an-address"}, headers=CSRF).status_code == 400

    login.sessions["cookie-c"] = {"authenticated": True, "subject": "1003", "display_name": "王五"}
    web.cookies.set("sso", "cookie-c")  # someone else neither sees nor takes it
    assert web.get("/api/whoami").json()["address"] is None
    assert web.get("/api/personas").json() == []
    assert web.post(f"/api/personas/{persona}/approve", json={"public": True}, headers=CSRF).status_code == 404

    web.cookies.set("sso", "cookie-a")
    assert web.get("/api/whoami").json()["address"] == "zhangsan@acme.cn"
    [mine] = web.get("/api/personas").json()
    assert mine["id"] == persona and mine["can_manage"] is True
    assert mine["mine"] is True and mine["approved"] is False and mine["made_by_other"] is True
    assert mine["public"] is False  # it answers nobody else before 张三 says it is all right
    approved = web.post(f"/api/personas/{persona}/approve", json={"public": True}, headers=CSRF)
    assert approved.status_code == 200 and approved.json()["approved"] is True and approved.json()["public"] is True
    assert web.put(f"/api/personas/{persona}/claim", json={"email": None}, headers=CSRF).status_code == 409

    web.cookies.set("sso", "cookie-c")  # now a colleague can ask it
    assert [p["id"] for p in web.get("/api/personas").json()] == [persona]

    web.cookies.set("sso", "cookie-a")  # "这不是我": back to the administrator, who sees the address was wrong
    assert web.post(f"/api/personas/{persona}/disown", headers=CSRF).json() == {"disowned": True}
    assert web.get("/api/personas").json() == []
    web.cookies.set("sso", "cookie-b")
    back = next(p for p in web.get("/api/personas").json() if p["id"] == persona)
    assert back["claim_email"] is None and back["claim_rejected"] == "zhangsan@acme.cn"
    assert back["claimed"] is False and back["public"] is False
    assert (
        web.put(f"/api/personas/{persona}/claim", json={"email": "zhangsan2@acme.cn"}, headers=CSRF).json()[
            "claim_email"
        ]
        == "zhangsan2@acme.cn"
    )


def test_an_sso_account_without_an_address_has_one_in_the_allowed_domain(tmp_path: Path) -> None:
    settings = AuthSettings(
        enabled=True,
        provider="sso",
        allowed_domains=["xjjk.com"],
        sso=SSOSettings(me_url="http://127.0.0.1:9/me", cookie="sso", login_url="/login"),
    )
    auth = Auth(settings, tmp_path)
    assert auth.work_address("ZhangXun", None) == "zhangxun@xjjk.com"
    assert auth.work_address("zhangxun", "Zhang.Xun@Corp.cn") == "zhang.xun@corp.cn"
    assert auth.work_address(None, None) is None and auth.work_address("a b", None) is None


def test_sso_administrators_match_by_account_name(tmp_path: Path) -> None:
    auth = Auth(
        AuthSettings(
            enabled=True,
            provider="sso",
            admin_emails=["ZhangXun@xjjk.com", "sso:7", "lisi"],
            sso=SSOSettings(me_url="http://127.0.0.1:9/me", cookie="sso", login_url="/login"),
        ),
        tmp_path,
    )
    assert auth.identity("sso:1", "张", "zhangxun")["admin"]  # account name: the address before the @
    assert auth.identity("sso:1", "张", "zhangxun@xjjk.com")["admin"]
    assert auth.identity("sso:7")["admin"] and auth.identity("sso:2", None, "lisi")["admin"]
    assert not auth.identity("sso:2", "张", "zhangxun2", "zhangxun@example.com")["admin"]
    other = Auth(
        AuthSettings(
            enabled=True,
            provider="sso",
            admin_emails=["zhangxun@example.com"],
            sso=SSOSettings(me_url="http://127.0.0.1:9/me", cookie="sso", login_url="/login"),
        ),
        tmp_path,
    )
    assert not other.identity("sso:1", None, "zhangxun")["admin"]  # only for an allowed domain
    assert AuthSettings().admin_emails == ["zhangxun@xjjk.com", "qianjinwen@xjjk.com"]


def test_sso_login_service_down_means_signed_out(sso: tuple[TestClient, FakeLogin]) -> None:
    web, login = sso
    login.server.shutdown()
    login.server.server_close()
    web.cookies.set("sso", "cookie-a")
    response = web.get("/api/whoami")
    assert response.status_code == 401 and response.json()["login_url"] == "/login?next=/twin/"


@pytest.mark.parametrize(
    "sso_settings,message",
    [
        ({"me_url": "file:///etc/passwd", "cookie": "s", "login_url": "/login"}, "me_url"),
        ({"me_url": "http://127.0.0.1:8765/api/auth/me", "cookie": "a b", "login_url": "/login"}, "cookie"),
        ({"me_url": "http://127.0.0.1:8765/api/auth/me", "cookie": "s", "login_url": "//evil.example"}, "login_url"),
        (
            {"me_url": "http://127.0.0.1:8765/api/auth/me", "cookie": "s", "login_url": "https://evil.example"},
            "login_url",
        ),
    ],
)
def test_sso_settings_are_validated(sso_settings: dict[str, str], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        AuthSettings(enabled=True, provider="sso", sso=SSOSettings(**sso_settings))


def test_recording_library_belongs_to_the_signed_in_account(web: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    # Whatever this machine has free, the upload is admitted (admission has its own tests).
    monkeypatch.setattr(
        "twin.web.library.shutil.disk_usage", lambda _: SimpleNamespace(total=10**12, used=0, free=10**12)
    )
    other = login(web, OTHER)
    member = login(web)
    # No twin yet: the library is the account's, not a twin's.
    assert web.get("/api/library").json()["recordings"] == []
    created = web.post("/api/library/uploads", json={"filename": "周会.wav", "size": 4}, headers=CSRF).json()
    assert web.put(f"/api/library/uploads/{created['id']}?offset=0", content=b"RIFF", headers=CSRF).status_code == 200
    recording = web.post(f"/api/library/uploads/{created['id']}/finish", headers=CSRF).json()
    assert [r["id"] for r in web.get("/api/library").json()["recordings"]] == [recording["id"]]
    web.cookies.set("twin_session", other)
    assert web.get("/api/library").json()["recordings"] == []
    assert web.get(f"/api/library/uploads/{created['id']}").status_code == 404
    assert web.delete(f"/api/library/recordings/{recording['id']}", headers=CSRF).json() == {"deleted": True}
    web.cookies.set("twin_session", member)
    assert [r["id"] for r in web.get("/api/library").json()["recordings"]] == [recording["id"]]
    web.cookies.clear()
    assert web.get("/api/library").status_code == 401


def test_persona_limit_zero_means_unlimited(web: TestClient) -> None:
    web.app.state.personas.settings.auth.max_personas_per_member = 0  # type: ignore[union-attr]
    login(web)
    assert len({create(web) for _ in range(5)}) == 5
