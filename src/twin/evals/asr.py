"""ASR benchmark: run local recognizers over a labeled manifest, cache their transcripts, score corpus CER.

Engines are scripts under deploy/asr-eval run by their own Python (the compute pack venv, an MLX venv), so model
dependencies never enter twin's environment. A run sends one JSON request on stdin and reads one JSON line per item
back; every line is appended to a cache keyed by the engine identity, so an interrupted run resumes and a rerun with
an unchanged engine only rescores.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import platform
import re
import subprocess
import tomllib
import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TextIO

import numpy as np

from ..util import fingerprint, open_private, private_directory
from .stats import mcnemar_exact_p

ENGINE_ROOT = Path(__file__).resolve().parents[3] / "deploy" / "asr-eval"
KINDS = {
    "sensevoice": "sensevoice.py",
    "paraformer": "paraformer.py",
    "qwen3-mlx": "qwen3_mlx.py",
    "fireredasr2-aed": "fireredasr2_aed.py",
    "fun-asr-nano": "fun_asr_nano.py",
}
# Engines that load an installed asr-funasr pack's models with the pack's own venv.
PACK_KINDS = ("sensevoice", "paraformer")
# Small files that describe a model directory; weights are covered by the directory path (a hub snapshot commit).
_MODEL_FILES = ("config.json", "model.safetensors.index.json", "cmvn.ark", "dict.txt", "train_bpe1000.model")
SPLITS = ("dev", "formal", "full")
DEFAULT_SIZE = 1000
DEFAULT_SEED = "asr-v1"
# Interjections and sentence-final particles: references transcribe them verbatim and recognizers keep or drop them
# by style, so the `nofill` score removes them from both sides to compare content words.
FILLERS = frozenset("呃嗯啊哦噢唉诶欸哎呀吧呢嘛哈")
MODES = ("strict", "nofill")
BOOTSTRAP_ROUNDS = 2000
_BOOTSTRAP_CELLS = 1_000_000
_CN_DIGIT = dict(zip("0123456789", "零一二三四五六七八九", strict=True))
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
Progress = Callable[[str, int, int], None]


@dataclass(frozen=True)
class Item:
    id: str
    audio: Path
    text: str
    duration: float
    group: str


@dataclass(frozen=True)
class Engine:
    name: str
    kind: str
    python: Path
    model: str | None = None
    options: dict[str, Any] = field(default_factory=dict)
    pack: Path | None = None  # installed asr-funasr pack whose models the pack engines load

    @property
    def script(self) -> Path:
        return ENGINE_ROOT / KINDS[self.kind]


def load_manifest(path: Path) -> list[Item]:
    """JSON lines of {id, audio (relative to the manifest), text, duration, group?}; ids unique, audio present."""
    items: list[Item] = []
    seen: set[str] = set()
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict) or not all(isinstance(row.get(k), str) for k in ("id", "audio", "text")):
            raise ValueError(f"清单第 {number} 行缺少 id/audio/text")
        if row["id"] in seen:
            raise ValueError(f"清单第 {number} 行 id 重复")
        duration = row.get("duration")
        if not isinstance(duration, int | float) or isinstance(duration, bool) or not duration > 0:
            raise ValueError(f"清单第 {number} 行 duration 无效")
        audio = path.parent / row["audio"]
        if not audio.is_file():
            raise ValueError(f"清单第 {number} 行音频不存在")
        group = row.get("group", row["id"])
        seen.add(row["id"])
        items.append(Item(row["id"], audio.resolve(), row["text"], float(duration), str(group)))
    if not items:
        raise ValueError("清单为空")
    return items


def select_items(items: Sequence[Item], split: str, size: int = DEFAULT_SIZE, seed: str = DEFAULT_SEED) -> list[Item]:
    """`formal` and `dev` are disjoint fixed samples of about `size` items; whole groups go to one side."""
    if split not in SPLITS:
        raise ValueError(f"split 必须是 {'/'.join(SPLITS)}")
    if split == "full":
        return list(items)
    if size < 1:
        raise ValueError("size 必须为正数")
    groups: dict[str, list[Item]] = {}
    for item in items:
        groups.setdefault(item.group, []).append(item)
    order = sorted(groups, key=lambda g: hashlib.sha256(f"{seed}\x1f{g}".encode()).hexdigest())
    formal: list[Item] = []
    dev: list[Item] = []
    for group in order:
        target = formal if len(formal) < size else dev if len(dev) < size else None
        if target is None:
            break
        target.extend(sorted(groups[group], key=lambda item: item.id))
    return formal if split == "formal" else dev


def load_engines(path: Path, funasr_pack: Path) -> list[Engine]:
    """TOML [[engine]] tables: name, kind, python, model, options, pack. The first engine is the baseline.

    `funasr_pack` is the installed asr-funasr version directory; sensevoice and paraformer engines use its venv and
    models unless `pack` names another version directory (packs up to 1.1.0 recognize with SenseVoice, from 1.2.0
    with Paraformer).
    """
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    rows = data.get("engine")
    if not isinstance(rows, list) or not rows:
        raise ValueError("引擎配置需要至少一个 [[engine]]")
    engines: list[Engine] = []
    for row in rows:
        name, kind = row.get("name"), row.get("kind")
        if not isinstance(name, str) or not _NAME.fullmatch(name) or any(e.name == name for e in engines):
            raise ValueError(f"引擎名称无效或重复：{name!r}")
        if kind not in KINDS:
            raise ValueError(f"未知引擎类型 {kind!r}；可选 {'/'.join(KINDS)}")
        pack_row = row.get("pack")
        if pack_row is not None and (kind not in PACK_KINDS or not isinstance(pack_row, str)):
            raise ValueError(f"引擎 {name} 的 pack 只用于 {'/'.join(PACK_KINDS)}，且必须是路径字符串")
        pack = (Path(pack_row).expanduser() if pack_row else funasr_pack) if kind in PACK_KINDS else None
        python = row.get("python")
        if python is None and pack is not None:
            python = str(pack / "venv" / "bin" / "python")
        model = row.get("model")
        if not isinstance(python, str) or (model is not None and not isinstance(model, str)):
            raise ValueError(f"引擎 {name} 的 python/model 必须是路径字符串")
        if kind not in PACK_KINDS and model is None:
            raise ValueError(f"引擎 {name} 需要 model（本机模型目录）")
        options = row.get("options", {})
        if not isinstance(options, dict):
            raise ValueError(f"引擎 {name} 的 options 必须是表")
        resolved = str(Path(model).expanduser().resolve()) if model is not None else None
        engines.append(Engine(name, kind, Path(python).expanduser(), resolved, options, pack))
    return engines


def _sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def engine_identity(engine: Engine) -> dict[str, Any]:
    """Everything that can change a transcript: engine code, package versions, model files, decode options."""
    if not engine.python.is_file():
        raise ValueError(f"引擎 {engine.name} 的 Python 不存在：{engine.python}")
    probe = subprocess.run(
        [str(engine.python), "-I", str(engine.script), "--identify"], capture_output=True, text=True, check=False
    )
    if probe.returncode != 0:
        raise RuntimeError(f"引擎 {engine.name} 自检失败：{probe.stderr.strip()[-500:]}")
    versions = json.loads(probe.stdout.strip().splitlines()[-1])["versions"]
    if engine.kind in PACK_KINDS:
        pack = engine.pack or Path()
        model = {"pack": _sha256(pack / "pack.toml") if (pack / "pack.toml").is_file() else None}
    else:
        root = Path(engine.model or "")
        model = {
            "path": str(root),
            **{name: _sha256(root / name) for name in _MODEL_FILES if (root / name).is_file()},
        }
    return {
        "kind": engine.kind,
        "script": _sha256(engine.script),
        "versions": versions,
        "model": model,
        "options": engine.options,
    }


def _open_append(path: Path) -> TextIO:
    """Owner-only append; a partial last line from a killed run is terminated so the next row stays parseable."""
    torn = False
    if path.is_file() and path.stat().st_size > 0:
        with path.open("rb") as existing:
            existing.seek(-1, os.SEEK_END)
            torn = existing.read(1) != b"\n"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    os.chmod(path, 0o600)
    stream = os.fdopen(fd, "a", encoding="utf-8")
    if torn:
        stream.write("\n")
    return stream


def _read_cache(path: Path) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue  # a run killed mid-write leaves at most one partial last line
            if isinstance(row, dict) and isinstance(row.get("id"), str) and isinstance(row.get("text"), str):
                rows[row["id"]] = row
    return rows


def transcribe(
    engine: Engine,
    items: Sequence[Item],
    cache_dir: Path,
    log_dir: Path,
    progress: Progress | None = None,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Return {id: {text, seconds}} for every item, running the engine only on items missing from its cache."""
    identity = engine_identity(engine)
    private_directory(cache_dir)
    cache = cache_dir / f"{engine.name}-{fingerprint(identity)[:12]}.jsonl"
    done = _read_cache(cache)
    todo = [item for item in items if item.id not in done]
    if progress is not None:
        progress(engine.name, len(items) - len(todo), len(items))
    if todo:
        request: dict[str, Any] = {
            "model": engine.model,
            "options": engine.options,
            "items": [{"id": i.id, "audio": str(i.audio), "duration": i.duration} for i in todo],
        }
        if engine.kind in PACK_KINDS:
            request["pack"] = str(engine.pack)
        private_directory(log_dir)
        wanted = {item.id for item in todo}
        with open_private(log_dir / f"{engine.name}.log") as log, _open_append(cache) as sink:
            process = subprocess.Popen(
                [str(engine.python), "-I", str(engine.script)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=log,
                text=True,
                encoding="utf-8",
            )
            assert process.stdin is not None and process.stdout is not None
            process.stdin.write(json.dumps(request, ensure_ascii=False))
            process.stdin.close()
            finished = len(items) - len(todo)
            for line in process.stdout:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue  # stray library output; engines keep results on stdout and logs on stderr
                if not isinstance(row, dict) or row.get("id") not in wanted or not isinstance(row.get("text"), str):
                    continue
                sink.write(json.dumps(row, ensure_ascii=False) + "\n")
                sink.flush()
                done[row["id"]] = row
                finished += 1
                if progress is not None:
                    progress(engine.name, finished, len(items))
            code = process.wait()
        if code != 0:
            raise RuntimeError(f"引擎 {engine.name} 退出码 {code}，日志见 {log_dir / (engine.name + '.log')}")
        missing = wanted - done.keys()
        if missing:
            raise RuntimeError(f"引擎 {engine.name} 有 {len(missing)} 条没有返回结果")
    return {item.id: done[item.id] for item in items}, identity


def score_tokens(text: str) -> list[str]:
    """Same normalization as the y15 speech scorer: NFKC, lower case, 5.5→五点五, each digit as a Chinese numeral,
    then Han characters and Latin words as tokens; punctuation and spaces never count."""
    value = unicodedata.normalize("NFKC", text).lower()
    value = re.sub(r"(?<=\d)\.(?=\d)", "点", value)
    value = re.sub(r"\d", lambda m: _CN_DIGIT[m.group()], value)
    return re.findall(r"[㐀-鿿]|[a-z]+(?:'[a-z]+)?", value)


def edit_counts(ref: Sequence[str], hyp: Sequence[str]) -> tuple[int, int, int]:
    """(substitutions, deletions, insertions) of a minimum edit alignment; ties prefer substitution, then deletion."""
    n, m = len(ref), len(hyp)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        dp[i][0] = i
    for j in range(m + 1):
        dp[0][j] = j
    for i in range(1, n + 1):
        row, above, r = dp[i], dp[i - 1], ref[i - 1]
        for j in range(1, m + 1):
            row[j] = min(above[j - 1] + (r != hyp[j - 1]), above[j] + 1, row[j - 1] + 1)
    sub = dele = ins = 0
    i, j = n, m
    while i or j:
        if i and j and dp[i][j] == dp[i - 1][j - 1] + (ref[i - 1] != hyp[j - 1]):
            sub += ref[i - 1] != hyp[j - 1]
            i, j = i - 1, j - 1
        elif i and dp[i][j] == dp[i - 1][j] + 1:
            dele += 1
            i -= 1
        else:
            ins += 1
            j -= 1
    return sub, dele, ins


def _tokens(text: str, mode: str) -> list[str]:
    tokens = score_tokens(text)
    return [t for t in tokens if t not in FILLERS] if mode == "nofill" else tokens


def _rng(seed: str) -> np.random.Generator:
    return np.random.default_rng(int(hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16], 16))


