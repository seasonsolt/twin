"""Versioned command compute packs for local repository installations."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import tempfile
import tomllib
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import load_settings
from .paths import TwinPaths, compute_defaults

PACK_ROOT = Path(__file__).resolve().parents[3] / "deploy" / "compute"
BEGIN = "# >>> twin compute asr-funasr"
END = "# <<< twin compute asr-funasr"
Runner = Callable[[list[str]], subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class Pack:
    source: Path
    name: str
    version: str
    kind: str
    platforms: tuple[str, ...]
    python: str
    entry: str
    models: list[dict[str, Any]]

    @property
    def model_bytes(self) -> int:
        return sum(int(file["size"]) for model in self.models for file in model["files"])


def discover(root: Path = PACK_ROOT) -> list[Pack]:
    packs = []
    for path in sorted(root.glob("*/pack.toml")):
        data = tomllib.loads(path.read_text())
        for key in ("name", "version", "entry"):
            if not isinstance(data[key], str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]*", data[key]):
                raise ValueError(f"算力包 {key} 无效：{path}")
        if data["name"] != path.parent.name or data["kind"] != "command":
            raise ValueError(f"算力包名称或类型无效：{path}")
        for model in data["models"]:
            if not re.fullmatch(r"[\w.-]+/[\w.-]+", model["id"]) or model["revision"] in {".", ".."}:
                raise ValueError("模型 ID 或 revision 无效")
            if not re.fullmatch(r"[\w.-]+", model["revision"]):
                raise ValueError("模型 revision 无效")
            for file in model["files"]:
                relative = Path(file["path"])
                if (
                    relative.is_absolute()
                    or ".." in relative.parts
                    or not re.fullmatch(r"[0-9a-f]{64}", file["sha256"])
                ):
                    raise ValueError("模型文件路径或 sha256 无效")
        packs.append(
            Pack(
                path.parent,
                data["name"],
                data["version"],
                data["kind"],
                tuple(data["platforms"]),
                data["python"],
                data["entry"],
                data["models"],
            )
        )
    return packs


def get_pack(name: str) -> Pack:
    for pack in discover():
        if pack.name == name:
            return pack
    raise ValueError(f"未知算力包 {name}；请运行 twin compute list（从仓库运行）")


def model_cache() -> Path:
    return Path(os.environ.get("MODELSCOPE_CACHE", "~/.cache/modelscope")).expanduser().resolve()


def model_directory(model: dict[str, Any], cache: Path) -> Path:
    candidates: list[Path] = [
        cache / "models" / model["id"].replace("/", "--") / "snapshots" / model["revision"],
        cache / "hub" / model["id"],
        cache / model["id"],
    ]
    return next((p for p in candidates if all((p / f["path"]).is_file() for f in model["files"])), candidates[0])


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_models(pack: Pack, cache: Path, record: Path | None = None) -> list[str]:
    previous: dict[str, Any] = {}
    if record and record.is_file():
        try:
            parsed = json.loads(record.read_text())
            if isinstance(parsed, dict):
                previous = parsed
        except (ValueError, OSError):
            pass
    verified = {}
    missing = []
    for model in pack.models:
        directory = model_directory(model, cache)
        valid = True
        for file in model["files"]:
            path = directory / file["path"]
            try:
                stat = path.stat()
                signature = {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha256": file["sha256"]}
                if stat.st_size != file["size"] or (
                    previous.get(str(path)) != signature and sha256(path) != file["sha256"]
                ):
                    valid = False
                else:
                    verified[str(path)] = signature
            except OSError:
                valid = False
        if not valid:
            missing.append(model["id"])
    if record:
        record.write_text(json.dumps(verified, indent=2) + "\n")
    return missing


def without_managed(text: str) -> str:
    lines = text.splitlines(keepends=True)
    starts = [i for i, line in enumerate(lines) if line.rstrip("\r\n") == BEGIN]
    ends = [i for i, line in enumerate(lines) if line.rstrip("\r\n") == END]
    if not starts and not ends:
        return text
    if len(starts) != 1 or len(ends) != 1 or starts[0] >= ends[0]:
        raise ValueError("转写配置标记不完整，请手动检查 twin compute asr-funasr 标记")
    block = "".join(lines[starts[0] + 1 : ends[0]])
    data = tomllib.loads(block)
    if set(data) != {"asr"}:
        raise ValueError("转写配置标记内含其他配置，请手动移出后重试")
    return "".join(lines[: starts[0]] + lines[ends[0] + 1 :])


def config_text(path: Path, *, remove: bool = False) -> str:
    original = path.read_bytes().decode("utf-8") if path.exists() else ""
    rest = without_managed(original)
    if remove:
        return rest
    if "asr" in tomllib.loads(rest):
        raise ValueError(
            "已有手写 [asr] 配置，不能覆盖（--force 也不覆盖）；请手动备份并移除该节后重试，或保留并手动配置命令"
        )
    command = str(compute_defaults()["asr_command"])
    block = (
        f'{BEGIN}\n[asr]\nprovider = "command"\ncommand = {json.dumps(command, ensure_ascii=False)}\n'
        f'language = "zh"\negress = "local"\n{END}\n'
    )
    return rest + ("\n" if rest and not rest.endswith("\n") else "") + block


def write_config(path: Path, *, remove: bool = False) -> None:
    original = path.read_bytes() if path.exists() else None
    updated = config_text(path, remove=remove).encode("utf-8")
    if updated == original or (original is None and remove):
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        if original is None:
            path.touch(mode=0o600)
        path.write_bytes(updated)
        load_settings(path)
    except Exception:
        if original is None:
            path.unlink(missing_ok=True)
        else:
            path.write_bytes(original)
        raise


def run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, check=True, timeout=1800)


@contextmanager
def pack_lock(root: Path, name: str) -> Iterator[None]:
    root.mkdir(parents=True, exist_ok=True)
    with (root / f".{name}.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("该算力包正在安装或移除，请稍后重试") from None
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def switch_current(current: Path, target: str) -> None:
    temporary = current.with_name(".current-next")
    temporary.unlink(missing_ok=True)
    temporary.symlink_to(target)
    temporary.replace(current)


def install(
    pack: Pack,
    config: Path,
    *,
    download_models: bool = False,
    force: bool = False,
    runner: Runner = run_command,
    progress: Callable[[str], None] = print,
) -> Path:
    target_platform = f"{platform.system().lower()}-{platform.machine().lower()}"
    if target_platform not in pack.platforms:
        raise ValueError(f"算力包不支持 {target_platform}；支持：{', '.join(pack.platforms)}")
    for executable in ("uv", "ffmpeg"):
        if shutil.which(executable) is None:
            raise ValueError(f"未找到 {executable}，请运行 brew install {executable}")
    config_text(config)
    load_settings(config)
    root = TwinPaths.from_env().compute
    with pack_lock(root, pack.name):
        return _install(pack, config, root, download_models, force, runner, progress)


def _install(
    pack: Pack,
    config: Path,
    root: Path,
    download: bool,
    force: bool,
    runner: Runner,
    progress: Callable[[str], None],
) -> Path:
    home = root / pack.name
    home.mkdir(exist_ok=True)
    current, target = home / "current", home / pack.version
    if current.exists() and not current.is_symlink():
        raise ValueError("current 必须是符号链接，请手动检查安装目录")
    old_link = os.readlink(current) if current.is_symlink() else None
    staging: Path | None = None
    backup = home / f".{pack.version}.previous"
    if backup.exists():
        raise ValueError(f"存在未清理的安装备份 {backup}，请先检查")
    reused = target.is_dir() and not force
    if reused:
        work = target
    else:
        staging = Path(tempfile.mkdtemp(prefix=f".{pack.version}-", dir=home))
        work = staging
    promoted = False

    def execute(command: list[str]) -> subprocess.CompletedProcess[str]:
        try:
            result = runner(command)
        except subprocess.SubprocessError as error:
            step = "健康检查" if "--check" in command else "依赖安装" if command[0] == "uv" else "模型下载"
            raise ValueError(f"算力包{step}失败，已保留旧安装；请检查依赖、缓存或网络后重试") from error
        if result.returncode:
            raise ValueError("算力包命令执行失败：" + Path(command[0]).name)
        return result

    try:
        if not reused:
            progress("创建 Python 3.12 环境并安装锁定依赖（首次可能需要数分钟）…")
            execute(["uv", "venv", "--python", pack.python, "--relocatable", str(work / "venv")])
            execute(
                [
                    "uv",
                    "pip",
                    "install",
                    "--python",
                    str(work / "venv/bin/python"),
                    "-r",
                    str(pack.source / f"requirements-{platform.system().lower()}-{platform.machine().lower()}.lock"),
                ]
            )
            shutil.copy2(pack.source / pack.entry, work / pack.entry)
            shutil.copy2(pack.source / "pack.toml", work / "pack.toml")
            if (target / "verified.json").is_file():
                shutil.copy2(target / "verified.json", work / "verified.json")
        progress("校验本地模型…")
        cache = model_cache()
        missing = verify_models(pack, cache, work / "verified.json")
        if missing and not download:
            raise ValueError(
                f"缺少模型或校验失败：{', '.join(missing)}；模型合计约 {pack.model_bytes / 1024**3:.2f} GiB。"
                f"允许下载时运行 twin compute install {pack.name} --download-models；缓存：{cache}"
            )
        for model in pack.models:
            if model["id"] not in missing:
                continue
            progress(f"下载模型 {model['id']}…")
            script = (
                "import sys; from modelscope import snapshot_download; "
                "snapshot_download(sys.argv[1], revision=sys.argv[2], cache_dir=sys.argv[3])"
            )
            execute([str(work / "venv/bin/python"), "-c", script, model["id"], model["revision"], str(cache)])
        if missing and verify_models(pack, cache, work / "verified.json"):
            raise ValueError("下载后模型 sha256 校验失败，保留旧安装；请检查模型版本和缓存")
        progress("运行离线健康检查（加载全部模型）…")
        result = execute([str(work / "venv/bin/python"), str(work / pack.entry), "--check"])
        try:
            healthy = json.loads(result.stdout.strip().splitlines()[-1]).get("ok") is True
        except (ValueError, IndexError, AttributeError):
            healthy = False
        if not healthy:
            raise ValueError("转写健康检查失败，保留旧安装")
        if staging:
            if target.exists():
                target.rename(backup)
            staging.rename(target)
            promoted = True
        switch_current(current, pack.version)
        write_config(config)
    except Exception:
        if old_link is not None:
            switch_current(current, old_link)
        else:
            current.unlink(missing_ok=True)
        if promoted:
            shutil.rmtree(target)
        if backup.exists():
            backup.rename(target)
        raise
    finally:
        if staging and staging.exists():
            shutil.rmtree(staging)
    if backup.exists():
        shutil.rmtree(backup)
    progress(f"已安装 {pack.name} {pack.version}，配置：{config}")
    return target


def remove(pack: Pack, config: Path) -> str:
    root = TwinPaths.from_env().compute
    with pack_lock(root, pack.name):
        write_config(config, remove=True)
        directory = root / pack.name
        if directory.is_symlink():
            directory.unlink()
        elif directory.exists():
            shutil.rmtree(directory)
    cache = model_cache()
    total = sum(
        path.stat().st_size
        for model in pack.models
        for path in model_directory(model, cache).rglob("*")
        if path.is_file()
    )
    return f"已移除 {pack.name}；模型缓存保留：{cache}（约 {total / 1024**3:.2f} GiB），由你决定是否清理。请重启网页。"


def installed_version(pack: Pack) -> str | None:
    manifest = TwinPaths.from_env().compute / pack.name / "current" / "pack.toml"
    if not manifest.is_file():
        return None
    return str(tomllib.loads(manifest.read_text()).get("version")) or None


def status(pack: Pack, config: Path) -> str:
    current = TwinPaths.from_env().compute / pack.name / "current"
    installed = (current / "venv/bin/python").is_file() and (current / pack.entry).is_file()
    version = installed_version(pack) or "未知"
    text = config.read_text() if config.is_file() else ""
    settings = load_settings(config)
    configured = "asr" in tomllib.loads(text)
    try:
        arguments = shlex.split(settings.asr.command or "")
        expected = shlex.split(str(compute_defaults()["asr_command"]))
        matches = (
            installed
            and settings.asr.provider == "command"
            and len(arguments) >= 2
            and all(
                Path(got).resolve() == Path(want).resolve() for got, want in zip(arguments[:2], expected, strict=True)
            )
        )
    except ValueError:
        matches = False
    missing = verify_models(pack, model_cache(), current / "verified.json" if installed else None)
    return (
        f"{pack.name}：{'已安装' if installed else '未安装'}；版本 {version}；"
        f"current → {os.readlink(current) if current.is_symlink() else '无'}；"
        f"[asr] {'存在' if configured else '不存在'}，{'指向当前安装' if matches else '未指向当前安装'}；"
        f"模型{'齐全且校验通过' if not missing else '缺失或校验失败：' + ', '.join(missing)}"
    )
