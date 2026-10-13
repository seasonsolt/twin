"""The L4 experiment must not change attribution or silently accept malformed edits."""

import importlib.util
import json
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "llm_clean", Path(__file__).resolve().parents[1] / "deploy/asr-eval/llm_clean.py"
)
assert SPEC and SPEC.loader
clean = importlib.util.module_from_spec(SPEC)


def load():
    SPEC.loader.exec_module(clean)
    return clean


def segments():
    return [
        {"start": 0, "end": 2, "speaker": "S1", "text": "我们讨论于音识别。"},
        {"start": 2, "end": 3, "speaker": "S2", "text": "嗯对对对。"},
    ]


def test_apply_only_changes_text_and_preserves_fillers():
    module = load()
    original = segments()
    result, rejected = module.apply_edits(original, {"edits": [{"id": 0, "text": "我们讨论语音识别。"}]}, {0, 1}, 0.25)
    assert result[0] == {**original[0], "text": "我们讨论语音识别。"}
    assert result[1] == original[1]
    assert original == segments()
    assert rejected == 0


@pytest.mark.parametrize(
    "edits",
    [
        [{"id": 3, "text": "未知"}],
        [{"id": 0, "text": "甲"}, {"id": 0, "text": "乙"}],
        [{"id": True, "text": "甲"}],
        [{"id": 0, "text": 123}],
        [{"id": 0, "text": "甲", "speaker": "S2"}],
    ],
)
def test_invalid_edits_fail_closed(edits):
    with pytest.raises(ValueError):
        load().apply_edits(segments(), {"edits": edits}, {0, 1}, 0.25)


def test_guard_rejects_large_changes_and_context_edits():
    module = load()
    result, rejected = module.apply_edits(segments(), {"edits": [{"id": 0, "text": "完全不同的内容"}]}, {0}, 0.25)
    assert result == segments()
    assert rejected == 1
    with pytest.raises(ValueError):
        module.apply_edits(segments(), {"edits": [{"id": 1, "text": "对"}]}, {0}, 0.25)


def test_replay_reconstructs_all_voice_views(tmp_path):
    rows = [
        {
            "session": "meeting",
            "target": target,
            "segments": segments(),
            "speakers": [{"id": "S1", "seconds": 2, "similarity": similarity}],
            "seconds": 1,
        }
        for target, similarity in [("person", 0.7), ("other", 0.2), ("@absent:visitor", 0.1)]
    ]
    cache = tmp_path / "clean.jsonl"
    cache.write_text("\n".join(json.dumps(row) for row in rows))
    request = {
        "audio": "/public/meeting.wav",
        "reference": "/public/person.wav",
        "references": {"other": "/public/other.wav", "@absent:visitor": "/public/visitor.wav"},
    }
    payload = load().replay(cache, request)
    assert payload["segments"] == segments()
    assert payload["speakers"][0] == {**rows[0]["speakers"][0], "similarities": {"other": 0.2, "@absent:visitor": 0.1}}
    with pytest.raises(ValueError):
        load().replay(cache, {**request, "audio": "/private/unknown.wav"})


def test_cache_key_includes_prompt_input_model_and_options():
    module = load()
    kwargs = dict(model="model", prompt="prompt", user="text", effort="low", endpoint="local")
    key = module.cache_key(**kwargs)
    for field in kwargs:
        assert module.cache_key(**{**kwargs, field: "changed"}) != key
