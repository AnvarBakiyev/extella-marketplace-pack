import plistlib
import subprocess
import tempfile
import unittest
from pathlib import Path

from runtime.extella_runtime.autostart import (
    AutostartSpec,
    install_autostart,
    render_launch_agent,
    render_windows_launcher,
)
from runtime.extella_runtime.paths import client_paths
from runtime.extella_runtime.platforms import detect_platform
from runtime.extella_runtime.transaction import InstallTransaction


class FakeRunner:
    def __init__(self):
        self.calls = []

    def __call__(self, argv):
        self.calls.append(tuple(argv))
        loaded = "print" in argv or "/Query" in argv
        return subprocess.CompletedProcess(argv, 1 if loaded else 0, "", "")


class AutostartTests(unittest.TestCase):
    def _spec(self, root):
        return AutostartSpec(
            service_id="activity-center",
            argv=(str(root / "python"), str(root / "server.py")),
            cwd=root,
            environment={"EXTELLA_DATA_ROOT": str(root / "data")},
        )

    def test_macos_definition_uses_absolute_argv_and_no_shell(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = plistlib.loads(render_launch_agent(self._spec(root), log_path=root / "service.log"))
            self.assertEqual(payload["ProgramArguments"][0], str(root / "python"))
            self.assertEqual(payload["WorkingDirectory"], str(root))
            self.assertNotIn("Program", payload)

    def test_windows_launcher_quotes_paths_as_literals(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "space's dir"
            payload = render_windows_launcher(self._spec(root), log_path=root / "service.log").decode()
            self.assertIn("Set-Location -LiteralPath", payload)
            self.assertIn("space''s dir", payload)
            self.assertNotIn("cmd.exe", payload)

    def test_registration_is_journalled_on_both_platforms(self):
        cases = (
            (detect_platform(system="Darwin", architecture="arm64", release="15"), {}),
            (
                detect_platform(system="Windows", architecture="AMD64", release="11", version="10.0.22631"),
                {"USERPROFILE": "C:/Users/Test", "APPDATA": "C:/Users/Test/AppData/Roaming", "LOCALAPPDATA": "C:/Users/Test/AppData/Local"},
            ),
        )
        for platform_info, base_env in cases:
            with self.subTest(platform=platform_info.key), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                env = {
                    **base_env,
                    "HOME": str(root / "home"),
                    "EXTELLA_DATA_ROOT": str(root / "data"),
                }
                paths = client_paths(platform_info=platform_info, env=env)
                runner = FakeRunner()
                transaction = InstallTransaction(release_version="2.0.0", state_root=root / "state")
                transaction.run(
                    "autostart",
                    lambda: install_autostart(
                        transaction,
                        self._spec(root),
                        platform_info=platform_info,
                        paths=paths,
                        runner=runner,
                    ),
                )
                report = transaction.commit()
                self.assertEqual(report["steps"][0]["status"], "installed")
                self.assertTrue(report["files"])
                self.assertTrue(any("bootstrap" in call or "/Create" in call for call in runner.calls))


if __name__ == "__main__":
    unittest.main()
