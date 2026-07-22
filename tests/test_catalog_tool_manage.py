import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def load_expert():
    path = ROOT / "experts/catalog_tool_manage.py"
    spec = importlib.util.spec_from_file_location("catalog_tool_manage_tested", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class CatalogToolManageTests(unittest.TestCase):
    def bridge(self, state_root: Path, *, changed: bool):
        bridge = ModuleType("extella_expert_bridge")
        bridge.locations = lambda: {"state_root": str(state_root)}
        bridge.ensure = lambda name, repair=False: {
            "tool": name,
            "status": "installed" if changed and repair else "ready",
            "ready": True,
            "path": "/usr/local/bin/" + name,
            "changed": bool(changed and repair),
        }
        bridge.path_or_error = lambda name, repair=False: ("/usr/local/bin/" + name, {"ready": True})
        return bridge

    def test_installs_and_only_then_owns_dependency(self):
        module = load_expert()
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            sys.modules,
            {"extella_expert_bridge": self.bridge(Path(directory), changed=True)},
        ):
            result = json.loads(module.catalog_tool_manage("install", "ffmpeg"))
            state = json.loads((Path(directory) / "catalog-tools.json").read_text())
        self.assertEqual(result["status"], "installed")
        self.assertTrue(result["managed"])
        self.assertEqual(state["tools"]["ffmpeg"]["managedDependencies"], ["ffmpeg"])

    def test_uninstall_preserves_preexisting_user_program(self):
        module = load_expert()
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            sys.modules,
            {"extella_expert_bridge": self.bridge(Path(directory), changed=False)},
        ), patch.object(subprocess, "run") as run:
            installed = json.loads(module.catalog_tool_manage("install", "pandoc"))
            removed = json.loads(module.catalog_tool_manage("uninstall", "pandoc"))
        self.assertEqual(installed["status"], "already")
        self.assertFalse(installed["managed"])
        self.assertTrue(removed["preserved_external"])
        run.assert_not_called()

    def test_uninstalls_only_recorded_extella_program(self):
        module = load_expert()
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            sys.modules,
            {"extella_expert_bridge": self.bridge(Path(directory), changed=True)},
        ), patch.object(
            subprocess,
            "run",
            return_value=SimpleNamespace(returncode=0, stdout="", stderr=""),
        ) as run:
            json.loads(module.catalog_tool_manage("install", "ghostscript"))
            removed = json.loads(module.catalog_tool_manage("uninstall", "ghostscript"))
            state = json.loads((Path(directory) / "catalog-tools.json").read_text())
        self.assertTrue(removed["device_removed"])
        self.assertTrue(removed["removed"])
        self.assertNotIn("ghostscript", state["tools"])
        argv = run.call_args.args[0]
        self.assertEqual(argv[:2], ["/usr/local/bin/brew", "uninstall"])
        self.assertIn("ghostscript", argv)
        self.assertFalse(run.call_args.kwargs["shell"])

    def test_partial_composite_install_keeps_cleanup_ownership(self):
        module = load_expert()
        with tempfile.TemporaryDirectory() as directory:
            bridge = self.bridge(Path(directory), changed=False)
            bridge.ensure = lambda name, repair=False: (
                {"ready": True, "path": "/usr/local/bin/ocrmypdf", "changed": True}
                if name == "ocrmypdf"
                else {"ready": False, "path": None, "changed": False, "message": "failed"}
            )
            with patch.dict(sys.modules, {"extella_expert_bridge": bridge}):
                result = json.loads(module.catalog_tool_manage("install", "ocr"))
                state = json.loads((Path(directory) / "catalog-tools.json").read_text())
        self.assertEqual(result["status"], "error")
        self.assertEqual(state["tools"]["ocr"]["managedDependencies"], ["ocrmypdf"])

    def test_windows_owned_tool_uses_noninteractive_winget_uninstall(self):
        module = load_expert()
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            sys.modules,
            {"extella_expert_bridge": self.bridge(Path(directory), changed=True)},
        ), patch(
            "sys.platform",
            "win32",
        ), patch.object(
            subprocess,
            "run",
            return_value=SimpleNamespace(returncode=0, stdout="", stderr=""),
        ) as run:
            json.loads(module.catalog_tool_manage("install", "ffmpeg"))
            removed = json.loads(module.catalog_tool_manage("uninstall", "ffmpeg"))
        self.assertTrue(removed["removed"])
        argv = run.call_args.args[0]
        self.assertEqual(argv[:4], ["/usr/local/bin/winget", "uninstall", "--id", "Gyan.FFmpeg"])
        self.assertIn("--disable-interactivity", argv)
        self.assertFalse(run.call_args.kwargs["shell"])

    def test_rejects_unknown_catalog_tool(self):
        result = json.loads(load_expert().catalog_tool_manage("install", "anything"))
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error_class"], "unsupported_tool")


if __name__ == "__main__":
    unittest.main()
