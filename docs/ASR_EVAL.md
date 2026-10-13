# 语音识别评测

`twin eval-asr` 在本机用同一批带人工标注的片段比较多个识别引擎，给出字错率（CER）、速度和逐条配对比较，用来判断换模型、改参数能不能让会议转写更准。第一个引擎是基线。asr-funasr 1.2.0 起线上识别改用 SeACo-Paraformer 加标点模型，对应引擎 `paraformer`；下文已有结论的基线是 1.1.0 包里的 SenseVoiceSmall。

## 分层

转写链路分层评测，每层只换一个变量，相邻两层同一批音频上的指标差就是这一层造成的损失，用来判断该先优化哪一层。

| 层 | 测什么 | 命令 | 主指标 |
| --- | --- | --- | --- |
| L1 模型层 | 识别模型本身，输入人工切好的单人片段 | `twin eval-asr` | CER（strict / nofill） |
| L2 切分层 | VAD 与声纹窗口切分，输入整场录音 | `twin eval-asr-session` | 不分说话人的整场 CER、漏检/误检语音 |
| L3 说话人层 | 声纹聚类与本人认领 | `twin eval-asr-session` | DER（collar 0.25 秒）、cpCER、自动认领正确/认错/未认领 |
| L4 后处理层 | 热词、LLM 清洗 | 缓存清洗后用 `twin eval-asr-session` 评分 | CER 差、专名召回、语气词保留 |
| L5 流程层 | twin 记到本人名下的文字 | `twin eval-asr-session` | 本人话语 CER、他人误归属 |
| L6 下游层 | 转写误差对记忆的影响 | 待实现 | persona eval 分数差 |

L4 已可用 AliMeeting 的公开逐字标注评测；专名召回和语气词保留尚无独立指标。L6 仍需建立转写误差与记忆质量之间的评测。

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

每场按带 `diarize` 的请求转写，一次带上这场所有被评测本人的参考声音（`reference` 加 `references`）。参考声音只影响相似度，不影响识别和聚类；asr-funasr 1.2.1 起一次返回每个说话人对每份声音的相似度，每场只跑一次；更早的包忽略 `references`，评测自动退回每人各跑一次。没有参考声音的场次跑一次。同一次请求还带上其他场次的人（不在这场会议里）的声音，凑满 32 份，看 twin 会不会把不在场的人认领成本人：L3 的「不在场误认」列给出次数和他们与任一说话人的最高相似度，调认领门槛时它必须保持为 0；更早的包不比较多份声音，这一列为「—」。L2 用同一次带 diarize 的输出、忽略说话人：线上开启 diarize 时 `run.py` 按声纹窗口重新切分，与不开启时不同。结果按引擎身份（命令、language、`files` 的摘要）缓存在清单旁的 `asr-cache/`，中断后只补缺的场次。

**评分。** 文字归一化与片段评测相同。

- 整场 CER：参考和输出各按开始时间拼接后对齐（M2MeT 的先入先出口径）。
- DER：逐帧（10 毫秒）漏检 + 误检 + 说话人混淆，除以参考说话人总时长；说话人按共同时长最大的一对一匹配；参考边界两侧各 0.25 秒不计分，另报 collar 0。重叠语音按每帧说话人数计。
- cpCER：每个说话人的话按时间拼接，取总错字最少的说话人对应；没对上的参考说话人全算删除，多出的输出说话人全算插入。
- 自动认领：按线上规则（`media/claim.py`，见 [MEDIA.md](MEDIA.md)）认领后，看每个被认领说话人的时间里谁说得最多：都是本人为正确，否则为认错。
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

2026-10-13，AliMeeting Eval 第一张分层成绩单（8 场 4.21 小时，远场第 0 通道，评测本人 21 人次；整场基线 asr-funasr 1.2.1，转写与 1.2.0 逐字相同）：

| 层 | 指标 | 1.2.1 Paraformer | 1.1.0 SenseVoice |
| --- | --- | --- | --- |
| L1 | 近场单句 CER（1706 条） | 4.32% | 5.41% |
| L1 | 远场单句 CER（同 1706 条） | 7.73% | 8.94% |
| L2 | 整场 CER（替换 / 删除 / 插入） | 34.82%（7.6 / 26.1 / 1.2） | 35.52% |
| L2 | 漏检 / 误检语音 | 10.0% / 1.6% | 10.0% / 1.6% |
| L3 | DER collar 0.25（漏检 / 误检 / 混淆） | 34.8%（21.6 / 1.4 / 11.8） | 34.8% |
| L3 | 说话人数误差（场均） | 多 3.6 人 | 相同 |
| L3 | 自动认领 正确 / 认错 / 未认领 | 9 / 0 / 12 | 相同 |
| L5 | 本人话语 CER / 他人误归属 | 34.95% / 3.1% | 35.64% / 3.0% |

