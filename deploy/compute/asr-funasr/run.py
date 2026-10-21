#!/usr/bin/env python3
"""离线会议转写命令；只在执行请求时导入模型依赖。`--serve` 常驻一个本机 HTTP 服务供 remote.py 调用。

请求带 `"embed": true` 时只计算整段音频的声纹（用于本人声音），不转写；
再带 `"spans"` 时按段各算一个声纹（用于复核已确认的说话人）。

1.4 起在 CUDA 上默认走重叠感知转写（overlap.py：允许两人同时说话的分人、重叠处分离、FireRedASR2 识别），
需要 pack.toml 的 `cuda_models` 齐全；Mac、CPU 或缺模型时仍走 1.3 的流程。`--pipeline` 可指定，
请求里的 `"pipeline": "classic"` 让重叠感知的服务按 1.3 流程处理这一个请求（评测用，twin 自己从不传）。"""

import argparse
import contextlib
import json
import math
import os
import re
import shutil
import sys
import tempfile
import threading
import tomllib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

MANIFEST = Path(__file__).with_name("pack.toml")
MAX_HOTWORDS = 200
MAX_REFERENCES = 32
# Embedding by spans: at most this many clips per request, each of at most this many (start, end) parts in seconds.
MAX_SPANS = 20000
MAX_SPAN_PARTS = 64
MAX_HEADER = 4 << 20
# Cosine distance at which agglomerative clustering stops merging speaker windows; a larger value merges more.
# 0.65 from the AliMeeting sweep in docs/ASR_EVAL.md: 0.55 split each person into several speakers, 0.75 merged people.
CLUSTER_THRESHOLD = 0.65
# A cluster under the size floor joins the nearest big cluster only when the cosine between their centroids is at
# least MERGE_SIMILARITY - 0.2 / (its window count) and leads the next big cluster by MERGE_LEAD; otherwise it stays
# its own (short) speaker. A single 1.5 s window is a noisy centroid, hence the allowance. Before 1.3.1 every small
# cluster was merged, which on AliMeeting put 21% of a person who spoke ~10 s into someone else's speaker, and in a
# long meeting let one generic centroid collect dozens of short clusters; see docs/ASR_EVAL.md.
MERGE_SIMILARITY = 0.5
MERGE_LEAD = 0.05
# "classic": VAD, CAM++ clustering, Paraformer (1.3); "overlap": overlap.py (1.4, CUDA only).
PIPELINES = ("classic", "overlap")


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
    hotwords, references = parse_hotwords(payload.get("hotwords")), parse_references(payload)
    pipeline = payload.get("pipeline")
    if pipeline is not None and pipeline not in PIPELINES:
        raise ValueError(f"pipeline 只能是 {' / '.join(PIPELINES)}")
    return audio, language, diarize, reference, hotwords, references, parse_cluster_threshold(payload), pipeline


def parse_cluster_threshold(payload):
    """Optional clustering distance for benchmarks; twin itself never sends it."""
    value = payload.get("cluster_threshold", CLUSTER_THRESHOLD)
    if isinstance(value, bool) or not isinstance(value, int | float) or not 0.1 <= value <= 0.95:
        raise ValueError("cluster_threshold 必须是 0.1–0.95 之间的数")
    return float(value)


def parse_references(payload):
    """Optional {name: absolute voice path}: every speaker is compared with each voice in one run. Like `reference`,
    a voice that is missing is skipped rather than failing the job."""
    value = payload.get("references")
    if value is None:
        return {}
    if not isinstance(value, dict) or len(value) > MAX_REFERENCES:
        raise ValueError(f"references 必须是最多 {MAX_REFERENCES} 项的 {{名称: 路径}}")
    result = {}
    for name, path in value.items():
        if not isinstance(name, str) or not 0 < len(name) <= 80 or not isinstance(path, str):
            raise ValueError("references 的名称和路径必须是字符串")
        if Path(path).is_absolute() and Path(path).is_file():
            result[name] = Path(path)
    return result


