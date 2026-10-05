# Generic personal-twin contracts

Positioning: Identity → Memory upload → Service. Repository, project, Python package and CLI are named `twin`.

## Shared rules and backends

- `persona.schema` owns `ReviewStatus`; `persona.transcript_schema` owns `Meeting` and `Utterance`, exclusively for lossless transcript corpus conversion.
- All model calls go through `llm.structured`; Chinese prompts use stable system instructions and per-call user data. Quotes are verified against the privacy view actually sent to extraction.
- `util.run_parallel` preserves order, scopes usage context and persists completed results via `on_result`; failures do not abort a batch. Outputs quoting personal data use `open_private` (0600); new private directories use 0700.
- `llm.LLMError` and `embed.EmbedError` are the public backend error boundaries. Embedding responses must include one indexed finite nonzero vector per input with stable dimensions. Fingerprints identify the vector space without secrets.
- `config.Settings`: target name/aliases, privacy, database, concurrency, LLM, embedding, optional judges/pricing/budget, TTS and synthetic-speech ASR. OpenAI-compatible LLM endpoints require explicit model/base URL and never silently target a public default.
- Tests are offline with `FakeLLM`, `HashingEmbedder`, fake HTTP transports and temporary databases. Python 3.12, strict mypy and ruff are required.

## Identity 与授权台账

- `identity`（代码层 1）是无 I/O 的冻结契约，后续只增不删。`Scope` 仅接受需授权细项的
  `facet:<facet_id>`、`egress:llm|embed|tts|asr`、`biometric:voice_clone|face`。
- `PersonaStore` 打开时以 `CREATE TABLE IF NOT EXISTS` 增加 `p_consent`；事件按自增 `seq` 只追加，
  包含 `grant|revoke|decline`、UTC 时间、来源 `questionnaire|cli|web` 和可选备注，删除资料不删除授权历史。
- `Identity.voice: str | None = None` 是追加的预置音色 ID，旧 JSON 缺失时为 `None`；
  `Identity.from_parts(..., voice=...)` 可从配置填入，不构造语音后端。
- `Identity.avatar: str | None = None` 追加风格化预置 ID，旧 JSON 默认 `None`；
  `Identity.from_parts(..., avatar=...)` 可从配置填入，CLI 与 `/api/identity.avatar` 显示配置预置，不涉及真人资产。
- `Identity.from_parts` 按 `seq` 折叠，每个范围以最新决定为准，只有 `grant` 算授权。
  gated facet 无台账事件时保持旧问卷推导（回答且未拒绝）；非 gated facet 始终允许。
- 问卷提交与文件导入在保存来源的同一事务中追加已回答细项的 `grant`、跳过细项的 `decline`；
  重复导入视为再次提交。保留 `Source.declined_facets`。撤回后运行 `twin persona build` 删除该细项条目，
  再由 `index_persona` 清除对应条目向量；不删除原始语料。
- 生物特征范围在本版本永不可 `grant`（M4：不支持本人声音复刻、照片驱动形象）。
  出境许可、预置音色校验与统一标识已接入。
- `twin identity show` 仅显示名字、别名、配置音色及预置音色/M4 提示、授权状态/时间/来源；`grant <scope>`、`revoke <scope>`
  可带 `--note`，备注不输出。

## 出境许可（EgressInfo）

- `config.egress_of(section)`（代码层 2）返回冻结的 `EgressInfo`：`kind`（llm/embed/tts/asr）、
  `external`、`declared`、`host`、中文 `reason`。仅输出主机名，不含 URL 凭据、路径或查询串。
- 四类配置及每位评委可追加 `egress = "local" | "external"`，显式声明优先；否则 hashing/silent
  为本机，anthropic/claude_cli/cloudflare 为外部。OpenAI 兼容地址只有 localhost、127.0.0.0/8、::1
  为本机（理由为“本机地址，未声明是否转发”），LAN 和未知地址均为外部。LLM/embed 与工厂一样
  回退到 `OPENAI_BASE_URL`；TTS/ASR 只使用配置地址。本机转发代理必须声明 external。
