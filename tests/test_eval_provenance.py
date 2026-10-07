from __future__ import annotations

import json
from pathlib import Path

import pytest

from twin.config import LLMSettings, Settings, configuration_fingerprint
from twin.embed import HashingEmbedder
from twin.evals.provenance import write_report
from twin.evals.schema import FailurePolicy, PairingPolicy, Purpose, Report, Scenario
from twin.llm import Effort, FakeLLM


@pytest.mark.parametrize("secret", ["1", "abc", "abcdefg", "abcdefgh", 'long-secret-"value'])
@pytest.mark.parametrize("chat", [False, True])
def test_report_redaction_preserves_json_numbers_and_redacts_secrets_of_any_length(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, secret: str, chat: bool
) -> None:
    settings = Settings()
    if chat:
        settings.chat_llm = LLMSettings(api_key_env="REPORT_REDACTION_TEST_KEY")
    else:
        settings.llm.api_key_env = "REPORT_REDACTION_TEST_KEY"
    monkeypatch.setenv(settings.effective_chat_llm.api_key_env, secret)
    report = Report(
        scenario=Scenario.PERSONAL,
        purpose=Purpose.FINAL_EVAL,
        systems=(),
        judges=(),
        failure_policy=FailurePolicy.ALL_JUDGES_REQUIRED,
        pairing_policy=PairingPolicy.ALL_SYSTEMS_INTERSECTION,
        skipped={"abc": 1},
        warnings=(f"Backend echoed {secret}; unrelated abc and 1",),
    )
    path = tmp_path / "records.json"
    write_report(path, report, settings)
    raw = path.read_text()
    restored = Report.model_validate_json(raw)
    assert restored.schema_version == 2 and restored.skipped == {"abc": 1}
    assert restored.warnings == (report.warnings[0].replace(secret, "[redacted]"),)
    if len(secret) >= 8:
        assert json.dumps(secret, ensure_ascii=False)[1:-1] not in raw


def test_configuration_identity_is_safe_and_sensitive_to_answer_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings()
    llm = FakeLLM(lambda s, u, schema: {})
    embedder = HashingEmbedder()
    panel: list[tuple[str, Effort]] = [("j0:judge", "low")]
    initial = configuration_fingerprint(settings, llm, embedder, panel)
    settings.llm.base_url = "https://private.invalid"
    settings.embed.base_url = "https://private-embed.invalid"
    settings.llm.api_key_env = "TEST_KEY_NAME"
    settings.embed.api_key_env = "TEST_EMBED_KEY_NAME"
    monkeypatch.setenv("TEST_KEY_NAME", "SECRET")
    monkeypatch.setenv("TEST_EMBED_KEY_NAME", "EMBED_SECRET")
    assert configuration_fingerprint(settings, llm, embedder, panel) == initial
    settings.llm.reasoning_effort = "none"
    no_reasoning = configuration_fingerprint(settings, llm, embedder, panel)
    assert no_reasoning != initial
    settings.llm.reasoning_effort = "low"
    assert configuration_fingerprint(settings, llm, embedder, panel) not in {initial, no_reasoning}
    settings.llm.reasoning_effort = None
    assert configuration_fingerprint(settings, llm, embedder, panel) == initial
    settings.llm.reasoning_effort_extract = "low"
    extraction_low = configuration_fingerprint(settings, llm, embedder, panel)
    assert extraction_low != initial
    settings.llm.reasoning_effort_extract = "none"
    assert configuration_fingerprint(settings, llm, embedder, panel) not in {initial, extraction_low}
    settings.llm.reasoning_effort_extract = None
    assert configuration_fingerprint(settings, llm, embedder, panel) == initial
    settings.judges = [LLMSettings(model="judge")]
    judge_default = configuration_fingerprint(settings, llm, embedder, panel)
    settings.judges[0].reasoning_effort = "none"
    assert configuration_fingerprint(settings, llm, embedder, panel) != judge_default
    settings.judges.clear()
    settings.target_aliases.append("alias")
    assert configuration_fingerprint(settings, llm, embedder, panel) != initial
    settings.target_aliases.clear()
    assert configuration_fingerprint(settings, llm, embedder, [("j0:judge", "high")]) != initial
    assert configuration_fingerprint(settings, llm, embedder, [("j0:other", "low")]) != initial
    assert configuration_fingerprint(settings, llm, HashingEmbedder(dim=512), panel) != initial
    settings.chat_llm = LLMSettings(model="fast-chat")
    chat_default = configuration_fingerprint(settings, llm, embedder, panel)
    assert chat_default != initial
    settings.chat_llm.extra_body = {"thinking": {"type": "disabled"}}
    assert configuration_fingerprint(settings, llm, embedder, panel) != chat_default
    settings.chat_llm.extra_body.clear()
    settings.chat_llm.base_url = "https://private-chat.invalid"
    settings.chat_llm.api_key_env = "CHAT_SECRET_KEY_NAME"
    assert configuration_fingerprint(settings, llm, embedder, panel) == chat_default
    settings.chat_llm = None
    llm.name = "other-answer-model"
    assert configuration_fingerprint(settings, llm, embedder, panel) != initial
