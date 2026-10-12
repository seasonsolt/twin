# twin · 给 AI 助手的说明

## 用户说“部署它 / 跑起来 / 启动”

默认指**本机本地启动**：在仓库里运行，数据在 `data/`，不注册常驻服务。只有用户明确要“常驻 / 开机自启 / 长期运行”时，才用 `deploy/mac/install.sh`：先运行 `--dry-run` 给用户看，确认后再执行，说明见 `deploy/mac/README.md`。

1. **前置**：Apple Silicon Mac。缺 uv 时运行 `brew install uv`；没有 Homebrew 时请用户按 https://brew.sh 自行安装，不要替用户安装。
2. **问两项非敏感设置**：OpenAI 兼容服务地址（`base_url`，通常以 `/v1` 结尾）和模型名。`./twin.toml` 的 `[llm]` 已经填好时跳过。
3. **密钥由用户自己填写**：不要让用户把密钥发到对话里，也不要替用户写入。请用户在 `./.env` 填写 `TWIN_LLM_KEY=...`（第 4 步首次运行时从 `.env.example` 生成，权限 0600），或在用户自己的终端运行一次 `./scripts/local-up.sh` 按提示输入（输入不显示）。服务不需要密钥时可以写 `TWIN_LLM_KEY=none`。
4. **后台启动**：脚本最后会在前台运行网页、不会自行退出，所以必须放在后台运行：

   ```bash
   ./scripts/local-up.sh --no-open --base-url <URL> --model <NAME>
   ```

   不要加 `--demo`，除非用户明确想先看虚构示例。首次运行会同步依赖，用 Homebrew 安装 ffmpeg，并安装录音转写包 `asr-funasr`（模型约 0.9 GiB，本机已有则复用），可能需要几分钟。Claude Code 桌面版也可以用 `.claude/launch.json` 里的 `twin-local` 启动预览。
5. **判断结果**：
   - 输出出现 `网页界面：http://127.0.0.1:<端口>` 后，访问该地址返回 200 即成功。把地址告诉用户，并说明下一步：在网页里按引导填写名字和介绍，添加会议录音或其他资料，转写后勾选属于自己的说话人，然后就可以聊天。端口被占用时会自动顺延。
   - 输出“尚未配置文字聊天模型”：按提示补齐后重新运行。
   - “环境自检”里的 ✗ 不会阻止启动；转写安装失败只影响录音转写，文字聊天照常可用。
6. **停止与更新**：停止时结束后台进程。更新时先停止，再运行 `git pull && ./scripts/local-up.sh`，数据库迁移和记忆内核重建会自动完成。

完整说明见 `docs/LOCAL_DEV.md`。

## 默认能力

文字聊天和会议录音转写默认开启；朗读真人音色和口型视频默认关闭，开启方法见 `docs/MEDIA.md`。

## 开发约定

- 检查：`uv run ruff check src tests deploy && uv run mypy && uv run pytest -q`。改了前端时运行 `pnpm -C frontend build`，并一起提交 `src/twin/web/static`。
- 密钥只放在环境变量或 `.env` 里，配置文件只写变量名。`twin.toml`、`.env`、`data/` 不入 git。
- 仓库是公开的：不要提交内部主机名、域名、本机路径或任何个人资料。