识别模型不是瓶颈：单句与整场之间差 27 点，主要来自重叠语音（76% 的参考字落在与他人重叠的句子里，单麦克风每一时刻只转出一个人）和 VAD 漏检。说话人聚类把每人切成 2–5 组，组本身很干净；未认领的 12 次里 11 次是相似度全部低于 0.6（参考声音是头戴麦、会议是远场阵列），相似度最高的组 21 次全是本人。层间损失表的「流程损失」为负：cpCER 把同一人的碎组算错，而 twin 允许认领多组，不宜当作 L3 到 L5 的中间层。

其中 21 次认领用的是当时的规则（相似度至少 0.6、领先第二名至少 0.1）。

2026-10-13，按 Eval 改认领规则：最相似的说话人至少 0.5 即认领，其余至少 0.55 一并认领（聚类拆出的同一人碎组），0.45–0.55 提示「可能也是你」。在 4090 上用 Eval + Test（69 人次）复核：认领 60 次、认错 0 次（旧规则 32 / 0）；不在场的人 739 次比较从未被认领，最高相似度 0.433（Eval）/ 0.402（Test）。追加门槛取 0.55 而不是 0.5，是因为 Test 上有两次别人的小组相似度到 0.50、0.53；这一步用到了 Test，Test 对认领门槛不再是留出集。

**重叠语音。** 把参考句按是否与他人重叠拆开，同一次整场输出分别对齐（聚类阈值 0.55）：

| 集 | 不重叠的句子 | 与他人重叠的句子 |
| --- | --- | --- |
| Eval | 24% 的字，CER 12.1%（删除 7.9%） | 76% 的字，CER 40.5%（删除 31.7%） |
| Test | 29% 的字，CER 8.8%（删除 5.1%） | 71% 的字，CER 41.7%（删除 31.7%） |

约九成错字在重叠语音里，主要是删除：单麦克风每一时刻只转出一个人。不重叠的句子比 L1 远场单句（7.7%）高的部分来自 VAD 漏检和切分。

**聚类阈值。** 用 `--cluster-threshold` 在 4090 上扫 asr-funasr 的声纹聚类阈值（CUDA 与 MPS 的声纹略有差别，聚类结果不能跨设备比较）：

| 阈值 | 多出的说话人（Eval / Test） | DER | 本人话语 CER | 他人误归属 | 认领 正确 / 认错 / 未认领（Test） |
| --- | --- | --- | --- | --- | --- |
| 0.55（原默认） | 3.9 / 3.6 | 35.4% / 29.8% | 39.85% / 36.13% | 1.8% / 2.5% | 41 / 0 / 7 |
| 0.60 | 2.5 / 1.9 | 30.6% / 25.8% | 38.07% / 30.94% | 1.9% / 2.9% | 40 / 0 / 8 |
| **0.65** | 1.4 / 0.5 | 25.9% / 23.0% | 31.28% / 27.59% | 3.1% / 3.6% | 40 / 0 / 8 |
| 0.70 | 0.5 / 0.2 | 24.8% / 22.4% | 30.76% / 27.52% | 3.5% / 3.9% | 40 / 0 / 8 |
| 0.75 | 0.4 / 0.4 | 27.4% / 27.0% | 35.49% / 36.05% | 5.2% / 11.0% | 36 / 1 / 11 |

1.2.1 起默认 0.65：Test 上本人话语 CER 比 0.55 低 8.5 点（48 人次 35 好 13 差，p = 0.002），误归属多约 1 点；0.70 只再好 0.07 点，离 0.75 开始把不同的人合并更近。整场 CER 几乎不随阈值变化（Test 33.1% → 32.3%），说话人层的损失（cpCER − 整场 CER）从 18.5 点降到 3.8 点。

**识别模型换成 FireRedASR2。** 片段层 FireRedASR2-AED 比 Paraformer 低约 3 点（远场 4.71% 对 7.73%，beam 1）。为了看整场能剩多少，[combo_firered.py](../deploy/asr-eval/combo_firered.py) 只替换 asr-funasr 的识别模型，VAD、声纹聚类和标点照旧，在 4090 上以服务方式运行，与原包同阈值（0.65）同批场次对比。直接替换时，FireRed 在「一人说话、另一人连声附和」的重叠片段里会转写附和声并循环（「对对对……」，最长一段 666 个「有」），Test 上 6990 段里有 158 段；`--fallback` 把这类输出（同一个字连续 8 次以上，或每秒超过 8 字）改用 Paraformer 重转。门槛只看 Eval 定，Paraformer 在 Eval 上从未触发。

