"""LLM backends behind one structured-output interface.

Every pipeline step calls ``llm.structured(system=..., user=..., schema=Model)`` and gets a validated
pydantic instance back. Backends:

- ``AnthropicLLM``: official Anthropic SDK, structured outputs, server-side refusal fallback.
- ``OpenAICompatLLM``: any OpenAI-compatible endpoint (vLLM / SGLang private deployments, DeepSeek,
  Qwen DashScope, Kimi, GLM ...). Validates and retries once on schema violations.
- ``ClaudeCLILLM``: shells out to a logged-in ``claude`` CLI. Local development only.
- ``FakeLLM``: deterministic handler for tests.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable, Sequence
from typing import Any, Literal, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from .usage import attempt, request, tracked
from .util import key_from_env

T = TypeVar("T", bound=BaseModel)
Effort = Literal["low", "medium", "high", "xhigh", "max"]


class LLMError(RuntimeError):
    pass


class LLMRefusal(LLMError):
    def __init__(self, message: str, category: str | None = None) -> None:
        super().__init__(message)
        self.category = category


class LLMTruncated(LLMError):
    pass


class LLMInvalidOutput(LLMError):
    pass


def retry_truncated[R](call: Callable[[], R]) -> R:
    """Make ``call`` once more after an ``LLMTruncated``. Some models (gpt-oss) now and then run on until the output
    cap on input they normally answer well within it; callers whose loss is a whole chunk of evidence use this."""
    try:
        return call()
    except LLMTruncated:
        return call()


class LLM(Protocol):
    name: str

    def structured(
        self,
        *,
        system: str,
        user: str,
        schema: type[T],
        effort: Effort = "medium",
        max_tokens: int | None = None,
        reasoning_effort: str | None = None,
    ) -> T:
        """``max_tokens=None`` uses the backend's configured output budget."""
        ...


class CallTally:
    """Passes calls through to the LLM and counts how many succeeded and failed. The pipeline stages tolerate
    individual failed calls, so this is what tells a stage in which every call failed (service unreachable, key
    rejected, rate limited) apart from one that merely had nothing to do."""

    def __init__(self, llm: LLM) -> None:
        self.llm = llm
        self.name = llm.name
        self._lock = threading.Lock()
        self.succeeded = 0
        self.failed = 0
        self.last_error: Exception | None = None

    def structured(self, *, system: str, user: str, schema: type[T], **options: Any) -> T:
        try:
            result = self.llm.structured(system=system, user=user, schema=schema, **options)
        except Exception as e:
            with self._lock:
                self.failed += 1
                self.last_error = e
            raise
        with self._lock:
            self.succeeded += 1
        return result

    def start_stage(self) -> None:
        with self._lock:
            self.succeeded = self.failed = 0
            self.last_error = None

    def require_working_calls(self, stage: str) -> None:
        if self.failed and not self.succeeded:
            error = self.last_error
            detail = str(error).rstrip("。.")
            raise LLMError(
                f"{stage}阶段的 {self.failed} 次模型调用全部失败，最后一次错误：{type(error).__name__}: {detail}。"
                "请检查模型服务地址、密钥、网络和限流情况，各次失败见上方以 FAILED 开头的行"
            )


