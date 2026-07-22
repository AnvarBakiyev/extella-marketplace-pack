#!/usr/bin/env python3
"""Record hash-bound external release evidence on an exact supported machine.

The runner never stores or prints the Extella token. Each invocation records
one phase so clean install, reboot, reinstall, service control, upgrade, and
uninstall can be executed at the correct real-machine boundaries.
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
from typing import Any, Mapping
import urllib.error
import urllib.request
import zipfile


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from installer.verification import (  # noqa: E402
    ALLOWED_ORIGIN,
    SERVICE_PORTS,
    verify_installed_client,
)
from installer.plugin_lifecycle import SUPPORTED_IDS  # noqa: E402
from runtime.extella_runtime.paths import client_paths  # noqa: E402
from runtime.extella_runtime.platforms import detect_platform  # noqa: E402


PHASES = {
    "baseline",
    "previous-release",
    "installed",
    "controlled",
    "reinstalled",
    "repair-prepared",
    "repaired",
    "restarted",
    "upgraded",
    "live-ui",
    "uninstalled",
}
CANDIDATE_PHASES = {
    "installed",
    "controlled",
    "reinstalled",
    "repair-prepared",
    "repaired",
    "restarted",
    "upgraded",
    "live-ui",
}
CHILD_SERVICES = tuple(service for service in SERVICE_PORTS if service != "extella_activity_center")


class MatrixError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise MatrixError("required JSON contract is missing or invalid") from error
    if not isinstance(value, dict):
        raise MatrixError("required JSON contract must be an object")
    return value


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(
            json.dumps(dict(value), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    finally:
        temporary.unlink(missing_ok=True)


def _candidate_identity(candidate: Path, release_manifest: Path) -> dict[str, Any]:
    release = _read_json(release_manifest)
    distribution = release.get("distribution")
    if not isinstance(distribution, dict) or distribution.get("status") not in {"candidate", "released"}:
        raise MatrixError("release manifest does not describe a candidate or released bundle")
    if candidate.name != distribution.get("fileName"):
        raise MatrixError("candidate filename differs from the release manifest")
    if candidate.stat().st_size != distribution.get("bytes"):
        raise MatrixError("candidate byte size differs from the release manifest")
    digest = _sha256(candidate)
    if digest != distribution.get("sha256"):
        raise MatrixError("candidate SHA-256 differs from the release manifest")
    try:
        with zipfile.ZipFile(candidate) as archive:
            bundle = json.loads(archive.read("bundle-manifest.json"))
    except (OSError, KeyError, ValueError, zipfile.BadZipFile) as error:
        raise MatrixError("candidate bundle manifest is invalid") from error
    release_sources = {
        item.get("id"): item.get("revision")
        for item in release.get("sourceRepositories") or []
        if isinstance(item, dict)
    }
    bundle_sources = {
        item.get("id"): item.get("revision")
        for item in bundle.get("sourceRepositories") or []
        if isinstance(item, dict)
    }
    if release_sources != bundle_sources or bundle.get("releaseVersion") != release.get("version"):
        raise MatrixError("candidate source revisions differ from the release manifest")
    if len(bundle.get("files") or []) != distribution.get("fileCount"):
        raise MatrixError("candidate file inventory differs from the release manifest")
    return {
        "fileName": candidate.name,
        "sha256": digest,
        "bytes": candidate.stat().st_size,
        "fileCount": len(bundle.get("files") or []),
        "releaseVersion": release.get("version"),
        "sourceRepositories": release_sources,
    }


def _boot_marker(system: str) -> str:
    if system == "Darwin":
        command = ("sysctl", "-n", "kern.boottime")
    else:
        powershell = "powershell.exe"
        command = (
            powershell,
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "(Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToUniversalTime().ToString('o')",
        )
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
        shell=False,
    )
    value = result.stdout.strip()
    if result.returncode != 0 or not value:
        raise MatrixError("could not establish the operating-system boot marker")
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def _installed_states(paths) -> tuple[Path, Path]:
    return (
        paths.state_root / "client" / "install-state.json",
        paths.state_root / "account" / "account-state.json",
    )


def _state_versions(state: dict[str, Any]) -> list[str]:
    versions: list[str] = []
    current: Any = state
    for _ in range(64):
        if not isinstance(current, dict):
            break
        version = current.get("releaseVersion")
        if isinstance(version, str) and version:
            versions.append(version)
        current = current.get("previousState")
    return versions


def _expected_file_hash(state: dict[str, Any], filename: str) -> str:
    current: Any = state
    for _ in range(64):
        if not isinstance(current, dict):
            break
        for change in current.get("changes") or []:
            if (
                isinstance(change, dict)
                and change.get("kind") == "file"
                and Path(str(change.get("target") or "")).name == filename
            ):
                digest = change.get("sha256")
                if isinstance(digest, str) and len(digest) == 64:
                    return digest
        current = current.get("previousState")
    raise MatrixError(f"installed ownership state has no file contract for {filename}")


def _http_json(
    url: str,
    *,
    method: str = "GET",
    token: str = "",
    accepted_statuses: tuple[str, ...] = ("ok", "success"),
    timeout: float = 20,
) -> dict[str, Any]:
    headers = {"Origin": ALLOWED_ORIGIN}
    if token:
        headers["X-Extella-Control"] = token
    request = urllib.request.Request(url, data=b"{}" if method == "POST" else None, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if not 200 <= int(response.status) < 300:
                raise MatrixError("Activity Center control returned a non-success status")
            value = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError) as error:
        raise MatrixError("Activity Center control request failed") from error
    if not isinstance(value, dict) or value.get("status") not in set(accepted_statuses):
        raise MatrixError("Activity Center control was not acknowledged")
    return value


def _install_supported_plugins() -> dict[str, int]:
    services = _http_json("http://127.0.0.1:8799/api/services")
    control_token = services.get("controlToken")
    if not isinstance(control_token, str) or len(control_token) < 20:
        raise MatrixError("Activity Center returned no control token")
    before = _http_json("http://127.0.0.1:8799/api/plugins")
    available = {
        str(item.get("id"))
        for item in before.get("plugins") or []
        if isinstance(item, dict)
    }
    expected = set(SUPPORTED_IDS)
    if available != expected:
        raise MatrixError("supported on-demand inventory differs from the release allowlist")
    ordered = sorted(expected)
    for index, plugin_id in enumerate(ordered, start=1):
        print(
            f"Supported program {index}/{len(ordered)}: installing and running verified smokes ({plugin_id})…",
            file=sys.stderr,
            flush=True,
        )
        result = _http_json(
            f"http://127.0.0.1:8799/api/plugins/{plugin_id}/install",
            method="POST",
            token=control_token,
            accepted_statuses=("installed",),
            timeout=2400,
        )
        service = result.get("service")
        ui = result.get("ui")
        account = result.get("account")
        if (
            result.get("pluginId") != plugin_id
            or not isinstance(service, dict)
            or service.get("status") != "running"
            or not isinstance(service.get("pid"), int)
            or not isinstance(ui, dict)
            or ui.get("status") != "ready"
            or not isinstance(account, dict)
            or account.get("status") != "installed"
        ):
            raise MatrixError(f"supported plugin did not complete its lifecycle: {plugin_id}")
        print(
            f"Supported program {index}/{len(ordered)}: ready ({plugin_id}).",
            file=sys.stderr,
            flush=True,
        )
    after = _http_json("http://127.0.0.1:8799/api/plugins")
    current = {
        str(item.get("id")): item
        for item in after.get("plugins") or []
        if isinstance(item, dict)
    }
    if set(current) != expected or any(
        item.get("installed") is not True or item.get("needsRepair") is True
        for item in current.values()
    ):
        raise MatrixError("supported plugin inventory is not current after installation")
    return {"plugins": len(expected), "healthyServices": len(expected), "readyUis": len(expected)}


def _control_cycle() -> dict[str, int]:
    inventory = _http_json("http://127.0.0.1:8799/api/services")
    control_token = inventory.get("controlToken")
    if not isinstance(control_token, str) or len(control_token) < 20:
        raise MatrixError("Activity Center returned no control token")
    actions = 0
    for service_id in CHILD_SERVICES:
        for action, expected in (("stop", "stopped"), ("start", "running"), ("restart", "running")):
            response = _http_json(
                f"http://127.0.0.1:8799/api/services/{service_id}/{action}",
                method="POST",
                token=control_token,
            )
            service = response.get("service")
            if not isinstance(service, dict) or service.get("status") != expected:
                raise MatrixError(f"service {action} did not reach {expected}: {service_id}")
            actions += 1
    return {"services": len(CHILD_SERVICES), "actions": actions}


def _phase_checks(
    phase: str,
    *,
    platform_info,
    release_version: str,
    prior_phases: list[dict[str, Any]],
    desktop_evidence: Path | None,
) -> dict[str, Any]:
    paths = client_paths(platform_info=platform_info)
    local_path, account_path = _installed_states(paths)
    if phase == "baseline":
        if prior_phases:
            raise MatrixError("baseline must be the first recorded phase")
        if local_path.exists() or account_path.exists() or any(_port_open(port) for port in SERVICE_PORTS.values()):
            raise MatrixError("clean-user baseline is not empty")
        return {"cleanUser": True, "closedPorts": len(SERVICE_PORTS)}
    if phase == "previous-release":
        if prior_phases:
            raise MatrixError("previous-release must be the first recorded phase")
        local = _read_json(local_path)
        account = _read_json(account_path)
        versions = {local.get("releaseVersion"), account.get("releaseVersion")}
        if len(versions) != 1 or release_version in versions or None in versions:
            raise MatrixError("installed previous release baseline is invalid")
        return {"previousRelease": next(iter(versions))}
    passed = {item.get("phase") for item in prior_phases if item.get("status") == "passed"}
    if phase == "installed" and "baseline" not in passed:
        raise MatrixError("installed phase requires a passed clean-user baseline")
    if phase == "upgraded" and "previous-release" not in passed:
        raise MatrixError("upgraded phase requires a recorded previous release")
    if phase in {
        "controlled",
        "reinstalled",
        "repair-prepared",
        "repaired",
        "restarted",
        "live-ui",
        "uninstalled",
    } and not (
        passed & {"installed", "upgraded", "controlled", "reinstalled", "restarted"}
    ):
        raise MatrixError(f"{phase} phase requires an earlier candidate installation")
    if phase == "uninstalled":
        if local_path.exists() or account_path.exists():
            raise MatrixError("owned install state remains after uninstall")
        open_ports = [port for port in SERVICE_PORTS.values() if _port_open(port)]
        if open_ports:
            raise MatrixError("Extella-owned service ports remain open after uninstall")
        return {"ownedStateRemoved": True, "closedPorts": len(SERVICE_PORTS)}
    local = _read_json(local_path)
    account = _read_json(account_path)
    if local.get("status") != "installed" or account.get("status") != "installed":
        raise MatrixError("candidate installed state is incomplete")
    if local.get("releaseVersion") != release_version or account.get("releaseVersion") != release_version:
        raise MatrixError("installed release version differs from candidate")
    if phase == "reinstalled":
        if local.get("previousState", {}).get("releaseVersion") != release_version:
            raise MatrixError("local reinstall chain was not recorded")
        if account.get("previousState", {}).get("releaseVersion") != release_version:
            raise MatrixError("account reinstall chain was not recorded")
    if phase == "repaired":
        if "repair-prepared" not in passed:
            raise MatrixError("repaired phase requires a recorded repair preparation")
        repaired_toolbar = any(
            isinstance(change, dict)
            and change.get("kind") == "file"
            and Path(str(change.get("target") or "")).name == "toolbar.js"
            for change in local.get("changes") or []
        )
        if not repaired_toolbar:
            raise MatrixError("repair transaction did not restore the owned toolbar artifact")
    if phase == "upgraded":
        older = set(_state_versions(local)[1:] + _state_versions(account)[1:]) - {release_version}
        if not older:
            raise MatrixError("previous release is absent from the upgrade transaction chain")
    if phase == "restarted":
        previous_boots = {
            item.get("bootId")
            for item in prior_phases
            if item.get("status") == "passed" and item.get("phase") in CANDIDATE_PHASES
        }
        current_boot = _boot_marker(platform_info.system)
        if not previous_boots or current_boot in previous_boots:
            raise MatrixError("cold-restart phase was recorded without a new OS boot")
    managed_install = _install_supported_plugins() if phase in {"installed", "upgraded"} else None
    token = getpass.getpass("Extella token for read-only release verification (hidden): ").strip()
    report = verify_installed_client(token=token, platform_info=platform_info)
    checks: dict[str, Any] = {
        "files": report["local"],
        "services": report["services"],
        "account": report["account"],
    }
    if managed_install is not None:
        checks["supportedOnDemand"] = managed_install
    if phase == "controlled":
        checks["controlCycle"] = _control_cycle()
        # Prove all services returned to healthy/owned state after the cycle.
        checks["afterControl"] = verify_installed_client(
            token=token, platform_info=platform_info
        )["services"]
    if phase == "repair-prepared":
        toolbar = paths.toolbar_root / "toolbar.js"
        expected = _expected_file_hash(local, "toolbar.js")
        if not toolbar.is_file() or _sha256(toolbar) != expected:
            raise MatrixError("owned toolbar differs before repair preparation")
        toolbar.unlink()
        if toolbar.exists():
            raise MatrixError("could not prepare the reversible toolbar repair probe")
        checks["repairPrepared"] = {"artifact": "toolbar", "sha256": expected}
    if phase == "live-ui":
        if desktop_evidence is None or not desktop_evidence.is_file():
            raise MatrixError("live Extella UI phase requires a screenshot evidence file")
        if desktop_evidence.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
            raise MatrixError("live Extella UI evidence must be a PNG or JPEG screenshot")
        size = desktop_evidence.stat().st_size
        if size < 10_000:
            raise MatrixError("live Extella UI evidence file is unexpectedly small")
        checks["desktopEvidence"] = {"sha256": _sha256(desktop_evidence), "bytes": size}
    return checks


def run(args: argparse.Namespace) -> dict[str, Any]:
    platform_info = detect_platform()
    if not platform_info.supported or platform_info.key != args.expected_platform:
        raise MatrixError(
            f"runner platform differs from required row: expected {args.expected_platform}, got {platform_info.key or 'unsupported'}"
        )
    identity = _candidate_identity(args.candidate.resolve(), args.release_manifest.resolve())
    if args.result.exists():
        evidence = _read_json(args.result)
        expected_identity = evidence.get("candidate")
        if evidence.get("platform") != platform_info.key or expected_identity != identity:
            raise MatrixError("existing evidence belongs to another platform or candidate")
    else:
        evidence = {
            "schemaVersion": 1,
            "sessionId": secrets.token_hex(16),
            "platform": platform_info.key,
            "candidate": identity,
            "phases": [],
        }
    phases = evidence.get("phases")
    if not isinstance(phases, list):
        raise MatrixError("existing evidence phase list is invalid")
    if any(item.get("phase") == args.phase for item in phases if isinstance(item, dict)):
        raise MatrixError("this phase is already recorded")
    boot_id = _boot_marker(platform_info.system)
    started = int(time.time())
    try:
        checks = _phase_checks(
            args.phase,
            platform_info=platform_info,
            release_version=identity["releaseVersion"],
            prior_phases=phases,
            desktop_evidence=args.desktop_evidence,
        )
        event = {
            "phase": args.phase,
            "status": "passed",
            "startedAt": started,
            "finishedAt": int(time.time()),
            "bootId": boot_id,
            "checks": checks,
        }
    except Exception as error:
        event = {
            "phase": args.phase,
            "status": "failed",
            "startedAt": started,
            "finishedAt": int(time.time()),
            "bootId": boot_id,
            "errorClass": type(error).__name__,
            "message": str(error)[:300],
        }
    phases.append(event)
    evidence["phases"] = phases
    evidence["evidenceSha256"] = _sha256_bytes_for_evidence(evidence)
    _atomic_json(args.result, evidence)
    return event


def _sha256_bytes_for_evidence(evidence: Mapping[str, Any]) -> str:
    unsigned = {key: value for key, value in evidence.items() if key != "evidenceSha256"}
    encoded = json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Record one Extella external release-matrix phase")
    parser.add_argument("--phase", choices=sorted(PHASES), required=True)
    parser.add_argument(
        "--expected-platform",
        choices=("macos-x86_64", "macos-arm64", "windows11-x86_64"),
        required=True,
    )
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--release-manifest", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--desktop-evidence", type=Path)
    args = parser.parse_args()
    try:
        event = run(args)
    except Exception as error:
        print(
            json.dumps(
                {"status": "failed", "errorClass": type(error).__name__, "message": str(error)[:300]},
                ensure_ascii=False,
            )
        )
        return 2
    print(json.dumps(event, ensure_ascii=False, indent=2))
    return 0 if event["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
