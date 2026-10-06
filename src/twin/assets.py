"""Private, content-addressed portrait and voice references for a persona."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
from pathlib import Path
from typing import Any, Literal

from .util import private_directory

_LOCK = threading.Lock()
ASSET_NAME = re.compile(r"[0-9a-f]{64}\.(png|wav)")


class AssetStore:
    def __init__(self, db_path: Path) -> None:
        self.directory = db_path.parent / "assets"

    def prepare(self) -> None:
        private_directory(self.directory)
        self.directory.chmod(0o700)

    def profile(self) -> dict[str, Any]:
        path = self.directory / "profile.json"
        if not path.is_file():
            return {"portrait": None, "voice": None}
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return {"portrait": data.get("portrait"), "voice": data.get("voice")}

    def path(self, kind: Literal["portrait", "voice"]) -> Path | None:
        entry = self.profile()[kind]
        if entry is None:
            return None
        name = entry.get("file", "")
        if not isinstance(name, str) or ASSET_NAME.fullmatch(name) is None:
            return None
        path = self.directory / name
        return path.resolve() if path.is_file() and not path.is_symlink() else None

    def update(self, kind: Literal["portrait", "voice"], entry: dict[str, Any] | None) -> dict[str, Any]:
        with _LOCK:
            self.prepare()
            profile = self.profile()
            profile[kind] = entry
            self.write(self.directory / "profile.json", json.dumps(profile, ensure_ascii=False).encode())
            return profile

    @staticmethod
    def write(path: Path, content: bytes, mode: int = 0o600) -> None:
        fd, name = tempfile.mkstemp(dir=path.parent, prefix=".asset-")
        temporary = Path(name)
        try:
            with os.fdopen(fd, "wb") as output:
                os.fchmod(output.fileno(), mode)
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

    def save(
        self, kind: Literal["portrait", "voice"], content: bytes, duration_s: float | None = None
    ) -> dict[str, Any]:
        self.prepare()
        sha = hashlib.sha256(content).hexdigest()
        name = sha + (".png" if kind == "portrait" else ".wav")
        self.write(self.directory / name, content)
        entry = (
            {"sha": sha, "file": name}
            if kind == "portrait"
            else {"id": "self-" + sha[:16], "file": name, "duration_s": duration_s}
        )
        return self.update(kind, entry)

    def publish_voice(self, voice_dir: Path | None) -> str | None:
        if voice_dir is None:
            return None
        path = self.path("voice")
        if path is None:
            return None
        voice_id = "self-" + path.stem[:16]
        voice_dir = voice_dir.expanduser()
        if not voice_dir.exists():
            voice_dir.mkdir(parents=True, exist_ok=True)
            voice_dir.chmod(0o755)
        target = voice_dir / f"{voice_id}.wav"
        content = path.read_bytes()
        if (
            not target.is_file()
            or target.is_symlink()
            or target.stat().st_size != len(content)
            or target.read_bytes() != content
        ):
            self.write(target, content, 0o644)
        else:
            target.chmod(0o644)
        return voice_id
