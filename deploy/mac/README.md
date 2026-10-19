# 在 Mac 上部署 twin

> 常驻部署（可选）；本地验证请看 [docs/LOCAL_DEV.md](../../docs/LOCAL_DEV.md)。

需要 Apple Silicon、macOS 14+ 和已安装的 Homebrew。P2 从当前仓库构建 wheel；发布下载/升级在 P3，算力包安装在 P4。默认开启文字聊天和会议录音转写（安装脚本运行 `twin compute install asr-funasr`，已有模型直接复用，失败不阻塞安装），可托管网页和备份；朗读真人音色、认人和口型视频默认关闭，按需开启，不会自动安装。

```bash
# 在仓库中先查看将执行的步骤，不安装软件、不写文件、不注册服务
./deploy/mac/install.sh --dry-run

# 安装依赖、构建 wheel、创建版本 venv、生成配置、注册并启动用户服务
./deploy/mac/install.sh
```

脚本不会自动安装 Homebrew、执行 curl|bash 或 sudo。已存在的配置和 env 不会覆盖；同一版本同一 wheel 可重复运行。相同版本的 wheel 内容改变时会拒绝覆盖已有 release，须先调整版本。依赖由 `uv export --frozen` 导出带哈希的锁文件，再用 `uv pip install --require-hashes` 安装。

## 目录与配置

| 内容 | macOS 默认位置 |
| --- | --- |
| 应用、算力、模型、数据、备份 | `~/Library/Application Support/twin/` |
| 应用版本 | `releases/<version>/venv/`，`current` 指向所选版本 |
| 配置 | `~/.config/twin/twin.toml` |
| 密钥 | `~/.config/twin/env`，权限必须为 0600 |
| 服务 | `~/Library/LaunchAgents/ai.twin.*.plist` |
| 日志 | `~/Library/Logs/twin/*.log` |

Linux 使用 `~/.local/share/twin/` 和 `~/.config/systemd/user/twin-*.service`/`.timer`。`TWIN_HOME` 覆盖应用、配置、日志和数据目录，服务文件仍默认写入 `~/Library/LaunchAgents` 或 `~/.config/systemd/user`，以便系统自动加载。测试须另设 `TWIN_SERVICE_DIR` 到临时目录来隔离服务文件；真实服务控制仍需显式执行 `twin ops start` 等命令。`TWIN_ENV_FILE` 可单独指定环境文件。

命令行入口先加载 env，再读取配置；选择顺序为显式 `TWIN_ENV_FILE` → 当前目录 `./.env`（与 `./twin.toml` 同时存在时）→ 部署目录 env，只选一个文件，不合并，也不会覆盖进程已有环境变量。文件权限必须为 0600。只支持 `KEY=VALUE`、注释及单/双引号，不支持 `export`、变量替换或命令执行。错误只显示行号和变量名，不显示值。可用编辑器填写 `TWIN_LLM_KEY`，以及实际启用后端需要的 `TWIN_EMBED_KEY`、`TWIN_TTS_KEY`、`TWIN_ASR_KEY`、`TWIN_SMTP_PASSWORD`。

CLI 配置优先级：`--config` → `TWIN_CONFIG` → 当前目录 `twin.toml` → 部署目录的配置。安装后的可执行文件是 `~/Library/Application Support/twin/current/venv/bin/twin`，可将该 `bin` 目录加入自己的 PATH。

```bash
twin init --profile mac-unified  # 默认写入部署配置目录，不覆盖现有配置
twin init --profile split        # 保留现有模板与远端配置方式
twin init --profile minimal      # 只生成 LLM/embed 基础配置
```

`mac-unified` 生成文字聊天所需的 `[llm]`、`[embed]` 和数据路径；安装脚本随后运行 `twin compute install asr-funasr` 写入 `[asr]`。转写未开启时 doctor 显示 ✗；朗读、认人和视频未开启时显示“未开启（可选）”，不算失败，网页隐藏对应播放、试听和真人视频入口，可按 [媒体配置说明](../../docs/MEDIA.md) 开启。

## 托管服务与自检

```bash
twin ops install-services
twin ops start
twin ops status
twin ops logs web
twin ops restart web
twin doctor                # 检查本机状态与 TCP 连通性，不调用模型
twin doctor --probe        # 才会调用启用的 LLM、向量、TTS、ASR，可能产生费用
```

默认服务只有 web（8765、仅监听 loopback）和每日 04:00 的备份。日志命令显示最近约 16 KiB；日志可能包含运行诊断，分享前请自行检查。macOS 的状态显示已加载/未加载；定时服务不需要一直运行。首次配置尚未填写时 doctor 返回非零，这是待配置提示。

可选配置：

```toml
[ops]
web_port = 8765
allow_hosts = ["twin.example.com"]
# 必须先自行配置 Cloudflare Tunnel 与凭据；命令只写路径和参数，不放 token。
# tunnel_command = ["/opt/homebrew/bin/cloudflared", "tunnel", "run", "your-tunnel-name"]

# 仅为已安装的 server 类算力包添加绝对命令；P4 再提供包安装与服务清单。
# [ops.compute_services]
# tts-router = ["/absolute/path/to/server", "--port", "8004"]

# P3 提供 upgrade 命令后才启用；这里只预留每日 04:30 的服务渲染。
# [upgrade]
# channel = "stable" # stable / canary / off，默认 off
```

改服务配置后重新执行 `install-services`，macOS 还需 `stop` 再 `start` 重新加载 plist（`restart` 仅 kickstart 已加载的配置）。删除服务配置项前先用旧配置停止该服务；P2 不会自动清理不再列出的旧单元。

公网访问前必须配置 `[auth] enabled = true`（企业 SSO，或邮箱验证码加 SMTP），域名加入 `allow_hosts`，详见 [使用指南](../../docs/GUIDE.md#团队部署与登录)。隧道直接执行配置的 cloudflared 命令；其凭据使用 cloudflared 自己的文件配置。

## 备份与恢复

```bash
twin ops backup
twin ops backup --reason migrate
twin ops stop
twin ops restore /absolute/path/to/backups/<snapshot>
twin ops start
```

数据根为配置数据库的父目录。每个 `.db`（包含各分身的 `twin.db`、`auth.db`）用 SQLite online backup，其他文件复制；包含分身注册表、接入配置、素材、原件、已完成上传和回收站。跳过 `media-cache/`、`.part`、SQLite WAL/SHM 侧文件。备份配置文件，但不备份 env、应用、算力或模型。文件为 0600、目录为 0700。

保留最近 7 份 `daily` 快照；`pre-upgrade-*` 快照保留 30 天；`migrate` 等手工命名快照不自动删除。不同数据库各自一致，在线复制期间跨库和文件之间不保证同一时刻；需要整站静止快照时先停止服务。

恢复需要服务管理器明确确认所有配置中的服务已停，无法读取状态时拒绝恢复。systemd 同时检查定时器和正在执行的任务。**恢复会替换整个数据目录和配置**，清除备份之后新增的数据；可先额外备份一次。快照先暂存并检查 SQLite 完整性，再替换。迁移到另一台机器后须检查配置中的绝对路径，并在开启新实例前停止原来的企业微信机器人连接。

## Mac 常驻注意事项

按需手动执行 `sudo pmset -c sleep 0`，并在系统设置开启“断电后自动重启”。LaunchAgent 需要该用户已登录；FileVault 机器重启后必须先登录一次。doctor 会读取 `pmset -g` 给出建议，不修改电源设置。
