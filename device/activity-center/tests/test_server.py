from __future__ import annotations

import sys
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bridge"))

import server  # noqa: E402
from server import (  # noqa: E402
    CONTROL_TOKEN,
    _LISTENER_COMMAND,
    control_authorized,
)


class ServerTests(unittest.TestCase):
    def test_windows_listener_inventory_returns_only_pid_metadata(self) -> None:
        response = subprocess.CompletedProcess(
            [],
            0,
            '[{"ProcessId":321,"ParentProcessId":7}]',
            "",
        )
        server._process_cache = (0.0, {})
        with (
            patch.object(server.platform, "system", return_value="Windows"),
            patch.object(server.shutil, "which", return_value="powershell.exe"),
            patch.object(server.subprocess, "run", return_value=response),
        ):
            result = server.listener_processes()
        self.assertEqual(result["processes"], [{"pid": 321, "ppid": 7}])
        self.assertNotIn("command", result["processes"][0])

    def test_matches_listener_and_rejects_shell_probe(self) -> None:
        listener = (
            "/Users/me/.cache/uv/archive-v0/env/bin/python "
            "/Users/me/.cache/uv/archive-v0/env/bin/extella-listener "
            "--url https://disnet.extella.ai/ --type private"
        )
        shell = "zsh -c ps | rg '/bin/extella-listener --url https://disnet.extella.ai/'"
        self.assertIsNotNone(_LISTENER_COMMAND.search(listener))
        self.assertIsNone(_LISTENER_COMMAND.search(shell))

    def test_control_requires_token_and_known_browser_origin(self) -> None:
        self.assertTrue(control_authorized("https://prod.extella.ai", CONTROL_TOKEN))
        self.assertTrue(control_authorized("", CONTROL_TOKEN))
        self.assertFalse(control_authorized("https://example.com", CONTROL_TOKEN))
        self.assertFalse(control_authorized("https://prod.extella.ai", "wrong"))


if __name__ == "__main__":
    unittest.main()
