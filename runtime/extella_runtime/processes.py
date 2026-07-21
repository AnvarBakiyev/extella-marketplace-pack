"""Cross-platform ownership-safe lifecycle for Extella local services."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from typing import Any, Mapping, Sequence
import urllib.error
import urllib.request

from .platforms import PlatformInfo, detect_platform


class ProcessControlError(RuntimeError):
    pass


@dataclass(frozen=True)
class RuntimeSpec:
    runtime_id: str
    name: str
    argv: tuple[str, ...]
    cwd: Path
    port: int
    health_url: str
    log_path: Path
    owner: str
    autostart: str


@dataclass(frozen=True)
class ProcessIdentity:
    pid: int
    ppid: int
    executable: str
    started_at: str
    command_hash: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_LOCK = threading.RLock()


def _run(argv: Sequence[str], timeout: int = 5) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(argv), capture_output=True, text=True, timeout=timeout, check=False, shell=False
    )


def _powershell() -> str | None:
    return shutil.which("powershell.exe") or shutil.which("pwsh.exe")


def process_identity(pid: int, *, platform_info: PlatformInfo | None = None) -> ProcessIdentity | None:
    platform_info = platform_info or detect_platform()
    if pid <= 0:
        return None
    try:
        if platform_info.system == "Windows":
            powershell = _powershell()
            if not powershell:
                return None
            script = (
                "$p=Get-CimInstance Win32_Process -Filter 'ProcessId = " + str(pid) + "';"
                "if($p){$p|Select-Object ProcessId,ParentProcessId,Name,CreationDate,CommandLine|ConvertTo-Json -Compress}"
            )
            result = _run((powershell, "-NoProfile", "-NonInteractive", "-Command", script))
            if result.returncode != 0 or not result.stdout.strip():
                return None
            row = json.loads(result.stdout)
            command = str(row.get("CommandLine") or "")
            return ProcessIdentity(
                pid=int(row.get("ProcessId") or pid),
                ppid=int(row.get("ParentProcessId") or 0),
                executable=str(row.get("Name") or "process"),
                started_at=str(row.get("CreationDate") or ""),
                command_hash=hashlib.sha256(command.encode("utf-8")).hexdigest(),
            )
        result = _run(("ps", "-p", str(pid), "-o", "ppid=,lstart=,command="))
        if result.returncode != 0 or not result.stdout.strip():
            return None
        line = result.stdout.strip()
        match = re.match(r"\s*(\d+)\s+(.{24})\s+(.*)$", line)
        if not match:
            return None
        command = match.group(3)
        try:
            executable = Path(shlex.split(command)[0]).name
        except (ValueError, IndexError):
            executable = "process"
        return ProcessIdentity(
            pid=pid,
            ppid=int(match.group(1)),
            executable=executable,
            started_at=match.group(2).strip(),
            command_hash=hashlib.sha256(command.encode("utf-8")).hexdigest(),
        )
    except (OSError, subprocess.SubprocessError, ValueError, json.JSONDecodeError):
        return None


def listening_pids(port: int, *, platform_info: PlatformInfo | None = None) -> list[int]:
    platform_info = platform_info or detect_platform()
    if not 0 < int(port) < 65536:
        return []
    try:
        if platform_info.system == "Windows":
            powershell = _powershell()
            if not powershell:
                return []
            script = (
                "Get-NetTCPConnection -State Listen -LocalPort " + str(int(port))
                + " -ErrorAction SilentlyContinue|Select-Object -ExpandProperty OwningProcess|Sort-Object -Unique"
            )
            result = _run((powershell, "-NoProfile", "-NonInteractive", "-Command", script))
        else:
            lsof = shutil.which("lsof") or "/usr/sbin/lsof"
            result = _run((lsof, "-nP", f"-iTCP:{int(port)}", "-sTCP:LISTEN", "-t"))
    except (OSError, subprocess.SubprocessError):
        return []
    pids: set[int] = set()
    for line in result.stdout.splitlines():
        try:
            pids.add(int(line.strip()))
        except ValueError:
            continue
    return sorted(pids)


def _health(url: str, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return 200 <= int(response.status) < 400
    except (urllib.error.URLError, OSError, ValueError):
        return False


def _read_state(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schemaVersion": 1, "runtimes": {}}
    if not isinstance(value, dict) or not isinstance(value.get("runtimes"), dict):
        return {"schemaVersion": 1, "runtimes": {}}
    return value


def _write_state(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _rotate_log(path: Path, maximum: int = 2 * 1024 * 1024, backups: int = 3) -> None:
    try:
        if not path.is_file() or path.stat().st_size < maximum:
            return
        for index in range(backups, 0, -1):
            source = path.with_name(path.name + (f".{index - 1}" if index > 1 else ""))
            target = path.with_name(path.name + f".{index}")
            if source.exists():
                if target.exists():
                    target.unlink()
                os.replace(source, target)
    except OSError:
        return


class ProcessSupervisor:
    def __init__(
        self,
        *,
        state_file: Path,
        platform_info: PlatformInfo | None = None,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        self.state_file = state_file
        self.platform_info = platform_info or detect_platform()
        if not self.platform_info.supported:
            raise ProcessControlError(self.platform_info.reason or "unsupported platform")
        self.environment = dict(os.environ if environment is None else environment)
        self._children: dict[str, subprocess.Popen[Any]] = {}

    def _record(self, runtime_id: str) -> dict[str, Any] | None:
        return _read_state(self.state_file).get("runtimes", {}).get(runtime_id)

    def _owned_identity(self, runtime_id: str) -> ProcessIdentity | None:
        record = self._record(runtime_id)
        if not isinstance(record, dict):
            return None
        identity = process_identity(int(record.get("pid") or 0), platform_info=self.platform_info)
        if identity is None:
            return None
        if identity.started_at != record.get("startedAt"):
            return None
        if identity.command_hash != record.get("commandHash"):
            return None
        return identity

    def claim_current_process(self, spec: RuntimeSpec) -> dict[str, Any]:
        """Bind a native-autostart process to its new post-login identity.

        The caller must already own the listening socket. This is used by the
        Activity Center after LaunchAgent or Task Scheduler starts it directly,
        because a PID fingerprint from the previous boot can never be reused.
        """

        with _LOCK:
            pid = os.getpid()
            identity = process_identity(pid, platform_info=self.platform_info)
            listeners = listening_pids(spec.port, platform_info=self.platform_info)
            if identity is None or listeners != [pid]:
                raise ProcessControlError(
                    "current autostart process does not exclusively own its declared port"
                )
            state = _read_state(self.state_file)
            state.setdefault("runtimes", {})[spec.runtime_id] = {
                "pid": identity.pid,
                "startedAt": identity.started_at,
                "commandHash": identity.command_hash,
                "owner": spec.owner,
                "port": spec.port,
            }
            _write_state(self.state_file, state)
            return identity.to_dict()

    def status(self, spec: RuntimeSpec) -> dict[str, Any]:
        identity = self._owned_identity(spec.runtime_id)
        pids = listening_pids(spec.port, platform_info=self.platform_info)
        healthy = _health(spec.health_url)
        owned = bool(identity and identity.pid in pids)
        error = None
        if pids and not owned:
            error = "port_occupied_by_unowned_process"
        elif identity and not healthy:
            error = "health_check_failed"
        return {
            "id": spec.runtime_id,
            "name": spec.name,
            "owner": spec.owner,
            "status": "running" if healthy and owned else "degraded" if identity or pids else "stopped",
            "pid": identity.pid if identity else None,
            "ppid": identity.ppid if identity else None,
            "process": identity.executable if identity else None,
            "port": spec.port,
            "healthy": healthy,
            "startedAt": identity.started_at if identity else None,
            "autostart": spec.autostart,
            "errorClass": error,
            "canStart": not pids,
            "canStop": owned,
        }

    def start(self, spec: RuntimeSpec, timeout: float = 30.0) -> dict[str, Any]:
        with _LOCK:
            current = self.status(spec)
            if current["status"] == "running":
                return current
            if listening_pids(spec.port, platform_info=self.platform_info):
                raise ProcessControlError(
                    f"port {spec.port} is occupied by a process not owned by {spec.runtime_id}"
                )
            if not spec.argv or not Path(spec.argv[0]).is_absolute():
                raise ProcessControlError("runtime argv must start with an absolute executable path")
            if not spec.cwd.is_dir():
                raise ProcessControlError(f"runtime working directory does not exist: {spec.cwd}")
            spec.log_path.parent.mkdir(parents=True, exist_ok=True)
            _rotate_log(spec.log_path)
            log = spec.log_path.open("ab", buffering=0)
            kwargs: dict[str, Any] = {
                "cwd": str(spec.cwd),
                "env": self.environment,
                "stdin": subprocess.DEVNULL,
                "stdout": log,
                "stderr": subprocess.STDOUT,
                "shell": False,
            }
            if self.platform_info.system == "Windows":
                kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            else:
                kwargs["start_new_session"] = True
            try:
                process = subprocess.Popen(list(spec.argv), **kwargs)
            finally:
                log.close()
            self._children[spec.runtime_id] = process
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if _health(spec.health_url):
                    break
                if process.poll() is not None:
                    break
                time.sleep(0.2)
            if not _health(spec.health_url):
                try:
                    process.terminate()
                    process.wait(timeout=5)
                except (OSError, subprocess.SubprocessError):
                    try:
                        process.kill()
                    except OSError:
                        pass
                self._children.pop(spec.runtime_id, None)
                raise ProcessControlError("runtime did not pass its health check")
            # Capture the fingerprint only after the child has exec'd and passed
            # health. Reading it immediately after Popen can observe the brief
            # pre-exec fork image and produce a fingerprint that changes at once.
            identity = process_identity(process.pid, platform_info=self.platform_info)
            if identity is None:
                process.terminate()
                process.wait(timeout=5)
                self._children.pop(spec.runtime_id, None)
                raise ProcessControlError("started process identity could not be verified")
            state = _read_state(self.state_file)
            state.setdefault("runtimes", {})[spec.runtime_id] = {
                "pid": identity.pid,
                "startedAt": identity.started_at,
                "commandHash": identity.command_hash,
                "owner": spec.owner,
                "port": spec.port,
            }
            _write_state(self.state_file, state)
            result = self.status(spec)
            if result["status"] != "running":
                try:
                    self.stop(spec, timeout=5.0)
                except ProcessControlError:
                    pass
                raise ProcessControlError("runtime ownership could not be confirmed")
            return result

    def stop(self, spec: RuntimeSpec, timeout: float = 10.0) -> dict[str, Any]:
        with _LOCK:
            identity = self._owned_identity(spec.runtime_id)
            if identity is None:
                if listening_pids(spec.port, platform_info=self.platform_info):
                    raise ProcessControlError("refusing to stop an unowned process")
                return self.status(spec)
            try:
                if self.platform_info.system == "Windows":
                    result = _run(("taskkill.exe", "/PID", str(identity.pid), "/T"), timeout=5)
                    if result.returncode not in {0, 128}:
                        raise ProcessControlError("Windows could not stop the owned process")
                else:
                    os.kill(identity.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            child = self._children.get(spec.runtime_id)
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if child is not None and child.poll() is not None:
                    break
                if process_identity(identity.pid, platform_info=self.platform_info) is None:
                    break
                time.sleep(0.1)
            if child is not None and child.poll() is not None:
                child.wait(timeout=1)
            if process_identity(identity.pid, platform_info=self.platform_info):
                if self.platform_info.system == "Windows":
                    _run(("taskkill.exe", "/PID", str(identity.pid), "/T", "/F"), timeout=5)
                else:
                    os.kill(identity.pid, signal.SIGKILL)
            if process_identity(identity.pid, platform_info=self.platform_info):
                raise ProcessControlError("owned process did not stop")
            child = self._children.pop(spec.runtime_id, None)
            if child is not None:
                try:
                    child.wait(timeout=1)
                except subprocess.SubprocessError:
                    pass
            state = _read_state(self.state_file)
            state.setdefault("runtimes", {}).pop(spec.runtime_id, None)
            _write_state(self.state_file, state)
            return self.status(spec)

    def restart(self, spec: RuntimeSpec, timeout: float = 30.0) -> dict[str, Any]:
        self.stop(spec)
        return self.start(spec, timeout=timeout)


def find_available_port(preferred: int, *, host: str = "127.0.0.1") -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((host, preferred))
            return preferred
        except OSError:
            sock.bind((host, 0))
            return int(sock.getsockname()[1])
