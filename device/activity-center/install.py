#!/usr/bin/env python3
"""Retired standalone Activity Center installer."""

from __future__ import annotations

import json


def main() -> int:
    print(
        json.dumps(
            {
                "status": "failed",
                "errorClass": "standalone_component_installer_retired",
                "message": (
                    "Activity Center is installed atomically by the versioned Extella Client "
                    "release. This standalone entrypoint made no changes."
                ),
            },
            ensure_ascii=False,
        )
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
