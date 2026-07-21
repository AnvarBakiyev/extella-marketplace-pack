import json
import tempfile
import unittest
from pathlib import Path

from runtime.extella_runtime.telemetry import StabilityEvent, record_local_aggregate


class TelemetryTests(unittest.TestCase):
    def test_only_categorical_allow_list_is_aggregated_locally(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "stability.json"
            event = StabilityEvent(
                platform="macos-arm64",
                architecture="arm64",
                component="client-installer",
                release_version="2.0.0-rc.1",
                error_class="none",
                install_stage="complete",
                success=True,
            )
            record_local_aggregate(path, event)
            record_local_aggregate(path, event)
            payload = json.loads(path.read_text())
            self.assertEqual(payload["transport"], "disabled")
            self.assertEqual(payload["aggregates"][0]["count"], 2)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_paths_and_free_text_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "stability.json"
            with self.assertRaises(ValueError):
                record_local_aggregate(
                    path,
                    StabilityEvent(
                        platform="macos-arm64",
                        architecture="arm64",
                        component="/Users/private/client",
                        release_version="2.0.0",
                        error_class="Token abc secret",
                        install_stage="prepare",
                        success=False,
                    ),
                )
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
