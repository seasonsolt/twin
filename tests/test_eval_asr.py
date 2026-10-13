"""ASR benchmark: normalization, edit counts, splits, engine protocol, transcript cache and paired comparison."""

import json
import sys
from pathlib import Path

import numpy as np
import pytest

from twin.evals import asr
from twin.evals.asr import (
    Engine,
    Item,
    bootstrap_ratio,
    edit_counts,
    load_engines,
    load_manifest,
    run_benchmark,
    score_tokens,
    select_items,
)

# A stand-in engine: echoes the reference with a fixed corruption and counts how many items it was asked to do.
FAKE_ENGINE = """
import json, sys
from pathlib import Path
if sys.argv[1:] == ["--identify"]:
    print(json.dumps({"versions": {"fake": "1"}}))
    raise SystemExit
request = json.load(sys.stdin)
options = request["options"]
refs = json.loads(Path(options["refs"]).read_text())
with open(options["calls"], "a") as calls:
    calls.write(f"{len(request['items'])}\\n")
for item in request["items"]:
    text = refs[item["id"]]
    if options.get("drop_last"):
        text = text[:-1]
    print(json.dumps({"id": item["id"], "text": text, "seconds": item["duration"] / 10}), flush=True)
"""


def _manifest(tmp_path: Path, texts: dict[str, str], groups: dict[str, str] | None = None) -> Path:
    (tmp_path / "audio").mkdir()
    lines = []
    for key, text in texts.items():
        (tmp_path / "audio" / f"{key}.wav").write_bytes(b"RIFF")
        row = {"id": key, "audio": f"audio/{key}.wav", "text": text, "duration": 2.0}
        if groups:
            row["group"] = groups[key]
        lines.append(json.dumps(row, ensure_ascii=False))
    path = tmp_path / "manifest.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_score_tokens_matches_speech_scorer() -> None:
    assert score_tokens("第8层，5.5 米！Hello world") == [*"第八层五点五米", "hello", "world"]
    assert score_tokens("，。？") == []


@pytest.mark.parametrize(
    ("ref", "hyp", "expected"),
    [
        ("abc", "abc", (0, 0, 0)),
        ("abc", "axc", (1, 0, 0)),
        ("abc", "ac", (0, 1, 0)),
        ("abc", "abcd", (0, 0, 1)),
        ("", "ab", (0, 0, 2)),
        ("ab", "", (0, 2, 0)),
    ],
)
def test_edit_counts(ref: str, hyp: str, expected: tuple[int, int, int]) -> None:
    assert edit_counts(list(ref), list(hyp)) == expected


def test_manifest_rejects_duplicates_and_missing_audio(tmp_path: Path) -> None:
    path = _manifest(tmp_path, {"a": "你好"})
    assert load_manifest(path)[0].group == "a"
    path.write_text(path.read_text() * 2)
    with pytest.raises(ValueError, match="重复"):
        load_manifest(path)
    (tmp_path / "audio" / "a.wav").unlink()
    path.write_text(path.read_text().splitlines()[0] + "\n")
    with pytest.raises(ValueError, match="音频不存在"):
        load_manifest(path)


def test_splits_are_disjoint_deterministic_and_keep_groups_whole() -> None:
    items = [Item(f"u{i}", Path("/x"), "字", 1.0, f"g{i // 3}") for i in range(90)]
    formal = select_items(items, "formal", size=20)
    dev = select_items(items, "dev", size=20)
    assert formal == select_items(list(reversed(items)), "formal", size=20)
    assert not {i.id for i in formal} & {i.id for i in dev}
    assert 20 <= len(formal) < 23 and 20 <= len(dev) < 23
    for sample in (formal, dev):
        groups = {i.group for i in sample}
        assert all(sum(i.group == g for i in sample) == 3 for g in groups)
    assert select_items(items, "full") == items
    assert select_items(items, "formal", size=20, seed="other") != formal


def test_engine_config_validation(tmp_path: Path) -> None:
    path = tmp_path / "engines.toml"
    for kind in sorted(set(asr.KINDS) - {"sensevoice"}):
        assert (asr.ENGINE_ROOT / asr.KINDS[kind]).is_file()
        path.write_text(f'[[engine]]\nname = "q"\nkind = "{kind}"\npython = "/bin/python"\n')
        with pytest.raises(ValueError, match="model"):
            load_engines(path, tmp_path / "pack")
    path.write_text('[[engine]]\nname = "x"\nkind = "whisper"\npython = "/bin/python"\n')
    with pytest.raises(ValueError, match="未知引擎"):
        load_engines(path, tmp_path / "pack")
    path.write_text('[[engine]]\nname = "a"\nkind = "sensevoice"\n' * 2)
    with pytest.raises(ValueError, match="重复"):
        load_engines(path, tmp_path / "pack")
    path.write_text(f'[[engine]]\nname = "q"\nkind = "qwen3-mlx"\nmodel = "/m"\npython = "/p"\npack = "{tmp_path}"\n')
    with pytest.raises(ValueError, match="pack"):
        load_engines(path, tmp_path / "pack")


