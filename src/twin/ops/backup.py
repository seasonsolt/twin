"""Consistent private SQLite snapshots and stopped-service restores."""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

from ..util import open_private, prepare_private_file, private_directory
from .paths import TwinPaths


def _copy_tree(source: Path, target: Path, *, snapshot: bool, link: bool = False) -> None:
    """Copy ``source`` into ``target``; SQLite databases as consistent snapshots when ``snapshot``. When backing up
    (``snapshot``), files of library recordings (``library/<owner>/recordings/``) are written once and never
    changed, so they are hard-linked instead (copied when the target is on another file system): backups do not
    hold the audio again each time. A restore copies everything, so the restored data shares nothing with the
    backup."""
    private_directory(target)
    target.chmod(0o700)
    for path in source.iterdir():
        if path.is_symlink():
            raise ValueError("备份或恢复目录不能包含符号链接")
        if path.name == "media-cache" or path.name.endswith((".part", "-wal", "-shm")):
            continue
        # Uploads awaiting transcription are deleted once transcribed, so a backup does not keep them alive for
        # weeks (a restored recording without one is re-uploaded); also skipped: a transcription's temporary audio
        # and files not yet published under their final name.
        if link and (path.name.startswith(("original.", "audio.wav")) or path.name.endswith(".tmp")):
            continue
        destination = target / path.name
        if path.is_dir():
            recordings = snapshot and path.name == "recordings" and source.parent.name == "library"
            _copy_tree(path, destination, snapshot=snapshot, link=link or recordings)
        elif path.is_file():
            if snapshot and path.suffix == ".db":
                prepare_private_file(destination)
                with (
                    closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as src,
                    closing(sqlite3.connect(destination)) as dst,
                ):
                    src.backup(dst)
                    dst.execute("PRAGMA journal_mode=DELETE")
            elif link:
                try:
                    os.link(path, destination)
                except OSError:
                    prepare_private_file(destination)
                    shutil.copyfile(path, destination)
            else:
                prepare_private_file(destination)
                shutil.copyfile(path, destination)
            destination.chmod(0o600)


def backup(paths: TwinPaths, data: Path, config: Path, reason: str = "daily") -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", reason):
        raise ValueError("备份原因仅支持 1–100 位字母、数字、下划线或连字符")
    private_directory(paths.backups)
    paths.backups.chmod(0o700)
    now = dt.datetime.now(dt.UTC)
    target = paths.backups / f"{now:%Y%m%dT%H%M%S%f}-{reason}"
    if paths.backups.resolve().is_relative_to(data.resolve()):
        raise ValueError("备份目录不能位于数据目录内")
    private_directory(target)
    try:
        if data.exists():
            _copy_tree(data, target / "data", snapshot=True)
        else:
            private_directory(target / "data")
        if config.is_file():
            prepare_private_file(target / "twin.toml")
            shutil.copyfile(config, target / "twin.toml")
        with open_private(target / "snapshot.json") as stream:
            json.dump({"version": 1, "reason": reason, "created_at": now.isoformat()}, stream)
    except BaseException:
        shutil.rmtree(target)
        raise
    prune(paths.backups, now)
    return target


def prune(root: Path, now: dt.datetime) -> None:
    daily: list[Path] = []
    for directory in sorted(root.iterdir(), reverse=True):
        manifest = directory / "snapshot.json"
        if directory.is_symlink() or not manifest.is_file():
            continue
        try:
            meta = json.loads(manifest.read_text())
            created = dt.datetime.fromisoformat(meta["created_at"])
            reason = meta["reason"]
        except (ValueError, KeyError, TypeError):
            continue
        if not isinstance(reason, str) or created.tzinfo is None:
            continue
        if reason.startswith("pre-upgrade-"):
            if now - created > dt.timedelta(days=30):
                shutil.rmtree(directory)
        elif reason == "daily":
            daily.append(directory)
    for directory in daily[7:]:
        shutil.rmtree(directory)


def restore(source: Path, data: Path, config: Path, *, services_stopped: bool) -> None:
    if not services_stopped:
        raise ValueError("恢复前必须先执行 twin ops stop，并确认所有服务已停")
    if source.is_symlink() or not (source / "snapshot.json").is_file() or not (source / "data").is_dir():
        raise ValueError("不是完整的 twin 备份目录")
    if source.resolve().is_relative_to(data.resolve()) or data.resolve().is_relative_to(source.resolve()):
        raise ValueError("备份目录与数据目录不能相互包含")
    metadata = json.loads((source / "snapshot.json").read_text())
    if not isinstance(metadata, dict) or metadata.get("version") != 1:
        raise ValueError("不支持此备份格式")
    if any(path.is_symlink() for path in source.rglob("*")):
        raise ValueError("恢复目录不能包含符号链接")
    staging = data.with_name(data.name + ".restore")
    previous = data.with_name(data.name + ".before-restore")
    config_staging = (
        data.with_name(data.name + ".restore.toml")
        if config.resolve().is_relative_to(data.resolve())
        else config.with_name(config.name + ".restore")
    )
    if any(path.exists() or path.is_symlink() for path in (staging, previous, config_staging)) or data.is_symlink():
        raise ValueError("恢复暂存目录已存在或数据目录是符号链接，请检查上次恢复状态")
    try:
        _copy_tree(source / "data", staging, snapshot=False)
        if (source / "twin.toml").is_file():
            private_directory(config_staging.parent)
            with open_private(config_staging) as stream:
                stream.write((source / "twin.toml").read_text())
        for db in staging.rglob("*.db"):
            with closing(sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
                if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise ValueError("备份中的数据库完整性检查失败")
        if data.exists():
            data.rename(previous)
        try:
            staging.rename(data)
            if config_staging.exists():
                private_directory(config.parent)
                config_staging.replace(config)
        except BaseException:
            if data.exists():
                shutil.rmtree(data)
            if previous.exists():
                previous.rename(data)
            raise
        if previous.exists():
            shutil.rmtree(previous)
    finally:
        config_staging.unlink(missing_ok=True)
        if staging.exists():
            shutil.rmtree(staging)
