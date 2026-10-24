# Generic personal-twin contracts

Positioning: Identity → Memory upload → Service. Repository, project, Python package and CLI are named `twin`.

## Shared rules and backends

- `persona.schema` owns `ReviewStatus` and the source/chat contracts.
- All model calls go through `llm.structured`; Chinese prompts use stable system instructions and per-call user data. Quotes are verified against the privacy view actually sent to extraction.
- `util.run_parallel` preserves order, scopes usage context and persists completed results via `on_result`; failures do not abort a batch. Outputs quoting personal data use `open_private` (0600); new private directories use 0700.
- `llm.LLMError` and `embed.EmbedError` are the public backend error boundaries. Embedding responses must include one indexed finite nonzero vector per input with stable dimensions. Fingerprints identify the vector space without secrets.
- `config.Settings`: target name/aliases, privacy, database, concurrency, LLM, embedding, optional judges/pricing/budget, TTS and synthetic-speech ASR. OpenAI-compatible LLM endpoints require explicit model/base URL and never silently target a public default.
- Tests are offline with `FakeLLM`, `HashingEmbedder`, fake HTTP transports and temporary databases. Python 3.12, strict mypy and ruff are required.

## 记忆内核版本

- `persona.kernel` 是代码层 1 的无 I/O 契约；冻结的 `KernelVersion(schema, prompt, taxonomy)`、`KERNEL` 与稳定排序的 `kernel_json` 描述当前内核。版本常量由这里提供给 profile/dimensions。
- `rebuild_scope` 只在 prompt 改变时返回 `full`，taxonomy 改变时返回 `merge`，仅 schema 改变返回 `none`。无记录按 schema 1 / persona-v4 / v1 比较；现存无 `kernel:built` 的生产库因此视为已使用当前内核，不重抽、不提示。
- `PersonaStore` 先读 `PRAGMA user_version`，最新库设置 WAL 后直接返回，不获取写事务；旧库才在 `BEGIN IMMEDIATE` 内复读版本、按顺序执行 `_MIGRATIONS` 并更新版本。旧无版本库保留数据，失败回滚全部迁移并关闭连接；超前 schema 抛出中文 `NewerStoreError`，拒绝打开。只读 `schema_version()` 返回数据库实际版本。
- `p_meta['kernel:built']` 存稳定 JSON；只有成功且来源版本未变的构建才与 `built_at`、pending 标记在同一事务更新。失败不会宣告内核构建成功。
- `stale_reason` 返回 `sources` / `kernel` / null，首次有来源或来源时间变化优先；空白库不标过期。`pending_chunks` 复用分段和内容键，只计未抽取且资料已就绪的分段，不调用模型。prompt 进入分段键；taxonomy 为 v1 时合并键保持原公式，其他值才额外进入合并键。启动恢复、Web 状态及 CLI status 仅在内核范围不为 none 时估算待重抽分段，否则为 0。
- `[kernel] auto_rebuild=true`、`max_auto_rebuild_chunks=400`；启动时有内核差异且禁用自动重建或待重抽数量超过阈值时等待确认。`GET /api/status` 返回 `kernel: {version, built, scope, pending_chunks, state}`，state 为 ready/pending/queued/running/error/awaiting_confirmation；version/built 为版本对象，未记录 built 为 null；还没有资料和条目的分身 scope 为 none。两个 `[kernel]` 参数可在系统设置「系统参数」里由管理员改写（`data/system.json`，立即生效）。`processing.notice` 在等待确认时为“记忆内核已升级，需要管理员确认后重新整理；目前沿用旧档案”。
- `POST /api/kernel/rebuild` 使用当前分身，要求管理员及 `X-Twin: 1`，返回 202 `{job_id}`；复用原有互斥构建任务。系统设置「部件升级」用 `GET/POST /api/admin/system/components[/kernel]` 一次查看和升级所有分身（见 WEB_UI.md）。`twin kernel status` 逐分身显示版本、数据库实际 schema、范围和分段数；`twin kernel rebuild [--persona ID|--all] [--yes]` 默认配置分身，超过阈值必须显式 `--yes`。

## Identity 与用户建档

- `identity`（代码层 1）是无 I/O 的冻结契约：`name: str`、`aliases: list[str]`、
  `about: str = ""`、`name_source: Literal["config", "user"] = "config"`、
  `voice: str | None = None`、`avatar: str | None = None`。形象预置 ID 优先来自分身元数据，否则使用该分身的确定性默认（默认分身使用配置）；不构造媒体后端。
- p_meta 保存 `identity:name` / `identity:about`。Web、API/MCP 身份、聊天与网页生成提示使用保存名，
  缺省回退配置 target_name；说话人匹配增加保存名作为别名，不替换配置名字/别名。
  `PUT /api/identity` 要求 X-Twin: 1，输入 `{name, about}`，去除首尾空白后名字 1–20 字、介绍 ≤200 字。
  名字与介绍事务保存，介绍改变时替换标题为“自我介绍”的笔记并排队自动处理；清空删除旧笔记。
- **预发布 breaking change（I4）**：此前声明契约只增不删；本次按用户明确决定移除授权账本。
  删除 `ConsentEvent`、`Decision`、`Scope`、`Origin`、生物特征 scopes，以及 `Identity.consents`、
  `granted`、`from_parts` 和 `PersonaStore` 的授权读写方法。不再创建 `p_consent`；已有表不读取、不删除。
- `consented_facets` 仅由问卷推导：非 gated facet 始终允许；gated facet 必须回答且未拒绝。分类 v2 起没有 gated 维度（D9 生活与喜好也直接从资料建档），机制保留给以后的隐私版本。`build_profile(grant_gated=True)` 跳过这条规则，只供评测测量授权后的效果（`eval-suite --grant-gated-facets`），产品代码不传。
  保留 `Source.declined_facets`；跨来源的拒绝优先于回答。问卷变化后重建档案并清理对应条目向量。
- 音色校验仅是后端预置音色的格式与列表检查；2D 形象必须为预置，3D 形象由 `vrm_path` 指定。
- `twin identity show` 显示名字、别名、预置音色、预置形象与出境表（类型、提供方、主机、本机/外部、声明/推断）。
  `GET /api/identity` 返回 name/aliases/about/name_source/voice/avatar/avatar_preset/avatar_presets/egress，不再返回 consents 或 biometric；
  移除 CLI grant/revoke 和 `POST /api/identity/consent`。问卷授权规则不变，关于你页不展示技术覆盖指标。

## 出境分类（EgressInfo）

- `config.egress_of(section)`（代码层 2）返回冻结的 `EgressInfo`：`kind`（llm/embed/tts/asr）、
  `external`、`declared`、`host`、中文 `reason`。仅输出主机名，不含 URL 凭据、路径或查询串。
- 四类配置及每位评委可追加 `egress = "local" | "external"`，显式声明优先；否则 hashing/silent
  为本机，anthropic/claude_cli/cloudflare 为外部。OpenAI 兼容地址只有 localhost、127.0.0.0/8、::1
  为本机（理由为“本机地址，未声明是否转发”），LAN 和未知地址均为外部。LLM/embed 与工厂一样
  回退到 `OPENAI_BASE_URL`；TTS/ASR 只使用配置地址。本机转发代理必须声明 external。
- 出境由配置决定，界面如实标出；CLI、Web、API、MCP 和评测按配置正常构造外部后端，
  不读取授权、不设出境门禁或对应 403。`egress.egress_status(settings)`（代码层 9）仅提供展示行。
  `/api/status` 和 `/api/identity` 的 egress 列表含 kind/provider/host/external/declared，仅列实际配置且外部的服务（评委 kind=judge），无 granted。
  hashing/silent 和未启用的视频不出现在网页外部服务列表中；OpenAI 兼容后端要求模型和有效配置的端点。
  LLM/向量可用 OPENAI_BASE_URL，TTS/ASR 与工厂一致要求各自 base_url；不将默认 ASR 当作已配置的外部服务。
- 后端仍懒构造并缓存，配置变更后重启；注入工厂仍用于离线测试。
  `media check` 仍仅用于合成评测句集（含自定义句集）。

## usage.py (tool layer 0)

- `UsageRecorder(pricing=None, max_cost_usd=None)` is thread-safe; `record_usage(recorder)` scopes a run,
  `call_stage(label)` scopes a coarse boundary, default `other`. `util.run_parallel` copies the caller's
  context independently into each worker, including nested pools. No dependency on persona or tracing vendors.
- Backend call sites emit one row per logical `structured` call, or per HTTP embedding batch. Rows contain
  stage, backend, configured model, SHA-256 identity of the canonical endpoint (no userinfo/query/fragment
  in the hash input; hashing also hides credential-like path components), nullable input/output,
  reasoning/cached tokens, characters, elapsed seconds, attempts, success, error **type only**, estimated USD,
  known partial USD and optional CLI-reported USD. No prompts, replies, keys or exception messages.
  FakeLLM and HashingEmbedder emit zero-token, zero-cost rows. Empty remote embedding input issues no call.
- Provider usage is captured before validation/refusal/truncation checks and summed across retries. SDK
  retries are disabled and transient HTTP/connection retries explicit; schema and CLI retries also count.
  Missing usage remains null, never synthesized from characters. `unknown_usage_attempts` marks incomplete
  input/output accounting; token sums are known subtotals, not claims of complete usage. Anthropic input
  includes its separately reported cache reads/writes. OpenAI reasoning/cached details are subsets of
  output/input, respectively, so cost never double-counts them.
- `[pricing."<exact model>"]`: finite nonnegative `input_per_m`, optional `output_per_m` (default 0 for
  embeddings), `reasoning_per_m` and `cached_per_m`. Absent detail rates inherit output/input rates.
  Unknown pricing or incomplete usage means `estimated_cost_usd=null` and CLI **费用未知**;
  `known_cost_usd` preserves priced reported subtotals. CLI-reported cost stays separately identified.
- `[budget] max_cost_usd` is optional, finite/nonnegative.
  Admission checks settled priced spend plus UTF-8 input bytes and the requested output cap as a conservative
  forecast. Budgeted attempts serialize admission/settlement, including retries. A sticky `BudgetExceeded`
  stops new wire requests and is checked again at run exit, even if individual errors are tolerated.
  No-price models cannot be budgeted; warn once at run start. Provider counts may differ from the forecast,
  usage may be absent and CLI output caps may be unavailable: this is not a hard provider billing limit.
- Generic `evals.provenance.write_report` writes private reports and redacts endpoint/query and secret string echoes without replacing JSON numbers. Traced persona CLI build/chat commands write `<db parent>/usage/<command>-<timestamp>/`; failed runs use a distinct failure directory.

## persona.schema / persona.sources (raw corpus and L2/L3 privacy boundary)

```python
def expression_view(store: PersonaStore, settings: Settings, *, source_id: str | None = None,
                    target_only: bool = False, until: date | None = None,
                    expressions: list[Expression] | None = None) -> list[Expression]
```

- The four converters (chat, interview, document, questionnaire) store original expression text and speaker names,
  irrespective of `settings.pseudonymize_others`. L1 reads remain raw.
- `Source.text_state: Literal["raw", "pseudonymized"]` is additive JSON metadata, with no SQLite column migration.
  New converters explicitly write `"raw"`. Missing metadata loads as `"pseudonymized"`: pre-change sources are
  left untouched, including when mixed with raw sources, because their original names cannot be recovered.
  Loading/building does not rewrite source rows. Re-importing the original file can replace the old row with raw
  expressions; there is no attempt to reverse the hashes or to guess which legacy rows retained raw text.
