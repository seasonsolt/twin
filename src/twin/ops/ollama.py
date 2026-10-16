"""The local embedding model of the repository quickstart: bge-m3 served by Ollama on this Mac.

Retrieval by meaning is the default; the model-free hashing embedder stays the fallback whenever Ollama or the model
cannot be made available, so nothing here ever blocks chat. The [embed] table it writes sits between markers, and
it only ever replaces the template's default hashing table, never one written by hand.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import time
import tomllib
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..config import EmbedSettings, load_settings, make_embedder
from ..embed import EmbedError

OLLAMA = "http://127.0.0.1:11434"
MODEL = "bge-m3"
REGISTRY = f"https://registry.ollama.ai/v2/library/{MODEL}"
MANIFEST = "application/vnd.docker.distribution.manifest.v2+json"
APP = Path("/Applications/Ollama.app")
BEGIN = "# >>> twin local embed bge-m3"
END = "# <<< twin local embed bge-m3"
# Keys of the template's [embed] table, which the managed one may replace; anything else was set by hand.
DEFAULT_KEYS = frozenset({"provider", "api_key_env", "egress"})
SETTINGS = EmbedSettings(provider="openai_compat", model=MODEL, base_url=f"{OLLAMA}/v1", egress="local")
BLOCK = (
    f"{BEGIN}\n"
    "# 本机 Ollama 的 bge-m3 按语义检索，数据不出本机；Ollama 未运行时聊天只按关键词检索。\n"
    "[embed]\n"
    'provider = "openai_compat"\n'
    f'model = "{MODEL}"\n'
    f'base_url = "{OLLAMA}/v1"\n'
    'egress = "local"\n'
    f"{END}\n"
)
_HEADER = re.compile(r"\s*\[")
_KEY = re.compile(r"\s*[A-Za-z0-9_-]+\s*=")
# Local calls go straight to Ollama, never through a proxy from the environment.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class OllamaError(RuntimeError):
    """Ollama or the model is not available; the message says why, for the person to act on."""


def _call(path: str, body: dict[str, Any] | None = None, timeout: float = 5) -> Any:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(f"{OLLAMA}{path}", data=data, headers={"Content-Type": "application/json"})
    with _OPENER.open(request, timeout=timeout) as response:
        return json.load(response)


def running() -> bool:
    try:
        _call("/api/version", timeout=2)
    except (OSError, ValueError):
        return False
    return True


def start(wait: float = 30) -> None:
    """Start Ollama when it is not running: the app when installed (it keeps itself running), else ``ollama serve``
    as this user's background process."""
    if running():
        return
    binary = shutil.which("ollama")
    if APP.is_dir():
        subprocess.run(["open", "-g", "-a", str(APP)], check=False, capture_output=True)
    elif binary:
        subprocess.Popen(
            [binary, "serve"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    else:
        raise OllamaError("未安装 Ollama（https://ollama.com 下载，或 brew install ollama）")
    deadline = time.monotonic() + wait
    while not running():
        if time.monotonic() > deadline:
            raise OllamaError(f"Ollama 启动后 {wait:.0f} 秒内仍未响应")
        time.sleep(0.5)


def has_model() -> bool:
    models = _call("/api/tags").get("models") or []
    return any(str(m.get("name", "")).split(":")[0] == MODEL for m in models)


class DownloadRefused(OllamaError):
    """Ollama would not follow the download to a private address, which a proxy in fake-ip mode hands out."""


def _tenths(progress: Callable[[str], None]) -> Callable[[int, int], None]:
    """Report a large download every tenth of the way, from the first tenth on."""
    reported = 0

    def update(completed: int, total: int) -> None:
        nonlocal reported
        if total > 100_000_000 and (tenth := completed * 10 // total) > reported:
            reported = tenth
            progress(f"  {tenth * 10}%")

    return update


def pull(progress: Callable[[str], None]) -> None:
    """Download the model through Ollama."""
    progress(f"下载向量模型 {MODEL}（约 1.2 GB，只需一次）…")
    request = urllib.request.Request(
        f"{OLLAMA}/api/pull", data=json.dumps({"model": MODEL}).encode(), headers={"Content-Type": "application/json"}
    )
    update = _tenths(progress)
    with _OPENER.open(request, timeout=300) as response:
        for line in response:
            if not line.strip():
                continue
            event = json.loads(line)
            if event.get("error"):
                error = str(event["error"])
                raise (DownloadRefused if "non-public" in error else OllamaError)(error)
            update(event.get("completed") or 0, event.get("total") or 0)
            if event.get("status") == "success":
                return
    raise OllamaError("下载中断，未完成")


def _fetch(layer: dict[str, Any], into: Path, progress: Callable[[str], None]) -> None:
    """Download one registry layer to ``into``, checked against its size and digest."""
    digest, size = str(layer["digest"]), int(layer["size"])
    update = _tenths(progress)
    hashed, received = hashlib.sha256(), 0
    with urllib.request.urlopen(f"{REGISTRY}/blobs/{digest}", timeout=60) as response, into.open("wb") as file:
        while chunk := response.read(1 << 20):
            hashed.update(chunk)
            file.write(chunk)
            received += len(chunk)
            update(received, size)
    if received != size or f"sha256:{hashed.hexdigest()}" != digest:
        raise OllamaError("下载的模型文件校验不通过，已丢弃")


def download(progress: Callable[[str], None]) -> None:
    """Fetch the model's files from the Ollama registry here and import them through Ollama's API: the same files
    ``ollama pull`` would store, checked against the manifest's digests."""
    progress("Ollama 不能直接下载（代理把下载地址解析成了内网 IP），改由 twin 从同一来源下载、校验后导入…")
    request = urllib.request.Request(f"{REGISTRY}/manifests/latest", headers={"Accept": MANIFEST})
    with urllib.request.urlopen(request, timeout=30) as response:
        layers = {layer["mediaType"]: layer for layer in json.load(response)["layers"]}
    model = layers.get("application/vnd.ollama.image.model")
    if model is None:
        raise OllamaError("模型清单里没有模型文件")
    with tempfile.TemporaryDirectory(prefix="twin-bge-m3-") as directory:
        path = Path(directory) / "model.gguf"
        _fetch(model, path, progress)
        with path.open("rb") as file:
            upload = urllib.request.Request(
                f"{OLLAMA}/api/blobs/{model['digest']}", data=file, headers={"Content-Length": str(model["size"])}
            )
            with _OPENER.open(upload, timeout=600):
                pass
    created = {"model": MODEL, "files": {"model.gguf": model["digest"]}, "stream": False}
    if license_layer := layers.get("application/vnd.ollama.image.license"):
        with urllib.request.urlopen(f"{REGISTRY}/blobs/{license_layer['digest']}", timeout=30) as response:
            created["license"] = response.read().decode("utf-8")
    status = _call("/api/create", created, timeout=600)
    if status.get("status") != "success":
        raise OllamaError(f"导入 Ollama 失败：{status.get('error') or status}")


def prepare(progress: Callable[[str], None]) -> None:
    """Make the model answer embeddings: start Ollama, download the model when missing (fetching it here when Ollama
    refuses to), then embed a probe text."""
    try:
        start()
        if not has_model():
            try:
                pull(progress)
            except DownloadRefused:
                download(progress)
        make_embedder(SETTINGS).embed(["连通测试"])
    except (OSError, ValueError, KeyError, EmbedError) as error:
        raise OllamaError(str(error)) from error


def config_text(text: str) -> str | None:
    """``text`` with the managed bge-m3 [embed] in place of the template's hashing table (or added when there is
    none); unchanged when already managed; None when [embed] was configured by hand."""
    if BEGIN in text:
        return text
    embed = tomllib.loads(text).get("embed")
    if embed is not None and (embed.get("provider", "hashing") != "hashing" or not set(embed) <= DEFAULT_KEYS):
        return None
    lines = text.splitlines(keepends=True)
    header = next((i for i, line in enumerate(lines) if line.strip() == "[embed]"), None)
    if header is None:
        return text + ("\n" if text and not text.endswith("\n") else "") + BLOCK
    following = next((i for i in range(header + 1, len(lines)) if _HEADER.match(lines[i])), len(lines))
    # The table ends at its last key: comments after it introduce what follows.
    last = max((i for i in range(header + 1, following) if _KEY.match(lines[i])), default=header)
    return "".join([*lines[:header], BLOCK, *lines[last + 1 :]])


def write_config(path: Path, text: str) -> None:
    """Write ``text`` only if it loads as a configuration, keeping the original otherwise."""
    original = path.read_bytes()
    try:
        path.write_text(text, encoding="utf-8")
        load_settings(path)
    except Exception:
        path.write_bytes(original)
        raise