def test_sensevoice_engine_defaults_to_installed_pack_and_accepts_another(tmp_path: Path) -> None:
    path = tmp_path / "engines.toml"
    path.write_text(
        '[[engine]]\nname = "a"\nkind = "sensevoice"\n'
        f'[[engine]]\nname = "b"\nkind = "sensevoice"\npack = "{tmp_path / "1.1.0"}"\n'
    )
    current, older = load_engines(path, tmp_path / "current")
    assert (current.pack, current.python) == (tmp_path / "current", tmp_path / "current" / "venv" / "bin" / "python")
    assert (older.pack, older.python) == (tmp_path / "1.1.0", tmp_path / "1.1.0" / "venv" / "bin" / "python")


def test_bootstrap_ratio_is_deterministic_and_brackets_estimate() -> None:
    errors = np.asarray([1, 0, 3, 2, 0, 1, 4, 0], dtype=np.float64)
    lengths = np.asarray([10, 8, 12, 9, 7, 11, 10, 6], dtype=np.float64)
    low, high = bootstrap_ratio(errors, lengths, "seed")
    assert (low, high) == bootstrap_ratio(errors, lengths, "seed")
    assert low <= errors.sum() / lengths.sum() <= high


def test_benchmark_caches_transcripts_and_compares(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    texts = {f"u{i}": "今天开会讨论预算" for i in range(6)}
    manifest = _manifest(tmp_path, texts)
    engine_root = tmp_path / "engines"
    engine_root.mkdir()
    (engine_root / "fake.py").write_text(FAKE_ENGINE)
    monkeypatch.setattr(asr, "ENGINE_ROOT", engine_root)
    monkeypatch.setitem(asr.KINDS, "fake", "fake.py")
    refs = tmp_path / "refs.json"
    refs.write_text(json.dumps(texts, ensure_ascii=False))
    calls = tmp_path / "calls.txt"
    python = Path(sys.executable)
    engines = [
        Engine("exact", "fake", python, None, {"refs": str(refs), "calls": str(calls)}),
        Engine("lossy", "fake", python, None, {"refs": str(refs), "calls": str(calls), "drop_last": True}),
    ]
    out, cache = tmp_path / "out", tmp_path / "cache"
    card = run_benchmark(manifest, engines, out, split="full", cache_dir=cache)
    exact, lossy = card["engines"]
    assert exact["metrics"]["strict"]["cer"] == 0
    assert lossy["metrics"]["strict"]["cer"] == pytest.approx(1 / 8)
    assert lossy["metrics"]["strict"]["deletion"] == pytest.approx(1 / 8)
    assert exact["rtf"] == pytest.approx(0.1)
    comparison = card["comparisons"][0]["strict"]
    assert comparison["cer_difference"] == pytest.approx(1 / 8)
    assert (comparison["items_better"], comparison["items_worse"]) == (0, 6)
    assert calls.read_text().split() == ["6", "6"]
    assert (out / "scorecard.md").read_text().count("lossy") == 3
    assert (out / "items.jsonl").stat().st_mode & 0o777 == 0o600

    # A rerun only rescores; a changed option is a new engine identity and transcribes again.
    run_benchmark(manifest, engines, out, split="full", cache_dir=cache)
    assert calls.read_text().split() == ["6", "6"]
    engines[1] = Engine("lossy", "fake", python, None, {**engines[1].options, "extra": 1})
    run_benchmark(manifest, engines, out, split="full", cache_dir=cache)
    assert calls.read_text().split() == ["6", "6", "6"]


def test_interrupted_cache_resumes_only_missing_items(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    texts = {f"u{i}": "预算" for i in range(4)}
    manifest = _manifest(tmp_path, texts)
    engine_root = tmp_path / "engines"
    engine_root.mkdir()
    (engine_root / "fake.py").write_text(FAKE_ENGINE)
    monkeypatch.setattr(asr, "ENGINE_ROOT", engine_root)
    monkeypatch.setitem(asr.KINDS, "fake", "fake.py")
    refs, calls = tmp_path / "refs.json", tmp_path / "calls.txt"
    refs.write_text(json.dumps(texts, ensure_ascii=False))
    engine = Engine("exact", "fake", Path(sys.executable), None, {"refs": str(refs), "calls": str(calls)})
    cache = tmp_path / "cache"
    run_benchmark(manifest, [engine], tmp_path / "out", split="full", cache_dir=cache)
    (cache_file,) = cache.iterdir()
    lines = cache_file.read_text().splitlines()
    cache_file.write_text("\n".join(lines[:2]) + '\n{"id": "u2", "te')  # killed mid-write
    run_benchmark(manifest, [engine], tmp_path / "out", split="full", cache_dir=cache)
    assert calls.read_text().split() == ["4", "2"]
    run_benchmark(manifest, [engine], tmp_path / "out", split="full", cache_dir=cache)
    assert calls.read_text().split() == ["4", "2"]
