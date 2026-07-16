"""Discover and narrowly control Extella-owned localhost services.

Only local servers declared in the Extella plugin registry are visible here.
Raw launch commands are never returned by the public API. A running process is
stoppable only when its cwd or LaunchAgent identity proves that it belongs to
the declared plugin, so a different app occupying the same port is left alone.
"""

from __future__ import annotations

import json
import os
import plistlib
import re
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any


REGISTRY_DIR = Path(
    os.environ.get(
        "EXTELLA_PLUGIN_REGISTRY",
        str(Path.home() / "extella-plugins" / "_registry"),
    )
)
STATE_FILE = Path(
    os.environ.get(
        "EXTELLA_SERVICE_STATE",
        str(Path.home() / ".extella" / "activity-center" / "services.json"),
    )
)
LAUNCH_AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"
_SERVICE_ID = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
_CONTROL_LOCK = threading.Lock()
_launch_cache: tuple[float, list[dict[str, Any]]] = (0.0, [])


class ServiceError(RuntimeError):
    """A user-facing service control error with an HTTP status."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def _read_state(path: Path = STATE_FILE) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"disabled": [], "launchAgents": {}}
    if not isinstance(payload, dict):
        return {"disabled": [], "launchAgents": {}}
    disabled = [
        item
        for item in payload.get("disabled", [])
        if isinstance(item, str) and _SERVICE_ID.fullmatch(item)
    ]
    mappings = {
        key: value
        for key, value in (payload.get("launchAgents") or {}).items()
        if isinstance(key, str)
        and _SERVICE_ID.fullmatch(key)
        and isinstance(value, str)
        and value.startswith("ai.extella.")
    }
    return {"disabled": sorted(set(disabled)), "launchAgents": mappings}


def _write_state(payload: dict[str, Any], path: Path = STATE_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _expanded_root(value: Any) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return Path(os.path.expanduser(value)).resolve()


def _path_related(first: Path | None, second: Path | None) -> bool:
    if first is None or second is None:
        return False
    try:
        first.relative_to(second)
        return True
    except ValueError:
        pass
    try:
        second.relative_to(first)
        return True
    except ValueError:
        return False


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
        service = (
            manifest.get("service")
            if isinstance(manifest.get("service"), dict)
            else {}
        )
        if ui.get("type") != "local_server" and not service.get("launchCmd"):
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
        main_file = str(ui.get("mainFile") or "").lstrip("/")
        description = str(manifest.get("tagline") or manifest.get("description") or "")
        if len(description) > 220:
            description = description[:217].rstrip() + "…"
        services.append(
            {
                "id": service_id,
                "name": str(manifest.get("name") or manifest.get("title") or service_id),
                "description": description,
                "port": port,
                "mainFile": main_file,
                "root": root,
                "launchCommand": service.get("launchCmd"),
                "staticFallback": not service.get("launchCmd") and root is not None,
                "registryFile": path.name,
            }
        )
    return services


def listening_pids(port: int) -> list[int]:
    try:
        result = subprocess.run(
            ["/usr/sbin/lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    pids: set[int] = set()
    for value in result.stdout.splitlines():
        try:
            pids.add(int(value.strip()))
        except ValueError:
            continue
    return sorted(pids)


def _process_info(pid: int) -> dict[str, Any]:
    ppid = 0
    process_name = "process"
    cwd: Path | None = None
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "ppid=,comm="],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
        parts = result.stdout.strip().split(maxsplit=1)
        if parts:
            ppid = int(parts[0])
        if len(parts) > 1:
            process_name = Path(parts[1]).name or "process"
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    try:
        result = subprocess.run(
            ["/usr/sbin/lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
        for line in result.stdout.splitlines():
            if line.startswith("n") and len(line) > 1:
                cwd = Path(line[1:]).resolve()
                break
    except (OSError, subprocess.SubprocessError):
        pass
    return {"pid": pid, "ppid": ppid, "process": process_name, "cwd": cwd}


def _launch_agents() -> list[dict[str, Any]]:
    global _launch_cache
    now = time.monotonic()
    if now - _launch_cache[0] < 3 and _launch_cache[1]:
        return _launch_cache[1]
    agents: list[dict[str, Any]] = []
    domain = f"gui/{os.getuid()}"
    for path in sorted(LAUNCH_AGENTS_DIR.glob("*.plist")):
        try:
            with path.open("rb") as handle:
                payload = plistlib.load(handle)
        except (OSError, plistlib.InvalidFileException):
            continue
        label = payload.get("Label")
        if not isinstance(label, str) or not label.startswith("ai.extella."):
            continue
        pid = 0
        try:
            result = subprocess.run(
                ["launchctl", "print", f"{domain}/{label}"],
                check=False,
                capture_output=True,
                text=True,
                timeout=2,
            )
            match = re.search(r"(?m)^\s*pid = (\d+)\s*$", result.stdout)
            if match:
                pid = int(match.group(1))
        except (OSError, subprocess.SubprocessError, ValueError):
            pass
        arguments = payload.get("ProgramArguments") or []
        safe_arguments = [value for value in arguments if isinstance(value, str)]
        working_dir = payload.get("WorkingDirectory")
        agents.append(
            {
                "label": label,
                "pid": pid,
                "path": path,
                "arguments": safe_arguments,
                "workingDirectory": working_dir if isinstance(working_dir, str) else "",
            }
        )
    _launch_cache = (now, agents)
    return agents


def _agent_for_service(
    service: dict[str, Any], pids: list[int], state: dict[str, Any]
) -> dict[str, Any] | None:
    agents = _launch_agents()
    remembered = state.get("launchAgents", {}).get(service["id"])
    if remembered:
        for agent in agents:
            if agent["label"] == remembered:
                return agent
    for agent in agents:
        if agent["pid"] and agent["pid"] in pids:
            state.setdefault("launchAgents", {})[service["id"]] = agent["label"]
            return agent
    root = service.get("root")
    for agent in agents:
        candidates = [agent.get("workingDirectory") or ""] + agent.get("arguments", [])
        for candidate in candidates:
            candidate_path = _expanded_root(candidate)
            if root and candidate_path and _path_related(root, candidate_path):
                state.setdefault("launchAgents", {})[service["id"]] = agent["label"]
                return agent
    return None


def _public_service(
    service: dict[str, Any], state: dict[str, Any], persist_mapping: bool = True
) -> dict[str, Any]:
    pids = listening_pids(service["port"])
    mapping_before = dict(state.get("launchAgents", {}))
    agent = _agent_for_service(service, pids, state)
    if persist_mapping and mapping_before != state.get("launchAgents", {}):
        _write_state(state)
    process_rows: list[dict[str, Any]] = []
    for pid in pids:
        info = _process_info(pid)
        owned = bool(agent and agent.get("pid") == pid) or _path_related(
            service.get("root"), info.get("cwd")
        )
        process_rows.append(
            {
                "pid": pid,
                "ppid": info["ppid"],
                "process": info["process"],
                "owned": owned,
            }
        )
    running = bool(process_rows)
    all_owned = running and all(row["owned"] for row in process_rows)
    disabled = service["id"] in set(state.get("disabled", []))
    launchable = bool(agent or service.get("launchCommand") or service.get("staticFallback"))
    source = (
        f"LaunchAgent · {agent['label']}"
        if agent
        else f"Реестр Extella · {service['registryFile']}"
    )
    main_file = service.get("mainFile")
    url = f"http://localhost:{service['port']}"
    if main_file:
        url += "/" + main_file
    blocked_reason = ""
    if running and not all_owned:
        blocked_reason = "Порт занят процессом, принадлежность которого Extella не подтверждена."
    elif not running and not launchable:
        blocked_reason = "В реестре нет команды запуска."
    return {
        "id": service["id"],
        "name": service["name"],
        "description": service["description"],
        "status": "running" if running else "stopped",
        "desired": "off" if disabled else "on",
        "port": service["port"],
        "url": url,
        "source": source,
        "project": service["root"].name if service.get("root") else "",
        "processes": process_rows,
        "canStop": bool(running and all_owned),
        "canStart": bool(not running and launchable),
        "controlBlockedReason": blocked_reason,
    }


def list_services() -> list[dict[str, Any]]:
    state = _read_state()
    return [_public_service(service, state) for service in registry_services()]


def _service_by_id(service_id: str) -> dict[str, Any]:
    if not _SERVICE_ID.fullmatch(service_id):
        raise ServiceError("Некорректный идентификатор сервиса.", 400)
    for service in registry_services():
        if service["id"] == service_id:
            return service
    raise ServiceError("Сервис не найден в реестре Extella.", 404)


def _launchctl(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["launchctl", *arguments],
            check=check,
            capture_output=True,
            text=True,
            timeout=8,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise ServiceError("Не удалось изменить состояние LaunchAgent.", 502) from error


def _wait_for_port(port: int, running: bool, timeout: float = 6.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if bool(listening_pids(port)) is running:
            return True
        time.sleep(0.15)
    return bool(listening_pids(port)) is running


def _start_service(service: dict[str, Any], state: dict[str, Any]) -> None:
    current_pids = listening_pids(service["port"])
    agent = _agent_for_service(service, current_pids, state)
    domain = f"gui/{os.getuid()}"
    if agent:
        _launchctl("enable", f"{domain}/{agent['label']}", check=False)
        loaded = _launchctl("print", f"{domain}/{agent['label']}", check=False)
        if loaded.returncode == 0:
            _launchctl("kickstart", "-k", f"{domain}/{agent['label']}")
        else:
            _launchctl("bootstrap", domain, str(agent["path"]))
    elif service.get("launchCommand"):
        env = dict(os.environ)
        env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:" + env.get(
            "PATH", ""
        )
        cwd = str(service.get("root") or Path.home())
        try:
            subprocess.Popen(
                ["/bin/zsh", "-lc", str(service["launchCommand"])],
                cwd=cwd,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError as error:
            raise ServiceError("Команда запуска не выполнилась.", 502) from error
    elif service.get("staticFallback"):
        try:
            subprocess.Popen(
                [sys.executable, "-m", "http.server", str(service["port"])],
                cwd=str(service["root"]),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError as error:
            raise ServiceError("Статический сервер не запустился.", 502) from error
    else:
        raise ServiceError("В реестре нет команды запуска.", 409)
    if not _wait_for_port(service["port"], True):
        raise ServiceError("Сервис запущен, но его порт пока не отвечает.", 504)


def _stop_service(service: dict[str, Any], state: dict[str, Any]) -> None:
    pids = listening_pids(service["port"])
    public = _public_service(service, state, persist_mapping=False)
    if pids and not public["canStop"]:
        raise ServiceError(public["controlBlockedReason"], 409)
    agent = _agent_for_service(service, pids, state)
    domain = f"gui/{os.getuid()}"
    if agent:
        _launchctl("disable", f"{domain}/{agent['label']}", check=False)
        _launchctl("bootout", f"{domain}/{agent['label']}", check=False)
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            continue
        except PermissionError as error:
            raise ServiceError("Недостаточно прав для остановки процесса.", 403) from error
    if _wait_for_port(service["port"], False, timeout=3.0):
        return
    for pid in listening_pids(service["port"]):
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            continue
        except PermissionError as error:
            raise ServiceError("Процесс не завершился после SIGTERM.", 409) from error
    if not _wait_for_port(service["port"], False, timeout=2.0):
        raise ServiceError("Процесс не освободил порт.", 409)


def control_service(service_id: str, action: str) -> dict[str, Any]:
    if action not in {"start", "stop"}:
        raise ServiceError("Неизвестное действие.", 400)
    with _CONTROL_LOCK:
        service = _service_by_id(service_id)
        state = _read_state()
        disabled = set(state.get("disabled", []))
        if action == "stop":
            preview = _public_service(service, state, persist_mapping=False)
            if preview["status"] == "running" and not preview["canStop"]:
                raise ServiceError(preview["controlBlockedReason"], 409)
            disabled.add(service_id)
            state["disabled"] = sorted(disabled)
            _write_state(state)
            _stop_service(service, state)
        else:
            current_pids = listening_pids(service["port"])
            if not current_pids:
                _start_service(service, state)
            else:
                agent = _agent_for_service(service, current_pids, state)
                if agent:
                    domain = f"gui/{os.getuid()}"
                    _launchctl("enable", f"{domain}/{agent['label']}", check=False)
            disabled.discard(service_id)
            state["disabled"] = sorted(disabled)
            _write_state(state)
        return _public_service(service, state)
