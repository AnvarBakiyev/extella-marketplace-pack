"""Transactional lifecycle for release-gated supported-on-demand plugins."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Iterable, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

from installer.account import (
    AccountInstaller,
    ExtellaAPI,
    discover_bundle_experts,
    repair_interrupted_account,
    uninstall_account_resources,
)
from installer.bundle import VerifiedBundle, verify_bundle
from installer.client import _restrict_secret_file, _runtime_environment
from runtime.extella_runtime.paths import ClientPaths, client_paths
from runtime.extella_runtime.platforms import PlatformInfo, detect_platform
from runtime.extella_runtime.processes import ProcessSupervisor, RuntimeSpec
from runtime.extella_runtime.transaction import (
    InstallTransaction,
    InstallationError,
    uninstall_from_state,
)


SUPPORTED_IDS = {
    "extella_adoption_wizard",
    "extella_contract_agent",
    "extella_travel_agency",
}
PLUGIN_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{1,79}$")
MAX_UI_SMOKE_BYTES = 64 * 1024


class PluginLifecycleError(InstallationError):
    """A supported plugin could not complete its declared lifecycle."""


def _package_root(paths: ClientPaths) -> Path:
    return paths.data_root / "packages" / "current"


def _load_manifest(
    package_root: Path,
    plugin_id: str,
    platform_info: PlatformInfo,
) -> tuple[dict[str, Any], VerifiedBundle]:
    if plugin_id not in SUPPORTED_IDS or not PLUGIN_ID.fullmatch(plugin_id):
        raise PluginLifecycleError("plugin is not in the supported on-demand allowlist")
    verified = verify_bundle(package_root)
    path = package_root / "payload/marketplace/release/plugins" / f"{plugin_id}.json"
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise PluginLifecycleError("supported plugin manifest is unavailable") from error
    if not isinstance(manifest, dict) or manifest.get("id") != plugin_id:
        raise PluginLifecycleError("supported plugin manifest identity mismatch")
    if manifest.get("classification") != "supported_on_demand":
        raise PluginLifecycleError("plugin is not classified as supported on-demand")
    if platform_info.key not in set(manifest.get("supportedPlatforms") or []):
        raise PluginLifecycleError("plugin does not support this platform")
    if (manifest.get("install") or {}).get("strategy") != "on_demand":
        raise PluginLifecycleError("plugin has no on-demand install contract")
    return manifest, verified


def _read_account_config(paths: ClientPaths, platform_info: PlatformInfo) -> dict[str, str]:
    target = paths.wizard_root / "config.json"
    try:
        config = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise PluginLifecycleError("Extella account configuration is missing; run Repair") from error
    if not isinstance(config, dict):
        raise PluginLifecycleError("Extella account configuration is invalid; run Repair")
    token = str(config.get("auth_token") or "").strip()
    agent_id = str(config.get("agent_id") or "").strip()
    api_base = str(config.get("api_base") or "https://api.extella.ai").strip()
    if len(token) < 20 or not re.fullmatch(r"agent_[A-Za-z0-9_-]{6,128}", agent_id):
        raise PluginLifecycleError("Extella account configuration is incomplete; run Repair")
    _restrict_secret_file(target, platform_info=platform_info)
    return {"token": token, "agent_id": agent_id, "api_base": api_base}


def _source_mappings(
    package_root: Path,
    manifest: Mapping[str, Any],
    paths: ClientPaths,
) -> list[tuple[Path, Path]]:
    plugin_id = str(manifest["id"])
    mappings: list[tuple[Path, Path]] = []
    if plugin_id == "extella_adoption_wizard":
        ui = package_root / "payload/wizard/ui"
        for source in sorted(ui.glob("*"), key=lambda item: item.name):
            if source.is_file() and "__pycache__" not in source.parts:
                mappings.append((source, paths.wizard_root / source.name))
        workspace = package_root / "payload/wizard/dist/workspace"
        for source in sorted(workspace.rglob("*"), key=lambda item: item.as_posix()):
            if source.is_file() and "__pycache__" not in source.parts:
                mappings.append((source, paths.wizard_root / "workspace" / source.relative_to(workspace)))
        catalog = package_root / "payload/wizard/catalog/catalog.json"
        mappings.extend(
            (
                (catalog, paths.data_root / "wizard/catalog/catalog.json"),
                (catalog, paths.wizard_root / "catalog.json"),
            )
        )
    else:
        locator = str((manifest.get("source") or {}).get("locator") or "")
        source_root = package_root / "payload/marketplace" / locator
        target_root = paths.plugins_root / plugin_id
        if not source_root.is_dir():
            raise PluginLifecycleError("supported plugin payload is missing")
        for source in sorted(source_root.rglob("*"), key=lambda item: item.as_posix()):
            if source.is_file() and "__pycache__" not in source.parts:
                mappings.append((source, target_root / source.relative_to(source_root)))
    if not mappings or any(not source.is_file() for source, _target in mappings):
        raise PluginLifecycleError("supported plugin payload is incomplete")
    return mappings


def _runtime_spec(
    manifest: Mapping[str, Any],
    *,
    paths: ClientPaths,
    python: Path,
) -> RuntimeSpec:
    runtime = manifest.get("runtime") if isinstance(manifest.get("runtime"), dict) else {}
    ui = manifest.get("ui") if isinstance(manifest.get("ui"), dict) else {}
    artifacts = manifest.get("artifacts") if isinstance(manifest.get("artifacts"), dict) else {}
    plugin_id = str(manifest["id"])
    root = paths.wizard_root if plugin_id == "extella_adoption_wizard" else paths.plugins_root / plugin_id
    replacements = {
        "${PYTHON}": str(python),
        "${EXTELLA_DATA}": str(paths.data_root),
        "${EXTELLA_PLUGIN_ROOT}": str(paths.plugins_root),
    }
    command = []
    for raw in runtime.get("command") or []:
        value = str(raw)
        for marker, replacement in replacements.items():
            value = value.replace(marker, replacement)
        command.append(value)
    port = int((runtime.get("port") or {}).get("preferred") or 0)
    health_path = str((runtime.get("health") or {}).get("path") or "/")
    if not command or not Path(command[0]).is_absolute() or not 1024 <= port <= 65535:
        raise PluginLifecycleError("supported plugin runtime contract is invalid")
    declared_root = str(artifacts.get("installRoot") or "")
    if not declared_root:
        raise PluginLifecycleError("supported plugin install root is missing")
    return RuntimeSpec(
        runtime_id=plugin_id,
        name=str(manifest.get("name") or plugin_id),
        argv=tuple(command),
        cwd=root,
        port=port,
        health_url=f"http://127.0.0.1:{port}{health_path}",
        log_path=paths.logs_root / f"{plugin_id}.log",
        owner=str(runtime.get("owner") or plugin_id),
        autostart="controller",
    )


def _registry_payload(
    manifest: Mapping[str, Any],
    spec: RuntimeSpec,
    paths: ClientPaths,
    bundle: VerifiedBundle,
) -> dict[str, Any]:
    ui = manifest.get("ui") if isinstance(manifest.get("ui"), dict) else {}
    return {
        "schemaVersion": 1,
        "id": spec.runtime_id,
        "name": manifest.get("name") or spec.runtime_id,
        "description": manifest.get("description") or "",
        "version": manifest.get("version"),
        "releaseVersion": bundle.release_version,
        "packageRevision": bundle.packaging_repository_revision,
        "classification": "supported_on_demand",
        "source": manifest.get("source"),
        "installed": True,
        "installedByExtella": True,
        "artifacts": {
            "rootPath": str(spec.cwd),
            "stateFile": str(paths.state_root / "plugins" / spec.runtime_id / "install-state.json"),
        },
        "ui": {
            "type": "local_server",
            "port": spec.port,
            "rootPath": str(spec.cwd),
            "mainFile": str(ui.get("entrypoint") or "").lstrip("/"),
            "openInBrowser": False,
        },
        "service": {
            "argv": list(spec.argv),
            "cwd": str(spec.cwd),
            "port": spec.port,
            "healthPath": str((manifest.get("runtime") or {}).get("health", {}).get("path") or "/"),
            "owner": spec.owner,
            "autostart": "controller",
        },
    }


def _existing_registry(
    path: Path,
    plugin_id: str,
    state_file: Path,
) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise PluginLifecycleError("refusing to replace an unreadable plugin registration") from error
    if (
        not isinstance(payload, dict)
        or payload.get("id") != plugin_id
        or payload.get("installedByExtella") is not True
    ):
        raise PluginLifecycleError("refusing to replace a plugin registration not owned by Extella")
    if not state_file.is_file():
        raise PluginLifecycleError("plugin registration has no lifecycle ownership state")
    return payload


def _enable_service_autostart(
    transaction: InstallTransaction,
    paths: ClientPaths,
    plugin_id: str,
) -> str:
    state_path = paths.state_root / "services.json"
    if not state_path.is_file():
        return "service autostart is enabled by default"
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    raw_disabled = payload.get("disabled", [])
    if not isinstance(raw_disabled, list):
        raw_disabled = []
    disabled = [
        item
        for item in raw_disabled
        if isinstance(item, str) and item != plugin_id
    ]
    errors = payload.get("lastErrors")
    if not isinstance(errors, dict):
        errors = {}
    had_error = plugin_id in errors
    errors.pop(plugin_id, None)
    if disabled == raw_disabled and not had_error and isinstance(payload.get("lastErrors"), dict):
        return "service autostart was already enabled"
    payload["disabled"] = sorted(set(disabled))
    payload["lastErrors"] = errors
    transaction.atomic_write(
        (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"),
        state_path,
        mode=0o600,
    )
    return "service autostart enabled for this installation"


def _probe_ui(
    manifest: Mapping[str, Any],
    spec: RuntimeSpec,
    *,
    timeout: float,
) -> dict[str, Any]:
    ui = manifest.get("ui") if isinstance(manifest.get("ui"), dict) else {}
    entrypoint = str(ui.get("entrypoint") or "")
    if (
        ui.get("type") != "local_server"
        or ui.get("runtimeId") != spec.runtime_id
        or not entrypoint.startswith("/")
        or entrypoint.startswith("//")
    ):
        raise PluginLifecycleError("plugin UI contract is invalid")
    url = f"http://127.0.0.1:{spec.port}{entrypoint}"
    request = Request(url, headers={"Accept": "text/html"}, method="GET")
    opener = build_opener(ProxyHandler({}))
    try:
        with opener.open(request, timeout=max(1.0, min(float(timeout), 30.0))) as response:
            status = int(getattr(response, "status", response.getcode()))
            content_type = str(response.headers.get("Content-Type") or "").lower()
            body = response.read(MAX_UI_SMOKE_BYTES)
    except (HTTPError, URLError, OSError, TimeoutError, ValueError) as error:
        raise PluginLifecycleError("plugin UI did not open") from error
    if not 200 <= status < 300 or "text/html" not in content_type:
        raise PluginLifecycleError("plugin UI did not return HTML")
    if not body or b"<html" not in body.lower():
        raise PluginLifecycleError("plugin UI response is invalid")
    return {"status": "ready", "url": url, "sampleBytes": len(body)}


def _copy_files(
    transaction: InstallTransaction,
    mappings: Iterable[tuple[Path, Path]],
) -> str:
    count = 0
    for source, target in mappings:
        before = len(transaction.files)
        transaction.atomic_copy(source, target)
        if len(transaction.files) > before:
            count += 1
    return f"verified plugin files ready ({count} changed)"


def install_supported_plugin(
    plugin_id: str,
    *,
    package_root: Path | None = None,
    platform_info: PlatformInfo | None = None,
    env: Mapping[str, str] | None = None,
    account_api: Any | None = None,
    python_executable: Path | None = None,
) -> dict[str, Any]:
    platform_info = platform_info or detect_platform()
    if not platform_info.supported:
        raise PluginLifecycleError(platform_info.reason or "unsupported platform")
    environment = dict(os.environ if env is None else env)
    paths = client_paths(platform_info=platform_info, env=environment)
    package_root = (package_root or _package_root(paths)).resolve()
    manifest, verified_bundle = _load_manifest(package_root, plugin_id, platform_info)
    config = _read_account_config(paths, platform_info)
    python = (python_executable or Path(sys.executable)).resolve()
    if not python.is_file():
        raise PluginLifecycleError("managed Python runtime is unavailable; run Repair")
    local = InstallTransaction(
        release_version=str(manifest.get("version") or "unknown"),
        state_root=paths.state_root / "plugins" / plugin_id,
    )
    account: AccountInstaller | None = None
    account_prepared = False
    supervisor = ProcessSupervisor(
        state_file=paths.state_root / "processes.json",
        platform_info=platform_info,
        environment={**environment, **_runtime_environment(paths)},
    )
    spec = _runtime_spec(manifest, paths=paths, python=python)
    ui_report: dict[str, Any] = {}
    registry_path = paths.plugins_root / "_registry" / f"{plugin_id}.json"
    local_state = paths.state_root / "plugins" / plugin_id / "install-state.json"
    existing_registry = _existing_registry(registry_path, plugin_id, local_state)
    try:
        def migrate_previous_runtime() -> str:
            if not existing_registry or existing_registry.get("packageRevision") == verified_bundle.packaging_repository_revision:
                return "no previous runtime migration required"
            status = supervisor.status(spec)
            if status.get("status") == "stopped":
                return "previous runtime was already stopped"
            if not status.get("canStop"):
                raise PluginLifecycleError("refusing to replace a running plugin process without verified ownership")
            supervisor.stop(spec)
            local.register_undo(lambda: supervisor.start(spec))
            return "previous owned runtime stopped for verified upgrade"

        local.run("plugin.migration", migrate_previous_runtime)
        mappings = _source_mappings(package_root, manifest, paths)
        local.run("plugin.files", lambda: _copy_files(local, mappings))
        registry = _registry_payload(manifest, spec, paths, verified_bundle)
        local.run(
            "plugin.registry",
            lambda: (
                local.atomic_write(
                    (json.dumps(registry, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
                    registry_path,
                    mode=0o600,
                )
                and "owned plugin registration verified"
            ),
        )
        local.run(
            "plugin.autostart",
            lambda: _enable_service_autostart(local, paths, plugin_id),
        )
        account_state = paths.state_root / "account" / "plugins" / plugin_id
        api = account_api or ExtellaAPI(config["token"], api_base=config["api_base"])
        repair_interrupted_account(api, account_state / "account-state.json")
        account = AccountInstaller(
            api,
            release_version=str(manifest.get("version") or "unknown"),
            state_root=account_state,
            agent_id=config["agent_id"],
        )
        experts = discover_bundle_experts(package_root)
        contract = manifest.get("experts") if isinstance(manifest.get("experts"), dict) else {}
        required = {str(name) for name in contract.get("required") or []}
        smokes = {str(name) for name in contract.get("smoke") or []}
        account.install(
            experts,
            required=required,
            smokes=smokes,
            kv_artifacts=(),
            agent_instructions=None,
            commit=False,
        )
        account_prepared = True

        def start() -> str:
            before = supervisor.status(spec)
            status = supervisor.start(
                spec,
                timeout=float((manifest.get("runtime") or {}).get("health", {}).get("timeoutSeconds") or 30),
            )
            if before.get("status") != "running":
                local.register_undo(lambda: supervisor.stop(spec))
            if status.get("status") != "running" or not status.get("pid"):
                raise PluginLifecycleError("plugin service did not prove a healthy owned PID")
            return "plugin service passed health check"

        local.run("plugin.service", start)

        def verify_ui() -> str:
            nonlocal ui_report
            ui_report = _probe_ui(
                manifest,
                spec,
                timeout=float((manifest.get("runtime") or {}).get("health", {}).get("timeoutSeconds") or 30),
            )
            return "plugin UI entrypoint opened and returned HTML"

        local.run("plugin.ui", verify_ui)
        account_report = account.transaction.commit()
        local_report = local.commit()
    except Exception:
        if account is not None and account_prepared:
            account.transaction.rollback(failed_step="plugin.finalize")
        local.rollback(failed_step="plugin.finalize")
        raise
    return {
        "schemaVersion": 1,
        "status": "installed",
        "pluginId": plugin_id,
        "version": manifest.get("version"),
        "platform": platform_info.key,
        "service": supervisor.status(spec),
        "ui": ui_report,
        "local": {"status": local_report["status"], "steps": len(local_report["steps"])},
        "account": {"status": account_report["status"], "steps": len(account_report["steps"])},
    }


def uninstall_supported_plugin(
    plugin_id: str,
    *,
    package_root: Path | None = None,
    platform_info: PlatformInfo | None = None,
    env: Mapping[str, str] | None = None,
    account_api: Any | None = None,
    python_executable: Path | None = None,
) -> dict[str, Any]:
    platform_info = platform_info or detect_platform()
    environment = dict(os.environ if env is None else env)
    paths = client_paths(platform_info=platform_info, env=environment)
    package_root = (package_root or _package_root(paths)).resolve()
    manifest, _verified_bundle = _load_manifest(package_root, plugin_id, platform_info)
    config = _read_account_config(paths, platform_info)
    python = (python_executable or Path(sys.executable)).resolve()
    spec = _runtime_spec(manifest, paths=paths, python=python)
    registry_path = paths.plugins_root / "_registry" / f"{plugin_id}.json"
    local_state = paths.state_root / "plugins" / plugin_id / "install-state.json"
    _existing_registry(registry_path, plugin_id, local_state)
    supervisor = ProcessSupervisor(
        state_file=paths.state_root / "processes.json",
        platform_info=platform_info,
        environment={**environment, **_runtime_environment(paths)},
    )
    current = supervisor.status(spec)
    if current.get("status") != "stopped":
        if not current.get("canStop"):
            raise PluginLifecycleError("refusing to stop a process not owned by this plugin")
        supervisor.stop(spec)
    account_state = paths.state_root / "account" / "plugins" / plugin_id / "account-state.json"
    account_report: dict[str, Any] = {"status": "not_installed", "steps": []}
    if account_state.is_file():
        api = account_api or ExtellaAPI(config["token"], api_base=config["api_base"])
        account_report = uninstall_account_resources(api, account_state)
        if account_report.get("status") != "uninstalled":
            return {
                "schemaVersion": 1,
                "status": account_report.get("status") or "failed",
                "pluginId": plugin_id,
                "service": supervisor.status(spec),
                "account": account_report,
                "local": {"status": "preserved"},
            }
    local_report = (
        uninstall_from_state(local_state)
        if local_state.is_file()
        else {"status": "not_installed", "steps": []}
    )
    status = "uninstalled" if local_report.get("status") in {"uninstalled", "not_installed"} else "failed"
    return {
        "schemaVersion": 1,
        "status": status,
        "pluginId": plugin_id,
        "account": account_report,
        "local": local_report,
        "service": supervisor.status(spec),
    }


def list_supported_plugins(
    *,
    package_root: Path | None = None,
    platform_info: PlatformInfo | None = None,
    env: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    platform_info = platform_info or detect_platform()
    environment = dict(os.environ if env is None else env)
    paths = client_paths(platform_info=platform_info, env=environment)
    package_root = (package_root or _package_root(paths)).resolve()
    plugins: list[dict[str, Any]] = []
    for plugin_id in sorted(SUPPORTED_IDS):
        try:
            manifest, verified_bundle = _load_manifest(package_root, plugin_id, platform_info)
        except PluginLifecycleError:
            continue
        state = paths.state_root / "plugins" / plugin_id / "install-state.json"
        registry = paths.plugins_root / "_registry" / f"{plugin_id}.json"
        registration: dict[str, Any] = {}
        try:
            candidate = json.loads(registry.read_text(encoding="utf-8"))
            if isinstance(candidate, dict):
                registration = candidate
        except (OSError, ValueError):
            pass
        installed_files = state.is_file() and registry.is_file()
        has_install_artifacts = state.is_file() or registry.is_file()
        current_package = (
            registration.get("id") == plugin_id
            and registration.get("installedByExtella") is True
            and registration.get("releaseVersion") == verified_bundle.release_version
            and registration.get("packageRevision") == verified_bundle.packaging_repository_revision
        )
        plugins.append(
            {
                "id": plugin_id,
                "name": manifest.get("name") or plugin_id,
                "description": manifest.get("description") or "",
                "version": manifest.get("version"),
                "classification": "supported_on_demand",
                "installed": installed_files and current_package,
                "needsRepair": has_install_artifacts and not (installed_files and current_package),
            }
        )
    return plugins
