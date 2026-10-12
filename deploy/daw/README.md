# daw 部署（https://daw.xjjk.com/twin/）

twin 挂在 audio-studio 的域名下，用它的登录；转写走 4090 经反向隧道提供的 `127.0.0.1:18790`。

## 发布

推送 `stable` 分支（`./scripts/release-stable.sh`）触发 `.cnb.yml` 的 `deploy-daw`：检查 → `git archive` 打包 →
腾讯云 TAT 分片上传 → 在 daw 上以 root 运行 `deploy/daw/deploy.sh`。脚本先备份数据，再切换 `current`；新版本
健康检查失败会自动回到上一版。

## 首次准备（管理员在 daw 上手工做一次，部署不会改动）

`/data/twin/.env`（属主 ubuntu，权限 0600）只放密钥：

```
TWIN_LLM_KEY=...
```

`/data/twin/twin.toml`（属主 ubuntu，0600）只写变量名，不写密钥：

```toml
target_name = "本人"
db_path = "/data/twin/data/twin.db"

[llm]
provider = "openai_compat"
model = "deepseek-flash"
base_url = "https://api.deepseek.com"
api_key_env = "TWIN_LLM_KEY"
json_mode = "json_object"
extra_body = { thinking = { type = "disabled" } }

[embed]
provider = "hashing"

[asr]
provider = "command"
command = "python3 /data/twin/current/deploy/compute/asr-funasr/remote.py --url http://127.0.0.1:18790"
language = "zh"
egress = "local"

[auth]
enabled = true
provider = "sso"
admin_emails = []  # 首次登录后从 journalctl -u twin 的“SSO 登录”行取 sso:<subject> 填入

[auth.sso]
me_url = "http://127.0.0.1:8765/api/auth/me"
cookie = "audio_studio_session"
login_url = "/login?next=/twin/"
```

audio-studio 的 nginx server 块需要一次性加入 `include /etc/nginx/snippets/daw-apps/*.conf;`，twin 的
`nginx-twin.conf` 由部署脚本放进该目录。

## 转写（4090）

在 4090 上 `sudo deploy/gpu/install.sh --user <账号> --python <装好依赖的 python> --daw ubuntu@<daw>`，
把输出的一行加入 daw 的 `~/.ssh/authorized_keys`（只允许这一个端口转发，不能登录）。检查：
`curl http://127.0.0.1:18790/health`（在 daw 上）。

## 排查

`systemctl status twin`、`journalctl -u twin -n 100`；版本在 `/data/twin/releases/`，`current` 指向在线版本。
