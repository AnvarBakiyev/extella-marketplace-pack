import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


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
            "entrypoints": {
                "macos": "installer/client_install.py",
                "windows11": "installer/client_install.py",
            },
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
        "uninstall": {
            "entrypoint": "installer/client_uninstall.py",
            "preserves": ["user-data"],
        },
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

    def test_expert_names_are_not_mistaken_for_account_agent_ids(self):
        plugin = valid_plugin()
        plugin["experts"]["required"] = ["agent_flash_role"]
        self.assertEqual([], release_gate.validate_plugin(self.write(plugin)))

    def test_account_agent_id_is_rejected(self):
        plugin = valid_plugin()
        plugin["source"]["revision"] = "agent_AbCd0123456789"
        issues = release_gate.validate_plugin(self.write(plugin))
        self.assertIn("security.agent_id", {issue.code for issue in issues})


class ToolbarSourceGateTests(unittest.TestCase):
    def _fixture(self, root: Path, *, canonical: bytes, distributed: bytes):
        marketplace = root / "marketplace"
        toolbar = root / "toolbar"
        (marketplace / "toolbar").mkdir(parents=True)
        (marketplace / "toolbar/toolbar.js").write_bytes(distributed)
        (toolbar / "toolbar/build").mkdir(parents=True)
        (toolbar / "toolbar/build/toolbar.js").write_bytes(canonical)
        (toolbar / "scripts").mkdir()
        (toolbar / "scripts/check-reproducible-build.js").write_text("// fixture")
        release = {
            "sourceRepositories": [{"id": "toolbar", "revision": "1" * 40}]
        }
        return marketplace, toolbar, release

    def _run(self, marketplace, toolbar, release):
        completed = [
            subprocess.CompletedProcess([], 0, "passed", ""),
            subprocess.CompletedProcess([], 0, "1" * 40 + "\n", ""),
        ]
        with patch.object(release_gate.subprocess, "run", side_effect=completed):
            return release_gate.validate_toolbar_source(marketplace, toolbar, release)

    def test_exact_reproducible_toolbar_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self._fixture(Path(directory), canonical=b"same", distributed=b"same")
            self.assertEqual(self._run(*fixture), [])

    def test_distribution_drift_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self._fixture(Path(directory), canonical=b"canonical", distributed=b"stale")
            issues = self._run(*fixture)
        self.assertIn("toolbar.distribution_drift", {issue.code for issue in issues})


class CapDependencyGateTests(unittest.TestCase):
    def test_capability_using_shared_bridge_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "experts").mkdir()
            (root / "experts/cap_example.py").write_text(
                "def cap_example():\n"
                "    from extella_expert_bridge import path_or_error\n"
                "    return path_or_error('ffmpeg')\n",
                encoding="utf-8",
            )
            self.assertEqual([], release_gate.validate_cap_dependency_contract(root))

    def test_private_capability_resolver_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "experts").mkdir()
            (root / "experts/cap_example.py").write_text(
                "def cap_example():\n"
                "    import shutil\n"
                "    return shutil.which('ffmpeg') or '/opt/homebrew/bin/ffmpeg'\n",
                encoding="utf-8",
            )
            issues = release_gate.validate_cap_dependency_contract(root)
        codes = {issue.code for issue in issues}
        self.assertIn("dependency.cap_bridge", codes)
        self.assertIn("dependency.direct_which", codes)
        self.assertIn("dependency.fixed_homebrew_path", codes)


if __name__ == "__main__":
    unittest.main()
