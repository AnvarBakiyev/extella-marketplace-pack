#!/usr/bin/env python3
"""CLI entrypoint for Extella Computer Doctor."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from extella_runtime.doctor import run_doctor


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extella Computer Doctor")
    parser.add_argument("--repair", action="store_true", help="Allow safe package-manager repairs")
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--port", action="append", type=int, default=[])
    parser.add_argument("--network-url", action="append", default=[])
    parser.add_argument(
        "--require-tool",
        action="append",
        default=[],
        help="Override the required tool list (repeatable)",
    )
    parser.add_argument(
        "--optional-tool",
        action="append",
        default=[],
        help="Override the optional tool list (repeatable)",
    )
    parser.add_argument("--compact", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    kwargs = {}
    if args.require_tool:
        kwargs["required_tools"] = tuple(args.require_tool)
    if args.optional_tool:
        kwargs["optional_tools"] = tuple(args.optional_tool)
    report = run_doctor(
        allow_repair=args.repair,
        data_root=args.data_root,
        ports=args.port,
        network_urls=args.network_url,
        **kwargs,
    )
    indent = None if args.compact else 2
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=indent))
    return 0 if report.ready else 2


if __name__ == "__main__":
    sys.exit(main())
