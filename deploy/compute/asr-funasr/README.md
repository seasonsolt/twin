# asr-funasr 会议录音转写包

这是音视频记忆的**输入能力**：FSMN VAD 找到语音片段，CAM++ 声纹聚类区分说话人并与本人参考声音比较，SeACo-Paraformer-large 转写文字，CT-Transformer 补标点。Paraformer 只识别中文（夹杂的英文术语也能出），中文会议上的术语和人名明显好于 SenseVoice，并支持热词。视频提取后的音轨走同一条流程。S1 是说话时间最长的人，不代表本人；请在网页核对、认领本人片段。

Mac 上每次转写启动一个 Python 进程，完成后退出，无常驻 worker、无服务端口。设备按 CUDA、MPS、CPU 的顺序自动选择；可在配置中的命令末尾追加 `--device cpu` 强制使用 CPU。实测 49 分钟会议：M 系列 Mac（MPS）约 67 秒，RTX 4090（常驻服务，见下文）约 16 秒。转写过程向 stderr 输出 `@@twin-progress <0–1>` 行，twin 据此显示进度。一次进程冷启动约 30 秒、峰值内存约 5 GB，首次导入可能更慢，适合后台整理会议录音。

## 安装与移除

在 Apple Silicon Mac 的仓库根目录执行（需要 uv 和 ffmpeg）：

```bash
brew install uv ffmpeg
uv run twin --config ./twin.toml compute list
uv run twin --config ./twin.toml compute install asr-funasr --download-models
uv run twin --config ./twin.toml compute status
uv run twin --config ./twin.toml compute remove asr-funasr
```

已有模型可去掉 `--download-models`，校验通过直接复用，不重复下载。缺失或摘要不符且没有该参数时，安装报错退出。`--force` 重建当前版本环境，仍不会覆盖手写 `[asr]`。依赖与模型首次准备通常需要数分钟到十几分钟，取决于网络与缓存；建议预留至少 5 GiB 磁盘空间（依赖、模型和下载缓存），重建时还需容纳旧环境。

安装位置优先使用 `TWIN_COMPUTE_HOME`，否则为 `TwinPaths.compute`（macOS 默认 `~/Library/Application Support/twin/compute`，可由 `TWIN_HOME` 间接改变）。这是机器共享目录，多个 clone 共用 `asr-funasr/<版本>` 与 `current` 链接，但各自配置要分别启用。需要完全留在仓库内时，安装和启动网页都设置同一个绝对路径：

```bash
export TWIN_COMPUTE_HOME="$PWD/.pi-runs/compute-home"
uv run twin --config ./twin.toml compute install asr-funasr
```

工具只更新 `--config` / `TWIN_CONFIG` / `./twin.toml` 所选文件中的标记块；其他内容与注释保留。已有手写 `[asr]` 时，先手动备份并移除该节，或保留它并手动设置命令。安装成功后按 Ctrl-C 停止网页，重新 `./scripts/local-up.sh`，在“记忆”页上传录音；已有失败上传点“重新转写”。

移除会删除此共享包的所有版本，以及当前配置的工具标记块，**保留模型缓存**。其他 clone 的配置不会自动修改，移除后它们需要重新安装或取消转写配置。模型缓存位置与大小会打印，由用户决定是否清理。

## 模型来源与版本

