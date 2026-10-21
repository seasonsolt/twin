"""评测用的重叠感知转写：pyannote 分人（允许同时说话），重叠处用 MossFormer2 分离，每人只转写自己的声音。

由 climb.py 的 `pyannote` 配置项接入，替换算力包 run.py 的 `Engine.transcribe`；返回格式与 run.py 相同，
所以 remote.py 和 eval-asr-session 不用改。流程：

1. 响度归一（climb.gain_for，默认 −27 dBFS）后的音频用于声纹、分离和识别；pyannote 用原始音频。
2. pyannote speaker-diarization-community-1 给出每人的发言段，段与段可以重叠。完全落在别人发言段里、又短于
   `drop_enclosed` 秒的段去掉：AliMeeting 上这类段约三成在参考标注里没有人说话，分离后那一路其实是别人的声音。
3. 同时有两人以上说话的时段是重叠区，每区取说话最久的两人，用 MossFormer2 把这一区（前后各带 `context` 秒）
   分成两路。两路分给谁按“分离域”声纹：每人取几段 3 秒单人语音过同一个分离器，取能量大的一路求均值。
   混合音上的质心不能用：分离后的 1.5 秒声纹与它的相似度普遍低于 0.4。
4. 每人的发言段按 run.organize 的规则合成不超过 15 秒的块；块里不属于此人的时段静音，重叠区换成此人那一路。
5. 识别用 Engine.recognize（可被 climb.py 的 firered 换成 FireRedASR2）。认领用的声纹只取单人时段的 1.5 秒窗口，
   与 run.py 的说话人质心同一算法。

依赖（只在评测环境装）：pyannote.audio 4.x 与本地模型目录、clearvoice（MossFormer2_SS_16K，从含 checkpoints/ 的
目录启动）。
"""

import math
import sys

import numpy as np

SAMPLE_RATE = 16000
FRAME = 0.01  # seconds per activity frame


def _unit(vector):
    return vector / (np.linalg.norm(vector) + 1e-9)


def drop_enclosed(turns, shorter_than):
    """Turns (start, end, speaker) without the short ones lying wholly inside another speaker's turn."""
    if not shorter_than:
        return list(turns)
    return [
        (b, e, x)
        for b, e, x in turns
        if e - b >= shorter_than or not any(y != x and yb <= b and e <= ye for yb, ye, y in turns)
    ]


def chunks(turns, longest=15.0, gap=1.2):
    """Consecutive same-speaker turns joined like run.organize (gap under `gap` s, up to `longest` s); longer ones
    split evenly. A turn of someone else starting in between ends the chunk, even when it overlaps."""
    merged = []
    for b, e, s in sorted(turns):
        if merged and merged[-1][2] == s and b - merged[-1][1] < gap and e - merged[-1][0] <= longest:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([b, e, s])
    result = []
    for b, e, s in merged:
        n = max(1, math.ceil((e - b) / longest))
        result += [(b + (e - b) * j / n, b + (e - b) * (j + 1) / n, s) for j in range(n)]
    return result


def activity(turns, speakers, frames):
    """Boolean (speaker, frame) matrix at FRAME resolution."""
    act = np.zeros((len(speakers), frames), bool)
    for b, e, x in turns:
        act[speakers.index(x), int(b / FRAME) : int(e / FRAME)] = True
    return act


def overlap_regions(act, speakers, shortest=0.0):
    """Runs of frames with two or more speakers; each gets the two speakers active the longest within it."""
    count = act.sum(axis=0)
    regions, f, n = [], 0, act.shape[1]
    while f < n:
        if count[f] < 2:
            f += 1
            continue
        g = f
        while g < n and count[g] >= 2:
            g += 1
        if (g - f) * FRAME >= shortest:
            on = act[:, f:g].sum(axis=1)
            regions.append({"start": f * FRAME, "end": g * FRAME, "pair": [speakers[i] for i in np.argsort(-on)[:2]]})
        f = g
    return regions


