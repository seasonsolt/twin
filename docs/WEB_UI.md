# 本地个人分身网页：设计与接口契约

`twin ui` 默认监听 `http://127.0.0.1:8765`，页面不加载外部资源。个人资料存于本机；配置远端模型或语音服务时，请确认数据使用权限。

## 页面

| 路由 | 页面 |
| --- | --- |
| `#/chat`（默认） | 和分身聊天，查看依据、播放与导出回答 |
| `#/questionnaire` | 建档问卷、草稿、提交与重测 |
| `#/persona` | 人格档案、条目审核、完成度与采集建议 |
| `#/sources` | 记忆资料导入、删除与人格构建 |
| `#/identity` | 身份：名字、预置音色与形象、出境状态（只读） |

顶栏显示目标姓名、资料/条目数量及模型后端。所有生成内容均标注模拟性质，不代表本人意见。

## 工厂、安全与任务

- `web.app.create_app(settings, *, llm_factory=None, embedder_factory=None, synthesizer_factory=None, allowed_hosts=())`；后端懒创建，测试可注入离线实现。
- 默认仅接受 localhost、127.0.0.1、[::1] Host；`twin ui --host/--allow-host` 可显式扩展。公网使用必须另加认证。WebSocket 一律关闭，代码 1008。
- 所有非 GET/HEAD 请求必须带 `X-Twin: 1`；不开 CORS。JSON 请求体上限 1 MB；`POST /api/persona/import` multipart 上限 100 MB、500 文件。
- 上传仅取 basename，解析内存中的文件内容，不落地到任意上传路径。支持问卷、聊天、访谈、文档、他人记述及通用转录语料；转录支持 TXT/MD/SRT/VTT/JSON，日期由参数、文件名或 JSON 提供。
- 响应带 nosniff、DENY、同源资源策略和 CSP；API 及 5xx 为 `no-store`，静态文件 `no-cache`。错误隐藏家目录路径。
- 请求及任务各自打开 `PersonaStore` 并关闭。人格构建互斥；聊天任务有并发和待处理数量限制。任务仅驻留内存，重启后清空，不自动续跑。
- 任务提交返回 `202 {job_id}`；`GET /api/jobs` 与 `/api/jobs/{id}` 提供状态、时间、日志、阶段、计数、里程碑、结果或错误。状态为 queued/running/done/failed；日志最近 500 行，里程碑另存。失败计数不能当作零分答案。

## 个人服务 API

| 方法/路径 | 契约 |
| --- | --- |
| `GET /api/status` | target_name、counts.sources/items、llm/embed 后端状态；不含数据库路径或密钥 |
| `GET /api/persona/sources` | 保持列表形状；来源元数据、标签、证据类别，追加 expressions_total/target/others、items_supported、facets（facet_id/name）、contributes_nothing、build_status |
| `GET /api/persona/state` | `{stale, built_at, sources_changed_at}`；时间为 ISO 字符串或 null |
| `POST /api/persona/import?kind=...&date=...` | multipart `files`；返回 imported/skipped |
| `DELETE /api/persona/sources/{id}` | 删除资料，返回 deleted |
| `POST /api/persona/build` | 构建人格并更新向量，返回 job_id |
| `GET /api/persona/items?include_rejected=false` | 条目、细项/维度、证据场合数 |
| `POST /api/persona/items/{id}/review` | status=confirmed/edited/rejected/unreviewed；edited 必须非空 statement；statement/note 上限 1000 字 |
| `GET /api/persona/coverage?as_of=...` | 细项、维度、来源矩阵、等级标签、分类版本与采集建议 |
| `POST /api/persona/chat` | messages（最多 40 条，每条 4000 字，最后为非空 user）、as_of；返回 job_id；结果为 ChatReply 加 cited 展示字段 |
| `GET /api/persona/questionnaire?round=initial/retest` | 问题、答案与提交状态 |
| `PUT /api/persona/questionnaire/draft` | round、answers；保存草稿 |
| `POST /api/persona/questionnaire/submit` | 初次提交导入问卷并尝试构建；重测仅记录，不进入建档证据 |

