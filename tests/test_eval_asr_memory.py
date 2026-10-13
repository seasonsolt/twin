from pathlib import Path

import pytest
from pydantic import BaseModel

from twin.config import Settings
from twin.evals.asr_memory import CachedLLM, JudgeDraft, judge_counts, memory_items, speech_lines, summarize
from twin.evals.asr_session import Run, Session
from twin.evals.diarization import Utterance
from twin.llm import FakeLLM
from twin.media.claim import Speaker


def test_end_to_end_isolated_fake_run_and_resume(tmp_path):
    import json

    from twin.evals.asr_memory import run_memory_benchmark

    (tmp_path / "audio.wav").touch()
    (tmp_path / "voice.wav").touch()
    seg = {"start": 0, "end": 1, "speaker": "A", "text": "喜欢蓝色"}
    (tmp_path / "ref.json").write_text(json.dumps({"segments": [seg]}))
    manifest = tmp_path / "sessions.jsonl"
    manifest.write_text(
        json.dumps(
            {
                "id": "fiction",
                "audio": "audio.wav",
                "reference": "ref.json",
                "duration": 1,
                "references": {"A": "voice.wav"},
            }
        )
    )
    base = tmp_path / "base.jsonl"
    base.write_text(
        json.dumps(
            {
                "session": "fiction",
                "target": "A",
                "segments": [seg],
                "seconds": 1,
                "speakers": [{"id": "A", "seconds": 1, "similarity": 0.8}],
            }
        )
    )

    def handler(system, user, schema):
        if schema.__name__ == "ExtractDraft":
            return {"items": [{"facet_id": "1.1", "statement": "喜欢蓝色", "quotes": [{"n": 1, "quote": "喜欢蓝色"}]}]}
        return {"gold": [[0, [0], False, False]], "candidate": [[0, [0], "supported", False, False]]}

    llm = FakeLLM(handler)
    kwargs = dict(
        manifest=manifest,
        base_cache=base,
        clean_cache=base,
        out=tmp_path / "out",
        cache=tmp_path / "cache",
        settings=Settings(),
        llm=llm,
        workers=1,
    )
    first = run_memory_benchmark(**kwargs)
    assert first["arms"]["clean"]["f1"] == 1
    assert first["cost"]["cache_hits"] == 0
    row = json.loads((tmp_path / "out/items.jsonl").read_text())
    assert row["texts"]["asr"] == "[00:00] 喜欢蓝色"
    assert row["texts"]["gold"] == row["texts"]["asr"]
    calls = len(llm.calls)
    assert run_memory_benchmark(**kwargs)["cost"]["cache_hits"] == calls
    assert len(llm.calls) == calls
    assert (tmp_path / "out/items.jsonl").stat().st_mode & 0o777 == 0o600
    second = {**json.loads(manifest.read_text()), "id": "unselected", "duration": 999}
    manifest.write_text(manifest.read_text() + "\n" + json.dumps(second))
    assert run_memory_benchmark(**kwargs, limit=1)["cost"]["audio_hours"] == pytest.approx(1 / 3600)


def test_cli_exposes_public_eval_command():
    from typer.testing import CliRunner

    from twin.cli import app

    result = CliRunner().invoke(app, ["eval-asr-memory", "--help"])
    assert result.exit_code == 0
    assert "public-alimeeting" in result.stdout


def test_speech_matches_l5_fallback_and_keeps_other_context():
    utterances = [Utterance(0, 1, "A", "喜欢蓝色"), Utterance(2, 3, "B", "我喜欢绿色")]
    session = Session("fiction", Path("unused"), 3, utterances, {"A": Path("voice")})
    run = Run(
        [Utterance(0, 1, "S1", "喜欢蓝色"), Utterance(2, 3, "S2", "我喜欢绿色")],
        [Speaker(id="S1", seconds=1, similarity=0.1), Speaker(id="S2", seconds=1, similarity=0.2)],
        1,
    )
    lines = speech_lines(session, "A", run)
    assert [text for _, text, own in lines if own] == ["[00:00] 喜欢蓝色"]
    assert any(not own for _, _, own in lines)
    assert speech_lines(session, "A", None)[0][2]


def test_real_extraction_and_merge_use_fictional_media_only():
    def handler(system, user, schema):
        assert "人格档案" in system
        assert "本人：" in user
        return {"items": [{"facet_id": "1.1", "statement": "喜欢蓝色", "quotes": [{"n": 1, "quote": "喜欢蓝色"}]}]}

    llm = FakeLLM(handler)
    result = memory_items([("本人", "[0:00] 喜欢蓝色", True)], llm, Settings())
    assert len(result) == 1
    assert result[0]["statement"] == "喜欢蓝色"
    assert len(llm.calls) == 1


