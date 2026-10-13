"""The L4 experiment must not change attribution or silently accept malformed edits."""

import argparse
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


def test_prepare_preserves_every_voice_view_without_reading_references(tmp_path, monkeypatch):
    module = load()
    manifest = tmp_path / "sessions.jsonl"
    manifest.write_text(json.dumps({"id": "meeting", "duration": 3, "reference": "must-not-read.json"}))
    rows = [
        {
            "session": "meeting",
            "target": target,
            "segments": segments(),
            "speakers": [{"id": "S1", "similarity": similarity}],
            "seconds": 42,
            "absent": ["visitor"],
        }
        for target, similarity in [("person", 0.7), ("~visitor", 0.1)]
    ]
    base = tmp_path / "base.jsonl"
    base.write_text("\n".join(json.dumps(row) for row in rows))
    config = tmp_path / "config.toml"
    config.write_text('[llm]\nmodel="fake"\n')
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("faithful")
    calls = []

    def complete(**kwargs):
        calls.append(kwargs)
        return {
            "payload": {"edits": [{"id": 0, "text": "我们讨论语音识别。"}]},
            "cached": False,
            "usage": {},
            "seconds": 1,
        }

    monkeypatch.setattr(module, "complete", complete)
    out = tmp_path / "clean.jsonl"
    args = argparse.Namespace(
        public_alimeeting=True,
        sessions=manifest,
        base_cache=base,
        config=config,
        prompt=prompt,
        out=out,
        cache=tmp_path / "cache",
        batch=80,
        workers=1,
        effort="low",
        guard=0.25,
    )
    module.prepare(args)
    assert len(calls) == 1
    assert "reference" not in calls[0]["user"]
    for before, after in zip(rows, module.read_rows(out), strict=True):
        assert {k: v for k, v in before.items() if k != "segments"} == {
            k: v for k, v in after.items() if k != "segments"
        }
        assert after["segments"][0] == {**before["segments"][0], "text": "我们讨论语音识别。"}
        assert after["segments"][1] == before["segments"][1]
    assert out.stat().st_mode & 0o777 == 0o600
    args.public_alimeeting = False
    with pytest.raises(ValueError):
        module.prepare(args)


def test_completion_cache_avoids_network_on_rerun(tmp_path, monkeypatch):
    module = load()
    import httpx

    calls = []

    def post(*args, **kwargs):
        calls.append(kwargs)
        return httpx.Response(
            200,
            json={
                "choices": [{"finish_reason": "stop", "message": {"content": '{"edits":[]}'}}],
                "usage": {"total_tokens": 10},
            },
        )

    monkeypatch.setattr(module.httpx, "post", post)
    monkeypatch.setenv("TEST_CLEAN_KEY", "test-only")
    kwargs = dict(
        config={"model": "fake", "base_url": "http://local.invalid/v1", "api_key_env": "TEST_CLEAN_KEY"},
        prompt="faithful",
        user="public fixture",
        effort="low",
        cache=tmp_path,
    )
    first = module.complete(**kwargs)
    second = module.complete(**kwargs)
    assert not first["cached"] and second["cached"]
    assert first["payload"] == second["payload"] == {"edits": []}
    assert len(calls) == 1
    assert "test-only" not in next(tmp_path.glob("*.json")).read_text()


def test_transient_failures_retry_with_backoff(tmp_path, monkeypatch):
    module = load()
    import httpx

    replies = iter(
        [
            httpx.Response(429, headers={"Retry-After": "45"}),
            httpx.Response(503),
            httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": '{"edits":[]}'}}]}),
        ]
    )
    delays = []
    monkeypatch.setattr(module.httpx, "post", lambda *a, **k: next(replies))
    monkeypatch.setattr(module.time, "sleep", delays.append)
    monkeypatch.setenv("TEST_CLEAN_KEY", "test-only")
    result = module.complete(
        config={"model": "fake", "base_url": "http://local.invalid/v1", "api_key_env": "TEST_CLEAN_KEY"},
        prompt="faithful",
        user="public fixture",
        effort="low",
        cache=tmp_path,
    )
    assert result["payload"] == {"edits": []}
    assert delays == [45, 60]
    assert result["attempts"] == 3
