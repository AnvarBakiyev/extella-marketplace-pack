#!/usr/bin/env python3
"""Retired standalone Activity Center uninstaller."""

from __future__ import annotations

import json


def main() -> int:
    print(
        json.dumps(
            {
                "status": "failed",
                "errorClass": "standalone_component_uninstaller_retired",
                "message": (
                    "Use the verified Extella Client bootstrap with --uninstall/-Uninstall. "
                    "This standalone entrypoint preserved all files and user data."
                ),
            },
            ensure_ascii=False,
        )
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
