"""Small stable bridge imported by device-side Extella experts.

The client installer makes this module importable by the listener runtime. The
dependency implementation remains in one place instead of being copied into
every expert.
"""

from __future__ import annotations

from typing import Any

try:
    from extella_runtime.ensure_tool import ensure_tool
except ModuleNotFoundError:  # repository tests import this file as runtime.extella_expert_bridge
    from runtime.extella_runtime.ensure_tool import ensure_tool


def ensure(name: str, *, repair: bool = False) -> dict[str, Any]:
    return ensure_tool(name, allow_install=repair).to_dict()


def path_or_error(name: str, *, repair: bool = False) -> tuple[str | None, dict[str, Any]]:
    result = ensure(name, repair=repair)
    path = result.get("path") if result.get("ready") else None
    return path, result
