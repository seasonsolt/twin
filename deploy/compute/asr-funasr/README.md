# asr-funasr 会议录音转写包

这是音视频记忆的**输入能力**：FSMN VAD 找到语音片段，CAM++ 声纹聚类区分说话人并与本人参考声音比较，SenseVoiceSmall 转写文字。视频提取后的音轨走同一条流程。S1 是说话时间最长的人，不代表本人；请在网页核对、认领本人片段。

每次转写启动一个 Python 进程，完成后退出，无常驻 worker、无服务端口。默认 CPU；如需尝试 MPS，可在配置中的命令末尾手动追加 `--device mps`。一次进程冷启动约 17 秒，首次导入可能更慢，适合后台整理会议录音。

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

安装位置优先使用 `TWIN_COMPUTE_HOME`，否则为 `TwinPaths.compute`（macOS 默认 `~/Library/Application Support/twin/compute`，可由 `TWIN_HOME` 间接改变）。这是机器共享目录，多个 clone 共用 `asr-funasr/1.0.0` 与 `current` 链接，但各自配置要分别启用。需要完全留在仓库内时，安装和启动网页都设置同一个绝对路径：

```bash
export TWIN_COMPUTE_HOME="$PWD/.pi-runs/compute-home"
uv run twin --config ./twin.toml compute install asr-funasr
```

工具只更新 `--config` / `TWIN_CONFIG` / `./twin.toml` 所选文件中的标记块；其他内容与注释保留。已有手写 `[asr]` 时，先手动备份并移除该节，或保留它并手动设置命令。安装成功后按 Ctrl-C 停止网页，重新 `./scripts/local-up.sh`，在“记忆”页上传录音；已有失败上传点“重新转写”。

移除会删除此共享包的所有版本，以及当前配置的工具标记块，**保留模型缓存**。其他 clone 的配置不会自动修改，移除后它们需要重新安装或取消转写配置。模型缓存位置与大小会打印，由用户决定是否清理。

## 模型来源与版本

| ModelScope ID | 用途 | 权重大小 |
| --- | --- | --- |
| [iic/SenseVoiceSmall](https://modelscope.cn/models/iic/SenseVoiceSmall) | 语音文字识别 | 约 893 MiB |
| [iic/speech_fsmn_vad_zh-cn-16k-common-pytorch](https://modelscope.cn/models/iic/speech_fsmn_vad_zh-cn-16k-common-pytorch) | 语音活动检测 | 约 1.6 MiB |
| [iic/speech_campplus_sv_zh-cn_16k-common](https://modelscope.cn/models/iic/speech_campplus_sv_zh-cn_16k-common) | 192 维声纹、聚类与参考声音比较 | 约 26.7 MiB |

模型与必要配置合计约 0.90 GiB。`pack.toml` 固定已验证的 `master` 快照文件 SHA-256；上游 master 若变化，不会静默接纳新权重，需要维护者更新包清单和版本。摘要主要来自 P0 清单，另外补齐实际运行必需的 CMVN 和 SentencePiece 文件。依赖按 P0 的完整版本快照锁定，含 scikit-learn。

缓存根为 `MODELSCOPE_CACHE`（默认 `~/.cache/modelscope`）；优先查找 `models/<组织>--<模型>/snapshots/<revision>`，兼容历史 `hub/<组织>/<模型>` 和 `<组织>/<模型>` 布局。仅在显式允许下载时调用 ModelScope SDK。安装流式校验摘要，版本目录的 `verified.json` 缓存文件大小、mtime 和期望摘要；未变的文件可免于重复读取。

## 命令契约与隐私

完整契约见 [docs/MEDIA.md](../../../docs/MEDIA.md#音视频记忆)。stdin 接收 JSON 请求，stdout 最后一行输出 JSON 结果；依赖日志转到 stderr。`run.py --check` 加载三个模型，用内置 1 秒正弦波逐一推理并检查声纹维度；不需要任何用户录音。

转写、声纹提取和匹配全程本机离线；运行强制设置 `HF_HUB_OFFLINE`、`MODELSCOPE_OFFLINE`、`TRANSFORMERS_OFFLINE`，模型加载禁用更新。缺模型只报错，不触发下载。安装 Python 依赖需要网络或已有包缓存；模型下载需要显式 `--download-models`。后续记忆整理/聊天仍使用 twin 配置的大模型，其出境范围由该配置决定。
