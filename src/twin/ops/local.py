"""Offline configuration gate for the repository quickstart."""

from __future__ import annotations

import os
from pathlib import Path

from ..config import load_settings
from .envfile import load_env_file, selected_env_file


def check_local_config() -> int:
    try:
        load_env_file(selected_env_file())
        settings = load_settings(Path("twin.toml"))
    except (ValueError, OSError):
        print("配置读取失败：请检查 twin.toml 的 TOML 格式及 .env 格式/权限；运行 twin doctor 查看详情。")
        return 1
    llm = settings.llm
    missing = [name for name in ("model", "base_url") if not (getattr(llm, name) or "").strip()]
    key_missing = not os.environ.get(llm.api_key_env, "").strip()
    if missing or key_missing:
        print("尚未配置文字聊天模型，服务未启动。请完成以下设置：")
        print("1. 编辑 ./twin.toml 的 [llm]，取消 model 和 base_url 两行的注释，填写可用的模型名和服务地址。")
        print(f'2. 保留 api_key_env = "{llm.api_key_env}"；在 ./.env 中填写 {llm.api_key_env}=你的密钥。')
        print("   密钥只放 .env 或已有进程环境变量，不写入 twin.toml；执行 chmod 600 .env。")
        print("   若设置了 TWIN_ENV_FILE，则应填写该文件；已有进程环境变量优先，不被文件覆盖。")
        print("3. 保存后重新运行 ./scripts/local-up.sh（需要示例时加 --demo）。")
        return 1
    return 0
