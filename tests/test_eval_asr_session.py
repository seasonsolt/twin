"""Whole-session ASR benchmark: manifests, the [asr] command contract, run caching, claims and the scorecard."""

import json
import sys
from pathlib import Path

import pytest

from twin.evals.asr_session import load_session_engines, load_sessions, run_session_benchmark

# A stand-in for a twin [asr] command: replies with canned segments per audio file, gives S1 a high similarity
# whenever a reference voice is sent, and logs every request so tests can count runs.
FAKE_COMMAND = """
import json, sys
from pathlib import Path
plan = json.loads(Path(sys.argv[1]).read_text())
request = json.load(sys.stdin)
with open(sys.argv[2], "a") as log:
    log.write(json.dumps({"audio": Path(request["audio"]).stem, "reference": bool(request.get("reference"))}) + "\\n")
segments = plan[Path(request["audio"]).stem]
ids = sorted({s["speaker"] for s in segments})
speakers = [
    {"id": i, "seconds": 1.0, "similarity": (0.8 if i == "S1" else 0.3) if request.get("reference") else None}
    for i in ids
]
print(json.dumps({"ok": True, "segments": segments, "speakers": speakers}))
"""

REFERENCES = {
    "s1": [
        {"start": 0, "end": 5, "speaker": "A", "text": "甲乙丙丁戊"},
        {"start": 5, "end": 8, "speaker": "B", "text": "己庚辛"},
    ],
    "s2": [
        {"start": 0, "end": 4, "speaker": "A", "text": "一二三四"},
        {"start": 4, "end": 8, "speaker": "C", "text": "五六七八"},
    ],
}
GOOD = {
    "s1": [
        {"start": 0, "end": 5, "speaker": "S1", "text": "甲乙丙丁戊"},
        {"start": 5, "end": 8, "speaker": "S2", "text": "己庚辛"},
    ],
    "s2": [
        {"start": 0, "end": 4, "speaker": "S1", "text": "一二三四"},
        {"start": 4, "end": 8, "speaker": "S2", "text": "五六七八"},
    ],
}
# Merges both people of s1 into one speaker, so the twin keeps B's words as A's.
MERGED = {
    "s1": [{"start": 0, "end": 8, "speaker": "S1", "text": "甲乙丙丁戊己庚辛"}],
    "s2": GOOD["s2"],
}


def _setup(tmp_path: Path) -> tuple[Path, Path, Path]:
    data = tmp_path / "data"
    (data / "sessions").mkdir(parents=True)
    (data / "voices").mkdir()
    (data / "voices" / "A.wav").write_bytes(b"RIFF")
    rows = []
    for session, segments in REFERENCES.items():
        (data / "sessions" / f"{session}.wav").write_bytes(b"RIFF")
        (data / "sessions" / f"{session}.json").write_text(json.dumps({"segments": segments}), encoding="utf-8")
        row = {
            "id": session,
            "audio": f"sessions/{session}.wav",
            "duration": 8.0,
            "reference": f"sessions/{session}.json",
            # A's voice came from s2, so A is evaluated as the person only in s1.
            "references": {"A": "voices/A.wav"} if session == "s1" else {},
        }
        rows.append(json.dumps(row))
    manifest = data / "sessions.jsonl"
    manifest.write_text("\n".join(rows) + "\n", encoding="utf-8")
    script = tmp_path / "fake.py"
    script.write_text(FAKE_COMMAND, encoding="utf-8")
    engines = tmp_path / "engines.toml"
    blocks = []
    for name, plan in (("good", GOOD), ("merged", MERGED)):
        plan_file = tmp_path / f"{name}.json"
        plan_file.write_text(json.dumps(plan), encoding="utf-8")
        command = f"{sys.executable} {script} {plan_file} {tmp_path / 'calls.jsonl'}"
        blocks.append(f'[[engine]]\nname = "{name}"\ncommand = "{command}"\nfiles = ["{plan_file}"]\n')
    engines.write_text("\n".join(blocks), encoding="utf-8")
    return manifest, engines, tmp_path / "calls.jsonl"


def _calls(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text().splitlines()] if path.is_file() else []


def test_load_sessions_reads_references_and_voices(tmp_path: Path) -> None:
    manifest, _, _ = _setup(tmp_path)
    sessions = load_sessions(manifest)
    assert [s.id for s in sessions] == ["s1", "s2"]
    assert [u.speaker for u in sessions[0].reference] == ["A", "B"]
    assert list(sessions[0].voices) == ["A"]
    assert sessions[1].voices == {}


