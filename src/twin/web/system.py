"""System settings for administrators: one view of every service, and the few settings changed in the browser.

Three layers, each with one job. ``twin.toml`` says where each service is and which model it uses (read-only here,
changed with a restart). ``.env`` holds the keys: this view names each variable and says whether it is set, never
its value. ``data/system.json`` holds what an administrator changes here, effective at once: whether speech and
video are switched on, and the library's token quota. A service works when it is configured and switched on; a
switch nobody has touched follows the configuration, so upgrading changes nothing.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import threading
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from ..assets import AssetStore
from ..config import LLMSettings, Settings, egress_of
from ..util import private_directory
from .gpu import GpuMonitor, _origin, asr_url
from .library import Libraries

log = logging.getLogger(__name__)

Switch = Literal["tts", "video"]
SWITCHES: tuple[Switch, ...] = ("tts", "video")
MAX_HOURS = 24 * 30


class SwitchBody(BaseModel):
    enabled: bool


class QuotaBody(BaseModel):
    """Both empty: back to ``[library]`` in twin.toml."""

    batch_tokens: int | None = Field(default=None, ge=0)
    batch_hours: float | None = Field(default=None, gt=0, le=MAX_HOURS, allow_inf_nan=False)


class SystemSettings:
    """The administrator's runtime settings, kept in ``system.json`` beside the database."""

    def __init__(self, settings: Settings, path: Path | None = None) -> None:
        self.settings = settings
        self.path = path or settings.db_path.parent / "system.json"
        self._lock = threading.Lock()
        self._data = self._read()

    def _read(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text())
        except FileNotFoundError:
            return {}
        except (OSError, ValueError):
            log.warning("系统设置 %s 无法读取，按 twin.toml 的配置运行", self.path)
            return {}
        return data if isinstance(data, dict) else {}

    def _save(self) -> None:
        private_directory(self.path.parent)
        AssetStore.write(self.path, json.dumps(self._data, ensure_ascii=False, indent=2).encode())

    @staticmethod
    def _stamp(by: str | None) -> dict[str, Any]:
        return {"at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"), "by": by}

    # ------------------------------------------------------------ switches

    def missing(self, name: Switch) -> str | None:
        """What twin.toml lacks before the service can be switched on, or None when it is configured."""
        if name == "tts" and self.settings.tts.provider == "silent":
            return "twin.toml 里没有配置 [tts]"
        if name == "video" and self.settings.video.provider == "none":
            return "twin.toml 里没有配置 [video]"
        return None

    def enabled(self, name: Switch) -> bool:
        """Configured and switched on; an untouched switch is on."""
        if self.missing(name):
            return False
        with self._lock:
            stored = self._data.get("switches", {}).get(name, {})
        return bool(stored.get("enabled", True)) if isinstance(stored, dict) else True

    def off(self, name: Switch) -> bool:
        """Configured but switched off by an administrator: the service must not be used."""
        return self.missing(name) is None and not self.enabled(name)

    def switch(self, name: Switch, enabled: bool, by: str | None) -> None:
        if reason := self.missing(name):
            raise ValueError(f"{reason}，写好后重启一次才能开启")
        with self._lock:
            self._data.setdefault("switches", {})[name] = {"enabled": enabled, **self._stamp(by)}
            self._save()
        log.info("管理员 %s %s了%s", by or "本机", "开启" if enabled else "关闭", name)

    def switch_view(self, name: Switch) -> dict[str, Any]:
        with self._lock:
            stored = self._data.get("switches", {}).get(name, {})
        stored = stored if isinstance(stored, dict) else {}
        return {
            "configured": self.missing(name) is None,
            "enabled": self.enabled(name),
            "missing": self.missing(name),
            "changed_at": stored.get("at"),
            "changed_by": stored.get("by"),
        }

    # ------------------------------------------------------------ quota

    def limits(self) -> tuple[int, float]:
        """The library's token quota: tokens per window of hours."""
        with self._lock:
            quota = self._data.get("quota")
        library = self.settings.library
        if not isinstance(quota, dict):
            return library.batch_tokens, library.batch_hours
        return int(quota.get("batch_tokens", library.batch_tokens)), float(
            quota.get("batch_hours", library.batch_hours)
        )

    def set_quota(self, body: QuotaBody, by: str | None) -> None:
        with self._lock:
            if body.batch_tokens is None and body.batch_hours is None:
                self._data.pop("quota", None)
            else:
                library = self.settings.library
                self._data["quota"] = {
                    "batch_tokens": library.batch_tokens if body.batch_tokens is None else body.batch_tokens,
                    "batch_hours": library.batch_hours if body.batch_hours is None else body.batch_hours,
                    **self._stamp(by),
                }
            self._save()
        log.info("管理员 %s 把 token 上限改为 %s / %s 小时", by or "本机", *self.limits())

    def quota_custom(self) -> bool:
        with self._lock:
            return isinstance(self._data.get("quota"), dict)


# ---------------------------------------------------------------- read-only views of twin.toml and .env


def _address(url: str | None) -> str:
    origin = _origin(url)
    return origin.split("://", 1)[1] if origin else "—"


_PROVIDERS = {
    "openai_compat": "OpenAI 兼容",
    "hashing": "本机字面匹配（hashing）",
    "command": "命令",
    "cloudflare": "Cloudflare",
    "silent": "未配置",
    "remote": "远端命令",
    "none": "未配置",
    "anthropic": "Anthropic",
    "claude_cli": "Claude CLI",
}


