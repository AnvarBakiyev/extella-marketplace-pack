#!/usr/bin/env python3
"""Retired legacy installer entrypoint.

Extella Client must be installed from an exact, versioned release bundle. This
file remains only so old bookmarks fail loudly instead of silently running the
former account-specific installer.
"""

from __future__ import annotations

import json


def main() -> int:
    print(
        json.dumps(
            {
                "status": "failed",
                "errorClass": "legacy_installer_retired",
                "message": (
                    "This installer is retired and made no changes. Use toolbar/install-all.sh "
                    "on supported macOS or toolbar/install-all.ps1 on Windows 11 x64 with the "
                    "published release bundle URL/path, SHA-256, and byte size."
                ),
            },
            ensure_ascii=False,
        )
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
