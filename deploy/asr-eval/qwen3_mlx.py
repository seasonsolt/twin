#!/usr/bin/env python3
"""ASR 评测引擎：Qwen3-ASR，经 mlx-audio 在 Apple 芯片上运行。

用装有 mlx-audio 的 Python 运行，model 为本机模型目录。默认 language=Chinese、贪心解码、batch_size=32。
batch_size>1 时按时长排序，交给 mlx-audio 的批量解码器 _generate_chunks_batched（私有接口，升级 mlx-audio 后要复核）。
它把同批音频用静音补到等长；在 M1 Max 上 32 条一批比逐条快约 1.8 倍，但约 8% 的转写字面有变化，CER 变化在 0.1 点内。
批大小因此计入引擎身份，比较时两边要用同样的设置。batch_size=1 走 generate()，与逐条调用一致。
"""

import json
import os
import sys
import time
from importlib import metadata

PACKAGES = ("mlx-audio", "mlx")


# Results own stdout; libraries that print banners or progress (funasr does) are sent to stderr instead.
RESULTS = sys.stdout
sys.stdout = sys.stderr


def emit(row):
    print(json.dumps(row, ensure_ascii=False), file=RESULTS, flush=True)


def main():
    if sys.argv[1:] == ["--identify"]:
        emit({"versions": {name: metadata.version(name) for name in PACKAGES}})
        return
    request = json.load(sys.stdin)
    options = request.get("options") or {}
    os.environ["HF_HUB_OFFLINE"] = "1"
    import numpy as np
    from mlx_audio.lm.sample_utils import make_sampler
    from mlx_audio.stt.utils import load_audio, load_model

    model = load_model(request["model"])
    language = options.get("language", "Chinese")
    batch = int(options.get("batch_size", 32))
    max_tokens = int(options.get("max_tokens", 512))
    items = sorted(request["items"], key=lambda item: item["duration"])
    if batch == 1:
        for item in items:
            began = time.perf_counter()
            result = model.generate(item["audio"], language=language, max_tokens=max_tokens)
            emit({"id": item["id"], "text": result.text.strip(), "seconds": time.perf_counter() - began})
        return
    sampler = make_sampler(0.0)
    for start in range(0, len(items), batch):
        part = items[start : start + batch]
        chunks = [(np.array(load_audio(item["audio"], sr=16000)), 0.0) for item in part]
        began = time.perf_counter()
        # The token budget is shared by the whole call, so give each clip its own max_tokens.
        texts, *_ = model._generate_chunks_batched(
            chunks,
            max_tokens=max_tokens * len(part),
            sampler=sampler,
            logits_processors=None,
            language=language,
            system_prompt=None,
            batch_size=len(part),
            verbose=False,
        )
        elapsed = time.perf_counter() - began
        total = sum(item["duration"] for item in part)
        for item, text in zip(part, texts, strict=True):
            emit({"id": item["id"], "text": text.strip(), "seconds": elapsed * item["duration"] / total})


if __name__ == "__main__":
    main()