- `expression_view` is the sole expression privacy transform for profile extraction and PersonaChat context
  (retrieved expressions, channels, context, voice samples and evidence quotes). It never writes to L1 or changes
  IDs or dates. `expressions` can supply evidence-quote spans for the same transformation.
  With privacy disabled, raw sources stay raw; legacy sources still cannot recover their lost names.
- Known other names come from non-target speakers in **all raw corpus sources**, not guessed from prose. The same
  catalog applies to every source kind: a name learned from chat/interview is also replaced in documents
  and questionnaire answers/questions. Names never observed as speakers are not detected (this is not
  NER). Target names and aliases are protected, including occurrences inside other names; existing `他人XXXX`
  codes are never hashed again. Stable codes retain `pseudonym(name)`'s original SHA-256 first-four-hex algorithm.
- `index_persona(store, embedder, settings, progress=None)` requires the same settings as profile/chat and embeds
  `expression_text` of the view, never raw expressions. This includes other speakers' messages in `context`, even
  when the target text itself contains no other names. Vector SHA keys use the final viewed text, so privacy or
  catalog changes re-embed only affected raw rows; unchanged legacy rows retain their SHA keys/vectors and cause
  no embedding call. CLI and web builds pass their active settings. A third namespace, `others`, embeds what other
  speakers said to the person (`others_view`: their messages in the same view, from ready sources) so the twin can
  recall what it was told; chat shows these as others' words and never as the person's own.
- Profile chunks contain the view both as rendered prompt text and as verification entries: evidence quotes are
  verified against exactly the view sent to the extractor, not against raw L1. Chunk hashes remain content-based;
  a changed privacy setting or known-name catalog invalidates affected chunks on the next build without changing
  `PROMPT_VERSION` or invalidating unchanged legacy chunks. Rebuild the profile after changing privacy settings.

### Chat answer modes (L3)

- 聊天检索每次从隐私视图的 `item_text` / `expression_text` 构建 BM25（CJK 字符 bigram + ASCII 单词），与向量排名按 RRF(60) 融合；无向量时仍可按关键词召回，不改存储。
- `ChatDraft.mode` / append-only `ChatReply.mode` are `Literal["grounded", "general", "inferred", "abstain"]`,
  defaulting to `"grounded"`. Missing mode on legacy drafts/replies becomes `"abstain"` when `abstain=true`,
  otherwise `"grounded"`; missing `abstain` is derived as `mode == "abstain"`. Explicit inconsistencies are rejected.
- Owner-specific answers remain evidence-grounded; unsupported owner questions, commitments and judgements of
  specific other people abstain. Unrelated general knowledge/how-to answers use `"general"`, may omit citations, and
  have confidence capped at 0.5; they are said as know-how, never as the owner's own experience.
