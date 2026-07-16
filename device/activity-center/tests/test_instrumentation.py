from __future__ import annotations

import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "instrumentation" / "extella_activity_hook.py"
SPEC = importlib.util.spec_from_file_location("extella_activity_hook_test", HOOK)
hook = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(hook)


class InstrumentationTests(unittest.TestCase):
    def test_writes_only_allow_listed_result_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            hook.EVENT_FILE = Path(temp) / "events.jsonl"
            parser = hook._LineParser()
            parser.feed(
                "INFO - Listener - Task 889d92cb-d13f-4235-b45e-8c180924eef2 result: dict = "
                "{'status': 'success', 'checked': 1, 'fired': [], "
                "'inbound_dbg': {'isids': ['wz_20260708_2d457f'], "
                "'polls': [{'sid': 'wz_20260708_2d457f', 'chan': 'telegram'}]}, "
                "'api_token': 'must-not-leak'}\n"
            )
            event = json.loads(hook.EVENT_FILE.read_text(encoding="utf-8"))
            self.assertEqual(event["type"], "result")
            self.assertEqual(event["summary"]["checked"], 1)
            self.assertTrue(event["summary"]["noRuns"])
            self.assertEqual(event["summary"]["sourceIds"], ["wz_20260708_2d457f"])
            self.assertEqual(event["summary"]["channel"], "telegram")
            self.assertNotIn("must-not-leak", hook.EVENT_FILE.read_text(encoding="utf-8"))

    def test_parses_function_name(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            hook.EVENT_FILE = Path(temp) / "events.jsonl"
            hook._LineParser().feed("[Listener] Looking for function: wz_connector_telegram\n")
            event = json.loads(hook.EVENT_FILE.read_text(encoding="utf-8"))
            self.assertEqual(event["function"], "wz_connector_telegram")

    def test_masks_credentials_in_raw_listener_output(self) -> None:
        output = io.StringIO()
        stream = hook._ObservedStream(output)
        stream.write(
            "kwargs={'api_token': 'secret-api'} "
            "GET /bot123456:telegram-secret/getUpdates --crypto-key key-secret\n"
        )
        visible = output.getvalue()
        self.assertNotIn("secret-api", visible)
        self.assertNotIn("telegram-secret", visible)
        self.assertNotIn("key-secret", visible)
        self.assertIn("<redacted>", visible)


if __name__ == "__main__":
    unittest.main()
