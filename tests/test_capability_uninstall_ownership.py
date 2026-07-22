import importlib.util
import json
import sys
import tempfile
from pathlib import Path
from types import ModuleType
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def load_expert():
    path = ROOT / "experts/catalog_capability_uninstall.py"
    spec = importlib.util.spec_from_file_location("catalog_capability_uninstall_tested", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class CapabilityUninstallOwnershipTests(unittest.TestCase):
    def bridge(self, root: Path):
        bridge = ModuleType("extella_expert_bridge")
        bridge.locations = lambda: {"mcp_root": str(root)}
        return bridge

    def test_missing_ownership_preserves_mcp_allowlist(self):
        module = load_expert()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            allowlist = root / "allowlist.json"
            original = {"servers": {"foreign": {"pkg": "@other/mcp", "title": "Foreign"}}}
            allowlist.write_text(json.dumps(original), encoding="utf-8")
            with patch.dict(sys.modules, {"extella_expert_bridge": self.bridge(root)}):
                result = json.loads(module.catalog_capability_uninstall(
                    "mcp", "foreign", "mcp_connect", "yes"
                ))
            self.assertEqual(result["error_class"], "ownership_not_confirmed")
            self.assertFalse(result["device_removed"])
            self.assertEqual(json.loads(allowlist.read_text(encoding="utf-8")), original)

    def test_owned_mcp_entry_is_removed_atomically(self):
        module = load_expert()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            allowlist = root / "allowlist.json"
            payload = {
                "servers": {
                    "mine": {
                        "pkg": "@extella/example-mcp",
                        "title": "Mine",
                        "owner": "extella_mcp_connect",
                        "installedByExtella": True,
                    },
                    "foreign": {"pkg": "@other/mcp"},
                }
            }
            allowlist.write_text(json.dumps(payload), encoding="utf-8")
            with patch.dict(sys.modules, {"extella_expert_bridge": self.bridge(root)}):
                result = json.loads(module.catalog_capability_uninstall(
                    "mcp", "mine", "mcp_connect", "yes"
                ))
            current = json.loads(allowlist.read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "success")
            self.assertTrue(result["removed"])
            self.assertEqual(set(current["servers"]), {"foreign"})
            self.assertEqual(list(root.glob("*.tmp")), [])

    def test_unowned_model_request_never_calls_ollama(self):
        module = load_expert()
        with patch("urllib.request.urlopen") as opened:
            result = json.loads(module.catalog_capability_uninstall(
                "model", "user-model:latest", "ollama", "no"
            ))
        self.assertEqual(result["error_class"], "ownership_not_confirmed")
        self.assertFalse(result["device_removed"])
        opened.assert_not_called()

    def test_mcp_connect_source_records_owner_and_rejects_collisions(self):
        source = (ROOT / "platform_experts/mcp_connect.py").read_text(encoding="utf-8")
        self.assertIn('"owner": "extella_mcp_connect"', source)
        self.assertIn('"installedByExtella": True', source)
        self.assertIn("уже принадлежит другому MCP-пакету", source)
        self.assertIn("os.replace(tmp, fp)", source)


if __name__ == "__main__":
    unittest.main()
