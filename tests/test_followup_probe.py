from __future__ import annotations

import importlib.util
import json
import re
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from pydantic import BaseModel

from twin.config import Settings
from twin.embed import HashingEmbedder
from twin.llm import FakeLLM
from twin.persona.store import PersonaStore

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "followup_probe.py"


@pytest.fixture(scope="module")
def probe() -> ModuleType:
    spec = importlib.util.spec_from_file_location("followup_probe", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up there
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def store(tmp_path: Path) -> Iterator[PersonaStore]:
    with PersonaStore(tmp_path / "twin.db") as opened:
        yield opened


def model(probe: ModuleType, answers: bool) -> FakeLLM:
    """Extracts one item per entry, and answers the question only once an answer is in the material."""

    def handler(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
        name = schema.__name__
        if name == "ExtractDraft":
            n = int(re.findall(r"\[(\d+)\]", user)[0])
            words = re.search(r"本人：(.{6})", user)
            assert words
            return {"items": [{"facet_id": "2.2", "statement": words[1], "quotes": [{"n": n, "quote": words[1]}]}]}
        if name == "MergeDraft":
            return {"items": [{"statement": "合并", "candidate_ids": re.findall(r"\[(pc_[0-9a-f]+)\]", user)}]}
        if name == "ChatDraft":
            if answers and "低一成" in user:
                ids = re.findall(r"\[((?:pi_[0-9a-f]+)|(?:src_[0-9a-f]+#\d+))\]", user)
                return {"reply": "最多低一成。", "citations": ids, "confidence": 0.9, "mode": "grounded"}
            return {"reply": "这得问我本人。", "citations": [], "confidence": 0.1, "mode": "abstain"}
        return {}

    return FakeLLM(handler)


def test_the_loop_closes_when_the_answer_is_used(probe: ModuleType, store: PersonaStore, tmp_path: Path) -> None:
    settings = Settings(target_name=probe.NAME, db_path=tmp_path / "twin.db")
    result = probe.run_loop(store, model(probe, True), HashingEmbedder(), settings, log=lambda line: None)
    assert result.ok, result.steps
    assert result.first.abstain and result.second and not result.second.abstain
    assert result.source_title == f"回答：{probe.QUESTION}" and result.answer_items and result.cited
    assert result.status_after == "answered" and [q for q, _ in result.calls].count("ChatDraft") == 2
    text = probe.report(result, "fake")
    assert text.startswith("# 弃权回流闭环 · fake") and "闭环成立" in text and "7. 第二次回答引用了" in text


def test_the_loop_reports_an_answer_the_twin_did_not_use(
    probe: ModuleType, store: PersonaStore, tmp_path: Path
) -> None:
    settings = Settings(target_name=probe.NAME, db_path=tmp_path / "twin.db")
    result = probe.run_loop(store, model(probe, False), HashingEmbedder(), settings, log=lambda line: None)
    assert not result.ok and result.second and result.second.abstain
    assert "闭环没有完全成立" in probe.report(result, "fake")


def test_the_command_writes_the_report_and_the_result(
    probe: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(probe, "make_llm", lambda settings: model(probe, True))
    monkeypatch.setattr(sys, "argv", ["followup_probe.py", "--out", str(tmp_path / "run")])
    assert probe.main() == 0
    assert "闭环成立" in (tmp_path / "run" / "report.md").read_text(encoding="utf-8")
    saved = json.loads((tmp_path / "run" / "result.json").read_text(encoding="utf-8"))
    assert saved["ok"] and saved["status_after"] == "answered" and saved["cited"]
    with pytest.raises(SystemExit, match="已有一次运行"):
        probe.main()
