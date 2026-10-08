# 使用指南

```bash
twin init                     # 生成带中文注释的 twin.toml，按注释填写模型和向量服务
```

模型等后端密钥只放在环境变量里（`TWIN_LLM_KEY`、`TWIN_EMBED_KEY` 等），配置文件只写变量名。企业微信机器人在分身档案页绑定，Secret 保存在分身私有数据目录（见下文）。
可选的 `[chat_llm]` 让聊天（网页、CLI、API/MCP 与评测作答）用更快的模型，档案抽取和构建仍用 `[llm]`；未配置时聊天也用 `[llm]`，示例见 `twin.toml.example`。
外部后端按配置使用，界面如实展示出境分类；用 `twin identity show` 查看，本机转发代理需声明 `egress = "external"`。

## 网页快速开始

运行 `twin ui`，按打印的本机地址**打开页面 → 你是谁 → 形象和声音 → 添加记忆 → 聊天**。
首次填写名字和一段介绍（也可以跳过）；介绍自动保存为“自我介绍”记忆，添加的内容会自动整理。
主导航只有“聊天 / 记忆 / 关于你”。在“关于你”随时修改名字与介绍、核对我了解到的你，也可选择“回答几个问题”。
名字保存后不再显示首次引导；没有记忆时聊天页会提示先添加。

## 多个分身

手机和桌面顶栏均可点击头像与名字切换分身；列表显示记忆数，可“新建分身”或进入“管理”重命名、确认删除。
新建后自动切换并进入四步引导。每个分身的介绍、记忆、照片、声音、聊天记录和音视频上传相互独立；切换停止播放，但后台任务继续为原分身处理。
默认 `[auth].enabled = false` 保持无登录、所有人都是管理员的本机模式。启用邮箱登录后，成员只看到自己的分身，默认最多创建 3 个；管理员可管理全部分身，列表标出其他拥有者的邮箱。旧分身（含 default）归管理员。

数据根目录为 `db_path.parent`。`personas.json` 记录 ID、owner（邮箱或 null）、创建时间和默认 ID；原数据库和 `assets/`、`media-cache/`、`media-sources/`、`uploads/` 原地保留为 `default`，无需迁移。
新分身使用 `personas/p-<10位hex>/twin.db` 和同布局的私有目录。聊天记录保存在各分身的 `twin.db` 里，可搜索、重命名、删除和继续；启用登录后按账号邮箱各自私有。默认分身不能删除；有运行或排队任务的分身暂不能删除。
CLI/MCP/评测继续使用配置数据库，不新增选择参数。

## 公网部署与邮箱登录

Cloudflare Access 已移除，不读取任何 `Cf-Access-*` 身份头；应用本身是认证边界。保持服务只绑定 `127.0.0.1`，Cloudflare Tunnel 的 HTTPS 公网域名指向本机端口，并保留原 Host。用 `twin ui --allow-host twin.example.com` 接受自己的域名，不要将开发服务器或本机端口直接暴露到公网。

1. 在 `twin.toml` 配置 `[auth] enabled = true`，填写 `allowed_domains`、`allowed_emails` 和 `admin_emails`（完整示例见 `twin.toml.example`）。域名仅匹配最后一个 `@` 后的完整部分，大小写不敏感；管理员邮箱也须在允许范围内。
2. 配置 `[auth.smtp]` 的 host、port（465 SSL / 587 STARTTLS）、username、from_address、from_name。`password_env = "TWIN_SMTP_PASSWORD"` 只写变量名；通过服务进程的环境安全传入密码，不存入配置或源码。启用登录但缺少 SMTP 配置/密码时启动失败。
3. 重启服务应用配置变更。允许的用户收到 6 位验证码（10 分钟有效、5 次错误后失效）；未允许的邮箱加入等候名单，不发邮件。发送限额：每邮箱 60 秒一次、每小时 5 次，每客户端 IP 每小时 20 次（隧道使用 `CF-Connecting-IP`，否则使用连接地址）。内存限额按进程计算，部署使用单进程。

会话默认 30 天，只存于 HttpOnly、Secure、SameSite=Lax cookie（本机 HTTP 开发可非 Secure），不在 localStorage 保存 token。`<数据根>/auth.db` 以 0600 保存验证码哈希、会话哈希及去重的等候邮箱；备份时视作私有资料。所有 API/媒体需会话，写操作仍需 `X-Twin: 1`。账号菜单常驻页面，提供“退出登录”。

管理员登录后可用同源 `GET /api/admin/waitlist` 查看等候名单；放行用户就是把邮箱加入配置 `allowed_emails` 并重启，没有审批 UI。不要在启用 auth 前移除原有外层保护，也不要在公网关闭 auth。

## 记忆上传

```bash
twin persona import 问卷.md 聊天记录.csv 文章/*.md    # 自动识别类型，不用选择
twin persona import 简历.pdf 想法.docx 网页.html
twin persona note "我喜欢先核对事实，再做决定。"        # 写一段笔记
twin persona import --kind interview 访谈.txt        # 可选：明确指定类型
twin persona sources                                # 看已导入的资料
twin persona build                                  # 抽取并合并人格档案，只处理新增或变化的部分
twin persona coverage                               # 看了解到什么，还可以分享什么
```

