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
            if not line.startswith(("# vrm_path = ", "# image_path = ", "# reasoning_effort = "))
        )
        == cli.CONFIG_TEMPLATE
    )
    assert load_settings(written) == Settings(db_path=tmp_path / "data" / "twin.db")
    for marker in ("api_key_env", "TWIN_LLM_KEY", "openai_compat", "hashing", '# reasoning_effort_extract = "low"'):
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
    for name in (
        "init",
        "ui",
        "persona",
        "media",
        "eval",
        "eval-compare",
        "eval-longmemeval",
        "eval-personamem",
        "eval-twin2k500",
    ):
        assert name in result.output
    assert set(
        cli.app.registered_commands[i].name or cli.app.registered_commands[i].callback.__name__
        for i in range(len(cli.app.registered_commands))
    ) == {"init", "ui", "api", "mcp", "eval", "eval-compare", "eval-longmemeval", "eval-personamem", "eval-twin2k500"}


@pytest.mark.parametrize("benchmark", ["longmemeval", "personamem", "twin2k500"])
def test_benchmarks_use_main_llm_without_production_chat(
    benchmark: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import importlib

    from twin.config import LLMSettings

    module = importlib.import_module(f"twin.evals.{benchmark}")
    settings = Settings(
        llm=LLMSettings(model="gpt-5.6-sol", base_url="https://xjjk.example/v1", api_key_env="TWIN_LLM_KEY"),
        chat_llm=LLMSettings(model="deepseek-flash", api_key_env="TWIN_LLM_KEY_DEEPSEEK"),
        judges=[LLMSettings(model="production-judge")],
    )
    monkeypatch.setattr(cli, "load_settings", lambda _: settings)
    monkeypatch.setattr(module, "load_dataset", lambda *args: (object(),))
    monkeypatch.setattr(module, "select_cases", lambda cases, **kwargs: cases)
    observed = []

    def run(cases, out, evaluation_settings, **kwargs):  # type: ignore[no-untyped-def]
        observed.append(evaluation_settings)
        assert kwargs["system"] == "twin"
        assert kwargs["score"] is True
        return {
            "system": "twin",
            "selected": 1,
            "completed": 1,
            "prediction_failures": 0,
            "judge_failures": 0,
            "missing": 0,
        }

    monkeypatch.setattr(module, "run_evaluation", run)
    source = tmp_path / "source.json"
    source.write_text("[]", encoding="utf-8")
    inputs = (
        ["--questions", str(source), "--contexts", str(source)]
        if benchmark == "personamem"
        else ["--dataset", str(source)]
    )
    args = [f"eval-{benchmark}", *inputs, "--out", str(tmp_path / "output")]
    if benchmark == "longmemeval":
        args.append("--score")
    result = invoke(None, *args)
    assert result.exit_code == 0, result.output
    assert len(observed) == 1
    assert observed[0].effective_chat_llm == settings.llm
    assert observed[0].judges == []
    assert settings.chat_llm is not None and settings.chat_llm.model == "deepseek-flash"
    assert settings.judges[0].model == "production-judge"


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