def parse_spans(payload):
    """Optional clips to embed one by one: [[[start, end], ...], ...] in seconds; a clip's parts are joined."""
    value = payload.get("spans")
    if value is None:
        return None
    if not isinstance(value, list) or len(value) > MAX_SPANS:
        raise ValueError(f"spans 必须是最多 {MAX_SPANS} 项的列表")
    result = []
    for clip in value:
        if not isinstance(clip, list) or not 0 < len(clip) <= MAX_SPAN_PARTS:
            raise ValueError(f"spans 的每一项必须是 1–{MAX_SPAN_PARTS} 段 [开始, 结束]")
        parts = []
        for part in clip:
            if (
                not isinstance(part, list)
                or len(part) != 2
                or not all(isinstance(x, int | float) and not isinstance(x, bool) and math.isfinite(x) for x in part)
                or not 0 <= part[0] < part[1]
            ):
                raise ValueError("spans 的每段必须是 [开始, 结束]（秒，开始小于结束）")
            parts.append((float(part[0]), float(part[1])))
        result.append(parts)
    return result


def parse_hotwords(value):
    """SeACo hotwords: distinct non-blank words without whitespace, in request order."""
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(word, str) for word in value):
        raise ValueError("hotwords 必须是字符串列表")
    words = list(dict.fromkeys(word.strip() for word in value if word.strip() and not re.search(r"\s", word.strip())))
    return words[:MAX_HOTWORDS]


# Threads computing voiceprints of stretches at once on CUDA (``Engine.embedding``).
EMBED_THREADS = 8


def model_directory(model):
    """Where a manifest model's files are, or None: ModelScope cache layouts under MODELSCOPE_CACHE, and for models
    from Hugging Face also the hub cache under HF_HOME; every file must be there with its listed size."""
    cache = Path(os.environ.get("MODELSCOPE_CACHE", "~/.cache/modelscope")).expanduser()
    candidates = [
        cache / "models" / model["id"].replace("/", "--") / "snapshots" / model["revision"],
        cache / "hub" / model["id"],
        cache / model["id"],
    ]
    if model.get("source") == "huggingface":
        hub = Path(os.environ.get("HF_HOME", "~/.cache/huggingface")).expanduser() / "hub"
        candidates.append(hub / f"models--{model['id'].replace('/', '--')}" / "snapshots" / model["revision"])
    return next(
        (
            p
            for p in candidates
            if all((p / f["path"]).is_file() and (p / f["path"]).stat().st_size == f["size"] for f in model["files"])
        ),
        None,
    )


def model_paths():
    manifest = tomllib.loads(MANIFEST.read_text())
    result = {}
    for model in manifest["models"]:
        path = model_directory(model)
        if path is None:
            raise ValueError(f"缺少模型 {model['id']}，请运行 twin compute install asr-funasr --download-models")
        result[model["role"]] = str(path)
    return result


def overlap_paths():
    """Role → path of the overlap-aware path's models (a file when the model lists one, else its directory), or None
    when one is missing; the bundled segmentation weights are checked against their sha256."""
    import hashlib

    manifest = tomllib.loads(MANIFEST.read_text())
    result = {}
    for model in manifest.get("cuda_models", []):
        path = model_directory(model)
        if path is None:
            return None
        main = model.get("main")
        result[model["role"]] = path / main if main else path
    for weight in manifest.get("bundled", []):
        path = MANIFEST.parent / weight["path"]
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != weight["sha256"]:
            raise ValueError(f"算力包自带的 {weight['path']} 缺失或校验失败，请重新安装")
        result[weight["role"]] = path
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


