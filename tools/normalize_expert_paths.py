#!/usr/bin/env python3
"""Normalize recurring legacy account-config access in shipped experts.

The release gate checks the result. This deterministic helper exists so the
same migration can be replayed when an upstream expert pack is refreshed.
"""

from __future__ import annotations

import argparse
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXPERT_ROOTS = (ROOT / "experts", ROOT / "platform_experts", ROOT / "automations/experts")

LEGACY_CONFIG = (
    'cfg = json.load(open(os.path.join(os.environ.get("EXTELLA_WIZARD_ROOT") '
    'or os.path.expanduser("~/extella_wizard"), "app", "config.json"), encoding="utf-8"))'
)


def expected(source: str) -> str:
    lines = source.splitlines(keepends=True)
    rendered: list[str] = []
    for line in lines:
        if LEGACY_CONFIG in line:
            indent = line[: len(line) - len(line.lstrip())]
            rendered.append(indent + "from extella_expert_bridge import account_config\n")
            rendered.append(indent + "cfg = account_config()\n")
        else:
            rendered.append(line)
    text = "".join(rendered)
    return text.replace(
        "~/extella_wizard/app/config.json",
        "the current device's platform-native Extella account config",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    changed: list[str] = []
    for directory in EXPERT_ROOTS:
        for path in sorted(directory.glob("*.py")):
            current = path.read_text(encoding="utf-8")
            rendered = expected(current)
            if current == rendered:
                continue
            changed.append(path.relative_to(ROOT).as_posix())
            if args.write:
                path.write_text(rendered, encoding="utf-8")
    if changed and not args.write:
        print("expert paths require normalization: " + ", ".join(changed))
        return 1
    if args.write:
        print(f"normalized {len(changed)} expert path contracts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
