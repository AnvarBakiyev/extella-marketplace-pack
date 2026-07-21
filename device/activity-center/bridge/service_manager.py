"""Discover and safely control Extella-owned localhost services.

The Activity Center exposes only registry metadata and verified process
identities. Raw argv, absolute roots, and secrets never leave this module.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sys
import threading
from typing import Any

from extella_runtime.paths import client_paths
from extella_runtime.processes import (
    ProcessControlError,
    ProcessSupervisor,
    RuntimeSpec,
)
from extella_runtime.platforms import detect_platform


_PATHS = client_paths(platform_info=detect_platform())
REGISTRY_DIR = Path(
    os.environ.get("EXTELLA_PLUGIN_REGISTRY", str(_PATHS.plugins_root / "_registry"))
)
STATE_FILE = Path(
    os.environ.get("EXTELLA_SERVICE_STATE", str(_PATHS.state_root / "services.json"))
)
PROCESS_STATE_FILE = Path(
    os.environ.get("EXTELLA_PROCESS_STATE", str(_PATHS.state_root / "processes.json"))
)
_SERVICE_ID = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
_CONTROL_LOCK = threading.RLock()
_SUPERVISOR = ProcessSupervisor(state_file=PROCESS_STATE_FILE)


class ServiceError(RuntimeError):
    """A user-facing service control error with an HTTP status."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def _read_state(path: Path = STATE_FILE) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"disabled": [], "lastErrors": {}}
    if not isinstance(payload, dict):
        return {"disabled": [], "lastErrors": {}}
    disabled = [
        item
        for item in payload.get("disabled", [])
        if isinstance(item, str) and _SERVICE_ID.fullmatch(item)
    ]
    errors = {
        key: str(value)[:240]
        for key, value in (payload.get("lastErrors") or {}).items()
        if isinstance(key, str) and _SERVICE_ID.fullmatch(key)
    }
    return {"disabled": sorted(set(disabled)), "lastErrors": errors}


