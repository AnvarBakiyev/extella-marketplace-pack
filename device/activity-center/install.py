#!/usr/bin/env python3
"""Install the Activity Center device observer for the modular toolbar build."""

from __future__ import annotations

import json
import os
import plistlib
import shutil
import subprocess
from glob import glob
from pathlib import Path


LABEL = "ai.extella.activity-center"


def listener_site_packages() -> list[Path]:
    pattern = str(
        Path.home()
        / ".cache"
        / "uv"
        / "archive-v0"
        / "*"
        / "lib"
        / "python3.*"
        / "site-packages"
        / "extella_listener"
    )
    return [Path(listener_dir).parent for listener_dir in glob(pattern)]


def install_hooks(hook_source: Path) -> list[str]:
    installed: list[str] = []
    expected = "import extella_activity_hook; extella_activity_hook.activate()\n"
    for site_packages in listener_site_packages():
        shutil.copy2(hook_source, site_packages / hook_source.name)
        (site_packages / "extella_activity_center.pth").write_text(
            expected, encoding="utf-8"
        )
        installed.append(str(site_packages))
    return installed


def install_launch_agent(support_dir: Path) -> Path:
    launch_agents = Path.home() / "Library" / "LaunchAgents"
    launch_agents.mkdir(parents=True, exist_ok=True)
    plist_path = launch_agents / f"{LABEL}.plist"
    state_dir = Path.home() / ".extella" / "activity-center"
    state_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "Label": LABEL,
        "ProgramArguments": ["/usr/bin/python3", str(support_dir / "server.py")],
        "RunAtLoad": True,
        "KeepAlive": True,
        "ProcessType": "Background",
        "StandardOutPath": str(state_dir / "bridge.log"),
        "StandardErrorPath": str(state_dir / "bridge.error.log"),
        "EnvironmentVariables": {"PYTHONUNBUFFERED": "1"},
    }
    with plist_path.open("wb") as handle:
        plistlib.dump(payload, handle, sort_keys=True)

    domain = f"gui/{os.getuid()}"
    service = f"{domain}/{LABEL}"
    loaded = (
        subprocess.run(
            ["launchctl", "print", service], check=False, capture_output=True
        ).returncode
        == 0
    )
    if loaded:
        subprocess.run(["launchctl", "kickstart", "-k", service], check=True)
    else:
        subprocess.run(
            ["launchctl", "bootstrap", domain, str(plist_path)], check=True
        )
    return plist_path


def main() -> None:
    if os.uname().sysname != "Darwin":
        print("Activity Center device observer is currently supported on macOS only")
        return

    root = Path(__file__).resolve().parent
    support_dir = (
        Path.home() / "Library" / "Application Support" / "Extella Activity Center"
    )
    support_dir.mkdir(parents=True, exist_ok=True)
    sources = (
        root / "bridge" / "server.py",
        root / "bridge" / "activity_model.py",
        root / "bridge" / "service_manager.py",
        root / "bridge" / "task_state.py",
        root / "instrumentation" / "extella_activity_hook.py",
    )
    for source in sources:
        shutil.copy2(source, support_dir / source.name)

    hook_paths = install_hooks(support_dir / "extella_activity_hook.py")
    boot_source = root.parent / "boot" / "restart_local_servers.py"
    boot_target = Path.home() / "extella-plugins" / "_boot" / boot_source.name
    boot_updated = False
    if boot_source.exists() and boot_target.parent.is_dir():
        shutil.copy2(boot_source, boot_target)
        boot_updated = True
    plist_path = install_launch_agent(support_dir)
    manifest = {
        "version": 3,
        "supportDir": str(support_dir),
        "launchAgent": str(plist_path),
        "hookPaths": hook_paths,
        "bootControllerUpdated": boot_updated,
    }
    (support_dir / "install.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    print(f"Activity Center observer installed ({len(hook_paths)} listener hooks)")
    print("Activity API: http://127.0.0.1:8799")


if __name__ == "__main__":
    main()