资料页每份来源显示原话（本人/他人）数量、当前未拒绝条目的支撑数量与细项名称；原话数量含留出的测试回答，证据按 expression_id 关联来源，每条档案对同一来源只计一次。`build_status` 为 `not_built|remembered|no_items`；新导入/替换而未完成构建显示“尚未构建”，成功构建无条目显示“构建后未产生档案条目”。`contributes_nothing` 表示当前支撑条目为零。

构建任务 result 保留已有字段，追加 `facet_diffs: {facet_id: {added, changed, removed}}` 和总计 `items_added/items_changed/items_removed/facets_changed`。资料页与问卷构建结果显示总计及有变化的细项；不输出条目文本。零变化的已合并细项仍可出现在 facet_diffs 中。

`stale` 在 sources_changed_at 晚于 built_at，或存在来源但没有 built_at 时为 true。资料页在构建按钮旁、聊天页在输入区上方显示“资料有变化，尚未重新构建；档案和聊天仍基于上次构建”；聊天不因此被阻止。导入、删除及成功构建后刷新资料摘要与状态；聊天进入或发送时检查状态。

错误返回 `{detail}`：400 参数/资料前置条件，403 安全检查，404 不存在，409 构建冲突（带 job_id），413 太大，429 待处理过多，503 后端配置错误，500 内部错误。

## 身份

`#/identity` 只读：显示配置中的名字、别名、预置音色、预置形象，以及各后端的出境状态（类型、提供方、主机、本机/外部、声明/推断）。页面和顶部状态栏如实标出配置后端是本机还是外部，不再展示授权状态。本人声音复刻与照片驱动形象不支持（由配置校验保证）。细项是否采集由问卷推导，见人格档案页的“未授权”标记。

- `GET /api/identity` 返回 `{name, aliases, voice, avatar, egress}`；`egress` 每行 `{kind, provider, host, external, declared}`，含评委；仅返回主机，不返回端点路径、查询参数或密钥。

## 播放、语音和导出

- persona 聊天气泡提供播放入口，传入完整 `ChatReply`（附加的 cited 展示字段不进入指纹）。播放面板常驻 `AI 合成 · 模拟推演，不代表本人意见`，先显示开头提示，再逐句呈现原回答。弃权只出提示，不讲述回答。
- 播放/暂停、逐句切换及导出可用键盘操作；Space 切换播放，左右方向键逐句切换，Escape 关闭并返回入口。系统减少动态效果时不自动推进文字。
- `POST /api/media/script`、`/api/media/export`、`/api/media/audio` 接收 `{kind: "chat_reply", answer: ChatReply, persona_name?: str}`。脚本/HTML 展示不调用模型；音频只调用配置的合成器。
- `GET /api/media/capabilities` 提供 available/backend/label/languages/audio_formats，无密钥或端点。语音失败不影响其他页面。
- 音频写入资料库目录下 media-cache，返回 script、ordered segments、manifest；分片可重复同一句索引。`GET /api/media/audio/{name}` 只接受 SHA-256 的 WAV/MP3 文件，验证目录边界，响应 `private, no-store`。
- 导出独立 HTML 不含可执行脚本或外部资源；文本转义，JSON 元数据安全转义，含 AI 标识与来源指纹。指纹不是签名，也不证明客户端提交回答的真实性。
- 语音不可用/拒绝/超时/过长对应 503/502/504/413，固定中文提示不回显服务消息。声音先播可听标识，以 ended 驱动句子推进；暂停保留位置，关闭释放音频，失败退回文字。

旧前端使用 ES 模块，无构建步骤；所有服务端文本通过 textContent 呈现，支持窄屏及系统深浅主题。

## 新前端（迁移中）

访问 `/next/`（`/next` 同样返回页面），默认 `#/chat`；`/next/#/gallery` 是交互组件与动效画廊。`/` 的旧 UI 保持不变。

### 技术栈与目录

