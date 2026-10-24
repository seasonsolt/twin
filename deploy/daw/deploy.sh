#!/usr/bin/env bash
# Deploy one twin release on daw from a `git archive` tarball. Run as root (deploy_via_tat.py does this).
#
# /data/twin/releases/<time>-<digest>/  code + its own .venv; /data/twin/current points at the live one
# /data/twin/twin.toml, /data/twin/.env  written once by an admin (see deploy/daw/README.md), never touched here
# /data/twin/data, /data/twin/home       data and backups, owned by the service user
#
# Every step before the switch is side-effect free for the running service. After the switch a failed health
# check points `current` back at the previous release and restarts it, unless the new release migrates a database
# further than the previous one reads: then the previous code could not start on the migrated data, so the switch
# stays and the deploy stops with how to go back from the backup made before it (README.md#回退).
set -euo pipefail

ROOT="${TWIN_DEPLOY_ROOT:-/data/twin}"
OWNER="${TWIN_DEPLOY_USER:-ubuntu}"
MIRROR="${TWIN_PYPI_MIRROR:-http://mirrors.tencentyun.com/pypi/simple}"
SERVICE=twin
PORT=8770
KEEP=3
UV_VERSION=0.13.0
ARCHIVE="${1:-}"

die() {
    echo "错误：$*" >&2
    exit 1
}

[[ -n "$ARCHIVE" && -f "$ARCHIVE" ]] || die "用法：$0 <release.tar.gz>"
[[ $EUID -eq 0 ]] || die "需要以 root 运行"
for command in curl ffmpeg flock nginx python3 runuser sha256sum systemctl tar; do
    command -v "$command" >/dev/null || die "缺少命令 $command"
done
[[ -f "$ROOT/twin.toml" && -f "$ROOT/.env" ]] || die "先按 deploy/daw/README.md 准备 $ROOT/twin.toml 和 $ROOT/.env"

cd "$ROOT"
exec 9>"$ROOT/.deploy.lock"
flock -n 9 || die "另一次部署正在进行"

as_owner() { runuser -u "$OWNER" -- env HOME="$(getent passwd "$OWNER" | cut -d: -f6)" "$@"; }
twin_cli() { as_owner env TWIN_HOME="$ROOT/home" TWIN_ENV_FILE="$ROOT/.env" "$@"; }

install -d -o "$OWNER" -g "$OWNER" -m 700 "$ROOT/data" "$ROOT/home"
install -d -o "$OWNER" -g "$OWNER" -m 755 "$ROOT/releases"

# 1. Unpack and build the new release next to the live one.
digest=$(sha256sum "$ARCHIVE" | cut -c1-12)
target="$ROOT/releases/$(date +%Y%m%d%H%M%S)-$digest"
install -d -o "$OWNER" -g "$OWNER" -m 755 "$target"
tar -xzf "$ARCHIVE" -C "$target"
chown -R "$OWNER:$OWNER" "$target"
for required in pyproject.toml uv.lock src/twin/web/static/index.html deploy/daw/twin.service deploy/daw/nginx-twin.conf; do
    [[ -f "$target/$required" ]] || die "发布包缺少 $required"
done

uv="$ROOT/tools/bin/uv"
if [[ ! -x "$uv" ]] || [[ "$("$uv" --version | cut -d' ' -f2)" != "$UV_VERSION" ]]; then
    install -d -o "$OWNER" -g "$OWNER" -m 755 "$ROOT/tools"
    as_owner python3 -m venv --clear "$ROOT/tools"
    as_owner "$ROOT/tools/bin/pip" install --quiet --disable-pip-version-check "uv==$UV_VERSION"
