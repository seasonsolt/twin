"""``twin`` command line. Results go to stdout; progress, warnings and errors go to stderr."""

from __future__ import annotations

import datetime as dt
import ipaddress
import json
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
from .embed import Embedder, EmbedError
from .llm import CallTally, LLMError
from .media.schema import MediaScript
from .persona.chat import PersonaChat, index_persona
from .persona.coverage import coverage_report
from .persona.coverage import report_markdown as coverage_markdown
from .persona.profile import build_profile, consented_facets
from .persona.schema import SOURCE_KIND_LABELS, ChatTurn, SourceKind
from .persona.sources import parse_source
from .persona.store import PersonaStore
from .usage import BudgetExceeded, UsageRecorder, active_recorder, call_stage, failure_directory, record_usage
from .util import RenameError, open_private, private_directory

DEFAULT_CONFIG = Path("twin.toml")
CONFIG_TEMPLATE = """# 通用个人分身：身份 → 记忆资料 → 服务。密钥仅从环境变量读取。
target_name = "本人"
target_aliases = []
db_path = "data/twin.db"
max_workers = 4

[llm]
provider = "openai_compat"
# 请设置内网模型名及端点；未配置不会调用公网默认端点。
# model = "your-model"
# base_url = "http://127.0.0.1:8000/v1"
api_key_env = "TWIN_LLM_KEY"

[embed]
provider = "hashing"
api_key_env = "TWIN_EMBED_KEY"

# 可选 [tts] / [asr] 配置见 docs/MEDIA.md。
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
            models = [settings.llm, *settings.judges]
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


def _llm(settings: Settings) -> CallTally:
    try:
        llm = make_llm(settings.llm)
    except Exception as e:
        raise _fail(
            f"无法初始化大模型后端 {settings.llm.provider}：{e}（密钥只能通过环境变量提供，见 README 的配置一节）"
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
    """Write an owner-only (0600) file: outputs quote meeting transcripts and the cognitive model."""
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


def _serve(application: Any, host: str, port: int, url: str, open_browser: bool) -> None:
    """Bind first, so a busy port is reported in Chinese before uvicorn starts, then serve until Ctrl-C."""
    import uvicorn

    address = host.strip().strip("[]")
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    try:
        sock = socket.create_server((address, port), family=family)
    except OSError as e:
        raise _fail(f"无法在 {host}:{port} 上启动网页界面：{e}（端口可能已被占用，可以用 --port 换一个端口）") from e
    server = uvicorn.Server(uvicorn.Config(application, log_level="warning"))
    _say(f"网页界面：{url}（按 Ctrl-C 停止）")
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
            "公网访问前必须在代理层加登录保护",
        ),
    ] = None,
) -> None:
    """启动本机网页界面：问卷、资料导入、人格档案、完成度和聊天。

    数据都留在本机：默认只监听 127.0.0.1，页面不加载任何外部资源。
    """
    settings = _settings(ctx)
    from .web import create_app

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
                    "同一网络里能连到这台机器的人，不需要登录就能查看个人资料、人格档案和聊天结果，",
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


persona_app = typer.Typer(
    help="通用数字分身：导入问卷、聊天记录、访谈、文档 → 人格档案 → 完成度 → 聊天。", no_args_is_help=True
)
app.add_typer(persona_app, name="persona")


def _persona_store(settings: Settings) -> PersonaStore:
    return PersonaStore(settings.db_path)


@persona_app.command("import")
def persona_import(
    ctx: typer.Context,
    paths: Annotated[list[Path], typer.Argument(help="要导入的文件，可以多个")],
    kind: Annotated[SourceKind, typer.Option("--kind", help="资料类型")],
    date: Annotated[str | None, typer.Option("--date", help="资料日期（问卷、访谈、文档；默认从文件名识别）")] = None,
) -> None:
    """导入资料。同一个文件内容不变时重复导入只会覆盖，不会重复。"""
    settings = _settings(ctx)
    when = _optional_date(date, "--date")
    with _persona_store(settings) as store:
        for path in paths:
            if not path.is_file():
                raise _fail(f"找不到文件 {path}")
            try:
                parsed = parse_source(kind, path, settings, when)
            except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as e:
                raise _fail(f"{path}：{e}") from e
            new = store.put_source(parsed)
            s = parsed.source
            span = f"{s.first_date or '—'} 至 {s.last_date or '—'}"
            _say(
                f"{'导入' if new else '已更新'} {path.name}（{SOURCE_KIND_LABELS[s.kind]}）：{s.n_expressions} 条，"
                f"本人 {s.n_target} 条，{span}"
                + (f"；未授权细项 {'、'.join(s.declined_facets)}" if s.declined_facets else "")
                + (f"；无法识别的行 {len(parsed.skipped_lines)} 行" if parsed.skipped_lines else "")
            )


@persona_app.command("sources")
def persona_sources(ctx: typer.Context) -> None:
    """列出已导入的资料。"""
    with _persona_store(_settings(ctx)) as store:
        for s in store.list_sources():
            _say(
                f"{s.source_id}  {SOURCE_KIND_LABELS[s.kind]}  {s.title}  本人 {s.n_target}/{s.n_expressions} 条  "
                f"{s.first_date or '—'} 至 {s.last_date or '—'}"
            )


@persona_app.command("build")
@_command_usage("build")
def persona_build(ctx: typer.Context) -> None:
    """抽取并合并人格档案，再更新检索向量；只处理新增或变化的部分。"""
    settings = _settings(ctx)
    llm = _llm(settings)
    embedder = _embedder(settings)
    with _persona_store(settings) as store:
        report = build_profile(store, llm, settings, _progress)
        for failure in report.failures:
            _progress(f"FAILED {failure}")
        _require_working_calls(llm, "人格档案")
        try:
            index_persona(store, embedder, settings, _progress)
        except EmbedError as e:
            raise _fail(f"向量化失败：{e}") from e
        _say(
            f"资料 {report.sources} 份，分块 {report.chunks_total}（本次抽取 {report.chunks_extracted}），"
            f"候选 {report.candidates} 条，合并细项 {report.facets_merged} 个，档案条目 {report.items} 条"
        )
        if report.failures:
            raise typer.Exit(code=1)


@persona_app.command("coverage")
def persona_coverage(
    ctx: typer.Context,
    as_of: Annotated[str | None, typer.Option("--as-of", help="按这一天计算（默认今天）")] = None,
    out: Annotated[Path | None, typer.Option("--out", help="把报告写入 Markdown 文件")] = None,
) -> None:
    """人格复刻完成度：维度汇总、细项 × 来源矩阵、下一步采集建议。"""
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
    as_of: Annotated[str | None, typer.Option("--as-of", help="只用这一天及以前的资料")] = None,
) -> None:
    """和数字分身聊天。"""
    settings = _settings(ctx)
    when = _optional_date(as_of, "--as-of")
    with _persona_store(settings) as store:
        twin = PersonaChat(store, _llm(settings), _embedder(settings), settings)
        history: list[ChatTurn] = []
        while True:
            text = message if message is not None else typer.prompt("你", default="", show_default=False)
            if not text.strip():
                return
            history.append(ChatTurn(role="user", content=text))
            try:
                answer = twin.reply(history, as_of=when)
            except (LLMError, EmbedError) as e:
                raise _fail(str(e)) from e
            history.append(ChatTurn(role="twin", content=answer.reply))
            flag = f"（弃权：{answer.abstain_reason}）" if answer.abstain else ""
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
    """本人资料评测；update 仅标记未运行，不修改记忆。"""
    from .config import configuration_fingerprint
    from .evals.personal import (
        PersonaSystem,
        ensure_output_directory,
        load_evalset,
        make_panel,
        run_evaluation,
        select_cases,
        write_outputs,
    )

    ensure_output_directory(out, allow_in_repo=allow_in_repo)
    selected = [part.strip() for value in categories for part in value.split(",")] if categories else None
    cases = select_cases(load_evalset(evalset), selected)
    settings = _settings(ctx)
    _usage_output.set(out)
    try:
        llm = make_llm(settings.llm)
        embedder = make_embedder(settings.embed)
        panel = make_panel(settings)
        identity = configuration_fingerprint(
            settings,
            llm,
            embedder,
            [(f"j{i}:{judge.llm.name}", judge.effort) for i, judge in enumerate(panel)],
            experiment={"repeats": repeats, "rubric_version": "1"},
        )
        with _persona_store(settings) as store:
            report = run_evaluation(
                cases,
                PersonaSystem(PersonaChat(store, llm, embedder, settings)),
                panel,
                persona_ref,
                repeats=repeats,
                max_workers=settings.max_workers,
                fingerprints={"configuration": identity},
            )
        write_outputs(out, report, settings, allow_in_repo=allow_in_repo)
    except Exception:
        # Neither SDK errors nor runtime validation errors may echo personal prompts or answers.
        raise _fail("本人资料评测失败；请检查配置、参考文本和输出权限（详情已隐藏）") from None
    _say("评测报告已写入；update 未运行：需要受控记忆编辑。")


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


media_app = typer.Typer(help="已保存回答的带标识展示、语音合成与合成句集回听评测。")
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
    persona_name: Annotated[str | None, typer.Option("--persona-name", help="默认配置中的目标人物")] = None,
) -> None:
    """Write a labelled presentation script without calling a model."""
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
    persona_name: Annotated[str | None, typer.Option("--persona-name", help="默认配置中的目标人物")] = None,
) -> None:
    """Export standalone HTML with visible and implicit AI labels and no JavaScript."""
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
    name: Annotated[str | None, typer.Option("--name", help="默认配置中的目标人物")] = None,
) -> None:
    """Render labelled speech files and a manifest from a validated saved answer."""
    from .config import make_synthesizer
    from .media.render import render_audio
    from .media.tts import MediaError

    with _errors():
        script = _media_source(ctx, source, kind, name)
        try:
            synthesizer = make_synthesizer(_settings(ctx).tts)
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
