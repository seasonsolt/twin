# 多媒体展示专线（M 线）

状态：通用个人分身的展示层。分层规则见 [ARCHITECTURE.md](ARCHITECTURE.md)。

目标：把分身已经得出、并通过引用校验的回答，用文字、语音、形象和视频片段呈现出来，用于个人对话播放和展示。媒体层是一个展示层，不是另一个"会说话的模型"。

## 1. 原则

1. **只改写呈现方式，不生成内容。** 媒体层的输入只有运行时层的输出：`ChatReply`（对话），以及它们的引用、置信度和弃权状态。媒体层不调用大模型改写措辞；分身弃权时，只展示弃权说明，不配音，也不出镜。
2. **不碰真人生物特征。** 只用预置音色和风格化（非写实）形象，不做声音克隆，不驱动真人照片或视频。真人的声音和形象属于敏感个人信息（《个人信息保护法》第 28、29 条），放在 M4，前提是本人单独书面同意，并满足资产隔离、访问审计和一键熔断要求。
3. **合成内容必须标识。** 按《人工智能生成合成内容标识办法》（2025-09-01 施行）：
   - 显式标识：画面常驻角标"AI 合成 · 模拟推演，不代表本人意见"；音频开头有一句语音提示；
   - 隐式标识：音频、视频和导出文件的元数据里写入生成方、"AI 生成合成"标记和来源回答的指纹。
4. **可追溯。** 每个产出物都记录它来自哪一次回答（运行快照或回答指纹）、用了哪些引用，以及音色和形象配置。
5. **人物无关、出境由配置决定。** `src/` 里不出现具体人物的专属内容；用本人资料评测和展示时，语音与识别只走本地或本人指定的服务，外部服务（如 Cloudflare）按配置使用，界面如实展示出境分类。

已确定（2026-10-04）：形象用风格化插画，不做写实；语音后端两种都接，Cloudflare `melotts` 用于合成数据和公开数据，本地自托管服务（MOSS-TTS-Nano 起步，可换 CosyVoice3）用于内网。

## 2. 分层

媒体线横跨 L0 和 L4/L5，不进入 L1 语料、L2 认知、L3 运行时：契约和语音后端放在 L0 基础设施，展示编排放在 L3 之上、与 L4 场景同级（以后的场景，例如代参会时开口提问，也能直接使用），接入放在 L5。代码层号（0–9）只用于 `tests/test_layers.py`，对应关系见 ARCHITECTURE.md 第 1 节。

| 模块 | 所属层（代码层号） | 内容 |
| --- | --- | --- |
| `media.schema` | L0 数据契约（1） | 全部媒体契约：`PresentableAnswer`、`MediaScript`、`MediaManifest`、`SpeechRequest`、`SpeechResult`、`LipSyncTrack`、`AvatarSpec`；只依赖标准库、pydantic 和 `util` |
| `media.tts` | L0 模型后端（2） | `SpeechSynthesizer` 协议、两个后端适配器（Cloudflare `melotts`、自托管 HTTP）、测试用的静音实现 |
| `media.asr` | L0 模型后端（2） | 仅用于评测的 `SpeechRecognizer` 协议、Cloudflare Whisper 与自托管 multipart 适配器 |
| `media.check` | 跨层评测（8） | 合成句集回听、字错率与合成墙钟秒/音频秒报告，不参与推理 |
| `media.adapters` | 与 L4 同级（7） | 运行时输出到 `PresentableAnswer` 的适配器：`ChatReply` 适配器 |
| `media.script` | 与 L4 同级（7） | 纯函数：`PresentableAnswer` 到 `MediaScript`（开头提示、按句切分、弃权只出提示） |
| `media.lipsync` | 与 L4 同级（7） | 纯函数：时间戳、PCM 能量或合成节奏到版本化口型轨 |
| `media.clip` | 与 L4 同级（7） | Pillow 平涂形象与字幕、条件静音片头与静音片尾、ffmpeg MP4 编码；复用语音缓存与口型轨 |
| `media.render` | 与 L4 同级（7） | 按脚本调用 `SpeechSynthesizer`、拼接音频、写入标识、生成 `LipSyncTrack`、缓存与导出 |
| `web.media` / `cli` | L5 接入（9） | API、回放面板、`twin media ...` 命令 |

