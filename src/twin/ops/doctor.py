"""Read-only deployment diagnostics; model requests require explicit probing."""

from __future__ import annotations

import io
import json
import os
import platform
import re
import shutil
import socket
import sqlite3
import stat
import sys
import tempfile
import wave
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import BaseModel

from ..config import (
    ASRSettings,
    EmbedSettings,
    LLMSettings,
    Settings,
    TTSSettings,
    make_embedder,
    make_llm,
    make_recognizer,
    make_synthesizer,
)
from ..media.schema import SpeechRequest, TranscriptionRequest
from ..persona.kernel import KERNEL, KernelVersion, rebuild_scope
from .paths import TwinPaths
from .service import ServiceManager, services


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool | None
    detail: str

    def text(self) -> str:
        return f"{'–' if self.ok is None else '✓' if self.ok else '✗'} {self.name}：{self.detail}"


def tcp(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except OSError:
        return False


def model_probe(kind: str, settings: Settings) -> None:
    if kind == "LLM":

        class Reply(BaseModel):
            ok: bool

        make_llm(settings.llm).structured(system="返回 ok=true。", user="连通测试", schema=Reply, max_tokens=32)
    elif kind == "向量":
        make_embedder(settings.embed).embed(["连通测试"])
    elif kind == "语音":
        make_synthesizer(settings.tts).synthesize(SpeechRequest(text="你好"))
    elif kind == "识别":
        stream = io.BytesIO()
        with wave.open(stream, "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(16000)
            audio.writeframes(b"\0" * 32000)
        if settings.asr.provider == "command":
            from ..media.ingest import make_transcriber

            with tempfile.TemporaryDirectory(prefix="twin-probe-") as directory:
                audio_path = Path(directory) / "probe.wav"
                audio_path.write_bytes(stream.getvalue())
                transcriber = make_transcriber(settings.asr)
                if transcriber is None:
                    raise ValueError("未配置识别命令")
                transcriber.transcribe(audio_path, 1.0, lambda *_: None)
        else:
            make_recognizer(settings.asr).transcribe(TranscriptionRequest(audio=stream.getvalue()))


def inspect_installation(
    paths: TwinPaths,
    settings: Settings,
    config: Path,
    backend: ServiceManager,
    *,
    probe: bool = False,
    connect: Callable[[str, int], bool] = tcp,
    invoke_model: Callable[[str, Settings], None] = model_probe,
) -> list[Check]:
    checks = [
        Check("Python", sys.version_info >= (3, 12), "需要 Python 3.12 或更高版本"),
        Check(
            "架构",
            platform.machine() == "arm64" if platform.system() == "Darwin" else None,
            "Mac 统一部署需要 arm64；Linux 支持分离部署",
        ),
        Check("ffmpeg", shutil.which("ffmpeg") is not None, "缺少时运行 brew install ffmpeg"),
        Check("配置校验", config.is_file(), "配置已解析" if config.is_file() else "请先运行 twin init"),
    ]
    fonts = (
        [Path(settings.media.font_path)]
        if settings.media.font_path
        else [
            Path("/System/Library/Fonts/PingFang.ttc"),
            Path("/System/Library/Fonts/Hiragino Sans GB.ttc"),
            Path("/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc"),
            Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        ]
    )
    checks.append(Check("中文字体", any(p.is_file() for p in fonts), "缺少时配置 [media] font_path"))
    checks.append(
        Check(
            "环境文件权限",
            paths.env.is_file() and stat.S_IMODE(paths.env.stat().st_mode) == 0o600,
            "应创建 env 并执行 chmod 600；密钥值不会显示",
        )
    )
    checks.append(
        Check(
            "数据目录权限",
            settings.db_path.parent.is_dir() and stat.S_IMODE(settings.db_path.parent.stat().st_mode) == 0o700,
            "数据目录必须为 0700，请执行 chmod 700",
        )
    )
    required = set()
    sections: list[LLMSettings | EmbedSettings | TTSSettings | ASRSettings] = [
        settings.llm,
        settings.effective_chat_llm,
        settings.embed,
        settings.tts,
        settings.asr,
        *settings.judges,
    ]
    for section in sections:
        if isinstance(section, ASRSettings) and not (section.base_url or section.command):
            continue
        if section.provider not in {"hashing", "silent", "command", "claude_cli"}:
            required.add(section.api_key_env)
    if settings.auth.enabled:
        required.add(settings.auth.smtp.password_env)
    for name in sorted(required):
        checks.append(
            Check(
                f"环境变量 {name}",
                bool(os.environ.get(name)),
                "已设置" if os.environ.get(name) else "请在 env 文件中填写",
            )
        )
    endpoints: list[tuple[str, LLMSettings | EmbedSettings | TTSSettings | ASRSettings]] = [
        ("LLM", settings.llm),
        ("向量", settings.embed),
        ("语音", settings.tts),
        ("识别", settings.asr),
    ]
    for name, section in endpoints:
        enabled = section.provider not in {"hashing", "silent"} and (
            not isinstance(section, ASRSettings) or bool(section.base_url or section.command)
        )
        if not enabled:
            checks.append(Check(name, None, "使用本机轻量后端或尚未配置"))
            continue
        endpoint = section.base_url or (os.environ.get("OPENAI_BASE_URL") if name in {"LLM", "向量"} else None)
        if endpoint:
            try:
                url = urlsplit(endpoint)
                reachable = bool(url.hostname) and connect(
                    url.hostname or "", url.port or (443 if url.scheme == "https" else 80)
                )
            except ValueError:
                reachable = False
            checks.append(Check(f"{name}连接", reachable, "仅检查 TCP；失败时检查端点和服务"))
        if name == "LLM" and section.provider == "openai_compat":
            checks.append(Check("LLM 配置", bool(section.model and endpoint), "必须填写 model 和 base_url"))
        if probe:
            try:
                invoke_model(name, settings)
                checks.append(Check(f"{name}探针", True, "模型调用成功"))
            except Exception:
                checks.append(Check(f"{name}探针", False, "模型调用失败，请检查后端配置与凭据（详情已隐藏）"))
    for name, command in [
        ("转写", settings.asr.command),
        ("认人", settings.vision.command),
        ("视频", settings.video.command),
    ]:
        if command and not (name == "视频" and settings.video.host):
            import shlex

            try:
                arguments = shlex.split(command)
                exists = bool(arguments) and shutil.which(arguments[0]) is not None
            except ValueError:
                exists = False
            checks.append(
                Check(
                    f"{name}命令",
                    exists,
                    "算力包需先 twin compute install（P4 提供）；自定义命令请检查路径",
                )
            )
    for service in services(paths, config, settings):
        try:
            result = backend.execute("status", service)
            checks.append(
                Check(
                    f"服务 {service.name}",
                    result.returncode == 0,
                    "未加载时运行 twin ops install-services 和 twin ops start",
                )
            )
        except OSError:
            checks.append(Check(f"服务 {service.name}", False, "服务管理器不可用，请检查用户会话"))
    checks.append(
        Check(
            "网页端口",
            None,
            "已占用，请结合 web 服务状态确认"
            if connect("127.0.0.1", settings.ops.web_port)
            else "空闲，启动服务后检查网页",
        )
    )
    root = settings.db_path.parent
    while not root.exists():
        root = root.parent
    free = shutil.disk_usage(root).free
    checks.append(
        Check("磁盘余量", free >= 2 * 1024**3, f"剩余 {free / 1024**3:.1f} GiB；建议至少保留 2 GiB，模型另计")
    )
    if platform.system() == "Darwin":
        try:
            result = backend.runner(["pmset", "-g"])
            awake = result.returncode == 0 and re.search(r"(?m)^\s*sleep\s+0(?:\s|$)", result.stdout) is not None
            checks.append(Check("防睡眠", awake, "需要时手动执行 sudo pmset -c sleep 0"))
        except OSError:
            checks.append(Check("防睡眠", False, "无法读取 pmset，请检查系统电源设置"))
    checks.append(Check("当前内核", True, f"{KERNEL.schema}/{KERNEL.prompt}/{KERNEL.taxonomy}"))
    for db in [settings.db_path, *sorted((settings.db_path.parent / "personas").glob("*/twin.db"))]:
        if not db.is_file():
            continue
        try:
            with closing(sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
                schema = connection.execute("PRAGMA user_version").fetchone()[0]
                row = connection.execute("SELECT value FROM p_meta WHERE key='kernel:built'").fetchone()
                built = KernelVersion(**json.loads(row[0])) if row else None
                scope = rebuild_scope(built, KERNEL)
            checks.append(
                Check(
                    f"记忆内核 {db.parent.name}",
                    schema <= KERNEL.schema,
                    f"schema {schema}；当前 {KERNEL.prompt}/{KERNEL.taxonomy}；范围 {scope}；"
                    "详情运行 twin kernel status",
                )
            )
        except (sqlite3.Error, ValueError, TypeError):
            checks.append(Check("记忆内核", False, "无法读取版本；请检查数据库或从备份恢复"))
    if any(settings.db_path.parent.rglob("channels.json")):
        checks.append(Check("企业微信", None, "存在接入配置；同一机器人只能运行一个实例，迁移前先停旧实例"))
    return checks