def absorb(found, emb, big, similarity=MERGE_SIMILARITY, lead=MERGE_LEAD):
    """Relabel each cluster outside `big` as the big cluster its centroid is closest to, when close enough and
    clearly closer than to the runner-up; `emb` rows are unit voiceprints. Returns the new labels."""
    import numpy as np

    found = np.asarray(found).copy()
    labels = [int(label) for label in dict.fromkeys(found.tolist())]
    cent = {}
    for label in labels:
        mean = emb[found == label].mean(axis=0)
        cent[label] = mean / (np.linalg.norm(mean) + 1e-9)
    for label in labels:
        if label in big:
            continue
        ranked = sorted(((float(np.dot(cent[label], cent[b])), b) for b in big), reverse=True)
        runner_up = ranked[1][0] if len(ranked) > 1 else -1.0
        size = int((found == label).sum())
        if ranked and ranked[0][0] >= similarity - 0.2 / size and ranked[0][0] - runner_up >= lead:
            found[found == label] = ranked[0][1]
    return found


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


def vector(value):
    """A unit voiceprint as JSON; twin keeps each speaker's so a new reference voice is compared without re-running."""
    return [round(float(x), 6) for x in value]


def emit(payload):
    print(json.dumps(payload, ensure_ascii=False, allow_nan=False), flush=True)


def report(fraction):
    """Progress for twin on stderr: one `@@twin-progress <0..1>` line per step."""
    os.write(2, f"\n@@twin-progress {min(1.0, max(0.0, fraction)):.4f}\n".encode())


