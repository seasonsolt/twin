"""Configuration setup for the repository quickstart: ask for what is missing, never echo secrets."""

from __future__ import annotations

import getpass
import json
import os
import re
import sys
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlsplit

from ..config import load_settings
from .envfile import load_env_file, selected_env_file

CONFIG = Path("twin.toml")


def set_llm_value(text: str, name: str, value: str) -> str:
    """Set `name` inside [llm], replacing an existing or commented-out line, else appending to the section."""
    line = f"{name} = {json.dumps(value, ensure_ascii=False)}"
    lines = text.splitlines()
    start = next((i for i, raw in enumerate(lines) if raw.strip() == "[llm]"), None)
    if start is None:
        return text.rstrip("\n") + f"\n\n[llm]\n{line}\n"
    end = next((i for i in range(start + 1, len(lines)) if re.match(r"\s*#?\s*\[", lines[i])), len(lines))
    pattern = re.compile(rf"\s*#?\s*{name}\s*=")
    target = next((i for i in range(start + 1, end) if pattern.match(lines[i])), None)
    if target is None:
        lines.insert(start + 1, line)
    else:
        lines[target] = line
    return "\n".join(lines) + "\n"


def set_env_value(path: Path, name: str, value: str) -> None:
    if '"' in value or "\n" in value:
        raise ValueError("密钥不能包含双引号或换行")
    entry = f'{name}="{value}"'
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    pattern = re.compile(rf"\s*{name}\s*=")
    lines = [entry if pattern.match(raw) else raw for raw in lines]
    if entry not in lines:
        lines.append(entry)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    path.chmod(0o600)


def _ask(prompt: str, read: Callable[[str], str], *, default: str = "", check: Callable[[str], bool] = bool) -> str:
    suffix = f"（回车使用 {default}）" if default else ""
    while True:
        value = read(f"{prompt}{suffix}：").strip() or default
        if value and check(value):
            return value
        print("  输入无效，请重新输入。")


def _is_url(value: str) -> bool:
    parts = urlsplit(value)
    return parts.scheme in {"http", "https"} and bool(parts.hostname)


def check_local_config(
    *,
    interactive: bool | None = None,
    read: Callable[[str], str] = input,
    read_secret: Callable[[str], str] = getpass.getpass,
    set_model: str = "",
    set_base_url: str = "",
) -> int:
    """Return 0 when text chat is configured; on a terminal, ask for missing values and save them first.

    `set_model` / `set_base_url` write non-secret settings without prompting, so agents can configure the repo.
    """
    if interactive is None:
        interactive = sys.stdin.isatty()
    env = selected_env_file()
    try:
        load_env_file(env)
        settings = load_settings(CONFIG)
    except (ValueError, OSError):
        print("配置读取失败：请检查 twin.toml 的 TOML 格式及 .env 格式/权限；运行 twin doctor 查看详情。")
        return 1
    if set_base_url and not _is_url(set_base_url):
        print("--base-url 需要 http(s):// 开头的完整地址。")
        return 1
    if set_model or set_base_url:
        text = CONFIG.read_text(encoding="utf-8")
        for name, value in (("model", set_model.strip()), ("base_url", set_base_url.strip())):
            if value:
                text = set_llm_value(text, name, value)
        CONFIG.write_text(text, encoding="utf-8")
        settings = load_settings(CONFIG)
    llm = settings.llm
    model = (llm.model or "").strip()
    base_url = (llm.base_url or "").strip()
    key_name = llm.api_key_env
    key_missing = not os.environ.get(key_name, "").strip()
    if not (model and base_url) or key_missing:
        if not interactive:
            missing = [name for name, value in (("model", model), ("base_url", base_url)) if not value]
            print("尚未配置文字聊天模型，服务未启动。在终端里运行 ./scripts/local-up.sh 会逐项询问；或者：")
            if missing:
                print(f"  补齐 {'、'.join(missing)}：./scripts/local-up.sh --base-url URL --model NAME")
            if key_missing:
                print(f"  在 {env} 填写 {key_name}=密钥（本地服务无需密钥可填 none；chmod 600）。")
            return 1
        print("配置文字聊天模型（OpenAI 兼容接口），只需填写一次：")
        try:
            text = CONFIG.read_text(encoding="utf-8")
            if not base_url:
                base_url = _ask(
                    "  服务地址 base_url，例如 https://api.openai.com/v1 或 http://127.0.0.1:8000/v1",
                    read,
                    check=_is_url,
                )
                text = set_llm_value(text, "base_url", base_url)
            if not model:
                model = _ask("  模型名 model", read)
                text = set_llm_value(text, "model", model)
            if key_missing:
                key = _ask(f"  密钥 {key_name}（输入不显示；本地服务无需密钥可填 none）", read_secret)
                if '"' in key:
                    print("  密钥不能包含双引号，请手动写入 .env。")
                    return 1
                set_env_value(env, key_name, key)
                os.environ[key_name] = key
                print(f"  已保存到 {env}（仅本人可读）。")
            CONFIG.write_text(text, encoding="utf-8")
            settings = load_settings(CONFIG)
        except (EOFError, KeyboardInterrupt):
            print("\n已取消，未启动服务。")
            return 1
        except (ValueError, OSError):
            print("写入配置失败：请检查 twin.toml / .env 后重试（详情已隐藏）。")
            return 1
        print(f"  已写入 ./twin.toml：model = {model}，base_url = {base_url}")
    data = settings.db_path.parent
    data.mkdir(parents=True, exist_ok=True, mode=0o700)
    data.chmod(0o700)
    return 0


def ensure_asr() -> int:
    """Turn on meeting transcription (a core feature) unless [asr] is already configured; never blocks chat."""
    from .compute import get_pack, install

    asr = load_settings(CONFIG).asr
    if asr.base_url or (asr.provider == "command" and asr.command):
        return 0
    pack = get_pack("asr-funasr")
    print(f"开启录音转写：本机已有模型直接复用，否则下载约 {pack.model_bytes / 1024**3:.1f} GiB（只需一次）。")
    try:
        install(pack, CONFIG, download_models=True, progress=lambda text: print(f"  {text}"))
    except (ValueError, OSError) as error:
        print(f"  录音转写暂未开启：{error}")
        print("  文字聊天不受影响；处理后重新运行 ./scripts/local-up.sh 会再次尝试。")
    return 0
