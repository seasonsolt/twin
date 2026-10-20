"""System settings for administrators: one view of every service, and the settings changed in the browser.

Three layers, each with one job. ``twin.toml`` says where each service is and which model it uses. ``.env`` holds
the keys: this view names each variable and says whether it is set, never its value; an administrator can replace
or remove one, written to the server's env file (owner-only) and used from the next request on. ``data/system.json``
holds what an administrator changes here, effective at once: whether speech and video are switched on, the
library's token quota, and the address and model name of the text, chat and embedding models, which then take the
place of twin.toml's. A service works when it is configured and switched on; a switch nobody has touched follows
the configuration, so upgrading changes nothing. Every change made here is appended to ``system-audit.jsonl``
beside it: who, when and what, never a key's value.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import re
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.types import ASGIApp, Receive, Scope, Send

from ..assets import AssetStore
from ..config import EmbedSettings, LLMSettings, Settings, egress_of
from ..ops.envfile import MAX_VALUE, selected_env_file, write_env_value
from ..usage import UsageLedger
from ..util import private_directory
from .gpu import GpuMonitor, _origin, asr_url
from .library import Libraries

log = logging.getLogger(__name__)

Switch = Literal["tts", "video"]
SWITCHES: tuple[Switch, ...] = ("tts", "video")
# The span of the token usage the view shows.
USAGE_HOURS = 24
MAX_HOURS = 24 * 30
# Pages an administrator may switch off for everyone. Chat is the twin itself and always stays.
Feature = Literal["work", "ledger"]
FEATURES: dict[Feature, str] = {"work": "工作", "ledger": "承诺账本"}
FEATURE_PATHS: dict[str, Feature] = {"/api/persona/work": "work", "/api/persona/ledger": "ledger"}
ModelSection = Literal["llm", "chat_llm", "embed"]
MODEL_SECTIONS: tuple[ModelSection, ...] = ("llm", "chat_llm", "embed")
MODEL_FIELDS = ("base_url", "model")
_BASE_URL = re.compile(r"https?://[A-Za-z0-9.\-\[\]:]+(/[^\s?#]*)?")


class SwitchBody(BaseModel):
    enabled: bool


class QuotaBody(BaseModel):
    """Both empty: back to ``[library]`` in twin.toml."""

    batch_tokens: int | None = Field(default=None, ge=0)
    batch_hours: float | None = Field(default=None, gt=0, le=MAX_HOURS, allow_inf_nan=False)


class ModelBody(BaseModel):
    """An empty field keeps twin.toml's value; both empty: back to twin.toml."""

    base_url: str | None = Field(default=None, max_length=500)
    model: str | None = Field(default=None, max_length=200)


class KeyBody(BaseModel):
    """Empty: remove the key from the env file."""

    value: str | None = Field(default=None, max_length=MAX_VALUE)