Node 22、pnpm 10.32.1、React 19、严格 TypeScript、Vite、Tailwind CSS v4（`@tailwindcss/vite`）、`motion/react`、Radix Dialog/Tooltip/Tabs/Switch、lucide-react、zustand、clsx/tailwind-merge、react-router HashRouter。版本精确锁定在 `frontend/package.json`，传递依赖锁定在 `frontend/pnpm-lock.yaml`。开发使用 Vitest、Testing Library/user-event、jsdom、ESLint/typescript-eslint/react-hooks、Prettier。

```text
frontend/
├── src/
│   ├── design/       # tokens.css、motion.ts
│   ├── components/   # ui/、motion/、layout/、effects/、reactbits/
│   ├── lib/          # 同源 API、格式化与样式合并
│   ├── stores/       # 状态与可见性轮询
│   ├── features/     # chat/、playback/、jobs/、sources/、profile/、questionnaire/、identity/
│   ├── pages/        # 聊天、记忆资料、人格档案、建档问卷、身份、组件画廊
│   ├── test/         # setup 与行为/对比度测试
│   └── main.tsx
├── package.json / pnpm-lock.yaml
├── vite.config.ts / tsconfig.json
├── eslint.config.js / .prettierrc.json
└── index.html
src/twin/web/static/next/
├── index.html
└── assets/           # 带哈希的 JS/CSS，构建产物随代码纳入版本控制
```

```sh
pnpm -C frontend install --frozen-lockfile
pnpm -C frontend dev       # /next/；API 代理到本地 8765，另行启动 twin ui
pnpm -C frontend typecheck
pnpm -C frontend lint      # ESLint + Prettier
pnpm -C frontend test
pnpm -C frontend build
uv run ruff check src tests deploy
uv run ruff format --check src tests deploy
uv run mypy
uv run pytest -q
```

Vite base 为 `/next/`，输出到 `src/twin/web/static/next`，清空旧输出、无 sourcemap、关闭 modulePreload polyfill。后端仅新增 `/next`、`/next/` 和 `/next/assets/`，沿用全部安全头与 Host/CSRF 保护；缺少构建时显示中文提示并链接旧界面。Python 包运行不依赖 Node。CI 单独构建并对产物执行 `git diff --exit-code src/twin/web/static/next`，提交代码时需一并更新产物。CI 新增 actions 使用已通过 GitHub release 和 tag 核实的 SHA。

### 设计令牌

原创样式仅借鉴温暖留白、白色卡片、单一蓝色强调、轻边框与模糊侧栏，不复制参考站点代码、字体或资产。全部字体为系统栈，无运行时外部资源。

| CSS 变量 | 浅色 | 深色（prefers-color-scheme） |
| --- | --- | --- |
| canvas | `#FBF8F4` | `#141311` |
| surface / surface-raised | `#FFFFFF` / `#FFFFFF` | `#201E1B` / `#2A2723` |
| border | `#E5E0D9` | `#403B34` |
| text-primary | `#292622` | `#F5F0E9` |
| text-secondary | `#625C54` | `#C4BCB1` |
| text-tertiary | `#756E65` | `#ABA195` |
| accent / hover / pressed | `#2563EB` / `#1D4ED8` / `#1E40AF` | `#8CB8FF` / `#A9CAFF` / `#BCD6FF` |
| on-accent | `#FFFFFF` | `#141311` |
| success / warning | `#187047` / `#8A570B` | `#7CDAA7` / `#ECC079` |
| danger / info | `#B72E38` / `#2463AE` | `#FF9DA3` / `#8CB8FF` |
| sidebar | white / 60% | `#201E1B` / 65% |

状态色只表达状态。文字（含次级/三级）、强调色及状态色在 canvas、surface、surface-raised 上以单元测试检查 WCAG AA ≥ 4.5:1。圆角为 8/12/16/20px/full；字号为 12/13/14/16/20/24/32px，正文 14px、行高 1.75，标题紧字距。间距使用 Tailwind scale。阴影 elevation 1–3：浅色 `0 2px 6px / .04`、`0 6px 20px / .08`、`0 16px 48px / .12`（色 `#292622`），深色黑色透明度 .16/.24/.32；卡片 `4px 4px 0 rgb(0 0 0 / .03)`，深色透明度 .2。变量通过 Tailwind v4 `@theme inline` 接入。

### 动效与可访问性