def inline_schema(schema: type[BaseModel]) -> dict[str, Any]:
    """JSON schema with $refs inlined and closed objects, accepted by strict json-schema decoders."""
    raw = schema.model_json_schema()
    defs: dict[str, Any] = raw.pop("$defs", {})

    def resolve(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                return resolve(defs[node["$ref"].rsplit("/", 1)[-1]])
            out: dict[str, Any] = {}
            for k, v in node.items():
                if k in ("title", "default"):
                    continue
                if k == "properties":
                    out[k] = {name: resolve(sub) for name, sub in v.items()}
                else:
                    out[k] = resolve(v)
            if out.get("type") == "object" and "properties" in out:
                out["additionalProperties"] = False
                out["required"] = list(out["properties"].keys())
            return out
        if isinstance(node, list):
            return [resolve(v) for v in node]
        return node

    result: dict[str, Any] = resolve(raw)
    return result


def _schema_instruction(schema: type[BaseModel]) -> str:
    return (
        "\n\n只输出一个 JSON 对象，不要输出任何其他文字或 Markdown 代码块。JSON 必须符合下面的 JSON Schema：\n"
        + json.dumps(inline_schema(schema), ensure_ascii=False)
    )


_LEADING_THINK = re.compile(r"^\s*<think>.*?</think>", re.DOTALL)
_FENCED = re.compile(r"```[A-Za-z]*[ \t]*\n?(.*?)```", re.DOTALL)


def _parses(text: str) -> bool:
    try:
        json.loads(text)
    except json.JSONDecodeError:
        return False
    return True


def _extract_json(text: str) -> str:
    """The JSON object in a model reply, without a leading ``<think>`` block, Markdown fences or surrounding prose.
    Returns the cleaned text unchanged when no JSON is found, so schema validation reports the problem."""
    s = _LEADING_THINK.sub("", text, count=1).strip()
    for candidate in (s, *(m.group(1).strip() for m in _FENCED.finditer(s))):
        if _parses(candidate):
            return candidate
    decoder = json.JSONDecoder()
    for start in (i for i, ch in enumerate(s) if ch == "{"):
        try:
            _, end = decoder.raw_decode(s, start)
        except json.JSONDecodeError:
            continue
        return s[start:end]
    return s


def _answer_text(content: list[Any]) -> str:
    """Text of the model that produced the answer. Structured-output requests carry no prefill claim, so after a
    mid-stream fallback the fallback model restarts the answer; the declined model's partial text stays in front of
    the fallback block and must not be joined to it."""
    start = max((i + 1 for i, block in enumerate(content) if block.type == "fallback"), default=0)
    return "".join(getattr(block, "text", "") for block in content[start:] if block.type == "text")


class AnthropicLLM:
    FALLBACK_BETA = "server-side-fallback-2026-07-01"
    DEFAULT_MAX_TOKENS = 64000
    MAX_OUTPUT_TOKENS = 128000

    def __init__(
        self, model: str = "claude-opus-5-5", client: Any | None = None, max_tokens: int | None = None
    ) -> None:
        import anthropic

        self.model = model
        self.name = f"anthropic:{model}"
        self.max_tokens = self.DEFAULT_MAX_TOKENS if max_tokens is None else max_tokens
        if client is None:
            client = anthropic.Anthropic(max_retries=0)
            # The SDK accepts missing credentials and only fails at the first request, deep inside a pipeline stage.
            if not (client.api_key or client.auth_token or getattr(client, "credentials", None) is not None):
                raise LLMError("没有找到 Anthropic 凭据，请设置环境变量 ANTHROPIC_API_KEY")
        if client is not None and callable(getattr(client, "with_options", None)):
            client = client.with_options(max_retries=0)
        self._client = client

    def _stream(self, system: str, user: str, schema: type[BaseModel], effort: Effort, max_tokens: int) -> Any:
        return request(
            lambda: self._stream_once(system, user, schema, effort, max_tokens),
            2,
            input_estimate=len((system + user + json.dumps(inline_schema(schema))).encode()),
            output_cap=max_tokens,
        )

    def _stream_once(self, system: str, user: str, schema: type[BaseModel], effort: Effort, max_tokens: int) -> Any:
        # Not ``output_format=schema``: the SDK would then validate each text block at content_block_stop, so a
        # truncated, refused or mid-stream-fallback partial raises pydantic.ValidationError before stop_reason
        # can be inspected. The wire request is identical.
        from anthropic import transform_schema

        with self._client.beta.messages.stream(
            model=self.model,
            max_tokens=max_tokens,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user}],
            output_config={"effort": effort, "format": {"type": "json_schema", "schema": transform_schema(schema)}},
            betas=[self.FALLBACK_BETA],
            fallbacks="default",
        ) as stream:
            return stream.get_final_message()

    @tracked("anthropic")
    def structured(
        self,
        *,
        system: str,
        user: str,
        schema: type[T],
        effort: Effort = "medium",
        max_tokens: int | None = None,
        reasoning_effort: str | None = None,
    ) -> T:
        import anthropic

        budget = self.max_tokens if max_tokens is None else max_tokens
        try:
            message = self._stream(system, user, schema, effort, budget)
            # Thinking shares the output budget and cannot be turned off; retry once with more room rather than lower
            # effort, so compared answers keep the configured effort.
            if message.stop_reason == "max_tokens" and budget < self.MAX_OUTPUT_TOKENS:
                retry_budget = min(2 * budget, self.MAX_OUTPUT_TOKENS)
                try:
                    message = self._stream(system, user, schema, effort, retry_budget)
                except anthropic.BadRequestError as e:
                    raise LLMTruncated(
                        f"{self.name} hit max_tokens={budget}; retry with max_tokens={retry_budget} was rejected: {e}"
                    ) from e
                budget = retry_budget
        except anthropic.AnthropicError as e:
            raise LLMError(f"{self.name}: {type(e).__name__}: {e}") from e

        if message.stop_reason == "refusal":
            details = getattr(message, "stop_details", None)
            category = getattr(details, "category", None)
            raise LLMRefusal(f"{self.name} refused: {category}", category=str(category) if category else None)
        if message.stop_reason == "max_tokens":
            raise LLMTruncated(f"{self.name} hit max_tokens={budget}")
        parsed = message.parsed_output
        if isinstance(parsed, schema):
            return parsed
        try:
            return schema.model_validate_json(_extract_json(_answer_text(message.content)))
        except ValidationError as e:
            raise LLMInvalidOutput(f"{self.name}: {e}") from e


