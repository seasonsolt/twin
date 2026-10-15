#!/usr/bin/env python3
"""评测用组合引擎：asr-funasr 算力包的切分、声纹聚类和标点照旧，只把识别模型换成 FireRedASR2-AED。

用装有算力包依赖和 fireredasr2s 的 Python 运行；`--` 之后的参数原样交给算力包 run.py，常用 `--serve --port`：

    python combo_firered.py --pack <算力包目录> --model <FireRedASR2-AED 目录> -- --serve --port 18792

请求、返回和 remote.py 客户端与算力包完全一致，所以 eval-asr-session 能把它和原包放在同一批场次上对比。
FireRed 没有热词接口，请求里的热词被忽略。解码参数同片段引擎 fireredasr2_aed.py，
beam 默认 1（片段评测里与 3 只差 0.1 点）；交叉注意力缓存也照搬那里，这样部署到算力机只需拷这一个文件。
没装 torchaudio 时放一个空模块：fireredasr2s 只在算词级时间戳时用它，这里不算时间戳。

`--fallback`：FireRed 的输出像是幻觉时，这一段改用算力包自己的 Paraformer。AliMeeting 上 FireRed 会在
“一人说话、另一人连声附和”的重叠片段里转写成附和声并循环（“对对对……”几十到几百字），所以判为幻觉的条件是：
同一个字连续 8 次以上，或每秒超过 8 个字（按 字数 /（秒数 + 1））。Paraformer 在 Eval 上最多 7.2 字/秒、从未连续 12 次。
"""

import argparse
import importlib.machinery
import importlib.util
import re
import sys
import types
from itertools import groupby
from pathlib import Path

MAX_RUN = 8
MAX_RATE = 8.0


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


def degenerate(text, seconds):
    """FireRed output that looks like a decoding loop rather than speech: one character repeated, or too many."""
    chars = re.sub(r"[^\w]", "", text)
    longest = max((len(list(group)) for _, group in groupby(chars)), default=0)
    return longest >= MAX_RUN or len(chars) / (seconds + 1) > MAX_RATE


def combine(run, model_dir, beam, fallback=False):
    """Replace run.Engine.recognize with FireRedASR2-AED; VAD, CAM++, clustering and ct-punc stay the pack's own."""
    if "torchaudio" not in sys.modules and importlib.util.find_spec("torchaudio") is None:
        stub = types.ModuleType("torchaudio")
        stub.__spec__ = importlib.machinery.ModuleSpec("torchaudio", None)
        sys.modules["torchaudio"] = stub
    original_init = run.Engine.__init__
    original_recognize = run.Engine.recognize

    def __init__(self, device="auto"):
        original_init(self, device)
        from fireredasr2s.fireredasr2.asr import load_fireredasr_aed_model
        from fireredasr2s.fireredasr2.data.asr_feat import ASRFeatExtractor
        from fireredasr2s.fireredasr2.tokenizer.aed_tokenizer import ChineseCharEnglishSpmTokenizer

        root = Path(model_dir)
        self.fr_features = ASRFeatExtractor(str(root / "cmvn.ark"))
        self.fr_tokenizer = ChineseCharEnglishSpmTokenizer(str(root / "dict.txt"), str(root / "train_bpe1000.model"))
        self.fr_model = load_fireredasr_aed_model(str(root / "model.pth.tar")).eval().to(self.device)
        cache_cross_attention(self.fr_model.decoder)

    def recognize(self, clips, hotwords):
        np, torch = self.np, self.torch
        ids = [str(k) for k in range(len(clips))]
        # Kaldi fbank expects int16-scaled samples, as kaldiio returns them when FireRed reads a wav file.
        waves = [(16000, np.asarray(clip, dtype=np.float32) * 32768.0) for clip in clips]
        feats, lengths, _, _, kept = self.fr_features(waves, ids)
        raw = {}
        if feats is not None:
            with torch.no_grad():
                hyps = self.fr_model.transcribe(
                    feats.to(self.device),
                    lengths.to(self.device),
                    beam_size=beam,
                    nbest=1,
                    decode_max_len=0,
                    softmax_smoothing=1.25,
                    length_penalty=0.6,
                    eos_penalty=1.0,
                )
            for uttid, hyp in zip(kept, hyps, strict=True):
                text = self.fr_tokenizer.detokenize([int(token) for token in hyp[0]["yseq"].cpu()])
                raw[uttid] = re.sub(r"(<blank>)|(<sil>)", "", text).lower().strip()
        texts = []
        for uttid in ids:
            text = raw.get(uttid, "")
            texts.append(str(self.punc.generate(input=text, disable_pbar=True)[0]["text"]).strip() if text else "")
        redo = [k for k, clip in enumerate(clips) if fallback and degenerate(texts[k], len(clip) / 16000)]
        if redo:
            for k, text in zip(redo, original_recognize(self, [clips[k] for k in redo], hotwords), strict=True):
                texts[k] = text
        return texts

    run.Engine.__init__ = __init__
    run.Engine.recognize = recognize


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pack", type=Path, required=True, help="asr-funasr 算力包目录（含 run.py）")
    parser.add_argument("--model", type=Path, required=True, help="FireRedASR2-AED 模型目录")
    parser.add_argument("--beam", type=int, default=1)
    parser.add_argument("--fallback", action="store_true", help="FireRed 输出像幻觉时这一段改用 Paraformer")
    args, rest = parser.parse_known_args()
    if rest[:1] == ["--"]:
        rest = rest[1:]
    run = load_module("run", args.pack / "run.py")
    combine(run, args.model, args.beam, args.fallback)
    sys.argv = [str(args.pack / "run.py"), *rest]
    return run.main()


if __name__ == "__main__":
    sys.exit(main())
