# 本地个人分身网页：设计与接口契约

`twin ui` 默认监听 `http://127.0.0.1:8765`，`/` 是唯一的 React 前端。页面使用 HashRouter，默认 `#/chat`，无需服务端应用路径回退。`/next`、`/next/` 仅作 308 重定向到 `/`，保留书签兼容；不再提供 `/static` 或 `/next/assets`。个人资料存于本机；配置远端模型或语音服务时，请确认数据使用权限。

## 技术栈与目录

Node 22、pnpm 10.32.1、React 19、严格 TypeScript、Vite、Tailwind CSS v4、`motion/react`、Radix Dialog/Tooltip/Tabs/Switch、lucide-react、zustand、clsx/tailwind-merge、react-router HashRouter。版本锁定在 `frontend/package.json` 和 `frontend/pnpm-lock.yaml`。测试使用 Vitest、Testing Library/user-event、jsdom；检查使用 ESLint、typescript-eslint、react-hooks 和 Prettier。

```text
frontend/
├── src/
│   ├── design/       # tokens.css、motion.ts
│   ├── components/   # ui/、motion/、layout/、effects/、reactbits/
│   ├── lib/          # 同源 API、格式化与样式合并
│   ├── stores/       # 状态与可见性轮询
│   ├── features/     # chat/、playback/、jobs/、sources/、profile/、questionnaire/、identity/
│   ├── pages/        # 聊天、记忆、关于你；首次引导、可选问卷与开发画廊
│   ├── test/         # 行为、动效、可访问性及对比度测试
│   ├── App.tsx       # HashRouter 与按页 lazy 加载
│   └── main.tsx      # React 入口
├── package.json / pnpm-lock.yaml
├── vite.config.ts / tsconfig.json
├── eslint.config.js / .prettierrc.json
└── index.html
src/twin/web/static/
├── index.html
└── assets/           # 带哈希的 JS/CSS，随代码纳入版本控制
```

Vite `base: '/'`，输出到 `../src/twin/web/static`，`emptyOutDir: true` 清空整个输出目录。资源通过 `/assets/*` 提供；无 sourcemap，关闭 modulePreload polyfill。Python 包运行不依赖 Node，构建产物随包分发。缺少 index 时 `/` 显示中文提示，告知开发者运行 `pnpm -C frontend build`；API 仍然可用。

## 开发与检查

```sh
pnpm -C frontend install --frozen-lockfile
pnpm -C frontend build
uv run twin ui             # 后端默认 127.0.0.1:8765
# 另一个终端：
pnpm -C frontend dev       # 打开 Vite 打印的地址，默认 http://127.0.0.1:5173/
pnpm -C frontend typecheck
pnpm -C frontend lint
pnpm -C frontend test
pnpm -C frontend build
uv run ruff check src tests deploy
uv run ruff format --check src tests deploy
uv run mypy
uv run pytest -q
```

Vite dev server 将 `/api` 代理到 `http://127.0.0.1:8765`，改写 Host 为目标主机，保持同源客户端请求与 `X-Twin: 1`，无需放宽后端 CSP 或开启 CORS。必须先启动 `twin ui`；若更改后端端口，同时调整 `frontend/vite.config.ts` 的 proxy target。开发服务器用于热更新，正式服务使用构建产物。

CI 前端任务运行四项检查后执行 `git diff --exit-code src/twin/web/static` 和 `test -z "$(git status --porcelain src/twin/web/static)"`，同时检查跟踪文件差异及新增未跟踪产物；提交前必须同步构建结果。`.gitattributes` 将 index 与 assets 标记为生成文件。

## 布局、令牌与可访问性

AppShell 桌面侧栏可折叠，图标态带 Tooltip，活动导航使用共享 pill；小于 768px 时从顶栏打开底部抽屉，支持下拖和键盘关闭。顶栏只显示姓名与 AI 标识，不显示模型或外部服务角标；外部服务只在“关于你”中说明。状态首次读取 `/api/status`，之后可见时每 10 秒刷新，隐藏时暂停定期刷新，恢复可见后立即读取；卸载清理请求、计时器和监听。

