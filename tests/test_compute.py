"""Offline lifecycle coverage for the command compute pack."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tomllib
from dataclasses import replace
from pathlib import Path

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
    assert (pack.version, pack.kind, pack.python, pack.entry) == ("1.0.0", "command", "3.12", "run.py")
    assert pack.platforms == ("darwin-arm64",)
    assert len(pack.models) == 3 and pack.model_bytes > 900_000_000
    assert all(len(f["sha256"]) == 64 for m in pack.models for f in m["files"])
    assert "scikit-learn==" in (pack.source / "requirements-darwin-arm64.lock").read_text()
    assert "am.mvn" in {f["path"] for m in pack.models for f in m["files"]}
    with pytest.raises(ValueError, match="未知"):
        compute.get_pack("../bad")


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
    assert load_settings(config).asr.command == compute_defaults()["asr_command"]
    original = config.read_bytes()
    compute.install(pack, config, download_models=True, runner=runner)
    assert len(runner.calls) == 4 and runner.calls[-1][-1] == "--check"
    assert config.read_bytes() == original
    status = compute.status(pack, config)
    assert "已安装" in status and "版本 1.0.0" in status and "指向当前安装" in status and "模型齐全" in status
    text = config.read_text()
    command = tomllib.loads(text)["asr"]["command"]
    config.write_text(text.replace(json.dumps(command), json.dumps(command + " --device mps")))
    assert "未指向当前安装" not in compute.status(pack, config)


@pytest.mark.parametrize("step", ["venv", "pip", "--check"])
def test_install_failure_preserves_previous(environment, step):
    pack, config, _ = environment
    old = compute.install(pack, config, runner=FakeRunner())
    old_config = config.read_bytes()
    new = replace(pack, version="1.1.0")
    with pytest.raises(ValueError, match="已保留旧安装"):
        compute.install(new, config, runner=FakeRunner(fail=lambda args: step in args))
    assert (old.parent / "current").resolve() == old
    assert config.read_bytes() == old_config
    assert not (old.parent / "1.1.0").exists()
    assert not list(old.parent.glob(".1.1.0-*"))


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
    assert script.parse_request({"audio": str(audio), "language": "invalid"}) == (audio, "auto", False, None)
    for request in ([], {}, {"audio": "relative.wav"}, {"audio": str(audio), "diarize": "yes"}):
        with pytest.raises(ValueError):
            script.parse_request(request)
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
    assert len(tomllib.loads(text)["models"]) == 3
