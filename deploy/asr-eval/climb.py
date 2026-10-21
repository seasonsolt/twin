#!/usr/bin/env python3
"""评测用：按一份 JSON 配置给 asr-funasr 算力包打补丁后照常服务，算力包的 run.py 不改。

用装有算力包依赖的 Python 运行；`--` 之后的参数原样交给算力包 run.py，常用 `--serve --port`：

    python climb.py --pack <算力包目录> --config vad-0.4.json -- --serve --port 18795

客户端仍是 remote.py。服务端的配置客户端看不到，所以评测 TOML 要把同一份配置文件写进 `files`，
eval-asr-session 才会按配置区分缓存。配置项（都可省略，省略即与算力包相同）：

- `vad`：FSMN VAD 的额外参数，如 `{"speech_noise_thres": 0.4}`，与 run.py 的 max_end_silence_time 等合并。
- `gain`：按整场的活跃电平（能量最高的 30% 个 30 毫秒帧的平均能量）把输入放大或缩小到 `target` dBFS，
  `stages` 为 `["vad"]` 时只作用于 VAD，`["vad", "speaker", "asr"]` 时声纹和识别也用放大后的音频。
  可选 `max_db` 限制放大量，`only_up` 只放大不缩小。模型都吃 float 波形，放大后超过 1 也不削波。
- `firered`：识别换成 FireRedASR2-AED（同目录的 combo_firered.py），如 `{"model": "<模型目录>", "beam": 1,
  "fallback": true}`；要用装了 fireredasr2s 的 Python 运行。
- `pyannote`：整个转写换成同目录 overlap_pipeline.py 的重叠感知流程（pyannote 分人 + MossFormer2 分离），如
  `{"model": "<community-1 目录>", "params": {"clustering": {"Fb": 0.6}}, "drop_enclosed": 0.5}`；
  它自带响度归一，不能与 `gain` 同用。可选 `asr_batch` 改识别批大小，`mem_gb` 限制本进程显存（与线上共用 GPU 时）。
"""

import argparse
import importlib.util
import json
import math
import sys
from pathlib import Path


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def combine(run, config):
    """Patch run.Engine according to `config`; unknown keys are an error so a typo never runs as the baseline."""
    unknown = set(config) - {"vad", "gain", "firered", "pyannote"}
    if unknown:
        raise ValueError(f"未知配置项：{sorted(unknown)}")
    if config.get("pyannote") and config.get("gain"):
        raise ValueError("pyannote 自带响度归一，不能与 gain 同用")
    vad = config.get("vad") or {}
    original_init = run.Engine.__init__

    def __init__(self, device="auto"):
        original_init(self, device)
        if vad:
            from funasr import AutoModel

            options = {"max_end_silence_time": 500, "max_single_segment_time": 30000, **vad}
            self.vad = AutoModel(
                model=run.model_paths()["vad"], device="cpu", disable_update=True, disable_pbar=True, **options
            )

    run.Engine.__init__ = __init__
    if config.get("firered"):
        firered = config["firered"]
        combo = load_module("combo_firered", Path(__file__).with_name("combo_firered.py"))
        combo.combine(run, firered["model"], firered.get("beam", 1), firered.get("fallback", False))
    if config.get("gain"):
        apply_gain(run, config["gain"])
    if config.get("pyannote"):
        overlap = load_module("overlap_pipeline", Path(__file__).with_name("overlap_pipeline.py"))
        overlap.combine(run, config["pyannote"], gain_for)
        batch = config["pyannote"].get("asr_batch")
        if batch:
            initialized = run.Engine.__init__

            def __init__(self, device="auto"):
                initialized(self, device)
                self.batch = batch

            run.Engine.__init__ = __init__


def active_level(wav):
    """dBFS of the loudest 30% of 30 ms frames: speech level, mostly independent of how much silence there is."""
    import numpy as np

    frames = wav[: len(wav) // 480 * 480].reshape(-1, 480)
    energy = np.sort((frames.astype(np.float64) ** 2).mean(axis=1))
    top = energy[int(len(energy) * 0.7) :]
    return 10 * np.log10(top.mean() + 1e-12) if len(top) else None


def gain_for(wav, gain):
    level = active_level(wav)
    if level is None:
        return 1.0
    db = gain["target"] - level
    if gain.get("only_up"):
        db = max(0.0, db)
    if "max_db" in gain:
        db = min(db, gain["max_db"])
    return float(10 ** (db / 20))


def apply_gain(run, gain):
    stages = set(gain.get("stages", ["vad"]))
    if not stages <= {"vad", "speaker", "asr"} or "target" not in gain:
        raise ValueError("gain 需要 target，stages 只能取 vad / speaker / asr")
    original_init, original_transcribe = run.Engine.__init__, run.Engine.transcribe

    def __init__(self, device="auto"):
        original_init(self, device)
        self.gain = 1.0

        def scaled(model, many):
            generate = model.generate

            def call(*args, input=None, **kwargs):
                if self.gain != 1.0:
                    input = [x * self.gain for x in input] if many else input * self.gain
                return generate(*args, input=input, **kwargs)

            model.generate = call

        if "vad" in stages:
            scaled(self.vad, many=False)
        if "asr" in stages:
            # Wrap recognize rather than the Paraformer model, so a replaced recognizer gets the gain too.
            recognize = self.recognize
            self.recognize = lambda clips, hotwords: recognize([c * self.gain for c in clips], hotwords)
        if "speaker" in stages:
            embed_all = self.embed_all
            self.embed_all = lambda clips, done: embed_all([c * self.gain for c in clips], done)

    def transcribe(self, audio, *args, **kwargs):
        import librosa

        self.gain = gain_for(librosa.load(str(audio), sr=16000, mono=True)[0], gain)
        sys.stderr.write(f"gain {20 * math.log10(self.gain):+.1f} dB for {audio}\n")
        try:
            return original_transcribe(self, audio, *args, **kwargs)
        finally:
            self.gain = 1.0

    run.Engine.__init__ = __init__
    run.Engine.transcribe = transcribe


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    args, rest = parser.parse_known_args()
    run = load_module("climb_pack", args.pack / "run.py")
    combine(run, json.loads(args.config.read_text()))
    sys.argv = [str(args.pack / "run.py"), *(rest[1:] if rest[:1] == ["--"] else rest)]
    return run.main()


if __name__ == "__main__":
    sys.exit(main())
