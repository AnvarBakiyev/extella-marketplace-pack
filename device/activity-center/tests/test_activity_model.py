from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bridge"))

from activity_model import build_activity  # noqa: E402


class ActivityModelTests(unittest.TestCase):
    def test_translates_background_tasks_and_correlates_worker(self) -> None:
        task_id = "889d92cb-d13f-4235-b45e-8c180924eef2"
        events = [
            {"ts": "2026-07-15T15:54:05+00:00", "pid": 100, "ppid": 1, "type": "received", "taskId": task_id},
            {"ts": "2026-07-15T15:54:06+00:00", "pid": 101, "ppid": 100, "type": "identified", "function": "wz_scheduler_tick"},
            {"ts": "2026-07-15T15:54:33+00:00", "pid": 100, "ppid": 1, "type": "result", "taskId": task_id, "summary": {"checked": 1, "noRuns": True, "sourceIds": ["wz_20260708_2d457f"], "channel": "telegram"}},
            {"ts": "2026-07-15T15:54:34+00:00", "pid": 100, "ppid": 1, "type": "completed", "taskId": task_id},
        ]
        activity = build_activity(events, {"count": 1, "orphaned": 0, "processes": []})
        self.assertEqual(activity["health"], "ok")
        self.assertEqual(activity["history"][0]["title"], "Проверено расписание")
        self.assertEqual(activity["history"][0]["detail"], "Проверено автоматизаций: 1. Запусков не потребовалось.")
        self.assertEqual(activity["history"][0]["category"], "background")
        self.assertEqual(activity["history"][0]["origin"], "AI Автоматизации · планировщик Extella")
        self.assertTrue(activity["history"][0]["recurring"])
        self.assertEqual(activity["history"][0]["manageTarget"], "automations")
        self.assertEqual(activity["history"][0]["sourceIds"], ["wz_20260708_2d457f"])

    def test_links_telegram_check_to_same_scheduler_cycle(self) -> None:
        scheduler_id = "889d92cb-d13f-4235-b45e-8c180924eef2"
        telegram_id = "68431d82-b22f-4848-88d7-9905c5d3bef0"
        events = [
            {"ts": "2026-07-15T15:54:05+00:00", "pid": 100, "ppid": 1, "type": "received", "taskId": scheduler_id},
            {"ts": "2026-07-15T15:54:06+00:00", "pid": 101, "ppid": 100, "type": "identified", "function": "wz_scheduler_tick"},
            {"ts": "2026-07-15T15:54:20+00:00", "pid": 100, "ppid": 1, "type": "received", "taskId": telegram_id},
            {"ts": "2026-07-15T15:54:21+00:00", "pid": 102, "ppid": 100, "type": "identified", "function": "wz_connector_telegram"},
            {"ts": "2026-07-15T15:54:28+00:00", "pid": 100, "ppid": 1, "type": "completed", "taskId": telegram_id},
            {"ts": "2026-07-15T15:54:33+00:00", "pid": 100, "ppid": 1, "type": "result", "taskId": scheduler_id, "summary": {"sourceIds": ["wz_20260708_2d457f"], "channel": "telegram"}},
            {"ts": "2026-07-15T15:54:34+00:00", "pid": 100, "ppid": 1, "type": "completed", "taskId": scheduler_id},
        ]
        activity = build_activity(events, {"count": 1, "orphaned": 0, "processes": []})
        telegram = next(task for task in activity["history"] if task["function"] == "wz_connector_telegram")
        self.assertEqual(telegram["sourceIds"], ["wz_20260708_2d457f"])
        self.assertEqual(telegram["manageLabel"], "Открыть расписание")

    def test_warns_about_orphaned_listeners(self) -> None:
        activity = build_activity([], {"count": 3, "orphaned": 2, "processes": []})
        self.assertEqual(activity["health"], "warning")
        self.assertEqual(activity["headline"], "Найдены лишние процессы Extella")

    def test_marks_tasks_from_restarted_listener_as_interrupted(self) -> None:
        task_id = "4287e350-0de9-4e4c-9287-a419cccd0bd3"
        events = [
            {"ts": "2026-07-15T16:16:07+00:00", "pid": 100, "ppid": 1, "type": "received", "taskId": task_id},
            {"ts": "2026-07-15T16:16:08+00:00", "pid": 101, "ppid": 100, "type": "identified", "function": "wz_scheduler_tick"},
        ]
        activity = build_activity(events, {"count": 1, "orphaned": 0, "processes": [{"pid": 200, "ppid": 2}]})
        self.assertFalse(activity["active"])
        self.assertEqual(activity["history"][0]["status"], "interrupted")
        self.assertEqual(activity["history"][0]["title"], "Прервана проверка расписания")


if __name__ == "__main__":
    unittest.main()
