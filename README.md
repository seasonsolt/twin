# twin

**A personal digital twin, grounded in a person's own material.**

[![CI](https://github.com/seasonsolt/twin/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/seasonsolt/twin/actions/workflows/ci.yml)

English | [简体中文](#简体中文)

> **Status: early.** Interfaces will still change.

twin builds a persona from someone's own material — questionnaires, chats, documents, interviews, transcripts — where every trait carries a verbatim, dated quote, and serves it as conversation and speech: **Identity → Memory upload → Service**. Answers cite their evidence or abstain; every output is labelled as AI-generated and does not represent the person. Architecture: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) (Chinese).

**Why twin.** Open-source "clone a person" projects mostly invent answers when the material is silent, keep no verifiable evidence, cannot answer "as of" a date, and rely on LoRA training that is slow to update. twin answers only from cited, verbatim evidence, abstains otherwise, and updates by re-indexing instead of retraining. On the author's own 59-question set, scored with the same judge script that was used for Second Me, twin reaches 98.4% fact accuracy and never fabricated on unanswerable questions (Second Me after its base upgrade: at best 78.1% and 70%). Caveat: twin answered with a frontier model while Second Me ran a local 1.7B–4B model, so part of the gap is the model, not the method. Details and limits are in the Chinese section below.

---

## 简体中文

通用的个人分身：从一个人的资料里提炼出有来源依据的人格档案，再以对话、语音等方式提供服务。

```
Identity 身份  ──►  Memory upload 记忆上传  ──►  Service 服务
```

- **有据可查。** 档案里每一条都带逐字核对过的原话和日期；回答引用不到依据时降低置信度或弃权，不硬编。
- **可以"穿越"。** `--as-of` 只用某一天及以前的资料作答。
- **明确标识。** 所有输出都是 AI 模拟，不代表本人意见；语音和导出文件带显式与隐式的 AI 合成标识。
- **隐私优先。** 他人姓名在进入档案时统一化名；对他人的评价不进档案；本人资料默认不发往境外服务。

架构与规则见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

## 为什么做 twin

### 开源方案的不足

| 项目 | 做法 | 不足 |
| --- | --- | --- |
| [Second Me](https://github.com/mindverse/Second-Me)（Apache-2.0） | 文档洞察 → 画像（shade、bio）→ 用合成数据做 LoRA 微调，本地小模型作答 | 画像与回答没有可核对的原话证据；没有按日期作答；资料里没有的事会编造（作者资料上不编造率 70%）；每次更新都要重新合成数据并训练；1.0.1 版只有一个 shade 时画像会变成空回复，训练数据随之失效，且界面显示成功；代码自 2025-05 起不再更新 |
| [Distilly](https://github.com/titanwings/distilly)（MIT，原名同事.skill） | 通读材料，生成一份人格与工作技能档案（Agent Skill），作答时只靠这份档案 | 没有检索和证据；档案一次性生成，更新靠重写；资料里没有的话题会用本人口吻编出立场（早期合成数据测试中，陷阱题 83% 被编造） |
| [WeClone](https://github.com/xming521/WeClone)（AGPL-3.0） | 用聊天记录微调 LoRA，复刻口吻 | 只学口吻，不管事实是否有据；需要训练，许可为 AGPL |
| mem0、Letta、Graphiti 等记忆框架 | 通用的智能体记忆 | 不是分身：没有人格维度、口吻和弃权规则；部分组件对中文支持差（例如 mem0 的 BM25 与实体抽取写死英文模型） |

### twin 怎么解决

| 问题 | twin 的做法 |
| --- | --- |
| 编造 | 回答只能依据检索到的档案条目和本人原话；依据不足时降低置信度或直接弃权 |
| 没有证据 | 每条档案条目都带逐字核对过的原话、日期和来源；引用不到的条目会被剔除 |
| 不能回到过去 | `--as-of` 只用某一天及以前的资料作答 |
| 更新要重新训练 | 不做 LoRA；新资料导入后增量抽取、重建索引即可生效。微调只能作为默认关闭的风格插件，在评测上显著胜出才允许打开 |
| 没有可信评测 | 内置评测框架：题库与资料留在仓库外，评委团、重复作答、按来源分组的置信区间、每次运行的来源记录 |
| 合成内容不标识 | 语音、导出文件都带显式和隐式的 AI 合成标识 |

### 评测能体现什么

**作者本人资料（59 题）。** 2026-10-05，同一套题库、同一个评分脚本和评委模型（Second Me 项目的 `judge.py`，`gpt-6.1-sol`）。twin 每题作答 3 次；表中 twin 取第 1 次回答，与 Second Me 每题一次的做法一致；Second Me 一栏取它几次运行中的最好值或区间：

| 类别 | twin | Second Me（升级后的第一阶段版本） |
| --- | --- | --- |
| 事实准确率（32 题） | **98.4%** | 78.1% |
| 资料里没有的问题不编造（10 题） | **100%** | 70% |
| 风格像本人（10 题，1–5） | **4.0** | 1.9–2.2 |
| 通用问题质量（5 题，1–5） | 2.6 | 3.0–3.2 |
| 记忆更新（2 题 × 增改删，6 分） | **6** | 3.5（删除 0/2） |

用 twin 自己的评测框架（3 次作答取平均、按来源文档 bootstrap）结果一致：事实 99.0%（95% 区间 94.7%–100%），不编造 96.7%（90%–100%），风格 4.23（4.0–4.5）。

读这组数字要注意：

- **作答模型不同。** twin 用前沿大模型作答，Second Me 用本地微调的 1.7B–4B 小模型。差距有一部分来自模型而不是方法；用同一个作答模型的对比还没有做。
- **评委与作答同源。** twin 的回答和评分都来自 `gpt-6.1-sol`，可能偏向自己；第二个不同家族的评委还没有加入。
- **通用问题更弱，这是取舍。** twin 只依据本人资料作答，遇到与本人无关的通用问题会说资料里没有，而不是像通用助手那样回答。
- **题少。** 不编造、风格各 10 题，通用只有 5 题，区间都很宽。

**早期原型的合成数据对比**（单次运行，题库按分身的验收点编写，有主场优势，只看方向）：

- 不编造：twin 的"不知道就说不知道"平衡准确率 100%，Second Me 方法 75%，Distilly 方法 58%。
- 口吻：**twin 明显不如 Distilly**，风格盲评中 Distilly 12 次胜 11 次。
- 事实回忆：全部笔记都能放进上下文时，Second Me 方法在决策追溯、台账上更好；资料规模变大后这个优势难以保持。

记忆更新一项是 twin 自己的评测框架在临时数据库副本上跑的：每步只导入或删除资料、增量构建，不重训；每步作答 3 次全对。只有 2 道题，样本很小。

**还没有被评测证明的。** 按日期作答、回答中转述原话的逐字核对率、成本与延迟。它们在路线图的第一步，见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

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
外部后端按配置使用，界面如实展示出境分类；用 `twin identity show` 查看，本机转发代理需声明 `egress = "external"`。

**网页快速开始**

运行 `twin ui`，按打印的本机地址**打开页面 → 你是谁 → 添加记忆 → 聊天**。
首次填写名字和一段介绍（也可以跳过）；介绍自动保存为“自我介绍”记忆，添加的内容会自动整理。
主导航只有“聊天 / 记忆 / 关于你”。在“关于你”随时修改名字与介绍、核对我了解到的你，也可选择“回答几个问题”。
名字保存后不再显示首次引导；没有记忆时聊天页会提示先添加。

**记忆上传**

```bash
twin persona import 问卷.md 聊天记录.csv 文章/*.md    # 自动识别类型，不用选择
twin persona import 简历.pdf 想法.docx 网页.html
twin persona note "我喜欢先核对事实，再做决定。"        # 写一段笔记
twin persona import --kind meeting 会议转写.txt      # 也支持 interview、biography
twin persona sources                                # 看已导入的资料
twin persona build                                  # 抽取并合并人格档案，只处理新增或变化的部分
twin persona coverage                               # 各维度的完成度，以及下一步该补什么资料
```

支持 TXT、Markdown、PDF（文字层）、Word（.docx）、HTML、CSV、JSON、SRT、VTT，自动识别文字编码（含 GBK）；每个文件最多 50 MB，扫描 PDF 暂不支持。日期默认取文件名，聊天缺失日期时取第一条日期，再回退到添加当天。需要强制类型时仍可用 `--kind`。

网页 `#/memories`（导航“记忆”）可以写一段、上传多个文件或整个文件夹。添加、删除后自动处理，不必点构建；可以查看分身看到的文字、记住的条数和失败重试。CLI 导入或笔记保存后，可运行 `twin persona build`，也可启动网页让它自动处理。

**服务**

```bash
twin persona chat "你怎么看远程办公？"
twin persona chat --as-of 2025-12-31 "那时候你怎么看？"
twin ui                                             # 本机网页：聊天、记忆、关于你；支持回放与朗读
twin api                                            # 令牌保护的本机 HTTP API（先设置 TWIN_API_TOKEN）
twin mcp                                            # stdio MCP，供其他工具和 Agent 使用
```

API/MCP 配置、接口与隐私规则见 [docs/SERVICE.md](docs/SERVICE.md)。

**语音（可选）**

在 `twin.toml` 的 `[tts]` 里配置语音后端：自托管的 MOSS-TTS-Nano（见 [deploy/tts-moss](deploy/tts-moss/README.md)）或 Cloudflare MeloTTS（外部服务，按配置使用）。

```bash
twin media speak 回复.json --out 音频目录/            # 带标识的分段语音和清单
twin media clip 回复.json --out clip.mp4              # 形象、字幕与标识；需系统 ffmpeg 和中文字体
twin media video 回复.json --out out.mp4              # [video] 通用 SSH 视频任务；常驻标识，见 docs/MEDIA.md
twin media check --out 评测目录/                      # 合成句集回听评测：字错率与延迟
```

浏览器 3D 形象可在 `[avatar]` 设置 `vrm_path` 指向本地风格化 VRM 文件（不入库）；未配置或加载失败时保留 2D 形象，见 [docs/MEDIA.md](docs/MEDIA.md)。

## 文档

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)：产品形态、分层、层间规则、治理、路线
- [docs/PERSONA_DIMENSIONS.md](docs/PERSONA_DIMENSIONS.md)：人格维度与完成度
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