## 3. 层间解耦规则

依赖方向服从 [ARCHITECTURE.md](ARCHITECTURE.md) 第 1 节，由 `tests/test_layers.py` 强制。在此之上，媒体线有五个边界，每个边界只通过**一个契约加一组适配器**连接：

| 边界 | 上游 | 契约（第 1 层） | 适配器 | 下游只依赖 |
| --- | --- | --- | --- | --- |
| B1 运行时 → 媒体 | `ChatReply` | `PresentableAnswer`：口语文本、弃权与原因、置信度、截至日期、答案级引用、来源指纹 | `media.adapters`，每种运行时输出一个函数 | `media.script` 只认 `PresentableAnswer` |
| B2 媒体 → 语音后端 | Cloudflare、自托管服务 | `SpeechRequest`（文本、音色、格式）/ `SpeechResult`（音频、格式、采样率、时长、可选的逐字时间戳） | `media.tts` 里每个后端一个类，实现 `SpeechSynthesizer` | `media.render` 只认协议和契约 |
| B3 语音 → 形象 | `SpeechResult` | `LipSyncTrack`（时间到口型开合，版本化）、`AvatarSpec`（插画图层与口型帧） | `media.render` 经 `media.lipsync` 生成口型轨：优先逐字时间戳（timings），其次 WAV PCM 能量（energy），否则合成节奏（pattern） | 前端只认 `AvatarSpec` 和 `LipSyncTrack`，不知道是哪个语音后端 |
| B4 媒体 → 接入层 | `media.render` 的产出 | `MediaScript`、`MediaManifest`、音频与口型轨文件 | `web.media`、`cli` 只做序列化和权限 | 浏览器和命令行只收契约 JSON 和文件 |
| B5 媒体 → 语音识别（仅用于评测） | Cloudflare Whisper、自托管 FunASR/SenseVoice shim | `TranscriptionRequest`（音频、格式、语言、可选提示）/ `Transcription`（文本、语言、时长、extras），均带版本 | `media.asr` 每个后端一个类，实现 `SpeechRecognizer` 并声明 `ASRCapabilities` | `media.check` 只认协议和契约，不读取厂商 extras |

具体规则：

1. **单向知情。** 上游不知道下游存在：运行时不导入媒体模块，语音后端不知道脚本和形象，前端不知道语音后端是哪家。
2. **只在适配器里认识对方。** 上游类型（`ChatReply`、厂商 API 字段）只出现在对应的适配器里。运行时演进、或者换语音厂商时，只改适配器和它的测试。
3. **契约带版本、只增不删。** 每个契约有 `schema_version`；新增字段必须有默认值；删除或改变含义要升版本，并保留旧版本的读取。
4. **能力用声明，不靠猜。** 适配器在 `capabilities` 里声明能力（是否给逐字时间戳、单次最大字数、支持的格式和采样率、是否流式）。上层按声明选择处理路径，例如口型轨在没有时间戳时退回能量包络。
5. **错误统一。** 适配器把后端错误转成 `MediaError` 的子类（不可用、拒绝、超时、输入过长），错误信息隐藏密钥和服务地址，和 `llm.LLMError` 的做法一致。厂商原始字段只放在 `extras` 里，上层不读。
6. **配置只经工厂。** B5 与 B2 相同：`[asr]` 只保存密钥环境变量名，`config.make_recognizer(settings)` 是唯一识别构造入口；识别不进入运行时。新增 `[tts]` 配置段，`config.make_synthesizer(settings)` 是唯一构造入口，与 `make_llm` 一样只写环境变量名、不写密钥。
7. **每个边界都有契约测试。** 同一套一致性测试参数化地跑过每个适配器：两个语音后端用录制或伪造的 HTTP 响应，测试不联网；运行时适配器用真实的 `ChatReply` 样本。新增后端必须先通过这套测试。B5 两个识别适配器同样共用离线一致性测试，统一复用 `media.tts.MediaError` 错误层次，禁止泄漏密钥或地址。

