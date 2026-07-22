import json
import tempfile
import unittest
from pathlib import Path
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

    def test_locations_and_account_config_use_platform_native_root(self):
        from runtime.extella_runtime.paths import client_paths
        from runtime.extella_runtime.platforms import detect_platform

        mac = detect_platform(system="Darwin", architecture="arm64", release="15")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            env = {"HOME": str(root / "home"), "EXTELLA_DATA_ROOT": str(root / "data")}
            paths = client_paths(platform_info=mac, env=env)
            config = root / "data/wizard/app/config.json"
            config.parent.mkdir(parents=True)
            config.write_text(json.dumps({"agent_id": "agent_test"}), encoding="utf-8")
            with patch("runtime.extella_expert_bridge.client_paths", return_value=paths):
                self.assertEqual(extella_expert_bridge.locations()["apps_root"], str(root / "data/apps"))
                self.assertEqual(extella_expert_bridge.account_config()["agent_id"], "agent_test")

    def test_knowledge_paths_are_collision_resistant_and_migrate_matching_legacy_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "knowledge"
            with patch(
                "runtime.extella_expert_bridge.locations",
                return_value={"knowledge_root": str(root)},
            ):
                first = Path(extella_expert_bridge.knowledge_path("База один"))
                second = Path(extella_expert_bridge.knowledge_path("База дваа"))
                self.assertNotEqual(first, second)
                self.assertEqual(first.parent, root)

                legacy = root / "______.json"
                legacy.write_text(
                    json.dumps({"name": "Знания", "chunks": []}), encoding="utf-8"
                )
                migrated = Path(extella_expert_bridge.knowledge_path("Знания"))
                self.assertTrue(migrated.is_file())
                self.assertFalse(legacy.exists())

    def test_service_control_builds_private_runtime_spec(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = type("Paths", (), {
                "state_root": root / "state",
                "logs_root": root / "logs",
            })()
            supervisor = unittest.mock.Mock()
            supervisor.status.return_value = {"status": "stopped", "pid": None}
            with (
                patch("runtime.extella_expert_bridge.client_paths", return_value=paths),
                patch("runtime.extella_expert_bridge.ProcessSupervisor", return_value=supervisor),
            ):
                result = extella_expert_bridge.service_control(
                    "status", runtime_id="third-party.demo", name="Demo",
                    argv=["/runtime/python", "server.py"], cwd=str(root), port=8888,
                    health_url="http://127.0.0.1:8888/",
                )
        self.assertEqual(result["status"], "stopped")
        spec = supervisor.status.call_args.args[0]
        self.assertEqual(spec.log_path.name, "third-party.demo.log")
        self.assertNotIn("/runtime/python", str(result))

    def test_registry_bridge_strips_secrets_and_removes_only_registration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            registry = root / "plugins/_registry"
            plugin_root = root / "plugins/demo"
            registry.mkdir(parents=True)
            plugin_root.mkdir(parents=True)
            (plugin_root / "user-data.txt").write_text("preserve", encoding="utf-8")
            manifest = {
                "id": "demo",
                "type": "github",
                "ui": {"runtimeId": "demo", "rootPath": str(plugin_root)},
                "api_token": "must-not-leave-device",
            }
            (registry / "demo.json").write_text(json.dumps(manifest), encoding="utf-8")
            with (
                patch(
                    "runtime.extella_expert_bridge.locations",
                    return_value={"plugin_registry": str(registry)},
                ),
                patch("runtime.extella_expert_bridge.activity_service_control") as control,
            ):
                listed = extella_expert_bridge.plugin_registry_list("demo")
                report = extella_expert_bridge.plugin_registration_remove("demo")
            self.assertEqual(listed[0]["id"], "demo")
            self.assertNotIn("api_token", listed[0])
            self.assertTrue(report["userFilesPreserved"])
            self.assertTrue((plugin_root / "user-data.txt").is_file())
            control.assert_called_once_with("demo", "stop")

    def test_registry_bridge_refuses_to_remove_bundled_registration(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = Path(directory) / "plugins/_registry"
            registry.mkdir(parents=True)
            manifest_path = registry / "extella_travel_agency.json"
            manifest_path.write_text(
                json.dumps({
                    "id": "extella_travel_agency",
                    "classification": "bundled",
                    "service": {"owner": "extella_travel_agency"},
                }),
                encoding="utf-8",
            )
            with (
                patch(
                    "runtime.extella_expert_bridge.locations",
                    return_value={"plugin_registry": str(registry)},
                ),
                patch("runtime.extella_expert_bridge.activity_service_control") as control,
            ):
                report = extella_expert_bridge.plugin_registration_remove("extella_travel_agency")
            self.assertEqual(report["status"], "blocked")
            self.assertTrue(manifest_path.is_file())
            control.assert_not_called()


if __name__ == "__main__":
    unittest.main()
