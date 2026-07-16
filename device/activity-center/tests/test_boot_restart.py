from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "boot" / "restart_local_servers.py"
SPEC = importlib.util.spec_from_file_location("restart_local_servers_test", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class BootRestartTests(unittest.TestCase):
    def test_activity_center_disabled_services_are_not_auto_started(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "services.json"
            state.write_text(
                json.dumps({"disabled": ["demo_local", 123, None]}),
                encoding="utf-8",
            )
            self.assertEqual(MODULE.load_disabled(state), {"demo_local"})


if __name__ == "__main__":
    unittest.main()
