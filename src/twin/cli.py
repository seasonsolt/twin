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
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from pathlib import Path
from typing import Annotated, Any

import typer

from .config import Settings, check_config_rename, load_settings, make_embedder, make_llm
from .egress import egress_status
from .embed import Embedder, EmbedError
from .identity import Identity
from .llm import CallTally, LLMError
from .media.schema import MediaScript
from .persona.chat import PersonaChat, index_persona
from .persona.coverage import coverage_report
from .persona.coverage import report_markdown as coverage_markdown
from .persona.profile import STALE_PROFILE_NOTICE, build_profile, consented_facets, profile_stale, source_memories
from .persona.schema import SOURCE_KIND_LABELS, ChatTurn, SourceKind
from .persona.sources import MEMORY_KIND_LABELS, parse_note, parse_source
from .persona.store import PersonaStore
from .persona.text import SUPPORTED_SUFFIXES
from .usage import BudgetExceeded, UsageRecorder, active_recorder, call_stage, failure_directory, record_usage
from .util import RenameError, open_private, private_directory

DEFAULT_CONFIG = Path("twin.toml")
CONFIG_TEMPLATE = """# 通用个人分身：身份 → 记忆资料 → 服务。密钥仅从环境变量读取。
target_name = "本人"
target_aliases = []
db_path = "data/twin.db"
max_workers = 4

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

# 企业微信智能机器人在分身档案 → 接入 → 绑定，见 docs/GUIDE.md。

# [api] # 对外服务：令牌值仅放环境变量，至少 32 个字符，见 docs/SERVICE.md。
# token_env = "TWIN_API_TOKEN"
# rate_per_minute = 30 # 每个令牌每分钟最多请求数（滑动窗口）。

# [auth] # 公网网页必须启用；默认 false 为无登录、管理员模式（仅本机开发）。
# enabled = true
# allowed_domains = ["xjjk.com"] # 只匹配 @ 后的完整域名，不匹配子域名
# allowed_emails = ["seasonsolt@gmail.com"]
# admin_emails = ["seasonsolt@gmail.com"]
# session_days = 30
# max_personas_per_member = 3
# [auth.smtp] # 465 使用 SSL，587 使用 STARTTLS；启用 auth 时必填
# host = "smtp.example.com"
# port = 465
# username = "your-smtp-account"
# from_address = "twin@example.com"
# from_name = "twin"
# password_env = "TWIN_SMTP_PASSWORD" # 密码只在环境变量，绝不写入文件

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
    except (ValueError, OSError, sqlite3.Error, LLMError, EmbedError, BudgetExceeded) as e:
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
        path = DEFAULT_CONFIG
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
def main(ctx: typer.Context, config: ConfigOption = None) -> None:
    with _errors():
        check_config_rename()
    ctx.obj = config


@app.command()
def init(
    ctx: typer.Context,
    path: Annotated[Path | None, typer.Argument(help="要生成的配置文件路径（默认 --config 或 ./twin.toml）")] = None,
    force: Annotated[bool, typer.Option("--force", help="覆盖已存在的文件")] = False,
) -> None:
    """生成带中文注释的 twin.toml 配置模板。"""
    target = path or _config_path(ctx) or DEFAULT_CONFIG
    if target.exists() and not force:
        raise _fail(f"{target} 已存在；如需覆盖请加 --force")
    with _errors():
        _write(target, CONFIG_TEMPLATE)
    _say(f"已生成配置文件 {target}。请先修改 target_name 和 [llm] 部分，密钥通过环境变量提供。")


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
            "公网访问前必须配置 [auth] enabled = true 及 SMTP 邮箱验证码登录",
        ),
    ] = None,
) -> None:
    """启动本机网页界面：问卷、资料导入、人格档案、完成度和聊天。

    数据都留在本机：默认只监听 127.0.0.1，页面不加载任何外部资源。
    """
    settings = _settings(ctx)
    from .web import create_app

    channels_logger = logging.getLogger("twin.channels")
    if not channels_logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setLevel(logging.INFO)
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
        channels_logger.addHandler(handler)
    channels_logger.setLevel(logging.INFO)
    channels_logger.propagate = False

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


persona_app = typer.Typer(
    help="通用数字分身：导入问卷、聊天记录、访谈、文档 → 人格档案 → 完成度 → 聊天。", no_args_is_help=True
)
app.add_typer(persona_app, name="persona")


def _persona_store(settings: Settings) -> PersonaStore:
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
            _say(
                f"{'导入' if new else '已更新'} {path.name}（{MEMORY_KIND_LABELS[s.kind]}）：{s.n_expressions} 条，"
                f"本人 {s.n_target} 条，{span}"
                + (f"；未授权细项 {'、'.join(s.declined_facets)}" if s.declined_facets else "")
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
            )


@persona_app.command("build")
@_command_usage("build")
def persona_build(ctx: typer.Context) -> None:
    """抽取并合并人格档案，再更新检索向量；只处理新增或变化的部分。"""
    settings = _settings(ctx)
    with _persona_store(settings) as store:
        if profile_stale(store):
            _progress(STALE_PROFILE_NOTICE)
        llm = _llm(settings)
        embedder = _embedder(settings)
        report = build_profile(store, llm, settings, _progress)
        for failure in report.failures:
            _progress(f"FAILED {failure}")
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
            _progress(STALE_PROFILE_NOTICE)
        twin = PersonaChat(store, _llm(settings, chat=True), _embedder(settings), settings)
        history: list[ChatTurn] = []
        while True:
            text = message if message is not None else typer.prompt("你", default="", show_default=False)
            if not text.strip():
                return
            history.append(ChatTurn(role="user", content=text))
            try:
                answer = twin.reply(history)
            except (LLMError, EmbedError) as e:
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
) -> None:
    """LongMemEval through production Twin, with an optional retrieval baseline. ``[[judges]]`` tables, when
    configured, judge instead of the main ``llm``."""
    try:
        report = _run_longmemeval(
            _benchmark_settings(ctx, keep_judges=True),
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
    score: bool,
) -> dict[str, Any]:
    from .evals.longmemeval import load_dataset, run_evaluation, select_cases, validate_output
    from .util import fingerprint

    out = validate_output(out)
    with dataset.open("rb") as stream:
        dataset_sha = hashlib.file_digest(stream, "sha256").hexdigest()
    cases = select_cases(load_dataset(dataset), limit=limit, offset=offset, per_type=per_type, seed=seed, split=split)
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
    return run_evaluation(cases, out, settings, system=system, dry_run=dry_run, score=True, fingerprints=identities)


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
    return run_evaluation(cases, out, settings, system=system, dry_run=dry_run, score=True, fingerprints=identities)


SUITE_SIZES = {"dev": {"lme": 3, "pm": 24, "t2k": 4}, "formal": {"lme": 5, "pm": 30, "t2k": 10}}


@app.command("eval-suite")
def eval_suite_command(
    ctx: typer.Context,
    out: Annotated[Path, typer.Option("--out", help="Fresh private suite directory outside git repositories")],
    split: Annotated[str, typer.Option("--split", help=SPLIT_HELP)] = "dev",
    repeats: Annotated[int, typer.Option("--repeats", min=1, help="Full runs per benchmark, to measure noise")] = 2,
    longmemeval: Annotated[Path | None, typer.Option("--longmemeval", help="LongMemEval S cleaned JSON")] = None,
    personamem_questions: Annotated[Path | None, typer.Option("--personamem-questions")] = None,
    personamem_contexts: Annotated[Path | None, typer.Option("--personamem-contexts")] = None,
    twin2k500: Annotated[Path | None, typer.Option("--twin2k500", help="Twin-2K-500 wave_split JSON/JSONL")] = None,
    lme_per_type: Annotated[int | None, typer.Option("--lme-per-type", min=1)] = None,
    pm_sample: Annotated[int | None, typer.Option("--pm-sample", min=1)] = None,
    t2k_participants: Annotated[int | None, typer.Option("--t2k-participants", min=1)] = None,
    baseline: Annotated[Path | None, typer.Option("--baseline", help="Earlier scorecard.json to compare with")] = None,
) -> None:
    """Run the three public benchmarks ``--repeats`` times through production Twin and write a scorecard.

    Iterate on the ``dev`` split; run ``formal`` only to record a milestone. Benchmarks run concurrently, repeats of
    one benchmark run in sequence, and each run lands in ``<out>/<benchmark>/r<n>/``.
    """
    from concurrent.futures import ThreadPoolExecutor

    from .evals.longmemeval import validate_output
    from .evals.scorecard import build_scorecard, compare, write_scorecard

    if split not in SUITE_SIZES:
        raise _fail("--split must be formal or dev")
    if (personamem_questions is None) != (personamem_contexts is None):
        raise _fail("PersonaMem needs both --personamem-questions and --personamem-contexts")
    sizes = {
        "lme": lme_per_type or SUITE_SIZES[split]["lme"],
        "pm": pm_sample or SUITE_SIZES[split]["pm"],
        "t2k": t2k_participants or SUITE_SIZES[split]["t2k"],
    }
    jobs: dict[str, Callable[[Settings, Path], dict[str, Any]]] = {}
    if longmemeval is not None:
        lme_dataset = longmemeval
        jobs["longmemeval"] = lambda settings, run: _run_longmemeval(
            settings, lme_dataset, run, limit=3, offset=0, per_type=sizes["lme"], seed="longmemeval-v1",
            split=split, system="twin", dry_run=False, score=True,
        )  # fmt: skip
    if personamem_questions is not None and personamem_contexts is not None:
        pm_questions, pm_contexts = personamem_questions, personamem_contexts
        jobs["personamem"] = lambda settings, run: _run_personamem(
            settings, pm_questions, pm_contexts, run, limit=3, offset=0, sample=sizes["pm"], seed="personamem-v1",
            split=split, system="twin", dry_run=False,
        )  # fmt: skip
    if twin2k500 is not None:
        t2k_dataset = twin2k500
        jobs["twin2k500"] = lambda settings, run: _run_twin2k500(
            settings, t2k_dataset, run, limit=None, offset=0, participants=sizes["t2k"], seed="twin2k500-v1",
            split=split, system="twin", dry_run=False,
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
        judged = _benchmark_settings(ctx, keep_judges=True)
        plain = _benchmark_settings(ctx)
    except Exception:
        raise _fail("Suite setup failed; check configuration, baseline and a fresh empty output directory") from None

    def run_benchmark(name: str) -> list[dict[str, Any]]:
        settings = judged if name == "longmemeval" else plain
        reports = []
        for index in range(1, repeats + 1):
            run = out / name / f"r{index}"
            private_directory(run)
            reports.append(jobs[name](settings, run))
            _progress(f"{name} r{index}/{repeats} done")
        return reports

    failed: list[str] = []
    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        futures = {name: pool.submit(run_benchmark, name) for name in jobs}
        for name, future in futures.items():
            try:
                if any(_benchmark_failed(report) for report in future.result()):
                    failed.append(name)
            except Exception:
                failed.append(name)
                _progress(f"{name} stopped early (details hidden)")
    try:
        card = build_scorecard(out, _suite_metadata(split, repeats, sizes))
        write_scorecard(out, card, compare(card, previous) if previous is not None else None)
    except Exception:
        raise _fail("Scorecard failed; every repeat of a benchmark must finish (details hidden)") from None
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
