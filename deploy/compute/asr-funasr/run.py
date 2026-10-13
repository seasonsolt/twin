#!/usr/bin/env python3
"""离线会议转写命令；只在执行请求时导入模型依赖。`--serve` 常驻一个本机 HTTP 服务供 remote.py 调用。"""

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
# Cosine distance at which agglomerative clustering stops merging speaker windows; a larger value merges more.
CLUSTER_THRESHOLD = 0.55


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
    return audio, language, diarize, reference, hotwords, references, parse_cluster_threshold(payload)


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


def parse_hotwords(value):
    """SeACo hotwords: distinct non-blank words without whitespace, in request order."""
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(word, str) for word in value):
        raise ValueError("hotwords 必须是字符串列表")
    words = list(dict.fromkeys(word.strip() for word in value if word.strip() and not re.search(r"\s", word.strip())))
    return words[:MAX_HOTWORDS]


def model_paths():
    cache = Path(os.environ.get("MODELSCOPE_CACHE", "~/.cache/modelscope")).expanduser()
    manifest = tomllib.loads(MANIFEST.read_text())
    result = {}
    for model in manifest["models"]:
        candidates = [
            cache / "models" / model["id"].replace("/", "--") / "snapshots" / model["revision"],
            cache / "hub" / model["id"],
            cache / model["id"],
        ]
        path = next((p for p in candidates if all((p / f["path"]).is_file() for f in model["files"])), None)
        if path is None:
            raise ValueError(f"缺少模型 {model['id']}，请运行 twin compute install asr-funasr --download-models")
        result[model["role"]] = str(path)
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


def report(fraction):
    """Progress for twin on stderr: one `@@twin-progress <0..1>` line per step."""
    os.write(2, f"\n@@twin-progress {min(1.0, max(0.0, fraction)):.4f}\n".encode())


class Engine:
    """The four models, loaded once; `--serve` keeps one Engine resident across requests."""

    def __init__(self, device="auto"):
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

    def embed(self, clip):
        np = self.np
        value = self.spk.generate(input=clip, disable_pbar=True)[0]["spk_embedding"]
        value = np.asarray(value.detach().cpu() if hasattr(value, "detach") else value, dtype=np.float32).reshape(-1)
        return value / (np.linalg.norm(value) + 1e-9)

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
        return {"ok": True, "device": self.device, "models": 4, "sample_seconds": 1, "embedding_dimensions": 192}

    def transcribe(
        self, audio, diarize, reference, hotwords, progress, references=None, cluster_threshold=CLUSTER_THRESHOLD
    ):
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
            cent = {int(label): emb[found == label].mean(axis=0) for label in set(found)}
            floor = max(3, total / 100000)
            big = [label for label in cent if (found == label).sum() * hop / 1000 >= floor] or list(cent)
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
        speakers = []
        if diarize:

            def voice(path):
                return self.embed(librosa.load(str(path), sr=16000, mono=True)[0])

            ref = voice(reference) if reference and centroids else None
            voices = {name: voice(path) for name, path in (references or {}).items()} if centroids else {}
            for label in order:
                value = float(np.dot(ref, centroids[label])) if ref is not None and label in centroids else None
                speaker = {"id": names[label], "seconds": round(totals[label], 2), "similarity": similarity(value)}
                if references:
                    speaker["similarities"] = {
                        name: similarity(float(np.dot(vec, centroids[label])) if label in centroids else None)
                        for name, vec in voices.items()
                    }
                speakers.append(speaker)
        return {"ok": True, "segments": segments, **({"speakers": speakers} if diarize else {})}


def run(request=None, *, device="auto", check=False):
    engine = Engine(device)
    if check:
        return engine.check()
    audio, _language, diarize, reference, hotwords, references, cluster_threshold = request
    return engine.transcribe(audio, diarize, reference, hotwords, report, references, cluster_threshold)


def read_upload(stream, length, directory):
    """Body: one JSON line {language, diarize, hotwords, audio_bytes/suffix, reference_bytes/suffix,
    references: [{name, bytes, suffix}]}, then the files in that order."""
    header = stream.readline(65536)
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
    if "cluster_threshold" in meta:
        request["cluster_threshold"] = meta["cluster_threshold"]
    return parse_request(request)


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
            self.reply(200, {"ok": True, "version": version, "device": engine.device, "busy": busy.locked()})

        def do_POST(self):
            if self.path != "/transcribe":
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
                    audio, _language, diarize, reference, hotwords, references, threshold = read_upload(
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
                        result = engine.transcribe(
                            audio,
                            diarize,
                            reference,
                            hotwords,
                            lambda f: line({"progress": round(f, 4)}),
                            references,
                            threshold,
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
        engine = Engine(args.device)
        sys.stderr.write(f"{json.dumps(engine.check(), ensure_ascii=False)}\n")
        server = make_server(engine, args.host, args.port)
        sys.stderr.write(f"listening on http://{args.host}:{args.port}\n")
        server.serve_forever()
        return 0
    try:
        payload = None if args.check else json.loads(sys.stdin.read())
        if isinstance(payload, dict) and args.cluster_threshold is not None:
            payload.setdefault("cluster_threshold", args.cluster_threshold)
        request = None if payload is None else parse_request(payload)
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
