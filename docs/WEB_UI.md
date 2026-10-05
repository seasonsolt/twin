# 本地个人分身网页：设计与接口契约

`twin ui` 默认监听 `http://127.0.0.1:8765`，页面不加载外部资源。个人资料存于本机；配置远端模型或语音服务时，请确认数据使用权限。

## 页面

| 路由 | 页面 |
| --- | --- |
| `#/chat`（默认） | 和分身聊天，查看依据、播放与导出回答 |
| `#/questionnaire` | 建档问卷、草稿、提交与重测 |
| `#/persona` | 人格档案、条目审核、完成度与采集建议 |
| `#/sources` | 记忆资料导入、删除与人格构建 |
| `#/identity` | 身份与授权：名字、预置音色、细项许可、出境与生物特征限制 |

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

`stale` 在 sources_changed_at 晚于 built_at，或存在来源但没有 built_at 时为 true。资料页在构建按钮旁、聊天页在输入区上方显示“资料或授权有变化，尚未重新构建；档案和聊天仍基于上次构建”；聊天不因此被阻止。导入、删除及成功构建后刷新资料摘要与状态；聊天进入或发送时检查状态。

错误返回 `{detail}`：400 参数/资料前置条件，403 安全检查，404 不存在，409 构建冲突（带 job_id），413 太大，429 待处理过多，503 后端配置错误，500 内部错误。

## 身份与授权

`#/identity` 只展示配置中的名字、别名与预置音色，不展示个人资料或台账备注。细项表显示最新决定、UTC 时间和来源；无记录时显示“未记录”及旧问卷推导状态。授权/撤回只追加台账，撤回先确认，变更后提示重建并链接到 `#/sources`。

出境表显示类型、提供方、主机、本机/外部、声明/推断和许可，仅外部行提供授权/撤回。授权前必须确认数据将发送到哪些外部主机；同类型许可共享，包括 `llm` 评委。出境许可在下一进程或下一次懒构造后端时生效，已构造的网页后端需重启，不热更新。生物特征只读、按钮禁用，显示 M4 禁止原因。AI 标识和隐私说明从 `/api/status.labels` 读取，不在页面中复制文案；授权后刷新顶部状态及说明。

- `GET /api/identity` 返回 `{name, aliases, voice, consents, egress, biometric}`。`consents` 包含每个需授权的细项，以及台账中其他范围的最新记录，按 scope 排序。每行字段为 `{scope, name, decision, label, at, origin, granted, derived_decision}`；有记录时 decision 为 `grant/revoke/decline`，无记录时 decision/at/origin 为 null、label 为“未记录”，derived_decision 为旧问卷推导的 `grant/decline`（有记录时为 null）。granted 是当前有效状态。
- `egress` 直接来自 `egress_status`，每行 `{kind, provider, host, external, declared, granted}`，含评委；仅返回主机，不返回端点路径、查询参数或密钥。`biometric` 固定 `{voice_clone: false, face: false, reason: <中文 M4 禁止原因>}`。
- `POST /api/identity/consent` 接收 `{scope, decision: "grant"|"revoke", note?: str}`，note 最多 200 字，写入台账的 origin 为 `web`。沿用 `X-Twin: 1`、Host 和请求体大小保护。不支持无须授权的细项；无效范围或生物特征 grant 返回 400 `{detail}`，采用身份契约的中文错误，不回显备注。生物特征 revoke 可记入台账，但不能启用该能力。
- 成功返回 `{seq, scope, decision, at, origin, rebuild_needed, restart_needed, message}`，无 note。facet 的 rebuild_needed 为 true，message 提示 `twin persona build`；egress 的 rebuild_needed 为 false、restart_needed 为 false（下一次懒构造无需重启），但 message 明确提醒已构造的网页后端需重启。所有范围的 restart_needed 均为 false；接口不自动构建、不重启进程。

## 播放、语音和导出

- persona 聊天气泡提供播放入口，传入完整 `ChatReply`（附加的 cited 展示字段不进入指纹）。播放面板常驻 `AI 合成 · 模拟推演，不代表本人意见`，先显示开头提示，再逐句呈现原回答。弃权只出提示，不讲述回答。
- 播放/暂停、逐句切换及导出可用键盘操作；Space 切换播放，左右方向键逐句切换，Escape 关闭并返回入口。系统减少动态效果时不自动推进文字。
- `POST /api/media/script`、`/api/media/export`、`/api/media/audio` 接收 `{kind: "chat_reply", answer: ChatReply, persona_name?: str}`。脚本/HTML 展示不调用模型；音频只调用配置的合成器。
- `GET /api/media/capabilities` 提供 available/backend/label/languages/audio_formats，无密钥或端点。语音失败不影响其他页面。
- 音频写入资料库目录下 media-cache，返回 script、ordered segments、manifest；分片可重复同一句索引。`GET /api/media/audio/{name}` 只接受 SHA-256 的 WAV/MP3 文件，验证目录边界，响应 `private, no-store`。
- 导出独立 HTML 不含可执行脚本或外部资源；文本转义，JSON 元数据安全转义，含 AI 标识与来源指纹。指纹不是签名，也不证明客户端提交回答的真实性。
- 语音不可用/拒绝/超时/过长对应 503/502/504/413，固定中文提示不回显服务消息。声音先播可听标识，以 ended 驱动句子推进；暂停保留位置，关闭释放音频，失败退回文字。

前端使用 ES 模块，无构建步骤；所有服务端文本通过 textContent 呈现，支持窄屏及系统深浅主题。
