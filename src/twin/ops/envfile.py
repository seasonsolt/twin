"""Load owner-only KEY=VALUE files without replacing process environment, and change one value in place."""

from __future__ import annotations

import os
import re
import shlex
import stat
from pathlib import Path

from ..assets import AssetStore
from .paths import TwinPaths

ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
MAX_VALUE = 4096


def selected_env_file() -> Path:
    """Select one env file; a higher-priority file never merges with a fallback.

    ./.env counts only beside ./twin.toml, so another project's .env is never read.
    """
    if "TWIN_ENV_FILE" in os.environ:
        return Path(os.environ["TWIN_ENV_FILE"]).expanduser()
    local = Path(".env")
    return local if local.exists() and Path("twin.toml").exists() else TwinPaths.from_env().env


def _owner_only(path: Path) -> None:
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode != 0o600:
        raise PermissionError(f"环境文件 {path} 权限为 {mode:04o}，请执行 chmod 600 {shlex.quote(str(path))}")


def load_env_file(path: Path) -> list[str]:
    if not path.exists():
        return []
    _owner_only(path)
    values: dict[str, str] = {}
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)", line)
        if not match:
            raise ValueError(f"环境文件第 {number} 行格式错误，只支持 KEY=VALUE")
        key, value = match.groups()
        if value.startswith(('"', "'")):
            quote = value[0]
            end = value.find(quote, 1)
            if end < 0 or (value[end + 1 :].strip() and not value[end + 1 :].strip().startswith("#")):
                raise ValueError(f"环境文件第 {number} 行引号格式错误")
            value = value[1:end]
        else:
            value = re.split(r"\s+#", value, maxsplit=1)[0].rstrip()
        values[key] = value
    for key, value in values.items():
        os.environ.setdefault(key, value)
    return list(values)


def _quoted(value: str) -> str:
    """The value as load_env_file reads it back: bare when it has no space, # or leading quote."""
    if not re.search(r"[\s#]", value) and not value.startswith(('"', "'")):
        return value
    for quote in ('"', "'"):
        if quote not in value:
            return f"{quote}{value}{quote}"
    raise ValueError("值里不能同时有单引号和双引号")


def write_env_value(path: Path, name: str, value: str | None) -> None:
    """Set ``name`` to ``value`` (None: remove it) in the env file, keeping every other line and comment. The file
    stays owner-only and is replaced in one step, so a reader never sees half of it."""
    if not ENV_NAME.fullmatch(name):
        raise ValueError(f"变量名 {name!r} 无效")
    if value is not None:
        if not value or value != value.strip() or len(value) > MAX_VALUE or not value.isprintable():
            raise ValueError(f"值不能为空、不能以空白开头或结尾、不能含换行等控制字符，最长 {MAX_VALUE} 个字符")
        line = f"{name}={_quoted(value)}"
    path = path.expanduser().resolve()
    lines: list[str] = []
    if path.exists():
        _owner_only(path)
        lines = path.read_text(encoding="utf-8").splitlines()
    assignment = re.compile(rf"\s*{re.escape(name)}\s*=")
    kept = [raw for raw in lines if not assignment.match(raw)]
    if value is not None:
        kept.append(line)
    path.parent.mkdir(parents=True, exist_ok=True)
    AssetStore.write(path, ("\n".join(kept) + "\n" if kept else "").encode())
