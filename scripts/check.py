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

The machine is shared by many checkouts: the heavy steps (tests, the frontend build, screenshots) each take one of
``TWIN_CHECK_SLOTS`` (default 2) slots shared by every checkout's check.py, waiting while all are taken, use at most
``TWIN_CHECK_WORKERS`` processes (default the cores divided among the slots), and run at a lower priority. The
frontend is built again only when its sources or the built files changed since the last build here.

Tests marked ``codec`` run the real ffmpeg / ffprobe. They do not run here (a test not marked so that runs either
fails, see tests/conftest.py) but on ``TWIN_CODEC_HOST`` (default y15; empty runs them here): all of them with
``--full``, else those testmon finds the changes affect, and not again once they passed there for the same code. The
checkout is copied there with rsync (what git does not ignore, without frontend/, data or keys); an unreachable host
only warns, except with ``--full``.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import os
import shlex
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager, nullcontext
from pathlib import Path
from typing import IO

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"
TESTMON_DATA = ".testmondata"
PACKAGE_DIR = "src/twin/"
STATIC_DIR = "src/twin/web/static/"
EVERYTHING = frozenset({"pyproject.toml", "uv.lock"})
PARALLEL_FROM = 200  # Selected tests from which pytest-xdist's worker startup pays off.
LINT_PATHS = ["src", "tests", "deploy", "scripts/check.py"]
# Shared by every checkout on this machine, so concurrent checks take turns at the heavy steps.
SLOTS_DIR = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "twin-check"
SLOTS = max(1, int(os.environ.get("TWIN_CHECK_SLOTS") or 2))
WORKERS = max(1, int(os.environ.get("TWIN_CHECK_WORKERS") or (os.cpu_count() or 4) // SLOTS))
# What the frontend was last built from here (``build_state``); in node_modules, so each checkout keeps its own.
BUILD_STAMP = ROOT / "frontend" / "node_modules" / ".cache" / "twin-build.stamp"
# Where the tests that run ffmpeg go: an SSH host with uv and ffmpeg, or "" for here.
CODEC_HOST = os.environ.get("TWIN_CODEC_HOST", "y15")
CODEC_WORKERS = 8
# The code the codec tests last passed for on CODEC_HOST (``codec_state``).
CODEC_STAMP = ROOT / ".pytest_cache" / "twin-codec.stamp"
# What is never copied to the codec host, whatever git ignores or not.
NOT_COPIED = [".git/", "frontend/", ".claude/", "data/", ".env*", "twin.toml", ".venv/", ".testmondata*"]
SSH = ["ssh", "-o", "BatchMode=yes", "-o", "ForwardX11=no", "-o", "ConnectTimeout=10"]


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


def testmon_selected(here: list[str]) -> int | None:
    """How many tests testmon would run now; None when it cannot tell (collection failed). Read-only: a collection
    that writes the record would mark the changes as seen, and the run after it would select nothing."""
    listed = subprocess.run(
        ["uv", "run", "pytest", "--testmon", "--testmon-nocollect", "--collect-only", "-q", *here],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if listed.returncode not in (0, 5):  # 5: no tests collected.
        return None
    return sum(1 for line in listed.stdout.splitlines() if "::" in line)


def codec_selected() -> list[str] | None:
    """The tests marked ``codec`` that testmon finds the changes affect (read-only, as ``testmon_selected``)."""
    listed = subprocess.run(
        ["uv", "run", "pytest", "--testmon", "--testmon-nocollect", "--collect-only", "-q", "-m", "codec"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if listed.returncode not in (0, 5):
        return None
    return [line for line in listed.stdout.splitlines() if "::" in line]


def codec_state(tests: list[str]) -> str:
    """A fingerprint of the tests asked for and of the Python code and dependencies they run."""
    digest = hashlib.sha256("\n".join(tests).encode())
    for path in sorted(git("ls-files", "--cached", "--others", "--exclude-standard", "src", "tests").splitlines()):
        file = ROOT / path
        if file.is_file() and not path.startswith(STATIC_DIR):
            digest.update(path.encode() + b"\0" + file.read_bytes() + b"\0")
    for name in sorted(EVERYTHING):
        digest.update((ROOT / name).read_bytes())
    return digest.hexdigest()


def codec_remote(tests: list[str], required: bool) -> Callable[[], int]:
    """Copy the checkout to CODEC_HOST and run ``tests`` there (every ``codec`` test when empty). Exit code 0 when
    the host cannot be reached and the run is not ``required``, after saying so."""
    # One folder per checkout (its name and where it is), the environment beside it so it outlives each copy.
    place = f"twin-codec-check/{ROOT.name}-{hashlib.sha256(str(ROOT).encode()).hexdigest()[:8]}"
    selection = [*tests] if tests else ["-m", "codec"]

    def go() -> int:
        if subprocess.run([*SSH, CODEC_HOST, "mkdir", "-p", place], cwd=ROOT).returncode != 0:
            print(f"连不上 {CODEC_HOST}：编解码测试没有跑" + ("。" if required else "（提交前的 --full 和 CI 会跑）。"))
            return 1 if required else 0
        copied = subprocess.run(
            [
                "rsync",
                "-az",
                "--delete",
                "--delete-excluded",
                *(f"--exclude={pattern}" for pattern in NOT_COPIED),
                "--filter=:- .gitignore",
                "-e",
                shlex.join(SSH),
                "./",
                f"{CODEC_HOST}:{place}/",
            ],
            cwd=ROOT,
        )
        if copied.returncode != 0:
            return copied.returncode
        script = (
            f"cd {place} && export UV_PROJECT_ENVIRONMENT=$HOME/{place}.venv && uv sync --frozen --quiet && "
            f"uv run --frozen pytest -q -p no:testmon -n {CODEC_WORKERS} {shlex.join(selection)}"
        )
        code = subprocess.run([*SSH, CODEC_HOST, script], cwd=ROOT).returncode
        if code == 0 and tests:
            CODEC_STAMP.parent.mkdir(parents=True, exist_ok=True)
            CODEC_STAMP.write_text(codec_state(tests))
        return code

    return go


def build_state() -> str:
    """A fingerprint of what the frontend build reads (every frontend file but tests and screenshots) and of the built
    files now there, so a build replaced by a checkout or another build is made again."""
    digest = hashlib.sha256()
    for path in sorted(git("ls-files", "--cached", "--others", "--exclude-standard", "frontend").splitlines()):
        file = ROOT / path
        if path.startswith(("frontend/e2e/", "frontend/src/test/")) or ".test." in path or not file.is_file():
            continue
        digest.update(path.encode() + b"\0" + file.read_bytes() + b"\0")
    static = ROOT / STATIC_DIR
    for file in sorted(static.rglob("*")) if static.is_dir() else ():
        if file.is_file():
            digest.update(file.relative_to(static).as_posix().encode() + b"\0")
    index = static / "index.html"
    digest.update(index.read_bytes() if index.is_file() else b"")
    return digest.hexdigest()


def built_already() -> bool:
    return BUILD_STAMP.is_file() and BUILD_STAMP.read_text() == build_state()


def take(file: IO[str]) -> bool:
    try:
        fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    return True


@contextmanager
def slot() -> Iterator[None]:
    """Hold one of the machine's ``SLOTS`` for a heavy step, waiting while every one is held. The lock goes with the
    process, so a check that is stopped never keeps one."""
    SLOTS_DIR.mkdir(parents=True, exist_ok=True)
    files = [(SLOTS_DIR / f"slot-{n}.lock").open("a") for n in range(SLOTS)]
    told = False
    try:
        while not any(take(file) for file in files):
            if not told:
                print(f"本机已有 {SLOTS} 个检查在跑测试或构建，排队等待……", flush=True)
                told = True
            time.sleep(2)
        yield
    finally:
        for file in files:
            file.close()


Command = list[str] | Callable[[], int]


def run(title: str, command: Command, heavy: bool = False) -> bool:
    print(f"\n▶ {title}" + (f"：{' '.join(command)}" if isinstance(command, list) else ""), flush=True)
    with slot() if heavy else nullcontext():
        started = time.monotonic()
        if isinstance(command, list):
            # Lower priority: the editor, the browser and other sessions stay responsive while it runs.
            code = subprocess.run(command, cwd=ROOT, preexec_fn=lambda: os.nice(10)).returncode
        else:
            code = command()
    # 5: pytest found nothing to run (testmon selected nothing, or no codec test was asked for).
    ok = code == 0 or (code == 5 and isinstance(command, list) and command[2] == "pytest")
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
    workers = ["-n", str(WORKERS)]
    # The tests that run ffmpeg go to CODEC_HOST, if there is one; any other test that runs it fails here.
    here = ["-m", "not codec"] if CODEC_HOST else []
    if CODEC_HOST:
        os.environ["TWIN_NO_CODEC"] = "1"
    # (title, command, whether it is heavy: takes a slot of the machine's).
    steps: list[tuple[str, Command, bool]] = [
        ("ruff", ["uv", "run", "ruff", "check", *LINT_PATHS], False),
        ("格式", ["uv", "run", "ruff", "format", "--check", *LINT_PATHS], False),
        ("mypy", ["uv", "run", "mypy"], False),
    ]
    if args.full:
        steps.append(("pytest", ["uv", "run", "pytest", "-q", *workers, *here], True))
        if CODEC_HOST:
            steps.append((f"编解码测试（{CODEC_HOST}）", codec_remote([], required=True), False))
    else:
        print(f"自 {base} 以来改动 {len(changed)} 个文件。")
        if not args.dry_run:
            seed_testmon_data()
        if reason := everything_reason(changed):
            # Run and record every test, so the next quick check starts from a full record.
            print(f"跑全部测试（{reason}）。")
            steps.append(("pytest", ["uv", "run", "pytest", "-q", *workers, *here, "--testmon-noselect"], True))
            if CODEC_HOST:
                steps.append((f"编解码测试（{CODEC_HOST}）", codec_remote([], required=False), False))
        else:
            count = None if args.dry_run else testmon_selected(here)
            print("testmon 按代码改动挑选测试" + ("。" if count is None else f"：{count} 个。"))
            parallel = [] if count is not None and count < PARALLEL_FROM else workers
            steps.append(("pytest", ["uv", "run", "pytest", "-q", *parallel, *here, "--testmon"], bool(parallel)))
            if CODEC_HOST and not args.dry_run:
                codec = codec_selected()
                if codec is None:
                    print("挑不出受影响的编解码测试：全部交给 " + CODEC_HOST + "。")
                    steps.append((f"编解码测试（{CODEC_HOST}）", codec_remote([], required=False), False))
                elif not codec:
                    print("改动不影响编解码测试。")
                elif CODEC_STAMP.is_file() and CODEC_STAMP.read_text() == codec_state(codec):
                    print(f"受影响的 {len(codec)} 个编解码测试上次已在 {CODEC_HOST} 通过，代码没变，跳过。")
                else:
                    print(f"受影响的 {len(codec)} 个编解码测试交给 {CODEC_HOST}。")
                    steps.append((f"编解码测试（{CODEC_HOST}）", codec_remote(codec, required=False), False))
            if named := named_tests(changed):
                print(f"另跑 {len(named)} 个提到改动文件的测试：")
                for test, name in named.items():
                    print(f"  {test}：提到 {name}")
                steps.append(
                    ("pytest（按文件名）", ["uv", "run", "pytest", "-q", *here, "--testmon-noselect", *named], False)
                )
    frontend = args.full or any(path.startswith("frontend/") for path in changed)
    if frontend:
        changed_only = [] if args.full else ["--changed", merge_base]
        steps += [
            ("前端类型", ["pnpm", "-C", "frontend", "typecheck"], False),
            ("前端 lint", ["pnpm", "-C", "frontend", "lint"], False),
            ("前端测试", ["pnpm", "-C", "frontend", "test", *changed_only, f"--maxWorkers={WORKERS}"], True),
        ]
        if built_already():
            print("前端源码和构建产物自上次构建后没变，跳过构建。")
        else:
            steps.append(("前端构建", ["pnpm", "-C", "frontend", "build"], True))
        if args.full:
            # Compares the build just made; about a minute, so only before committing.
            steps.append(
                (
                    "截图对比",
                    ["env", "TWIN_SCREENSHOTS_NO_BUILD=1", "./scripts/screenshots.sh", f"--workers={WORKERS}"],
                    True,
                )
            )
        else:
            print("改了前端：截图对比只在 --full 时运行（./scripts/screenshots.sh）。")
    if args.dry_run:
        print(f"测试和构建最多 {WORKERS} 个进程，本机同时最多 {SLOTS} 个检查在跑这些步骤。")
        if CODEC_HOST:
            print(f"编解码测试（codec）不在本机跑，交给 {CODEC_HOST}。")
        for title, command, _ in steps:
            print(f"会跑 {title}" + (f"：{' '.join(command)}" if isinstance(command, list) else ""))
        return 0

    failed = []
    for title, command, heavy in steps:
        if not run(title, command, heavy):
            failed.append(title)
        elif title == "前端构建":
            BUILD_STAMP.parent.mkdir(parents=True, exist_ok=True)
            BUILD_STAMP.write_text(build_state())
    if frontend and not failed and git("status", "--porcelain", STATIC_DIR):
        print(f"\n前端构建产物有变化，请一起提交 {STATIC_DIR}。")
    if failed:
        print(f"\n✗ 未通过：{'、'.join(failed)}")
        return 1
    print("\n✓ 全部通过" + ("" if args.full else "；提交前再跑一次 --full。"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