def test_load_sessions_rejects_unknown_person(tmp_path: Path) -> None:
    manifest, _, _ = _setup(tmp_path)
    row = json.loads(manifest.read_text().splitlines()[0])
    row["references"] = {"Z": "voices/A.wav"}
    manifest.write_text(json.dumps(row) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Z 不在参考说话人中"):
        load_sessions(manifest)


def test_load_session_engines_validates(tmp_path: Path) -> None:
    path = tmp_path / "e.toml"
    path.write_text('[[engine]]\nname = "x"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="需要 command"):
        load_session_engines(path)
    path.write_text('[[engine]]\nname = "x"\ncommand = "true"\nfiles = ["/no/such/file"]\n', encoding="utf-8")
    with pytest.raises(ValueError, match="files 不存在"):
        load_session_engines(path)


def test_benchmark_scores_layers_and_caches_runs(tmp_path: Path) -> None:
    manifest, engines, calls = _setup(tmp_path)
    out, cache = tmp_path / "out", tmp_path / "cache"
    card = run_session_benchmark(manifest, load_session_engines(engines), out, cache_dir=cache)

    # One run per evaluated person (s1: A with a reference voice) or one plain run (s2), per engine.
    assert sorted((c["audio"], c["reference"]) for c in _calls(calls)) == [
        ("s1", True),
        ("s1", True),
        ("s2", False),
        ("s2", False),
    ]
    good, merged = card["engines"]
    assert good["segmentation"]["strict"]["cer"]["rate"] == 0
    assert good["speakers"]["der_0.25"]["rate"] == 0
    assert good["speakers"]["strict"]["cpcer"]["rate"] == 0
    assert good["speakers"]["claims"] == {"correct": 1, "wrong": 0, "none": 0, "suggested_correct": 1, "people": 1}
    assert good["person"]["strict"]["cer"]["rate"] == 0
    assert good["person"]["strict"]["misattributed"] == 0
    assert good["person"]["auto_claimed"] == 1

    # Merging s1 keeps the words right (session CER 0) but loses B as a speaker.
    assert merged["segmentation"]["strict"]["cer"]["rate"] == 0
    assert merged["speakers"]["der_0.25"]["rate"] > 0
    assert merged["speakers"]["strict"]["cpcer"]["rate"] == pytest.approx(6 / 16)  # 3 insertions + 3 deletions
    assert merged["speakers"]["claims"]["correct"] == 1  # the lone speaker is mostly A and is auto-claimed
    assert merged["person"]["strict"]["cer"]["rate"] == pytest.approx(3 / 5)  # B's three characters inserted
    assert merged["person"]["strict"]["misattributed"] == pytest.approx(3 / 8)

    comparison = card["comparisons"][0]
    assert comparison["candidate"] == "merged"
    assert comparison["cpcer"]["worse"] == 1 and comparison["cpcer"]["better"] == 0

    text = (out / "scorecard.md").read_text(encoding="utf-8")
    for heading in ("L2 切分层", "L3 说话人层", "L5 流程层", "层间损失", "与基线逐场配对比较"):
        assert heading in text
    assert (out / "items.jsonl").stat().st_mode & 0o777 == 0o600

    # A rerun with unchanged engines only rescores.
    before = len(_calls(calls))
    again = run_session_benchmark(manifest, load_session_engines(engines), tmp_path / "out2", cache_dir=cache)
    assert len(_calls(calls)) == before
    assert again["engines"][1]["speakers"]["strict"]["cpcer"] == merged["speakers"]["strict"]["cpcer"]


def test_engine_identity_changes_with_hashed_files(tmp_path: Path) -> None:
    manifest, engines, calls = _setup(tmp_path)
    cache = tmp_path / "cache"
    run_session_benchmark(manifest, load_session_engines(engines)[:1], tmp_path / "o1", cache_dir=cache)
    before = len(_calls(calls))
    plan = tmp_path / "good.json"
    plan.write_text(plan.read_text() + " ", encoding="utf-8")
    run_session_benchmark(manifest, load_session_engines(engines)[:1], tmp_path / "o2", cache_dir=cache)
    assert len(_calls(calls)) == before + 2
