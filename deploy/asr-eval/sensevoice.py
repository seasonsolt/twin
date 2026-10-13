#!/usr/bin/env python3
"""ASR 评测引擎：SenseVoiceSmall，按 asr-funasr 包转写 VAD 片段的方式运行。

用算力包 venv 的 Python 运行，模型路径来自包内 run.py 的 model_paths()，与线上同一份权重。参数对齐 run.py：
默认 MPS、每批 16 段、language=zh、use_itn=True。评测片段已经切好，所以不跑 VAD 和声纹聚类。
stdin 收一个 JSON 请求，stdout 每条输出一行 {"id","text","seconds"}；seconds 按时长分摊每批推理耗时。
"""

import importlib.util
import json
import os
import re
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
    paths = pack.model_paths()
    # Packs up to 1.1.0 list SenseVoiceSmall first; from 1.2.0 they map roles and recognize with Paraformer.
    if not isinstance(paths, list) or "SenseVoice" not in paths[0]:
        raise SystemExit(f"{request['pack']} 不含 SenseVoiceSmall；用 pack 指向 asr-funasr 1.1.0 或更早的版本目录")
    sensevoice = paths[0]
    for name in ("HF_HUB_OFFLINE", "MODELSCOPE_OFFLINE", "TRANSFORMERS_OFFLINE"):
        os.environ[name] = "1"
    os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
    import librosa
    import torch
    from funasr import AutoModel

    torch.set_num_threads(8)
    device = options.get("device") or ("mps" if torch.backends.mps.is_available() else "cpu")
    batch = int(options.get("batch_size", 16 if device == "mps" else 1))
    language = options.get("language", "zh")
    asr = AutoModel(model=sensevoice, device=device, disable_update=True, disable_pbar=True)
    # Similar lengths per batch, like production's merged VAD chunks; padding stays small.
    items = sorted(request["items"], key=lambda item: item["duration"])
    for start in range(0, len(items), batch):
        part = items[start : start + batch]
        clips = [librosa.load(item["audio"], sr=16000, mono=True)[0] for item in part]
        began = time.perf_counter()
        results = asr.generate(
            input=clips, cache={}, language=language, use_itn=True, batch_size=len(clips), disable_pbar=True
        )
        elapsed = time.perf_counter() - began
        total = sum(item["duration"] for item in part)
        for item, result in zip(part, results, strict=True):
            text = re.sub(r"<\|[^|]*\|>", "", str(result.get("text", ""))).strip()
            emit({"id": item["id"], "text": text, "seconds": elapsed * item["duration"] / total})


if __name__ == "__main__":
    main()
