"""Privacy-minimal local stability counters.

No network transport is defined here. Only a fixed allow-list of categorical
fields is persisted, so tokens, paths, commands, documents, and log text cannot
enter the aggregate by accident.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import re
import tempfile
import time
from typing import Any


_CATEGORY = re.compile(r"^[A-Za-z0-9_.-]{1,96}$")
_PLATFORMS = {"macos-x86_64", "macos-arm64", "windows11-x86_64"}
_ARCHITECTURES = {"x86_64", "arm64"}


@dataclass(frozen=True)
class StabilityEvent:
    platform: str
    architecture: str
    component: str
    release_version: str
    error_class: str
    install_stage: str
    success: bool

    def validated(self) -> "StabilityEvent":
        if self.platform not in _PLATFORMS:
            raise ValueError("unsupported telemetry platform")
        if self.architecture not in _ARCHITECTURES:
            raise ValueError("unsupported telemetry architecture")
        for value in (
            self.component,
            self.release_version,
            self.error_class,
            self.install_stage,
        ):
            if not _CATEGORY.fullmatch(value):
                raise ValueError("telemetry contains a non-categorical value")
        return self

    def to_wire(self) -> dict[str, Any]:
        payload = asdict(self.validated())
        return {
            "platform": payload["platform"],
            "architecture": payload["architecture"],
            "component": payload["component"],
            "releaseVersion": payload["release_version"],
            "errorClass": payload["error_class"],
            "installStage": payload["install_stage"],
            "success": payload["success"],
        }


def record_local_aggregate(path: Path, event: StabilityEvent) -> dict[str, Any]:
    wire = event.to_wire()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        payload = {"schemaVersion": 1, "transport": "disabled", "aggregates": []}
    if not isinstance(payload, dict) or not isinstance(payload.get("aggregates"), list):
        payload = {"schemaVersion": 1, "transport": "disabled", "aggregates": []}
    now = int(time.time())
    row = next(
        (
            item
            for item in payload["aggregates"]
            if isinstance(item, dict)
            and all(item.get(key) == value for key, value in wire.items())
        ),
        None,
    )
    if row is None:
        row = {**wire, "count": 0, "lastAt": now}
        payload["aggregates"].append(row)
    row["count"] = int(row.get("count") or 0) + 1
    row["lastAt"] = now
    payload["updatedAt"] = now
    payload["aggregates"] = sorted(
        payload["aggregates"],
        key=lambda item: tuple(str(item.get(key, "")) for key in wire),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return payload


__all__ = ["StabilityEvent", "record_local_aggregate"]