| 预设 | stiffness | damping | 用途 |
| --- | --- | --- | --- |
| snappy | 520 | 38 | 按钮轻触、开关 |
| gentle | 260 | 30 | 列表进入、页面、对话框、进度 |
| bouncy | 380 | 18 | 仅轻松的点缀反馈 |
| layout | 420 | 40 | 重排、侧栏宽度、标签/导航指示器、通知堆栈 |

退出时长 quick/page/dialog 为 120/160/180ms；默认淡入淡出 150ms。`useMotionPreset()` 感知 `useReducedMotion()`，并订阅 media query 的实时变化（上游 hook 缓存初始偏好）：开启减少动态效果时只用淡入淡出，关闭位移、缩放、拖动、共享布局动画与 shimmer；进度和开关直接更新位置并淡入。不把弹簧仅改成快速 tween 来“减少”运动。拖动有惯性与弹性边界，距离 > 100px 或距离 > 10px 且速度 > 600px/s 才关闭，未达阈值回弹；始终提供键盘可用的关闭入口。

UI：Button（4 变体/3 尺寸/loading）、IconButton、Card、Input、自动增高且 IME 安全的 Textarea、Field、Badge、Meter、Skeleton、EmptyState、Table、Tabs、Switch、Dialog、ConfirmProvider/useConfirm、Toast/toast、Tooltip。动效：Pressable、Reveal/Stagger/StaggerItem、PageTransition、LayoutScope/LayoutItem（隔离 LayoutGroup）、DragDismiss。每项在 gallery 有最小可交互示例。确认使用 `const confirm = useConfirm(); await confirm({title, body, confirmLabel, tone})`，返回 boolean，Escape/取消/关闭返回 false；卸载会结清待处理请求。Radix 提供焦点约束、键盘操作与 ARIA；通知包含 polite live region。

AppShell 桌面侧栏可折叠，图标态带 Tooltip，活动导航有共享 pill；<768px 从顶栏打开弹簧底部抽屉，可下拖关闭。顶栏展示姓名、模型与外部 egress 主机（`外部 · <host>`，info 色调），不显示本机后端；身份导航与页面标题为“身份”。`stores/status.ts` 首次获取 `/api/status` 总会执行，即使标签页处于后台也不跳过或因隐藏而取消；此后可见时每 10 秒刷新，隐藏时暂停定期刷新并取消后续请求，恢复可见后立即刷新，卸载清理计时器与监听。

所有 AI 标签及免责声明必须来自 `/api/status.labels`（explicit/disclaimer/chat_notice），不能在前端复制或兜底硬编码；未加载显示 Skeleton/留空。API 客户端仅接受本地 `/api/`，JSON/form 编码，所有非 GET 请求带 `X-Twin: 1`，错误为带 status/detail 的 `ApiError`，保留中文 detail，其他错误映射为中文。HTML 导出使用 `responseType: 'text'`；错误仍按 JSON detail 解析。

### React Bits（F0b）

使用官方 shadcn registry 的 **TypeScript + Tailwind** 变体，配置在 `frontend/components.json`。安装命令为 `pnpm -C frontend dlx shadcn@latest add --cwd frontend @react-bits/<Name>-TS-TW --yes`（本次 CLI 4.21.2）；安装日期 2026-10-05。7 个源文件均与 React Bits 提交 `ca44b3f9ee180676a06d7de8ec6bea84cddff85b` 的 `src/ts-tailwind/` 字节一致，之后仅做一处带行内说明的 Stepper 空 interface lint 修复。源文件保存在 `frontend/src/components/reactbits/`，保留上游格式（仅排除 Prettier，ESLint 仍检查）。完整 **MIT + Commons Clause** 许可、来源及版本在该目录的 `NOTICE.md`：仅用于本应用，不单独销售、再许可或作为组件库再分发。

页面只从 `frontend/src/components/effects/` 导入应用 wrapper；ESLint `no-restricted-imports` 禁止该目录之外的应用代码直接导入 vendored 组件（含相对路径、`@/` 别名），测试验证规则及页面导入。继续复用现有 Motion、设计令牌和 UI，不安装其他装饰组件。新增运行依赖只有精确版本 `gsap@3.15.0`（AnimatedContent/ScrollTrigger）；`motion@12.34.0` 保持原版本。资源全部本地打包，无 CDN 或运行时网络资源。

