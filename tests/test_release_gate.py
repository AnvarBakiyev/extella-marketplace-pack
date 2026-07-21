import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "release_gate.py"
SPEC = importlib.util.spec_from_file_location("release_gate", MODULE_PATH)
assert SPEC and SPEC.loader
release_gate = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = release_gate
SPEC.loader.exec_module(release_gate)


def valid_plugin() -> dict:
    return {
        "schemaVersion": 1,
        "id": "example_plugin",
        "name": "Example",
        "version": "1.0.0",
        "classification": "bundled",
        "source": {"type": "bundled", "locator": "release/plugins/example_plugin.json", "revision": "release"},
        "supportedPlatforms": ["macos-x86_64", "macos-arm64", "windows11-x86_64"],
        "install": {
            "strategy": "bundled",
            "entrypoints": {"macos": "install.sh", "windows11": "install.ps1"},
            "idempotent": True,
            "transactional": True,
            "mutablePaths": ["${EXTELLA_DATA}/example"],
        },
        "runtime": {
            "kind": "local_service",
            "owner": "example_plugin",
            "command": ["${PYTHON}", "${INSTALL_ROOT}/server.py"],
            "port": {"mode": "fixed", "preferred": 19000, "bind": "127.0.0.1"},
            "health": {"type": "http", "path": "/health", "timeoutSeconds": 30},
            "pid": {"strategy": "service_manager", "path": None},
            "autostart": {"macos": "launchagent", "windows11": "scheduled_task"},
        },
        "ui": {"type": "local_server", "entrypoint": "/", "runtimeId": "example_plugin", "smokePath": "/"},
        "artifacts": {"installRoot": "${EXTELLA_DATA}/example", "registryFile": "${EXTELLA_DATA}/_registry/example.json", "files": ["server.py"]},
        "experts": {"required": [], "smoke": []},
        "secrets": [],
        "uninstall": {"entrypoint": "uninstall", "preserves": ["user-data"]},
        "migration": {"strategy": "replace_preserve_data", "fromVersions": ["0.x"]},
        "releaseState": {"advertised": False, "verification": "pending"},
    }


class PluginManifestTests(unittest.TestCase):
    def write(self, data: dict) -> Path:
        tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
        json.dump(data, tmp)
        tmp.close()
        return Path(tmp.name)

    def test_valid_manifest_passes_contract_invariants(self):
        path = self.write(valid_plugin())
        self.assertEqual([], release_gate.validate_plugin(path))

    def test_personal_path_is_rejected(self):
        plugin = valid_plugin()
        plugin["artifacts"]["installRoot"] = "/Users/anvarbakiyev/tool"
        issues = release_gate.validate_plugin(self.write(plugin))
        self.assertIn("security.personal_path", {issue.code for issue in issues})

    def test_static_ready_is_rejected(self):
        plugin = valid_plugin()
        plugin["runtime"]["ready"] = True
        issues = release_gate.validate_plugin(self.write(plugin))
        self.assertIn("runtime.static_ready", {issue.code for issue in issues})

    def test_unverified_capability_cannot_be_advertised(self):
        plugin = valid_plugin()
        plugin["releaseState"]["advertised"] = True
        issues = release_gate.validate_plugin(self.write(plugin))
        self.assertIn("release.unverified_advertisement", {issue.code for issue in issues})


if __name__ == "__main__":
    unittest.main()
