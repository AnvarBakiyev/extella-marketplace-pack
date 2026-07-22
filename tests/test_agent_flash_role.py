import importlib.util
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = ROOT / "tools" / "build_agent_flash_role.py"
SPEC = importlib.util.spec_from_file_location("build_agent_flash_role", TOOL_PATH)
assert SPEC and SPEC.loader
build_agent_flash_role = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = build_agent_flash_role
SPEC.loader.exec_module(build_agent_flash_role)


class AgentFlashRoleTests(unittest.TestCase):
    def setUp(self):
        self.path = ROOT / "experts" / "agent_flash_role.py"
        self.source = self.path.read_text(encoding="utf-8")

    def test_generated_payload_exactly_matches_all_role_sources(self):
        expected = build_agent_flash_role.load_roles(ROOT)
        self.assertEqual(build_agent_flash_role.extract_roles(self.source), expected)
        self.assertEqual(
            build_agent_flash_role.render_expert_source(self.source, expected),
            self.source,
        )

    def test_cloud_expert_source_stays_below_release_limit_and_has_bounded_lines(self):
        self.assertLessEqual(len(self.source.encode("utf-8")), 64 * 1024)
        self.assertLessEqual(max(map(len, self.source.splitlines())), 512)

    def test_compact_payload_decodes_inside_real_entrypoint(self):
        namespace = {}
        exec(compile(self.source, str(self.path), "exec"), namespace)
        result = json.loads(namespace["agent_flash_role"]("agent_test", "missing-role"))
        self.assertEqual(result["status"], "error")
        self.assertIn("missing-role", result["message"])


if __name__ == "__main__":
    unittest.main()
