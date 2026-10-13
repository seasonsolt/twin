#!/usr/bin/env python3
"""ASR 评测引擎：Fun-ASR-Nano-2512（通义），经 Transformers 原生实现在 Apple 芯片的 MPS 上运行。

用装有 transformers>=5.17 的 Python 运行，model 为 FunAudioLLM/Fun-ASR-Nano-2512-hf 的本机目录；不加载远程代码。
默认 language=zh、贪心解码、float32、batch_size=16、max_new_tokens=256。按时长排序后成批解码：
音频特征右侧补零并带掩码，文本提示左侧补齐，所以同批长度不同只影响速度。
"""

import json
import sys
import time
from importlib import metadata

PACKAGES = ("transformers", "torch", "librosa")


# Results own stdout; libraries that print banners or progress are sent to stderr instead.
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
    import librosa
    import torch
    from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor

    device = options.get("device") or ("mps" if torch.backends.mps.is_available() else "cpu")
    batch = int(options.get("batch_size", 16))
    language = options.get("language", "zh")
    max_new_tokens = int(options.get("max_new_tokens", 256))
    dtype = getattr(torch, options.get("dtype", "float32"))
    processor = AutoProcessor.from_pretrained(request["model"], local_files_only=True)
    model = AutoModelForSpeechSeq2Seq.from_pretrained(request["model"], local_files_only=True, dtype=dtype)
    model = model.to(device).eval()
    items = sorted(request["items"], key=lambda item: item["duration"])
    for start in range(0, len(items), batch):
        part = items[start : start + batch]
        clips = [librosa.load(item["audio"], sr=16000, mono=True)[0] for item in part]
        began = time.perf_counter()
        inputs = processor.apply_transcription_request(
            audio=clips,
            language=language,
            processor_kwargs={
                "return_tensors": "pt",
                "audio_kwargs": {"sampling_rate": 16000},
                "text_kwargs": {"padding": True},
            },
        ).to(device)
        if "input_features" in inputs:
            inputs["input_features"] = inputs["input_features"].to(dtype)
        with torch.inference_mode():
            generated = model.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=False)
        texts = processor.batch_decode(generated[:, inputs["input_ids"].shape[1] :], skip_special_tokens=True)
        elapsed = time.perf_counter() - began
        total = sum(item["duration"] for item in part)
        for item, text in zip(part, texts, strict=True):
            emit({"id": item["id"], "text": text.strip(), "seconds": elapsed * item["duration"] / total})


if __name__ == "__main__":
    main()
