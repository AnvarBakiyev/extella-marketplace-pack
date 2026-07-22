import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from installer import plugin_lifecycle
from runtime.extella_runtime.platforms import detect_platform


class FakeAccountTransaction:
    def __init__(self):
        self.rolled_back = False

    def commit(self):
        return {"status": "installed", "steps": [{"status": "installed"}]}

    def rollback(self, *, failed_step=None):
        del failed_step
        self.rolled_back = True


class FakeAccountInstaller:
    installs = []
    instances = []

    def __init__(self, api, *, release_version, state_root, agent_id=None):
        del api, release_version, state_root
        self.agent_id = agent_id or ""
        self.transaction = FakeAccountTransaction()
        self.__class__.instances.append(self)

    def install(self, experts, *, required, smokes, kv_artifacts, agent_instructions, commit):
        del experts, kv_artifacts, agent_instructions
        self.__class__.installs.append((set(required), set(smokes), commit))
        return {"status": "prepared"}


class FakeSupervisor:
    running = set()

    def __init__(self, **_kwargs):
        pass

    def status(self, spec):
        running = spec.runtime_id in self.running
        return {
            "status": "running" if running else "stopped",
            "pid": 4242 if running else None,
            "canStop": running,
            "canStart": not running,
            "port": spec.port,
            "owner": spec.owner,
        }

    def start(self, spec, timeout=30):
        del timeout
        if not (spec.cwd / "server.py").is_file():
            raise AssertionError("service started before files were installed")
        self.running.add(spec.runtime_id)
        return self.status(spec)

    def stop(self, spec):
        self.running.discard(spec.runtime_id)
        return self.status(spec)


class UnhealthySupervisor(FakeSupervisor):
    def start(self, spec, timeout=30):
        del timeout
        return self.status(spec)