class Engine:
    """The four models, loaded once; `--serve` keeps one Engine resident across requests."""

    def __init__(self, device="auto", pipeline="auto"):
        paths = model_paths()
        os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
        import numpy as np
        import torch
        from funasr import AutoModel

        self.np, self.torch = np, torch
        torch.set_num_threads(8)
        if device == "auto":
            device = "cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu"

        def load(path, on=None, **kwargs):
            return AutoModel(model=path, device=on or device, disable_update=True, disable_pbar=True, **kwargs)

        # Measured on Apple silicon (49 min meeting): FSMN VAD takes 8 s on CPU but 93 s on MPS; Paraformer and
        # same-length CAM++ batches are several times faster on MPS; padded CPU batches are ~3x slower than single
        # clips. GPU and CPU give the same text, so a GPU that fails to load falls back to CPU.
        self.vad = load(paths["vad"], "cpu", max_end_silence_time=500, max_single_segment_time=30000)
        self.spk = load(paths["speaker"], "cpu")
        try:
            self.asr = load(paths["asr"])
            self.punc = load(paths["punc"])
            self.spk_batch = load(paths["speaker"]) if device != "cpu" else None
        except Exception:
            if device == "cpu":
                raise
            device = "cpu"
            self.asr = load(paths["asr"])
            self.punc = load(paths["punc"])
            self.spk_batch = None
        self.device = device
        self.batch = 16 if device != "cpu" else 1
        extra = overlap_paths() if pipeline != "classic" and device == "cuda" else None
        if pipeline == "overlap" and extra is None:
            raise ValueError("重叠感知转写需要 CUDA 和 pack.toml 里 cuda_models 列出的模型")
        self.overlap = None
        if extra is not None:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            import overlap

            self.overlap = overlap.Overlap(self, extra, paths["vad"])
        self.pipeline = "overlap" if self.overlap else "classic"

    def embed(self, clip):
        np = self.np
        value = self.spk.generate(input=clip, disable_pbar=True)[0]["spk_embedding"]
        value = np.asarray(value.detach().cpu() if hasattr(value, "detach") else value, dtype=np.float32).reshape(-1)
        return value / (np.linalg.norm(value) + 1e-9)

    def voice(self, path):
        import librosa

        return self.embed(librosa.load(str(path), sr=16000, mono=True)[0])

    def embedding(self, audio, spans=None):
        if spans is None:
            return {"ok": True, "embedding": vector(self.voice(audio))}
        import librosa

        np = self.np
        wav = librosa.load(str(audio), sr=16000, mono=True)[0]
        clips = [np.concatenate([wav[int(b * 16000) : int(e * 16000)] for b, e in parts]) for parts in spans]
        # A clip past the end of the audio, or too short for CAM++ to look at, has no voiceprint.
        wanted = [k for k, clip in enumerate(clips) if len(clip) >= 1600]
        found = [None] * len(clips)
        if self.device == "cuda" and self.spk_batch is not None:
            # Clips differ in length and padding would change their voiceprints, so each is its own call; one by one
            # most of a call is launching small kernels, so several threads keep the GPU busy (3x on a 4090, the
            # same voiceprints). The model's own inference holds no state; AutoModel.generate rewrites shared kwargs.
            from concurrent.futures import ThreadPoolExecutor

            with ThreadPoolExecutor(EMBED_THREADS) as pool:
                for k, value in zip(wanted, pool.map(lambda k: self.embed_gpu(clips[k]), wanted), strict=True):
                    found[k] = vector(value)
        else:
            # MPS stays on CPU, where every new clip length would cost it a fresh graph.
            with self.torch.no_grad():
                for k in wanted:
                    found[k] = vector(self.embed(clips[k]))
        return {"ok": True, "embeddings": found}

    def embed_gpu(self, clip):
        np, torch = self.np, self.torch
        with torch.no_grad():  # per thread: grad mode is thread-local
            found, _ = self.spk_batch.model.inference(data_in=[torch.from_numpy(clip)], device=self.device)
        row = found[0]["spk_embedding"].detach().cpu().numpy().astype(np.float32).reshape(-1)
        return row / (np.linalg.norm(row) + 1e-9)

    def embed_all(self, clips, done):
        # Equal-length groups avoid zero padding, so batched embeddings match single-clip ones. Small groups stay
        # on CPU: every new clip length costs MPS a fresh graph, which outweighs the batch for a handful of clips.
        np, torch = self.np, self.torch
        result = [None] * len(clips)
        groups = {}
        for k, clip in enumerate(clips):
            groups.setdefault(len(clip), []).append(k)
        finished = 0
        with torch.no_grad():
            for members in groups.values():
                if self.spk_batch is None or len(members) < 8:
                    for k in members:
                        result[k] = self.embed(clips[k])
                        finished += 1
                        if finished % 50 == 0:
                            done(finished / len(clips))
                    continue
                for i in range(0, len(members), 64):
                    part = members[i : i + 64]
                    found, _ = self.spk_batch.model.inference(
                        data_in=[torch.from_numpy(clips[k]) for k in part], device=self.device
                    )
                    rows = found[0]["spk_embedding"].detach().cpu().numpy().astype(np.float32)
                    for k, row in zip(part, rows, strict=True):
                        result[k] = row / (np.linalg.norm(row) + 1e-9)
                    finished += len(part)
                    done(finished / len(clips))
        return np.stack(result)

    def recognize(self, clips, hotwords):
        options = {"hotword": " ".join(hotwords)} if hotwords else {}
        results = self.asr.generate(input=clips, cache={}, batch_size=len(clips), disable_pbar=True, **options)
        texts = []
        for result in results:
            text = str(result.get("text", "")).strip()
            texts.append(str(self.punc.generate(input=text, disable_pbar=True)[0]["text"]).strip() if text else "")
        return texts

    def check(self):
        np = self.np
        wav = (0.01 * np.sin(2 * np.pi * 440 * np.arange(16000) / 16000)).astype(np.float32)
        self.vad.generate(input=wav, cache={}, disable_pbar=True)
        embedding = self.embed(wav)
        self.recognize([wav], ["转写"])
        self.punc.generate(input="今天开会讨论转写", disable_pbar=True)
        if not np.isfinite(embedding).all() or embedding.size != 192:
            raise ValueError("声纹健康检查失败")
        if self.spk_batch is not None:
            batched = self.embed_all([wav] * 8, lambda _: None)
            if not np.allclose(batched[0], embedding, atol=1e-3):
                raise ValueError("声纹批量健康检查失败")
        models = 4
        if self.overlap is not None:
            self.overlap.diarizer(wav)
            streams = self.overlap.separate(wav)
            self.overlap.recognize([wav], [])
            if len(streams) != 2 or not all(np.isfinite(s).all() and len(s) == len(wav) for s in streams):
                raise ValueError("分离健康检查失败")
            models = 8
        return {
            "ok": True,
            "device": self.device,
            "pipeline": self.pipeline,
            "models": models,
            "sample_seconds": 1,
            "embedding_dimensions": 192,
        }

    def describe(self, order, names, totals, centroids, reference, references):
        """The speakers list of a result: time, similarity to the reference voice(s) and unit voiceprint."""
        np = self.np
        ref = self.voice(reference) if reference and centroids else None
        voices = {name: self.voice(path) for name, path in (references or {}).items()} if centroids else {}
        speakers = []
        for label in order:
            value = float(np.dot(ref, centroids[label])) if ref is not None and label in centroids else None
            speaker = {"id": names[label], "seconds": round(totals[label], 2), "similarity": similarity(value)}
            if label in centroids:
                speaker["embedding"] = vector(centroids[label])
            if references:
                speaker["similarities"] = {
                    name: similarity(float(np.dot(vec, centroids[label])) if label in centroids else None)
                    for name, vec in voices.items()
                }
            speakers.append(speaker)
        return speakers

    def transcribe(
        self,
        audio,
        diarize,
        reference,
        hotwords,
        progress,
        references=None,
        cluster_threshold=CLUSTER_THRESHOLD,
        pipeline=None,
    ):
        """The transcript, saying which pack version and pipeline made it (1.4.1+), so twin knows what a newer one
        would transcribe again."""
        if self.overlap is not None and pipeline != "classic":
            result = self.overlap.transcribe(audio, diarize, reference, hotwords, progress, references)
            used = "overlap"
        elif pipeline == "overlap":
            raise ValueError("这台服务没有加载重叠感知转写")
        else:
            result = self.classic(audio, diarize, reference, hotwords, progress, references, cluster_threshold)
            used = "classic"
        return {**result, "version": tomllib.loads(MANIFEST.read_text())["version"], "pipeline": used}

    def classic(self, audio, diarize, reference, hotwords, progress, references, cluster_threshold):
        import librosa

        np = self.np
        wav, _ = librosa.load(str(audio), sr=16000, mono=True)
        spans = [list(s) for s in self.vad.generate(input=wav, cache={}, disable_pbar=True)[0]["value"]]
        progress(0.05)
        labels = [0] * len(spans)
        centroids = {}
        if diarize and spans:
            windows, hop, total = make_windows(spans)
            clips = [wav[int(b * 16) : int(e * 16)] for _, b, e in windows]
            emb = self.embed_all(clips, lambda f: progress(0.05 + 0.15 * f))
            if len(windows) >= 2:
                from sklearn.cluster import AgglomerativeClustering

                found = AgglomerativeClustering(
                    n_clusters=None, metric="cosine", linkage="average", distance_threshold=cluster_threshold
                ).fit_predict(emb)
            else:
                found = np.zeros(len(windows), dtype=int)
            floor = max(3, total / 100000)
            sizes = {int(label): int((found == label).sum()) for label in set(found)}
            big = {label for label, n in sizes.items() if n * hop / 1000 >= floor} or set(sizes)
            found = absorb(found, emb, big)
            for k in range(1, len(found) - 1):
                if windows[k - 1][0] == windows[k][0] == windows[k + 1][0] and found[k - 1] == found[k + 1] != found[k]:
                    found[k] = found[k - 1]
            for label in set(int(x) for x in found):
                mean = emb[found == label].mean(axis=0)
                centroids[label] = mean / (np.linalg.norm(mean) + 1e-9)
            spans, labels = rebuild_spans(windows, found)

        totals, order, names, chunks = organize(spans, labels)
        segments = []
        progress(0.2)
        for i in range(0, len(chunks), self.batch):
            part = chunks[i : i + self.batch]
            texts = self.recognize([wav[int(b * 16) : int(e * 16)] for b, e, _ in part], hotwords)
            progress(0.2 + 0.8 * (i + len(part)) / len(chunks))
            for (beg, end, label), text in zip(part, texts, strict=True):
                if text:
                    segments.append(
                        {
                            "start": round(beg / 1000, 2),
                            "end": round(end / 1000, 2),
                            "text": text,
                            **({"speaker": names[label]} if diarize else {}),
                        }
                    )
        speakers = self.describe(order, names, totals, centroids, reference, references) if diarize else []
        return {"ok": True, "segments": segments, **({"speakers": speakers} if diarize else {})}


