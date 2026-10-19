"""``twin`` command line. Results go to stdout; progress, warnings and errors go to stderr."""

from __future__ import annotations

import datetime as dt
import hashlib
import ipaddress
import json
import logging
import os
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import webbrowser
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import replace
from functools import wraps
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, Literal

import typer

from .config import Settings, check_config_rename, load_settings, make_embedder, make_llm
from .egress import egress_status
from .embed import Embedder, EmbedError
from .identity import Identity
from .llm import CallTally, LLMError
from .media.schema import MediaScript
from .ops.envfile import load_env_file, selected_env_file
from .ops.paths import TwinPaths
from .persona.chat import PersonaChat, index_persona
from .persona.coverage import coverage_report
from .persona.coverage import report_markdown as coverage_markdown
from .persona.dimensions import requires_consent
from .persona.gate import MemoryUpdating
from .persona.kernel import KERNEL, rebuild_scope
from .persona.profile import (
    KERNEL_STALE_NOTICE,
    STALE_PROFILE_NOTICE,
    build_profile,
    consented_facets,
    pending_chunks,
    profile_stale,
    source_memories,
    stale_reason,
)
from .persona.schema import SOURCE_KIND_LABELS, ChatTurn, SourceKind
from .persona.sources import MEMORY_KIND_LABELS, parse_note, parse_source
from .persona.store import NewerStoreError, PersonaStore
from .persona.text import SUPPORTED_SUFFIXES
from .usage import BudgetExceeded, UsageRecorder, active_recorder, call_stage, failure_directory, record_usage
from .util import RenameError, open_private, private_directory

if TYPE_CHECKING:
    from .evals.persona_runtime import ProfileCache

DEFAULT_CONFIG = Path("twin.toml")
CONFIG_TEMPLATE = """# 通用个人分身：身份 → 记忆资料 → 服务。密钥仅从环境变量读取。
target_name = "本人"
target_aliases = []
db_path = "data/twin.db"
max_workers = 4

# [kernel]
# auto_rebuild = true
# max_auto_rebuild_chunks = 400

[media]
# font_path = "/path/to/chinese-font.ttc" # 视频导出；留空自动查找系统中文字体

[llm]
# egress = "local" 或 "external"：未声明时按提供方/主机推断；外部服务按配置使用，界面如实标出。
# 本机代理若转发到境外 API，应设置 egress = "external"。
provider = "openai_compat"
# 请设置内网模型名及端点；未配置不会调用公网默认端点。
# model = "your-model"
# base_url = "http://127.0.0.1:8000/v1"
api_key_env = "TWIN_LLM_KEY"
# hedge_after_s = 2.5 # 流式聊天首 token 超时后只追加一次竞速请求；0 禁用
# reasoning_effort_extract = "low"  # 提取/合并的思考档位；不写则沿用 reasoning_effort，但 none 自动改为 low

# 可选聊天专用模型：不配置时沿用 [llm]；提取、构建、问卷及默认评委仍使用 [llm]。
# [llm] 和 [chat_llm] 都支持 extra_body，原样传给 OpenAI 兼容请求。
# DeepSeek 只支持 json_object；不要设置 reasoning_effort（包括 none），改用 extra_body。
# [chat_llm]
# provider = "openai_compat"
# model = "deepseek-flash"
# base_url = "https://api.deepseek.com"
# api_key_env = "TWIN_LLM_KEY_DEEPSEEK"
# json_mode = "json_object"
# extra_body = { thinking = { type = "disabled" } }
# hedge_after_s = 2.5 # 配置 [chat_llm] 时使用这里的值；流式请求不使用 JSON mode

[embed]
# egress = "local" 或 "external"：hashing 默认为本机；外部向量服务按配置使用。
# 本机转发代理应设置 egress = "external"。
provider = "hashing"
api_key_env = "TWIN_EMBED_KEY"

# 工作模式的网页搜索和读网页，走 DeepSeek 的 /v1/tools/search 和 /v1/tools/fetch（网页由 DeepSeek 抓取）。
# 默认开启：密钥用 TWIN_SEARCH_KEY；没设时，若 [chat_llm] 或 [llm] 也在 api.deepseek.com，就沿用它的密钥。
# 两者都没有时工作模式不带搜索。搜索词和要读的链接会发给 DeepSeek，状态里列为外部服务。
# [search]
# enabled = true
# api_key_env = "TWIN_SEARCH_KEY"
# count = 8 # 每次搜索返回几条，1-50

# 企业微信智能机器人在分身档案 → 接入 → 绑定，见 docs/GUIDE.md。

# [api] # 对外服务：令牌值仅放环境变量，至少 32 个字符，见 docs/SERVICE.md。
# token_env = "TWIN_API_TOKEN"
# rate_per_minute = 30 # 每个令牌每分钟最多请求数（滑动窗口）。

# [auth] # 公网网页必须启用；默认 false 为无登录、管理员模式（仅本机开发）。
# enabled = true
# allowed_domains = ["xjjk.com"] # 只匹配 @ 后的完整域名，不匹配子域名
# allowed_emails = ["seasonsolt@gmail.com"]
# admin_emails = ["zhangxun@xjjk.com", "qianjinwen@xjjk.com"] # 也匹配 SSO 账号名 zhangxun；可写 sso:<subject>
# session_days = 30
# max_personas_per_member = 3   # 0 = 不限
# [auth.smtp] # 465 使用 SSL，587 使用 STARTTLS；启用 auth 时必填
# host = "smtp.example.com"
# port = 465
# username = "your-smtp-account"
# from_address = "twin@example.com"
# from_name = "twin"
# password_env = "TWIN_SMTP_PASSWORD" # 密码只在环境变量，绝不写入文件
# 或借用同站另一个应用的登录（单点登录，不发邮件、不用 [auth.smtp]），见 deploy/daw/README.md：
# provider = "sso"  # 写在 [auth] 里；能登录那个应用的人都能进入，管理员按 SSO 账号名或 sso:<subject> 匹配 admin_emails
# [auth.sso]
# me_url = "http://127.0.0.1:8765/api/auth/me"  # 带着对方的会话 cookie 询问身份：200 已登录，401 未登录
# cookie = "audio_studio_session"
# login_url = "/login?next=/twin/"  # 未登录时浏览器跳往的本站路径
# cache_seconds = 60

# [video] # 可选真人视频通道，默认关闭
# provider = "remote" # 执行配置的 SSH 或本机任务
# command 必须配置；host 省略或为空时本机执行并复制输出，否则使用 SSH/scp；出境声明与契约见 docs/MEDIA.md

# [avatar] # 2D 预置形象；或用 vrm_path 指定 3D 模型。
# preset = "chestnut" # 可选 chestnut（栗）、wave（澜）、bun（禾）、stone（石）、silver（岚）。

# 可选 [tts] / [asr] 配置见 docs/MEDIA.md；下面为可取消注释的配置节。
# [tts]
# voice_dir = "data/voices" # 可选：发布本人参考 WAV；与 TTS 容器只读 /voices 挂载共享。
# egress = "local" 或 "external"：silent 默认为本机；外部朗读服务按配置使用。
# 本机转发代理应设置 egress = "external"。
# provider = "silent"

# 音视频记忆 + 合成语音评测的 HTTP 识别（与下面命令示例二选一）。
# [asr]
# egress = "local" # 或 "external"；外部服务/本机转发代理按实际情况声明。
# provider = "openai_compat" # 也支持 cloudflare，见 docs/MEDIA.md。
# model = "your-asr-model"
# base_url = "http://127.0.0.1:8001/v1"
# api_key_env = "TWIN_ASR_KEY"
# language = "zh"

# 音视频记忆的命令识别：stdin JSON audio/language/diarize，已有本人声音时附 reference。
# stdout 最后一行 ok/segments（可附 speaker）、speakers（id/seconds/similarity）；旧驱动仍可用。
# [asr]
# provider = "command"
# command = "python /path/to/transcribe.py"
# language = "zh"
# egress = "local"

# 账号录音库（网页「我的分身 → 录音库」）：上传后预留的安全余量与同时排队的文件数。
# 批次额度：录音库在任意 batch_hours 小时内最多花 batch_tokens 个大模型 token（转写校对与团队分身重建，
# 新录音、重试、重建都计入）；用完后校对和重建暂停，页面会提示，窗口腾出后自动继续。0 表示不限。
# 管理员也可以在网页「系统 → 模型与 Token」里临时改这两项（存在 data/system.json，立即生效）。
# [library]
# headroom_gb = 20
# max_pending = 20
# batch_tokens = 20000000
# batch_hours = 24

# 视频形象候选（可选）：stdin video/intervals/out_dir/max_candidates；stdout ok/candidates。
# 仅返回 out_dir 内的普通图片，详情与可选 face_box 见 docs/MEDIA.md。
# [vision]
# provider = "command"
# command = "python /path/to/portraits.py"
# egress = "local" # 命令调用外部服务时改为 external。

# [[judges]]
# egress = "local" 或 "external"：每位评委也单独分类，外部服务按配置使用。
# 本机转发代理应设置 egress = "external"。
# provider = "openai_compat"
# model = "your-judge-model"
# base_url = "http://127.0.0.1:8000/v1"
"""
app = typer.Typer(
    name="twin",
    help="通用个人分身：身份 → 记忆资料 → 服务。",
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_show_locals=False,
)
ConfigOption = Annotated[Path | None, typer.Option("--config", "-c", help="配置文件路径")]
_usage_output: ContextVar[Path | None] = ContextVar("cli_usage_output", default=None)
_WILDCARD_HOSTS = frozenset({"0.0.0.0", "::", ""})


def _say(message: str) -> None:
    typer.echo(message)


def _progress(message: str) -> None:
    typer.echo(message, err=True)


def _fail(message: str) -> typer.Exit:
    typer.echo(f"错误：{message}", err=True)
    return typer.Exit(code=1)


def _backend_errors() -> tuple[type[Exception], ...]:
    """Base exceptions of the model / embedding SDKs and of the claude CLI subprocess. An SDK exception can only
    exist if its module was imported, so the SDKs are looked up in ``sys.modules`` instead of being imported."""
    errors: list[type[Exception]] = [subprocess.SubprocessError]
    for module, name in (("anthropic", "AnthropicError"), ("openai", "OpenAIError")):
        if module in sys.modules:
            errors.append(getattr(sys.modules[module], name))
    return tuple(errors)


@contextmanager
def _errors() -> Iterator[None]:
    try:
        yield
    except (ValueError, OSError, sqlite3.Error, NewerStoreError, LLMError, EmbedError, BudgetExceeded) as e:
        raise _fail(str(e)) from e
    except Exception as e:
        if not isinstance(e, _backend_errors()):
            raise
        raise _fail(f"调用模型服务失败：{type(e).__name__}: {e}") from e


def _config_path(ctx: typer.Context) -> Path | None:
    return ctx.obj if isinstance(ctx.obj, Path) else None


def _settings(ctx: typer.Context) -> Settings:
    path, source = _config_path(ctx), "--config"
    if path is None and os.environ.get("TWIN_CONFIG"):
        path, source = Path(os.environ["TWIN_CONFIG"]), "环境变量 TWIN_CONFIG"
    if path is not None and not path.is_file():
        raise _fail(f"找不到配置文件 {path}（来自{source}；可以先运行 `twin init {path}` 生成）")
    if path is None:
        path = DEFAULT_CONFIG if DEFAULT_CONFIG.is_file() else TwinPaths.from_env().config
        if not path.is_file():
            _progress(f"提示：没有找到配置文件 {path}，使用默认配置（可运行 `twin init` 生成）")
    with _errors():
        settings = load_settings(path)
    if recorder := active_recorder():
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        _usage_output.set(settings.db_path.parent / "usage" / f"{ctx.command.name}-{stamp}")
        recorder.pricing = dict(settings.pricing)
        if recorder.max_cost_usd is None:
            recorder.max_cost_usd = settings.budget.max_cost_usd
        if recorder.max_cost_usd is not None:
            models = [settings.llm, settings.effective_chat_llm, *settings.judges]
            unpriced = {model.model or "claude-opus-5-5" for model in models} - settings.pricing.keys()
            if settings.embed.provider != "hashing" and settings.embed.model not in settings.pricing:
                unpriced.add(settings.embed.model)
            if unpriced:
                _progress("警告：以下模型费用未知，无法纳入预算：" + "、".join(sorted(unpriced)))
    return settings


def _require_working_calls(llm: CallTally, stage: str) -> None:
    try:
        llm.require_working_calls(stage)
    except LLMError as error:
        raise _fail(str(error)) from error


def _llm(settings: Settings, *, chat: bool = False) -> CallTally:
    config = settings.effective_chat_llm if chat else settings.llm
    try:
        llm = make_llm(config, "chat_llm") if chat and settings.chat_llm is not None else make_llm(config)
    except Exception as e:
        raise _fail(
            f"无法初始化大模型后端 {config.provider}：{e}（密钥只能通过环境变量提供，见 README 的配置一节）"
        ) from e
    return CallTally(llm)


