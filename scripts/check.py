"""Run with: uv run python scripts/check.py [--full] [--base REF] [--dry-run].

Quick check while iterating: ruff and mypy as usual, but only the tests the changes can affect, and the frontend
checks only when ``frontend/`` changed since ``--base`` (default origin/main, else main; uncommitted and untracked
files included). ``--full`` runs every check CI runs, including the screenshot comparison of the key pages
(scripts/screenshots.sh, in Docker); run it once before committing or releasing.

Python tests are chosen by pytest-testmon, which records the code each test executes in ``.testmondata`` and reruns
a test when that code changes; the first run in a checkout records every test and takes longer. A new worktree
starts from a copy of the main checkout's record when there is one. testmon cannot see code run in a subprocess or
files read as data, so tests that name a changed script, config or data file (``deploy/``, ``scripts/``, ...) run
too; a changed package data file or pyproject.toml / uv.lock reruns every test.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"
TESTMON_DATA = ".testmondata"
PACKAGE_DIR = "src/twin/"
STATIC_DIR = "src/twin/web/static/"
EVERYTHING = frozenset({"pyproject.toml", "uv.lock"})
PARALLEL_FROM = 200  # Selected tests from which pytest-xdist's worker startup pays off.
LINT_PATHS = ["src", "tests", "deploy", "scripts/check.py"]


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True).stdout


def default_base() -> str:
    for ref in ("origin/main", "main"):
        found = subprocess.run(["git", "rev-parse", "--verify", "--quiet", ref], cwd=ROOT, capture_output=True)
        if found.returncode == 0:
            return ref
    raise SystemExit("找不到 origin/main 或 main，请用 --base 指定比较的提交")


def changed_files(merge_base: str) -> list[str]:
    """Paths changed since ``merge_base``: commits, staged, unstaged and untracked files."""
    tracked = git("diff", "--name-only", merge_base).splitlines()
    untracked = git("ls-files", "--others", "--exclude-standard").splitlines()
    return sorted(set(tracked) | set(untracked))


def mention(path: str) -> str | None:
    """The text a test would contain if it runs or reads ``path`` outside testmon's view; None for files testmon
    tracks (package and test modules) or no test reads (frontend sources, Markdown)."""
    if path.startswith(("frontend/", "tests/")) or path.endswith(".md"):
        return None
    if path.endswith(".py"):
        # Package modules are tracked; other Python (deploy/compute packs) may run in a subprocess.
        return None if path.startswith(PACKAGE_DIR) else "/".join(Path(path).parts[-2:])
    return Path(path).name


def named_tests(changed: list[str]) -> dict[str, str]:
    """Test files that name a changed file testmon cannot track, with the name each one mentions."""
    names = sorted({name for path in changed if (name := mention(path))})
    found: dict[str, str] = {}
    for test in sorted(TESTS.rglob("test_*.py")):
        text = test.read_text(encoding="utf-8")
        if hit := next((name for name in names if name in text), None):
            found[test.relative_to(ROOT).as_posix()] = hit
    return found


def everything_reason(changed: list[str]) -> str | None:
    if hit := sorted(EVERYTHING.intersection(changed)):
        return f"{', '.join(hit)} 变了"
    data = [p for p in changed if p.startswith(PACKAGE_DIR) and not p.startswith(STATIC_DIR) and not p.endswith(".py")]
    return f"包内数据文件 {data[0]} 变了" if data else None


def seed_testmon_data() -> None:
    """Start a new worktree from the main checkout's record: testmon rechecks every fingerprint, so a stale copy only
    reruns more tests."""
    own = ROOT / TESTMON_DATA
    main_checkout = Path(git("rev-parse", "--path-format=absolute", "--git-common-dir").strip()).parent
    source = main_checkout / TESTMON_DATA
    if not own.exists() and main_checkout != ROOT and source.exists():
        shutil.copyfile(source, own)
        print(f"从主仓库复制了测试覆盖记录（{source}）。")


def testmon_selected() -> int | None:
    """How many tests testmon would run now; None when it cannot tell (collection failed). Read-only: a collection
    that writes the record would mark the changes as seen, and the run after it would select nothing."""
    listed = subprocess.run(
        ["uv", "run", "pytest", "--testmon", "--testmon-nocollect", "--collect-only", "-q"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if listed.returncode not in (0, 5):  # 5: no tests collected.
        return None
    return sum(1 for line in listed.stdout.splitlines() if "::" in line)


def run(title: str, command: list[str]) -> bool:
    print(f"\n▶ {title}：{' '.join(command)}", flush=True)
    started = time.monotonic()
    code = subprocess.run(command, cwd=ROOT).returncode
    ok = code == 0 or (code == 5 and command[2] == "pytest")  # 5: testmon found nothing to rerun.
    print(f"{'✓' if ok else '✗'} {title}（{time.monotonic() - started:.1f} 秒）", flush=True)
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description="按改动只跑受影响的检查；--full 跑全部（与 CI 一致）。")
    parser.add_argument("--full", action="store_true", help="跑全部检查，提交或发布前用")
    parser.add_argument("--base", help="与哪个提交比较改动，默认 origin/main，没有时用 main")
    parser.add_argument("--dry-run", action="store_true", help="只列出会跑哪些检查")
    args = parser.parse_args()

    base = args.base or default_base()
    merge_base = git("merge-base", base, "HEAD").strip()
    changed = changed_files(merge_base)
    steps: list[tuple[str, list[str]]] = [
        ("ruff", ["uv", "run", "ruff", "check", *LINT_PATHS]),
        ("格式", ["uv", "run", "ruff", "format", "--check", *LINT_PATHS]),
        ("mypy", ["uv", "run", "mypy"]),
    ]
    if args.full:
        steps.append(("pytest", ["uv", "run", "pytest", "-q", "-n", "auto"]))
    else:
        print(f"自 {base} 以来改动 {len(changed)} 个文件。")
        if not args.dry_run:
            seed_testmon_data()
        if reason := everything_reason(changed):
            # Run and record every test, so the next quick check starts from a full record.
            print(f"跑全部测试（{reason}）。")
            steps.append(("pytest", ["uv", "run", "pytest", "-q", "-n", "auto", "--testmon-noselect"]))
        else:
            count = None if args.dry_run else testmon_selected()
            print("testmon 按代码改动挑选测试" + ("。" if count is None else f"：{count} 个。"))
            parallel = [] if count is not None and count < PARALLEL_FROM else ["-n", "auto"]
            steps.append(("pytest", ["uv", "run", "pytest", "-q", *parallel, "--testmon"]))
            if named := named_tests(changed):
                print(f"另跑 {len(named)} 个提到改动文件的测试：")
                for test, name in named.items():
                    print(f"  {test}：提到 {name}")
                steps.append(("pytest（按文件名）", ["uv", "run", "pytest", "-q", "--testmon-noselect", *named]))
    frontend = args.full or any(path.startswith("frontend/") for path in changed)
    if frontend:
        steps += [
            ("前端类型", ["pnpm", "-C", "frontend", "typecheck"]),
            ("前端 lint", ["pnpm", "-C", "frontend", "lint"]),
            ("前端测试", ["pnpm", "-C", "frontend", "test", *([] if args.full else ["--changed", merge_base])]),
            ("前端构建", ["pnpm", "-C", "frontend", "build"]),
        ]
        if args.full:
            # Compares the build just made; about a minute, so only before committing.
            steps.append(("截图对比", ["env", "TWIN_SCREENSHOTS_NO_BUILD=1", "./scripts/screenshots.sh"]))
        else:
            print("改了前端：截图对比只在 --full 时运行（./scripts/screenshots.sh）。")
    if args.dry_run:
        for title, command in steps:
            print(f"会跑 {title}：{' '.join(command)}")
        return 0

    failed = [title for title, command in steps if not run(title, command)]
    if frontend and not failed and git("status", "--porcelain", STATIC_DIR):
        print(f"\n前端构建产物有变化，请一起提交 {STATIC_DIR}。")
    if failed:
        print(f"\n✗ 未通过：{'、'.join(failed)}")
        return 1
    print("\n✓ 全部通过" + ("" if args.full else "；提交前再跑一次 --full。"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
