#!/usr/bin/env python3
"""ASR 评测引擎：FireRedASR2-AED（小红书 FireRedASR2S），PyTorch 在 Apple 芯片的 MPS 上运行。

用装有 fireredasr2s 的 Python 运行，model 为模型目录（含 model.pth.tar、cmvn.ark、dict.txt、train_bpe1000.model）。
官方 FireRedAsr2.transcribe() 只认 CUDA，所以这里用它的特征提取、模型和分词器，自己把张量放到 MPS 上，
解码参数取官方 README 的默认值：beam_size=3、softmax_smoothing=1.25、aed_length_penalty=0.6、eos_penalty=1.0。
按时长排序后每批 batch_size 条（默认 16）；同批特征补零到等长，由编码器掩码屏蔽。
"""

import json
import re
import sys
import time
from importlib import metadata
from pathlib import Path

PACKAGES = ("fireredasr2s", "torch", "kaldi_native_fbank")


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
    import torch
    from fireredasr2s.fireredasr2.asr import load_fireredasr_aed_model
    from fireredasr2s.fireredasr2.data.asr_feat import ASRFeatExtractor
    from fireredasr2s.fireredasr2.tokenizer.aed_tokenizer import ChineseCharEnglishSpmTokenizer

    root = Path(request["model"])
    device = options.get("device") or ("mps" if torch.backends.mps.is_available() else "cpu")
    batch = int(options.get("batch_size", 16))
    beam = int(options.get("beam_size", 3))
    features = ASRFeatExtractor(str(root / "cmvn.ark"))
    tokenizer = ChineseCharEnglishSpmTokenizer(str(root / "dict.txt"), str(root / "train_bpe1000.model"))
    model = load_fireredasr_aed_model(str(root / "model.pth.tar")).eval().to(device)
    items = sorted(request["items"], key=lambda item: item["duration"])
    for start in range(0, len(items), batch):
        part = items[start : start + batch]
        feats, lengths, _, _, kept = features([str(item["audio"]) for item in part], [item["id"] for item in part])
        began = time.perf_counter()
        texts = {}
        if feats is not None:
            with torch.no_grad():
                hyps = model.transcribe(
                    feats.to(device),
                    lengths.to(device),
                    beam_size=beam,
                    nbest=1,
                    decode_max_len=0,
                    softmax_smoothing=1.25,
                    length_penalty=0.6,
                    eos_penalty=1.0,
                )
            for uttid, hyp in zip(kept, hyps, strict=True):
                text = tokenizer.detokenize([int(token) for token in hyp[0]["yseq"].cpu()])
                texts[uttid] = re.sub(r"(<blank>)|(<sil>)", "", text).lower()
        elapsed = time.perf_counter() - began
        total = sum(item["duration"] for item in part)
        for item in part:
            # Clips too short for one fbank frame are dropped by the extractor; they score as empty output.
            emit({"id": item["id"], "text": texts.get(item["id"], ""), "seconds": elapsed * item["duration"] / total})


if __name__ == "__main__":
    main()