def _embedder(settings: Settings) -> Embedder:
    try:
        return make_embedder(settings.embed)
    except Exception as e:
        raise _fail(f"无法初始化向量化后端 {settings.embed.provider}：{e}") from e


def _date(value: str, option: str) -> dt.date:
    try:
        return dt.date.fromisoformat(value.strip())
    except ValueError as e:
        raise typer.BadParameter(f"日期格式应为 YYYY-MM-DD，收到 {value!r}", param_hint=option) from e


def _optional_date(value: str | None, option: str) -> dt.date | None:
    return None if value is None else _date(value, option)


def _write(path: Path, text: str) -> None:
    """Write an owner-only (0600) file: outputs quote personal memories and profile items."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open_private(path) as f:
        f.write(text)


def _command_usage[**P, R](stage: str) -> Callable[[Callable[P, R]], Callable[P, R]]:
    def decorate(fn: Callable[P, R]) -> Callable[P, R]:
        @wraps(fn)
        def command(*args: P.args, **kwargs: P.kwargs) -> R:
            override = kwargs.get("max_cost_usd")
            recorder = UsageRecorder(max_cost_usd=override if isinstance(override, (int, float)) else None)
            token = _usage_output.set(None)
            failed = False
            try:
                with _errors(), record_usage(recorder), call_stage(stage):
                    return fn(*args, **kwargs)
            except Exception:
                failed = True
                if recorder.stop is not None:
                    raise _fail(str(recorder.stop)) from recorder.stop
                raise
            finally:
                if (directory := _usage_output.get()) is not None and recorder.rows:
                    if failed:
                        directory = failure_directory(directory)
                        _usage_output.set(directory)
                    recorder.write(directory)
                if stage == "build":
                    typer.echo(recorder.chinese_summary(), err=failed)
                    if (directory := _usage_output.get()) is not None and recorder.rows:
                        typer.echo(f"调用追踪：{directory}（calls.jsonl、usage.json）", err=failed)
                _usage_output.reset(token)

        return command

    return decorate


@app.callback()
def main(
    ctx: typer.Context,
    config: ConfigOption = None,
    home: Annotated[Path | None, typer.Option("--home", help="部署根目录（同 TWIN_HOME）")] = None,
) -> None:
    with _errors():
        if home is not None:
            os.environ["TWIN_HOME"] = str(home)
        env = selected_env_file()
        try:
            load_env_file(env)
        except (ValueError, OSError) as error:
            if ctx.invoked_subcommand != "doctor":
                raise
            ctx.meta["env_error"] = str(error)
        check_config_rename()
    ctx.obj = config


@app.command()
def init(
    ctx: typer.Context,
    path: Annotated[Path | None, typer.Argument(help="要生成的配置文件路径（默认 --config 或 ./twin.toml）")] = None,
    force: Annotated[bool, typer.Option("--force", help="覆盖已存在的文件")] = False,
    profile: Annotated[
        Literal["mac-unified", "split", "minimal"] | None, typer.Option("--profile", help="部署档位")
    ] = None,
) -> None:
    """生成带中文注释的 twin.toml 配置模板。"""
    target = path or _config_path(ctx) or (TwinPaths.from_env().config if profile == "mac-unified" else DEFAULT_CONFIG)
    if target.exists() and not force:
        raise _fail(f"{target} 已存在；如需覆盖请加 --force")
    with _errors():
        template = CONFIG_TEMPLATE
        if profile == "minimal":
            template = (
                'target_name = "本人"\ndb_path = "data/twin.db"\n\n[llm]\nprovider = "openai_compat"\n'
                'api_key_env = "TWIN_LLM_KEY"\n# model = "your-model"\n'
                '# base_url = "http://127.0.0.1:8000/v1"\n\n[embed]\nprovider = "hashing"\n'
            )
        if profile == "mac-unified":
            paths = TwinPaths.from_env()
            template = template.replace(
                'db_path = "data/twin.db"', "db_path = " + json.dumps(str(paths.data / "twin.db"))
            )
            template += (
                "\n# 默认开启文字聊天与录音转写（安装脚本运行 twin compute install asr-funasr 写入 [asr]）；\n"
                "# 朗读真人音色、认人和口型视频默认关闭，按需开启，详见 docs/MEDIA.md。\n"
            )
            private_directory(paths.data)
        private_directory(target.parent)
        _write(target, template)
    _say(f"已生成配置文件 {target}。请先修改 target_name 和 [llm] 部分，密钥通过环境变量提供。")


compute_app = typer.Typer(help="安装与管理本机转写算力包。", no_args_is_help=True)
app.add_typer(compute_app, name="compute")


def _compute_config(ctx: typer.Context) -> Path:
    return _config_path(ctx) or Path(os.environ.get("TWIN_CONFIG", str(DEFAULT_CONFIG)))


@compute_app.command("list")
def compute_list() -> None:
    """列出仓库提供的算力包。"""
    from .ops.compute import discover

    with _errors():
        for pack in discover():
            _say(f"{pack.name} {pack.version}（{pack.kind}；{', '.join(pack.platforms)}）")


@compute_app.command("status")
def compute_status(ctx: typer.Context) -> None:
    """查看安装、配置与模型校验状态。"""
    from .ops.compute import discover, status

    with _errors():
        for pack in discover():
            _say(status(pack, _compute_config(ctx)))


@compute_app.command("install")
def compute_install(
    ctx: typer.Context,
    pack: Annotated[str, typer.Argument(help="算力包名称")],
    download_models: Annotated[bool, typer.Option("--download-models", help="允许下载缺失的模型")] = False,
    force: Annotated[bool, typer.Option("--force", help="重建当前版本环境；不覆盖手写配置")] = False,
) -> None:
    """校验、安装转写包并启用当前配置。"""
    from .ops.compute import get_pack, install

    with _errors():
        install(get_pack(pack), _compute_config(ctx), download_models=download_models, force=force, progress=_say)
        _say(
            "重启网页后生效（本地：Ctrl-C 后重新 ./scripts/local-up.sh；常驻：twin ops restart）；"
            "已上传但未转写的录音点“重新转写”或“重试”。"
        )


@compute_app.command("remove")
def compute_remove(ctx: typer.Context, pack: Annotated[str, typer.Argument()]) -> None:
    """移除算力包及工具写入的配置，保留模型缓存。"""
    from .ops.compute import get_pack, remove

    with _errors():
        _say(remove(get_pack(pack), _compute_config(ctx)))


ops_app = typer.Typer(help="装机、服务托管与备份恢复。", no_args_is_help=True)
app.add_typer(ops_app, name="ops")


def _ops_config(ctx: typer.Context) -> Path:
    return _config_path(ctx) or Path(
        os.environ.get("TWIN_CONFIG", DEFAULT_CONFIG if DEFAULT_CONFIG.is_file() else TwinPaths.from_env().config)
    )


def _ops_action(ctx: typer.Context, action: str, name: str | None) -> None:
    from .ops.service import manager, services

    with _errors():
        paths = TwinPaths.from_env()
        settings = _settings(ctx)
        backend = manager(paths)
        items = services(paths, _ops_config(ctx), settings)
        if name:
            items = [item for item in items if item.name == name]
            if not items:
                raise ValueError("服务名称不存在")
        if action == "install-services":
            backend.install(items)
            _say("已写入用户服务配置")
            return
        for item in items:
            if action == "logs":
                path = paths.service_log(item.name)
                _say(f"{item.name}：{path}")
                if path.is_file():
                    with path.open("rb") as stream:
                        stream.seek(max(0, path.stat().st_size - 16384))
                        _say(stream.read().decode("utf-8", errors="replace"))
                else:
                    _say("暂无日志")
            else:
                result = backend.execute(action, item)
                _say(
                    f"{item.name}：{'已加载' if result.returncode == 0 else '未加载或不可用'}"
                    if action == "status"
                    else f"{item.name}：操作完成"
                )


@ops_app.command("install-services")
def ops_install(ctx: typer.Context) -> None:
    """写入服务文件并重新加载用户配置。"""
    _ops_action(ctx, "install-services", None)


@ops_app.command("start")
def ops_start(ctx: typer.Context, name: Annotated[str | None, typer.Argument()] = None) -> None:
    """启动服务。"""
    _ops_action(ctx, "start", name)


@ops_app.command("stop")
def ops_stop(ctx: typer.Context, name: Annotated[str | None, typer.Argument()] = None) -> None:
    """停止服务。"""
    _ops_action(ctx, "stop", name)


@ops_app.command("restart")
def ops_restart(ctx: typer.Context, name: Annotated[str | None, typer.Argument()] = None) -> None:
    """重新启动服务。"""
    _ops_action(ctx, "restart", name)


@ops_app.command("status")
def ops_status(ctx: typer.Context, name: Annotated[str | None, typer.Argument()] = None) -> None:
    """查看服务状态。"""
    _ops_action(ctx, "status", name)


@ops_app.command("logs")
def ops_logs(ctx: typer.Context, name: Annotated[str | None, typer.Argument()] = None) -> None:
    """查看最近的服务日志。"""
    _ops_action(ctx, "logs", name)


@ops_app.command("backup")
def ops_backup(ctx: typer.Context, reason: Annotated[str, typer.Option("--reason")] = "daily") -> None:
    """创建私有数据快照。"""
    from .ops.backup import backup

    with _errors():
        settings = _settings(ctx)
        _say(f"备份完成：{backup(TwinPaths.from_env(), settings.db_path.parent, _ops_config(ctx), reason)}")


@ops_app.command("restore")
def ops_restore(ctx: typer.Context, directory: Annotated[Path, typer.Argument()]) -> None:
    """确认服务停止后恢复快照。"""
    from .ops.backup import restore
    from .ops.service import manager, services

    with _errors():
        paths = TwinPaths.from_env()
        settings = _settings(ctx)
        backend = manager(paths)
        stopped = all(backend.stopped(item) for item in services(paths, _ops_config(ctx), settings))
        restore(directory, settings.db_path.parent, _ops_config(ctx), services_stopped=stopped)
        _say("恢复完成；请检查配置中的绝对路径，再运行 twin ops start")


@app.command("doctor")
def doctor_command(
    ctx: typer.Context,
    probe: Annotated[bool, typer.Option("--probe", help="实际调用模型，可能产生费用")] = False,
    local: Annotated[bool, typer.Option("--local", help="仓库本地验证：不检查常驻服务和防睡眠")] = False,
) -> None:
    """检查部署；默认不调用模型。"""
    from .ops.doctor import inspect_installation
    from .ops.service import manager

    with _errors():
        paths = replace(TwinPaths.from_env(), env=selected_env_file())
        try:
            settings = load_settings(_ops_config(ctx))
        except (ValueError, OSError):
            _say("✗ 配置校验：无法解析配置，请检查 twin.toml（详情已隐藏）")
            raise typer.Exit(1) from None
        checks = inspect_installation(paths, settings, _ops_config(ctx), manager(paths), probe=probe, local=local)
        if ctx.meta.get("env_error"):
            _say(f"✗ 环境文件：{ctx.meta['env_error']}")
        for check in checks:
            _say(check.text())
        if ctx.meta.get("env_error") or any(check.ok is False for check in checks):
            raise typer.Exit(1)


def _is_loopback(host: str) -> bool:
    name = host.strip().strip("[]").lower()
    if name == "localhost":
        return True
    try:
        return ipaddress.ip_address(name).is_loopback
    except ValueError:
        return False


def _open_when_started(server: Any, url: str) -> None:
    deadline = time.monotonic() + 30
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.1)
    if server.started:
        webbrowser.open(url)


def _serve(application: Any, host: str, port: int, url: str, open_browser: bool, title: str = "网页界面") -> None:
    """Bind first, so a busy port is reported in Chinese before uvicorn starts, then serve until Ctrl-C."""
    import uvicorn

    address = host.strip().strip("[]")
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    try:
        sock = socket.create_server((address, port), family=family)
    except OSError as e:
        raise _fail(f"无法在 {host}:{port} 上启动{title}：{e}（端口可能已被占用，可以用 --port 换一个端口）") from e
    server = uvicorn.Server(uvicorn.Config(application, log_level="warning"))
    _say(f"{title}：{url}（按 Ctrl-C 停止）")
    if open_browser:
        threading.Thread(target=_open_when_started, args=(server, url), daemon=True).start()
    with sock:
        server.run(sockets=[sock])


@app.command()
def ui(
    ctx: typer.Context,
    host: Annotated[
        str, typer.Option("--host", help="监听地址；默认只监听本机 127.0.0.1，改成其他地址会让同一网络里的人也能访问")
    ] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", help="端口")] = 8765,
    open_browser: Annotated[bool, typer.Option("--open", help="启动后自动用浏览器打开")] = False,
    allow_host: Annotated[
        list[str] | None,
        typer.Option(
            "--allow-host",
            help="额外接受的主机名（可重复），用于反向代理或隧道后面的公网域名；只放行主机名，不改变监听地址。"
            "公网访问前必须配置 [auth] enabled = true，并配置 SMTP 邮箱验证码登录或同站单点登录",
        ),
    ] = None,
) -> None:
    """启动本机网页界面：问卷、资料导入、人格档案、完成度和聊天。

    数据都留在本机：默认只监听 127.0.0.1，页面不加载任何外部资源。
    """
    settings = _settings(ctx)
    from .web import create_app

    # Bot connections and first single sign-on logins are worth keeping in the service log; the rest stays quiet.
    for name in ("twin.channels", "twin.auth"):
        service_logger = logging.getLogger(name)
        if not service_logger.handlers:
            handler = logging.StreamHandler(sys.stderr)
            handler.setLevel(logging.INFO)
            handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
            service_logger.addHandler(handler)
        service_logger.setLevel(logging.INFO)
        service_logger.propagate = False

    address = host.strip().strip("[]")
    extra_hosts: tuple[str, ...] = ()
    if not _is_loopback(host):
        if address not in _WILDCARD_HOSTS:
            extra_hosts = (address,)
        bar = "!" * 72
        _progress(
            "\n".join(
                [
                    bar,
                    f"警告：网页界面将监听 {host}:{port}，不只是本机可以访问。",
                    "已启用邮箱登录；只有允许的用户可访问其分身，管理员可管理全部分身。"
                    if settings.auth.enabled
                    else "同一网络里能连到这台机器的人，不需要登录就能查看个人资料、人格档案和聊天结果，",
                    "还能导入转写、修改审核结果、发起构建和聊天（会调用模型、产生费用）。",
                    "服务只接受用 localhost、127.0.0.1、[::1]"
                    + (f" 或 {address}" if extra_hosts else "")
                    + " 作为主机名的请求。",
                    "如果不是确实需要，请去掉 --host（默认只监听 127.0.0.1）。",
                    bar,
                ]
            )
        )
    url_host = "127.0.0.1" if address in _WILDCARD_HOSTS else (f"[{address}]" if ":" in address else address)
    with _errors():
        application = create_app(settings, allowed_hosts=(*extra_hosts, *(allow_host or ())))
    _serve(application, host, port, f"http://{url_host}:{port}", open_browser)


@app.command("api")
def api_command(
    ctx: typer.Context,
    host: Annotated[str, typer.Option("--host", help="监听地址，默认只监听本机")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", help="端口")] = 8780,
    allow_host: Annotated[list[str] | None, typer.Option("--allow-host", help="额外接受的主机名，可重复")] = None,
    allow_remote: Annotated[bool, typer.Option("--allow-remote", help="明确允许非本机监听，远程访问须用 TLS")] = False,
) -> None:
    """启动 Bearer 令牌保护的 HTTP API，见 docs/SERVICE.md。"""
    from .api import api_token, create_api

    settings = _settings(ctx)
    with _errors():
        token = api_token(settings)
    if not _is_loopback(host) and not allow_remote:
        raise _fail("非本机监听需显式指定 --allow-remote；默认仅监听 127.0.0.1")
    if not _is_loopback(host):
        _progress("警告：API 将允许远程连接；请使用可信网络和 TLS 代理保护 Bearer 令牌")
    address = host.strip().strip("[]")
    url_host = "127.0.0.1" if address in _WILDCARD_HOSTS else (f"[{address}]" if ":" in address else address)
    application = create_api(settings, token=token, allowed_hosts=allow_host or ())
    _serve(application, host, port, f"http://{url_host}:{port}", False, title="服务 API")


@app.command("mcp")
def mcp_command(ctx: typer.Context) -> None:
    """启动 stdio MCP 服务，不监听网络端口，见 docs/SERVICE.md。"""
    from .mcp_server import create_mcp_server

    settings = _settings(ctx)
    try:
        create_mcp_server(settings).run(transport="stdio")
    except Exception:
        raise _fail("MCP 服务暂时不可用，请检查配置后重试") from None


demo_app = typer.Typer(help="导入完全虚构的示例分身。", no_args_is_help=True)
app.add_typer(demo_app, name="demo")


@demo_app.command("seed")
def demo_seed(
    ctx: typer.Context,
    force: Annotated[bool, typer.Option("--force", help="重新导入示例来源，保留自行添加的资料")] = False,
) -> None:
    """创建或复用“示例·林舟”；只导入资料，不调用模型。请先停止网页服务。"""
    from .ops.demo import seed_demo

    with _errors():
        persona_id, count = seed_demo(_settings(ctx), force=force)
    _say(f"示例·林舟（{persona_id}）：本次导入 {count} 份虚构示例资料。")
    _say("启动网页后切换到“示例·林舟”，等待自动整理完成再提问（整理会调用配置的模型）。")
    _say(f"也可运行 twin kernel rebuild --persona {persona_id} 手动整理此分身。")


persona_app = typer.Typer(
    help="通用数字分身：导入问卷、聊天记录、访谈、文档 → 人格档案 → 完成度 → 聊天。", no_args_is_help=True
)
app.add_typer(persona_app, name="persona")


def _persona_store(settings: Settings) -> PersonaStore:
    with _errors():
        return PersonaStore(settings.db_path)


identity_app = typer.Typer(help="查看配置的只读身份与出境状态。", no_args_is_help=True)
app.add_typer(identity_app, name="identity")


@identity_app.command("show")
def identity_show(ctx: typer.Context) -> None:
    """查看名字、别名、预置音色、预置形象与出境分类。"""
    from .persona.store import stored_avatar

    settings = _settings(ctx)
    identity = Identity(
        name=settings.target_name,
        aliases=settings.target_aliases,
        voice=settings.tts.voice,
        avatar=stored_avatar(settings.db_path, settings.avatar.preset),
    )
    _say(f"名字：{identity.name}")
    _say(f"别名：{'、'.join(identity.aliases) or '—'}")
    _say(f"音色：{identity.voice}（预置音色）")
    _say(f"形象：{identity.avatar}（风格化插画，不使用照片）")
    _say("出境：类型 | 提供方 | 主机 | 本机/外部 | 声明/推断")
    for index, row in enumerate(egress_status(settings)):
        kind = f"llm（评委 {index - 4}）" if 5 <= index < 5 + len(settings.judges) else row["kind"]
        _say(
            f"{kind} | {row['provider']} | {row['host'] or '未知'} | "
            f"{'外部' if row['external'] else '本机'} | {'声明' if row['declared'] else '推断'}"
        )


kernel_app = typer.Typer(help="查看和重建记忆内核。", no_args_is_help=True)
app.add_typer(kernel_app, name="kernel")


def _kernel_personas(settings: Settings) -> list[tuple[str, Settings]]:
    from .web.jobs import JobManager, describe_error
    from .web.personas import Personas

    registry = Personas(settings, JobManager(settings.max_workers, describe_error))
    return [
        (entry["id"], registry.settings_for(entry["id"]))
        for entry in registry.data["personas"]
        if not entry.get("deleted_at")
    ]


@kernel_app.command("status")
def kernel_status(ctx: typer.Context) -> None:
    with _errors():
        for persona_id, settings in _kernel_personas(_settings(ctx)):
            with _persona_store(settings) as store:
                built = store.kernel_built()
                scope = rebuild_scope(built, KERNEL)
                _say(f"分身：{persona_id}")
                _say(f"当前内核：{KERNEL.schema}/{KERNEL.prompt}/{KERNEL.taxonomy}")
                _say(f"库内内核：{built.schema}/{built.prompt}/{built.taxonomy}" if built else "库内内核：未记录")
                count = pending_chunks(store, settings) if scope != "none" else 0
                _say(f"schema：{store.schema_version()}  范围：{scope}  待重抽分段：{count}")


@kernel_app.command("snapshots")
def kernel_snapshots(ctx: typer.Context) -> None:
    """列出内核升级前自动保存的快照（每个分身保留最近 3 份）。"""
    from .persona.store import list_snapshots

    with _errors():
        for persona_id, settings in _kernel_personas(_settings(ctx)):
            found = list_snapshots(settings.db_path)
            _say(f"分身 {persona_id}：{'无快照' if not found else ''}")
            for path in reversed(found):
                _say(f"  {path}（{path.stat().st_size / 1024**2:.1f} MiB）")


@kernel_app.command("restore")
def kernel_restore(
    ctx: typer.Context,
    snapshot: Annotated[Path, typer.Argument(help="twin kernel snapshots 列出的快照文件")],
    persona: Annotated[str, typer.Option("--persona")] = "default",
    yes: Annotated[bool, typer.Option("--yes", help="确认已停止网页并覆盖当前数据")] = False,
) -> None:
    """用快照覆盖分身数据；覆盖前自动再快照一次当前数据。"""
    from .persona.store import restore_snapshot

    selected = [resolved for pid, resolved in _kernel_personas(_settings(ctx)) if pid == persona]
    if not selected:
        raise _fail("分身不存在")
    if not yes:
        raise _fail("恢复会覆盖该分身的当前数据：先停止网页（Ctrl-C 或 twin ops stop），再加 --yes")
    with _errors():
        before = restore_snapshot(snapshot, selected[0].db_path)
    _say(f"已恢复分身 {persona}" + (f"；恢复前的数据另存为 {before}" if before else ""))
    _say(
        "用当前代码启动会再次按新内核整理；要继续用旧内核，先切回旧版本代码（如 git switch --detach <旧版本>）再启动。"
    )


@kernel_app.command("rebuild")
@_command_usage("build")
def kernel_rebuild(
    ctx: typer.Context,
    persona: Annotated[str | None, typer.Option("--persona")] = None,
    all_personas: Annotated[bool, typer.Option("--all")] = False,
    yes: Annotated[bool, typer.Option("--yes")] = False,
) -> None:
    if all_personas and persona:
        raise _fail("--persona 和 --all 不能同时使用")
    settings = _settings(ctx)
    selected = [
        (pid, resolved) for pid, resolved in _kernel_personas(settings) if all_personas or pid == (persona or "default")
    ]
    if not selected:
        raise _fail("分身不存在")
    for pid, resolved in selected:
        with _persona_store(resolved) as store:
            count = pending_chunks(store, resolved)

            if count > settings.kernel.max_auto_rebuild_chunks and not yes:
                raise _fail(f"分身 {pid} 待重抽 {count} 个分段，超过费用闸；请确认后加 --yes")
    for pid, resolved in selected:
        with _persona_store(resolved) as store:
            resolved = resolved.model_copy(
                update={"target_name": store.get_meta("identity:name") or resolved.target_name}
            )
            report = build_profile(store, _llm(resolved), resolved, _progress)
            index_persona(store, _embedder(resolved), resolved, _progress)
            _say(f"分身 {pid}：{report.change_summary()}")
            if report.failures:
                raise _fail("部分记忆处理失败，请重试")


@persona_app.command("import")
def persona_import(
    ctx: typer.Context,
    paths: Annotated[list[Path], typer.Argument(help="要导入的文件，可以多个")],
    kind: Annotated[SourceKind | None, typer.Option("--kind", help="资料类型（默认自动识别）")] = None,
    date: Annotated[str | None, typer.Option("--date", help="资料日期（问卷、访谈、文档；默认从文件名识别）")] = None,
) -> None:
    """导入资料。同一个文件内容不变时重复导入只会覆盖，不会重复。"""
    settings = _settings(ctx)
    when = _optional_date(date, "--date")
    with _persona_store(settings) as store:
        for path in paths:
            if not path.is_file():
                raise _fail(f"找不到文件 {path}")
            if path.name.startswith(".") or path.suffix.lower() not in SUPPORTED_SUFFIXES:
                _say(f"跳过 {path.name}：隐藏文件或不支持的文件类型")
                continue
            try:
                parsed = parse_source(kind, path, settings, when)
            except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as e:
                raise _fail(f"{path}：{e}") from e
            new = store.put_source(parsed)
            s = parsed.source
            span = f"{s.first_date or '—'} 至 {s.last_date or '—'}"
            # Only a gated facet left blank keeps the twin from learning it; others are just unanswered.
            withheld = [f for f in s.declined_facets if requires_consent(f)]
            _say(
                f"{'导入' if new else '已更新'} {path.name}（{MEMORY_KIND_LABELS[s.kind]}）：{s.n_expressions} 条，"
                f"本人 {s.n_target} 条，{span}"
                + (f"；未授权细项 {'、'.join(withheld)}" if withheld else "")
                + (f"；无法识别的行 {len(parsed.skipped_lines)} 行" if parsed.skipped_lines else "")
            )


@persona_app.command("note")
def persona_note(ctx: typer.Context, text: Annotated[str, typer.Argument(help="要记住的文字")]) -> None:
    settings = _settings(ctx)
    with _errors(), _persona_store(settings) as store:
        parsed = parse_note(text, settings)
        store.put_source(parsed)
    _say(f"已添加 {parsed.source.title}")


@persona_app.command("sources")
def persona_sources(ctx: typer.Context) -> None:
    """列出已导入的资料。"""
    with _persona_store(_settings(ctx)) as store:
        memories = source_memories(store)
        for s in store.list_sources():
            memory = memories[s.source_id]
            status = {"not_built": "尚未构建", "no_items": "构建后未产生档案条目", "remembered": "已记住"}[
                memory.build_status
            ]
            facets = "、".join(f["name"] for f in memory.facets) or "—"
            _say(
                f"{s.source_id}  {SOURCE_KIND_LABELS[s.kind]}  {s.title}  本人 {s.n_target}/{s.n_expressions} 条  "
                f"{s.first_date or '—'} 至 {s.last_date or '—'}  "
                f"原话 {memory.expressions_total}（本人 {memory.expressions_target} / "
                f"他人 {memory.expressions_others}）  "
                f"支撑档案 {memory.items_supported} 条  涉及：{facets}  {status}"
                + (f"（{memory.nothing_found_reason}）" if memory.nothing_found_reason else "")
            )


@persona_app.command("reextract")
def persona_reextract(
    ctx: typer.Context,
    source_ids: Annotated[list[str] | None, typer.Argument(help="资料编号，可以多个")] = None,
    nothing_found: Annotated[
        bool, typer.Option("--nothing-found", help="加上所有已抽取过、但没有形成记忆的资料")
    ] = False,
    empty_chunks: Annotated[
        bool,
        typer.Option("--empty-chunks", help="只重抽当时一条结论也没抽出的分段；不指定资料时针对所有资料"),
    ] = False,
    yes: Annotated[bool, typer.Option("--yes", help="分段数超过费用闸时确认")] = False,
) -> None:
    """让模型重新抽取指定资料：资料没变也重抽，下次构建时生效。"""
    settings = _settings(ctx)
    with _persona_store(settings) as store:
        selected = list(dict.fromkeys(source_ids or []))
        if missing := [sid for sid in selected if store.get_source(sid) is None]:
            raise _fail(f"找不到资料：{'、'.join(missing)}")
        if nothing_found:
            memories = source_memories(store)
            selected += [
                sid
                for sid, m in memories.items()
                if m.build_status == "no_items" and m.chunks_extracted and sid not in selected
            ]
        if empty_chunks:
            empty = store.empty_chunks()
            if not selected:
                selected = [s.source_id for s in store.list_sources()]
            counts = {sid: empty.get(sid, 0) for sid in selected}
        else:
            extracted = store.extraction_stats()
            counts = {sid: extracted.get(sid, (0, None))[0] for sid in selected}
        selected = [sid for sid in selected if counts[sid] or not empty_chunks]
        if not selected:
            raise _fail(
                "没有一条结论也没抽出的分段"
                if empty_chunks
                else "没有要重新抽取的资料：请给出资料编号，或加 --nothing-found / --empty-chunks"
            )
        chunks = sum(counts[sid] for sid in selected)
        if chunks > settings.kernel.max_auto_rebuild_chunks and not yes:
            raise _fail(f"将重抽 {len(selected)} 份资料的 {chunks} 个分段，超过费用闸；请确认后加 --yes")
        for sid in selected:
            store.reextract_source(sid, empty_only=empty_chunks)
    _say(f"已标记 {len(selected)} 份资料（{chunks} 个分段）重新抽取，运行 twin persona build 生效")


@persona_app.command("build")
@_command_usage("build")
def persona_build(ctx: typer.Context) -> None:
    """抽取并合并人格档案，再更新检索向量；只处理新增或变化的部分。"""
    settings = _settings(ctx)
    with _persona_store(settings) as store:
        if profile_stale(store):
            _progress(KERNEL_STALE_NOTICE if stale_reason(store) == "kernel" else STALE_PROFILE_NOTICE)
        llm = _llm(settings)
        embedder = _embedder(settings)
        report = build_profile(store, llm, settings, _progress)
        for failure in report.failures:
            _progress(f"FAILED {failure}")
        for degraded in report.degraded:
            _progress(f"未完全合并，下次构建会重试：{degraded}")
        if llm.failed and not llm.succeeded:
            raise _fail(f"人格档案阶段的 {llm.failed} 次模型调用全部失败：{type(llm.last_error).__name__}")
        try:
            index_persona(store, embedder, settings, _progress)
        except EmbedError as e:
            raise _fail(f"向量化失败：{e}") from e
        _say(
            f"资料 {report.sources} 份，分块 {report.chunks_total}（本次抽取 {report.chunks_extracted}），"
            f"候选 {report.candidates} 条，合并细项 {report.facets_merged} 个，档案条目 {report.items} 条"
        )
        if report.chunks_extracted:
            x = report.extraction
            _say(
                f"本次模型提炼 {x.returned} 条结论，保留 {x.kept} 条；丢弃：细项不可用 {x.off_facet} 条，"
                f"结论为空 {x.empty_statement} 条，"
                f"没有可核对的引文 {x.unsupported} 条（引文对不上 {x.quotes_unmatched} 处、"
                f"编号不存在 {x.quotes_misnumbered} 处、风格引用他人记述 {x.quotes_narrated_style} 处）"
                + (f"；回复被截断后拆分重抽 {x.splits} 次" if x.splits else "")
            )
            if x.unknown_facets:
                common = sorted(x.unknown_facets.items(), key=lambda kv: (-kv[1], kv[0]))[:10]
                _say("不在可用列表里的细项（模型写法×次数）：" + "、".join(f"“{f}”×{n}" for f, n in common))
        _say(report.change_summary())
        for facet_id, diff in sorted(report.facet_diffs.items()):
            if diff.added or diff.changed or diff.removed:
                _say(f"  {facet_id}：新增 {diff.added} 条、修改 {diff.changed} 条、删除 {diff.removed} 条")
        if report.failures:
            raise typer.Exit(code=1)


@persona_app.command("coverage")
def persona_coverage(
    ctx: typer.Context,
    as_of: Annotated[str | None, typer.Option("--as-of", help="按这一天计算（默认今天）")] = None,
    out: Annotated[Path | None, typer.Option("--out", help="把报告写入 Markdown 文件")] = None,
) -> None:
    """看看分身了解到什么，还有哪些内容可以补充。"""
    settings = _settings(ctx)
    with _persona_store(settings) as store:
        report = coverage_report(
            store.list_items(), consented_facets(store), _optional_date(as_of, "--as-of"), demand=store.chat_demand()
        )
    text = coverage_markdown(report)
    if out is not None:
        _write(out, text)
        _say(f"已写入 {out}")
    else:
        _say(text)


@persona_app.command("chat")
@_command_usage("chat")
def persona_chat(
    ctx: typer.Context,
    message: Annotated[str | None, typer.Argument(help="只问一句；不给则进入多轮对话，空行退出")] = None,
) -> None:
    """和数字分身聊天。"""
    settings = _settings(ctx)
    with _persona_store(settings) as store:
        if profile_stale(store):
            _progress(KERNEL_STALE_NOTICE if stale_reason(store) == "kernel" else STALE_PROFILE_NOTICE)
        twin = PersonaChat(store, _llm(settings, chat=True), _embedder(settings), settings, ledger=True)
        history: list[ChatTurn] = []
        while True:
            text = message if message is not None else typer.prompt("你", default="", show_default=False)
            if not text.strip():
                return
            history.append(ChatTurn(role="user", content=text))
            try:
                answer = twin.reply(history)
            except (LLMError, EmbedError, MemoryUpdating) as e:
                raise _fail(str(e)) from e
            history.append(ChatTurn(role="twin", content=answer.reply))
            flag = (
                f"（弃权：{answer.abstain_reason}）"
                if answer.abstain
                else "（推测，非本人表达）"
                if answer.mode == "inferred"
                else ""
            )
            _say(f"{settings.target_name}的分身：{answer.reply}")
            _say(f"  置信度 {answer.confidence:.2f}{flag}  依据 {', '.join(answer.citations) or '无'}")
            if message is not None:
                return


@app.command("eval")
@_command_usage("eval")
def personal_eval_command(
    ctx: typer.Context,
    evalset: Annotated[Path, typer.Option("--evalset", help="仓库外的本人资料题库 JSON")],
    persona_ref: Annotated[Path, typer.Option("--persona-ref", help="仓库外的本人资料参考文本")],
    out: Annotated[Path, typer.Option("--out", help="私有报告目录（默认禁止仓库内路径）")],
    repeats: Annotated[int, typer.Option("--repeats", min=1)] = 1,
    categories: Annotated[list[str] | None, typer.Option("--categories", help="分类，可重复或逗号分隔")] = None,
    allow_in_repo: Annotated[bool, typer.Option("--allow-in-repo")] = False,
) -> None:
    """本人资料评测；update 在临时数据库副本上顺序执行导入、增量构建和删除。"""
    from .config import configuration_fingerprint
    from .evals.personal import (
        ensure_output_directory,
        load_evalset,
        make_panel,
        run_persona_evaluation,
        select_cases,
        write_outputs,
    )

    ensure_output_directory(out, allow_in_repo=allow_in_repo)
    selected = [part.strip() for value in categories for part in value.split(",")] if categories else None
    cases = select_cases(load_evalset(evalset), selected)
    settings = _settings(ctx)
    _usage_output.set(out)
    try:
        llm = make_llm(settings.chat_llm, "chat_llm") if settings.chat_llm is not None else make_llm(settings.llm)
        embedder = make_embedder(settings.embed)
        panel = make_panel(settings)
        identity = configuration_fingerprint(
            settings,
            llm,
            embedder,
            [(f"j{i}:{judge.llm.name}", judge.effort) for i, judge in enumerate(panel)],
            experiment={"repeats": repeats, "rubric_version": "1"},
        )
        report = run_persona_evaluation(
            cases,
            llm,
            embedder,
            settings,
            panel,
            persona_ref,
            repeats=repeats,
            fingerprints={"configuration": identity},
        )
        write_outputs(out, report, settings, allow_in_repo=allow_in_repo)
    except Exception:
        # Neither SDK errors nor runtime validation errors may echo personal prompts or answers.
        raise _fail("本人资料评测失败；请检查配置、参考文本和输出权限（详情已隐藏）") from None
    _say("评测报告已写入；update 已在临时副本上运行。" if "update" not in report.skipped else "评测报告已写入。")


SPLIT_HELP = "formal (documented sample) or dev (disjoint sample for day-to-day iteration)"
JUDGES_HELP = "Judge with the config's [[judges]] tables instead of the main llm (opt-in: they may be paid endpoints)"


@app.command("eval-longmemeval")
def longmemeval_command(
    ctx: typer.Context,
    dataset: Annotated[Path, typer.Option("--dataset", help="LongMemEval S cleaned JSON")],
    out: Annotated[Path, typer.Option("--out", help="Fresh private directory outside git repositories")],
    limit: Annotated[int, typer.Option("--limit", min=1)] = 3,
    offset: Annotated[int, typer.Option("--offset", min=0)] = 0,
    per_type: Annotated[
        int | None, typer.Option("--per-type", min=1, help="Seeded random sample of this many per question type")
    ] = None,
    seed: Annotated[str, typer.Option("--seed", help="Question sampling seed")] = "longmemeval-v1",
    split: Annotated[str, typer.Option("--split", help=SPLIT_HELP)] = "formal",
    system: Annotated[str, typer.Option("--system", help="twin (default) or retrieval baseline")] = "twin",
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    score: Annotated[bool, typer.Option("--score/--no-score", help="Optional custom configured-judge scoring")] = False,
    configured_judges: Annotated[bool, typer.Option("--configured-judges", help=JUDGES_HELP)] = False,
) -> None:
    """LongMemEval through production Twin, with an optional retrieval baseline."""
    try:
        report = _run_longmemeval(
            _benchmark_settings(ctx, keep_judges=configured_judges),
            dataset,
            out,
            limit=limit,
            offset=offset,
            per_type=per_type,
            seed=seed,
            split=split,
            system=system,
            dry_run=dry_run,
            score=score,
        )
    except Exception:
        raise _fail(
            "LongMemEval failed; check dataset, configuration and fresh private output directory (details hidden)"
        ) from None
    _say(
        f"LongMemEval: selected={report['selected']}, completed={report['completed']}, "
        f"preparation_failures={report.get('preparation_failures', 0)}, "
        f"prediction_failures={report['prediction_failures']}, judge_failures={report['judge_failures']}, "
        f"missing={report['missing']}; system={report['system']}."
    )
    if not dry_run and _benchmark_failed(report):
        raise typer.Exit(code=1)


def _run_longmemeval(
    settings: Settings,
    dataset: Path,
    out: Path,
    *,
    limit: int,
    offset: int,
    per_type: int | None,
    seed: str,
    split: str,
    system: str,
    dry_run: bool,
    profile_cache: ProfileCache | None = None,
    grant_gated: bool = False,
    prepare_workers: int = 1,
    answer_workers: int = 1,
    call_slots: threading.Semaphore | None = None,
    judge_slots: threading.Semaphore | None = None,
    score: bool,
    types: Sequence[str] | None = None,
) -> dict[str, Any]:
    from .evals.longmemeval import load_dataset, run_evaluation, select_cases, validate_output
    from .util import fingerprint

    out = validate_output(out)
    with dataset.open("rb") as stream:
        dataset_sha = hashlib.file_digest(stream, "sha256").hexdigest()
    cases = select_cases(
        load_dataset(dataset), limit=limit, offset=offset, per_type=per_type, seed=seed, split=split, types=types
    )
    configured_identity = fingerprint(
        {
            "reader": settings.effective_chat_llm.model_dump(exclude={"base_url", "api_key_env"}),
            "embed": settings.embed.model_dump(exclude={"base_url", "api_key_env"}),
            "judges": [
                judge.model_dump(exclude={"base_url", "api_key_env"}) for judge in settings.judges or [settings.llm]
            ]
            if score
            else [],
            "limit": limit,
            "offset": offset,
            **({"per_type": per_type, "seed": seed} if per_type is not None else {}),
            **({"split": split} if split != "formal" else {}),
            **({"types": list(types)} if types is not None else {}),
            "score": score,
        }
    )
    return run_evaluation(
        cases,
        out,
        settings,
        system=system,
        dry_run=dry_run,
        score=score,
        fingerprints={"dataset_sha256": dataset_sha, "configuration": configured_identity},
        profile_cache=profile_cache,
        grant_gated=grant_gated,
        prepare_workers=prepare_workers,
        answer_workers=answer_workers,
        call_slots=call_slots,
        judge_slots=judge_slots,
    )


def _benchmark_failed(report: dict[str, Any]) -> bool:
    return any(
        report.get(key, 0) for key in ("preparation_failures", "prediction_failures", "judge_failures", "missing")
    )


def _benchmark_settings(ctx: typer.Context, *, keep_judges: bool = False) -> Settings:
    config = _config_path(ctx)
    if config is None and os.environ.get("TWIN_CONFIG"):
        config = Path(os.environ["TWIN_CONFIG"])
    if config is not None and not config.is_file():
        raise ValueError("Missing configuration")
    settings = load_settings(config)
    return settings.model_copy(update={"chat_llm": settings.llm, **({} if keep_judges else {"judges": []})})


def _benchmark_fingerprints(
    settings: Settings,
    paths: dict[str, Path],
    limit: int | None,
    offset: int,
    selection: dict[str, Any] | None = None,
) -> dict[str, str]:
    from .util import fingerprint

    result = {}
    for name, path in paths.items():
        with path.open("rb") as stream:
            result[name] = hashlib.file_digest(stream, "sha256").hexdigest()
    result["configuration"] = fingerprint(
        {
            "reader": settings.effective_chat_llm.model_dump(exclude={"base_url", "api_key_env"}),
            "embed": settings.embed.model_dump(exclude={"base_url", "api_key_env"}),
            "limit": limit,
            "offset": offset,
            **(selection or {}),
        }
    )
    return result


def _benchmark_status(name: str, report: dict[str, Any], *, dry_run: bool) -> None:
    _say(
        f"{name}: selected={report['selected']}, completed={report['completed']}, "
        f"preparation_failures={report.get('preparation_failures', 0)}, "
        f"prediction_failures={report['prediction_failures']}, missing={report['missing']}."
    )
    if not dry_run and _benchmark_failed(report):
        raise typer.Exit(code=1)


@app.command("eval-personamem")
def personamem_command(
    ctx: typer.Context,
    questions: Annotated[Path, typer.Option("--questions", help="Official PersonaMem questions CSV")],
    contexts: Annotated[Path, typer.Option("--contexts", help="Official shared contexts JSONL")],
    out: Annotated[Path, typer.Option("--out", help="Fresh private output directory outside git repositories")],
    limit: Annotated[int, typer.Option("--limit", min=1)] = 3,
    offset: Annotated[int, typer.Option("--offset", min=0)] = 0,
    sample: Annotated[int | None, typer.Option("--sample", min=1, help="Seeded random sample of questions")] = None,
    seed: Annotated[str, typer.Option("--seed", help="Question sampling seed")] = "personamem-v1",
    split: Annotated[str, typer.Option("--split", help=SPLIT_HELP)] = "formal",
    system: Annotated[str, typer.Option("--system", help="twin (default) or retrieval baseline")] = "twin",
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
) -> None:
    """PersonaMem through production Twin with official multiple-choice scoring."""
    try:
        report = _run_personamem(
            _benchmark_settings(ctx),
            questions,
            contexts,
            out,
            limit=limit,
            offset=offset,
            sample=sample,
            seed=seed,
            split=split,
            system=system,
            dry_run=dry_run,
        )
    except Exception:
        raise _fail(
            "PersonaMem failed; check input, configuration and fresh output directory (details hidden)"
        ) from None
    _benchmark_status("PersonaMem", report, dry_run=dry_run)


@app.command("eval-personamem2")
def personamem2_command(
    ctx: typer.Context,
    benchmark: Annotated[
        Path, typer.Option("--benchmark", help="PersonaMem-v2 benchmark/text/benchmark.csv; histories beside it")
    ],
    out: Annotated[Path, typer.Option("--out", help="Fresh private output directory outside git repositories")],
    personas: Annotated[
        int | None, typer.Option("--personas", min=1, help="Personas to draw; all their questions")
    ] = None,
    seed: Annotated[str, typer.Option("--seed", help="Persona sampling seed")] = "personamem-v2",
    split: Annotated[str, typer.Option("--split", help=SPLIT_HELP)] = "formal",
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
) -> None:
    """PersonaMem-v2 (text, 32k) through production Twin with upstream multiple-choice scoring."""
    try:
        report = _run_personamem2(
            _benchmark_settings(ctx), benchmark, out, personas=personas, seed=seed, split=split, dry_run=dry_run
        )
    except Exception:
        raise _fail(
            "PersonaMem-v2 failed; check input, downloaded histories, configuration and fresh output directory "
            "(details hidden)"
        ) from None
    _benchmark_status("PersonaMem-v2", report, dry_run=dry_run)


def _run_personamem2(
    settings: Settings,
    benchmark: Path,
    out: Path,
    *,
    personas: int | None,
    seed: str,
    split: str,
    dry_run: bool,
    profile_cache: ProfileCache | None = None,
    grant_gated: bool = False,
    prepare_workers: int = 1,
    answer_workers: int = 1,
    call_slots: threading.Semaphore | None = None,
) -> dict[str, Any]:
    from .evals.personamem2 import load_benchmark, load_cases, run_evaluation, split_personas, validate_output

    out = validate_output(out)
    rows = load_benchmark(benchmark)
    chosen = split_personas(rows, split, personas, seed)
    cases = load_cases(rows, chosen, benchmark.resolve().parent)
    identities = _benchmark_fingerprints(
        settings, {"dataset_sha256": benchmark}, None, 0, {"personas": chosen, "seed": seed, "split": split}
    )
    return run_evaluation(
        cases,
        out,
        settings,
        dry_run=dry_run,
        fingerprints=identities,
        profile_cache=profile_cache,
        grant_gated=grant_gated,
        prepare_workers=prepare_workers,
        answer_workers=answer_workers,
        call_slots=call_slots,
    )


def _run_personamem(
    settings: Settings,
    questions: Path,
    contexts: Path,
    out: Path,
    *,
    limit: int,
    offset: int,
    sample: int | None,
    seed: str,
    split: str,
    system: str,
    dry_run: bool,
    profile_cache: ProfileCache | None = None,
    grant_gated: bool = False,
    prepare_workers: int = 1,
    answer_workers: int = 1,
    call_slots: threading.Semaphore | None = None,
) -> dict[str, Any]:
    from .evals.longmemeval import validate_output
    from .evals.personamem import load_dataset, run_evaluation, select_cases

    out = validate_output(out)
    cases = select_cases(
        load_dataset(questions, contexts), limit=limit, offset=offset, sample=sample, seed=seed, split=split
    )
    selection = {"sample": sample, "seed": seed} if sample is not None else None
    if selection is not None and split != "formal":
        selection["split"] = split
    identities = _benchmark_fingerprints(
        settings, {"questions_sha256": questions, "contexts_sha256": contexts}, limit, offset, selection
    )
    return run_evaluation(
        cases,
        out,
        settings,
        system=system,
        dry_run=dry_run,
        score=True,
        fingerprints=identities,
        profile_cache=profile_cache,
        grant_gated=grant_gated,
        prepare_workers=prepare_workers,
        answer_workers=answer_workers,
        call_slots=call_slots,
    )


@app.command("eval-twin2k500")
def twin2k500_command(
    ctx: typer.Context,
    dataset: Annotated[Path, typer.Option("--dataset", help="Official wave_split exported JSON/JSONL")],
    out: Annotated[Path, typer.Option("--out", help="Fresh private output directory outside git repositories")],
    limit: Annotated[
        int | None, typer.Option("--limit", min=1, help="Response items; default 3, or all with --participants")
    ] = None,
    offset: Annotated[int, typer.Option("--offset", min=0)] = 0,
    participants: Annotated[
        int | None, typer.Option("--participants", min=1, help="Seeded random sample of participants")
    ] = None,
    seed: Annotated[str, typer.Option("--seed", help="Participant sampling seed")] = "twin2k500-v1",
    split: Annotated[str, typer.Option("--split", help=SPLIT_HELP)] = "formal",
    system: Annotated[str, typer.Option("--system", help="twin (default) or retrieval baseline")] = "twin",
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
) -> None:
    """Twin-2K-500 production Twin built from waves 1–3, evaluated on wave 4."""
    try:
        report = _run_twin2k500(
            _benchmark_settings(ctx),
            dataset,
            out,
            limit=limit,
            offset=offset,
            participants=participants,
            seed=seed,
            split=split,
            system=system,
            dry_run=dry_run,
        )
    except Exception:
        raise _fail(
            "Twin-2K-500 failed; check input, configuration and fresh output directory (details hidden)"
        ) from None
    _benchmark_status("Twin-2K-500", report, dry_run=dry_run)


def _run_twin2k500(
    settings: Settings,
    dataset: Path,
    out: Path,
    *,
    limit: int | None,
    offset: int,
    participants: int | None,
    seed: str,
    split: str,
    system: str,
    dry_run: bool,
    profile_cache: ProfileCache | None = None,
    grant_gated: bool = False,
    prepare_workers: int = 1,
    answer_workers: int = 1,
    call_slots: threading.Semaphore | None = None,
) -> dict[str, Any]:
    from .evals.longmemeval import validate_output
    from .evals.twin2k500 import load_dataset, run_evaluation, sample_participants, select_cases

    out = validate_output(out)
    loaded = load_dataset(dataset)
    if participants is None:
        if split != "formal":
            raise ValueError("the dev split is a seeded sample; pass participants")
        limit = 3 if limit is None else limit
        cases = select_cases(loaded, limit=limit, offset=offset)
        selection = None
    else:
        sampled = sample_participants(loaded, participants, seed, split)
        cases = select_cases(loaded, limit=limit, offset=offset, participant_ids=sampled)
        selection = {"participants": sorted(sampled), "seed": seed}
    identities = _benchmark_fingerprints(settings, {"dataset_sha256": dataset}, limit, offset, selection)
    return run_evaluation(
        cases,
        out,
        settings,
        system=system,
        dry_run=dry_run,
        score=True,
        fingerprints=identities,
        profile_cache=profile_cache,
        grant_gated=grant_gated,
        prepare_workers=prepare_workers,
        answer_workers=answer_workers,
        call_slots=call_slots,
    )


SUITE_SIZES = {
    "dev": {"lme": 3, "pm": 24, "pm2": 4, "t2k": 4},
    "formal": {"lme": 10, "pm": 30, "pm2": 8, "t2k": 10},
}


@app.command("eval-suite")
def eval_suite_command(
    ctx: typer.Context,
    out: Annotated[Path, typer.Option("--out", help="Fresh private suite directory outside git repositories")],
    split: Annotated[str, typer.Option("--split", help=SPLIT_HELP)] = "dev",
    repeats: Annotated[int, typer.Option("--repeats", min=1, help="Full runs per benchmark, to measure noise")] = 3,
    longmemeval: Annotated[Path | None, typer.Option("--longmemeval", help="LongMemEval S cleaned JSON")] = None,
    personamem_questions: Annotated[Path | None, typer.Option("--personamem-questions")] = None,
    personamem_contexts: Annotated[Path | None, typer.Option("--personamem-contexts")] = None,
    personamem2: Annotated[
        Path | None, typer.Option("--personamem2", help="PersonaMem-v2 benchmark/text/benchmark.csv")
    ] = None,
    twin2k500: Annotated[Path | None, typer.Option("--twin2k500", help="Twin-2K-500 wave_split JSON/JSONL")] = None,
    lme_per_type: Annotated[int | None, typer.Option("--lme-per-type", min=1)] = None,
    lme_types: Annotated[
        str | None,
        typer.Option(
            "--lme-types",
            help="Comma-separated LongMemEval question types to draw (default all), e.g. temporal-reasoning to "
            "focus a round on one weak type with a larger --lme-per-type",
        ),
    ] = None,
    pm_sample: Annotated[int | None, typer.Option("--pm-sample", min=1)] = None,
    pm2_personas: Annotated[int | None, typer.Option("--pm2-personas", min=1)] = None,
    t2k_participants: Annotated[int | None, typer.Option("--t2k-participants", min=1)] = None,
    baseline: Annotated[Path | None, typer.Option("--baseline", help="Earlier scorecard.json to compare with")] = None,
    configured_judges: Annotated[bool, typer.Option("--configured-judges", help=JUDGES_HELP)] = False,
    profile_cache: Annotated[
        Path | None,
        typer.Option(
            "--profile-cache",
            help="Private directory outside git that keeps built profiles across suites; repeat n reuses build n "
            "until the profile-building code changes",
        ),
    ] = None,
    prepare_workers: Annotated[
        int,
        typer.Option(
            "--prepare-workers",
            min=1,
            help="Subjects whose profiles each run builds at once, before answering; each build already "
            "makes several model calls at a time",
        ),
    ] = 4,
    answer_workers: Annotated[
        int, typer.Option("--answer-workers", min=1, help="Questions each run answers at once")
    ] = 4,
    max_calls: Annotated[
        int,
        typer.Option(
            "--max-calls",
            min=1,
            help="Model calls in flight across the whole suite, shared by every benchmark and repeat; lower it if "
            "the endpoint rate-limits or times out",
        ),
    ] = 32,
    max_judge_calls: Annotated[
        int,
        typer.Option(
            "--max-judge-calls",
            min=1,
            help="Judge calls in flight across the whole suite, within --max-calls; judge endpoints often allow "
            "fewer concurrent requests than the answer model",
        ),
    ] = 4,
    builds: Annotated[
        int | None,
        typer.Option(
            "--builds",
            min=1,
            help="Profile builds the repeats share, at most --repeats (the default, one build per repeat). "
            "Fewer builds make a round that changes profile building much faster, but the spread between repeats "
            "then leaves out build-to-build variance; confirm a promising change with one build per repeat",
        ),
    ] = None,
    grant_gated_facets: Annotated[
        bool,
        typer.Option(
            "--grant-gated-facets",
            help="Build profiles as if the person consented to every consent-gated facet (life and preferences, "
            "health, family); the scorecard says so. Production derives consent from questionnaires",
        ),
    ] = False,
) -> None:
    """Run the three public benchmarks ``--repeats`` times through production Twin and write a scorecard.

    Iterate on the ``dev`` split; run ``formal`` only to record a milestone. Every benchmark and repeat runs at the
    same time under one ``--max-calls`` cap, and each run lands in ``<out>/<benchmark>/r<n>/``.
    """
    from concurrent.futures import ThreadPoolExecutor

    from .evals.longmemeval import validate_output
    from .evals.persona_runtime import ProfileCache
    from .evals.scorecard import build_scorecard, compare, write_scorecard

    if split not in SUITE_SIZES:
        raise _fail("--split must be formal or dev")
    builds = builds or repeats
    if builds > repeats:
        raise _fail("--builds cannot exceed --repeats")
    if (personamem_questions is None) != (personamem_contexts is None):
        raise _fail("PersonaMem needs both --personamem-questions and --personamem-contexts")
    sizes = {
        "lme": lme_per_type or SUITE_SIZES[split]["lme"],
        "pm": pm_sample or SUITE_SIZES[split]["pm"],
        "pm2": pm2_personas or SUITE_SIZES[split]["pm2"],
        "t2k": t2k_participants or SUITE_SIZES[split]["t2k"],
    }
    question_types = [t.strip() for t in lme_types.split(",") if t.strip()] if lme_types is not None else None
    if question_types is not None:
        from .evals.longmemeval import QUESTION_TYPES

        if not question_types or set(question_types) - set(QUESTION_TYPES):
            raise _fail("--lme-types takes question types among: " + ", ".join(QUESTION_TYPES))
    slots = threading.Semaphore(max_calls)
    judge_slots = threading.Semaphore(max_judge_calls)
    jobs: dict[str, Callable[[Settings, Path, ProfileCache | None], dict[str, Any]]] = {}
    if longmemeval is not None:
        lme_dataset = longmemeval
        jobs["longmemeval"] = lambda settings, run, cache: _run_longmemeval(
            settings, lme_dataset, run, limit=3, offset=0, per_type=sizes["lme"], seed="longmemeval-v1",
            split=split, system="twin", dry_run=False, score=True, profile_cache=cache, grant_gated=grant_gated_facets,
            prepare_workers=prepare_workers, answer_workers=answer_workers, call_slots=slots,
            judge_slots=judge_slots, types=question_types,
        )  # fmt: skip
    if personamem_questions is not None and personamem_contexts is not None:
        pm_questions, pm_contexts = personamem_questions, personamem_contexts
        jobs["personamem"] = lambda settings, run, cache: _run_personamem(
            settings, pm_questions, pm_contexts, run, limit=3, offset=0, sample=sizes["pm"], seed="personamem-v1",
            split=split, system="twin", dry_run=False, profile_cache=cache, grant_gated=grant_gated_facets,
            prepare_workers=prepare_workers, answer_workers=answer_workers, call_slots=slots,
        )  # fmt: skip
    if personamem2 is not None:
        pm2_benchmark = personamem2
        jobs["personamem2"] = lambda settings, run, cache: _run_personamem2(
            settings, pm2_benchmark, run, personas=sizes["pm2"], seed="personamem-v2", split=split, dry_run=False,
            profile_cache=cache, grant_gated=grant_gated_facets, prepare_workers=prepare_workers,
            answer_workers=answer_workers, call_slots=slots,
        )  # fmt: skip
    if twin2k500 is not None:
        t2k_dataset = twin2k500
        jobs["twin2k500"] = lambda settings, run, cache: _run_twin2k500(
            settings, t2k_dataset, run, limit=None, offset=0, participants=sizes["t2k"], seed="twin2k500-v1",
            split=split, system="twin", dry_run=False, profile_cache=cache, grant_gated=grant_gated_facets,
            prepare_workers=prepare_workers, answer_workers=answer_workers, call_slots=slots,
        )  # fmt: skip
    if not jobs:
        raise _fail("Name at least one benchmark dataset")
    try:
        previous = json.loads(baseline.read_text(encoding="utf-8")) if baseline is not None else None
        out = validate_output(out)
        if out.exists() and any(out.iterdir()):
            raise ValueError
        private_directory(out)
        out.chmod(0o700)
        if profile_cache is not None:
            profile_cache = validate_output(profile_cache)
            private_directory(profile_cache)
            profile_cache.chmod(0o700)
        judged = _benchmark_settings(ctx, keep_judges=configured_judges)
        plain = _benchmark_settings(ctx)
    except Exception:
        raise _fail("Suite setup failed; check configuration, baseline and a fresh empty output directory") from None

    def run_repeat(name: str, index: int) -> dict[str, Any]:
        settings = judged if name == "longmemeval" else plain
        run = out / name / f"r{index}"
        private_directory(run)
        # Repeat n uses build slot n, cycling when the repeats share fewer builds; repeats on one slot build it once
        # (see ``ProfileCache.building``). Granted builds hold facets default builds never extract, so they keep
        # slots of their own.
        slot = f"r{(index - 1) % builds + 1}" + ("-granted" if grant_gated_facets else "")
        cache = ProfileCache(profile_cache, slot) if profile_cache is not None else None
        report = jobs[name](settings, run, cache)
        _progress(f"{name} r{index}/{repeats} done")
        return report

    failed: list[str] = []
    runs = [(name, index) for index in range(1, repeats + 1) for name in jobs]
    with ThreadPoolExecutor(max_workers=len(runs)) as pool:
        futures = {run: pool.submit(run_repeat, *run) for run in runs}
        for (name, index), future in futures.items():
            try:
                if _benchmark_failed(future.result()) and name not in failed:
                    failed.append(name)
            except Exception:
                if name not in failed:
                    failed.append(name)
                _progress(f"{name} r{index} stopped early (details hidden)")
    try:
        metadata = _suite_metadata(split, repeats, sizes)
        metadata["judges"] = [judge.model for judge in judged.judges] or [judged.llm.model]
        metadata["profile_cache"] = profile_cache is not None
        metadata["grant_gated_facets"] = grant_gated_facets
        metadata["builds"] = builds
        if question_types is not None:
            metadata["lme_types"] = question_types
        metadata["prepare_workers"] = prepare_workers
        metadata["answer_workers"] = answer_workers
        metadata["max_calls"] = max_calls
        metadata["max_judge_calls"] = max_judge_calls
        card = build_scorecard(out, metadata)
    except Exception:
        raise _fail("Scorecard failed; every repeat of a benchmark must finish (details hidden)") from None
    comparison = None
    if previous is not None:
        try:
            comparison = compare(card, previous)
        except ValueError as e:
            # Still write the scorecard: losing a finished suite to a mismatched baseline costs hours.
            _say(f"Baseline not compared: {e}.")
    write_scorecard(out, card, comparison)
    _say(f"Scorecard written to {out / 'scorecard.md'}.")
    if failed:
        _say("Runs with failures (counted as wrong in the scorecard): " + ", ".join(failed))
        raise typer.Exit(code=1)


def _suite_metadata(split: str, repeats: int, sizes: dict[str, int]) -> dict[str, Any]:
    repo = Path(__file__).resolve().parents[2]
    try:
        commit = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "-C", str(repo), "status", "--porcelain", "--untracked-files=no"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        commit += "-dirty" if dirty else ""
    except (OSError, subprocess.CalledProcessError):
        commit = "unknown"
    return {
        "split": split,
        "repeats": repeats,
        "sizes": sizes,
        "commit": commit,
        "date": dt.datetime.now(dt.UTC).strftime("%Y-%m-%d %H:%M UTC"),
    }


@app.command("eval-scorecard")
def eval_scorecard_command(
    suite: Annotated[Path, typer.Argument(help="Suite directory with <benchmark>/r<n>/ runs")],
    baseline: Annotated[Path | None, typer.Option("--baseline", help="Earlier scorecard.json to compare with")] = None,
) -> None:
    """Rebuild a suite's scorecard from its runs, optionally against a baseline, without calling a model."""
    from .evals.scorecard import build_scorecard, compare, write_scorecard

    with _errors():
        existing = suite / "scorecard.json"
        metadata = (
            {
                k: v
                for k, v in json.loads(existing.read_text(encoding="utf-8")).items()
                if k not in ("benchmarks", "comparison", "version")
            }
            if existing.is_file()
            else {"split": "unknown"}
        )
        card = build_scorecard(suite, metadata)
        previous = json.loads(baseline.read_text(encoding="utf-8")) if baseline is not None else None
        write_scorecard(suite, card, compare(card, previous) if previous is not None else None)
    _say(f"Scorecard written to {suite / 'scorecard.md'}.")


