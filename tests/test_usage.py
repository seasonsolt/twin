"""Offline accounting, budget, privacy and concurrency contracts."""

from __future__ import annotations

import json
import stat
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import openai
import pytest
from pydantic import BaseModel

from twin.cli import CONFIG_TEMPLATE
from twin.config import Settings, load_settings
from twin.embed import HashingEmbedder, OpenAICompatEmbedder, embedder_fingerprint
from twin.evals.provenance import write_report
from twin.evals.schema import FailurePolicy, PairingPolicy, Purpose, Report, Scenario
from twin.llm import AnthropicLLM, ClaudeCLILLM, FakeLLM, LLMInvalidOutput, LLMRefusal, OpenAICompatLLM
from twin.usage import (
    BudgetExceeded,
    Price,
    UsageRecorder,
    call_stage,
    canonical_endpoint,
    record_usage,
    request,
)
from twin.util import fingerprint, run_parallel


class Answer(BaseModel):
    value: str


def response(
    text: str = '{"value":"ok"}',
    *,
    incoming: int = 100,
    outgoing: int = 50,
    reason: int = 10,
    cached: int = 20,
    finish: str = "stop",
) -> Any:
    return SimpleNamespace(
        usage=SimpleNamespace(
            prompt_tokens=incoming,
            completion_tokens=outgoing,
            completion_tokens_details=SimpleNamespace(reasoning_tokens=reason),
            prompt_tokens_details=SimpleNamespace(cached_tokens=cached),
        ),
        choices=[SimpleNamespace(finish_reason=finish, message=SimpleNamespace(content=text, refusal=None))],
    )


class Client:
    base_url = "https://user:password@EXAMPLE.com:443//v1/?token=query-secret#fragment"

    def __init__(self, *responses: Any) -> None:
        self.responses = iter(responses)
        self.count = 0
        self.chat = SimpleNamespace(completions=self)
        self.embeddings = self

    def create(self, **kwargs: Any) -> Any:
        self.count += 1
        result = next(self.responses)
        if isinstance(result, Exception):
            raise result
        return result


def call(llm: Any) -> Answer:
    return llm.structured(system="private prompt", user="private response", schema=Answer)


def report() -> Report:
    return Report(
        scenario=Scenario.BIOGRAPHY,
        purpose=Purpose.FINAL_EVAL,
        systems=(),
        judges=(),
        failure_policy=FailurePolicy.ALL_JUDGES_REQUIRED,
        pairing_policy=PairingPolicy.ALL_SYSTEMS_INTERSECTION,
    )


def test_openai_usage_price_details_and_stage(tmp_path: Path) -> None:
    recorder = UsageRecorder({"model": Price(input_per_m=2, output_per_m=3, reasoning_per_m=10, cached_per_m=0.5)})
    with record_usage(recorder), call_stage("answer"):
        assert call(OpenAICompatLLM("model", client=Client(response()))).value == "ok"
    row = recorder.rows[0]
    assert (row.stage, row.backend, row.model, row.endpoint) == (
        "answer",
        "openai_compat",
        "model",
        "sha256:" + fingerprint("https://example.com/v1"),
    )
    assert (row.input_tokens, row.output_tokens, row.reasoning_tokens, row.cached_tokens) == (100, 50, 10, 20)
    assert (row.attempts, row.success, row.error_type, row.unknown_usage_attempts) == (1, True, None, 0)
    assert row.latency_seconds >= 0
    assert row.estimated_cost_usd == pytest.approx(390 / 1_000_000)
    recorder.write(tmp_path)
    for name in ("usage.json", "calls.jsonl"):
        assert stat.S_IMODE((tmp_path / name).stat().st_mode) == 0o600
    assert json.loads((tmp_path / "usage.json").read_text()) == recorder.summary()
    assert "prompt" not in json.loads((tmp_path / "calls.jsonl").read_text())


