# Generic personal-twin contracts

Positioning: Identity → Memory upload → Service. Repository, project, Python package and CLI are named `twin`.

## Shared rules and backends

- `persona.schema` owns `ReviewStatus` and the source/chat contracts.
- All model calls go through `llm.structured`; Chinese prompts use stable system instructions and per-call user data. Quotes are verified against the privacy view actually sent to extraction.
- `util.run_parallel` preserves order, scopes usage context and persists completed results via `on_result`; failures do not abort a batch. Outputs quoting personal data use `open_private` (0600); new private directories use 0700.
- `llm.LLMError` and `embed.EmbedError` are the public backend error boundaries. Embedding responses must include one indexed finite nonzero vector per input with stable dimensions. Fingerprints identify the vector space without secrets.
- `config.Settings`: target name/aliases, privacy, database, concurrency, LLM, embedding, optional judges/pricing/budget, TTS and synthetic-speech ASR. OpenAI-compatible LLM endpoints require explicit model/base URL and never silently target a public default.
- Tests are offline with `FakeLLM`, `HashingEmbedder`, fake HTTP transports and temporary databases. Python 3.12, strict mypy and ruff are required.

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
- `consented_facets` 仅由问卷推导：非 gated facet 始终允许；gated facet 必须回答且未拒绝。
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
  no embedding call. CLI and web builds pass their active settings.
- Profile chunks contain the view both as rendered prompt text and as verification entries: evidence quotes are
  verified against exactly the view sent to the extractor, not against raw L1. Chunk hashes remain content-based;
  a changed privacy setting or known-name catalog invalidates affected chunks on the next build without changing
  `PROMPT_VERSION` or invalidating unchanged legacy chunks. Rebuild the profile after changing privacy settings.

### Chat answer modes (L3)

- 聊天检索每次从隐私视图的 `item_text` / `expression_text` 构建 BM25（CJK 字符 bigram + ASCII 单词），与向量排名按 RRF(60) 融合；无向量时仍可按关键词召回，不改存储。
- `ChatDraft.mode` / append-only `ChatReply.mode` are `Literal["grounded", "general", "abstain"]`,
  defaulting to `"grounded"`. Missing mode on legacy drafts/replies becomes `"abstain"` when `abstain=true`,
  otherwise `"grounded"`; missing `abstain` is derived as `mode == "abstain"`. Explicit inconsistencies are rejected.
- Owner-specific answers remain evidence-grounded; unsupported owner questions, commitments and judgements of
  specific other people abstain. Unrelated general knowledge/how-to answers use `"general"`, begin with a short
  general-knowledge/non-owner-view notice, may omit citations, and have confidence capped at 0.5.
  The frontend adds a neutral `通用回答 · 非本人观点` badge; `需要本人确认` is reserved for abstention.
- Quotation marks may enclose only verbatim text from speaking samples or retrieved material, never emphasis,
  terms or paraphrases presented as the owner's words. The other grounding rules remain unchanged.
- Chat log JSON appends `mode` without a SQLite migration. `chat_demand()` excludes general questions from both
  asked and abstained facet counts; legacy logs without mode retain their previous demand behaviour.

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
  subjects, and `persona-v3` causes re-extraction on the next explicit build. Existing profiles can still be read.
- Removed CLI chat `--as-of` and Web `ChatBody.as_of`; Web chat always uses current material. Eval and service
  HTTP/MCP retain optional advanced `as_of`. Coverage date filtering is unchanged.
- Removed archived biography eval payloads and their `decision/stance/voice/trap` type discriminator.
  Only the personal scenario and question input/expected/output contracts remain; old biography eval reports are
  no longer supported (this does not affect user databases).
- Unused `[twin] k_principles/k_question_patterns/k_tradeoffs/k_stances/k_cases/k_directives`,
  `persona_principles`, `segment_window_chars` are not settings. Old/unknown keys are silently ignored,
  without warnings. CLI `persona coverage` remains with plain-language output.

## Free-form memory ingestion (code layer 4; Web layer 9)

