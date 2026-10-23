"""Precision selection plus upstream decoder conformance (also run in the GPU pack environment)."""

import copy
import importlib.util
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

PACK = Path(__file__).resolve().parents[1] / "deploy" / "compute" / "asr-funasr"


def load(name):
    spec = importlib.util.spec_from_file_location(name, PACK / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("device", "major", "supported", "expected"),
    [
        ("cuda", 8, True, "bf16"),
        ("cuda", 7, True, "fp32"),
        ("cuda", 8, False, "fp32"),
        ("cpu", 8, True, "fp32"),
        ("mps", 8, True, "fp32"),
    ],
)
def test_only_native_bf16_cuda_changes_precision(device, major, supported, expected):
    def context(d):
        assert d.type == "cuda"  # CPU/MPS must not query CUDA or initialize a CUDA context.
        return nullcontext()

    torch = SimpleNamespace(
        device=lambda d: SimpleNamespace(type=d),
        bfloat16="bf16",
        float32="fp32",
        cuda=SimpleNamespace(
            device=context, get_device_capability=lambda d: (major, 0), is_bf16_supported=lambda: supported
        ),
    )
    assert load("firered_decode").inference_dtype(torch, device) == expected


@pytest.fixture
def upstream():
    torch = pytest.importorskip("torch")
    module = pytest.importorskip("fireredasr2s.fireredasr2.models.module.transformer_decoder")
    torch.set_num_threads(1)
    return torch, module.TransformerDecoder


@pytest.mark.parametrize("seed", [0, 19, 42])
def test_incremental_decoder_matches_upstream_across_batches_and_padding(upstream, seed):
    torch, decoder_type = upstream
    torch.manual_seed(seed)
    original = decoder_type(1, 2, 0, 13, 2, 2, 8).eval()
    # Untie the projection so this tiny random decoder does not just repeat SOS.
    original.tgt_word_prj = torch.nn.Linear(8, 13, bias=True)
    candidate = copy.deepcopy(original)
    for decoder in [original, candidate]:
        load("overlap").cache_cross_attention(decoder)
    load("firered_decode").install_greedy_decoder(candidate)
    with torch.no_grad():
        # Reuse the decoder: caches must reset when the next batch is shorter or has fewer rows.
        for batch, frames, limit in [(3, 9, 9), (1, 4, 1), (2, 6, 0)]:
            encoded = torch.randn(batch, frames, 8)
            mask = torch.ones(batch, 1, frames, dtype=torch.uint8)
            mask[0, :, frames // 2 :] = 0
            kwargs = {"decode_max_len": limit, "softmax_smoothing": 1.25, "length_penalty": 0.6}
            expected = original.batch_beam_search(encoded, mask, **kwargs)
            actual = candidate.batch_beam_search(encoded, mask, **kwargs)
            assert [h[0]["yseq"].tolist() for h in actual] == [h[0]["yseq"].tolist() for h in expected]


def test_early_eos_padding_and_decode_limit_preserve_every_hypothesis(upstream):
    torch, decoder_type = upstream

    class Projection(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.step = 0

        def forward(self, x):
            tokens = [2, [0, 7, 2, 2, 2][self.step], 8]
            self.step += 1
            logits = torch.full((3, 13), -10.0)
            for i, token in enumerate(tokens):
                logits[i, token] = 10.0
            return logits

    original = decoder_type(1, 2, 0, 13, 2, 2, 8).eval()
    original.tgt_word_prj = Projection()
    candidate = copy.deepcopy(original)
    load("firered_decode").install_greedy_decoder(candidate)
    encoded, mask = torch.randn(3, 5, 8), torch.ones(3, 1, 5, dtype=torch.uint8)
    with torch.no_grad():
        for decoder in [original, candidate]:
            result = decoder.batch_beam_search(encoded, mask, decode_max_len=5)
            assert [h[0]["yseq"].tolist() for h in result] == [[], [0, 7], [8] * 5]


def test_beam_search_with_multiple_hypotheses_keeps_upstream_contract(upstream):
    torch, decoder_type = upstream
    torch.manual_seed(8)
    original = decoder_type(1, 2, 0, 13, 2, 2, 8).eval()
    candidate = copy.deepcopy(original)
    load("firered_decode").install_greedy_decoder(candidate)
    encoded, mask = torch.randn(2, 4, 8), torch.ones(2, 1, 4, dtype=torch.uint8)
    with torch.no_grad():
        before = original.batch_beam_search(encoded, mask, beam_size=3, nbest=2, eos_penalty=0.9)
        after = candidate.batch_beam_search(encoded, mask, beam_size=3, nbest=2, eos_penalty=0.9)
    for a, b in zip(before, after, strict=True):
        assert len(a) == len(b) == 2
        for x, y in zip(a, b, strict=True):
            assert x["yseq"].tolist() == y["yseq"].tolist()
            torch.testing.assert_close(x["confidence"], y["confidence"])