def test_schema_retry_sums_tokens_and_counts_attempts() -> None:
    recorder = UsageRecorder({"model": Price(input_per_m=1, output_per_m=2)})
    client = Client(response("not JSON"), response())
    with record_usage(recorder):
        call(OpenAICompatLLM("model", client=client))
    row = recorder.rows[0]
    assert len(recorder.rows) == 1 and client.count == row.attempts == 2
    assert (row.input_tokens, row.output_tokens, row.reasoning_tokens, row.cached_tokens) == (200, 100, 20, 40)
    assert row.estimated_cost_usd == pytest.approx(400 / 1_000_000)
    assert recorder.spent == pytest.approx(row.estimated_cost_usd)


@pytest.mark.parametrize("finish,error", [("content_filter", LLMRefusal), ("stop", LLMInvalidOutput)])
def test_failed_responses_are_billed_without_error_text(finish: str, error: type[Exception]) -> None:
    recorder = UsageRecorder({"model": Price(input_per_m=1, output_per_m=1)})
    client = Client(response("SECRET", finish=finish), response("SECRET", finish=finish))
    with record_usage(recorder), pytest.raises(error):
        call(OpenAICompatLLM("model", client=client))
    row = recorder.rows[0]
    assert row.error_type == error.__name__ and not row.success
    assert row.input_tokens == 100 * row.attempts
    assert row.estimated_cost_usd is not None
    assert recorder.summary()["totals"]["failures"] == 1