- `sources.extract_text(name, data) -> str` delegates to `persona.text`: pypdf reads PDF text layers (empty → `这个 PDF 没有可提取的文字（可能是扫描件）`), python-docx reads paragraphs/table cells, EPUB chapters are read in spine order from the OPF package (stdlib zip/XML, DRM-protected books fail with a Chinese reason), stdlib HTMLParser drops script/style and preserves paragraph breaks. Text/Markdown/CSV/JSON/SRT/VTT use charset-normalizer, preferring Unicode/GB18030 for short Chinese exports. Single-file limit: 50 MB; unsupported suffixes are skipped with Chinese reasons. No OCR or personal-text logging.
- `detect_kind(name, text, settings=None) -> SourceKind`: questionnaire uses existing numbered-question/facet-tag and answer markers; chat uses ≥60% non-empty lines matching existing timestamped chat patterns, or CSV/JSON rows with time+sender+content aliases from the chat parser; interview uses ≥60% speaker lines and a configured target name/alias as speaker; otherwise document. Import date defaults to filename, then first chat date-like line, then today; existing dated expressions retain their dates.
- `POST /api/persona/import`: multipart `files`; optional `kind` (omitted means auto per file), legacy explicit `date` retained. Relative folder names are reduced to basename; any hidden path component is skipped. Response `{imported, skipped}` always lists per-file outcomes, including when all are skipped; imported entries append `detected_kind` and `detected_kind_label` (plain Chinese).
- `POST /api/persona/notes`: `{text, title?}`, text length 1–20000 and non-whitespace. Document source dated today, default title `笔记 YYYY-MM-DD HH:MM`; given title retained. Note origin has a `note:` prefix so its plain label is 笔记.
- `GET /api/persona/sources` appends `status: processing|remembered|nothing_found|failed` and `remembered: int` (distinct supported, non-rejected items), plus detected kind/label. Existing source-memory fields remain compatible; no preview is included. Failed processing is persisted separately from pending/built markers. `GET /api/persona/sources/{id}/text` returns text/plain from `expression_view`, first 20000 characters; missing source → 404. Raw L1 is never exposed by this endpoint.
- After successful Web import/note/delete, `PersonaProcessing` debounces about 3 s. It uses cancellable scheduling (injectable for tests) and JobManager exclusivity; edits during a running build coalesce into exactly one follow-up. Backend construction occurs inside the job, so adding memories works before models are configured. Failures remain retryable via `POST /api/persona/build` (202 job_id). Last finish/error survive restart; queued/running jobs do not. UI startup requeues stale memory, including imports/notes saved by CLI.
- `GET /api/persona/processing` returns `{state: idle|queued|running, job_id?, last_finished_at?, last_error?}`; a build in progress takes precedence over a queued follow-up. Error messages are sanitized; an old input-version failure is not assigned to newly added memories.
- Web chat without items returns 200 `ChatReply + cited`, friendly Chinese abstention explaining processing/no memories, before constructing backends. Persisting PersonaChat with no built profile also abstains without model calls. Non-persisting service/eval retrieval remains unchanged, including expression-only corpora.
- CLI: `twin persona import 文件…` auto-detects and prints the kind per file; `--kind` remains an explicit override. `twin persona note "文字"` saves a note. CLI build is unchanged; UI resumes pending CLI memory on startup.

## Memory upload queries and builds (code layers 3/5)

- `PersonaStore` 的 `p_meta.sources_changed_at` 为带 UTC 时区的 ISO 时间（微秒精度），仅在新增/替换来源、实际删除来源时，与对应写入同事务更新。`source_pending:<source_id>` 是来源等待构建的内部标记，成功构建后清除。
- `profile.source_memories(store) -> dict[str, SourceMemory]` 是纯查询：每个来源返回 `expressions_total/target/others`、`items_supported`、`facets`（facet_id/name）、`contributes_nothing`、`build_status`（not_built/remembered/no_items）。按证据 expression_id 查询实际来源，重复引用和跨来源条目对每个来源只计一次；未拒绝条目口径与完成度一致。仍存于上次档案的条目也计入支撑，过期状态独立展示。
- `profile.profile_stale(store) -> bool`：sources_changed_at 晚于 built_at，或来源非空而 built_at 缺失；旧无 sources_changed_at 的库兼容，旧 built_at 无时区时按本机时间解析。这个状态只覆盖来源变化，不追踪配置变化。
- `BuildReport` 保留原字段并追加 `facet_diffs: dict[str, FacetItemDiff]`；`FacetItemDiff` 含 `added/changed/removed`。比较 replace_facet_items 前后的原始 item_id 与 statement，不受人工审核替换表述影响；相同 ID 仅 statement 改变算 changed，ID 改变算 removed + added，证据/情境改变不算 statement diff。包含成功合并但零变化的细项，不包含失败或跳过的细项。
- BuildReport 提供派生总计 `items_added/items_changed/items_removed/facets_changed` 和 `change_summary()`。facets_changed 只计算有非零 diff 的细项；无变化增量构建总计为零。构建日志仅使用编号、计数及错误类型，不记录条目文本、来源标题或异常正文。
- 只有无失败且输入版本仍未变的构建，才由 `mark_profile_built` 同事务更新 built_at 并清除 pending 标记；built_at 记录本次构建开始时间。部分失败或构建期间来源改变仍保持 stale，已完成结果保留供重试。CLI build/chat 在 stale 时向 stderr 提示，chat 仍运行。

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
  persona_name/generated_at（UTC），追加 `mode: Literal["grounded", "general", "abstain"] = "grounded"`；
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
  max_personas_per_member (default 3, 409). Cross-owner persona selection or deletion returns 404.
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
  `PresentableAnswer` appends `mode: Literal["grounded", "general", "abstain"] = "grounded"`, preserved by the
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
