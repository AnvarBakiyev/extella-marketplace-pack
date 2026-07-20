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
    # extella-listener раскладывается ПО-РАЗНОМУ в зависимости от версии колеса:
    #   старые           → .../archive-v0/<hash>/lib/python3.*/site-packages/extella_listener
    #   1.2.1+ (purelib) → .../archive-v0/<hash>/extella_listener-*.data/purelib/extella_listener
    # Прежний glob видел только первую раскладку. На машине со свежим листенером (у клиента как раз
    # он) хук не ставился НИ КУДА → наблюдатель молчит, виджет пуст при живых логах (Гульжан, 20.07).
    base = Path.home() / ".cache" / "uv" / "archive-v0"
    patterns = [
        str(base / "*" / "lib" / "python3.*" / "site-packages" / "extella_listener"),
        str(base / "*" / "*.data" / "purelib" / "extella_listener"),
    ]
    dirs = []
    seen = set()
    for pat in patterns:
        for listener_dir in glob(pat):
            parent = Path(listener_dir).parent
            if str(parent) not in seen:
                seen.add(str(parent))
                dirs.append(parent)
    return dirs


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


LOCAL_SERVERS_LABEL = "ai.extella.local-servers"


def install_local_servers_agent(restart_script: Path) -> Path:
    # Автоподъём локальных серверов плагинов (Travel Agency и др. с ui.type=local_server).
    # Механизм существовал только на dev-машине: у клиента после перезагрузки server.py плагина
    # никто не поднимал → «localhost не поднялся» (Гульжан, 20.07). Ставим тот же LaunchAgent,
    # что работал вручную: RunAtLoad + перепроверка раз в 10 мин (идемпотентно, поднимает и
    # упавшие). Сам restart_local_servers.py идемпотентен: занятые порты пропускает.
    launch_agents = Path.home() / "Library" / "LaunchAgents"
    launch_agents.mkdir(parents=True, exist_ok=True)
    plist_path = launch_agents / f"{LOCAL_SERVERS_LABEL}.plist"
    boot_dir = restart_script.parent
    payload = {
        "Label": LOCAL_SERVERS_LABEL,
        "ProgramArguments": ["/usr/bin/python3", str(restart_script)],
        "RunAtLoad": True,
        "StartInterval": 600,
        "StandardOutPath": str(boot_dir / "launchagent.out.log"),
        "StandardErrorPath": str(boot_dir / "launchagent.err.log"),
    }
    with plist_path.open("wb") as handle:
        plistlib.dump(payload, handle, sort_keys=True)
    domain = f"gui/{os.getuid()}"
    service = f"{domain}/{LOCAL_SERVERS_LABEL}"
    loaded = (
        subprocess.run(
            ["launchctl", "print", service], check=False, capture_output=True
        ).returncode
        == 0
    )
    if loaded:
        subprocess.run(["launchctl", "kickstart", "-k", service], check=False)
    else:
        subprocess.run(
            ["launchctl", "bootstrap", domain, str(plist_path)], check=False
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

    # Автоподъём локальных серверов плагинов. Раньше boot-скрипт копировался ТОЛЬКО если папка
    # _boot уже была — на чистом клиенте её нет, поэтому не копировался НИКОГДА, и LaunchAgent
    # автоподъёма не ставился. Теперь папку создаём, скрипт кладём всегда, агент поднимаем — и
    # прогоняем скрипт разово, чтобы серверы поднялись сразу, не дожидаясь перезагрузки.
    boot_source = root.parent / "boot" / "restart_local_servers.py"
    boot_target = Path.home() / "extella-plugins" / "_boot" / boot_source.name
    boot_updated = False
    local_servers_agent = None
    if boot_source.exists():
        boot_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(boot_source, boot_target)
        boot_updated = True
        try:
            local_servers_agent = str(install_local_servers_agent(boot_target))
            subprocess.run(["/usr/bin/python3", str(boot_target)],
                           check=False, capture_output=True, timeout=60)
        except Exception as exc:  # noqa: BLE001 — доставка виджета не должна падать из-за автоподъёма
            print(f"  ~ local-servers autostart: {exc}")

    plist_path = install_launch_agent(support_dir)
    manifest = {
        "version": 4,
        "supportDir": str(support_dir),
        "launchAgent": str(plist_path),
        "localServersAgent": local_servers_agent,
        "hookPaths": hook_paths,
        "bootControllerUpdated": boot_updated,
    }
    (support_dir / "install.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    print(f"Activity Center observer installed ({len(hook_paths)} listener hooks)")
    if local_servers_agent:
        print("Local-servers autostart installed (ai.extella.local-servers)")
    print("Activity API: http://127.0.0.1:8799")


if __name__ == "__main__":
    main()
