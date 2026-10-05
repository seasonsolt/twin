from __future__ import annotations

import json
from pathlib import Path

import pytest

from twin.config import Settings, configuration_fingerprint
from twin.embed import HashingEmbedder
from twin.evals.provenance import write_report
from twin.evals.schema import FailurePolicy, PairingPolicy, Purpose, Report, Scenario
from twin.llm import Effort, FakeLLM


@pytest.mark.parametrize("secret", ["1", "abc", "abcdefg", "abcdefgh", 'long-secret-"value'])
def test_report_redaction_preserves_json_numbers_and_redacts_secrets_of_any_length(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, secret: str
) -> None:
    settings = Settings()
    settings.llm.api_key_env = "REPORT_REDACTION_TEST_KEY"
    monkeypatch.setenv(settings.llm.api_key_env, secret)
    report = Report(
        scenario=Scenario.BIOGRAPHY,
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
    settings.target_aliases.append("alias")
    assert configuration_fingerprint(settings, llm, embedder, panel) != initial
    settings.target_aliases.clear()
    assert configuration_fingerprint(settings, llm, embedder, [("j0:judge", "high")]) != initial
    assert configuration_fingerprint(settings, llm, embedder, [("j0:other", "low")]) != initial
    assert configuration_fingerprint(settings, llm, HashingEmbedder(dim=512), panel) != initial
    llm.name = "other-answer-model"
    assert configuration_fingerprint(settings, llm, embedder, panel) != initial
