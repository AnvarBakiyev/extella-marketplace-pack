import unittest
from unittest.mock import patch

from runtime import extella_expert_bridge
from runtime.extella_runtime.ensure_tool import EnsureResult


class ExpertBridgeTests(unittest.TestCase):
    @patch("runtime.extella_expert_bridge.ensure_tool")
    def test_bridge_returns_json_safe_result(self, mocked):
        mocked.return_value = EnsureResult(
            "node", "ready", path="/runtime/node", version="v22.0.0", platform="macos-arm64"
        )
        path, result = extella_expert_bridge.path_or_error("node")
        self.assertEqual(path, "/runtime/node")
        self.assertTrue(result["ready"])


if __name__ == "__main__":
    unittest.main()
