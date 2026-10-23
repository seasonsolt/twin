# 团队分身网页：设计与接口契约

`twin ui` 默认监听 `http://127.0.0.1:8765`，`/` 是唯一的 React 前端。页面使用 HashRouter，无需服务端应用路径回退；`/` 对能管理分身的人（管理员，或名下有能管理的分身的成员）进入 `#/team`，对只能聊天的访客进入 `#/chat`；访客打开团队类地址也回到 `#/chat`。未登录时任何地址都先到 `#/login`，登录后去 `#/team`；进应用之前的两步（会议里找自己、看看你的分身）在 `#/welcome`，没有要做的事时直接离开它。`/next`、`/next/` 仅作 308 重定向到 `/`，保留书签兼容；不再提供 `/static` 或 `/next/assets`。会议录音和分身资料存于部署所在的机器；配置远端模型或语音服务时，请确认数据使用权限。

## 技术栈与目录

Node 22、pnpm 10.32.1、React 19、严格 TypeScript、Vite、Tailwind CSS v4、`motion/react`、Radix Dialog/Tooltip/Tabs/Switch、lucide-react、zustand、clsx/tailwind-merge、react-router HashRouter。版本锁定在 `frontend/package.json` 和 `frontend/pnpm-lock.yaml`。测试使用 Vitest、Testing Library/user-event、jsdom，关键页面截图对比使用 Playwright（固定版本镜像）；检查使用 ESLint、typescript-eslint、react-hooks、本地样式规则 `eslint/twin-ui.js` 和 Prettier。

```text
frontend/
├── src/
│   ├── design/       # tokens.css、motion.ts
│   ├── components/   # ui/、motion/、layout/、effects/、reactbits/
│   ├── lib/          # 同源 API、格式化与样式合并
│   ├── stores/       # 状态与可见性轮询
│   ├── features/     # chat/、avatar/、jobs/、sources/、profile/、questionnaire/、identity/、library/（团队表和两页共用的 useTeamData）、inbox/（待处理的行、逐个听、延迟提交）
│   ├── pages/        # 团队、成员页（Member、旧地址跳转 ProfileRedirect）、录音库、待处理（Inbox）、承诺（Commitments，账本组件是 Ledger）、聊天、认领页（Claimed）、会议里找自己（MemberVoice）、记忆；首次引导、可选问卷与开发画廊
│   ├── test/         # 行为、动效、可访问性、对比度及样式规则测试
│   ├── App.tsx       # HashRouter 与按页 lazy 加载
│   └── main.tsx      # React 入口
├── package.json / pnpm-lock.yaml
├── vite.config.ts / tsconfig.json
├── e2e/              # 截图对比：pages.spec.ts、mockApi.ts（固定数据）、__screenshots__/ 基线
├── eslint/           # 本地 ESLint 规则 twin-ui（样式护栏）
├── eslint.config.js / .prettierrc.json / playwright.config.ts
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
uv run pytest -q -n auto
```

Vite dev server 将 `/api` 代理到 `http://127.0.0.1:8765`，改写 Host 为目标主机，保持同源客户端请求与 `X-Twin: 1`，无需放宽后端 CSP 或开启 CORS。必须先启动 `twin ui`；若更改后端端口，同时调整 `frontend/vite.config.ts` 的 proxy target。开发服务器用于热更新，正式服务使用构建产物。

CI 前端任务运行四项检查和截图对比（`./scripts/screenshots.sh`，失败时上传差异图）后执行 `git diff --exit-code src/twin/web/static` 和 `test -z "$(git status --porcelain src/twin/web/static)"`，同时检查跟踪文件差异及新增未跟踪产物；提交前必须同步构建结果。`.gitattributes` 将 index 与 assets 标记为生成文件。

## 布局、令牌与可访问性

AppShell 桌面使用三层底色：`soft` 窗口底，直接放 68px 图标导航栏；`canvas` 对话列表；`surface` 白色内容面板。内容面板距顶部 8px，左上圆角 16px。导航按钮为 44×44px、圆角 12px，名称放在 Tooltip 与 aria-label，当前页为白色 tile 加 elevation-1 阴影。顺序为团队、录音库、分隔线、当前分身头像（32px，强调色环，打开 PersonaSwitcher）、聊天/工作/档案/承诺账本、弹性空白、最近分身快捷入口（36px）与 +N/新建、账户。功能开关与访客权限继续决定哪些入口可见；手机底部保留带文字的导航。

分身切换面板支持键盘、搜索（超过 6 个分身）、记忆数、当前勾选、新建与管理入口。顶栏不显示模型或外部服务角标；外部服务只在档案中说明。状态首次读取 `/api/status`，之后可见时每 10 秒刷新，隐藏时暂停，恢复可见后立即读取；卸载清理请求、计时器和监听。

设计令牌集中在 `frontend/src/design/tokens.css`，经 Tailwind v4 `@theme inline` 接入。使用系统字体，不加载外部字体或资产。

三套主题，默认朱砂红；不跟随系统深色模式。登录页底部和账户菜单（手机在团队页底部）可切换，选择只记在本浏览器（`localStorage` 的 `twin:theme`，读不到时用默认），由 `stores/theme.ts` 写到 `<html data-theme>`。命名主题只覆盖与默认不同的令牌。

| 变量 | 朱砂红（默认） | 海蓝（`blue`） | 墨夜（`ink`，深色） |
| --- | --- | --- | --- |
| canvas / soft | `#FFF4EA` / `#FBE9DD` | `#F3F5F8` / `#E5EBF4` | `#16130F` / `#2A2420` |
| surface / surface-raised | `#FFFFFF` / `#FFFFFF` | 同默认 | `#201C18` / `#2A2420` |
| border | `#F2DFCF` | `#DBE1EA` | `#3D352E` |
| text-primary | `#2B1D16` | `#17202C` | `#F5F0E9` |
| text-secondary / text-tertiary | `#6B4A3A` / `#795442` | `#4A5566` / `#566173` | `#C4BCB1` / `#A99F93` |
| accent / hover / pressed | `#C9432C` / `#B33723` / `#982C1C` | `#1F5FBF` / `#1A53A8` / `#154385` | `#E0674F` / `#E87C66` / `#D9634C` |
| on-accent | `#FFFFFF` | 同默认 | `#1A0E0A` |
| stage-bg / stage-ink（舞台） | accent / `#FFFFFF` | accent / `#FFFFFF` | `#2A2420` / `#F5E6D6` |
| sun / note（提示卡片） | `#F5B83D` / `#FDE7B8` | 同默认 | `#B0502F` / `#3A2E1E` |
| success / warning | `#2E7D5B` / `#8A570B` | 同默认 | `#6CC49A` / `#E6B45C` |
| danger / info | `#B72E38` / `#2463AE` | 同默认 | `#F2848A` / `#84AEEA` |

每套主题的文字、强调及状态色在三种表面上都由单元测试检查 WCAG AA ≥ 4.5:1。圆角 8（控件）/12（列表行、提示）/16px（卡片、对话框）/full，字号 12/13/14/15/16/18/22/26px，正文 14px、行高 1.6；阴影和半透明侧栏也由令牌控制。状态色只表达状态。

UI primitives 包含 Button、IconButton、Card、Input、自动增高且 IME 安全的 Textarea、Field、Select、Checkbox、Radio、Slider、Chip、Badge、StatusDot、Meter、Skeleton、EmptyState、Table、Tabs、Switch、Dialog、ConfirmProvider、Toast 和 Tooltip；页面级组件见下节。Radix 提供焦点约束、键盘操作与 ARIA；确认默认聚焦取消，关闭后恢复原入口。通知只用 polite live region，不抢焦点。

twin 不添加免责声明。React 按文本渲染服务端内容，不执行用户 HTML，不输出个人文本日志。

## 页面组件与样式护栏

页面和功能代码只用 `components/ui` 拼界面，外观由组件的语义参数决定，className 只放布局：

| 用途 | 组件 |
| --- | --- |
| 页面骨架 | `Page`（标题、说明、整页操作、旁注链接）、`Section`（小标题即区域名称；`framed` 放进描边卡片） |
| 布局 | `Stack`、`Row`、`Toolbar`（两端对齐可换行）、`Grid`（2/3/4 列响应式）；只接受 gap 档位 0/1/2/3/4/5/6/8（×4px），不接受 className |
| 文字 | `Heading`（display 26 / page 22 / title 18 / section 16 / item 15px）、`Text`（xs 12 / sm 13 / md 14 / lg 16px，控件里的名字用 xl 18 / 2xl 22px；语义 tone）、`TextLink`（站内、外链或像链接的按钮） |
| 容器 | `Card`（raised/outline/note/soft/danger，padding 档位）、`ListRow`、`Notice`、`Disclosure`、`MediaFrame`、`Clip`（给视频、3D 视图等单个子元素裁成卡片/行/圆形圆角）、`Dialog`（`variant="sheet"` 手机底部弹层；`anchor` 贴着触发按钮的浮层位置） |
| 数据 | `Stat`、`KeyValue`、`Meter`（`max` 计数上限、`size="sm"` 细条）、`AudioLevel`、`AvatarFrame`（`size="fill"` 填满外框、`outlined`）、`Portrait`（人像照片，裁向脸部）、`StepNumber`、`Skeleton`（`panel` 大面板占位） |
| 选择与文件 | `Select`（原生 select 统一样式）、`Checkbox`、`Radio`、`Slider`、`Chip`、`ThemePicker`（主题色点，单选）、`Input`（`size="lg"` 登录等单字段表单）、`FileDrop`（拖放区）、`FileInput`（由按钮打开的隐藏文件选择） |
| 操作 | `Button`（`shape="pill"`）、`IconButton`（`shape="circle"`、`size="lg"`）、`LinkButton`（按钮样式的链接，如下载）、`ActionMenu`（“⋯”操作菜单） |
| 应用外壳 | `NavPill`（侧栏和底部标签栏的药丸导航，可带滑动高亮）、`PlainButton`（只有圆角形状的按钮，用于头像、分身行等外壳自绘控件）、`SkipLink`、`Spacer`（按测量高度留白） |

