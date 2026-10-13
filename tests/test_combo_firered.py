"""Combo engine: the pack keeps VAD, diarization and punctuation; FireRedASR2-AED only replaces recognition."""

import contextlib
import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import numpy as np
import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "deploy" / "asr-eval" / "combo_firered.py"


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Tokens(list):
    def cpu(self) -> "_Tokens":
        return self


class _Batch:
    def __init__(self, rows: list[np.ndarray]) -> None:
        self.rows = rows

    def to(self, device: str) -> "_Batch":
        assert device == "cuda"
        return self


def _fake_firered(monkeypatch: pytest.MonkeyPatch, seen: dict) -> None:
    """fireredasr2s stand-ins: a clip's "transcript" is its peak sample, so scaling and order are both visible."""

    class Features:
        def __init__(self, cmvn: str) -> None:
            seen["cmvn"] = cmvn

        def __call__(self, waves, ids):
            kept = [
                (uttid, wav) for (rate, wav), uttid in zip(waves, ids, strict=True) if rate == 16000 and len(wav) >= 400
            ]
            if not kept:
                return None, None, [], [], []
            return _Batch([w for _, w in kept]), _Batch([]), [], [], [u for u, _ in kept]

    class Model:
        decoder = SimpleNamespace(layer_stack=[])

        def eval(self) -> "Model":
            return self

        def to(self, device: str) -> "Model":
            seen["device"] = device
            return self

        def transcribe(self, feats: _Batch, lengths: _Batch, **options):
            seen["options"] = options
            return [[{"yseq": _Tokens([int(np.abs(row).max())])}] for row in feats.rows]

    class Tokenizer:
        def __init__(self, vocab: str, bpe: str) -> None:
            pass

        def detokenize(self, tokens: list[int]) -> str:
            return seen.get("texts", {}).get(tokens[0], f"<sil>Peak {tokens[0]}<blank>")

    modules = {
        "fireredasr2s": ModuleType("fireredasr2s"),
        "fireredasr2s.fireredasr2": ModuleType("fireredasr2s.fireredasr2"),
        "fireredasr2s.fireredasr2.asr": SimpleNamespace(load_fireredasr_aed_model=lambda path: Model()),
        "fireredasr2s.fireredasr2.data": ModuleType("fireredasr2s.fireredasr2.data"),
        "fireredasr2s.fireredasr2.data.asr_feat": SimpleNamespace(ASRFeatExtractor=Features),
        "fireredasr2s.fireredasr2.tokenizer": ModuleType("fireredasr2s.fireredasr2.tokenizer"),
        "fireredasr2s.fireredasr2.tokenizer.aed_tokenizer": SimpleNamespace(ChineseCharEnglishSpmTokenizer=Tokenizer),
    }
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)


def _fake_run(calls: list | None = None) -> ModuleType:
    class Engine:
        def __init__(self, device: str = "auto") -> None:
            self.np = np
            self.torch = SimpleNamespace(no_grad=contextlib.nullcontext)
            self.device = device
            self.punc = SimpleNamespace(generate=lambda input, disable_pbar: [{"text": f"{input}。"}])

        def recognize(self, clips, hotwords):
            if calls is None:
                raise AssertionError("the pack's own recognizer must not run")
            calls.append(len(clips))
            return [f"paraformer {len(clip)}。" for clip in clips]

    run = ModuleType("run")
    run.Engine = Engine
    return run


def _combo(monkeypatch: pytest.MonkeyPatch, seen: dict) -> ModuleType:
    _fake_firered(monkeypatch, seen)
    monkeypatch.setitem(sys.modules, "torchaudio", ModuleType("torchaudio"))  # keep the combo's stub out of sys.modules
    return _load("combo_firered", SCRIPT)


@pytest.mark.parametrize(
    ("text", "seconds", "expected"),
    [
        ("对对对对对对对。", 3.0, False),
        ("嗯，对对对对对对对对对。", 3.0, True),
        ("有" * 600, 6.8, True),
        ("首先咱们确定一下咱们这个产品的目标，这个人群客户群这一块儿。", 4.6, False),
        ("首先咱们确定一下咱们这个产品的目标", 1.0, True),
        ("", 0.0, False),
    ],
)
def test_degenerate_output(monkeypatch: pytest.MonkeyPatch, text: str, seconds: float, expected: bool) -> None:
    assert _combo(monkeypatch, {}).degenerate(text, seconds) is expected


def test_fallback_redoes_only_degenerate_clips_with_paraformer(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seen: dict = {"texts": {16384: "对" * 30, 8192: "预算"}}
    combo = _combo(monkeypatch, seen)
    calls: list = []
    run = _fake_run(calls)
    combo.combine(run, tmp_path, beam=1, fallback=True)
    engine = run.Engine("cuda")
    clips = [np.full(1600, 0.5, np.float32), np.full(800, -0.25, np.float32)]
    assert engine.recognize(clips, []) == ["paraformer 1600。", "预算。"]
    assert calls == [1]

    run = _fake_run()
    combo.combine(run, tmp_path, beam=1)  # without --fallback the loop is kept as FireRed wrote it
    assert run.Engine("cuda").recognize(clips[:1], []) == ["对" * 30 + "。"]


def test_recognize_uses_firered_then_the_packs_punctuation(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seen: dict = {}
    combo = _combo(monkeypatch, seen)
    run = _fake_run()
    combo.combine(run, tmp_path, beam=1)
    engine = run.Engine("cuda")
    assert (seen["cmvn"], seen["device"]) == (str(tmp_path / "cmvn.ark"), "cuda")

    clips = [np.full(1600, 0.5, np.float32), np.zeros(10, np.float32), np.full(800, -0.25, np.float32)]
    # The too-short middle clip is dropped by the feature extractor and comes back empty, in place.
    assert engine.recognize(clips, ["热词"]) == ["peak 16384。", "", "peak 8192。"]
    assert seen["options"]["beam_size"] == 1
    assert engine.recognize([np.zeros(10, np.float32)], []) == [""]
