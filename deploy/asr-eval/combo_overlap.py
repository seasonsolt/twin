#!/usr/bin/env python3
"""Eval-only single-channel MossFormer2 recovery; the production pack is unchanged.

Run from a directory containing checkpoints/MossFormer2_SS_16K with ClearVoice
installed, then pass the pack's server arguments after --. References are used
only by the original pack for claims, never as separator enrollment.
"""

import argparse
import importlib.util
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path


def load_module(path):
    spec = importlib.util.spec_from_file_location("overlap_pack", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def distinct_text(text, original):
    def clean(s):
        return re.sub(r"[^\w]", "", s).lower()

    a, b = clean(text), clean(original)
    return bool(a) and a not in b and SequenceMatcher(None, a, b).ratio() < 0.8


def assign(vector, centroids, minimum=0.45, margin=0.05):
    scores = sorted(((float(vector @ c), name) for name, c in centroids.items()), reverse=True)
    if len(scores) < 2 or scores[0][0] < minimum or scores[0][0] - scores[1][0] < margin:
        return None
    return scores[0][1]


def recover(engine, wav, result, mode, progress, hotwords=()):
    np = engine.np
    original = result["segments"]
    grouped = {}
    for segment in original:
        grouped.setdefault(segment["speaker"], []).append(segment)
    if len(grouped) < 2:
        return result
    centroids = {}
    for name, segments in grouped.items():
        vectors = []
        for s in sorted(segments, key=lambda s: s["end"] - s["start"], reverse=True)[:5]:
            begin, end = int(s["start"] * 16000), int(s["end"] * 16000)
            if end - begin >= 16000:
                mid = (begin + end) // 2
                vectors.append(engine.embed(wav[max(begin, mid - 16000) : min(end, mid + 16000)]))
        if vectors:
            mean = np.mean(vectors, axis=0)
            centroids[name] = mean / (np.linalg.norm(mean) + 1e-9)
    output = []
    for index, segment in enumerate(original):
        additions, replacements = [], []
        begin, end = int(segment["start"] * 16000), int(segment["end"] * 16000)
        for start in range(begin, end, 8 * 16000):
            stop = min(end, start + 8 * 16000)
            clip = wav[start:stop]
            if len(clip) < 8000:
                continue
            streams = engine.separate(clip)
            energy = float(np.mean(clip**2)) + 1e-12
            accepted = []
            for stream in streams:
                if not np.isfinite(stream).all() or float(np.mean(stream**2)) / energy < 0.03:
                    continue
                name = assign(engine.embed(stream), centroids)
                if name is not None:
                    accepted.append((name, stream))
            if len(accepted) != 2 or accepted[0][0] == accepted[1][0]:
                continue
            if segment["speaker"] not in [name for name, _ in accepted]:
                continue
            for name, stream in accepted:
                if mode == "add" and name == segment["speaker"]:
                    continue
                spans = engine.vad.generate(input=stream, cache={}, disable_pbar=True)[0]["value"]
                for b, e in spans:
                    b, e = max(0, int(b * 16)), min(len(stream), int(e * 16))
                    if e - b < 3200:
                        continue
                    text = engine.recognize([stream[b:e]], hotwords)[0]
                    if not text or (name != segment["speaker"] and not distinct_text(text, segment["text"])):
                        continue
                    item = {
                        "start": round((start + b) / 16000, 2),
                        "end": round((start + e) / 16000, 2),
                        "speaker": name,
                        "text": text,
                    }
                    if name != segment["speaker"]:
                        additions.append(item)
                    else:
                        replacements.append(item)
        # Replacing only part of a long turn would silently delete its unprocessed words.
        if mode == "replace" and end - begin <= 8 * 16000 and additions and replacements:
            output.extend(replacements)
        else:
            output.append(segment)
        output.extend(additions)
        progress(0.4 + 0.6 * (index + 1) / len(original))
    result["segments"] = sorted(output, key=lambda s: (s["start"], s["speaker"]))
    for speaker in result["speakers"]:
        speaker["seconds"] = round(sum(s["end"] - s["start"] for s in output if s["speaker"] == speaker["id"]), 2)
    return result


def combine(run, mode):
    original_init, original_transcribe = run.Engine.__init__, run.Engine.transcribe

    def initialize(self, device="auto"):
        import torch
        from clearvoice import ClearVoice

        if torch.cuda.is_available():
            free, total = torch.cuda.mem_get_info()
            budget = min(10 * 2**30, free - 7 * 2**30)
            if budget < 3 * 2**30:
                raise RuntimeError("Insufficient GPU headroom: require 7 GiB spare plus 3 GiB for this prototype")
            torch.cuda.set_per_process_memory_fraction(budget / total)
        original_init(self, device)
        self.separator = ClearVoice(task="speech_separation", model_names=["MossFormer2_SS_16K"]).models[0]
        self.separator.model.eval()

    def separate(self, clip):
        # Direct inference avoids wrapper padding and per-stream RMS amplification.
        with self.torch.inference_mode():
            tensor = self.torch.from_numpy(clip[None]).to(self.separator.device)
            streams = self.separator.model(tensor)
            return [stream[0, : len(clip)].detach().cpu().numpy() for stream in streams]

    def transcribe(
        self, audio, diarize, reference, hotwords, progress, references=None, cluster_threshold=run.CLUSTER_THRESHOLD
    ):
        result = original_transcribe(
            self,
            audio,
            diarize,
            reference,
            hotwords,
            lambda f: progress(f * 0.4),
            references=references,
            cluster_threshold=cluster_threshold,
        )
        if not diarize or not result["segments"]:
            progress(1)
            return result
        import librosa

        wav, _ = librosa.load(str(audio), sr=16000, mono=True)
        return recover(self, wav, result, mode, progress, hotwords)

    run.Engine.__init__ = initialize
    run.Engine.separate = separate
    run.Engine.transcribe = transcribe


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, required=True)
    parser.add_argument("--mode", choices=["add", "replace"], default="add")
    args, rest = parser.parse_known_args()
    run = load_module(args.pack / "run.py")
    combine(run, args.mode)
    sys.argv = [str(args.pack / "run.py"), *(rest[1:] if rest[:1] == ["--"] else rest)]
    return run.main()


if __name__ == "__main__":
    sys.exit(main())
