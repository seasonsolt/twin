"""Overlap-aware transcription (asr-funasr 1.4, CUDA): every speaker is transcribed from their own voice, also where
two people talk at once. Chosen on AliMeeting against the 1.3 path and pyannote community-1; see docs/ASR_EVAL.md
(个人上传路径：三套分人方案对比).

1. Loudness: the whole recording is scaled so the loudest 30% of its 30 ms frames sit at -27 dBFS; voiceprints,
   separation and recognition use the scaled audio, diarization the original.
2. Diarization allowing overlaps (diarize.py: 3D-Speaker's pipeline with the segmentation model of segmentation.py).
   A turn shorter than 0.5 s lying wholly inside another speaker's turn is dropped: on AliMeeting such turns are
   mostly the other person's words, and their separated stream would repeat them.
3. Where two or more people talk, the stretch (with 0.5 s either side) is split into two streams by MossFormer2.
   The streams go to the two speakers active there the longest, by voiceprints taken in the separated domain: for
   each speaker up to ten 3 s single-speaker clips go through the same separator and the louder stream is embedded.
   Voiceprints of the mixture do not work: a separated 1.5 s clip is mostly under 0.4 alike to them.
4. Each speaker's turns are joined into chunks of at most 15 s (gap under 1.2 s; someone else's turn in between ends
   the chunk); inside a chunk the stretches that are not theirs are muted and overlaps are replaced by their stream.
5. FireRedASR2-AED transcribes the chunks (beam 1), ct-punc adds punctuation; output that looks like a decoding loop
   (one character 8 times in a row, or over 8 characters a second) is transcribed again by Paraformer.
6. A speaker's voiceprint for claims is the mean of CAM++ zh-cn (the 1.3 model, so stored voiceprints stay valid)
   over 1.5 s windows of their single-speaker time.

The result has the same shape as run.Engine.transcribe. FireRed has no hotwords; they only reach Paraformer's
retries.
"""

from __future__ import annotations

import math
import re
from itertools import groupby

import numpy as np

SAMPLE_RATE = 16000
TARGET_DBFS = -27.0
DROP_ENCLOSED = 0.5  # seconds
CONTEXT = 0.5  # seconds of audio either side of an overlap given to the separator
PROBES = 10  # single-speaker clips per speaker for the separated-domain voiceprint
PROBE_FRAMES = 150  # 1.5 s runs at least; probes are 3 s from the start of the longest runs
FADE = 0.02  # seconds
MUTE_PAD = 0.1  # seconds of a speaker's own time kept unmuted either side
LONGEST, GAP = 15.0, 1.2  # chunk length and join gap, seconds, as run.organize
SEPARATE_BLOCK = 10 * SAMPLE_RATE  # MossFormer2 runs on 10 s pieces
ASR_BATCH = 8
BEAM = 1
MAX_RUN, MAX_RATE = 8, 8.0  # FireRed loop detection


