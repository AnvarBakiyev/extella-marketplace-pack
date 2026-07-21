import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CapabilityDependencySourceTests(unittest.TestCase):
    def test_checked_in_capability_sources_are_normalized(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "tools/normalize_cap_dependencies.py")],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