class SystemSettings:
    """The administrator's runtime settings, kept in ``system.json`` beside the database. Model overrides are
    written into ``settings``' own [llm] / [chat_llm] / [embed] objects, which every persona's copy of the settings
    shares, so all of them use the new address at once."""

    def __init__(self, settings: Settings, path: Path | None = None, env_file: Path | None = None) -> None:
        self.settings = settings
        self.path = path or settings.db_path.parent / "system.json"
        self.audit_path = self.path.with_name("system-audit.jsonl")
        self._env_file = env_file
        self._lock = threading.Lock()
        self._data = self._read()
        # What twin.toml says, to go back to when an override is removed.
        self._toml = {
            name: {field: getattr(section, field) for field in MODEL_FIELDS}
            for name in MODEL_SECTIONS
            if (section := self.section(name)) is not None
        }
        # Raised on every change of a model or key, so whatever caches a client built from them builds it again.
        self.generation = 0
        # Called with "llm" / "chat_llm" / "embed" / "keys" after a change.
        self.listeners: list[Callable[[str], None]] = []
        for name in MODEL_SECTIONS:
            self._apply(name)

    @property
    def env_file(self) -> Path:
        return self._env_file or selected_env_file()

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

    # ------------------------------------------------------------ features

    def feature_on(self, name: Feature) -> bool:
        """An untouched feature is on."""
        with self._lock:
            stored = self._data.get("features", {}).get(name, {})
        return bool(stored.get("enabled", True)) if isinstance(stored, dict) else True

    def features(self) -> dict[str, bool]:
        return {name: self.feature_on(name) for name in FEATURES}

    def set_feature(self, name: Feature, enabled: bool, by: str | None) -> None:
        with self._lock:
            self._data.setdefault("features", {})[name] = {"enabled": enabled, **self._stamp(by)}
            self._save()
        self._record(by, "feature", feature=name, enabled=enabled)

    def feature_view(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            stored = dict(self._data.get("features", {}))
        found: dict[str, dict[str, Any]] = {}
        for name, label in FEATURES.items():
            entry = stored.get(name)
            entry = entry if isinstance(entry, dict) else {}
            found[name] = {
                "label": label,
                "enabled": self.feature_on(name),
                "changed_at": entry.get("at"),
                "changed_by": entry.get("by"),
            }
        return found

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

    # ------------------------------------------------------------ models and keys

    def section(self, name: ModelSection) -> LLMSettings | EmbedSettings | None:
        return {"llm": self.settings.llm, "chat_llm": self.settings.chat_llm, "embed": self.settings.embed}[name]

    def model_locked(self, name: ModelSection) -> str | None:
        """Why this model's address and name cannot be changed here, or None when they can."""
        section = self.section(name)
        if section is None:
            return "twin.toml 里没有配置 [chat_llm]，聊天用整理记忆的模型"
        if section.provider != "openai_compat":
            return f"[{name}] 用的是{_PROVIDERS[section.provider]}，只能在 twin.toml 里修改"
        return None

    def model_override(self, name: ModelSection) -> dict[str, Any] | None:
        with self._lock:
            stored = self._data.get("models", {}).get(name)
        return stored if isinstance(stored, dict) else None

    def _apply(self, name: ModelSection) -> None:
        section, toml = self.section(name), self._toml.get(name)
        if section is None or toml is None or self.model_locked(name):
            return
        override = self.model_override(name) or {}
        for field in MODEL_FIELDS:
            value = override.get(field)
            setattr(section, field, value if isinstance(value, str) and value else toml[field])

    def set_model(self, name: str, body: ModelBody, by: str | None) -> None:
        if name not in MODEL_SECTIONS:
            raise LookupError("没有这个模型")
        if reason := self.model_locked(name):
            raise ValueError(reason)
        base_url = (body.base_url or "").strip().rstrip("/")
        model = (body.model or "").strip()
        if base_url and (not _BASE_URL.fullmatch(base_url) or "@" in base_url):
            raise ValueError("地址要以 http:// 或 https:// 开头，不带账号密码和查询参数，例如 http://127.0.0.1:8000/v1")
        if model and not model.isprintable():
            raise ValueError("模型名不能含换行等控制字符")
        before = {field: getattr(self.section(name), field) for field in MODEL_FIELDS}
        with self._lock:
            models = self._data.setdefault("models", {})
            if not base_url and not model:
                models.pop(name, None)
            else:
                models[name] = {"base_url": base_url or None, "model": model or None, **self._stamp(by)}
            self._save()
        self._apply(name)
        after = {field: getattr(self.section(name), field) for field in MODEL_FIELDS}
        self._changed(
            name,
            by,
            "model",
            section=f"[{name}]",
            address=[_address(before["base_url"]), _address(after["base_url"])],
            model=[before["model"], after["model"]],
        )

    def key_names(self) -> set[str]:
        return {key["env"] for key in keys_view(self.settings)}

    def set_key(self, env: str, value: str | None, by: str | None) -> None:
        """Write the key to the env file and the running process; never logged, stored elsewhere or sent back."""
        if env not in self.key_names():
            raise LookupError("没有这个密钥")
        value = (value or "").strip() or None
        write_env_value(self.env_file, env, value)
        if value is None:
            os.environ.pop(env, None)
        else:
            os.environ[env] = value
        self._changed("keys", by, "key", env=env, set=value is not None)

    def _changed(self, what: str, by: str | None, action: str, **detail: Any) -> None:
        self.generation += 1
        self._record(by, action, **detail)
        for listener in self.listeners:
            listener(what)

    def _record(self, by: str | None, action: str, **detail: Any) -> None:
        """Append the change to the audit log, without any key's value."""
        entry = {**self._stamp(by), "action": action, **detail}
        try:
            private_directory(self.audit_path.parent)
            fd = os.open(self.audit_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            with os.fdopen(fd, "a", encoding="utf-8") as audit:
                audit.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            log.warning("系统设置审计记录 %s 无法写入", self.audit_path)
        log.info("管理员 %s 修改了系统设置：%s", by or "本机", json.dumps(detail, ensure_ascii=False))

    def audit(self, limit: int = 20) -> list[dict[str, Any]]:
        """The latest changes, newest first."""
        try:
            lines = self.audit_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        found: list[dict[str, Any]] = []
        for line in reversed(lines):
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if isinstance(entry, dict):
                found.append(entry)
            if len(found) >= limit:
                break
        return found


class FeatureGate:
    """Refuses the API of a page an administrator switched off, for every twin and every caller."""

    def __init__(self, app: ASGIApp, system: SystemSettings) -> None:
        self.app, self.system = app, system

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            path = str(scope.get("path", ""))
            for prefix, name in FEATURE_PATHS.items():
                if (path == prefix or path.startswith(prefix + "/")) and not self.system.feature_on(name):
                    response = JSONResponse(
                        {"detail": f"管理员已关闭{FEATURES[name]}", "code": "feature_off"}, status_code=403
                    )
                    await response(scope, receive, send)
                    return
        await self.app(scope, receive, send)


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


def _model(use: str, section: str, llm: LLMSettings | EmbedSettings) -> dict[str, Any]:
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


def editable_models(system: SystemSettings) -> list[dict[str, Any]]:
    """Each model an administrator may point elsewhere: the full address for the edit field (an endpoint, not a
    secret; credentials in it are refused), whether twin.toml's value is overridden, and why not when it cannot be."""
    uses = {"llm": "整理记忆、校对转写", "chat_llm": "聊天回答", "embed": "检索向量"}
    found = []
    for name in MODEL_SECTIONS:
        section = system.section(name)
        override = system.model_override(name)
        found.append(
            {
                "name": name,
                "section": f"[{name}]",
                "use": uses[name],
                "base_url": section.base_url if section is not None else None,
                "model": section.model if section is not None else None,
                "locked": system.model_locked(name),
                "custom": override is not None,
                "changed_at": override.get("at") if override else None,
                "changed_by": override.get("by") if override else None,
            }
        )
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


def register(
    app: FastAPI, system: SystemSettings, monitor: GpuMonitor, libraries: Libraries, usage: UsageLedger | None = None
) -> None:
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
            "features": system.feature_view(),
            "config": config_view(system.settings),
            "models": models_view(system.settings),
            "editable_models": editable_models(system),
            "keys": keys_view(system.settings),
            "env_file": system.env_file.name,
            "audit": system.audit(),
            "quota": {
                **libraries.quota(libraries.owner(request)),
                "custom": system.quota_custom(),
                "default_limit": library.batch_tokens,
                "default_hours": library.batch_hours,
            },
            # Where the model tokens of the last day went, by use; empty when the process keeps no ledger.
            "usage": usage.since(USAGE_HOURS) if usage is not None else [],
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

    @app.put("/api/admin/system/models/{name}")
    def put_model(name: str, body: ModelBody, request: Request) -> dict[str, Any]:
        """Point a model elsewhere, used from the next request on; a new embedding model re-embeds the index, and
        retrieval ranks by keywords until it finishes."""
        by = admin(request)
        try:
            system.set_model(name, body, by)
        except LookupError as e:
            raise HTTPException(404, str(e)) from None
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        monitor.refresh(force=True)
        return view(request)

    @app.put("/api/admin/system/keys/{env}")
    def put_key(env: str, body: KeyBody, request: Request) -> dict[str, Any]:
        """Replace or remove a key. The response, like every other, says only whether it is set."""
        by = admin(request)
        try:
            system.set_key(env, body.value, by)
        except LookupError as e:
            raise HTTPException(404, str(e)) from None
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        except PermissionError as e:
            raise HTTPException(409, str(e)) from None
        except OSError:
            raise HTTPException(500, "密钥文件无法写入，请检查服务器上 env 文件所在目录的权限") from None
        return view(request)

    @app.put("/api/admin/system/features/{name}")
    def put_feature(name: str, body: SwitchBody, request: Request) -> dict[str, Any]:
        """Switch 工作 or 承诺账本 on or off for everyone at once; their data stays. Chat cannot be switched off."""
        by = admin(request)
        if name not in FEATURES:
            raise HTTPException(404, "没有这个功能；聊天不能关闭")
        system.set_feature(name, body.enabled, by)
        return view(request)
