from __future__ import annotations

import os
from pathlib import Path

import pytest

# Set by scripts/check.py, which leaves the tests marked ``codec`` to another machine: a test not marked so that
# runs ffmpeg or ffprobe fails, so the mark stays true.
NO_CODEC = os.environ.get("TWIN_NO_CODEC") == "1"


@pytest.fixture(autouse=True)
def _isolated_ops_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("TWIN_HOME", str(tmp_path / "twin-home"))
    monkeypatch.setenv("TWIN_SERVICE_DIR", str(tmp_path / "services"))
    monkeypatch.delenv("TWIN_ENV_FILE", raising=False)
    # A developer's own search key must not send test queries to the web.
    monkeypatch.delenv("TWIN_SEARCH_KEY", raising=False)


@pytest.fixture(autouse=True)
def _no_retrieval_rewrite(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Chat makes one extra model call to rewrite the retrieval query. Tests written against the reply call alone
    see no rewrite; tests marked ``rewrite`` exercise the real one."""
    if request.node.get_closest_marker("rewrite") is None:
        from twin.persona.rewrite import Rewrite

        monkeypatch.setattr("twin.persona.chat.rewrite", lambda *args, **kwargs: Rewrite())


@pytest.fixture(scope="session")
def _no_codec_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """ffmpeg and ffprobe that fail, saying what to do; once per run and outside each test's own tmp_path."""
    fakes = tmp_path_factory.mktemp("no-codec")
    for tool in ("ffmpeg", "ffprobe"):
        fake = fakes / tool
        fake.write_text(
            f"#!/bin/sh\necho '这个测试调用了 {tool}：请给它加上 @pytest.mark.codec' >&2\nexit 97\n", encoding="utf-8"
        )
        fake.chmod(0o755)
    return fakes


@pytest.fixture(autouse=True)
def _codec_marked(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    if not NO_CODEC or request.node.get_closest_marker("codec"):
        return
    fakes = request.getfixturevalue("_no_codec_path")
    monkeypatch.setenv("PATH", f"{fakes}{os.pathsep}{os.environ['PATH']}")


@pytest.fixture
def gated_life_facets(monkeypatch: pytest.MonkeyPatch) -> None:
    """No dimension needs questionnaire consent by default; gate D9 again so the consent mechanism stays tested."""
    from dataclasses import replace

    from twin.persona.dimensions import DIMENSION_BY_ID

    monkeypatch.setitem(DIMENSION_BY_ID, "D9", replace(DIMENSION_BY_ID["D9"], consent_required=True))
