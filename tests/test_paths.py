import unittest

from runtime.extella_runtime.paths import client_paths
from runtime.extella_runtime.platforms import detect_platform


class ClientPathTests(unittest.TestCase):
    def test_macos_paths_use_application_support(self):
        mac = detect_platform(system="Darwin", architecture="x86_64", release="15")
        paths = client_paths(platform_info=mac, env={"HOME": "/Users/new-user"})
        self.assertEqual(
            str(paths.data_root), "/Users/new-user/Library/Application Support/Extella"
        )
        self.assertEqual(
            str(paths.autostart_root), "/Users/new-user/Library/LaunchAgents"
        )

    def test_windows_paths_use_appdata(self):
        windows = detect_platform(
            system="Windows", architecture="AMD64", release="11", version="10.0.26100"
        )
        paths = client_paths(
            platform_info=windows,
            env={
                "USERPROFILE": "C:/Users/new-user",
                "LOCALAPPDATA": "C:/Users/new-user/AppData/Local",
                "APPDATA": "C:/Users/new-user/AppData/Roaming",
            },
        )
        self.assertEqual(str(paths.data_root), "C:/Users/new-user/AppData/Local/Extella")
        self.assertEqual(
            str(paths.toolbar_root), "C:/Users/new-user/AppData/Roaming/extella-desktop"
        )


if __name__ == "__main__":
    unittest.main()