`eslint/twin-ui.js` 在页面和功能代码里报错（中文提示应改用的组件）：手写 `button/input/select/textarea`；`style` 属性；className、`cn()` 参数和类名常量里的任意值 `xx-[..]`、十六进制颜色、字号类 `text-xs…3xl`、圆角类 `rounded-*`。这些目录豁免（原因写在 `eslint.config.js`）：`components/ui`（设计系统本身）、`components/motion`、`components/effects`、`components/reactbits`、`features/avatar`（插画与 3D 形象）、`features/profile/graph`（画布图谱）、`features/chat/ChatStage.tsx`（聊天舞台：高度、肖像尺寸、呼吸缩放和说话光环逐帧跟随弹簧和音量，写在 style 里的 motion 值）、`test`。页面代码里的 `eslint-disable` 不生效（`noInlineConfig`），例外只能写进配置。

`design/tokens.css` 的 `@theme` 收窄了 Tailwind 尺度：颜色只有令牌色（无调色板）、圆角只有 sm/md/lg/full、字号只有上表 8 档、间距只有列出的档位（`--spacing` 置空：0–16 按 4px 递进，另有 7/9/11/18/20/24/28/32/40/48/52/56/60/64/80 作尺寸用；`p-13`、`rounded-xl`、`text-4xl`、`bg-green-500` 这类越界类不会生成）。比例宽度用分数类（`max-w-17/20`）。缺档位时先确认设计需要，再在 `@theme` 和 `lib/utils.ts` 的 tailwind-merge 配置里一起加。

新增组件放在 `components/ui`，参数用语义（tone/size/variant/gap），在 `pages/GalleryPageKit.tsx`（`#/gallery`）展示。

## 截图对比

`frontend/e2e/pages.spec.ts` 对团队、录音库、待处理（列表和逐个听）、承诺、系统设置、录音详情、聊天、成员页、记忆、登录等页面（登录另有海蓝、墨夜两张，团队另有墨夜一张），在 1280×800 桌面和 375×812 手机上整页截图，逐像素对比 `e2e/__screenshots__/` 里的基线。页面读的是构建产物（`e2e/serve.mjs` 提供 `src/twin/web/static`），所有 `/api` 由 `e2e/mockApi.ts` 返回虚构的固定数据；没有 mock 的请求或页面报错都会让测试失败。时间固定为 2026-10-17 10:00（Asia/Shanghai），减少动态效果并关闭动画和光标。

```sh
./scripts/screenshots.sh                      # 先构建，再在 mcr.microsoft.com/playwright:v1.63.0-noble 里对比
./scripts/screenshots.sh --update-snapshots   # 有意改变外观后重新生成基线
./scripts/screenshots.sh -g chat              # 其余参数交给 playwright test
```

在固定镜像里跑，字体和渲染与机器无关：同一套基线在 arm64（本机）和 amd64（CI）上逐像素一致。需要 Docker；`check.py --full` 和 CI 都会跑。只有有意改变外观时才更新基线，逐张看过新图后与代码一起提交；对比失败时实际图和差异图在 `frontend/e2e/.results/`（CI 上传为 screenshot-diffs）。

## 动效与 React Bits wrappers

`frontend/src/design/motion.ts` 统一弹簧及退出时长：

| 预设 | stiffness / damping | 用途 |
| --- | --- | --- |
| snappy | 520 / 38 | 按钮、开关 |
| gentle | 260 / 30 | 页面、列表、对话框、进度 |
| bouncy | 380 / 18 | 点缀反馈 |
| layout | 420 / 40 | 重排、侧栏、导航与通知 |

quick/page/dialog 退出为 120/160/180ms，默认 crossfade 150ms。`useMotionPreset()` 实时响应系统减少动态效果：关闭位移、缩放、拖动、共享布局、shimmer 与眨眼，仅保留淡入淡出/立即更新。聊天头像在减少动态效果下关闭光环动画，仅保留静态说话圆点；语音仍按音频结束顺序推进。

**3D 形象微动**（`features/avatar/motion.ts`，状态取自 `PresenceState`）：眨眼间隔在 2–6 秒间随机，约 15% 为连眨；思考时每次先等 0.2–0.7 秒，再把视线和头部移向上方或侧上方，保持 1–2 秒后用 0.9–1.8 秒缓慢移回，下一次间隔 1.2–4 秒，所有时长每次重新抽取，没有固定周期（依据会话中的认知性视线回避研究：Andrist 等，IVA 2013、HRI 2014）；回答一开始，视线 0.4 秒内回到用户。倾听时只保留很小的眼跳，胸口向用户前倾约 3°，头部回仰其中约六成，脸基本保持平视。说话沿用口型与轻微点头。减少动态效果时只保留稀疏的单次眨眼和口型，不前倾、不转头、不移开视线。聊天舞台的大头像会随状态实时运动，列表里的小头像只渲染一帧；肖像照片不做任何假口型。`#/gallery` 的“形象对比”可切换四种状态查看（需配置 VRM）。

**路由过渡暂不使用 React `<ViewTransition>`**（2026-10 评估）：React 19.3.1 已稳定导出 `ViewTransition`，`HashRouter` 也已把导航包在 `startTransition` 里，技术上包住 `<Outlet>` 就能生效。暂不升级的原因：一是 `?section=` 这类页内切换同样是导航，会让整页交叉淡入，正属于“小而频繁的交互”，需要另外按路径过滤；二是页面懒加载，Suspense 骨架到内容的切换也会被截图过渡，和页面里 Motion 的入场动画叠在一起；三是注意力第一：切换页面时用户的注意力已经在目标页，150ms 的整页淡入不帮助聚焦，却要为此升级 React 小版本（19.3 的 transition 改为分开渲染，会影响懒加载时序）。以后若要加，只用于路径变化，不用于对话框、标签切换和设置层，减少动态效果时关闭 `::view-transition-*` 动画，并且不要同时给 `Link` 加 `viewTransition`，否则会出现两套过渡。

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

## 登录与认证边界

本机默认 `[auth].enabled = false`，所有请求为管理员；团队部署启用 auth，不依赖 Cloudflare Access，也不读取 `Cf-Access-*`。登录方式由 `[auth].provider` 选择，`password_login = true` 再并列 twin 自己的账号密码：

