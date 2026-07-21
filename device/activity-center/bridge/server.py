"""Local API for the Extella Activity Center toolbar extension.

Activity data stays read-only. The only mutation is a token-protected control
route for localhost services declared in the Extella plugin registry.
"""

from __future__ import annotations

import json
import os
import platform
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
from glob import glob
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from shutil import copy2
from typing import Any
from urllib.parse import urlparse

from activity_model import build_activity, read_events
from service_manager import ServiceError, control_service, list_services, start_desired_services
from task_state import dismiss_tasks, read_dismissed


HOST = os.environ.get("EXTELLA_ACTIVITY_HOST", "127.0.0.1")
PORT = int(os.environ.get("EXTELLA_ACTIVITY_PORT", "8799"))
EVENT_FILE = Path(
    os.environ.get(
        "EXTELLA_ACTIVITY_FILE",
        str(Path.home() / ".extella" / "activity-center" / "events.jsonl"),
    )
)
ALLOWED_ORIGINS = {
    "https://prod.extella.ai",
    "https://api.extella.ai",
    "http://127.0.0.1:8799",
    "http://localhost:8799",
}
CONTROL_TOKEN = secrets.token_urlsafe(24)

_process_cache: tuple[float, dict[str, Any]] = (0.0, {})
_LISTENER_COMMAND = re.compile(
    r"^/\S*/bin/python(?:3(?:\.\d+)?)?\s+/\S*/bin/extella-listener\s+--url\s+"
)


def control_authorized(origin: str, token: str) -> bool:
    if origin and origin not in ALLOWED_ORIGINS:
        return False
    return secrets.compare_digest(token, CONTROL_TOKEN)


def activity_payload(include_dismissed: bool = False) -> dict[str, Any]:
    payload = build_activity(
        read_events(EVENT_FILE),
        listener_processes(),
        dismissed_ids=[] if include_dismissed else read_dismissed(),
    )
    payload["controlToken"] = CONTROL_TOKEN
    return payload


def listener_processes() -> dict[str, Any]:
    global _process_cache
    now = time.monotonic()
    if now - _process_cache[0] < 2 and _process_cache[1]:
        return _process_cache[1]

    processes: list[dict[str, int]] = []
    try:
        if platform.system() == "Windows":
            powershell = shutil.which("powershell.exe") or shutil.which("pwsh.exe")
            if not powershell:
                raise OSError("PowerShell is unavailable")
            script = (
                "Get-CimInstance Win32_Process|Where-Object {$_.CommandLine -like '*extella-listener*' "
                "-and $_.CommandLine -like '*--url*'}|Select-Object ProcessId,ParentProcessId|ConvertTo-Json -Compress"
            )
            result = subprocess.run(
                [powershell, "-NoProfile", "-NonInteractive", "-Command", script],
                check=True,
                capture_output=True,
                text=True,
                timeout=4,
            )
            rows = json.loads(result.stdout or "[]")
            if isinstance(rows, dict):
                rows = [rows]
            for row in rows if isinstance(rows, list) else []:
                processes.append(
                    {"pid": int(row["ProcessId"]), "ppid": int(row.get("ParentProcessId") or 0)}
                )
        else:
            result = subprocess.run(
                ["ps", "-axo", "pid=,ppid=,command="],
                check=True,
                capture_output=True,
                text=True,
                timeout=2,
            )
            for line in result.stdout.splitlines():
                parts = line.strip().split(maxsplit=2)
                if len(parts) != 3:
                    continue
                pid_text, ppid_text, command = parts
                if not _LISTENER_COMMAND.search(command):
                    continue
                processes.append({"pid": int(pid_text), "ppid": int(ppid_text)})
    except (OSError, subprocess.SubprocessError, ValueError):
        pass

    info = {
        "count": len(processes),
        "orphaned": sum(process["ppid"] == 1 for process in processes),
        "processes": processes,
    }
    _process_cache = (now, info)
    return info


