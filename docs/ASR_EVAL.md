# 语音识别评测

`twin eval-asr` 在本机用同一批带人工标注的片段比较多个识别引擎，给出字错率（CER）、速度和逐条配对比较，用来判断换模型、改参数能不能让会议转写更准。第一个引擎是基线。asr-funasr 1.2.0 起线上识别改用 SeACo-Paraformer 加标点模型，对应引擎 `paraformer`；下文已有结论的基线是 1.1.0 包里的 SenseVoiceSmall。

## 分层

转写链路分层评测，每层只换一个变量，相邻两层同一批音频上的指标差就是这一层造成的损失，用来判断该先优化哪一层。

| 层 | 测什么 | 命令 | 主指标 |
| --- | --- | --- | --- |
| L1 模型层 | 识别模型本身，输入人工切好的单人片段 | `twin eval-asr` | CER（strict / nofill） |
| L2 切分层 | VAD 与声纹窗口切分，输入整场录音 | `twin eval-asr-session` | 不分说话人的整场 CER、漏检/误检语音 |
| L3 说话人层 | 声纹聚类与本人认领 | `twin eval-asr-session` | DER（collar 0.25 秒）、cpCER、自动认领正确/认错/未认领 |
| L4 后处理层 | 热词、LLM 清洗 | 待实现 | CER 差、专名召回、语气词保留 |
| L5 流程层 | twin 记到本人名下的文字 | `twin eval-asr-session` | 本人话语 CER、他人误归属 |
| L6 下游层 | 转写误差对记忆的影响 | 待实现 | persona eval 分数差 |

L4–L6 需要人工逐字校对的本人会议录音，尚未建立。

## 数据

清单是 JSON Lines，每行 `{"id", "audio", "text", "duration", "group"?}`：`audio` 相对清单所在目录，`text` 是人工参考文本，`duration` 为秒，`group` 是可选的录音编号。同一录音的片段错误相关，有 `group` 时置信区间按整段录音重抽，抽样也让同一录音整体落在同一边；没有时每条自成一组。

