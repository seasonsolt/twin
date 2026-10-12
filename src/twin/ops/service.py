"""User service rendering and injectable process execution."""

from __future__ import annotations

import os
import platform
import plistlib
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ..config import Settings
from ..util import open_private, prepare_private_file, private_directory
from .paths import TwinPaths

Runner = Callable[[list[str]], subprocess.CompletedProcess[str]]


def run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, check=False, timeout=30)


@dataclass(frozen=True)
class Service:
    name: str
    arguments: tuple[str, ...]
    daily: tuple[int, int] | None = None

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9-]*", self.name) or not self.arguments:
            raise ValueError("服务名称或命令无效")
        if any("\n" in arg or "\r" in arg or "\0" in arg for arg in self.arguments):
            raise ValueError("服务命令不能包含换行或空字符")


def services(paths: TwinPaths, config: Path, settings: Settings) -> list[Service]:
    command: tuple[str, ...] = (str(paths.current / "venv" / "bin" / "twin"), "--config", str(config.resolve()))
    if os.environ.get("TWIN_HOME"):
        command = (command[0], "--home", str(paths.home.resolve()), *command[1:])
    web = [*command, "ui", "--port", str(settings.ops.web_port)]
    for host in settings.ops.allow_hosts:
        web.extend(["--allow-host", host])
    result = [Service("web", tuple(web)), Service("backup", (*command, "ops", "backup"), (4, 0))]
    for name, arguments in settings.ops.compute_services.items():
        if (
            not re.fullmatch(r"[a-z][a-z0-9-]*", name)
            or name in {"web", "backup", "tunnel", "upgrade"}
            or not arguments
        ):
            raise ValueError("算力服务名称或命令无效")
        result.append(Service(name, tuple(arguments)))
    if settings.ops.tunnel_command:
        result.append(Service("tunnel", tuple(settings.ops.tunnel_command)))
    if settings.upgrade.channel != "off":
        result.append(
            Service("upgrade", (*command, "upgrade", "--channel", settings.upgrade.channel, "--if-idle"), (4, 30))
        )
    return result


class ServiceManager:
    def __init__(self, paths: TwinPaths, runner: Runner = run_command) -> None:
        self.paths, self.runner = paths, runner

    def render(self, service: Service) -> dict[Path, str]:
        raise NotImplementedError

    def command(self, action: str, service: Service) -> list[str]:
        raise NotImplementedError

    def install(self, items: list[Service]) -> None:
        private_directory(self.paths.logs)
        self.paths.logs.chmod(0o700)
        for service in items:
            prepare_private_file(self.paths.service_log(service.name))
            for path, text in self.render(service).items():
                private_directory(path.parent)
                with open_private(path) as stream:
                    stream.write(text)

    def stopped(self, service: Service) -> bool:
        raise NotImplementedError

    def execute(self, action: str, service: Service) -> subprocess.CompletedProcess[str]:
        result = self.runner(self.command(action, service))
        if result.returncode and action != "status":
            raise ValueError(f"服务 {service.name} 的 {action} 操作失败（退出码 {result.returncode}）")
        return result


class LaunchdManager(ServiceManager):
    def stopped(self, service: Service) -> bool:
        result = self.runner(self.command("status", service))
        if result.returncode not in {0, 113}:
            raise ValueError("无法确认 launchd 服务状态，拒绝恢复；请检查用户会话")
        return result.returncode == 113

    def execute(self, action: str, service: Service) -> subprocess.CompletedProcess[str]:
        if action in {"start", "stop"}:
            stopped = self.stopped(service)
            if (action == "start" and not stopped) or (action == "stop" and stopped):
                return subprocess.CompletedProcess([], 0, "", "")
        return super().execute(action, service)

    def render(self, service: Service) -> dict[Path, str]:
        value: dict[str, object] = {
            "Label": f"ai.twin.{service.name}",
            "ProgramArguments": list(service.arguments),
            "EnvironmentVariables": {"TWIN_ENV_FILE": str(self.paths.env)},
            "KeepAlive": service.daily is None,
            "Umask": 0o077,
            "ThrottleInterval": 10,
            "StandardOutPath": str(self.paths.service_log(service.name)),
            "StandardErrorPath": str(self.paths.service_log(service.name)),
        }
        if service.name == "web":
            value["ProcessType"] = "Interactive"
        if service.daily:
            value["StartCalendarInterval"] = {"Hour": service.daily[0], "Minute": service.daily[1]}
        else:
            value["RunAtLoad"] = True
        return {self.paths.launch_agents / f"ai.twin.{service.name}.plist": plistlib.dumps(value).decode()}

    def command(self, action: str, service: Service) -> list[str]:
        domain = f"gui/{os.getuid()}"
        label = f"{domain}/ai.twin.{service.name}"
        commands = {
            "start": [
                "launchctl",
                "bootstrap",
                domain,
                str(self.paths.launch_agents / f"ai.twin.{service.name}.plist"),
            ],
            "stop": ["launchctl", "bootout", label],
            "restart": ["launchctl", "kickstart", "-k", label],
            "status": ["launchctl", "print", label],
        }
        return commands[action]