| 集 | 引擎 | 整场 CER（替换 / 删除 / 插入） | cpCER | 本人话语 CER | 他人误归属 | RTF（4090） |
| --- | --- | --- | --- | --- | --- | --- |
| Eval | Paraformer | 33.82%（6.5 / 26.3 / 1.1） | 37.98% | 31.28% | 3.1% | 0.015 |
| Eval | FireRed | 32.74%（5.0 / 27.0 / 0.8） | 36.71% | 30.01% | 3.0% | 0.019 |
| Eval | FireRed + 兜底 | **32.42%**（4.7 / 26.9 / 0.8） | 36.40% | **29.82%** | 3.0% | 0.020 |
| Test | Paraformer | 32.31%（7.1 / 24.4 / 0.9） | 36.08% | 27.59% | 3.6% | 0.012 |
| Test | FireRed | 32.64%（8.2 / 23.6 / 0.9） | 37.12% | 26.48% | 3.5% | 0.023 |
| Test | FireRed + 兜底 | **30.83%**（5.1 / 25.1 / 0.7） | 34.31% | **25.64%** | 3.4% | 0.022 |

兜底版与 Paraformer 逐场配对（Test）：整场 CER −1.48 点（20 场 19 好），本人话语 CER −1.94 点（48 人次 41 好 6 差，p < 10⁻⁶）；DER 不变，说明聚类没受影响。不加兜底时 Test 整场 CER 反而高 0.33 点，循环把整段内容替换掉。收益集中在替换错误，删除略增（FireRed 对附和声更「安静」）。识别模型能拿到的约 2 点，远小于聚类阈值的 8.5 点和重叠语音里约 30 点的删除，下一步的大头仍是重叠语音（分离或多通道）。FireRed 约 1.2B 参数，M1 Max 上片段 RTF 为 0.22（beam 1），Paraformer 为 0.045，约慢 5 倍；进线上包前要先在 Mac 上测整场耗时，或只在有 GPU 的算力机上提供。

## L4：用 LLM 校对缓存转写

[llm_clean.py](../deploy/asr-eval/llm_clean.py) 是仅用于公开评测的两阶段工具，不接入上传流程、不运行 ASR：

1. `prepare` 按清单 ID 从指定的基线缓存取假设文本，同场只清洗一次，再复制到每个本人和不在场声音的视图。不会读取人工参考文本或音频。仅发送说话人编号、原转写和允许编辑的片段编号，须显式加 `--public-alimeeting`；不要用于私人录音。
2. `replay` 按 `CommandTranscriber` 协议回放清洗结果，恢复各参考声音的相似度。时间、说话人、片段数量、说话人列表及各视图的相似度不变；评分仍用未经修改的 `twin eval-asr-session`。

[提示词](../deploy/asr-eval/llm_clean_prompt.txt) 要求只改确定的识别错误，禁止总结、润色、补全残句、跨片段搬词；保留口头语、重复和自我修正。每次提供全场上下文，只返回指定片段的稀疏修改。程序拒绝重复或越界 ID、类型错误和额外字段；空替换及超过编辑距离门槛的修改逐段回退原文。门槛按去标点后的字母数字字符计算，不能保证语义忠实，仍可能把原本正确的词改错。

```bash
# EVAL_ROOT 是仓库外的公开数据目录；TWIN_CONFIG 指向自己的配置。
# 密钥只从环境变量读取，不写入命令或输出文件。
uv run python deploy/asr-eval/llm_clean.py prepare \
  --sessions "$EVAL_ROOT/alimeeting/eval/sessions.jsonl" \
  --base-cache "$EVAL_ROOT/cache/<基线缓存>.jsonl" \
  --config "$TWIN_CONFIG" --public-alimeeting \
  --cache "$EVAL_ROOT/llm-cache" --out "$EVAL_ROOT/runs/<变体>/clean.jsonl" \
  --batch 400 --effort low --guard 0.25 --workers 2
```

响应按服务地址、模型、推理等级、提示词和完整输入的摘要缓存，权限 0600；改变门槛可复用响应，不需再次调用。`clean.metrics.json` 记录调用次数、供应商返回的 token 数、缓存命中、调用耗时、整批墙钟时间和被拒绝的修改。连接错误、HTTP 408/429/5xx 最多重试 4 次，退避 30/60/120/240 秒，并尊重秒数格式的 `Retry-After`；其他 HTTP 错误、耗尽重试或格式错误报错，不把失败伪装成成功清洗。