| 上游组件 / wrapper | 应用 API | 默认行为 | 减少动态效果 |
| --- | --- | --- | --- |
| BlurText 语义适配 / `ReplyReveal` | `text, className?` | `Intl.Segmenter` 词级分段，≤25ms 交错、含揭示总时长≤约1.2s，3px 模糊/2px 位移、120ms 揭示；保留原空白 | 全文立即显示 |
| ShinyText / `ThinkingLabel` | `text?`（默认“思考中…”） | 次级/主文字令牌间的柔和高光，3s 播放、2s 间隔，polite status | 静态文字 |
| CountUp / `MetricNumber` | `value, from?, suffix?` | 0.6s spring 计数，千位分隔；网格预留起点/终点宽度 | 最终值立即显示 |
| AnimatedList / `MessageList` | `items: {id,text,content?}[], label, className?` | 使用稳定 ID 的语义列表；文本使用上游淡入，富消息 content 使用 gentle 入场；150ms 淡出；禁用全局方向键/Tab 监听、缩放和渐变，无列表交错 | 直接显示，无入场动画；退出仅淡出 |
| SpotlightCard / `SpotlightAction` | `children, label, onClick, disabled?` | 语义按钮、键盘入口；accent 6% 光斑 × 上游 0.6 opacity，原配色由 wrapper 覆盖 | 完全关闭光斑 |
| Stepper / `FlowStepper` | `steps: {id,title,content}[], onComplete?, completedText?, initialStep?, completeOnLast?` | 应用令牌、可聚焦的步骤按钮、中文导航与完成状态；为后续问卷预备 | 同样的步骤导航，直接切换，无滑动/高度动画 |
| AnimatedContent / `SectionReveal` | `children, className?` | 首次滚动进入时 8px/250ms 揭示，无缩放 | 区块立即可见，不创建滚动触发器 |

文字与数值使用完整的 visually hidden 文本，所有动态呈现均 `aria-hidden`，避免重复或逐词/逐帧播报；文字动画不改变布局，指标预留宽度。Gallery 的“React Bits 动效”区展示全部 7 个 wrapper，各有重播按钮和减少动态效果说明；列表支持添加/移除，流程支持切换与完成。聊天、记忆资料、人格档案、建档问卷和身份均使用真实 API；业务路由无占位页，gallery 保留组件示例，不填充虚构业务数据。

确认弹窗打开时明确聚焦**取消**，不自动聚焦破坏性动作；程序化 `confirm()` 将打开前的 `document.activeElement` 保存在请求中，并在关闭动画卸载后恢复仍连接的元素，关闭时通过独立 ref 保留焦点，避免 request 清空后丢失目标。通知只通过 polite live region 播报，新增通知不主动移动焦点。测试覆盖无 trigger 的输入框焦点恢复，以及通知显示期间首个 Escape 关闭且返回入口。

### 迁移状态

| 新路由 | 状态 | 旧界面 |
| --- | --- | --- |
| `#/chat` | 已迁移（/next） | `/#/chat` |
| 聊天回复 → 回放面板（含形象） | 已迁移（/next） | 旧聊天页回放面板 |
| `#/questionnaire` | 已迁移（/next） | `/#/questionnaire` |
| `#/persona` | 已迁移（/next） | `/#/persona` |
| `#/sources` | 已迁移（/next） | `/#/sources` |
| `#/identity` | 已迁移（/next） | `/#/identity` |
| `#/gallery` | F0 UI + F0b React Bits wrapper 示例已实现 | 不适用 |

### F1 聊天与回放

`/next/#/chat` 使用 MessageList、最新回复的 ReplyReveal、ThinkingLabel、Textarea 和确认弹窗；旧回复（包括恢复的历史）静态显示。会话仅在本标签页的 sessionStorage 保存完成的往返；失败回退用户消息并恢复输入，支持原请求重试，不恢复后台任务。发送时传完整 messages 和可选 as_of，每秒轮询任务，路由变化/卸载/清空时停止等待并 Abort 请求（不取消服务端任务）。进入和发送时检查 stale，重建入口指向新前端 `#/sources`。