def run(request=None, *, device="auto", pipeline="auto", check=False, embed=False, spans=None):
    engine = Engine(device, pipeline)
    if check:
        return engine.check()
    audio, _language, diarize, reference, hotwords, references, cluster_threshold, chosen = request
    if embed:
        return engine.embedding(audio) if spans is None else engine.embedding(audio, spans)
    return engine.transcribe(audio, diarize, reference, hotwords, report, references, cluster_threshold, chosen)


def read_upload(stream, length, directory):
    """Body: one JSON line {language, diarize, hotwords, spans, audio_bytes/suffix, reference_bytes/suffix,
    references: [{name, bytes, suffix}]}, then the files in that order. Returns ``parse_request``'s values and the
    spans to embed (``parse_spans``)."""
    # Spans to embed make the header long: a two-hour meeting has a few thousand.
    header = stream.readline(MAX_HEADER)
    if not header.endswith(b"\n"):
        raise ValueError("请求无效")
    meta = json.loads(header)
    if not isinstance(meta, dict):
        raise ValueError("请求无效")
    extra = meta.get("references", [])
    if not isinstance(extra, list) or len(extra) > MAX_REFERENCES or not all(isinstance(r, dict) for r in extra):
        raise ValueError("请求无效")
    files = [("audio", meta.get("audio_bytes"), meta.get("audio_suffix"))]
    files.append(("reference", meta.get("reference_bytes", 0), meta.get("reference_suffix")))
    files += [(f"voice-{k}", r.get("bytes"), r.get("suffix")) for k, r in enumerate(extra)]
    sizes = [size for _, size, _ in files]
    if not all(isinstance(n, int) and not isinstance(n, bool) and n >= 0 for n in sizes) or not sizes[0]:
        raise ValueError("请求无效")
    if not all(sizes[2:]):
        raise ValueError("请求无效")
    if len(header) + sum(sizes) != length:
        raise ValueError("请求长度不符")
    paths = {}
    for name, size, suffix in files:
        if not size:
            continue
        # Keep the extension: decoders pick the container format from it.
        suffix = suffix or ""
        if not isinstance(suffix, str) or not re.fullmatch(r"(\.[A-Za-z0-9]{1,8})?", suffix):
            raise ValueError("请求无效")
        path = Path(directory) / (name + suffix.lower())
        with path.open("wb") as out:
            remaining = size
            while remaining:
                block = stream.read(min(remaining, 1 << 20))
                if not block:
                    raise ValueError("请求不完整")
                out.write(block)
                remaining -= len(block)
        paths[name] = path
    request = {"audio": str(paths["audio"]), "language": meta.get("language"), "diarize": meta.get("diarize", False)}
    if "reference" in paths:
        request["reference"] = str(paths["reference"])
    if extra:
        request["references"] = {r.get("name"): str(paths[f"voice-{k}"]) for k, r in enumerate(extra)}
        if len(request["references"]) != len(extra):
            raise ValueError("references 名称重复")
    if "hotwords" in meta:
        request["hotwords"] = meta["hotwords"]
    for key in ("cluster_threshold", "pipeline"):
        if key in meta:
            request[key] = meta[key]
    return (*parse_request(request), parse_spans(meta))


