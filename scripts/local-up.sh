#!/usr/bin/env bash
set -euo pipefail

repo_root="${REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
demo=false
open_browser=true
dry_run=false
port=8765
while [[ $# -gt 0 ]]; do
    case "$1" in
        --demo) demo=true; shift ;;
        --no-open) open_browser=false; shift ;;
        --dry-run) dry_run=true; shift ;;
        --port)
            if [[ $# -lt 2 || ! "$2" =~ ^[0-9]{1,5}$ ]]; then
                echo '错误：--port 需要 1–65535 的整数。' >&2
                exit 2
            fi
            port=$((10#$2))
            if (( port < 1 || port > 65535 )); then
                echo '错误：--port 需要 1–65535 的整数。' >&2
                exit 2
            fi
            shift 2 ;;
        --help|-h)
            echo '用法：./scripts/local-up.sh [--demo] [--no-open] [--port N] [--dry-run]'
            exit 0 ;;
        *) echo "错误：未知参数 $1" >&2; exit 2 ;;
    esac
done
cd "$repo_root"
repo_root="$PWD"
echo '本地验证：默认只有文字聊天，数据默认保存在本仓库 data/。'
echo '更新代码：停止服务后运行 git pull && ./scripts/local-up.sh'
echo '数据库迁移和记忆内核增量重建由应用自动完成（保留费用闸）。'
if "$dry_run"; then
    echo '预览：检查 uv；缺少 ffmpeg 只提示（文字聊天不需要）。'
    echo 'uv sync --frozen'
    echo '若缺少 twin.toml：twin --config ./twin.toml init ./twin.toml（默认模板，db_path = data/twin.db）'
    echo '若缺少 .env：从 .env.example 复制；chmod 600 .env'
    echo '缺少 [llm] model/base_url 或密钥时在终端逐项询问并保存（密钥写入 .env，不回显）；非终端则提示后退出。'
    echo '创建数据目录 data/（权限 700）'
    echo 'twin --config ./twin.toml doctor --local（只展示，不阻塞；不检查常驻服务）'
    echo "端口 $port 被占用时自动改用后续空闲端口"
    if "$demo"; then echo 'twin --config ./twin.toml demo seed'; fi
    echo "exec twin --config ./twin.toml ui --port $port$(if "$open_browser"; then printf ' --open'; fi)"
    exit 0
fi
if ! command -v uv >/dev/null 2>&1; then
    echo '缺少 uv。请先安装：brew install uv，然后重新运行本脚本。' >&2
    exit 1
fi
if ! command -v ffmpeg >/dev/null 2>&1; then
    echo '提示：未找到 ffmpeg；文字聊天不需要，导入录音时再运行 brew install ffmpeg。'
fi
uv sync --frozen
export PATH="$repo_root/.venv/bin:$PATH"
if [[ ! -e .env ]]; then
    (umask 077; cp .env.example .env)
fi
chmod 600 .env
if [[ ! -e twin.toml ]]; then
    twin --config ./twin.toml init ./twin.toml >/dev/null
    echo '已生成 ./twin.toml（默认文字聊天，数据在 data/）。'
fi
python -c 'from twin.ops.local import check_local_config; raise SystemExit(check_local_config())'
echo '环境自检：'
twin --config ./twin.toml doctor --local || echo '以上 ✗ 项不阻塞本地启动，可稍后处理。'
if "$demo"; then twin --config ./twin.toml demo seed; fi
free_port=$(python - "$port" <<'PY'
import socket, sys
start = int(sys.argv[1])
for port in range(start, min(start + 20, 65536)):
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            continue
        print(port)
        break
PY
)
if [[ -z "$free_port" ]]; then
    echo "错误：端口 $port 起的 20 个端口都被占用，请用 --port 指定。" >&2
    exit 1
fi
if [[ "$free_port" != "$port" ]]; then
    echo "端口 $port 已被占用，改用 ${free_port}。"
    port=$free_port
fi
args=(--config ./twin.toml ui --port "$port")
if "$open_browser"; then args+=(--open); fi
exec twin "${args[@]}"