@app.command("eval-extract")
def eval_extract_command(
    ctx: typer.Context,
    cases: Annotated[Path, typer.Option("--cases", help="题单 JSONL：LongMemEval 证据轮次与关键事实")],
    dataset: Annotated[Path, typer.Option("--dataset", help="LongMemEval S cleaned JSON")],
    out: Annotated[Path, typer.Option("--out", help="仓库外的评测目录，各变体写在其下的 <variant>/")],
    variant: Annotated[str, typer.Option("--variant", help="baseline 或 v1、v2……")] = "baseline",
    reps: Annotated[int, typer.Option("--reps", min=1, help="每块重复几次")] = 2,
    per_type: Annotated[int | None, typer.Option("--per-type", min=1, help="试跑：每种题型只取题单里的前几块")] = None,
    workers: Annotated[int, typer.Option("--workers", min=1, help="同时评测几块")] = 4,
    timeout_s: Annotated[float, typer.Option("--timeout-s", min=1, help="每块（抽取加评分）的总时限")] = 600,
    approve_harness: Annotated[
        bool, typer.Option("--approve-harness", help="批准当前的运行器、评分和题单（改动后需重新批准）")
    ] = False,
    allow_in_repo: Annotated[bool, typer.Option("--allow-in-repo")] = False,
) -> None:
    """逐块抽取评测：每块是 LongMemEval 一段会话里含人工标注证据的块，评它是否抽出关键事实、保留结论是否有依据。"""
    import re

    from .evals.extraction import (
        VARIANT_PATTERN,
        HarnessChanged,
        check_harness,
        first_per_type,
        load_cases,
        load_sessions,
        run_eval,
        same_model,
        served_model,
        write_state,
    )
    from .evals.harness import Judge
    from .evals.personal import ensure_output_directory
    from .util import private_directory

    with _errors():
        if not re.fullmatch(VARIANT_PATTERN, variant):
            raise ValueError("--variant 只能是 baseline 或 v1、v2……")
        ensure_output_directory(out, allow_in_repo=allow_in_repo)
        settings = _benchmark_settings(ctx, keep_judges=True)
        if not settings.judges:
            raise ValueError("配置里没有 [[judges]]；评委要和被测的 [llm] 分开配置")
        selected = load_cases(cases)
        if per_type is not None:
            selected = first_per_type(selected, per_type)
        private_directory(out)
        try:
            check_harness(out, cases, approve_harness)
        except HarnessChanged as e:
            _say(str(e))
            raise typer.Exit(code=2) from None
        llm = make_llm(settings.llm, "llm")
        served = served_model(llm)
        if served is not None and not same_model(settings.llm.model or "", served):
            raise ValueError(f"服务端返回的模型 {served} 与配置的 {settings.llm.model} 不一致")
        judges = [
            (f"j{i}:{config.model}", Judge(make_llm(config, f"judges[{i}]"), config.effort_twin))
            for i, config in enumerate(settings.judges)
        ]
        write_state(out, settings, judges)
        summary = run_eval(
            settings,
            llm,
            judges,
            selected,
            load_sessions(dataset, selected),
            out,
            variant=variant,
            reps=reps,
            workers=workers,
            timeout_s=timeout_s,
            progress=_progress,
        )
    _say(f"served model: {served or 'not reported'}")
    _say(json.dumps(summary, ensure_ascii=False, indent=2))