中文分段使用 `Intl.Segmenter(undefined, {granularity: 'word'})`；无此 API 时，CJK 逐字符、其他文字按空白分隔。拼接视觉单元等于原文，屏幕阅读器只读取完整文本；交错延迟按单元数缩放，总揭示≤约1.2s。为避免 BlurText 的空格分割和自动插空格，适配只在 effects wrapper 中使用现有 motion 逐单元揭示，不修改 vendored 源码。减少动态效果直接显示全文。

PlaybackDialog 复用 Dialog 的弹簧开关、模糊遮罩和焦点约束。脚本、开头提示、显式标识和形象 badge 均来自 media/status API。保留文字按句计时、已展示句子、Space/左右键/Escape、关闭后返回“回放”入口；回答依据按脚本引用顺序复用聊天的紧凑引用卡片（匹配 reply.cited 的原话、日期、来源或档案细项），仅缺失展示条目的引用退回编号与理由；按钮聚焦时 Space 保持原生按钮行为。朗读从开头提示开始，音频同句分片有序播放，ended 推进句子；暂停保留音频时间，手动切句/关闭重置。失败显示中文 detail 并回退文字，合成请求失败后允许重试。导出下载 API 返回的独立 HTML。

Avatar 是旧 SVG 的 React 移植，保留调色板验证、四级口型、随机眨眼和常驻 API 标签。口型按当前音频分片的 currentTime × lipsync.fps 读取；暂停、等待、关闭或关闭朗读时归零。减少动态效果不眨眼、口型仅0/1、文字仅手动推进，但朗读仍可自动推进；运行中切换偏好会暂停回放，不重取脚本。关闭/卸载清理定时器、rAF、音频监听/资源、请求和下载 URL。无新增运行时依赖。

有意差异：Enter 发送、Shift+Enter 换行（旧版 Ctrl/⌘+Enter）；清空增加确认；显示时间戳和 as_of；依据改为键盘按钮加弹簧卡片；仅最新回复揭示；朗读合成失败可再次请求。旧 UI 与后端完全不变。

测试覆盖 API CSRF/编码/错误、确认 true/false/关闭/Escape、IME 安全、Tabs、Switch/loading、通知、减少动态效果与双色对比度，以及发送/轮询/失败重试/会话清空/路由取消、中文分段与完整阅读文本、依据键盘展开收起、回放快捷键/焦点恢复/有序分片/暂停续播/口型/眨眼/关闭清理/导出/API 标签。业务测试模拟 fetch 和视觉 Motion 层以隔离计时器，既有 primitive/motion/effects 测试保留真实 Motion。`tests/test_web_next.py` 检查页面/资源 MIME、安全头、无内联脚本或外部资源、缺少构建的回退。

### F2 记忆资料与人格档案

组件树：

```text
AppShell（HashRouter，按页 lazy）
├── Sources → useSources + useJob
│   ├── 导入 Card → KindSelector / DropZone / 日期 Field / 每文件结果
│   ├── 资料 Card → LayoutScope / MessageList(layout) / SourceRow / ConfirmDialog
│   └── 构建 Card → stale 提示 / JobProgress(Meter) / BuildSummary
└── Profile → useProfile
    ├── 日期 Field → CoverageOverview（维度指标 / 细项矩阵 / 建议）
    └── 条目 Card → 审核筛选 / include_rejected Switch
        └── MessageList(layout) 或 VirtualItemList → ItemCard（证据 / 内联修改 / 审核）
```

`useJob` 每秒读取任务快照；阶段优先使用 API `stage`，未提供时回读最后一条 `[n/N]` 日志；阶段进度为 `(current-1)/total`，否则使用 tally（含失败项），完成为 100%。无法估算时 Meter 不设置 aria-valuenow，不伪装成 0%。保留状态、用时、里程碑、英文日志、失败原因和构建缓存补跑提示。网络错误每 2 秒重试，累计 15 次后停止并提供“重新连接”；新任务 404 提示服务重启，过期的恢复记录静默清除。提交 409 时 API 客户端保留 job_id 并跟踪冲突任务；非构建任务完成不显示构建汇总。进入页先 GET /api/jobs 查找 queued/running 的 persona_build，再恢复本标签页保存的编号；已结束的恢复结果不重复成功通知。路由失活/卸载清理请求和计时器，不取消服务端工作。

