from __future__ import annotations

import datetime as dt
import secrets
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from typer.testing import CliRunner

from twin import api, cli
from twin.config import ApiSettings, EmbedSettings, LLMSettings, Settings
from twin.embed import HashingEmbedder
from twin.llm import FakeLLM
from twin.persona.chat import PersonaChat
from twin.persona.store import PersonaStore


@pytest.fixture
def token(monkeypatch: pytest.MonkeyPatch) -> str:
    value = secrets.token_urlsafe(32)
    monkeypatch.setenv("TWIN_API_TOKEN", value)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    return value


@pytest.fixture
def chat() -> Iterator[PersonaChat]:
    with PersonaStore(":memory:") as store:
        yield PersonaChat(
            store,
            FakeLLM(
                lambda *args: {
                    "reply": "需要本人确认。",
                    "citations": [],
                    "confidence": 0.2,
                    "abstain": True,
                    "abstain_reason": "没有依据",
                    "topic_facets": ["2.1"],
                }
            ),
            HashingEmbedder(),
            Settings(),
        )


def test_health_auth_identity_and_answer(token: str, chat: PersonaChat) -> None:
    app = api.create_api(chat.settings, lambda: chat)
    with TestClient(app, base_url="http://localhost") as client:
        health = client.get("/v1/health")
        assert health.json() == {"status": "ok"}
        assert "X-AI-Generated" not in health.headers
        for authorization in (None, "Bearer wrong", "Basic wrong", "Bearer 非令牌"):
            headers = {} if authorization is None else {"Authorization": authorization}
            # HTTP transports restrict header text to ASCII; exercise UTF-8 comparison via raw bytes.
            if authorization == "Bearer 非令牌":
                headers = {"Authorization": authorization.encode()}
            response = client.post("/v1/ask", json={"question": "私密问题"}, headers=headers)
            assert response.status_code == 401
            assert "私密问题" not in response.text and token not in response.text
        client.headers["Authorization"] = f"Bearer {token}"
        identity = client.get("/v1/identity")
        assert identity.json() == {"name": "本人", "avatar": "default", "voice": "default"}
        response = client.post("/v1/ask", json={"question": "私密问题", "as_of": "2025-01-01"})
        assert response.status_code == 200
        assert response.json()["as_of"] == "2025-01-01"
        assert response.json()["answer"] == "需要本人确认。" and response.json()["abstain"]
        assert "label" not in response.json()
        assert response.headers["Cache-Control"] == "no-store"
        assert chat.store.chat_demand() == {}
        assert app.state.backend.usage.summary()["totals"]["calls"] == 2


