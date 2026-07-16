from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bridge"))

import service_manager  # noqa: E402


class ServiceManagerTests(unittest.TestCase):
    def test_discovers_only_registered_local_servers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            registry = Path(tmp)
            (registry / "local.json").write_text(
                json.dumps(
                    {
                        "id": "demo_local",
                        "name": "Demo",
                        "tagline": "A safe local service",
                        "ui": {
                            "type": "local_server",
                            "port": 9123,
                            "rootPath": str(registry / "demo"),
                        },
                        "service": {"launchCmd": "run-with-a-secret"},
                    }
                ),
                encoding="utf-8",
            )
            (registry / "remote.json").write_text(
                json.dumps({"id": "remote", "ui": {"type": "web"}}),
                encoding="utf-8",
            )
            services = service_manager.registry_services(registry)
            self.assertEqual([service["id"] for service in services], ["demo_local"])
            self.assertEqual(services[0]["port"], 9123)

    def test_public_payload_never_exposes_launch_command_or_full_root(self) -> None:
        service = {
            "id": "demo_local",
            "name": "Demo",
            "description": "Local demo",
            "port": 9123,
            "mainFile": "index.html",
            "root": Path("/Users/example/private/project"),
            "launchCommand": "TOKEN=secret python server.py",
            "staticFallback": False,
            "registryFile": "demo_local.json",
        }
        state = {"disabled": [], "launchAgents": {}}
        with (
            patch.object(service_manager, "listening_pids", return_value=[]),
            patch.object(service_manager, "_launch_agents", return_value=[]),
        ):
            public = service_manager._public_service(
                service, state, persist_mapping=False
            )
        serialized = json.dumps(public)
        self.assertNotIn("TOKEN=secret", serialized)
        self.assertNotIn("/Users/example/private", serialized)
        self.assertEqual(public["project"], "project")
        self.assertTrue(public["canStart"])

    def test_unknown_port_owner_cannot_be_stopped(self) -> None:
        service = {
            "id": "demo_local",
            "name": "Demo",
            "description": "",
            "port": 9123,
            "mainFile": "",
            "root": Path("/Users/example/expected"),
            "launchCommand": "python server.py",
            "staticFallback": False,
            "registryFile": "demo_local.json",
        }
        state = {"disabled": [], "launchAgents": {}}
        with (
            patch.object(service_manager, "listening_pids", return_value=[4321]),
            patch.object(service_manager, "_launch_agents", return_value=[]),
            patch.object(
                service_manager,
                "_process_info",
                return_value={
                    "pid": 4321,
                    "ppid": 1,
                    "process": "Python",
                    "cwd": Path("/Users/example/someone-else"),
                },
            ),
        ):
            public = service_manager._public_service(
                service, state, persist_mapping=False
            )
        self.assertFalse(public["canStop"])
        self.assertIn("не подтверждена", public["controlBlockedReason"])

    def test_rejected_stop_does_not_persist_disabled_state(self) -> None:
        service = {"id": "demo_local", "port": 9123}
        with (
            patch.object(service_manager, "_service_by_id", return_value=service),
            patch.object(
                service_manager,
                "_read_state",
                return_value={"disabled": [], "launchAgents": {}},
            ),
            patch.object(
                service_manager,
                "_public_service",
                return_value={
                    "status": "running",
                    "canStop": False,
                    "controlBlockedReason": "not owned",
                },
            ),
            patch.object(service_manager, "_write_state") as write_state,
        ):
            with self.assertRaises(service_manager.ServiceError):
                service_manager.control_service("demo_local", "stop")
        write_state.assert_not_called()


if __name__ == "__main__":
    unittest.main()