资料导入保留六种类型和原帮助文案、可选日期、multipart files、逐文件已导入/已更新/未导入及原因；全部跳过时沿用后端 400 中文 detail，显示内联错误和通知并保留文件选择。来源显示原话（本人/他人）、本人/全部、支撑条目、涉及细项、日期、未授权细项以及两种未记忆状态。删除通过 danger ConfirmDialog，乐观移除、失败回滚（无撤销按钮）；导入、删除、构建完成刷新资料、stale 和状态 store。构建汇总保留资料/块/候选/条目/失败数、总差异与按 ID 排序的非零细项差异，不记录或新增日志输出个人文本。

人格档案保留维度授权计数、覆盖/充分/验证比例、矛盾、API level_labels、未授权标记、细项 × 来源矩阵、前 15 条建议、适用条件、原提炼和审核状态。确认/修改/驳回/撤销审核均调用 review API，乐观更新且失败回滚；失败编辑保留草稿。审核成功重新读取完成度。按维度/细项分组，≤300 个可见条目使用普通列表，>300 才用无依赖的可变高度窗口列表（ResizeObserver、预估高度、overscan、焦点行保留、aria-setsize/posinset、可键盘滚动区域）。

| 与旧页对照 | 状态 |
| --- | --- |
| 六种导入、日期、结果/跳过原因、资料记忆摘要、删除、stale、构建/恢复/重试/差异 | 已完成 |
| 维度比例/授权数/矛盾、等级标签、来源矩阵、建议、四种审核操作与筛选 | 已完成 |
| 下拉类型与文件框 → 原生 radio 分段指示器和可键盘操作的多文件 drop zone | 有意不同；转录选择器开放后端已支持的 SRT/VTT |
| 表格 → 维度/细项/来源卡片；末条证据预览 → 可展开全部证据 | 有意不同 |
| 默认待核实筛选 → 默认全部非否决条目；否决需开启 include_rejected | 有意不同；原审核筛选仍可用 |
| 完成度 as_of 日期 | 新增；仅传给 coverage，当前条目不是历史快照（items API 无日期参数） |
| 大列表窗口化、乐观回滚、审核后完成度刷新 | 新增；普通列表删除以 layout spring 合拢，窗口列表直接更新位置 |
| 未迁移能力 | 本任务两页无缺失；问卷入口由 F3 接入新前端 |

动效使用现有 gentle/layout 弹簧：drop zone 轻缩放/边框、Meter、证据高度、普通列表间隙；阶段文本 crossfade。没有列表 stagger，刷新/审核不会重新交错入场。减少动态效果关闭共享布局、位移、缩放和高度动画，仅保留淡入淡出与立即更新；未知进度不使用移动条纹。效果只从 effects wrapper 导入，按具体模块导入避免将画廊的 GSAP 带入业务路由。无新增运行时依赖，旧 UI 与后端不改。

F2 测试：`jobs.test.tsx` 覆盖轮询/阶段与 tally/自动重试/重新连接/运行任务恢复/过期记录/提交失败与 409/清理；`persona.test.tsx` 覆盖导入成功与跳过/上传失败/键盘 picker/拖放/来源摘要/删除确认与回滚/构建差异与 stale/失败提示/覆盖率与 API 等级/确认修改驳回撤销及回滚/证据键盘展开/as_of 重取/include_rejected/300 与 301 条窗口化边界/请求取消。聊天 stale 链接测试同步改为新路由。

### F3 建档问卷与身份