class SupportedPluginLifecycleTests(unittest.TestCase):
    def setUp(self):
        FakeAccountInstaller.installs = []
        FakeAccountInstaller.instances = []
        FakeSupervisor.running = set()
        self.mac = detect_platform(system="Darwin", architecture="arm64", release="15.5")

    def fixture(self, root: Path):
        data = root / "data"
        package = root / "package"
        source = package / "payload/marketplace/automations/ui/extella_travel_agency"
        source.mkdir(parents=True)
        (source / "server.py").write_text("print('service')\n", encoding="utf-8")
        (source / "index.html").write_text("<html>index</html>", encoding="utf-8")
        (source / "onboarding.html").write_text("<html>onboarding</html>", encoding="utf-8")
        manifests = package / "payload/marketplace/release/plugins"
        manifests.mkdir(parents=True)
        manifest = {
            "id": "extella_travel_agency",
            "name": "Travel Agency",
            "description": "Supported travel workflow",
            "version": "1.0.0",
            "classification": "supported_on_demand",
            "source": {
                "type": "bundled",
                "locator": "automations/ui/extella_travel_agency",
                "revision": "release",
            },
            "supportedPlatforms": ["macos-arm64"],
            "install": {"strategy": "on_demand"},
            "runtime": {
                "owner": "extella_travel_agency",
                "command": ["${PYTHON}", "${EXTELLA_DATA}/plugins/extella_travel_agency/server.py"],
                "port": {"preferred": 8766},
                "health": {"path": "/x/health", "timeoutSeconds": 5},
            },
            "ui": {"entrypoint": "/onboarding.html"},
            "artifacts": {"installRoot": "${EXTELLA_DATA}/plugins/extella_travel_agency"},
            "experts": {"required": ["travel_required"], "smoke": ["travel_smoke"]},
        }
        (manifests / "extella_travel_agency.json").write_text(json.dumps(manifest), encoding="utf-8")
        config = data / "wizard/app/config.json"
        config.parent.mkdir(parents=True)
        config.write_text(
            json.dumps(
                {
                    "auth_token": "token-that-is-long-enough-for-validation",
                    "agent_id": "agent_current123",
                    "api_base": "https://api.extella.ai",
                }
            ),
            encoding="utf-8",
        )
        config.chmod(0o600)
        env = {"HOME": str(root / "home"), "EXTELLA_DATA_ROOT": str(data)}
        return package, data, env

    def lifecycle_patches(self):
        return (
            patch.object(plugin_lifecycle, "verify_bundle", return_value=SimpleNamespace(release_version="test")),
            patch.object(plugin_lifecycle, "repair_interrupted_account"),
            patch.object(plugin_lifecycle, "discover_bundle_experts", return_value={}),
            patch.object(plugin_lifecycle, "AccountInstaller", FakeAccountInstaller),
            patch.object(plugin_lifecycle, "ProcessSupervisor", FakeSupervisor),
            patch.object(plugin_lifecycle, "_restrict_secret_file"),
        )

    def test_install_is_explicit_transactional_and_starts_owned_service(self):
        with tempfile.TemporaryDirectory() as directory:
            package, data, env = self.fixture(Path(directory))
            patches = self.lifecycle_patches()
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
                result = plugin_lifecycle.install_supported_plugin(
                    "extella_travel_agency",
                    package_root=package,
                    platform_info=self.mac,
                    env=env,
                    account_api=object(),
                    python_executable=Path(sys.executable),
                )
            self.assertEqual(result["status"], "installed")
            self.assertEqual(result["service"]["pid"], 4242)
            self.assertTrue((data / "plugins/extella_travel_agency/server.py").is_file())
            registry = json.loads((data / "plugins/_registry/extella_travel_agency.json").read_text())
            self.assertTrue(registry["installedByExtella"])
            self.assertEqual(registry["classification"], "supported_on_demand")
            self.assertEqual(FakeAccountInstaller.installs, [({"travel_required"}, {"travel_smoke"}, False)])

    def test_uninstall_removes_owned_files_but_preserves_user_data(self):
        with tempfile.TemporaryDirectory() as directory:
            package, data, env = self.fixture(Path(directory))
            patches = self.lifecycle_patches()
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
                plugin_lifecycle.install_supported_plugin(
                    "extella_travel_agency",
                    package_root=package,
                    platform_info=self.mac,
                    env=env,
                    account_api=object(),
                    python_executable=Path(sys.executable),
                )
                user_file = data / "plugins/extella_travel_agency/uploads/passport.png"
                user_file.parent.mkdir(parents=True)
                user_file.write_bytes(b"user-data")
                result = plugin_lifecycle.uninstall_supported_plugin(
                    "extella_travel_agency",
                    package_root=package,
                    platform_info=self.mac,
                    env=env,
                    account_api=object(),
                    python_executable=Path(sys.executable),
                )
            self.assertEqual(result["status"], "uninstalled")
            self.assertFalse((data / "plugins/extella_travel_agency/server.py").exists())
            self.assertFalse((data / "plugins/_registry/extella_travel_agency.json").exists())
            self.assertEqual(user_file.read_bytes(), b"user-data")

    def test_unknown_plugin_fails_before_any_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            package, data, env = self.fixture(Path(directory))
            with patch.object(plugin_lifecycle, "verify_bundle") as verify:
                with self.assertRaisesRegex(plugin_lifecycle.PluginLifecycleError, "allowlist"):
                    plugin_lifecycle.install_supported_plugin(
                        "unknown_plugin",
                        package_root=package,
                        platform_info=self.mac,
                        env=env,
                        account_api=object(),
                        python_executable=Path(sys.executable),
                    )
            verify.assert_not_called()
            self.assertFalse((data / "plugins/unknown_plugin").exists())

    def test_unhealthy_service_rolls_back_account_files_and_registration(self):
        with tempfile.TemporaryDirectory() as directory:
            package, data, env = self.fixture(Path(directory))
            patches = self.lifecycle_patches()
            with (
                patches[0], patches[1], patches[2], patches[3],
                patch.object(plugin_lifecycle, "ProcessSupervisor", UnhealthySupervisor),
                patches[5],
            ):
                with self.assertRaisesRegex(Exception, "plugin.service"):
                    plugin_lifecycle.install_supported_plugin(
                        "extella_travel_agency",
                        package_root=package,
                        platform_info=self.mac,
                        env=env,
                        account_api=object(),
                        python_executable=Path(sys.executable),
                    )
            self.assertTrue(FakeAccountInstaller.instances[0].transaction.rolled_back)
            self.assertFalse((data / "plugins/extella_travel_agency/server.py").exists())
            self.assertFalse((data / "plugins/_registry/extella_travel_agency.json").exists())


if __name__ == "__main__":
    unittest.main()