@app.command("eval-asr")
def eval_asr_command(
    manifest: Annotated[Path, typer.Option("--manifest", help="评测清单 JSONL：id/audio/text/duration/group")],
    engines: Annotated[Path, typer.Option("--engines", help="引擎 TOML；第一个 [[engine]] 是基线")],
    out: Annotated[Path, typer.Option("--out", help="仓库外的输出目录")],
    split: Annotated[str, typer.Option("--split", help="dev（默认）、formal 或 full")] = "dev",
    size: Annotated[int, typer.Option("--size", help="dev/formal 各抽多少条")] = 1000,
    seed: Annotated[str, typer.Option("--seed")] = "asr-v1",
    cache: Annotated[Path | None, typer.Option("--cache", help="转写缓存目录，默认清单旁的 asr-cache/")] = None,
    allow_in_repo: Annotated[bool, typer.Option("--allow-in-repo")] = False,
) -> None:
    """本机语音识别评测：各引擎转写同一批片段，算字错率并与第一个引擎逐条配对比较；已缓存的转写不重跑。"""
    from .evals.asr import load_engines, run_benchmark
    from .evals.personal import ensure_output_directory
    from .ops.paths import TwinPaths

    last: dict[str, int] = {}

    def progress(name: str, done: int, total: int) -> None:
        step = max(1, total // 10)
        if done == total or done // step != last.get(name, -1) // step:
            _say(f"{name}: {done}/{total}")
        last[name] = done

    with _errors():
        cache_dir = cache if cache is not None else manifest.parent / "asr-cache"
        ensure_output_directory(out, allow_in_repo=allow_in_repo)
        ensure_output_directory(cache_dir, allow_in_repo=allow_in_repo)
        card = run_benchmark(
            manifest,
            load_engines(engines, TwinPaths.from_env().compute / "asr-funasr" / "current"),
            out,
            split=split,
            size=size,
            seed=seed,
            cache_dir=cache_dir,
            progress=progress,
        )
    for engine in card["engines"]:
        strict = engine["metrics"]["strict"]
        _say(f"{engine['engine']}: CER {100 * strict['cer']:.2f}%  RTF {engine['rtf']:.4f}")
    _say(f"成绩单已写入 {out / 'scorecard.md'}。")


@app.command("eval-asr-memory")
def eval_asr_memory_command(
    sessions: Annotated[Path, typer.Option("--sessions", help="AliMeeting 场次清单")],
    base_cache: Annotated[Path, typer.Option("--base-cache", help="原 ASR 缓存 JSONL")],
    clean_cache: Annotated[Path, typer.Option("--clean-cache", help="固定 L4 方案的清洗 JSONL")],
    llm_config: Annotated[Path, typer.Option("--llm-config", help="仅读取 TOML 的 [llm]，不访问用户数据")],
    out: Annotated[Path, typer.Option("--out", help="仓库外输出目录")],
    cache: Annotated[Path, typer.Option("--cache", help="仓库外模型响应缓存")],
    public_alimeeting: Annotated[bool, typer.Option("--public-alimeeting", help="确认仅使用公开 AliMeeting")] = False,
    workers: Annotated[int, typer.Option("--workers", min=1, max=6)] = 2,
    one_target_per_session: Annotated[
        bool, typer.Option("--one-target-per-session", help="按 l6-test-v1 SHA256 每个有 L5 目标的场次选一人")
    ] = False,
    limit: Annotated[int | None, typer.Option("--limit", min=1, help="仅用于 Eval 冒烟检查的人次数")] = None,
) -> None:
    """L6：用原生产抽取和合并比较 gold / ASR / 清洗记忆，并测量重复抽取及裁判噪声。"""
    import tomllib

    from .config import LLMSettings, Settings, make_llm
    from .evals.asr_memory import run_memory_benchmark
    from .evals.personal import ensure_output_directory

    if not public_alimeeting:
        raise typer.BadParameter("必须确认 --public-alimeeting；禁止发送私人录音或资料")
    with _errors():
        ensure_output_directory(out, allow_in_repo=False)
        ensure_output_directory(cache, allow_in_repo=False)
        config = LLMSettings.model_validate(tomllib.loads(llm_config.read_text())["llm"])
        settings = Settings(target_name="本人", llm=config)
        llm = make_llm(config.model_copy(update={"max_retries": 0}))
        card = run_memory_benchmark(
            manifest=sessions,
            base_cache=base_cache,
            clean_cache=clean_cache,
            out=out,
            cache=cache,
            settings=settings,
            llm=llm,
            workers=workers,
            limit=limit,
            one_per_session=one_target_per_session,
        )
    _say(f"L6 已评分 {card['people']} 人次；成绩单：{out / 'scorecard.md'}")


@app.command("eval-asr-session")
def eval_asr_session_command(
    sessions: Annotated[
        Path, typer.Option("--sessions", help="整场清单 JSONL：id/audio/duration/reference/references")
    ],
    engines: Annotated[Path, typer.Option("--engines", help="引擎 TOML：name/command；第一个 [[engine]] 是基线")],
    out: Annotated[Path, typer.Option("--out", help="仓库外的输出目录")],
    cache: Annotated[Path | None, typer.Option("--cache", help="转写缓存目录，默认清单旁的 asr-cache/")] = None,
    allow_in_repo: Annotated[bool, typer.Option("--allow-in-repo")] = False,
) -> None:
    """整场语音识别评测：按 twin [asr] command 转写整场会议，给出切分、说话人和本人话语三层成绩；已缓存的不重跑。"""
    from .evals.asr_session import load_session_engines, run_session_benchmark
    from .evals.personal import ensure_output_directory

    last: dict[str, int] = {}

    def progress(name: str, done: int, total: int) -> None:
        if done != last.get(name):
            _say(f"{name}: {done}/{total}")
        last[name] = done

    with _errors():
        cache_dir = cache if cache is not None else sessions.parent / "asr-cache"
        ensure_output_directory(out, allow_in_repo=allow_in_repo)
        ensure_output_directory(cache_dir, allow_in_repo=allow_in_repo)
        card = run_session_benchmark(
            sessions, load_session_engines(engines), out, cache_dir=cache_dir, progress=progress
        )
    for engine in card["engines"]:
        cer = engine["segmentation"]["strict"]["cer"]["rate"]
        der = engine["speakers"]["der_0.25"]["rate"]
        cpcer = engine["speakers"]["strict"]["cpcer"]["rate"]
        _say(f"{engine['engine']}: 整场 CER {100 * cer:.2f}%  DER {100 * der:.2f}%  cpCER {100 * cpcer:.2f}%")
    _say(f"成绩单已写入 {out / 'scorecard.md'}。")


@app.command("eval-compare")
def personal_eval_compare_command(
    ctx: typer.Context,
    run_a: Annotated[Path, typer.Argument(help="基线 records.json")],
    run_b: Annotated[Path, typer.Argument(help="候选 records.json")],
    out: Annotated[Path, typer.Option("--out")],
    allow_in_repo: Annotated[bool, typer.Option("--allow-in-repo")] = False,
) -> None:
    """按分类配对比较 B-A；按来源文档 bootstrap，不调用模型。"""
    from .evals.personal import ensure_output_directory, read_records, write_comparison

    with _errors():
        ensure_output_directory(out, allow_in_repo=allow_in_repo)
        write_comparison(out, read_records(run_a), read_records(run_b), _settings(ctx), allow_in_repo=allow_in_repo)
    _say("配对比较报告已写入（B - A）。")


survey_app = typer.Typer(
    help="问卷评测：分身答卷，本人不看答案先作答再阅卷；隔两周本人再答一次，得到归一化准确率。", no_args_is_help=True
)
app.add_typer(survey_app, name="survey")
InstrumentOption = Annotated[Path | None, typer.Option("--instrument", help="自定义问卷 JSON（默认内置 48 题）")]
AllowInRepo = Annotated[bool, typer.Option("--allow-in-repo")]


def _survey_out(path: Path, allow_in_repo: bool) -> None:
    from .evals.personal import ensure_output_directory

    ensure_output_directory(path.parent, allow_in_repo=allow_in_repo)
    if path.is_symlink():
        raise ValueError("答卷文件不能是符号链接")


def _survey_grade(path: Path) -> None:
    """Blind grading: the person picks their own answer before the twin's is shown; saved after every item."""
    from .evals.survey import LETTERS, read_sheet, write_sheet

    sheet = read_sheet(path)
    todo = [row for row in sheet.items if row.person.choice is None and not row.person.skipped]
    total = len(sheet.items)
    if not todo:
        _say("这份答卷已经阅完。")
        return
    _say("先选你自己的答案，再看分身选了什么。字母作答，s 跳过这题，q 保存并退出。")
    for row in todo:
        item = row.item
        letters = LETTERS[: len(item.options)]
        _say("")
        _say(f"第 {sheet.items.index(row) + 1}/{total} 题")
        _say(item.question)
        for letter, option in zip(letters, item.options, strict=True):
            _say(f"  {letter}. {option}")
        while True:
            answer = typer.prompt("你会选", default="", show_default=False).strip().upper()
            if answer in {"Q", "S"} or (len(answer) == 1 and answer in letters):
                break
            _say(f"请输入 {letters[0]}–{letters[-1]}，或 s / q。")
        if answer == "Q":
            break
        if answer == "S":
            row.person.skipped = True
        else:
            row.person.choice = letters.index(answer)
            twin = row.twin
            if twin is not None:
                if twin.choice is None:
                    _say("分身选了：没有选（说不知道）")
                else:
                    verdict = "✓ 一样" if twin.choice == row.person.choice else "✗ 不一样"
                    _say(f"分身选了：{LETTERS[twin.choice]}. {item.options[twin.choice]}  {verdict}")
                _say(f"分身的话：{twin.reply.strip()}")
                rating = typer.prompt("分身说的理由像你吗？1–5，回车跳过", default="", show_default=False).strip()
                if rating in {"1", "2", "3", "4", "5"}:
                    row.person.rating = int(rating)
        write_sheet(path, sheet)
    left = sum(1 for row in sheet.items if row.person.choice is None and not row.person.skipped)
    _say(f"已保存。还剩 {left} 题。" if left else "全部阅完。用 twin survey score 看结果。")


@survey_app.command("ask")
@_command_usage("chat")
def survey_ask_command(
    ctx: typer.Context,
    out: Annotated[Path, typer.Option("--out", help="答卷 JSON（仓库外，仅本人可读写）")],
    repeats: Annotated[int, typer.Option("--repeats", min=1, help="每题作答次数，取多数")] = 3,
    as_of: Annotated[str | None, typer.Option("--as-of", help="让分身只用这一天以前的资料作答")] = None,
    force_choice: Annotated[bool, typer.Option("--force-choice", help="资料不够也必须选（和论文做法一致）")] = False,
    baseline: Annotated[
        str | None,
        typer.Option("--baseline", help="换成基线作答：intro 只看自我介绍，blank 没有任何信息；不需要再阅卷"),
    ] = None,
    no_judge: Annotated[bool, typer.Option("--no-judge", help="防泄漏检查只看字面相似，不调用模型")] = False,
    instrument: InstrumentOption = None,
    allow_in_repo: AllowInRepo = False,
) -> None:
    """让分身答问卷，写出待阅的答卷；先检查哪些题记忆里已经答过。"""
    from .evals.survey import ask_baseline, ask_survey, load_instrument, screen_leakage, write_sheet

    with _errors():
        _survey_out(out, allow_in_repo)
        if out.exists():
            raise ValueError(f"{out} 已存在；换一个文件名，避免覆盖已阅的答卷")
        if baseline not in {None, "intro", "blank"}:
            raise typer.BadParameter("应为 intro 或 blank", param_hint="--baseline")
        survey = load_instrument(instrument)
        settings = _settings(ctx)
        with _persona_store(settings) as store:
            if baseline is not None:
                about = (store.get_meta("identity:about") or "") if baseline == "intro" else None
                try:
                    sheet = ask_baseline(
                        _llm(settings, chat=True),
                        survey,
                        about=about,
                        max_workers=settings.max_workers,
                        progress=_progress,
                    )
                except RuntimeError as e:
                    raise _fail(str(e)) from None
            else:
                if profile_stale(store):
                    _progress(STALE_PROFILE_NOTICE)
                flagged = screen_leakage(store, survey, None if no_judge else _llm(settings))
                if flagged:
                    _progress(f"有 {len(flagged)} 题可能已在记忆里答过，照常作答，但默认不计分。")
                twin = PersonaChat(store, _llm(settings, chat=True), _embedder(settings), settings)
                try:
                    sheet = ask_survey(
                        twin,
                        survey,
                        repeats=repeats,
                        as_of=_optional_date(as_of, "--as-of"),
                        force_choice=force_choice,
                        max_workers=settings.max_workers,
                        progress=_progress,
                    )
                except RuntimeError as e:
                    raise _fail(str(e)) from None
                for row in sheet.items:
                    row.leak = flagged.get(row.item.id)
        write_sheet(out, sheet)
    if baseline is not None:
        _say(f"基线已答完，写入 {out}。用 twin survey score {out} --key <已阅的分身答卷> 计分。")
    else:
        _say(f"分身已答完 {len(sheet.items)} 题，答卷写入 {out}。下一步：twin survey grade {out}")


@survey_app.command("grade")
def survey_grade_command(
    sheet: Annotated[Path, typer.Argument(help="twin survey ask 写出的答卷")],
) -> None:
    """阅卷：先选你自己的答案，再看分身的答案并给理由打分；随时可以退出，下次接着阅。"""
    with _errors():
        _survey_grade(sheet)


@survey_app.command("self")
def survey_self_command(
    out: Annotated[Path, typer.Option("--out", help="你自己的答卷（仓库外）")],
    instrument: InstrumentOption = None,
    allow_in_repo: AllowInRepo = False,
) -> None:
    """只有你自己作答，不调用分身；隔两周左右再答一次，用来测你自己的一致性。"""
    from .evals.survey import blank_sheet, load_instrument, write_sheet

    with _errors():
        _survey_out(out, allow_in_repo)
        if not out.exists():
            write_sheet(out, blank_sheet(load_instrument(instrument)))
        _survey_grade(out)


@survey_app.command("score")
def survey_score_command(
    sheet: Annotated[Path, typer.Argument(help="已阅的答卷")],
    retest: Annotated[Path | None, typer.Option("--retest", help="隔一段时间后你自己再答的答卷")] = None,
    key: Annotated[Path | None, typer.Option("--key", help="给基线答卷计分时，用这份已阅的分身答卷做标准答案")] = None,
    include_leaked: Annotated[bool, typer.Option("--include-leaked", help="把记忆里可能已答过的题也算进去")] = False,
    out: Annotated[Path | None, typer.Option("--out", help="把报告写入 Markdown 文件")] = None,
) -> None:
    """统计准确率、作答率、各方面和性格；给了 --retest 再算归一化准确率。不调用模型。"""
    from .evals.survey import apply_key, read_sheet, score_markdown, score_sheet

    with _errors():
        scored = read_sheet(sheet)
        if key is not None:
            scored = apply_key(scored, read_sheet(key))
        summary = score_sheet(scored, read_sheet(retest) if retest is not None else None, include_leaked=include_leaked)
        text = score_markdown(summary)
        if out is not None:
            _write(out, text)
            _say(f"已写入 {out}")
        else:
            _say(text)


media_app = typer.Typer(help="已保存回答的展示、语音合成与合成句集回听评测。")
app.add_typer(media_app, name="media")


def _media_source(ctx: typer.Context, source: Path, kind: str, persona_name: str | None) -> MediaScript:
    """Load a validated runtime answer, not a generated or rewritten presentation."""
    from .media.adapters import presentable_from_payload
    from .media.script import script_from_presentable

    if kind not in {"chat_reply"}:
        raise typer.BadParameter("来源应为 chat_reply", param_hint="--kind")
    name = persona_name if persona_name is not None else _settings(ctx).target_name
    presentable = presentable_from_payload(kind, json.loads(source.read_bytes()))
    return script_from_presentable(presentable, name)


@media_app.command("script")
def media_script_command(
    ctx: typer.Context,
    source: Annotated[Path, typer.Argument(help="已保存的 ChatReply JSON")],
    out: Annotated[Path, typer.Option("--out", help="脚本 JSON 输出（仅本人可读写）")],
    kind: Annotated[str, typer.Option("--kind", help="chat_reply")] = "chat_reply",
    persona_name: Annotated[str | None, typer.Option("--persona-name", help="分身的名字（默认使用配置）")] = None,
) -> None:
    """Write a presentation script without calling a model."""
    with _errors():
        script = _media_source(ctx, source, kind, persona_name)
        _write(out, script.model_dump_json(indent=2) + "\n")
    _say(f"已写入 {out}")


@media_app.command("export")
def media_export_command(
    ctx: typer.Context,
    source: Annotated[Path, typer.Argument(help="已保存的 ChatReply JSON")],
    out: Annotated[Path, typer.Option("--out", help="独立 HTML 输出（仅本人可读写）")],
    kind: Annotated[str, typer.Option("--kind", help="chat_reply")] = "chat_reply",
    persona_name: Annotated[str | None, typer.Option("--persona-name", help="分身的名字（默认使用配置）")] = None,
) -> None:
    """Export standalone HTML with source metadata and no JavaScript."""
    from .media.render import export_html

    with _errors():
        _write(out, export_html(_media_source(ctx, source, kind, persona_name), clock=lambda: dt.datetime.now(dt.UTC)))
    _say(f"已写入 {out}")


@media_app.command("speak")
def media_speak_command(
    ctx: typer.Context,
    source: Annotated[Path, typer.Argument(help="已保存的 ChatReply JSON")],
    out: Annotated[Path, typer.Option("--out", help="语音与清单输出目录（仅本人可访问）")],
    kind: Annotated[str, typer.Option("--kind", help="chat_reply")] = "chat_reply",
    name: Annotated[str | None, typer.Option("--name", help="分身的名字（默认使用配置）")] = None,
) -> None:
    """Render speech files and a manifest from a validated saved answer."""
    from .config import make_synthesizer
    from .media.render import render_audio
    from .media.script import speech_script
    from .media.tts import MediaError

    with _errors():
        script = speech_script(_media_source(ctx, source, kind, name))
        settings = _settings(ctx)
        try:
            synthesizer = make_synthesizer(settings.tts)
        except RenameError as e:
            raise _fail(str(e)) from None
        except (MediaError, ValueError):
            raise _fail("语音未配置或不可用，请检查 [tts] 配置和密钥环境变量") from None
        if synthesizer.name == "silent":
            raise _fail("语音未配置，请先设置 [tts] 语音服务与预置音色")
        private_directory(out)
        out.chmod(0o700)
        requests = out / "requests"
        private_directory(requests)
        requests.chmod(0o700)
        try:
            rendered = render_audio(script, synthesizer, out)
        except MediaError:
            raise _fail("语音合成失败，请检查语音服务、预置音色和语言配置后重试") from None
    _say(f"已写入语音与清单：{out / rendered.manifest_file}")


@media_app.command("clip")
def media_clip_command(
    ctx: typer.Context,
    source: Annotated[Path, typer.Argument(help="已保存的 ChatReply JSON")],
    out: Annotated[Path, typer.Option("--out", help="MP4 输出（仅本人可读写）")],
    kind: Annotated[str, typer.Option("--kind", help="chat_reply")] = "chat_reply",
    name: Annotated[str | None, typer.Option("--name", help="分身的名字（默认使用配置）")] = None,
) -> None:
    """Export an existing reply with a stylized avatar and subtitles."""
    from .config import make_synthesizer
    from .media.clip import render_clip
    from .media.schema import AVATAR_PRESETS
    from .media.tts import MediaError
    from .persona.store import stored_avatar

    with _errors():
        try:
            script = _media_source(ctx, source, kind, name)
        except (ValueError, OSError):
            raise _fail("无法读取回答，请检查输入文件是否为有效的 ChatReply JSON") from None
        settings = _settings(ctx)
        try:
            synthesizer = make_synthesizer(settings.tts)
        except (MediaError, ValueError):
            raise _fail("语音未配置或不可用，请检查 [tts] 配置和密钥环境变量") from None
        try:
            render_clip(
                script,
                synthesizer,
                AVATAR_PRESETS[stored_avatar(settings.db_path, settings.avatar.preset)],
                out,
                font_path=settings.media.font_path,
            )
        except MediaError as exc:
            raise _fail(str(exc)) from None
    _say(f"已写入 {out}")


@media_app.command("video")
def media_video_command(
    ctx: typer.Context,
    source: Annotated[Path, typer.Argument(help="已保存的 ChatReply JSON")],
    out: Annotated[Path, typer.Option("--out", help="MP4 输出（仅本人可读写）")],
    kind: Annotated[str, typer.Option("--kind", help="chat_reply")] = "chat_reply",
    name: Annotated[str | None, typer.Option("--name", help="分身的名字（默认使用配置）")] = None,
) -> None:
    """Generate a video through a configured, generic remote job."""
    from .config import make_video_synthesizer
    from .media.tts import MediaError

    with _errors():
        try:
            script = _media_source(ctx, source, kind, name)
        except (ValueError, OSError):
            raise _fail("无法读取回答，请检查输入文件是否为有效的 ChatReply JSON") from None
        try:
            synthesizer = make_video_synthesizer(_settings(ctx))
            if synthesizer is None:
                raise _fail("视频未配置，请先设置 [video]")
            result = synthesizer.synthesize(script, out)
        except MediaError as exc:
            raise _fail(str(exc)) from None
    _say(f"已写入 {out}，时长 {result.duration_s:g} 秒")
    for segment in result.segments:
        if segment.cer > _settings(ctx).video.max_cer:
            _say(f"回听警告：{segment.id} cer={segment.cer:g}")
    if result.warnings and not any(s.cer > _settings(ctx).video.max_cer for s in result.segments):
        _say("视频生成有提示，请检查回听结果")


@media_app.command("check", help="合成句集回听评测：字错率、延迟与后端指纹。")
def media_check_command(
    ctx: typer.Context,
    out: Annotated[Path, typer.Option("--out", help="回听评测报告目录（仅本人可访问）")],
    sentences: Annotated[Path | None, typer.Option("--sentences", help="JSONL 句集，每行包含 text")] = None,
    repeats: Annotated[int, typer.Option("--repeats", min=1, help="每句独立合成与识别次数（不复用缓存）")] = 1,
) -> None:
    """Evaluate synthetic sentences using configured synthesis and recognition backends."""
    from .config import make_recognizer, make_synthesizer
    from .media.check import DEFAULT_SENTENCES, load_sentences, run_check
    from .media.tts import MediaError

    with _errors():
        settings = _settings(ctx)
        texts = load_sentences(sentences) if sentences is not None else DEFAULT_SENTENCES
        try:
            synthesizer = make_synthesizer(settings.tts)
            recognizer = make_recognizer(settings.asr)
            report = run_check(synthesizer, recognizer, out, texts, language=settings.asr.language, repeats=repeats)
        except RenameError as e:
            raise _fail(str(e)) from None
        except (MediaError, ValueError):
            raise _fail("回听评测失败，请检查 [tts]、[asr] 配置、语言与密钥环境变量") from None
    ratio = report.synthesis_wall_per_audio_s
    latency = f"{ratio:.4f}" if ratio is not None else "未知"
    _say(
        f"回听评测：{len(report.sentences)} 句 × {report.repeats} 次，CER {report.cer:.4f}，"
        f"整轮平均 CER {report.mean_cer:.4f}，最差整轮 CER {report.worst_repeat_cer:.4f}，"
        f"不完整重复 {report.incomplete_repeats}，警告分片 {report.warning_parts}，合成秒/音频秒 {latency}，"
        f"疑似繁体 {report.traditional_sentence_count} 句；已写入 {out}"
    )
