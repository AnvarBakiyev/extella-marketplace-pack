#!/usr/bin/env python3
"""Fail-closed release gate for the Extella desktop distribution.

The gate intentionally uses only the Python standard library so it can run on
a clean build worker before any project dependencies are installed. JSON Schema
files are the public contract; this module enforces the security and cross-file
invariants that JSON Schema cannot express by itself.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable


SUPPORTED_PLATFORMS = {
    "macos-x86_64",
    "macos-arm64",
    "windows11-x86_64",
}
CLASSIFICATIONS = {"bundled", "supported_on_demand", "third_party_unverified"}
SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$")
PLUGIN_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{1,79}$")
SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
PERSONAL_PATH = re.compile(
    r"(?:/Users/[^/$\s]+|/home/(?:ubuntu|anvarbakiyev)(?:/|$)|[A-Za-z]:\\Users\\[^\\$\s]+)",
    re.IGNORECASE,
)
AGENT_ID = re.compile(r"\bagent_[A-Za-z0-9_-]{8,}\b")
DEVICE_ID = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)
ALLOWED_AGENT_IDS = {
    "agent_extella_alibaba_default",
    "agent_extella_default",
    "agent_XXXXXXXX",
}


def _looks_account_specific_agent(value: str) -> bool:
    suffix = value.removeprefix("agent_")
    return any(character.isupper() or character.isdigit() or character == "-" for character in suffix)


@dataclass(frozen=True)
class Issue:
    code: str
    path: str
    message: str


def _read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _walk_strings(value: Any, location: str = "$") -> Iterable[tuple[str, str]]:
    if isinstance(value, str):
        yield location, value
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _walk_strings(item, f"{location}[{index}]")
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _walk_strings(item, f"{location}.{key}")


def _required_object(
    data: dict[str, Any], key: str, path: Path, issues: list[Issue]
) -> dict[str, Any]:
    value = data.get(key)
    if not isinstance(value, dict):
        issues.append(Issue("manifest.required_object", str(path), f"{key} must be an object"))
        return {}
    return value


def validate_plugin(path: Path) -> list[Issue]:
    issues: list[Issue] = []
    try:
        data = _read_json(path)
    except (OSError, json.JSONDecodeError) as exc:
        return [Issue("manifest.invalid_json", str(path), str(exc))]
    if not isinstance(data, dict):
        return [Issue("manifest.root", str(path), "manifest root must be an object")]

    required = {
        "schemaVersion", "id", "name", "version", "classification", "source",
        "supportedPlatforms", "install", "runtime", "ui", "artifacts", "experts",
        "secrets", "uninstall", "migration", "releaseState",
    }
    for key in sorted(required - set(data)):
        issues.append(Issue("manifest.missing", str(path), f"missing required field: {key}"))

    if data.get("schemaVersion") != 1:
        issues.append(Issue("manifest.schema_version", str(path), "schemaVersion must be 1"))
    if not isinstance(data.get("id"), str) or not PLUGIN_ID.fullmatch(data.get("id", "")):
        issues.append(Issue("manifest.id", str(path), "id is not portable/canonical"))
    if not isinstance(data.get("version"), str) or not SEMVER.fullmatch(data.get("version", "")):
        issues.append(Issue("manifest.version", str(path), "version must be semantic"))
    if data.get("classification") not in CLASSIFICATIONS:
        issues.append(Issue("manifest.classification", str(path), "unsupported classification"))

    platforms = data.get("supportedPlatforms")
    if not isinstance(platforms, list) or not platforms:
        issues.append(Issue("manifest.platforms", str(path), "supportedPlatforms must be non-empty"))
    elif not set(platforms).issubset(SUPPORTED_PLATFORMS):
        issues.append(Issue("manifest.platforms", str(path), "manifest advertises an unsupported platform"))

    install = _required_object(data, "install", path, issues)
    if install.get("idempotent") is not True:
        issues.append(Issue("install.idempotent", str(path), "supported installs must be idempotent"))
    if install.get("transactional") is not True:
        issues.append(Issue("install.transactional", str(path), "supported installs must be transactional"))

    runtime = _required_object(data, "runtime", path, issues)
    if "ready" in runtime:
        issues.append(Issue("runtime.static_ready", str(path), "static ready is forbidden"))
    if runtime.get("kind") == "local_service":
        health = runtime.get("health")
        pid = runtime.get("pid")
        command = runtime.get("command")
        if not isinstance(health, dict) or health.get("type") != "http" or not health.get("path"):
            issues.append(Issue("runtime.health", str(path), "local services require an HTTP health check"))
        if not isinstance(pid, dict) or pid.get("strategy") == "none":
            issues.append(Issue("runtime.pid", str(path), "local services require owned PID tracking"))
        if not isinstance(command, list) or not command:
            issues.append(Issue("runtime.command", str(path), "local services require argv command templates"))

    release_state = _required_object(data, "releaseState", path, issues)
    if release_state.get("advertised") is True and release_state.get("verification") != "verified":
        issues.append(Issue("release.unverified_advertisement", str(path), "only verified capabilities may be advertised"))

    for location, text in _walk_strings(data):
        if PERSONAL_PATH.search(text):
            issues.append(Issue("security.personal_path", str(path), f"personal path at {location}"))
        if DEVICE_ID.search(text):
            issues.append(Issue("security.device_id", str(path), f"device id at {location}"))
        for match in AGENT_ID.findall(text):
            if match not in ALLOWED_AGENT_IDS and _looks_account_specific_agent(match):
                issues.append(Issue("security.agent_id", str(path), f"account-specific agent id at {location}"))

    return issues


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_release(root: Path, manifest_path: Path) -> list[Issue]:
    issues: list[Issue] = []
    try:
        data = _read_json(manifest_path)
    except (OSError, json.JSONDecodeError) as exc:
        return [Issue("release.invalid_json", str(manifest_path), str(exc))]
    if not isinstance(data, dict):
        return [Issue("release.root", str(manifest_path), "release root must be an object")]

    required = {
        "schemaVersion", "releaseId", "version", "status", "supportedPlatforms",
        "sourceRepositories", "artifacts", "capabilities", "installers", "verification",
    }
    for key in sorted(required - set(data)):
        issues.append(Issue("release.missing", str(manifest_path), f"missing required field: {key}"))
    if data.get("schemaVersion") != 1 or data.get("releaseId") != "extella-client":
        issues.append(Issue("release.identity", str(manifest_path), "unsupported release contract"))
    if not isinstance(data.get("version"), str) or not SEMVER.fullmatch(data.get("version", "")):
        issues.append(Issue("release.version", str(manifest_path), "version must be semantic"))
    if set(data.get("supportedPlatforms") or []) != SUPPORTED_PLATFORMS:
        issues.append(Issue("release.platforms", str(manifest_path), "release must target exactly the approved matrix"))

    for source in data.get("sourceRepositories") or []:
        if not isinstance(source, dict) or not SHA40.fullmatch(str(source.get("revision", ""))):
            issues.append(Issue("release.source_revision", str(manifest_path), "every source revision must be a full Git SHA"))

    artifact_ids: set[str] = set()
    for artifact in data.get("artifacts") or []:
        if not isinstance(artifact, dict):
            issues.append(Issue("artifact.object", str(manifest_path), "artifact must be an object"))
            continue
        artifact_id = str(artifact.get("id", ""))
        if not artifact_id or artifact_id in artifact_ids:
            issues.append(Issue("artifact.id", str(manifest_path), f"duplicate/empty artifact id: {artifact_id}"))
        artifact_ids.add(artifact_id)
        rel = artifact.get("path")
        target = root / rel if isinstance(rel, str) else None
        if target is None or not target.is_file():
            issues.append(Issue("artifact.missing", str(manifest_path), f"artifact not found: {rel}"))
            continue
        expected_size = artifact.get("bytes")
        expected_sha = artifact.get("sha256")
        if expected_size != target.stat().st_size:
            issues.append(Issue("artifact.bytes", str(target), "artifact size does not match manifest"))
        if not isinstance(expected_sha, str) or not SHA256.fullmatch(expected_sha) or _sha256(target) != expected_sha:
            issues.append(Issue("artifact.sha256", str(target), "artifact SHA-256 does not match manifest"))

    capabilities = data.get("capabilities") or []
    for capability in capabilities:
        if not isinstance(capability, dict):
            issues.append(Issue("capability.object", str(manifest_path), "capability must be an object"))
            continue
        plugin_path = root / str(capability.get("manifest", ""))
        plugin_issues = validate_plugin(plugin_path)
        issues.extend(plugin_issues)
        if plugin_path.is_file():
            plugin = _read_json(plugin_path)
            if plugin.get("id") != capability.get("id"):
                issues.append(Issue("capability.id", str(plugin_path), "capability id differs from plugin manifest"))
            if plugin.get("classification") != capability.get("classification"):
                issues.append(Issue("capability.classification", str(plugin_path), "classification differs from release manifest"))

    verification = data.get("verification") or {}
    matrix = verification.get("matrix") if isinstance(verification, dict) else {}
    if data.get("status") == "released" and (
        not isinstance(matrix, dict) or any(matrix.get(p) != "passed" for p in SUPPORTED_PLATFORMS)
    ):
        issues.append(Issue("release.matrix", str(manifest_path), "released status requires a passed platform matrix"))

    return issues


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--manifest", type=Path, default=Path("release/release-manifest.json"))
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    manifest = args.manifest if args.manifest.is_absolute() else root / args.manifest
    issues = validate_release(root, manifest)
    if args.as_json:
        print(json.dumps({"status": "failed" if issues else "passed", "issues": [asdict(i) for i in issues]}, indent=2))
    else:
        for issue in issues:
            print(f"ERROR {issue.code}: {issue.path}: {issue.message}")
        print(f"release gate: {'FAILED' if issues else 'PASSED'} ({len(issues)} issue(s))")
    return 1 if issues else 0


if __name__ == "__main__":
    sys.exit(main())
