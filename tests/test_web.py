from __future__ import annotations

import socket
import threading
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, NamedTuple

import pytest
import typer
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from typer.testing import CliRunner

from twin import cli
from twin.config import Settings
from twin.web import app as web_app
from twin.web import create_app
from twin.web.jobs import JobManager, describe_error

TARGET = "本人"
BASE_URL = "http://127.0.0.1"
runner = CliRunner()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(db_path=tmp_path / "twin.db")


def make_client(settings: Settings, **options: Any) -> TestClient:
    return TestClient(create_app(settings, **options), base_url=BASE_URL)


def test_only_loopback_host_names_are_answered(settings: Settings) -> None:
    client = make_client(settings)
    for host in ("127.0.0.1:8765", "localhost", "LocalHost:9000", "[::1]:8765", "[::1]"):
        assert client.get("/api/status", headers={"Host": host}).status_code == 200, host
    for host in ("evil.example", "evil.example:8765", "localhost.evil.example", "127.0.0.1.nip.io", "[::2]:8765"):
        response = client.get("/api/status", headers={"Host": host})
        assert response.status_code == 403, host
        assert "主机名" in response.json()["detail"]
    response = client.post("/api/build", json={}, headers={"Host": "evil.example"})
    assert response.status_code == 403


def test_extra_allowed_host(settings: Settings) -> None:
    client = make_client(settings, allowed_hosts=["192.168.1.5"])
    assert client.get("/api/status", headers={"Host": "192.168.1.5:8765"}).status_code == 200
    assert client.get("/api/status", headers={"Host": "192.168.1.6:8765"}).status_code == 403


def test_root_without_front_end_files_shows_a_hint(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(web_app, "STATIC_DIR", tmp_path / "missing")
    client = make_client(settings)
    response = client.get("/")
    assert response.status_code == 200 and "前端文件" in response.text
    assert client.get("/api/status").status_code == 200


def test_front_end_files_are_served(settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text('<!doctype html><title>分身</title><script type="module" src="app.js"></script>')
    (static / "app.js").write_text("export {};\n")
    monkeypatch.setattr(web_app, "STATIC_DIR", static)
    client = make_client(settings)

    page = client.get("/")
    assert page.status_code == 200 and "<title>分身</title>" in page.text
    assert "script-src 'self'" in page.headers["content-security-policy"]
    script = client.get("/app.js")
    assert script.status_code == 200 and "javascript" in script.headers["content-type"]
    assert client.get("/static/app.js").status_code == 200
    missing = client.get("/api/nope")
    assert missing.status_code == 404 and missing.json()["detail"] == "找不到请求的资源"
    assert client.get("/static/%2E%2E/data/twin.db").status_code == 404


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_a_job_killed_by_a_base_exception_does_not_block_later_jobs() -> None:
    def die(log: Callable[[str], None]) -> object:
        log("开始")
        raise SystemExit(3)

    manager = JobManager(1, describe_error)
    job = manager.submit("persona_build", "构建", die)
    assert manager.wait(job.job_id, 10)
    for thread in threading.enumerate():
        if thread.name == f"twin-{job.job_id}":
            thread.join(10)
    snapshot = manager.snapshot(job.job_id)
    assert snapshot is not None and snapshot["status"] == "failed" and snapshot["progress"] == ["开始"]
    assert snapshot["error"] == "构建人格档案失败：任务意外中断（详细信息见运行 twin ui 的终端）"
    assert manager.active_exclusive() is None
    later = manager.submit("persona_build", "构建", lambda log: {"ok": True})
    assert manager.wait(later.job_id, 10)
    assert manager.snapshot(later.job_id) == {**manager.recent()[0], "result": {"ok": True}}


def test_unknown_job_is_404(settings: Settings) -> None:
    response = make_client(settings).get("/api/jobs/j_nope")
    assert response.status_code == 404 and "找不到任务" in response.json()["detail"]


@pytest.fixture
def config(tmp_path: Path) -> Path:
    path = tmp_path / "twin.toml"
    path.write_text(f'target_name = "{TARGET}"\ndb_path = "twin.db"\n', encoding="utf-8")
    return path


class Served(NamedTuple):
    app: Any
    host: str
    port: int
    url: str
    open_browser: bool


@pytest.fixture
def served(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[Served]]:
    calls: list[Served] = []
    monkeypatch.setattr(cli, "_serve", lambda *args: calls.append(Served(*args)))
    yield calls


def test_ui_listens_on_loopback_by_default(config: Path, served: list[Served]) -> None:
    result = CliRunner().invoke(cli.app, ["--config", str(config), "ui", "--open"])
    assert result.exit_code == 0, result.output
    [call] = served
    assert (call.host, call.port, call.url, call.open_browser) == ("127.0.0.1", 8765, "http://127.0.0.1:8765", True)
    assert "警告" not in result.stderr
    client = TestClient(call.app, base_url=call.url)
    assert client.get("/api/status").json()["target_name"] == TARGET


def test_ui_warns_when_listening_beyond_this_machine(config: Path, served: list[Served]) -> None:
    result = CliRunner().invoke(cli.app, ["--config", str(config), "ui", "--host", "192.168.1.5", "--port", "9000"])
    assert result.exit_code == 0, result.output
    assert "警告：网页界面将监听 192.168.1.5:9000" in result.stderr and "或 192.168.1.5" in result.stderr
    [call] = served
    assert call.url == "http://192.168.1.5:9000"
    client = TestClient(call.app, base_url=call.url)
    assert client.get("/api/status").status_code == 200
    assert client.get("/api/status", headers={"Host": "10.0.0.1:9000"}).status_code == 403

    result = CliRunner().invoke(cli.app, ["--config", str(config), "ui", "--host", "0.0.0.0"])
    assert result.exit_code == 0 and "警告" in result.stderr and "或 0.0.0.0" not in result.stderr
    assert served[-1].url == "http://127.0.0.1:8765"


def test_ui_answers_an_allowed_proxy_host_name_while_listening_on_loopback(config: Path, served: list[Served]) -> None:
    result = CliRunner().invoke(
        cli.app, ["--config", str(config), "ui", "--port", "8770", "--allow-host", "Twin.Example.com"]
    )
    assert result.exit_code == 0, result.output
    [call] = served
    assert (call.host, call.url) == ("127.0.0.1", "http://127.0.0.1:8770")
    client = TestClient(call.app, base_url=call.url)
    assert client.get("/api/status", headers={"Host": "twin.example.com"}).status_code == 200
    assert client.get("/api/status", headers={"Host": "other.example.com"}).status_code == 403


def test_ui_reports_a_busy_port_in_chinese(capsys: pytest.CaptureFixture[str]) -> None:
    with socket.create_server(("127.0.0.1", 0)) as busy:
        port = busy.getsockname()[1]
        with pytest.raises(typer.Exit):
            cli._serve(object(), "127.0.0.1", port, f"http://127.0.0.1:{port}", False)
    assert "端口可能已被占用" in capsys.readouterr().err


def test_websockets_are_refused(settings: Settings) -> None:
    client = make_client(settings)
    for host in ("127.0.0.1:8765", "evil.example"):
        with pytest.raises(WebSocketDisconnect) as refused, client.websocket_connect("/", headers={"Host": host}):
            pass
        assert refused.value.code == 1008, host
        expected = "host name not allowed" if host == "evil.example" else "websocket connections are not supported"
        assert refused.value.reason == expected
    assert client.get("/api/status").status_code == 200