- **企业 SSO（主路径，`provider = "sso"`）**：借用同站另一个应用的会话 cookie，twin 带着它请求 `me_url`，200 为已登录、401 为未登录。身份取其中的 account（工号）、display_name 和 email；目前 SSO 只给 account，暂不给邮箱。工号和邮箱（有则）都是认领分身的依据（`Personas.claim`）。登录页上是“用享佳统一身份登录”按钮：表单 POST 到 `start_url`（那个应用的登录起点，它校验同站来源后跳往认证中心），没有 `start_url` 时链接到 `login_url`。两个地址都只能是本站路径。浏览器按 CSP `form-action` 检查表单的每一步跳转，所以 `start_url` 要和 `sign_in_origin`（认证中心的源）一起配置：twin 把它加进 `form-action`；缺了 `sign_in_origin` 时 `/api/auth/methods` 不给 `start_url`，按钮退回链接。
- **twin 账号密码（`password_login = true`，或只用它时 `provider = "password"`）**：账号由 `twin account` 命令行管理，身份为 `user:<账号>`；同时带着 SSO cookie 和 twin 会话时以 SSO 为准。
- **邮箱验证码（备选，`provider = "email"`）**：应用内验证码登录，身份就是邮箱。SMTP 设置、环境密码、隧道与 allowlist 部署步骤见 [使用指南](GUIDE.md#团队部署与登录)。

`AuthGate` 先读取 `/api/whoami`，`401 {code:"login_required"}` 时显示 twin 自己的登录页，不再跳往别的页面；登录页读 `/api/auth/methods` 决定显示哪些方式（读不到时按只有邮箱处理）。有统一身份或账号密码时标题为“登录 twin”，统一身份按钮在上为主操作，下面“或用 twin 账号登录”；只有邮箱时标题为“用邮箱登录”。有统一身份时，统一身份按钮下面是“或用邮箱验证码”和已展开的邮箱输入，账号密码仍在“或用 twin 账号登录”后展开。账号输入 autocomplete=username，密码 type=password、autocomplete=current-password，登录成功进入团队页。邮箱输入 type=email、autocomplete=email，16px；获取验证码后显示 6 位 inputmode=numeric、autocomplete=one-time-code 输入，支持粘贴和前导零。“重新发送”按实际截止时间倒计时 60 秒，“换个邮箱”返回。未允许用户看到“已加入等候名单”、邮箱与“开放后会第一时间通知你”，不显示验证码输入。错误使用中文普通文本。登录页左侧（手机为顶部色带）是舞台：标语“最懂你的，是另一个你。”、一句说明（手机隐藏）和“个人分身 → 超级个体 → 超级组织”演进线；右侧是登录方式，没有配色选择（配色在登录后的账户菜单里）。

会话只用 HttpOnly cookie，前端不存 token。普通 API、媒体 fetch、分片上传及资产 XHR 遇到 login_required 时清空当前身份和分身内存状态、卸载内容并回到登录；切换页显示小号账号和“退出登录”，任何登录方式都显示；退出时 `/api/auth/logout` 同时清掉 twin 会话和 SSO 会话 cookie（`Path=/`），回到 twin 登录页。身份恢复后先加载可见分身，再挂载页面；no_persona 对带企业账号（邮箱或工号）的成员先进入“会议里找自己”（`MemberVoice`），可跳过，再显示新建分身流程，不回退 default；过期的 persona 404 会重新加载列表并选首个可见分身。`/api/whoami` 另带 `address`（企业邮箱）和 `account`（工号）。

| 方法/路径 | 契约 |
| --- | --- |
| `POST /api/auth/request` | `{email}` → `{status:"code_sent"}` 或 `{status:"waitlist"}`；邮件只含验证码，无链接 |
| `POST /api/auth/verify` | `{email,code}` → `{email,admin}` 并设置 twin_session cookie；代码 10 分钟有效，5 次错误后销毁 |
| `GET /api/auth/methods` | 未登录也可读：`{sso:{start_url,login_url}|null, password, email, team_name}`，登录页据此显示方式；团队有名字时，登录卡片上方多一行“邀请你加入 团队名” |
| `POST /api/auth/password` | `{username,password}` → 身份并设置 twin_session cookie；错误统一为“账号或密码不对”，同一账号 15 分钟 5 次、同一地址一小时 30 次失败后 429 |
| `POST /api/auth/logout` | 删除服务端会话并清 twin_session；SSO 下同时清那个应用的会话 cookie（`Path=/`） |
| `GET /api/whoami` | `{email,admin,auth_enabled,features,team_name}`；启用登录且未登录返回 401；`team_name` 是系统设置里的团队名，侧栏和首次进入页的顶部读它，没设置时显示“我的团队” |
| `GET /api/admin/waitlist` | 仅管理员，`[{email,created_at}]`（Unix 秒时间戳）；添加允许邮箱需改配置并重启 |

启用 auth 时 `/api/*` 除 auth 路径和 whoami 外全部需会话，包含媒体 GET/HEAD；静态页面公开，API 无登录返回 `401 {detail:"请先登录",code:"login_required"}`。所有写请求仍必须带 X-Twin。`auth.db` 权限 0600；验证码仅存带随机盐哈希、expiry 和 attempts，会话仅存 32-byte 随机 token 的哈希、email 与 expiry，过期行按请求清理。发送限流每邮箱 60 秒一次、每小时 5 次，每客户端 IP 每小时 20 次；SMTP TLS 连接，测试只使用 mock。

## 多分身

`stores/personas.ts` 管理列表及当前 ID；`lib/persona.ts` 对 localStorage 读写使用 try/catch，禁用存储仍可切换。
`api()`、资产 XHR、原始媒体 fetch 均带 `X-Twin-Persona`；图片、VRM、声音参考、音频、视频和下载 URL 使用 `personaUrl()` 添加 `?persona=<id>`（已有 query 则追加）。
切换按 ID 重挂载路由树，无整页刷新；停止音频/视频、取消旧请求、重置 status 并重新读取所选分身。
聊天 sessionStorage、视频结果/提交缓存、任务记录、问卷离页写队列和上传 localStorage 续传记录均按 ID 隔离；保留默认分身旧键，旧数据无需迁移。
离页问卷写入和仍未返回的视频提交保留原分身归属；服务端已接受任务继续运行，返回该分身后恢复查看。

“新建分身”就地询问名字（只问这一次），不离开当前页面，输入时头像位显示名字的第一个字；本人还没有自己的分身时预填账号名字，表单下方提示“下一步：加一段会议录音，勾出哪位是你。”。团队页没有录音时，是“从一段会议录音开始”：拖放区、三步说明和“请同事来认自己”（复制站点地址）；没有分身的人要建分身，在团队页的“添加 → 新建分身”、聊天里的分身切换面板就地建；没有分身时打开对话，工作台和导航保持原样，内容区就是“先新建一个分身”和这张表单，侧栏当前分身的位置是虚线空位，点它也是新建。背后有正在看的内容时才用小卡片：电脑上从侧栏 ＋ 旁弹出（弹出时 ＋ 的提示收起），切换面板里的“＋ 新建分身”在当前页中间弹出，手机上从底部弹出，背后的页面只变暗不模糊。

创建后自动切换并打开它的聊天，侧栏照常显示，没有整页引导。聊天空白处是设置卡片“让<姓名>认识你”（`features/setup/SetupCard.tsx`），三步：① 加一段会议录音（拖放或选择文件，转写在后台；“没有录音？写一段或上传文档”就地展开文字框，文档也可直接拖进来）；② 勾出哪位是你（转写好后就地列出说话人：试听按钮、“说话人 N · X 分钟”、一句最长的发言摘录、“是我”，下面“都不是我”；不区分说话人的转写给“整段都是我”）；③ 整理记忆（进度条）。卡片底部“还可以：一句话介绍自己（就地小卡片，只改介绍）· 形象和声音（档案）”。记忆整理好后记下引导完成（`POST /api/identity/onboarding-complete`），卡片收成一行绿色提示“<姓名>已经记住 N 条关于你的事 · 来自「…」”和“看看记了什么”，下面三个试问芯片，点了直接发出。卡片在本次访问里一直留着，直到开始对话。新分身（`onboarding_pending`）或没有任何资料的分身显示这张卡片；管理员按邮箱或工号批量建、或由会议生成的分身不显示。
“管理”复用 PUT identity 重命名并保留介绍；删除二次确认，默认分身不显示删除，运行/排队任务或请求存在时服务器拒绝删除。
列表恢复时若所存 ID 已被删除或不可访问则选择首个可见分身；管理员优先 default。成员没有分身时：企业账号先进“会议里找自己”，其余直接打开新建流程。成员能看到自己建的、认领的和别人公开的分身；认领来的分身先显示认领页（见下节，在 `#/welcome`），点“没问题”或“稍后再说”之前，其他页面都会回到它。只有默认分身可回退到 `[avatar].image_path` 和视频驱动内置素材；
其他分身需自己的肖像和声音才能生成真人视频，否则能力包含 `reason: "先在「关于你」上传形象和声音"`，语音使用 `[tts].voice`。

## 插画形象与图谱

档案「形象和声音」提供「选择插画形象」：栗、澜、禾、石、岚五个圆形缩略图，选中项以各自 accent 色描边；移动端单行横向滚动。照片或 3D 模型存在时折叠到「没有照片时使用的插画形象」。保存期间禁用选择，完成后 toast 提示并立即更新档案头部和分身列表。无照片的舞台、聊天、切换栏和分身卡片均显示该分身的预置。

`features/profile/graph/fit.ts` 在布局停止、筛选或画布尺寸变化后拟合实际布局坐标；节点半径和固定像素标签一起计算边界，最大投影跨度约为画布较短边的 85%。2D 求缩放和平移，3D 按当前视角求透视相机距离与目标点，避免全局最长标签 padding 使图谱缩小。中心节点没有照片时将相同预置 SVG 栅格化到画布/CanvasTexture；图像失败保留首字回退。

## 音视频人物确认

记忆页有 `needs_speaker` 来源时显示“有 N 段录音需要确认哪位是你”紧凑横幅，点开第一条；列表显示“待确认”芯片。媒体详情提供说话人行（编号、时长、轮换短片段试听、建议者“像你”、单选）和“都不是我（旁观资料）”。只有一人自动确认，多人高置信度自动识别显示“已自动识别，可修改”，其余来源在确认前不进入记忆构建。修改后自动重新整理，详情文字同步更新。

确认后显示最多 3 个声音候选播放器和“用这段做声音”，最多 6 张形象候选缩略图和“用这张做形象”；后台提取时轮询进度，采纳后 toast 通知并触发与手动上传相同的资产刷新/缓存失效事件。API 契约见 [MEDIA.md](MEDIA.md)。单选、按钮至少 44px 触控区，输入 16px，播放器不自动播放。所有请求带当前分身，试听/候选 audio/img URL 使用 `personaUrl()`。

档案“形象和声音”在本分身已有候选时显示“从你的视频里挑一个”，打开同一候选选择器，仍可正常手动上传。

## 页面

侧栏从上到下为团队、对话、录音库、待处理（数字）、承诺（可被管理员在系统设置里关闭），访客只有对话；手机底部是聊天、档案、承诺。

| Hash 路由 | 功能 |
| --- | --- |
| `#/team`（管理员、成员的默认页） | 团队：“成员”标签是一张表（成员、录音、分身、最近、操作；最近是 TA 最近一场会议的日期和标题，看得到的录音里取，没有就是“—”），每行一人，按名字找人，按“可以聊 / 整理中 / 没有分身”筛选，数字前端算；录音库里认出的人、自己建的分身和别人公开的分身并在同一张表，点名字去成员页（自建的分身在录音库里也有一个人，名字下一行是 TA 介绍的第一行，没有录音；自建的分身名字和会议里某个人相同时，不按名字合并，这一行的“⋯”里由建的人确认“是会议里的人 / 不是同一个人”）；别人公开的分身，表里也能直接“聊天”；有分身的行是“聊天”，没有分身的是“生成分身”（为还没有分身的人填企业邮箱或工号，可空着；同一个邮箱或工号只能用在一个分身上），其余在“⋯”（编辑名字和性别、声线和抽查、企业邮箱或工号、删除）；每个分身标出“等 X 登录认领”“已认领”或“X 说不是 TA，换一个”；转写显示细进度条。表头右上的“添加”菜单是“添加人物”“新建分身”和“按邮箱或工号建分身（N）”（一次为多人填完企业邮箱或工号并批量生成）。“已删除”标签列出 7 天内删除的分身，可恢复，没有删除的分身时不显示这个标签。待处理已经是 `#/inbox`，团队页旧的 `?tab=todo` 跳过去（保留 `cat`）。没有录音时保留上传引导（有没有分身都一样）。访客默认进 `#/chat` |
| `#/team/<人的编号>`、`#/team/twin/<分身编号>` | 成员页：前者是录音库里的人（`people.id`，自己建的、别人公开的分身也有一个人），后者是分身自己的地址，名册里有对应的人时自动跳到人的编号（名册读不出来或还没有人，如分身还没起名，就留在原地）；进页时先切到这个人的分身，再读它的内容。页头是“团队 / 名字”、头像、名字、分身状态、一行介绍，右边“和某某聊天”和“⋯”（编辑、接入、别名、外部服务、设为公开或私有、删除分身，默认分身没有删除）。标签：档案（九个方面，每条记忆一行，“改”和“⋯”里的依据、删掉、恢复原样）、记忆（来源、上传、图谱）、你不在时（只有本人看到，数字是等你决定的条数，也显示在侧栏账户上：“等你决定”是同事的问题里分身留给本人的部分——要决定、要答应、涉及评价、资料里没有，一行一个，第一条展开着，显示分身答了什么；要答应的事带“待接承诺”，可“接下 / 改时间 / 不接”，输入框里的话发到提问人的对话并存进记忆，“请分身起草”把分身按本人记忆写的草稿放进输入框（要本人定的地方留着“【请你定：…】”，改完才发得出）；“⋯”里“不答”；其下“分身推测”是分身对同事猜着答的，可“没错”或“⋯ → 更正”，“有出处”折叠着只给个数，近 7 天；已不答、过期和处理过的折叠在“已处理”里，不答和过期的可放回）、承诺（账本组件嵌入，功能开关关闭时不显示）、形象和声音。“本人”是认领了这个分身的人；没有登录功能的本机，默认分身算本人。别人的公开分身没有标签和“⋯”，只有名字、介绍和“和某某聊天”。录音库里的人还没有分身时，页面是参加过的录音和“生成分身”。人和分身找不到时回到团队页；访客进不了这些地址 |
| `#/twins` | 重定向至 `#/team`：自建和别人公开的分身是团队表里的行，重命名、公开和删除在成员页的“⋯”，新建在“添加”，7 天内删除的在“已删除” |
| `#/voice` | 会议里找自己（`MemberVoice`）：企业账号读一句话，听团队库里像自己的声音，每条只给一句话、会议标题和日期，回答“是我”或“不是”；确认后用这些发言建自己的分身，之后可再来补充。没有企业账号（邮箱或工号）时 404；没有分身的企业账号在聊天等页面会先到 `#/welcome` 的这一步（顶部“1 认出你自己”和“稍后再说”），可跳过 |
| `#/library` | 录音库：只有标题，没有容量、排队和说明（容量在系统设置的“录音库容量”）。全部/待确认/处理中/失败分类及数量，右边按标题或参会人找录音；每行是标题、日期·时长·说话人数、参会人头像（没认出的是一个“?”）和一个状态：待确认是“认 N 位说话人”（进入录音认人），认完是“都认出来了”，转写中是进度条，失败是“重试”；“⋯”里是回到上一版转写、重新采集（有新版转写可用时，需确认）和删除（需确认，删了不能恢复）。有可重新采集的录音时，页头“⋯”可一次选多份；已申请的在“处理中”里标“重新采集中”。额度用完、转写没配好两条提示保留。上传在侧栏，整页拖放照旧；没有侧栏的手机上页头有“上传录音”。空库保留引导 |
| `#/inbox` | 待处理：标题右边是已认出的发言占比和“列表 / 逐个听”。类别用胶囊标签，空的不显示：新的声音、还没认人、转写失败、可能是同一个人、有人说不是自己、分身被退回、零碎片段、有空再看（`?cat=`）。新的声音一行一个声音：试听、名字（会上被叫作的名字、声音像的人，都是按钮，最有把握的突出）、认不出时是输入名字的框，“⋯”里是其他人、换一段、打开录音、不在团队里、几个人混在一起；先显示 20 个，“像已经够建分身的人”和“像你标过不认识的”折叠在后面。点了以后这一行先变成“已归给某某 · 撤销”，5 秒后才告诉服务器（`features/inbox/useDeferred.ts`）；撤销不发请求，离开页面（含关闭标签页）前把没发的都发出去，一串答案依次发、最后只重新加载一次。零碎片段、可能是同一个人的合并和“不是同一个人”同样延迟提交；删除录音仍要确认。“逐个听”（`?view=focus`）只走新的声音：一个大的试听、候选人的对比听和“是某某”、输入名字、跳过；全程可以只用键盘：空格播放，← → 换一段录音，1 2 选候选，S 跳过，N 输入名字，U 撤销上一个，Enter 确认有把握的那个，“?”悬停看快捷键。录音页确认完说话人回到这里，键盘落在下一行 |
| `#/commitments` | 承诺：页头右边选人（同聊天里的选人），下面是这个人分身的承诺账本，和成员页“承诺”标签是同一个组件（`Ledger`）；功能开关关闭时去聊天。`#/ledger` 跳到这里。访客进不了 |
| `#/library/<录音 id>` | 一次确认一位说话人：单播放器与片段切换、声纹候选选择或新建人物，确认后聚焦下一位；手机底部固定确认与声纹样本控件；接下来与已确认列表分开，已确认可“改”重新处理；全部完成提示回团队，底部可展开完整转写稿；团队任务确认后返回团队 |
| 认领页（`Claimed`，在 `#/welcome` 的第二步） | 登录后有分身是给本人建的（邮箱或工号对上）或本人在会议里认出自己声音建的、本人还没点“没问题”时，代替整个界面显示，顶部是“1 认出你自己 → 2 看看你的分身”和“稍后再说”（先进应用，分身仍未确认）：标“已归到你名下”，列出这个分身从会议整理出的你答应过的事（至多 3 条）和最有证据的 3 条画像，可点三个示例问题去试聊；底部勾选“同事能问我的分身”（默认勾上），点“没问题，开始用”记下 `approved_at` 并进入这个分身的成员页（`#/team/twin/<分身编号>`）；点“这不是我”（只对别人建的分身，二次确认）把分身退回；自己在会议里认出声音建的则给“回去再听一遍”链接到 `/voice`。有多个待认领的分身时先处理第一个。点示例问题会跳到聊天试聊：顶栏出现“试聊中：你点“没问题”之前，同事问不到它。”横幅和“回去确认”按钮，只在聊天页显示，点“回去确认”回到认领页 |
| `#/chat` | 多轮聊天、文件附件问答、依据、内联语音与真人视频；无日期输入或资料截止提示 |
| `#/profile`、`#/memories`、`#/about`、`#/sources`、`#/persona`、`#/identity` | 重定向至当前分身的成员页，保留 `?section=` 和 `?view=`（`#/memories`、`#/sources` 去“记忆”标签，其余去“档案”）：认得出的人去 `#/team/<人的编号>`，其余去 `#/team/twin/<分身编号>`；没有任何分身时去 `#/team`。旧的 `?section=channels` 打开“接入”设置，`?section=questions` 去“你不在时”（不是本人时去“档案”），`?section=graph` 去“记忆”的图谱 |
| `#/questionnaire` | 可选问卷，关于你中的“回答几个问题”链接；不在主导航中 |
| `#/gallery` | 开发组件与动效画廊，仅通过 URL 访问 |
| 任意页面 `?system=<分区>` | 管理员的「系统」弹窗盖在当前页上：监控、GPU 服务、向量服务、ASR 转写、TTS 朗读、视频服务、模型与 Token；关闭后去掉参数、回到原处 |

「系统」是管理员的弹窗（`features/admin/SystemDialog.tsx`，外壳是 `components/ui` 的 `SettingsDialog`），从侧栏左下角账户头像展开的菜单里点「系统设置」（手机上在分身切换面板里的“系统”）打开，打开的分区记在地址的 `?system=` 参数里，关闭后回到原页面，输入和滚动位置都在。服务的运行状态、开关、模型、密钥是否设置和 token 额度都只在这里，不进业务页面。「监控」里的「Token 用在哪」按用途列出最近 24 小时所有大模型调用的次数和 token（聊天回答、抢先重发、聊天的各个辅助步骤、录音校对、从发言辨认说话人、整理记忆、承诺账本、工作模式），来自 `twin ui` 写在数据目录 `usage.db` 的按小时汇总：只记用途、模型名和数字，不记内容，保留 90 天；提供方没报用量的调用（例如抢先重发后被关掉的那一份）单独计数。管理员登录后，`stores/system.ts` 每 60 秒读一次 `/api/admin/system`；开着的服务检查失败时，账户头像、菜单里的「系统设置」和弹窗里对应分区各显示一个红点，除此之外不打扰。「团队」里填团队名（20 字以内，保存后侧栏、首次进入页和登录页立即换上，清除后回到“我的团队”）、朗读和视频开关、「功能」里的工作和承诺账本开关（聊天始终开启）、token 额度、「录音库容量」只读显示排队了多少、还能放多少（读 `/api/library`，满了在菜单里标红）；「系统参数」里录音库的排队上限、磁盘余量和失败原件保留天数、文字模型和向量模型的地址与模型名、密钥改完立即生效，所有分身一起；改模型和密钥藏在“修改地址和模型”“设置/更换”按钮后面，密钥输入框从空开始、保存后不再显示。其余配置只读，改 twin.toml 后重启。「部件升级」集中管理新版本带来的升级：记忆内核（抽取与合并提示词、记忆分类）逐个分身列出记忆按哪个版本整理、待重新整理多少段，可单个或全部升级（全部升级前确认，会调用模型；分身轮流整理，整理完成前沿用旧档案），自动升级开关和自动升级上限也在这里；承诺账本抽取列出各分身还没按当前规则读过的会议，可单个或全部整理；录音库的自动归属和片段复核规则只显示版本，启动时自动重判。这一页打开时才读取（要打开每个分身的记忆库），不轮询；有升级在跑时每 5 秒刷新。记忆页不再放升级按钮：记忆按旧内核整理时只留一行说明，管理员看到「去设置里升级」。

工作台首次读取 identity 只为判断有没有分身（`no_persona`）；认识新分身的步骤都在它的聊天里（见上文设置卡片），不再有整页引导。

名字保存到 p_meta 的 identity:name，介绍保存到 identity:about；有效名字为用户保存值，否则为配置 target_name。用户保存的名字也参与说话人匹配，配置名字与别名仍有效。介绍设定或变化时，事务内替换标题为“自我介绍”的笔记，并触发自动处理；清空介绍删除旧笔记。单独改名字不重复添加笔记。

对话页是三块：左边宽 280px 的列表（浅色纸面，左上圆角 16px），中间对话，右边可选的形象。列表最上面是**选人**：头像、姓名、箭头，打开 PersonaSwitcher（只在对话页出现；页面里选人只有这一处，列表收起或手机上才换成页头的头像，用的是同一个 `features/chat/PersonPicker.tsx`）。下面是“新对话”和搜索，列表按今天/更早分组，对话和任务一起按最近使用排，任务在标题下标“任务”；每行的“⋯”里是重命名、删除（任务只有删除，在做的任务不能删），底部“显示更多”。桌面 ≥1280px 默认展开，较窄窗口默认收起；`stores/chatLayout.ts` 安全保存 `twin:chat-layout` 中的 sheet/stage 选择，存储不可用时退回本次会话状态。页头是姓名（管理者点它去成员页）、对话标题和“⋯”（语音、形象）。移动端顶栏保留列表、头像、姓名与状态、“⋯”、新对话；消息区滚动，输入框留在底部。

页面由两个线程组件和一个外壳拼成：`features/chat/ChatThread.tsx`（问答：消息、依据、朗读和复制、附件、输入框）、`features/work/WorkThread.tsx`（任务：进度、文件、停下和插话）、`pages/Chat.tsx`（选人、列表 `features/chat/SessionList.tsx`、页头和形象）；朗读与视频状态在 `features/chat/usePlayback.ts`，任务状态在 `features/work/useWork.ts`。输入框里“问答 / 交代任务”选一个：问答发给分身聊天，交代任务开一个任务（地址 `#/chat?mode=task`，旧地址 `#/work` 跳到这里）。管理员关掉“工作”功能后不显示这个切换，`mode=task` 也只显示问答。切换时输入框里已写的字跟着过去；从列表里点任务或对话，页面就切到对应的一种；在做的任务行标“任务 · 在做”，选了“交代任务”时列表顶上的“新对话”叫“新任务”。访客同样有这个切换（功能开着时）。

形象默认关闭，页头“⋯”里点“形象”打开白色聊天面板内的右侧 340px 强调色舞台（圆角 20px）；关闭按钮回到纯文字对话。手机及较窄窗口中形象浮在对话上方，避免挤压正文。复用 ChatStage 的肖像、PresenceRing、字幕和视频播放。现有语音能力是回答朗读，不是麦克风双向会话；页头“⋯”里的“语音”播放最近回答，开始朗读时自动打开舞台，未配置朗读或没有回答时禁用。形象选择与列表选择独立记忆。

消息与输入框共享居中的 720px 内容列。分身正文为 16px / 1.75，无气泡；用户消息右对齐，canvas 底、18px 圆角。回答下面一行：左侧是回答类型的徽章（“有本人资料支持 · 2”“资料不足，需要问本人”等），右侧是用时、朗读和复制。徽章后面有东西可看（引用的记忆和原话，或没有作答的原因）时是个按钮，点一下就在回答下面展开一层：引用的每条记忆一张卡，本人可以直接“改一下 / 删掉”，访客只看；再点收起。没有侧边的依据层。操作在悬停或聚焦时显示，最后一条回答和触屏设备常显；没有反馈接口时不新增反馈入口。`verified=false` 不显示徽章，只有一个“⋯”，点开说明无法核对。空对话显示 64px 头像、“和<姓名>聊聊”、身份接口的真实简介与输入框；无简介则省略。只有设置卡片在记忆刚整理好时给三个固定的试问芯片，平时不放示例问题；对话列表为空时写“还没有对话，问<姓名>点什么吧”；sources 包含文档，不能当作录音段数，因此省略录音计数，只显示真实的思考/说话状态。

输入框是 20px 圆角、边框和轻阴影的 UI 组件，至少两行；下面一行是左侧“+”附件和右侧圆形发送按钮。格式与容量提示只在附件的 Tooltip/aria-label 中显示。新增半径档位 `bubble=18px`、`chat=20px`，另为导航宽度 68px、列表 280px、舞台 340px、正文列 720px 和发送按钮 34px 定义布局令牌；文字与颜色使用现有令牌，组件展示在 `GalleryPageKit`。

聊天继续使用 MessageList、MessageText、TypingIndicator 与 Textarea；Enter 发送、Shift+Enter 换行，IME 安全。通过 fetch 读取 `POST /api/persona/chat/stream` 的 SSE，首个 delta 后隐藏思考指示，final 用校验后的正文替换并附加依据；`stale` 与 `error` 撤回回答并恢复输入。对话由现有 conversations API 保存、恢复和分页，旧 sessionStorage 记录继续迁移。新对话立即清空且不删除历史；离页、切换分身或新请求取消旧流。进入/发送时检查记忆状态。聊天请求不包含截止日期，advanced as_of 只保留在服务 API/MCP 和评测。

聊天输入框支持最多 5 个可提取文字的附件，单文件和单次总量均不超过 50 MiB，提取文字合计最多 200 万字符；支持 TXT、Markdown、PDF 文字层、Word、EPUB、HTML、CSV、JSON、SRT、VTT，不做 OCR。附件经 `POST /api/persona/chat/stream-with-files` 作为 multipart 本轮上下文处理，不写入 PersonaStore、不触发档案重建；后端按当前问题选取有限摘录，文件引用以“附件名 · 摘录 N”显示。原文件不保存，但回答和引用摘录随对话记录保存；后续追问需重新附加。附件内容会发往配置的聊天模型，界面对此有提示。没有档案时，带附件的聊天仍可依据文件内容回答。

肖像仅在身份区域和可选形象面板显示，不在每条回答旁重复。`features/chat/ChatAvatar.tsx` 优先级为 **肖像 > VRM 静态预览 > 分身选中的插画形象**；图片或模型失败继续回退。朗读入口沿用媒体能力判断，视频仍沿用现有非弃权生成规则。

`features/chat/useReplyAudio.ts` 管理全聊天唯一的语音播放状态。新回复收到 final 后，非弃权且语音可用时立即启动朗读，在真人视频生成期间由肖像显示说话状态。自动朗读或点击“播放”先 POST `/api/media/audio`，带 `segments: [0]`，首段返回并解码后立即播放；其余脚本段最多两个并行请求，提前下载、解码，严格按脚本段及段内分片顺序播放。`GaplessAudio.ts` 用 Web Audio 时间轴连续排程，就绪分片之间无额外停顿；不支持 Web Audio 时回退 `<audio>`。分片未就绪时等待，返回后立即继续；重复播放复用回复缓存、解码缓冲和服务端原有缓存键。ARIA 名称为“播放语音”/“暂停语音”。暂停保留分片与时间，开始另一条回复先停止前一条。回复下方细进度线按分片时长和播放时间累计（剩余时长未齐时估算）；当前头像复用 `features/avatar/SpeakingGlow.tsx` 的弹簧光环，强度取当前分片播放时间 × lipsync.fps 的 level，不伪造嘴部。暂停、等待或结束时光环淡出，减少动态效果时仅显示静态说话圆点。错误显示回复内的中文小字，可再次点击“播放”；离页、清空和卸载停止音频并释放请求与 rAF。聊天仅保留原生按钮键盘行为，不提供逐句导航、快捷键帮助或 HTML/2D 片段导出入口；相关后端接口保留供 API/CLI 使用。

可选 3D 预览由 `features/avatar/AvatarPreview.tsx` 统一选择并通过 React.lazy 加载 `Avatar3D.tsx`，props 为 `{url, mouth, speaking, onFallback}`。组件使用 GLTFLoader / VRMLoaderPlugin、头骨摄像机取景、令牌三点光、临界阻尼口型和头动、眨眼/lookAt 与模型 SpringBones；署名来自模型元数据。关于你页保持闭口，仍按 VRM > 肖像 > 2D 选择；画廊“形象对比”并排展示 2D/3D，共享演示口型轨和重播按钮。聊天的 VRM `still` 模式仅渲染一帧，不启动眨眼、头动或口型循环。离屏/隐藏停止 rAF，卸载销毁渲染器和模型资源；失败先回退配置肖像、再回退 2D，MP4 导出仍为 2D。CSP 的 img-src 允许 blob: 加载内嵌纹理，media-src 允许本地与 blob: 录音回放；配置与许可注意事项见 [MEDIA.md](MEDIA.md#浏览器-3d-形象v1)。

记忆页（`Memories.tsx`）有“写一段”“上传文件”“上传文件夹”三个标签，不选择类型或日期。支持 .txt/.md/.pdf/.docx/.epub/.html/.htm/.csv/.json/.srt/.vtt，每文件最多 1 GB；PDF 只读文字层，不做 OCR。文件夹以相对文件名发送，服务端只保存 basename，隐藏文件和未知格式显示跳过原因。添加后提示“已添加，正在记住…”。同一文件选择器还接受音频/视频（≤4 GiB），走 `lib/mediaUpload.ts` 而非文档 multipart 路径；顺序 8 MiB 分片、网络/5xx 指数退避、409 按服务端 offset 重同步。断网暂停，online/页面可见时唤醒；localStorage 仅保存 id/name/size/lastModified，刷新后重选同一文件继续。显示文件名、百分比与 MB 和“上传中，请保持页面打开”，16px 文件输入、44px 点击区域，适配 iPhone 底部标签布局。

记忆列表用 MessageList 展示标题、可选日期（无日期不显示前导分隔符）、笔记/文档/聊天记录/问卷/访谈和状态：正在记住…（ThinkingLabel）、已记住 N 条、没找到关于你的内容、处理失败＋重试。“查看”打开只读 Dialog，展示隐私视图的前 20000 字；“删除”通过 ConfirmDialog 确认，成功后自动重新处理。页头显示精简处理指示，非 idle 时每 2 秒轮询 processing 与列表；只在 last_error 存在时显示小的“重新处理”，无构建卡片或构建汇总。离页清理请求和计时器。媒体行另有音频/视频图标、时长、等待转写/提取音频/转写中 x/y 分钟/整理中/已加入/失败状态；未配置 ASR 显示“需要配置语音识别”，可点“重新转写”。媒体任务未结束时也每 2 秒轮询列表，详情为时间戳转写正文。

成员页的“形象和声音”标签和“编辑”窗口（原关于你页）：编辑用名字与介绍的表单调用 PUT identity。其下「形象」可选择照片，在 3:4 框内拖动/双指缩放并用 XHR 上传；「声音」可录制（朗读提示、计时/音量、30 秒自动停、回放/重录/使用）或上传录音/视频，保存后可播放处理后的参考 WAV，有语音服务时自动准备试听。两者均可恢复默认，上传时禁用按钮并显示进度，输入 16px、点击区域至少 44px。本人上传肖像优先；无上传时保留配置 VRM/肖像/2D 预览。聊天头像立即使用带 sha 版本的肖像 URL，声音变更清空客户端音频缓存。"我了解到的你"按九个口语主题分组：经历与身份、看重什么、怎么做决定、怎么思考、擅长什么、说话方式、和人相处、最近在关注、生活与喜好。条目抽出来就用，不逐条确认：顶部检索框按意思找记忆（`/api/persona/items/search`，和聊天同一套检索），结果和分组列表里每条都能“改一下 / 删掉”，改过的可“恢复原样”；只标“你改过”和“只有别人的说法”。有证据矛盾的条目时显示“有矛盾的 N 条”，想看再点。失败回滚并保留修改草稿。聊天回答的“依据”里，本人可以直接改或删引用到的记忆，访客只看依据。记忆条目上，只有本人能用的标“只有本人能用”，本人在“⋯”里“设为同事能用 / 设为只有本人”；管理员、建分身的人按同事档看，只看到同事能用的条目，也改不了档位。和别人的分身（本人已认领）聊天时，输入框下面有一行小字“本人看得到分身的回答”，自己和自己的分身聊天、没有本人的分身不显示。对话里“本人”的回复（轮次角色 `self`）在提问人的对话里单独标“本人”（左边一道细线，名字旁一个“本人”徽标），分身的回答在这样的对话里标“某某的分身”，被转给本人的回答下面一行“已转给某某本人 · 等回复 / 已回复 / 已接受 / 已拒绝 / 不答 / 已过期”（等回复时每 20 秒看一次，本人回了就出现在这条回答下面）；对话列表里最后一句是本人回复的会话，标题后面小字“本人已回”（接口 `owner_replied`）；本人的话不随下一次提问发给分身（分身从服务端按会话读到它，以它为准）。隐藏内部编号、比例、等级与来源矩阵。“这几个方面分身还不了解，或只提到过”从 coverage suggestions 映射为主题建议，去重后最多五条，链接到记忆。不再保留 Profile、Identity 页面和 CoverageOverview/虚拟档案列表。

成员页的 URL 参数 `?section=` 取 `overview`（档案，默认）、`memories`、`away`、`ledger`、`assets`，记忆标签的 `?view=graph` 是图谱；切换标签写进地址并回到页面顶部。成员页和旧档案页用同一批组件（`features/profile/`：`OverviewTab`、`MemoriesTab`、`AssetsTab`、`PersonaSettings`、`EditIdentityDialog`），记忆条目是一行的 `ItemRow`（聊天依据里改记忆和图谱的记忆卡片仍是完整的 `ItemCard`）；覆盖度分四档，叫“还不了解 / 提到过 / 了解一些 / 了解较多”，回答经过检查的细项在“了解较多”后面带 ✓（接口的 `checked`）；记忆条目上，只有本人能用的标“只有本人能用”，本人在“⋯”里改成“设为同事能用 / 设为只有本人”（只有本人看到全部记忆；管理员和同事看到的只有同事能用的那部分，也改不了）。

可选的“回答几个问题”有 20 题、九个日常主题，全部可以跳过，所有已答内容都成为记忆。按 API section 分组，用 FlowStepper 导航到首个未答组；跳过清空答案，空答案不计已答。草稿 800ms 防抖、版本化串行 PUT；保存回答等待草稿成功，确认说明记忆导入与替换。离页完成待写草稿，小于 60KB 时尽力 keepalive，不另存个人答案。仅未保存且写入中的离开才警告。没有轮次切换或重测入口。

关于你独立读取 identity 与 media capabilities；预览失败不影响名字编辑。小的“外部服务”区域读取 status.egress，仅列实际配置且外部的服务，用“大模型 / 向量 / 朗读 / 语音识别 / 视频生成 / 回答检查”和主机描述，不显示提供方 ID；不展示技术分类表。3D 署名仍来自模型元数据；形象闭口、减少动态效果不眨眼。

## 流式聊天延迟检查

`[chat_llm]`（未配置则 `[llm]`）的 `hedge_after_s` 默认 2.5 秒，0 禁用；首 token 未到时最多追加一个相同请求，先返回正文的胜出，另一个取消并关闭。OpenAI 兼容流式调用保留 extra_body，但不请求 JSON mode：正文之后是 `<<<META>>>` 独立行和元数据 JSON。缺少或无效元数据时保留正文，返回无引用、零置信度、`mode=general` 且 `verified=false` 的回答：不算弃权、不进待回答，回答下方不显示类型标签，“处理详情”说明无法核对（短寒暄最常缺元数据）；弃权原因也只在“处理详情”里显示；最终仍执行引用过滤、置信度上限、引号校验与原有聊天日志。核心画像不随检索问题改变，系统提示按同一分身的档案保持稳定。

运行 `uv run python scripts/chat_latency.py http://127.0.0.1:8765 --persona default`，打印五个问题的 first delta 与 final 秒数。启用登录时通过 `TWIN_SESSION` 环境变量提供会话 cookie；`--questions` 可传入五个自定义问题。脚本会产生普通聊天日志，不会验证真实回答质量；模型和网络延迟仍取决于部署。

## API 与任务契约

客户端只接受同源 `/api/`，非 GET 请求带 `X-Twin: 1`；全部分身数据请求带 `X-Twin-Persona`，GET/HEAD 支持等价 `?persona=`（header 优先）；管理员缺省选择默认；成员缺省选自己的首个分身，没有时返回 409 `{detail:"先新建一个分身",code:"no_persona"}`。未知或跨拥有者 ID 返回 404“分身不存在”（所有 route families 在路由前统一检查）。JSON/form 编码，错误为含 status/detail/code 的 ApiError，保留中文 detail。

| 方法/路径 | 契约 |
| --- | --- |
| `GET /api/personas` | `[{id,name,owner|null,avatar_url|null,avatar_preset,sources,created_at,is_default,public,can_manage,…}]`，管理员看全部，成员看自己建的、认领的和别人公开的；owner 为 null 的旧分身归管理员；调用时先按登录的邮箱或工号认领给 TA 建的分身。管理者另得 `claim`、`claimed`、`claim_rejected`；认领者另得 `mine`、`approved`、`made_by_other`、`from_meetings` |
| `POST /api/personas` | `{name}`，201 返回新分身，owner 为当前账号（auth 关闭则 null）；成员达到 max_personas_per_member 时 409“最多可以建 3 个分身”；私有目录及 identity，registry 仅增加拥有者邮箱 |
| `PATCH /api/personas/{id}` | `{public}` 设为公开/私有；由团队录音库生成的分身在本人认领并点“没问题”前设为公开返回 409 |
| `PUT /api/personas/{id}/claim` | `{claim}` 给谁建的：企业邮箱或工号（不区分大小写，空值清除）；格式不对 400，已用在另一个分身 409，本人已认领 409；改填后清掉“退回”标记 |
| `POST /api/personas/{id}/approve` | `{public}` 仅认领它的本人：记下 `approved_at` 并设置同事能不能问 |
| `POST /api/personas/{id}/disown` | “这不是我”：仅认领它的本人，自己建的 409；分身退回建它的人，原 claim 记入 `claim_rejected`，`member`、`approved_at` 清除并设为私有 |
| `GET /api/personas/trash`、`POST /api/personas/{id}/restore` | 自己能管理的已删分身（7 天内）/ 恢复 |
| `DELETE /api/personas/{id}` | 删除该目录；默认分身 400，运行/排队任务或请求存在时 409 |
| `POST /api/identity/onboarding-complete` | 完成当前分身的新建引导 |
| `GET /api/status` | target_name、counts、llm/embed、egress（仅实际配置且外部，评委 kind=judge）；无数据库路径或密钥 |
| `GET /api/jobs`、`/api/jobs/{id}` | 状态、时间、进度日志、阶段、计数、里程碑、结果/错误 |
| `GET /api/persona/sources` | 保留原字段，追加 detected_kind/label、status（processing/remembered/nothing_found/failed；媒体另有 queued/extracting/transcribing/needs_asr）、remembered；媒体追加 media_sha/duration_s/creation_time/transcribed_s/media_job_id；不含 preview |
| `GET /api/persona/sources/{id}/text` | text/plain，隐私视图，最多 20000 字，不存在 404 |
| `POST /api/persona/notes` | `{text: str, title?: str}`，text 1–20000 字，空白拒绝；默认标题“笔记 YYYY-MM-DD HH:MM”，当天日期 |
| `GET /api/persona/processing` | `{state: idle/queued/running, job_id?, last_finished_at?, last_error?}` |
| `GET /api/persona/state` | `{stale, built_at, sources_changed_at}` |
| `POST /api/persona/import` | multipart files；kind 可选（默认逐文件自动识别），显式 kind/date 兼容；返回 imported/skipped 原因，逐文件追加 detected_kind 和 detected_kind_label |
| `DELETE /api/persona/sources/{id}` | 删除记忆并自动重新处理，返回 deleted |
| `POST /api/persona/build` | 构建与向量更新，202 job_id |
| `POST /api/uploads` | JSON `{filename,size,type}`，拒绝空文件、不支持后缀、超过 4 GiB；返回 `{id,offset:0,chunk_size:8388608}`；创建时清理超过 24 小时未活动的上传 |
| `PUT /api/uploads/{id}?offset=N` | octet-stream 流式追加，≤16 MiB；不匹配时 409 `{offset}`，成功 `{offset}`；中断或超限回滚本次分片 |
| `GET /api/uploads/{id}` / `DELETE /api/uploads/{id}` | `{offset,size}` / 取消并删除分片；不存在 GET 返回中文 404 |
| `POST /api/uploads/{id}/finish` | 完成后 SHA 去重、保留原件、排队 media_ingest；返回来源字段、new、job_id；可重复调用 |
| `GET /api/library` | 团队录音库里当前账号能看的录音（上传的、参会的，管理员看全部；不属于某个分身，不看 `X-Twin-Persona`），每段带 `can_edit`：`{recordings,pending,max_pending,asr,capacity:{free_bytes,arriving_bytes,arriving,headroom_bytes}}`，每段录音另带 `people`（认出的人名）和 `unsettled`（还没定的说话人数），录音列表据此显示“已认人 / N 位待确认 / 还没认人”，`proofread` 为 `done`/`failed`/`waiting`/空（已校对 / 校对未完成用原文 / 待校对 / 无人确认不校对）；`quota:{limit,hours,used,exhausted,resets_at,waiting_proofread,waiting_twins}` 是批次额度，用完时页面提示暂停了什么，额度腾出后这次请求会补启暂停的校对和分身重建；团队页把有未定说话人、又不在“拿不准”队列里的录音列为“试听并确认”；同时补启排队中的转写 |
| `POST/GET/PUT/DELETE /api/library/uploads…` | 与 `/api/uploads` 相同的分片协议；创建时排队数（排队/转写中 + 未传完）达到 `[library].max_pending` 返回 409，传完后可用空间会低于 `headroom_gb` 返回 507 |
| `POST /api/library/uploads/{id}/finish` | 按 SHA 去重为录音（`new`），依次转写（与分身录音共用一个转写名额）；转写稿与 FLAC 试听文件校验后删除原件。同事先传过同一段时只返回 `{id,filename,new:false,mine:false}`，录音仍归先传的人 |
| `POST /api/library/recordings/{id}/retry` / `DELETE /api/library/recordings/{id}` | 失败且原件仍在时重新排队，否则 409 / 删除录音及其文件，转写中 409；删除会关闭用到它的团队分身直到重建 |
| `GET /api/library/recordings/{id}` | 录音加 `transcript_id`、`revision`、`can_edit`、`mine`（归给当前账号的说话人）、`segments` 和 `speakers`（`decision`、`person_id`、`sample`、`auto`、`disputed`、`samples`；能改时另有 `rejected`、`candidates`、`near`）。看不到的录音 404，能看不能改的录音上做修改 403 |
| `POST /api/library/recordings/{id}/speakers/{sid}/not-me` | 会上被确认的人说这段不是自己：归属清空、记为不是 TA、标 `disputed` 等上传者处理；不是归给自己的 409 |
| `GET /api/library/recordings/{id}/speakers/{sid}/samples/{i}` | 该说话人第 i 段试听 WAV（0 起，个数见 `samples`） |
| `PUT /api/library/recordings/{id}/speakers/{sid}` | `{transcript_id,revision,action:confirm\|unknown\|mixed\|reject\|clear,person_id?,new_person?,sample?}`，返回 `{revision,person_id}`；转写或修订号已变 409 |
| `GET /api/library/review` | 当前账号能改的录音里，有人说“不是我”的在前，然后是未决定且有候选的说话人，最像的在前 |
| `GET/POST /api/library/people`、`DELETE /api/library/people/{id}` | 团队人物名单（确认过的录音数、秒数、样本数、`persona_id` 仅当前账号能管理该分身时给出、`updating`、`auto` 未命名、`gender` 性别 male/female/空、`recording_id` 能看的一段录音、`can_manage`、`self_claimed`、`twin_elsewhere` 分身由别的同事管理、`similar` 仅管理员可见的可能同一人）/ `{name}` 新建，重名 409 / 删除人物及其归属和样本，已有分身 409 |
| `PATCH /api/library/people/{id}` | `{name?, gender?}`：改名（未命名的人起名后不再是“未命名”），重名 409；同场的分身随之重建，已有分身同步改名。改性别不重建；已有分身时，若当前插画形象与性别不符，换成该性别的一款（生成分身时同样按性别选） |
| `GET /api/admin/system?refresh=` | 仅管理员（否则 403）。GPU 机器上各服务的检查记录（`services`：`key/name/enabled/address/latest/since/checks/failures/availability/first_at/last_failure/buckets`，每分钟一次、保留一天；朗读服务关闭时不检查）、`switches.tts/video`（`configured/enabled/missing/changed_at/changed_by`）、`config`（各服务 twin.toml 的主机、端口和模型，不含路径、命令、密钥）、`models`（`[llm]`/`[chat_llm]`）、`editable_models`（`[llm]`/`[chat_llm]`/`[embed]` 的完整地址、模型名、`locked` 不能改的原因、`custom/changed_at/changed_by`）、`keys`（环境变量名、用途、`set`，从不含值）、`env_file`（密钥写入的文件名，不含路径）、`audit`（最近 20 条修改：谁、何时、改了什么，从不含密钥值）和 `quota`（团队录音库的用量加 `custom/default_limit/default_hours`）；`refresh=true` 立即检查一次（5 秒内不重复） |
| `PUT /api/admin/system/switches/{tts\|video}` | `{enabled}`，立即生效并写入 `data/system.json`，返回同上；未配置 409，其他名字 404 |
| `PUT /api/admin/system/features/{work\|ledger}` | `{enabled}`，对所有分身、所有成员立即生效，写入 `data/system.json` 并记审计；关闭后菜单不再出现，`/api/persona/work*`、`/api/persona/ledger*` 返回 403 `{detail:"管理员已关闭…", code:"feature_off"}`，已有任务和记录保留。聊天不能关闭（404）。`/api/whoami` 带 `features:{work,ledger}` 给前端决定菜单 |
| `PUT /api/admin/system/models/{llm\|chat_llm\|embed}` | `{base_url?, model?}` 代替 twin.toml 的地址和模型名，空项沿用 twin.toml，两项都空时恢复；写入 `data/system.json`，立即重建模型客户端、所有分身一起生效；只有 OpenAI 兼容接口能改（否则或未配置 400），地址须 http(s)、不带账号密码和查询参数（400），其他名字 404。换向量模型后各分身在后台重新生成检索向量，完成前按关键词检索 |
| `PUT /api/admin/system/keys/{env}` | `{value}` 设置、`{}` 移除；只接受 `keys` 里列出的变量名（否则 404），值不能含换行等控制字符（400）。写入服务器的 env 文件（`$TWIN_ENV_FILE`，否则 `./.env`，保持 0600，原子替换，保留其他行；权限不是 0600 时 409），同时更新运行中的进程并重建客户端；`TWIN_API_TOKEN` 由另一个进程 `twin api` 读取，重启它才生效。审计写入 `data/system-audit.jsonl`（0600），只记变量名和是否设置 |
| `PUT /api/admin/system/quota` | `{batch_tokens?, batch_hours?}` 覆盖 `[library]` 的批次额度（0 为不限，小时 0–720），两项都空时恢复 twin.toml；立即生效，等额度的校对和重建在录音库下一次刷新时继续 |
| `PUT /api/admin/system/params/{key}` | `{value}` 代替 twin.toml 的值、`{}` 恢复；可改的只有 `kernel.auto_rebuild`、`kernel.max_auto_rebuild_chunks`、`library.max_pending`、`library.headroom_gb`、`library.failed_keep_days`（其他 404），按 twin.toml 的类型和范围校验（400，中文说明）。写入 `data/system.json` 并记审计，立即生效，所有分身一起；`GET /api/admin/system` 的 `params` 列出每项的 `label/help/unit/value/default/custom/changed_at/changed_by` |
| `GET /api/admin/system/components` | 仅管理员。`kernel`（当前 `version`，`twins` 每个分身的 `id/name` 加 `/api/status` 里的 `kernel` 字段）、`ledger`（`version`、`enabled`，开启时 `twins` 每个分身的 `meetings/pending/running`）、`library`（`attribution/cleanup` 规则版本） |
| `POST /api/admin/system/components/{kernel\|ledger}` | `{persona_ids?}`，空为全部需要的分身；返回 202 `{queued, ...components}`。内核只排队记忆按旧版本整理的分身，轮流重建；账本只整理有未读会议、没在整理的分身，承诺账本关闭时 409；未知分身 404；记审计 |
| `POST /api/library/people/{id}/same` | `{persona_id, same}`：建分身的人（和管理员）确认自建的分身是不是这个同名的人；是则连上，不是则以后不再问；对不上 409，不是自己管的分身 404 |
| `POST /api/library/people/{id}/persona` | 生成该人物的团队分身（会议记录模式），可带 `{claim}`（企业邮箱或工号，TA 登录即认领），幂等：`{persona_id,new}`；需要 `can_manage`，别的同事已建 409，claim 已用在别处 409 |
| `POST /api/library/people/{id}/merge` / `.../apart` | 仅管理员：`{into}` 把这个人并入另一人（被并入方有自己的分身时 409）/ `{other}` 两人不是同一个人 |
| `GET/PUT/DELETE /api/library/voice` 等 | 员工 1b：企业账号读一句话，在团队录音库里听推给自己的声音并确认“是我”，见 `web/voice.py` |
| `POST /api/persona/sources/{id}/transcribe` | 重新转写原件，202 `{source_id,job_id}`；同来源已有任务则复用 |
| `GET /api/persona/items?include_rejected=false` | 条目、细项/维度、证据场合数；`conflict=true` 只看证据矛盾的 |
| `GET /api/persona/items/search?q=` | 按意思和关键词找条目（聊天的混合检索，向量不可用时只按关键词），最多 20 条，不含已删 |
| `GET /api/persona/items/summary` | 各维度条目数和证据矛盾的条目数 |
| `PUT /api/persona/items/{id}/tier` | `{tier: "colleague"|"self"|null}`：本人决定这条记忆谁能用（同事能用 / 只有本人能用，null 回到细项默认）；只有本人（认领并确认过分身的人；没有登录功能的本机，用的人）可以改，其余 403；条目对不上或观看者看不到 404。条目和覆盖度接口对同事档的观看者只含同事能用的条目 |
| `POST /api/persona/items/{id}/review` | edited/rejected/unreviewed（恢复原样）；edited 必须非空；confirmed 仍接受但界面不再使用 |
| `GET /api/persona/coverage?as_of=...` | 完成度、来源矩阵、等级标签、分类版本、建议 |
| `POST /api/persona/chat` | messages（≤40 条、每条≤4000 字、最后非空 user）；有档案时 202 job_id，结果 ChatReply + cited；无档案时 200 直接返回友好弃权回复 |
| `POST /api/persona/chat/stream` | 同样的请求与鉴权/分身隔离；200 text/event-stream，delta `{text}` → final `ChatReply + cited`，失败为 error `{detail}`；立即发送注释、等待期间每 10 秒心跳；no-cache、X-Accel-Buffering: no |
| `GET /api/persona/handoffs` | 只有本人（认领并确认过分身的人；没有登录功能的本机，用的人），其余 403：本人的“你不在时”。`waiting` 等你决定的转交（最先到期的在前；每条有 `kind/kind_label` 要你决定、要你答应、涉及评价、无出处、`asker_name`、`question`、`context` 提问人上一句、`answer` 分身答了什么、`days_left`、`commit` 待接的承诺 `{entry_id, what, due, pending}`、`source_known`——假表示来源不明，只能存进记忆）、`guessed` 分身对同事猜着答的（未看过的）、`sourced`/`sourced_count` 有出处的、`answered` 近 `days`（7）天答了几问、`shelved` 不答和已过期的、`settled` 已处理的、`pending` 等你决定的条数。卡在“正在写回”超过 30 秒的会在这里补完 |
| `GET /api/persona/handoffs/count` | `{pending}`：等你决定的条数，侧栏账户上的数字 |
| `POST /api/persona/handoffs/{id}/reply` | `{text, remember=true}`：本人的回复，写进提问人原来的对话（标“本人”，只写一次），`remember` 时也存成记忆；已回复的再回 409；提问人已删会话 409（不写、不存）；别人的或不存在的 404。返回 `{handoff, pending}` |
| `POST /api/persona/handoffs/{id}/draft` | 请分身起草：只返回 `{text}`，不发送不存；要你定的地方写成“【请你定：…】”，带着它的回复被拒（409）；已处理的 409；模型失败 502 |
| `POST /api/persona/handoffs/{id}/accept`、`/decline`、`/dismiss`、`/restore` | 接下（可带 `{due}` 改时间；只有“要你答应”的）、不接、不答、放回（再等一周）；接下和不接各往提问人的对话写一句固定的话；已用文字回复的承诺之后接下，只改承诺和状态，不再写第二条 |
| `POST /api/persona/answers/{conversation_id}/{turn}/confirm`、`/correct` | 分身对同事猜着答的：没错 / `{text}` 更正（写进提问人的对话、存成记忆） |
| `POST /api/persona/ledger/{entry_id}/accept`、`/decline` | 账本里“待你接受”的承诺（同事在对话里求本人答应的）：接下（可带 `{due}`）/ 不接，和“你不在时”里是同一件事；不是对话来的条目 404 |
| `GET /api/persona/questionnaire?round=initial` | 问题、答案、提交状态 |
| `PUT /api/persona/questionnaire/draft` | round、answers，保存草稿 |
| `POST /api/persona/questionnaire/submit` | 导入全部回答并尝试构建；只支持 initial |
| `GET /api/identity` | name/aliases/about/name_source（config 或 user）/voice/avatar/avatar_preset/avatar_presets（id、name）/egress；name 是有效名字；新建未完成引导时追加 onboarding_pending=true；无授权账本 |
| `PUT /api/identity` | X-Twin: 1；`{name, about}`；去除首尾空白后名字 1–20 字，介绍 ≤200 字；返回完整 identity；介绍变化会替换“自我介绍”笔记并自动处理 |
| `PUT /api/identity/avatar-preset` | `{preset: id}`，仅分身管理者；保存 `identity:avatar_preset` 并返回身份；未知 ID 中文 400，访客 403 |
| `GET /api/media/capabilities` | available/backend/languages/audio_formats/avatar/avatar_preset/avatar_presets、`video: {available: bool}`；avatar_model 为 `{format: "vrm", url: "/api/media/avatar.vrm"}` 或 null；avatar_image 为 `{url: "/api/media/avatar-image"}` 或 null（语音失败时仍返回） |
| `GET /api/media/avatar.vrm` | 配置的本地 VRM 流，model/gltf-binary、no-cache；未配置中文 JSON 404 |
| `GET /api/media/avatar-image` | 本人上传肖像优先，否则配置的本地肖像；上传版本能力 URL 含 ?v=sha；image/png、image/jpeg 或 image/webp、no-cache |
| `GET /api/me/assets` | portrait/voice profile + speech_clone（voice_dir 已配置）、video 布尔能力 |
| `PUT /api/me/portrait` / `DELETE /api/me/portrait` | multipart file（JPEG/PNG/WebP ≤15MB）及可选 x/y/w/h 归一化裁剪；删除恢复默认；返回 profile |
| `PUT /api/me/voice` / `DELETE /api/me/voice` | multipart file（录音/视频 ≤95MB），CPU ffmpeg 处理并校验至少 5 秒；删除恢复默认；返回 profile |
| `GET /api/me/voice/reference` | 本人处理后的单声道 24kHz PCM16 WAV，private/no-store；不存在中文 JSON 404 |
| `POST /api/media/script`、`/export`、`/audio`、`/clip` | `{kind: "chat_reply", answer: ChatReply, persona_name?: str}`；audio 可追加 `segments?: int[]`（零基脚本段索引，省略为全部），返回 `segment_count` 与所选分片 URL/口型轨、完整 script 和所选分片 manifest；非法索引 400 |
| `POST /api/media/audio/stream` | `{answer: ChatReply, persona_name?: str}`；同样的鉴权、X-Twin 与分身隔离；octet-stream 帧：1 字节类型 + 4 字节大端长度 + payload。类型 1 为 JSON 采样率/段数或段索引/纯文本字幕，2 为单声道 PCM16LE，3 为 JSON 总时长，4 为脱敏 JSON 错误；no-store、X-Accel-Buffering: no |
| `GET /api/media/audio/{name}` | SHA-256 命名 WAV/MP3 分片，验证目录边界 |
| `POST /api/media/video` | 与 clip 相同的请求体，返回 `{job_id}`；弃权回答 400，未配置 503 |
| `GET /api/media/video/jobs/{job_id}` | 当前分身的视频任务状态（与其他任务共用按分身隔离的 JobManager）；done 结果 `{file, duration_s, warnings}`，重启清空 |
| `GET /api/media/video/{name}` | 64 位十六进制文件名的 MP4 流，校验目录与符号链接；video/mp4、private/no-store；不存在 404 |

任务状态 queued/running/done/failed，每个任务含 persona_id，查询仅返回当前分身的任务，跨分身任务编号返回 404。日志最近 500 行，里程碑另存；人格构建、转写、视频各自全局串行，聊天有并发及待处理数量限制。任务仅驻留内存，重启清空；UI 启动时发现 stale 会重新排队。导入、笔记、删除和介绍变化后约 3 秒防抖自动处理；运行中发生多次变化只排一个后续处理，复用 run_persona_build 和 JobManager。完成时间与错误持久化，失败可以 POST build 重试。stale 表示来源比档案新，不阻止聊天。构建结果包含 items_added/changed/removed、facets_changed 和 facet_diffs；失败不当作零分答案。

`POST /api/media/clip` 保留供 CLI/API 使用，网页不提供 2D 片段或 HTML 导出操作。clip 同步返回 `video/mp4`，`Content-Disposition: attachment`；复用现有安全与请求体限制，脚本最多 100,000 字符、视频最多 600 秒。需系统 ffmpeg 与中文字体（见 [MEDIA.md](MEDIA.md)），临时 MP4 在响应完成后清理。

`video.available=true` 时，`features/chat/useReplyVideos.ts` 自动为非弃权回复提交真人视频任务，每条回复只启动一次；页面同一时间只处理一个视频任务，后续回复排队（新回复优先），已有会话任务优先恢复轮询，避免堆积 GPU 工作。`ReplyVideo.tsx` 生成期间仅显示小字“真人版生成中…”，不显示按钮、卡片或进度条；每秒轮询专用任务接口。完成后显示标为“真人版”的 `<video controls playsInline preload="metadata">`，宽度 100%、最大 360px、圆角，poster 为肖像，原生播放/全屏控件及“保存”链接；visually hidden 完整回复文本作为描述。如果该回复的语音仍在播放（包括等下一段），延迟首次显示直到语音停止，不自动播放视频。成品与已提交任务 ID 按回复、肖像 sha 和声音 ID 缓存在本标签页 sessionStorage，返回聊天不重复提交；失败只显示“真人版生成失败 · 重试”。轮询连接失败保留任务 ID，重试恢复轮询而非重复生成；已确认失败或不存在的任务才重新提交。离页停止轮询，不取消已提交的远端任务；正在提交的请求保留以记录任务 ID。超阈值分段用小字提示回听出入，不展示识别文本。远端 JSON 契约和本地后处理见 [MEDIA.md](MEDIA.md#34-本人视频通道v2)。

脚本与独立 HTML 导出不调用模型，音频与视频只调用配置合成器。导出自包含、无可执行脚本或外部资源，文本及 inert JSON 安全转义，含来源元数据和指纹；指纹不是签名。音频存于数据库目录的 media-cache，GET 为 `private, no-store`。语音不可用/拒绝/超时/过长为 503/502/504/413，不回显服务消息；已经开始的 PCM 流使用错误帧。

听优先使用 fetch/ReadableStream + Web Audio，PCM 统一为 24 kHz，首段约 150 ms 缓冲后在同一时间线上连续排程；断粮冻结播放进度、显示等待，补足缓冲后继续。字幕按实际播放时间切换，舞台音量由输出 AnalyserNode 的 RMS 驱动。播放和发送按钮同步创建/恢复 AudioContext（含 Safari），暂停冻结音频时钟；停止、换回复/分身和离页取消 fetch 并清理音源。未收到音频时连接失败或流端点 404/5xx 自动退回旧的分段播放。完整成功流按文本、音色、模型和版本保存在当前分身的私有 media-cache，重放不重新合成。

流响应在鉴权/安全/分身中间件中逐块透传，首个采样率帧在访问上游前发送。Cloudflare Tunnel 应直接转发此 HTTP 响应，不启用额外代理缓存/响应聚合；应用发送 no-store 与 X-Accel-Buffering: no。外部代理的缓冲设置仍需部署端验证。

## 安全与服务路由

`web.app.create_app` 懒创建后端，测试可注入离线工厂。默认仅接受 localhost、127.0.0.1、[::1] Host，显式 `--host/--allow-host` 可扩展；公网必须另加认证。所有非 GET/HEAD 请求要求 `X-Twin: 1`，不开 CORS，WebSocket 一律关闭（1008）。JSON 上限 1 MB，上传总上限 1 GB、500 文件，单文件 1 GB；文档上传只取 basename，流式解析并暂存到临时文件，不读客户端指定的服务器路径。音视频 PUT 分片路径豁免 JSON 体积限制，但仍要求 X-Twin，由端点流式检查 16 MiB 上限，写入私有 uploads/<id>.part；JSON 创建请求仍受 1 MB 限制。音视频原件以 SHA 命名的私有目录保存，删除来源同时删除媒体。

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
