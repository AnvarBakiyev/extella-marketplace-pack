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


class FakeSupervisor:
    def __init__(self, status):
        self.value = status

    def status(self, spec):
        del spec
        return dict(self.value)

    def start(self, spec):
        self.value.setdefault("started", []).append(spec.runtime_id)
        return {"status": "running"}


class ServiceManagerTests(unittest.TestCase):
    def test_boot_starts_enabled_services_and_preserves_disabled_choice(self) -> None:
        enabled = service_manager.RuntimeSpec(
            runtime_id="enabled",
            name="Enabled",
            argv=(sys.executable, "server.py"),
            cwd=Path("/expected"),
            port=9123,
            health_url="http://127.0.0.1:9123/",
            log_path=Path("/tmp/enabled.log"),
            owner="enabled",
            autostart="activity_center",
        )
        disabled = service_manager.RuntimeSpec(
            runtime_id="disabled",
            name="Disabled",
            argv=(sys.executable, "server.py"),
            cwd=Path("/expected"),
            port=9124,
            health_url="http://127.0.0.1:9124/",
            log_path=Path("/tmp/disabled.log"),
            owner="disabled",
            autostart="activity_center",
        )
        supervisor = FakeSupervisor({"started": []})
        state = {"disabled": ["disabled"], "lastErrors": {}}
        with (
            patch.object(
                service_manager,
                "registry_services",
                return_value=[
                    {"id": "enabled", "runtimeSpec": enabled},
                    {"id": "disabled", "runtimeSpec": disabled},
                ],
            ),
            patch.object(service_manager, "_read_state", return_value=state),
            patch.object(service_manager, "_SUPERVISOR", supervisor),
            patch.object(service_manager, "_write_state") as write_state,
        ):
            result = service_manager.start_desired_services()
        self.assertEqual(result["started"], ["enabled"])
        self.assertEqual(supervisor.value["started"], ["enabled"])
        write_state.assert_called_once()

    def test_discovers_safe_argv_contract_and_rejects_legacy_shell_control(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            registry = Path(tmp)
            project = registry / "demo"
            project.mkdir()
            (registry / "safe.json").write_text(
                json.dumps(
                    {
                        "id": "demo_safe",
                        "name": "Demo",
                        "ui": {
                            "type": "local_server",
                            "port": 9123,
                            "rootPath": str(project),
                        },
                        "service": {
                            "argv": [sys.executable, "-m", "http.server", "9123"],
                            "healthPath": "/",
                            "owner": "demo_safe",
                        },
                    }
                ),
                encoding="utf-8",
            )
            (registry / "legacy.json").write_text(
                json.dumps(
                    {
                        "id": "demo_legacy",
                        "ui": {
                            "type": "local_server",
                            "port": 9124,
                            "rootPath": str(project),
                        },
                        "service": {"launchCmd": "TOKEN=secret python server.py"},
                    }
                ),
                encoding="utf-8",
            )
            services = service_manager.registry_services(registry)
            self.assertEqual(
                [service["id"] for service in services], ["demo_legacy", "demo_safe"]
            )
            self.assertIsNone(services[0]["runtimeSpec"])
            self.assertIsInstance(services[1]["runtimeSpec"], service_manager.RuntimeSpec)

    def test_public_payload_never_exposes_argv_or_full_root(self) -> None:
        spec = service_manager.RuntimeSpec(
            runtime_id="demo_local",
            name="Demo",
            argv=(sys.executable, "server.py", "--secret", "hidden"),
            cwd=Path("/Users/example/private/project"),
            port=9123,
            health_url="http://127.0.0.1:9123/",
            log_path=Path("/tmp/service.log"),
            owner="demo",
            autostart="controller",
        )
        service = {
            "id": "demo_local",
            "name": "Demo",
            "description": "Local demo",
            "port": 9123,
            "mainFile": "index.html",
            "root": spec.cwd,
            "registryFile": "demo_local.json",
            "runtimeSpec": spec,
            "blockedReason": "",
        }
        supervisor = FakeSupervisor(
            {
                "status": "running",
                "pid": 321,
                "ppid": 1,
                "process": "Python",
                "owner": "demo",
                "startedAt": "today",
                "autostart": "controller",
                "errorClass": None,
                "canStart": False,
                "canStop": True,
                "healthy": True,
            }
        )
        public = service_manager._public_service(
            service, {"disabled": [], "lastErrors": {}}, supervisor=supervisor
        )
        serialized = json.dumps(public)
        self.assertNotIn("hidden", serialized)
        self.assertNotIn("/Users/example/private", serialized)
        self.assertEqual(public["pid"], 321)
        self.assertTrue(public["canStop"])

    def test_unknown_port_owner_cannot_be_stopped(self) -> None:
        spec = service_manager.RuntimeSpec(
            runtime_id="demo_local",
            name="Demo",
            argv=(sys.executable, "server.py"),
            cwd=Path("/expected"),
            port=9123,
            health_url="http://127.0.0.1:9123/",
            log_path=Path("/tmp/service.log"),
            owner="demo",
            autostart="controller",
        )
        service = {
            "id": "demo_local",
            "name": "Demo",
            "description": "",
            "port": 9123,
            "mainFile": "",
            "root": spec.cwd,
            "registryFile": "demo_local.json",
            "runtimeSpec": spec,
            "blockedReason": "",
        }
        supervisor = FakeSupervisor(
            {
                "status": "degraded",
                "pid": None,
                "ppid": None,
                "process": None,
                "owner": "demo",
                "startedAt": None,
                "autostart": "controller",
                "errorClass": "port_occupied_by_unowned_process",
                "canStart": False,
                "canStop": False,
                "healthy": True,
            }
        )
        public = service_manager._public_service(
            service, {"disabled": [], "lastErrors": {}}, supervisor=supervisor
        )
        self.assertFalse(public["canStop"])
        self.assertIn("not confirmed", public["controlBlockedReason"])

    def test_rejected_stop_does_not_persist_disabled_state(self) -> None:
        spec = service_manager.RuntimeSpec(
            runtime_id="demo_local",
            name="Demo",
            argv=(sys.executable, "server.py"),
            cwd=Path("/expected"),
            port=9123,
            health_url="http://127.0.0.1:9123/",
            log_path=Path("/tmp/service.log"),
            owner="demo",
            autostart="controller",
        )
        service = {"id": "demo_local", "port": 9123, "runtimeSpec": spec}
        with (
            patch.object(service_manager, "_service_by_id", return_value=service),
            patch.object(
                service_manager,
                "_read_state",
                return_value={"disabled": [], "lastErrors": {}},
            ),
            patch.object(
                service_manager,
                "_public_service",
                return_value={
                    "status": "degraded",
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
