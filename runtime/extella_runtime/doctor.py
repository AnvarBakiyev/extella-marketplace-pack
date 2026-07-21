"""Computer Doctor preflight with stable JSON-friendly results."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import ctypes
import os
from pathlib import Path
import shutil
import socket
import ssl
import threading
from typing import Any, Iterable, Mapping
import urllib.error
import urllib.parse
import urllib.request

from .ensure_tool import Executor, Which, ensure_tool
from .platforms import PlatformInfo, detect_platform


DEFAULT_REQUIRED_TOOLS = ("python", "git")
DEFAULT_OPTIONAL_TOOLS = (
    "node",
    "npm",
    "npx",
    "uv",
    "uvx",
    "ffmpeg",
    "ghostscript",
    "imagemagick",
    "pandoc",
    "ollama",
)


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    status: str
    message: str
    required: bool = True
    details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DoctorReport:
    status: str
    platform: dict[str, Any]
    checks: tuple[DoctorCheck, ...]
    changed: bool = False

    @property
    def ready(self) -> bool:
        return self.status == "ready"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": 1,
            "status": self.status,
            "ready": self.ready,
            "changed": self.changed,
            "platform": self.platform,
            "checks": [check.to_dict() for check in self.checks],
        }


def _nearest_existing(path: Path) -> Path:
    candidate = path
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate


def _port_check(port: int) -> DoctorCheck:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", port))
    except OSError as exc:
        return DoctorCheck(
            f"port:{port}",
            "warning",
            "Port is already occupied; ownership and health must be verified before install",
            required=False,
            details={"port": port, "errorClass": "port_occupied", "error": str(exc)},
        )
    finally:
        sock.close()
    return DoctorCheck(
        f"port:{port}", "pass", "Port is available", required=False, details={"port": port}
    )


def _path_check(environment: Mapping[str, str]) -> DoctorCheck:
    raw = environment.get("PATH", "")
    entries = [entry for entry in raw.split(os.pathsep) if entry]
    existing = [entry for entry in entries if Path(entry).is_dir()]
    status = "pass" if entries and existing else "warning"
    return DoctorCheck(
        "path",
        status,
        "PATH contains usable directories" if status == "pass" else "PATH is empty or contains no existing directories",
        required=False,
        details={
            "entryCount": len(entries),
            "existingEntryCount": len(existing),
            "missingEntryCount": len(entries) - len(existing),
        },
    )


def _ssl_check() -> DoctorCheck:
    try:
        context = ssl.create_default_context()
        paths = ssl.get_default_verify_paths()
        if context.verify_mode != ssl.CERT_REQUIRED or not context.check_hostname:
            raise RuntimeError("default TLS verification is disabled")
    except Exception as exc:
        return DoctorCheck(
            "ssl",
            "failed",
            "Python TLS verification is unavailable",
            details={"errorClass": type(exc).__name__, "error": str(exc)},
        )
    return DoctorCheck(
        "ssl",
        "pass",
        "Python TLS verification is available",
        details={
            "openssl": ssl.OPENSSL_VERSION,
            "caFileConfigured": bool(paths.cafile or paths.openssl_cafile),
            "caPathConfigured": bool(paths.capath or paths.openssl_capath),
        },
    )


def _native_loader_check() -> DoctorCheck:
    try:
        ctypes.CDLL(None)
    except (OSError, TypeError) as exc:
        return DoctorCheck(
            "native_loader",
            "failed",
            "Native library loader is unavailable",
            details={"errorClass": type(exc).__name__, "error": str(exc)},
        )
    return DoctorCheck("native_loader", "pass", "Native library loader is available")


def _loopback_http_check(timeout: float = 3.0) -> DoctorCheck:
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.settimeout(timeout)
    try:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = int(server.getsockname()[1])

        def respond() -> None:
            try:
                connection, _ = server.accept()
                with connection:
                    connection.settimeout(timeout)
                    connection.recv(4096)
                    connection.sendall(
                        b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nOK"
                    )
            except OSError:
                return

        thread = threading.Thread(target=respond, daemon=True)
        thread.start()
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=timeout) as response:
            body = response.read()
            status = int(response.status)
        thread.join(timeout)
        if status != 200 or body != b"OK":
            raise RuntimeError("loopback response was not healthy")
    except (OSError, urllib.error.URLError, RuntimeError) as exc:
        return DoctorCheck(
            "localhost_http",
            "failed",
            "Localhost HTTP services cannot be started or reached",
            details={"errorClass": type(exc).__name__, "error": str(exc)},
        )
    finally:
        server.close()
    return DoctorCheck(
        "localhost_http",
        "pass",
        "Localhost HTTP bind and request succeeded",
        details={"bind": "127.0.0.1", "probePort": port},
    )


def _network_check(url: str, timeout: int = 10) -> DoctorCheck:
    request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "ExtellaDoctor/1"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = int(response.status)
    except (urllib.error.URLError, OSError) as exc:
        return DoctorCheck(
            "network",
            "action_required",
            "Required release endpoint is not reachable",
            details={"origin": urllib.parse.urlsplit(url).netloc, "error": str(exc)},
        )
    return DoctorCheck(
        "network",
        "pass" if 200 <= status < 400 else "action_required",
        "Required release endpoint is reachable" if 200 <= status < 400 else "Release endpoint rejected the request",
        details={"origin": urllib.parse.urlsplit(url).netloc, "httpStatus": status},
    )


def _overall_status(checks: Iterable[DoctorCheck], supported: bool) -> str:
    if not supported:
        return "unsupported"
    required = [check for check in checks if check.required]
    if any(check.status == "failed" for check in required):
        return "failed"
    if any(check.status in {"action_required", "unsupported"} for check in required):
        return "action_required"
    return "ready"


def run_doctor(
    *,
    allow_repair: bool = False,
    platform_info: PlatformInfo | None = None,
    data_root: Path | None = None,
    required_tools: Iterable[str] = DEFAULT_REQUIRED_TOOLS,
    optional_tools: Iterable[str] = DEFAULT_OPTIONAL_TOOLS,
    ports: Iterable[int] = (),
    network_urls: Iterable[str] = (),
    minimum_free_bytes: int = 2 * 1024 * 1024 * 1024,
    env: Mapping[str, str] | None = None,
    executor: Executor | None = None,
    which: Which | None = None,
) -> DoctorReport:
    """Diagnose first; mutate dependencies only when ``allow_repair`` is true."""

    platform_info = platform_info or detect_platform()
    checks: list[DoctorCheck] = []
    if not platform_info.supported:
        checks.append(
            DoctorCheck(
                "platform",
                "unsupported",
                platform_info.reason or "Unsupported platform",
                details=platform_info.to_dict(),
            )
        )
        return DoctorReport("unsupported", platform_info.to_dict(), tuple(checks))
    checks.append(
        DoctorCheck(
            "platform", "pass", f"Supported platform: {platform_info.key}",
            details=platform_info.to_dict()
        )
    )

    environment = dict(os.environ if env is None else env)
    checks.append(_path_check(environment))
    checks.append(_ssl_check())
    checks.append(_native_loader_check())
    checks.append(_loopback_http_check())
    home = Path(environment.get("USERPROFILE") or environment.get("HOME") or Path.home())
    root = data_root or home / ".extella"
    writable_parent = _nearest_existing(root)
    writable = os.access(writable_parent, os.W_OK)
    checks.append(
        DoctorCheck(
            "data_root",
            "pass" if writable else "action_required",
            "Extella data directory can be created or updated" if writable else "Extella data directory is not writable",
            details={"path": str(root), "existingParent": str(writable_parent)},
        )
    )
    try:
        free_bytes = shutil.disk_usage(writable_parent).free
        disk_status = "pass" if free_bytes >= minimum_free_bytes else "action_required"
        checks.append(
            DoctorCheck(
                "disk_space",
                disk_status,
                "Enough free disk space" if disk_status == "pass" else "Not enough free disk space",
                details={"freeBytes": free_bytes, "minimumBytes": minimum_free_bytes},
            )
        )
    except OSError as exc:
        checks.append(
            DoctorCheck(
                "disk_space", "failed", "Free disk space could not be measured",
                details={"error": str(exc)}
            )
        )

    tool_kwargs: dict[str, Any] = {
        "allow_install": allow_repair,
        "platform_info": platform_info,
        "env": environment,
    }
    if executor is not None:
        tool_kwargs["executor"] = executor
    if which is not None:
        tool_kwargs["which"] = which
    changed = False
    for required, names in ((True, required_tools), (False, optional_tools)):
        for name in names:
            result = ensure_tool(name, **tool_kwargs)
            changed = changed or result.changed
            if result.ready:
                status = "pass"
            elif required:
                status = result.status
            else:
                status = "warning"
            checks.append(
                DoctorCheck(
                    f"tool:{name}",
                    status,
                    result.message or (f"{name} is ready" if result.ready else f"{name} is unavailable"),
                    required=required,
                    details=result.to_dict(),
                )
            )

    if platform_info.system == "Darwin":
        launch_agents = home / "Library" / "LaunchAgents"
        parent = _nearest_existing(launch_agents)
        autostart_ready = os.access(parent, os.W_OK)
        autostart_detail = {"mechanism": "LaunchAgent", "path": str(launch_agents)}
    else:
        search_path = environment.get("PATH", "")
        if which is None:
            autostart_ready = shutil.which("schtasks.exe", path=search_path) is not None
        else:
            autostart_ready = which("schtasks.exe", search_path) is not None
        autostart_detail = {"mechanism": "ScheduledTask"}
    checks.append(
        DoctorCheck(
            "autostart",
            "pass" if autostart_ready else "action_required",
            "Per-user autostart is available" if autostart_ready else "Per-user autostart is not available",
            details=autostart_detail,
        )
    )
    checks.extend(_port_check(port) for port in ports)
    checks.extend(_network_check(url) for url in network_urls)
    return DoctorReport(
        _overall_status(checks, platform_info.supported),
        platform_info.to_dict(),
        tuple(checks),
        changed=changed,
    )
