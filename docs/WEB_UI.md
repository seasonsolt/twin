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
│   ├── pages/        # 五个业务页面及组件画廊
│   ├── test/         # 行为、动效、可访问性及对比度测试
│   └── main.tsx      # HashRouter 与按页 lazy 加载
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

AppShell 桌面侧栏可折叠，图标态带 Tooltip，活动导航使用共享 pill；小于 768px 时从顶栏打开底部抽屉，支持下拖和键盘关闭。顶栏显示姓名、模型与外部 egress 主机，不暴露端点路径或密钥。状态首次读取 `/api/status`，之后可见时每 10 秒刷新，隐藏时暂停定期刷新，恢复可见后立即读取；卸载清理请求、计时器和监听。

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

动画文本/数值使用完整的 visually hidden 文本，视觉动态层 `aria-hidden`，避免逐词逐帧播报。`#/gallery` 提供所有 UI、Motion 与七个 wrapper 的可交互示例及重播入口，不填充虚构业务数据。

## 页面

| Hash 路由 | 功能 |
| --- | --- |
| `#/chat`（默认） | 多轮聊天、as_of、依据、回放、朗读与导出 |
| `#/sources` | 六种资料导入、来源记忆摘要、删除、stale 与构建进度/差异 |
| `#/persona` | 维度/细项完成度、来源矩阵、采集建议、条目审核与修改 |
| `#/questionnaire` | 建档问卷、服务端草稿、交卷、自动构建与重测 |
| `#/identity` | 名字、别名、预置音色/形象及出境表，只读 |
| `#/gallery` | 组件与动效画廊 |

聊天使用 MessageList、最新回复的 ReplyReveal、ThinkingLabel、Textarea；Enter 发送、Shift+Enter 换行，IME 安全。完成的往返仅保存在本标签页 sessionStorage；失败恢复输入并可重试，清空需确认。进入/发送时检查 stale，重建入口是同一应用的 `#/sources`。任务每秒轮询，离页取消等待和请求，不取消服务端任务。

PlaybackDialog 使用 `features/playback/usePlayback.ts` 和 `Avatar.tsx`。先展示开头提示，再逐句呈现原回答，弃权不讲述回答；引用按脚本顺序解析。Space 播放/暂停、左右键切句、Escape 关闭并返回入口；聚焦按钮时 Space 保持原生行为。音频有序分片由 ended 推进，暂停保留时间，口型按 currentTime × lipsync.fps 取值；暂停、等待、纯文字播放时闭嘴。形象只使用 API 的预置调色板、四级口型和常驻标签，无图片输入。关闭释放音频、计时器、rAF、请求及下载 URL；语音失败显示中文 detail 并退回文字，可重试合成。

资料页支持问卷、聊天、访谈、文档、他人记述和通用转录，multipart 多文件及可选日期。来源摘要显示本人/他人原话、支撑条目、涉及细项与 not_built/remembered/no_items；删除需确认，乐观更新失败回滚。构建汇总保留计数与非零 facet_diffs，不新增个人文本日志。useJob 可恢复运行中的构建，409 跟踪冲突 job_id，断线重试并提供重新连接；重启后任务不续跑。

档案页按维度/细项分组，显示授权、覆盖/充分/验证比例、矛盾、API 等级标签、来源矩阵与建议。review 支持确认/修改/驳回/撤销，失败回滚并保留编辑草稿；审核后刷新完成度。≤300 个可见条目用普通列表，更多时用可变高度窗口列表并保留焦点行。as_of 只影响 coverage，items 不是历史快照。

问卷按 API section 分组，用 FlowStepper 导航到首个未答组；可跳过题清空答案，空答案不计已答。草稿 800ms 防抖、版本化串行 PUT；提交等待保存成功，需确认且说明替换、授权与测试题留出规则。离页完成待写草稿，小于 60KB 时尽力 keepalive，不另存个人答案。仅未保存且写入中的离开才警告。重测只恢复答案和提交状态，无评分、不构建。

身份页独立读取 identity 与 media capabilities，逐行原样展示 kind/provider/host/external/declared，含评委。预览失败不影响身份表；形象闭口、减少动态效果不眨眼。不支持真人声音复刻或照片驱动形象，由配置校验保证。

## API 与任务契约

客户端只接受同源 `/api/`，非 GET 请求带 `X-Twin: 1`；JSON/form 编码，错误为含 status/detail 的 ApiError，保留中文 detail。HTML 导出按 text 读取，错误仍解析 JSON。

| 方法/路径 | 契约 |
| --- | --- |
| `GET /api/status` | target_name、counts、llm/embed、egress、labels；无数据库路径或密钥 |
| `GET /api/jobs`、`/api/jobs/{id}` | 状态、时间、进度日志、阶段、计数、里程碑、结果/错误 |
| `GET /api/persona/sources` | 来源元数据及 expressions_total/target/others、items_supported、facets、contributes_nothing、build_status |
| `GET /api/persona/state` | `{stale, built_at, sources_changed_at}` |
| `POST /api/persona/import?kind=...&date=...` | multipart files，返回 imported/skipped |
| `DELETE /api/persona/sources/{id}` | 删除资料，返回 deleted |
| `POST /api/persona/build` | 构建与向量更新，202 job_id |
| `GET /api/persona/items?include_rejected=false` | 条目、细项/维度、证据场合数 |
| `POST /api/persona/items/{id}/review` | confirmed/edited/rejected/unreviewed；edited 必须非空 |
| `GET /api/persona/coverage?as_of=...` | 完成度、来源矩阵、等级标签、分类版本、建议 |
| `POST /api/persona/chat` | messages（≤40 条、每条≤4000 字、最后非空 user）、as_of；202 job_id，结果 ChatReply + cited |
| `GET /api/persona/questionnaire?round=initial/retest` | 问题、答案、提交状态 |
| `PUT /api/persona/questionnaire/draft` | round、answers，保存草稿 |
| `POST /api/persona/questionnaire/submit` | 初次导入并尝试构建；重测仅记录 |
| `GET /api/identity` | name/aliases/voice/avatar/egress；无授权账本 |
| `GET /api/media/capabilities` | available/backend/label/languages/audio_formats/avatar |
| `POST /api/media/script`、`/export`、`/audio` | `{kind: "chat_reply", answer: ChatReply, persona_name?: str}` |
| `GET /api/media/audio/{name}` | SHA-256 命名 WAV/MP3 分片，验证目录边界 |

任务状态 queued/running/done/failed，日志最近 500 行，里程碑另存；人格构建互斥，聊天有并发及待处理数量限制。任务仅驻留内存，重启清空。stale 表示来源比档案新，不阻止聊天。构建结果包含 items_added/changed/removed、facets_changed 和 facet_diffs；失败不当作零分答案。

脚本与独立 HTML 导出不调用模型，音频只调用配置合成器。导出自包含、无可执行脚本或外部资源，文本及 inert JSON 安全转义，含 AI 标识和来源指纹；指纹不是签名。音频存于数据库目录的 media-cache，GET 为 `private, no-store`。语音不可用/拒绝/超时/过长为 503/502/504/413，不回显服务消息。

## 安全与服务路由

`web.app.create_app` 懒创建后端，测试可注入离线工厂。默认仅接受 localhost、127.0.0.1、[::1] Host，显式 `--host/--allow-host` 可扩展；公网必须另加认证。所有非 GET/HEAD 请求要求 `X-Twin: 1`，不开 CORS，WebSocket 一律关闭（1008）。JSON 上限 1 MB，上传上限 100 MB、500 文件；上传只取 basename，内存解析，不读客户端指定的服务器路径。

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
