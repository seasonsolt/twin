"""The administrator's view of the GPU services: probes against fake HTTP services and the day's record."""

from __future__ import annotations

import json
import socket
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from twin.config import ASRSettings, AuthSettings, EmbedSettings, Settings, SMTPSettings
from twin.web import create_app
from twin.web.gpu import GpuMonitor, asr_url, targets
from twin.web.jobs import PersonaProcessing

CSRF = {"X-Twin": "1"}
REMOTE = "python3 /srv/twin/deploy/compute/asr-funasr/remote.py"


class Fake:
    """A GPU service on a free loopback port whose answers the test changes as it goes."""

    def __init__(self) -> None:
        self.health: Any = {"ok": True, "version": "1.2", "device": "cuda", "busy": False}
        self.health_status = 200
        self.embed_status = 200
        self.embedding: Any = [0.1, 0.2]
        self.delay = 0.0
        # Answers for particular GET paths, instead of the health answer.
        self.paths: dict[str, tuple[int, Any]] = {}
        self.requests: list[tuple[str, str, dict[str, str], Any]] = []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:
                pass

            def answer(self, status: int, body: Any) -> None:
                time.sleep(fake.delay)
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self) -> None:
                fake.requests.append(("GET", self.path, dict(self.headers), None))
                self.answer(*fake.paths.get(self.path, (fake.health_status, fake.health)))

            def do_POST(self) -> None:
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                fake.requests.append(("POST", self.path, dict(self.headers), body))
                self.answer(fake.embed_status, {"data": [{"embedding": fake.embedding}]})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, args=(0.05,), daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def asr() -> Iterator[Fake]:
    fake = Fake()
    yield fake
    fake.close()


@pytest.fixture
def embed() -> Iterator[Fake]:
    fake = Fake()
    fake.health = {"ok": True, "version": "0.3", "model": "BAAI/bge-m3", "device": "cuda"}
    yield fake
    fake.close()


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def settings_for(tmp_path: Path, asr: str | None, embed: str | None, **auth: Any) -> Settings:
    return Settings(
        db_path=tmp_path / "twin.db",
        asr=ASRSettings(provider="command", command=f"{REMOTE} --url {asr}") if asr else ASRSettings(),
        embed=EmbedSettings(provider="openai_compat", base_url=f"{embed}/v1", api_key_env="TEST_GPU_EMBED_KEY")
        if embed
        else EmbedSettings(),
        **auth,
    )


def monitor_for(tmp_path: Path, asr: str | None, embed: str | None, **options: Any) -> GpuMonitor:
    return GpuMonitor(settings_for(tmp_path, asr, embed), timeout=0.5, **options)


def service(snapshot: dict[str, Any], key: str) -> dict[str, Any]:
    return next(s for s in snapshot["services"] if s["key"] == key)


