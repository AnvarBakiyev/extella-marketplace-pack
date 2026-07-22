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


class RequiredBundlePayloadTests(unittest.TestCase):
    def test_installer_runtime_resolver_is_a_release_gate_requirement(self):
        self.assertIn(
            "payload/marketplace/runtime/pinokio_recipe_resolver.js",
            release_gate.REQUIRED_BUNDLE_PAYLOAD,
        )

    def test_supported_plugin_lifecycle_is_a_release_gate_requirement(self):
        self.assertIn(
            "payload/marketplace/installer/plugin_lifecycle.py",
            release_gate.REQUIRED_BUNDLE_PAYLOAD,
        )


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

    def test_legacy_global_agent_scope_is_rejected(self):
        plugin = valid_plugin()
        plugin["source"]["revision"] = "agent_extella_alibaba_default"
        issues = release_gate.validate_plugin(self.write(plugin))
        self.assertIn("security.static_agent_scope", {issue.code for issue in issues})


class ToolbarSourceGateTests(unittest.TestCase):
    def _fixture(self, root: Path, *, canonical: bytes, distributed: bytes):
        marketplace = root / "marketplace"
        toolbar = root / "toolbar"
        (marketplace / "toolbar").mkdir(parents=True)
        (marketplace / "toolbar/toolbar.js").write_bytes(distributed)
        (toolbar / "toolbar/build").mkdir(parents=True)
        (toolbar / "toolbar/build/toolbar.js").write_bytes(canonical)
        (toolbar / "scripts").mkdir()
        for name in (
            "check-reproducible-build.js",
            "check-account-scope.js",
            "check-runtime-portability.js",
            "check-catalog-contract.js",
            "check-managed-runtime-lifecycle.js",
        ):
            (toolbar / f"scripts/{name}").write_text("// fixture")
        release = {
            "sourceRepositories": [{"id": "toolbar", "revision": "1" * 40}]
        }
        return marketplace, toolbar, release

    def _run(self, marketplace, toolbar, release):
        completed = [
            *(subprocess.CompletedProcess([], 0, "passed", "") for _ in range(5)),
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

    def test_managed_runtime_contract_failure_fails_candidate_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            marketplace, toolbar, release = self._fixture(
                Path(directory), canonical=b"same", distributed=b"same"
            )
            completed = [
                *(subprocess.CompletedProcess([], 0, "passed", "") for _ in range(4)),
                subprocess.CompletedProcess([], 1, "", "managed lifecycle failed"),
            ]
            with patch.object(release_gate.subprocess, "run", side_effect=completed):
                issues = release_gate.validate_toolbar_source(marketplace, toolbar, release)
        self.assertIn("toolbar.managed_runtime", {issue.code for issue in issues})


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


class ShippedExpertPortabilityTests(unittest.TestCase):
    def fixture(self):
        directory = tempfile.TemporaryDirectory()
        root = Path(directory.name) / "marketplace"
        wizard = Path(directory.name) / "wizard"
        for path in (root / "experts", root / "platform_experts", root / "automations/experts", wizard / "experts"):
            path.mkdir(parents=True)
        return directory, root, wizard

    def test_platform_native_bridge_passes(self):
        directory, root, wizard = self.fixture()
        try:
            (root / "experts/example.py").write_text(
                "def example():\n    from extella_expert_bridge import locations\n    return locations()['apps_root']\n",
                encoding="utf-8",
            )
            self.assertEqual([], release_gate.validate_shipped_expert_portability(root, wizard))
        finally:
            directory.cleanup()

    def test_legacy_path_and_unowned_shell_are_rejected(self):
        directory, root, wizard = self.fixture()
        try:
            (root / "experts/example.py").write_text(
                "def example():\n"
                "    import os, subprocess\n"
                "    return subprocess.run('x', shell=True, cwd=os.path.expanduser('~/extella-apps'))\n",
                encoding="utf-8",
            )
            issues = release_gate.validate_shipped_expert_portability(root, wizard)
        finally:
            directory.cleanup()
        codes = {issue.code for issue in issues}
        self.assertIn("portability.legacy_home_path", codes)
        self.assertIn("runtime.unowned_shell", codes)


class ShippedRuntimeSecurityTests(unittest.TestCase):
    def fixture(self):
        directory = tempfile.TemporaryDirectory()
        root = Path(directory.name) / "marketplace"
        wizard = Path(directory.name) / "wizard"
        (root / "automations/ui/example").mkdir(parents=True)
        (root / "toolbar").mkdir(parents=True)
        (wizard / "ui").mkdir(parents=True)
        return directory, root, wizard

    def test_safety_prompt_text_is_not_mistaken_for_executable_shell(self):
        directory, root, wizard = self.fixture()
        try:
            (wizard / "ui/prompt.py").write_text(
                "RULE = 'Never use shell=True or ssl.CERT_NONE'\n",
                encoding="utf-8",
            )
            self.assertEqual([], release_gate.validate_shipped_runtime_security(root, wizard))
        finally:
            directory.cleanup()

    def test_actual_unverified_tls_shell_and_static_agent_are_rejected(self):
        directory, root, wizard = self.fixture()
        try:
            (root / "automations/ui/example/server.py").write_text(
                "import ssl, subprocess\n"
                "CTX = ssl.create_default_context()\n"
                "CTX.check_hostname = False\n"
                "CTX.verify_mode = ssl.CERT_NONE\n"
                "subprocess.run(['tool'], shell=True)\n",
                encoding="utf-8",
            )
            (root / "toolbar/toolbar.js").write_text(
                "const agent = 'agent_extella_default';\n",
                encoding="utf-8",
            )
            issues = release_gate.validate_shipped_runtime_security(root, wizard)
        finally:
            directory.cleanup()
        codes = {issue.code for issue in issues}
        self.assertIn("security.tls_verification_disabled", codes)
        self.assertIn("runtime.unowned_shell", codes)
        self.assertIn("security.static_agent_scope", codes)


class CatalogPolicyTests(unittest.TestCase):
    def fixture(self):
        directory = tempfile.TemporaryDirectory()
        root = Path(directory.name) / "marketplace"
        wizard = Path(directory.name) / "wizard"
        (root / "release").mkdir(parents=True)
        (root / "experts").mkdir()
        (wizard / "experts").mkdir(parents=True)
        (root / "experts/example.py").write_text("def example():\n    return {}\n", encoding="utf-8")
        (root / "release/catalog-policy.json").write_text(
            json.dumps({
                "schemaVersion": 1,
                "defaultClassification": "third_party_unverified",
                "supportedOnDemand": [],
                "sources": {
                    key: {"classification": "third_party_unverified", "advertisedAsGuaranteed": False}
                    for key in ("_mkt_apps", "_mkt_loc", "_mkt_mcp", "_mkt_models", "_mkt_programs")
                },
                "visibility": {"hideField": "hidden", "hideWhenTrue": True},
            }),
            encoding="utf-8",
        )
        for filename in ("models_catalog.json", "apps_catalog.json", "mcp_catalog.json"):
            (root / filename).write_text(
                json.dumps({"catalog": {"shelf": [{
                    "id": "example/source",
                    "classification": "third_party_unverified",
                    "hidden": False,
                    "label": "Third-party · unverified",
                }]}}),
                encoding="utf-8",
            )
        (root / "composer_catalog.json").write_text(
            json.dumps({"blocks": [{"id": "example", "params": {}}]}), encoding="utf-8"
        )
        return directory, root, wizard

    def test_explicit_unverified_catalogs_and_real_composer_expert_pass(self):
        directory, root, wizard = self.fixture()
        try:
            self.assertEqual([], release_gate.validate_catalog_policy(root, wizard))
        finally:
            directory.cleanup()

    def test_guaranteed_label_and_missing_composer_expert_fail(self):
        directory, root, wizard = self.fixture()
        try:
            models = root / "models_catalog.json"
            models.write_text(json.dumps({"catalog": {"shelf": [{
                "id": "example/source", "label": "Работает", "hidden": False,
            }]}}), encoding="utf-8")
            (root / "composer_catalog.json").write_text(
                json.dumps({"blocks": [{"id": "missing", "defaults": {"folder": "~/private"}}]}),
                encoding="utf-8",
            )
            issues = release_gate.validate_catalog_policy(root, wizard)
        finally:
            directory.cleanup()
        codes = {issue.code for issue in issues}
        self.assertIn("catalog.item_classification", codes)
        self.assertIn("catalog.item_advertisement", codes)
        self.assertIn("catalog.composer_expert", codes)
        self.assertIn("catalog.composer_path", codes)


class LifecycleEntrypointTests(unittest.TestCase):
    def test_stale_component_installer_and_raw_branch_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            required = {
                "install.py": "legacy_installer_retired",
                "install_toolbar.sh": "toolbar/install-all.sh",
                "toolbar/install.sh": "install-all.sh",
                "toolbar/install.ps1": "install-all.ps1",
                "toolbar/Install-Extella.command": "install-all.sh",
                "toolbar/Install-Extella.bat": "install-all.ps1",
                "toolbar/fix-certs.sh": "legacy_certificate_repair_retired",
                "device/activity-center/install.py": "standalone_component_installer_retired",
                "device/activity-center/uninstall.py": "standalone_component_uninstaller_retired",
            }
            for relative, marker in required.items():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(marker, encoding="utf-8")
            (root / "toolbar/install.sh").write_text(
                "install-all.sh raw.githubusercontent.com/example/project/main/file", encoding="utf-8"
            )
            (root / "device/boot").mkdir(parents=True)
            (root / "device/boot/restart_local_servers.py").write_text("legacy", encoding="utf-8")
            (root / "toolbar/version.json").write_text(
                json.dumps({"updatesEnabled": True}), encoding="utf-8"
            )
            issues = release_gate.validate_lifecycle_entrypoints(root)
        codes = {issue.code for issue in issues}
        self.assertIn("security.mutable_source", codes)
        self.assertIn("lifecycle.stale_copy", codes)
        self.assertIn("lifecycle.update_policy", codes)

    def test_wizard_standalone_lifecycle_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            wizard = Path(directory)
            (wizard / "docs").mkdir()
            (wizard / "scripts").mkdir()
            (wizard / "install.py").write_text("print('legacy')", encoding="utf-8")
            (wizard / "extella-update.sh").write_text(
                "curl https://raw.githubusercontent.com/example/wizard/main/install.py | python3",
                encoding="utf-8",
            )
            (wizard / "extella-plugin.json").write_text("{}", encoding="utf-8")
            retired_scripts = {
                "release.sh": "legacy_wizard_release_script_retired",
                "deploy.sh": "legacy_wizard_live_deploy_retired",
                "qa_delta_update.sh": "legacy_wizard_delta_updater_retired",
                "publish_release.py": "legacy_wizard_kv_publisher_retired",
                "register_app_cards.py": "legacy_wizard_registry_writer_retired",
            }
            for name, marker in retired_scripts.items():
                (wizard / "scripts" / name).write_text(marker, encoding="utf-8")
            for relative in ("README.md", "INSTALL.md", "UPDATE_FOR_COLLEAGUES.md", "docs/RELEASE_AND_MERGE.md"):
                (wizard / relative).write_text("verified release", encoding="utf-8")
            issues = release_gate.validate_wizard_lifecycle(wizard)
        codes = {issue.code for issue in issues}
        self.assertIn("lifecycle.wizard_stale_entrypoint", codes)
        self.assertIn("lifecycle.wizard_stale_manifest", codes)
        self.assertIn("security.mutable_source", codes)

    def test_retired_wizard_lifecycle_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            wizard = Path(directory)
            (wizard / "docs").mkdir()
            (wizard / "scripts").mkdir()
            (wizard / "install.py").write_text("legacy_wizard_installer_retired", encoding="utf-8")
            (wizard / "extella-update.sh").write_text("legacy_wizard_updater_retired", encoding="utf-8")
            retired_scripts = {
                "release.sh": "legacy_wizard_release_script_retired",
                "deploy.sh": "legacy_wizard_live_deploy_retired",
                "qa_delta_update.sh": "legacy_wizard_delta_updater_retired",
                "publish_release.py": "legacy_wizard_kv_publisher_retired",
                "register_app_cards.py": "legacy_wizard_registry_writer_retired",
            }
            for name, marker in retired_scripts.items():
                (wizard / "scripts" / name).write_text(marker, encoding="utf-8")
            for relative in ("README.md", "INSTALL.md", "UPDATE_FOR_COLLEAGUES.md", "docs/RELEASE_AND_MERGE.md"):
                (wizard / relative).write_text("verified immutable release", encoding="utf-8")
            self.assertEqual([], release_gate.validate_wizard_lifecycle(wizard))


if __name__ == "__main__":
    unittest.main()