支持 TXT、Markdown、PDF（文字层）、Word（.docx）、EPUB 电子书、HTML、CSV、JSON、SRT、VTT，自动识别文字编码（含 GBK）；每个文件最多 50 MB，扫描 PDF 暂不支持。日期默认取文件名，聊天缺失日期时取第一条日期，再回退到添加当天。需要强制类型时仍可用 `--kind`。

网页 `#/memories`（导航“记忆”）可以写一段、上传多个文件或整个文件夹，也支持最多 4 GB 的录音、播客、手机视频和屏幕录制。音视频以 8 MiB 分片断点续传；上传时保持页面打开，刷新后重新选择同一文件可继续。原件保留，ffmpeg 提取音频后由 `[asr]` 转写，带时间戳的文字自动进入普通记忆整理。未配置识别也可上传，配置后重启服务，点“重新转写”。命令/HTTP 配置见 [MEDIA.md](MEDIA.md#音视频记忆)。添加、删除后自动处理，不必点构建；可以查看分身看到的文字、记住的条数和失败重试。CLI 导入或笔记保存后，可运行 `twin persona build`，也可启动网页让它自动处理。

## 服务

```bash
twin persona chat "你怎么看远程办公？"
twin ui                                             # 本机网页：多个分身、流式聊天、保存的对话、记忆、朗读与真人视频
twin api                                            # 令牌保护的本机 HTTP API（先设置 TWIN_API_TOKEN）
twin mcp                                            # stdio MCP，供其他工具和 Agent 使用
```

API/MCP 保留高级（advanced）可选参数 `as_of`，评测也保留日期筛选；CLI 和网页聊天不提供它。
配置、接口与隐私规则见 [SERVICE.md](SERVICE.md)。

## 接入企业微信

1. 企业微信 → 工作台 → 智能机器人 → 创建，选择 **API 模式 → 使用长连接**，复制 Bot ID 和 Secret。
2. 打开 `twin ui`，切换到要接入的分身，进入 **档案 → 接入 → 绑定**，填写 Bot ID 和 Secret 后保存。不必修改 `twin.toml` 或重启服务。
3. 「接入」显示连接状态；看到「已连接」后，同事可以单聊机器人，或在群里 @ 它；语音消息也支持（企业微信自动转成文字）。可见范围在企业微信管理后台设置，请只开放给可以查看该分身记忆的同事。

在同一处点击「修改」可更换机器人或 Secret；Bot ID 不变时，Secret 留空表示保持原值。点击「解绑」并确认即可停止连接。只有分身管理者能查看或修改接入设置，公开分身的访客不能访问。

Secret 保存在该分身私有数据目录、与 `twin.db` 同级的 `channels.json` 中（0600 权限；默认分身位于数据根目录），不会返回给浏览器或写入日志。备份时视作私有凭据；删除分身时一起进入回收站，恢复后自动重连。如果机器人已绑定其他分身，恢复的分身会显示冲突，不会抢占连接。

每个机器人只能保持一条长连接，不要用同一 Bot ID 同时运行多个服务，也不能绑定到多个未删除的分身。回复沿用网页聊天的记忆检索与引用核验，聊天上下文仅保存在服务内存，重启后清空。旧配置中的 `wecom.bots` 会被忽略，请在档案页重新绑定。

## 语音与视频（可选）

在 `twin.toml` 的 `[tts]` 里配置语音后端：自托管的 MOSS-TTS-Nano（见 [deploy/tts-moss](../deploy/tts-moss/README.md)）或 Cloudflare MeloTTS（外部服务，按配置使用）。

```bash
twin media speak 回复.json --out 音频目录/            # 分段语音和清单
twin media clip 回复.json --out clip.mp4              # 形象与字幕；需系统 ffmpeg 和中文字体
twin media video 回复.json --out out.mp4              # [video] 通用 SSH 视频任务，见 docs/MEDIA.md
twin media check --out 评测目录/                      # 合成句集回听评测：字错率与延迟
```

网页上可裁剪上传本人照片（JPEG、PNG、WebP、HEIC，最大 15 MB）、录一段声音或上传录音/视频，首次引导也可设置或跳过。
照片用于聊天头像和真人视频；声音用于视频，配置 `[tts].voice_dir` 后也用于听和试听。
素材保存在各分身数据目录的私有 `assets/` 中。只有默认分身可回退到配置的本人肖像和视频驱动素材；
其他分身无照片时使用首字/VRM，无声音时使用 `[tts].voice` 预置音色，真人视频必须先上传该分身自己的照片和声音。
声音处理需系统 ffmpeg；
语音容器需将 `voice_dir` 只读挂载到 `/voices`，见 [deploy/tts-moss](../deploy/tts-moss/README.md)。

视频驱动 JSON 契约新增可选 `portrait`、`voice_ref`：本机为绝对路径，SSH 模式先 scp 到远端 home 的
`.cache/twin-assets/<sha>.<ext>` 后传相对路径。默认分身缺省时驱动沿用自己的素材，其他分身不允许省略素材，完整契约见 [MEDIA.md](MEDIA.md)。

浏览器 3D 形象可在 `[avatar]` 设置 `vrm_path` 指向本地风格化 VRM 文件（不入库）；未配置或加载失败时保留 2D 形象，见 [MEDIA.md](MEDIA.md)。
