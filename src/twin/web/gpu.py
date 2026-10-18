"""Health of the GPU services (transcription, text embeddings, speech) that twin reaches over the GPU machine's tunnel.

The server checks them every minute and keeps the results of the last day in memory, so an administrator away from
the office network can see in the browser whether they answer now and whether they stayed up. Only the host and port
of each service are shown; paths, credentials and keys never leave the server. A service the administrator switched
off is not checked.
"""

from __future__ import annotations

import os
import shlex
import threading
import time
from collections import deque
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

import httpx

from ..config import Settings

TIMEOUT = 3.0
INTERVAL = 60.0
WINDOW = 24 * 3600
BUCKETS = 24
# remote.py's own default when the command gives no --url.
ASR_REMOTE_DEFAULT = "http://127.0.0.1:18790"
PROBE_TEXT = "健康检查"


@dataclass(frozen=True)
class Target:
    key: str
    name: str
    # http(s)://host:port, without a path, credentials or query.
    origin: str
    health_url: str
    # For the embedding service: its embeddings endpoint and model, asked for one real vector.
    embeddings_url: str | None = None
    model: str | None = None
    # Asked when the service has no health endpoint (404): an OpenAI-compatible model list.
    models_url: str | None = None
    # The key's variable name; its value goes with every request to the service.
    api_key_env: str | None = None