- The twin speaks as the owner at every boundary, not as an assistant referring to them: replies never mention
  material, records, the ledger or being a twin (unless asked whether it is the person or an AI), and never say
  "ask the person" or "needs the person's confirmation". A gap in basic personal facts is passed over for later, a
  forgotten detail is not recalled, an undecided plan is not yet sayable, a commitment is deferred ("let me get back to
  you"; what the answer leaves to the owner becomes a handoff, see 转交闭环), and another person is not judged behind their back. Only the
  wording changes: mode, abstention and confidence follow the rules above.
- `"inferred"` is the best inference for "what would they choose/do/prefer/think" questions the material does not
  answer directly but has indirect evidence for (related past answers, stated values, traits, habits). The text states
  it is an inference and never presents it as something the owner said or did; factual recall, commitments and
  judgements of specific other people never use it. Finalization requires at least one valid citation (otherwise the
  reply becomes `abstain` with confidence ≤ 0.3), caps confidence at `INFERRED_CONFIDENCE_CAP` (0.5, also enforced by
  `ChatReply`), and treats `answered=false` like a grounded miss. When the question fixes the output format (e.g. only
  an option label) the text may be just that; the inference status then lives in `mode`. The frontend states every reply's
  mode in the line under it (`有本人资料支持` / `根据资料推测，不是本人原话` / `通用建议，不代表本人观点` /
  `资料不足，需要问本人`, never a confidence figure) beside the evidence summary, whose side layer shows the original
  words; MCP/CLI append `（推测，非本人表达）` and WeCom a footer line; consumers that need the
  owner's own view must not treat `inferred` as `grounded`.
- `ChatDraft.asked` names the item the question wants and `answered` (default `true`) says whether the text supplies it.
  A `grounded` draft with `answered=false` is finalized as `abstain` (confidence capped at 0.3, reason defaults to the
  asked item); `general` and `abstain` drafts are unaffected. Replies follow the language of the other party's latest
  message; quoted original words stay verbatim and are verified as before.
- The system prompt names today's date: `PersonaChat.reply(today=…)`, else `as_of`, else the local date. `today`
  changes only the date the reply counts from, never which evidence is visible. Retrieved quotes and expressions are
  labelled with the date they were said (`原话（YYYY-MM-DD 说）`, `YYYY-MM-DD 说 · channel`).
- Each reply first makes one structured call (`persona.rewrite.rewrite`) naming up to five aspects of the person's
  material the latest user turns rest on, in Chinese with English keywords (for a specific policy, the political
  stance and related values). Retrieval ranks items and expressions for the turns and for those aspects, fusing the
  vector and keyword rankings of both with equal weight. An `LLMError` drops the aspects; budget stops propagate.
- With at least `persona.style.MIN_GRADED` graded questionnaire answers visible at `as_of`, the system prompt gains an
  答题风格 section giving the share answered at the strongest end (Chinese and English intensity words, each part of a
  matrix answer counted once) and asks inferred graded answers to follow that habit rather than default to the
  moderate option. Chat-only profiles get no such section.
- Questions about spans, recency, order or totals (`persona.derive.needs_derivation`) get one extra structured call
  that lists the dated events and quantities the retrieved material states, each tied to a record id. Code drops facts
  citing unknown ids or dated after today, then computes days since today, gaps between consecutive events, totals and
  change per unit into a `【推算】` section of the user message; the reply may treat those values as given by the
  material. The call is skipped for other questions; an `LLMError` leaves the section out, budget stops propagate.
- Quotation marks may enclose only verbatim text from speaking samples or retrieved material, never emphasis,
  terms or paraphrases presented as the owner's words. The other grounding rules remain unchanged.
- Chat log JSON appends `mode` without a SQLite migration. `chat_demand()` excludes general questions from both
  asked and abstained facet counts and counts inferred answers as asked and as gaps (no direct evidence existed); legacy logs without mode retain their previous demand behaviour.

### 两档记忆与会话归属（团队版二·1）

- **档位**（`persona/tiers.py`）：每条档案条目属于“同事能用”（`colleague`）或“只有本人能用”（`self`）。默认档按细项定（`DEFAULT_TIERS`：家庭、健康与运动、生活习惯与作息、兴趣爱好、品味偏好、常讲的经历与故事、情绪触发与压力反应、最近在想或纠结的问题默认只有本人能用，其余同事能用；兴趣爱好和品味偏好的默认档待定，先按私密算），本人逐条改的存在分身库 `p_item_tiers`（`_MIGRATIONS` 第 5 条，只存改过的）。默认档表在 `tiers.py`，不在 `dimensions.py`，也不进内核指纹：换默认档不触发重新整理，`PROMPT_VERSION` / `TAXONOMY_VERSION` 不变（`KernelVersion.schema` 随迁移数加到 6，不影响 `rebuild_scope`）。重新合并一个细项时，本人改过的档沿候选编号带到新条目；本人设成“只有本人能用”的条目在候选对不上时，按引用的原话带给所有引用它的新条目（宁严勿松），本人开放的档只沿候选带。
- **会话档位 `audience`**：`PersonaChat(..., audience=)`，`"self"` 可以用全部条目，`"colleague"`（默认）只能用同事档条目。过滤发生在检索之前（`PersonaChat._items`）：候选、BM25、核心画像（同事版和本人版）、说话样本以外的材料、推测的依据都只来自能用的条目；模型根本看不到别档的条目，所以逐段回答、`retrieved_ids`、`citations` 里也不会有它；`inferred` 引用了不在 `ctx.ids` 里的条目会被丢掉，没有依据的推测按弃权。`ledger=True` 只在 `audience="self"` 时生效（`ledger and audience == self`）。本人原话和别人对本人说过的话本身没有档位，但只有“只有本人能用”的条目所依据的那些话（`tiers.private_expressions`：条目证据里的原话编号，同事档条目也依据同一句的除外）同事档同样看不到——检索、说话样本、依据详情里都不出现，否则条目藏起来，原话照样能被找出来；承诺账本只给本人档。
- **谁是本人档**（`Personas.audience`）：没开登录时（只有一个人在用）是 `self`；开了登录，只有认领了这个分身并点过“没问题”的人（名册里的 `member` 且有 `approved_at`）是 `self`；管理员、建分身的人、访客、还没认领的分身的任何人都是 `colleague`（管理者聊天按同事档，也看不到只有本人能用的条目）。网页请求在 `scope["twin_audience"]` 里带着它；HTTP 服务（`/api`）、MCP、企业微信和命令行以外的入口不带档位，一律同事档，命令行 `twin persona chat` 是本人在自己的机器上聊，按本人档。
- **会话建立时定档**：`POST /api/conversations` 把会话记进团队库（`teamdb`）的 `conversations`（id、分身、提问人、`audience`、`via`、`delegation_id`、标题、更新时间、`deleted_at`），之后每次提问、改名、删除跟着刷新。聊天请求带 `conversation_id` 时，`ConversationIndex.audience` 取索引里的档，且不超过此刻提问人的档（本人把分身退回后，自己的会话也只能按同事档答）；索引里没有的会话（索引写失败，或建在索引之前）一律是同事档。不带会话编号的请求按此刻的档。工作模式的任务同理，`WorkTask.audience` 建任务时定下，旧任务是同事档。
- **条目接口按观看者的档**：`GET /api/persona/items`、`/items/search`、`/items/summary`、`/coverage`、`POST /items/{id}/review` 对同事档的观看者（管理员、建分身的人）只包含同事能用的条目，看不到的条目 review 返回 404；每个条目多 `tier`（`colleague` / `self`）和 `tier_changed`（本人改过）。`PUT /api/persona/items/{id}/tier` 体 `{"tier": "colleague" | "self" | null}`（null 回到细项默认档），只有本人档的观看者可以改，其余 403，条目不存在或看不到 404。`cited_view` 对同事档也不给出别档条目和承诺账本。
- **轮次加“本人”角色**：分身库 `conversation_turns` 多 `handoff_id`（`_MIGRATIONS` 第 6 条，同一会话里同一个转交编号唯一）；`append_conversation_turn(..., role="self", handoff_id=...)` 同一个编号重复写入时跳过并返回 `False`，旧会话的轮次不受影响（`get_conversation` 的轮次只有带编号的才有 `handoff_id`）。网页接口不接受客户端写入 `self` 轮次（`SavedTurn.role` 仍是 `user` / `twin`），前端类型先加上、不显示。
- **团队库** `data/team/team.db`（0700 / 0600、WAL、自己的 `_MIGRATIONS`、迁移前快照在 `team/snapshots/`、比程序新就拒绝打开、`meta` 表记对账时间）；会话索引是分身库的可重建副本，启动时按各分身库对账（缺的补成同事档，标题时间同步，已不存在的标已删除，它们的待办转交同时撤回），命令行 `twin team reconcile`（对账）、`twin team reindex`（按各分身库重建，已在索引里的会话保留原来的档位，其余同事档；分身库里已没有的会话，待办转交同样撤回，与对账一致）。分身进回收站时索引隐藏（接口按活着的分身过滤），7 天后彻底删除时索引一起删。备份照旧复制整个 `data/`，新库自动在内。
- **覆盖度四档**：`GET /api/persona/coverage` 每个细项的 `level` 改成 0 还不了解 / 1 提到过 / 2 了解一些 / 3 了解较多（`level_labels`），另有 `trusted`（有一条本人原话或本人确认过的依据）和 `checked`（了解较多且测试题至少 3 道、准确度到 0.7；`checked_label` 是“回答经过检查”，不是第五档）；方面的 `covered` / `sufficient` / `verified` 分别是第 1 档以上、第 3 档、第 3 档且 `checked` 的占比；补全建议只给第 0、1 档的细项。同事档的观看者看到的覆盖度只按同事能用的条目算。
- **people 与团队表**：`GET /api/library/people` 每个人多 `last_meeting`（`{recording_id, title, date}`，观看者能看到的录音里最近一场）、`talk`（观看者能聊天的分身编号，别人公开的分身也有）、`twin_id`（该人的分身在观看者自己的分身列表里的编号，不论能不能打开或聊天：本人声音认领的分身、别人公开的分身都有；只用于前端去重，同一个分身不出现两行）；自己建的、别人公开的、按工号建的分身没有录音库的人时自动补一个人（只补有名字的分身，不连录音库、不跟着转写；分身改名后，只为它补的、不在任何录音里的人跟着改名，录音里的人仍叫会议里的名字），名字已经是某个人的名字时不按名字合并，响应的 `matches` 列出等建分身的人确认的（分身、人、名字），`POST /api/library/people/{id}/same` 体 `{persona_id, same}` 确认是同一个人（连上）或不是（以后不再问，记在团队库 `meta`）。手工建的分身的人，只有管理员和建分身、认领它的人能改名或删除，管理录音的同事不行。
- **团队名**：`PUT /api/admin/system/team` 体 `{"name": "…" | null}`（管理员，最长 20 字，存 `system.json`），`GET /api/admin/system`、`/api/whoami` 带 `team_name`，`GET /api/auth/methods` 也带 `team_name`（登录前就能读；登录页沿用 main 的样子，目前不显示）。

### 转交闭环（团队版二·2）

- **回答时判断**：`ChatDraft` / `ChatReply` 多四个字段，都有默认值，旧的元数据和旧会话照常读：`owner_part`（`none` / `decide` 要本人决定 / `commit` 要本人答应 / `evaluate` 要本人评价某个具体的人 / `missing` 只有本人答得了而资料里没有）、`owner_ask`（要本人定的那一件事）、`commit_what`、`commit_due`（`commit` 时对方要的事和截止日期，一年以外的日期当作没有）。它是对这一次回答单独的判断，**不从 `abstain` 推导**：有实质回答、另有一部分要本人定的混合回答也标；能按资料或账本里已有的说法答的不算。流式输出的元数据 JSON 里多这四个字段，没有时省略即可；`ChatMeta` 补元数据时同样带上。聊天提示词多一节“转交”（`HANDOFF_SECTION`，只在 `reach="owner"` 时加），人称不变；`PersonaChat(..., reach=)`：`owner`（有人认领的分身、同事档会话）要标，`unclaimed`（没人认领，没有人能接）提示词改为“{名字}还没认领分身，请直接联系本人”且 `owner_part` 一律 `none`，回复里没有这句时代码补上（`_hand_over`），`none`（本人自己的会话和不做转交的调用方，默认）不加这一节。检索改写（`rewrite`）多一个 `owner_cue`，问的是要本人答应、拍板、评价时为真；`OWNER_CUE` 的关键词在改写失败时顶上。
- **先核后显**：`owner_cue` 为真且 `reach` 不是 `none` 时，`stream_reply` 不逐字输出，等 `_finalize` 去掉对不上的引号之后把核对过的正文作为一次 `delta` 给出，再给 `final`；其余回答仍逐字显示、结束后才去引号。这只改输出的时机，不改抽取。
- **本人的原话在会话里算数**：本人回复写进会话后，同一段会话里提问人再问，`PersonaChat.reply/stream_reply(owner_said=...)` 把它放进用户消息的【本人亲自答复】一节（系统提示词多一节“本人已经亲自答复的”，最近 4 条，可被引用、不算编造），以它为准。`owner_said` 由服务端按会话读（`PersonaStore.owner_replies(conversation_id, asker)`，只读提问人自己的会话里的 `self` 轮次），不来自请求体；请求体里的 `ChatTurn.role` 仍只有 `user` / `twin`，页面伪造不了本人的话。
- **聊天提示词与内核指纹**：`ChatDraft`、`ChatReply`、聊天提示词、检索改写都不在 `profile.prompt_fingerprint()` 里，所以 `PROMPT_VERSION` / `TAXONOMY_VERSION` 不变（`tests/test_kernel.py` 通过）；抽取、合并和维度没有动。
- **团队库 `handoffs`**（`teamdb` 的 `_MIGRATIONS` 第 2 条，`conversations` 同时多 `asker_name`）：每个提问人、每段会话各一条，唯一键 `(conversation_id, turn)`，同一段会话里同一个问题（`group_key`，按 `followup_id` 归一）还在等的时候不再生成第二条。字段：`persona_id`、`owner`（建立时的本人账号，换人后仍归原来的人）、`conversation_id`、`turn`（触发的那一轮）、`asker` / `asker_name`、`via`、`kind`（`decide` / `commit` / `evaluate` / `missing` / `inferred`——最后一种只在本人更正分身的推测时出现）、`question`、`context`（提问人上一句）、`ask`、`commit_what` / `commit_due`、`status`、`outcome`、`reply`、`reply_tier`（`none` 不存进记忆 / `colleague` 存，条目档位照细项默认 / `self` 存，但同“记一下”选“只有我”：来源记 `note_tier:` 为 `self`，由它做成的条目只有本人的对话用得到，回复转交时由本人选）、`reply_turn`、`ledger_id`、`group_key`、`created_at`、`expires_at`（七天）、`replied_at`。没有认领的分身不生成；`conversation_id` 为空的是“来源不明”（旧的待你回答迁来的），只能存进记忆，不能写回。
- **七种状态**：`delivered` 已送达、`replied` 已回复、`accepted` 已接受、`declined` 已拒绝、`dismissed` 不答、`expired` 已过期、`withdrawn` 已撤回，另有写回中间的 `writing`（正在写回）。`expired` 在读的时候由 `expire_due` 补上，过期的仍可回复或放回；提问人删会话时，没处理完的（已送达、写回中、不答、已过期）改 `withdrawn`，已经回复的保持原样；分身彻底删除时转交和更正记录一起删，进回收站时按活着的分身过滤。
- **本人回复写回只写一次**（`handoffs.HandoffDesk._settle` / `finish`）：① `TeamDB.begin_reply` 一条 SQL 把已送达、不答或已过期的转交原子地改为 `writing` 并存下回复，同时来的几个回复只有一个成功，其余得到 `HandoffUnavailable`（接口 409）；② 分身库追加 `self` 轮次（`conversation_turns.handoff_id`，同一会话同一转交唯一，已有就跳过），并存成记忆（`parse_answer`，来源编号由转交编号定，重复存是同一条）；③ `finish_reply` 标成 `outcome`（`replied` / `accepted` / `declined`）并记下第几轮。启动时（`create_app` 里 `handoffs.run_all`）把卡在 `writing` 的重做一遍，靠第 ② 步的唯一编号不重复写；会话已被提问人删除时标 `withdrawn`，不写、不存。`GET /api/conversations/{id}` 给提问人读：`self` 轮次带 `handoff_id`，被转交的 `twin` 轮次带 `handoff:{id, status, status_label, owner_name, kind}`；流式的 `final` 事件也带 `handoff`，页面不必再取。
- **生成转交的顺序**：分身那一轮写进分身库后，`HandoffDesk.raise_for` 再写团队库；团队库失败只记日志，不影响会话；启动时 `reconcile` 在近 14 天的同事档会话里找 `owner_part` 不是 `none`、却没有转交的轮次补上。
- **承诺“待你接受”**：`LedgerStatus` 多 `pending_accept`（“待你接受”），`LedgerEntry` 多 `origin`（`meeting` / `conversation`，默认 `meeting`）和 `handoff_id`，旧条目没有这两个字段照常读，不提 `LEDGER_VERSION`。`commit` 转交生成时同时写一条这样的承诺（编号由转交编号定，重复写是同一条；`source_id` / `expression_id` 是 `handoff:{id}`，`quote` 是提问人的问题，`counterpart` 是提问人），会议重新整理不会碰它。`pending_accept` 的承诺不进会前简报的“你答应过他的”，聊天里标“对方求我答应，我还没接”。接下后状态回到按线程推导、审核标已确认（改了日期标已修改）；不接时审核标已拒绝。
- **接口**（分身范围，只有本人档的观看者可用，其余 403；`GET /api/conversations/*` 除外）：`GET /api/persona/handoffs`（`waiting` 等你决定、`guessed` 分身推测、`sourced` / `sourced_count` 有出处、`answered` 近 `days`=7 天答了几问、`shelved` 不答和已过期、`settled` 已处理、`pending`）、`GET /api/persona/handoffs/count`（账户上的数字：待决定条数）、`POST /api/persona/handoffs/{id}/reply`（`{text, remember=true, tier?}`，`tier` 为 `none` / `colleague` / `self`，不带时 `remember` 决定是 `colleague` 还是 `none`；`HandoffDesk.reply` 的 `tier` 同，记忆在 `_remember` 里存，`self` 时紧接着 `set_note_tier(来源, self)`，重做时同一个来源再设一次无妨）、`/accept`（`{due?}` 接下，可改时间，回复里写一句“接下了：…”）、`/decline`（不接）、`/dismiss`（不答）、`/restore`（放回，再等一周）、`/draft`（请分身起草：用本人档的记忆和这一问起草一段回复，只返回 `{text}`，不发送不存；要本人定的地方写成“【请你定：…】”，带着它的回复被拒 409，改完才能发；`HandoffDesk.draft`）；`GET /api/conversations` 每条多一个 `owner_replied`（最后一句是本人的回复），对话列表据此标“本人已回”；`POST /api/persona/answers/{conversation_id}/{turn}/confirm`（没错）与 `/correct`（`{text}` 更正：写进提问人的会话、存成记忆、记一条 `inferred` 转交）；`POST /api/persona/ledger/{entry_id}/accept` / `decline` 是账本里对 `pending_accept` 条目的同一件事。接下和不接只写一句固定的话进会话，不存成记忆；已用文字回复的承诺型转交，之后在账本里接下只改承诺和状态，不再写第二个轮次。
- **旧的“待你回答”**：启动时按分身把 `persona/followups` 的问题迁成转交一次（编号 `legacy-{分身}-{问题}`，`kind=missing`，没有提问人和会话，进度记在团队库 `meta` 的 `handoffs:legacy:{分身}`；待回答→已送达、已回答→已回复、已忽略→不答）。旧接口 `/api/persona/followups*` 再保留一期，改动同步到对应的转交；页面已经读转交。`persona/followups.py` 的聚合和回答整理不变。

### 我的分身和全部对话（团队版二·3）

- **本人档助手**（`persona/assistant.py`）：本人和自己的分身说话（会话档位 `self`，并且开了登录、确知是本人；没开登录时没人是“本人”，聊天照旧是分身）用第二份提示词 `ASSISTANT_SYSTEM`，由 `PersonaChat(..., assistant=True)` 选用，只在 `audience="self"` 时生效；同事、渠道、命令行、评测都不传，仍是分身第一人称。第二人称：“你 10 月 15 日说过……”；能用全部条目、承诺账本和别人对本人说过的话；资料里没有时回“资料里没有这条，要补一句吗？”（`mode=abstain`）；起草用本人口吻；不转交（`reach` 仍是 `none`）。流式输出格式 `ASSISTANT_STREAM_FORMAT` 的元数据字段是 `asked、answered、citations、confidence、mode、abstain、abstain_reason、topic_facets、promise_what、promise_to、promise_due`，没有 `owner_*`。这是聊天提示词，不在内核指纹里，`PROMPT_VERSION` / `TAXONOMY_VERSION` 不变；抽取、合并、维度没有动。
- **`ChatDraft` / `ChatReply` 多三个字段**（都有默认值，旧元数据、旧会话照常读）：`promise_what`（本人在这句话里说他答应了的事）、`promise_to`、`promise_due`。只有 `assistant` 时才填；其余聊天一律为空。
- **本人说了的承诺直接生效**：回复保存时（`append_reply(..., assistant=True)` → `persona.assistant.record_promise`）把它写进承诺账本：`origin=conversation`、`status=None`（按线程推导，即开着）、审核 `confirmed`、`owner` / `speaker` 是本人、`counterpart` 是对象、`source_id` 是 `said:{会话}`，编号由会话和轮次定（重复写是同一条），会议重新整理不会碰它；回复的元数据里多 `commitment`（`entry_id`、`what`、`to`、`due`），随回复保存，界面据此写“已记入承诺”。账本写不进去时回复里不带承诺，不会说记了而没记。
- **“记一下”**：本人档助手会话里，消息以“记一下 / 记一记 / 记一笔 / 记住 / 记下来 / 记下 / 记着”（前面可有“请 / 麻烦 / 帮我”）开头，后面有内容且不是问句，就记成一条笔记：不问模型，不丢；回复是固定的一句，元数据多 `note`（`id` 是资料编号、`text`、`tier`）。笔记是一条 `note:` 来源（标题“记一下 月-日 时:分”），由下一次整理变成条目；档位记在分身库 `p_meta` 的 `note_tier:{资料编号}`，不新增表。默认“只有本人能用”（`DEFAULT_NOTE_TIER`），本人再选：`PUT /api/persona/notes/{资料编号}/tier` 体 `{"tier": "none" | "colleague" | "self"}`（只有本人；`none` 是不存，删掉这条来源；只能改“记一下”记下的，其余 404）。`GET /api/conversations/{id}` 把每条 `note.tier` 刷成当前的（已删的是 `none`）。
- **笔记的档位到条目**：`PersonaStore.set_note_tier` 记下档位并把它写到已经站在这条来源上的条目；之后整理出的条目在 `replace_facet_items` 里按它定档（本人对条目自己改过的优先，一个条目站在几条笔记上时只要有一条是本人的就是本人的，见 `tiers.note_item_tier`）。整理出条目之前，笔记自己的原话也不给同事档：`tiers.PrivateWords` 按来源编号（表达编号以来源编号开头）把“只有本人能用”的笔记的原话从同事档的检索、说话样本和依据详情里挡住，`PersonaChat._private_expressions` 和 `cited_view` 都用它；同事档的观看者（管理员、建分身的人）读 `GET /api/persona/sources` 时这条来源不在列表里，`/sources/{id}/text` 是 404。“记一下，我答应……”只记成笔记，不进承诺；要进承诺直接说“我答应……”。
- **看同事会得到什么**：`POST /api/persona/chat/stream`（和带附件的那个）体多 `preview: true`，只有本人可用（别人 403，非流式 `/api/persona/chat` 400）。只取最后一条消息，按同事档（`audience=colleague`、没有账本、`reach` 同真正的同事问时，没有人称转换）用同一个检索和提示词答一遍，`persist=False`：不存会话、不记提问、不生成转交。最后的 `final` 多 `preview.withheld`：同一问题在本人档的检索里找到、却不给同事的条目（`id`、`facet`、`text`，最多 3 条）。`retrieved_ids`、`citations`、`cited` 和同事真去问时一致（`tests/test_web_assistant.py`）。
- **`GET /api/conversations/{id}`** 多 `audience`（这段会话按哪一档答，没有档位记录的是 `colleague`）。
- **跨分身的会话列表** `GET /api/personas/conversations`（团队库的会话索引，不带分身头，没有逐人请求）：只列这个登录人自己提的会话（别人问他的分身的，他看不到），限于他看得见、不在回收站的分身。参数：`offset`（每页 50）、`with`（只看某个分身）、`mine`（只看和他自己的分身〔`Personas.own_twins`：认领了、点过“没问题”的〕的本人档会话和任务，也就是“我的分身”；不带时这些不在列表里，和自己分身的旧会话〔建索引前或还没点“没问题”时的〕是普通会话，照常在）。返回 `conversations`（`id`、`persona_id`、`title`、`preview`（最后一句话的前 120 个字，从各分身自己的库读，列表搜索用）、`updated_at`、`via`、`handoff`：该会话里转交的进展，如“等本人回复”“本人已回”，没有就是空）、`tasks`（`task_id`、`persona_id`、`title`、`status`、`updated_at`，第一页才带，读各分身的 `work/`）、`more`（还有下一页）、`mine`（`{persona_id, pending}`，`pending` 是等他决定的转交数，没有自己的分身或没开登录时是 `null`）。名字和头像不在里面，前端按 `persona_id` 对 `/api/personas`。

### 补一补、导入转写稿和承诺汇总（团队版二·4）

- **承诺汇总** `GET /api/personas/commitments`（`web/commitments.py`；不带分身头，要有至少一个自己管理的分身，管理员是全部，承诺功能关闭时同 `/api/persona/ledger` 一样 403）：读这个人管理的各分身库的账本（不存新东西，也没有缓存），一条一条合成一张表。同一场会在几个人的账本里各有一份，各自从自己主人的角度写（“本人”是账本的主人），所以先把“本人”（`owner`、`counterpart`、`speaker`）换成主人的名字，再按“同一场会（录音库的录音编号，分身来源编号 `src_lib_<录音>_<摘要>` 里的那段；别的来源就是来源本身）、同一行（`expression_id` 的序号，同一段录音在各分身的来源里编号相同）、同种类、同一个负责人”算同一件事，每件事只留一条：先留负责人自己账本里的，其次本人看过的，再其次把握大的，再其次靠前的分身。每条多 `persona_id`、`persona_name`、`meeting`；条数等于各人账本合起来去掉重复之后的条数（`tests/test_commitments_summary.py`）。负责人对不上同一个名字（另一边没认出是谁，写成“其他人2”）的不会被认作同一件事，宁可多一条也不丢。从录音库做出来的分身，记忆在按改动的归属重新整理（`gate.MemoryUpdating`）时，它的账本自己的接口也 409，汇总同样先不算它、把它列在 `updating`（`[{id,name}]`），整理完才回来（`/api/personas/commitments` 不拦整条，免得一个分身整理时全队都看不到）。
- **导入转写稿**（把单分身已有的转写稿解析搬到录音库）：`persona.sources.parse_turns(name, data)` 用单分身导入同一套规则读文件（`extract_text` 的 txt / md / docx / pdf / srt / vtt / html，`speaker：话`、`speaker 时间` 后接话、`[时间] speaker：话` 这几种行；飞书妙记、通义听悟、腾讯会议的导出是这几种之一），返回每一轮的说话人（写成什么就是什么）、话和开始的时间（秒，`1:02:03` 或 `12:30`，没有就是 `None`）；不到 3 轮，或没有谁说过第二次，就不是转写稿（400）。钉钉听记没有拿到样本，也没有格式线索，不单独认。录音库多一种录音：`Recording.kind = "transcript"`（`Library.add_transcript`）：不转写、直接 `ready`，同一个文件（SHA）再导入是原来那段；说话人的编号就是标签（`林舟`、`说话人 3`）；`Transcript.timed` 为真（每一轮都有时间）时每段从该轮的时间（相对第一轮）到下一轮开始，时长是最后一轮的结束，否则所有段落在 0，`duration_s` 为空，说话人的秒数按字数估（每秒 4 个字）；说话人没有声纹（`embedding` 为空）、没有试听。录音库行和录音页的日期取 `creation_time`（转写稿是导入者给的日期），没有就取添加日；转写稿时长是约数，界面写“约 N 分钟”。`proofread` 和 `named` 记成转写稿自己的编号，所以不排队校对和辨认；不进“听过再复核”（`Reviews.waiting` 跳过）和“重新采集”（`recollectable` 跳过）。`Team.sources` 把它交给分身时 `TwinSource.kind = "transcript"`，分身的来源按音频算（同会议），只有 `timed` 时每行带 `[mm:ss]`。归属：名字（宽度、大小写、空格不计）和团队里某个人的名字一样、且只对上一个人的，导入时归给 TA；`发言人1` 这类标签不对名字；上传的人在窗口里选的优先；不选的留着，之后在录音页或“待处理”的“还没认人”里认，“不是团队成员”是 `unknown`。这些决定走 `Team.decide`，算上传的人的决定（不是 `auto`），没有声纹样本，**不改 `ATTRIBUTION_VERSION` / `CLEANUP_VERSION`**（自动归属和复核的规则没动）。预览和导入都按上传的准入判断（`Libraries.admit`）：这个人排队转写的文件达到 `max_pending` 返回 409，磁盘余量不足返回 507，预览不返回 `turns`、`minutes`、`generic`。接口见 WEB_UI.md：`POST /api/library/transcripts/preview`、`POST /api/library/transcripts`。
- **补一补**（`persona/fill.py`、`web/fill.py`）：问题是 `persona/questionnaire.py` 的题，不新写；挑题按 `coverage_report` 的建议次序（还不了解先于提到过，细项编号为序），默认不问默认档是“只有本人能用”的细项，`?facet=` / `?dimension=` 是本人点开的，那时不论档位。回答先整理成草稿：`persona.profile.chunks_of` 把这段回答当成本人的话（`parse_answer`，渠道“补一补”，不存）切成块，用**同一个抽取提示词和同一个抽取函数** `extract_chunk` 读，其他人的名字照常换成代号，草稿里换回名字；没有写新提示词，没有改输出结构和维度，`PROMPT_VERSION` / `TAXONOMY_VERSION` 不变。存：每条留下的结论存成一个来源（`parse_answer`，本人的话，来源编号由问题和结论定，重复存是同一个来源），档位用 `PersonaStore.set_note_tier` 记在来源上，条目整理出来时按它定档，和“记一下”相同；之后的整理照旧。存之前给本人看的“升到哪一档”是把这些来源当成一次本人原话的场合，用 `coverage.facet_coverage` 在现有条目上加上去算的，整理出来之后的实际档位可以不同（抽取可能把它归到别的细项）。网页上固定问卷的页面拿掉了（`#/questionnaire` 跳到成员页），`/api/persona/questionnaire*` 和 CLI 保留。

### 组织层（团队版二·5）

团队库（`teamdb`）`_MIGRATIONS` 末尾追加三条，各管一块：第 3 条 `team_answers`、`team_answer_vectors`；第 4 条 `facet_coverage`；第 5 条 `delegations`（`conversations` 早有的 `via`、`delegation_id` 开始用上）。仍然是追加、迁移前快照、比程序新就拒绝打开。分身进回收站期间，它的团队答案不被引用（聊天、⌘K、代问都按活着的分身过滤，恢复后又能引用）；7 天后彻底删除时，`forget_persona` 把它的团队答案改成已撤回（连向量一起删）、覆盖度缓存和代问记录删掉。

**a 团队答案**（`teamanswers.py`、`handoffs.py`、`web/handoffs.py`、`web/team_answers.py`）

- **表** `team_answers`：`id`、`persona_id`、`owner`（确认人账号）、`title`（归纳的问法，默认是第一条的问题，可改）、`body`（本人的回复，可改）、`handoff_id`（从哪条转交来；一条转交同时只能有一个没撤回的团队答案）、`item_id`（预留，现在不填：回复存进记忆后条目要等下一次整理才出来）、`source_id`（同时存进记忆的那个来源）、`status`（`valid` 有效 / `stale` 可能过期 / `withdrawn` 已撤回）、`stale_note`（哪天哪场说了什么）、`judged`（上次核对看过的“之后说的话”的标记）、`confirmed_at`、`withdrawn_at`。`team_answer_vectors`：标题的向量，按向量模型的指纹分开存；没有向量或另一个模型的，下一次匹配时补做。撤回即删向量。
- **设为团队答案**：只有回答的本人（认领并点过“没问题”的人；`web.handoffs.person`，管理员、同事、访客 403，管理员不能代设）。两个入口：① 合并卡里勾“同时设为团队答案”（`POST /api/persona/handoffs/reply-many` 体里的 `team_answer: {title, body}`），② “常被问到”里的“设为团队答案”（`POST /api/persona/team-answers` `{handoff_id, title?, body?}`，转交必须已回复）。标题、内容为空时用第一条的问题和本人的回复；标题 1–80 字，内容 1–4000 字，超出或为空 400。企业微信、命令行、MCP、服务接口、评测的聊天不引用团队答案。这条回复同时按“同事能用”存进记忆（`parse_answer`，来源编号由转交编号定，已经存过的是同一个来源）。
- **“你不在时”按意思合并**（`teamanswers.merge_groups`，`GET /api/persona/handoffs` 多 `groups`、`often`、`answers`，每条等你决定的多 `twin_mode`）：只看等你决定、来源在对话里的“要决定”“无出处”两类（要答应的每个提问人各接各的，评价是对那个人的），问题的向量相似度达到向量模型自己的“算重复”的阈值（`cluster_threshold`：bge-m3 0.82、哈希 0.6，没有校准过），或问法归一后相同（`group_key`），就是一件事（单连接分组），两条以上才成组；没有向量模型或失败时只合问法相同的。**只在界面上合并**：转交还是每个提问人、每段会话各一条，数量、状态、归属都不变；`groups` 是转交编号的列表。“拆开分别回”是前端本地的。
- **一次回几个人**：`POST /api/persona/handoffs/reply-many` `{ids, text, remember=true, tier?, team_answer?}`（最多 20 条；带 `team_answer` 时 `tier` 只能是 `colleague`，`none` / `self` 400）：先全部核对是本人的、文字没有留着“【请你定】”，每条各自走原来的三步写回（`HandoffDesk._settle`），回复只存成一次记忆（第一条成功的），其余只写进各自的对话；某条已被提问人删掉或已处理，进 `failed: [{id, detail}]`，不影响其他。需要团队答案时先核对标题和内容再发，发完用第一条成功的转交设；设不成功也在 `failed` 里说，已发的回复不撤。
- **常被问到**（`HandoffDesk._often`）：本人已回复、存了记忆（`reply_tier=colleague`）、还不是团队答案、没点过“不用”的转交，近 7 天里同事档会话中的分身回答引用过站在这条回复上的记忆（回答元数据的 `citations` 对上条目的证据）`OFTEN_USES`（2）次以上，列在 `often`：`{handoff_id, title, reply, askers, uses, days}`，最多 5 条。`POST /api/persona/handoffs/{id}/often/decline`（不用）记在团队库 `meta` 的 `answers:declined:{转交编号}`，设成团队答案后清掉。
- **同事问到时原样引用**：聊天（流式和非流式、本人的助手、“看同事会得到什么”）收到消息后，用最后一句（短于 12 字时带上上一句）去匹配全队的团队答案（有效和可能过期的，不含撤回的；向量相似度达到上面的阈值，最多 2 条，刚过阈值 0.06 以内的标 `partial` “只回答了”；提问人自己确认的不引用）。匹配到的成卡放进回复元数据的 `team_answers`：`{id, persona_id, owner_name, title, body, confirmed_at, status, stale_note, partial}`——**不带当初是谁问的**；同时在给分身的用户消息里加【团队答案】一节、系统提示词加“## 团队答案”（`TEAM_ANSWER_SECTION`：卡片已原样显示，不要改写或复述，只补卡片没有的，带“可能已经变了”的提醒以本人为准，不再说“资料里没有”或转给本人），分身自己的话单独成块。这是聊天提示词，不在内核指纹里，`PROMPT_VERSION` / `TAXONOMY_VERSION` 不变。有团队答案卡的回答不自动生成转交（`HandoffDesk.raise_for`、启动补做都跳过），提问人要问本人，点卡片上的“还有疑问，问某某”：`POST /api/personas/team-answers/{id}/ask` `{question?}`（不带分身头；登录人，不能是确认人自己，答案已撤回 404，确认人还没认领 409），在确认人的分身里以提问人名义新开一段同事档会话（提问 + 分身一句“已转给某某本人”），并生成一条“无出处”转交（`HandoffDesk.hand_over`），回复回到这段会话。已经发出去的对话里的卡片不改，只是读取时把状态换成现在的（有效 ↔ 可能过期；撤回的不换）。
- **可能过期**（`TeamAnswers.check_stale`）：分身整理完（自动构建和问卷提交后的构建）调用一次：取本人确认之后（含当天）说的话（本人的原话，不含这条回复自己的来源，会议和对话都算），按和这条团队答案的向量相似度挑最近的 3 句（相似度不到“重复阈值减 0.2”、下限 0.3 的不看），问聊天模型有没有哪一句明确改了或否定了答案（`Contradiction.index`，0 表示没有），有就标 `stale`，`stale_note` 写“日期「来源」里说：原话前 80 字”。看过的话标在 `judged`，没有新的话不再问模型；模型失败只记日志，答案不变。本人的三个动作：`PATCH /api/persona/team-answers/{id}` 更新（标题、内容，恢复有效，重做向量）、`POST …/keep` 仍然有效（记下现在看过的，不再因同样的话标过期）、`POST …/withdraw` 撤回（之后不再被引用；撤回后再更新或再撤回 409）。`GET /api/persona/team-answers` 列出有效和可能过期的（过期的在前）。

**c 这事谁懂**（`finder.py`、`web/ask.py`）

- `GET /api/personas/ask?q=`（不带分身头；登录人；问题 2–300 字）返回 `{team_answers, people, meetings, decision, degraded}`：团队答案（同上，最多 2 条）；该问谁（最多 3 人）；相关会议（最多 3 场，每场带 `line`：那一句在录音页转写稿里的序号，从 0 数）；`decision` 问题里有要人拍板、答应、评价的词（`OWNER_CUE`），界面写“具体要他拍板，他的分身会转给本人”；`degraded` 向量模型不可用，只找会议。名字的查找仍在前端。
- **排人**：把问题的向量和各分身里“同事能用”的条目的向量比（条目向量就是聊天检索用的 `items` 命名空间，不复制内容），相似度不到“重复阈值减 0.3”（下限 0.3）的不算；每个分身取最相近的 6 条；分身最相近的那条要在全队最相近那条往下 0.12 以内才保留（不然就是别人比它相关得多），它自己最相近那条往下 0.12 以内的算“和这件事有关”，它们的细项就是这件事落在的方面；人按这些细项上的了解程度排：先看档（还不了解的不推荐，只有“提到过 / 了解一些 / 了解较多”），同档看场合数，再看最近一次，再看相似度，最后看分身编号，不出分数。只用同事能用的条目（本人档的条目既不被找、也不被算），了解程度按 `persona.coverage.facet_coverage` 的四档算。**不推荐**：提问人自己，没有人认领的分身，没开放给同事问的分身（`public` 为假），整理中的分身（`MemoryUpdating`），没有条目或条目和这件事对不上的分身。
- **覆盖度缓存** `facet_coverage`（`persona_id, facet_id, level, occasions, last_seen, kernel, updated_at`，只存第 1 档以上的细项）：分身整理完刷新（`refresh_coverage`）；改档位、复核、删资料这类不经整理的改动，靠 `PersonaStore.items_signature()`（条目数和大小、复核状态、档位、`built_at`、条目向量模型的小标记）发现：问的时候标记和缓存里记的（团队库 `meta` 的 `coverage:signature:{分身}`）不同就重算，所以本人把一条改成“只有我”，下一次问就不再找到他。缓存删了（`TeamDB.forget_coverage`）下次问时重做；内核版本变了也重做。
- **延迟评估**（`uv run python scripts/bench_finder.py`，合成数据，不含向量模型自己算问题向量的一次调用，本机）：41 个分身 × 300 条（1024 维）：第一次问 ≈0.47 秒（读全部向量、算覆盖度），之后 ≈0.09 秒（向量在内存里，每个分身只看一眼标记），一个分身变了 ≈0.10 秒，内存 39 MiB；100 × 600：第一次 ≈1.9 秒，之后 ≈0.27 秒，187 MiB。结论：现在的规模不需要把条目向量另存进团队库，进程内按标记失效的缓存够用；每次问的时间主要花在逐个打开分身库看标记上，人数再多一个数量级时再考虑把标记和向量存进团队库。
- **会议**：按字词（BM25）在看得到的录音的逐句转写（校对过的）里找，看得到的录音就是 `Libraries.access`（上传的、认出自己的，管理员是全部）；一场只取最相近的一句（至少两个词对上、占问题词的三分之一以上），给 `{recording_id, title, date, speaker, quote, start}`，说话人是确认过的才写名字。逐句转写读一次放在内存，录音有变化才重新建索引。

**b 分身之间对话（助手代问）**（`delegations.py`、`web/delegation.py`、`web/persona.py`）

- **表** `delegations`：`id`、`initiator`（发起人账号）、`persona_id`（发起人自己的分身）、`conversation_id`（“我的分身”里那段）、`question`、`created_at`。问到的每个人在 `conversations` 里各有一段会话：`via=delegate`、`delegation_id`、同事档、提问人是发起人、`asker_name` 是“发起人（助手代问）”。
- **怎么发起**：只有本人在“我的分身”里（会话档为本人档、开了登录、确知是本人，不是试问）说“帮我问问某某：……”（`delegations.CUE`：帮我 / 替我 / 帮忙 / 给我 + 问问 / 问一下），由程序认出，不靠模型，也不会自己去问。写在冒号前面的必须全是能问的名字（未开放的、没有的名字当场说“没有找到「X」”），没有冒号时从句首起认名字（长名优先）。一次最多 3 位，重名、没写问题、问自己各回一句话，**不问任何人、不记代问**。能问的是这个人看得到的分身（公开的或自己管理的）里不是自己的；还没认领的也能问（它答“请直接联系本人”之类，没有可转的人）。
- **怎么问**（`Delegations.ask`）：先记一条 `delegations`，再**按说的顺序**给每个同事的分身各开一段发起人的会话（同事档、`via=delegate`，写库时检查），再并行各问各的：和同事自己来问一样的聊天（`reach` 照该分身的本人、同事档记忆、承诺账本不用、不是助手口吻，所以回答里“要本人定”的部分照常标 `owner_part`），但**不自动生成转交**；同事本人确认过的团队答案命中该分身时直接用（回一句“团队里已经有确认过的答案”和卡片，不问模型）；某个分身整理中、模型失败，就在它那段会话里记一句“暂时没能回答”，不影响其他人。最后助手用聊天模型归纳一段（`Summary`，不替本人答应、不加事实，失败就没有）。助手那一轮的回复是“已用你的名义问了王屿、陈一，本人看得到。”，元数据 `delegation: {id, summary}`。问的过程占一个聊天名额，期间每 10 秒一个心跳。
- **只走一跳（写库层）**：`TeamDB.create_delegation` 只收发起人自己的、本人档、直接问的会话（`audience=self`、`via=direct`、分身对得上、没删）；`record_conversation(via=delegate)` 要求有对应的代问、同事档、提问人就是发起人、不是发起人自己的分身，一次代问最多 3 段（已写的会话再写不重复计）；`create_handoff` 对代问的会话只收 `via=delegate` 的（所以分身自己的回答、启动补做都做不出转交），`via=delegate` 的只收对得上的代问会话和同一个提问人。代问出去的会话是同事档，不是“我的分身”，它里面再说“帮我问问……”只是普通提问。
- **读和决定**（只有发起人，在自己的分身的上下文里，其余 403；找不到 404）：`GET /api/persona/delegations/{id}` 返回 `{id, question, targets, limit}`，每个 `target`：`persona_id`、`name`、`conversation_id`、`state`（`answered` 答了 / `needs_owner` 要本人定 / `skipped` 先不用 / `handed` 已转、等回复 / `replied` 本人已回）、`answer`、`mode`、`ask`（分身标的“要本人定的那一件事”）、`team_answer`、`handoff`（`status`、`status_label`）、`owner_reply`、`also`（答案里“问沈从”“找陈一”式地指到的、还没问的同事，最多 2 个，已满 3 位时没有）。`POST …/forward` `{conversation_id}` 转给本人：这时才生成一条转交，以发起人名义（`asker_name` “发起人（助手代问）”、`via=delegate`、`kind=missing`、`ask` 用分身标的那一句），进同事本人的“你不在时”，本人回复回到这段会话，卡片显示“本人已回”；没认领的或已转过的 409。`POST …/skip` 先不用（记在 `meta` 的 `delegation:skipped:{会话}`，不生成转交）。`POST …/ask` `{persona_id}` 也问问某某的分身：同一个问题再问一位（发起人决定，仍然离发起人一跳；满 3 位、已问过、问自己、不能问的 409）。
- **列表**：`GET /api/personas/conversations` 每条多 `delegated`（这段会话问了几位，没有是 0）；`?mine=true` 第一页多带上发起人的代问会话（`via=delegate`，别的分身的），前端放在“问同事”下；“全部”里本来就有，标“助手代问”。`TeamDB.conversations` 多 `via`、`delegation_id` 两个筛选，按代问取时按问的先后排。

### 赋能（团队版二·6）

（`lenses.py`、`web/lenses.py`、`teamdb.py`）本人把自己的判断借给同事用：在自己成员页的“赋能”里起名、勾选开放的细项、选给谁用，随时暂停、撤回。管理员不能代为发布（见下）；“挂赋能”“采纳写回”“名人赋能”不在这一期。

- **表**（团队库 `_MIGRATIONS` 第 6 条）：`lenses`（`id`、`persona_id`、`name`、`facets` 开放的细项编号 JSON、`audience` JSON、`status` `active` 生效 / `paused` 暂停 / `withdrawn` 撤回、`forgiven` 纠正后重新开放时不再计的次数 JSON、`published_at`、`ended_at`）；`lens_uses`（`id`、`lens_id`、`question`、`said`、`facets`、`corrected`、`at`）。**`lens_uses` 没有提问人这一列，也不连会话、转交**：只记问题、赋能说的话、用到的细项、有没有被纠正，和日期（`at` 只到天，不存几点）。分身彻底删除时，它的赋能和使用记录一起删。
- **只借判断**：能开放的细项只在看重什么、怎么做决定、怎么思考、擅长什么四个方面里（`LENS_FACETS`）；经历、说话方式、和人相处、近期关注、生活和喜好永远不进。
- **按细项判断、按大类开放**（`lenses.judge`，只看“同事能用”的条目，本人档不算）：细项同时满足两条才够格——①了解较多（`facet_coverage` 的第 3 档，这一档已经计入场合数、本人原话和来源种类，不再单独卡）；②没有矛盾条目。不够格的细项给一个原因（“了解还不够多 / 内容有矛盾 / 只有本人能用 / 还没有记忆”）。发布时按 4 个大类（看重什么、怎么做决定、怎么思考、擅长什么）选，选一类就开放这一类的全部细项；一类里至少一个细项够格才能开放，否则发布和调整时拒绝并点名大类（400）；回答只用够格的细项，其余细项等记忆够了自动加入。✓“回答经过检查”照样标出（`checked`，现在没有测试题时不出现）。录音库分身与别的分身同样判断，不另设规则。门槛暂定，未经赋能盲测（验证③）；覆盖度本身不变。
- **谁能用**：`audience` 是全团队（`team`）或指定的人（`people`，按对方认领的分身编号记，对方以登录账号认领的分身为准；账号列表不对前端公开）。分身没认领、进了回收站、正在整理记忆时不能用；设计稿里的“销售部”需要部门，现在没有这个概念，没做。
- **使用中再查一遍**（`lenses.in_use`）：赋能说话用的细项 = 开放的 ∩ 此刻仍满足门槛的 ∩ 没被纠正停用的；开放后出了矛盾、本人把条目改成“只有我”，下一次问就不再用。同一个细项被纠正 3 次（`STOP_AFTER`，暂定）停用，本人调整范围时重新勾上它即重新开放，之前的纠正不再计（`forgiven`）。
- **赋能怎么说**：不调用聊天模型，也不编：把问题和开放细项里的条目比（词有两个以上对上且占问题词五分之一以上，或向量近到和 ⌘K 排人一样的下限；没有向量时只比词），取最相近的至多 3 条（每个细项至多 2 条），原样给出条目的话和依据（本人原话在前，每条至多 2 句、120 字，经过和聊天一样的隐私视图，只靠本人档条目的原话不出现）。问到价格、折扣、审批、拍板这类（`SETTLED_BY_PERSON`、`OWNER_CUE`）另加“具体怎么定：未开放，可直接问某某”；没有对得上的条目就说没有能回答的，可以直接问本人。每条标“根据某某说过的话推测，不代表某某的意见”。赋能自己不转交、不写记忆、不写承诺。
- **同事怎么用**：在对方的分身里聊天时，输入框旁多一个“赋能”按钮（有可用的赋能才出现）：`GET /api/persona/lenses/available` 返回此刻能用的赋能（名字、实际在用的细项）；`POST /api/persona/lenses/{id}/ask` `{question, conversation_id?}` 把问题和赋能的回答写进提问人自己的会话（回复元数据多一个 `lens` 卡片：`{id, name, owner_name, views[{facet_id, facet, text, basis[{quote, date, kind}]}], empty, settled_by_person, note}`），同时记一条使用记录（不含提问人）；赋能暂停、撤回、不对这个人开放、分身没认领都是 404，整理记忆中 409，本人自己问自己的赋能 403（预览用 `POST /api/persona/lenses/preview`）。这两个接口和别的聊天接口一样放行给访客（同事）。答不上时的“问某某本人”是另一个请求，`POST /api/persona/lenses/ask-owner` `{conversation_id}`：由提问人点了才以提问人自己的名义生成一条普通转交（`kind=missing`，进本人的“你不在时”，本人看得到是谁问的），和赋能的使用记录互不关联；已转过、本人没认领 409，不是自己的会话 404。
- **本人的接口**（`web.handoffs.person`：认领并点过“没问题”的本人，管理员、同事、访客 403）：`GET /api/persona/lenses` → `{lenses, facets, stop_after}`（未撤回的赋能：`id`、`name`、`status`、`audience`、`facets`、`speaking` 现在在用的、`failing` 开放了但此刻不满足的、`stopped` 被纠正停用的 `[{facet_id, name, corrected}]`、`uses_week` 近 7 天用了几次；`facets` 是全部能开放的细项逐个的 `{facet_id, name, dimension, level, label, checked, occasions, ok, reasons}`）；`POST /api/persona/lenses/preview` `{facets}` 看看读起来什么样（不发布、不记）；`POST /api/persona/lenses` `{name, facets, audience}` 发布（名字 1–20 字）；`PATCH /api/persona/lenses/{id}` 改名字 / 范围 / 给谁用；`POST …/pause`、`…/resume`、`…/withdraw`（撤回后不能恢复、不能再改，409，要用就重新发布；撤回的不再列出）；`GET …/uses?facet=` 使用记录（新的在前，至多 50 条）；`POST …/uses/{use}/correct` 纠正一条。
- **“管理员可以邀请本人发布”不做**：管理员只能邀请、不能替本人打开；邀请需要记录和通知，设计稿里的邀请卡没有对应的数据，先不放，本人自己在“赋能”里发布。

### Pre-release removals (P3)

- Deleted `persona.transcripts`, `persona.transcript_schema`, `Meeting`, `Utterance`, meeting converters,
  `SourceKind.MEETING/BIOGRAPHY`, `parse_biography`, `Source.meeting_id` and expression utterance/timestamp fields.
  CLI/API import rejects `meeting` and `biography`; existing database source rows and nested candidate/item
  evidence of either kind normalize to `document` on read, including document-filtered queries. IDs and text
  are preserved; old JSON/SQL rows are not rewritten. Unknown removed JSON fields are ignored.
  Legacy `narrated`/`own_words` provenance remains so third-party text is not presented as the owner's own words.
  Dedicated third-person/classical-Chinese prompt rules and biography voice fallback are removed.
- Removed questionnaire `round=retest`, held-out question flags/filtering and retest UI. Only `initial` is accepted;
  every submitted answer is profile evidence. The unused SQLite `held_out` column remains solely for opening old
  databases and receives zero on new writes; no query uses it. Legacy rows remain readable, including former
  held-out answers. Old retest metadata is ignored.
- Questionnaire version is `q-v1`: 20 optional everyday questions covering nine topics. Old `q-v0` answers are
  not displayed under new questions; previously imported sources remain and are replaced on next submission.
  Facet IDs stay stable; names use general-life wording (`taxonomy v1`). Extraction/merge statements omit pronoun
  subjects, and existing profiles remain readable across the current kernel baseline.

- Removed CLI chat `--as-of` and Web `ChatBody.as_of`; Web chat always uses current material. Eval and service
  HTTP/MCP retain optional advanced `as_of`. Coverage date filtering is unchanged.
- Removed archived biography eval payloads and their `decision/stance/voice/trap` type discriminator.
  Only the personal scenario and question input/expected/output contracts remain; old biography eval reports are
  no longer supported (this does not affect user databases).
- Unused `[twin] k_principles/k_question_patterns/k_tradeoffs/k_stances/k_cases/k_directives`,
  `persona_principles`, `segment_window_chars` are not settings. Old/unknown keys are silently ignored,
  without warnings. CLI `persona coverage` remains with plain-language output.

## Free-form memory ingestion (code layer 4; Web layer 9)

- `sources.extract_text(name, data) -> str` delegates to `persona.text`: pypdf reads PDF text layers (empty → `这个 PDF 没有可提取的文字（可能是扫描件）`), python-docx reads paragraphs/table cells, EPUB chapters are read in spine order from the OPF package (stdlib zip/XML, DRM-protected books fail with a Chinese reason), stdlib HTMLParser drops script/style and preserves paragraph breaks. Text/Markdown/CSV/JSON/SRT/VTT use charset-normalizer, preferring Unicode/GB18030 for short Chinese exports. Single-file limit: 1 GiB; unsupported suffixes are skipped with Chinese reasons. No OCR or personal-text logging.
- `detect_kind(name, text, settings=None) -> SourceKind`: questionnaire uses existing numbered-question/facet-tag and answer markers; chat uses ≥60% non-empty lines matching existing timestamped chat patterns, or CSV/JSON rows with time+sender+content aliases from the chat parser; interview uses ≥60% speaker lines and a configured target name/alias as speaker; otherwise document. Import date defaults to filename, then first chat date-like line, then today; existing dated expressions retain their dates.
- `POST /api/persona/import`: multipart `files`; optional `kind` (omitted means auto per file), legacy explicit `date` retained. Relative folder names are reduced to basename; any hidden path component is skipped. Response `{imported, skipped}` always lists per-file outcomes, including when all are skipped; imported entries append `detected_kind` and `detected_kind_label` (plain Chinese).
- `POST /api/persona/notes`: `{text, title?}`, text length 1–20000 and non-whitespace. Document source dated today, default title `笔记 YYYY-MM-DD HH:MM`; given title retained. Note origin has a `note:` prefix so its plain label is 笔记.
- `GET /api/persona/sources` appends `status: processing|remembered|nothing_found|failed` and `remembered: int` (distinct supported, non-rejected items), plus detected kind/label. Existing source-memory fields remain compatible; no preview is included. Failed processing is persisted separately from pending/built markers. `GET /api/persona/sources/{id}/text` returns text/plain from `expression_view`, first 20000 characters; missing source → 404. Raw L1 is never exposed by this endpoint.
- After successful Web import/note/delete, `PersonaProcessing` debounces about 3 s. It uses cancellable scheduling (injectable for tests) and JobManager exclusivity; edits during a running build coalesce into exactly one follow-up. Backend construction occurs inside the job, so adding memories works before models are configured. Failures remain retryable via `POST /api/persona/build` (202 job_id). Last finish/error survive restart; queued/running jobs do not. UI startup requeues stale memory, including imports/notes saved by CLI.
- `GET /api/persona/processing` returns `{state: idle|queued|running, job_id?, last_finished_at?, last_error?}`; a build in progress takes precedence over a queued follow-up. Error messages are sanitized; an old input-version failure is not assigned to newly added memories.
- Web chat without items returns 200 `ChatReply + cited`, friendly Chinese abstention explaining processing/no memories, before constructing backends. Persisting PersonaChat with no built profile also abstains without model calls. Non-persisting service/eval retrieval remains unchanged, including expression-only corpora.
- CLI: `twin persona import 文件…` auto-detects and prints the kind per file; `--kind` remains an explicit override. `twin persona note "文字"` saves a note. CLI build is unchanged; UI resumes pending CLI memory on startup.

## 会议录音认领（P2.2）

- `media.ingest.Transcriber.diarizes: bool` 显式声明说话人区分能力，CommandTranscriber=true、HTTPTranscriber=false；上传流程传给 `analyse`，保存为 `Analysis.diarized`。HTTP 的整段 S1 永不自动认领，suggested=null，进入 needs_speaker。
- 区分说话人时，单人无参考声音自动认领；有参考声音必须 similarity ≥ 0.6（null 不认领）。多人沿用全部有分数、最高 ≥ 0.6 且领先 ≥ 0.1 的规则，只认领一位。其他 ≥ 0.6 者列入 also_suggested，前端显示“可能也是你”，默认不勾选。
- `Analysis.claimed: list[str]` 是唯一认领状态；旧文件缺少 claimed 时由 speaker 迁移（null → []），diarized 缺省 true。speaker 为只读派生兼容字段，等于 claimed[0] 或 null。所有已认领者的表达均标为本人，仅未认领者编号“其他人N”；声音和形象候选使用全部已认领片段并剔除未认领者的重叠发言。
- `PUT /api/persona/sources/{id}/speaker` 接受 `{speakers: ["S1", "S3"]}`（[] 为旁观资料），继续接受 `{speaker: "S1"}` / `{speaker: null}`。两种字段只能提供一种，speakers 不接受 null；所有 ID 必须存在，按顺序去重。修改后替换表达、轮换 revision 使旧候选失效、排队重建。
- `GET .../speakers` 追加 claimed、diarized、also_suggested ID 列表，以及各 speakers 条目的 also_suggested 布尔值。前端多选后统一确认，保留独立试听；diarized=false 时说明“当前转写服务不区分说话人”，只给“整段都是我”/“都不是我（旁观资料）”。详见 [MEDIA.md](MEDIA.md)。

## Memory upload queries and builds (code layers 3/5)

- `PersonaStore` 的 `p_meta.sources_changed_at` 为带 UTC 时区的 ISO 时间（微秒精度），仅在新增/替换来源、实际删除来源时，与对应写入同事务更新。`source_pending:<source_id>` 是来源等待构建的内部标记，成功构建后清除。
- `profile.source_memories(store) -> dict[str, SourceMemory]` 是纯查询：每个来源返回 `expressions_total/target/others`、`items_supported`、`facets`（facet_id/name）、`contributes_nothing`、`build_status`（not_built/remembered/no_items）。按证据 expression_id 查询实际来源，重复引用和跨来源条目对每个来源只计一次；未拒绝条目口径与完成度一致。仍存于上次档案的条目也计入支撑，过期状态独立展示。
- `profile.profile_stale(store) -> bool`：sources_changed_at 晚于 built_at，或来源非空而 built_at 缺失；旧无 sources_changed_at 的库兼容，旧 built_at 无时区时按本机时间解析。这个状态覆盖来源与内核版本变化，不追踪其他配置变化。
- `BuildReport` 保留原字段并追加 `facet_diffs: dict[str, FacetItemDiff]`；`FacetItemDiff` 含 `added/changed/removed`。比较 replace_facet_items 前后的原始 item_id 与 statement，不受人工审核替换表述影响；相同 ID 仅 statement 改变算 changed，ID 改变算 removed + added，证据/情境改变不算 statement diff。包含成功合并但零变化的细项，不包含失败或跳过的细项。
- BuildReport 提供派生总计 `items_added/items_changed/items_removed/facets_changed` 和 `change_summary()`。facets_changed 只计算有非零 diff 的细项；无变化增量构建总计为零。构建日志仅使用编号、计数及错误类型，不记录条目文本、来源标题或异常正文。
- 只有无失败且输入版本仍未变的构建，才由 `mark_profile_built` 同事务更新 built_at 并清除 pending 标记；built_at 记录本次构建开始时间。部分失败或构建期间来源改变仍保持 stale，已完成结果保留供重试。CLI build/chat 在 stale 时向 stderr 提示，chat 仍运行。
- 细项合并调用失败（多为长输出超时）时，`merge_facet` 把这批候选分成两半各合并一次，仍失败的一半保留为未合并的单条条目，并抛出携带全部条目的 `MergeDegraded`。构建照常保存这些条目，记入 `BuildReport.degraded`（不进 `failures`，不阻止 `mark_profile_built`），但不写该细项的合并键，下次构建会重新合并。预算停止等非模型错误不降级。
- 条目不再逐条确认（破坏性变更，前端同步）：删除 `POST /api/persona/items/review-batch`；`GET /api/persona/items/summary` 去掉 `unreviewed`（总数和各维度），追加 `conflicts`（证据矛盾的未删条目数）。`GET /api/persona/items` 追加 `conflict=true`。新增 `GET /api/persona/items/search?q=&limit=20`（`q` 1–200 字、去空白后非空，`limit` 1–500），返回 `{items, total}`，按 `chat.search_items` 排序：聊天的条目混合检索（向量 + BM25，RRF 60），关键词还覆盖证据原话；嵌入服务不可用时只按关键词、只返回命中。访客不可用。
- 作答置信度：`PersonaItem.trusted` = 本人确认或修改过，或至少一条证据是本人原话（`own_words`）；只引用不可信条目（只有别人转述）的回答封顶 0.6，此前是只引用未确认条目就封顶。`review` 字段和 `confirmed` 状态保留，旧库的确认照常生效。

## Generic evaluation schema (code layer 1)

All contracts are frozen and forbid extras. `CaseInput` exposes only identity, personal scenario, mode and `QuestionInput(id, category, prompt)`; answers live separately in `QuestionExpected`. `Prediction` has `QuestionOutput(reply)`, nullable capabilities and explicit raw data. `Judgement` retains rubric verdicts; failed/uncalled rows have `score=None`. `Report` preserves records, policies, purposes, fingerprints, generic statistics and warnings. Development purpose requires a dev split; reports cannot mix purposes. Aggregation order is judge → repeat → case → group.

## evals/harness.py (layer 8)

- `Judge(llm, effort)` is defined here. `SystemUnderTest.spec` describes a prepared system;
  `predict(CaseInput, *, as_of, repeat)` never receives `Case` or expected answers. Scenario preparation and
  leakage checks remain the caller's responsibility.
- `run_predictions(cases, systems, repeats, as_of, max_workers)` returns `PredictionRun(predictions, failures)`.
  Order is system → case → zero-based repeat; horizons are computed once per case before execution.
  Exceptions or mismatched output identities produce `PredictionFailure(system_id, case_id, repeat, reason, error)`,
  not fabricated predictions. `reason` retains the diagnostic string; `error` retains the original exception
  (defaulting to `None` for manually constructed failures).
- `Rubric` supplies `rubric_id`, `rubric_version`, `applies(case, prediction)` and a callable taking
  `(judge, case, prediction, against)`. `run_judgements` returns prediction → judge → rubric rows in input order.
  The panel assigns zero-based `j{index}:{llm.name}` judge IDs, replacing rubric-supplied IDs while checking
  the other identity fields. Panel members sharing a backend name remain distinct for aggregation.
  Exceptions (including applicability errors) become `failed` rows with error text and no score;
  inapplicable rubrics produce `not_called`, not zero. Optional `against` selects a comparison prediction
  sharing case, mode and repeat; invalid comparisons are rejected before judging.
- `aggregate_scores` returns `(case_id, system_id, against_system_id) → float | None`, for one metric at a time.
  Judge means precede repeat means. `ALL_JUDGES_REQUIRED` invalidates an answer on any failed judge
  (including across repeats); `MEAN_OF_SUCCESSFUL` averages successful judges, then successful repeats.
  Uncalled/score-less rows do not affect means; no usable score remains `None`.
- `paired_case_ids` returns a system-keyed mapping of sorted case-ID tuples using non-null absolute scores.
  `ALL_SYSTEMS_INTERSECTION` uses the same intersection for every requested system;
  `PER_CONTROL_INTERSECTION` independently pairs each with the required control (which may be outside `systems`).
  Relative scores are already paired and are not treated as absolute scores. Both runners use `util.run_parallel`;
  outputs and failure records are identical for serial and parallel execution.


## Service presentation and access (S2)

- `service`（代码层 7）拥有冻结、禁止额外字段的 `ServiceCitation` / `ServiceAnswer` v1（ServiceAnswer 忽略旧 label 字段）。
  `answer_question(chat, question, as_of)` 是服务路径唯一的 ChatReply 适配器，调用
  `PersonaChat.reply([ChatTurn(role="user", content=question)], as_of=as_of, persist=False)`；
  问题超过 2000 字符时抛出不含输入的中文 ValueError。
- 引用按 L3 顺序解析，条目复用聊天 `_visible_items`（含 `item_as_of` 与证据隐私视图），
  表达复用 `expression_view(target_only=True, until=as_of)`；条目取最后可见证据，表达取本人文本，
  沿用聊天的空白整理/截断。返回 ref_id/kind/quote/date/source_kind，不暴露来源路径或审核备注。
- ServiceAnswer 包含 schema_version/answer/abstain/abstain_reason/confidence/citations/as_of/
  persona_name/generated_at（UTC），追加 `mode: Literal["grounded", "general", "inferred", "abstain"] = "grounded"`；
  文本、弃权、置信度和 mode 保持 L3 原值。
  `ServiceIdentity` 仅含 name/avatar/voice，不输出授权或备注。
- `api` / `mcp_server`（代码层 9）共用懒 ServiceBackend，配置 LLM 与 embed 均
  按配置使用外部后端，无出境授权门禁；注入 chat_factory 是可信测试接缝。后端配置变更需重启。
  每次默认请求关闭临时 store，不写聊天日志；进程内 UsageRecorder 使用 service 阶段、pricing 与累计 budget，
  不记录原文、不写追踪文件。
- HTTP 的 /v1/health 无鉴权；/v1/identity、/v1/ask 使用 Bearer + compare_digest。
  `[api] token_env` 默认 TWIN_API_TOKEN（至少 32 字符）；rate_per_minute 默认 30，
  单令牌 60 秒滑动窗口，429 附 Retry-After。Host 默认仅 loopback 名称，额外主机显式允许，
  非本机监听需 --allow-remote；请求体 16 KiB，问题 2000 字符。
- 官方 mcp SDK FastMCP 通过 stdio 提供 ask_twin 与 twin_identity，公布结构化输出 schema，
  文本直接呈现回答或姓名；后端错误固定中文消息，不记录个人文本。
  命令、请求/输出格式与客户端配置见 [SERVICE.md](SERVICE.md)。

## Web authentication and ownership

- `[auth] enabled = false` preserves local development, CLI and test behavior: no login, admin identity.
  Enabled auth requires SMTP configuration and an environment password, never Cloudflare Access headers.
- `web.auth` (layer 9) provides `/api/auth/request`, `/verify`, `/logout` and `/api/whoami`.
  Allowed email/domain comparisons are lowercase and exact; disallowed addresses dedupe into the waitlist without mail.
  Six-digit codes use secrets, salted hashes, 10-minute expiry and a five-wrong-attempt burn; successful consumption is atomic.
  Requests are limited per email (60 seconds / 5 per hour) and per IP (20 per hour, CF-Connecting-IP or peer).
  Sessions use random 32-byte tokens stored only as hashes, with email/expiry in private `auth.db` (0600).
  Cookie flags: HttpOnly, Secure except plain HTTP localhost, SameSite=Lax, Path=/, configured Max-Age.
- All `/api/*` routes except `/api/auth/*` and `/api/whoami` require a valid session when enabled,
  including media GETs. Missing sessions return `401 {detail:"请先登录",code:"login_required"}`.
  State-changing requests still require `X-Twin: 1`; static frontend serving stays public.
  `/api/admin/waitlist` is admin-only; allowing a user means changing config and restarting.
- Registry entries add `owner: email|null`; missing owner migrates to null (admin-owned, including default).
  Admins see/manage all; members only their own. Creating assigns the session email and enforces
  max_personas_per_member (default 3, 409; 0 = unlimited). Cross-owner persona selection or deletion returns 404.
  Members with no selection use their first twin, never default; none returns 409/no_persona.
  CLI/MCP keep using the configured database. Default portrait/voice fallbacks remain unchanged.
- Frontend checks whoami, shows email/code/waitlist screens, resends after a 60-second countdown,
  and returns to login on login_required, including upload/media requests. No token is stored in browser storage.
  no_persona opens creation; stale selections resolve to the first visible twin; the switcher supports logout.

## Web frontend serving

- `frontend/` is the only UI: React + TypeScript, HashRouter, built by Vite with base `/` into
  `src/twin/web/static/index.html` and hashed `assets/`. `web.app` serves `/` and `/assets/*`;
  `/next` and `/next/` are 308 redirects to `/`. There is no `/static` mount or non-API SPA fallback.
- Missing index returns a Chinese build hint (`pnpm -C frontend build`) while APIs remain available.
  Unknown APIs retain JSON 404s. StaticFiles contains asset paths and rejects escaping symlinks.
- Security headers and CSP are unchanged; API/5xx use no-store, frontend responses use no-cache.
  Client API requests stay same-origin and non-GET requests carry `X-Twin: 1`.
  The Vite dev server proxies `/api` to the default `twin ui` backend at 127.0.0.1:8765.
- UI behavior is covered by `frontend/src/test/`; build/HTTP contracts by `tests/test_web_frontend.py`.
  Frontend layout, tokens, motion, pages and endpoint details: [WEB_UI.md](WEB_UI.md).

## Media presentation (M0)

- `media.schema` (layer 1) defines frozen `PresentableAnswer`, `Segment`, `MediaCitation`, `MediaScript` and
  `MediaManifest`, version 1. It depends only on stdlib, pydantic and util; `PresentableAnswer` forbids extra fields.
- twin 是个人工具，不添加免责声明。
- 预发布契约移除媒体、形象与服务的 label/explicit_label 字段；旧清单和记录读取时接受并忽略这些字段，重新序列化不再输出，版本号仍为 1。保留导出文件的来源元数据 comment，不写 title 标签。
- `media.adapters` (layer 7) is the only media module that knows `ChatReply`; it validates raw JSON
  and produces `PresentableAnswer` with unchanged text and the upstream fingerprint.
  `media.script` (layer 7) converts only this boundary contract, without models, retrieval or rewriting.
  Sentence boundaries are Chinese/ASCII terminal punctuation clusters or line breaks outside `「」` / `“”` quotes;
  ASCII periods end a sentence only before whitespace, a closing quote or end of text, never between two digits.
  Only segment-edge whitespace is trimmed. Unclosed quotes conservatively retain the remainder together.
  `PresentableAnswer` appends `mode: Literal["grounded", "general", "inferred", "abstain"] = "grounded"`, preserved by the
  ChatReply adapter. General replies preserve all model content, including the first sentence, without added notices.
  The video adapter sends only speech segments.
  Abstention produces only an abstention notice, never speech; an empty reason has a neutral default.
- `source_fingerprint = util.fingerprint(source.model_dump(mode="json"))`: all validated source fields, excluding
  web-only resolved views, and independent of JSON key order. Persona display names do not change the source hash.
  Citations remain answer-level `(ref_id, reason)` objects; chat references have empty reasons. There is no inferred
  sentence-to-citation mapping. The manifest records the source hash, UTC creation time, generator and AI-generation metadata;
  it is provenance metadata, not a signature or verification of supplied answers.
- `twin media script ANSWER.json --out script.json [--kind chat_reply] [--persona-name NAME]` and
  `twin media export ANSWER.json --out playback.html` with the same options are offline, owner-only (0600) outputs.
  Default kind is `chat_reply`; default name is `settings.target_name`. Invalid input causes no output write.
  HTML rendering and `EXPORT_CSP` live in `media.render` (layer 7), shared by CLI and HTTP; `export_html` receives
  an explicit creation clock for deterministic tests. `web.media` (layer 9) only parses HTTP, invokes adapters,
  scripts and rendering, and serializes responses. HTML has no executable JavaScript or resources.

## Avatar and lip sync (M2)

- `LipSyncTrack` v1 is frozen and forbids extras: `fps: int = 25` (positive), `levels: list[int]`
  (strict integers 0–3, at most `fps × 600`), and `source: Literal["timings", "energy", "pattern"]`.
  `media.lipsync` (layer 7) prioritizes timings, then sniffed WAV energy, then synthetic rhythm;
  `render_audio` attaches the track without reading backend extras. Track time is local to each file.
- `AvatarSpec` v1 is frozen and forbids extras except ignored legacy labels: `avatar_id`, `palette` (exactly skin/hair/outfit/background/accent, six-digit hex),
  `mouth_states: Literal[4] = 4`, `stylized: Literal[True] = True`. No URL, path or image fields exist.
  `AVATAR_PRESETS` contains five approved illustrations and their flat palettes: chestnut (栗), wave (澜), bun (禾), stone (石), silver (岚).
  Legacy default/ink/dawn IDs alias to chestnut in configuration and persisted contracts.
- `AudioPart.lipsync: LipSyncTrack | None = None` is append-only; old manifests load with null tracks
  and display an idle avatar. HTTP audio segments carry the same nullable track.
- `Settings.avatar` defaults to `AvatarSettings(preset="chestnut")`; unknown presets produce a Chinese
  preset list. Capabilities always include the selected `AvatarSpec`,
  even when speech is unavailable. Identity preserves its string `avatar`; identity and capabilities also expose
  `avatar_preset` and `avatar_presets: [{id, name}]`. `identity:avatar_preset` metadata overrides the deterministic
  SHA-256 persona-ID choice (the default persona uses configuration). Manager-only `PUT /api/identity/avatar-preset`
  saves `{preset: id}` and returns updated identity; unknown IDs return Chinese HTTP 400 errors.
  `frontend/src/features/avatar/Avatar.tsx` renders the selected inline SVG with group-based blinking and four mouth levels.
  Playback samples the current part by audio time; pause/stop/text-only closes the mouth, close releases
  rAF and blink timers. Reduced motion disables blinking and limits openness to 0/1.

## Speech access (M1)

- `create_app(..., synthesizer_factory=...)` lazily defaults to `config.make_synthesizer(settings.tts)`.
  `silent` declares speech unavailable in the UI; HTTP capabilities expose backend, languages and formats.
- `TTSSettings.voice` accepts only preset IDs matching `^[A-Za-z0-9_.-]{1,64}$` (not `.` / `..`), rejecting
  paths, URLs and data references with a Chinese preset-only error.
  `SynthCapabilities.voices: list[str] | None = None` is additive; `None` means enumeration is unsupported,
  an empty list means no presets. Silent and Cloudflare declare `["default"]` and validate at construction;
  Cloudflare does not support speaker selection.
- The existing `synth.capabilities` property is retained. OpenAI-compatible speech lazily queries
  `GET {base_url}/voices` on first access and caches a valid string list from HTTP 200 or `None` from 404/405.
  It uses the speech transport's authentication, timeout, retry and no-redirect handling; other failures and
  malformed responses raise sanitized `MediaError` subclasses, not silent fallback. Failed discovery can retry.
  The configured ID is checked on capability access, before first synthesis; request IDs are also checked before
  POST whenever enumeration is available. Unknown IDs raise a Chinese error naming the ID and preset count.
- Cloudflare construction requires a nonempty configured key environment variable and names only that variable
  on failure; the self-hosted OpenAI-compatible shim keeps credentials optional.
- `POST /api/media/audio` uses the same source adapters and script contract, then `render_audio` into the database
  directory's `media-cache/`. Its ordered segment URLs may repeat a script index for split sentences; manifest
  and exported files retain the source fingerprint. Abstention speaks only notices, never answer content.
  Cache-file GET accepts only lowercase SHA-256 names with `.wav` / `.mp3`, resolves containment and retains
  security headers with `private, no-store`. POST keeps the 1 MB limit and `X-Twin: 1` rule. Backend-neutral
  unavailable / rejected / timeout / too-long errors map to 503 / 502 / 504 / 413 with fixed Chinese messages.
- `twin media speak ANSWER.json --out DIR [--kind chat_reply] [--name NAME]` calls only the configured
  speech factory and renderer, writing 0700 directories and 0600 audio, cache and manifest files. An unconfigured
  (silent) backend exits with a Chinese configuration error. Voice presets only; no rewriting or voice cloning.
- Browser speech starts directly with the reply content. Pause preserves the playhead, closure releases playback,
  and failures fall back to text.
