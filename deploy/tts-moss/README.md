# MOSS-TTS-Nano 内网语音服务（CPU / OpenAI 兼容）

本目录是独立部署适配器，不导入 twin，也不修改运行时、媒体契约或渲染层。
`twin.media.tts.OpenAICompatSpeech` 通过 B2 HTTP 边界调用它；服务不知道回答、引用、脚本或形象。
仅合成客户端提交的原文，不调用大模型改写内容。

## 官方资料与版本锁定

已核对以下官方资料及其中的推理入口：

- [GitHub README](https://github.com/OpenMOSS/MOSS-TTS-Nano#quickstart)
- [TTS 模型卡](https://huggingface.co/OpenMOSS-Team/MOSS-TTS-Nano)
- [音频 tokenizer 模型卡及 decode 接口](https://huggingface.co/OpenMOSS-Team/MOSS-Audio-Tokenizer-Nano)
- [官方 requirements.txt](https://github.com/OpenMOSS/MOSS-TTS-Nano/blob/8b7bcc9341b3b4ef3a3a58ba1338a7d85ff133eb/requirements.txt)
- [官方预置音色及运行时](https://github.com/OpenMOSS/MOSS-TTS-Nano/blob/8b7bcc9341b3b4ef3a3a58ba1338a7d85ff133eb/moss_tts_nano_runtime.py)

公开 HF API JSON 的 `sha` 字段给出了下列完整 commit（不是可变的 `main`）：

| 仓库 | 固定 revision |
| --- | --- |
| `OpenMOSS-Team/MOSS-TTS-Nano` | `44502f80dbf9743528fa921cc544d662c685ebec` |
| `OpenMOSS-Team/MOSS-Audio-Tokenizer-Nano` | `6aa02b01e445cc585582cf0ba480bc3ea6c8dd68` |

查询来源分别是 `https://huggingface.co/api/models/OpenMOSS-Team/MOSS-TTS-Nano` 和
`https://huggingface.co/api/models/OpenMOSS-Team/MOSS-Audio-Tokenizer-Nano`。
`server.py` 为配置、模型和文本 tokenizer 同时指定 `revision`、`code_revision`。
两仓库需要 `trust_remote_code=True`，会执行仓库 Python 代码；固定权重与代码版本能避免上游更新后
无审核执行新代码，但不是沙箱。升级时须重新审核远程代码、依赖和模型卡，手动更新常量并复验。
不要把高权限凭据或宿主机敏感目录挂进容器。

官方精确指定 `torch==2.7.0`、`torchaudio==2.7.0`、`transformers==4.57.1`；本镜像的前两项
使用同版本的 `+cpu` 构建，由 `https://download.pytorch.org/whl/cpu` 提供，避免安装 CUDA 依赖。
其余服务所需直接依赖也在 `requirements.txt` 中精确固定；官方对它们使用范围或未指定版本，
这些补充 pin 是本服务选择，不是声称官方给出了精确版本。没有引入官方网页 demo 所需的
`python-multipart`、WeTextProcessing/pynini 或 ONNX Runtime；此实现直接传入原文，不做其文本归一化。

推理使用 `AutoModelForCausalLM.from_pretrained(...).to(device="cpu", dtype=torch.float32).eval()`，
并显式提供已锁定的文本 tokenizer 和 `AutoModel` 音频 tokenizer，避免模型内部无 revision 的二次加载。
TTS 全局/局部注意力选择 `eager`，音频 tokenizer 使用 CPU `sdpa` / `fp32`，不需要 FlashAttention。
官方 `model.inference(...)` 返回 `waveform` 和 `sample_rate`；原生输出是 48 kHz 双声道。
本服务取两声道均值，限幅后转换为小端 int16 单声道 PCM，用标准库 `wave` 编码 WAV。
官方入口还会写临时音频文件，本服务用临时目录并在响应前删除，不持久化请求音频。

## 请求级确定性（M1d）

已读取上述固定 GitHub runtime，以及 HF revision
`44502f80dbf9743528fa921cc544d662c685ebec` 的
[`modeling_moss_tts_nano.py`](https://huggingface.co/OpenMOSS-Team/MOSS-TTS-Nano/blob/44502f80dbf9743528fa921cc544d662c685ebec/modeling_moss_tts_nano.py)、
`gpt2_decoder.py`、`prompting.py`、`tokenization_moss_tts_nano.py` 与 `config.json`，
并核对固定音频 tokenizer 的 `modeling_moss_audio_tokenizer.py` / `config.json`：

- `_sample_next_token`（HF 第 896–934 行）先做重复惩罚、temperature、top_k、top_p 过滤，再调用
  **全局 torch RNG** 的 `torch.multinomial`，未传 generator。
  `_sample_next_assistant_text_token` 在“继续音频 / audio_end”之间采样；
  `_iter_generation_events` 又对每帧各音频码本采样。因此早停本身也有随机性。
- `inference`、生成入口与采样函数均不接受 `torch.Generator` 或 seed；GitHub runtime 的 seed
  只是锁内 `torch.manual_seed`（CUDA 可用时也设 CUDA seed），不改变采样方式。
- 推理路径没有 numpy/python 随机抽样；GPT2 的 dropout 在 eval 下关闭，固定配置的 dropout 也是零。
  音频 tokenizer 的推理量化为确定性距离选择，attention dropout 为零，没有随机前缀抽样。
  随机权重初始化属于启动加载，不属于请求；runtime 的 UUID 随机后缀只用于文件名，不影响波形。
- **保留本 shim 原有采样方式和参数**：`do_sample=True`，HF 入口默认
  text temperature/top_p/top_k = **1.5/1.0/50**，audio = **1.7/0.8/25**，
  audio repetition penalty = **1.0**。GitHub runtime 的显式默认分别为 **1.0/1.0/50**、
  **0.8/0.95/25**、惩罚 **1.2**；此前 shim 直接调用 HF 入口，未采用这一组 runtime 覆盖值，
  本次也不切换，以免混入音质/解码策略变化。runtime 仅 warmup 使用贪心，常规合成默认采样，
  没有因此改用贪心解码的依据。

每次有效请求在同一引擎锁内计算 seed：将 `[MODEL_REVISION, voice, input text, attempt]` 按紧凑 JSON
（UTF-8、保留中文）编码，取 SHA-256 摘要前 4 字节的大端无符号整数。
真实引擎在模型加载后、推理前以该 uint32 重置 `random.seed`、`numpy.random.seed`、
`torch.manual_seed`；CPU-only 不需要单独 CUDA seed。无本地 generator 通道，故使用锁内全局 RNG。
`attempt` 为从 0 开始的内部合成尝试序号；不使用进程随机化的 `hash()`，不把请求序号或时间混入 seed。
相同 revision/音色/原文/attempt 即使隔着其他请求或服务重启也得到相同 seed，
不同原文或 attempt 通常得到不同 seed（32 位种子有碰撞可能）。
seed、正文均不写日志，不提供客户端 seed/采样参数入口。

确定性不保证朗读完整性；固定 seed 可能稳定复现某一次截断。375 帧上限保持不变。

### 完整性守卫与警告

Reviewer 的实机验证确认相同文本得到逐字节相同音频；三轮回听 CER 为 MOSS 3.7%、Cloudflare 7.6%。
但 MOSS 将“请用AI辅助整理，但不要生成新的事实。”稳定截断在逗号处。Xiaoyu 实测：

| 输入 / 情况 | 音频时长 | 秒 / 可朗读字符 |
| --- | --- | --- |
| 上述截断句（17 个可朗读字符） | 1.68 s | 0.099 |
| AI 两侧有空格的同一句 | 4.56 s | 0.268 |
| AI 替换为“人工智能” | — | 0.223 |
| 普通完整句 | — | 0.22–0.28 |

据此采用保守启发式常量：`MIN_SECONDS_PER_CHAR = 0.15`、`MIN_SPEAKABLE_CHARS = 6`、
`MAX_SYNTHESIS_ATTEMPTS = 3`。NFKC 后只计 CJK 统一/兼容表意字符（含扩展区）、Latin 字母和十进制数字；
不计标点、空格、emoji。以单声道 PCM 的帧数 / 采样率求时长，不以 WAV 文件大小估计。
可朗读字符少于 6 时跳过守卫，只合成一次。其余输入若时长 / 字符数 **严格小于** 0.15，
在同一锁内用下一 attempt 的确定性 seed 重合成；最多三次（不是三次重试），返回首个达到阈值的结果。
三次均未达到阈值时，返回时长最长的一次（并列取最早），附加
`X-Speech-Warning: possibly-truncated`，仍为 HTTP 200 WAV。参数、原文、采样方式不变；引擎错误仍返回脱敏 503。
日志记录 `chars`、`attempts`、耗时，不记录正文、seed 或异常内容。

该守卫是时长启发式，不是 ASR/语义校验；可能漏检，也可能对快速或非中文语音误报。
相同部署上的尝试顺序和最终选择仍确定。twin 的 OpenAI 适配器将头复制到
`SpeechResult.extras['warning']`（脱敏），并将已知警告提升为通用契约 `SpeechResult.warnings`。
渲染层只读取该契约列表，清单各 `AudioPart.warnings` 和缓存保存警告，不读取厂商 extras；
`twin media check` 的 `warning_parts` 统计携带警告的分片数（含全部重复，不计内部尝试数）。

v3 中文朗读文本会在 CJK 与 Latin 字母/数字的相邻边界加 ASCII 空格；展示原文不变，
不在 Latin 单词、数字、版本字符串或 URL 内部插空格。
离线 FakeEngine 测试验证 HTTP 路径传递稳定、随文本/音色/revision/attempt 变化的 seed，
覆盖首轮通过、重试、三次上限、最长结果及警告响应；
真实波形确定性需在相同 CPU、固定依赖、权重和预置资源的部署上复验，不承诺跨硬件/版本逐位一致。
可用 `twin media check --repeats 4 --out <私有目录>` 检查；每次重复使用新的渲染缓存并实际调用后端。
升级此 shim 后须移除上游旧音频缓存，避免缓存掩盖行为变化。

## 预置音色与本人的参考声音

HF TTS 仓库没有独立 speaker-id 音色权重；官方所谓预置音色实际来自 GitHub `assets/audio/`。
为保证资源不漂移，这些固定资源也锁定到 GitHub commit
`8b7bcc9341b3b4ef3a3a58ba1338a7d85ff133eb`，首次启动下载到 `/cache/presets/<commit>/`。
不安装、不运行官方支持上传音频的 demo 服务。名称与文件映射来源是同一 commit 的
[`moss_tts_nano_runtime.py` 第 26–43 行 `_DEFAULT_VOICE_FILES`](https://github.com/OpenMOSS/MOSS-TTS-Nano/blob/8b7bcc9341b3b4ef3a3a58ba1338a7d85ff133eb/moss_tts_nano_runtime.py#L26-L43)，
已通过 `curl` 获取固定版本原文核对。该上游表本身存在过期引用：`Zhiming -> zh_2.wav`、
`Weiguo -> zh_5.wav`、`Nathan -> en_5.wav`、`Aoi -> jp_3.wav`、`Hina -> jp_4.wav`、
`Mei -> jp_5.wav` 在该 commit 的 `assets/audio/` 中均不存在，故从本服务白名单排除。
其余资产如 `en_6.wav`、`zh_10.wav` 没有该表对应名称，不猜测或重映射。
仅下载官方表与实际资产的交集，并排除真人音色和非 WAV：

| 语言 | 官方预置名称（大小写敏感） | 文件 |
| --- | --- | --- |
| 中文 | `Junhao` | `zh_1.wav` |
| 中文 | `Xiaoyu` | `zh_3.wav` |
| 中文 | `Yuewen` | `zh_4.wav` |
| 中文 | `Lingyu` | `zh_6.wav` |
| 英文 | `Ava` | `en_2.wav` |
| 英文 | `Bella` | `en_3.wav` |
| 英文 | `Adam` | `en_4.wav` |
| 日文 | `Yui` | `jp_2.wav` |

官方还有 `Trump`、`Sakura`：**`Trump` 是明确的真人参考音色，按 MEDIA.md M4 禁止使用，
不会下载或暴露**；`Sakura` 的资源是 MP3，本镜像不装 ffmpeg，因此也不开放。
`default`、`alloy` 等不是官方预置名称，不做静默映射。请先查询 `/v1/voices`。

预置和本人的声音都使用 `inference(mode="voice_clone", prompt_audio_path=<参考 WAV>)`。
`TTS_VOICE_DIR` 默认为 `/voices`；每次请求重新扫描其中匹配
`^self-[0-9a-f]{16}\.wav$` 的普通文件（不接受符号链接）。`/v1/voices` 为已加载预置与这些 ID 的并集。
选择本人的 ID 时，参考路径为 `<TTS_VOICE_DIR>/<id>.wav`，新增文件不需重启。
HTTP 仍不接受 mode、音频、任意路径、上传或参考转录，额外字段统一拒绝；严格 ID 校验阻止路径穿越。
twin 的网页负责处理本人录音，并通过 `[tts].voice_dir` 发布 0644 WAV；将同一个目录只读挂载到 `/voices`。
宿主机目录及其祖先需允许容器 UID 10001 遍历，不要直接挂载私有 `assets/` 目录。

AI 合成显式提示、隐式元数据、回答指纹与引用追溯由 twin 的 renderer 添加。
单独调用本服务得到的是未加标识的原始 WAV，不能替代 renderer 的合规导出；弃权时是否配音
也由上游媒体层决定。本服务不记录请求正文、令牌、下载 URL 或异常原文；合成仅记录字符数和耗时，
预置加载失败仅记录缺失名称，模型/tokenizer 加载失败记录一条明确错误；禁用访问日志。

## 在 CPU Docker 主机部署

在仓库根目录执行（GPU 主机或任意 Docker 主机）：

```bash
docker build -t twin-tts:moss-nano deploy/tts-moss
export TWIN_VOICE_DIR="$HOME/twin-voices"
mkdir -p "$TWIN_VOICE_DIR"; chmod 755 "$TWIN_VOICE_DIR"
# 在本地安全设置 SHIM_API_KEY；不要把真实值写进仓库或命令历史。
read -r -s -p '语音服务令牌: ' SHIM_API_KEY; echo
export SHIM_API_KEY
docker run -d --name twin-tts --restart unless-stopped \
  -p 127.0.0.1:8001:8001 \
  -v twin-hf:/cache \
  -v "$TWIN_VOICE_DIR:/voices:ro" \
  -e SHIM_API_KEY \
  --cpus 4 --memory 8g \
  twin-tts:moss-nano

docker logs --tail 30 twin-tts
docker inspect --format '{{.State.Health.Status}}' twin-tts
curl -fsS -H "Authorization: Bearer $SHIM_API_KEY" http://127.0.0.1:8001/healthz
curl -fsS -H "Authorization: Bearer $SHIM_API_KEY" http://127.0.0.1:8001/v1/voices
```

不设置或设置为空的 `SHIM_API_KEY` 时不校验令牌；建议始终设置。
设置后四个端点全部要求 Bearer 令牌，使用恒定时间比较；HEALTHCHECK 从容器环境读取同一令牌。
具有 Docker 管理权限的人员仍能读取容器环境，此令牌不能防御宿主机管理员。
容器内监听 `0.0.0.0:8001` 才能接受 Docker 转发，但**宿主机只发布到 127.0.0.1**；不要改为公网绑定。
容器以 UID/GID 10001 非 root 身份运行，一个 uvicorn worker，所有引擎调用串行加锁。

构建只安装依赖，不下载权重。首次启动在 FastAPI lifespan 加载模型、tokenizer 和白名单资源，
全部缓存到 `HF_HOME=/cache` 命名卷；模型或 tokenizer 加载失败仍会终止启动，并记录一条脱敏错误。
预置资源逐个下载、校验（包括已有缓存）；单个下载失败、404、空文件或无效 WAV 不会终止服务，
只记录缺失名称并跳过。`/v1/voices` 仅列出成功加载的音色，不再列出整个候选白名单。
至少一个音色可用时 `/healthz` 返回 200；全部缺失时服务仍启动，但返回 503 和 JSON 原因。
启动阶段需要访问 Hugging Face 和 GitHub；之后正文只在内网 CPU 上处理，不发送给任何外部推理 API。
首次启动可能耗时数分钟或更久，健康检查提供 30 分钟启动宽限；缺失资源需检查网络/缓存并重启，
请求期间不重新下载预置资源。
保留命名卷即可复用缓存，勿执行删除卷的清理命令。已有非本镜像创建的卷若权限不兼容，需由管理员
将缓存目录所有者设置为 `10001:10001`，不能通过改成 root 运行解决。

资源规划：官方给出约 0.1B TTS 参数、约 22M 音频 tokenizer 参数，以及 4 核 CPU 推理能力。
建议至少 4 核、8 GiB 内存、缓存盘预留 2 GiB 以上；FP32 权重本身约数百 MB，实际还有 Python、
PyTorch、缓存和长文本激活开销。这里没有下载模型或测量真实 CPU 性能，以上是容量建议而非延迟保证。
CPU 首次请求和长文本可能较慢；模型按约 75 文本 token 自动分段，每段最多 375 音频帧，
即约 30 秒，过长的单段可能截断。建议 renderer 按短句调用，1000 字符只是 HTTP 上限，不保证
一次高质量朗读 1000 字。实际音质、完整性、首句延迟与字错率必须另行在目标机器验收。

也可使用 `docker compose -f deploy/tts-moss/compose.yaml up -d --build`；设置 `TWIN_VOICE_DIR` 和
`SHIM_API_KEY` 环境变量，compose 将声音目录只读挂载到 `/voices`。若 twin 与容器位于不同主机，
`voice_dir` 需为共享/同步目录；HTTP 隧道本身不会同步 WAV。视频通道的 SSH 素材传输与此独立。

## Mac SSH 隧道与 twin 配置

Mac 上保持此会话运行（本地端口需空闲）：

```bash
ssh -N -L 8001:127.0.0.1:8001 <gpu-host>
```

Mac 设置 `TWIN_TTS_KEY` 为服务端相同令牌（只写环境变量，不写入 TOML）。`twin.toml`：

```toml
[tts]
provider = "openai_compat"
model = "MOSS-TTS-Nano"
base_url = "http://127.0.0.1:8001/v1"
api_key_env = "TWIN_TTS_KEY"
voice = "Junhao" # 未设置本人声音时的回退
voice_dir = "/path/to/twin-voices" # 与容器 /voices 相同的宿主机目录
streaming = true # 默认；流端点不存在时自动回退整段 WAV
language = "zh"
timeout = 600
max_retries = 0
```

网页听优先请求 `POST /v1/audio/speech/stream`，JSON 为 model/input/voice；成功需 `audio/pcm`、`X-Sample-Rate` 与分块发送的单声道 PCM16LE。此端点由上游服务实现；404/405 或 `streaming = false` 使用原来的整段 WAV，仍通过同一个浏览器 PCM 流播放。其他语音 provider 总是使用整段解码回退。

renderer 使用 WAV。通用 OpenAI 适配器也能请求 MP3，但**本镜像仅支持 WAV**，请求 MP3 返回 400。
较长超时适合 CPU 合成；重试设为 0 防止超时请求在串行服务端重复堆积。
更新模型/预置 revision 后还应清理上游已有的音频结果缓存，避免复用旧版本音频。

## HTTP 契约与离线测试

- `POST /v1/audio/speech`：`model`、`input`、`voice` 必填，`response_format` 可省略（默认 `wav`）；
  成功为 `audio/wav`，单声道 PCM16，`Cache-Control: no-store`。
- `GET /v1/models`：OpenAI 风格模型列表，仅注册 `MOSS-TTS-Nano`。
- `GET /v1/voices`：`{"voices": ["Junhao", ..., "self-0123456789abcdef"]}`，已加载预置加参考目录中严格匹配的 ID。
- `GET /healthz`：有任一可用音色时 200 `{"status": "ok"}`；无可用音色时 503
  `{"status": "degraded", "reason": "no voices available"}`。模型/tokenizer 启动加载失败时服务不会就绪；
  此端点不做真实合成探针。
- 空白文本、未知模型/音色、非 WAV 格式：400；令牌无效：401；输入超过 1000 个 Unicode 字符：413；
  字段缺失、类型错误、额外字段或 JSON 无效：422；引擎错误或无效 PCM：503。错误不回显正文或异常。

`tests/test_tts_shim.py` 按路径导入 `server.py` 并注入 `FakeEngine`，拦截 ML 包导入，完全离线。
覆盖所有端点、鉴权、拒绝克隆参数、长度边界、请求种子、并发串行化、日志脱敏和失败响应。
启动测试保留真实 lifespan/预置加载路径，仅替换模型加载、下载器和 WAV 检查依赖；验证部分 404、
网络错误、无效 WAV 不影响启动，全部缺失时健康检查 503，模型/tokenizer 失败仍终止启动且日志脱敏。
映射测试核对固定表、WAV 扩展名、文件唯一性及真人音色排除。
端到端测试使用真实 `OpenAICompatSpeech(client=TestClient(app), base_url="http://testserver/v1")`，
检查版本化 `SpeechResult`、WAV 采样率/时长、格式及无厂商字段泄漏，遵守 B2 一致性要求。
这些测试不证明真实模型或 Docker 镜像已经运行成功。
