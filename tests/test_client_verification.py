import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from installer.account import AGENTS_KV_KEY, INSTALL_SMOKE_MARKER, INSTALL_SMOKE_PARAM
from installer.verification import (
    ALLOWED_ORIGIN,
    SERVICE_PORTS,
    ClientVerificationError,
    verify_installed_client,
)
from runtime.extella_runtime.platforms import detect_platform


class VerificationAPI:
    def __init__(self, expert_code, kv):
        self.expert_code = expert_code
        self.kv = kv

    def post(self, endpoint, payload, *, timeout=90):
        if endpoint == "/api/token/validate":
            return {"status": "success"}
        if endpoint == "/api/expert/get":
            return {
                "status": "success",
                "name": payload["name"],
                "expert_code": self.expert_code,
                "global": True,
            }
        if endpoint == "/api/expert/run":
            self.assert_install_smoke(payload)
            return {
                "status": "success",
                "result": {
                    "status": "success",
                    "installSmoke": payload["expert_name"],
                    "contract": INSTALL_SMOKE_MARKER,
                },
            }
        if endpoint == "/api/kv/get":
            return {"status": "success", "value": self.kv[payload["key"]]}
        if endpoint == "/api/agent/get":
            return {
                "status": "success",
                "agent_id": payload["agent_id"],
                "provider": "alibaba",
                "model": "qwen3.7-max-2026-06-08",
            }
        if endpoint == "/api/agent/run":
            return {"status": "success", "output_text": "EXTELLA_READY"}
        raise AssertionError(endpoint)

    @staticmethod
    def assert_install_smoke(payload):
        if payload.get("params") != {INSTALL_SMOKE_PARAM: True}:
            raise AssertionError("expert was not run with the install-smoke contract")


class ClientVerificationTests(unittest.TestCase):
    def _fixture(self, root):
        release = "2.0.0-rc.1"
        data = root / "data"
        home = root / "home"
        toolbar = home / "Library/Application Support/extella-desktop/toolbar.js"
        required = (
            toolbar,
            data / "installer/client_install.py",
            data / "installer/client_uninstall.py",
            data / "installer/client_verify.py",
            data / "installer/external_matrix.py",
            data / "activity-center/server.py",
            data / "wizard/app/server.py",
            data / "wizard/app/wizard.html",
            data / "plugins/extella_travel_agency/server.py",
            data / "plugins/extella_contract_agent/server.py",
            data / "wizard/app/config.json",
        )
        for path in required:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixture", encoding="utf-8")
        (data / "wizard/app/config.json").chmod(0o600)
        registry = data / "plugins/_registry"
        registry.mkdir(parents=True)
        for service_id in set(SERVICE_PORTS) - {"extella_activity_center"}:
            (registry / f"{service_id}.json").write_text(
                json.dumps({"id": service_id}), encoding="utf-8"
            )
        expert_code = (
            "def extella_system_install_smoke(__extella_install_smoke=False):\n"
            "    return {'status': 'success'}\n"
        )
        ownership = json.dumps(
            {
                "schemaVersion": 1,
                "releaseVersion": release,
                "provider": "alibaba",
                "model": "qwen3.7-max-2026-06-08",
                "wizard": "agent_user_Qwen123",
                "builder": "agent_user_Qwen456",
            }
        )
        catalog = '{"items": []}'
        account_state = {
            "schemaVersion": 1,
            "status": "installed",
            "releaseVersion": release,
            "changes": [
                {
                    "kind": "expert",
                    "identity": "extella_system_install_smoke",
                    "installed_sha256": hashlib.sha256(expert_code.encode()).hexdigest(),
                },
                {
                    "kind": "kv",
                    "identity": "apps_catalog",
                    "installed_sha256": hashlib.sha256(catalog.encode()).hexdigest(),
                },
                {
                    "kind": "kv",
                    "identity": AGENTS_KV_KEY,
                    "installed_sha256": hashlib.sha256(ownership.encode()).hexdigest(),
                },
            ],
        }
        states = {
            data / "state/client/install-state.json": {
                "schemaVersion": 1,
                "status": "installed",
                "releaseVersion": release,
                "changes": [],
            },
            data / "state/account/account-state.json": account_state,
            data / "state/doctor/latest.json": {
                "schemaVersion": 1,
                "status": "ready",
            },
        }
        for path, value in states.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(value), encoding="utf-8")
        kv = {"apps_catalog": catalog, AGENTS_KV_KEY: ownership}
        return expert_code, kv, {"HOME": str(home), "EXTELLA_DATA_ROOT": str(data)}

    @staticmethod
    def _http_get(url, origin):
        if url.endswith("/api/services"):
            services = [
                {
                    "id": service_id,
                    "status": "running",
                    "owner": service_id,
                    "port": port,
                    "pid": 1000 + index,
                }
                for index, (service_id, port) in enumerate(SERVICE_PORTS.items())
            ]
            return 200, {"Access-Control-Allow-Origin": origin}, json.dumps({"services": services}).encode()
        return 200, {}, b"<html>ready</html>"

    def test_verifies_files_account_smokes_services_and_cors(self):
        platform_info = detect_platform(system="Darwin", architecture="arm64", release="15")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            code, kv, env = self._fixture(root)
            report = verify_installed_client(
                platform_info=platform_info,
                env=env,
                account_api=VerificationAPI(code, kv),
                http_get=self._http_get,
            )
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["account"]["expertSmokes"], 1)
        self.assertEqual(report["services"]["uniquePids"], 4)

    def test_fails_when_remote_expert_differs_from_installed_contract(self):
        platform_info = detect_platform(system="Darwin", architecture="arm64", release="15")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _code, kv, env = self._fixture(root)
            with self.assertRaises(ClientVerificationError):
                verify_installed_client(
                    platform_info=platform_info,
                    env=env,
                    account_api=VerificationAPI("def changed(): pass\n", kv),
                    http_get=self._http_get,
                )

    def test_unsupported_platform_stops_before_any_probe(self):
        linux = detect_platform(system="Linux", architecture="x86_64", release="6")
        with self.assertRaises(ClientVerificationError):
            verify_installed_client(
                platform_info=linux,
                account_api=None,
                http_get=lambda *_: (_ for _ in ()).throw(AssertionError("must not probe")),
            )


if __name__ == "__main__":
    unittest.main()
