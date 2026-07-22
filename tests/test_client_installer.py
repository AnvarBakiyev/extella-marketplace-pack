import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from installer.client import _restrict_secret_file, prepare_local_client
from runtime.extella_runtime.platforms import detect_platform


ROOT = Path(__file__).resolve().parents[1]


class ClientInstallerTests(unittest.TestCase):
    def test_secret_file_permissions_are_restricted_on_macos(self):
        mac = detect_platform(system="Darwin", architecture="arm64", release="15.5")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text("secret")
            path.chmod(0o644)
            _restrict_secret_file(path, platform_info=mac)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_windows_secret_acl_uses_current_sid_without_secret_arguments(self):
        windows = detect_platform(
            system="Windows", architecture="AMD64", release="11", version="10.0.22631"
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text("TOP_SECRET")
            with (
                patch("installer.client.shutil.which", return_value="C:/PowerShell/pwsh.exe"),
                patch(
                    "installer.client._run",
                    return_value=SimpleNamespace(returncode=0, stdout="", stderr=""),
                ) as run,
            ):
                _restrict_secret_file(path, platform_info=windows)
            argv = run.call_args.args[0]
            self.assertNotIn("TOP_SECRET", " ".join(argv))
            self.assertIn("WindowsIdentity", " ".join(argv))

    def _bundle(self, bundle: Path):
        files = []

        def copy(source: Path, relative: str):
            target = bundle / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            files.append(
                {
                    "path": relative,
                    "bytes": target.stat().st_size,
                    "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                }
            )

        for source in sorted((ROOT / "runtime/extella_runtime").glob("*.py")):
            copy(source, "payload/marketplace/runtime/extella_runtime/" + source.name)
        copy(ROOT / "runtime/extella_expert_bridge.py", "payload/marketplace/runtime/extella_expert_bridge.py")
        copy(ROOT / "runtime/pinokio_recipe_resolver.js", "payload/marketplace/runtime/pinokio_recipe_resolver.js")
        for source in sorted((ROOT / "installer").glob("*.py")):
            copy(source, "payload/marketplace/installer/" + source.name)
        copy(ROOT / "tools/external_matrix.py", "payload/marketplace/tools/external_matrix.py")
        copy(ROOT / "toolbar/toolbar.js", "payload/marketplace/toolbar/toolbar.js")
        for directory in ("bridge", "instrumentation"):
            for source in sorted((ROOT / "device/activity-center" / directory).glob("*.py")):
                copy(source, f"payload/marketplace/device/activity-center/{directory}/{source.name}")
        for plugin_id in ("extella_adoption_wizard", "extella_travel_agency", "extella_contract_agent"):
            copy(
                ROOT / "release/plugins" / f"{plugin_id}.json",
                f"payload/marketplace/release/plugins/{plugin_id}.json",
            )
        for plugin_id in ("extella_travel_agency", "extella_contract_agent"):
            for name, content in (
                ("server.py", "print('server')\n"),
                ("index.html", "<html>index</html>"),
                ("onboarding.html", "<html>onboarding</html>"),
            ):
                target = bundle / f"payload/marketplace/automations/ui/{plugin_id}/{name}"
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
                files.append(
                    {
                        "path": target.relative_to(bundle).as_posix(),
                        "bytes": target.stat().st_size,
                        "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                    }
                )
        for name, content in (
            ("server.py", "print('wizard')\n"),
            ("wizard.html", "<html>wizard</html>"),
        ):
            target = bundle / f"payload/wizard/ui/{name}"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            files.append(
                {
                    "path": target.relative_to(bundle).as_posix(),
                    "bytes": target.stat().st_size,
                    "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                }
            )
        workspace = bundle / "payload/wizard/dist/workspace/workspace_autopilot.py"
        workspace.parent.mkdir(parents=True, exist_ok=True)
        workspace.write_text("print('workspace')\n", encoding="utf-8")
        files.append(
            {
                "path": workspace.relative_to(bundle).as_posix(),
                "bytes": workspace.stat().st_size,
                "sha256": hashlib.sha256(workspace.read_bytes()).hexdigest(),
            }
        )
        catalog = bundle / "payload/wizard/catalog/catalog.json"
        catalog.parent.mkdir(parents=True, exist_ok=True)
        catalog.write_text('{"capabilities":[],"process_archetypes":[]}', encoding="utf-8")
        files.append(
            {
                "path": catalog.relative_to(bundle).as_posix(),
                "bytes": catalog.stat().st_size,
                "sha256": hashlib.sha256(catalog.read_bytes()).hexdigest(),
            }
        )
        manifest = {
            "schemaVersion": 1,
            "releaseVersion": "2.0.0-rc.1",
            "supportedPlatforms": ["macos-x86_64", "macos-arm64", "windows11-x86_64"],
            "sourceRepositories": [
                {"id": "marketplace", "revision": "1" * 40},
                {"id": "toolbar", "revision": "2" * 40},
                {"id": "wizard", "revision": "3" * 40},
            ],
            "packagingRepositoryRevision": "4" * 40,
            "files": sorted(files, key=lambda item: item["path"]),
        }
        (bundle / "bundle-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    def test_prepares_standard_paths_and_safe_service_registries(self):
        mac = detect_platform(system="Darwin", architecture="arm64", release="15")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = root / "bundle"
            bundle.mkdir()
            self._bundle(bundle)
            prepared, verified = prepare_local_client(
                bundle,
                platform_info=mac,
                env={"HOME": str(root / "home"), "EXTELLA_DATA_ROOT": str(root / "data")},
                python_executable=Path(sys.executable),
                network_urls=(),
            )
            report = prepared.transaction.commit()
            self.assertEqual(verified.release_version, "2.0.0-rc.1")
            self.assertEqual(report["status"], "installed")
            self.assertTrue((root / "data/wizard/app/wizard.html").is_file())
            self.assertTrue((root / "data/wizard/app/workspace/workspace_autopilot.py").is_file())
            self.assertTrue((root / "data/runtime/pinokio_recipe_resolver.js").is_file())
            self.assertTrue((root / "data/installer/client_uninstall.py").is_file())
            self.assertTrue((root / "data/installer/external_matrix.py").is_file())
            registry = json.loads(
                (root / "data/plugins/_registry/extella_adoption_wizard.json").read_text()
            )
            self.assertNotIn("launchCmd", registry["service"])
            self.assertNotIn("ready", registry["service"])
            self.assertEqual(registry["service"]["argv"][0], str(Path(sys.executable).resolve()))
            self.assertEqual(registry["service"]["autostart"], "activity_center")


if __name__ == "__main__":
    unittest.main()
