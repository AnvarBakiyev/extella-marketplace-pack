#!/usr/bin/env python3
"""Accept complete, hash-bound external matrix results into release evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import time
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
PLATFORMS = {"macos-x86_64", "macos-arm64", "windows11-x86_64"}
CLEAN_PHASES = {
    "baseline",
    "installed",
    "controlled",
    "reinstalled",
    "repair-prepared",
    "repaired",
    "live-ui",
    "restarted",
    "uninstalled",
}
UPGRADE_PHASES = {
    "previous-release",
    "upgraded",
    "controlled",
    "live-ui",
    "restarted",
    "uninstalled",
}


class EvidenceImportError(RuntimeError):
    pass


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise EvidenceImportError("external evidence JSON is missing or invalid") from error
    if not isinstance(value, dict):
        raise EvidenceImportError("external evidence root must be an object")
    return value


def _digest_payload(value: Mapping[str, Any]) -> str:
    unsigned = {key: item for key, item in value.items() if key != "evidenceSha256"}
    encoded = json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _atomic_write(path: Path, value: Mapping[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(dict(value), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _expected_candidate(release: Mapping[str, Any]) -> dict[str, Any]:
    distribution = release.get("distribution")
    if not isinstance(distribution, dict):
        raise EvidenceImportError("release distribution contract is missing")
    return {
        "fileName": distribution.get("fileName"),
        "sha256": distribution.get("sha256"),
        "bytes": distribution.get("bytes"),
        "fileCount": distribution.get("fileCount"),
        "releaseVersion": release.get("version"),
        "sourceRepositories": {
            item.get("id"): item.get("revision")
            for item in release.get("sourceRepositories") or []
            if isinstance(item, dict)
        },
    }


def _validate_run(
    run: Mapping[str, Any],
    *,
    platform: str,
    candidate: Mapping[str, Any],
    required_phases: set[str],
) -> dict[str, Any]:
    if run.get("schemaVersion") != 1 or run.get("platform") != platform:
        raise EvidenceImportError("external evidence platform or schema differs")
    if run.get("candidate") != candidate:
        raise EvidenceImportError("external evidence belongs to another candidate")
    if run.get("evidenceSha256") != _digest_payload(run):
        raise EvidenceImportError("external evidence digest is invalid")
    phases = run.get("phases")
    if not isinstance(phases, list):
        raise EvidenceImportError("external evidence phase list is invalid")
    indexed = {
        phase.get("phase"): phase
        for phase in phases
        if isinstance(phase, dict) and isinstance(phase.get("phase"), str)
    }
    if len(indexed) != len(phases) or set(indexed) != required_phases:
        raise EvidenceImportError("external evidence does not contain the exact required phase set")
    if any(phase.get("status") != "passed" for phase in indexed.values()):
        raise EvidenceImportError("external evidence contains a non-passed phase")
    live = indexed["live-ui"].get("checks", {}).get("desktopEvidence", {})
    if not isinstance(live, dict) or len(str(live.get("sha256") or "")) != 64 or int(live.get("bytes") or 0) < 10_000:
        raise EvidenceImportError("live Extella screenshot evidence is incomplete")
    restarted_boot = indexed["restarted"].get("bootId")
    earlier_boots = {
        phase.get("bootId")
        for name, phase in indexed.items()
        if name not in {"restarted", "uninstalled"}
    }
    if not restarted_boot or restarted_boot in earlier_boots:
        raise EvidenceImportError("cold-restart evidence has no new OS boot marker")
    return {
        "sessionId": run.get("sessionId"),
        "evidenceSha256": run.get("evidenceSha256"),
        "desktopEvidenceSha256": live["sha256"],
    }


def import_evidence(
    *,
    platform: str,
    clean_result: Path,
    upgrade_result: Path,
    release_manifest: Path,
    verification_evidence: Path,
) -> dict[str, Any]:
    if platform not in PLATFORMS:
        raise EvidenceImportError("unsupported release-matrix platform")
    release = _read(release_manifest)
    evidence = _read(verification_evidence)
    candidate = _expected_candidate(release)
    clean = _validate_run(
        _read(clean_result),
        platform=platform,
        candidate=candidate,
        required_phases=CLEAN_PHASES,
    )
    upgrade = _validate_run(
        _read(upgrade_result),
        platform=platform,
        candidate=candidate,
        required_phases=UPGRADE_PHASES,
    )
    matrix = evidence.get("platformMatrix")
    if not isinstance(matrix, dict) or platform not in matrix:
        raise EvidenceImportError("release evidence matrix is incomplete")
    matrix[platform] = {
        "native_bootstrap": "passed",
        "clean_os_install": "passed",
        "clean_account": "passed",
        "service_control": "passed",
        "reinstall_repair_uninstall": "passed",
        "cold_restart": "passed",
        "upgrade_previous": "passed",
        "ui_live_extella": "passed",
    }
    external_runs = evidence.setdefault("externalRuns", {})
    if not isinstance(external_runs, dict):
        raise EvidenceImportError("externalRuns must be an object")
    external_runs[platform] = {
        "candidateSha256": candidate["sha256"],
        "clean": clean,
        "upgrade": upgrade,
        "importedAt": int(time.time()),
    }
    verification = release.get("verification")
    if not isinstance(verification, dict) or not isinstance(verification.get("matrix"), dict):
        raise EvidenceImportError("release verification matrix is incomplete")
    verification["matrix"][platform] = "passed"
    _atomic_write(verification_evidence, evidence)
    _atomic_write(release_manifest, release)
    return {"status": "accepted", "platform": platform, "clean": clean, "upgrade": upgrade}


def main() -> int:
    parser = argparse.ArgumentParser(description="Accept Extella external release evidence")
    parser.add_argument("--platform", choices=sorted(PLATFORMS), required=True)
    parser.add_argument("--clean-result", type=Path, required=True)
    parser.add_argument("--upgrade-result", type=Path, required=True)
    parser.add_argument("--release-manifest", type=Path, default=ROOT / "release/release-manifest.json")
    parser.add_argument(
        "--verification-evidence",
        type=Path,
        default=ROOT / "release/verification-evidence.json",
    )
    args = parser.parse_args()
    try:
        report = import_evidence(**vars(args))
    except Exception as error:
        print(json.dumps({"status": "failed", "errorClass": type(error).__name__, "message": str(error)[:300]}))
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
