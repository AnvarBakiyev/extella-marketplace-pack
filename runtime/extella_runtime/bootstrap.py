"""Safe environment defaults injected into Extella device Python runtimes."""

from __future__ import annotations

import os

from .paths import client_paths
from .platforms import detect_platform


def activate() -> None:
    """Expose standard per-user roots without overwriting explicit configuration."""

    try:
        platform_info = detect_platform()
        if not platform_info.supported:
            return
        paths = client_paths(platform_info=platform_info)
    except Exception:
        return
    defaults = {
        "EXTELLA_DATA_ROOT": str(paths.data_root),
        "EXTELLA_WIZARD_ROOT": str(paths.data_root / "wizard"),
        "EXTELLA_PLUGIN_ROOT": str(paths.plugins_root),
        "EXTELLA_PLUGIN_REGISTRY": str(paths.plugins_root / "_registry"),
        "EXTELLA_ACTIVITY_FILE": str(paths.state_root / "activity" / "events.jsonl"),
        "EXTELLA_SERVICE_STATE": str(paths.state_root / "services.json"),
        "EXTELLA_PROCESS_STATE": str(paths.state_root / "processes.json"),
    }
    for key, value in defaults.items():
        os.environ.setdefault(key, value)


__all__ = ["activate"]
