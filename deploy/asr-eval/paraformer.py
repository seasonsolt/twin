#!/usr/bin/env python3
"""ASR 评测引擎：SeACo-Paraformer 加标点，即 asr-funasr 1.2.0 起的线上识别。

用算力包 venv 的 Python 运行，直接实例化包内 run.py 的 Engine 并调用 recognize()，模型、设备选择、标点都与线上
同一份代码。评测片段已经切好，所以不跑 VAD 和声纹聚类。options 可设 device、batch_size（默认取包的设置：
GPU 16、CPU 1）、hotwords（字符串列表，与线上请求的 hotwords 相同）。
stdin 收一个 JSON 请求，stdout 每条输出一行 {"id","text","seconds"}；seconds 按时长分摊每批推理耗时。
"""

import importlib.util
import json
import os
import sys
import time
from importlib import metadata
from pathlib import Path

PACKAGES = ("funasr", "torch", "librosa")


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
    spec = importlib.util.spec_from_file_location("asr_funasr_run", Path(request["pack"]) / "run.py")
    pack = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pack)
    # Packs up to 1.1.0 return a list led by SenseVoiceSmall; from 1.2.0 a role map with the Paraformer recognizer.
    if not isinstance(pack.model_paths(), dict) or not hasattr(pack.Engine, "recognize"):
        raise SystemExit(f"{request['pack']} 不是 asr-funasr 1.2.0 或更新的版本；Paraformer 从 1.2.0 起才是线上识别")
    for name in ("HF_HUB_OFFLINE", "MODELSCOPE_OFFLINE", "TRANSFORMERS_OFFLINE"):
        os.environ[name] = "1"
    import librosa

    engine = pack.Engine(options.get("device", "auto"))
    batch = int(options.get("batch_size", engine.batch))
    hotwords = pack.parse_hotwords(options.get("hotwords"))
    # Similar lengths per batch, like production's merged VAD chunks; padding stays small.
    items = sorted(request["items"], key=lambda item: item["duration"])
    for start in range(0, len(items), batch):
        part = items[start : start + batch]
        clips = [librosa.load(item["audio"], sr=16000, mono=True)[0] for item in part]
        began = time.perf_counter()
        texts = engine.recognize(clips, hotwords)
        elapsed = time.perf_counter() - began
        total = sum(item["duration"] for item in part)
        for item, text in zip(part, texts, strict=True):
            emit({"id": item["id"], "text": text, "seconds": elapsed * item["duration"] / total})


if __name__ == "__main__":
    main()
