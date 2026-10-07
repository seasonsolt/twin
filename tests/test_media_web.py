"""Media endpoints reuse web hardening and export only escaped, inert content."""

from __future__ import annotations

import datetime as dt
import json
import re
from collections.abc import Iterator
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from twin.cli import app
from twin.config import Settings
from twin.media.adapters import presentable_from_chat_reply
from twin.media.render import EXPORT_CSP, export_html
from twin.media.schema import MediaManifest, MediaScript
from twin.media.script import script_from_presentable
from twin.persona.schema import ChatReply
from twin.web import create_app
from twin.web.app import MAX_JSON_BYTES

ATTACK = '<script>alert(1)</script><img src="https://example.invalid/a">'
HEADERS = {"X-Twin": "1"}
CREATED_AT = dt.datetime(2026, 1, 2, 3, 4, 5, tzinfo=dt.UTC)


@pytest.fixture
def source() -> ChatReply:
    return ChatReply(
        reply=ATTACK, citations=[ATTACK], confidence=0.6, abstain=False, abstain_reason="", retrieved_ids=[]
    )


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    settings = Settings(target_name="合成人物", db_path=tmp_path / "twin.db")
    with TestClient(create_app(settings), base_url="http://127.0.0.1") as client:
        yield client


class ExportParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: list[tuple[str, dict[str, str | None]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append((tag, dict(attrs)))


def test_api_script(client: TestClient, source: ChatReply) -> None:
    body = {"kind": "chat_reply", "answer": source.model_dump(mode="json")}
    response = client.post("/api/media/script", json=body, headers=HEADERS)
    assert response.status_code == 200
    script = MediaScript.model_validate(response.json())
    assert script == script_from_presentable(presentable_from_chat_reply(source), "合成人物")
    assert response.headers["cache-control"] == "no-store"
    assert "script-src 'self'" in response.headers["content-security-policy"]
    body["persona_name"] = "另一个合成人物"
    assert client.post("/api/media/script", json=body, headers=HEADERS).json()["persona_name"] == "另一个合成人物"


@pytest.mark.parametrize("endpoint", ["script", "export"])
def test_api_hardening(client: TestClient, source: ChatReply, endpoint: str) -> None:
    path = f"/api/media/{endpoint}"
    body = {"kind": "chat_reply", "answer": source.model_dump(mode="json")}
    assert client.post(path, json=body).status_code == 403
    assert client.post(path, json=body, headers={**HEADERS, "Host": "evil.invalid"}).status_code == 403
    large = client.post(path, content=b"x" * (MAX_JSON_BYTES + 1), headers=HEADERS)
    assert large.status_code == 413
    assert large.headers["cache-control"] == "no-store"
    assert client.post(path, headers=HEADERS, content="{").status_code == 400
    assert client.post(path, headers=HEADERS, json={"kind": "invalid", "answer": {}}).status_code == 400
    assert (
        client.post(path, headers=HEADERS, json={"kind": "removed_kind", "answer": body["answer"]}).status_code == 400
    )
    assert client.post(path, headers=HEADERS, json={"kind": "chat_reply", "answer": {}}).status_code == 400


def check_export(text: str, expected_fingerprint: str, created_at: dt.datetime | None = None) -> None:
    parser = ExportParser()
    parser.feed(text)
    scripts = [attrs for tag, attrs in parser.tags if tag == "script"]
    assert scripts == [{"type": "application/json", "id": "media-manifest"}]
    assert not any(tag in {"img", "iframe", "link", "object"} for tag, _ in parser.tags)
    assert not any(key.startswith("on") for _, attrs in parser.tags for key in attrs)
    assert ("meta", {"name": "ai-generated", "content": "true"}) in parser.tags
    assert ("meta", {"name": "generator", "content": "twin"}) in parser.tags
    assert not any(tag in {"header", "footer"} for tag, _ in parser.tags)
    assert ATTACK not in text
    manifest = re.search(r'<script type="application/json" id="media-manifest">(.*?)</script>', text)
    assert manifest is not None
    parsed = MediaManifest.model_validate_json(manifest[1])
    assert parsed.source_fingerprint == expected_fingerprint
    assert parsed.created_at.tzinfo is not None
    if created_at is not None:
        assert parsed.created_at == created_at
    assert unescape(re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]*)">', text)[1]) == EXPORT_CSP  # type: ignore[index]


def test_api_export(client: TestClient, source: ChatReply) -> None:
    body = {"kind": "chat_reply", "answer": source.model_dump(mode="json"), "persona_name": ATTACK}
    response = client.post("/api/media/export", json=body, headers=HEADERS)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-security-policy"] == EXPORT_CSP
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert "attachment" in response.headers["content-disposition"]
    check_export(response.text, presentable_from_chat_reply(source).source_fingerprint)
    source.reply = "没有个人经验。一般来说，先验证。"
    source.abstain = True
    source.mode = "abstain"
    source.abstain_reason = "没有依据"
    result = client.post("/api/media/export", json={**body, "answer": source.model_dump(mode="json")}, headers=HEADERS)
    assert result.status_code == 200
    assert '<p class="speech">没有个人经验。</p>' in result.text
    assert '<p class="notice">没有依据</p>' not in result.text


def test_manifest_cannot_break_out(source: ChatReply) -> None:
    script = script_from_presentable(presentable_from_chat_reply(source), ATTACK).model_copy(
        update={"source_fingerprint": ATTACK}
    )
    text = export_html(script, clock=lambda: CREATED_AT)
    assert text == export_html(script, clock=lambda: CREATED_AT)
    check_export(text, ATTACK, created_at=CREATED_AT)
    assert "\\u003c/script\\u003e" in text


@pytest.mark.parametrize("command", ["script", "export"])
@pytest.mark.parametrize("existing", [False, True])
def test_cli_private_outputs(tmp_path: Path, source: ChatReply, command: str, existing: bool) -> None:
    input_file = tmp_path / "reply.json"
    input_file.write_text(source.model_dump_json(), encoding="utf-8")
    output = tmp_path / "nested" / ("output.json" if command == "script" else "output.html")
    if existing:
        output.parent.mkdir()
        output.write_text("old")
        output.chmod(0o644)
    result = CliRunner().invoke(
        app,
        ["media", command, str(input_file), "--kind", "chat_reply", "--persona-name", "合成人物", "--out", str(output)],
    )
    assert result.exit_code == 0, result.output
    assert output.stat().st_mode & 0o777 == 0o600
    if command == "script":
        assert MediaScript.model_validate_json(output.read_bytes()) == script_from_presentable(
            presentable_from_chat_reply(source), "合成人物"
        )
    else:
        check_export(output.read_text(), presentable_from_chat_reply(source).source_fingerprint)


def test_cli_default_name_and_invalid_source(tmp_path: Path, source: ChatReply) -> None:
    config = tmp_path / "twin.toml"
    config.write_text('target_name = "合成人物"\n', encoding="utf-8")
    input_file = tmp_path / "answer.json"
    input_file.write_text(source.model_dump_json(), encoding="utf-8")
    output = tmp_path / "script.json"
    args = ["--config", str(config), "media", "script", str(input_file), "--out", str(output)]
    runner = CliRunner()
    assert runner.invoke(app, [*args, "--kind", "chat_reply"]).exit_code == 0
    data: dict[str, Any] = json.loads(output.read_text())
    assert data["persona_name"] == "合成人物"
    output.unlink()
    assert runner.invoke(app, [*args, "--kind", "invalid"]).exit_code != 0
    assert not output.exists()
    input_file.write_text("{}")
    assert runner.invoke(app, args).exit_code != 0
    assert not output.exists()
