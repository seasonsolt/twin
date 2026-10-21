#!/usr/bin/env bash
# Set up a GPU machine to serve twin on daw: a resident transcription service (`run.py --serve`, 127.0.0.1:18790),
# optionally a text-embedding service (`embed.py`, bge-m3, 127.0.0.1:18791), and one reverse SSH tunnel that exposes
# both ports on daw's loopback. The GPU machine dials out; daw never needs to reach it.
#
#   sudo deploy/gpu/install.sh --user <account> --python <python with the asr-funasr deps and CUDA torch> \
#       --daw ubuntu@<daw address> [--embed-model <local BAAI/bge-m3 directory>] [--dry-run]
#
# Re-running updates the scripts and the units. The tunnel key is created once; put the printed line in daw's
# ~/.ssh/authorized_keys in place of an older one (it can only open these forwards, never a shell).
set -euo pipefail

port=18790
embed_port=18791
user=''
python=''
daw=''
embed_model=''
dry_run=false
while [[ $# -gt 0 ]]; do
    case "$1" in
        --user|--python|--daw|--embed-model)
            [[ $# -ge 2 && -n "$2" ]] || { echo "错误：$1 需要一个值" >&2; exit 2; }
            case "$1" in --user) user=$2 ;; --python) python=$2 ;; --daw) daw=$2 ;; --embed-model) embed_model=$2 ;; esac
            shift 2 ;;
        --dry-run) dry_run=true; shift ;;
        -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
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
[[ -z "$embed_model" || -f "$embed_model/config.json" ]] || { echo "错误：$embed_model 不是模型目录" >&2; exit 2; }

pack="$(cd "$(dirname "${BASH_SOURCE[0]}")/../compute/asr-funasr" && pwd)"
# Modules run.py imports and bundled weights, listed in pack.toml (asr-funasr 1.4+).
files=$("$python" -c 'import sys, tomllib; print(" ".join(tomllib.load(open(sys.argv[1], "rb")).get("files", [])))' \
    "$pack/pack.toml")
target="$home/twin-asr"
key="$home/.ssh/twin_asr_tunnel"
forwards="-R 127.0.0.1:$port:127.0.0.1:$port"
listen="permitlisten=\"127.0.0.1:$port\""
after="twin-asr.service"
if [[ -n "$embed_model" ]]; then
    forwards="$forwards -R 127.0.0.1:$embed_port:127.0.0.1:$embed_port"
    listen="$listen,permitlisten=\"127.0.0.1:$embed_port\""
    after="$after twin-embed.service"
fi

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
embed_unit="[Unit]
Description=twin text embeddings (resident bge-m3 on the GPU)
After=network.target

[Service]
Type=simple
User=$user
WorkingDirectory=$target
ExecStart=$python $target/embed.py --model $embed_model --host 127.0.0.1 --port $embed_port
Restart=on-failure
RestartSec=10
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
"
tunnel_unit="[Unit]
Description=Reverse tunnel publishing the twin GPU services on daw's loopback
After=network-online.target $after
Wants=network-online.target

[Service]
Type=simple
User=$user
ExecStart=/usr/bin/ssh -N -i $key -o IdentitiesOnly=yes -o BatchMode=yes -o ExitOnForwardFailure=yes \\
    -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -o StrictHostKeyChecking=accept-new \\
    $forwards $daw
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
"

if "$dry_run"; then
    echo "将复制 run.py、pack.toml、embed.py${files:+ 和 $files} 到 ${target}，并写入以下服务："
    printf '%s\n' "--- /etc/systemd/system/twin-asr.service" "$asr_unit"
    [[ -z "$embed_model" ]] || printf '%s\n' "--- /etc/systemd/system/twin-embed.service" "$embed_unit"
    printf '%s\n' "--- /etc/systemd/system/twin-asr-tunnel.service" "$tunnel_unit"
    exit 0
fi
[[ $EUID -eq 0 ]] || { echo "错误：需要 sudo 运行" >&2; exit 1; }

install -d -o "$user" -g "$(id -gn "$user")" -m 755 "$target"
install -o "$user" -g "$(id -gn "$user")" -m 644 "$pack/run.py" "$pack/pack.toml" "$(dirname "${BASH_SOURCE[0]}")/embed.py" "$target/"
for file in $files; do
    install -d -o "$user" -g "$(id -gn "$user")" -m 755 "$target/$(dirname "$file")"
    install -o "$user" -g "$(id -gn "$user")" -m 644 "$pack/$file" "$target/$file"
done
install -d -o "$user" -g "$(id -gn "$user")" -m 700 "$home/.ssh"
if [[ ! -f "$key" ]]; then
    runuser -u "$user" -- ssh-keygen -q -t ed25519 -N '' -C "twin-asr-tunnel@$(hostname)" -f "$key"
fi
printf '%s' "$asr_unit" > /etc/systemd/system/twin-asr.service
printf '%s' "$tunnel_unit" > /etc/systemd/system/twin-asr-tunnel.service
if [[ -n "$embed_model" ]]; then
    printf '%s' "$embed_unit" > /etc/systemd/system/twin-embed.service
fi
systemctl daemon-reload
systemctl enable --quiet twin-asr twin-asr-tunnel
systemctl restart twin-asr
if [[ -n "$embed_model" ]]; then
    systemctl enable --quiet twin-embed
    systemctl restart twin-embed
fi
systemctl restart twin-asr-tunnel

for _ in $(seq 1 90); do
    curl --silent --fail --max-time 2 "http://127.0.0.1:$port/health" && echo && break
    sleep 2
done
if [[ -n "$embed_model" ]]; then
    for _ in $(seq 1 90); do
        curl --silent --fail --max-time 2 "http://127.0.0.1:$embed_port/health" && echo && break
        sleep 2
    done
fi
echo "在 daw 的 ~/.ssh/authorized_keys 用下面一行替换这把密钥原来的那行（只允许这些端口转发，不能登录）："
echo "restrict,port-forwarding,$listen,command=\"/usr/sbin/nologin\" $(cat "$key.pub")"