`twin media check [--sentences FILE] [--repeats N] --out DIR` 使用固定合成句集（可用含 `text` 的 JSONL 替换），逐句调用 `render_audio` 并识别全部有序分片。报告文件 `report.json` / `report.md` 为 0600；记录两个后端的无密钥指纹。CER 双方先经可选 `media.speech_text.speech_text`（懒加载并记录是否应用及版本），再 NFKC、小写、去标点和空白；总 CER 按总编辑距离/总参考字数计算，空参考分母取一。简体中文提示用于中文识别；常见繁体专用字仅标记，不转换。合成墙钟秒/音频秒使用独立空缓存，包含渲染与写盘，时长未知则不计算比率。

M1d：`--repeats` 默认 1，必须至少为 1；每句每次重复都有独立空缓存，即使句集有相同文本也实际调用合成器，再识别全部有序分片。`report.json` 为 `schema_version=3`，保留旧字段：逐句旧识别、score、分片和计时字段描述第一次重复；`repeat_checks` 保留每次识别、CER、分片、计时及零基 `repeat_index`。逐句 `mean_cer` / `worst_cer` 为各次 CER 的算术平均 / 最大值。`INCOMPLETE_LENGTH_RATIO = 0.8`：规范化识别长度 **严格小于** 规范化参考长度的 80% 即为 `incomplete`，恰好 80% 或空参考不算；逐句和总体 `incomplete_repeats` 记录次数，这只是截断启发式，不等同语义完整性。

总 `edits`、`reference_chars`、`cer` 及计时覆盖所有重复；`repeat_cers` 按相同重复序号组成整轮、以总编辑距离 / 总参考字数（空参考总分母取一）计算。总体 `mean_cer` 是各整轮 CER 的算术平均，`worst_repeat_cer` 是最差整轮 CER，`worst_sentence_repeat_cer` 另报所有单句重复中的最大 CER；总体平均仍按参考长度加权，不是逐句 CER 的简单平均。`traditional_sentence_count` 为任一次重复含疑似繁体的句子数，不重复计句。报告 Markdown 展示每次识别，不把多次识别拼成一条假设。

M1d follow-up：服务完整性守卫及实机阈值依据见 `deploy/tts-moss/README.md`。OpenAI 适配器将 `X-Speech-Warning` 脱敏保存到 `SpeechResult.extras['warning']`，并将已知的 `possibly-truncated` 提升到追加的通用 `SpeechResult.warnings` 契约字段（默认空列表）；渲染层不读取 extras，只将通用警告写到 `AudioPart.warnings`（默认空列表，旧清单仍可读）。缓存不保存 extras，但保存通用警告。报告 v3 追加各次、逐句及总 `warning_parts`，计携带 `possibly-truncated` 的音频分片数；逐句与总计覆盖所有重复，区别于 ASR 长度判断的 `incomplete_repeats`，不把服务内部尝试计为独立分片。

### B3 口型与风格化形象（M2）

`SpeechResult` 只在展示层转换：`LipSyncTrack` v1 默认 `fps=25`，`levels` 每帧为 0–3（闭嘴到大开口），长度不超过 `fps × 600`，更长音频仅生成前 600 秒。`source` 为 timings / energy / pattern；时间戳对应各音频分片的朗读文本，词间闭嘴、词内按字符位置交替 2/3。WAV 能量支持 8/16-bit PCM 单/双声道，以每帧全部声道样本的 RMS、三帧移动平均、片内第 95 百分位为基准，按严格大于 10% / 35% / 70% 分成四档；纯静音全零，稀疏非静音导致基准为零时退回最大 RMS。MP3 或不支持/损坏的 WAV 使用明确合成的 pattern；未知时长默认 1 秒，不猜测音素。

