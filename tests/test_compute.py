"""Offline lifecycle coverage for the command compute pack."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import tomllib
import urllib.error
import urllib.request
import wave
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from twin import cli
from twin.config import ASRSettings, Settings, load_settings
from twin.ops import compute
from twin.ops.doctor import inspect_installation
from twin.ops.paths import TwinPaths, compute_defaults
from twin.ops.service import LaunchdManager


@pytest.fixture
def environment(tmp_path, monkeypatch):
    monkeypatch.setenv("TWIN_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("TWIN_COMPUTE_HOME", str(tmp_path / "shared compute"))
    monkeypatch.setenv("MODELSCOPE_CACHE", str(tmp_path / "models"))
    monkeypatch.setenv("TWIN_ENV_FILE", str(tmp_path / "absent-env"))
    monkeypatch.delenv("TWIN_CONFIG", raising=False)
    monkeypatch.setattr(compute.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(compute.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(compute.shutil, "which", lambda command: command)
    monkeypatch.chdir(tmp_path)
    config = tmp_path / "twin.toml"
    config.write_text('# 原样保留\ntarget_name = "本人"\n\n[embed] # 注释\nprovider = "hashing"\n')
    pack = compute.discover()[0]
    model = {
        "id": "test/model",
        "revision": "master",
        "files": [{"path": "weight", "size": 6, "sha256": hashlib.sha256(b"weight").hexdigest()}],
    }
    pack = replace(pack, models=[model])
    path = compute.model_directory(model, compute.model_cache()) / "weight"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"weight")
    return pack, config, path


class FakeRunner:
    def __init__(self, fail=None, download=None):
        self.calls = []
        self.fail = fail
        self.download = download

    def __call__(self, args):
        self.calls.append(args)
        if self.fail and self.fail(args):
            raise subprocess.CalledProcessError(1, args)
        if args[:2] == ["uv", "venv"]:
            python = Path(args[-1]) / "bin/python"
            python.parent.mkdir(parents=True)
            python.write_text("fake python")
        if "-c" in args and self.download:
            self.download.write_bytes(b"weight")
        return subprocess.CompletedProcess(args, 0, 'dependency noise\n{"ok": true}\n', "")


def test_discover_manifest_and_lock():
    packs = compute.discover()
    assert [p.name for p in packs] == ["asr-funasr"]
    pack = packs[0]
    assert (pack.version, pack.kind, pack.python, pack.entry) == ("1.5.4", "command", "3.12", "run.py")
    assert pack.platforms == ("darwin-arm64",)
    assert len(pack.models) == 4 and pack.model_bytes > 2_000_000_000
    assert sorted(m["role"] for m in pack.models) == ["asr", "punc", "speaker", "vad"]
    assert all(len(f["sha256"]) == 64 for m in pack.models for f in m["files"])
    assert "scikit-learn==" in (pack.source / "requirements-darwin-arm64.lock").read_text()
    assert "am.mvn" in {f["path"] for m in pack.models for f in m["files"]}
    assert {"overlap.py", "diarize.py", "segmentation.py", "THIRD_PARTY.md"} <= set(pack.files)
    with pytest.raises(ValueError, match="未知"):
        compute.get_pack("../bad")


@pytest.mark.parametrize("name", ["../run.py", "/etc/hosts", "missing.py"])
def test_discover_rejects_pack_files_outside_or_missing(tmp_path, name):
    copy = tmp_path / "asr-funasr"
    shutil.copytree(compute.PACK_ROOT / "asr-funasr", copy)
    assert [p.name for p in compute.discover(tmp_path)] == ["asr-funasr"]
    text = (copy / "pack.toml").read_text().replace("files = [\n", f'files = [\n  "{name}",\n', 1)
    (copy / "pack.toml").write_text(text)
    with pytest.raises(ValueError, match="算力包文件无效"):
        compute.discover(tmp_path)


def test_paths_override(environment, monkeypatch, tmp_path):
    assert TwinPaths.from_env().compute == tmp_path / "shared compute"
    assert str(tmp_path / "shared compute") in compute_defaults()["asr_command"]
    monkeypatch.delenv("TWIN_COMPUTE_HOME")
    assert TwinPaths.from_env().compute == tmp_path / "home/compute"


def test_install_reuse_switch_and_status(environment):
    pack, config, _ = environment
    runner = FakeRunner()
    target = compute.install(pack, config, runner=runner)
    assert runner.calls[0][:2] == ["uv", "venv"]
    assert runner.calls[1][:3] == ["uv", "pip", "install"]
    assert runner.calls[2][-1] == "--check"
    assert len(runner.calls) == 3
    assert (target.parent / "current").resolve() == target
    for name in pack.files:  # modules run.py imports and the bundled weights, in their own folders
        assert (target / name).read_bytes() == (pack.source / name).read_bytes()
    assert load_settings(config).asr.command == compute_defaults()["asr_command"]
    original = config.read_bytes()
    compute.install(pack, config, download_models=True, runner=runner)
    assert len(runner.calls) == 4 and runner.calls[-1][-1] == "--check"
    assert config.read_bytes() == original
    status = compute.status(pack, config)
    assert "已安装" in status and "版本 1.5.4" in status and "指向当前安装" in status and "模型齐全" in status
    text = config.read_text()
    command = tomllib.loads(text)["asr"]["command"]
    config.write_text(text.replace(json.dumps(command), json.dumps(command + " --device mps")))
    assert "未指向当前安装" not in compute.status(pack, config)


@pytest.mark.parametrize("step", ["venv", "pip", "--check"])
def test_install_failure_preserves_previous(environment, step):
    pack, config, _ = environment
    old = compute.install(pack, config, runner=FakeRunner())
    old_config = config.read_bytes()
    new = replace(pack, version="9.9.9")
    with pytest.raises(ValueError, match="已保留旧安装"):
        compute.install(new, config, runner=FakeRunner(fail=lambda args: step in args))
    assert (old.parent / "current").resolve() == old
    assert config.read_bytes() == old_config
    assert not (old.parent / "9.9.9").exists()
    assert not list(old.parent.glob(".9.9.9-*"))


def test_missing_requires_opt_in_and_downloads_once(environment):
    pack, config, weight = environment
    weight.unlink()
    runner = FakeRunner(download=weight)
    original = config.read_bytes()
    with pytest.raises(ValueError, match="--download-models"):
        compute.install(pack, config, runner=runner)
    assert all("-c" not in call for call in runner.calls)
    assert config.read_bytes() == original
    assert not (TwinPaths.from_env().compute / pack.name / pack.version).exists()
    compute.install(pack, config, download_models=True, runner=runner)
    assert sum("-c" in call for call in runner.calls) == 1
    compute.install(pack, config, download_models=True, force=True, runner=runner)
    assert sum("-c" in call for call in runner.calls) == 1


def test_download_hash_failure_and_unhealthy_output(environment):
    pack, config, weight = environment
    weight.write_bytes(b"broken")
    with pytest.raises(ValueError, match="下载后"):
        compute.install(pack, config, download_models=True, runner=FakeRunner())
    weight.write_bytes(b"weight")
    runner = FakeRunner()

    def unhealthy(args):
        result = runner(args)
        return subprocess.CompletedProcess(args, 0, '{"ok":false}', "") if "--check" in args else result

    with pytest.raises(ValueError, match="健康检查失败"):
        compute.install(pack, config, runner=unhealthy)
    assert not (TwinPaths.from_env().compute / pack.name / "current").exists()


def test_verified_cache_and_modified_model(environment, monkeypatch, tmp_path):
    pack, _, weight = environment
    record = tmp_path / "verified.json"
    assert compute.verify_models(pack, compute.model_cache(), record) == []
    original_hash = compute.sha256
    calls = []

    def hashing(path):
        calls.append(path)
        return original_hash(path)

    monkeypatch.setattr(compute, "sha256", hashing)
    assert compute.verify_models(pack, compute.model_cache(), record) == []
    assert calls == []
    old = weight.stat()
    weight.write_bytes(b"broken")
    os.utime(weight, ns=(old.st_atime_ns, old.st_mtime_ns + 1000000))
    assert compute.verify_models(pack, compute.model_cache(), record) == ["test/model"]
    assert calls == [weight]
    assert json.loads(record.read_text()) == {}


def test_config_preserves_comments_idempotent_remove(environment):
    _, config, _ = environment
    original = config.read_bytes()
    compute.write_config(config)
    updated = config.read_bytes()
    assert updated.startswith(original)
    compute.write_config(config)
    assert config.read_bytes() == updated
    assert load_settings(config).asr.egress == "local"
    compute.write_config(config, remove=True)
    assert config.read_bytes() == original
    compute.write_config(config, remove=True)
    assert config.read_bytes() == original


@pytest.mark.parametrize("section", ['[asr]\nprovider="command"\n', '["asr"]\nprovider="command"\n'])
def test_refuse_handwritten_even_with_force(environment, section):
    pack, config, _ = environment
    config.write_text(config.read_text() + section)
    original = config.read_bytes()
    runner = FakeRunner()
    with pytest.raises(ValueError, match="手写"):
        compute.install(pack, config, force=True, runner=runner)
    assert runner.calls == []
    compute.write_config(config, remove=True)
    assert config.read_bytes() == original


def test_invalid_config_restored_and_force_rolls_back(environment, monkeypatch):
    pack, config, _ = environment
    target = compute.install(pack, config, runner=FakeRunner())
    original = config.read_bytes()
    (target / "retained").write_text("old")
    real_load = compute.load_settings

    def invalid(path):
        if not (target / "retained").exists():
            raise ValueError("写入后校验失败")
        return real_load(path)

    # Force a changed command block so post-write validation actually executes.
    config.write_text(original.decode().replace('language = "zh"', 'language = "en"'))
    before = config.read_bytes()
    monkeypatch.setattr(compute, "load_settings", invalid)
    with pytest.raises(ValueError, match="校验失败"):
        compute.install(pack, config, force=True, runner=FakeRunner())
    assert config.read_bytes() == before
    assert (target / "retained").read_text() == "old"
    assert (target.parent / "current").resolve() == target


def test_write_validation_restores_missing_or_existing(environment, monkeypatch, tmp_path):
    _, config, _ = environment
    original = config.read_bytes()

    def reject(_):
        raise ValueError("配置错误")

    monkeypatch.setattr(compute, "load_settings", reject)
    for path in (config, tmp_path / "new.toml"):
        with pytest.raises(ValueError):
            compute.write_config(path)
    assert config.read_bytes() == original
    assert not (tmp_path / "new.toml").exists()


def test_remove_preserves_models_and_other_config(environment):
    pack, config, weight = environment
    original = config.read_bytes()
    target = compute.install(pack, config, runner=FakeRunner())
    result = compute.remove(pack, config)
    assert "模型缓存保留" in result
    assert not target.parent.exists()
    assert weight.read_bytes() == b"weight"
    assert config.read_bytes() == original


def test_cli_config_priority(environment, monkeypatch, tmp_path):
    pack, config, _ = environment
    calls = []
    monkeypatch.setattr(compute, "get_pack", lambda _: pack)
    monkeypatch.setattr(compute, "install", lambda pack, path, **kw: calls.append((path, kw)))
    runner = CliRunner()
    assert runner.invoke(cli.app, ["compute", "list"]).exit_code == 0
    for prefix, expected in (([], config), (["--config", str(tmp_path / "explicit.toml")], tmp_path / "explicit.toml")):
        result = runner.invoke(cli.app, [*prefix, "compute", "install", "asr-funasr", "--force"])
        assert result.exit_code == 0, result.output
        assert calls[-1][0].resolve() == expected and calls[-1][1]["force"]
    monkeypatch.setenv("TWIN_CONFIG", str(tmp_path / "environment.toml"))
    assert runner.invoke(cli.app, ["compute", "install", "asr-funasr"]).exit_code == 0
    assert calls[-1][0] == tmp_path / "environment.toml"


def test_platform_and_tools_preflight(environment, monkeypatch):
    pack, config, _ = environment
    runner = FakeRunner()
    monkeypatch.setattr(compute.platform, "machine", lambda: "x86_64")
    with pytest.raises(ValueError, match="不支持"):
        compute.install(pack, config, runner=runner)
    monkeypatch.setattr(compute.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(compute.shutil, "which", lambda _: None)
    with pytest.raises(ValueError, match="brew install uv"):
        compute.install(pack, config, runner=runner)
    assert runner.calls == []


def test_doctor_missing_script_and_python(environment, monkeypatch, tmp_path):
    _, config, _ = environment
    monkeypatch.setattr(compute.shutil, "which", lambda command: command if command == sys.executable else None)
    paths = TwinPaths.from_env()
    backend = LaunchdManager(paths, lambda args: subprocess.CompletedProcess(args, 1, "", ""))
    for command in (f"{sys.executable} {tmp_path}/missing.py", "/missing/python /missing/run.py"):
        settings = Settings(asr=ASRSettings(provider="command", command=command))
        checks = inspect_installation(paths, settings, config, backend, connect=lambda *_: False)
        check = next(c for c in checks if c.name == "识别")
        assert check.ok is False
        assert "twin compute install asr-funasr" in check.advice


@pytest.fixture
def script():
    path = compute.PACK_ROOT / "asr-funasr/run.py"
    spec = importlib.util.spec_from_file_location("asr_pack", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_script_pure_functions(script, tmp_path, capsys):
    audio = tmp_path / "audio.wav"
    audio.touch()
    assert script.parse_request({"audio": str(audio), "language": "invalid"}) == (
        audio,
        "auto",
        False,
        None,
        [],
        {},
        script.CLUSTER_THRESHOLD,
        None,
    )
    assert script.parse_request({"audio": str(audio), "cluster_threshold": 0.7})[-2] == 0.7
    assert script.parse_request({"audio": str(audio), "pipeline": "classic"})[-1] == "classic"
    with pytest.raises(ValueError, match="pipeline"):
        script.parse_request({"audio": str(audio), "pipeline": "fast"})
    for bad in (True, "0.7", 0.05, 1.0):
        with pytest.raises(ValueError, match="cluster_threshold"):
            script.parse_request({"audio": str(audio), "cluster_threshold": bad})
    for request in ([], {}, {"audio": "relative.wav"}, {"audio": str(audio), "diarize": "yes"}):
        with pytest.raises(ValueError):
            script.parse_request(request)
    # Several voices in one run; a missing voice is skipped like a missing `reference`.
    request = {"audio": str(audio), "references": {"A": str(audio), "B": str(tmp_path / "missing.wav")}}
    assert script.parse_request(request)[-3] == {"A": audio}
    for references in (
        ["x"],
        {"A": 1},
        {"": str(audio)},
        {f"v{i}": str(audio) for i in range(script.MAX_REFERENCES + 1)},
    ):
        with pytest.raises(ValueError, match="references"):
            script.parse_request({"audio": str(audio), "references": references})
    windows, hop, total = script.make_windows([[0, 3000]])
    assert windows == [(0, 0, 1500), (0, 750, 2250), (0, 1500, 3000)]
    assert (hop, total) == (750, 3000)
    spans, labels = script.rebuild_spans(windows, [0, 1, 1])
    assert spans == [[0, 1125], [1125, 3000]] and labels == [0, 1]
    totals, order, names, chunks = script.organize(spans, labels)
    assert order == [1, 0] and names == {1: "S1", 0: "S2"} and totals[1] == 1.875
    assert chunks == [[0, 1125, 0], [1125, 3000, 1]]
    assert script.organize([[0, 1000], [1500, 3000], [4200, 5000]], [0, 0, 0])[-1] == [[0, 3000, 0], [4200, 5000, 0]]
    assert [script.similarity(v) for v in (None, -1, 1.01, float("nan"), 0.7345)] == [None, 0, 1, None, 0.735]
    print("dependency noise")
    script.emit({"ok": True, "segments": [], "speakers": []})
    assert json.loads(capsys.readouterr().out.splitlines()[-1])["ok"] is True
    assert "funasr" not in sys.modules and "torch" not in sys.modules


def test_script_absorbs_small_clusters_only_into_a_clear_match(script):
    import numpy as np

    a, b, c = np.eye(192)[:3]
    tilted = 0.35 * a + np.sqrt(1 - 0.35**2) * c
    between = (a + b) / np.sqrt(2)
    rows = [a] * 10 + [b] * 10 + [a] * 4 + [c] * 4 + [between] + [tilted]
    found = np.array([0] * 10 + [1] * 10 + [2] * 4 + [3] * 4 + [4] + [5])
    result = script.absorb(found, np.stack(rows), {0, 1})
    # Same voice joins; another voice and a voice as close to both stay apart; one window gets the 0.2 allowance.
    assert result.tolist() == [0] * 10 + [1] * 10 + [0] * 4 + [3] * 4 + [4] + [0]
    assert found.tolist()[-1] == 5
    assert script.absorb(found, np.stack(rows), {0}).tolist()[20:] == [0] * 4 + [3] * 4 + [0, 0]
    assert script.absorb(found, np.stack(rows), set(range(6))).tolist() == found.tolist()


def test_script_says_which_version_and_pipeline_made_a_transcript(script):
    class Overlap:
        def transcribe(self, *args):
            return {"ok": True, "segments": []}

    engine = object.__new__(script.Engine)
    engine.overlap = Overlap()
    result = engine.transcribe(Path("a.wav"), True, None, [], lambda f: None)
    assert result == {"ok": True, "segments": [], "version": "1.5.4", "pipeline": "overlap"}
    engine.classic = lambda *args: {"ok": True, "segments": [], "speakers": []}
    assert engine.transcribe(Path("a.wav"), True, None, [], lambda f: None, pipeline="classic")["pipeline"] == "classic"
    engine.overlap = None
    assert engine.transcribe(Path("a.wav"), True, None, [], lambda f: None)["version"] == "1.5.4"
    with pytest.raises(ValueError, match="重叠感知"):
        engine.transcribe(Path("a.wav"), True, None, [], lambda f: None, pipeline="overlap")


def test_script_missing_models_is_json_without_dependencies(tmp_path):
    result = subprocess.run(
        [sys.executable, str(compute.PACK_ROOT / "asr-funasr/run.py"), "--check"],
        env={**os.environ, "MODELSCOPE_CACHE": str(tmp_path)},
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout.splitlines()[-1])
    assert result.returncode == 1 and payload["ok"] is False
    assert "缺少模型" in payload["error"] and "--download-models" in payload["error"]


def test_manifest_has_no_personal_paths():
    text = (compute.PACK_ROOT / "asr-funasr/pack.toml").read_text()
    assert "/Users/" not in text
    assert len(tomllib.loads(text)["models"]) == 4


def test_denoising_is_optional_and_does_not_change_what_transcripts_say(script, tmp_path, monkeypatch):
    manifest = tomllib.loads((compute.PACK_ROOT / "asr-funasr/pack.toml").read_text())
    # Its model is not one the overlap-aware path needs, so a service without it transcribes as before.
    assert [m["role"] for m in manifest["playback_models"]] == ["denoise"]
    assert "denoise" not in {m["role"] for m in manifest["cuda_models"]}
    assert (manifest["version"], manifest["transcription"]) == ("1.5.4", "1.5.4")
    assert script.transcription_version() == "1.5.4"
    monkeypatch.setenv("MODELSCOPE_CACHE", str(tmp_path))
    monkeypatch.setenv("HF_HOME", str(tmp_path))
    assert script.playback_path() is None and script.Playback().available is False
    audio = tmp_path / "a.flac"
    audio.write_bytes(b"x")
    assert script.parse_denoise({"audio": str(audio), "output": str(tmp_path / "b.flac")}) == (
        audio,
        tmp_path / "b.flac",
    )
    for output in ("b.flac", str(tmp_path / "b.wav"), str(tmp_path / "gone" / "b.flac"), None):
        with pytest.raises(ValueError):
            script.parse_denoise({"audio": str(audio), "output": output})
    result = script.denoise_command({"audio": str(audio), "denoise": True, "output": str(tmp_path / "b.flac")})
    assert result["ok"] is False and "不能降噪" in result["error"]


def test_capabilities_answer_without_models(tmp_path):
    result = subprocess.run(
        [sys.executable, str(compute.PACK_ROOT / "asr-funasr/run.py")],
        input=json.dumps({"capabilities": True}),
        env={**os.environ, "MODELSCOPE_CACHE": str(tmp_path), "HF_HOME": str(tmp_path)},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert json.loads(result.stdout.splitlines()[-1]) == {"ok": True, "version": "1.5.4", "denoise": False}


def test_script_hotwords_and_upload(script, tmp_path):
    assert script.parse_hotwords(None) == []
    assert script.parse_hotwords([" 魔搭 ", "", "两 个", "魔搭", "twin"]) == ["魔搭", "twin"]
    assert len(script.parse_hotwords([f"词{i}" for i in range(500)])) == script.MAX_HOTWORDS
    for bad in ("魔搭", [1], {"a": 1}):
        with pytest.raises(ValueError, match="hotwords"):
            script.parse_hotwords(bad)
    header = json.dumps({"diarize": True, "hotwords": ["魔搭"], "audio_bytes": 3, "audio_suffix": ".WAV"}).encode()
    body = header + b"\nabc"
    audio, language, diarize, reference, hotwords, references, threshold, pipeline, spans = script.read_upload(
        io.BytesIO(body), len(body), tmp_path
    )
    assert threshold == script.CLUSTER_THRESHOLD and pipeline is None and spans is None
    assert (audio.name, audio.read_bytes(), language, diarize, reference, hotwords, references) == (
        "audio.wav",
        b"abc",
        "auto",
        True,
        None,
        ["魔搭"],
        {},
    )
    voices = [{"name": "A", "bytes": 2, "suffix": ".wav"}, {"name": "B", "bytes": 1}]
    header = json.dumps(
        {"audio_bytes": 3, "reference_bytes": 1, "references": voices, "cluster_threshold": 0.65, "pipeline": "classic"}
    )
    body = header.encode() + b"\nabcRAAB"
    (tmp_path / "multi").mkdir()
    *_, reference, _, references, threshold, pipeline, _ = script.read_upload(
        io.BytesIO(body), len(body), tmp_path / "multi"
    )
    assert threshold == 0.65 and pipeline == "classic"
    assert reference.read_bytes() == b"R"
    assert {name: path.read_bytes() for name, path in references.items()} == {"A": b"AA", "B": b"B"}
    for meta, data, length in (
        ({"audio_bytes": 3}, b"abc", 99),
        ({"audio_bytes": 0}, b"", None),
        ({"audio_bytes": True}, b"a", None),
        ({"audio_bytes": 3, "audio_suffix": "/../x"}, b"abc", None),
        ({"audio_bytes": 3, "reference_bytes": 2}, b"abc", None),
        ({"audio_bytes": 3, "references": [{"name": "A", "bytes": 0}]}, b"abc", None),
        ({"audio_bytes": 3, "references": [{"name": "A", "bytes": 1}, {"name": "A", "bytes": 1}]}, b"abcxy", None),
        ({"audio_bytes": 3, "references": "A"}, b"abc", None),
        ({"audio_bytes": 3, "spans": [[[2, 1]]]}, b"abc", None),
    ):
        raw = json.dumps(meta).encode() + b"\n" + data
        with pytest.raises(ValueError):
            script.read_upload(io.BytesIO(raw), length or len(raw) + (2 if "reference_bytes" in meta else 0), tmp_path)


@pytest.fixture
def remote():
    path = compute.PACK_ROOT / "asr-funasr/remote.py"
    spec = importlib.util.spec_from_file_location("asr_remote", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_remote_client_round_trip(script, remote, tmp_path, capfd, monkeypatch):
    class FakeEngine:
        device = "cuda"
        pipeline = "overlap"

        def __init__(self):
            self.calls = []

        def transcribe(self, audio, diarize, reference, hotwords, progress, references, cluster_threshold, pipeline):
            self.threshold, self.chosen = cluster_threshold, pipeline
            self.calls.append(
                (audio.read_bytes(), audio.suffix, diarize, reference and reference.read_bytes(), hotwords)
            )
            self.voices = {name: path.read_bytes() for name, path in references.items()}
            progress(0.5)
            if audio.read_bytes() == b"boom":
                raise RuntimeError("显存不足")
            return {"ok": True, "segments": [{"start": 0.0, "end": 1.0, "text": "你好", "speaker": "S1"}]}

        def embedding(self, audio, spans=None):
            self.embedded = audio.read_bytes()
            if spans is not None:
                return {"ok": True, "embeddings": [[float(len(parts))] for parts in spans]}
            return {"ok": True, "embedding": [0.6, 0.8]}

    engine = FakeEngine()
    server = script.make_server(engine, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        audio, reference, words = tmp_path / "audio.wav", tmp_path / "voice.wav", tmp_path / "hotwords.txt"
        audio.write_bytes(b"RIFF-audio")
        reference.write_bytes(b"ref")
        words.write_text("# 人名\n邓郁松\n\n魔搭\n", encoding="utf-8")
        request = {"audio": str(audio), "language": "zh", "diarize": True, "reference": str(reference)}
        result = remote.transcribe(url, request, hotwords=remote.read_hotwords(words))
        assert result["ok"] is True and result["segments"][0]["text"] == "你好"
        assert engine.calls[-1] == (b"RIFF-audio", ".wav", True, b"ref", ["邓郁松", "魔搭"])
        assert engine.voices == {}
        other = tmp_path / "other.wav"
        other.write_bytes(b"other")
        many = {**request, "references": {"A": str(reference), "B": str(other), "C": str(tmp_path / "gone.wav")}}
        assert remote.transcribe(url, many)["ok"] is True
        assert engine.voices == {"A": b"ref", "B": b"other"}
        assert remote.transcribe(url, {**request, "cluster_threshold": 0.7})["ok"] is True
        assert engine.threshold == 0.7 and engine.chosen is None
        assert remote.transcribe(url, {**request, "pipeline": "classic"})["ok"] is True
        assert engine.chosen == "classic"
        calls = len(engine.calls)
        assert remote.transcribe(url, {"audio": str(reference), "embed": True}) == {"ok": True, "embedding": [0.6, 0.8]}
        assert engine.embedded == b"ref" and len(engine.calls) == calls
        spans = [[[0, 1.5]], [[2, 3], [4.5, 6]]]
        assert remote.transcribe(url, {"audio": str(reference), "embed": True, "spans": spans}) == {
            "ok": True,
            "embeddings": [[1.0], [2.0]],
        }
        assert "@@twin-progress 0.5000" in capfd.readouterr().err
        audio.write_bytes(b"boom")
        assert remote.transcribe(url, {"audio": str(audio)}) == {"ok": False, "error": "显存不足"}
        with urllib.request.urlopen(url + "/health") as response:
            assert json.loads(response.read()) == {
                "ok": True,
                "version": "1.5.4",
                "transcription": "1.5.4",
                "denoise": False,
                "device": "cuda",
                "pipeline": "overlap",
                "busy": False,
            }
        bad = b'{"audio_bytes": 1, "hotwords": "x"}\nA'
        with pytest.raises(urllib.error.HTTPError) as rejected:
            urllib.request.urlopen(urllib.request.Request(url + "/transcribe", data=bad, method="POST"))
        assert rejected.value.code == 400 and "hotwords" in json.loads(rejected.value.read())["error"]
        with pytest.raises(ValueError, match="音频文件不存在"):
            remote.transcribe(url, {"audio": str(tmp_path / "missing.wav")})
    finally:
        server.shutdown()
        server.server_close()
    monkeypatch.setattr(remote, "CONNECT_WAITS", ())
    with pytest.raises(ValueError, match="连不上转写服务"):
        remote.transcribe(url, {"audio": str(audio)}, timeout=2)
    with pytest.raises(ValueError, match="地址无效"):
        remote.transcribe("https://example.com", {"audio": str(audio)})


def test_remote_command_contract(tmp_path):
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"x")
    result = subprocess.run(
        [sys.executable, str(compute.PACK_ROOT / "asr-funasr/remote.py"), "--url", "http://127.0.0.1:9"],
        input=json.dumps({"audio": str(audio)}),
        capture_output=True,
        text=True,
        env={**os.environ, "TWIN_ASR_CONNECT_SECONDS": "0"},
    )
    payload = json.loads(result.stdout.splitlines()[-1])
    assert result.returncode == 1 and payload == {"ok": False, "error": "连不上转写服务，请检查 GPU 机器上的服务和隧道"}


def test_a_recording_waits_for_a_restarting_service(script, remote, tmp_path, monkeypatch):
    class FakeEngine:
        device, pipeline = "cuda", "overlap"

        def transcribe(self, audio, *args):
            return {"ok": True, "segments": []}

    # The port is taken back and served only after the client has been refused a few times.
    probe = script.make_server(FakeEngine(), "127.0.0.1", 0)
    port = probe.server_address[1]
    probe.server_close()
    monkeypatch.setattr(remote, "CONNECT_WAITS", (0.2,) * 25)
    started: list[Any] = []

    def start_late() -> None:
        time.sleep(0.6)
        server = script.make_server(FakeEngine(), "127.0.0.1", port)
        started.append(server)
        server.serve_forever()

    threading.Thread(target=start_late, daemon=True).start()
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"RIFF-audio")
    try:
        assert remote.transcribe(f"http://127.0.0.1:{port}", {"audio": str(audio)}, flac=False)["ok"] is True
    finally:
        for server in started:
            server.shutdown()
            server.server_close()


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
def test_remote_uploads_wav_as_lossless_flac(script, remote, tmp_path):
    audio = tmp_path / "audio.wav"
    with wave.open(str(audio), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(16000)
        out.writeframes(b"\x00\x00" * 16000)
    seen = []

    class FakeEngine:
        device = "cpu"
        pipeline = "classic"

        def transcribe(self, audio, diarize, reference, hotwords, progress, references, cluster_threshold, pipeline):
            seen.append((audio.suffix, audio.stat().st_size))
            return {"ok": True, "segments": []}

    server = script.make_server(FakeEngine(), "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        assert remote.transcribe(url, {"audio": str(audio)}) == {"ok": True, "segments": []}
        assert remote.transcribe(url, {"audio": str(audio)}, flac=False) == {"ok": True, "segments": []}
    finally:
        server.shutdown()
        server.server_close()
    assert seen[0][0] == ".flac" and seen[0][1] < audio.stat().st_size
    assert seen[1] == (".wav", audio.stat().st_size)
    assert remote.compress(tmp_path / "voice.m4a", tmp_path) == tmp_path / "voice.m4a"


def test_embed_request_skips_transcription(script, monkeypatch, tmp_path):
    class FakeEngine:
        def __init__(self, device, pipeline):
            pass

        def embedding(self, audio):
            return {"ok": True, "embedding": script.vector([0.123456789, 1])}

        def transcribe(self, *args):
            raise AssertionError("embed must not transcribe")

    monkeypatch.setattr(script, "Engine", FakeEngine)
    voice = tmp_path / "voice.wav"
    voice.write_bytes(b"x")
    request = script.parse_request({"audio": str(voice), "embed": True})
    assert script.run(request, embed=True) == {"ok": True, "embedding": [0.123457, 1.0]}


def test_embed_spans_are_checked(script):
    assert script.parse_spans({}) is None
    assert script.parse_spans({"spans": [[[0, 1.5]], [[2, 3], [4.5, 6]]]}) == [[(0.0, 1.5)], [(2.0, 3.0), (4.5, 6.0)]]
    for bad in ("x", [[]], [[[1, 1]]], [[[0, True]]], [[[0, float("inf")]]], [[[0]]], [[[0, 1]] * 65]):
        with pytest.raises(ValueError, match="spans"):
            script.parse_spans({"spans": bad})


def test_remote_denoising_round_trip(script, remote, tmp_path, capfd):
    class FakeEngine:
        device, pipeline = "cuda", "overlap"

    class FakePlayback:
        available = True

        def __call__(self, audio, output, progress):
            progress(0.5)
            if audio.read_bytes() == b"boom":
                raise RuntimeError("显存不足")
            output.write_bytes(b"fLaC" + audio.read_bytes()[::-1] * 300000)
            return {"ok": True, "denoised": True, "seconds": 1.0}

    server = script.make_server(FakeEngine(), "127.0.0.1", 0, playback=FakePlayback())
    old = script.make_server(FakeEngine(), "127.0.0.1", 0)
    for each in (server, old):
        threading.Thread(target=each.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    old_url = f"http://127.0.0.1:{old.server_address[1]}"
    try:
        audio, output = tmp_path / "playback.flac", tmp_path / "playback-denoised.flac"
        audio.write_bytes(b"abc")
        assert remote.capabilities(url) == {"ok": True, "version": "1.5.4", "denoise": True}
        assert remote.capabilities(old_url)["denoise"] is False
        request = {"audio": str(audio), "denoise": True, "output": str(output)}
        assert remote.denoise(url, request) == {"ok": True, "denoised": True, "seconds": 1.0}
        # Megabytes after the result line arrive whole, through a temporary file.
        assert output.read_bytes() == b"fLaC" + b"cba" * 300000
        assert [p.name for p in tmp_path.iterdir() if p.name.startswith(".")] == []
        assert "@@twin-progress 0.5000" in capfd.readouterr().err
        audio.write_bytes(b"boom")
        assert remote.denoise(url, request) == {"ok": False, "error": "显存不足"}
        # A service that cannot denoise says so; output is left alone.
        assert remote.denoise(old_url, {**request, "output": str(tmp_path / "other.flac")})["ok"] is False
        assert not (tmp_path / "other.flac").exists()
        with pytest.raises(ValueError, match="output"):
            remote.denoise(url, {**request, "output": "relative.flac"})
    finally:
        for each in (server, old):
            each.shutdown()
            each.server_close()
    with pytest.raises(ValueError, match="连不上"):
        remote.capabilities(url, timeout=2)


def test_remote_command_routes_capabilities_and_denoising(remote, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(remote, "capabilities", lambda url: {"ok": True, "version": "1.5.0", "denoise": True})
    monkeypatch.setattr(remote, "denoise", lambda url, request, timeout: {"ok": True, "denoised": True})
    for request, expected in (({"capabilities": True}, "version"), ({"denoise": True}, "denoised")):
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(request)))
        monkeypatch.setattr(sys, "argv", ["remote.py"])
        assert remote.main() == 0
        assert expected in json.loads(capsys.readouterr().out.splitlines()[-1])
