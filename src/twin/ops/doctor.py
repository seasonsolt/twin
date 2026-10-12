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
import time
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
    advice: str = ""

    def text(self) -> str:
        detail = self.detail + (f"；{self.advice}" if self.ok is False and self.advice else "")
        return f"{'–' if self.ok is None else '✓' if self.ok else '✗'} {self.name}：{detail}"


def tcp(host: str, port: int, timeout: float = 2) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
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
        Check("Python", sys.version_info >= (3, 12), platform.python_version(), "需要 Python 3.12 或更高版本"),
        Check(
            "架构",
            platform.machine() == "arm64" if platform.system() == "Darwin" else None,
            platform.machine(),
            "Mac 统一部署需要 arm64",
        ),
        Check(
            "ffmpeg",
            shutil.which("ffmpeg") is not None,
            "已安装" if shutil.which("ffmpeg") else "未找到",
            "运行 brew install ffmpeg",
        ),
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
    font_found = any(p.is_file() for p in fonts)
    checks.append(Check("中文字体", font_found, "已找到" if font_found else "未找到", "配置 [media] font_path"))
    checks.append(
        Check(
            "环境文件权限",
            paths.env.is_file() and stat.S_IMODE(paths.env.stat().st_mode) == 0o600,
            f"权限 {stat.S_IMODE(paths.env.stat().st_mode):04o}" if paths.env.is_file() else "文件不存在",
            "创建 env 并执行 chmod 600；密钥值不会显示",
        )
    )
    checks.append(
        Check(
            "数据目录权限",
            settings.db_path.parent.is_dir() and stat.S_IMODE(settings.db_path.parent.stat().st_mode) == 0o700,
            f"权限 {stat.S_IMODE(settings.db_path.parent.stat().st_mode):04o}"
            if settings.db_path.parent.is_dir()
            else "目录不存在",
            "创建数据目录并执行 chmod 700",
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
        if section.provider in {"anthropic", "cloudflare"}:
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
            checks.append(Check(name, None, "本机轻量后端" if section.provider == "hashing" else "未开启（可选）"))
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
            checks.append(
                Check(f"{name}连接", reachable, "TCP 可连接" if reachable else "TCP 未连接", "检查端点和服务")
            )
        if name == "LLM" and section.provider == "openai_compat":
            configured = bool(section.model and endpoint)
            checks.append(
                Check(
                    "LLM 配置",
                    configured,
                    "模型与端点已填写" if configured else "模型或端点缺失",
                    "填写 model 和 base_url",
                )
            )
        if probe:
            try:
                invoke_model(name, settings)
                checks.append(Check(f"{name}探针", True, "模型调用成功"))
            except Exception:
                checks.append(Check(f"{name}探针", False, "模型调用失败，请检查后端配置与凭据（详情已隐藏）"))
    for name, command in [
        ("转写", settings.asr.command if settings.asr.provider == "command" else None),
        ("认人", settings.vision.command),
        ("视频", settings.video.command if settings.video.provider != "none" else None),
    ]:
        if name in {"认人", "视频"} and not command:
            checks.append(Check(name, None, "未开启（可选）"))
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
                    "已找到" if exists else "未找到",
                    "算力包需先 twin compute install（P4 提供）；自定义命令请检查路径",
                )
            )
    web_loaded = False
    for service in services(paths, config, settings):
        try:
            result = backend.execute("status", service)
            if service.name == "web":
                web_loaded = result.returncode == 0
            checks.append(
                Check(
                    f"服务 {service.name}",
                    result.returncode == 0,
                    "已加载" if result.returncode == 0 else "未加载",
                    "运行 twin ops install-services 和 twin ops start",
                )
            )
        except OSError:
            checks.append(Check(f"服务 {service.name}", False, "服务管理器不可用，请检查用户会话"))
    deadline = time.monotonic() + 10
    listening = connect("127.0.0.1", settings.ops.web_port)
    while web_loaded and not listening:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(1, remaining))
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        listening = (
            tcp("127.0.0.1", settings.ops.web_port, timeout=min(2, remaining))
            if connect is tcp
            else connect("127.0.0.1", settings.ops.web_port)
        )
    checks.append(
        Check(
            "网页端口",
            listening if web_loaded else None,
            "已监听"
            if web_loaded and listening
            else "服务已加载，但端口未监听（已等待最多 10 秒）"
            if web_loaded
            else "已占用，web 服务未加载"
            if listening
            else "空闲，web 服务未加载",
            "运行 twin ops logs web 检查启动错误",
        )
    )
    root = settings.db_path.parent
    while not root.exists():
        root = root.parent
    free = shutil.disk_usage(root).free
    checks.append(Check("磁盘余量", free >= 2 * 1024**3, f"剩余 {free / 1024**3:.1f} GiB", "至少保留 2 GiB，模型另计"))
    if platform.system() == "Darwin":
        try:
            result = backend.runner(["pmset", "-g"])
            awake = result.returncode == 0 and re.search(r"(?m)^\s*sleep\s+0(?:\s|$)", result.stdout) is not None
            checks.append(
                Check(
                    "防睡眠",
                    awake,
                    "已关闭自动睡眠" if awake else "未确认关闭自动睡眠",
                    "手动执行 sudo pmset -c sleep 0",
                )
            )
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
                    f"schema {schema}；当前 {KERNEL.prompt}/{KERNEL.taxonomy}；范围 {scope}",
                    "详情运行 twin kernel status",
                )
            )
        except (sqlite3.Error, ValueError, TypeError):
            checks.append(Check("记忆内核", False, "无法读取版本；请检查数据库或从备份恢复"))
    if any(settings.db_path.parent.rglob("channels.json")):
        checks.append(Check("企业微信", None, "存在接入配置；同一机器人只能运行一个实例，迁移前先停旧实例"))
    return checks