`AvatarSpec` v1 只有预置 ID、同源常驻标识、五种十六进制平涂色、四种口型及 `stylized=True`，没有图片、路径或资源地址。`[avatar].preset` 仅接受 default / ink / dawn；不支持照片或视频输入（M4 门槛）。React 组件 `frontend/src/features/playback/Avatar.tsx` 渲染内联 SVG，不获取形象资源，前端只消费形象与口型契约，不按语音后端选择动画。每个 `AudioPart.lipsync` 默认为 `None`，旧清单仍可读，HTTP 序列化为 null，形象保持静止。

回放以各分片的 `audio.currentTime` 驱动口型；暂停、停止、纯文字播放时闭嘴，关闭时释放动画与眨眼计时。正常情况下每 3–6 秒眨眼；减少动态效果时不眨眼，口型限于 0/1，保留正在说话的提示。弃权仅呈现提示，不生成讲述内容。

### 3.1 朗读文本规范化（M1c-tn / M1d v3）

`media.speech_text`（代码层 7）是纯函数，`SPEECH_TEXT_VERSION = 3`。仅对 `language="zh"` 的合成输入规范化：百分数、小数、中文分组整数、量词前及独立的“两”、逐位年份、月日、时分、范围、序数、千分位和人民币金额（如 `¥1,200` → “一千二百元”）。原始 `MediaScript`、展示、HTML 和文本导出不变；不生成或改写回答内容。

v2 新增有效公历日期：`YYYY-MM-DD` / `YYYY/MM/DD`（含长句中的日期）读为逐位年份加数量月日，如 `2026-10-04` → “二零二六年十月四日”。`M/D` 仅在前接“于/在/到/至”或后接“前/后/起/截止/日”时按日期读（不猜年份；用闰年 2000 校验无年份的月日，允许 2/29），已有“日”不重复添加。无效日期如 `2026-13-40`、`2026-02-29`、`在4/31` 原样保留。拉丁词、版本、混合编号、URL、邮箱和 ISO 时间戳（如 `2026-10-04T18:30:00Z`）仍原样保留；`v2026-10-04` 等编号不当作日期。歧义 `10/4` 无日期上下文时保持 v1 的数字规则。除此以外沿用 v1 行为，不把日期误作范围。前导零数字串、裸的 7/8 位本地号码及 11 位以 1 开头的号码逐位读；带量词或金额单位时按数量读，区号及 `+86` 电话保留原有分隔符。其他整数按万/亿分组。此规则保守处理歧义，不猜测编号含义。

v3 在规范化后、切分前，为 CJK 统一/兼容表意字符与 Latin 字母/十进制数字的每个相邻边界加一个 ASCII 空格，如“请用AI辅助整理” → “请用 AI 辅助整理”。已有空白不重复添加，Latin 词、数字、版本和 URL 内部不插空格（包括 URL 的中文路径）；URL 的外侧边界可加空格。插入空格的原文 span 为空，分片仍可拼回原文；仅影响朗读文本，函数保持幂等。无效日期/编号的数字内容不变，但其与中文相邻的外侧边界也加空格，如“在4/31核对” → “在 4/31 核对”。v2 的无年份日期上下文兼容该单个边界空格，以保持无效月日的幂等性。

缩写默认不展开。B2 的 `SynthCapabilities.reads_latin_acronyms` 默认 `True`，Cloudflare MeloTTS 声明 `False`；编排只按声明将独立的 2–5 位大写缩写分字母加空格（`AI` → `A I`），不按后端名称猜测。静音和 OpenAI 兼容后端保持默认。