def test_asr_address_comes_from_the_remote_command(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def url(command: str | None, provider: str = "command") -> str | None:
        return asr_url(Settings(db_path=tmp_path / "t.db", asr=ASRSettings(provider=provider, command=command)))  # type: ignore[arg-type]

    assert url(f"{REMOTE} --url http://127.0.0.1:18790") == "http://127.0.0.1:18790"
    assert url(f"{REMOTE} --url=http://10.0.0.2:9000 --x 1") == "http://10.0.0.2:9000"
    monkeypatch.delenv("TWIN_ASR_REMOTE_URL", raising=False)
    assert url(REMOTE) == "http://127.0.0.1:18790"
    monkeypatch.setenv("TWIN_ASR_REMOTE_URL", "http://127.0.0.1:18795")
    assert url(REMOTE) == "http://127.0.0.1:18795"
    assert url("python3 local_asr.py") is None
    assert url("unbalanced 'quote") is None
    assert url(None, "openai_compat") is None
    # Only scheme, host and port are kept for display; credentials and paths stay on the server.
    found = targets(
        Settings(
            db_path=tmp_path / "t.db",
            asr=ASRSettings(provider="command", command=f"{REMOTE} --url http://u:secret@127.0.0.1:18790/x?k=1"),
            embed=EmbedSettings(provider="openai_compat", base_url="http://127.0.0.1:18791/v1"),
        )
    )
    assert [(t.key, t.origin) for t in found] == [
        ("asr", "http://127.0.0.1:18790"),
        ("embed", "http://127.0.0.1:18791"),
    ]
    assert targets(Settings(db_path=tmp_path / "t.db")) == []


def test_healthy_services(tmp_path: Path, asr: Fake, embed: Fake, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_GPU_EMBED_KEY", "sk-test-only")
    asr.health["busy"] = True
    monitor = monitor_for(tmp_path, asr.url, embed.url)
    monitor.check()
    snapshot = monitor.snapshot()
    one = service(snapshot, "asr")
    assert one["name"] == "转写服务" and one["address"] == asr.url.removeprefix("http://")
    latest = one["latest"]
    assert latest["ok"] and latest["reason"] is None
    assert (latest["version"], latest["device"], latest["busy"]) == ("1.2", "cuda", True)
    assert latest["latency_ms"] is not None and latest["at"] > 0
    assert one["availability"] == 1 and one["failures"] == 0 and one["last_failure"] is None
    vectors = service(snapshot, "embed")["latest"]
    assert vectors["ok"] and vectors["model"] == "BAAI/bge-m3" and vectors["embeddings_ms"] is not None
    # The embedding service is asked for /health beside /v1, then for one real embedding with the key.
    assert [r[:2] for r in embed.requests] == [("GET", "/health"), ("POST", "/v1/embeddings")]
    assert embed.requests[1][2]["Authorization"] == "Bearer sk-test-only"
    assert embed.requests[1][3] == {"model": "BAAI/bge-m3", "input": ["健康检查"]}
    assert "sk-test-only" not in json.dumps(snapshot)


def test_timeout(tmp_path: Path, asr: Fake) -> None:
    asr.delay = 1.0
    monitor = monitor_for(tmp_path, asr.url, None)
    started = time.perf_counter()
    monitor.check()
    assert time.perf_counter() - started < 0.9
    latest = service(monitor.snapshot(), "asr")["latest"]
    assert not latest["ok"] and "响应超时" in latest["reason"]


def test_server_error(tmp_path: Path, asr: Fake, embed: Fake) -> None:
    asr.health_status = 500
    embed.embed_status = 500
    monitor = monitor_for(tmp_path, asr.url, embed.url)
    monitor.check()
    snapshot = monitor.snapshot()
    assert service(snapshot, "asr")["latest"]["reason"] == "服务返回错误（HTTP 500）"
    # /health says ok, but the real embeddings request fails.
    vectors = service(snapshot, "embed")["latest"]
    assert not vectors["ok"] and vectors["reason"] == "向量接口调用失败：服务返回错误（HTTP 500）"


def test_other_failures(tmp_path: Path, asr: Fake, embed: Fake) -> None:
    monitor = monitor_for(tmp_path, f"http://127.0.0.1:{free_port()}", embed.url)
    embed.embedding = []
    monitor.check()
    snapshot = monitor.snapshot()
    assert service(snapshot, "asr")["latest"]["reason"] == "隧道未连接或服务未启动（连接被拒绝）"
    assert service(snapshot, "embed")["latest"]["reason"] == "向量接口返回了空向量"
    asr.health = {"ok": False, "version": "1.2"}
    monitor = monitor_for(tmp_path, asr.url, embed.url)
    embed.health_status = 404  # an embedding server without /health (Ollama) is judged by its embeddings
    embed.embedding = [0.5]
    monitor.check()
    snapshot = monitor.snapshot()
    assert service(snapshot, "asr")["latest"]["reason"] == "服务自检未通过"
    assert service(snapshot, "embed")["latest"]["ok"]


def test_tunnel_up_but_nothing_behind_it(tmp_path: Path) -> None:
    # The reverse tunnel's listener accepts and hangs up when the GPU machine has nothing on the port.
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()

    def hang_up() -> None:
        connection, _ = listener.accept()
        connection.close()

    threading.Thread(target=hang_up, daemon=True).start()
    monitor = monitor_for(tmp_path, f"http://127.0.0.1:{listener.getsockname()[1]}", None)
    monitor.check()
    listener.close()
    assert service(monitor.snapshot(), "asr")["latest"]["reason"] == "隧道已连接，但 GPU 机器上的服务没有响应"


def test_record_shows_stability(tmp_path: Path, asr: Fake) -> None:
    now = [1_000_000.0]
    monitor = monitor_for(tmp_path, asr.url, None, window=3600.0, clock=lambda: now[0])
    for minute in range(90):
        asr.health_status = 500 if 30 <= minute < 40 else 200
        monitor.check()
        now[0] += 60
    one = service(monitor.snapshot(), "asr")
    # Only the last hour is kept: minutes 30..89, ten of them failed.
    assert one["checks"] == 60 and one["failures"] == 10
    assert one["availability"] == pytest.approx(50 / 60)
    assert one["last_failure"] == {"at": 1_000_000.0 + 39 * 60, "reason": "服务返回错误（HTTP 500）"}
    assert one["since"] == 1_000_000.0 + 40 * 60
    assert sum(b["checks"] for b in one["buckets"]) == 60 and sum(b["failures"] for b in one["buckets"]) == 10
    assert len(monitor.histories[0].checks) <= 61


def test_background_checks(tmp_path: Path, asr: Fake) -> None:
    monitor = monitor_for(tmp_path, asr.url, None, interval=0.05)
    monitor.start()
    try:
        deadline = time.monotonic() + 5
        while service(monitor.snapshot(), "asr")["checks"] < 3 and time.monotonic() < deadline:
            time.sleep(0.02)
    finally:
        monitor.stop()
    assert service(monitor.snapshot(), "asr")["checks"] >= 3


def test_admin_endpoint(tmp_path: Path, asr: Fake, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TWIN_SMTP_PASSWORD", "test-only")
    monkeypatch.setattr(PersonaProcessing, "queue", lambda _: None)
    sent: list[str] = []
    monkeypatch.setattr("twin.web.auth.send_code", lambda *args: sent.append(str(args[2])))
    settings = settings_for(
        tmp_path,
        asr.url,
        None,
        auth=AuthSettings(
            enabled=True,
            allowed_emails=["admin@example.com", "member@example.com"],
            admin_emails=["admin@example.com"],
            smtp=SMTPSettings(host="smtp.example.com", username="test", from_address="twin@example.com"),
        ),
    )
    app = create_app(settings)
    monitor: GpuMonitor = app.state.gpu
    monitor.interval = 3600  # no background round during the test
    client = TestClient(app, base_url="http://localhost")
    assert client.get("/api/admin/system").status_code == 401

    def login(email: str) -> None:
        client.post("/api/auth/request", json={"email": email}, headers=CSRF)
        assert client.post("/api/auth/verify", json={"email": email, "code": sent[-1]}, headers=CSRF).status_code == 200

    login("member@example.com")
    assert client.get("/api/admin/system").status_code == 403
    login("admin@example.com")
    first = client.get("/api/admin/system")
    assert first.status_code == 200
    assert service(first.json(), "asr")["latest"]["ok"] and len(asr.requests) == 1
    # A recent result is reused; refresh checks again, but not twice within five seconds.
    client.get("/api/admin/system")
    client.get("/api/admin/system?refresh=true")
    assert len(asr.requests) == 1
    monitor.histories[0].checks[-1].at -= 10
    asr.health_status = 500
    body = client.get("/api/admin/system?refresh=true").json()
    assert len(asr.requests) == 2
    one = service(body, "asr")
    assert one["latest"]["reason"] == "服务返回错误（HTTP 500）" and one["availability"] == 0.5
    assert "smtp" not in json.dumps(body) and "remote.py" not in json.dumps(body)


def test_endpoint_without_gpu_services(tmp_path: Path) -> None:
    client = TestClient(create_app(Settings(db_path=tmp_path / "twin.db")), base_url="http://localhost")
    body = client.get("/api/admin/system").json()
    assert body["services"] == []
