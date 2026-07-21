import json
import tempfile
import unittest
from pathlib import Path

from runtime.install_runtime import install
from runtime.extella_runtime.platforms import detect_platform


class RuntimeInstallTests(unittest.TestCase):
    def test_runtime_install_is_idempotent_and_journalled(self):
        mac = detect_platform(system="Darwin", architecture="arm64", release="15")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            environment = {
                "HOME": str(root / "home"),
                "EXTELLA_DATA_ROOT": str(root / "data"),
            }
            import_root = root / "listener-site"
            first = install(
                release_version="2.0.0",
                env=environment,
                platform_info=mac,
                import_roots=[import_root],
            )
            second = install(
                release_version="2.0.0",
                env=environment,
                platform_info=mac,
                import_roots=[import_root],
            )
            self.assertEqual(first["status"], "installed")
            self.assertEqual(second["status"], "installed")
            self.assertTrue((root / "data" / "runtime" / "extella_runtime" / "ensure_tool.py").is_file())
            self.assertEqual(
                (import_root / "extella_client_runtime.pth").read_text(encoding="utf-8"),
                str(root / "data" / "runtime")
                + "\nimport extella_runtime.bootstrap; extella_runtime.bootstrap.activate()\n",
            )
            state = json.loads(
                (root / "data" / "state" / "runtime" / "install-state.json").read_text()
            )
            self.assertEqual(state["releaseVersion"], "2.0.0")


if __name__ == "__main__":
    unittest.main()
