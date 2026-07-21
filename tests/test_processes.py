import socket
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from runtime.extella_runtime.platforms import detect_platform
from runtime.extella_runtime.processes import (
    ProcessControlError,
    ProcessSupervisor,
    RuntimeSpec,
    listening_pids,
    process_identity,
)


class WindowsProcessAdapterTests(unittest.TestCase):
    def setUp(self):
        self.windows = detect_platform(
            system="Windows", architecture="AMD64", release="11", version="10.0.26100"
        )

    @patch("runtime.extella_runtime.processes._powershell", return_value="powershell.exe")
    @patch("runtime.extella_runtime.processes._run")
    def test_windows_identity_contains_no_raw_command(self, run, _powershell):
        import subprocess

        run.return_value = subprocess.CompletedProcess(
            [], 0,
            stdout='{"ProcessId":42,"ParentProcessId":7,"Name":"python.exe","CreationDate":"20260721234209.000000+000","CommandLine":"python.exe server.py --secret hidden"}',
            stderr="",
        )
        identity = process_identity(42, platform_info=self.windows)
        self.assertEqual(identity.pid, 42)
        self.assertEqual(identity.executable, "python.exe")
        self.assertNotIn("hidden", str(identity.to_dict()))

    @patch("runtime.extella_runtime.processes._powershell", return_value="powershell.exe")
    @patch("runtime.extella_runtime.processes._run")
    def test_windows_port_owner_adapter(self, run, _powershell):
        import subprocess

        run.return_value = subprocess.CompletedProcess([], 0, stdout="42\n99\n42\n", stderr="")
        self.assertEqual(listening_pids(8765, platform_info=self.windows), [42, 99])


@unittest.skipUnless(sys.platform == "darwin", "physical process test runs on macOS host")
class ProcessSupervisorTests(unittest.TestCase):
    def _free_port(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]

    def test_start_idempotence_health_pid_and_safe_stop(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            port = self._free_port()
            spec = RuntimeSpec(
                runtime_id="test_runtime",
                name="Test runtime",
                argv=(sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"),
                cwd=root,
                port=port,
                health_url=f"http://127.0.0.1:{port}/",
                log_path=root / "service.log",
                owner="test",
                autostart="none",
            )
            supervisor = ProcessSupervisor(
                state_file=root / "processes.json",
                platform_info=detect_platform(system="Darwin", architecture="arm64", release="15"),
            )
            first = supervisor.start(spec, timeout=10)
            second = supervisor.start(spec, timeout=10)
            self.assertEqual(first["status"], "running")
            self.assertEqual(first["pid"], second["pid"])
            self.assertTrue(first["canStop"])
            stopped = supervisor.stop(spec)
            self.assertEqual(stopped["status"], "stopped")

    def test_refuses_to_stop_unowned_port(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            port = self._free_port()
            spec = RuntimeSpec(
                runtime_id="not_owned",
                name="Not owned",
                argv=(sys.executable, "-m", "http.server", str(port)),
                cwd=root,
                port=port,
                health_url=f"http://127.0.0.1:{port}/",
                log_path=root / "service.log",
                owner="test",
                autostart="none",
            )
            supervisor = ProcessSupervisor(
                state_file=root / "processes.json",
                platform_info=detect_platform(system="Darwin", architecture="arm64", release="15"),
            )
            external = __import__("subprocess").Popen(
                list(spec.argv), cwd=root, stdout=__import__("subprocess").DEVNULL,
                stderr=__import__("subprocess").DEVNULL
            )
            try:
                for _ in range(30):
                    if supervisor.status(spec)["errorClass"] == "port_occupied_by_unowned_process":
                        break
                    __import__("time").sleep(0.1)
                with self.assertRaises(ProcessControlError):
                    supervisor.stop(spec)
            finally:
                external.terminate()
                external.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
