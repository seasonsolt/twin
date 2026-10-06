"""Offline deployment-shim endpoints and the real B2 HTTP adapter contract."""

from __future__ import annotations

import builtins
import importlib.util
import io
import logging
import random
import sys
import time
import wave
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from pathlib import Path
from threading import Lock
from types import ModuleType, SimpleNamespace
from typing import Any
from urllib.error import HTTPError, URLError

import numpy as np
import pytest
from fastapi.testclient import TestClient

from twin.media.schema import SpeechRequest, SpeechResult, VoiceSpec
from twin.media.tts import MediaRejected, OpenAICompatSpeech

SERVER_PATH = Path(__file__).resolve().parents[1] / "deploy" / "tts-moss" / "server.py"


@pytest.fixture
def shim(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    monkeypatch.delenv("SHIM_API_KEY", raising=False)
    original_import = builtins.__import__

    def guarded_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name.split(".", 1)[0] in {"torch", "torchaudio", "transformers", "huggingface_hub"}:
            raise AssertionError("Offline shim tests must not import ML dependencies")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    spec = importlib.util.spec_from_file_location("twin_test_tts_shim", SERVER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def client(shim: ModuleType) -> Iterator[TestClient]:
    with TestClient(shim.create_app(shim.FakeEngine())) as instance:
        yield instance


def payload(shim: ModuleType, **updates: object) -> dict[str, object]:
    return {"model": shim.MODEL_ID, "input": "你好，世界。", "voice": "Junhao", "response_format": "wav", **updates}


def test_import_and_engine_construction_are_lazy(shim: ModuleType) -> None:
    engine = shim.MossNanoEngine()
    assert engine.voices() == []
    assert "Trump" not in shim.FakeEngine().voices()
    assert "Sakura" not in shim.FakeEngine().voices()
    assert "default" not in shim.FakeEngine().voices()


def test_request_seeds_are_stable_and_depend_on_text_voice_revision(shim: ModuleType) -> None:
    assert shim.synthesis_seed("revision", "voice", "text") == 1630311344
    calls: list[tuple[str, str, int]] = []

    class RecordingFake(shim.FakeEngine):
        def synthesize(self, text: str, voice: str, *, seed: int) -> tuple[bytes, int]:
            calls.append((text, voice, seed))
            pcm, rate = super().synthesize(text, voice, seed=seed)
            return pcm, rate

    with TestClient(shim.create_app(RecordingFake())) as instance:
        first = instance.post("/v1/audio/speech", json=payload(shim, input="第一句"))
        assert instance.post("/v1/audio/speech", json=payload(shim, input="另一句")).status_code == 200
        again = instance.post("/v1/audio/speech", json=payload(shim, input="第一句"))
        assert instance.post("/v1/audio/speech", json=payload(shim, input="第一句", voice="Ava")).status_code == 200
    assert first.status_code == again.status_code == 200 and first.content == again.content
    seeds = [seed for _, _, seed in calls]
    assert seeds[0] == seeds[2] == shim.synthesis_seed(shim.MODEL_REVISION, "Junhao", "第一句")
    assert len(set(seeds)) == 3
    assert all(0 <= seed < 2**32 for seed in seeds)
    assert seeds[0] != shim.synthesis_seed("new-revision", "Junhao", "第一句")
    assert shim.synthesis_seed("ab", "c", "d") != shim.synthesis_seed("a", "bc", "d")


@pytest.mark.parametrize(
    ("durations", "expected_attempts", "selected", "warning"),
    [
        ([2.0, 0.1, 0.1], 1, 0, False),
        ([0.1, 2.0, 0.1], 2, 1, False),
        ([0.1, 0.2, 2.0], 3, 2, False),
        ([0.3, 0.5, 0.4], 3, 1, True),
        ([0.5, 0.5, 0.5], 3, 0, True),
    ],
)
def test_completeness_guard_retry_cap_longest_and_stable_seed_sequence(
    shim: ModuleType,
    caplog: pytest.LogCaptureFixture,
    durations: list[float],
    expected_attempts: int,
    selected: int,
    warning: bool,
) -> None:
    text = "这是完整合成句子"
    seeds = [shim.synthesis_seed(shim.MODEL_REVISION, "Junhao", text, attempt) for attempt in range(3)]
    calls: list[int] = []

    class ShortFake(shim.FakeEngine):
        def synthesize(self, text: str, voice: str, *, seed: int) -> tuple[bytes, int]:
            calls.append(seed)
            attempt = seeds.index(seed)
            return bytes([attempt + 1, 0]) * round(durations[attempt] * 1000), 1000

    with TestClient(shim.create_app(ShortFake())) as instance, caplog.at_level(logging.INFO):
        first = instance.post("/v1/audio/speech", json=payload(shim, input=text))
        second = instance.post("/v1/audio/speech", json=payload(shim, input=text))
    assert first.status_code == second.status_code == 200 and first.content == second.content
    assert calls == seeds[:expected_attempts] * 2
    assert len(set(seeds)) == 3
    assert first.headers.get("X-Speech-Warning") == ("possibly-truncated" if warning else None)
    with wave.open(io.BytesIO(first.content), "rb") as audio:
        assert audio.getnframes() == round(durations[selected] * 1000)
        assert audio.readframes(1) == bytes([selected + 1, 0])
    assert f"attempts={expected_attempts}" in caplog.text and text not in caplog.text


@pytest.mark.parametrize("text", ["你好AI！", "１２３４５，！", "？！"])
def test_completeness_guard_skips_inputs_below_six_speakable_chars(shim: ModuleType, text: str) -> None:
    calls: list[int] = []

    class ShortFake(shim.FakeEngine):
        def synthesize(self, text: str, voice: str, *, seed: int) -> tuple[bytes, int]:
            calls.append(seed)
            return b"\0\0", 1000

    with TestClient(shim.create_app(ShortFake())) as instance:
        response = instance.post("/v1/audio/speech", json=payload(shim, input=text))
    assert response.status_code == 200 and "X-Speech-Warning" not in response.headers
    assert len(calls) == 1


def test_speakable_nfkc_count_and_exact_duration_threshold(shim: ModuleType) -> None:
    assert shim.speakable_characters("请用AI辅助整理，但不要生成新的事实。") == 17
    assert shim.speakable_characters("ＡＩ 和１２，𠀀é！") == 7
    assert shim.speakable_characters("？！— 😀") == 0
    assert shim.MIN_SECONDS_PER_CHAR == 0.15 and shim.MIN_SPEAKABLE_CHARS == 6
    assert shim.MAX_SYNTHESIS_ATTEMPTS == 3
    calls: list[int] = []

    class ThresholdFake(shim.FakeEngine):
        def synthesize(self, text: str, voice: str, *, seed: int) -> tuple[bytes, int]:
            calls.append(seed)
            return b"\0\0" * 900, 1000  # Exactly 0.15 seconds for each of six chars.

    with TestClient(shim.create_app(ThresholdFake())) as instance:
        response = instance.post("/v1/audio/speech", json=payload(shim, input="一二三四五六"))
    assert response.status_code == 200 and len(calls) == 1
    assert "X-Speech-Warning" not in response.headers


@pytest.mark.parametrize("voice", ["Junhao", "self-0123456789abcdef"])
def test_moss_resets_all_rngs_before_inference_without_changing_sampling(
    shim: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, voice: str
) -> None:
    torch_seeds: list[int] = []
    torch_stub = SimpleNamespace(manual_seed=torch_seeds.append, inference_mode=nullcontext)
    previous_import = builtins.__import__

    def mocked_import(name: str, *args: Any, **kwargs: Any) -> Any:
        return torch_stub if name == "torch" else previous_import(name, *args, **kwargs)

    observations: list[tuple[float, float, dict[str, Any]]] = []

    def inference(**kwargs: Any) -> None:
        observations.append((random.random(), float(np.random.random()), kwargs))
        raise RuntimeError("Stop before waveform handling; no real model in this test")

    monkeypatch.setenv("TTS_VOICE_DIR", str(tmp_path / "voices"))
    (tmp_path / "voices").mkdir()
    reference = tmp_path / "voices" / "self-0123456789abcdef.wav"
    reference.write_bytes(b"reference")
    engine = shim.MossNanoEngine(tmp_path)
    engine._model = SimpleNamespace(inference=inference)
    engine._available_voices = ["Junhao"]
    python_state, numpy_state = random.getstate(), np.random.get_state()
    try:
        monkeypatch.setattr(builtins, "__import__", mocked_import)
        with TestClient(shim.create_app(engine)) as instance:
            for text in ["第一句", "另一句", "第一句"]:
                assert instance.post("/v1/audio/speech", json=payload(shim, input=text, voice=voice)).status_code == 503
        assert torch_seeds[0] == torch_seeds[2] != torch_seeds[1]
        assert observations[0][:2] == observations[2][:2] != observations[1][:2]
        assert torch_seeds[0] == shim.synthesis_seed(shim.MODEL_REVISION, voice, "第一句")
        for _, _, kwargs in observations:
            assert kwargs["do_sample"] is True
            assert kwargs["max_new_frames"] == 375
            assert kwargs["device"] == "cpu"
            expected = (
                reference if voice.startswith("self-") else tmp_path / "presets" / shim.PRESET_REVISION / "zh_1.wav"
            )
            assert kwargs["prompt_audio_path"] == str(expected)
            assert not any("temperature" in key or "top_" in key or "repetition_penalty" in key for key in kwargs)
    finally:
        random.setstate(python_state)
        np.random.set_state(numpy_state)


def test_preset_mapping_matches_pinned_runtime_and_existing_assets(shim: ModuleType) -> None:
    assert shim.PRESET_FILES == {
        "Junhao": "zh_1.wav",
        "Xiaoyu": "zh_3.wav",
        "Yuewen": "zh_4.wav",
        "Lingyu": "zh_6.wav",
        "Ava": "en_2.wav",
        "Bella": "en_3.wav",
        "Adam": "en_4.wav",
        "Yui": "jp_2.wav",
    }
    files = list(shim.PRESET_FILES.values())
    assert all(filename.endswith(".wav") for filename in files)
    assert len(files) == len(set(files))
    assert "Trump" not in shim.PRESET_FILES
    assert "Sakura" not in shim.PRESET_FILES


@pytest.mark.parametrize("all_missing", [False, True])
def test_startup_with_failed_preset_downloads(
    shim: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    all_missing: bool,
) -> None:
    engine = shim.MossNanoEngine(tmp_path)
    model_loads: list[bool] = []

    def load_models() -> None:
        model_loads.append(True)
        engine._model = object()
        engine._text_tokenizer = object()
        engine._audio_tokenizer = object()

    monkeypatch.setattr(engine, "_load_models", load_models)
    soundfile = ModuleType("soundfile")

    def info(path: str) -> SimpleNamespace:
        with wave.open(path, "rb") as audio:
            return SimpleNamespace(frames=audio.getnframes())

    monkeypatch.setattr(soundfile, "info", info, raising=False)
    monkeypatch.setitem(sys.modules, "soundfile", soundfile)
    attempted: list[str] = []
    missing = set(shim.PRESET_FILES) if all_missing else {"Xiaoyu", "Bella", "Adam"}
    filenames = {filename: name for name, filename in shim.PRESET_FILES.items()}

    def downloader(url: str, timeout: int) -> io.BytesIO:
        assert timeout == 120
        name = filenames[url.rsplit("/", 1)[1]]
        attempted.append(name)
        if name in missing:
            if name == "Bella":
                raise URLError("private-network-error")
            if name == "Adam":
                return io.BytesIO(b"invalid-wav-private-error")
            raise HTTPError(url + "?token=private-token", 404, "Not Found", None, None)
        return io.BytesIO(shim.make_wav(b"\0\0" * 16, 48000))

    monkeypatch.setattr(shim, "urlopen", downloader)
    expected = [name for name in shim.PRESET_FILES if name not in missing]
    with caplog.at_level(logging.WARNING), TestClient(shim.create_app(engine)) as instance:
        assert model_loads == [True]
        assert attempted == list(shim.PRESET_FILES)
        assert engine.voices() == expected
        voices = instance.get("/v1/voices")
        assert voices.status_code == 200
        assert voices.json() == {"voices": expected}
        assert "Trump" not in voices.text
        health = instance.get("/healthz")
        assert health.status_code == (503 if all_missing else 200)
        assert health.json() == (
            {"status": "degraded", "reason": "no voices available"} if all_missing else {"status": "ok"}
        )
        for name in missing:
            assert instance.post("/v1/audio/speech", json=payload(shim, voice=name)).status_code == 400
        # Unavailable voices do not trigger download attempts on requests or repeated load calls.
        engine.load()
        assert model_loads == [True]
        assert attempted == list(shim.PRESET_FILES)
    records = [record.getMessage() for record in caplog.records if record.name == "uvicorn.error.tts"]
    assert records == [f"preset unavailable: {name}" for name in shim.PRESET_FILES if name in missing]
    assert "private-" not in caplog.text
    assert "https://" not in caplog.text
    preset_dir = tmp_path / "presets" / shim.PRESET_REVISION
    assert {path.name for path in preset_dir.iterdir()} == {shim.PRESET_FILES[name] for name in expected}


@pytest.mark.parametrize("component", ["model", "text tokenizer", "audio tokenizer"])
def test_model_tokenizer_startup_failure_is_fatal_and_logged_once(
    shim: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    component: str,
) -> None:
    engine = shim.MossNanoEngine(tmp_path)

    def fail_load() -> None:
        raise RuntimeError(f"{component}: private-token")

    monkeypatch.setattr(engine, "_load_models", fail_load)
    message = "TTS startup failed: model/tokenizer load failure"
    with (
        caplog.at_level(logging.ERROR),
        pytest.raises(RuntimeError, match=message),
        TestClient(shim.create_app(engine)),
    ):
        pytest.fail("Model/tokenizer failure must abort startup")
    records = [record.getMessage() for record in caplog.records if record.name == "uvicorn.error.tts"]
    assert records == [message]
    assert "private-token" not in caplog.text


def test_discovery_and_health(client: TestClient, shim: ModuleType) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    response = client.get("/v1/models")
    assert response.status_code == 200
    assert response.json() == {
        "object": "list",
        "data": [{"id": shim.MODEL_ID, "object": "model", "created": 0, "owned_by": "local"}],
    }
    response = client.get("/v1/voices")
    assert response.status_code == 200
    assert response.json() == {"voices": list(shim.PRESET_FILES)}
    assert len(response.json()["voices"]) == 8
    assert "Trump" not in response.text


def test_wav_for_every_preset_is_deterministic(client: TestClient, shim: ModuleType) -> None:
    for voice in shim.PRESET_FILES:
        response = client.post("/v1/audio/speech", json=payload(shim, voice=voice))
        assert response.status_code == 200
        assert response.headers["content-type"] == "audio/wav"
        assert response.headers["cache-control"] == "no-store"
        assert response.content == client.post("/v1/audio/speech", json=payload(shim, voice=voice)).content
        with wave.open(io.BytesIO(response.content), "rb") as audio:
            assert audio.getnchannels() == 1
            assert audio.getsampwidth() == 2
            assert audio.getframerate() == 48000
            assert audio.getnframes() / audio.getframerate() == pytest.approx(0.08 * len("你好，世界。"))
            assert set(audio.readframes(audio.getnframes())) == {0}


def test_default_response_format_is_wav(client: TestClient, shim: ModuleType) -> None:
    body = payload(shim)
    del body["response_format"]
    response = client.post("/v1/audio/speech", json=body)
    assert response.status_code == 200
    assert response.content.startswith(b"RIFF")


@pytest.mark.parametrize(
    ("updates", "status"),
    [
        ({"model": "other-model"}, 400),
        ({"voice": "unknown"}, 400),
        ({"voice": "Trump"}, 400),
        ({"voice": "../../sensitive.wav"}, 400),
        ({"input": ""}, 400),
        ({"input": " \n\t"}, 400),
        ({"input": "长" * 1001}, 413),
        ({"response_format": "mp3"}, 400),
        ({"response_format": "pcm"}, 400),
        ({"input": 123}, 422),
        ({"input": None}, 422),
        ({"voice": ["Junhao"]}, 422),
        ({"reference_audio": "private-audio"}, 422),
        ({"reference_audio_path": "/private/audio.wav"}, 422),
        ({"prompt_audio_path": "/private/audio.wav"}, 422),
        ({"prompt_text": "private-transcript"}, 422),
        ({"mode": "voice_clone"}, 422),
        ({"speed": 1.0}, 422),
    ],
)
def test_rejected_speech(client: TestClient, shim: ModuleType, updates: dict[str, object], status: int) -> None:
    response = client.post("/v1/audio/speech", json=payload(shim, **updates))
    assert response.status_code == status
    assert isinstance(response.json()["detail"], str)
    if updates.get("response_format") == "mp3":
        assert "wav" in response.json()["detail"] and "mp3" in response.json()["detail"]


@pytest.mark.parametrize("field", ["model", "voice", "input"])
def test_missing_fields(client: TestClient, shim: ModuleType, field: str) -> None:
    body = payload(shim)
    del body[field]
    assert client.post("/v1/audio/speech", json=body).status_code == 422


def test_malformed_json_and_exact_character_limit(client: TestClient, shim: ModuleType) -> None:
    response = client.post("/v1/audio/speech", content="{", headers={"content-type": "application/json"})
    assert response.status_code == 422
    assert client.post("/v1/audio/speech", json=payload(shim, input="字" * 1000)).status_code == 200


@pytest.mark.parametrize("path", ["/v1/audio/clone", "/v1/audio/voices", "/v1/voice-clone"])
def test_no_cloning_routes(client: TestClient, path: str) -> None:
    assert client.post(path, json={"reference_audio": "private-audio"}).status_code == 404


def test_optional_auth_on_every_endpoint(shim: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHIM_API_KEY", "local-secret")
    with TestClient(shim.create_app(shim.FakeEngine())) as instance:
        for path in ("/healthz", "/v1/models", "/v1/voices", "/v1/audio/speech"):
            for header in (None, "Bearer incorrect", "Basic local-secret", "Bearer ", "Bearer local-secret-extra"):
                headers = {} if header is None else {"Authorization": header}
                response = (
                    instance.post(path, json=payload(shim), headers=headers)
                    if path.endswith("speech")
                    else instance.get(path, headers=headers)
                )
                assert response.status_code == 401
                assert response.headers["www-authenticate"] == "Bearer"
                assert "local-secret" not in response.text
            headers = {"Authorization": "Bearer local-secret"}
            response = (
                instance.post(path, json=payload(shim), headers=headers)
                if path.endswith("speech")
                else instance.get(path, headers=headers)
            )
            assert response.status_code == 200


def test_disabled_auth_accepts_adapter_placeholder_token(client: TestClient, shim: ModuleType) -> None:
    response = client.post("/v1/audio/speech", json=payload(shim), headers={"Authorization": "Bearer EMPTY"})
    assert response.status_code == 200


@pytest.mark.parametrize("bad_pcm", [b"", b"\0", b"\0\0"])
def test_engine_failures_are_sanitized(shim: ModuleType, caplog: pytest.LogCaptureFixture, bad_pcm: bytes) -> None:
    class BrokenEngine:
        def voices(self) -> list[str]:
            return ["Junhao"]

        def synthesize(self, text: str, voice: str, *, seed: int) -> tuple[bytes, int]:
            if bad_pcm == b"\0\0":
                raise RuntimeError(text + " secret-token")
            return bad_pcm, 48000

    sensitive = "这段请求包含保密资料"
    with TestClient(shim.create_app(BrokenEngine())) as instance, caplog.at_level(logging.INFO):
        response = instance.post("/v1/audio/speech", json=payload(shim, input=sensitive))
    assert response.status_code == 503
    assert sensitive not in response.text + caplog.text
    assert "secret-token" not in response.text + caplog.text
    assert "chars=" in caplog.text and "elapsed_s=" in caplog.text


@pytest.mark.parametrize("rate", [0, -1, True, 48000.5])
def test_invalid_engine_sample_rate(shim: ModuleType, rate: object) -> None:
    with pytest.raises(ValueError):
        shim.make_wav(b"\0\0", rate)


def test_success_and_validation_do_not_log_text(
    client: TestClient, shim: ModuleType, caplog: pytest.LogCaptureFixture
) -> None:
    sensitive = "隐私正文不应进入日志"
    with caplog.at_level(logging.INFO):
        assert client.post("/v1/audio/speech", json=payload(shim, input=sensitive)).status_code == 200
        response = client.post("/v1/audio/speech", json=payload(shim, reference_audio=sensitive))
    assert response.status_code == 422
    assert sensitive not in caplog.text + response.text
    records = [record.getMessage() for record in caplog.records if record.name == "uvicorn.error.tts"]
    assert len(records) == 1
    assert records[0].startswith(f"speech chars={len(sensitive)} attempts=3 elapsed_s=")


def test_engine_calls_are_serialized(shim: ModuleType) -> None:
    class SerializedEngine:
        def __init__(self) -> None:
            self.guard = Lock()
            self.active = 0
            self.maximum = 0

        def voices(self) -> list[str]:
            return ["Junhao"]

        def synthesize(self, text: str, voice: str, *, seed: int) -> tuple[bytes, int]:
            with self.guard:
                self.active += 1
                self.maximum = max(self.maximum, self.active)
            time.sleep(0.01)
            with self.guard:
                self.active -= 1
            return b"\0\0" * 4800, 48000

    engine = SerializedEngine()
    with TestClient(shim.create_app(engine)) as instance, ThreadPoolExecutor(max_workers=6) as pool:
        responses = list(pool.map(lambda _: instance.post("/v1/audio/speech", json=payload(shim)), range(12)))
    assert all(response.status_code == 200 for response in responses)
    assert engine.maximum == 1


def test_owner_voice_directory_is_rescanned_and_rejects_paths(
    shim: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("TTS_VOICE_DIR", str(tmp_path))
    engine = shim.MossNanoEngine(tmp_path / "cache")
    engine._available_voices = ["Junhao"]
    with TestClient(shim.create_app(shim.FakeEngine())) as instance:
        assert instance.get("/v1/voices").json()["voices"] == list(shim.PRESET_FILES)
        valid = tmp_path / "self-0123456789abcdef.wav"
        valid.write_bytes(b"reference")
        for name in ("self-abcd.wav", "self-0123456789ABCDEF.wav", "self-0123456789abcdef.mp3", "preset.wav"):
            (tmp_path / name).write_bytes(b"invalid name")
        (tmp_path / "self-1111111111111111.wav").mkdir()
        (tmp_path / "self-2222222222222222.wav").symlink_to(valid)
        assert engine.voices() == ["Junhao", valid.stem]
        assert instance.get("/v1/voices").json()["voices"] == [*shim.PRESET_FILES, valid.stem]
        assert instance.post("/v1/audio/speech", json=payload(shim, voice=valid.stem)).status_code == 200
        for voice in ("../" + valid.stem, str(valid), valid.name, "self-0123456789ABCDEF"):
            assert instance.post("/v1/audio/speech", json=payload(shim, voice=voice)).status_code == 400
        valid.unlink()
        assert instance.post("/v1/audio/speech", json=payload(shim, voice=valid.stem)).status_code == 400
        assert engine.voices() == ["Junhao"]


def test_end_to_end_openai_adapter_contract(shim: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    key = "contract-secret"
    monkeypatch.setenv("SHIM_API_KEY", key)
    monkeypatch.setenv("TWIN_TTS_KEY", key)
    voice = VoiceSpec(voice_id="Junhao", language="zh", label="预置中文音色")
    with TestClient(shim.create_app(shim.FakeEngine())) as instance:
        synth = OpenAICompatSpeech(
            model=shim.MODEL_ID, base_url="http://testserver/v1", client=instance, voice=voice, max_retries=0
        )
        request = SpeechRequest(text="你好，世界。", voice=voice, audio_format="wav")
        result = synth.synthesize(request)
        assert isinstance(result, SpeechResult)
        assert result.schema_version == 1
        assert result.audio_format == request.audio_format
        assert result.audio and result.timings is None
        assert result.sample_rate == 48000
        assert result.duration_s == pytest.approx(len(request.text) * 0.08)
        assert result.extras == {}
        assert key not in synth.identity and "http://testserver/v1" not in synth.identity
        assert not synth.capabilities.streaming
        with wave.open(io.BytesIO(result.audio), "rb") as audio:
            assert audio.getframerate() == result.sample_rate
            assert audio.getnframes() / audio.getframerate() == pytest.approx(result.duration_s)
            assert audio.getnchannels() == 1 and audio.getsampwidth() == 2
        with pytest.raises(MediaRejected):
            synth.synthesize(request.model_copy(update={"audio_format": "mp3"}))
