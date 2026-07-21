#!/usr/bin/env python3
"""Uninstall Extella Client resources owned by the versioned installer."""

from __future__ import annotations

import json
from pathlib import Path
import sys


sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from installer.account import prompt_token  # noqa: E402
from installer.client import uninstall_client  # noqa: E402
from runtime.extella_runtime.platforms import detect_platform  # noqa: E402


def main() -> int:
    platform_info = detect_platform()
    if not platform_info.supported:
        print(
            json.dumps(
                {
                    "status": "unsupported",
                    "errorClass": "unsupported_platform",
                    "message": platform_info.reason,
                },
                ensure_ascii=False,
            )
        )
        return 3
    token = prompt_token()
    try:
        report = uninstall_client(token=token, platform_info=platform_info)
    except Exception as error:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "errorClass": type(error).__name__,
                    "message": str(error)[:300],
                },
                ensure_ascii=False,
            )
        )
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] in {"uninstalled", "not_installed"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
