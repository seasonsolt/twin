from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import Result
from typer.testing import CliRunner

from twin import cli
from twin.config import Settings, load_settings

ROOT = Path(__file__).resolve().parents[1]

runner = CliRunner()


def test_init_writes_template_identical_to_example_with_code_defaults(tmp_path: Path) -> None:
    result = ok(None, "init")

    written = tmp_path / "twin.toml"
    assert "已生成配置文件 twin.toml" in result.stdout
    assert written.read_text(encoding="utf-8") == cli.CONFIG_TEMPLATE
    example = (ROOT / "twin.toml.example").read_text(encoding="utf-8")
    assert (
        "".join(
            line
            for line in example.splitlines(keepends=True)
            if not line.startswith(("# vrm_path = ", "# reasoning_effort = "))
        )
        == cli.CONFIG_TEMPLATE
    )
    assert load_settings(written) == Settings(db_path=tmp_path / "data" / "twin.db")
    for marker in ("api_key_env", "TWIN_LLM_KEY", "openai_compat", "hashing"):
        assert marker in cli.CONFIG_TEMPLATE


def test_init_refuses_to_overwrite_without_force(tmp_path: Path) -> None:
    target = tmp_path / "conf" / "mine.toml"
    ok(None, "init", str(target))
    target.write_text("# edited\n", encoding="utf-8")

    result = invoke(None, "init", str(target))
    assert result.exit_code == 1 and "已存在" in result.stderr and "--force" in result.stderr
    assert target.read_text(encoding="utf-8") == "# edited\n"

    ok(None, "init", str(target), "--force")
    assert target.read_text(encoding="utf-8") == cli.CONFIG_TEMPLATE


def test_init_uses_config_option_as_target(tmp_path: Path) -> None:
    target = tmp_path / "other.toml"
    ok(target, "init")
    assert target.read_text(encoding="utf-8") == cli.CONFIG_TEMPLATE


def test_remaining_commands() -> None:
    result = runner.invoke(cli.app, ["--help"])
    assert result.exit_code == 0
    for name in ("init", "ui", "persona", "media", "eval", "eval-compare"):
        assert name in result.output
    assert set(
        cli.app.registered_commands[i].name or cli.app.registered_commands[i].callback.__name__
        for i in range(len(cli.app.registered_commands))
    ) == {"init", "ui", "api", "mcp", "eval", "eval-compare"}


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("TWIN_CONFIG", raising=False)
    monkeypatch.chdir(tmp_path)


def invoke(config: Path | None, *args: str) -> Result:
    argv = ["--config", str(config)] if config is not None else []
    return CliRunner().invoke(cli.app, [*argv, *args])


def ok(config: Path | None, *args: str) -> Result:
    result = invoke(config, *args)
    assert result.exit_code == 0, (result.stdout, result.stderr, result.exception)
    return result
