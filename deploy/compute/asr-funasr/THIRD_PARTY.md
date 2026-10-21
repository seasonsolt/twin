# 第三方代码与模型

asr-funasr 1.4 的重叠感知转写（`overlap.py`）用到以下第三方代码与模型。

## 随包分发

| 文件 | 来源 | 许可 | 改动 |
| --- | --- | --- | --- |
| `diarize.py` | [3D-Speaker](https://github.com/modelscope/3D-Speaker) commit 065629c 的 `speakerlab/bin/infer_diarization.py` 与 `speakerlab/process/cluster.py` | Apache-2.0 | 改为从本地路径加载模型；只保留谱聚类，AHC 用 scipy 的 average linkage 代替 fastcluster；k-means 与特征分解固定随机种子 |
| `segmentation.py` | [pyannote.audio](https://github.com/pyannote/pyannote-audio) 4.0.7 的 PyanNet、SincNet、Powerset 与 `Inference` 滑窗推理；SincNet 的滤波器组来自 [asteroid-filterbanks](https://github.com/asteroid-team/asteroid-filterbanks) 0.4.0 | MIT | 只保留推理所需部分，超参数写成常量 |
| `weights/segmentation-community-1.safetensors` | [pyannote/speaker-diarization-community-1](https://huggingface.co/pyannote/speaker-diarization-community-1) 的 `segmentation/pytorch_model.bin`（sha256 7ad24338…，5,906,507 字节） | CC-BY-4.0 | 只取出权重张量，转存为 safetensors；数值不变 |

### 3D-Speaker（Apache-2.0）

Copyright 3D-Speaker (https://github.com/alibaba-damo-academy/3D-Speaker). All Rights Reserved.
Licensed under the Apache License, Version 2.0 (http://www.apache.org/licenses/LICENSE-2.0).

### pyannote.audio（MIT）

```
MIT License

Copyright (c) 2020 CNRS

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

### asteroid-filterbanks（MIT）

```
MIT License

Copyright (c) 2019 Pariente Manuel

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

### pyannote speaker-diarization-community-1（CC-BY-4.0）

分段模型权重由 pyannote 发布，许可为 [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/)。这里随包分发的是转存为 safetensors 的同一份权重，没有重新训练或改动数值。

## 运行时下载，不随包分发

`pack.toml` 的 `cuda_models` 和 `playback_models` 固定了版本与 sha256：

| 模型 | 用途 | 许可 |
| --- | --- | --- |
| [iic/speech_campplus_sv_zh_en_16k-common_advanced](https://modelscope.cn/models/iic/speech_campplus_sv_zh_en_16k-common_advanced)（ModelScope） | 分人用的中英文声纹 | Apache-2.0 |
| [alibabasglab/MossFormer2_SS_16K](https://huggingface.co/alibabasglab/MossFormer2_SS_16K) | 重叠语音两路分离 | Apache-2.0 |
| [FireRedTeam/FireRedASR2-AED](https://huggingface.co/FireRedTeam/FireRedASR2-AED) | 识别 | Apache-2.0 |
| [alibabasglab/MossFormer2_SE_48K](https://huggingface.co/alibabasglab/MossFormer2_SE_48K) | 试听用的降噪（不参与转写） | Apache-2.0 |

推理代码来自 Python 依赖 `clearvoice`（ClearerVoice-Studio，Apache-2.0）和 `fireredasr2s`（FireRedASR2S，Apache-2.0），只在 GPU 服务的环境里安装。
