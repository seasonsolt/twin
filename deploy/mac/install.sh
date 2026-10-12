#!/usr/bin/env bash
set -euo pipefail
umask 077

repo="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
if [[ "${1:-}" == "--dry-run" && $# == 1 ]]; then
    printf '%s\n' \
        '预演：检查 Apple Silicon、macOS 14+、Homebrew；不执行任何安装。' \
        'brew install uv ffmpeg cloudflared git（已安装则跳过）' \
        'uv build --wheel；uv export --frozen --no-dev --no-emit-project（保留哈希）' \
        '从 twin.ops.paths 解析目录；建立 releases/<version>/venv' \
        'uv pip install --require-hashes -r requirements.lock；安装本仓库 wheel' \
        '原子切换 current；不存在配置时 twin init --profile mac-unified；创建 0600 env' \
        '默认只有文字聊天；媒体能力按需开启，P4 将提供 twin compute install；本次不下载模型' \
        'twin ops install-services；twin ops start；twin doctor' \
        "TWIN_HOME=${TWIN_HOME:-默认系统目录}"
    exit 0
fi
if (( $# != 0 )); then
    printf '%s\n' '用法：deploy/mac/install.sh [--dry-run]' >&2
    exit 2
fi
if [[ "$(uname -s)" != Darwin || "$(uname -m)" != arm64 ]]; then
    printf '%s\n' '需要 Apple Silicon Mac（arm64）。' >&2
    exit 1
fi
mac_version="$(sw_vers -productVersion)"
if (( ${mac_version%%.*} < 14 )); then
    printf '%s\n' '需要 macOS 14 或更高版本。' >&2
    exit 1
fi
if ! command -v brew >/dev/null 2>&1; then
    printf '%s\n' '请先按 https://brew.sh 的说明手动安装 Homebrew，然后重试。安装命令：' \
        '/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"' >&2
    exit 1
fi
for formula in uv ffmpeg cloudflared git; do
    if ! command -v "$formula" >/dev/null 2>&1; then
        brew install "$formula"
    fi
done
cd "$repo"
build_dir="$(mktemp -d)"
trap 'rm -rf -- "$build_dir"' EXIT
uv build --wheel --out-dir "$build_dir"
uv export --frozen --no-dev --no-emit-project --format requirements-txt --output-file "$build_dir/requirements.lock"
uv run --no-project --python 3.12 python - "$repo" "$build_dir/paths" <<'PY'
import os
import sys
import tomllib
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]) / "src"))
from twin.ops.paths import TwinPaths
paths = TwinPaths.from_env()
version = tomllib.loads((Path(sys.argv[1]) / "pyproject.toml").read_text())["project"]["version"]
values = [str(paths.home), str(paths.config), str(paths.env), version]
if any("\n" in value for value in values):
    raise SystemExit("目录不能包含换行")
Path(sys.argv[2]).write_text("\n".join(values) + "\n")
PY
{
    IFS= read -r install_home
    IFS= read -r config_path
    IFS= read -r env_path
    IFS= read -r version
} < "$build_dir/paths"
release="$install_home/releases/$version"
wheels=("$build_dir"/*.whl)
wheel="${wheels[0]}"
wheel_hash="$(shasum -a 256 "$wheel" | cut -d ' ' -f 1)"
if [[ -f "$release/wheel.sha256" ]]; then
    installed_hash="$(< "$release/wheel.sha256")"
    if [[ "$installed_hash" != "$wheel_hash" ]]; then
        printf '%s\n' '相同版本已有不同 wheel，请先调整应用版本；不会覆盖现有 release。' >&2
        exit 1
    fi
else
    mkdir -p "$release"
    uv venv --python 3.12 --allow-existing "$release/venv"
    uv pip install --python "$release/venv/bin/python" --require-hashes -r "$build_dir/requirements.lock"
    uv pip install --python "$release/venv/bin/python" --no-deps "$wheel"
    printf '%s\n' "$wheel_hash" > "$release/wheel.sha256"
fi
uv run --no-project --python 3.12 python - "$install_home" "$release" <<'PY'
import os
import sys
from pathlib import Path
root, release = map(Path, sys.argv[1:])
link = root / "current.new"
if link.is_symlink():
    link.unlink()
link.symlink_to(release)
os.replace(link, root / "current")
PY
mkdir -p "$(dirname -- "$env_path")"
if [[ ! -e "$env_path" ]]; then
    : > "$env_path"
fi
chmod 600 "$env_path"
export TWIN_ENV_FILE="$env_path"
twin=("$install_home/current/venv/bin/twin" --config "$config_path")
if [[ ! -f "$config_path" ]]; then
    "${twin[@]}" init --profile mac-unified
fi
printf '%s\n' "请编辑 $config_path，填写模型与端点；在 $env_path 中填写 TWIN_LLM_KEY（及启用后端所需变量）。" \
    '默认只有文字聊天；媒体能力可手写配置（docs/MEDIA.md），P4 将提供 twin compute install。会议录音需开启转写（asr-funasr）。'
"${twin[@]}" ops install-services
"${twin[@]}" ops start
if ! "${twin[@]}" doctor; then
    printf '%s\n' '安装完成，自检仍有待配置项；填写配置与 env 后运行 twin ops restart 和 twin doctor。'
fi
printf '%s\n' '建议手动执行 sudo pmset -c sleep 0，并开启“断电后自动重启”。' \
    'LaunchAgent 需要用户登录；FileVault 机器重启后需先登录一次。'