- `egress.require_egress`（代码层 9）读取 Identity 或 PersonaStore 的最新台账决定：只有 grant
  允许外部服务，无记录、decline、revoke 均拒绝；本机不需授权。CLI 在构造 LLM、embed、每位评委
  和回复朗读 TTS 前检查；Web 默认懒工厂同样检查，拒绝返回 403 `{"detail": "中文原因与授权命令"}`。
  `/api/status` 增加各后端（含评委）的 `egress` 列表，包含 kind/provider/host/external/declared/granted。
- 检查在首次构造而非应用启动；撤回对下一进程/下一次懒构造生效，已有 Web 缓存需重启，不热更新。
  Web 注入工厂是可信测试接缝，仅绕过该工厂的检查；默认工厂和所有配置评委仍强制执行。
  `media check` 仅用于非个人数据的合成评测句集（含自定义句集），不需出境授权。

## Transcript parsing (code layer 4)

`persona.transcripts.parse_transcript` supports line transcripts, timestamped speaker blocks, SRT/WebVTT, normalized transcript JSON and pre-existing FunASR JSON. This is pure format conversion, not audio transcription. Local speaker sidecars map labels before target aliases are normalized. Dates come from explicit arguments, JSON or filenames; ambiguous/missing dates and unrecognized formats raise `ValueError`. Consecutive turns can be merged and renumbered. Uploaded text uses `parse_transcript_text` and never reads server-side paths.

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

- All six converters (chat, interview, document, biography, questionnaire, meeting) store original expression
  text and speaker names, irrespective of `settings.pseudonymize_others`; existing parsing/whitespace rules are
  unchanged. L1 reads and the meeting inverse remain raw.
- `Source.text_state: Literal["raw", "pseudonymized"]` is additive JSON metadata, with no SQLite column migration.
  New converters explicitly write `"raw"`. Missing metadata loads as `"pseudonymized"`: pre-change sources are
  left untouched, including when mixed with raw sources, because their original names cannot be recovered.
  Loading/building does not rewrite source rows. Re-importing the original file can replace the old row with raw
  expressions; there is no attempt to reverse the hashes or to guess which legacy rows retained raw text.
- `expression_view` is the sole expression privacy transform for profile extraction and PersonaChat context
  (retrieved expressions, channels, context, voice samples and evidence quotes). It never writes to L1 or changes
  IDs, dates or meeting timestamps. `expressions` can supply evidence-quote spans for the same transformation.
  With privacy disabled, raw sources stay raw; legacy sources still cannot recover their lost names.
