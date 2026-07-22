"""Persist task rows the user chose to remove from Activity Center."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Iterable
from extella_runtime.paths import client_paths


STATE_FILE = Path(os.environ.get("EXTELLA_TASK_STATE") or (
    client_paths().state_root / "activity" / "tasks.json"
))
_TASK_ID = re.compile(r"^[A-Za-z0-9_.-]{1,160}$")


def read_dismissed(path: Path = STATE_FILE) -> set[str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    values = payload.get("dismissed", []) if isinstance(payload, dict) else []
    return {
        value
        for value in values
        if isinstance(value, str) and _TASK_ID.fullmatch(value)
    }


def dismiss_tasks(task_ids: Iterable[str], path: Path = STATE_FILE) -> set[str]:
    dismissed = read_dismissed(path)
    dismissed.update(
        task_id
        for task_id in task_ids
        if isinstance(task_id, str) and _TASK_ID.fullmatch(task_id)
    )
    # The lifecycle event file is bounded on read, so an unbounded tombstone
    # set has no value. Keep a deterministic bounded set.
    retained = sorted(dismissed)[-2000:]
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps({"dismissed": retained}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, path)
    return set(retained)
