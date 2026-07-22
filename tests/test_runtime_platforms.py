import unittest

from runtime.extella_runtime.platforms import detect_platform


class PlatformDetectionTests(unittest.TestCase):
    def test_supported_matrix(self):
        cases = (
            ({"system": "Darwin", "architecture": "x86_64", "release": "15.5"}, "macos-x86_64"),
            ({"system": "Darwin", "architecture": "arm64", "release": "15.5"}, "macos-arm64"),
            (
                {
                    "system": "Windows",
                    "architecture": "AMD64",
                    "release": "10",
                    "version": "10.0.26100",
                },
                "windows11-x86_64",
            ),
        )
        for inputs, expected in cases:
            with self.subTest(expected=expected):
                result = detect_platform(**inputs)
                self.assertTrue(result.supported)
                self.assertEqual(result.key, expected)

    def test_unsupported_platforms_fail_closed(self):
        cases = (
            {"system": "Linux", "architecture": "x86_64", "release": "6.8"},
            {
                "system": "Windows",
                "architecture": "AMD64",
                "release": "10",
                "version": "10.0.19045",
            },
            {
                "system": "Windows",
                "architecture": "ARM64",
                "release": "11",
                "version": "10.0.26100",
            },
        )
        for inputs in cases:
            with self.subTest(inputs=inputs):
                result = detect_platform(**inputs)
                self.assertFalse(result.supported)
                self.assertIsNone(result.key)

    def test_rosetta_report_is_bound_to_physical_apple_silicon(self):
        result = detect_platform(
            system="Darwin",
            architecture="x86_64",
            physical_architecture="arm64",
            release="25.5",
        )
        self.assertTrue(result.supported)
        self.assertEqual(result.key, "macos-arm64")
        self.assertEqual(result.architecture, "arm64")


if __name__ == "__main__":
    unittest.main()