class OpenAICompatLLM:
    DEFAULT_MAX_TOKENS = 8192

    def __init__(
        self,
        model: str,
        base_url: str | None = None,
        api_key_env: str = "OPENAI_API_KEY",
        json_mode: Literal["json_schema", "json_object", "none"] = "json_object",
        client: Any | None = None,
        max_tokens: int | None = None,
        timeout: float = 600.0,
        max_retries: int = 2,
        reasoning_effort: Literal["none", "minimal", "low", "medium", "high", "xhigh"] | None = None,
        extra_body: dict[str, Any] | None = None,
    ) -> None:
        import openai

        key_from_env(api_key_env)
        self.model = model
        self.name = f"openai_compat:{model}"
        self.json_mode = json_mode
        self.reasoning_effort = reasoning_effort
        self.extra_body = extra_body or {}
        self.max_retries = max_retries
        self.max_tokens = self.DEFAULT_MAX_TOKENS if max_tokens is None else max_tokens
        if client is not None and callable(getattr(client, "with_options", None)):
            client = client.with_options(max_retries=0)
        self._client = client or openai.OpenAI(
            base_url=base_url,
            api_key=key_from_env(api_key_env) or "EMPTY",
            timeout=timeout,
            max_retries=0,
        )
        self.base_url = str(getattr(self._client, "base_url", base_url or os.environ.get("OPENAI_BASE_URL", "")))

    def _response_format(self, schema: type[BaseModel]) -> dict[str, Any] | None:
        if self.json_mode == "json_schema":
            return {
                "type": "json_schema",
                "json_schema": {"name": schema.__name__, "schema": inline_schema(schema), "strict": True},
            }
        if self.json_mode == "json_object":
            return {"type": "json_object"}
        return None

    def _complete(self, messages: list[Any], kwargs: dict[str, Any]) -> Any:
        import openai

        try:
            resp = request(
                lambda: self._client.chat.completions.create(messages=messages, **kwargs),
                self.max_retries,
                input_estimate=len(json.dumps(messages, ensure_ascii=False).encode()),
                output_cap=kwargs["max_tokens"],
            )
        except openai.BadRequestError as e:
            raise LLMError(
                f"{self.name} rejected the request (HTTP 400): {e.message}。"
                "如果是输入加 max_tokens 超过了服务端的上下文长度或输出上限：调小 [llm] max_tokens 或 "
                "减少单次输入资料，或调大推理服务的 --max-model-len"
            ) from e
        except openai.APIError as e:
            raise LLMError(f"{self.name}: {type(e).__name__}: {e}") from e
        if not resp.choices:
            raise LLMError(f"{self.name}: response has no choices")
        return resp.choices[0]

    @tracked("openai_compat")
    def structured(
        self,
        *,
        system: str,
        user: str,
        schema: type[T],
        effort: Effort = "medium",
        max_tokens: int | None = None,
        reasoning_effort: str | None = None,
    ) -> T:
        budget = self.max_tokens if max_tokens is None else max_tokens
        messages: list[Any] = [
            {"role": "system", "content": system + _schema_instruction(schema)},
            {"role": "user", "content": user},
        ]
        kwargs: dict[str, Any] = {"model": self.model, "max_tokens": budget}
        if self.extra_body:
            kwargs["extra_body"] = self.extra_body
        effective_effort = self.reasoning_effort if reasoning_effort is None else reasoning_effort
        if effective_effort is not None:
            kwargs["reasoning_effort"] = effective_effort
        response_format = self._response_format(schema)
        if response_format is not None:
            kwargs["response_format"] = response_format

        last_error: Exception | None = None
        for _ in range(2):
            choice = self._complete(messages, kwargs)
            if choice.finish_reason == "length":
                raise LLMTruncated(f"{self.name} hit max_tokens={budget}")
            refusal = getattr(choice.message, "refusal", None)
            if choice.finish_reason == "content_filter" or refusal:
                raise LLMRefusal(
                    f"{self.name} refused: {refusal or choice.finish_reason}",
                    category="content_filter" if choice.finish_reason == "content_filter" else "refusal",
                )
            content = choice.message.content or ""
            try:
                return schema.model_validate_json(_extract_json(content))
            except ValidationError as e:
                last_error = e
                messages.append({"role": "assistant", "content": content})
                messages.append(
                    {"role": "user", "content": f"上面的输出不符合 schema：{e}\n请只输出修正后的完整 JSON。"}
                )
        raise LLMInvalidOutput(f"{self.name}: {last_error}")


