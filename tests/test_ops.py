from __future__ import annotations

import datetime as dt
import json
import os
import plistlib
import sqlite3
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from twin import cli
from twin.config import (
    ASRSettings,
    EmbedSettings,
    LLMSettings,
    OpsSettings,
    Settings,
    TTSSettings,
    UpgradeSettings,
    load_settings,
)
from twin.ops.backup import backup, prune, restore
from twin.ops.doctor import inspect_installation
from twin.ops.envfile import load_env_file
from twin.ops.paths import TwinPaths, compute_defaults
from twin.ops.service import LaunchdManager, Service, SystemdUserManager, services
from twin.persona.store import PersonaStore
from twin.util import open_private, private_directory


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    clock = [0.0]
    monkeypatch.setattr("twin.ops.doctor.time.monotonic", lambda: clock[0])
    monkeypatch.setattr("twin.ops.doctor.time.sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    monkeypatch.delenv("TWIN_CONFIG", raising=False)
    original = subprocess.run

    def guarded(command, *args, **kwargs):  # type: ignore[no-untyped-def]
        assert command[0] not in {"launchctl", "systemctl", "pmset", "brew"}
        return original(command, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", guarded)


def fake_runner(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(command, 0, "sleep 0\n", "")


def configured() -> tuple[TwinPaths, Settings]:
    paths = TwinPaths.from_env()
    private_directory(paths.config_dir)
    private_directory(paths.data)
    with open_private(paths.config) as stream:
        stream.write(f"db_path = {json.dumps(str(paths.data / 'twin.db'))}\n")
    with open_private(paths.env) as stream:
        stream.write("")
    return paths, load_settings(paths.config)


def test_paths_override_contains_all_writes() -> None:
    paths = TwinPaths.from_env()
    assert all(
        value.is_relative_to(paths.home)
        for name, value in vars(paths).items()
        if name not in {"launch_agents", "systemd_user"}
    )
    assert paths.launch_agents == paths.systemd_user == Path(os.environ["TWIN_SERVICE_DIR"])
    assert compute_defaults()["tts_port"] == 8004
    assert str(paths.compute) in str(compute_defaults()["asr_command"])


@pytest.mark.parametrize("system", ["Darwin", "Linux"])
def test_platform_layout(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, system: str) -> None:
    monkeypatch.delenv("TWIN_HOME")
    monkeypatch.delenv("TWIN_SERVICE_DIR")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr("twin.ops.paths.platform.system", lambda: system)
    paths = TwinPaths.from_env()
    assert paths.config == tmp_path / ".config/twin/twin.toml"
    assert paths.home == tmp_path / ("Library/Application Support/twin" if system == "Darwin" else ".local/share/twin")
    assert paths.launch_agents == tmp_path / "Library/LaunchAgents"


@pytest.mark.parametrize("system", ["Darwin", "Linux"])
def test_home_override_keeps_system_service_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, system: str
) -> None:
    monkeypatch.delenv("TWIN_SERVICE_DIR")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr("twin.ops.paths.platform.system", lambda: system)
    paths = TwinPaths.from_env()
    assert paths.home == Path(os.environ["TWIN_HOME"])
    assert paths.launch_agents == tmp_path / "Library/LaunchAgents"
    assert paths.systemd_user == tmp_path / ".config/systemd/user"


@pytest.mark.parametrize(
    "ready_after,loaded,expected,elapsed",
    [(1, True, True, 0), (4, True, True, 3), (99, True, False, 10), (99, False, None, 0)],
)
def test_doctor_port_startup_grace(ready_after: int, loaded: bool, expected: bool | None, elapsed: int) -> None:
    from twin.ops import doctor

    paths, settings = configured()
    calls = 0

    def connect(host: str, port: int) -> bool:
        nonlocal calls
        calls += 1
        return calls >= ready_after

    backend = LaunchdManager(paths, lambda cmd: subprocess.CompletedProcess(cmd, 0 if loaded else 113, "sleep 0", ""))
    checks = doctor.inspect_installation(paths, settings, paths.config, backend, connect=connect)
    check = next(item for item in checks if item.name == "网页端口")
    assert check.ok is expected
    assert doctor.time.monotonic() == elapsed
    assert calls == (10 if elapsed == 10 else elapsed + 1)


def test_doctor_optional_media_and_success_advice(monkeypatch: pytest.MonkeyPatch) -> None:
    from twin.ops.doctor import Check

    paths, settings = configured()
    for key in ("TWIN_TTS_KEY", "TWIN_ASR_KEY"):
        monkeypatch.delenv(key, raising=False)
    checks = inspect_installation(
        paths, settings, paths.config, LaunchdManager(paths, fake_runner), connect=lambda *_: True
    )
    for name in ("语音", "认人", "视频"):
        check = next(item for item in checks if item.name == name)
        assert check.ok is None and check.detail == "未开启（可选）"
    asr = next(item for item in checks if item.name == "识别")
    assert asr.ok is False and "twin compute install asr-funasr" in asr.advice
    assert not any("TWIN_TTS_KEY" in item.name or "TWIN_ASR_KEY" in item.name for item in checks)
    assert Check("测试", True, "通过", "修复").text() == "✓ 测试：通过"
    assert Check("测试", None, "跳过", "修复").text() == "– 测试：跳过"
    assert Check("测试", False, "失败", "修复").text() == "✗ 测试：失败；修复"
    assert all(
        not any(word in item.text() for word in ("请", "建议", "运行 ", "chmod", "必须")) for item in checks if item.ok
    )


@pytest.mark.parametrize("provider,required", [("silent", False), ("openai_compat", False), ("cloudflare", True)])
def test_doctor_tts_credentials_follow_provider(monkeypatch: pytest.MonkeyPatch, provider: str, required: bool) -> None:
    paths, settings = configured()
    settings.tts = TTSSettings.model_validate(
        {"provider": provider, "base_url": "http://127.0.0.1:8004/v1", "model": "test"}
    )
    monkeypatch.delenv("TWIN_TTS_KEY", raising=False)
    checks = inspect_installation(
        paths, settings, paths.config, LaunchdManager(paths, fake_runner), connect=lambda *_: True
    )
    keys = [item for item in checks if item.name == "环境变量 TWIN_TTS_KEY"]
    assert bool(keys) is required
    if required:
        assert keys[0].ok is False


def test_env_loading_atomic_and_no_expansion(monkeypatch: pytest.MonkeyPatch) -> None:
    paths, _ = configured()
    monkeypatch.setenv("OPS_KEEP", "process")
    monkeypatch.delenv("OPS_LOAD", raising=False)
    paths.env.write_text("# private\nOPS_KEEP=file\nOPS_LOAD='$(not-executed) # literal' # comment\n")
    assert load_env_file(paths.env) == ["OPS_KEEP", "OPS_LOAD"]
    assert os.environ["OPS_KEEP"] == "process"
    assert os.environ["OPS_LOAD"] == "$(not-executed) # literal"
    monkeypatch.delenv("OPS_LOAD")
    paths.env.write_text("OPS_LOAD=secret\ninvalid secret line\n")
    with pytest.raises(ValueError, match="第 2 行") as error:
        load_env_file(paths.env)
    assert "secret" not in str(error.value)
    assert "OPS_LOAD" not in os.environ


@pytest.mark.parametrize("mode", [0o644, 0o400, 0o700, 0o660, 0o1600])
def test_env_requires_exact_mode(mode: int) -> None:
    paths, _ = configured()
    paths.env.chmod(mode)
    with pytest.raises(PermissionError, match="chmod 600"):
        load_env_file(paths.env)


@pytest.mark.parametrize("line", ['KEY="unfinished', "KEY='value' extra", "export KEY=x"])
def test_env_rejects_invalid_format(line: str) -> None:
    paths, _ = configured()
    paths.env.write_text(line)
    with pytest.raises(ValueError):
        load_env_file(paths.env)


def test_launchd_render_snapshot_and_commands() -> None:
    paths, settings = configured()
    backend = LaunchdManager(paths, fake_runner)
    web, daily = services(paths, paths.config, settings)
    value = plistlib.loads(next(iter(backend.render(web).values())).encode())
    assert value == {
        "Label": "ai.twin.web",
        "ProgramArguments": list(web.arguments),
        "EnvironmentVariables": {"TWIN_ENV_FILE": str(paths.env)},
        "KeepAlive": True,
        "Umask": 0o077,
        "ThrottleInterval": 10,
        "StandardOutPath": str(paths.logs / "web.log"),
        "StandardErrorPath": str(paths.logs / "web.log"),
        "ProcessType": "Interactive",
        "RunAtLoad": True,
    }
    timer = plistlib.loads(next(iter(backend.render(daily).values())).encode())
    assert timer["StartCalendarInterval"] == {"Hour": 4, "Minute": 0}
    assert timer["KeepAlive"] is False and "RunAtLoad" not in timer
    assert backend.command("start", web) == [
        "launchctl",
        "bootstrap",
        f"gui/{os.getuid()}",
        str(paths.launch_agents / "ai.twin.web.plist"),
    ]
    assert backend.command("restart", web) == ["launchctl", "kickstart", "-k", f"gui/{os.getuid()}/ai.twin.web"]
    backend.install([web, daily])
    assert (paths.launch_agents / "ai.twin.web.plist").stat().st_mode & 0o777 == 0o600


def test_systemd_render_snapshot_and_runner() -> None:
    paths, settings = configured()
    calls: list[list[str]] = []

    def run(command: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return fake_runner(command)

    backend = SystemdUserManager(paths, run)
    web, daily = services(paths, paths.config, settings)
    rendered = backend.render(daily)
    assert rendered[paths.systemd_user / "twin-backup.timer"] == (
        "[Unit]\nDescription=twin backup\n\n[Timer]\nOnCalendar=*-*-* 04:00:00\nPersistent=true\n"
        "\n[Install]\nWantedBy=timers.target\n"
    )
    unit = rendered[paths.systemd_user / "twin-backup.service"]
    assert "Type=oneshot" in unit and '"ops" "backup"' in unit
    assert f'EnvironmentFile=-"{paths.env}"' in unit
    assert "Restart=on-failure" in backend.render(web)[paths.systemd_user / "twin-web.service"]
    backend.install([web, daily])
    backend.execute("start", daily)
    backend.execute("stop", daily)
    assert calls == [
        ["systemctl", "--user", "daemon-reload"],
        ["systemctl", "--user", "enable", "--now", "twin-backup.timer"],
        ["systemctl", "--user", "disable", "--now", "twin-backup.timer"],
        ["systemctl", "--user", "stop", "twin-backup.service"],
    ]


def test_service_list_options() -> None:
    paths, settings = configured()
    settings.ops = OpsSettings(
        allow_hosts=["twin.example.test"],
        compute_services={"tts-router": ["/bin/router"]},
        tunnel_command=["/bin/cloudflared", "tunnel", "run"],
    )
    settings.upgrade = UpgradeSettings(channel="stable")
    items = services(paths, paths.config, settings)
    assert [item.name for item in items] == ["web", "backup", "tts-router", "tunnel", "upgrade"]
    assert items[-1].daily == (4, 30)
    assert items[0].arguments[-2:] == ("--allow-host", "twin.example.test")
    settings.ops.compute_services = {"../escape": ["bad"]}
    with pytest.raises(ValueError):
        services(paths, paths.config, settings)


@pytest.mark.parametrize(
    "manager_class,code,out,expected",
    [
        (LaunchdManager, 113, "", True),
        (LaunchdManager, 0, "", False),
        (SystemdUserManager, 3, "inactive", True),
        (SystemdUserManager, 0, "active", False),
    ],
)
def test_service_stopped(manager_class, code: int, out: str, expected: bool) -> None:  # type: ignore[no-untyped-def]
    backend = manager_class(TwinPaths.from_env(), lambda cmd: subprocess.CompletedProcess(cmd, code, out, ""))
    assert backend.stopped(Service("web", ("twin",))) is expected


@pytest.mark.parametrize("manager_class", [LaunchdManager, SystemdUserManager])
def test_service_errors_never_mean_stopped(manager_class) -> None:  # type: ignore[no-untyped-def]
    backend = manager_class(TwinPaths.from_env(), lambda cmd: subprocess.CompletedProcess(cmd, 1, "", "secret"))
    with pytest.raises(ValueError, match="拒绝恢复"):
        backend.stopped(Service("web", ("twin",)))


def test_backup_wal_permissions_and_restore() -> None:
    paths, settings = configured()
    connection = sqlite3.connect(settings.db_path)
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("CREATE TABLE example (value TEXT)")
        connection.execute("INSERT INTO example VALUES ('committed')")
        connection.commit()
        assert settings.db_path.with_name("twin.db-wal").exists()
        with PersonaStore(paths.data / "personas/p-example/twin.db") as store:
            store.set_meta("test", "persona")
        for name in (
            "assets/a",
            "uploads/done.wav",
            "uploads/unfinished.part",
            "media-cache/a",
            "channels.json",
            "personas.json",
        ):
            file = paths.data / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text("payload")
        target = backup(paths, paths.data, paths.config)
    finally:
        connection.close()
    with sqlite3.connect(target / "data/twin.db") as copied:
        assert copied.execute("SELECT value FROM example").fetchone() == ("committed",)
    assert not (target / "data/media-cache").exists()
    assert not (target / "data/uploads/unfinished.part").exists()
    assert not list(target.rglob("*-wal"))
    for path in target.rglob("*"):
        assert path.stat().st_mode & 0o777 == (0o700 if path.is_dir() else 0o600)
    with pytest.raises(ValueError, match="先执行"):
        restore(target, paths.data, paths.config, services_stopped=False)
    (paths.data / "new-file").write_text("remove on restore")
    restore(target, paths.data, paths.config, services_stopped=True)
    assert not (paths.data / "new-file").exists()
    assert (paths.data / "assets/a").read_text() == "payload"
    with PersonaStore(paths.data / "personas/p-example/twin.db") as store:
        assert store.get_meta("test") == "persona"


def test_retention() -> None:
    paths, _ = configured()
    private_directory(paths.backups)
    now = dt.datetime.now(dt.UTC)
    for index in range(10):
        folder = paths.backups / f"daily-{index:02d}"
        folder.mkdir()
        (folder / "snapshot.json").write_text(json.dumps({"reason": "daily", "created_at": now.isoformat()}))
    for name, age in [("pre-upgrade-old", 31), ("pre-upgrade-new", 29), ("migrate", 100)]:
        folder = paths.backups / name
        folder.mkdir()
        (folder / "snapshot.json").write_text(
            json.dumps({"reason": name, "created_at": (now - dt.timedelta(days=age)).isoformat()})
        )
    prune(paths.backups, now)
    assert len(list(paths.backups.glob("daily-*"))) == 7
    assert not (paths.backups / "pre-upgrade-old").exists()
    assert (paths.backups / "pre-upgrade-new").exists()
    assert (paths.backups / "migrate").exists()


def test_restore_rejects_links_and_bad_database() -> None:
    paths, _ = configured()
    target = backup(paths, paths.data, paths.config)
    (target / "data/link").symlink_to(paths.config)
    with pytest.raises(ValueError, match="符号链接"):
        restore(target, paths.data, paths.config, services_stopped=True)
    (target / "data/link").unlink()
    (target / "data/twin.db").write_text("invalid")
    (paths.data / "keep").write_text("old")
    with pytest.raises(sqlite3.DatabaseError):
        restore(target, paths.data, paths.config, services_stopped=True)
    assert (paths.data / "keep").read_text() == "old"


def test_doctor_no_model_calls_and_explicit_probes(monkeypatch: pytest.MonkeyPatch) -> None:
    paths, settings = configured()
    settings.llm = LLMSettings(model="fake", base_url="http://example.invalid/v1")
    settings.embed = EmbedSettings(provider="openai_compat", base_url="http://example.invalid/v1")
    settings.tts = TTSSettings(provider="openai_compat", model="fake", base_url="http://example.invalid/v1")
    settings.asr = ASRSettings(provider="command", command="nonexistent-asr")
    with PersonaStore(settings.db_path) as store:
        store.set_meta("test", "value")
    calls: list[str] = []
    monkeypatch.setenv("TWIN_LLM_KEY", "do-not-print")
    monkeypatch.setattr("twin.ops.doctor.platform.system", lambda: "Darwin")
    backend = LaunchdManager(paths, fake_runner)
    checks = inspect_installation(
        paths,
        settings,
        paths.config,
        backend,
        connect=lambda *_: False,
        invoke_model=lambda kind, _: calls.append(kind),
    )
    assert calls == []
    text = "\n".join(check.text() for check in checks)
    assert "do-not-print" not in text and "example.invalid" not in text
    assert "记忆内核" in text and "防睡眠" in text and "网页端口" in text
    assert "算力包需先" in text
    inspect_installation(
        paths,
        settings,
        paths.config,
        backend,
        probe=True,
        connect=lambda *_: True,
        invoke_model=lambda kind, _: calls.append(kind),
    )
    assert calls == ["LLM", "向量", "语音", "识别"]


@pytest.mark.parametrize("profile", ["mac-unified", "minimal", "split"])
def test_init_profiles(profile: str) -> None:
    result = CliRunner().invoke(cli.app, ["init", "--profile", profile])
    assert result.exit_code == 0, result.output
    path = TwinPaths.from_env().config if profile == "mac-unified" else Path("twin.toml")
    settings = load_settings(path)
    if profile == "mac-unified":
        assert "twin compute install asr-funasr" in path.read_text()
        assert "docs/MEDIA.md" in path.read_text()
        active = {line.strip() for line in path.read_text().splitlines()}
        assert all(f"[{section}]" not in active for section in ("tts", "asr", "vision", "video"))
        assert settings.db_path == TwinPaths.from_env().data / "twin.db"
        assert settings.tts.provider == "silent"
        assert settings.video.provider == "none"
        assert settings.asr.command is None and settings.vision.command is None
    if profile == "minimal":
        assert "[tts]" not in path.read_text()
    if profile == "split":
        assert path.read_text() == cli.CONFIG_TEMPLATE


def test_cli_env_before_settings_and_override(monkeypatch: pytest.MonkeyPatch) -> None:
    paths, _ = configured()
    paths.env.write_text('OPS_ENTRY="loaded"\n')
    monkeypatch.delenv("OPS_ENTRY", raising=False)
    result = CliRunner().invoke(cli.app, ["identity", "show"])
    assert result.exit_code == 0, result.output
    assert os.environ["OPS_ENTRY"] == "loaded"
    paths.env.chmod(0o644)
    result = CliRunner().invoke(cli.app, ["identity", "show"])
    assert result.exit_code == 1 and "chmod 600" in result.output


def test_cli_service_actions_with_fake_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    paths, _ = configured()
    calls: list[list[str]] = []

    def run(command: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return fake_runner(command)

    monkeypatch.setattr("twin.ops.service.manager", lambda paths: SystemdUserManager(paths, run))
    for action in ("install-services", "start", "restart", "status", "logs", "stop"):
        result = CliRunner().invoke(cli.app, ["ops", action])
        assert result.exit_code == 0, (result.output, result.exception)
    assert calls and (paths.systemd_user / "twin-web.service").exists()
    result = CliRunner().invoke(cli.app, ["ops", "status", "missing"])
    assert result.exit_code == 1 and "名称不存在" in result.output


def test_cli_doctor_bad_env_is_reported_without_loading(monkeypatch: pytest.MonkeyPatch) -> None:
    paths, _ = configured()
    paths.env.write_text("PRIVATE_TEST=do-not-print\ninvalid=value extra\nBROKEN\n")
    monkeypatch.delenv("PRIVATE_TEST", raising=False)
    monkeypatch.setattr("twin.ops.service.manager", lambda paths: LaunchdManager(paths, fake_runner))
    original = inspect_installation

    def inspect(*args, **kwargs):  # type: ignore[no-untyped-def]
        return original(*args, **kwargs, connect=lambda *_: False)

    monkeypatch.setattr("twin.ops.doctor.inspect_installation", inspect)
    result = CliRunner().invoke(cli.app, ["doctor"])
    assert result.exit_code == 1
    assert "环境文件" in result.output and "第 3 行" in result.output
    assert "do-not-print" not in result.output and "PRIVATE_TEST" not in os.environ


def test_cli_backup_restore_requires_known_stopped_services(monkeypatch: pytest.MonkeyPatch) -> None:
    paths, _ = configured()
    result = CliRunner().invoke(cli.app, ["ops", "backup", "--reason", "migrate"])
    assert result.exit_code == 0, result.output
    snapshot = next(paths.backups.iterdir())
    monkeypatch.setattr("twin.ops.service.manager", lambda paths: LaunchdManager(paths, fake_runner))
    result = CliRunner().invoke(cli.app, ["ops", "restore", str(snapshot)])
    assert result.exit_code == 1 and "先执行" in result.output
    monkeypatch.setattr(
        "twin.ops.service.manager",
        lambda paths: LaunchdManager(paths, lambda command: subprocess.CompletedProcess(command, 113, "", "")),
    )
    result = CliRunner().invoke(cli.app, ["ops", "restore", str(snapshot)])
    assert result.exit_code == 0 and "恢复完成" in result.output


def test_restore_failure_preserves_original_config_and_data(monkeypatch: pytest.MonkeyPatch) -> None:
    paths, _ = configured()
    snapshot = backup(paths, paths.data, paths.config)
    (paths.data / "keep").write_text("current")
    paths.config.write_text("# current config")
    original = Path.replace

    def fail_config(source: Path, destination: Path) -> Path:
        if destination == paths.config:
            raise OSError("cannot replace config")
        return original(source, destination)

    monkeypatch.setattr(Path, "replace", fail_config)
    with pytest.raises(OSError, match="cannot replace"):
        restore(snapshot, paths.data, paths.config, services_stopped=True)
    assert paths.config.read_text() == "# current config"
    assert (paths.data / "keep").read_text() == "current"
    assert not paths.data.with_name(paths.data.name + ".before-restore").exists()


def test_backup_auth_database_and_failed_snapshot_cleanup() -> None:
    paths, _ = configured()
    with sqlite3.connect(paths.data / "auth.db") as connection:
        connection.execute("CREATE TABLE sessions (value TEXT)")
        connection.execute("INSERT INTO sessions VALUES ('private')")
    snapshot = backup(paths, paths.data, paths.config)
    with sqlite3.connect(snapshot / "data/auth.db") as connection:
        assert connection.execute("SELECT value FROM sessions").fetchone() == ("private",)
    (paths.data / "unsafe").symlink_to(paths.env)
    with pytest.raises(ValueError, match="符号链接"):
        backup(paths, paths.data, paths.config)
    assert list(paths.backups.iterdir()) == [snapshot]


def test_installer_dry_run_writes_nothing() -> None:
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["bash", str(root / "deploy/mac/install.sh"), "--dry-run"], capture_output=True, text=True, check=True
    )
    assert "预演" in result.stdout and "asr-funasr" in result.stdout
    assert not TwinPaths.from_env().home.exists()