def _write_state(payload: dict[str, Any], path: Path = STATE_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _expanded_root(value: Any) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    expanded = os.path.expandvars(os.path.expanduser(value))
    return Path(expanded).resolve()


def _expand_argv(values: Any, root: Path | None) -> tuple[str, ...]:
    if not isinstance(values, list) or not values:
        return ()
    replacements = {
        "${PYTHON}": sys.executable,
        "${EXTELLA_DATA}": str(_PATHS.data_root),
        "${EXTELLA_PLUGIN_ROOT}": str(_PATHS.plugins_root),
        "${ROOT}": str(root or ""),
    }
    argv: list[str] = []
    for index, raw in enumerate(values):
        if not isinstance(raw, str) or not raw:
            return ()
        value = raw
        for marker, replacement in replacements.items():
            value = value.replace(marker, replacement)
        value = os.path.expandvars(os.path.expanduser(value))
        if index == 0 and not Path(value).is_absolute():
            return ()
        if index > 0 and root and not Path(value).is_absolute():
            candidate = root / value
            if candidate.exists():
                value = str(candidate)
        argv.append(value)
    return tuple(argv)


def _runtime_spec(
    manifest: dict[str, Any],
    registry_file: Path,
    root: Path | None,
    port: int,
) -> tuple[RuntimeSpec | None, str]:
    service = manifest.get("service") if isinstance(manifest.get("service"), dict) else {}
    argv = _expand_argv(service.get("argv") or service.get("launchArgv"), root)
    static_fallback = not argv and root is not None and not service.get("launchCmd")
    if static_fallback:
        argv = (
            sys.executable,
            "-m",
            "http.server",
            str(port),
            "--bind",
            "127.0.0.1",
        )
    if not argv:
        reason = (
            "Legacy shell launch commands are visible but cannot be controlled safely."
            if service.get("launchCmd")
            else "The registry does not contain a safe argv launch contract."
        )
        return None, reason
    if root is None:
        return None, "The registry does not contain a runtime working directory."
    health_path = str(service.get("healthPath") or "/").strip()
    if not health_path.startswith("/"):
        health_path = "/" + health_path
    runtime_id = str(manifest.get("id") or registry_file.stem)
    owner = str(service.get("owner") or runtime_id)
    autostart = str(service.get("autostart") or "controller")
    return (
        RuntimeSpec(
            runtime_id=runtime_id,
            name=str(manifest.get("name") or manifest.get("title") or runtime_id),
            argv=argv,
            cwd=root,
            port=port,
            health_url=f"http://127.0.0.1:{port}{health_path}",
            log_path=_PATHS.logs_root / f"{runtime_id}.log",
            owner=owner,
            autostart=autostart,
        ),
        "",
    )


def registry_services(registry_dir: Path = REGISTRY_DIR) -> list[dict[str, Any]]:
    services: list[dict[str, Any]] = []
    if not registry_dir.is_dir():
        return services
    for path in sorted(registry_dir.glob("*.json")):
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(manifest, dict):
            continue
        ui = manifest.get("ui") if isinstance(manifest.get("ui"), dict) else {}
        service = manifest.get("service") if isinstance(manifest.get("service"), dict) else {}
        if ui.get("type") != "local_server" and not (
            service.get("argv") or service.get("launchArgv") or service.get("launchCmd")
        ):
            continue
        service_id = str(manifest.get("id") or path.stem)
        if not _SERVICE_ID.fullmatch(service_id):
            continue
        try:
            port = int(ui.get("port") or service.get("port"))
        except (TypeError, ValueError):
            continue
        if not 0 < port < 65536:
            continue
        root = _expanded_root(ui.get("rootPath") or service.get("cwd"))
        description = str(
            manifest.get("purpose")
            or manifest.get("tagline")
            or manifest.get("description")
            or ""
        )
        if len(description) > 220:
            description = description[:217].rstrip() + "…"
        spec, blocked = _runtime_spec(manifest, path, root, port)
        services.append(
            {
                "id": service_id,
                "name": str(manifest.get("name") or manifest.get("title") or service_id),
                "description": description,
                "port": port,
                "mainFile": str(ui.get("mainFile") or "").lstrip("/"),
                "root": root,
                "registryFile": path.name,
                "runtimeSpec": spec,
                "blockedReason": blocked,
            }
        )
    return services


def _public_service(
    service: dict[str, Any],
    state: dict[str, Any],
    persist_mapping: bool = True,
    supervisor: ProcessSupervisor = _SUPERVISOR,
) -> dict[str, Any]:
    del persist_mapping
    spec = service.get("runtimeSpec")
    disabled = service["id"] in set(state.get("disabled", []))
    if isinstance(spec, RuntimeSpec):
        runtime = supervisor.status(spec)
    else:
        runtime = {
            "status": "stopped",
            "pid": None,
            "ppid": None,
            "process": None,
            "owner": service["id"],
            "startedAt": None,
            "autostart": "none",
            "errorClass": "unsafe_launch_contract",
            "canStart": False,
            "canStop": False,
            "healthy": False,
        }
    processes = []
    if runtime.get("pid"):
        processes.append(
            {
                "pid": runtime["pid"],
                "ppid": runtime.get("ppid") or 0,
                "process": runtime.get("process") or "process",
                "owned": True,
            }
        )
    blocked = service.get("blockedReason") or ""
    if runtime.get("errorClass") == "port_occupied_by_unowned_process":
        blocked = "The port is occupied by a process whose Extella ownership is not confirmed."
    elif runtime.get("errorClass") == "health_check_failed":
        blocked = "The owned process is running but its health check is failing."
    project = service.get("root").name if service.get("root") else ""
    main_file = service.get("mainFile")
    url = f"http://localhost:{service['port']}"
    if main_file:
        url += "/" + main_file
    return {
        "id": service["id"],
        "name": service["name"],
        "description": service["description"],
        "status": runtime["status"],
        "desired": "off" if disabled else "on",
        "pid": runtime.get("pid"),
        "port": service["port"],
        "url": url,
        "source": f"Extella registry · {service['registryFile']}",
        "project": project,
        "owner": runtime.get("owner") or service["id"],
        "startedAt": runtime.get("startedAt"),
        "autostart": runtime.get("autostart") or "none",
        "lastError": state.get("lastErrors", {}).get(service["id"]) or blocked,
        "processes": processes,
        "canStop": bool(runtime.get("canStop")),
        "canStart": bool(runtime.get("canStart") and isinstance(spec, RuntimeSpec)),
        "canRestart": bool(runtime.get("canStop") and isinstance(spec, RuntimeSpec)),
        "controlBlockedReason": blocked,
    }


def list_services() -> list[dict[str, Any]]:
    state = _read_state()
    return [_public_service(service, state) for service in registry_services()]


def start_desired_services() -> dict[str, Any]:
    """Start each enabled registry runtime once under verified ownership."""

    with _CONTROL_LOCK:
        state = _read_state()
        disabled = set(state.get("disabled", []))
        started: list[str] = []
        failed: list[dict[str, str]] = []
        for service in registry_services():
            service_id = service["id"]
            spec = service.get("runtimeSpec")
            if service_id in disabled or not isinstance(spec, RuntimeSpec):
                continue
            try:
                _SUPERVISOR.start(spec)
                started.append(service_id)
                state.setdefault("lastErrors", {}).pop(service_id, None)
            except ProcessControlError as error:
                error_class = type(error).__name__
                state.setdefault("lastErrors", {})[service_id] = str(error)[:240]
                failed.append({"id": service_id, "errorClass": error_class})
        _write_state(state)
        return {"started": started, "failed": failed}


def _service_by_id(service_id: str) -> dict[str, Any]:
    if not _SERVICE_ID.fullmatch(service_id):
        raise ServiceError("Invalid service identifier.", 400)
    for service in registry_services():
        if service["id"] == service_id:
            return service
    raise ServiceError("Service was not found in the Extella registry.", 404)


def control_service(service_id: str, action: str) -> dict[str, Any]:
    if action not in {"start", "stop", "restart"}:
        raise ServiceError("Unknown service action.", 400)
    with _CONTROL_LOCK:
        service = _service_by_id(service_id)
        state = _read_state()
        spec = service.get("runtimeSpec")
        if not isinstance(spec, RuntimeSpec):
            raise ServiceError(service.get("blockedReason") or "Safe launch contract is missing.", 409)
        disabled = set(state.get("disabled", []))
        try:
            if action == "stop":
                preview = _public_service(service, state, persist_mapping=False)
                if preview["status"] != "stopped" and not preview["canStop"]:
                    raise ServiceError(preview["controlBlockedReason"], 409)
                _SUPERVISOR.stop(spec)
                disabled.add(service_id)
            elif action == "restart":
                _SUPERVISOR.restart(spec)
                disabled.discard(service_id)
            else:
                _SUPERVISOR.start(spec)
                disabled.discard(service_id)
        except ProcessControlError as error:
            state.setdefault("lastErrors", {})[service_id] = str(error)[:240]
            _write_state(state)
            raise ServiceError(str(error), 409) from error
        state["disabled"] = sorted(disabled)
        state.setdefault("lastErrors", {}).pop(service_id, None)
        _write_state(state)
        return _public_service(service, state)