先规范化整段再按后端字数上限切分，避免切坏数字或使展开后的请求超限。音频清单及各片段记录 `speech_text_version`，片段的 `spoken_text` 是实际发送的文本，`text` 保留原文并可顺序拼回原段；若单个数字展开超过上限，后续音频片段的原文可为空。旧清单字段默认版本 `0`、朗读文本为空，仍可读取。缓存及音频清单文件指纹包含规范化版本；逐字时间戳对应朗读文本而非原文。

### 3.2 预置音色与统一标识（I3）

`[tts].voice` 只接受 `^[A-Za-z0-9_.-]{1,64}$` 的预置 ID（不接受 `.` / `..`）；路径、URL、data 引用会得到中文错误。生物特征限制仅作为配置校验：本版本不支持真人声音复刻或照片驱动形象，形象只能选择预置。

B2 的 `SynthCapabilities.voices: list[str] | None = None` 为追加字段：`None` 表示后端不能枚举，空列表表示没有预置音色。静音与 Cloudflare 仅有 `["default"]`，构造时检查配置；Cloudflare 不支持音色选择。OpenAI 兼容适配器保持 `synth.capabilities` 属性接口，第一次读取时懒查询 `GET {base_url}/voices`，使用与合成相同的认证、超时、重试及禁止重定向策略。200 的合法字符串列表与 404/405 的 `None` 都会缓存；其他状态、传输错误及非法响应走脱敏的统一语音错误，不静默降级，失败后可重试查询。

可枚举时，配置音色在读取能力（最迟首次合成）时检查；每次合成也检查请求音色。不在列表中就用中文拒绝，包含配置 ID 和预置数，绝不提交合成文本。查询延迟到媒体能力/朗读入口，应用启动、身份查看及纯文字功能不访问语音后端。`Identity.voice` 默认 `None` 兼容旧契约，`twin identity show` 从配置填入 ID 并显示预置音色与 M4 禁止项。

标识单一来源是 `media.schema`：`EXPLICIT_LABEL`、`OPENING_NOTICE`、保留现有聊天提示措辞的 `CHAT_NOTICE`，以及页脚函数 `disclaimer(name, external)`。`MediaScript.explicit_label` / `MediaManifest.label` 的 `Literal` 不变，以测试防止与常量漂移。`GET /api/status` 的 `labels: {explicit, disclaimer, chat_notice}` 供回放角标、页脚和聊天标题读取；React 前端不复制文案，`frontend/src/components/layout/AppShell.tsx` 在标签未加载时显示 Skeleton/留空。导出、音频开头与元数据仍使用契约中的同源标识。

页脚按 `egress_status`（所有配置后端，含评委）判定是否存在**配置的外部**服务：

- 没有：`所有推演结果均为模拟，供个人使用参考，不代表{name}本人的意见或决定。数据只保存在本机。`
- 有：`所有推演结果均为模拟，供个人使用参考，不代表{name}本人的意见或决定。部分数据经配置的外部服务处理，详见页面顶部的出境提示。`

任一配置后端分类为外部即使用外部措辞；全部为本机时使用本机措辞，不存在独立授权状态。

### 3.3 MP4 片段导出（M3）

`twin media clip REPLY.json --out clip.mp4` / `POST /api/media/clip` 仅展示已保存的回答，不生成新措辞。默认 1280×720、25 fps；左侧沿用浏览器形象的平涂几何与配色（四档口型，无眨眼），右侧按字符实际宽度换行显示当前段原文。口型取各音频分片的 `lipsync`，缺失时闭嘴；弃权不显示形象，只展示提示。全程保留 `EXPLICIT_LABEL` 角标。

若脚本首段为 `kind="notice"` 且文本为 `OPENING_NOTICE`，直接从该段开始播放（带形象与开头语音提示），不再添加重复的静音片头。否则保留约 2 秒的静音片头，显示 `OPENING_NOTICE`。随后按顺序播放 `render_audio` 的全部分片，复用输出目录旁的 `media-cache`。片尾约 3 秒，静音显示“回答依据”和标识。当前 `MediaScript.citations` 仅有编号与理由，没有原话或引用日期，因此不伪造引用原话卡片，也不把 `as_of` 当作引用日期。视频文字不写日志。

