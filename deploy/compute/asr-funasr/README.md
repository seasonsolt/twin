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

完整契约见 [docs/MEDIA.md](../../../docs/MEDIA.md#音视频记忆)。stdin 接收 JSON 请求，stdout 最后一行输出 JSON 结果；依赖日志转到 stderr。1.2.1 起请求可带 `"references": {"<名称>": "<绝对路径>"}`（最多 32 份），每个说话人另返回 `similarities`，与每份声音逐一比较；转写和切分不变，`twin eval-asr-session` 用它把每场会议只跑一次。缺失的声音文件跳过，与 `reference` 相同；常驻服务和 `remote.py` 同样支持。1.2.1 起声纹聚类的余弦距离阈值默认 0.65（原为 0.55，越大合并越多）：AliMeeting 上场均多出的说话人从 3.9 / 3.6 个降到 1.4 / 0.5 个（Eval / Test），本人话语 CER 降 8.6 / 8.5 个点，他人误归属从 1.8% / 2.5% 升到 3.1% / 3.6%，详见 [docs/ASR_EVAL.md](../../../docs/ASR_EVAL.md)。评测可在请求里带 `"cluster_threshold"` 覆盖，或在 `run.py` / `remote.py` 命令末尾加 `--cluster-threshold 0.7`；twin 自己从不传。`run.py --check` 加载四个模型，用内置 1 秒正弦波逐一推理并检查声纹维度；不需要任何用户录音。

转写、声纹提取和匹配全程本机离线；运行强制设置 `HF_HUB_OFFLINE`、`MODELSCOPE_OFFLINE`、`TRANSFORMERS_OFFLINE`，模型加载禁用更新。缺模型只报错，不触发下载。安装 Python 依赖需要网络或已有包缓存；模型下载需要显式 `--download-models`。后续记忆整理/聊天仍使用 twin 配置的大模型，其出境范围由该配置决定。

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

服务一次只跑一个任务，其余请求排队；响应是逐行 JSON（进度，最后是结果），`remote.py` 把进度转成 `@@twin-progress` 行。上传的录音和参考声音写进临时目录，处理完立即删除。服务没有认证，只应监听本机，再经 SSH 隧道转发到 twin 所在机器，不要直接暴露到网络。`remote.py` 上传前会用 ffmpeg 把 wav 无损压成 FLAC（体积约为原来的 40%，识别结果不变；压缩失败就原样上传，`--no-flac` 关闭），带宽窄时上传时间能省一半以上。`remote.py --hotwords <文件>` 可指定热词文件（每行一个，`#` 开头为注释），请求自带热词时以请求为准。
