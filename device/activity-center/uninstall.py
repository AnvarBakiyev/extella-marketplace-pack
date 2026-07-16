#!/usr/bin/env python3
"""Remove the Activity Center device observer without touching toolbar.js."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from install import LABEL, listener_site_packages


def main() -> None:
    for site_packages in listener_site_packages():
        for name in ("extella_activity_hook.py", "extella_activity_center.pth"):
            try:
                (site_packages / name).unlink()
            except FileNotFoundError:
                pass

    domain = f"gui/{os.getuid()}"
    subprocess.run(
        ["launchctl", "bootout", f"{domain}/{LABEL}"],
        check=False,
        capture_output=True,
    )
    plist = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
    try:
        plist.unlink()
    except FileNotFoundError:
        pass

    support_dir = (
        Path.home() / "Library" / "Application Support" / "Extella Activity Center"
    )
    if support_dir.exists():
        shutil.rmtree(support_dir)
    print("Activity Center device observer removed; rebuild toolbar to remove its UI")


if __name__ == "__main__":
    main()
