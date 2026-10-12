"""Canonical paths for a twin installation."""

from __future__ import annotations

import os
import platform
import shlex
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TwinPaths:
    home: Path
    config_dir: Path
    config: Path
    env: Path
    releases: Path
    current: Path
    compute: Path
    models: Path
    data: Path
    backups: Path
    logs: Path
    launch_agents: Path
    systemd_user: Path

    @classmethod
    def from_env(cls) -> TwinPaths:
        override = os.environ.get("TWIN_HOME")
        if override:
            home = Path(override).expanduser().resolve()
        elif platform.system() == "Darwin":
            home = Path.home() / "Library" / "Application Support" / "twin"
        else:
            home = Path.home() / ".local" / "share" / "twin"
        config_dir = home / "config" if override else Path.home() / ".config" / "twin"
        return cls(
            home,
            config_dir,
            config_dir / "twin.toml",
            Path(os.environ.get("TWIN_ENV_FILE", config_dir / "env")).expanduser().resolve(),
            home / "releases",
            home / "current",
            home / "compute",
            home / "models",
            home / "data",
            home / "backups",
            home / "logs" if override or platform.system() != "Darwin" else Path.home() / "Library" / "Logs" / "twin",
            home / "LaunchAgents" if override else Path.home() / "Library" / "LaunchAgents",
            home / "systemd" if override else Path.home() / ".config" / "systemd" / "user",
        )

    def service_log(self, name: str) -> Path:
        return self.logs / f"{name}.log"


def compute_defaults() -> dict[str, str | int]:
    """Stable P4 service contract; availability is checked by the installer/doctor."""
    root = TwinPaths.from_env().compute
    commands = {}
    for kind, pack in (("asr", "asr-funasr"), ("vision", "vision-mediapipe"), ("video", "video-ditto")):
        current = root / pack / "current"
        commands[kind + "_command"] = shlex.join([str(current / "venv" / "bin" / "python"), str(current / "run.py")])
    return {"tts_port": 8004, **commands}
