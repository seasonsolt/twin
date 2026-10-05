"""Local, prompt-free call accounting. No tracing service or credentials are persisted."""

from __future__ import annotations

import inspect
import json
import math
import posixpath
import random
import re
import threading
import time
import warnings
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass
from datetime import UTC
from email.utils import parsedate_to_datetime
from functools import wraps
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, Field

from .util import fingerprint, open_private, private_directory


class Price(BaseModel):
    input_per_m: float = Field(ge=0, allow_inf_nan=False)
    output_per_m: float = Field(default=0, ge=0, allow_inf_nan=False)
    reasoning_per_m: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    cached_per_m: float | None = Field(default=None, ge=0, allow_inf_nan=False)


class BudgetExceeded(RuntimeError):
    """Sticky run-level stop, even when a pipeline tolerates individual call failures."""


@dataclass
class CallRow:
    stage: str
    backend: str
    model: str
    endpoint: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    reasoning_tokens: int | None = None
    cached_tokens: int | None = None
    characters: int = 0
    latency_seconds: float = 0
    attempts: int = 0
    success: bool = False
    error_type: str | None = None
    estimated_cost_usd: float | None = None
    known_cost_usd: float = 0.0
    reported_cost_usd: float | None = None
    unknown_usage_attempts: int = 0


def canonical_endpoint(base_url: str) -> str:
    """Normalize an endpoint, discarding userinfo, query and fragment (never pass keys here)."""
    parts = urlsplit(base_url)
    host = (parts.hostname or "").lower()
    if ":" in host:
        host = f"[{host}]"
    port = parts.port
    if port is not None and (parts.scheme.lower(), port) not in (("http", 80), ("https", 443)):
        host = f"{host}:{port}"
    path = posixpath.normpath("/" + re.sub(r"/+", "/", parts.path).lstrip("/")).rstrip("/")
    return urlunsplit((parts.scheme.lower(), host, path, "", ""))


def _field(value: Any, name: str) -> Any:
    return value.get(name) if isinstance(value, dict) else getattr(value, name, None)