def make_server(engine, host, port, *, max_bytes=4 << 30):
    """One job at a time on the resident engine; the response streams NDJSON progress lines, then the result."""
    version = tomllib.loads(MANIFEST.read_text())["version"]
    busy = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            sys.stderr.write(f"{self.address_string()} {format % args}\n")

        def reply(self, status, payload):
            body = (json.dumps(payload, ensure_ascii=False) + "\n").encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path != "/health":
                return self.reply(404, {"ok": False, "error": "not found"})
            self.reply(
                200,
                {
                    "ok": True,
                    "version": version,
                    "device": engine.device,
                    "pipeline": engine.pipeline,
                    "busy": busy.locked(),
                },
            )

        def do_POST(self):
            if self.path not in {"/transcribe", "/embed"}:
                return self.reply(404, {"ok": False, "error": "not found"})
            try:
                length = int(self.headers.get("Content-Length", ""))
            except ValueError:
                return self.reply(411, {"ok": False, "error": "缺少请求长度"})
            if not 0 < length <= max_bytes:
                return self.reply(413, {"ok": False, "error": "音频超过大小限制"})
            directory = tempfile.mkdtemp(prefix="twin-asr-")
            try:
                try:
                    audio, _language, diarize, reference, hotwords, references, threshold, chosen, spans = read_upload(
                        self.rfile, length, directory
                    )
                except (ValueError, UnicodeDecodeError) as error:
                    return self.reply(400, {"ok": False, "error": str(error)})
                self.send_response(200)
                self.send_header("Content-Type", "application/x-ndjson")
                self.end_headers()

                def line(payload):
                    self.wfile.write((json.dumps(payload, ensure_ascii=False, allow_nan=False) + "\n").encode())
                    self.wfile.flush()

                line({"queued": busy.locked()})
                with busy:
                    try:
                        if self.path == "/embed":
                            result = engine.embedding(audio) if spans is None else engine.embedding(audio, spans)
                        else:
                            result = engine.transcribe(
                                audio,
                                diarize,
                                reference,
                                hotwords,
                                lambda f: line({"progress": round(f, 4)}),
                                references,
                                threshold,
                                chosen,
                            )
                    except (BrokenPipeError, ConnectionResetError):
                        raise
                    except Exception as error:
                        result = {"ok": False, "error": str(error) or type(error).__name__}
                line({"result": result})
            except (BrokenPipeError, ConnectionResetError):
                sys.stderr.write("client went away; job abandoned\n")
            finally:
                shutil.rmtree(directory, ignore_errors=True)

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", choices=("auto", "cpu", "mps", "cuda"), default="auto")
    parser.add_argument(
        "--pipeline", choices=("auto", *PIPELINES), default="auto", help="auto：CUDA 且模型齐全时用 overlap"
    )
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--serve", action="store_true", help="常驻服务：加载一次模型，经 HTTP 处理请求")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18790)
    parser.add_argument(
        "--cluster-threshold", type=float, help=f"评测用：声纹聚类距离阈值（默认 {CLUSTER_THRESHOLD}），请求可覆盖"
    )
    args = parser.parse_args()
    for key in ("HF_HUB_OFFLINE", "MODELSCOPE_OFFLINE", "TRANSFORMERS_OFFLINE"):
        os.environ[key] = "1"
    if args.device == "cpu":
        os.environ["CUDA_VISIBLE_DEVICES"] = ""
    if args.serve:
        engine = Engine(args.device, args.pipeline)
        sys.stderr.write(f"{json.dumps(engine.check(), ensure_ascii=False)}\n")
        server = make_server(engine, args.host, args.port)
        sys.stderr.write(f"listening on http://{args.host}:{args.port}\n")
        server.serve_forever()
        return 0
    embed = False
    try:
        payload = None if args.check else json.loads(sys.stdin.read())
        if isinstance(payload, dict) and args.cluster_threshold is not None:
            payload.setdefault("cluster_threshold", args.cluster_threshold)
        request = None if payload is None else parse_request(payload)
        embed = isinstance(payload, dict) and payload.get("embed") is True
        spans = parse_spans(payload) if embed else None
        # Redirect native library writes as well as Python prints throughout imports/inference.
        sys.stdout.flush()
        saved = os.dup(1)
        try:
            os.dup2(2, 1)
            with contextlib.redirect_stdout(sys.stderr):
                payload = run(
                    request, device=args.device, pipeline=args.pipeline, check=args.check, embed=embed, spans=spans
                )
        finally:
            os.dup2(saved, 1)
            os.close(saved)
    except Exception as error:
        payload = {"ok": False, "error": str(error)}
    emit(payload)
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