设计令牌集中在 `frontend/src/design/tokens.css`，经 Tailwind v4 `@theme inline` 接入。使用系统字体，不加载外部字体或资产。

| 变量 | 浅色 | 深色（prefers-color-scheme） |
| --- | --- | --- |
| canvas | `#FBF8F4` | `#141311` |
| surface / surface-raised | `#FFFFFF` / `#FFFFFF` | `#201E1B` / `#2A2723` |
| border | `#E5E0D9` | `#403B34` |
| text-primary | `#292622` | `#F5F0E9` |
| text-secondary / text-tertiary | `#625C54` / `#756E65` | `#C4BCB1` / `#ABA195` |
| accent / hover / pressed | `#2563EB` / `#1D4ED8` / `#1E40AF` | `#8CB8FF` / `#A9CAFF` / `#BCD6FF` |
| on-accent | `#FFFFFF` | `#141311` |
| success / warning | `#187047` / `#8A570B` | `#7CDAA7` / `#ECC079` |
| danger / info | `#B72E38` / `#2463AE` | `#FF9DA3` / `#8CB8FF` |

文字、强调及状态色在三种表面上由单元测试检查 WCAG AA ≥ 4.5:1。圆角 8/12/16/20px/full，字号 12/13/14/16/20/24/32px，正文 14px、行高 1.75；阴影和半透明侧栏也由令牌控制。状态色只表达状态。

UI primitives 包含 Button、IconButton、Card、Input、自动增高且 IME 安全的 Textarea、Field、Badge、Meter、Skeleton、EmptyState、Table、Tabs、Switch、Dialog、ConfirmProvider、Toast 和 Tooltip。Radix 提供焦点约束、键盘操作与 ARIA；确认默认聚焦取消，关闭后恢复原入口。通知只用 polite live region，不抢焦点。

所有 AI 标签及免责声明来自 `/api/status.labels`（explicit/disclaimer/chat_notice）或媒体 API 的标签字段，不在前端硬编码或兜底复制。未加载时显示 Skeleton/留空。React 按文本渲染服务端内容，不执行用户 HTML，不输出个人文本日志。

## 动效与 React Bits wrappers

`frontend/src/design/motion.ts` 统一弹簧及退出时长：

| 预设 | stiffness / damping | 用途 |
| --- | --- | --- |
| snappy | 520 / 38 | 按钮、开关 |
| gentle | 260 / 30 | 页面、列表、对话框、进度 |
| bouncy | 380 / 18 | 点缀反馈 |
| layout | 420 / 40 | 重排、侧栏、导航与通知 |

quick/page/dialog 退出为 120/160/180ms，默认 crossfade 150ms。`useMotionPreset()` 实时响应系统减少动态效果：关闭位移、缩放、拖动、共享布局、shimmer 与眨眼，仅保留淡入淡出/立即更新。回放偏好变化会暂停播放；减少动态效果下文字不自动推进，口型限于 0/1，朗读仍可按音频结束推进。

应用仅从 `components/effects/` 导入 wrapper，ESLint 禁止业务代码直接导入 `components/reactbits/`。上游 TypeScript + Tailwind 源码、来源版本及 **MIT + Commons Clause** 许可保存在 `frontend/src/components/reactbits/NOTICE.md`；不作为独立组件库销售或再分发。GSAP 仅供 AnimatedContent/ScrollTrigger 使用，业务页按具体模块导入，避免不必要加载。全部资源本地打包，无 CDN。

