from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bridge"))

from task_state import dismiss_tasks, read_dismissed  # noqa: E402


class TaskStateTests(unittest.TestCase):
    def test_dismissed_tasks_persist_without_invalid_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tasks.json"
            dismiss_tasks(["task-1", "bad/id", "task-2"], path)
            self.assertEqual(read_dismissed(path), {"task-1", "task-2"})
