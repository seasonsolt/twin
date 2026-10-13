#!/usr/bin/env python3
"""ASR 评测引擎：asr-funasr 包（1.2.0 起，SeACo-Paraformer + 标点）自己的识别路径。

用包的 venv 运行，pack 为包目录（含 run.py 与 pack.toml，已安装的版本目录或仓库里的 deploy/compute/asr-funasr）。
直接构造包内的 Engine 并调用 Engine.recognize()，识别与标点和线上相同；每批段数取 Engine.batch（GPU/MPS 16，CPU 1）。
评测片段已经切好，所以不跑 VAD 和声纹聚类（Engine 仍会加载它们，只多几秒）。options 可设 device（默认 auto）和
hotwords（字符串列表，默认不用）。按时长排序成批，同批补零较少；seconds 按时长分摊每批耗时。
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
    for name in ("HF_HUB_OFFLINE", "MODELSCOPE_OFFLINE", "TRANSFORMERS_OFFLINE"):
        os.environ[name] = "1"
    spec = importlib.util.spec_from_file_location("asr_funasr_run", Path(request["pack"]) / "run.py")
    pack = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pack)
    if not hasattr(pack, "Engine") or not hasattr(pack.Engine, "recognize"):
        raise SystemExit(f"{request['pack']} 没有 Engine.recognize；1.1.0 及更早的包用 sensevoice 引擎")
    import librosa

    engine = pack.Engine(options.get("device", "auto"))
    hotwords = list(options.get("hotwords", []))
    items = sorted(request["items"], key=lambda item: item["duration"])
    for start in range(0, len(items), engine.batch):
        part = items[start : start + engine.batch]
        clips = [librosa.load(item["audio"], sr=16000, mono=True)[0] for item in part]
        began = time.perf_counter()
        texts = engine.recognize(clips, hotwords)
        elapsed = time.perf_counter() - began
        total = sum(item["duration"] for item in part)
        for item, text in zip(part, texts, strict=True):
            emit({"id": item["id"], "text": text, "seconds": elapsed * item["duration"] / total})


if __name__ == "__main__":
    main()