def test_real_sdk_retries_are_visible(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("twin.usage.time.sleep", lambda _: None)
    requests = []

    def transport(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(429, json={"error": {"message": "busy", "type": "rate_limit"}})
        return httpx.Response(
            200,
            json={
                "id": "id",
                "object": "chat.completion",
                "created": 1,
                "model": "model",
                "choices": [
                    {"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": '{"value":"ok"}'}}
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            },
        )

    client = openai.OpenAI(
        api_key="secret",
        base_url="https://example.com/v1",
        max_retries=10,
        http_client=httpx.Client(transport=httpx.MockTransport(transport)),
    )
    recorder = UsageRecorder({"model": Price(input_per_m=1, output_per_m=1)})
    with client, record_usage(recorder):
        call(OpenAICompatLLM("model", client=client, max_retries=1))
    row = recorder.rows[0]
    assert len(requests) == row.attempts == 2
    assert (row.input_tokens, row.output_tokens, row.unknown_usage_attempts) == (10, 5, 1)
    assert row.estimated_cost_usd is None
    assert row.known_cost_usd == pytest.approx(15 / 1_000_000)
    assert "费用未知" in recorder.chinese_summary()


def test_embedding_batch_rows_usage_and_character_fallback() -> None:
    a = SimpleNamespace(usage=SimpleNamespace(prompt_tokens=8), data=[SimpleNamespace(index=0, embedding=[1, 2])])
    b = SimpleNamespace(data=[SimpleNamespace(index=0, embedding=[2, 1])])
    recorder = UsageRecorder({"embed": Price(input_per_m=2)})
    with record_usage(recorder), call_stage("build"):
        result = OpenAICompatEmbedder("embed", client=Client(a, b), batch_size=1).embed(["甲乙", "丙"])
    assert result.shape == (2, 2)
    assert len(recorder.rows) == 2
    assert recorder.rows[0].input_tokens == 8
    assert recorder.rows[0].estimated_cost_usd == pytest.approx(16 / 1_000_000)
    assert recorder.rows[1].input_tokens is None and recorder.rows[1].characters == 1
    assert recorder.rows[1].estimated_cost_usd is None
    assert recorder.summary()["totals"]["unknown_cost_calls"] == 1


def test_fake_and_hashing_zero_cost_and_nested_thread_context() -> None:
    recorder = UsageRecorder()
    llm = FakeLLM(lambda *_: {"value": "ok"})

    def worker(_: int) -> None:
        with call_stage("judge"):
            call(llm)
        run_parallel(lambda _: call(llm), range(2), 2)
        HashingEmbedder(dim=8).embed(["甲"])

    with record_usage(recorder), call_stage("answer"):
        assert run_parallel(worker, range(30), 4) == [None] * 30
        call(llm)
    with record_usage(recorder):
        call(llm)
    assert len(recorder.rows) == 122
    assert sum(row.stage == "judge" for row in recorder.rows) == 30
    assert sum(row.stage == "answer" for row in recorder.rows) == 91
    assert recorder.rows[-1].stage == "other"
    assert all(row.estimated_cost_usd == 0 and row.input_tokens == 0 and row.attempts == 1 for row in recorder.rows)
    assert recorder.summary()["totals"]["estimated_cost_usd"] == 0


def test_anthropic_usage_truncation_retry_and_cache() -> None:
    messages = iter(
        [
            SimpleNamespace(
                stop_reason="max_tokens",
                usage=SimpleNamespace(
                    input_tokens=10, output_tokens=20, cache_read_input_tokens=4, cache_creation_input_tokens=2
                ),
            ),
            SimpleNamespace(
                stop_reason="end_turn",
                parsed_output=Answer(value="ok"),
                usage=SimpleNamespace(input_tokens=7, output_tokens=9, cache_read_input_tokens=3),
            ),
        ]
    )

    class Stream:
        def __enter__(self) -> Stream:
            return self

        def __exit__(self, *args: Any) -> None:
            pass

        def get_final_message(self) -> Any:
            return next(messages)

    client = SimpleNamespace(
        base_url="https://api.anthropic.com",
        beta=SimpleNamespace(messages=SimpleNamespace(stream=lambda **_: Stream())),
    )
    recorder = UsageRecorder({"model": Price(input_per_m=1, output_per_m=2)})
    with record_usage(recorder):
        call(AnthropicLLM("model", client=client, max_tokens=30))
    row = recorder.rows[0]
    assert (row.attempts, row.input_tokens, row.output_tokens, row.cached_tokens) == (2, 26, 29, 7)
    assert row.reasoning_tokens is None
    assert row.estimated_cost_usd == pytest.approx(84 / 1_000_000)


@pytest.mark.parametrize("usage", [True, False])
def test_claude_cli_usage_and_reported_cost(monkeypatch: pytest.MonkeyPatch, usage: bool) -> None:
    monkeypatch.setattr("twin.llm.shutil.which", lambda _: "/claude")
    payload: dict[str, Any] = {"structured_output": {"value": "ok"}}
    if usage:
        payload.update(usage={"input_tokens": 10, "output_tokens": 5}, total_cost_usd=0.01)
    monkeypatch.setattr(
        "twin.llm.subprocess.run", lambda *_, **__: subprocess.CompletedProcess([], 0, json.dumps(payload), "")
    )
    recorder = UsageRecorder()
    with record_usage(recorder):
        call(ClaudeCLILLM(retry_delays=()))
    row = recorder.rows[0]
    assert row.attempts == 1
    assert row.input_tokens == (10 if usage else None)
    assert row.reported_cost_usd == (0.01 if usage else None)
    assert row.estimated_cost_usd is None


def test_budget_rejects_before_network_and_survives_tolerated_failure() -> None:
    client = Client(response())
    recorder = UsageRecorder({"model": Price(input_per_m=1, output_per_m=1)}, max_cost_usd=0)
    with pytest.raises(BudgetExceeded, match="已停止新调用"), record_usage(recorder):
        outcomes = run_parallel(lambda _: call(OpenAICompatLLM("model", client=client)), range(8), 4)
        assert all(isinstance(outcome, BudgetExceeded) for outcome in outcomes)
    assert client.count == 0
    assert all(row.attempts == 0 for row in recorder.rows)


def test_budget_sees_settled_cost_before_retry() -> None:
    client = Client(response("invalid", incoming=10, outgoing=1), response())
    recorder = UsageRecorder({"model": Price(input_per_m=100, output_per_m=0)}, max_cost_usd=0.05)
    # Preflight input is below $0.05, but the deliberately large reported input exhausts the budget.
    client.responses = iter([response("invalid", incoming=600, outgoing=1), response()])
    with pytest.raises(BudgetExceeded), record_usage(recorder):
        call(OpenAICompatLLM("model", client=client, max_tokens=1))
    assert client.count == 1 and recorder.spent == pytest.approx(0.06)
    assert recorder.rows[0].attempts == 1


def test_unpriced_model_is_never_assigned_a_price() -> None:
    recorder = UsageRecorder(max_cost_usd=0)
    with record_usage(recorder):
        call(OpenAICompatLLM("unknown", client=Client(response())))
    assert recorder.rows[0].input_tokens == 100
    assert recorder.summary()["totals"]["estimated_cost_usd"] is None
    assert "费用未知" in recorder.chinese_summary()


def test_no_api_key_or_endpoint_query_in_any_new_artifact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    key, query = "top-secret-API-KEY", "token=query-secret"
    monkeypatch.setenv("TWIN_LLM_KEY", key)
    settings = Settings()
    settings.llm.base_url = Client.base_url
    client = Client(response())
    recorder = UsageRecorder()
    with record_usage(recorder), call_stage("answer"):
        call(OpenAICompatLLM("model", client=client))
        write_report(
            tmp_path / "records.json",
            report().model_copy(
                update={
                    "warnings": (f"Echoed {key}; {Client.base_url}; {query}",),
                }
            ),
            settings,
        )
    summary = json.loads((tmp_path / "usage.json").read_text())
    records = json.loads((tmp_path / "records.json").read_text())
    assert records["metrics"]["usage"] == summary
    Report.model_validate(records)
    for name in ("calls.jsonl", "usage.json", "records.json"):
        text = (tmp_path / name).read_text()
        assert all(
            secret not in text
            for secret in (key, query, "query-secret", "password", "private prompt", "private response")
        )
        assert stat.S_IMODE((tmp_path / name).stat().st_mode) == 0o600


def test_endpoint_identity_also_hides_secrets_in_the_path(tmp_path: Path) -> None:
    client = Client(response())
    client.base_url = "https://example.com/v1/key-in-path-secret"
    recorder = UsageRecorder()
    with record_usage(recorder):
        call(OpenAICompatLLM("model", client=client))
    recorder.write(tmp_path)
    assert recorder.rows[0].endpoint.startswith("sha256:")
    assert "key-in-path-secret" not in (tmp_path / "calls.jsonl").read_text()


def test_endpoint_normalization_preserves_embed_fingerprint() -> None:
    assert canonical_endpoint(Client.base_url) == "https://example.com/v1"
    a = OpenAICompatEmbedder("model", client=Client())
    b = OpenAICompatEmbedder("model", client=Client())
    b.base_url = "https://example.com/v1"
    assert embedder_fingerprint(a) == embedder_fingerprint(b)


def test_pricing_config_template_and_cli_option(tmp_path: Path) -> None:
    path = tmp_path / "twin.toml"
    path.write_text('[pricing."model"]\ninput_per_m = 1\noutput_per_m = 2\n[budget]\nmax_cost_usd = 3\n')
    settings = load_settings(path)
    assert settings.pricing["model"] == Price(input_per_m=1, output_per_m=2)
    assert settings.budget.max_cost_usd == 3
    example = Path("twin.toml.example").read_text(encoding="utf-8")
    assert (
        "".join(
            line
            for line in example.splitlines(keepends=True)
            if not line.startswith(("# vrm_path = ", "# reasoning_effort = "))
        )
        == CONFIG_TEMPLATE
    )


def retry_error(status: int = 429, headers: dict[str, str] | None = None) -> openai.APIStatusError:
    return openai.APIStatusError(
        "provider failure",
        response=httpx.Response(status, headers=headers, request=httpx.Request("POST", "https://example.com/v1")),
        body={},
    )


@pytest.mark.parametrize("random_value", [0.0, 0.5, 1.0])
def test_retry_jitter_bounds_and_backoff_cap(random_value: float) -> None:
    sleeps: list[float] = []
    calls = 0
    random_calls = 0

    def fail_then_succeed() -> str:
        nonlocal calls
        calls += 1
        if calls <= 6:
            raise retry_error()
        return "ok"

    def randomness() -> float:
        nonlocal random_calls
        random_calls += 1
        return random_value

    assert request(fail_then_succeed, 6, sleep=sleeps.append, random_fn=randomness) == "ok"
    assert calls == 7 and random_calls == 6
    bases = [0.5, 1.0, 2.0, 4.0, 8.0, 8.0]
    assert sleeps == pytest.approx([base * (1 - 0.25 * random_value) for base in bases])
    assert all(base * 0.75 <= delay <= base for base, delay in zip(bases, sleeps, strict=True))


@pytest.mark.parametrize(
    "headers,expected",
    [
        ({"Retry-After": "2"}, 2.0),
        ({"retry-after": "1.25"}, 1.25),
        ({"retry-after-ms": "1250"}, 1.25),
        ({"retry-after-ms": "1500", "retry-after": "2"}, 1.5),
        ({"retry-after": "Wed, 21 Oct 2015 07:28:00 GMT"}, 17.0),
        ({"retry-after": "120"}, 60.0),
        ({"retry-after-ms": "120000"}, 60.0),
        ({"retry-after": "Wed, 21 Oct 2015 07:30:00 GMT"}, 60.0),
        ({"retry-after": "0"}, 0.0),
    ],
)
def test_retry_server_hints_override_jitter(headers: dict[str, str], expected: float) -> None:
    sleeps: list[float] = []
    calls = 0

    def fail_then_succeed() -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise retry_error(headers=headers)
        return "ok"

    def no_randomness() -> float:
        raise AssertionError("Server hints must bypass jitter")

    assert request(fail_then_succeed, 1, sleep=sleeps.append, random_fn=no_randomness, now=lambda: 1445412463.0) == "ok"
    assert calls == 2 and sleeps == [expected]


@pytest.mark.parametrize(
    "headers,expected",
    [
        ({"retry-after-ms": "invalid", "retry-after": "2"}, 2.0),
        ({"retry-after": "invalid"}, 0.375),
        ({"retry-after": "-1"}, 0.375),
        ({"retry-after": "nan"}, 0.375),
        ({"retry-after": "inf"}, 0.375),
        ({"retry-after": "Wed, 21 Oct 2015 07:27:00 GMT"}, 0.375),
    ],
)
def test_invalid_or_past_retry_hints_fall_back(headers: dict[str, str], expected: float) -> None:
    sleeps: list[float] = []
    calls = 0

    def fail_then_succeed() -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise retry_error(headers=headers)
        return "ok"

    assert request(fail_then_succeed, 1, sleep=sleeps.append, random_fn=lambda: 1.0, now=lambda: 1445412463.0) == "ok"
    assert sleeps == [expected]


@pytest.mark.parametrize("status", [None, 400, 401, 403, 404, 422])
def test_non_transient_errors_do_not_retry_or_sleep(status: int | None) -> None:
    sleeps: list[float] = []
    calls = 0
    error = retry_error(status, {"retry-after": "60"}) if status is not None else ValueError("local failure")

    def fail() -> None:
        nonlocal calls
        calls += 1
        raise error

    def no_randomness() -> float:
        raise AssertionError("Non-transient errors must not sample jitter")

    with pytest.raises(type(error)) as caught:
        request(fail, 3, sleep=sleeps.append, random_fn=no_randomness)
    assert caught.value is error and calls == 1 and sleeps == []


@pytest.mark.parametrize("retries", [0, 2])
def test_retry_exhaustion_does_not_sleep_after_last_attempt(retries: int) -> None:
    sleeps: list[float] = []
    calls = 0
    error = retry_error(headers={"retry-after-ms": "200"})

    def fail() -> None:
        nonlocal calls
        calls += 1
        raise error

    with pytest.raises(openai.APIStatusError) as caught:
        request(fail, retries, sleep=sleeps.append, random_fn=lambda: 0.0)
    assert caught.value is error and calls == retries + 1
    assert sleeps == [0.2] * retries
