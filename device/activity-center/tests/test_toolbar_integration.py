from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PANEL = ROOT / "toolbar" / "src" / "panels" / "activity-center.js"
BUILD = ROOT / "toolbar" / "build.js"


class ToolbarIntegrationTests(unittest.TestCase):
    def test_activity_panel_is_part_of_modular_build(self) -> None:
        self.assertIn("'activity-center.js'", BUILD.read_text(encoding="utf-8"))
        source = PANEL.read_text(encoding="utf-8")
        self.assertIn("{ id: 'automations', l: 'Расписания' }", source)
        self.assertIn("Регулярные задачи", source)
        self.assertIn("Локальные сервисы Extella", source)
        self.assertIn("X-Extella-Control", source)
        self.assertIn("Очистить выполненные", source)
        self.assertIn("Убрать запись из ленты", source)
        self.assertIn("Cancel в нижней панели Extella", source)
        self.assertIn("PID ", source)
        self.assertIn("right:12px;bottom:12px", source)

    def test_removed_subtitle_does_not_return(self) -> None:
        self.assertNotIn(
            "Понятная лента вместо технического лога",
            PANEL.read_text(encoding="utf-8"),
        )


if __name__ == "__main__":
    unittest.main()
