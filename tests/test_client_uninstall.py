import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from installer.client import _uninstall_supported_plugins, uninstall_client
from runtime.extella_runtime.transaction import InstallationError
from runtime.extella_runtime.platforms import detect_platform


class ClientUninstallTests(unittest.TestCase):
    def setUp(self):
        self.mac = detect_platform(system="Darwin", architecture="arm64", release="15.5")

    def paths(self, root: Path):
        return SimpleNamespace(
            data_root=root / "data",
            state_root=root / "data/state",
            plugins_root=root / "data/plugins",
            runtime_root=root / "data/runtime",
        )

    def test_supported_plugins_are_removed_before_base_client(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.paths(root)
            marker = paths.state_root / "plugins/extella_travel_agency/install-state.json"
            marker.parent.mkdir(parents=True)
            marker.write_text("{}", encoding="utf-8")
            result = {
                "status": "uninstalled",
                "account": {"status": "uninstalled"},
                "local": {"status": "uninstalled"},
                "service": {"status": "stopped"},
            }
            with patch(
                "installer.plugin_lifecycle.uninstall_supported_plugin",
                return_value=result,
            ) as uninstall:
                reports = _uninstall_supported_plugins(
                    paths=paths,
                    platform_info=self.mac,
                    environment={"HOME": str(root / "home")},
                    account_api=object(),
                )
            self.assertEqual(set(reports), {"extella_travel_agency"})
            self.assertEqual(reports["extella_travel_agency"]["service"], "stopped")
            self.assertEqual(
                uninstall.call_args.kwargs["package_root"],
                paths.data_root / "packages/current",
            )

    def test_plugin_only_install_is_not_reported_as_absent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.paths(root)
            with (
                patch("installer.client.client_paths", return_value=paths),
                patch(
                    "installer.client._uninstall_supported_plugins",
                    return_value={"extella_travel_agency": {"status": "uninstalled"}},
                ),
            ):
                report = uninstall_client(
                    platform_info=self.mac,
                    env={"HOME": str(root / "home")},
                )
            self.assertEqual(report["status"], "uninstalled")
            self.assertIn("extella_travel_agency", report["plugins"])

    def test_invalid_base_account_token_fails_before_plugin_removal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.paths(root)
            account_state = paths.state_root / "account/account-state.json"
            account_state.parent.mkdir(parents=True)
            account_state.write_text('{"status":"installed"}', encoding="utf-8")
            api = SimpleNamespace(post=lambda *_args, **_kwargs: {"status": "error"})
            with (
                patch("installer.client.client_paths", return_value=paths),
                patch("installer.client._uninstall_supported_plugins") as plugins,
            ):
                with self.assertRaisesRegex(InstallationError, "validation failed"):
                    uninstall_client(
                        token="invalid-but-present-token",
                        platform_info=self.mac,
                        env={"HOME": str(root / "home")},
                        account_api=api,
                    )
            plugins.assert_not_called()


if __name__ == "__main__":
    unittest.main()
