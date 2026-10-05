# 本地个人分身网页：设计与接口契约

`twin ui` 默认监听 `http://127.0.0.1:8765`，页面不加载外部资源。个人资料存于本机；配置远端模型或语音服务时，请确认数据使用权限。

## 页面

| 路由 | 页面 |
| --- | --- |
| `#/chat`（默认） | 和分身聊天，查看依据、播放与导出回答 |
| `#/questionnaire` | 建档问卷、草稿、提交与重测 |
| `#/persona` | 人格档案、条目审核、完成度与采集建议 |
| `#/sources` | 记忆资料导入、删除与人格构建 |

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
| `GET /api/persona/sources` | 来源元数据、来源标签与证据类别 |
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

错误返回 `{detail}`：400 参数/资料前置条件，403 安全检查，404 不存在，409 构建冲突（带 job_id），413 太大，429 待处理过多，503 后端配置错误，500 内部错误。

## 播放、语音和导出

- persona 聊天气泡提供播放入口，传入完整 `ChatReply`（附加的 cited 展示字段不进入指纹）。播放面板常驻 `AI 合成 · 模拟推演，不代表本人意见`，先显示开头提示，再逐句呈现原回答。弃权只出提示，不讲述回答。
- 播放/暂停、逐句切换及导出可用键盘操作；Space 切换播放，左右方向键逐句切换，Escape 关闭并返回入口。系统减少动态效果时不自动推进文字。
- `POST /api/media/script`、`/api/media/export`、`/api/media/audio` 接收 `{kind: "chat_reply", answer: ChatReply, persona_name?: str}`。脚本/HTML 展示不调用模型；音频只调用配置的合成器。
- `GET /api/media/capabilities` 提供 available/backend/label/languages/audio_formats，无密钥或端点。语音失败不影响其他页面。
- 音频写入资料库目录下 media-cache，返回 script、ordered segments、manifest；分片可重复同一句索引。`GET /api/media/audio/{name}` 只接受 SHA-256 的 WAV/MP3 文件，验证目录边界，响应 `private, no-store`。
- 导出独立 HTML 不含可执行脚本或外部资源；文本转义，JSON 元数据安全转义，含 AI 标识与来源指纹。指纹不是签名，也不证明客户端提交回答的真实性。
- 语音不可用/拒绝/超时/过长对应 503/502/504/413，固定中文提示不回显服务消息。声音先播可听标识，以 ended 驱动句子推进；暂停保留位置，关闭释放音频，失败退回文字。

前端使用 ES 模块，无构建步骤；所有服务端文本通过 textContent 呈现，支持窄屏及系统深浅主题。
