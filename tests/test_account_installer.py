import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from installer.account import (
    AGENTS_KV_KEY,
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
    _normalise_expert,
    repair_interrupted_account,
    required_experts,
    uninstall_account_resources,
)


class FakeAPI:
    def __init__(self):
        self.experts = {}
        self.kv = {}
        self.fail_save = None
        self.strip_saved_newlines = set()
        self.repr_install_smokes = set()
        self.nested_install_smokes = set()
        self.transient_api_failures = {}
        self.calls = []
        self.default_agent_id = "agent_account_QwenBase"
        self.agents = {
            self.default_agent_id: {
                "status": "success",
                "agent_id": self.default_agent_id,
                "provider": "alibaba",
                "model": "qwen3.7-max-2026-06-08",
            }
        }
        self.next_agent = 1
        self.fail_agent_runs = set()
        self.transient_agent_run_failures = {}
        self.agent_scope = ""
        self.scope_history = []

    def set_agent_scope(self, agent_id):
        self.agent_scope = agent_id
        self.scope_history.append(agent_id)

    def post(self, endpoint, payload, *, timeout=90):
        self.calls.append((endpoint, dict(payload)))
        remaining = self.transient_api_failures.get(endpoint, 0)
        if remaining:
            self.transient_api_failures[endpoint] = remaining - 1
            raise APIError(endpoint, "http_error", http_status=429, code="rate limited")
        if endpoint == "/api/token/validate":
            return {"status": "success", "agent_id": self.default_agent_id}
        if endpoint == "/api/expert/get":
            name = payload["name"]
            if name not in self.experts:
                raise APIError(endpoint, "http_error", http_status=404, code="not found")
            return dict(self.experts[name])
        if endpoint == "/api/expert/save":
            if payload["name"] == self.fail_save:
                return {"status": "error"}
            if not isinstance(payload.get("description"), str) or not payload["description"]:
                raise APIError(endpoint, "http_error", http_status=422, code="description too short")
            code = payload["code"]
            if payload["name"] in self.strip_saved_newlines:
                code = code.rstrip("\n")
            self.experts[payload["name"]] = {
                "status": "success",
                "name": payload["name"],
                "expert_code": code,
                "description": payload.get("description", ""),
                "kwargs": payload.get("kwargs", {}),
                "cspl": payload.get("cspl", "fython"),
                "global": True,
            }
            return {"status": "success"}
        if endpoint == "/api/expert/delete":
            if set(payload) != {"name"}:
                raise APIError(endpoint, "http_error", http_status=422, code="invalid delete payload")
            self.experts.pop(payload["name"], None)
            return {"status": "success"}
        if endpoint == "/api/expert/run":
            if payload.get("params", {}).get(INSTALL_SMOKE_PARAM):
                result = {
                    "status": "success",
                    "ok": True,
                    "installSmoke": payload["expert_name"],
                    "contract": INSTALL_SMOKE_MARKER,
                }
                if payload["expert_name"] in self.repr_install_smokes:
                    result = repr(result)
                if payload["expert_name"] in self.nested_install_smokes:
                    result = {"status": "success", "result": repr(result)}
                return {"status": "success", "result": result}
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
            if payload["agent_id"] in self.fail_agent_runs:
                raise APIError(endpoint, "http_error", http_status=400, code="pro_key_required")
            remaining = self.transient_agent_run_failures.get(payload["agent_id"], 0)
            if remaining:
                self.transient_agent_run_failures[payload["agent_id"]] = remaining - 1
                raise APIError(endpoint, "http_error", http_status=500, code="temporary provider failure")
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
            if set(payload) != {"key"}:
                raise APIError(endpoint, "http_error", http_status=422, code="invalid remove payload")
            self.kv.pop(payload["key"], None)
            return {"status": "success"}
        raise AssertionError(endpoint)


def expert(name, code=None):
    code = code or f"# expert: {name}\ndef {name}():\n    return '__EXTELLA_AGENT__'\n"
    return ExpertSource(name, Path(name + ".py"), code, name, {}, "a" * 64)


