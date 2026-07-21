#!/usr/bin/env python3
"""Uninstall Extella Client resources owned by the versioned installer."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from types import SimpleNamespace


sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from installer.account import prompt_token  # noqa: E402
from installer.client import uninstall_client  # noqa: E402
from runtime.extella_runtime.paths import client_paths  # noqa: E402
from runtime.extella_runtime.platforms import detect_platform  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Uninstall the owned Extella Client release")
    parser.add_argument("--api-base", default="https://api.extella.ai")
    parser.add_argument("--matrix-result", type=Path)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--release-manifest", type=Path)
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
    matrix_values = (args.matrix_result, args.candidate, args.release_manifest)
    if any(matrix_values) and not all(matrix_values):
        print(
            json.dumps(
                {
                    "status": "failed",
                    "errorClass": "matrix_arguments",
                    "message": "Matrix uninstall evidence requires result, candidate, and release manifest paths.",
                },
                ensure_ascii=False,
            )
        )
        return 2
    matrix = None
    if args.matrix_result is not None:
        try:
            try:
                from tools import external_matrix as matrix  # type: ignore[no-redef]
            except ModuleNotFoundError:
                from installer import external_matrix as matrix  # type: ignore[no-redef]
            identity = matrix._candidate_identity(
                args.candidate.resolve(), args.release_manifest.resolve()
            )
            existing = matrix._read_json(args.matrix_result)
            if existing.get("platform") != platform_info.key or existing.get("candidate") != identity:
                raise RuntimeError("matrix evidence belongs to another platform or candidate")
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
    paths = client_paths(platform_info=platform_info)
    account_state = paths.state_root / "account" / "account-state.json"
    token = prompt_token() if account_state.exists() else ""
    try:
        report = uninstall_client(
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
    if matrix is not None and report["status"] == "uninstalled":
        try:
            event = matrix.run(
                SimpleNamespace(
                    phase="uninstalled",
                    expected_platform=platform_info.key,
                    candidate=args.candidate,
                    release_manifest=args.release_manifest,
                    result=args.matrix_result,
                    desktop_evidence=None,
                )
            )
        except Exception as error:
            event = {
                "phase": "uninstalled",
                "status": "failed",
                "errorClass": type(error).__name__,
                "message": str(error)[:300],
            }
        report["matrixEvidence"] = event
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return (
        0
        if report["status"] in {"uninstalled", "not_installed"}
        and report.get("matrixEvidence", {}).get("status", "passed") == "passed"
        else 2
    )


if __name__ == "__main__":
    raise SystemExit(main())
