import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from types import ModuleType, SimpleNamespace
import unittest
import urllib.error
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def load_expert():
    path = ROOT / "experts/cap_localmodel_install.py"
    spec = importlib.util.spec_from_file_location("cap_localmodel_install_tested", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class Opened:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class LocalModelInstallTests(unittest.TestCase):
    def bridge(self, root: Path, service_control):
        bridge = ModuleType("extella_expert_bridge")
        bridge.path_or_error = lambda name, repair=False: (str(root / "ollama"), {"ready": True})
        bridge.locations = lambda: {"logs_root": str(root / "logs")}
        bridge.service_control = service_control
        return bridge

    def test_extella_started_ollama_is_registered_with_pid_and_port(self):
        module = load_expert()
        calls = []

        def service(action, **kwargs):
            calls.append((action, kwargs))
            return {"status": "running", "canStop": True, "pid": 4242, "port": 11434}

        with tempfile.TemporaryDirectory() as directory, patch.dict(
            sys.modules,
            {"extella_expert_bridge": self.bridge(Path(directory), service)},
        ), patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("offline"),
        ), patch.object(
            subprocess,
            "run",
            return_value=SimpleNamespace(stdout="", returncode=0),
        ), patch.object(subprocess, "Popen") as popen:
            result = json.loads(module.cap_localmodel_install("qwen2.5:7b"))

        self.assertEqual(result["status"], "pulling")
        self.assertEqual(result["runtime"], {"owned": True, "pid": 4242, "port": 11434})
        self.assertEqual(calls[0][0], "start")
        self.assertEqual(calls[0][1]["runtime_id"], "extella.ollama")
        self.assertEqual(calls[0][1]["owner"], "extella_catalog_model")
        self.assertEqual(popen.call_args.args[0][1], "pull")
        self.assertFalse(popen.call_args.kwargs["shell"])

    def test_existing_user_ollama_is_used_but_not_claimed(self):
        module = load_expert()

        def service(_action, **_kwargs):
            return {"status": "degraded", "canStop": False, "pid": None, "port": 11434}

        with tempfile.TemporaryDirectory() as directory, patch.dict(
            sys.modules,
            {"extella_expert_bridge": self.bridge(Path(directory), service)},
        ), patch(
            "urllib.request.urlopen",
            return_value=Opened(),
        ), patch.object(
            subprocess,
            "run",
            return_value=SimpleNamespace(stdout="qwen2.5:7b latest", returncode=0),
        ), patch.object(subprocess, "Popen") as popen:
            result = json.loads(module.cap_localmodel_install("qwen2.5:7b"))

        self.assertEqual(result["status"], "already")
        self.assertEqual(result["runtime"], {"owned": False, "pid": None, "port": 11434})
        popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