def bootstrap_ratio(numerator: np.ndarray, denominator: np.ndarray, seed: str) -> tuple[float, float]:
    """95% percentile interval of sum(numerator)/sum(denominator) over groups resampled with replacement."""
    count = numerator.size
    rng = _rng(seed)
    rows = max(1, _BOOTSTRAP_CELLS // count)
    ratios: list[np.ndarray] = []
    done = 0
    while done < BOOTSTRAP_ROUNDS:
        batch = min(rows, BOOTSTRAP_ROUNDS - done)
        draws = rng.integers(0, count, size=(batch, count))
        ratios.append(numerator[draws].sum(axis=1) / np.maximum(denominator[draws].sum(axis=1), 1))
        done += batch
    low, high = np.percentile(np.concatenate(ratios), [2.5, 97.5])
    return float(low), float(high)


def _by_group(items: Sequence[Item], values: Sequence[int]) -> np.ndarray:
    sums: dict[str, int] = {}
    for item, value in zip(items, values, strict=True):
        sums[item.group] = sums.get(item.group, 0) + value
    return np.asarray([sums[g] for g in sorted(sums)], dtype=np.float64)


def score(
    items: Sequence[Item], engines: Sequence[Engine], outputs: dict[str, dict[str, dict[str, Any]]], seed: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, dict[str, list[int]]]]:
    """Per-engine corpus CER with group-bootstrap intervals, and paired comparisons of each engine to the first."""
    errors: dict[str, dict[str, list[int]]] = {}
    results: list[dict[str, Any]] = []
    lengths: dict[str, list[int]] = {mode: [len(_tokens(i.text, mode)) for i in items] for mode in MODES}
    group_lengths = {mode: _by_group(items, lengths[mode]) for mode in MODES}
    audio = sum(item.duration for item in items)
    for engine in engines:
        rows = outputs[engine.name]
        metrics: dict[str, Any] = {}
        errors[engine.name] = {}
        for mode in MODES:
            counts = [edit_counts(_tokens(i.text, mode), _tokens(rows[i.id]["text"], mode)) for i in items]
            total = max(sum(lengths[mode]), 1)
            per_item = [sum(c) for c in counts]
            errors[engine.name][mode] = per_item
            low, high = bootstrap_ratio(_by_group(items, per_item), group_lengths[mode], f"{seed}:{engine.name}:{mode}")
            metrics[mode] = {
                "cer": sum(per_item) / total,
                "ci95": [low, high],
                "substitution": sum(c[0] for c in counts) / total,
                "deletion": sum(c[1] for c in counts) / total,
                "insertion": sum(c[2] for c in counts) / total,
                "reference_tokens": sum(lengths[mode]),
            }
        seconds = sum(float(rows[i.id].get("seconds") or 0.0) for i in items)
        results.append(
            {
                "engine": engine.name,
                "metrics": metrics,
                "rtf": seconds / audio if audio else None,
                "empty_outputs": sum(1 for i in items if not score_tokens(rows[i.id]["text"]) and score_tokens(i.text)),
            }
        )
    comparisons: list[dict[str, Any]] = []
    baseline = engines[0].name
    for engine in engines[1:]:
        entry: dict[str, Any] = {"baseline": baseline, "candidate": engine.name}
        for mode in MODES:
            a, b = errors[baseline][mode], errors[engine.name][mode]
            better = sum(x > y for x, y in zip(a, b, strict=True))
            worse = sum(x < y for x, y in zip(a, b, strict=True))
            diff = [y - x for x, y in zip(a, b, strict=True)]
            low, high = bootstrap_ratio(
                _by_group(items, diff), group_lengths[mode], f"{seed}:{baseline}:{engine.name}:{mode}"
            )
            entry[mode] = {
                "cer_difference": sum(diff) / max(sum(lengths[mode]), 1),
                "ci95": [low, high],
                "items_better": better,
                "items_worse": worse,
                "sign_test_p": mcnemar_exact_p(better, worse),
            }
        comparisons.append(entry)
    return results, comparisons, errors