def active_level(wav):
    """dBFS of the loudest 30% of 30 ms frames: speech level, mostly independent of how much silence there is."""
    frames = wav[: len(wav) // 480 * 480].reshape(-1, 480)
    energy = np.sort((frames.astype(np.float64) ** 2).mean(axis=1))
    top = energy[int(len(energy) * 0.7) :]
    return 10 * np.log10(top.mean() + 1e-12) if len(top) else None


def gain(wav, target=TARGET_DBFS):
    level = active_level(wav)
    return 1.0 if level is None else float(10 ** ((target - level) / 20))


def drop_enclosed(turns, shorter_than=DROP_ENCLOSED):
    """Turns (start, end, speaker) without the short ones lying wholly inside another speaker's turn."""
    return [
        (b, e, x)
        for b, e, x in turns
        if e - b >= shorter_than or not any(y != x and yb <= b and e <= ye for yb, ye, y in turns)
    ]


def chunks(turns, longest=LONGEST, gap=GAP):
    """Consecutive same-speaker turns joined (gap under `gap` s, up to `longest` s); longer ones split evenly. A turn
    of someone else starting in between ends the chunk, even when it overlaps."""
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
    """Boolean (speaker, 10 ms frame) matrix."""
    act = np.zeros((len(speakers), frames), bool)
    for b, e, x in turns:
        act[speakers.index(x), int(b * 100) : int(e * 100)] = True
    return act


def overlap_regions(act, speakers):
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
        on = act[:, f:g].sum(axis=1)
        regions.append({"start": f / 100, "end": g / 100, "pair": [speakers[i] for i in np.argsort(-on)[:2]]})
        f = g
    return regions


def runs_of(mask):
    """Index runs of the True frames of a boolean vector."""
    idx = np.flatnonzero(mask)
    return np.split(idx, np.flatnonzero(np.diff(idx) != 1) + 1) if len(idx) else []


def speaker_audio(wav, start, end, speaker, act_row, regions, fade=FADE, pad=MUTE_PAD):
    """One chunk of a speaker's own audio: the mixture where only they talk, their separated stream in overlaps,
    silence where they do not talk (a chunk can span someone else's short turn)."""
    bs, es = int(start * SAMPLE_RATE), int(end * SAMPLE_RATE)
    audio = wav[bs:es].copy()
    for r in regions:
        if speaker not in r["audio"] or r["end"] <= start or end <= r["start"]:
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
    reach = int(pad * 100)
    mine = act_row[int(start * 100) : int(start * 100) + (es - bs) // 160 + 1]
    grown = np.zeros_like(mine)
    for q in np.flatnonzero(mine):
        grown[max(0, q - reach) : q + reach + 1] = True
    level = np.repeat(grown.astype(np.float32), 160)[: len(audio)]
    if len(level) < len(audio):
        level = np.pad(level, (0, len(audio) - len(level)), constant_values=1)
    k = int(fade * SAMPLE_RATE)
    if k:
        level = np.convolve(level, np.ones(k, np.float32) / k, mode="same")
    return audio * level


def degenerate(text, seconds):
    """FireRed output that looks like a decoding loop rather than speech: one character repeated, or too many."""
    chars = re.sub(r"[^\w]", "", text)
    longest = max((len(list(group)) for _, group in groupby(chars)), default=0)
    return longest >= MAX_RUN or len(chars) / (seconds + 1) > MAX_RATE


def cache_cross_attention(decoder):
    """Project the encoder output to cross-attention keys and values once per batch (identical text, ~2x faster)."""
    for layer in decoder.layer_stack:
        attention = layer.cross_attn
        projected = {}

        def forward(q, k, v, mask=None, attention=attention, projected=projected):
            if projected.get("source") is not k:
                bs = k.size(0)
                projected["source"] = k
                projected["k"] = attention.w_ks(k).view(bs, -1, attention.n_head, attention.d_k).transpose(1, 2)
                projected["v"] = attention.w_vs(v).view(bs, -1, attention.n_head, attention.d_k).transpose(1, 2)
            bs = q.size(0)
            q = attention.w_qs(q).view(bs, -1, attention.n_head, attention.d_k).transpose(1, 2)
            mask = mask.unsqueeze(1) if mask is not None else None
            output = attention.attention(q, projected["k"], projected["v"], mask=mask)
            return attention.fc(output.transpose(1, 2).contiguous().view(bs, -1, attention.d_model))

        attention.forward = forward


class FireRed:
    """FireRedASR2-AED from its model directory (fireredasr2s package); `__call__` returns raw lower-cased text."""

    def __init__(self, root, device):
        import torch
        from fireredasr2s.fireredasr2.asr import load_fireredasr_aed_model
        from fireredasr2s.fireredasr2.data.asr_feat import ASRFeatExtractor
        from fireredasr2s.fireredasr2.tokenizer.aed_tokenizer import ChineseCharEnglishSpmTokenizer

        self.torch, self.device = torch, device
        self.features = ASRFeatExtractor(str(root / "cmvn.ark"))
        self.tokenizer = ChineseCharEnglishSpmTokenizer(str(root / "dict.txt"), str(root / "train_bpe1000.model"))
        self.model = load_fireredasr_aed_model(str(root / "model.pth.tar")).eval().to(device)
        cache_cross_attention(self.model.decoder)

    def __call__(self, clips):
        ids = [str(k) for k in range(len(clips))]
        # Kaldi fbank expects int16-scaled samples, as kaldiio returns them when FireRed reads a wav file.
        waves = [(SAMPLE_RATE, np.asarray(clip, dtype=np.float32) * 32768.0) for clip in clips]
        feats, lengths, _, _, kept = self.features(waves, ids)
        found = {}
        if feats is not None:
            with self.torch.no_grad():
                hyps = self.model.transcribe(
                    feats.to(self.device),
                    lengths.to(self.device),
                    beam_size=BEAM,
                    nbest=1,
                    decode_max_len=0,
                    softmax_smoothing=1.25,
                    length_penalty=0.6,
                    eos_penalty=1.0,
                )
            for uttid, hyp in zip(kept, hyps, strict=True):
                text = self.tokenizer.detokenize([int(token) for token in hyp[0]["yseq"].cpu()])
                found[uttid] = re.sub(r"(<blank>)|(<sil>)", "", text).lower().strip()
        return [found.get(uttid, "") for uttid in ids]


class Separator:
    """MossFormer2_SS_16K (clearvoice's network) with the pinned checkpoint; splits a clip into two streams."""

    def __init__(self, checkpoint, device):
        import argparse

        import torch
        from clearvoice.models.mossformer2_ss.mossformer2 import MossFormer2_SS_16K

        # clearvoice's config/inference/MossFormer2_SS_16K.yaml
        args = argparse.Namespace(
            num_spks=2, encoder_kernel_size=16, encoder_embedding_dim=512, mossformer_sequence_dim=512,
            num_mossformer_layer=24,
        )  # fmt: skip
        self.torch, self.device = torch, device
        self.model = MossFormer2_SS_16K(args).model
        state = torch.load(checkpoint, map_location="cpu", weights_only=True)["model"]
        state = {key.removeprefix("module."): value for key, value in state.items()}
        self.model.load_state_dict(state, strict=True)
        self.model.eval().to(device)

    def __call__(self, clip):
        streams = [np.zeros_like(clip), np.zeros_like(clip)]
        with self.torch.inference_mode():
            for b in range(0, len(clip), SEPARATE_BLOCK):
                piece = clip[b : b + SEPARATE_BLOCK]
                found = self.model(self.torch.from_numpy(piece[None]).to(self.device))
                for j in range(2):
                    streams[j][b : b + len(piece)] = found[j][0, : len(piece)].float().cpu().numpy()
        return streams


def unit(vector):
    return vector / (np.linalg.norm(vector) + 1e-9)


class Overlap:
    """The overlap-aware path on top of a run.Engine (its VAD, CAM++ zh-cn, Paraformer and ct-punc stay in use).
    `paths` maps roles to local model paths: diarize-speaker (a .pt file), segmentation (.safetensors), separation
    (a .pt file) and firered (a directory)."""

    def __init__(self, engine, paths, vad_path):
        import diarize
        import segmentation
        from funasr import AutoModel

        self.engine, device = engine, engine.device
        # 3D-Speaker's VAD settings are the model's own defaults, not run.py's shorter segments.
        vad = AutoModel(model=vad_path, device="cpu", disable_update=True, disable_pbar=True)
        segmenter = segmentation.Segmenter(paths["segmentation"], device)
        self.diarizer = diarize.Diarizer(vad, paths["diarize-speaker"], segmenter, device)
        self.separate = Separator(paths["separation"], device)
        self.firered = FireRed(paths["firered"], device)

    def recognize(self, clips, hotwords):
        engine = self.engine
        texts = [
            str(engine.punc.generate(input=text, disable_pbar=True)[0]["text"]).strip() if text else ""
            for text in self.firered(clips)
        ]
        redo = [k for k, clip in enumerate(clips) if degenerate(texts[k], len(clip) / SAMPLE_RATE)]
        if redo:
            for k, text in zip(redo, engine.recognize([clips[k] for k in redo], hotwords), strict=True):
                texts[k] = text
        return texts

    def voiceprints(self, wav, act, speakers):
        """Per speaker: the separated-domain centroid (for assigning streams) and the claim centroid."""
        engine = self.engine
        alone = act & (act.sum(axis=0) == 1)
        separated, claims = {}, {}
        for i, x in enumerate(speakers):
            runs = runs_of(alone[i])
            longest = sorted((r for r in runs if len(r) >= PROBE_FRAMES), key=len, reverse=True)[:PROBES]
            vectors = []
            for r in longest:
                streams = self.separate(wav[int(r[0] * 160) : int(r[0] * 160) + 3 * SAMPLE_RATE])
                louder = streams[int(np.argmax([np.mean(s**2) for s in streams]))]
                vectors.append(engine.embed_gpu(louder.astype(np.float32)))
            if vectors:
                separated[x] = unit(np.mean(vectors, axis=0))
            windows = []
            for r in runs:
                t = int(r[0])
                while t + 50 <= r[-1] + 1:
                    windows.append(wav[t * 160 : min(int(r[-1]) + 1, t + 150) * 160])
                    t += 75
            if windows:
                claims[x] = unit(engine.embed_all(windows, lambda _: None).mean(axis=0))
        return separated, claims

    def assign(self, wav, regions, separated, progress):
        """Separate every overlap region and give each of its pair their stream."""
        engine, pad = self.engine, int(CONTEXT * SAMPLE_RATE)
        for k, r in enumerate(regions):
            b16, e16 = int(r["start"] * SAMPLE_RATE), int(r["end"] * SAMPLE_RATE)
            lo, hi = max(0, b16 - pad), min(len(wav), e16 + pad)
            streams = [s[b16 - lo : e16 - lo] for s in self.separate(wav[lo:hi])]
            a, c = r["pair"]
            if a in separated and c in separated and e16 - b16 >= 1600:
                v = [engine.embed_gpu(s.astype(np.float32)) for s in streams]
                keep = v[0] @ separated[a] + v[1] @ separated[c] >= v[0] @ separated[c] + v[1] @ separated[a]
            else:  # too short to compare voices: the louder stream goes to whoever talks longer here
                keep = np.mean(streams[0] ** 2) >= np.mean(streams[1] ** 2)
            r["audio"] = {a: streams[0], c: streams[1]} if keep else {a: streams[1], c: streams[0]}
            progress(0.3 + 0.3 * (k + 1) / len(regions))

    def transcribe(self, audio, diarize, reference, hotwords, progress, references=None):
        import librosa

        engine = self.engine
        raw = librosa.load(str(audio), sr=SAMPLE_RATE, mono=True)[0]
        wav = (raw * gain(raw)).astype(np.float32)
        turns = drop_enclosed([(b, e, f"S{x}") for b, e, x in self.diarizer(raw)])
        progress(0.15)
        speakers = sorted({x for _, _, x in turns})
        act = activity(turns, speakers, len(wav) // 160 + 1)
        separated, claims = self.voiceprints(wav, act, speakers)
        progress(0.3)
        regions = overlap_regions(act, speakers)
        self.assign(wav, regions, separated, progress)
        pieces = [
            (b, e, x, speaker_audio(wav, b, e, x, act[speakers.index(x)], regions))
            for b, e, x in chunks(turns)
            if e - b >= 0.1
        ]
        totals = {x: float(act[i].sum()) / 100 for i, x in enumerate(speakers)}
        order = sorted(speakers, key=lambda x: -totals[x])
        names = {x: f"S{i + 1}" for i, x in enumerate(order)}
        segments = []
        for i in range(0, len(pieces), ASR_BATCH):
            part = pieces[i : i + ASR_BATCH]
            for (b, e, x, _), text in zip(part, self.recognize([p[3] for p in part], hotwords), strict=True):
                if text:
                    speaker = {"speaker": names[x]} if diarize else {}
                    segments.append({"start": round(b, 2), "end": round(e, 2), "text": text, **speaker})
            progress(0.6 + 0.4 * (i + len(part)) / len(pieces))
        segments.sort(key=lambda s: (s["start"], s.get("speaker", "")))
        result = {"ok": True, "segments": segments}
        if diarize:
            result["speakers"] = engine.describe(order, names, totals, claims, reference, references)
        return result
