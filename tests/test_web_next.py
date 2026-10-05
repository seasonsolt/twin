from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from twin.config import Settings
from twin.web import app as web_app
from twin.web import create_app


class IndexParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.references: list[str] = []
        self.scripts: list[dict[str, str | None]] = []
        self.inline_script: list[str] = []
        self.in_script = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        for name in ("src", "href"):
            value = attributes.get(name)
            if value:
                self.references.append(value)
        if tag == "script":
            self.scripts.append(attributes)
            self.in_script = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self.in_script = False

    def handle_data(self, data: str) -> None:
        if self.in_script:
            self.inline_script.append(data)


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(Settings(db_path=tmp_path / "twin.db")), base_url="http://127.0.0.1")


@pytest.mark.parametrize("path", ["/next", "/next/"])
def test_next_serves_built_index_with_unchanged_security(client: TestClient, path: str) -> None:
    response = client.get(path)
    assert response.status_code == 200
    assert response.text == (web_app.STATIC_DIR / "next" / "index.html").read_text(encoding="utf-8")
    assert response.headers["content-security-policy"] == web_app._SECURITY_HEADERS["Content-Security-Policy"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-type"].startswith("text/html")
    assert client.get("/").status_code == 200


def test_next_assets_and_csp_safe_build(client: TestClient) -> None:
    parser = IndexParser()
    parser.feed(client.get("/next/").text)
    assert parser.scripts and parser.references
    assert all(script.get("src") for script in parser.scripts)
    assert not "".join(parser.inline_script).strip()
    for reference in parser.references:
        assert not re.search(r"https?://", reference, re.IGNORECASE)
        assert reference.startswith("/next/assets/")
        assert re.search(r"-[\w-]+\.(js|css)$", reference)
        response = client.get(reference)
        assert response.status_code == 200, reference
        expected = "text/javascript" if reference.endswith(".js") else "text/css"
        assert response.headers["content-type"].startswith(expected)
        assert response.headers["content-security-policy"] == web_app._SECURITY_HEADERS["Content-Security-Policy"]
    assets = web_app.STATIC_DIR / "next" / "assets"
    for stylesheet in assets.glob("*.css"):
        css = stylesheet.read_text(encoding="utf-8")
        assert not re.search(r"(?:@import\s+(?:url\(\s*)?|url\(\s*)[\"']?(?:https?:|//)", css, re.IGNORECASE)
    assert not list(assets.glob("*.map"))
    assert client.get("/next/assets/%2E%2E/%2E%2E/app.py").status_code == 404


@pytest.mark.parametrize("old_ui", [False, True])
def test_next_without_build_shows_placeholder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, old_ui: bool) -> None:
    static = tmp_path / "static"
    static.mkdir()
    if old_ui:
        (static / "index.html").write_text("<title>old UI</title>", encoding="utf-8")
    monkeypatch.setattr(web_app, "STATIC_DIR", static)
    client = TestClient(create_app(Settings(db_path=tmp_path / "twin.db")), base_url="http://127.0.0.1")
    for path in ("/next", "/next/"):
        response = client.get(path)
        assert response.status_code == 200 and "新前端文件" in response.text
        assert "script-src 'self'" in response.headers["content-security-policy"]
    assert client.get("/api/status").status_code == 200
    assert client.get("/").status_code == 200
