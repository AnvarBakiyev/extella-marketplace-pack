#!/usr/bin/env python3
"""Verify an installed Extella Client without mutating it."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from installer.account import prompt_token  # noqa: E402
from installer.verification import verify_installed_client  # noqa: E402
from runtime.extella_runtime.platforms import detect_platform  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the installed Extella Client release")
    parser.add_argument("--api-base", default="https://api.extella.ai")
    args = parser.parse_args()
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
        report = verify_installed_client(
            token=token,
            api_base=args.api_base,
            platform_info=platform_info,
        )
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