class SystemdUserManager(ServiceManager):
    def stopped(self, service: Service) -> bool:
        units = [f"twin-{service.name}.service"]
        if service.daily:
            units.append(f"twin-{service.name}.timer")
        for unit in units:
            result = self.runner(["systemctl", "--user", "is-active", unit])
            if result.returncode == 0:
                return False
            if result.returncode not in {3, 4} or result.stdout.strip() not in {"inactive", "failed", "unknown"}:
                raise ValueError("无法确认 systemd 服务状态，拒绝恢复；请检查用户会话")
        return True

    def execute(self, action: str, service: Service) -> subprocess.CompletedProcess[str]:
        result = super().execute(action, service)
        if action == "stop" and service.daily:
            extra = self.runner(["systemctl", "--user", "stop", f"twin-{service.name}.service"])
            if extra.returncode:
                raise ValueError("定时任务仍未停止，请检查用户服务")
        return result

    def render(self, service: Service) -> dict[Path, str]:
        def quote(value: str, *, expand: bool = False) -> str:
            escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%")
            return '"' + (escaped.replace("$", "$$") if expand else escaped) + '"'

        command = " ".join(quote(arg, expand=True) for arg in service.arguments)
        text = (
            f"[Unit]\nDescription=twin {service.name}\n\n[Service]\n"
            f"Type={'oneshot' if service.daily else 'simple'}\nUMask=0077\nExecStart={command}\n"
            f"EnvironmentFile=-{quote(str(self.paths.env))}\n"
            f"Environment={quote('TWIN_ENV_FILE=' + str(self.paths.env))}\n"
            f"StandardOutput={quote('append:' + str(self.paths.service_log(service.name)))}\n"
            f"StandardError={quote('append:' + str(self.paths.service_log(service.name)))}\n"
        )
        if not service.daily:
            text += "Restart=on-failure\nRestartSec=10\n\n[Install]\nWantedBy=default.target\n"
        result = {self.paths.systemd_user / f"twin-{service.name}.service": text}
        if service.daily:
            hour, minute = service.daily
            result[self.paths.systemd_user / f"twin-{service.name}.timer"] = (
                f"[Unit]\nDescription=twin {service.name}\n\n[Timer]\n"
                f"OnCalendar=*-*-* {hour:02d}:{minute:02d}:00\nPersistent=true\n"
                "\n[Install]\nWantedBy=timers.target\n"
            )
        return result

    def install(self, items: list[Service]) -> None:
        super().install(items)
        result = self.runner(["systemctl", "--user", "daemon-reload"])
        if result.returncode:
            raise ValueError("无法重新加载用户服务配置")

    def command(self, action: str, service: Service) -> list[str]:
        unit = f"twin-{service.name}.{'timer' if service.daily else 'service'}"
        return [
            "systemctl",
            "--user",
            *(["enable", "--now"] if action == "start" else ["disable", "--now"] if action == "stop" else [action]),
            unit,
        ]


def manager(paths: TwinPaths, runner: Runner = run_command) -> ServiceManager:
    return LaunchdManager(paths, runner) if platform.system() == "Darwin" else SystemdUserManager(paths, runner)