def speaker_audio(wav, start, end, speaker, act_row, regions, fade=0.02, pad=0.1):
    """One chunk of a speaker's own audio: the mixture where only they talk, their separated stream in overlaps,
    silence where they do not talk (a merged chunk can span someone else's short turn)."""
    b16, e16 = int(start * SAMPLE_RATE), int(end * SAMPLE_RATE)
    audio = wav[b16:e16].astype(np.float32).copy()
    for r in regions:
        if speaker not in r.get("audio", {}) or r["end"] <= start or end <= r["start"]:
            continue
        rb, re_ = max(start, r["start"]), min(end, r["end"])
        src = r["audio"][speaker][int((rb - r["start"]) * SAMPLE_RATE) : int((re_ - r["start"]) * SAMPLE_RATE)]
        offset = int((rb - start) * SAMPLE_RATE)
        src = src[: len(audio) - offset]
        k = min(int(fade * SAMPLE_RATE), len(src) // 4)
        ramp = np.ones(len(src), np.float32)
        if k and rb > start:
            ramp[:k] = np.linspace(0, 1, k)
        if k and re_ < end:
            ramp[-k:] = np.linspace(1, 0, k)
        audio[offset : offset + len(src)] = ramp * src + (1 - ramp) * audio[offset : offset + len(src)]
    mine = act_row[int(start / FRAME) : int(start / FRAME) + len(audio) // 160 + 1]
    grown = np.zeros(len(mine), bool)
    reach = int(pad / FRAME)
    for q in np.flatnonzero(mine):
        grown[max(0, q - reach) : q + reach + 1] = True
    gain = np.repeat(grown.astype(np.float32), 160)[: len(audio)]
    if len(gain) < len(audio):
        gain = np.pad(gain, (0, len(audio) - len(gain)), constant_values=1.0)
    k = int(fade * SAMPLE_RATE)
    if k:
        gain = np.convolve(gain, np.ones(k, np.float32) / k, mode="same")
    return audio * gain


def combine(run, config, gain_for):
    """Replace run.Engine.transcribe with the overlap-aware pipeline described in the module docstring."""
    import torch

    model_dir = config["model"]
    params = config.get("params") or {}
    enclosed = config.get("drop_enclosed", 0.5)
    context = config.get("context", 0.5)
    probes = config.get("probes", 10)
    target = config.get("gain_target", -27)
    original_init = run.Engine.__init__

    def __init__(self, device="auto"):
        original_init(self, device)
        from clearvoice import ClearVoice
        from pyannote.audio import Pipeline

        if config.get("mem_gb") and torch.cuda.is_available():
            # The GPU is shared with production services: cap this process instead of growing into their memory.
            total = torch.cuda.get_device_properties(0).total_memory
            torch.cuda.set_per_process_memory_fraction(min(1.0, config["mem_gb"] * 2**30 / total))
        pipeline = Pipeline.from_pretrained(str(model_dir))
        if params:
            merged = pipeline.parameters(instantiated=True)
            for key, value in params.items():
                merged[key].update(value)
            pipeline.instantiate(merged)
        self.diarizer = pipeline.to(torch.device(self.device if self.device != "mps" else "cpu"))
        self.separator = ClearVoice(task="speech_separation", model_names=["MossFormer2_SS_16K"]).models[0]
        self.separator.model.eval()

    def separate(self, clip):
        streams = [np.zeros_like(clip), np.zeros_like(clip)]
        with torch.inference_mode():
            for b in range(0, len(clip), 10 * SAMPLE_RATE):
                piece = clip[b : b + 10 * SAMPLE_RATE]
                found = self.separator.model(torch.from_numpy(piece[None]).to(self.separator.device))
                for j in range(2):
                    streams[j][b : b + len(piece)] = found[j][0, : len(piece)].float().cpu().numpy()
        return streams

    def transcribe(self, audio, diarize, reference, hotwords, progress, references=None, cluster_threshold=None):
        import librosa

        raw = librosa.load(str(audio), sr=SAMPLE_RATE, mono=True)[0]
        wav = (raw * gain_for(raw, {"target": target})).astype(np.float32)
        found = self.diarizer({"waveform": torch.from_numpy(raw[None]), "sample_rate": SAMPLE_RATE})
        turns = [
            (float(t.start), float(t.end), str(x)) for t, _, x in found.speaker_diarization.itertracks(yield_label=True)
        ]
        turns = drop_enclosed(turns, enclosed)
        progress(0.15)
        speakers = sorted({x for _, _, x in turns})
        act = activity(turns, speakers, len(wav) // 160 + 1)
        alone = act & (act.sum(axis=0) == 1)
        separated, centroids = {}, {}
        for i, x in enumerate(speakers):
            idx = np.flatnonzero(alone[i])
            runs = np.split(idx, np.flatnonzero(np.diff(idx) != 1) + 1) if len(idx) else []
            longest = sorted((r for r in runs if len(r) >= 150), key=len, reverse=True)[:probes]
            vectors = []
            for r in longest:
                streams = self.separate(wav[int(r[0] * 160) : int(r[0] * 160) + 3 * SAMPLE_RATE])
                louder = streams[int(np.argmax([np.mean(s**2) for s in streams]))]
                vectors.append(
                    self.embed_gpu(louder.astype(np.float32)) if self.device == "cuda" else self.embed(louder)
                )
            if vectors:
                separated[x] = _unit(np.mean(vectors, axis=0))
            windows = []
            for r in runs:
                t = int(r[0])
                while t + 50 <= r[-1] + 1:
                    windows.append(wav[t * 160 : min(int(r[-1]) + 1, t + 150) * 160])
                    t += 75
            if windows:
                centroids[x] = _unit(self.embed_all(windows, lambda f: None).mean(axis=0))
        progress(0.3)
        regions = overlap_regions(act, speakers)
        pad = int(context * SAMPLE_RATE)
        for k, r in enumerate(regions):
            b16, e16 = int(r["start"] * SAMPLE_RATE), int(r["end"] * SAMPLE_RATE)
            lo, hi = max(0, b16 - pad), min(len(wav), e16 + pad)
            streams = [s[b16 - lo : e16 - lo] for s in self.separate(wav[lo:hi])]
            a, c = r["pair"]
            if a in separated and c in separated and e16 - b16 >= 1600:
                v = [self.embed_gpu(s.astype(np.float32)) if self.device == "cuda" else self.embed(s) for s in streams]
                keep = v[0] @ separated[a] + v[1] @ separated[c] >= v[0] @ separated[c] + v[1] @ separated[a]
            else:  # too short to compare voices: the louder stream goes to whoever talks longer here
                keep = np.mean(streams[0] ** 2) >= np.mean(streams[1] ** 2)
            r["audio"] = {a: streams[0], c: streams[1]} if keep else {a: streams[1], c: streams[0]}
            progress(0.3 + 0.3 * (k + 1) / max(1, len(regions)))
        pieces = [
            (b, e, x, speaker_audio(wav, b, e, x, act[speakers.index(x)], regions))
            for b, e, x in chunks(turns)
            if e - b >= 0.1
        ]
        totals = {x: float(act[i].sum()) * FRAME for i, x in enumerate(speakers)}
        order = sorted(speakers, key=lambda x: -totals[x])
        names = {x: f"S{i + 1}" for i, x in enumerate(order)}
        segments = []
        for i in range(0, len(pieces), self.batch):
            part = pieces[i : i + self.batch]
            texts = self.recognize([p[3] for p in part], hotwords)
            for (b, e, x, _), text in zip(part, texts, strict=True):
                if text:
                    segments.append(
                        {
                            "start": round(b, 2),
                            "end": round(e, 2),
                            "text": text,
                            **({"speaker": names[x]} if diarize else {}),
                        }
                    )
            progress(0.6 + 0.4 * (i + len(part)) / max(1, len(pieces)))
        segments.sort(key=lambda s: (s["start"], s.get("speaker", "")))
        result = {"ok": True, "segments": segments}
        if diarize:
            ref = self.voice(reference) if reference else None
            voices = {name: self.voice(path) for name, path in (references or {}).items()}
            listed = []
            for x in order:
                c = centroids.get(x)
                value = float(np.dot(ref, c)) if ref is not None and c is not None else None
                speaker = {"id": names[x], "seconds": round(totals[x], 2), "similarity": run.similarity(value)}
                if c is not None:
                    speaker["embedding"] = run.vector(c)
                if references:
                    speaker["similarities"] = {
                        name: run.similarity(float(np.dot(v, c)) if c is not None else None)
                        for name, v in voices.items()
                    }
                listed.append(speaker)
            result["speakers"] = listed
        sys.stderr.write(
            f"pyannote {len(speakers)} speakers, {len(regions)} overlap regions, {len(segments)} segments\n"
        )
        return result

    run.Engine.__init__ = __init__
    run.Engine.separate = separate
    run.Engine.transcribe = transcribe
