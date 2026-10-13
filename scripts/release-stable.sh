#!/usr/bin/env bash
# Publish the commit on origin/main to the stable branch that colleagues run (fast-forward only).
set -euo pipefail

yes=false
if [[ "${1:-}" == --yes ]]; then yes=true; elif (( $# != 0 )); then
    echo '用法：./scripts/release-stable.sh [--yes]' >&2
    exit 2
fi
cd "$(dirname "${BASH_SOURCE[0]}")/.."
if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
    echo '有未提交的改动，请先提交并推到 origin/main。' >&2
    exit 1
fi
git fetch --quiet origin
head=$(git rev-parse HEAD)
if [[ "$head" != "$(git rev-parse origin/main)" ]]; then
    echo '当前提交不是 origin/main：请先 git push origin main（或切到 main 并 git pull），再发布。' >&2
    exit 1
fi
base=''
if git rev-parse --verify --quiet origin/stable >/dev/null; then
    base=origin/stable
    if [[ "$(git rev-parse origin/stable)" == "$head" ]]; then
        echo 'stable 已是当前提交，无需发布。'
        exit 0
    fi
    if ! git merge-base --is-ancestor origin/stable HEAD; then
        echo 'origin/stable 不在 main 的历史上，无法快进发布；请检查 stable 分支。' >&2
        exit 1
    fi
fi

echo '发布前检查：ruff、mypy、pytest…'
uv run ruff check src tests deploy
uv run mypy
uv run pytest -q -n auto

versions() { git show "$1:src/twin/persona/kernel.py" | grep -E '^(PROMPT|TAXONOMY)_VERSION = ' | tr '\n' ' '; }
echo
if [[ -n "$base" ]]; then
    echo "将发布 $(git rev-list --count "$base..HEAD") 个提交："
    git log --oneline "$base..HEAD"
    old=$(versions "$base")
    new=$(versions HEAD)
    if [[ "$old" != "$new" ]]; then
        echo "记忆内核变化：${old}→ ${new}"
        echo '同事下次启动会按新内核重新整理记忆（超过费用闸需在记忆页确认；整理前自动快照，可回退）。'
    else
        echo '记忆内核版本不变：同事的记忆不会重新整理。'
    fi
else
    echo '首次创建 stable 分支。'
fi
if ! "$yes"; then
    read -r -p "发布到 stable？[y/N] " answer
    [[ "$answer" == y || "$answer" == Y ]] || { echo '已取消。'; exit 1; }
fi
git push origin HEAD:refs/heads/stable
echo "已发布 $(git log -1 --format='%h %s') 到 stable；同事运行 ./scripts/local-up.sh 时自动更新。"
