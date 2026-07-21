#!/usr/bin/env python3
"""Install the shared Extella runtime after Computer Doctor preflight."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import site
import sys

try:
    from extella_runtime.paths import client_paths
    from extella_runtime.platforms import PlatformInfo, detect_platform
    from extella_runtime.transaction import InstallationError, InstallTransaction
except ModuleNotFoundError:  # repository tests import this file as runtime.install_runtime
    from runtime.extella_runtime.paths import client_paths
    from runtime.extella_runtime.platforms import PlatformInfo, detect_platform
    from runtime.extella_runtime.transaction import InstallationError, InstallTransaction


def _listener_roots(env: dict[str, str]) -> list[Path]:
    home = Path(env.get("USERPROFILE") or env.get("HOME") or Path.home())
    candidates = [home / ".cache" / "uv" / "archive-v0"]
    if env.get("LOCALAPPDATA"):
        candidates.append(Path(env["LOCALAPPDATA"]) / "uv" / "cache" / "archive-v0")
    if env.get("UV_CACHE_DIR"):
        candidates.append(Path(env["UV_CACHE_DIR"]) / "archive-v0")
    roots: list[Path] = []
    seen: set[str] = set()
    patterns = (
        "*/lib/python*/site-packages/extella_listener",
        "*/*.data/purelib/extella_listener",
        "*/Lib/site-packages/extella_listener",
    )
    for archive in candidates:
        for pattern in patterns:
            for listener in archive.glob(pattern):
                parent = listener.parent
                identity = str(parent)
                if identity not in seen:
                    seen.add(identity)
                    roots.append(parent)
    return roots


def _source_runtime() -> Path:
    return Path(__file__).resolve().parent


def install(
    *,
    release_version: str,
    env: dict[str, str] | None = None,
    platform_info: PlatformInfo | None = None,
    import_roots: list[Path] | None = None,
) -> dict:
    environment = dict(os.environ if env is None else env)
    platform_info = platform_info or detect_platform()
    if not platform_info.supported:
        raise InstallationError(platform_info.reason or "unsupported platform")
    paths = client_paths(platform_info=platform_info, env=environment)
    source = _source_runtime()
    transaction = InstallTransaction(
        release_version=release_version,
        state_root=paths.state_root / "runtime",
    )

    def copy_runtime() -> str:
        for item in sorted((source / "extella_runtime").glob("*.py")):
            transaction.atomic_copy(item, paths.runtime_root / "extella_runtime" / item.name)
        transaction.atomic_copy(
            source / "extella_expert_bridge.py",
            paths.runtime_root / "extella_expert_bridge.py",
        )
        return "shared runtime files installed"

    def install_import_hooks() -> str:
        targets: list[Path] = list(import_roots or [])
        if import_roots is None:
            user_site = site.getusersitepackages()
            if isinstance(user_site, str) and user_site:
                targets.append(Path(user_site))
            targets.extend(_listener_roots(environment))
        unique = list(dict.fromkeys(targets))
        if not unique:
            raise InstallationError("no Python import-hook target could be discovered")
        content = (str(paths.runtime_root) + "\n").encode("utf-8")
        for target in unique:
            transaction.atomic_write(content, target / "extella_client_runtime.pth", mode=0o644)
        return f"runtime import hook installed in {len(unique)} environment(s)"

    transaction.run("runtime.files", copy_runtime)
    transaction.run("runtime.import_hooks", install_import_hooks)
    return transaction.commit()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-version", required=True)
    parser.add_argument("--compact", action="store_true")
    args = parser.parse_args()
    try:
        report = install(release_version=args.release_version)
    except Exception as exc:
        payload = {
            "schemaVersion": 1,
            "status": "failed",
            "errorClass": type(exc).__name__,
            "message": str(exc)[:500],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=None if args.compact else 2))
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=None if args.compact else 2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
