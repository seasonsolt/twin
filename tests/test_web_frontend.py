"""Built React frontend serving, bookmark redirects and security contracts."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from httpx import Response

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


def assert_security(response: Response, cache_control: str = "no-cache") -> None:
    for name, value in web_app._SECURITY_HEADERS.items():
        assert response.headers[name] == value
    assert response.headers["cache-control"] == cache_control


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(Settings(db_path=tmp_path / "twin.db")), base_url="http://127.0.0.1")


def test_root_serves_built_index_with_unchanged_security(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert response.text == (web_app.STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert response.headers["content-type"].startswith("text/html")
    assert_security(response)
    head = client.head("/")
    assert head.status_code == 200 and not head.content
    assert_security(head)


def test_assets_and_csp_safe_build(client: TestClient) -> None:
    parser = IndexParser()
    parser.feed(client.get("/").text)
    assert parser.scripts and parser.references
    assert all(script.get("src") for script in parser.scripts)
    assert not "".join(parser.inline_script).strip()
    for reference in parser.references:
        bundled = re.fullmatch(r"/assets/[\w-]+-[\w-]+\.(js|css)", reference)
        assert bundled or reference == "/fonts/ma-shan-zheng/font.css"
        response = client.get(reference)
        assert response.status_code == 200, reference
        expected = "text/javascript" if reference.endswith(".js") else "text/css"
        assert response.headers["content-type"].startswith(expected)
        assert_security(response)
    assets = web_app.STATIC_DIR / "assets"
    # Include lazy-loaded page chunks and styles, not just index references.
    for asset in assets.iterdir():
        assert asset.suffix in (".js", ".css")
        response = client.get(f"/assets/{asset.name}")
        assert response.status_code == 200, asset.name
        expected = "text/javascript" if asset.suffix == ".js" else "text/css"
        assert response.headers["content-type"].startswith(expected)
        assert_security(response)
    for stylesheet in assets.glob("*.css"):
        css = stylesheet.read_text(encoding="utf-8")
        assert not re.search(r"(?:@import\s+(?:url\(\s*)?|url\(\s*)[\"']?(?:[a-z][\w+.-]*:|//)", css, re.IGNORECASE)
    assert not list(assets.glob("*.map"))
    assert {path.name for path in web_app.STATIC_DIR.iterdir()} == {"index.html", "assets", "fonts"}
    font_css = client.get("/fonts/ma-shan-zheng/font.css")
    assert font_css.status_code == 200
    assert_security(font_css)
    assert "font-display: swap" in font_css.text and "unicode-range:" in font_css.text
    urls = re.findall(r"url\(([^)]+)\)", font_css.text)
    assert len(urls) == 92
    for url in urls:
        assert re.fullmatch(r"/fonts/ma-shan-zheng/slice-\d{3}\.woff2", url)
        response = client.get(url)
        assert response.status_code == 200 and response.content.startswith(b"wOF2")
        assert response.headers["content-type"].startswith("font/woff2")
        assert_security(response)


@pytest.mark.parametrize("path", ["/next", "/next/"])
@pytest.mark.parametrize("method", ["get", "head"])
def test_bookmarks_redirect_to_root(client: TestClient, path: str, method: str) -> None:
    response = client.request(method, path, follow_redirects=False)
    assert response.status_code == 308 and response.headers["location"] == "/"
    assert_security(response)
    assert client.get(path).text == client.get("/").text


@pytest.mark.parametrize("directory_exists", [False, True])
def test_without_build_shows_placeholder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, directory_exists: bool
) -> None:
    static = tmp_path / "static"
    if directory_exists:
        static.mkdir()
    monkeypatch.setattr(web_app, "STATIC_DIR", static)
    client = TestClient(create_app(Settings(db_path=tmp_path / "twin.db")), base_url="http://127.0.0.1")
    response = client.get("/")
    assert response.status_code == 200 and "前端文件" in response.text
    assert "pnpm -C frontend build" in response.text
    assert response.headers["content-type"].startswith("text/html")
    assert_security(response)
    for path in ("/next", "/next/"):
        redirect = client.get(path, follow_redirects=False)
        assert redirect.status_code == 308 and redirect.headers["location"] == "/"
        assert_security(redirect)
    assert client.get("/api/status").status_code == 200
    missing = client.get("/api/nope")
    assert missing.status_code == 404 and missing.json() == {"detail": "找不到请求的资源"}
    assert_security(missing, "no-store")
    assert client.get("/assets/missing.js").status_code == 404


@pytest.mark.parametrize(
    "path",
    [
        "/api/nope",
        "/api/nope.js",
        "/api/nope/",
        "/chat",
        "/index.html",
        "/app.js",
        "/static/app.js",
        "/next/assets/missing.js",
        "/assets/missing.js",
        "/fonts/missing.woff2",
        "/fonts/%2E%2E/index.html",
        "/fonts/%2E%2E%2F%2E%2E%2Fapp.py",
        "/assets/%2E%2E/index.html",
        "/assets/%2E%2E/%2E%2E/app.py",
        "/assets/%2E%2E%2F%2E%2E%2Fapp.py",
        "/%2E%2E/data/twin.db",
        "/static/%2E%2E/data/twin.db",
    ],
)
def test_unknown_paths_and_traversal_are_json_404(client: TestClient, path: str) -> None:
    response = client.get(path)
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {"detail": "找不到请求的资源"}
    assert_security(response, "no-store" if path.startswith("/api/") else "no-cache")


def test_assets_do_not_follow_symlinks_outside_static(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    static = tmp_path / "static"
    assets = static / "assets"
    assets.mkdir(parents=True)
    (static / "index.html").write_text("<!doctype html><title>twin</title>", encoding="utf-8")
    outside = tmp_path / "private.js"
    outside.write_text("export {};", encoding="utf-8")
    (assets / "escape.js").symlink_to(outside)
    monkeypatch.setattr(web_app, "STATIC_DIR", static)
    client = TestClient(create_app(Settings(db_path=tmp_path / "twin.db")), base_url="http://127.0.0.1")
    response = client.get("/assets/escape.js")
    assert response.status_code == 404 and response.json() == {"detail": "找不到请求的资源"}
    assert_security(response)
