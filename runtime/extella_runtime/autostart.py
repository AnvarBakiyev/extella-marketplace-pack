"""Per-user autostart definitions for supported Extella platforms."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
from typing import Callable, Mapping, Sequence

from .paths import ClientPaths
from .platforms import PlatformInfo
from .transaction import InstallTransaction, InstallationError


Runner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]
SERVICE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{1,79}$")


@dataclass(frozen=True)
class AutostartSpec:
    service_id: str
    argv: tuple[str, ...]
    cwd: Path
    environment: Mapping[str, str]

    def validate(self) -> None:
        if not SERVICE_ID.fullmatch(self.service_id):
            raise InstallationError(f"invalid autostart service id: {self.service_id}")
        if not self.argv or not Path(self.argv[0]).is_absolute():
            raise InstallationError("autostart argv must begin with an absolute executable")
        if any("\x00" in value or "\n" in value or "\r" in value for value in self.argv):
            raise InstallationError("autostart argv contains control characters")
        if not self.cwd.is_absolute():
            raise InstallationError("autostart working directory must be absolute")
        for key, value in self.environment.items():
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
                raise InstallationError(f"invalid environment key: {key}")
            if "\x00" in value or "\n" in value or "\r" in value:
                raise InstallationError(f"invalid environment value: {key}")


def _run(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(argv), capture_output=True, text=True, timeout=30, check=False, shell=False
    )


def _mac_label(service_id: str) -> str:
    return f"ai.extella.{service_id.replace('_', '-')}"


def render_launch_agent(spec: AutostartSpec, *, log_path: Path) -> bytes:
    spec.validate()
    payload = {
        "Label": _mac_label(spec.service_id),
        "ProgramArguments": list(spec.argv),
        "WorkingDirectory": str(spec.cwd),
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "ProcessType": "Background",
        "StandardOutPath": str(log_path),
        "StandardErrorPath": str(log_path),
        "EnvironmentVariables": {**spec.environment, "PYTHONUNBUFFERED": "1"},
    }
    return plistlib.dumps(payload, fmt=plistlib.FMT_XML, sort_keys=True)


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def render_windows_launcher(spec: AutostartSpec, *, log_path: Path) -> bytes:
    spec.validate()
    lines = ["$ErrorActionPreference = 'Stop'"]
    for key, value in sorted({**spec.environment, "PYTHONUNBUFFERED": "1"}.items()):
        lines.append(f"$env:{key} = {_ps_quote(value)}")
    lines.append(f"Set-Location -LiteralPath {_ps_quote(str(spec.cwd))}")
    command = " ".join(_ps_quote(value) for value in spec.argv)
    lines.append(f"& {command} *>> {_ps_quote(str(log_path))}")
    lines.append("exit $LASTEXITCODE")
    return ("\n".join(lines) + "\n").encode("utf-8")


def _mac_loaded(label: str, *, runner: Runner) -> bool:
    domain = f"gui/{os.getuid()}"
    return runner(("launchctl", "print", f"{domain}/{label}")).returncode == 0


def _windows_task_name(service_id: str) -> str:
    return f"\\Extella\\{service_id}"


def _windows_loaded(service_id: str, *, runner: Runner) -> bool:
    return runner(("schtasks.exe", "/Query", "/TN", _windows_task_name(service_id))).returncode == 0


def _unregister(
    spec: AutostartSpec,
    *,
    platform_info: PlatformInfo,
    runner: Runner,
) -> None:
    if platform_info.system == "Darwin":
        domain = f"gui/{os.getuid()}"
        runner(("launchctl", "bootout", f"{domain}/{_mac_label(spec.service_id)}"))
    else:
        runner(("schtasks.exe", "/Delete", "/TN", _windows_task_name(spec.service_id), "/F"))


def install_autostart(
    transaction: InstallTransaction,
    spec: AutostartSpec,
    *,
    platform_info: PlatformInfo,
    paths: ClientPaths,
    runner: Runner = _run,
) -> str:
    """Install and activate a per-user autostart definition transactionally."""

    spec.validate()
    if platform_info.system == "Darwin":
        label = _mac_label(spec.service_id)
        target = paths.autostart_root / f"{label}.plist"
        was_loaded = _mac_loaded(label, runner=runner)

        def restore_registration() -> None:
            _unregister(spec, platform_info=platform_info, runner=runner)
            if was_loaded and target.is_file():
                runner(("launchctl", "bootstrap", f"gui/{os.getuid()}", str(target)))

        transaction.register_undo(restore_registration)
        transaction.atomic_write(
            render_launch_agent(spec, log_path=paths.logs_root / f"{spec.service_id}.log"),
            target,
            mode=0o644,
        )
        if was_loaded:
            _unregister(spec, platform_info=platform_info, runner=runner)
        result = runner(("launchctl", "bootstrap", f"gui/{os.getuid()}", str(target)))
        if result.returncode != 0:
            raise InstallationError("LaunchAgent registration failed")
        return str(target)

    target = paths.autostart_root / f"{spec.service_id}.ps1"
    was_loaded = _windows_loaded(spec.service_id, runner=runner)

    def restore_task() -> None:
        _unregister(spec, platform_info=platform_info, runner=runner)
        if was_loaded and target.is_file():
            _create_windows_task(spec.service_id, target, runner=runner)

    transaction.register_undo(restore_task)
    transaction.atomic_write(
        render_windows_launcher(spec, log_path=paths.logs_root / f"{spec.service_id}.log"),
        target,
        mode=0o600,
    )
    result = _create_windows_task(spec.service_id, target, runner=runner)
    if result.returncode != 0:
        raise InstallationError("Windows Scheduled Task registration failed")
    return str(target)


def _create_windows_task(service_id: str, launcher: Path, *, runner: Runner) -> subprocess.CompletedProcess[str]:
    powershell = shutil.which("powershell.exe") or "powershell.exe"
    action = f'"{powershell}" -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "{launcher}"'
    return runner(
        (
            "schtasks.exe",
            "/Create",
            "/TN",
            _windows_task_name(service_id),
            "/SC",
            "ONLOGON",
            "/TR",
            action,
            "/RL",
            "LIMITED",
            "/F",
        )
    )


def remove_autostart(
    service_id: str,
    *,
    platform_info: PlatformInfo,
    paths: ClientPaths,
    runner: Runner = _run,
) -> None:
    spec = AutostartSpec(service_id, (str(Path.cwd() / "placeholder"),), Path.cwd(), {})
    _unregister(spec, platform_info=platform_info, runner=runner)
    if platform_info.system == "Darwin":
        (paths.autostart_root / f"{_mac_label(service_id)}.plist").unlink(missing_ok=True)
    else:
        (paths.autostart_root / f"{service_id}.ps1").unlink(missing_ok=True)
