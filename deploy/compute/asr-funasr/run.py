#!/usr/bin/env python3
"""离线会议转写命令；只在执行请求时导入模型依赖。"""

import argparse
import contextlib
import json
import math
import os
import re
import sys
import tomllib
from pathlib import Path


def parse_request(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("audio"), str):
        raise ValueError("请求无效")
    audio = Path(payload["audio"])
    if not audio.is_absolute() or not audio.is_file():
        raise ValueError("音频文件不存在")
    language = payload.get("language") or "auto"
    if not isinstance(language, str) or language not in {"zh", "en", "yue", "ja", "ko", "auto"}:
        language = "auto"
    diarize = payload.get("diarize", False)
    if not isinstance(diarize, bool):
        raise ValueError("diarize 必须是布尔值")
    reference = payload.get("reference")
    reference = Path(reference) if isinstance(reference, str) else None
    if reference is not None and (not reference.is_absolute() or not reference.is_file()):
        reference = None
    return audio, language, diarize, reference


def model_paths():
    cache = Path(os.environ.get("MODELSCOPE_CACHE", "~/.cache/modelscope")).expanduser()
    manifest = tomllib.loads(Path(__file__).with_name("pack.toml").read_text())
    result = []
    for model in manifest["models"]:
        candidates = [
            cache / "models" / model["id"].replace("/", "--") / "snapshots" / model["revision"],
            cache / "hub" / model["id"],
            cache / model["id"],
        ]
        path = next((p for p in candidates if all((p / f["path"]).is_file() for f in model["files"])), None)
        if path is None:
            raise ValueError(f"缺少模型 {model['id']}，请运行 twin compute install asr-funasr --download-models")
        result.append(str(path))
    return result


def make_windows(spans):
    total = sum(e - b for b, e in spans)
    hop = max(750, int(total / 6000))
    windows = []
    for i, (b, e) in enumerate(spans):
        if e - b <= 1500:
            windows.append((i, b, e))
            continue
        t = b
        while t < e:
            end = min(t + 1500, e)
            windows.append((i, max(b, end - 1500), end))
            if end >= e:
                break
            t += hop
    return windows, hop, total


def rebuild_spans(windows, found):
    spans, labels = [], []
    for k, (i, b, e) in enumerate(windows):
        label = int(found[k])
        if spans and windows[k - 1][0] == i and labels[-1] == label:
            spans[-1][1] = e
        elif spans and windows[k - 1][0] == i:
            cut = (windows[k - 1][2] + b) // 2 if windows[k - 1][2] > b else b
            spans[-1][1] = cut
            spans.append([cut, e])
            labels.append(label)
        else:
            spans.append([b, e])
            labels.append(label)
    return spans, labels


def organize(spans, labels):
    totals = {}
    for (b, e), label in zip(spans, labels, strict=True):
        totals[label] = totals.get(label, 0) + (e - b) / 1000
    order = sorted(totals, key=lambda k: -totals[k])
    names = {label: f"S{i + 1}" for i, label in enumerate(order)}
    chunks = []
    for (beg, end), label in zip(spans, labels, strict=True):
        if chunks and chunks[-1][2] == label and end - chunks[-1][0] <= 15000 and beg - chunks[-1][1] < 1200:
            chunks[-1][1] = end
        else:
            chunks.append([beg, end, label])
    return totals, order, names, chunks


def similarity(value):
    return round(min(1.0, max(0.0, value)), 3) if value is not None and math.isfinite(value) else None


def emit(payload):
    print(json.dumps(payload, ensure_ascii=False, allow_nan=False), flush=True)


