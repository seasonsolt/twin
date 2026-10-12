from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from twin import cli
from twin.config import Settings, load_settings
from twin.ops import demo
from twin.ops.envfile import load_env_file, selected_env_file
from twin.ops.local import check_local_config, set_llm_value
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
        assert "model" in output and "base_url" in output and "LOCAL_TEST_KEY" in output
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