def run_benchmark(
    manifest: Path,
    engines: Sequence[Engine],
    out: Path,
    *,
    split: str = "dev",
    size: int = DEFAULT_SIZE,
    seed: str = DEFAULT_SEED,
    cache_dir: Path,
    progress: Progress | None = None,
) -> dict[str, Any]:
    items = select_items(load_manifest(manifest), split, size, seed)
    outputs: dict[str, dict[str, dict[str, Any]]] = {}
    identities: dict[str, dict[str, Any]] = {}
    for engine in engines:
        outputs[engine.name], identities[engine.name] = transcribe(engine, items, cache_dir, out / "logs", progress)
    results, comparisons, errors = score(items, engines, outputs, seed)
    card = {
        "version": 1,
        "manifest": {"name": manifest.name, "sha256": _sha256(manifest)},
        "split": split,
        "size": size if split != "full" else None,
        "seed": seed if split != "full" else None,
        "items": len(items),
        "audio_hours": sum(i.duration for i in items) / 3600,
        "normalization": "NFKC, lower, digits→汉字 one by one, punctuation dropped; nofill also drops "
        + "".join(sorted(FILLERS)),
        "host": {"machine": platform.machine(), "processor": _processor()},
        "date": dt.datetime.now(dt.UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "engines": [
            {
                **result,
                "kind": engine.kind,
                "identity": fingerprint(identities[engine.name])[:12],
                "details": identities[engine.name],
            }
            for engine, result in zip(engines, results, strict=True)
        ],
        "comparisons": comparisons,
    }
    write_outputs(out, card, items, engines, outputs, errors)
    return card


def _processor() -> str:
    try:
        return subprocess.run(
            ["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return platform.processor()


def write_outputs(
    out: Path,
    card: dict[str, Any],
    items: Sequence[Item],
    engines: Sequence[Engine],
    outputs: dict[str, dict[str, dict[str, Any]]],
    errors: dict[str, dict[str, list[int]]],
) -> None:
    """scorecard.json/.md hold aggregates only; items.jsonl holds references and transcripts and stays private."""
    private_directory(out)
    with open_private(out / "scorecard.json") as stream:
        stream.write(json.dumps(card, ensure_ascii=False, indent=2))
    with open_private(out / "scorecard.md") as stream:
        stream.write(render_markdown(card))
    with open_private(out / "items.jsonl") as stream:
        for k, item in enumerate(items):
            row = {
                "id": item.id,
                "reference": item.text,
                **{
                    e.name: {"text": outputs[e.name][item.id]["text"], "errors": errors[e.name]["strict"][k]}
                    for e in engines
                },
            }
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")


def _pct(value: float) -> str:
    return f"{100 * value:.2f}%"


def render_markdown(card: dict[str, Any]) -> str:
    sample = f"{card['split']} {card['items']} 条 / {card['audio_hours']:.2f} 小时"
    lines = [
        "# ASR 评测成绩单",
        "",
        f"清单 `{card['manifest']['name']}`（sha256 {card['manifest']['sha256'][:12]}），样本 {sample}，"
        f"{card['host']['processor']}，{card['date']}。",
        "",
        "| 引擎 | 严格 CER | 95% 区间 | 去口头语 CER | 替换 / 删除 / 插入 | RTF | 空输出 | 身份 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for engine in card["engines"]:
        strict, nofill = engine["metrics"]["strict"], engine["metrics"]["nofill"]
        low, high = strict["ci95"]
        rtf = f"{engine['rtf']:.4f}" if engine["rtf"] is not None else "—"
        lines.append(
            f"| {engine['engine']} | {_pct(strict['cer'])} | {_pct(low)}–{_pct(high)} | {_pct(nofill['cer'])} | "
            f"{_pct(strict['substitution'])} / {_pct(strict['deletion'])} / {_pct(strict['insertion'])} | "
            f"{rtf} | {engine['empty_outputs']} | `{engine['identity']}` |"
        )
    if card["comparisons"]:
        lines += [
            "",
            "## 与基线逐条配对比较",
            "",
            "CER 差 = 候选 − 基线，负数表示候选更好；区间为按组 bootstrap；符号检验看逐条错字数变好/变差的条数。",
            "",
            "| 候选 | 口径 | CER 差 | 95% 区间 | 变好 / 变差 | 符号检验 p |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for comparison in card["comparisons"]:
            for mode in MODES:
                entry = comparison[mode]
                low, high = entry["ci95"]
                lines.append(
                    f"| {comparison['candidate']} | {mode} | {100 * entry['cer_difference']:+.2f} 点 | "
                    f"{100 * low:+.2f}–{100 * high:+.2f} | {entry['items_better']} / {entry['items_worse']} | "
                    f"{entry['sign_test_p']:.2g} |"
                )
    lines += ["", f"归一化：{card['normalization']}。", ""]
    return "\n".join(lines)