fi
# uv.lock pins files.pythonhosted.org, which crawls from here; the cloud mirror serves the same files, and the
# exported requirements keep the lock's versions and hashes.
index=(--index-url "$MIRROR")
if [[ "$MIRROR" == http://* ]]; then
    host=${MIRROR#http://}
    index+=(--allow-insecure-host "${host%%/*}")
fi
(
    cd "$target"
    as_owner env UV_PYTHON_DOWNLOADS=never "$uv" export --frozen --no-dev --no-emit-project --quiet -o requirements.txt
    as_owner env UV_PYTHON_DOWNLOADS=never "$uv" venv --quiet --python python3 .venv
    as_owner "$uv" pip sync --quiet --python .venv/bin/python "${index[@]}" requirements.txt
    as_owner "$uv" pip install --quiet --python .venv/bin/python --no-deps -e .
)
as_owner "$target/.venv/bin/twin" --help >/dev/null || die "新版本无法启动 twin 命令"

# 2. Snapshot the data with the code that wrote it; migrations of the new release snapshot again on start.
backup=""
if [[ -x "$ROOT/current/.venv/bin/twin" ]]; then
    said=$(twin_cli "$ROOT/current/.venv/bin/twin" --config "$ROOT/twin.toml" ops backup --reason deploy)
    echo "$said"
    backup=${said#*备份完成：}
fi

# How many migrations each database of a release knows (a twin's, the team's): a release that knows more than the
# live one migrates the data on start one way.
migrations() {
    as_owner "$1/.venv/bin/python" -c '
import importlib
counts = []
for name in ("twin.persona.store", "twin.teamdb"):
    try:
        counts.append(len(importlib.import_module(name)._MIGRATIONS))
    except (ImportError, AttributeError):
        counts.append(0)
print(*counts)'
}
one_way=""
if [[ -x "$ROOT/current/.venv/bin/python" ]]; then
    read -r -a before <<<"$(migrations "$ROOT/current")"
    read -r -a after <<<"$(migrations "$target")"
    for i in "${!after[@]}"; do
        if ((after[i] > ${before[i]:-0})); then
            one_way=1
        fi
    done
    [[ -n "$one_way" ]] && echo "新版本会升级数据库结构（${before[*]} → ${after[*]}），升级后旧版本无法打开数据"
fi

# 3. System files: only reload what changed.
if ! cmp -s "$target/deploy/daw/twin.service" "/etc/systemd/system/$SERVICE.service"; then
    install -m 644 "$target/deploy/daw/twin.service" "/etc/systemd/system/$SERVICE.service"
    systemctl daemon-reload
    systemctl enable --quiet "$SERVICE"
fi
snippet="/etc/nginx/snippets/daw-apps/twin.conf"
if ! cmp -s "$target/deploy/daw/nginx-twin.conf" "$snippet"; then
    install -d -m 755 "$(dirname "$snippet")"
    [[ -f "$snippet" ]] && cp -a "$snippet" "$snippet.previous"
    install -m 644 "$target/deploy/daw/nginx-twin.conf" "$snippet"
    if ! nginx -t 2>&1; then
        if [[ -f "$snippet.previous" ]]; then mv "$snippet.previous" "$snippet"; else rm -f "$snippet"; fi
        die "nginx 配置检查失败，已恢复原配置"
    fi
    rm -f "$snippet.previous"
    systemctl reload nginx
fi

# 4. Switch, restart, check; on failure go back to the previous release.
previous=$(readlink "$ROOT/current" || true)
switch_to() {
    ln -sfn "$1" "$ROOT/current.next"
    mv -T "$ROOT/current.next" "$ROOT/current"
    systemctl restart "$SERVICE"
}
healthy() {
    # A release that migrates the data snapshots every twin's database before it serves: give it longer.
    local page status seconds=60
    [[ -n "$one_way" ]] && seconds=900
    for _ in $(seq 1 "$seconds"); do
        page=$(curl --silent --max-time 3 "http://127.0.0.1:$PORT/" || true)
        status=$(curl --silent --output /dev/null --max-time 3 --write-out '%{http_code}' \
            "http://127.0.0.1:$PORT/api/whoami" || true)
        if [[ "$page" == *"<title>twin</title>"* && ("$status" == 200 || "$status" == 401) ]]; then
            return 0
        fi
        sleep 1
    done
    return 1
}
through_nginx() {
    # Only once audio-studio's server block includes the snippets; until then twin is up but not published.
    if ! grep -rqs "snippets/daw-apps" /etc/nginx/sites-enabled/; then
        echo "提示：nginx 还没有引入 /etc/nginx/snippets/daw-apps/*.conf，https://daw.xjjk.com/twin/ 暂不可访问" >&2
        return 0
    fi
    local page
    page=$(curl --silent --max-time 5 --header 'Host: daw.xjjk.com' http://127.0.0.1/twin/ || true)
    [[ "$page" == *"<title>twin</title>"* ]]
}

switch_to "$target"
if ! healthy || ! through_nginx; then
    journalctl -u "$SERVICE" -n 40 --no-pager >&2 || true
    if [[ -n "$one_way" ]]; then
        # The previous code can not open the migrated data: switching back would leave nothing running at all.
        die "新版本健康检查失败。它已升级数据库结构，旧版本 $(basename "$previous") 打不开升级后的数据，所以没有自动回退，服务停在新版本上。先看上面的日志；要回到旧版本，按 deploy/daw/README.md 的“回退”一节用部署前的备份 ${backup:-（没有找到）} 恢复"
    fi
    if [[ -n "$previous" && -d "$previous" ]]; then
        switch_to "$previous"
        healthy && die "新版本健康检查失败，已回到 $(basename "$previous")"
        die "新版本健康检查失败，回到 $(basename "$previous") 后仍不健康，请登录 daw 检查"
    fi
    die "新版本健康检查失败，且没有可回退的版本"
fi

# 5. Keep the newest releases; the live one is always among them.
find "$ROOT/releases" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | sort -r | tail -n +$((KEEP + 1)) |
    while read -r name; do
        [[ "$ROOT/releases/$name" == "$(readlink "$ROOT/current")" ]] || rm -rf "${ROOT:?}/releases/$name"
    done
echo "部署完成：$(basename "$target")（https://daw.xjjk.com/twin/）"