class _TransientCLIError(LLMError):
    """The CLI reported an API-side failure (``terminal_reason: api_error``: overload, rate limit, a login refresh
    racing with another process) that is worth retrying."""


class ClaudeCLILLM:
    """Development backend using a locally logged-in Claude Code CLI (``claude -p``).

    Calls that fail with ``terminal_reason: api_error`` are retried after each of ``retry_delays`` seconds; other
    failures (bad options, refusals, invalid output, timeouts) are raised at once."""

    def __init__(
        self,
        model: str = "claude-opus-5-5",
        binary: str = "claude",
        timeout: float = 900,
        retry_delays: Sequence[float] = (5.0, 20.0, 60.0),
    ) -> None:
        if shutil.which(binary) is None:
            raise LLMError(f"找不到可执行文件 {binary}，需要本机已安装并登录 Claude Code")
        self.model = model
        self.binary = binary
        self.timeout = timeout
        self.retry_delays = tuple(retry_delays)
        self.name = f"claude_cli:{model}"
        self._workdir = tempfile.mkdtemp(prefix="twin-cli-")
        self._sleep: Callable[[float], None] = time.sleep

    @tracked("claude_cli")
    def structured(
        self,
        *,
        system: str,
        user: str,
        schema: type[T],
        effort: Effort = "medium",
        max_tokens: int | None = None,
        reasoning_effort: str | None = None,
    ) -> T:
        cmd = [
            self.binary,
            "-p",
            "--output-format",
            "json",
            "--tools",
            "",
            "--no-session-persistence",
            "--strict-mcp-config",
            "--setting-sources",
            "",
            "--model",
            self.model,
            "--effort",
            effort,
            "--system-prompt",
            system,
            "--json-schema",
            json.dumps(inline_schema(schema), ensure_ascii=False),
        ]
        for delay in (*self.retry_delays, None):
            try:
                return self._call(cmd, user, schema)
            except _TransientCLIError:
                if delay is None:
                    raise
                self._sleep(delay)
        raise AssertionError("unreachable")

    def _call(self, cmd: list[str], user: str, schema: type[T]) -> T:
        try:
            payload, proc = attempt(
                lambda: self._invoke(cmd, user),
                input_estimate=len(user.encode()),
            )
        except subprocess.TimeoutExpired as e:
            raise LLMError(f"{self.name} timed out after {self.timeout:g}s") from e
        error = (
            _TransientCLIError
            if isinstance(payload, dict) and payload.get("terminal_reason") == "api_error"
            else LLMError
        )
        if proc.returncode != 0:
            raise error(f"{self.name} exited {proc.returncode}: {proc.stderr[-2000:] or proc.stdout[-2000:]}")
        if not isinstance(payload, dict):
            raise LLMInvalidOutput(f"{self.name}: non-JSON CLI output: {proc.stdout[-500:]}")
        if payload.get("is_error"):
            raise error(f"{self.name}: {payload.get('result') or payload.get('subtype')}")
        if payload.get("stop_reason") == "refusal":
            raise LLMRefusal(f"{self.name} refused")
        data = payload.get("structured_output")
        try:
            if data is not None:
                return schema.model_validate(data)
            return schema.model_validate_json(_extract_json(str(payload.get("result", ""))))
        except ValidationError as e:
            raise LLMInvalidOutput(f"{self.name}: {e}") from e

    def _invoke(self, cmd: list[str], user: str) -> tuple[Any, subprocess.CompletedProcess[str]]:
        proc = subprocess.run(cmd, input=user, capture_output=True, text=True, timeout=self.timeout, cwd=self._workdir)
        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError:
            payload = None
        return payload, proc


class FakeLLM:
    """Test double. ``handler(system, user, schema)`` returns an instance or a plain dict."""

    def __init__(self, handler: Callable[[str, str, type[BaseModel]], BaseModel | dict[str, Any]]) -> None:
        self.name = "fake"
        self.handler = handler
        self.calls: list[tuple[str, str, str]] = []

    @tracked("fake", zero=True)
    def structured(
        self,
        *,
        system: str,
        user: str,
        schema: type[T],
        effort: Effort = "medium",
        max_tokens: int | None = None,
        reasoning_effort: str | None = None,
    ) -> T:
        self.calls.append((schema.__name__, system, user))
        out = self.handler(system, user, schema)
        if isinstance(out, schema):
            return out
        if isinstance(out, BaseModel):
            out = out.model_dump()
        return schema.model_validate(out)