| wrapper | 上游/适配 | 行为与减少动态效果 |
| --- | --- | --- |
| ReplyReveal | BlurText 语义适配 | Intl.Segmenter 分词，约 1.2s 内揭示；减少动态效果立即显示全文 |
| ThinkingLabel | ShinyText | 柔和高光；减少动态效果静态文字 |
| MetricNumber | CountUp | 0.6s 计数、预留宽度；减少动态效果立即显示最终值 |
| MessageList | AnimatedList | 稳定 ID 语义列表，禁用全局方向键/Tab 监听及缩放；减少动态效果无入场动画 |
| SpotlightAction | SpotlightCard | 键盘可用的语义按钮；减少动态效果关闭光斑 |
| FlowStepper | Stepper | 可聚焦步骤按钮、中文导航；减少动态效果直接切换 |
| SectionReveal | AnimatedContent | 首次滚动进入 8px/250ms 揭示；减少动态效果不创建滚动触发器 |

回复动画文本/数值使用完整的 visually hidden 文本，视觉动态层 `aria-hidden`，避免逐词逐帧播报。ThinkingLabel 只渲染一份可访问文字，避免重复的处理提示。`#/gallery` 提供所有 UI、Motion 与七个 wrapper 的可交互示例及重播入口，不填充虚构业务数据。

## 页面

| Hash 路由 | 功能 |
| --- | --- |
主导航恰好三个入口：聊天、记忆、关于你。

| `#/chat`（默认） | 多轮聊天、依据、回放、朗读与导出；无日期输入或资料截止提示 |
| `#/memories` | 写一段、上传文件/文件夹、自动记住、文字预览和删除 |
| `#/about` | 编辑名字与介绍、形象/音色、我了解到的你、还想多了解、外部服务 |
| `#/sources` | 重定向至 `#/memories`，兼容旧书签 |
| `#/persona`、`#/identity` | 重定向至 `#/about` |
| `#/questionnaire` | 可选问卷，关于你中的“回答几个问题”链接；不在主导航中 |
| `#/gallery` | 开发组件与动效画廊，仅通过 URL 访问 |

首次读取 identity 和 status：没有用户保存的名字（name_source=config）且没有记忆时，显示全页引导，不显示侧栏。FlowStepper 的三步为“你是谁”（名字与一段介绍、示例占位符）、“添加记忆”（嵌入记忆页添加区）、“开始聊天”。步骤内容有 p-5 / sm:p-6 内边距，两种动效模式均使用中文按钮，最后只保留一个“开始聊天”动作。第一步保存成功后才能继续；记忆可以不添加。可用“跳过”直接进入聊天，跳过会保存当前配置名（最多前 20 字），不添加介绍。保存名字后，即使删除全部记忆或刷新页面也不再出现引导；已有记忆的用户也不显示。开发画廊不受引导阻挡。

名字保存到 p_meta 的 identity:name，介绍保存到 identity:about；有效名字为用户保存值，否则为配置 target_name。用户保存的名字也参与说话人匹配，配置名字与别名仍有效。介绍设定或变化时，事务内替换标题为“自我介绍”的笔记，并触发自动处理；清空介绍删除旧笔记。单独改名字不重复添加笔记。

聊天使用 MessageList、最新回复的 ReplyReveal、ThinkingLabel、Textarea；Enter 发送、Shift+Enter 换行，IME 安全。完成的往返仅保存在本标签页 sessionStorage；失败恢复输入并可重试，清空需确认。进入/发送时检查 stale，空对话与无记忆状态的添加入口指向 `#/memories`。界面不发送截止日期，API 仍兼容 as_of。没有档案时直接显示友好的弃权回复（200），不创建聊天任务；正常聊天任务每秒轮询，离页取消等待和请求，不取消服务端任务。

PlaybackDialog 使用 `features/playback/usePlayback.ts` 和 `Avatar.tsx`。先展示开头提示，再逐句呈现原回答，弃权不讲述回答；引用按脚本顺序解析。Space 播放/暂停、左右键切句、Escape 关闭并返回入口；聚焦按钮时 Space 保持原生行为。音频有序分片由 ended 推进，暂停保留时间，口型按 currentTime × lipsync.fps 取值；暂停、等待、纯文字播放时闭嘴。形象只使用 API 的预置调色板、四级口型和常驻标签，无图片输入。关闭释放音频、计时器、rAF、请求及下载 URL；语音失败显示中文 detail 并退回文字，可重试合成。