@pytest.mark.parametrize("kind", ["llm", "embed"])
def test_external_backends_construct_lazily_without_grant(
    token: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    settings = Settings(
        db_path=tmp_path / "twin.db",
        llm=LLMSettings(model="offline", base_url="http://127.0.0.1:8000/v1"),
    )
    if kind == "llm":
        settings.llm.egress = "external"
    else:
        settings.embed = EmbedSettings(provider="openai_compat", base_url="https://external.invalid/v1")
    constructed: list[str] = []
    monkeypatch.setattr(
        api,
        "make_llm",
        lambda _: (
            constructed.append("llm")
            or FakeLLM(
                lambda *_: {
                    "reply": "需要本人确认。",
                    "citations": [],
                    "confidence": 0.2,
                    "abstain": True,
                    "abstain_reason": "没有依据",
                }
            )
        ),
    )
    monkeypatch.setattr(api, "make_embedder", lambda _: constructed.append("embed") or HashingEmbedder())
    client = TestClient(api.create_api(settings), base_url="http://127.0.0.1")
    assert client.get("/v1/health").status_code == 200
    assert not constructed and not settings.db_path.exists()
    response = client.post("/v1/ask", json={"question": "私密问题"}, headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200 and response.json()["answer"] == "需要本人确认。"
    assert "私密问题" not in response.text and constructed == ["llm", "embed"]
    assert (
        client.post("/v1/ask", json={"question": "私密问题"}, headers={"Authorization": f"Bearer {token}"}).status_code
        == 200
    )
    assert constructed == ["llm", "embed"]


def test_backend_failure_sanitized(token: str, capsys: pytest.CaptureFixture[str]) -> None:
    question = "非常私密的问题"

    def broken() -> PersonaChat:
        raise RuntimeError(f"{question} {token} https://secret.invalid")

    client = TestClient(api.create_api(Settings(), broken), base_url="http://localhost")
    response = client.post("/v1/ask", json={"question": question}, headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 503 and response.json()["detail"] == api.BACKEND_UNAVAILABLE
    assert question not in response.text and token not in response.text and "secret.invalid" not in response.text
    assert not capsys.readouterr().err


def test_sliding_rate_limit(token: str, monkeypatch: pytest.MonkeyPatch) -> None:
    now = [100.0]
    monkeypatch.setattr(api.time, "monotonic", lambda: now[0])
    client = TestClient(api.create_api(Settings(api=ApiSettings(rate_per_minute=2))), base_url="http://localhost")
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/v1/identity", headers=headers).status_code == 200
    now[0] += 10
    assert client.get("/v1/identity", headers=headers).status_code == 200
    response = client.post("/v1/ask", headers=headers, json={"question": "私密问题"})
    assert response.status_code == 429 and response.headers["Retry-After"] == "50"
    assert "私密问题" not in response.text
    assert client.get("/v1/health").status_code == 200
    assert client.get("/v1/identity").status_code == 401
    now[0] += 50
    assert client.get("/v1/identity", headers=headers).status_code == 200
    assert client.get("/v1/identity", headers=headers).status_code == 429


@pytest.mark.parametrize("host", ["localhost:8780", "127.0.0.1:8780", "[::1]:8780"])
def test_loopback_hosts(token: str, host: str) -> None:
    client = TestClient(api.create_api(Settings()))
    assert client.get("/v1/health", headers={"Host": host}).status_code == 200


def test_host_allowlist_and_hardening(token: str) -> None:
    client = TestClient(api.create_api(Settings(), allowed_hosts=["twin.example"]))
    for host, status in [("attacker.example", 403), ("twin.example:8780", 200)]:
        response = client.get("/v1/health", headers={"Host": host})
        assert response.status_code == status
        assert response.headers["X-Content-Type-Options"] == "nosniff"
    with pytest.raises(WebSocketDisconnect) as exc, client.websocket_connect("/v1/ask", headers={"Host": "localhost"}):
        pytest.fail("websockets must be refused")
    assert exc.value.code == 1008


@pytest.mark.parametrize(
    "body",
    [{"question": "私" * 2001}, {"question": "私密问题", "as_of": "私密日期"}, {"question": ["私密问题"]}],
)
def test_validation_never_echoes_input(token: str, body: object) -> None:
    client = TestClient(api.create_api(Settings()), base_url="http://localhost")
    response = client.post("/v1/ask", json=body, headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 400 and "私" not in response.text


def test_body_limit(token: str) -> None:
    client = TestClient(api.create_api(Settings()), base_url="http://localhost")
    response = client.post("/v1/ask", content="私" * api.MAX_BODY_BYTES, headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 413 and "私" not in response.text


def test_configurable_token_env(token: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TWIN_API_TOKEN")
    monkeypatch.setenv("TWIN_SERVICE_TEST_TOKEN", token)
    settings = Settings(api=ApiSettings(token_env="TWIN_SERVICE_TEST_TOKEN"))
    client = TestClient(api.create_api(settings), base_url="http://localhost")
    assert client.get("/v1/identity", headers={"Authorization": f"Bearer {token}"}).status_code == 200


@pytest.mark.parametrize("short", [None, "", "short", " " * 32])
def test_cli_refuses_unsafe_token(short: str | None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    if short is None:
        monkeypatch.delenv("TWIN_API_TOKEN", raising=False)
    else:
        monkeypatch.setenv("TWIN_API_TOKEN", short)
    config = tmp_path / "twin.toml"
    config.write_text("", encoding="utf-8")
    result = CliRunner().invoke(cli.app, ["--config", str(config), "api"])
    assert result.exit_code == 1 and "至少 32" in result.output and "secrets.token_urlsafe(32)" in result.output
    if short and short.strip():
        assert short not in result.output


def test_cli_remote_requires_opt_in(token: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = tmp_path / "twin.toml"
    config.write_text("", encoding="utf-8")
    args = ["--config", str(config), "api", "--host", "0.0.0.0"]
    result = CliRunner().invoke(cli.app, args)
    assert result.exit_code == 1 and "--allow-remote" in result.output
    served: list[object] = []
    monkeypatch.setattr(cli, "_serve", lambda *args, **kwargs: served.append((args, kwargs)))
    result = CliRunner().invoke(cli.app, [*args, "--allow-remote", "--allow-host", "twin.example"])
    assert result.exit_code == 0 and served and token not in result.output


def test_default_backends_construct_once_and_close_request_stores(
    token: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(
        db_path=tmp_path / "twin.db", llm=LLMSettings(model="offline", base_url="http://127.0.0.1:8000/v1")
    )
    calls: list[str] = []

    def llm_factory(_: object) -> FakeLLM:
        calls.append("llm")
        return FakeLLM(lambda *a: {"reply": "未知", "citations": [], "confidence": 0.1, "abstain": True})

    def embed_factory(_: object) -> HashingEmbedder:
        calls.append("embed")
        return HashingEmbedder()

    monkeypatch.setattr(api, "make_llm", llm_factory)
    monkeypatch.setattr(api, "make_embedder", embed_factory)
    backend = api.ServiceBackend(settings)
    assert backend.ask("问题", dt.date(2025, 1, 1)).as_of == dt.date(2025, 1, 1)
    backend.ask("问题", None)
    assert calls == ["llm", "embed"] and backend.usage.summary()["totals"]["calls"] == 4
    with PersonaStore(settings.db_path) as store:
        assert store.chat_demand() == {}
