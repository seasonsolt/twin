from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _no_retrieval_rewrite(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Chat makes one extra model call to rewrite the retrieval query. Tests written against the reply call alone
    see no rewrite; tests marked ``rewrite`` exercise the real one."""
    if request.node.get_closest_marker("rewrite") is None:
        monkeypatch.setattr("twin.persona.chat.rewrite", lambda *args, **kwargs: "")