class AccountInstallerTests(unittest.TestCase):
    def test_normalises_live_expert_response_field_names(self):
        normalised = _normalise_expert(
            {
                "status": "success",
                "expert_name": "live_expert",
                "expert_description": "Live description",
                "expert_code": "def live_expert(): return True\n",
                "expert_params": {"value": ""},
                "cspl": "fython",
                "global": True,
            }
        )
        self.assertEqual(normalised["name"], "live_expert")
        self.assertEqual(normalised["description"], "Live description")
        self.assertEqual(normalised["kwargs"], {"value": ""})

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

    def test_real_toolbar_contract_excludes_wizard_and_includes_catalog_runtime(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory) / "bundle"
            manifests = bundle / "payload/marketplace/release/plugins"
            shutil.copytree(root / "release/plugins", manifests)
            required, smokes = required_experts(bundle)
        self.assertNotIn("wz_build_runner", required | smokes)
        self.assertNotIn("wz_capability_install", required | smokes)
        self.assertTrue({
            "catalog_tool_manage",
            "catalog_capability_uninstall",
            "cap_localmodel_install",
            "app_install",
            "app_start",
            "app_uninstall",
        }.issubset(required))

    def test_uses_token_associated_keyless_qwen_for_clean_account(self):
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
            self.assertEqual(len(api.agents), 1)
            self.assertTrue(all(agent["provider"] == "alibaba" for agent in api.agents.values()))
            self.assertTrue(all(agent["model"] == "qwen3.7-max-2026-06-08" for agent in api.agents.values()))
            ownership = json.loads(api.kv["extella:client:agents:v1"])
            self.assertIn(ownership["wizard"], api.agents)
            self.assertIn(ownership["builder"], api.agents)
            self.assertEqual(ownership["wizard"], api.default_agent_id)
            self.assertEqual(ownership["builder"], api.default_agent_id)
            self.assertFalse(any(endpoint == "/api/agent/create" for endpoint, _ in api.calls))
            self.assertEqual(api.agent_scope, ownership["wizard"])
            self.assertEqual(api.scope_history[-1], ownership["wizard"])

    def test_toolbar_profile_does_not_create_wizard_agent_ownership(self):
        api = FakeAPI()
        with tempfile.TemporaryDirectory() as directory:
            installer = AccountInstaller(
                api,
                release_version="2.0.0",
                state_root=Path(directory),
            )
            report = installer.install(
                {"safe_smoke": expert("safe_smoke")},
                required={"safe_smoke"},
                smokes=set(),
                kv_artifacts=[],
                agent_instructions=None,
            )
        self.assertEqual(report["status"], "installed")
        self.assertNotIn("extella:client:agents:v1", api.kv)
        self.assertFalse(any(endpoint == "/api/agent/create" for endpoint, _ in api.calls))

    def test_progress_reports_safe_bounded_account_steps(self):
        api = FakeAPI()
        events = []
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
                kv_artifacts=[KVArtifact("private:key", "TOP_SECRET", "test")],
                progress=events.append,
            )
        self.assertEqual(
            [event["phase"] for event in events],
            [
                "account_validation",
                "expert",
                "catalog_data",
                "functional_smoke",
                "account_complete",
            ],
        )
        self.assertEqual(events[1]["item"], "safe_smoke")
        serialized = json.dumps(events)
        self.assertNotIn("TOP_SECRET", serialized)
        self.assertNotIn("private:key", serialized)

    def test_repair_replaces_stale_pro_agent_ownership_with_token_qwen(self):
        api = FakeAPI()
        stale = "agent_user_ProQwen123"
        api.agents[stale] = {
            "status": "success",
            "agent_id": stale,
            "provider": "alibaba",
            "model": "qwen3.7-max-2026-06-08",
        }
        api.fail_agent_runs.add(stale)
        api.kv[AGENTS_KV_KEY] = json.dumps({"wizard": stale, "builder": stale})
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
            ownership = json.loads(api.kv[AGENTS_KV_KEY])
            self.assertEqual(ownership["wizard"], api.default_agent_id)
            self.assertEqual(ownership["builder"], api.default_agent_id)
            self.assertIn(stale, api.agents)
            self.assertFalse(any(endpoint == "/api/agent/delete" for endpoint, _ in api.calls))

    def test_live_api_trailing_newline_normalization_is_not_a_verification_failure(self):
        api = FakeAPI()
        api.strip_saved_newlines.add("newline_normalized")
        with tempfile.TemporaryDirectory() as directory:
            installer = AccountInstaller(
                api,
                release_version="2.0.0",
                state_root=Path(directory),
                agent_id="agent_user_Qwen123",
            )
            report = installer.install(
                {"newline_normalized": expert("newline_normalized")},
                required={"newline_normalized"},
                smokes=set(),
                kv_artifacts=[],
            )
            self.assertEqual(report["status"], "installed")
            self.assertFalse(api.experts["newline_normalized"]["expert_code"].endswith("\n"))

    def test_token_qwen_smoke_retries_transient_failure_and_is_cached(self):
        api = FakeAPI()
        api.transient_agent_run_failures[api.default_agent_id] = 2
        with tempfile.TemporaryDirectory() as directory, patch("installer.account.time.sleep"):
            installer = AccountInstaller(
                api,
                release_version="2.0.0",
                state_root=Path(directory),
            )
            installer.install(
                {"safe_smoke": expert("safe_smoke")},
                required={"safe_smoke"},
                smokes=set(),
                kv_artifacts=[],
                agent_instructions={"wizard": "wizard instructions", "builder": "builder instructions"},
            )
        agent_runs = [endpoint for endpoint, _ in api.calls if endpoint == "/api/agent/run"]
        self.assertEqual(len(agent_runs), 3)

    def test_live_fython_literal_result_is_accepted_without_eval(self):
        api = FakeAPI()
        api.repr_install_smokes.add("literal_smoke")
        with tempfile.TemporaryDirectory() as directory:
            installer = AccountInstaller(
                api,
                release_version="2.0.0",
                state_root=Path(directory),
                agent_id="agent_user_Qwen123",
            )
            report = installer.install(
                {"literal_smoke": expert("literal_smoke")},
                required={"literal_smoke"},
                smokes=set(),
                kv_artifacts=[],
            )
        self.assertEqual(report["status"], "installed")

    def test_live_fython_nested_result_envelope_is_accepted(self):
        api = FakeAPI()
        api.nested_install_smokes.add("nested_smoke")
        with tempfile.TemporaryDirectory() as directory:
            installer = AccountInstaller(
                api,
                release_version="2.0.0",
                state_root=Path(directory),
                agent_id="agent_user_Qwen123",
            )
            report = installer.install(
                {"nested_smoke": expert("nested_smoke")},
                required={"nested_smoke"},
                smokes=set(),
                kv_artifacts=[],
            )
        self.assertEqual(report["status"], "installed")

    def test_rollback_retries_transient_api_throttling(self):
        api = FakeAPI()
        api.fail_save = "second"
        api.transient_api_failures["/api/expert/delete"] = 2
        with tempfile.TemporaryDirectory() as directory, patch("installer.account.time.sleep"):
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
            report = json.loads((Path(directory) / "last-account-report.json").read_text())
        self.assertEqual(report["status"], "rolled_back")
        self.assertNotIn("first", api.experts)
        deletes = [endpoint for endpoint, _ in api.calls if endpoint == "/api/expert/delete"]
        self.assertEqual(len(deletes), 4)

    def test_install_retries_transient_idempotent_api_write(self):
        api = FakeAPI()
        api.transient_api_failures["/api/expert/save"] = 2
        with tempfile.TemporaryDirectory() as directory, patch("installer.account.time.sleep"):
            installer = AccountInstaller(
                api,
                release_version="2.0.0",
                state_root=Path(directory),
                agent_id="agent_user_Qwen123",
            )
            report = installer.install(
                {"retry_save": expert("retry_save")},
                required={"retry_save"},
                smokes=set(),
                kv_artifacts=[],
            )
        self.assertEqual(report["status"], "installed")
        saves = [endpoint for endpoint, _ in api.calls if endpoint == "/api/expert/save"]
        self.assertEqual(len(saves), 3)

    def test_install_smoke_waits_for_bounded_provider_propagation(self):
        api = FakeAPI()
        api.transient_api_failures["/api/expert/run"] = 5
        with tempfile.TemporaryDirectory() as directory, patch("installer.account.time.sleep") as sleep:
            installer = AccountInstaller(
                api,
                release_version="2.0.0",
                state_root=Path(directory),
                agent_id="agent_user_Qwen123",
            )
            report = installer.install(
                {"slow_compile": expert("slow_compile")},
                required={"slow_compile"},
                smokes=set(),
                kv_artifacts=[],
            )
        self.assertEqual(report["status"], "installed")
        runs = [endpoint for endpoint, _ in api.calls if endpoint == "/api/expert/run"]
        self.assertEqual(len(runs), 6)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [1.0, 3.0, 7.0, 15.0, 30.0])

    def test_next_install_repairs_durable_failed_rollback_first(self):
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
                {"partial": expert("partial")},
                required={"partial"},
                smokes=set(),
                kv_artifacts=[],
            )
            state_file = root / "account-state.json"
            state = json.loads(state_file.read_text())
            state["status"] = "rollback_failed"
            state_file.write_text(json.dumps(state))

            report = repair_interrupted_account(api, state_file)
            self.assertEqual(report["status"], "uninstalled")
            self.assertNotIn("partial", api.experts)
            self.assertFalse(state_file.exists())

    def test_repair_accepts_resources_already_restored_by_partial_rollback(self):
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
                {"previous": expert("previous")},
                required={"previous"},
                smokes=set(),
                kv_artifacts=[KVArtifact("catalog", "new catalog", "catalog")],
            )
            state_file = root / "account-state.json"
            state = json.loads(state_file.read_text())
            state["status"] = "rollback_failed"
            state_file.write_text(json.dumps(state))

            api.experts["previous"] = dict(state["changes"][0]["previous"])
            api.kv["catalog"] = "old catalog"
            report = repair_interrupted_account(api, state_file)

            self.assertEqual(report["status"], "uninstalled")
            self.assertEqual(
                [step["status"] for step in report["steps"]],
                ["already_restored", "already_restored"],
            )
            self.assertFalse(state_file.exists())
            repair_report = json.loads((root / "last-account-repair-report.json").read_text())
            self.assertEqual(repair_report["status"], "uninstalled")

    def test_repair_reconstructs_legacy_snapshot_metadata(self):
        api = FakeAPI()
        api.experts["legacy"] = {
            "status": "success",
            "name": "legacy",
            "expert_code": (
                "# expert: legacy\n"
                "# description: Previous legacy description\n"
                "# params: value\n"
                "def legacy(value=''): return 'old'\n"
            ),
            "description": "Previous legacy description",
            "kwargs": {"value": ""},
            "cspl": "fython",
            "global": True,
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            installer = AccountInstaller(
                api,
                release_version="2.0.0",
                state_root=root,
                agent_id="agent_user_Qwen123",
            )
            installer.install(
                {"legacy": expert("legacy")},
                required={"legacy"},
                smokes=set(),
                kv_artifacts=[],
            )
            state_file = root / "account-state.json"
            state = json.loads(state_file.read_text())
            state["status"] = "rollback_failed"
            state["changes"][0]["previous"]["description"] = ""
            state["changes"][0]["previous"]["kwargs"] = {}
            state_file.write_text(json.dumps(state))

            report = repair_interrupted_account(api, state_file)

            self.assertEqual(report["status"], "uninstalled")
            self.assertEqual(api.experts["legacy"]["description"], "Previous legacy description")
            self.assertEqual(api.experts["legacy"]["kwargs"], {"value": ""})
            self.assertEqual(
                report["steps"][0]["reconstructedFields"],
                ["description", "kwargs"],
            )

    def test_repair_persists_sanitized_api_failure_details(self):
        api = FakeAPI()
        with tempfile.TemporaryDirectory() as directory, patch("installer.account.time.sleep"):
            root = Path(directory)
            installer = AccountInstaller(
                api,
                release_version="2.0.0",
                state_root=root,
                agent_id="agent_user_Qwen123",
            )
            installer.install(
                {"partial": expert("partial")},
                required={"partial"},
                smokes=set(),
                kv_artifacts=[],
            )
            state_file = root / "account-state.json"
            state = json.loads(state_file.read_text())
            state["status"] = "rollback_failed"
            state_file.write_text(json.dumps(state))
            api.transient_api_failures["/api/expert/get"] = 6

            with self.assertRaisesRegex(AccountInstallError, "status=failed, failed=1"):
                repair_interrupted_account(api, state_file)

            repair_report = json.loads((root / "last-account-repair-report.json").read_text())
            self.assertEqual(repair_report["status"], "failed")
            self.assertEqual(repair_report["steps"][0]["errorClass"], "APIError")
            self.assertEqual(repair_report["steps"][0]["apiErrorClass"], "http_error")
            self.assertEqual(repair_report["steps"][0]["httpStatus"], 429)

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