可选 3D 预览由 `features/avatar/AvatarPreview.tsx` 统一选择并通过 React.lazy 加载 `Avatar3D.tsx`，props 为 `{url, mouth, speaking, label, onFallback}`。组件使用 GLTFLoader / VRMLoaderPlugin、头骨摄像机取景、令牌三点光、临界阻尼口型和头动、眨眼/lookAt 与模型 SpringBones；AI 标签常驻，署名来自模型元数据。回放复用既有口型驱动，关于你页保持闭口，画廊“形象对比”并排展示 2D/3D，共享演示口型轨和重播按钮。离屏/隐藏停止 rAF，卸载销毁渲染器和模型资源；失败回退 2D，MP4 导出仍为 2D。CSP 仅 img-src 增加 blob: 以加载内嵌纹理；配置与许可注意事项见 [MEDIA.md](MEDIA.md#浏览器-3d-形象v1)。

记忆页（`Memories.tsx`）有“写一段”“上传文件”“上传文件夹”三个标签，不选择类型或日期。支持 .txt/.md/.pdf/.docx/.html/.htm/.csv/.json/.srt/.vtt，每文件最多 50 MB；PDF 只读文字层，不做 OCR。文件夹以相对文件名发送，服务端只保存 basename，隐藏文件和未知格式显示跳过原因。添加后提示“已添加，正在记住…”。

记忆列表用 MessageList 展示标题、可选日期（无日期不显示前导分隔符）、笔记/文档/聊天记录/问卷/访谈和状态：正在记住…（ThinkingLabel）、已记住 N 条、没找到关于你的内容、处理失败＋重试。“查看”打开只读 Dialog，展示隐私视图的前 20000 字；“删除”通过 ConfirmDialog 确认，成功后自动重新处理。页头显示精简处理指示，非 idle 时每 2 秒轮询 processing 与列表；只在 last_error 存在时显示小的“重新处理”，无构建卡片或构建汇总。离页清理请求和计时器。

关于你页（About.tsx）用名字与介绍的内联表单调用 PUT identity，预览现有 3D/2D 形象并显示预置音色。"我了解到的你"按九个口语主题分组：经历与身份、看重什么、怎么做决定、怎么思考、擅长什么、说话方式、和人相处、最近在关注、生活与喜好。每条显示表述和“依据”折叠引用，用“对 / 改一下 / 不对”调用原 review API，状态显示待确认 / 已确认 / 已修改 / 已否定；失败回滚并保留修改草稿。隐藏内部编号、比例、等级与来源矩阵。“还想多了解”从 coverage suggestions 映射为主题建议，去重后最多五条，链接到记忆。不再保留 Profile、Identity 页面和 CoverageOverview/虚拟档案列表。

问卷按 API section 分组，用 FlowStepper 导航到首个未答组；可跳过题清空答案，空答案不计已答。草稿 800ms 防抖、版本化串行 PUT；提交等待保存成功，需确认且说明替换、授权与测试题留出规则。离页完成待写草稿，小于 60KB 时尽力 keepalive，不另存个人答案。仅未保存且写入中的离开才警告。重测只恢复答案和提交状态，无评分、不构建。

关于你独立读取 identity 与 media capabilities；预览失败不影响名字编辑。小的“外部服务”区域读取 status.egress，仅列实际配置且外部的服务，用“大模型 / 向量 / 朗读 / 语音识别 / 视频生成 / 回答检查”和主机描述，不显示提供方 ID；不展示技术分类表。3D 署名仍来自模型元数据；形象闭口、减少动态效果不眨眼。

## API 与任务契约

客户端只接受同源 `/api/`，非 GET 请求带 `X-Twin: 1`；JSON/form 编码，错误为含 status/detail 的 ApiError，保留中文 detail。HTML 导出按 text 读取，错误仍解析 JSON。

| 方法/路径 | 契约 |
| --- | --- |
| `GET /api/status` | target_name、counts、llm/embed、egress（仅实际配置且外部，评委 kind=judge）、labels；无数据库路径或密钥 |
| `GET /api/jobs`、`/api/jobs/{id}` | 状态、时间、进度日志、阶段、计数、里程碑、结果/错误 |
| `GET /api/persona/sources` | 保留原字段，追加 detected_kind/label、status（processing/remembered/nothing_found/failed）、remembered；不含 preview |
| `GET /api/persona/sources/{id}/text` | text/plain，隐私视图，最多 20000 字，不存在 404 |
| `POST /api/persona/notes` | `{text: str, title?: str}`，text 1–20000 字，空白拒绝；默认标题“笔记 YYYY-MM-DD HH:MM”，当天日期 |
| `GET /api/persona/processing` | `{state: idle/queued/running, job_id?, last_finished_at?, last_error?}` |
| `GET /api/persona/state` | `{stale, built_at, sources_changed_at}` |
| `POST /api/persona/import` | multipart files；kind 可选（默认逐文件自动识别），显式 kind/date 兼容；返回 imported/skipped 原因，逐文件追加 detected_kind 和 detected_kind_label |
| `DELETE /api/persona/sources/{id}` | 删除记忆并自动重新处理，返回 deleted |
| `POST /api/persona/build` | 构建与向量更新，202 job_id |
| `GET /api/persona/items?include_rejected=false` | 条目、细项/维度、证据场合数 |
| `POST /api/persona/items/{id}/review` | confirmed/edited/rejected/unreviewed；edited 必须非空 |
| `GET /api/persona/coverage?as_of=...` | 完成度、来源矩阵、等级标签、分类版本、建议 |
| `POST /api/persona/chat` | messages（≤40 条、每条≤4000 字、最后非空 user）、as_of；有档案时 202 job_id，结果 ChatReply + cited；无档案时 200 直接返回友好弃权回复 |
| `GET /api/persona/questionnaire?round=initial/retest` | 问题、答案、提交状态 |
| `PUT /api/persona/questionnaire/draft` | round、answers，保存草稿 |
| `POST /api/persona/questionnaire/submit` | 初次导入并尝试构建；重测仅记录 |
| `GET /api/identity` | name/aliases/about/name_source（config 或 user）/voice/avatar/egress；name 是有效名字；无授权账本 |
| `PUT /api/identity` | X-Twin: 1；`{name, about}`；去除首尾空白后名字 1–20 字，介绍 ≤200 字；返回完整 identity；介绍变化会替换“自我介绍”笔记并自动处理 |
| `GET /api/media/capabilities` | available/backend/label/languages/audio_formats/avatar、`video: {available: bool}`；avatar_model 为 `{format: "vrm", url: "/api/media/avatar.vrm"}` 或 null |
| `GET /api/media/avatar.vrm` | 配置的本地 VRM 流，model/gltf-binary、no-cache；未配置中文 JSON 404 |
| `POST /api/media/script`、`/export`、`/audio`、`/clip` | `{kind: "chat_reply", answer: ChatReply, persona_name?: str}` |
| `GET /api/media/audio/{name}` | SHA-256 命名 WAV/MP3 分片，验证目录边界 |
| `POST /api/media/video` | 与 clip 相同的请求体，返回 `{job_id}`；弃权回答 400，未配置 503 |
| `GET /api/media/video/jobs/{job_id}` | 视频专用 JobManager 的任务状态；done 结果 `{file, duration_s, warnings}`，重启清空 |
| `GET /api/media/video/{name}` | 64 位十六进制文件名的 MP4 流，校验目录与符号链接；video/mp4、X-AI-Generated: twin、private/no-store；不存在 404 |

任务状态 queued/running/done/failed，日志最近 500 行，里程碑另存；人格构建互斥，聊天有并发及待处理数量限制。任务仅驻留内存，重启清空；UI 启动时发现 stale 会重新排队。导入、笔记、删除和介绍变化后约 3 秒防抖自动处理；运行中发生多次变化只排一个后续处理，复用 run_persona_build 和 JobManager。完成时间与错误持久化，失败可以 POST build 重试。stale 表示来源比档案新，不阻止聊天。构建结果包含 items_added/changed/removed、facets_changed 和 facet_diffs；失败不当作零分答案。

回放面板在 HTML“导出”旁提供“导出视频”：显示加载状态，下载 `twin-media.mp4`，失败显示中文 toast；标识仍只来自 API。`POST /api/media/clip` 同步返回 `video/mp4`，`Content-Disposition: attachment`、`X-AI-Generated: twin`；复用现有安全与请求体限制，脚本最多 100,000 字符、视频最多 600 秒。需系统 ffmpeg 与中文字体（见 [MEDIA.md](MEDIA.md)），临时 MP4 在响应完成后清理。

配置 `[video]` 后，回放面板另显示“生成真人视频”（弃权时隐藏）。先确认“在本人 GPU 主机上生成，通常需要几分钟”，再用 JobProgress 展示串行后台任务；每秒轮询视频专用任务接口，关闭面板取消请求和计时器，不取消远端任务。完成后内联 `<video controls>` 及下载链接，超阈值分段显示“第 N 句回听与原文有出入”（开头提示单独提示），不展示识别文本。标签仅从 API 读取。远端 JSON 契约和本地永久标识见 [MEDIA.md](MEDIA.md#34-本人视频通道v2)。

脚本与独立 HTML 导出不调用模型，音频与视频只调用配置合成器。导出自包含、无可执行脚本或外部资源，文本及 inert JSON 安全转义，含 AI 标识和来源指纹；指纹不是签名。音频存于数据库目录的 media-cache，GET 为 `private, no-store`。语音不可用/拒绝/超时/过长为 503/502/504/413，不回显服务消息。

## 安全与服务路由

`web.app.create_app` 懒创建后端，测试可注入离线工厂。默认仅接受 localhost、127.0.0.1、[::1] Host，显式 `--host/--allow-host` 可扩展；公网必须另加认证。所有非 GET/HEAD 请求要求 `X-Twin: 1`，不开 CORS，WebSocket 一律关闭（1008）。JSON 上限 1 MB，上传总上限 100 MB、500 文件，单文件 50 MB；上传只取 basename，内存解析，不读客户端指定的服务器路径。

所有响应（页面、资源、重定向及错误）保留以下安全头：

- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `Referrer-Policy: no-referrer`
- `Cross-Origin-Resource-Policy: same-origin`
- `Content-Security-Policy` 原值：

```text
default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'
```

页面无内联脚本、外部 src/href 或 CSS url 资源。JS/CSS MIME 显式注册，避免 nosniff 拒绝脚本。API 和 5xx `Cache-Control: no-store`，页面、资源及重定向 `no-cache`；媒体下载保留 `private, no-store`。只暴露 `/` 的 index 与 `/assets`，StaticFiles 禁止跨目录路径和外部符号链接。未知 API 返回中文 JSON 404，不回退 index；未知非 API 路径也不做 SPA 回退。

错误返回 `{detail}`：400 参数/资料前置条件，403 安全检查，404 不存在，409 构建冲突（带 job_id），413 太大，429 待处理过多，503 后端配置错误，500 内部错误。错误隐藏家目录路径，不记录个人文本。`tests/test_web_frontend.py` 检查构建 index、全部资源 MIME/安全头、本地资源约束、书签重定向、缺少构建的提示及路径边界；页面行为由 `frontend/src/test/` 覆盖。