公开基准用 [WenetSpeech](https://github.com/wenet-e2e/WenetSpeech) `test_meeting`（8370 条、15.2 小时真实会议，中文），Hugging Face 镜像 `lmms-lab-audio/WenetSpeech` 的 `data/test_meeting-*.parquet` 约 220 MB。这份镜像没有录音编号，区间按单条重抽，会偏窄。转成清单（仓库外目录）：

```bash
uv run deploy/asr-eval/prepare_wenetspeech.py test_meeting-00000-of-00001.parquet --out ~/asr-eval/wenet-meeting
```

自建的本人会议片段也写成同样的清单即可，记得填 `group`。清单、音频、输出和缓存都不入 git；`--out` 与缓存目录在 git 仓库内时拒绝运行（`--allow-in-repo` 例外）。

## 引擎

引擎写在 TOML 里，每个 `[[engine]]` 用自己的 Python 运行 `deploy/asr-eval/` 下的脚本，模型依赖不进入 twin 环境：

```toml
[[engine]]
name = "sensevoice"          # 基线；python 默认为该 asr-funasr 包的 venv，模型用包内同一份权重
kind = "sensevoice"
pack = "~/Library/Application Support/twin/compute/asr-funasr/1.1.0"   # 默认为已安装的 current；1.2.0 起不含 SenseVoice

[[engine]]
name = "qwen3-asr-1.7b-8bit"
kind = "qwen3-mlx"
python = "~/.local/share/voxcpm2-mlx/venv/bin/python"   # 装有 mlx-audio 的环境
model = "~/.cache/huggingface/hub/models--mlx-community--Qwen3-ASR-1.7B-8bit/snapshots/<commit>"
options = { batch_size = 32 }
```

- `paraformer`：SeACo-Paraformer 加标点，直接调用包内 `run.py` 的 `Engine.recognize()`，模型、设备选择和标点与线上同一份代码；需要 1.2.0 及以后的包。options 可设 `device`、`batch_size`（默认取包的设置）、`hotwords`（字符串列表）。
- `sensevoice`：参数对齐 `deploy/compute/asr-funasr/run.py` 转写 VAD 片段的方式：MPS、每批 16 段、`language=zh`、`use_itn=True`。片段已切好，不跑 VAD 和声纹。options 可设 `device`、`batch_size`、`language`。包里没有 SenseVoiceSmall（1.2.0 及以后）时引擎直接报错，用 `pack` 指向旧版本目录。
- `qwen3-mlx`：Qwen3-ASR 经 mlx-audio，贪心解码，`language` 默认 `Chinese`、`max_tokens` 默认 512、`batch_size` 默认 32。
- `fun-asr-nano`：Fun-ASR-Nano-2512 经 Transformers 原生实现（`transformers>=5.17`，不加载远程代码），model 为 `FunAudioLLM/Fun-ASR-Nano-2512-hf` 的本机目录。MPS、float32、贪心解码；options 可设 `device`、`dtype`、`batch_size`（默认 16）、`language`（默认 `zh`）、`max_new_tokens`（默认 256）。
- `fireredasr2-aed`：FireRedASR2-AED，python 为装有 `fireredasr2s` 和 `kaldi_native_fbank` 的环境，model 为 `FireRedTeam/FireRedASR2-AED` 的本机目录。官方推理只认 CUDA，脚本复用它的特征、模型和分词器，自己放到 MPS 上；解码参数取官方默认（beam 3）。options 可设 `device`、`batch_size`（默认 16）、`beam_size`。

新引擎各用一个独立环境，例如：

```bash
uv venv --python 3.12 ~/.local/share/asr-eval/fun-asr-nano/venv
uv pip install --python ~/.local/share/asr-eval/fun-asr-nano/venv/bin/python \
  transformers==5.17.0 torch==2.10.0 torchaudio==2.10.0 librosa==0.11.0 soundfile==0.13.1
uv venv --python 3.12 ~/.local/share/asr-eval/fireredasr2/venv
uv pip install --python ~/.local/share/asr-eval/fireredasr2/venv/bin/python \
  "fireredasr2s @ git+https://github.com/FireRedTeam/FireRedASR2S@4e7d9aaf4482a47cec1724807026b9b151926eb5" \
  kaldi_native_fbank==1.22.3
huggingface-cli download FunAudioLLM/Fun-ASR-Nano-2512-hf --revision d93b302ee7fd505e1b3576120fc142fc6f7820e1
huggingface-cli download FireRedTeam/FireRedASR2-AED
```

引擎协议：stdin 一个 JSON 请求（`model`、`options`、`items` 列表；sensevoice 另有 `pack`），stdout 每条一行 `{"id", "text", "seconds"}`，日志写 stderr（评测输出目录的 `logs/`）。`--identify` 只打印依赖版本。新增引擎类型时在 `src/twin/evals/asr.py` 的 `KINDS` 登记脚本。

## 运行

```bash
uv run twin eval-asr --manifest ~/asr-eval/wenet-meeting/manifest.jsonl \
  --engines ~/asr-eval/engines.toml --out ~/asr-eval/runs/<日期>-<改动>
```

- **划分。** `--split dev`（默认）日常迭代，`--split formal` 只在阶段结束时跑一次，`--split full` 跑全量。dev 与 formal 是按种子 `asr-v1` 固定、互不重叠的样本，各约 `--size`（默认 1000）条；同一 `group` 不会拆到两边。比较两份成绩单时清单、划分、规模和种子必须相同。
- **缓存。** 每条转写一写出就追加到缓存（默认清单旁的 `asr-cache/`，0600），文件名带引擎身份指纹：引擎脚本、依赖版本、模型文件（sensevoice 为算力包 `pack.toml`，含权重摘要；qwen3-mlx 为模型目录与 `config.json`）和 options。中断后重跑只补缺的条目；引擎不变时重跑只重新算分，约 1 秒；改了任何一项就是新身份，从头转写。
- **输出。** `scorecard.json` / `scorecard.md` 只含汇总；`items.jsonl` 含参考文本和各引擎转写，供逐条查错，权限 0600。

## 评分

- **归一化**与 y15 合成语音评分相同：NFKC、小写、`5.5`→`五点五`、数字逐位转汉字，再按汉字和英文单词切分，标点与空格不计。CER =（替换 + 删除 + 插入）/ 参考字数，按全体字数汇总（不是逐条平均）。
- **两种口径**：`strict` 按参考原文；`nofill` 两边都去掉 `呃嗯啊哦噢唉诶欸哎呀吧呢嘛哈` 等语气词再算。参考文本逐字记了语气词，各模型保留与否只是风格，`nofill` 看实词识别。
- **区间与配对比较**：CER 的 95% 区间按组 bootstrap 2000 次；候选与基线比较时用同一批重抽样本算 CER 差的区间，并数出逐条错字数变好、变差的条数，做双侧精确符号检验。
- **波动下限**：同一引擎的批量推理会把同批片段补成等长，换一批组合，约 10% 的 SenseVoice 转写字面不同，CER 相差约 0.04 点。同一划分每次组批相同，结果可复现；但小于约 0.1 点的差别不要解读为改进。
- **RTF** 为推理秒数 / 音频秒数，不含模型加载；缓存命中的条目沿用当时记录的耗时，换机器后要清缓存重测速度。

## 性能

在 Apple M1 Max 上，`test_meeting` 中 Qwen3-ASR-1.7B 逐条解码的 RTF 约 0.083（15.2 小时全量约 76 分钟）。时间几乎都花在逐词解码上，它受内存带宽限制，所以评测用了下面几招：

| 手段 | 效果 |
| --- | --- |
| dev / formal 约 1000 条（1.8 小时）代替全量 | 两个引擎合计约 4.5 分钟；CER 差的 95% 区间宽约 ±0.3 点，足以分辨 0.5 点以上的变化 |
| Qwen3-ASR 按时长排序、32 条一批解码 | RTF 0.083 → 0.036，全量约 33 分钟；约 8% 转写字面变化，CER 变化在 0.1 点内，因此批大小计入引擎身份 |
| 转写缓存按引擎身份复用 | 只改评分或只加一个新引擎时，其他引擎不再运行 |
| 引擎常驻一个进程 | 模型只加载一次（SenseVoice 冷启动约 17 秒） |

批大小再加到 32 以上收益递减：同批每段仍逐段编码音频，编码约占批量解码时间的三分之一。

## 整场评测

`twin eval-asr-session` 用 twin 上传录音时同一套 `CommandTranscriber` 与 `analyse()` 跑整场会议，被测的就是线上运行的程序。

**数据。** [AliMeeting](https://www.openslr.org/119/)（OpenSLR SLR119，CC BY-SA 4.0）：中文真实会议，每场 2–4 人、15–30 分钟，句级说话人与时间标注（TextGrid）。Eval 8 场 4 小时（3.42 GB）日常迭代，Test 20 场 10 小时（8.90 GB）阶段结束时跑一次；训练集用不到。解压后转换（仓库外目录）：

```bash
uv run deploy/asr-eval/prepare_alimeeting.py <解压目录>/Eval_Ali --out ~/asr-eval/alimeeting/eval
```

远场取 8 通道阵列的第 0 通道，最接近手机或笔记本单个麦克风；去掉 `(SIL)`、`<sil>` 等标注记号。输出：

- `sessions.jsonl`：每场 `{id, audio, duration, reference, references}`，`reference` 指向 `{"segments": [{start, end, speaker, text}]}`，`references` 为 `{说话人: 参考声音}`。
- `manifest-far.jsonl` / `manifest-near.jsonl`：不与他人重叠的单句，`group` 为场次，直接交给 `twin eval-asr` 得到同一批音频的 L1。近场是干净音频的对照。
- `voices/<说话人>.wav`：约 10 秒不与他人重叠的近场录音，模拟本人参考声音。优先取该说话人最后一场会议，那一场不再把他当「本人」评测；只参加一场的人取同一场的近场录音。AliMeeting Eval/Test 里每人只参加一场，所以全部是同场取样：麦克风不同，但内容与被评的远场重叠，自动认领结果偏乐观，与线上「另录一段本人声音」相比是上限。`sessions.jsonl` 的 `voice_from` 记录取自哪一场；孤立语音不足 5 秒的人没有参考声音。

**引擎。** TOML 的每个 `[[engine]]` 写 `name`、`command`（twin `[asr] command` 的写法），可选 `language`（默认 `zh`）和 `files`（计入引擎身份的文件，如算力包的 `pack.toml`）。线上引擎的 `command` 照抄 `twin.toml` 里 `twin compute install asr-funasr` 写入的那一行；算力包目录随系统而定（macOS 默认 `~/Library/Application Support/twin/compute`，可用 `TWIN_COMPUTE_HOME` 改）：

```toml
[[engine]]
name = "funasr-1.2.0"
command = "'<算力包目录>/asr-funasr/current/venv/bin/python' '<算力包目录>/asr-funasr/current/run.py'"
files = ["<算力包目录>/asr-funasr/current/pack.toml"]
```

**运行。**

```bash
uv run twin eval-asr-session --sessions ~/asr-eval/alimeeting/eval/sessions.jsonl \
  --engines ~/asr-eval/session-engines.toml --out ~/asr-eval/runs/<日期>-<改动>
```

每场按带 `diarize` 的请求转写，一次带上这场所有被评测本人的参考声音（`reference` 加 `references`）。参考声音只影响相似度，不影响识别和聚类；asr-funasr 1.2.1 起一次返回每个说话人对每份声音的相似度，每场只跑一次；更早的包忽略 `references`，评测自动退回每人各跑一次。没有参考声音的场次跑一次。L2 用同一次带 diarize 的输出、忽略说话人：线上开启 diarize 时 `run.py` 按声纹窗口重新切分，与不开启时不同。结果按引擎身份（命令、language、`files` 的摘要）缓存在清单旁的 `asr-cache/`，中断后只补缺的场次。

**评分。** 文字归一化与片段评测相同。

- 整场 CER：参考和输出各按开始时间拼接后对齐（M2MeT 的先入先出口径）。
- DER：逐帧（10 毫秒）漏检 + 误检 + 说话人混淆，除以参考说话人总时长；说话人按共同时长最大的一对一匹配；参考边界两侧各 0.25 秒不计分，另报 collar 0。重叠语音按每帧说话人数计。
- cpCER：每个说话人的话按时间拼接，取总错字最少的说话人对应；没对上的参考说话人全算删除，多出的输出说话人全算插入。
- 自动认领：按线上规则（相似度至少 0.6、领先第二名至少 0.1）认领后，看被认领说话人的时间里谁说得最多：是本人为正确，否则为认错。
- 本人话语 CER：参考里本人的话对比 twin 记到本人名下的文字；没有自动认领时按用户手动选对说话人计算。他人误归属：本人名下的字里，落在只有别人说话时段的比例。
- 区间按场次 bootstrap；与基线逐场配对，符号检验按场次。Eval 只有 8 场，区间很宽，结论以 Test 为准。

`scorecard.md` 按层分节，末尾给出层间损失（说话人损失 = cpCER − 整场 CER，流程损失 = 本人话语 CER − cpCER）；`items.jsonl` 含每场参考与输出，权限 0600。

## 已有结论

2026-10-12，WenetSpeech `test_meeting` 全量 8370 条，逐条解码：

| 引擎 | 严格 CER | 去口头语 CER | RTF |
| --- | --- | --- | --- |
| SenseVoiceSmall（当时线上） | 7.62% | 7.00% | 0.005 |
| Qwen3-ASR-1.7B 8bit（MLX） | 5.84% | 5.18% | 0.083 |

同日用 `twin eval-asr` 跑的划分基线（Qwen3-ASR 32 条一批，提交前的工作区）：

| 划分 | SenseVoice 严格 CER | Qwen3-ASR 严格 CER | CER 差（95% 区间） | 变好 / 变差 | 用时 |
| --- | --- | --- | --- | --- | --- |
| dev（1000 条，1.79 小时） | 7.38% | 5.84% | −1.54（−1.85 至 −1.23） | 315 / 118 | 4.5 分钟 |
| formal（1000 条） | 8.03% | 5.95% | −2.08（−2.40 至 −1.76） | 363 / 119 | 4.3 分钟 |

全量逐条结果：Qwen3-ASR 的 CER 低 1.78 点（95% 区间 1.69–1.91），相对少错约 23%；逐条看 2860 条更好、1000 条更差。替换和删除都下降，删除从 2.57% 降到 2.01%。官方报告的 bf16 版本在同一测试集为 5.88%，与本机 8bit 一致。Qwen-Audio-3.1 系列只有阿里云 API，没有开放权重，录音须上传，不符合本机离线转写的约定，没有纳入。

2026-10-13 在 dev 划分加入 Fun-ASR-Nano 与 FireRedASR2-AED（引擎各自默认参数，Qwen3-ASR 32 条一批）：

| 引擎 | 严格 CER | 去口头语 CER | 比基线（95% 区间） | 变好 / 变差 | RTF |
| --- | --- | --- | --- | --- | --- |
| SenseVoiceSmall（1.1.0 包） | 7.38% | 6.76% | — | — | 0.004 |
| FireRedASR2-AED，beam 3 | **4.58%** | **3.90%** | −2.80（−3.16 至 −2.47） | 436 / 104 | 0.212 |
| FireRedASR2-AED，beam 1 | 4.68% | 3.98% | −2.70（−3.07 至 −2.36） | 429 / 105 | 0.094 |
| Qwen3-ASR-1.7B 8bit | 5.84% | 5.21% | −1.54（−1.85 至 −1.23） | 315 / 118 | 0.036 |
| Fun-ASR-Nano-2512 | 6.44% | 5.73% | −0.94（−1.24 至 −0.64） | 271 / 157 | 0.059 |

FireRedASR2-AED 与官方报告的 WenetSpeech 会议集 4.53% 一致，是本机最准的开源模型，但在 MPS 上最慢：约九成时间在自回归解码，官方解码器每步都重算整段音频的交叉注意力投影，还有多次 GPU 同步。beam 1 快约 2.2 倍，CER 只升 0.1 点；要再快需要给解码器加交叉注意力缓存。批再加大反而变慢（80 条实测 beam 3：每批 16 条 RTF 0.26，32 条 0.31）。Fun-ASR-Nano 用的是 Transformers 原生实现，不是官方 FunASR 推理路径。