| ModelScope ID | 用途 | 权重大小 |
| --- | --- | --- |
| [iic/speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch](https://modelscope.cn/models/iic/speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch) | 中文语音识别，支持热词 | 约 952 MiB |
| [iic/punc_ct-transformer_cn-en-common-vocab471067-large](https://modelscope.cn/models/iic/punc_ct-transformer_cn-en-common-vocab471067-large) | 中英文标点恢复 | 约 1092 MiB |
| [iic/speech_fsmn_vad_zh-cn-16k-common-pytorch](https://modelscope.cn/models/iic/speech_fsmn_vad_zh-cn-16k-common-pytorch) | 语音活动检测 | 约 1.6 MiB |
| [iic/speech_campplus_sv_zh-cn_16k-common](https://modelscope.cn/models/iic/speech_campplus_sv_zh-cn_16k-common) | 192 维声纹、聚类与参考声音比较 | 约 26.7 MiB |

模型与必要配置合计约 2.0 GiB；`pack.toml` 用 `role`（asr / vad / punc / speaker）标明每个模型的用途。`pack.toml` 固定已验证的 `master` 快照文件 SHA-256；上游 master 若变化，不会静默接纳新权重，需要维护者更新包清单和版本。摘要与 ModelScope 官方仓库一致，并补齐实际运行必需的 CMVN、`seg_dict` 等文件。依赖按 P0 的完整版本快照锁定，含 scikit-learn。

缓存根为 `MODELSCOPE_CACHE`（默认 `~/.cache/modelscope`）；优先查找 `models/<组织>--<模型>/snapshots/<revision>`，兼容历史 `hub/<组织>/<模型>` 和 `<组织>/<模型>` 布局。仅在显式允许下载时调用 ModelScope SDK。安装流式校验摘要，版本目录的 `verified.json` 缓存文件大小、mtime 和期望摘要；未变的文件可免于重复读取。

## 命令契约与隐私

完整契约见 [docs/MEDIA.md](../../../docs/MEDIA.md#音视频记忆)。stdin 接收 JSON 请求，stdout 最后一行输出 JSON 结果；依赖日志转到 stderr。1.2.1 起请求可带 `"references": {"<名称>": "<绝对路径>"}`（最多 32 份），每个说话人另返回 `similarities`，与每份声音逐一比较；转写和切分不变，`twin eval-asr-session` 用它把每场会议只跑一次。缺失的声音文件跳过，与 `reference` 相同；常驻服务和 `remote.py` 同样支持。1.2.1 起声纹聚类的余弦距离阈值默认 0.65（原为 0.55，越大合并越多）：AliMeeting 上场均多出的说话人从 3.9 / 3.6 个降到 1.4 / 0.5 个（Eval / Test），本人话语 CER 降 8.6 / 8.5 个点，他人误归属从 1.8% / 2.5% 升到 3.1% / 3.6%，详见 [docs/ASR_EVAL.md](../../../docs/ASR_EVAL.md)。评测可在请求里带 `"cluster_threshold"` 覆盖，或在 `run.py` / `remote.py` 命令末尾加 `--cluster-threshold 0.7`；twin 自己从不传。1.3.0 起每个说话人另返回 `embedding`（192 维单位声纹），twin 存进 `analysis.json`；请求带 `"embed": true` 时只返回整段音频的声纹 `{"ok": true, "embedding": [...]}`，不转写，常驻服务对应 `POST /embed`。本人声音换了以后，twin 用它和存下的声纹重新比较，不必重新转写。1.3.1 起，低于时长下限的小类只有和最近的大类足够像（质心余弦 ≥ 0.5 − 0.2/窗口数）、并且明显比第二近的大类更像（高 0.05）时才并入，否则保留为单独的短说话人，不再一律并进最近的人，详见 [docs/ASR_EVAL.md](../../../docs/ASR_EVAL.md#小类合并门限2026-10-20asr-funasr-131)。1.3.2 起 `"embed": true` 的请求可再带 `"spans": [[[开始, 结束], ...], ...]`（秒；每项最多 64 段、拼起来算一个声纹，最多 20000 项），返回 `{"ok": true, "embeddings": [[...] 或 null, ...]}`，与 spans 一一对应，不足 0.1 秒的为 null；twin 用它逐段复核已确认的说话人，`remote.py` 原样转发。旧版本忽略 spans、只返回整段声纹，twin 会改为逐段单独请求。1.3.3 起在 CUDA 上用 8 个线程把这些片段送进 GPU 上的 CAM++（直接调模型推理，绕开 `AutoModel.generate` 共享的可变参数），4090 上 1501 段从 83 秒降到 20 秒，声纹与 1.3.2 一致（余弦 ≥ 0.99999）；MPS 与 CPU 不变。`run.py --check` 加载四个模型，用内置 1 秒正弦波逐一推理并检查声纹维度；不需要任何用户录音。

转写、声纹提取和匹配全程本机离线；运行强制设置 `HF_HUB_OFFLINE`、`MODELSCOPE_OFFLINE`、`TRANSFORMERS_OFFLINE`，模型加载禁用更新。缺模型只报错，不触发下载。安装 Python 依赖需要网络或已有包缓存；模型下载需要显式 `--download-models`。后续记忆整理/聊天仍使用 twin 配置的大模型，其出境范围由该配置决定。

## FireRed 推理优化（1.5.4）

重叠流程的 FireRed 在支持原生 BF16 的 CUDA 显卡上使用 BF16 权重和输入；其余设备保留 FP32。beam=1 解码按 token 缓存 self-attention 的键和值，attention 使用 PyTorch SDPA，已有 cross-attention 缓存继续使用。其他 beam/search 参数仍交给上游解码器。分人、分离、声纹、复读回退和补标点规则不变。

BF16 和 SDPA 可能改变极少量边界词，因此包版本和转写版本都升为 **1.5.4**。已有录音由用户决定是否重新转写。启动日志打印 FireRed 的实际精度；`/health` 返回包与转写版本。质量验证范围和限制见 [ASR 评测](../../../docs/ASR_EVAL.md)。

## 热词

请求 JSON 可带 `"hotwords": ["邓郁松", "魔搭"]`：去掉空白项和含空格的词，去重，最多 200 个。热词只提高这些词被识别出来的概率，不会强行替换文字。热词的来源（例如从记忆里的人名、项目名自动整理）以后再定，目前默认不传。

## 常驻服务与远程转写

没有 Apple 芯片、或想用独立 GPU 机器时，可以在 GPU 机器上常驻一份模型，twin 所在机器用只依赖标准库的 `remote.py` 转发请求，契约与 `run.py` 完全相同：

```bash
# GPU 机器：Python 环境需含 pack 依赖与 CUDA 版 torch；模型缓存同上
python run.py --serve --port 18790          # 只监听 127.0.0.1；启动时先跑一次 --check
curl -s http://127.0.0.1:18790/health       # {"ok": true, "version": ..., "device": "cuda", "busy": false}
```

```toml
# twin 机器的 twin.toml（手写 [asr]，local-up 不会覆盖）
[asr]
provider = "command"
command = "python3 /path/to/twin/deploy/compute/asr-funasr/remote.py --url http://127.0.0.1:18790"
```

服务一次只跑一个任务，其余请求排队；响应是逐行 JSON（进度，最后是结果），`remote.py` 把进度转成 `@@twin-progress` 行。正因为服务自己排队，twin 的录音库在用 `remote.py` 时会提前开始下一条录音：解码、上传和上一条的识别同时进行，服务做完一条马上接下一条，不再空等；下一条解码后的音频要放得进 `[library] headroom_gb` 之外的空间才提前开始，否则照旧一条一条来。`[asr] ahead = true / false` 可以强制打开或关闭；在本机直接跑模型的命令（`run.py`）默认不提前，免得同时加载两份模型。上传的录音和参考声音写进临时目录，处理完立即删除。服务没有认证，只应监听本机，再经 SSH 隧道转发到 twin 所在机器，不要直接暴露到网络。`remote.py` 上传前会用 ffmpeg 把 wav 无损压成 FLAC（体积约为原来的 40%，识别结果不变；压缩失败就原样上传，`--no-flac` 关闭），带宽窄时上传时间能省一半以上。`remote.py --hotwords <文件>` 可指定热词文件（每行一个，`#` 开头为注释），请求自带热词时以请求为准。

## GPU 上的重叠感知转写（1.4）

1.4.0 起，CUDA 上默认走重叠感知转写（`pipeline = "overlap"`），Mac 和 CPU 不变（`classic`，即上面的 Paraformer 流程）：

1. 响度归一到 −27 dBFS（分人仍用原始音频）。
2. 3D-Speaker 的分人流程：FSMN VAD、1.5 秒窗 0.75 秒步长、中英文 CAM++ 声纹、谱聚类（随机种子固定，结果可复现）。
3. pyannote community-1 的分段模型找出两人同时说话的地方，并给重叠帧补上第二个说话人。权重随包分发（`weights/`，约 5.6 MiB，sha256 写在 `pack.toml`），推理代码在 `segmentation.py`，不依赖 pyannote.audio、不需要 HF token。
4. 重叠区（前后各带 0.5 秒上下文）用 MossFormer2 分成两路，按声纹把两路分给对应的人；每人每段只保留自己的声音，其他人说话的时间静音。
5. FireRedASR2-AED 识别，CT-Transformer 补标点；FireRed 输出复读（同一字连续 8 次以上，或每秒超过 8 字）时改用 Paraformer 重识别这一段。
6. 本人认领、声纹和返回格式与 `classic` 相同。

本人话语 CER 在 AliMeeting Eval / Test 上从 31.7% / 28.0% 降到 20.5% / 17.6%，在留出的 AISHELL-4 测试集上从 23.2% 降到 16.1%（选对说话人时），详见 [docs/ASR_EVAL.md](../../../docs/ASR_EVAL.md#个人上传路径三套分人方案对比2026-10-21)。请求带 `"pipeline": "classic"`（或 `run.py --pipeline classic`、`remote.py --pipeline classic`）可退回原流程，评测用它做配对对照；twin 自己从不传。缺少下面任一模型时自动退回 `classic`，`/health` 和 `--check` 报告实际使用的流程。

1.4.1 起转写结果另带 `"version"`（包版本）和 `"pipeline"`（实际使用的流程），转写和声纹与 1.4.0 相同。twin 把它记在每份转写上，换了包版本或流程后，录音库会列出哪些录音可以用新版重新转写；更早的包不带这两项，twin 记为版本未知。

1.5.1 转写结果与 1.4.1 相同、只是更快：单段声纹在 GPU 上算，识别和补标点交替进行。超过 16000 个声纹窗（约 3.5 小时语音）的录音，谱聚类改用同一个相似度矩阵的稀疏存储；此前 8 小时以上的录音要几十 GB 内存、会被系统杀掉，现在约 3 GB。

1.5.2 每条请求结束后把释放的内存交还系统（服务按请求开线程，glibc 原本会留着各线程释放的内存，连续转写几条多小时录音后超过 27 GB 被系统杀掉）；`remote.py` 在服务没有任何响应时（重启加载模型的半分钟里）每 5 秒重试，最多 2 分钟，环境变量 `TWIN_ASR_CONNECT_SECONDS` 可改。

额外的模型在运行时从官方仓库取（`pack.toml` 的 `cuda_models` 固定了版本与 sha256，不随包分发）：

| 模型 | 来源 | 用途 |
| --- | --- | --- |
| iic/speech_campplus_sv_zh_en_16k-common_advanced | ModelScope | 分人用的中英文声纹 |
| alibabasglab/MossFormer2_SS_16K | Hugging Face | 重叠语音两路分离 |
| FireRedTeam/FireRedASR2-AED | Hugging Face | 识别 |

GPU 环境在 pack 依赖之外还需要 `clearvoice`、FireRedASR2S 的 `fireredasr2s` 包和 `safetensors`。4090 上常驻服务约占 12 GB 显存，常驻内存约 8–10 GB、峰值约 11 GB；AliMeeting Eval 上 RTF 0.04，AISHELL-4 上 0.03（Mac 经 SSH 隧道测，含上传），原流程约 0.01。第三方代码与许可见 [THIRD_PARTY.md](THIRD_PARTY.md)。