def ensure_hooks_installed() -> int:
    """Keep the capture hook present when uv refreshes its tool environment."""
    source = Path(__file__).with_name("extella_activity_hook.py")
    if not source.exists():
        return 0
    archives = [Path.home() / ".cache" / "uv" / "archive-v0"]
    if os.environ.get("LOCALAPPDATA"):
        archives.append(Path(os.environ["LOCALAPPDATA"]) / "uv" / "cache" / "archive-v0")
    if os.environ.get("UV_CACHE_DIR"):
        archives.append(Path(os.environ["UV_CACHE_DIR"]) / "archive-v0")
    patterns = (
        "*/lib/python*/site-packages/extella_listener",
        "*/*.data/purelib/extella_listener",
        "*/Lib/site-packages/extella_listener",
    )
    installed = 0
    listener_dirs = {
        Path(listener_dir)
        for archive in archives
        for pattern in patterns
        for listener_dir in glob(str(archive / pattern))
    }
    for listener_dir in sorted(listener_dirs, key=lambda path: path.as_posix()):
        site_packages = listener_dir.parent
        target = site_packages / source.name
        pth = site_packages / "extella_activity_center.pth"
        try:
            if not target.exists() or target.read_bytes() != source.read_bytes():
                copy2(source, target)
            expected = "import extella_activity_hook; extella_activity_hook.activate()\n"
            if not pth.exists() or pth.read_text(encoding="utf-8") != expected:
                pth.write_text(expected, encoding="utf-8")
            installed += 1
        except OSError:
            continue
    return installed


class Handler(BaseHTTPRequestHandler):
    server_version = "ExtellaActivityCenter/1.0"

    def log_message(self, _format: str, *_args: Any) -> None:
        return

    def _cors(self) -> None:
        origin = self.headers.get("Origin", "")
        if origin in ALLOWED_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header(
            "Access-Control-Allow-Headers", "Content-Type, X-Extella-Control"
        )

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/api/health":
            self._send_json(
                200,
                {
                    "status": "ok",
                    "eventsFile": EVENT_FILE.exists(),
                    "hooks": ensure_hooks_installed(),
                    "listeners": listener_processes(),
                },
            )
            return
        if path == "/api/activity":
            self._send_json(200, activity_payload())
            return
        if path == "/api/services":
            self._send_json(
                200,
                {
                    "status": "ok",
                    "services": list_services(),
                    "controlToken": CONTROL_TOKEN,
                },
            )
            return
        self._send_json(404, {"status": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        origin = self.headers.get("Origin", "")
        if not control_authorized(
            origin, self.headers.get("X-Extella-Control", "")
        ):
            self._send_json(
                403,
                {"status": "forbidden", "message": "Control token required"},
            )
            return
        path = urlparse(self.path).path
        task_match = re.fullmatch(
            r"/api/tasks/([A-Za-z0-9_.-]{1,160})/dismiss", path
        )
        if task_match:
            dismissed = dismiss_tasks([task_match.group(1)])
            self._send_json(
                200,
                {"status": "ok", "dismissed": len(dismissed)},
            )
            return
        if path == "/api/tasks/clear-completed":
            visible = activity_payload(include_dismissed=True)
            task_ids = [task["id"] for task in visible.get("history", [])]
            dismissed = dismiss_tasks(task_ids)
            self._send_json(
                200,
                {
                    "status": "ok",
                    "cleared": len(task_ids),
                    "dismissed": len(dismissed),
                },
            )
            return
        match = re.fullmatch(
            r"/api/services/([A-Za-z0-9_.-]{1,128})/(start|stop|restart)", path
        )
        if not match:
            self._send_json(404, {"status": "not_found"})
            return
        try:
            service = control_service(match.group(1), match.group(2))
        except ServiceError as error:
            self._send_json(
                error.status,
                {"status": "error", "message": str(error)},
            )
            return
        self._send_json(200, {"status": "ok", "service": service})


def main() -> None:
    ensure_hooks_installed()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    threading.Thread(target=start_desired_services, name="extella-service-boot", daemon=True).start()
    print(f"Extella Activity Center listening on http://{HOST}:{PORT}", flush=True)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    sys.exit(main())