def _number(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


class UsageRecorder:
    """Thread-safe rows and budget gate. Budgeted attempts serialize admission and settlement.

    Preflight uses UTF-8 bytes as a conservative input estimate plus the requested output cap;
    recorded tokens always come from the provider. This is not a provider-enforced billing cap.
    """

    def __init__(self, pricing: Mapping[str, Price] | None = None, max_cost_usd: float | None = None) -> None:
        if max_cost_usd is not None and (not math.isfinite(max_cost_usd) or max_cost_usd < 0):
            raise ValueError("费用预算必须是非负有限数值")
        self.pricing = dict(pricing or {})
        self.max_cost_usd = max_cost_usd
        self.rows: list[CallRow] = []
        self._lock = threading.RLock()
        self._gate = threading.RLock()
        self.spent = 0.0
        self.stop: BudgetExceeded | None = None

    def cost(self, row: CallRow, *, zero: bool = False) -> float | None:
        if zero:
            return 0.0
        price = self.pricing.get(row.model)
        if price is None or row.input_tokens is None or row.unknown_usage_attempts:
            return None
        output = row.output_tokens or 0
        reasoning = min(row.reasoning_tokens or 0, output)
        cached = min(row.cached_tokens or 0, row.input_tokens)
        return (
            (row.input_tokens - cached) * price.input_per_m
            + cached * (price.cached_per_m if price.cached_per_m is not None else price.input_per_m)
            + (output - reasoning) * price.output_per_m
            + reasoning * (price.reasoning_per_m if price.reasoning_per_m is not None else price.output_per_m)
        ) / 1_000_000

    def check(self, row: CallRow, input_estimate: int, output_cap: int) -> None:
        with self._lock:
            if self.stop is not None:
                raise self.stop
            price = self.pricing.get(row.model)
            if self.max_cost_usd is None or price is None:
                return
            forecast = (
                input_estimate * max(price.input_per_m, price.cached_per_m or 0)
                + output_cap * max(price.output_per_m, price.reasoning_per_m or 0)
            ) / 1_000_000
            if self.spent + forecast > self.max_cost_usd:
                self.stop = BudgetExceeded(
                    f"费用预算不足：已估算 ${self.spent:.6f}，下一次调用预计最多 ${forecast:.6f}，"
                    f"超过上限 ${self.max_cost_usd:.6f}；已停止新调用"
                )
                raise self.stop

    def add(self, row: CallRow, zero: bool) -> None:
        with self._lock:
            row.estimated_cost_usd = self.cost(row, zero=zero)
            self.rows.append(row)

    def summary(self) -> dict[str, Any]:
        with self._lock:
            rows = list(self.rows)

        def aggregate(selected: list[CallRow]) -> dict[str, Any]:
            result: dict[str, Any] = {
                "calls": len(selected),
                "failures": sum(not r.success for r in selected),
                "attempts": sum(r.attempts for r in selected),
                "characters": sum(r.characters for r in selected),
                "unknown_cost_calls": sum(r.estimated_cost_usd is None for r in selected),
                "known_cost_usd": sum(r.known_cost_usd for r in selected),
                "reported_cost_usd": sum(r.reported_cost_usd or 0 for r in selected),
            }
            for name in ("input_tokens", "output_tokens", "reasoning_tokens", "cached_tokens"):
                values = [getattr(r, name) for r in selected]
                result[name] = sum(v for v in values if v is not None) if any(v is not None for v in values) else None
            result["unknown_usage_attempts"] = sum(r.unknown_usage_attempts for r in selected)
            result["estimated_cost_usd"] = None if result["unknown_cost_calls"] else result["known_cost_usd"]
            return result

        groups = sorted({(r.stage, r.model) for r in rows})
        return {
            "stages": [
                {"stage": stage, "model": model, **aggregate([r for r in rows if (r.stage, r.model) == (stage, model)])}
                for stage, model in groups
            ],
            "totals": aggregate(rows),
        }

    def write(self, directory: Path) -> None:
        private_directory(directory)
        with self._lock:
            rows = [asdict(row) for row in self.rows]
            summary = self.summary()
        with open_private(directory / "calls.jsonl") as stream:
            for row in rows:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        with open_private(directory / "usage.json") as stream:
            stream.write(json.dumps(summary, ensure_ascii=False, indent=2))

    def chinese_summary(self) -> str:
        total = self.summary()["totals"]
        cost = total["estimated_cost_usd"]
        money = f"估算费用 ${cost:.6f}" if cost is not None else f"费用未知（已知部分 ${total['known_cost_usd']:.6f}）"
        if total["reported_cost_usd"]:
            money += f"；CLI 报告费用 ${total['reported_cost_usd']:.6f}"

        def tokens(key: str) -> str:
            return "未知" if total[key] is None else str(total[key])

        return (
            f"调用统计：{total['calls']} 次，失败 {total['failures']} 次；输入 {tokens('input_tokens')} token、"
            f"输出 {tokens('output_tokens')} token（推理 {tokens('reasoning_tokens')}、"
            f"缓存 {tokens('cached_tokens')}），"
            f"未报告用量的尝试 {total['unknown_usage_attempts']} 次，字符 {total['characters']}；{money}。"
        )


_stage: ContextVar[str] = ContextVar("call_stage", default="other")
_recorder: ContextVar[UsageRecorder | None] = ContextVar("usage_recorder", default=None)
_active: ContextVar[CallRow | None] = ContextVar("usage_call", default=None)
_default = UsageRecorder()


def failure_directory(directory: Path) -> Path:
    """Keep failed-run traces without changing an existing successful run's artifacts."""
    parent = directory.parent
    while not parent.exists():
        parent = parent.parent
    return parent / f"{directory.name}-failed-{time.time_ns()}"


def active_recorder() -> UsageRecorder | None:
    return _recorder.get()


def current_recorder() -> UsageRecorder:
    return _recorder.get() or _default


@contextmanager
def call_stage(label: str) -> Iterator[None]:
    token = _stage.set(label)
    try:
        yield
    finally:
        _stage.reset(token)


@contextmanager
def record_usage(recorder: UsageRecorder) -> Iterator[UsageRecorder]:
    token = _recorder.set(recorder)
    try:
        yield recorder
        if recorder.stop is not None:
            raise recorder.stop
    finally:
        _recorder.reset(token)


def usage_run[**P, R](fn: Callable[P, R]) -> Callable[P, R]:
    """Isolate a direct evaluation run; reuse an enclosing CLI run's recorder."""
    signature = inspect.signature(fn)

    @wraps(fn)
    def run(*args: P.args, **kwargs: P.kwargs) -> R:
        if _recorder.get() is not None:
            return fn(*args, **kwargs)
        arguments = signature.bind(*args, **kwargs).arguments
        settings = arguments["settings"]
        recorder = UsageRecorder(settings.pricing, settings.budget.max_cost_usd)
        if recorder.max_cost_usd is not None:
            backends = [arguments.get("llm"), arguments.get("embedder")]
            backends.extend(judge.llm for judge in arguments.get("judges", ()) or ())
            unpriced = set()
            for backend in backends:
                while backend is not None and hasattr(backend, "llm"):
                    backend = backend.llm
                model = getattr(backend, "model", None)
                if model is not None and model not in recorder.pricing:
                    unpriced.add(model)
            if unpriced:
                warnings.warn("以下模型费用未知，无法纳入预算：" + "、".join(sorted(unpriced)), stacklevel=2)
        failed = False
        try:
            with record_usage(recorder):
                return fn(*args, **kwargs)
        except BaseException:
            failed = True
            raise
        finally:
            directory = arguments.get("out")
            if directory is None and (records_path := arguments.get("records_path")) is not None:
                directory = records_path.parent
            if directory is not None and recorder.rows:
                if failed:
                    directory = failure_directory(directory)
                recorder.write(directory)

    return run


def tracked[**P, R](backend: str, *, zero: bool = False) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """One row per logical structured call (or embedding batch), including all explicit retries."""

    def decorate(fn: Callable[P, R]) -> Callable[P, R]:
        @wraps(fn)
        def call(*args: P.args, **kwargs: P.kwargs) -> R:
            self = args[0]
            recorder = current_recorder()
            client = getattr(self, "_client", None)
            canonical = canonical_endpoint(str(getattr(client, "base_url", getattr(self, "base_url", ""))))
            endpoint = "sha256:" + fingerprint(canonical) if canonical else ""
            row = CallRow(_stage.get(), backend, getattr(self, "model", getattr(self, "name", "unknown")), endpoint)
            if zero:
                row.input_tokens = row.output_tokens = row.reasoning_tokens = row.cached_tokens = 0
                row.attempts = 1
            token = _active.set(row)
            start = time.perf_counter()
            try:
                result = fn(*args, **kwargs)
                row.success = True
                return result
            except BaseException as error:
                row.error_type = type(error).__name__
                raise
            finally:
                row.latency_seconds = time.perf_counter() - start
                recorder.add(row, zero)
                _active.reset(token)

        return call

    return decorate


def attempt[R](call: Callable[[], R], *, input_estimate: int = 0, output_cap: int = 0, characters: int = 0) -> R:
    """Capture usage before response validation, so refused/truncated/invalid outputs still count."""
    row = _active.get()
    if row is None:
        return call()
    recorder = current_recorder()
    gate = recorder._gate if recorder.max_cost_usd is not None else threading.RLock()
    with gate:
        recorder.check(row, input_estimate, output_cap)
        row.attempts += 1
        row.characters += characters
        row.unknown_usage_attempts += 1
        response = call()
        payload = response[0] if isinstance(response, tuple) else response
        usage = _field(payload, "usage")
        if usage is not None:
            anthropic_input = _number(_field(usage, "input_tokens"))
            incoming = _number(_field(usage, "prompt_tokens"))
            outgoing = _number(_field(usage, "completion_tokens"))
            if anthropic_input is not None:
                # Anthropic's cache reads/writes are separate from input_tokens, unlike OpenAI's inclusive prompt count.
                incoming = (
                    anthropic_input
                    + (_number(_field(usage, "cache_read_input_tokens")) or 0)
                    + (_number(_field(usage, "cache_creation_input_tokens")) or 0)
                )
                outgoing = _number(_field(usage, "output_tokens"))
            reasoning = _number(_field(_field(usage, "completion_tokens_details"), "reasoning_tokens"))
            if reasoning is None:
                reasoning = _number(_field(usage, "reasoning_tokens"))
            cached = _number(_field(_field(usage, "prompt_tokens_details"), "cached_tokens"))
            if cached is None:
                cached = _number(_field(usage, "cached_tokens"))
            if cached is None:
                cached = _number(_field(usage, "cache_read_input_tokens"))
            if incoming is not None and (outgoing is not None or row.backend == "openai_compat_embed"):
                row.unknown_usage_attempts -= 1
            attempt_row = CallRow(
                row.stage,
                row.backend,
                row.model,
                row.endpoint,
                input_tokens=incoming or 0,
                output_tokens=outgoing,
                reasoning_tokens=reasoning,
                cached_tokens=cached,
            )
            cost = recorder.cost(attempt_row) or 0
            for name, value in (
                ("input_tokens", incoming),
                ("output_tokens", outgoing),
                ("reasoning_tokens", reasoning),
                ("cached_tokens", cached),
            ):
                if value is not None:
                    setattr(row, name, (getattr(row, name) or 0) + value)
            row.known_cost_usd += cost
            with recorder._lock:
                recorder.spent += cost
        reported = _field(payload, "total_cost_usd")
        if reported is None:
            reported = _field(payload, "cost_usd")
        if isinstance(reported, (int, float)) and not isinstance(reported, bool) and reported >= 0:
            row.reported_cost_usd = (row.reported_cost_usd or 0) + reported
        return response


def _retry_delay(error: Exception, retry: int, random_fn: Callable[[], float], now: Callable[[], float]) -> float:
    headers = getattr(getattr(error, "response", None), "headers", {})
    for name, scale in (("retry-after-ms", 0.001), ("retry-after", 1.0)):
        value = headers.get(name)
        if value is None:
            continue
        try:
            delay = float(value) * scale
        except (TypeError, ValueError):
            if name != "retry-after":
                continue
            try:
                date = parsedate_to_datetime(value)
                if date.tzinfo is None:
                    date = date.replace(tzinfo=UTC)
                delay = date.timestamp() - now()
            except (TypeError, ValueError, OverflowError):
                continue
        if math.isfinite(delay) and delay >= 0:
            return min(delay, 60.0)
    return min(0.5 * 2.0 ** min(retry, 4), 8.0) * (1.0 - 0.25 * random_fn())


def request[R](
    call: Callable[[], R],
    retries: int,
    *,
    input_estimate: int = 0,
    output_cap: int = 0,
    characters: int = 0,
    sleep: Callable[[float], None] | None = None,
    random_fn: Callable[[], float] | None = None,
    now: Callable[[], float] | None = None,
) -> R:
    """Count every wire attempt; honor capped server hints before jittered SDK-style backoff."""
    sleep = sleep if sleep is not None else time.sleep
    random_fn = random_fn if random_fn is not None else random.random
    now = now if now is not None else time.time
    for retry in range(retries + 1):
        try:
            return attempt(call, input_estimate=input_estimate, output_cap=output_cap, characters=characters)
        except Exception as error:
            status = getattr(error, "status_code", None)
            transient = type(error).__name__ in {"APIConnectionError", "APITimeoutError"} or (
                isinstance(status, int) and (status in {408, 409, 429} or status >= 500)
            )
            if retry == retries or not transient:
                raise
            sleep(_retry_delay(error, retry, random_fn, now))
    raise AssertionError("unreachable")
