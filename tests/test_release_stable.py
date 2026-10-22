"""The cnb release button's script: only a passed main commit that stable fast-forwards to reaches stable."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def rel() -> ModuleType:
    spec = importlib.util.spec_from_file_location("release_stable", ROOT / "deploy/release_stable.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def commit(work: Path, message: str, prompt: str = "persona-v7", taxonomy: str = "v2") -> str:
    kernel = work / "src/twin/persona/kernel.py"
    kernel.parent.mkdir(parents=True, exist_ok=True)
    kernel.write_text(f'PROMPT_VERSION = "{prompt}"\nTAXONOMY_VERSION = "{taxonomy}"\n# {message}\n')
    git(work, "add", "-A")
    git(work, "commit", "-q", "-m", message)
    return git(work, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """An origin with main and stable, and a shallow clone of main like the one the cnb job runs in."""
    origin, work = tmp_path / "origin.git", tmp_path / "work"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    git(tmp_path, "init", "-q", "-b", "main", str(work))
    git(work, "config", "user.email", "t@example.com")
    git(work, "config", "user.name", "t")
    commit(work, "first")
    git(work, "push", "-q", str(origin), "main", "main:stable")
    clone = tmp_path / "clone"
    git(tmp_path, "clone", "-q", "--depth", "1", f"file://{origin}", str(clone))
    monkeypatch.chdir(clone)
    return origin, work


def passed(sha: str) -> list[dict[str, Any]]:
    return [{"createTime": "2026-10-22T01:00:00Z", "status": "success", "buildLogUrl": f"https://cnb/{sha[:8]}"}]


def test_releases_the_tip_of_main_and_says_whether_the_kernel_changed(
    rel: ModuleType, repo: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    origin, work = repo
    commit(work, "second")
    tip = commit(work, "third", prompt="persona-v8")
    git(work, "push", "-q", str(origin), "main")
    asked: list[str] = []
    rel.release(f"file://{origin}", "", lambda sha: asked.append(sha) or passed(sha))
    assert asked == [tip] and git(origin, "rev-parse", "stable") == tip
    out = capsys.readouterr().out
    assert "将发布 2 个提交" in out and "second" in out and "third" in out
    assert 'PROMPT_VERSION = "persona-v7"' in out and 'PROMPT_VERSION = "persona-v8"' in out
    rel.release(f"file://{origin}", "", passed)
    assert "无需发布" in capsys.readouterr().out


def test_releases_an_earlier_main_commit_without_a_kernel_change(
    rel: ModuleType, repo: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    origin, work = repo
    chosen = commit(work, "second")
    commit(work, "third")
    git(work, "push", "-q", str(origin), "main")
    rel.release(f"file://{origin}", chosen[:8], passed)
    assert git(origin, "rev-parse", "stable") == chosen
    assert "记忆内核版本不变" in capsys.readouterr().out


@pytest.mark.parametrize(
    "builds, reason",
    [
        ([], "没有 push 构建记录"),
        ([{"createTime": "2026-10-22T01:00:00Z", "status": "error"}], "error"),
        ([{"createTime": "2026-10-22T01:00:00Z", "status": "pending"}], "pending"),
        (
            [
                {"createTime": "2026-10-22T01:00:00Z", "status": "success"},
                {"createTime": "2026-10-22T02:00:00Z", "status": "error"},
            ],
            "error",
        ),
    ],
)
def test_refuses_a_commit_whose_main_checks_did_not_pass(
    rel: ModuleType, repo: tuple[Path, Path], builds: list[dict[str, Any]], reason: str
) -> None:
    origin, work = repo
    before = git(origin, "rev-parse", "stable")
    commit(work, "second")
    git(work, "push", "-q", str(origin), "main")
    with pytest.raises(rel.ReleaseError, match=reason):
        rel.release(f"file://{origin}", "", lambda sha: builds)
    assert git(origin, "rev-parse", "stable") == before


def test_refuses_what_stable_cannot_fast_forward_to(rel: ModuleType, repo: tuple[Path, Path]) -> None:
    origin, work = repo
    first = git(work, "rev-parse", "HEAD")
    git(work, "switch", "-q", "-c", "elsewhere")
    side = commit(work, "not on main")
    git(work, "push", "-q", str(origin), "elsewhere")
    with pytest.raises(rel.ReleaseError, match="都没有提交"):
        rel.release(f"file://{origin}", side, passed)
    with pytest.raises(rel.ReleaseError, match="都没有提交"):
        rel.release(f"file://{origin}", "no-such-commit", passed)
    git(work, "push", "-q", "-f", str(origin), "elsewhere:stable")
    with pytest.raises(rel.ReleaseError, match="不在 main 上"):
        rel.release(f"file://{origin}", side, passed)
    git(work, "switch", "-q", "main")
    commit(work, "second")
    git(work, "push", "-q", str(origin), "main")
    with pytest.raises(rel.ReleaseError, match="无法快进"):
        rel.release(f"file://{origin}", "", passed)
    assert git(origin, "rev-parse", "stable") == side != first


def test_refuses_an_ablation_kernel(rel: ModuleType, repo: tuple[Path, Path]) -> None:
    origin, work = repo
    commit(work, "ablation", prompt="persona-v6-abl-t3", taxonomy="abl-t3")
    git(work, "push", "-q", str(origin), "main")
    with pytest.raises(rel.ReleaseError, match="消融"):
        rel.release(f"file://{origin}", "", passed)


def test_button_and_pipeline_agree() -> None:
    button = (ROOT / ".cnb/web_trigger.yml").read_text()
    cnb = (ROOT / ".cnb.yml").read_text()
    assert "event: web_trigger_release" in button and "RELEASE_COMMIT:" in button and "reg: ^main$" in button
    main = cnb[: cnb.index("\nstable:")]
    assert "  web_trigger_release:" in main and "python3 deploy/release_stable.py" in main


def test_failures_never_print_the_token(rel: ModuleType, repo: tuple[Path, Path]) -> None:
    with pytest.raises(rel.ReleaseError) as error:
        rel.release("https://cnb:s3cret-token@127.0.0.1:9/x.git", "", passed)
    assert "s3cret-token" not in str(error.value) and "git fetch 失败" in str(error.value)
    with pytest.raises(rel.ReleaseError, match="查不到"):
        rel.cnb_builds("http://127.0.0.1:9", "group/repo", "s3cret-token")("a" * 40)
