import tempfile
import unittest
from pathlib import Path

from runtime.extella_runtime.doctor import run_doctor
from runtime.extella_runtime.ensure_tool import CommandOutcome
from runtime.extella_runtime.platforms import detect_platform


class DoctorTests(unittest.TestCase):
    def test_unsupported_platform_stops_before_other_checks(self):
        linux = detect_platform(system="Linux", architecture="x86_64", release="6.8")
        report = run_doctor(platform_info=linux)
        self.assertEqual(report.status, "unsupported")
        self.assertEqual([check.name for check in report.checks], ["platform"])

    def test_supported_dry_run_can_be_ready(self):
        mac = detect_platform(system="Darwin", architecture="arm64", release="15.5")

        def which(executable, search_path):
            del search_path
            if executable in {"python3", "git"}:
                return f"/opt/homebrew/bin/{executable}"
            return None

        def executor(argv, timeout):
            del timeout
            version = "Python 3.12.9" if argv[0].endswith("python3") else "git version 2.49.0"
            return CommandOutcome(0, version, "")

        with tempfile.TemporaryDirectory() as directory:
            report = run_doctor(
                platform_info=mac,
                data_root=Path(directory) / ".extella",
                required_tools=("python", "git"),
                optional_tools=(),
                minimum_free_bytes=1,
                env={"HOME": directory, "PATH": ""},
                which=which,
                executor=executor,
            )
        self.assertEqual(report.status, "ready")
        self.assertFalse(report.changed)


if __name__ == "__main__":
    unittest.main()
