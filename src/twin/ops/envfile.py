"""Load owner-only KEY=VALUE files without replacing process environment."""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path


def load_env_file(path: Path) -> list[str]:
    if not path.exists():
        return []
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode != 0o600:
        raise PermissionError(f"环境文件 {path} 权限为 {mode:04o}，请执行 chmod 600 {path}")
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