引擎 TOML 中，基线也可用 `replay --cache <原缓存>`，避免任何 GPU 连接；候选改为 `replay --cache <clean.jsonl>`。`command` 用 twin 环境的 Python 执行脚本；`files` 必须包括脚本、提示词、对应缓存，以及候选的 `clean.metrics.json`，使代码、提示词、参数和结果变化均改变身份。第一个引擎放未清洗基线，照常运行 `twin eval-asr-session --sessions ... --engines ... --out ... --cache ...`。回放得到的 RTF **不是**清洗速度，成本只看 `clean.metrics.json`。

### 2026-10-13：Eval 迭代

固定 `codex/gpt-6.1-sol`，全场假设文本作上下文，保留口头语；以下均为 Paraformer、聚类阈值 0.65，8 场 4.205 小时、81,005 个参考 token。只在 Eval 选择策略：

| 变体 | 整场 CER（替换 / 删除 / 插入） | 去口头语 CER | 本人话语 CER | 他人误归属 |
| --- | --- | --- | --- | --- |
| 未清洗 | 33.816%（6.475 / 26.261 / 1.080） | 31.997% | 31.280% | 3.122657% |
| low，80 段，门槛 0.25 | 33.609%（6.266 / 26.259 / 1.084） | 31.780% | 31.077% | 3.122652% |
| 同批响应，门槛 0.10 | 33.677%（6.337 / 26.256 / 1.084） | 31.850% | 31.136% | 3.122591% |
| 同批响应，门槛 1.00 | 33.572%（6.228 / 26.260 / 1.084） | 31.742% | 31.051% | 3.122652% |
| medium，80 段，门槛 0.25 | 33.598%（6.258 / 26.256 / 1.084） | 31.767% | 31.063% | 3.122167% |
| **最终：low，400 段，门槛 0.25** | **33.635%（6.292 / 26.260 / 1.083）** | **31.807%** | **31.104%** | **3.122611%** |

误归属多保留小数，避免四舍五入掩盖变化：时间和说话人不变，但编辑后的字数会轻微改变加权比例。门槛 1.00 仍拒绝空替换和超过原文长度 100% 的编辑，并非完全无保护。它比 0.25 多降 0.037 点，不值得放宽忠实性保护；medium 比 low 只多降 0.011 点。400 段版比 80 段少降 0.026 点，却少用 74% token，因此在接触 Test 前锁定为最终方案；该策略修正 128 段、拒绝 10 项大幅修改。

最终方案 Eval 整场 CER −0.181 点，配对 bootstrap 95% 区间 −0.236 至 −0.120，8 场 7 好 1 差，双侧符号检验 p=0.0703（未达到 0.05）；本人 CER −0.176 点，区间 −0.240 至 −0.109，21 人次 19 好 2 差，p=0.000221。**现有评分器的 L5 配对及区间单位是「场次 × 本人」，不是独立场次**，不可把这一 p 值当成 21 场独立证据。其他变体 L2 同样 7 好 1 差。DER、认领结果完全不变。收益几乎全在替换，删除率没有实质下降。

| Eval 方案 | 调用数 | 输入 / 输出 token | 总 token | 墙钟秒 | 每小时音频墙钟秒 |
| --- | --- | --- | --- | --- | --- |
| low，80 段 | 37 | 657,301 / 10,805 | 668,106 | 270.0 | 64.2 |
| medium，80 段 | 37 | 657,301 / 17,152 | 674,453 | 390.7 | 92.9 |
| 最终 low，400 段 | 9 | 166,337 / 5,953 | 172,290 | 125.9 | 29.9 |

以上为并发 2 的实际整批耗时；两次门槛重评没有新增模型调用。token 为网关返回的 usage（可能包含网关附加输入及供应商缓存），未获服务单价，不换算金额。最终方案约 2.14 次调用、40,972 token/小时音频。中途 FireRed Eval 遇到 HTTP 429，改为并发 1 并退避续跑；后续 Test 也按并发 1 运行，不把两种并发的速度混为一谈。输出均在仓库外 `runs/2026-10-13-llm-clean-*`，原始模型响应在 `llm-cache/`。

### 固定方案验证

在 Paraformer Eval 选定方案后，只将同一提示词、low 推理、400 段和 0.25 门槛应用到 FireRed Eval 及两个引擎的 Test；没有用 Test 改提示词或调门槛。Test 每个基线引擎仅运行这一种清洗配置；瞬时失败以相同请求退避重试，不作新变体。Test 为 20 场、10.777 小时、209,075 个参考 token、48 人次。

