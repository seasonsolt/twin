# twin

**A personal digital twin, grounded in a person's own material.**

[![CI](https://github.com/seasonsolt/twin/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/seasonsolt/twin/actions/workflows/ci.yml)

English | [简体中文](#简体中文)

> **Status: early.** Interfaces will still change.

twin builds a persona from freely added memories — notes, chats, documents, optional questions and interviews — where every trait carries a verbatim, dated quote, and serves it as conversation and speech: **Identity → Memory upload → Service**. Answers cite their evidence or abstain. twin is a personal tool and does not add disclaimers. Architecture: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) (Chinese).

**Why twin.** Open-source "clone a person" projects mostly invent answers when the material is silent, keep no verifiable evidence, and rely on LoRA training that is slow to update. The author first tried to fix this inside Second Me: the fork [seasonsolt/Second-Me](https://github.com/seasonsolt/Second-Me) swapped every replaceable module for the best option as of Q3 2026 (Qwen3, MLX LoRA, retrieval-first memory, 8K context) and still fell short, because the gap is architectural. twin was therefore designed from scratch: it answers only from cited, verbatim evidence, abstains otherwise, and updates by re-indexing instead of retraining. On the author's own 59-question set, scored with the same judge script that was used for Second Me, twin reaches 98.4% fact accuracy and never fabricated on unanswerable questions (original Second Me: 4.7% and 10%; upgraded fork: at best 78.1% and 70%). Caveat: twin answered with a frontier model while Second Me ran a local 0.5B (original) or 1.7B (upgraded) model, so part of the gap is the model, not the method. Details and limits are in the Chinese section below.

**Memory architecture.** Two layers instead of a plain vector store: the person's own *expressions* (dated, with context, own words vs. narration), and *persona items* derived from them across 9 dimensions / 39 facets, each item carrying mechanically verified verbatim quotes, behaviour-vs-self-report evidence classes, occasion counts, explicit conflicts, and the person's own review (confirm / edit / reject, preserved across re-merges). Answers pick one of three modes — grounded, general, abstain — then pass citation validation, confidence caps and a quote guard. Updates are deterministic and incremental (content-hashed chunks, candidates and items; only changed facets re-merge), and any answer can be computed "as of" a past date. Agent-memory frameworks (mem0, Letta, Graphiti/Zep, MemOS, Cognee, MIRIX) remember facts *about* a user for a task; twin models *who the person is and how they speak*, and refuses when the material is silent. Digital-human projects (Duix-Avatar/HeyGem, LiveTalking, Fay) clone face and voice but have no identity-grade memory; twin pairs both.

---

## 简体中文

通用的个人分身：从一个人的资料里提炼出有来源依据的人格档案，再以对话、语音等方式提供服务。

```
Identity 身份  ──►  Memory upload 记忆上传  ──►  Service 服务
```

- **有据可查。** 档案里每一条都带逐字核对过的原话和日期；回答引用不到依据时降低置信度或弃权，不硬编。
- **随时添加记忆。** 写一段、上传文件或文件夹，自动整理；问卷可以不填。
- **隐私优先。** 他人姓名在进入档案时统一化名；对他人的评价不进档案；本人资料默认不发往境外服务。

架构与规则见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

## 为什么做 twin

### 开源方案的不足

| 项目 | 做法 | 不足 |
| --- | --- | --- |
| [Second Me](https://github.com/mindverse/Second-Me) 原始版本（Apache-2.0） | 文档洞察 → 画像（shade、bio）→ 用合成数据做 LoRA 微调，事实也训练进模型，本地 Qwen2.5-0.5B 作答，上下文 1024 token | 画像与回答没有可核对的原话证据；没有按日期作答；资料里没有的事会编造（作者资料上不编造率 10%）；每次更新都要重新合成数据并训练；1.0.1 版只有一个 shade 时画像会变成空回复，训练数据随之失效，且界面显示成功；代码自 2025-05 起不再更新 |
| [Second Me 升级版](https://github.com/seasonsolt/Second-Me)（作者的第一次尝试，已冻结） | 同一架构，可替换模块升级到 2026 年第三季度的最好选择：Qwen3-1.7B、Apple Silicon 上 MLX LoRA、检索式记忆（事实来自检索，LoRA 只学风格）、8192 token 上下文、按 embedding 模型选检索阈值 | 仍然没有原话证据和按日期作答，置信度靠模型自评；不编造率最高 80%；检索式记忆按设计增删改不用重训，但评测中删除 0/2 生效 |
| [Distilly](https://github.com/titanwings/distilly)（MIT，原名同事.skill） | 通读材料，生成一份人格与工作技能档案（Agent Skill），作答时只靠这份档案 | 没有检索和证据；档案一次性生成，更新靠重写；资料里没有的话题会用本人口吻编出立场（早期合成数据测试中，陷阱题 83% 被编造） |
| [WeClone](https://github.com/xming521/WeClone)（AGPL-3.0） | 用聊天记录微调 LoRA，复刻口吻 | 只学口吻，不管事实是否有据；需要训练，许可为 AGPL |
| mem0、Letta、Graphiti / Zep、MemOS、Cognee、MIRIX 等记忆框架 | 给智能体用的通用记忆：抽取事实（mem0）、可自我编辑的记忆块（Letta）、带有效期的时序知识图谱（Graphiti）、可组合的记忆仓（MemOS）、知识图谱（Cognee）、按类型分的个人活动记忆（MIRIX） | 不是分身：记的是"关于用户的事实"，不是"这个人是谁、怎么想、怎么说"；没有人格维度、口吻模仿和弃权规则；榜单（LoCoMo、LongMemEval）测的是对话回忆准确率，不测像不像本人；部分组件对中文支持差（例如 mem0 的 BM25 与实体抽取写死英文模型） |
| Duix-Avatar（HeyGem）、LiveTalking、Fay 等数字人 | 形象克隆、口型同步视频、声音克隆，部分带对话和知识库 | 只解决"长得像、声音像"，没有身份级的记忆：回答内容不出自本人资料，也没有证据和弃权 |

### 先试过升级 Second Me：为什么另起炉灶

twin 不是第一次尝试。作者先 fork 了 Second Me（[seasonsolt/Second-Me](https://github.com/seasonsolt/Second-Me)），不改架构，只把能替换的模块都换成 2026 年第三季度最新、最好的选择：基座模型、训练框架、检索式记忆、上下文长度、检索阈值、推理运行时。目的是测出这套架构的上限。

结果模块升级确实有效，但仍然达不到预期（见下面评测中的“原始版本”与“升级版本”）：事实准确率从 4.7% 提到最高 78.1%，不编造从 10% 提到最高 80%，风格只有 1.9–2.2 分，删除记忆 0/2 生效。剩下的差距来自架构本身，换更好的模块补不上：

- 作答靠本地小模型加 LoRA，回答没有可核对的原话证据，也不按日期作答；
- 置信度由模型自评，证据不足时不会主动弃权；
- LoRA 的训练数据仍由资料合成，记忆改了，训练出的权重不会跟着改，删除无法保证生效。

所以这个 fork 已冻结，twin 从头设计，把证据、日期、弃权和评测作为架构的一部分，而不是在 LoRA 管线上打补丁。

### twin 怎么解决

| 问题 | twin 的做法 |
| --- | --- |
| 编造 | 回答只能依据检索到的档案条目和本人原话；依据不足时降低置信度或直接弃权 |
| 没有证据 | 每条档案条目都带逐字核对过的原话、日期和来源；引用不到的条目会被剔除 |
| 更新要重新训练 | 不做 LoRA；新资料导入后增量抽取、重建索引即可生效。微调只能作为默认关闭的风格插件，在评测上显著胜出才允许打开 |
| 没有可信评测 | 内置评测框架：题库与资料留在仓库外，评委团、重复作答、按来源分组的置信区间、每次运行的来源记录 |

### 记忆架构

twin 的记忆不是"把文本切块放进向量库"，而是两层：**本人说过的原话**，和从原话里提炼、每条都带证据的**人格档案**。

```
资料（笔记、聊天记录、文档、录音/视频转写、问卷、访谈）
  │ 解析：只保留本人说的话；他人姓名化名；录音视频先区分说话人、认出哪位是本人
  ▼
原话 Expression ──── 每句带日期、渠道、上下文（被问的问题 / 前几条他人消息），标明是本人原话还是第三方转述
  │ 抽取（按 6000 字分段，大模型）：每个候选结论必须附 1–3 段逐字核对通过的原话，核对不过就丢弃
  ▼
候选 Candidate ──── 归入 9 个维度、39 个细项（经历、价值观、怎么做决定、怎么思考、擅长什么、说话方式、和人相处、最近关注、生活喜好）
  │ 合并（按细项，大模型）：同义合并；行为证据优先于自述；自述与行为矛盾时标出 conflict
  ▼
档案条目 PersonaItem ── 结论 + 适用场景 + 证据列表（原话、日期、来源、自述/行为）；按"不同来源 × 不同日期"计次
  │ 本人可以确认、修改或否决每一条；审阅结果在之后的重新合并中保留
  ▼
索引 ──── 档案条目和原话各一个向量空间；换 embedding 模型时自动重建
```

**作答时**，每次组装同一套材料：与问题最相关的 12 条档案和 6 句原话；每个维度证据最多的 2 条作为"核心画像"（不管问什么都在）；最近 8 句本人的聊天原话作为"说话样本"；最近 8 轮对话。模型先判断问题属于哪一类：

| 模式 | 什么时候 | 怎么回答 |
| --- | --- | --- |
| 有据（grounded） | 问的是本人的观点、经历、做法，资料里有 | 只依据档案和原话，用本人口吻，标出引用了哪些条目 |
| 通用（general） | 与本人无关的知识或方法问题 | 照常帮忙，开头说明这不是本人的观点 |
| 弃权（abstain） | 关于本人但资料里没有，或要替本人承诺、评价具体他人 | 用本人口吻说明这得问本人，不编 |

回答之后还有三道机械检查，不依赖模型自觉：

- **引用核对**：只保留真实出现在材料里的引用编号。
- **置信度封顶**：通用回答 ≤ 0.5；没有引用或弃权 ≤ 0.3；只引用了未经本人确认的转述 ≤ 0.6。
- **引号守卫**：回答里加了引号、却在材料里找不到逐字出处的"原话"，自动去掉引号，不把转述冒充成本人原话。

**更新**是确定性的增量计算，不重训：分段、候选、条目的编号都由内容哈希得出，新增资料只抽取没见过的分段，只有候选集合变了的细项才重新合并，删除资料会让依赖它的条目随之更新或消失，并给出逐细项的增删改清单。每条证据都有日期，可以回答"截至某一天，他会怎么说"。

**隐私**：每个分身一个独立的 SQLite 文件；对话按登录的人分开；他人姓名在进入大模型、向量和聊天之前统一化名；生活类细项需要本人同意才抽取；后台如实显示哪些服务会让数据离开本机。

和"智能体记忆"框架的区别可以归结为下面几点：

| | 智能体记忆（mem0、Letta、Graphiti、MemOS 等） | twin |
| --- | --- | --- |
| 记什么 | 关于用户和世界的事实，服务于完成任务 | 这个人是谁、怎么想、怎么做决定、怎么说话 |
| 证据 | 部分有来源追溯（Graphiti） | 每条结论都带逐字核对过的本人原话和日期 |
| 不知道时 | 没有专门的弃权机制 | 三种模式之一，资料没有就弃权 |
| 口吻 | 人设只是一段提示词 | 说话样本 + 说话方式维度，评测里单独打分 |
| 随时间变化 | Graphiti 用有效期表示事实变化 | 证据带日期，可以按任意一天作答 |
| 形象和声音 | 不涉及 | 本人照片和声音克隆，回答可以被"说出来"、配真人视频 |

### 评测能体现什么

**作者本人资料（59 题）。** 2026-10-05，同一套题库、同一个评分脚本和评委模型（Second Me 项目的 `judge.py`，`gpt-6.1-sol`）。twin 每题作答 3 次；表中 twin 取第 1 次回答，与 Second Me 每题一次的做法一致；升级版本一栏取它修复前后几次运行中的最好值或区间：

| 类别 | twin | Second Me 原始版本（Qwen2.5-0.5B） | Second Me 升级版本（Qwen3-1.7B） |
| --- | --- | --- | --- |
| 事实准确率（32 题） | **98.4%** | 4.7% | 78.1% |
| 资料里没有的问题不编造（10 题） | **100%** | 10% | 70% |
| 风格像本人（10 题，1–5） | **4.0** | 1.0 | 1.9–2.2 |
| 通用问题质量（5 题，1–5） | 2.6 | 2.2 | 3.0–3.2 |
| 记忆更新（2 题 × 增改删，6 分） | **6** | 0 | 3.5（删除 0/2） |

用 twin 自己的评测框架（3 次作答取平均、按来源文档 bootstrap）结果一致：事实 99.0%（95% 区间 94.7%–100%），不编造 96.7%（90%–100%），风格 4.23（4.0–4.5）。

**换不同家族的评委复核。** 冻结 Second Me fork 时，用 `claude-sonnet-5-5`（与所有作答模型都不同家族）对同一份资料、57 道题（不含记忆更新）单次重评，方向一致：事实 twin 98.4% / 原始 6.2% / 升级 68.8%，不编造 100% / 10% / 80%，风格 3.9 / 1.0 / 1.9，通用 2.0 / 2.2 / 3.0。完整表格见 [seasonsolt/Second-Me](https://github.com/seasonsolt/Second-Me) 的 README。

**当前版本（twin 自己的评测框架）。** 同一份资料、同一套题，评委固定为 `gpt-6.1-sol`，每题作答 3 次，括号内为 95% 区间。作答模型由 `[chat_llm]` 决定（见 [docs/PERSONAL_EVAL.md](docs/PERSONAL_EVAL.md)）：

| 类别 | `gpt-5.6-sol`，不开思考（2026-10-06） | `deepseek-flash`，不开思考（2026-10-07，现在线上） |
| --- | --- | --- |
| 事实准确率（32 题） | 97.4%（93.2%–100%） | 97.9%（94.7%–100%） |
| 资料里没有的问题不编造（10 题） | 100% | 90%（70%–100%） |
| 风格像本人（10 题，1–5） | 4.2（4.0–4.4） | 4.0（3.9–4.1） |
| 通用问题质量（5 题，1–5） | 4.5（4.1–4.8） | 3.9（3.5–4.3） |
| 记忆更新（2 题 × 增改删，6 分） | 6 | 5 |
| 回答里加引号却在资料里找不到的"原话" | 0（运行时去掉 26 处） | 0（运行时去掉 31 处） |

线上用 `deepseek-flash` 是为了速度：同样的提示词下，第一个字约 0.7 秒、整段约 2 秒，`gpt-5.6-sol` 分别约 3.7 秒和 5 秒。代价写在表里：事实持平，但通用问题偏保守（15 次里有 5 次本该帮忙却弃权），口吻和不编造略降。针对它的提示词调整正在评测，结果会更新到这里。

通用问题的做法：与本人无关的问题，分身先说明"这不是本人的观点"，再给出一般性的回答。引号一项靠的是运行时检查：引号里的文字如果不在分身看到的资料里逐字出现，就去掉引号、保留文字，不把转述当成本人原话。

读这组数字要注意：

- **作答模型不同。** twin 用前沿大模型作答，Second Me 用本地微调的小模型（原始版本 0.5B，升级版本 1.7B）。差距有一部分来自模型而不是方法；用同一个作答模型的对比还没有做。
- **评委与作答同源。** 主表评委是 `gpt-6.1-sol`，可能偏向同家族的回答；不同家族的 `claude-sonnet-5-5` 只单次复核过一次，twin 自己的评测框架还没有接入第二个评委。
- **题少。** 不编造、风格各 10 题，通用只有 5 题，区间都很宽。

**早期原型的合成数据对比**（单次运行，题库按分身的验收点编写，有主场优势，只看方向）：

- 不编造：twin 的"不知道就说不知道"平衡准确率 100%，Second Me 方法 75%，Distilly 方法 58%。
- 口吻：**twin 明显不如 Distilly**，风格盲评中 Distilly 12 次胜 11 次。
- 事实回忆：全部笔记都能放进上下文时，Second Me 方法更容易找回笔记里的具体细节；资料规模变大后这个优势难以保持。

记忆更新一项是 twin 自己的评测框架在临时数据库副本上跑的：每步只导入或删除资料、增量构建，不重训；每步作答 3 次全对。只有 2 道题，样本很小。

**还没有被评测证明的。** 成本与延迟、用同一个作答模型和 Second Me 对比。它们在路线图的第一步，见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

## 安装

需要 Python 3.12+，推荐 [uv](https://docs.astral.sh/uv/)：

```bash
uv sync
source .venv/bin/activate
```

## 使用

```bash
twin init                     # 生成带中文注释的 twin.toml，按注释填写模型和向量服务
```

密钥只放在环境变量里（`TWIN_LLM_KEY`、`TWIN_EMBED_KEY` 等），配置文件只写变量名。
可选的 `[chat_llm]` 让聊天（网页、CLI、API/MCP 与评测作答）用更快的模型，档案抽取和构建仍用 `[llm]`；未配置时聊天也用 `[llm]`，示例见 `twin.toml.example`。
外部后端按配置使用，界面如实展示出境分类；用 `twin identity show` 查看，本机转发代理需声明 `egress = "external"`。

**网页快速开始**

运行 `twin ui`，按打印的本机地址**打开页面 → 你是谁 → 形象和声音 → 添加记忆 → 聊天**。
首次填写名字和一段介绍（也可以跳过）；介绍自动保存为“自我介绍”记忆，添加的内容会自动整理。
主导航只有“聊天 / 记忆 / 关于你”。在“关于你”随时修改名字与介绍、核对我了解到的你，也可选择“回答几个问题”。
名字保存后不再显示首次引导；没有记忆时聊天页会提示先添加。

**多个分身**

手机和桌面顶栏均可点击头像与名字切换分身；列表显示记忆数，可“新建分身”或进入“管理”重命名、确认删除。
新建后自动切换并进入四步引导。每个分身的介绍、记忆、照片、声音、聊天记录和音视频上传相互独立；切换停止播放，但后台任务继续为原分身处理。
默认 `[auth].enabled = false` 保持无登录、所有人都是管理员的本机模式。启用邮箱登录后，成员只看到自己的分身，默认最多创建 3 个；管理员可管理全部分身，列表标出其他拥有者的邮箱。旧分身（含 default）归管理员。

数据根目录为 `db_path.parent`。`personas.json` 记录 ID、owner（邮箱或 null）、创建时间和默认 ID；原数据库和 `assets/`、`media-cache/`、`media-sources/`、`uploads/` 原地保留为 `default`，无需迁移。
新分身使用 `personas/p-<10位hex>/twin.db` 和同布局的私有目录。聊天记录保存在各分身的 `twin.db` 里，可搜索、重命名、删除和继续；启用登录后按账号邮箱各自私有。默认分身不能删除；有运行或排队任务的分身暂不能删除。
CLI/MCP/评测继续使用配置数据库，不新增选择参数。

**公网部署与邮箱登录**

Cloudflare Access 已移除，不读取任何 `Cf-Access-*` 身份头；应用本身是认证边界。保持服务只绑定 `127.0.0.1`，Cloudflare Tunnel 的 HTTPS 公网域名指向本机端口，并保留原 Host。用 `twin ui --allow-host twin.example.com` 接受自己的域名，不要将开发服务器或本机端口直接暴露到公网。

1. 在 `twin.toml` 配置 `[auth] enabled = true`，填写 `allowed_domains`、`allowed_emails` 和 `admin_emails`（完整示例见 `twin.toml.example`）。域名仅匹配最后一个 `@` 后的完整部分，大小写不敏感；管理员邮箱也须在允许范围内。
2. 配置 `[auth.smtp]` 的 host、port（465 SSL / 587 STARTTLS）、username、from_address、from_name。`password_env = "TWIN_SMTP_PASSWORD"` 只写变量名；通过服务进程的环境安全传入密码，不存入配置或源码。启用登录但缺少 SMTP 配置/密码时启动失败。
3. 重启服务应用配置变更。允许的用户收到 6 位验证码（10 分钟有效、5 次错误后失效）；未允许的邮箱加入等候名单，不发邮件。发送限额：每邮箱 60 秒一次、每小时 5 次，每客户端 IP 每小时 20 次（隧道使用 `CF-Connecting-IP`，否则使用连接地址）。内存限额按进程计算，部署使用单进程。

会话默认 30 天，只存于 HttpOnly、Secure、SameSite=Lax cookie（本机 HTTP 开发可非 Secure），不在 localStorage 保存 token。`<数据根>/auth.db` 以 0600 保存验证码哈希、会话哈希及去重的等候邮箱；备份时视作私有资料。所有 API/媒体需会话，写操作仍需 `X-Twin: 1`。账号菜单常驻页面，提供“退出登录”。

管理员登录后可用同源 `GET /api/admin/waitlist` 查看等候名单；放行用户就是把邮箱加入配置 `allowed_emails` 并重启，没有审批 UI。不要在启用 auth 前移除原有外层保护，也不要在公网关闭 auth。

**记忆上传**

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

网页 `#/memories`（导航“记忆”）可以写一段、上传多个文件或整个文件夹，也支持最多 4 GB 的录音、播客、手机视频和屏幕录制。音视频以 8 MiB 分片断点续传；上传时保持页面打开，刷新后重新选择同一文件可继续。原件保留，ffmpeg 提取音频后由 `[asr]` 转写，带时间戳的文字自动进入普通记忆整理。未配置识别也可上传，配置后重启服务，点“重新转写”。命令/HTTP 配置见 [docs/MEDIA.md](docs/MEDIA.md#音视频记忆)。添加、删除后自动处理，不必点构建；可以查看分身看到的文字、记住的条数和失败重试。CLI 导入或笔记保存后，可运行 `twin persona build`，也可启动网页让它自动处理。

**服务**

```bash
twin persona chat "你怎么看远程办公？"
twin ui                                             # 本机网页：多个分身、流式聊天、保存的对话、记忆、朗读与真人视频
twin api                                            # 令牌保护的本机 HTTP API（先设置 TWIN_API_TOKEN）
twin mcp                                            # stdio MCP，供其他工具和 Agent 使用
```

API/MCP 保留高级（advanced）可选参数 `as_of`，评测也保留日期筛选；CLI 和网页聊天不提供它。
配置、接口与隐私规则见 [docs/SERVICE.md](docs/SERVICE.md)。

**语音（可选）**

在 `twin.toml` 的 `[tts]` 里配置语音后端：自托管的 MOSS-TTS-Nano（见 [deploy/tts-moss](deploy/tts-moss/README.md)）或 Cloudflare MeloTTS（外部服务，按配置使用）。

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
语音容器需将 `voice_dir` 只读挂载到 `/voices`，见 [deploy/tts-moss](deploy/tts-moss/README.md)。

视频驱动 JSON 契约新增可选 `portrait`、`voice_ref`：本机为绝对路径，SSH 模式先 scp 到远端 home 的
`.cache/twin-assets/<sha>.<ext>` 后传相对路径。默认分身缺省时驱动沿用自己的素材，其他分身不允许省略素材，完整契约见 [docs/MEDIA.md](docs/MEDIA.md)。

浏览器 3D 形象可在 `[avatar]` 设置 `vrm_path` 指向本地风格化 VRM 文件（不入库）；未配置或加载失败时保留 2D 形象，见 [docs/MEDIA.md](docs/MEDIA.md)。

## 文档

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)：产品形态、分层、层间规则、治理、路线
- [docs/PERSONA_DIMENSIONS.md](docs/PERSONA_DIMENSIONS.md)：分身可以了解你的哪些方面
- [docs/MEDIA.md](docs/MEDIA.md)：语音与展示通道
- [docs/CONTRACTS.md](docs/CONTRACTS.md)、[docs/WEB_UI.md](docs/WEB_UI.md)：模块与网页接口契约

## 开发

前端需要 Node 22 和 pnpm 10；构建产物随 Python 包分发，`twin ui` 在 `/` 提供唯一的 React 界面。

```bash
pnpm -C frontend install && pnpm -C frontend build
pnpm -C frontend typecheck
pnpm -C frontend lint
pnpm -C frontend test
uv run ruff check src tests deploy && uv run ruff format --check src tests deploy
uv run mypy
uv run pytest -q
```

开发时先运行 `uv run twin ui`（默认 `127.0.0.1:8765`），再在另一个终端运行 `pnpm -C frontend dev`，打开 Vite 打印的地址（默认 `http://127.0.0.1:5173/`）。Vite 将 `/api` 代理到后端；若改变后端端口，调整 `frontend/vite.config.ts` 的 proxy target。前端改动后重新 build，并同步 `src/twin/web/static/` 产物。布局、动效与安全契约见 [docs/WEB_UI.md](docs/WEB_UI.md)。
