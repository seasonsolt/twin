#!/usr/bin/env bash
# Set up a GPU machine to transcribe for twin on daw: a resident `run.py --serve` plus a reverse SSH tunnel that
# exposes it as 127.0.0.1:18790 on daw. The GPU machine dials out; daw never needs to reach it.
#
#   sudo deploy/gpu/install.sh --user <account> --python <python with the asr-funasr deps and CUDA torch> \
#       --daw ubuntu@<daw address> [--dry-run]
#
# Re-running updates run.py/pack.toml and the units. The tunnel key is created once; add the printed line to
# daw's ~/.ssh/authorized_keys (it can only open that one forward, never a shell).
set -euo pipefail

port=18790
user=''
python=''
daw=''
dry_run=false
while [[ $# -gt 0 ]]; do
    case "$1" in
        --user|--python|--daw)
            [[ $# -ge 2 && -n "$2" ]] || { echo "错误：$1 需要一个值" >&2; exit 2; }
            case "$1" in --user) user=$2 ;; --python) python=$2 ;; --daw) daw=$2 ;; esac
            shift 2 ;;
        --dry-run) dry_run=true; shift ;;
        -h|--help) sed -n '2,9p' "$0"; exit 0 ;;
        *) echo "错误：未知参数 $1" >&2; exit 2 ;;
    esac
done
[[ -n "$user" && -n "$python" && -n "$daw" ]] || { echo "错误：需要 --user、--python 和 --daw" >&2; exit 2; }
[[ "$user" =~ ^[A-Za-z_][A-Za-z0-9_.-]*$ ]] || { echo "错误：用户名无效" >&2; exit 2; }
home=$(getent passwd "$user" 2>/dev/null | cut -d: -f6 || true)
[[ -n "$home" ]] || home=$(eval echo "~$user")  # no getent (macOS dry run); the name is validated above
[[ "$home" == /* ]] || home=""
[[ -n "$home" ]] || { echo "错误：没有用户 $user" >&2; exit 2; }
[[ -x "$python" ]] || { echo "错误：$python 不可执行" >&2; exit 2; }

pack="$(cd "$(dirname "${BASH_SOURCE[0]}")/../compute/asr-funasr" && pwd)"
target="$home/twin-asr"
key="$home/.ssh/twin_asr_tunnel"

asr_unit="[Unit]
Description=twin meeting transcription (resident asr-funasr on the GPU)
After=network.target

[Service]
Type=simple
User=$user
WorkingDirectory=$target
ExecStart=$python $target/run.py --serve --host 127.0.0.1 --port $port
Restart=on-failure
RestartSec=10
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
"
tunnel_unit="[Unit]
Description=Reverse tunnel publishing twin-asr as 127.0.0.1:$port on daw
After=network-online.target twin-asr.service
Wants=network-online.target

[Service]
Type=simple
User=$user
ExecStart=/usr/bin/ssh -N -i $key -o IdentitiesOnly=yes -o BatchMode=yes -o ExitOnForwardFailure=yes \\
    -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -o StrictHostKeyChecking=accept-new \\
    -R 127.0.0.1:$port:127.0.0.1:$port $daw
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
"

if "$dry_run"; then
    echo "将复制 run.py、pack.toml 到 ${target}，并写入以下两个服务："
    printf '%s\n' "--- /etc/systemd/system/twin-asr.service" "$asr_unit" "--- /etc/systemd/system/twin-asr-tunnel.service" "$tunnel_unit"
    exit 0
fi
[[ $EUID -eq 0 ]] || { echo "错误：需要 sudo 运行" >&2; exit 1; }

install -d -o "$user" -g "$(id -gn "$user")" -m 755 "$target"
install -o "$user" -g "$(id -gn "$user")" -m 644 "$pack/run.py" "$pack/pack.toml" "$target/"
install -d -o "$user" -g "$(id -gn "$user")" -m 700 "$home/.ssh"
if [[ ! -f "$key" ]]; then
    runuser -u "$user" -- ssh-keygen -q -t ed25519 -N '' -C "twin-asr-tunnel@$(hostname)" -f "$key"
fi
printf '%s' "$asr_unit" > /etc/systemd/system/twin-asr.service
printf '%s' "$tunnel_unit" > /etc/systemd/system/twin-asr-tunnel.service
systemctl daemon-reload
systemctl enable --quiet twin-asr twin-asr-tunnel
systemctl restart twin-asr
systemctl restart twin-asr-tunnel

for _ in $(seq 1 90); do
    curl --silent --fail --max-time 2 "http://127.0.0.1:$port/health" && echo && break
    sleep 2
done
echo "在 daw 的 ~/.ssh/authorized_keys 加入下面一行（只允许这一个端口转发，不能登录）："
echo "restrict,port-forwarding,permitlisten=\"127.0.0.1:$port\",command=\"/usr/sbin/nologin\" $(cat "$key.pub")"
