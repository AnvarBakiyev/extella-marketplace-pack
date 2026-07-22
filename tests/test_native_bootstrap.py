import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
MACOS = ROOT / "toolbar" / "install-all.sh"
WINDOWS = ROOT / "toolbar" / "install-all.ps1"


class NativeBootstrapTests(unittest.TestCase):
    def test_macos_rejects_unsupported_system_before_temp_or_download(self):
        with tempfile.TemporaryDirectory() as directory:
            fake = Path(directory) / "uname"
            fake.write_text(
                '#!/bin/sh\nif [ "${1:-}" = "-s" ]; then echo Linux; else echo x86_64; fi\n',
                encoding="utf-8",
            )
            fake.chmod(0o755)
            result = subprocess.run(
                ("/bin/sh", str(MACOS)),
                capture_output=True,
                text=True,
                env={**os.environ, "PATH": f"{directory}:/usr/bin:/bin"},
                timeout=10,
                check=False,
            )
        self.assertEqual(result.returncode, 3)
        self.assertIn("No changes were made", result.stderr)

    def test_bootstraps_are_pinned_and_never_use_raw_main(self):
        mac = MACOS.read_text(encoding="utf-8")
        windows = WINDOWS.read_text(encoding="utf-8")
        combined = mac + windows
        self.assertNotIn("raw.githubusercontent.com", combined)
        self.assertNotIn("refs/heads/main", combined)
        self.assertIn('UV_VERSION="0.11.30"', mac)
        self.assertIn('$UvVersion = "0.11.30"', windows)
        self.assertIn('PYTHON_VERSION="3.12.13"', mac)
        self.assertIn('$PythonVersion = "3.12.13"', windows)
        self.assertIn("--verify-only", mac)
        self.assertIn("[switch]$VerifyOnly", windows)
        self.assertIn("--uninstall", mac)
        self.assertIn("[switch]$Uninstall", windows)
        self.assertIn("client_uninstall.py", combined)
        self.assertIn("Strict bundle verification failed", windows)
        self.assertIn("PYTHONDONTWRITEBYTECODE=1", mac)
        self.assertIn('$env:PYTHONDONTWRITEBYTECODE = "1"', windows)
        self.assertLess(mac.index('if [ "$(uname -s'), mac.index("WORK=$(mktemp"))
        self.assertIn("sysctl.proc_translated", mac)
        self.assertIn("hw.optional.arm64", mac)
        self.assertLess(mac.index("sysctl.proc_translated"), mac.index("WORK=$(mktemp"))
        self.assertLess(windows.index("Keep platform rejection"), windows.index("New-Item -ItemType Directory -Path $Work"))

    def test_bootstrap_syntax(self):
        result = subprocess.run(
            ("/bin/sh", "-n", str(MACOS)), capture_output=True, text=True, check=False
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        powershell = shutil.which("pwsh")
        if powershell:
            command = (
                "$errors=$null; [System.Management.Automation.Language.Parser]::ParseFile("
                f"'{str(WINDOWS).replace("'", "''")}', [ref]$null, [ref]$errors) | Out-Null; "
                "if($errors.Count){$errors | Out-String | Write-Error; exit 1}"
            )
            parsed = subprocess.run(
                (powershell, "-NoProfile", "-Command", command),
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(parsed.returncode, 0, parsed.stderr)


if __name__ == "__main__":
    unittest.main()