def run(request=None, *, device="cpu", check=False):
    paths = model_paths()
    import librosa
    import numpy as np
    import torch
    from funasr import AutoModel

    torch.set_num_threads(8)

    def load(path, **kwargs):
        return AutoModel(model=path, device=device, disable_update=True, disable_pbar=True, **kwargs)

    vad = load(paths[1], max_end_silence_time=500, max_single_segment_time=30000)
    spk = load(paths[2])
    asr = load(paths[0])

    def embed(clip):
        value = spk.generate(input=clip, disable_pbar=True)[0]["spk_embedding"]
        value = np.asarray(value.detach().cpu() if hasattr(value, "detach") else value, dtype=np.float32).reshape(-1)
        return value / (np.linalg.norm(value) + 1e-9)

    if check:
        wav = (0.01 * np.sin(2 * np.pi * 440 * np.arange(16000) / 16000)).astype(np.float32)
        vad.generate(input=wav, cache={}, disable_pbar=True)
        embedding = embed(wav)
        asr.generate(input=[wav], cache={}, language="zh", use_itn=True, batch_size=1, disable_pbar=True)
        if not np.isfinite(embedding).all() or embedding.size != 192:
            raise ValueError("声纹健康检查失败")
        return {"ok": True, "device": device, "models": 3, "sample_seconds": 1, "embedding_dimensions": 192}

    audio, language, diarize, reference = request
    wav, _ = librosa.load(str(audio), sr=16000, mono=True)
    spans = [list(s) for s in vad.generate(input=wav, cache={}, disable_pbar=True)[0]["value"]]
    labels = [0] * len(spans)
    centroids = {}
    if diarize and spans:
        windows, hop, total = make_windows(spans)
        emb = np.stack([embed(wav[int(b * 16) : int(e * 16)]) for _, b, e in windows])
        if len(windows) >= 2:
            from sklearn.cluster import AgglomerativeClustering

            found = AgglomerativeClustering(
                n_clusters=None, metric="cosine", linkage="average", distance_threshold=0.55
            ).fit_predict(emb)
        else:
            found = np.zeros(len(windows), dtype=int)
        cent = {int(label): emb[found == label].mean(axis=0) for label in set(found)}
        big = [label for label in cent if (found == label).sum() * hop / 1000 >= max(3, total / 100000)] or list(cent)
        for k, label in enumerate(found):
            if int(label) not in big:
                found[k] = max(big, key=lambda b: float(np.dot(emb[k], cent[b])))
        for k in range(1, len(found) - 1):
            if windows[k - 1][0] == windows[k][0] == windows[k + 1][0] and found[k - 1] == found[k + 1] != found[k]:
                found[k] = found[k - 1]
        for label in set(int(x) for x in found):
            mean = emb[found == label].mean(axis=0)
            centroids[label] = mean / (np.linalg.norm(mean) + 1e-9)
        spans, labels = rebuild_spans(windows, found)

    totals, order, names, chunks = organize(spans, labels)
    segments = []
    for i in range(0, len(chunks), 16):
        batch = chunks[i : i + 16]
        clips = [wav[int(b * 16) : int(e * 16)] for b, e, _ in batch]
        results = asr.generate(
            input=clips, cache={}, language=language, use_itn=True, batch_size=len(clips), disable_pbar=True
        )
        for (beg, end, label), result in zip(batch, results, strict=True):
            text = re.sub(r"<\|[^|]*\|>", "", str(result.get("text", ""))).strip()
            if text:
                segments.append(
                    {
                        "start": round(beg / 1000, 2),
                        "end": round(end / 1000, 2),
                        "text": text,
                        **({"speaker": names[label]} if diarize else {}),
                    }
                )
    speakers = []
    if diarize:
        ref = embed(librosa.load(str(reference), sr=16000, mono=True)[0]) if reference and centroids else None
        for label in order:
            value = float(np.dot(ref, centroids[label])) if ref is not None and label in centroids else None
            speakers.append({"id": names[label], "seconds": round(totals[label], 2), "similarity": similarity(value)})
    return {"ok": True, "segments": segments, **({"speakers": speakers} if diarize else {})}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", choices=("cpu", "mps"), default="cpu")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    for key in ("HF_HUB_OFFLINE", "MODELSCOPE_OFFLINE", "TRANSFORMERS_OFFLINE"):
        os.environ[key] = "1"
    os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")
    try:
        request = None if args.check else parse_request(json.loads(sys.stdin.read()))
        # Redirect native library writes as well as Python prints throughout imports/inference.
        sys.stdout.flush()
        saved = os.dup(1)
        try:
            os.dup2(2, 1)
            with contextlib.redirect_stdout(sys.stderr):
                payload = run(request, device=args.device, check=args.check)
        finally:
            os.dup2(saved, 1)
            os.close(saved)
    except Exception as error:
        payload = {"ok": False, "error": str(error)}
    emit(payload)
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