@dataclass
class Check:
    at: float
    ok: bool
    latency_ms: int | None = None
    reason: str | None = None
    version: str | None = None
    device: str | None = None
    busy: bool | None = None
    model: str | None = None
    embeddings_ms: int | None = None

    def view(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class History:
    target: Target
    checks: deque[Check] = field(default_factory=deque)


def _origin(url: str | None) -> str | None:
    """``scheme://host:port`` of an http(s) URL, or None for anything else."""
    if not url:
        return None
    try:
        parts = urlsplit(url.strip())
        port = parts.port
    except ValueError:
        return None
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        return None
    host = f"[{parts.hostname}]" if ":" in parts.hostname else parts.hostname
    return f"{parts.scheme}://{host}" + (f":{port}" if port else "")


def asr_url(settings: Settings) -> str | None:
    """The transcription service's address: ``--url`` of the ``[asr]`` command (the remote client), its default when
    the command runs remote.py without one, or None when transcription does not go through such a service."""
    s = settings.asr
    if s.provider != "command" or not s.command:
        return None
    try:
        words = shlex.split(s.command)
    except ValueError:
        return None
    for k, word in enumerate(words):
        if word == "--url" and k + 1 < len(words):
            return words[k + 1]
        if word.startswith("--url="):
            return word.removeprefix("--url=")
    if any(word.endswith("remote.py") for word in words):
        return os.environ.get("TWIN_ASR_REMOTE_URL") or ASR_REMOTE_DEFAULT
    return None


def _beside(base_url: str, name: str) -> str:
    """``name`` beside an OpenAI-compatible base URL, which ends in /v1."""
    return base_url.rstrip("/").removesuffix("/v1") + "/" + name


def targets(settings: Settings) -> list[Target]:
    found: list[Target] = []
    if origin := _origin(asr_url(settings)):
        found.append(Target("asr", "转写服务", origin, origin + "/health"))
    embed = settings.embed
    if embed.provider == "openai_compat" and (origin := _origin(embed.base_url)):
        assert embed.base_url is not None
        found.append(
            Target(
                "embed",
                "文本向量服务",
                origin,
                _beside(embed.base_url, "health"),
                embeddings_url=embed.base_url.rstrip("/") + "/embeddings",
                model=embed.model,
                api_key_env=embed.api_key_env,
            )
        )
    tts = settings.tts
    if tts.provider == "openai_compat" and (origin := _origin(tts.base_url)):
        assert tts.base_url is not None
        found.append(
            Target(
                "tts",
                "朗读服务",
                origin,
                # The speech server in deploy/tts-moss answers /healthz.
                _beside(tts.base_url, "healthz"),
                models_url=tts.base_url.rstrip("/") + "/models",
                api_key_env=tts.api_key_env,
            )
        )
    return found


def _failure(error: Exception) -> str:
    """Why a request failed, in words an administrator can act on."""
    if isinstance(error, httpx.TimeoutException):
        return f"响应超时（超过 {TIMEOUT:g} 秒），服务可能卡住或显卡繁忙"
    if isinstance(error, httpx.ConnectError):
        return "隧道未连接或服务未启动（连接被拒绝）"
    if isinstance(error, (httpx.RemoteProtocolError, httpx.ReadError)):
        # The reverse tunnel accepts the connection on this side and drops it when nothing listens on the GPU machine.
        return "隧道已连接，但 GPU 机器上的服务没有响应"
    if isinstance(error, httpx.HTTPStatusError):
        return f"服务返回错误（HTTP {error.response.status_code}）"
    return "无法访问服务"


def _text(value: Any) -> str | None:
    return str(value)[:80] if isinstance(value, (str, int, float)) and not isinstance(value, bool) else None


class GpuMonitor:
    """Checks the configured GPU services and remembers the results of the last ``window`` seconds."""

    def __init__(
        self,
        settings: Settings,
        *,
        interval: float = INTERVAL,
        window: float = WINDOW,
        timeout: float = TIMEOUT,
        clock: Callable[[], float] = time.time,
        active: Callable[[str], bool] = lambda key: True,
    ) -> None:
        self.interval, self.window, self.timeout, self.clock = interval, window, timeout, clock
        # Whether the service with this key is switched on; a switched-off one is not checked.
        self.active = active
        self.histories = [History(target) for target in targets(settings)]
        self.started_at = clock()
        self._lock = threading.Lock()
        self._checking = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------ checking

    def _probe(self, target: Target) -> Check:
        at = self.clock()
        started = time.perf_counter()
        check = Check(at=at, ok=False)
        headers = {}
        key = os.environ.get(target.api_key_env or "")
        if key:
            headers["Authorization"] = f"Bearer {key}"
        with httpx.Client(timeout=self.timeout, trust_env=False, follow_redirects=False, headers=headers) as client:
            try:
                response = client.get(target.health_url)
                check.latency_ms = round((time.perf_counter() - started) * 1000)
                response.raise_for_status()
                health = response.json()
                if not isinstance(health, dict):
                    raise ValueError
            except httpx.HTTPStatusError as e:
                # A server without a health endpoint (Ollama, a plain speech server) still counts if embeddings
                # work or it lists its models.
                if e.response.status_code != 404 or not (target.embeddings_url or target.models_url):
                    check.reason = _failure(e)
                    return check
                if target.models_url:
                    try:
                        client.get(target.models_url).raise_for_status()
                    except httpx.HTTPError as error:
                        check.reason = _failure(error)
                        return check
                health = {}
            except httpx.HTTPError as e:
                check.reason = _failure(e)
                return check
            except ValueError:
                check.reason = "服务返回的内容无法识别"
                return check
            check.version = _text(health.get("version"))
            check.device = _text(health.get("device"))
            check.model = _text(health.get("model"))
            if isinstance(health.get("busy"), bool):
                check.busy = health["busy"]
            if health.get("ok") is False:
                check.reason = "服务自检未通过"
                return check
            if target.embeddings_url:
                check.reason = self._embed(client, target, check)
                if check.reason:
                    return check
        check.ok = True
        return check

    def _embed(self, client: httpx.Client, target: Target, check: Check) -> str | None:
        """One tiny embeddings request, so a healthy-looking server that cannot embed is caught."""
        assert target.embeddings_url is not None
        started = time.perf_counter()
        try:
            response = client.post(target.embeddings_url, json={"model": target.model, "input": [PROBE_TEXT]})
            check.embeddings_ms = round((time.perf_counter() - started) * 1000)
            response.raise_for_status()
            vector = response.json()["data"][0]["embedding"]
        except httpx.HTTPError as e:
            return "向量接口调用失败：" + _failure(e)
        except (ValueError, KeyError, IndexError, TypeError):
            return "向量接口返回的内容无法识别"
        if not isinstance(vector, list) or not vector:
            return "向量接口返回了空向量"
        return None

    def retarget(self, settings: Settings) -> None:
        """After an administrator changed a service's address or model: check the services as configured now,
        keeping the record of each one that did not change."""
        with self._lock:
            kept = {h.target: h for h in self.histories}
            self.histories = [kept.get(target) or History(target) for target in targets(settings)]

    def _active(self) -> list[History]:
        return [h for h in self.histories if self.active(h.target.key)]

    def check(self) -> None:
        """Check every switched-on service at once and record the results."""
        histories = self._active()
        if not histories:
            return
        with self._checking, ThreadPoolExecutor(len(histories)) as pool:
            results = list(pool.map(lambda h: self._probe(h.target), histories))
        with self._lock:
            for history, result in zip(histories, results, strict=True):
                history.checks.append(result)
                while history.checks and history.checks[0].at < result.at - self.window:
                    history.checks.popleft()

    def fresh(self, age: float) -> bool:
        histories = self._active()
        with self._lock:
            return all(h.checks and h.checks[-1].at >= self.clock() - age for h in histories)

    def refresh(self, force: bool = False) -> None:
        """Check now when the record is older than two rounds, or when ``force``d and older than five seconds (so
        repeated clicks do not pile up)."""
        if self.histories and (not self.fresh(self.interval * 2) or (force and not self.fresh(5))):
            self.check()

    # ------------------------------------------------------------ reporting

    def snapshot(self) -> dict[str, Any]:
        now = self.clock()
        with self._lock:
            services = [self._view(h, now) for h in self.histories]
        return {"now": now, "interval": self.interval, "window": self.window, "services": services}

    def _view(self, history: History, now: float) -> dict[str, Any]:
        checks = [c for c in history.checks if c.at >= now - self.window]
        latest = checks[-1] if checks else None
        failures = [c for c in checks if not c.ok]
        # Since when the service has been in its current state, as far as the window reaches.
        since = None
        for c in reversed(checks):
            if c.ok != (latest.ok if latest else True):
                break
            since = c.at
        size = self.window / BUCKETS
        buckets = [{"start": now - self.window + k * size, "checks": 0, "failures": 0} for k in range(BUCKETS)]
        for c in checks:
            bucket = buckets[min(BUCKETS - 1, max(0, int((c.at - (now - self.window)) // size)))]
            bucket["checks"] += 1
            bucket["failures"] += not c.ok
        target = history.target
        return {
            "key": target.key,
            "name": target.name,
            "enabled": self.active(target.key),
            "address": target.origin.split("://", 1)[1],
            "latest": latest.view() if latest else None,
            "since": since,
            "checks": len(checks),
            "failures": len(failures),
            "availability": (len(checks) - len(failures)) / len(checks) if checks else None,
            "first_at": checks[0].at if checks else None,
            "last_failure": {"at": failures[-1].at, "reason": failures[-1].reason} if failures else None,
            "buckets": buckets,
        }

    # ------------------------------------------------------------ background

    def start(self) -> None:
        if not self.histories or self._thread:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="twin-gpu-monitor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(self.timeout * 2 + 1)
            self._thread = None

    def _run(self) -> None:
        while not self._stop.is_set():
            # A failed round must not end the monitor.
            with suppress(Exception):
                self.check()
            self._stop.wait(self.interval)
