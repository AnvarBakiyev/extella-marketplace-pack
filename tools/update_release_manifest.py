#!/usr/bin/env python3
"""Refresh artifact checksums in a candidate release manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--manifest", type=Path, default=Path("release/release-manifest.json"))
    args = parser.parse_args()
    root = args.root.resolve()
    manifest_path = args.manifest if args.manifest.is_absolute() else root / args.manifest
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    if data.get("status") != "candidate":
        raise SystemExit("refusing to rewrite checksums for a non-candidate release")
    for artifact in data.get("artifacts", []):
        target = root / artifact["path"]
        if not target.is_file():
            raise SystemExit(f"artifact does not exist: {target}")
        artifact["bytes"] = target.stat().st_size
        artifact["sha256"] = sha256(target)
    manifest_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

