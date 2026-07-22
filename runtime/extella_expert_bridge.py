"""Small stable bridge imported by device-side Extella experts.

The client installer makes this module importable by the listener runtime. The
dependency implementation remains in one place instead of being copied into
every expert.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
from typing import Any
import urllib.request

try:
    from extella_runtime.ensure_tool import TOOL_SPECS, ensure_tool
    from extella_runtime.paths import client_paths
    from extella_runtime.processes import ProcessSupervisor, RuntimeSpec
except ModuleNotFoundError:  # repository tests import this file as runtime.extella_expert_bridge
    from runtime.extella_runtime.ensure_tool import TOOL_SPECS, ensure_tool
    from runtime.extella_runtime.paths import client_paths
    from runtime.extella_runtime.processes import ProcessSupervisor, RuntimeSpec


def ensure(name: str, *, repair: bool = False) -> dict[str, Any]:
    return ensure_tool(name, allow_install=repair).to_dict()


def known_tools() -> list[str]:
    """Return the centrally supported dependency identifiers."""

    return sorted(TOOL_SPECS)


def path_or_error(name: str, *, repair: bool = False) -> tuple[str | None, dict[str, Any]]:
    result = ensure(name, repair=repair)
    path = result.get("path") if result.get("ready") else None
    return path, result


def locations() -> dict[str, str]:
    """Return platform-native Extella locations without account identifiers."""

    paths = client_paths()
    values = paths.to_dict()
    values.update(
        {
            "apps_root": str(paths.data_root / "apps"),
            "knowledge_root": str(paths.data_root / "knowledge"),
            "mcp_root": str(paths.data_root / "mcp"),
            "user_files_root": str(paths.data_root / "files"),
            "plugin_registry": str(paths.plugins_root / "_registry"),
            "account_config": str(paths.wizard_root / "config.json"),
            "workspace_root": str(paths.wizard_root / "workspace"),
            "wizard_data_root": str(paths.wizard_root.parent),
            "sessions_root": str(paths.wizard_root.parent / "sessions"),
            "published_root": str(paths.wizard_root.parent / "published"),
            "vault_key": str(paths.wizard_root / "vault.key"),
            "reports_root": str(paths.data_root / "files" / "reports"),
        }
    )
    return values


def account_config() -> dict[str, Any]:
    """Read current-device account config from its native private path."""

    path = Path(locations()["account_config"])
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def resolve_pinokio_recipe(root: str, entry: str, *, fixed_port: int | None = None) -> dict[str, Any]:
    """Resolve a third-party Pinokio recipe in the bundled restricted JS sandbox."""

    node, state = path_or_error("node", repair=True)
    if not node:
        return {"status": "error", "message": state.get("message") or "Node.js unavailable"}
    directory = Path(root).resolve()
    script = Path(__file__).with_name("pinokio_recipe_resolver.js")
    target = (directory / entry).resolve()
    if not directory.is_dir() or directory not in target.parents or not target.is_file():
        return {"status": "error", "message": "recipe entry is outside the installed application"}
    try:
        result = subprocess.run(
            [node, str(script), str(directory), entry, "", "", str(fixed_port or "")],
            capture_output=True, text=True, timeout=120, check=False, shell=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return {"status": "error", "message": f"recipe resolver failed: {type(error).__name__}"}
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"status": "error", "message": "recipe resolver returned invalid JSON"}
    if result.returncode != 0 or not isinstance(payload, dict):
        return {"status": "error", "message": "recipe resolver rejected the source"}
    return payload


def service_control(
    action: str,
    *,
    runtime_id: str,
    name: str,
    argv: list[str] | tuple[str, ...],
    cwd: str,
    port: int,
    health_url: str,
    owner: str = "extella_plugin_runtime",
    autostart: str = "disabled",
    timeout: float = 30.0,
    environment: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Control a local service through the ownership-safe shared supervisor."""

    if action not in {"status", "start", "stop", "restart"}:
        raise ValueError("unsupported service action")
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{1,79}", runtime_id):
        raise ValueError("invalid runtime_id")
    if not argv or not Path(argv[0]).is_absolute():
        raise ValueError("service executable must be absolute")
    if not 0 < int(port) < 65536:
        raise ValueError("invalid service port")
    paths = client_paths()
    spec = RuntimeSpec(
        runtime_id=runtime_id,
        name=name,
        argv=tuple(str(item) for item in argv),
        cwd=Path(cwd),
        port=int(port),
        health_url=health_url,
        log_path=paths.logs_root / "services" / f"{runtime_id}.log",
        owner=owner,
        autostart=autostart,
    )
    supervisor = ProcessSupervisor(
        state_file=paths.state_root / "processes.json",
        environment=environment,
    )
    if action in {"start", "restart"}:
        return getattr(supervisor, action)(spec, timeout=max(1.0, min(float(timeout), 300.0)))
    return getattr(supervisor, action)(spec)


def activity_services() -> dict[str, Any]:
    """Read the local Activity Center's public service view."""

    with urllib.request.urlopen("http://127.0.0.1:8799/api/services", timeout=5) as opened:
        payload = json.load(opened)
    if not isinstance(payload, dict) or payload.get("status") != "ok":
        raise RuntimeError("Activity Center returned an invalid service document")
    return payload


def activity_health() -> dict[str, Any]:
    """Read the controller health view, including read-only Desktop listeners."""

    with urllib.request.urlopen("http://127.0.0.1:8799/api/health", timeout=5) as opened:
        payload = json.load(opened)
    if not isinstance(payload, dict) or payload.get("status") != "ok":
        raise RuntimeError("Activity Center returned an invalid health document")
    return payload


