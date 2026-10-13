from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolated_ops_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("TWIN_HOME", str(tmp_path / "twin-home"))
    monkeypatch.setenv("TWIN_SERVICE_DIR", str(tmp_path / "services"))
    monkeypatch.delenv("TWIN_ENV_FILE", raising=False)


@pytest.fixture(autouse=True)
def _no_retrieval_rewrite(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Chat makes one extra model call to rewrite the retrieval query. Tests written against the reply call alone
    see no rewrite; tests marked ``rewrite`` exercise the real one."""
    if request.node.get_closest_marker("rewrite") is None:
        monkeypatch.setattr("twin.persona.chat.rewrite", lambda *args, **kwargs: "")


@pytest.fixture
def gated_life_facets(monkeypatch: pytest.MonkeyPatch) -> None:
    """No dimension needs questionnaire consent by default; gate D9 again so the consent mechanism stays tested."""
    from dataclasses import replace

    from twin.persona.dimensions import DIMENSION_BY_ID

    monkeypatch.setitem(DIMENSION_BY_ID, "D9", replace(DIMENSION_BY_ID["D9"], consent_required=True))
