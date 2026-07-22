#!/usr/bin/env python3
"""Native-bootstrap entrypoint for installing an extracted Extella bundle."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

# The extracted bundle has an exact signed inventory. Imports must not add
# __pycache__ files before verify_bundle() has validated that inventory.
sys.dont_write_bytecode = True

MARKETPLACE_ROOT = Path(__file__).resolve().parents[1]
BUNDLE_ROOT = MARKETPLACE_ROOT.parents[1]
if str(MARKETPLACE_ROOT) not in sys.path:
    sys.path.insert(0, str(MARKETPLACE_ROOT))

from installer.account import prompt_token  # noqa: E402
from installer.client import install_client  # noqa: E402
from runtime.extella_runtime.platforms import detect_platform  # noqa: E402


def _console_progress(event: dict) -> None:
    """Write human progress to stderr while keeping final stdout valid JSON."""

    phase = str(event.get("phase") or "")
    current = int(event.get("current") or 0)
    total = int(event.get("total") or 0)
    raw_item = str(event.get("item") or "")
    item = raw_item if raw_item.replace("_", "").isalnum() else ""
    if phase == "local_prepare":
        message = "[Client] Checking this computer and installing local files…"
    elif phase == "account_repair":
        message = "[Account] Checking for an interrupted earlier installation…"
    elif phase == "account_validation":
        message = "[Account] Validating the Extella account…"
    elif phase == "account_runtime_preflight":
        message = "[Account] Checking cloud expert execution…"
    elif phase == "expert":
        suffix = f": {item}" if item else ""
        message = f"[Account] Expert {current}/{total}{suffix} — install and verification"
    elif phase == "catalog_data":
        message = f"[Account] Catalog data {current}/{total} — install and verification"
    elif phase == "functional_smoke":
        suffix = f": {item}" if item else ""
        message = f"[Account] Final smoke {current}/{total}{suffix}"
    elif phase == "account_complete":
        message = "[Account] Account resources verified."
    elif phase == "service_activation":
        message = "[Services] Starting and verifying Activity Center…"
    elif phase == "commit":
        message = "[Client] Committing the verified installation…"
    elif phase == "complete":
        message = "[Client] Installation complete."
    else:
        return
    print(message, file=sys.stderr, flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle-root", type=Path, default=BUNDLE_ROOT)
    parser.add_argument("--bootstrap-python-root", type=Path)
    parser.add_argument("--no-start", action="store_true")
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
        report = install_client(
            args.bundle_root,
            token=token,
            platform_info=platform_info,
            bootstrap_python_root=args.bootstrap_python_root,
            activate_services=not args.no_start,
            progress=_console_progress,
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