def activity_service_control(service_id: str, action: str) -> dict[str, Any]:
    """Ask the one system controller to change a registered service state."""

    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", service_id):
        raise ValueError("invalid Activity Center service id")
    if action not in {"start", "stop", "restart"}:
        raise ValueError("invalid Activity Center action")
    overview = activity_services()
    token = str(overview.get("controlToken") or "")
    if not token:
        raise RuntimeError("Activity Center control token is unavailable")
    request = urllib.request.Request(
        f"http://127.0.0.1:8799/api/services/{service_id}/{action}",
        data=b"{}",
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Origin": "http://127.0.0.1:8799",
            "X-Extella-Control": token,
        },
    )
    with urllib.request.urlopen(request, timeout=60) as opened:
        payload = json.load(opened)
    if not isinstance(payload, dict) or payload.get("status") != "ok":
        raise RuntimeError("Activity Center rejected service control")
    service = payload.get("service")
    return service if isinstance(service, dict) else {}


_PLUGIN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,119}")
_SENSITIVE_FIELD = re.compile(r"(?:token|secret|password|passwd|api[_-]?key)", re.IGNORECASE)


def _safe_manifest(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _safe_manifest(item)
            for key, item in value.items()
            if not _SENSITIVE_FIELD.search(str(key))
        }
    if isinstance(value, list):
        return [_safe_manifest(item) for item in value]
    return value


def _registry_entries(only_id: str = "") -> list[tuple[Path, dict[str, Any]]]:
    if only_id and (not _PLUGIN_ID.fullmatch(only_id) or ".." in only_id.split("/")):
        raise ValueError("invalid plugin id")
    registry = Path(locations()["plugin_registry"])
    entries: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(registry.glob("*.json"), key=lambda item: item.name)[:1000]:
        try:
            resolved = path.resolve(strict=True)
            if resolved.parent != registry.resolve() or not resolved.is_file():
                continue
            payload = json.loads(resolved.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        plugin_id = str(payload.get("id") or "")
        if not _PLUGIN_ID.fullmatch(plugin_id) or (only_id and plugin_id != only_id):
            continue
        entries.append((resolved, payload))
    return entries


def plugin_registry_list(only_id: str = "") -> list[dict[str, Any]]:
    """Read native plugin registrations without exposing embedded credentials."""

    return [_safe_manifest(payload) for _path, payload in _registry_entries(only_id)]


def _is_unverified_third_party(manifest: dict[str, Any]) -> bool:
    source = manifest.get("source")
    source_text = source.lower() if isinstance(source, str) else ""
    return (
        str(manifest.get("type") or "").lower() in {"github", "huggingface"}
        or str(manifest.get("classification") or "").lower()
        in {"third-party", "third_party", "unverified"}
        or source_text.startswith(("https://github.com/", "http://github.com/", "hf:"))
    )


def plugin_registration_remove(plugin_id: str) -> dict[str, Any]:
    """Stop a registered service and remove only its registration.

    Third-party files are preserved because their data ownership is unknown.
    The Activity Center remains the only process controller.
    """

    entries = _registry_entries(plugin_id)
    removable = [(path, manifest) for path, manifest in entries if _is_unverified_third_party(manifest)]
    if entries and not removable:
        return {
            "status": "blocked",
            "pluginId": plugin_id,
            "message": "Bundled and system registrations can only be changed by the Extella installer.",
            "registrationsRemoved": 0,
            "serviceStopped": False,
            "userFilesPreserved": True,
        }
    stopped = False
    for _path, _manifest in removable:
        try:
            activity_service_control(plugin_id, "stop")
            stopped = True
        except Exception:
            pass
    removed = 0
    for path, _manifest in removable:
        try:
            path.unlink()
            removed += 1
        except OSError:
            pass
    return {
        "status": "ok",
        "pluginId": plugin_id,
        "registrationsRemoved": removed,
        "serviceStopped": stopped,
        "userFilesPreserved": True,
    }


def plugin_log_tail(plugin_id: str, limit: int = 120) -> dict[str, Any]:
    """Return a bounded, redacted tail from an owned plugin root and central log."""

    entries = _registry_entries(plugin_id)
    paths = client_paths()
    allowed_roots = (paths.plugins_root.resolve(), (paths.data_root / "apps").resolve())
    candidates: list[Path] = [paths.logs_root / "services" / f"{plugin_id}.log"]
    for _registry_path, manifest in entries:
        artifacts = manifest.get("artifacts") if isinstance(manifest.get("artifacts"), dict) else {}
        ui = manifest.get("ui") if isinstance(manifest.get("ui"), dict) else {}
        raw_root = artifacts.get("rootPath") or ui.get("rootPath")
        if not isinstance(raw_root, str) or not raw_root:
            continue
        try:
            root = Path(raw_root).resolve(strict=True)
        except OSError:
            continue
        if not any(root == allowed or allowed in root.parents for allowed in allowed_roots):
            continue
        for pattern in ("server.log", "nohup.out", "*.log", "logs/*.log"):
            candidates.extend(sorted(root.glob(pattern), key=lambda item: item.as_posix())[:2])
    collected: list[str] = []
    for path in candidates[:12]:
        try:
            if not path.is_file() or path.stat().st_size > 20 * 1024 * 1024:
                continue
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]
        except OSError:
            continue
        collected.append(f"=== {path.name} ===")
        collected.extend(lines)
    text = "\n".join(collected[-limit:])
    text = re.sub(r"(?i)(token|secret|password|api[_-]?key)(\s*[:=]\s*)\S+", r"\1\2<redacted>", text)
    return {"status": "ok", "log": text[:30000]}
