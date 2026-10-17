#!/usr/bin/env bash
# 关键页面截图对比（frontend/e2e）。在固定版本的 Playwright 镜像里运行，本机和 CI 用同一套基线。
#   ./scripts/screenshots.sh                      先构建前端，再对比截图
#   ./scripts/screenshots.sh --update-snapshots   界面有意改变时，重新生成基线（提交前逐张看一遍）
#   ./scripts/screenshots.sh -g chat              其余参数原样交给 playwright test
# 设置 TWIN_SCREENSHOTS_NO_BUILD=1 跳过构建（scripts/check.py 已先构建）。对比失败时差异图在 frontend/e2e/.results/。
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# 与 frontend/package.json 里 @playwright/test 的版本一致。
image='mcr.microsoft.com/playwright:v1.63.0-noble'

if ! command -v docker >/dev/null 2>&1 || ! docker info >/dev/null 2>&1; then
    echo '错误：截图测试需要 Docker（本机装 Docker Desktop 或 OrbStack 并启动）。' >&2
    echo '截图在固定的 Linux 镜像里生成，换成本机浏览器字体会不同，基线对不上。' >&2
    exit 1
fi
if [[ "${TWIN_SCREENSHOTS_NO_BUILD:-}" != 1 ]]; then
    pnpm -C "$repo_root/frontend" build
fi
tty=()
if [[ -t 1 ]]; then tty=(-t); fi
exec docker run --rm "${tty[@]}" --ipc=host --init \
    --user "$(id -u):$(id -g)" -e HOME=/tmp -e CI="${CI:-}" \
    -v "$repo_root:/repo" -w /repo/frontend \
    "$image" node node_modules/@playwright/test/cli.js test "$@"
