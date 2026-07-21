#!/usr/bin/env python3
"""Stable JSON protocol for the shared Extella dependency resolver."""

from __future__ import annotations

import argparse
import json
import sys

from extella_runtime.ensure_tool import TOOL_SPECS, ensure_tool


def main() -> int:
    parser = argparse.ArgumentParser(description="Resolve or repair an Extella dependency")
    parser.add_argument("tool", choices=sorted(TOOL_SPECS))
    parser.add_argument("--repair", action="store_true")
    args = parser.parse_args()
    result = ensure_tool(args.tool, allow_install=args.repair)
    print(json.dumps(result.to_dict(), ensure_ascii=False))
    return 0 if result.ready else 2


if __name__ == "__main__":
    sys.exit(main())
