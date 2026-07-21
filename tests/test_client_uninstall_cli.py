import io
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from installer import client_uninstall
from runtime.extella_runtime.platforms import detect_platform


class ClientUninstallCliTests(unittest.TestCase):
    def test_windows_self_hosted_uninstall_stops_before_mutation(self):
        windows = detect_platform(
            system="Windows", architecture="AMD64", release="11", version="10.0.26100"
        )
        output = io.StringIO()
        with (
            patch.object(sys, "argv", ["client_uninstall.py"]),
            patch.object(client_uninstall, "detect_platform", return_value=windows),
            patch.object(
                client_uninstall,
                "client_paths",
                return_value=SimpleNamespace(runtime_root=Path("C:/Extella/runtime")),
            ),
            patch.object(client_uninstall.sys, "executable", "C:/Extella/runtime/python/python.exe"),
            patch("sys.stdout", output),
            patch.object(client_uninstall, "uninstall_client") as uninstall,
        ):
            code = client_uninstall.main()
        self.assertEqual(code, 4)
        self.assertIn("self_hosted_uninstall", output.getvalue())
        uninstall.assert_not_called()


if __name__ == "__main__":
    unittest.main()
