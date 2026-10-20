# daw 部署（https://daw.xjjk.com/twin/）

twin 挂在 audio-studio 的域名下，用它的登录；转写和文字向量走 4090 经反向隧道提供的 `127.0.0.1:18790`、`127.0.0.1:18791`。

## 发布

推送 `stable` 分支（`./scripts/release-stable.sh`）触发 `.cnb.yml` 的 `deploy-daw`：检查 → `git archive` 打包 →
腾讯云 TAT 分片上传 → 在 daw 上以 root 运行 `deploy/daw/deploy.sh`。脚本先备份数据，再切换 `current`；新版本
健康检查失败会自动回到上一版。部署备份只保留最近 10 份，更早的在下一次备份时删除；录音库录音和分身的原件、
试听片段、声音候选等写完不再改的文件用硬链接，不重复占盘（与线上同盘，不能代替异地备份）。

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

[embed]  # 4090 上的 bge-m3（见下文）；没有时写 provider = "hashing"
provider = "openai_compat"
model = "BAAI/bge-m3"
base_url = "http://127.0.0.1:18791/v1"
egress = "local"
timeout = 15
max_retries = 1

[asr]
provider = "command"
command = "python3 /data/twin/current/deploy/compute/asr-funasr/remote.py --url http://127.0.0.1:18790"
language = "zh"
egress = "local"

[auth]
enabled = true
provider = "sso"
password_login = true  # twin 自己的账号密码，与统一身份并列；账号用 twin account add 创建
admin_emails = ["zhangxun@xjjk.com", "qianjinwen@xjjk.com"]  # 按 SSO 账号名匹配（zhangxun 或 zhangxun@xjjk.com）；也可写 journalctl -u twin “SSO 登录”行里的 sso:<subject>

[auth.sso]
me_url = "http://127.0.0.1:8765/api/auth/me"
cookie = "audio_studio_session"
start_url = "/auth/start?next=/twin/"  # 登录页的统一身份按钮直接交给 audio-studio 跳认证中心
sign_in_origin = "https://center.njxjjt.com"  # 认证中心的源：浏览器只在 twin 的 CSP form-action 放行它时才跟随跳转；不写则按钮退回链接到 login_url
login_url = "/login?next=/twin/"
```

在 daw 上创建 twin 账号（密码在终端输入）：`sudo -u ubuntu /data/twin/current/.venv/bin/twin --config /data/twin/twin.toml account add <账号> --name <名字>`。

audio-studio 的 nginx server 块需要一次性加入 `include /etc/nginx/snippets/daw-apps/*.conf;`，twin 的
`nginx-twin.conf` 由部署脚本放进该目录。

## 转写与文字向量（4090）

先把 BAAI/bge-m3 下到 4090 本地目录（连不上 Hugging Face 时用 ModelScope 的同名仓库），再在 4090 上运行
`sudo deploy/gpu/install.sh --user <账号> --python <装好依赖的 python> --daw ubuntu@<daw> --embed-model <模型目录>`。
它写入 `twin-asr`、`twin-embed` 和一条同时转发两个端口的隧道；把输出的一行替换进 daw 的 `~/.ssh/authorized_keys`
（只允许这两个端口转发，不能登录）。**先改 daw 的这一行，再重启隧道**：隧道设了 `ExitOnForwardFailure`，daw 不允许
18791 时整条隧道连不上，转写也会中断。检查（在 daw 上）：`curl http://127.0.0.1:18790/health`、
`curl http://127.0.0.1:18791/health`。
不在办公网时，管理员点网页左下角账户头像，在菜单里打开「系统设置」（手机上在分身切换面板里），在「监控」和「GPU 服务」分区看：twin 每分钟检查一次两个服务（向量服务再做一次真实
向量化），显示是否正常、异常原因、最近一天的可用率和最近一次失败；记录只在进程内，twin 重启后从头记。

管理员也可以在「系统设置 → 模型与 Token」里修改文字模型和向量模型的地址与模型名、设置或更换密钥，保存后立即生效，
不用登录 daw：密钥写入 `/data/twin/.env`（0600），只显示是否已设置；修改记录在 `/data/twin/data/system-audit.jsonl`。
管理员由 `[auth] admin_emails` 决定：写 `zhangxun@xjjk.com` 时，SSO 账号名是 `zhangxun` 或 `zhangxun@xjjk.com` 的人都是管理员
（账号名见 `journalctl -u twin` 里“SSO 登录：…（账号 …）”一行）。

向量服务停了或隧道断了，聊天退回只按关键词检索，照常回答；记忆整理的向量化那一步会失败，服务恢复后下一次整理接着做。
换向量模型后，各分身在网页启动时发现旧向量并自动重新向量化。显卡与转写（有时还有语言模型）共用，向量服务常驻约
1.6 GB 显存，每次请求后归还临时显存。

## 排查

`systemctl status twin`、`journalctl -u twin -n 100`；版本在 `/data/twin/releases/`，`current` 指向在线版本。
