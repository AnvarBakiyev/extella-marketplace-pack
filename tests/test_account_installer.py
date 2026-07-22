import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from installer.account import (
    APIError,
    BOOTSTRAP_AGENT_SCOPE,
    AccountInstallError,
    AccountInstaller,
    ExtellaAPI,
    ExpertSource,
    KVArtifact,
    INSTALL_SMOKE_MARKER,
    INSTALL_SMOKE_PARAM,
    instrument_expert_code,
    load_expert_sources,
    required_experts,
    uninstall_account_resources,
)


class FakeAPI:
    def __init__(self):
        self.experts = {}
        self.kv = {}
        self.fail_save = None
        self.calls = []
        self.agents = {}
        self.next_agent = 1
        self.agent_scope = ""
        self.scope_history = []

    def set_agent_scope(self, agent_id):
        self.agent_scope = agent_id
        self.scope_history.append(agent_id)

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
            if payload.get("params", {}).get(INSTALL_SMOKE_PARAM):
                return {
                    "status": "success",
                    "result": {
                        "status": "success",
                        "ok": True,
                        "installSmoke": payload["expert_name"],
                        "contract": INSTALL_SMOKE_MARKER,
                    },
                }
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
    def test_api_starts_with_non_real_bootstrap_scope_and_accepts_current_account_agent(self):
        api = ExtellaAPI("t" * 24)
        self.assertEqual(api.agent_scope, BOOTSTRAP_AGENT_SCOPE)
        api.set_agent_scope("agent_user_Qwen123")
        self.assertEqual(api.agent_scope, "agent_user_Qwen123")
        with self.assertRaises(AccountInstallError):
            api.set_agent_scope(BOOTSTRAP_AGENT_SCOPE)

    def test_live_token_validation_contract_is_injected_by_secret_owning_client(self):
        token = "t" * 24
        response = MagicMock()
        response.read.return_value = b'{"status":"success","valid":true}'
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        with patch("installer.account.urllib.request.urlopen", return_value=response) as opener:
            result = ExtellaAPI(token).post("/api/token/validate", {})

        request = opener.call_args.args[0]
        self.assertEqual(json.loads(request.data), {"token": token})
        self.assertTrue(result["valid"])

    def test_instrumented_python_expert_delegates_and_has_safe_probe(self):
        source = expert(
            "greeting",
            "# expert: greeting\ndef greeting(name='world'):\n    return 'hello ' + name\n",
        )
        namespace = {}
        exec(instrument_expert_code(source, "agent_user_Qwen123"), namespace)
        self.assertEqual(namespace["greeting"](name="Ada"), "hello Ada")
        self.assertEqual(
            namespace["greeting"](**{INSTALL_SMOKE_PARAM: True}),
            {
                "status": "success",
                "ok": True,
                "installSmoke": "greeting",
                "contract": INSTALL_SMOKE_MARKER,
            },
        )

    def test_every_bundled_source_accepts_deterministic_install_smoke(self):
        root = Path(__file__).resolve().parents[1]
        wizard = root.parent / "wizard"
        inventory = json.loads((root / "release/expert-classification.json").read_text())
        paths = [
            *root.glob("experts/*.py"),
            *root.glob("platform_experts/*.py"),
            *root.glob("automations/experts/*.py"),
            *wizard.glob("experts/*.py"),
        ]
        sources = load_expert_sources(paths)
        for name in inventory["bundled"]:
            instrumented = instrument_expert_code(sources[name], "agent_user_Qwen123")
            self.assertIn(f"{INSTALL_SMOKE_PARAM}=False", instrumented)
            if "$extens(" not in "\n".join(instrumented.splitlines()[:20]):
                compile(instrumented, str(sources[name].path), "exec")

    def test_full_clean_account_contract_installs_and_smokes_every_bundled_expert(self):
        root = Path(__file__).resolve().parents[1]
        wizard = root.parent / "wizard"
        api = FakeAPI()
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory) / "bundle"
            marketplace_target = bundle / "payload/marketplace"
            wizard_target = bundle / "payload/wizard"
            for relative in (
                "experts",
                "platform_experts",
                "automations/experts",
                "release/plugins",
            ):
                shutil.copytree(root / relative, marketplace_target / relative)
            for relative in (
                "release/catalog-policy.json",
                "apps_catalog.json",
                "composer_catalog.json",
                "loc_catalog.json",
                "mcp_catalog.json",
                "models_catalog.json",
            ):
                target = marketplace_target / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(root / relative, target)
            shutil.copytree(wizard / "experts", wizard_target / "experts")
            shutil.copytree(wizard / "agents", wizard_target / "agents")

            sources = __import__(
                "installer.account", fromlist=["discover_bundle_experts"]
            ).discover_bundle_experts(bundle)
            required, functional_smokes = required_experts(bundle)
            installer = AccountInstaller(
                api,
                release_version="2.0.0-rc.1",
                state_root=Path(directory) / "state",
            )
            report = installer.install(
                sources,
                required=required,
                smokes=functional_smokes,
                kv_artifacts=__import__(
                    "installer.account", fromlist=["catalog_kv_artifacts"]
                ).catalog_kv_artifacts(bundle),
                agent_instructions={
                    "wizard": (wizard / "agents/wizard_agent.instructions.md").read_text(),
                    "builder": (wizard / "agents/builder_agent.instructions.md").read_text(),
                },
            )
            self.assertEqual(report["status"], "installed")
            self.assertEqual(set(api.experts), required | functional_smokes)
            install_smokes = [
                payload["expert_name"]
                for endpoint, payload in api.calls
                if endpoint == "/api/expert/run" and payload["params"].get(INSTALL_SMOKE_PARAM)
            ]
            self.assertEqual(set(install_smokes), required | functional_smokes)
            self.assertEqual(len(install_smokes), len(required | functional_smokes))
            functional = [
                payload["expert_name"]
                for endpoint, payload in api.calls
                if endpoint == "/api/expert/run" and not payload["params"].get(INSTALL_SMOKE_PARAM)
            ]
            self.assertEqual(set(functional), functional_smokes)

    def test_base_contract_excludes_on_demand_and_unverified_experts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifests = root / "payload/marketplace/release/plugins"
            manifests.mkdir(parents=True)
            for index, classification in enumerate(
                ("bundled", "supported_on_demand", "third_party_unverified")
            ):
                (manifests / f"p{index}.json").write_text(
                    json.dumps(
                        {
                            "classification": classification,
                            "experts": {
                                "required": [f"required_{index}"],
                                "smoke": [f"smoke_{index}"],
                            },
                        }
                    ),
                    encoding="utf-8",
                )
            required, smokes = required_experts(root)
            self.assertEqual(required, {"required_0"})
            self.assertEqual(smokes, {"smoke_0"})

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
            self.assertEqual(api.agent_scope, ownership["wizard"])
            self.assertEqual(api.scope_history[-1], ownership["wizard"])

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
            install_smokes = [
                payload["expert_name"]
                for endpoint, payload in api.calls
                if endpoint == "/api/expert/run" and payload["params"].get(INSTALL_SMOKE_PARAM)
            ]
            self.assertEqual(install_smokes, ["built_in"])

    def test_durable_uninstall_restores_previous_and_removes_owned_resources(self):
        api = FakeAPI()
        api.experts["previous"] = {
            "status": "success",
            "name": "previous",
            "expert_code": "# expert: previous\ndef previous(): return 'old'\n",
            "description": "old",
            "kwargs": {},
            "cspl": "fython",
            "global": True,
        }
        api.kv["catalog"] = "old catalog"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            installer = AccountInstaller(
                api,
                release_version="2.0.0",
                state_root=root,
                agent_id="agent_user_Qwen123",
            )
            installer.install(
                {"previous": expert("previous"), "new": expert("new")},
                required={"previous", "new"},
                smokes=set(),
                kv_artifacts=[KVArtifact("catalog", "new catalog", "catalog")],
            )
            state_file = root / "account-state.json"
            self.assertEqual(state_file.stat().st_mode & 0o777, 0o600)
            report = uninstall_account_resources(api, state_file)
            self.assertEqual(report["status"], "uninstalled")
            self.assertIn("return 'old'", api.experts["previous"]["expert_code"])
            self.assertNotIn("new", api.experts)
            self.assertEqual(api.kv["catalog"], "old catalog")
            self.assertFalse(state_file.exists())

    def test_durable_uninstall_preserves_resource_changed_after_install(self):
        api = FakeAPI()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            installer = AccountInstaller(
                api,
                release_version="2.0.0",
                state_root=root,
                agent_id="agent_user_Qwen123",
            )
            installer.install(
                {"owned": expert("owned")},
                required={"owned"},
                smokes=set(),
                kv_artifacts=[],
            )
            api.experts["owned"]["expert_code"] += "# user edit\n"
            report = uninstall_account_resources(api, root / "account-state.json")
            self.assertEqual(report["status"], "action_required")
            self.assertIn("user edit", api.experts["owned"]["expert_code"])

    def test_reinstall_chain_removes_first_install_from_clean_account(self):
        api = FakeAPI()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = AccountInstaller(
                api,
                release_version="1.0.0",
                state_root=root,
                agent_id="agent_user_Qwen123",
            )
            first.install(
                {"owned": expert("owned", "# expert: owned\ndef owned(): return 'v1'\n")},
                required={"owned"},
                smokes=set(),
                kv_artifacts=[],
            )
            second = AccountInstaller(
                api,
                release_version="2.0.0",
                state_root=root,
                agent_id="agent_user_Qwen123",
            )
            second.install(
                {"owned": expert("owned", "# expert: owned\ndef owned(): return 'v2'\n")},
                required={"owned"},
                smokes=set(),
                kv_artifacts=[],
            )
            state = json.loads((root / "account-state.json").read_text())
            self.assertEqual(state["previousState"]["releaseVersion"], "1.0.0")
            report = uninstall_account_resources(api, root / "account-state.json")
            self.assertEqual(report["status"], "uninstalled")
            self.assertNotIn("owned", api.experts)


if __name__ == "__main__":
    unittest.main()