Pillow 绘制 RGB 帧，经 ffmpeg stdin 编码 H.264（libx264、yuv420p、CRF 23、veryfast）+ AAC，启用 faststart。音频统一为 48 kHz 单声道 PCM，再用 concat demuxer 拼接片尾静音及需要时的片头静音。MP4 `title` 为显式标识，`comment` 为 `AI-generated; twin; source <回答指纹>`；指纹不是签名。输出文件为 0600，中间文件完成/失败后清理；缓存保留。文本上限 100,000 字符，完整视频上限 600 秒。

系统依赖 **ffmpeg**（含 ffprobe）：macOS `brew install ffmpeg`；Ubuntu `sudo apt-get install -y ffmpeg fonts-noto-cjk`。Python 依赖 Pillow。字体按 `[media].font_path`（可选字符串路径）优先，否则依次查找 macOS Hiragino Sans GB / STHeiti、Linux Noto Sans CJK / WenQuanYi；找不到时用中文提示配置字体。自定义示例：

```toml
[media]
font_path = "/path/to/chinese-font.ttc"
```

ffmpeg stderr 只捕获，不回显；错误只给通用中文提示，不记录字幕或后端原始响应。静音合成器可离线导出，真实朗读需配置 `[tts]`。

## 4. 阶段

| 阶段 | 内容 | 验收 |
| --- | --- | --- |
| M0 展示内核（不用模型，已完成） | `media.schema`、`media.script`；网页"回放"视图：逐句显示 `reply`，同步高亮对应引用和原话，常驻显式标识；导出带隐式标识的独立 HTML | 弃权回答不产生讲述段；每句的引用都能在原回答中找到；标识在所有视图和导出物中存在；分层测试通过；不依赖任何模型或网络 |
| M1 语音（已完成，含 M1b–M1d：自托管服务、朗读规范化、回听评测、确定性与截断防护） | `media.tts` 协议与适配器；预置音色；开头语音提示；音频元数据标识；缓存 | 用语音识别回听（Workers AI whisper 或本地 ASR）计算字错率；首句延迟；元数据标识可读出；中文 `melotts` 的效果先实测再决定是否作为默认 |
| M2 形象（已完成（浏览器端）） | 风格化 2D 形象：浏览器端 Canvas/SVG，口型由音频能量或音素时间戳驱动；不用照片 | 无真人照片或视频输入；角标标识常驻；低端机也能流畅播放 |
| M3 片段导出（已完成） | 对话片段导出为 mp4：形象、字幕、回答依据片尾和标识，用 ffmpeg 合成，元数据写入隐式标识 | 导出物能追溯到来源回答；常驻角标、开头提示与片尾标识（不是防篡改或防裁剪保护） |
| M4 真人声音与形象（门槛） | 声音复刻、真人形象驱动 | 暂不开发。进入前需要：本人单独书面同意、模型资产隔离与审计、一键熔断、对外使用的审批流程 |

## 5. 接入

- persona 聊天气泡提供播放入口；输入 `ChatReply` 原回答，按 `chat_reply` 适配，不生成新措辞。
- `twin media script/export/speak/clip REPLY.json --out PATH` 默认来源为 `chat_reply`。静音后端支持离线文字展示；朗读需配置 `[tts]`，合成回听测试另需 `[asr]`。
- `/` 的 React 前端通过 `frontend/src/features/playback/PlaybackDialog.tsx` 和 `usePlayback.ts` 管理文字/音频、请求与资源生命周期；形象使用同目录 `Avatar.tsx`，样式令牌在 `frontend/src/design/tokens.css`。构建资源由 `/assets/*` 提供，独立导出 HTML 不依赖这些资源。
- 本地 API、访问保护和播放控件见 [WEB_UI.md](WEB_UI.md)。