`/next/#/questionnaire` 用 `useQuestionnaire` 读取第一轮或 `?round=retest` 的服务端草稿，按 API `section` 分组，通过 FlowStepper 切换；进入时定位第一道未答题所在组。保留题号、题干、种类、对应细项、情境/开放题帮助、测试题留出提示、4000 字限制和已答/总题数。Textarea 自动增高、IME 安全，Enter 仅换行，不触发提交。可跳过题的“跳过”清空答案；空答案不计已答，提交时仍由旧后端推导 declined_facets，不发送新的授权字段。

草稿 800ms 防抖 PUT，按版本串行保存不可变快照；保存中继续编辑会接着保存最新版本，“已保存”轻淡入淡出。保存失败保留输入并提供重试；提交先等待最新草稿保存成功，失败时不 POST。换轮或路由卸载会清掉防抖计时器、取消读取但继续完成写入，快速返回同一轮先等退出时的写入再读取，避免恢复旧快照。小于 60KB 的退出写入启用 keepalive，大草稿使用普通请求以避免浏览器 64KB 限制；关闭标签页时的写入只能尽力完成。只有仍有未保存修改且写入正在进行时，刷新/关闭页才出现浏览器原生警告，应用内导航链接/轮次切换才出现 ConfirmDialog；单纯等待防抖或已保存不弹警告。

交卷使用 ConfirmDialog，说明导入为问卷来源、需要重新构建、后端尝试自动开始、测试题不进档案、可跳过题不授权，以及重新提交会替换上次答案。成功展示 API notice、Toast、`#/sources` 的构建/进度入口；返回 job_id 时复用 F2 的 useJob、JobProgress、构建恢复、完成摘要与细项差异，以及档案/聊天链接。重测恢复已存答案，保留提交日期、建议重测日期、修改后重新提交与 API notice；**旧页和接口都没有重测评分，故不计算或展示分数**，重测也不启动构建。

`/next/#/identity` 用 `useIdentity` 独立读取 `/api/identity` 和 `/api/media/capabilities`。只读展示名字、别名、预置音色/形象、出境表及不支持真人声音复刻/照片驱动形象的说明；类型、提供方、主机原样来自 API（包括评委行，不按下标改写类型）。小形象复用 playback 的 Avatar 和 capabilities 中的配置 spec，口型始终为 0，允许眨眼，减少动态效果关闭眨眼。身份读取失败可重试；预览失败不影响身份表格。AI 标识只来自 status.labels.explicit 和 avatar.spec.label，未加载不硬编码兜底。卸载取消读取并清理眨眼计时器。

| 与旧页对照 | 状态 |
| --- | --- |
| 第一轮/重测、草稿恢复/保存、题干/细项/种类、留出测试题、可跳过细项授权、进度 | 已完成 |
| 确认提交/替换、API notice、自动构建跟踪/恢复/差异、提交日期与重测建议日期 | 已完成 |
| 一题一屏和题号总览 → 按旧 section 分组的键盘可操作 FlowStepper | 有意不同；组内同时展示题目 |
| 1500ms 保存 → 800ms 串行防抖、保存失败重试、仅写入中离开警告 | 有意不同；不增加本地个人答案存储或日志 |
| 身份只读字段、出境表、限制说明和 API 模拟标识 | 已完成 |
| 身份页形象预览、出境 kind 不按行号改写 | 新增/修正；使用配置的预置 spec 与真实 API kind |
| 重测评分 | 不适用；按旧页只恢复答案与展示提交状态，无后端改动 |

F3 测试：`questionnaire.test.tsx` 覆盖草稿恢复/首个未答分组、两种动态偏好的步骤导航/键盘、800ms 假计时防抖/X-Twin/IME、跳过与进度、串行保存中编辑、离开警告/取消/确认、卸载保存/计时清理、快速换轮返回、保存失败/重试、交卷取消/确认/替换/成功/错误、自动构建摘要与链接、重测恢复/提交状态（无评分）、轮次隔离与加载重试；`identity.test.tsx` 覆盖 API 数据与逐行出境、配置 Avatar/闭口/眨眼/减少动态效果/清理、API 标签无硬编码、读取与预览失败重试/取消。AppShell 身份测试改为真实新页面，档案的问卷入口不再链接旧 UI。无新增运行时依赖，旧 UI 与后端不改，构建产物仍在 `src/twin/web/static/next/`。