| 集 / 引擎 | 整场 CER（替换 / 删除 / 插入） | 去口头语 CER | 本人话语 CER | 他人误归属 |
| --- | --- | --- | --- | --- |
| Eval / FireRed + 兜底 | 32.419%（4.736 / 26.906 / 0.778） | 30.745% | 29.823% | 2.976468% |
| Eval / 同上 + 清洗 | 32.392%（4.707 / 26.906 / 0.779） | 30.715% | 29.795% | 2.976524% |
| Test / Paraformer | 32.308%（7.084 / 24.375 / 0.849） | 30.428% | 27.587% | 3.622111% |
| Test / Paraformer + 清洗 | 32.056%（6.832 / 24.375 / 0.848） | 30.162% | 27.320% | 3.622480% |
| Test / FireRed + 兜底 | 30.825%（5.048 / 25.119 / 0.658） | 29.059% | 25.643% | 3.433138% |
| Test / 同上 + 清洗 | 30.783%（5.008 / 25.116 / 0.660） | 29.015% | 25.606% | 3.433657% |

Paraformer Test 逐场配对：整场 CER **−0.252 点**（95% 区间 −0.302 至 −0.209），20 场全部变好，p=1.91×10⁻⁶；本人 CER **−0.267 点**（−0.320 至 −0.218），48 人次 43 好、3 差、2 不变，p=4.62×10⁻¹⁰（仍须注意 L5 的人次相关性）。整场净少错 527 个 token，约为原错误的 0.78%；其中替换少 526、删除多 1、插入少 2。删除这个主要瓶颈没有改善。

FireRed Eval 整场仅降 0.027 点，5 好、2 差、1 不变，p=0.453；本人降 0.028 点，9 好、6 差、6 不变，p=0.607。识别器本身更准确后，可供纯文本纠正的余量更小。FireRed Test 整场 CER **−0.042 点**（95% 区间 −0.066 至 −0.018），16 好、4 差，p=0.0118；本人 CER **−0.037 点**（−0.064 至 −0.013），27 好、10 差、11 不变，p=0.00763。统计上可见，但不到 0.1 点，不应当作实用升级。误归属也微升 0.000519 个百分点，未通过同一个上线门槛。

Paraformer Test 清洗 28 次成功调用（另有 1 次 HTTP 502，退避重试成功），输入 540,171、输出 21,125，共 561,296 token；并发 1，墙钟 873.7 秒，即每小时音频 **81.1 秒、2.60 次调用、52,085 token**。这是新增清洗成本，不含 ASR 和评分；失败请求没有返回 token 用量，不能假定完全免费。FireRed Eval 的 9 个响应共 168,831 token，其中 3 个为恢复前已有缓存；恢复这次墙钟 127.1 秒不是完整冷运行耗时，不与新跑的速度直接比较。

FireRed Test 为 28 次成功调用、另有 2 次 HTTP 429 重试；输入 536,501、输出 9,605，共 546,106 token，并发 1，墙钟 443.3 秒，折合每小时音频 **41.1 秒、2.60 次调用、50,676 token**。两套 Test 均没有缓存命中，所有成本来自此次固定方案。文字清洗请求已完成，未运行任何 GPU 任务。

### 建议

**保留评测工具，暂不接入 ingest，更不默认开启。** Paraformer 的 Test 改善是真实且一致的，但只有约 0.25 点，远小于此前聚类的 8.5 点、换识别器的约 1.5–2 点，以及重叠语音留下的二十多点删除。不能据此支持「LLM 清洗是下一步最高收益改进」；它更像有成本的小幅校对。

本任务的上线门槛还要求误归属不升。Paraformer Test 从 3.622111% 升至 3.622480%，**增加 0.000369 个百分点**，严格说没有通过。各声音视图、每段时间与说话人字段已逐项核对完全不变，DER 与认领结果也不变；这极小的变化来自文本长度改变后的比例加权，不能解读为明显的说话人混淆恶化，但也不能把它四舍五入隐藏为「零增长」。不根据 Test 再加长度保护或挑选编辑，否则将是在留出集上调参。

对 twin 的记忆抽取，优先保留逐字证据、口头语及自我修正，交由原有抽取流程决定哪些内容值得记住，不为了文笔先不可逆地删词。这里没有做 L6 记忆质量评测，不能从 CER 或阅读流畅度推断记忆一定更好；语义误改、上下文诱导的补写、延迟、服务限流，以及全场文字外发仍是风险。没有修改 `src/`、配置默认值或记忆抽取提示词；后续若探索更严格的保护，应另设独立留出集验证。
