"""Capture a safe, structured activity stream from extella-listener output.

The module is loaded through a small .pth file inside the uv tool environment.
It never stores raw listener output: only allow-listed lifecycle events, a few
numeric fields, and narrow scheduler-routing identifiers are written to JSONL.
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO


def _native_event_file() -> Path:
    override = os.environ.get("EXTELLA_ACTIVITY_FILE")
    if override:
        return Path(override)
    home = Path(os.environ.get("USERPROFILE") or os.environ.get("HOME") or Path.home())
    if sys.platform == "darwin":
        data_root = home / "Library" / "Application Support" / "Extella"
    else:
        data_root = Path(os.environ.get("LOCALAPPDATA") or home / "AppData" / "Local") / "Extella"
    return data_root / "state" / "activity" / "events.jsonl"


EVENT_FILE = _native_event_file()

_UUID = r"[0-9a-fA-F-]{36}"
_RECEIVED_RE = re.compile(rf"Got task:\s*({_UUID})")
_IDENTIFIED_RE = re.compile(r"Looking for function:\s*([A-Za-z_][A-Za-z0-9_]*)")
_RETURNED_RE = re.compile(r"Function\s+([A-Za-z_][A-Za-z0-9_]*)\s+returned")
_RESULT_RE = re.compile(rf"Task\s+({_UUID})\s+result:\s*([A-Za-z0-9_]+)\s*=\s*(.*)")
_COMPLETED_RE = re.compile(rf"Task completed:\s*({_UUID})")
_ERROR_RE = re.compile(rf"Task\s+({_UUID})\s+error:\s*(.*)", re.IGNORECASE)


def _redact_for_display(text: str) -> str:
    """Mask common credentials before listener output reaches the raw log panel."""
    text = re.sub(r"(--crypto-key\s+)\S+", r"\1<redacted>", text)
    text = re.sub(
        r"((?:['\"]?api_token['\"]?)\s*[:=]\s*['\"])[^'\"]+(['\"])",
        r"\1<redacted>\2",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"(/bot)\d+:[A-Za-z0-9_-]+", r"\1<redacted>", text)
    text = re.sub(
        r"((?:['\"]?X-Auth-Token['\"]?)\s*[:=]\s*['\"])[^'\"]+(['\"])",
        r"\1<redacted>\2",
        text,
        flags=re.IGNORECASE,
    )
    return text


def _write_event(event: dict[str, Any]) -> None:
    """Append one compact event atomically without touching stdout/stderr."""
    EVENT_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "pid": os.getpid(),
        "ppid": os.getppid(),
        **event,
    }
    encoded = (json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )
    fd = os.open(EVENT_FILE, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        os.write(fd, encoded)
    finally:
        os.close(fd)


def _extract_int(text: str, field: str) -> int | None:
    match = re.search(rf"['\"]{re.escape(field)}['\"]\s*:\s*(\d+)", text)
    return int(match.group(1)) if match else None


def _extract_bool(text: str, field: str) -> bool | None:
    match = re.search(rf"['\"]{re.escape(field)}['\"]\s*:\s*(true|false|True|False)", text)
    if not match:
        return None
    return match.group(1).lower() == "true"


def _safe_result_summary(text: str) -> dict[str, Any]:
    """Extract only fields useful to a human; never persist the raw result."""
    summary: dict[str, Any] = {}
    status_match = re.search(r"['\"]status['\"]\s*:\s*['\"]([A-Za-z_-]+)['\"]", text)
    if status_match:
        summary["status"] = status_match.group(1).lower()

    for field in ("checked", "processed", "handled"):
        value = _extract_int(text, field)
        if value is not None:
            summary[field] = value

    ok = _extract_bool(text, "ok")
    if ok is not None:
        summary["ok"] = ok

    summary["noMessages"] = bool(
        re.search(r"['\"]messages['\"]\s*:\s*\[\s*\]", text)
        or re.search(r"['\"]msgs['\"]\s*:\s*0", text)
    )
    summary["noRuns"] = bool(re.search(r"['\"]fired['\"]\s*:\s*\[\s*\]", text))

    # Scheduler integration ids are safe routing metadata. Accept only the
    # narrow wz_* identifier shape; never persist surrounding result content.
    source_ids: list[str] = []
    ids_match = re.search(r"['\"]isids['\"]\s*:\s*\[([^\]]*)\]", text)
    if ids_match:
        source_ids.extend(
            re.findall(r"['\"](wz_[A-Za-z0-9_-]{3,80})['\"]", ids_match.group(1))
        )
    sid_match = re.search(r"['\"]sid['\"]\s*:\s*['\"](wz_[A-Za-z0-9_-]{3,80})['\"]", text)
    if sid_match:
        source_ids.append(sid_match.group(1))
    if source_ids:
        summary["sourceIds"] = list(dict.fromkeys(source_ids))[:5]

    channel_match = re.search(
        r"['\"]chan(?:nel)?['\"]\s*:\s*['\"](telegram|whatsapp|email)['\"]",
        text,
        flags=re.IGNORECASE,
    )
    if channel_match:
        summary["channel"] = channel_match.group(1).lower()
    return summary


class _LineParser:
    def __init__(self) -> None:
        self._buffer = ""

    def feed(self, text: str) -> None:
        self._buffer += text.replace("\r", "\n")
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            self.parse(line.strip())

    def parse(self, line: str) -> None:
        if not line:
            return

        match = _RECEIVED_RE.search(line)
        if match:
            _write_event({"type": "received", "taskId": match.group(1)})
            return

        match = _IDENTIFIED_RE.search(line)
        if match:
            _write_event({"type": "identified", "function": match.group(1)})
            return

        match = _RETURNED_RE.search(line)
        if match:
            _write_event({"type": "function_returned", "function": match.group(1)})
            return

        match = _RESULT_RE.search(line)
        if match:
            _write_event(
                {
                    "type": "result",
                    "taskId": match.group(1),
                    "resultType": match.group(2),
                    "summary": _safe_result_summary(match.group(3)),
                }
            )
            return

        match = _COMPLETED_RE.search(line)
        if match:
            _write_event({"type": "completed", "taskId": match.group(1)})
            return

        match = _ERROR_RE.search(line)
        if match:
            # The error text can contain arbitrary data. Store only a generic flag.
            _write_event({"type": "failed", "taskId": match.group(1)})
            return

        if "[Listener] Starting..." in line:
            _write_event({"type": "listener_started"})


class _ObservedStream:
    def __init__(self, wrapped: TextIO) -> None:
        self._wrapped = wrapped
        self._parser = _LineParser()
        self._lock = threading.Lock()

    def write(self, text: str) -> int:
        sanitized = _redact_for_display(text)
        self._wrapped.write(sanitized)
        with self._lock:
            try:
                self._parser.feed(sanitized)
            except Exception:
                # Observability must never interrupt the listener.
                pass
        return len(text)

    def flush(self) -> None:
        self._wrapped.flush()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._wrapped, name)


def activate() -> None:
    """Enable capture only inside extella-listener and its worker processes."""
    if os.environ.get("EXTELLA_ACTIVITY_HOOK_PID") == str(os.getpid()):
        return

    argv = " ".join(sys.argv).lower()
    inherited = os.environ.get("EXTELLA_ACTIVITY_PARENT") == "1"
    if "extella-listener" not in argv and not inherited:
        return

    os.environ["EXTELLA_ACTIVITY_HOOK_PID"] = str(os.getpid())
    os.environ["EXTELLA_ACTIVITY_PARENT"] = "1"
    if not isinstance(sys.stdout, _ObservedStream):
        sys.stdout = _ObservedStream(sys.stdout)
    if not isinstance(sys.stderr, _ObservedStream):
        sys.stderr = _ObservedStream(sys.stderr)


__all__ = ["activate"]