def config_view(settings: Settings) -> dict[str, list[list[str]]]:
    """Each service's configuration as label/value rows: host and port only, no paths, commands or keys."""
    embed, asr, tts, video = settings.embed, settings.asr, settings.tts, settings.video
    rows: dict[str, list[list[str]]] = {
        "embed": [["接口", _PROVIDERS[embed.provider]]],
        "asr": [["接口", _PROVIDERS[asr.provider]]],
        "tts": [["接口", _PROVIDERS[tts.provider]]],
        "video": [["接口", _PROVIDERS[video.provider]]],
    }
    if embed.provider == "openai_compat":
        rows["embed"] += [
            ["地址", _address(embed.base_url)],
            ["模型", embed.model],
            ["每批 / 超时 / 重试", f"{embed.batch_size} · {embed.timeout:g} 秒 · {embed.max_retries} 次"],
        ]
    if asr.provider == "command":
        rows["asr"] += [["地址", _address(asr_url(settings)) if asr_url(settings) else "本机命令"]]
    else:
        rows["asr"] += [["地址", _address(asr.base_url)], ["模型", asr.model or "—"]]
    if tts.provider != "silent":
        rows["tts"] += [["地址", _address(tts.base_url)], ["模型", tts.model or "—"], ["预置音色", tts.voice]]
    if video.provider == "remote":
        rows["video"] += [["主机", video.host or "本机"], ["每条超时", f"{video.timeout_s:g} 秒"]]
    return rows


def _model(use: str, section: str, llm: LLMSettings) -> dict[str, Any]:
    egress = egress_of(llm)
    return {
        "use": use,
        "section": section,
        "provider": _PROVIDERS[llm.provider],
        "model": llm.model or "—",
        "address": _address(llm.base_url) if llm.base_url else (egress.host or "—"),
        "external": egress.external,
    }


def models_view(settings: Settings) -> list[dict[str, Any]]:
    found = [_model("整理记忆、校对转写", "[llm]", settings.llm)]
    if settings.chat_llm is not None:
        found.append(_model("聊天回答", "[chat_llm]", settings.chat_llm))
    return found


def keys_view(settings: Settings) -> list[dict[str, Any]]:
    """The key variables in use, and whether each is set in the server's environment (never the value)."""
    wanted: list[tuple[str, str]] = []
    if settings.llm.provider != "claude_cli":
        wanted.append((settings.llm.api_key_env, "文字模型"))
    if settings.chat_llm is not None and settings.chat_llm.provider != "claude_cli":
        wanted.append((settings.chat_llm.api_key_env, "聊天模型"))
    if settings.embed.provider == "openai_compat":
        wanted.append((settings.embed.api_key_env, "向量服务"))
    if settings.asr.provider != "command":
        wanted.append((settings.asr.api_key_env, "转写服务"))
    if settings.tts.provider != "silent":
        wanted.append((settings.tts.api_key_env, "朗读服务"))
    wanted.append((settings.api.token_env, "外部调用 /api"))
    seen: dict[str, dict[str, Any]] = {}
    for env, use in wanted:
        if env in seen:
            seen[env]["use"] += f"、{use}"
        else:
            seen[env] = {"env": env, "use": use, "set": bool(os.environ.get(env))}
    return list(seen.values())


def register(app: FastAPI, system: SystemSettings, monitor: GpuMonitor, libraries: Libraries) -> None:
    def admin(request: Request) -> str | None:
        identity = request.scope["twin_identity"]
        if not identity["admin"]:
            raise HTTPException(403, "仅管理员可以查看和修改系统设置")
        email = identity.get("email")
        return str(email) if email else None

    def view(request: Request) -> dict[str, Any]:
        library = system.settings.library
        return {
            **monitor.snapshot(),
            "switches": {name: system.switch_view(name) for name in SWITCHES},
            "config": config_view(system.settings),
            "models": models_view(system.settings),
            "keys": keys_view(system.settings),
            "quota": {
                **libraries.quota(libraries.owner(request)),
                "custom": system.quota_custom(),
                "default_limit": library.batch_tokens,
                "default_hours": library.batch_hours,
            },
        }

    @app.get("/api/admin/system")
    def get_system(request: Request, refresh: bool = False) -> dict[str, Any]:
        """Every service's state and its record of the last day, the switches, configuration, keys and quota;
        ``refresh`` checks the services now first."""
        admin(request)
        monitor.refresh(force=refresh)
        return view(request)

    @app.put("/api/admin/system/switches/{name}")
    def put_switch(name: str, body: SwitchBody, request: Request) -> dict[str, Any]:
        by = admin(request)
        if name not in SWITCHES:
            raise HTTPException(404, "没有这个开关")
        try:
            system.switch(name, body.enabled, by)
        except ValueError as e:
            raise HTTPException(409, str(e)) from None
        if body.enabled:
            monitor.refresh(force=True)
        return view(request)

    @app.put("/api/admin/system/quota")
    def put_quota(body: QuotaBody, request: Request) -> dict[str, Any]:
        # Proofreading and rebuilds waiting on the quota start again at the library's next status poll.
        system.set_quota(body, admin(request))
        return view(request)