def test_production_merge_conflict_is_kept_for_judging():
    import re

    def handler(system, user, schema):
        if schema.__name__ == "ExtractDraft":
            return {
                "items": [
                    {"facet_id": "1.1", "statement": color, "quotes": [{"n": 1, "quote": color}]}
                    for color in ("喜欢蓝色", "喜欢红色")
                ]
            }
        return {
            "items": [
                {
                    "statement": "颜色偏好不一致",
                    "conflict": "两种偏好缺少情境区分",
                    "candidate_ids": sorted(set(re.findall(r"pc_[0-9a-f]+", user))),
                }
            ]
        }

    items = memory_items([("本人", "喜欢蓝色，喜欢红色", True)], FakeLLM(handler), Settings())
    assert items[0]["conflict"] == "两种偏好缺少情境区分"


def test_cache_replicates_are_independent_but_reruns_free(tmp_path):
    class Reply(BaseModel):
        value: int

    llm = FakeLLM(lambda *_: {"value": 1})
    a = CachedLLM(llm, tmp_path, "gold0", "identity")
    b = CachedLLM(llm, tmp_path, "gold1", "identity")
    for wrapper in [a, a, b]:
        assert wrapper.structured(system="s", user="u", schema=Reply).value == 1
    assert len(llm.calls) == 2
    assert all(p.stat().st_mode & 0o777 == 0o600 for p in tmp_path.glob("*.json"))


def test_transient_retry_does_not_cache_or_log_error_messages(tmp_path, monkeypatch):
    from twin.evals import asr_memory
    from twin.llm import LLMError

    class Reply(BaseModel):
        value: int

    class RateLimit(Exception):
        status_code = 429

    attempts = []
    delays = []

    def handler(*_):
        attempts.append(1)
        if len(attempts) == 1:
            raise LLMError("sensitive-error-marker") from RateLimit()
        return {"value": 1}

    monkeypatch.setattr(asr_memory.time, "sleep", delays.append)
    wrapper = CachedLLM(FakeLLM(handler), tmp_path, "replica", "identity")
    assert wrapper.structured(system="s", user="u", schema=Reply).value == 1
    assert delays == [30]
    assert "sensitive-error-marker" not in next(tmp_path.glob("*.json")).read_text()


def test_compact_judge_expands_without_changing_decisions():
    from twin.evals.asr_memory import CompactJudge

    wire = CompactJudge.model_validate(
        {
            "gold": [[0, [1], True, False]],
            "candidate": [[0, [], "garbled", False, False], [1, [0], "supported", True, False]],
        }
    )
    draft = wire.expand()
    assert draft.gold[0].matches == [1]
    assert draft.candidate[0].status == "garbled"
    assert judge_counts(draft, 1, 2)["precision"] == 0.5


def test_judge_requires_complete_valid_ids_and_separates_unsupported():
    d = JudgeDraft.model_validate(
        {
            "gold": [{"id": 0, "matches": [0], "entity": False, "number": True}],
            "candidate": [
                {"id": 0, "matches": [0], "status": "supported", "entity": False, "number": True},
                {"id": 1, "matches": [], "status": "unsupported", "entity": True, "number": False},
            ],
        }
    )
    c = judge_counts(d, 1, 2)
    assert c["recall"] == 1 and c["precision"] == 0.5
    assert c["f1"] == pytest.approx(2 / 3)
    assert c["unsupported"] == 1
    assert c["number_gold_count"] == 1
    assert c["entity_candidate_count"] == 1
    with pytest.raises(ValueError):
        judge_counts(d, 2, 2)
    assert judge_counts(JudgeDraft(gold=[], candidate=[]), 0, 0)["f1"] is None


def test_judge_repairs_incomplete_coverage_once():
    from twin.evals.asr_memory import judge

    def handler(system, user, schema):
        if "校验失败" not in user:
            return {"gold": [], "candidate": []}
        return {"gold": [[0, [0], False, False]], "candidate": [[0, [0], "supported", False, False]]}

    llm = FakeLLM(handler)
    counts, _ = judge(llm, [{"statement": "喜欢蓝色"}], [{"statement": "喜欢蓝色"}])
    assert counts["f1"] == 1
    assert len(llm.calls) == 2


def test_pairing_uses_people_and_session_cluster_ci():
    rows = []
    for session in ["s1", "s2"]:
        rows.append(
            {
                "session": session,
                "target": "p",
                "scores": {
                    name: [{"precision": x, "recall": x, "f1": x}] * 2
                    for name, x in [("gold_repeat", 0.9), ("asr", 0.5), ("clean", 0.6)]
                },
            }
        )
    result = summarize(rows)
    assert result["paired"]["f1"]["difference"] == pytest.approx(0.1)
    assert result["paired"]["f1"]["better"] == 2
    assert result["paired"]["f1"]["ci95"] == pytest.approx([0.1, 0.1])
