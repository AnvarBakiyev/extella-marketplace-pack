import unittest

from runtime.extella_runtime.ensure_tool import (
    CommandOutcome,
    TOOL_SPECS,
    ensure_tool,
    resolve_tool,
)
from runtime.extella_runtime.platforms import detect_platform


MAC = detect_platform(system="Darwin", architecture="arm64", release="15.5")


class EnsureToolTests(unittest.TestCase):
    def test_resolves_and_verifies_candidate(self):
        def which(executable, search_path):
            del search_path
            return "/opt/homebrew/bin/node" if executable == "node" else None

        def executor(argv, timeout):
            del timeout
            self.assertEqual(argv[0], "/opt/homebrew/bin/node")
            return CommandOutcome(0, "v22.17.0\n", "")

        result = resolve_tool("node", platform_info=MAC, env={"PATH": ""}, which=which, executor=executor)
        self.assertTrue(result.ready)
        self.assertEqual(result.version, "v22.17.0")

    def test_missing_tool_is_action_required_without_mutation(self):
        result = ensure_tool(
            "ffmpeg",
            platform_info=MAC,
            env={"PATH": ""},
            which=lambda executable, search_path: None,
            executor=lambda argv, timeout: self.fail("executor should not run"),
        )
        self.assertEqual(result.status, "action_required")
        self.assertEqual(result.error_class, "tool_missing")

    def test_old_runtime_is_rejected(self):
        result = resolve_tool(
            "python",
            platform_info=MAC,
            env={"PATH": ""},
            which=lambda executable, search_path: "/usr/bin/python3" if executable == "python3" else None,
            executor=lambda argv, timeout: CommandOutcome(0, "Python 3.9.6", ""),
        )
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error_class, "incompatible_version")

    def test_repair_uses_package_manager_and_reverifies(self):
        installed = {"value": False}

        def which(executable, search_path):
            del search_path
            if executable == "brew":
                return "/opt/homebrew/bin/brew"
            if executable == "ffmpeg" and installed["value"]:
                return "/opt/homebrew/bin/ffmpeg"
            return None

        def executor(argv, timeout):
            del timeout
            if argv[0].endswith("brew") and len(argv) == 2:
                return CommandOutcome(0, "Homebrew 4.6.0", "")
            if argv[:3] == ("/opt/homebrew/bin/brew", "install", "ffmpeg"):
                installed["value"] = True
                return CommandOutcome(0, "installed", "")
            if argv[0].endswith("ffmpeg"):
                return CommandOutcome(0, "ffmpeg version 7.1", "")
            return CommandOutcome(1, "", "unexpected")

        result = ensure_tool(
            "ffmpeg", allow_install=True, platform_info=MAC, env={"PATH": ""},
            which=which, executor=executor
        )
        self.assertEqual(result.status, "installed")
        self.assertTrue(result.changed)

    def test_extended_capability_tools_have_central_contracts(self):
        expected = {
            "audacity_cli", "sox", "calibre", "cwebp", "exiftool", "flac",
            "gifsicle", "graphviz", "img2pdf", "libreoffice", "ocrmypdf",
            "tesseract", "oxipng", "pdftotext", "pngquant", "qpdf", "rsvg",
            "conda", "pnpm", "yarn",
        }
        self.assertTrue(expected.issubset(TOOL_SPECS))

    def test_cask_install_is_centralized_and_reverified(self):
        installed = {"value": False}

        def which(executable, search_path):
            del search_path
            if executable == "brew":
                return "/opt/homebrew/bin/brew"
            if executable == "soffice" and installed["value"]:
                return "/Applications/LibreOffice.app/Contents/MacOS/soffice"
            return None

        def executor(argv, timeout):
            del timeout
            if argv == ("/opt/homebrew/bin/brew", "--version"):
                return CommandOutcome(0, "Homebrew 4.6.0", "")
            if argv == ("/opt/homebrew/bin/brew", "install", "--cask", "libreoffice"):
                installed["value"] = True
                return CommandOutcome(0, "installed", "")
            if argv[0].endswith("soffice"):
                return CommandOutcome(0, "LibreOffice 25.2", "")
            return CommandOutcome(1, "", "unexpected")

        result = ensure_tool(
            "libreoffice", allow_install=True, platform_info=MAC, env={"PATH": ""},
            which=which, executor=executor,
        )
        self.assertEqual(result.status, "installed")
        self.assertTrue(result.changed)


if __name__ == "__main__":
    unittest.main()
