"""Read-only verification of an installed Extella Client release."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable, Mapping
import urllib.error
import urllib.request

from installer.account import (
    AGENTS_KV_KEY,
    INSTALL_SMOKE_MARKER,
    INSTALL_SMOKE_PARAM,
    QWEN_PROVIDER,
    SAFE_AGENT_ID,
    AccountAPI,
    ExtellaAPI,
    _normalise_expert,
    _canonical_expert_code,
    _response_success,
    scope_api_to_agent,
)
from runtime.extella_runtime.paths import ClientPaths, client_paths
from runtime.extella_runtime.platforms import PlatformInfo, detect_platform


SERVICE_PORTS = {
    "extella_activity_center": 8799,
    "extella_adoption_wizard": 8765,
    "extella_travel_agency": 8766,
    "extella_contract_agent": 8767,
}
UI_ENDPOINTS = {
    "activity": "http://127.0.0.1:8799/api/services",
    "wizard": "http://127.0.0.1:8765/wizard.html",
    "travel": "http://127.0.0.1:8766/onboarding.html",
    "contract": "http://127.0.0.1:8767/onboarding.html",
}
ALLOWED_ORIGIN = "https://prod.extella.ai"
HttpGet = Callable[[str, str], tuple[int, Mapping[str, str], bytes]]


class ClientVerificationError(RuntimeError):
    """A required installed-state invariant did not pass."""


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _read_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ClientVerificationError(f"{label} state is missing or invalid") from error
    if not isinstance(value, dict):
        raise ClientVerificationError(f"{label} state is missing or invalid")
    return value


def _read_state(path: Path, label: str) -> dict[str, Any]:
    value = _read_json_object(path, label)
    if value.get("status") != "installed":
        raise ClientVerificationError(f"{label} state is not installed")
    return value


def _state_chain(state: dict[str, Any]) -> list[dict[str, Any]]:
    chain: list[dict[str, Any]] = []
    current: Any = state
    for _ in range(64):
        if not isinstance(current, dict):
            break
        chain.append(current)
        current = current.get("previousState")
    if isinstance(current, dict):
        raise ClientVerificationError("installed state chain is unexpectedly deep")
    return chain


def _owned_changes(state: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    selected: dict[tuple[str, str], dict[str, Any]] = {}
    for current in _state_chain(state):
        changes = current.get("changes")
        if not isinstance(changes, list):
            raise ClientVerificationError("account state changes are invalid")
        for change in changes:
            if not isinstance(change, dict):
                continue
            kind = str(change.get("kind") or "")
            identity = str(change.get("identity") or "")
            if kind in {"expert", "kv", "agent"} and identity:
                selected.setdefault((kind, identity), change)
    return selected


def _default_http_get(url: str, origin: str) -> tuple[int, Mapping[str, str], bytes]:
    request = urllib.request.Request(url, headers={"Origin": origin})
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            return int(response.status), dict(response.headers.items()), response.read(2 * 1024 * 1024)
    except (urllib.error.URLError, OSError, ValueError) as error:
        raise ClientVerificationError("required localhost endpoint is unavailable") from error


def _get_kv(api: AccountAPI, key: str) -> str:
    response = api.post("/api/kv/get", {"key": key, "global": True})
    value = response.get("value")
    if not isinstance(value, str):
        raise ClientVerificationError(f"required account KV is missing: {key}")
    return value


def _verify_local_files(paths: ClientPaths, platform_info: PlatformInfo) -> dict[str, int]:
    required = (
        paths.toolbar_root / "toolbar.js",
        paths.data_root / "installer" / "client_install.py",
        paths.data_root / "installer" / "client_uninstall.py",
        paths.data_root / "installer" / "client_verify.py",
        paths.data_root / "installer" / "external_matrix.py",
        paths.data_root / "activity-center" / "server.py",
        paths.wizard_root / "server.py",
        paths.wizard_root / "wizard.html",
        paths.plugins_root / "extella_travel_agency" / "server.py",
        paths.plugins_root / "extella_contract_agent" / "server.py",
        paths.wizard_root / "config.json",
    )
    missing = [path.name for path in required if not path.is_file()]
    if missing:
        raise ClientVerificationError(f"required installed files are missing: {', '.join(missing[:5])}")
    registries = list((paths.plugins_root / "_registry").glob("*.json"))
    registry_ids: set[str] = set()
    for path in registries:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ClientVerificationError("a local plugin registry is invalid") from error
        if isinstance(value, dict) and isinstance(value.get("id"), str):
            registry_ids.add(value["id"])
    expected = set(SERVICE_PORTS) - {"extella_activity_center"}
    if registry_ids != expected:
        raise ClientVerificationError("local service registry does not match the release contract")
    config = paths.wizard_root / "config.json"
    if platform_info.system != "Windows" and config.stat().st_mode & 0o077:
        raise ClientVerificationError("credential file permissions are not restricted")
    return {"files": len(required), "registries": len(registry_ids)}


def _verify_services(http_get: HttpGet) -> dict[str, int]:
    responses: dict[str, tuple[int, Mapping[str, str], bytes]] = {}
    for name, url in UI_ENDPOINTS.items():
        status, headers, body = http_get(url, ALLOWED_ORIGIN)
        if not 200 <= status < 400 or not body:
            raise ClientVerificationError(f"required local UI is unhealthy: {name}")
        responses[name] = (status, headers, body)
    activity_headers = {str(key).lower(): str(value) for key, value in responses["activity"][1].items()}
    if activity_headers.get("access-control-allow-origin") != ALLOWED_ORIGIN:
        raise ClientVerificationError("Activity Center CORS contract did not pass")
    try:
        payload = json.loads(responses["activity"][2].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ClientVerificationError("Activity Center returned invalid service state") from error
    services = payload.get("services") if isinstance(payload, dict) else None
    if not isinstance(services, list):
        raise ClientVerificationError("Activity Center returned no service inventory")
    indexed = {
        str(service.get("id")): service
        for service in services
        if isinstance(service, dict) and service.get("id") in SERVICE_PORTS
    }
    if set(indexed) != set(SERVICE_PORTS):
        raise ClientVerificationError("Activity Center service inventory is incomplete")
    pids: list[int] = []
    for service_id, port in SERVICE_PORTS.items():
        service = indexed[service_id]
        pid = service.get("pid")
        if (
            service.get("status") != "running"
            or service.get("owner") != service_id
            or service.get("port") != port
            or not isinstance(pid, int)
            or pid <= 1
        ):
            raise ClientVerificationError(f"service ownership or health failed: {service_id}")
        pids.append(pid)
    if len(pids) != len(set(pids)):
        raise ClientVerificationError("multiple services report the same owned PID")
    return {"services": len(indexed), "uniquePids": len(set(pids)), "uis": len(responses)}


def _verify_account(
    api: AccountAPI,
    state: dict[str, Any],
    *,
    release_version: str,
) -> dict[str, int]:
    validation = api.post("/api/token/validate", {})
    if not _response_success(validation):
        raise ClientVerificationError("Extella token validation failed")
    changes = _owned_changes(state)
    experts = sorted(identity for kind, identity in changes if kind == "expert")
    kv_keys = sorted(identity for kind, identity in changes if kind == "kv")
    if not experts or not kv_keys:
        raise ClientVerificationError("account installation inventory is empty")
    for name in experts:
        response = api.post("/api/expert/get", {"name": name, "global": True})
        expert = _normalise_expert(response)
        expected = str(changes[("expert", name)].get("installed_sha256") or "")
        if (
            expert is None
            or expert.get("global") is not True
            or _sha256_bytes(_canonical_expert_code(expert["code"]).encode("utf-8")) != expected
        ):
            raise ClientVerificationError(f"installed expert differs from release state: {name}")
        smoke = api.post(
            "/api/expert/run",
            {
                "expert_name": name,
                "params": {INSTALL_SMOKE_PARAM: True},
                "global": True,
            },
            timeout=180,
        )
        result: Any = smoke.get("result", smoke)
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except json.JSONDecodeError:
                result = None
        if (
            not _response_success(smoke)
            or not isinstance(result, dict)
            or result.get("installSmoke") != name
            or result.get("contract") != INSTALL_SMOKE_MARKER
        ):
            raise ClientVerificationError(f"installed expert smoke failed: {name}")
    for key in kv_keys:
        value = _get_kv(api, key)
        expected = str(changes[("kv", key)].get("installed_sha256") or "")
        if _sha256_bytes(value.encode("utf-8")) != expected:
            raise ClientVerificationError(f"installed account KV differs from release state: {key}")
    ownership = json.loads(_get_kv(api, AGENTS_KV_KEY))
    if not isinstance(ownership, dict) or ownership.get("releaseVersion") != release_version:
        raise ClientVerificationError("current-account agent ownership is invalid")
    agent_ids = [ownership.get("wizard"), ownership.get("builder")]
    if any(not isinstance(agent_id, str) or not SAFE_AGENT_ID.fullmatch(agent_id) for agent_id in agent_ids):
        raise ClientVerificationError("current-account Qwen agent identities are invalid")
    unique_agent_ids = list(dict.fromkeys(agent_ids))
    if not 1 <= len(unique_agent_ids) <= 2:
        raise ClientVerificationError("current-account Qwen agent identities are invalid")
    for agent_id in unique_agent_ids:
        response = api.post("/api/agent/get", {"agent_id": agent_id})
        agent = response.get("result") if isinstance(response.get("result"), dict) else response
        if (
            str(agent.get("provider") or "").lower() != QWEN_PROVIDER
            or not str(agent.get("model") or "").lower().startswith("qwen3.7")
        ):
            raise ClientVerificationError("current-account agent is not the required Qwen model")
        smoke = api.post(
            "/api/agent/run",
            {
                "agent_id": agent_id,
                "input": "Reply with exactly: EXTELLA_READY",
                "store": False,
                "run_timeout": 90,
            },
            timeout=140,
        )
        if not _response_success(smoke) or "EXTELLA_READY" not in json.dumps(smoke, ensure_ascii=False):
            raise ClientVerificationError("current-account Qwen agent smoke failed")
    return {
        "experts": len(experts),
        "expertSmokes": len(experts),
        "kv": len(kv_keys),
        "agents": len(unique_agent_ids),
    }


def verify_installed_client(
    *,
    token: str = "",
    api_base: str = "https://api.extella.ai",
    platform_info: PlatformInfo | None = None,
    env: Mapping[str, str] | None = None,
    account_api: AccountAPI | None = None,
    http_get: HttpGet | None = None,
) -> dict[str, Any]:
    """Verify current files, account resources, localhost UIs, and owned processes."""

    platform_info = platform_info or detect_platform()
    if not platform_info.supported:
        raise ClientVerificationError(platform_info.reason or "unsupported platform")
    environment = dict(os.environ if env is None else env)
    paths = client_paths(platform_info=platform_info, env=environment)
    local_state = _read_state(paths.state_root / "client" / "install-state.json", "local")
    account_state = _read_state(paths.state_root / "account" / "account-state.json", "account")
    release_version = str(local_state.get("releaseVersion") or "")
    if not release_version or account_state.get("releaseVersion") != release_version:
        raise ClientVerificationError("local and account release versions differ")
    doctor = _read_json_object(paths.state_root / "doctor" / "latest.json", "Doctor")
    if doctor.get("status") != "ready":
        raise ClientVerificationError("Computer Doctor report is not ready")
    api = account_api or ExtellaAPI(token, api_base=api_base)
    wizard_config = _read_json_object(paths.wizard_root / "config.json", "Wizard config")
    wizard_agent = str(wizard_config.get("agent_id") or "")
    if not SAFE_AGENT_ID.fullmatch(wizard_agent):
        raise ClientVerificationError("Wizard config has no current-account agent")
    scope_api_to_agent(api, wizard_agent)
    local = _verify_local_files(paths, platform_info)
    services = _verify_services(http_get or _default_http_get)
    account = _verify_account(api, account_state, release_version=release_version)
    return {
        "schemaVersion": 1,
        "status": "passed",
        "releaseVersion": release_version,
        "platform": platform_info.key,
        "doctor": {"status": doctor.get("status")},
        "local": local,
        "services": services,
        "account": account,
    }
