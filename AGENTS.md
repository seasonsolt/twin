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

   不要加 `--demo`，除非用户明确想先看虚构示例。首次运行会同步依赖，用 Homebrew 安装 ffmpeg 和 Ollama，安装录音转写包 `asr-funasr`（模型约 2.0 GiB，本机已有则复用），并在 Ollama 里下载向量模型 bge-m3（约 1.2 GB），可能需要几分钟。Claude Code 桌面版也可以用 `.claude/launch.json` 里的 `twin-local` 启动预览。
5. **判断结果**：
   - 输出出现 `网页界面：http://127.0.0.1:<端口>` 后，访问该地址返回 200 即成功。把地址告诉用户，并说明下一步：在网页里按引导填写名字和介绍，添加会议录音或其他资料，转写后勾选属于自己的说话人，然后就可以聊天。端口被占用时会自动顺延。
   - 输出“尚未配置文字聊天模型”：按提示补齐后重新运行。
   - “环境自检”里的 ✗ 不会阻止启动；转写安装失败只影响录音转写，文字聊天照常可用。bge-m3 启用失败时检索退回 hashing（只按字面匹配），把脚本输出的原因告诉用户。
6. **停止与更新**：停止时结束后台进程。更新时先停止再运行 `./scripts/local-up.sh`：`stable` 分支会自动更新到最新稳定版，数据库迁移和记忆内核重新整理自动完成。

完整说明见 `docs/LOCAL_DEV.md`。

## 默认能力

文字聊天、会议录音转写和按语义检索（本机 Ollama 的 bge-m3，失败时退回 hashing）默认开启；朗读真人音色和口型视频默认关闭，开启方法见 `docs/MEDIA.md`。

## 打磨记忆内核与发布

- 同事运行 `stable` 分支；内核在 `main` 上迭代，确认后运行 `./scripts/release-stable.sh` 发布（检查通过后只快进 `stable`）。
- 修改抽取/合并提示词、输出结构（`persona/profile.py`）或维度分类（`persona/dimensions.py`）时，必须同时提升 `persona/kernel.py` 的 `PROMPT_VERSION` / `TAXONOMY_VERSION` 并记录新指纹，否则 `tests/test_kernel.py` 失败；不提升版本，同事已有的记忆不会按新内核重新整理。
- 数据库结构变化只能在 `persona/store.py` 的 `_MIGRATIONS` 末尾追加；迁移和新内核整理前会自动快照，回退见 `docs/LOCAL_DEV.md#回退记忆内核`。

## 开发约定

- 检查：改动过程中运行 `uv run python scripts/check.py`，只跑受影响的测试（pytest-testmon 按代码改动挑选；改了前端时才跑前端检查和构建）。提交前运行一次 `uv run python scripts/check.py --full`，与 CI 一致。改了前端时一起提交 `src/twin/web/static`。
- 密钥只放在环境变量或 `.env` 里，配置文件只写变量名。`twin.toml`、`.env`、`data/` 不入 git。
- 不要提交密钥、本机路径、个人资料或会议内容。
