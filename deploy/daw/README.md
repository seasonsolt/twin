# daw 部署（https://daw.xjjk.com/twin/）

twin 挂在 audio-studio 的域名下，用它的登录；转写和文字向量走 4090 经反向隧道提供的 `127.0.0.1:18790`、`127.0.0.1:18791`。

## 发布

在 cnb 的 `main` 分支页面点“发布到 stable”（可填提交，留空发布 `main` 最新提交）：`deploy/release_stable.py`
确认该提交在 `main` 上的检查已通过、`stable` 能快进过去，列出发布的提交和记忆内核是否变化，再推送 `stable`。
推送 `stable` 触发 `.cnb.yml` 的 `deploy-daw`（检查已在 `main` 上跑过，不再重跑）：`git archive` 打包 →
腾讯云 TAT 分片上传 → 在 daw 上以 root 运行 `deploy/daw/deploy.sh`。脚本先备份数据，再切换 `current`；新版本
健康检查失败会自动回到上一版；新版本升级了数据库结构时（日志里有“新版本会升级数据库结构”），旧版本打不开
升级后的数据，脚本不再自动回退，健康检查最多等 15 分钟，失败时停在新版本上，见下文“回退”。最后 `deploy/daw/check_live.py` 读 https://daw.xjjk.com/twin/ 的 `X-Twin-Release`
响应头（`git archive` 写进 `src/twin/web/RELEASE` 的提交号），不是本次提交就标红，上传中途退出这类“绿了但没切换”
的情况因此也会显示失败。部署备份只保留最近 10 份，更早的在下一次备份时删除；录音库录音和分身的原件、
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
不在办公网时，管理员点网页左下角账户头像，在菜单里打开「设置」（手机上在分身切换面板里），在「系统 → 状态」和它下面的「GPU 机器」页看：twin 每分钟检查一次两个服务（向量服务再做一次真实
向量化），显示是否正常、异常原因、最近一天的可用率和最近一次失败；记录只在进程内，twin 重启后从头记。

管理员也可以在「设置 → 模型与额度」里修改文字模型和向量模型的地址与模型名、设置或更换密钥，保存后立即生效，
不用登录 daw：密钥写入 `/data/twin/.env`（0600），只显示是否已设置；修改记录在 `/data/twin/data/system-audit.jsonl`。
管理员由 `[auth] admin_emails` 决定：写 `zhangxun@xjjk.com` 时，SSO 账号名是 `zhangxun` 或 `zhangxun@xjjk.com` 的人都是管理员
（账号名见 `journalctl -u twin` 里“SSO 登录：…（账号 …）”一行）。

向量服务停了或隧道断了，聊天退回只按关键词检索，照常回答；记忆整理的向量化那一步会失败，服务恢复后下一次整理接着做。
换向量模型后，各分身在网页启动时发现旧向量并自动重新向量化。显卡与转写（有时还有语言模型）共用，向量服务常驻约
1.6 GB 显存，每次请求后归还临时显存。

## 回退

只换回旧代码：新版本没有升级数据库结构时，把 `current` 指回上一版即可（`ln -sfn /data/twin/releases/<上一版> /data/twin/current`，
再 `systemctl restart twin`）。升级过结构的版本（部署日志里有“新版本会升级数据库结构”）上线后，旧版本启动时会报
“数据库由更新版本的 twin 写入（schema …），当前版本只支持到 …”，必须连数据一起回到部署前的备份。部署后新写的数据
（对话、你不在时、上传的资料）不会带回旧版本；它们留在挪开的目录里，确认不再需要后再删。在 daw 上以 root 执行：

```bash
systemctl stop twin
ls /data/twin/home/backups/          # 部署前那份以 -deploy 结尾，部署日志“备份完成：”后面就是它
mv /data/twin/data /data/twin/data.upgraded-$(date +%Y%m%d%H%M%S)
cp -a /data/twin/home/backups/<时间>-deploy/data /data/twin/data
ln -sfn /data/twin/releases/<上一版> /data/twin/current
systemctl start twin
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8770/api/whoami   # 200 或 401 即正常
```

`cp -a` 保留属主 ubuntu 和 0700/0600 权限；备份里录音这类文件和线上共用硬链接，复制出来会多占一份空间，先用
`df -h /data` 确认够用。不要用 `twin ops restore`：它检查的是 `twin ops` 自己装的用户服务，不认 `twin.service`。
`releases/` 只留最近 3 个版本，上一版不在时先按“发布”重新部署那个提交。回退后 `stable` 仍是新版本，修好前不要再
发布或重跑 `deploy-daw`，否则会再次升级。

## 排查

`systemctl status twin`、`journalctl -u twin -n 100`；版本在 `/data/twin/releases/`，`current` 指向在线版本。