- Known other names come from non-target speakers in **all raw corpus sources**, not guessed from prose. The same
  catalog applies to every source kind: a name learned from chat/interview/meeting is also replaced in documents,
  biographies and questionnaire answers/questions. Names never observed as speakers are not detected (this is not
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

### Meeting corpus conversion (L1)

```python
def meeting_to_source(meeting: Meeting, settings: Settings) -> ParsedSource
def source_to_meeting(parsed: ParsedSource) -> Meeting
```

- `SourceKind.MEETING = "meeting"`, label **会议转写**, is `EvidenceClass.BEHAVIOR` (actual behaviour),
  not self-report or narration. Its expressions have `narrated=False`.
- The converter accepts an already parsed, speaker-normalised `Meeting`; it does not parse transcripts again, merge turns,
  strip text, drop empty utterances or pseudonymise speakers/text, even when `settings.pseudonymize_others=True`.
  One expression per utterance in list order; `idx` is its zero-based position, `is_target` comes from
  `settings.is_target`, `date` is the meeting date, `channel` is its title or, if empty, its meeting ID.
- Context reuses the chat rule: only target expressions receive context, from the last `CONTEXT_MESSAGES=3`
  non-target utterances since the preceding target utterance, rendered `speaker：text`. Context whitespace is
  collapsed and clipped to `CONTEXT_CHARS=400` (a leading ellipsis and the tail); verbatim expression text is untouched.
- `source_id_for(MEETING, meeting.source, meeting.model_dump_json())` derives a content-stable source ID;
  expression IDs are `f"{source_id}#{position:05d}"`. Settings and import time do not affect IDs.
  `imported_at` uses the existing source import-time rule.
- Additive optional fields, all defaulting to `None`: `Source.meeting_id: str | None`,
  `Expression.utterance_idx: int | None`, `Expression.start: float | None`, `Expression.end: float | None`.
  The latter two retain the utterance timestamps in seconds. Existing serialized sources/expressions load without
  these fields; all other converters leave them unset and retain their existing behaviour.
- Existing source fields retain meeting metadata exactly: `title` retains even an empty title, `origin` retains
  the full `Meeting.source` path, and `first_date=last_date=Meeting.date`, including for an empty meeting.
  `source_to_meeting(meeting_to_source(meeting, settings)) == meeting`, also after source/expression JSON serialization:
  it restores meeting ID, date, title, source path and each utterance's original index, speaker, text and timestamps
  in stored list order. Non-target-only meetings are accepted. The inverse raises `ValueError` for a non-meeting
  source or missing meeting ID/date/utterance index rather than fabricating lost metadata.
- `parse_source(MEETING, path, settings, date)` parses a transcript via `persona.transcripts`, including local speaker sidecars. `parse_text` uses the pure `parse_transcript_text` for web uploads without accessing filesystem paths. CLI and web both accept this generic corpus kind; no meeting runtime or derived meeting store exists.

## Memory upload queries and builds (code layers 3/5)

- `PersonaStore` 的 `p_meta.sources_changed_at` 为带 UTC 时区的 ISO 时间（微秒精度），在新增/替换来源、实际删除来源及 `facet:` 授权决定改变时，与对应写入同事务更新；重复相同授权决定及非 facet 授权不更新。删除来源保留授权历史。`source_pending:<source_id>` 是来源等待构建的内部标记，成功构建后清除。
- `profile.source_memories(store) -> dict[str, SourceMemory]` 是纯查询：每个来源返回 `expressions_total/target/others`（包括 held_out）、`items_supported`、`facets`（facet_id/name）、`contributes_nothing`、`build_status`（not_built/remembered/no_items）。按证据 expression_id 查询实际来源，重复引用和跨来源条目对每个来源只计一次；未拒绝条目口径与完成度一致。仍存于上次档案的条目也计入支撑，过期状态独立展示。
- `profile.profile_stale(store) -> bool`：sources_changed_at 晚于 built_at，或来源非空而 built_at 缺失；旧无 sources_changed_at 的库兼容，旧 built_at 无时区时按本机时间解析。这个状态只覆盖来源/细项授权，不追踪配置变化。
- `BuildReport` 保留原字段并追加 `facet_diffs: dict[str, FacetItemDiff]`；`FacetItemDiff` 含 `added/changed/removed`。比较 replace_facet_items 前后的原始 item_id 与 statement，不受人工审核替换表述影响；相同 ID 仅 statement 改变算 changed，ID 改变算 removed + added，证据/情境改变不算 statement diff。包含成功合并但零变化的细项，不包含失败或跳过的细项。
- BuildReport 提供派生总计 `items_added/items_changed/items_removed/facets_changed` 和 `change_summary()`。facets_changed 只计算有非零 diff 的细项；无变化增量构建总计为零。构建日志仅使用编号、计数及错误类型，不记录条目文本、来源标题或异常正文。
- 只有无失败且输入版本仍未变的构建，才由 `mark_profile_built` 同事务更新 built_at 并清除 pending 标记；built_at 记录本次构建开始时间。部分失败或构建期间来源/授权改变仍保持 stale，已完成结果保留供重试。CLI build/chat 在 stale 时向 stderr 提示，chat 仍运行。

## Generic evaluation schema (code layer 1)

All contracts are frozen and forbid extras. `CaseInput` exposes only identity, scenario, mode and `BiographyInput(id, type, prompt)`; answers live separately in `BiographyExpected`. The biography-shaped question/answer contracts remain temporarily for the next personal-evaluation task, without any biography runner or benchmark. `Prediction` has `BiographyOutput(reply)`, nullable capabilities and explicit raw data. `Judgement` retains rubric verdicts; failed/uncalled rows have `score=None`. `Report` preserves records, policies, purposes, fingerprints, generic statistics and warnings. Development purpose requires a dev split; reports cannot mix purposes. Aggregation order is judge → repeat → case → group.

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

- `service`（代码层 7）拥有冻结、禁止额外字段的 `ServiceCitation` / `ServiceAnswer` v1；字段只增不删。
  `answer_question(chat, question, as_of)` 是服务路径唯一的 ChatReply 适配器，调用
  `PersonaChat.reply([ChatTurn(role="user", content=question)], as_of=as_of, persist=False)`；
  问题超过 2000 字符时抛出不含输入的中文 ValueError。
- 引用按 L3 顺序解析，条目复用聊天 `_visible_items`（含 `item_as_of` 与证据隐私视图），
  表达复用 `expression_view(target_only=True, until=as_of)`；条目取最后可见证据，表达取本人文本，
  沿用聊天的空白整理/截断。返回 ref_id/kind/quote/date/source_kind，不暴露来源路径或审核备注。
- ServiceAnswer 包含 schema_version/answer/abstain/abstain_reason/confidence/citations/as_of/label/
  persona_name/generated_at（UTC）；文本、弃权与置信度保持 L3 原值，label 与 EXPLICIT_LABEL 的 Literal 一致。
  `ServiceIdentity` 仅含 name/avatar/voice/label，不输出授权或备注。
- `api` / `mcp_server`（代码层 9）共用懒 ServiceBackend，配置 LLM 与 embed 均在构造前执行
  `require_configured_egress`；注入 chat_factory 是可信测试接缝。后端缓存需重启才能应用撤回。
  每次默认请求关闭临时 store，不写聊天日志；进程内 UsageRecorder 使用 service 阶段、pricing 与累计 budget，
  不记录原文、不写追踪文件。
- HTTP 的 /v1/health 无鉴权；/v1/identity、/v1/ask 使用 Bearer + compare_digest。
  `[api] token_env` 默认 TWIN_API_TOKEN（至少 32 字符）；rate_per_minute 默认 30，
  单令牌 60 秒滑动窗口，429 附 Retry-After。Host 默认仅 loopback 名称，额外主机显式允许，
  非本机监听需 --allow-remote；请求体 16 KiB，问题 2000 字符。所有响应带 X-AI-Generated: twin。
- 官方 mcp SDK FastMCP 通过 stdio 提供 ask_twin 与 twin_identity，公布结构化输出 schema，
  文本以显式 AI 标识开头；拒绝出境是中文工具错误，后端错误固定中文消息，不记录个人文本。
  命令、请求/输出格式与客户端配置见 [SERVICE.md](SERVICE.md)。

## Media presentation (M0)

- `media.schema` (layer 1) defines frozen `PresentableAnswer`, `Segment`, `MediaCitation`, `MediaScript` and
  `MediaManifest`, version 1. It depends only on stdlib, pydantic and util; `PresentableAnswer` forbids extra fields.
  The explicit label is `AI 合成 · 模拟推演，不代表本人意见`; the first segment always contains
  `以下内容由 AI 合成，是模拟推演，不代表本人意见。`.
- `media.schema.EXPLICIT_LABEL` / `OPENING_NOTICE` 是显式标识与开头提示的唯一来源；
  `CHAT_NOTICE` 保留聊天页提示，`disclaimer(name, external)` 生成页脚。
  `MediaScript.explicit_label` / `MediaManifest.label` 保留原 `Literal` 契约，并测试其与常量一致。
  `/api/status.labels` 追加 `{explicit, disclaimer, chat_notice}`，网页回放、页脚、聊天标题读取这些字段，
  静态 HTML 仅用中性占位符。页脚的 `external` 来自 `egress_status`（含评委）：任一配置后端
  同时为外部且已授权则说明 `部分数据经已授权的外部服务处理，详见页面顶部的出境提示。`，否则使用本机措辞。
- `media.adapters` (layer 7) is the only media module that knows `ChatReply`; it validates raw JSON
  and produces `PresentableAnswer` with unchanged text and the upstream fingerprint.
  `media.script` (layer 7) converts only this boundary contract, without models, retrieval or rewriting.
  Sentence boundaries are Chinese/ASCII terminal punctuation clusters or line breaks outside `「」` / `“”` quotes;
  ASCII periods end a sentence only before whitespace, a closing quote or end of text, never between two digits.
  Only segment-edge whitespace is trimmed. Unclosed quotes conservatively retain the remainder together.
  Abstention produces the opening notice and an abstention notice, never speech; an empty reason has a neutral default.
- `source_fingerprint = util.fingerprint(source.model_dump(mode="json"))`: all validated source fields, excluding
  web-only resolved views, and independent of JSON key order. Persona display names do not change the source hash.
  Citations remain answer-level `(ref_id, reason)` objects; chat references have empty reasons. There is no inferred
  sentence-to-citation mapping. The manifest records the source hash, UTC creation time, generator and AI labels;
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
- `AvatarSpec` v1 is frozen and forbids extras: `avatar_id`, `label` (the exact same Literal and default
  `EXPLICIT_LABEL` as MediaScript), `palette` (exactly skin/hair/outfit/background/accent, six-digit hex),
  `mouth_states: Literal[4] = 4`, `stylized: Literal[True] = True`. No URL, path or image fields exist.
  `AVATAR_PRESETS` contains three invented flat palettes: default, ink and dawn.
- `AudioPart.lipsync: LipSyncTrack | None = None` is append-only; old manifests load with null tracks
  and display an idle avatar. HTTP audio segments carry the same nullable track.
- `Settings.avatar` defaults to `AvatarSettings(preset="default")`; unknown presets produce a Chinese
  preset list and photo/video prohibition (M4). Capabilities always include the selected `AvatarSpec`,
  even when speech is unavailable. SVG uses DOM calls, a permanent `spec.label` badge and no asset inputs.
  Playback samples the current part by audio time; pause/stop/text-only closes the mouth, close releases
  rAF and blink timers. Reduced motion disables blinking and limits openness to 0/1.

## Speech access (M1)

- `create_app(..., synthesizer_factory=...)` lazily defaults to `config.make_synthesizer(settings.tts)`.
  `silent` declares speech unavailable in the UI; HTTP capabilities expose backend, AI label, languages and formats.
- `TTSSettings.voice` accepts only preset IDs matching `^[A-Za-z0-9_.-]{1,64}$` (not `.` / `..`), rejecting
  paths, URLs and data references with a Chinese preset-only / M4 error.
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
  and labelled files retain the source fingerprint. Abstention speaks only notices, never answer content.
  Cache-file GET accepts only lowercase SHA-256 names with `.wav` / `.mp3`, resolves containment and retains
  security headers with `private, no-store`. POST keeps the 1 MB limit and `X-Twin: 1` rule. Backend-neutral
  unavailable / rejected / timeout / too-long errors map to 503 / 502 / 504 / 413 with fixed Chinese messages.
- `twin media speak ANSWER.json --out DIR [--kind chat_reply] [--name NAME]` calls only the configured
  speech factory and renderer, writing 0700 directories and 0600 audio, cache and manifest files. An unconfigured
  (silent) backend exits with a Chinese configuration error. Voice presets only; no rewriting or voice cloning.
- Browser speech starts with the audible AI notice; audio completion drives highlighting, including under reduced
  motion. Pause preserves the playhead, steps reset it, closure releases playback, and failures fall back to text.
  The persistent visible AI label and a backend-neutral speech label remain near the controls.
