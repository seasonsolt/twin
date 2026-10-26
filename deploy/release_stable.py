#!/usr/bin/env python3
"""Fast-forward `stable` to a `main` commit whose cnb checks passed; the `stable` push then deploys to daw.

Runs from the "发布到 stable" button on the `main` branch page in cnb (.cnb/web_trigger.yml → `web_trigger_release`
in .cnb.yml). The button is the human gate: colleagues' local installs follow `stable`, and a memory kernel change
makes every twin re-process its memories, which costs model calls, so this prints what is being released first.
Standard library only, so the job needs no dependency install.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

KERNEL = "src/twin/persona/kernel.py"
MAIN = "refs/release/main"
STABLE = "refs/release/stable"

FetchBuilds = Callable[[str], list[dict[str, Any]]]


class ReleaseError(Exception):
    pass


def git(*args: str) -> str:
    # The empty http.extraHeader drops any header the runner set up for its read-only checkout token, so only the
    # credentials in the remote URL are sent; they are masked if git echoes the URL back.
    result = subprocess.run(["git", "-c", "http.extraHeader=", *args], capture_output=True, text=True)
    if result.returncode != 0:
        raise ReleaseError(f"git {args[0]} 失败：{re.sub(r'//[^/@\s]+@', '//***@', result.stderr.strip())}")
    return result.stdout.strip()


def kernel_versions(commit: str) -> str:
    source = git("show", f"{commit}:{KERNEL}")
    return " ".join(re.findall(r'^(?:PROMPT|TAXONOMY)_VERSION = "[^"]*"', source, flags=re.M))


def main_check(builds: list[dict[str, Any]], commit: str) -> str:
    """The newest `main` push build of the commit decides; a rebuild that passed counts."""
    if not builds:
        raise ReleaseError(f"{commit[:8]} 在 main 上没有 push 构建记录：只能发布 main 上检查过的提交。")
    newest = max(builds, key=lambda build: str(build.get("createTime", "")))
    status = newest.get("status")
    if status != "success":
        raise ReleaseError(f"{commit[:8]} 的 main 检查是 {status}，没有通过：{newest.get('buildLogUrl', '')}")
    return str(newest.get("buildLogUrl", ""))


def release(remote: str, requested: str, fetch_builds: FetchBuilds) -> None:
    if git("rev-parse", "--is-shallow-repository") == "true":
        git("fetch", "--quiet", "--unshallow", remote)
    git("fetch", "--quiet", "--no-tags", remote, f"+refs/heads/main:{MAIN}", f"+refs/heads/stable:{STABLE}")
    try:
        target = git("rev-parse", "--verify", "--quiet", f"{requested or MAIN}^{{commit}}")
    except ReleaseError:
        raise ReleaseError(f"main 和 stable 上都没有提交 {requested}：只能发布 main 的提交。") from None
    if not is_ancestor(target, MAIN):
        raise ReleaseError(f"{target[:8]} 不在 main 上：只能发布 main 的提交。")
    stable = git("rev-parse", STABLE)
    if target == stable:
        print(f"stable 已是 {target[:8]}，无需发布。")
        return
    if not is_ancestor(stable, target):
        raise ReleaseError(f"stable（{stable[:8]}）不在 {target[:8]} 的历史上，无法快进发布；请检查 stable 分支。")
    new = kernel_versions(target)
    if "abl-" in new:
        raise ReleaseError(f"{target[:8]} 带着消融实验的内核版本（{new}），不能发布。")
    log_url = main_check(fetch_builds(target), target)

    print(f"main 检查已通过：{log_url}")
    print(f"将发布 {git('rev-list', '--count', f'{stable}..{target}')} 个提交：")
    print(git("log", "--oneline", f"{stable}..{target}"))
    old = kernel_versions(stable)
    if old != new:
        print(f"记忆内核变化：{old} → {new}")
        print("同事下次启动会按新内核重新整理记忆（超过费用闸需管理员在设置的“记忆”里确认；整理前自动快照，可回退）。")
    else:
        print("记忆内核版本不变：同事的记忆不会重新整理。")
    # A plain push only fast-forwards: if stable moved since the fetch, the server refuses it.
    git("push", "--quiet", remote, f"{target}:refs/heads/stable")
    print(f"已发布 {git('log', '-1', '--format=%h %s', target)} 到 stable；")
    print("stable 的 deploy-daw 流水线接着部署 https://daw.xjjk.com/twin/，同事运行 ./scripts/local-up.sh 时自动更新。")


def is_ancestor(ancestor: str, descendant: str) -> bool:
    return subprocess.run(["git", "merge-base", "--is-ancestor", ancestor, descendant]).returncode == 0


def cnb_builds(api: str, repo: str, token: str) -> FetchBuilds:
    def fetch(commit: str) -> list[dict[str, Any]]:
        query = urllib.parse.urlencode({"sha": commit, "sourceRef": "main", "event": "push", "page_size": 20})
        request = urllib.request.Request(
            f"{api}/{repo}/-/build/logs?{query}",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return list(json.load(response).get("data") or [])
        except (OSError, ValueError) as error:
            raise ReleaseError(f"查不到 {commit[:8]} 的 main 检查结果：{error}") from None

    return fetch


def main() -> None:
    env = os.environ
    if env.get("CNB_BRANCH") != "main":
        raise SystemExit("只能在 main 分支页面上点“发布到 stable”。")
    token = env["CNB_TOKEN"]
    user = urllib.parse.quote(env.get("CNB_TOKEN_USER_NAME", "cnb"), safe="")
    remote = env["CNB_REPO_URL_HTTPS"].replace("https://", f"https://{user}:{urllib.parse.quote(token, safe='')}@", 1)
    try:
        release(
            remote,
            env.get("RELEASE_COMMIT", "").strip(),
            cnb_builds(env.get("CNB_API_ENDPOINT", "https://api.cnb.cool"), env["CNB_REPO_SLUG"], token),
        )
    except ReleaseError as error:
        print(f"未发布：{error}", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
