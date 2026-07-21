import json
import tempfile
import unittest
from pathlib import Path

from installer.account import (
    APIError,
    AccountInstallError,
    AccountInstaller,
    ExpertSource,
    KVArtifact,
)


class FakeAPI:
    def __init__(self):
        self.experts = {}
        self.kv = {}
        self.fail_save = None
        self.calls = []
        self.agents = {}
        self.next_agent = 1

    def post(self, endpoint, payload, *, timeout=90):
        self.calls.append((endpoint, dict(payload)))
        if endpoint == "/api/token/validate":
            return {"status": "success"}
        if endpoint == "/api/expert/get":
            name = payload["name"]
            if name not in self.experts:
                raise APIError(endpoint, "http_error", http_status=404, code="not found")
            return dict(self.experts[name])
        if endpoint == "/api/expert/save":
            if payload["name"] == self.fail_save:
                return {"status": "error"}
            self.experts[payload["name"]] = {
                "status": "success",
                "name": payload["name"],
                "expert_code": payload["code"],
                "description": payload.get("description", ""),
                "kwargs": payload.get("kwargs", {}),
                "cspl": payload.get("cspl", "fython"),
                "global": True,
            }
            return {"status": "success"}
        if endpoint == "/api/expert/delete":
            self.experts.pop(payload["name"], None)
            return {"status": "success"}
        if endpoint == "/api/expert/run":
            return {"status": "success", "result": json.dumps({"ok": True})}
        if endpoint == "/api/agent/create":
            agent_id = f"agent_user_Qwen{self.next_agent}"
            self.next_agent += 1
            self.agents[agent_id] = {
                "status": "success",
                "agent_id": agent_id,
                "provider": payload["provider"],
                "model": payload["model"],
            }
            return {"status": "success", "agent_id": agent_id}
        if endpoint == "/api/agent/get":
            if payload["agent_id"] not in self.agents:
                raise APIError(endpoint, "http_error", http_status=404, code="not found")
            return dict(self.agents[payload["agent_id"]])
        if endpoint == "/api/agent/run":
            return {"status": "success", "output_text": "EXTELLA_READY"}
        if endpoint == "/api/agent/delete":
            self.agents.pop(payload["agent_id"], None)
            return {"status": "success"}
        if endpoint == "/api/kv/get":
            if payload["key"] not in self.kv:
                raise APIError(endpoint, "http_error", http_status=404, code="not found")
            return {"status": "success", "value": self.kv[payload["key"]]}
        if endpoint == "/api/kv/set":
            self.kv[payload["key"]] = payload["value"]
            return {"status": "success"}
        if endpoint == "/api/kv/remove":
            self.kv.pop(payload["key"], None)
            return {"status": "success"}
        raise AssertionError(endpoint)


def expert(name, code=None):
    code = code or f"# expert: {name}\ndef {name}():\n    return '__EXTELLA_AGENT__'\n"
    return ExpertSource(name, Path(name + ".py"), code, name, {}, "a" * 64)


class AccountInstallerTests(unittest.TestCase):
    def test_creates_two_explicit_qwen_agents_for_clean_account(self):
        api = FakeAPI()
        with tempfile.TemporaryDirectory() as directory:
            installer = AccountInstaller(
                api,
                release_version="2.0.0",
                state_root=Path(directory),
            )
            installer.install(
                {"safe_smoke": expert("safe_smoke")},
                required={"safe_smoke"},
                smokes={"safe_smoke"},
                kv_artifacts=[],
                agent_instructions={"wizard": "wizard instructions", "builder": "builder instructions"},
            )
            self.assertEqual(len(api.agents), 2)
            self.assertTrue(all(agent["provider"] == "alibaba" for agent in api.agents.values()))
            self.assertTrue(all(agent["model"] == "qwen3.7-max-2026-06-08" for agent in api.agents.values()))
            ownership = json.loads(api.kv["extella:client:agents:v1"])
            self.assertIn(ownership["wizard"], api.agents)
            self.assertIn(ownership["builder"], api.agents)

    def test_installs_verifies_smokes_and_never_journals_token(self):
        api = FakeAPI()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            installer = AccountInstaller(
                api,
                release_version="2.0.0",
                state_root=root,
                agent_id="agent_user_Qwen123",
            )
            report = installer.install(
                {"safe_smoke": expert("safe_smoke")},
                required={"safe_smoke"},
                smokes={"safe_smoke"},
                kv_artifacts=[KVArtifact("catalog", "{}", "catalog")],
            )
            self.assertEqual(report["status"], "installed")
            self.assertIn("agent_user_Qwen123", api.experts["safe_smoke"]["expert_code"])
            state_text = (root / "account-state.json").read_text(encoding="utf-8")
            self.assertNotIn("X-Auth-Token", state_text)
            self.assertNotIn("expert_code", state_text)

    def test_required_failure_restores_previous_account_state(self):
        api = FakeAPI()
        api.experts["first"] = {
            "status": "success",
            "name": "first",
            "expert_code": "# expert: first\ndef first(): return 'old'\n",
            "description": "old",
            "kwargs": {},
            "cspl": "fython",
            "global": True,
        }
        api.fail_save = "second"
        with tempfile.TemporaryDirectory() as directory:
            installer = AccountInstaller(
                api,
                release_version="2.0.0",
                state_root=Path(directory),
                agent_id="agent_user_Qwen123",
            )
            with self.assertRaises(AccountInstallError):
                installer.install(
                    {"first": expert("first"), "second": expert("second")},
                    required={"first", "second"},
                    smokes=set(),
                    kv_artifacts=[],
                )
            self.assertIn("return 'old'", api.experts["first"]["expert_code"])
            self.assertNotIn("second", api.experts)
            report = json.loads((Path(directory) / "last-account-report.json").read_text())
            self.assertEqual(report["status"], "rolled_back")

    def test_does_not_install_discovered_but_unowned_experts(self):
        api = FakeAPI()
        with tempfile.TemporaryDirectory() as directory:
            installer = AccountInstaller(
                api,
                release_version="2.0.0",
                state_root=Path(directory),
                agent_id="agent_user_Qwen123",
            )
            installer.install(
                {
                    "built_in": expert("built_in"),
                    "third_party_unverified": expert("third_party_unverified"),
                },
                required={"built_in"},
                smokes=set(),
                kv_artifacts=[],
            )
            self.assertEqual(set(api.experts), {"built_in"})
            saved = [payload["name"] for endpoint, payload in api.calls if endpoint == "/api/expert/save"]
            self.assertEqual(saved, ["built_in"])


if __name__ == "__main__":
    unittest.main()
