"""Platform-native per-user paths for the Extella client distribution."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import os
from pathlib import Path
from typing import Any, Mapping

from .platforms import PlatformInfo, detect_platform


@dataclass(frozen=True)
class ClientPaths:
    data_root: Path
    toolbar_root: Path
    plugins_root: Path
    wizard_root: Path
    runtime_root: Path
    state_root: Path
    logs_root: Path
    autostart_root: Path

    def to_dict(self) -> dict[str, Any]:
        return {key: str(value) for key, value in asdict(self).items()}


def client_paths(
    *,
    platform_info: PlatformInfo | None = None,
    env: Mapping[str, str] | None = None,
) -> ClientPaths:
    platform_info = platform_info or detect_platform()
    if not platform_info.supported:
        raise RuntimeError(platform_info.reason or "unsupported platform")
    environment = dict(os.environ if env is None else env)
    home = Path(environment.get("USERPROFILE") or environment.get("HOME") or Path.home())
    override = environment.get("EXTELLA_DATA_ROOT")
    if platform_info.system == "Darwin":
        data_root = Path(override) if override else home / "Library" / "Application Support" / "Extella"
        toolbar_root = home / "Library" / "Application Support" / "extella-desktop"
        autostart_root = home / "Library" / "LaunchAgents"
    else:
        local_app_data = Path(environment.get("LOCALAPPDATA") or home / "AppData" / "Local")
        app_data = Path(environment.get("APPDATA") or home / "AppData" / "Roaming")
        data_root = Path(override) if override else local_app_data / "Extella"
        toolbar_root = app_data / "extella-desktop"
        autostart_root = data_root / "ScheduledTasks"
    return ClientPaths(
        data_root=data_root,
        toolbar_root=toolbar_root,
        plugins_root=data_root / "plugins",
        wizard_root=data_root / "wizard" / "app",
        runtime_root=data_root / "runtime",
        state_root=data_root / "state",
        logs_root=data_root / "logs",
        autostart_root=autostart_root,
    )
