from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from twin import cli
from twin.config import Settings, load_settings
from twin.ops import demo, ollama
from twin.ops.envfile import load_env_file, selected_env_file
from twin.ops.local import check_local_config, ensure_asr, ensure_embed, set_llm_value
from twin.ops.paths import TwinPaths
from twin.persona.schema import SourceKind
from twin.persona.sources import expression_view, parse_note, parse_source
from twin.persona.store import PersonaStore

ROOT = Path(__file__).resolve().parents[1]
RUNNER = CliRunner()


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    for key in ("TWIN_CONFIG", "LOCAL_TEST_VALUE", "LOCAL_TEST_ONLY", "LOCAL_TEST_KEY"):
        monkeypatch.delenv(key, raising=False)


def private_env(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    path.chmod(0o600)


@pytest.mark.parametrize("choice", ["explicit", "local", "deployed", "missing_explicit"])
def test_cli_env_precedence(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, choice: str) -> None:
    deployed = TwinPaths.from_env().env
    private_env(deployed, "LOCAL_TEST_VALUE=deployed\nLOCAL_TEST_ONLY=deployed\n")
    local = tmp_path / ".env"
    if choice != "deployed":
        private_env(local, "LOCAL_TEST_VALUE=local\n")
    explicit = tmp_path / "explicit env"
    if choice == "explicit":
        private_env(explicit, "LOCAL_TEST_VALUE=explicit\n")
    if choice in {"explicit", "missing_explicit"}:
        monkeypatch.setenv("TWIN_ENV_FILE", str(explicit))
    Path("twin.toml").write_text("")
    result = RUNNER.invoke(cli.app, ["init", "other.toml"])
    assert result.exit_code == 0, result.output
    assert os.environ.get("LOCAL_TEST_VALUE") == (None if choice == "missing_explicit" else choice)
    assert os.environ.get("LOCAL_TEST_ONLY") == ("deployed" if choice == "deployed" else None)
    monkeypatch.delenv("LOCAL_TEST_VALUE", raising=False)
    monkeypatch.delenv("LOCAL_TEST_ONLY", raising=False)


def test_local_env_never_overwrites_process(monkeypatch: pytest.MonkeyPatch) -> None:
    private_env(Path(".env"), "LOCAL_TEST_VALUE=file\n")
    Path("twin.toml").write_text("")
    monkeypatch.setenv("LOCAL_TEST_VALUE", "process")
    result = RUNNER.invoke(cli.app, ["init", "other.toml"])
    assert result.exit_code == 0
    assert os.environ["LOCAL_TEST_VALUE"] == "process"


def test_cli_rejects_local_env_permissions_without_fallback() -> None:
    Path(".env").write_text("LOCAL_TEST_VALUE=hidden-value\n")
    Path(".env").chmod(0o644)
    Path("twin.toml").write_text("")
    private_env(TwinPaths.from_env().env, "LOCAL_TEST_VALUE=deployed\n")
    result = RUNNER.invoke(cli.app, ["init", "other.toml"])
    assert result.exit_code == 1
    assert "chmod 600 .env" in result.output
    assert "hidden-value" not in result.output
    assert "LOCAL_TEST_VALUE" not in os.environ
    assert not Path("other.toml").exists()


def test_env_outside_twin_checkout_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    Path(".env").write_text("LOCAL_TEST_VALUE=other-project\n")
    Path(".env").chmod(0o644)
    private_env(TwinPaths.from_env().env, "LOCAL_TEST_VALUE=deployed\n")
    assert selected_env_file() == TwinPaths.from_env().env
    result = RUNNER.invoke(cli.app, ["init", "other.toml"])
    assert result.exit_code == 0, result.output
    assert os.environ.get("LOCAL_TEST_VALUE") == "deployed"
    monkeypatch.delenv("LOCAL_TEST_VALUE")


def test_doctor_checks_selected_env(monkeypatch: pytest.MonkeyPatch) -> None:
    private_env(Path(".env"), "")
    Path("twin.toml").write_text("")
    checked = []

    def inspect(paths, *args, **kwargs):  # type: ignore[no-untyped-def]
        checked.append(paths.env)
        return []

    monkeypatch.setattr("twin.ops.doctor.inspect_installation", inspect)
    result = RUNNER.invoke(cli.app, ["doctor"])
    assert result.exit_code == 0, result.output
    assert checked == [Path(".env")]


def test_env_permission_advice_quotes_spaces(tmp_path: Path) -> None:
    path = tmp_path / "my env"
    path.write_text("")
    path.chmod(0o644)
    with pytest.raises(PermissionError, match="chmod 600 '"):
        load_env_file(path)


@pytest.mark.parametrize(
    "filename,kind",
    list(
        zip(
            demo.DEMO_FILES,
            [SourceKind.DOCUMENT, SourceKind.CHAT, SourceKind.CHAT, SourceKind.INTERVIEW, SourceKind.DOCUMENT],
            strict=True,
        )
    ),
)
def test_demo_sources_detected(tmp_path: Path, filename: str, kind: SourceKind) -> None:
    settings = Settings(db_path=tmp_path / "twin.db", target_name=demo.DEMO_NAME, target_aliases=["林舟"])
    parsed = parse_source(None, demo.DEMO_DIRECTORY / filename, settings)
    assert parsed.source.kind is kind
    assert parsed.source.n_target > 0
    assert not parsed.skipped_lines
    assert "虚构示例" in (demo.DEMO_DIRECTORY / filename).read_text()
    assert all(expression.date is not None for expression in parsed.expressions)
    if kind in {SourceKind.CHAT, SourceKind.INTERVIEW}:
        assert parsed.source.n_target < parsed.source.n_expressions


def test_demo_seed_isolated_idempotent_force(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def forbidden(*args, **kwargs):  # type: ignore[no-untyped-def]
        pytest.fail("demo seed must not construct model backends")

    monkeypatch.setattr(cli, "make_llm", forbidden)
    monkeypatch.setattr(cli, "make_embedder", forbidden)
    directory = tmp_path / "examples"
    shutil.copytree(demo.DEMO_DIRECTORY, directory)
    monkeypatch.setattr(demo, "DEMO_DIRECTORY", directory)
    Path("twin.toml").write_text('db_path = "data/twin.db"\n')
    settings = Settings(db_path=Path("data/twin.db"))
    with PersonaStore(settings.db_path) as store:
        store.put_source(parse_note("默认分身的私有笔记", settings, "原笔记"))
        default_sources = store.list_sources()
    first = RUNNER.invoke(cli.app, ["demo", "seed"])
    assert first.exit_code == 0, first.output
    assert "本次导入 5 份" in first.output
    registry = json.loads(Path("data/personas.json").read_text())
    assert len(registry["personas"]) == 2
    entry = next(item for item in registry["personas"] if item["id"] != "default")
    db = Path("data/personas") / entry["id"] / "twin.db"
    with PersonaStore(db) as store:
        assert store.get_meta("identity:name") == demo.DEMO_NAME
        sources = store.list_sources()
        assert len(sources) == 5
        before = store.get_meta("sources_changed_at")
        view = expression_view(store, settings.model_copy(update={"db_path": db, "target_name": demo.DEMO_NAME}))
        assert any(e.speaker.startswith("他人") for e in view)
        assert all("岚禾" not in e.text + e.context + e.speaker for e in view)
    second = RUNNER.invoke(cli.app, ["demo", "seed"])
    assert second.exit_code == 0 and "本次导入 0 份" in second.output
    with PersonaStore(db) as store:
        assert store.get_meta("sources_changed_at") == before
        assert store.list_sources() == sources
        custom = parse_note("手工补充的资料", settings, "手动笔记")
        store.put_source(custom)
        store.set_identity(demo.DEMO_NAME, "手工简介", None)
    changed = directory / demo.DEMO_FILES[0]
    changed.write_text(changed.read_text() + "\n新增的虚构示例内容。\n")
    force = RUNNER.invoke(cli.app, ["demo", "seed", "--force"])
    assert force.exit_code == 0 and "本次导入 5 份" in force.output
    with PersonaStore(db) as store:
        assert len(store.list_sources()) == 6
        assert store.get_source(custom.source.source_id) is not None
        assert store.get_meta("identity:about") == "手工简介"
        assert sum(source.origin == demo.DEMO_FILES[0] for source in store.list_sources()) == 1
        assert any("新增的虚构示例内容" in e.text for e in store.list_expressions())
    assert len(json.loads(Path("data/personas.json").read_text())["personas"]) == 2
    with PersonaStore(settings.db_path) as store:
        assert store.list_sources() == default_sources


def test_demo_missing_files_fail_before_creating_data(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(demo, "DEMO_DIRECTORY", tmp_path / "missing")
    result = RUNNER.invoke(cli.app, ["demo", "seed"])
    assert result.exit_code == 1
    assert "完整 git 仓库" in result.output
    assert not Path("data").exists()


@pytest.mark.parametrize("options", [[], ["--demo"], ["--demo", "--no-open", "--port", "9001"]])
def test_local_up_dry_run_no_side_effects(tmp_path: Path, options: list[str]) -> None:
    env = {**os.environ, "REPO_ROOT": str(tmp_path)}
    result = subprocess.run(
        ["/bin/bash", str(ROOT / "scripts/local-up.sh"), "--dry-run", *options],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert list(tmp_path.iterdir()) == []
    assert "uv sync --frozen" in result.stdout
    assert "git pull && ./scripts/local-up.sh" in result.stdout
    assert ("demo seed" in result.stdout) == ("--demo" in options)
    command = result.stdout.splitlines()[-1]
    assert command.endswith("--port 9001" if "--no-open" in options else "--port 8765 --open")


def test_local_up_dry_run_preserves_existing_files(tmp_path: Path) -> None:
    private_env(tmp_path / ".env", "LOCAL_TEST_VALUE=unchanged\n")
    (tmp_path / ".env").chmod(0o644)
    (tmp_path / "twin.toml").write_text("unchanged")
    before = {p.name: (p.read_bytes(), p.stat().st_mode, p.stat().st_mtime_ns) for p in tmp_path.iterdir()}
    subprocess.run(
        ["/bin/bash", str(ROOT / "scripts/local-up.sh"), "--dry-run", "--demo"],
        env={**os.environ, "REPO_ROOT": str(tmp_path)},
        check=True,
        capture_output=True,
    )
    assert before == {p.name: (p.read_bytes(), p.stat().st_mode, p.stat().st_mtime_ns) for p in tmp_path.iterdir()}


@pytest.mark.parametrize(
    "options", [["--port"], ["--port", "0"], ["--port", "65536"], ["--port", "abc"], ["--unknown"]]
)
def test_local_up_dry_run_invalid_options(tmp_path: Path, options: list[str]) -> None:
    result = subprocess.run(
        ["/bin/bash", str(ROOT / "scripts/local-up.sh"), "--dry-run", *options],
        env={**os.environ, "REPO_ROOT": str(tmp_path)},
        capture_output=True,
    )
    assert result.returncode == 2
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "model,url,key", [(False, False, False), (True, False, True), (True, True, False), (True, True, True)]
)
def test_local_configuration_gate(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], model: bool, url: bool, key: bool
) -> None:
    config = '[llm]\napi_key_env = "LOCAL_TEST_KEY"\n'
    if model:
        config += 'model = "test-model"\n'
    if url:
        config += 'base_url = "http://127.0.0.1:8000/v1"\n'
    Path("twin.toml").write_text(config)
    private_env(Path(".env"), "LOCAL_TEST_KEY=\n")
    if key:
        monkeypatch.setenv("LOCAL_TEST_KEY", "test-only-sentinel")
    assert check_local_config() == (0 if model and url and key else 1)
    output = capsys.readouterr().out
    if not (model and url and key):
        assert ("--base-url URL --model NAME" in output) == (not (model and url))
        assert ("LOCAL_TEST_KEY=" in output) == (not key)
    assert "test-only-sentinel" not in output
    assert Path("data").exists() == (model and url and key)
    monkeypatch.delenv("LOCAL_TEST_KEY", raising=False)


def test_local_configuration_gate_reads_selected_env(monkeypatch: pytest.MonkeyPatch) -> None:
    Path("twin.toml").write_text(
        '[llm]\nmodel="test"\nbase_url="http://localhost:8000/v1"\napi_key_env="LOCAL_TEST_KEY"\n'
    )
    private_env(Path(".env"), "LOCAL_TEST_KEY=test-only\n")
    assert selected_env_file() == Path(".env")
    assert check_local_config() == 0
    monkeypatch.delenv("LOCAL_TEST_KEY")


def test_local_setup_prompts_and_saves(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    Path("twin.toml").write_text(cli.CONFIG_TEMPLATE.replace("TWIN_LLM_KEY", "LOCAL_TEST_KEY"))
    shutil.copy(ROOT / ".env.example", ".env")
    Path(".env").chmod(0o600)
    Path(".env").write_text(Path(".env").read_text().replace("TWIN_LLM_KEY", "LOCAL_TEST_KEY"))
    answers = iter(["not a url", "http://127.0.0.1:8000/v1", "", "test-model"])
    status = check_local_config(
        interactive=True, read=lambda _: next(answers), read_secret=lambda _: "test-only-sentinel"
    )
    assert status == 0
    output = capsys.readouterr().out
    assert "test-only-sentinel" not in output
    settings = load_settings(Path("twin.toml"))
    assert (settings.llm.model, settings.llm.base_url) == ("test-model", "http://127.0.0.1:8000/v1")
    assert 'LOCAL_TEST_KEY="test-only-sentinel"' in Path(".env").read_text().splitlines()
    assert stat.S_IMODE(Path(".env").stat().st_mode) == 0o600
    assert stat.S_IMODE(Path("data").stat().st_mode) == 0o700
    monkeypatch.delenv("LOCAL_TEST_KEY")
    assert check_local_config(interactive=False) == 0


def test_local_setup_cancel_writes_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    Path("twin.toml").write_text('[llm]\napi_key_env = "LOCAL_TEST_KEY"\n')

    def cancel(_: str) -> str:
        raise EOFError

    assert check_local_config(interactive=True, read=cancel, read_secret=cancel) == 1
    assert Path("twin.toml").read_text() == '[llm]\napi_key_env = "LOCAL_TEST_KEY"\n'
    assert not Path("data").exists()


def test_set_llm_value_only_touches_llm_section() -> None:
    text = (
        '[chat_llm]\nmodel = "chat"\n\n[llm]\nprovider = "openai_compat"\n# model = "x"\n\n'
        '[embed]\nprovider = "hashing"\n'
    )
    updated = set_llm_value(set_llm_value(text, "model", "m"), "base_url", "http://h/v1")
    assert updated.count('model = "chat"') == 1
    assert '[llm]\nbase_url = "http://h/v1"\nprovider = "openai_compat"\nmodel = "m"\n' in updated


def test_doctor_local_skips_services(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from twin.ops.doctor import inspect_installation

    class Backend:
        def execute(self, *args):  # type: ignore[no-untyped-def]
            pytest.fail("local doctor must not query the service manager")

        def runner(self, *args):  # type: ignore[no-untyped-def]
            pytest.fail("local doctor must not read power settings")

    settings = Settings(db_path=tmp_path / "data/twin.db")
    checks = inspect_installation(
        TwinPaths.from_env(),
        settings,
        Path("twin.toml"),
        Backend(),  # type: ignore[arg-type]
        local=True,
        connect=lambda *_: False,
    )
    names = {check.name for check in checks}
    assert not any(name.startswith("服务") for name in names)
    assert {"网页端口", "防睡眠"}.isdisjoint(names)


def test_shell_variables_before_cjk_are_braced() -> None:
    """Some locales read the bytes of `$port，` as part of the name, which `set -u` turns into a crash."""
    scripts = subprocess.run(["git", "ls-files", "*.sh"], cwd=ROOT, capture_output=True, text=True, check=True)
    pattern = re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*[^\x00-\x7F]")
    offenders = [
        f"{name}:{number}"
        for name in scripts.stdout.split()
        for number, line in enumerate((ROOT / name).read_text(encoding="utf-8").splitlines(), 1)
        if pattern.search(line)
    ]
    assert offenders == []


@pytest.mark.parametrize("state", ["handwritten", "managed-current", "managed-old", "missing", "fails"])
def test_ensure_asr(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], state: str) -> None:
    from twin.ops import compute

    config = '[llm]\nmodel = "m"\n'
    if state == "handwritten":
        config += '[asr]\nprovider = "command"\ncommand = "transcribe"\n'
    if state.startswith("managed"):
        config += f'{compute.BEGIN}\n[asr]\nprovider = "command"\ncommand = "transcribe"\n{compute.END}\n'
    Path("twin.toml").write_text(config)
    pack = compute.get_pack("asr-funasr")
    monkeypatch.setattr(compute, "installed_version", lambda _: "1.0.0" if state == "managed-old" else pack.version)
    calls = []

    def install(pack, path, *, download_models, progress):  # type: ignore[no-untyped-def]
        calls.append((pack.name, path, download_models))
        if state == "fails":
            raise ValueError("未找到 ffmpeg，请运行 brew install ffmpeg")

    monkeypatch.setattr(compute, "install", install)
    assert ensure_asr() == 0
    expected = state in {"managed-old", "missing", "fails"}
    assert calls == ([("asr-funasr", Path("twin.toml"), True)] if expected else [])
    output = capsys.readouterr().out
    assert ("文字聊天不受影响" in output) == (state == "fails")
    assert ("升级录音转写包 1.0.0" in output) == (state == "managed-old")


def test_local_up_dry_run_asr_opt_out(tmp_path: Path) -> None:
    def run(*options: str) -> str:
        return subprocess.run(
            ["/bin/bash", str(ROOT / "scripts/local-up.sh"), "--dry-run", *options],
            env={**os.environ, "REPO_ROOT": str(tmp_path)},
            capture_output=True,
            text=True,
            check=True,
        ).stdout

    assert "asr-funasr" in run()
    assert "asr-funasr" not in run("--no-asr")


def test_local_setup_from_flags(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    Path("twin.toml").write_text(cli.CONFIG_TEMPLATE.replace("TWIN_LLM_KEY", "LOCAL_TEST_KEY"))
    assert check_local_config(interactive=False, set_base_url="not-a-url", set_model="m") == 1
    assert not load_settings(Path("twin.toml")).llm.model
    assert check_local_config(interactive=False, set_base_url="http://127.0.0.1:8000/v1", set_model="m") == 1
    output = capsys.readouterr().out
    assert "--base-url URL" not in output and "LOCAL_TEST_KEY=" in output
    settings = load_settings(Path("twin.toml"))
    assert (settings.llm.model, settings.llm.base_url) == ("m", "http://127.0.0.1:8000/v1")
    monkeypatch.setenv("LOCAL_TEST_KEY", "none")
    assert check_local_config(interactive=False) == 0


def _git(cwd: Path, *args: str) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com"}
    env |= {"GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True).stdout


@pytest.mark.parametrize("case", ["behind", "dirty", "other-branch", "no-update"])
def test_local_up_updates_stable_and_restarts(tmp_path: Path, case: str) -> None:
    origin, work = tmp_path / "origin.git", tmp_path / "work"
    _git(tmp_path, "init", "-q", "--bare", str(origin))
    seed = tmp_path / "seed"
    (seed / "scripts").mkdir(parents=True)
    shutil.copy(ROOT / "scripts/local-up.sh", seed / "scripts/local-up.sh")
    (seed / "README").write_text("v1\n")
    _git(seed, "init", "-q", "-b", "stable")
    _git(seed, "add", ".")
    _git(seed, "commit", "-qm", "v1")
    _git(seed, "push", "-q", str(origin), "stable")
    _git(tmp_path, "clone", "-q", "-b", "stable", str(origin), str(work))
    # The release replaces the script with a stub, so a restart is visible in the output.
    (seed / "scripts/local-up.sh").write_text('#!/usr/bin/env bash\necho "NEW SCRIPT $TWIN_LOCAL_UP_UPDATED $*"\n')
    _git(seed, "commit", "-qam", "v2")
    _git(seed, "push", "-q", str(origin), "stable")
    if case == "dirty":
        (work / "README").write_text("local edit\n")
    if case == "other-branch":
        _git(work, "switch", "-qc", "dev")
    options = ["--no-update"] if case == "no-update" else []
    env = {k: v for k, v in os.environ.items() if k not in {"TWIN_LOCAL_UP_UPDATED", "REPO_ROOT"}}
    env["PATH"] = "/usr/bin:/bin"  # git but no uv: a script that is not replaced stops at the uv check
    result = subprocess.run(
        ["/bin/bash", str(work / "scripts/local-up.sh"), "--no-open", *options],
        env=env,
        capture_output=True,
        text=True,
    )
    if case == "behind":
        assert "稳定版：已更新 1 个提交" in result.stdout
        assert "NEW SCRIPT 1 --no-open" in result.stdout
    else:
        assert "NEW SCRIPT" not in result.stdout
        assert "缺少 uv" in result.stderr
        assert ("跳过自动更新" in result.stdout) == (case == "dirty")


def _init_config() -> str:
    """The twin.toml that ./scripts/local-up.sh generates on first run."""
    result = RUNNER.invoke(cli.app, ["--config", "twin.toml", "init", "twin.toml"])
    assert result.exit_code == 0, result.output
    return Path("twin.toml").read_text(encoding="utf-8")


@pytest.mark.parametrize("state", ["default", "default-fails", "managed", "managed-down", "handwritten"])
def test_ensure_embed(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], state: str) -> None:
    config = _init_config()
    if state.startswith("managed"):
        config = ollama.config_text(config) or ""
    if state == "handwritten":
        config = config.replace(
            'provider = "hashing"', 'provider = "openai_compat"\nmodel = "m"\nbase_url = "http://x/v1"'
        )
    Path("twin.toml").write_text(config, encoding="utf-8")
    calls = []

    def prepare(progress):  # type: ignore[no-untyped-def]
        calls.append(True)
        if state.endswith(("fails", "down")):
            raise ollama.OllamaError("未安装 Ollama")

    monkeypatch.setattr(ollama, "prepare", prepare)
    assert ensure_embed() == 0
    assert calls == ([] if state == "handwritten" else [True])
    embed = load_settings(Path("twin.toml")).embed
    enabled = state in {"default", "managed", "managed-down"}
    assert (embed.provider, embed.model if enabled else None) == (
        ("openai_compat", "bge-m3") if enabled else ("hashing" if state != "handwritten" else "openai_compat", None)
    )
    output = capsys.readouterr().out
    assert ("继续使用本机轻量后端 hashing" in output) == (state == "default-fails")
    assert ("聊天先只按关键词检索" in output) == (state == "managed-down")
    assert ("已启用 bge-m3" in output) == (state == "default")


def test_embed_config_replaces_only_the_default_table() -> None:
    template = _init_config()
    managed = ollama.config_text(template)
    table = re.search(r'\[embed\]\n(?:#.*\n)*provider = "hashing"\napi_key_env = "TWIN_EMBED_KEY"\n', template)
    assert table is not None
    # Only the table changes: the comments that follow it stay with what they introduce.
    assert managed == template.replace(table.group(), ollama.BLOCK)
    Path("twin.toml").write_text(managed, encoding="utf-8")
    embed = load_settings(Path("twin.toml")).embed
    assert (embed.provider, embed.model, embed.base_url, embed.egress) == (
        "openai_compat",
        "bge-m3",
        "http://127.0.0.1:11434/v1",
        "local",
    )
    assert ollama.config_text(managed) == managed
    assert ollama.config_text('[llm]\nmodel = "m"\n') == '[llm]\nmodel = "m"\n' + ollama.BLOCK
    assert ollama.config_text('[embed]\nprovider = "hashing"\nbatch_size = 8\n') is None


class FakeResponse:
    def __init__(self, events: list[dict[str, object]]) -> None:
        self.lines = [json.dumps(event).encode() + b"\n" for event in events]

    def __enter__(self) -> list[bytes]:
        return self.lines

    def __exit__(self, *args: object) -> None:
        return None


@pytest.mark.parametrize("outcome", ["success", "proxy", "cut"])
def test_ollama_pull_reports_progress_and_tells_a_refused_download_apart(
    monkeypatch: pytest.MonkeyPatch, outcome: str
) -> None:
    total = 1_200_000_000
    events: list[dict[str, object]] = [{"status": "pulling manifest"}]
    events += [{"status": "pulling", "total": total, "completed": total * k // 4} for k in range(5)]
    if outcome == "success":
        events.append({"status": "success"})
    if outcome == "proxy":
        refused = "redirect target not allowed: x.r2.cloudflarestorage.com resolves to non-public 198.18.3.1"
        events = [{"status": "pulling", "total": total, "completed": 0}, {"error": refused}]
    monkeypatch.setattr(ollama._OPENER, "open", lambda request, timeout: FakeResponse(events))
    lines: list[str] = []
    if outcome == "success":
        ollama.pull(lines.append)
        assert lines[1:] == ["  20%", "  50%", "  70%", "  100%"]
        return
    with pytest.raises(ollama.OllamaError) as raised:
        ollama.pull(lines.append)
    # A refusal before any byte arrives prints no progress line.
    assert (len(lines) == 1) == (outcome == "proxy")
    assert isinstance(raised.value, ollama.DownloadRefused) == (outcome == "proxy")
    assert ("下载中断" in str(raised.value)) == (outcome == "cut")


@pytest.mark.parametrize("intact", [True, False])
def test_refused_pull_fetches_the_registry_files_checks_and_imports_them(
    monkeypatch: pytest.MonkeyPatch, intact: bool
) -> None:
    import hashlib
    import io

    weights = b"gguf-weights" * 1000
    digest = "sha256:" + hashlib.sha256(weights if intact else b"other").hexdigest()
    manifest = {
        "layers": [
            {"mediaType": "application/vnd.ollama.image.model", "digest": digest, "size": len(weights)},
            {"mediaType": "application/vnd.ollama.image.license", "digest": "sha256:lic", "size": 3},
        ]
    }
    registry = {
        f"{ollama.REGISTRY}/manifests/latest": json.dumps(manifest).encode(),
        f"{ollama.REGISTRY}/blobs/{digest}": weights,
        f"{ollama.REGISTRY}/blobs/sha256:lic": b"MIT",
    }
    uploads: list[tuple[str, bytes]] = []
    created: list[dict[str, object]] = []

    def urlopen(request: object, timeout: float) -> io.BytesIO:
        url = request if isinstance(request, str) else request.full_url  # type: ignore[attr-defined]
        return io.BytesIO(registry[url])

    def upload(request, timeout):  # type: ignore[no-untyped-def]
        uploads.append((request.full_url, request.data.read()))
        return io.BytesIO(b"")

    def refused(progress):  # type: ignore[no-untyped-def]
        raise ollama.DownloadRefused("resolves to non-public 198.18.3.1")

    monkeypatch.setattr(ollama.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(ollama._OPENER, "open", upload)
    monkeypatch.setattr(ollama, "_call", lambda path, body, timeout: created.append(body) or {"status": "success"})
    monkeypatch.setattr(ollama, "start", lambda: None)
    monkeypatch.setattr(ollama, "has_model", lambda: False)
    monkeypatch.setattr(ollama, "pull", refused)
    probed: list[list[str]] = []
    monkeypatch.setattr(ollama, "make_embedder", lambda settings: type("E", (), {"embed": staticmethod(probed.append)}))
    if not intact:
        with pytest.raises(ollama.OllamaError, match="校验不通过"):
            ollama.prepare(lambda line: None)
        assert uploads == [] and created == [] and probed == []
        return
    ollama.prepare(lambda line: None)
    assert uploads == [(f"{ollama.OLLAMA}/api/blobs/{digest}", weights)]
    assert created == [{"model": "bge-m3", "files": {"model.gguf": digest}, "stream": False, "license": "MIT"}]
    assert probed == [["连通测试"]]


def test_local_up_dry_run_embed_opt_out(tmp_path: Path) -> None:
    def run(*options: str) -> str:
        return subprocess.run(
            ["/bin/bash", str(ROOT / "scripts/local-up.sh"), "--dry-run", *options],
            env={**os.environ, "REPO_ROOT": str(tmp_path)},
            capture_output=True,
            text=True,
            check=True,
        ).stdout

    assert "bge-m3" in run()
    assert "bge-m3" not in run("--no-embed")
