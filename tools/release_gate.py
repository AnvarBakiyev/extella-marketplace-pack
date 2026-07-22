#!/usr/bin/env python3
"""Fail-closed release gate for the Extella desktop distribution.

The gate intentionally uses only the Python standard library so it can run on
a clean build worker before any project dependencies are installed. JSON Schema
files are the public contract; this module enforces the security and cross-file
invariants that JSON Schema cannot express by itself.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import subprocess
import sys
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping


SUPPORTED_PLATFORMS = {
    "macos-x86_64",
    "macos-arm64",
    "windows11-x86_64",
}
EVIDENCE_SCENARIOS = {
    "native_bootstrap",
    "clean_os_install",
    "clean_account",
    "service_control",
    "reinstall_repair_uninstall",
    "cold_restart",
    "upgrade_previous",
    "ui_live_extella",
}
REQUIRED_BUNDLE_PAYLOAD = frozenset(
    {
        "payload/marketplace/installer/client_verify.py",
        "payload/marketplace/installer/verification.py",
        "payload/marketplace/tools/external_matrix.py",
        "payload/marketplace/runtime/pinokio_recipe_resolver.js",
    }
)
CLASSIFICATIONS = {"bundled", "supported_on_demand", "third_party_unverified"}
SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$")
PLUGIN_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{1,79}$")
SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
PERSONAL_PATH = re.compile(
    r"(?:/Users/[A-Za-z0-9._-]+(?:/|$)|/home/(?:ubuntu|anvarbakiyev)(?:/|$)|[A-Za-z]:\\Users\\[A-Za-z0-9._-]+(?:\\|$))",
    re.IGNORECASE,
)
AGENT_ID = re.compile(r"\bagent_[A-Za-z0-9_-]{8,}\b")
DEVICE_ID = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)
ALLOWED_AGENT_IDS = {
    "agent_XXXXXXXX",
}
STATIC_AGENT_SCOPE = re.compile(r"\bagent_extella_(?:default|alibaba_default)\b")
SECRET_ASSIGNMENT = re.compile(
    r"(?i)(?:auth[_-]?token|api[_-]?key|secret|password)\s*[:=]\s*['\"][A-Za-z0-9_./+\-=]{16,}['\"]"
)
FORBIDDEN_SOURCE = {
    "security.tls_verification_disabled": re.compile(
        r"check_hostname\s*=\s*False|CERT_NONE"
    ),
    "security.mutable_source": re.compile(
        r"raw\.githubusercontent\.com/[^\s'\"]+/(?:main|master)/|refs/heads/(?:main|master)"
    ),
}
CAP_LEGACY_DEPENDENCY_SOURCE = {
    "dependency.direct_which": re.compile(r"shutil\.which\s*\("),
    "dependency.fixed_homebrew_path": re.compile(r"/(?:opt/homebrew|usr/local)/bin/"),
    "dependency.direct_brew": re.compile(r"subprocess\.(?:run|Popen)\s*\(\s*\[\s*brew\b"),
    "dependency.direct_pip_install": re.compile(
        r"(?:pip[\"']\s*,\s*[\"']install|[\"']-m[\"']\s*,\s*[\"']pip[\"']\s*,\s*[\"']install)"
    ),
}
SHIPPED_EXPERT_PORTABILITY_SOURCE = {
    "portability.legacy_home_path": re.compile(r"~/|Path\.home\s*\("),
    "portability.legacy_extella_env": re.compile(r"EXTELLA_(?:WIZARD|PLUGIN)_ROOT"),
    "portability.temporary_runtime_path": re.compile(r"/(?:var/)?tmp/"),
    "dependency.fixed_tool_path": re.compile(r"/(?:opt/homebrew|usr/local|usr/bin)/"),
    "dependency.direct_which": re.compile(r"shutil\.which\s*\("),
    "dependency.current_interpreter": re.compile(r"sys\.executable"),
    "runtime.unowned_shell": re.compile(r"shell\s*=\s*True"),
    "runtime.unsafe_kill": re.compile(r"(?:pkill\b|kill\s+-9|os\.kill\s*\()"),
    "runtime.static_ready": re.compile(
        r'["\']service["\']\s*:\s*\{[^}]*["\']ready["\']\s*:\s*True', re.DOTALL
    ),
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
    if data.get("classification") == "bundled":
        entrypoints = install.get("entrypoints") if isinstance(install.get("entrypoints"), dict) else {}
        if set(entrypoints.values()) != {"installer/client_install.py"}:
            issues.append(
                Issue(
                    "install.unified_entrypoint",
                    str(path),
                    "bundled capabilities must use the unified client installer",
                )
            )
        uninstall = data.get("uninstall") if isinstance(data.get("uninstall"), dict) else {}
        if uninstall.get("entrypoint") != "installer/client_uninstall.py":
            issues.append(
                Issue(
                    "uninstall.unified_entrypoint",
                    str(path),
                    "bundled capabilities must use the unified client uninstaller",
                )
            )

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
        if STATIC_AGENT_SCOPE.search(text):
            issues.append(Issue("security.static_agent_scope", str(path), f"static agent scope at {location}"))
        for match in AGENT_ID.findall(text):
            if match not in ALLOWED_AGENT_IDS and _looks_account_specific_agent(match):
                issues.append(Issue("security.agent_id", str(path), f"account-specific agent id at {location}"))

    return issues


def _expert_source_map(root: Path, wizard_root: Path) -> tuple[dict[str, Path], list[Issue]]:
    issues: list[Issue] = []
    selected: dict[str, Path] = {}
    hashes: dict[str, str] = {}
    paths = [
        *root.glob("experts/*.py"),
        *root.glob("platform_experts/*.py"),
        *root.glob("automations/experts/*.py"),
        *wizard_root.glob("experts/*.py"),
    ]
    for path in sorted(paths, key=lambda item: item.as_posix()):
        digest = _sha256(path)
        if path.stem in hashes and hashes[path.stem] != digest:
            issues.append(
                Issue("expert.conflicting_source", str(path), f"conflicting source for {path.stem}")
            )
        else:
            hashes[path.stem] = digest
            selected[path.stem] = path
    return selected, issues


def validate_expert_contract(root: Path, wizard_root: Path) -> list[Issue]:
    issues: list[Issue] = []
    inventory_path = root / "release/expert-classification.json"
    try:
        inventory = _read_json(inventory_path)
    except (OSError, json.JSONDecodeError) as exc:
        return [Issue("expert.inventory", str(inventory_path), str(exc))]
    keys = ("bundled", "supportedOnDemand", "thirdPartyUnverified")
    classified: dict[str, str] = {}
    for key in keys:
        values = inventory.get(key) if isinstance(inventory, dict) else None
        if not isinstance(values, list) or values != sorted(values) or len(values) != len(set(values)):
            issues.append(Issue("expert.inventory_order", str(inventory_path), f"{key} must be sorted and unique"))
            continue
        for value in values:
            if not isinstance(value, str) or value in classified:
                issues.append(Issue("expert.inventory_duplicate", str(inventory_path), str(value)))
            else:
                classified[value] = key
    sources, source_issues = _expert_source_map(root, wizard_root)
    issues.extend(source_issues)
    if set(sources) != set(classified):
        missing = sorted(set(sources) - set(classified))
        stale = sorted(set(classified) - set(sources))
        issues.append(
            Issue(
                "expert.inventory_exact",
                str(inventory_path),
                f"classification must exactly cover sources; missing={missing[:8]} stale={stale[:8]}",
            )
        )
    manifest_sets = {"bundled": set(), "supportedOnDemand": set()}
    for path in sorted((root / "release/plugins").glob("*.json")):
        try:
            plugin = _read_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        experts = plugin.get("experts") if isinstance(plugin.get("experts"), dict) else {}
        names = set(experts.get("required") or []) | set(experts.get("smoke") or [])
        if plugin.get("classification") == "bundled":
            manifest_sets["bundled"].update(names)
        elif plugin.get("classification") == "supported_on_demand":
            manifest_sets["supportedOnDemand"].update(names)
    for key in manifest_sets:
        if manifest_sets[key] != set(inventory.get(key) or []):
            issues.append(
                Issue("expert.manifest_union", str(inventory_path), f"{key} differs from plugin contracts")
            )
    for name in inventory.get("bundled") or []:
        path = sources.get(name)
        if path is None:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for code, pattern in FORBIDDEN_SOURCE.items():
            if pattern.search(text):
                issues.append(Issue(code, str(path), f"forbidden pattern in bundled expert {name}"))
        if not re.search(rf"(?m)^def[ \t]+{re.escape(name)}[ \t]*\(", text):
            issues.append(Issue("expert.entrypoint", str(path), f"entrypoint {name} was not found"))
    return issues


def validate_cap_dependency_contract(root: Path) -> list[Issue]:
    """Every shipped cap_* dependency must route through one runtime bridge."""

    issues: list[Issue] = []
    for path in sorted((root / "experts").glob("cap_*.py")):
        text = path.read_text(encoding="utf-8", errors="replace")
        try:
            compile(text, str(path), "exec")
        except SyntaxError as error:
            issues.append(Issue("dependency.cap_syntax", str(path), str(error)))
            continue
        uses_external_dependency = path.name != "cap_local_ask.py"
        if uses_external_dependency and "extella_expert_bridge" not in text:
            issues.append(
                Issue(
                    "dependency.cap_bridge",
                    str(path),
                    "capability bypasses the shared Extella dependency bridge",
                )
            )
        for code, pattern in CAP_LEGACY_DEPENDENCY_SOURCE.items():
            if pattern.search(text):
                issues.append(
                    Issue(code, str(path), "capability contains a private dependency resolver")
                )
    return issues


def validate_shipped_expert_portability(root: Path, wizard_root: Path) -> list[Issue]:
    """Reject device-specific paths and private process control in every shipped expert."""

    issues: list[Issue] = []
    paths = [
        *root.glob("experts/*.py"),
        *root.glob("platform_experts/*.py"),
        *root.glob("automations/experts/*.py"),
        *wizard_root.glob("experts/*.py"),
    ]
    for path in sorted(set(paths), key=lambda item: item.as_posix()):
        text = path.read_text(encoding="utf-8", errors="replace")
        if PERSONAL_PATH.search(text):
            issues.append(Issue("security.personal_path", str(path), "personal path in shipped expert"))
        if STATIC_AGENT_SCOPE.search(text):
            issues.append(Issue("security.static_agent_scope", str(path), "static account scope in shipped expert"))
        for code, pattern in SHIPPED_EXPERT_PORTABILITY_SOURCE.items():
            if pattern.search(text):
                issues.append(Issue(code, str(path), "non-portable runtime behavior in shipped expert"))
    return issues


def _shipped_runtime_files(root: Path, wizard_root: Path) -> list[Path]:
    patterns = (
        "installer/**/*.py",
        "runtime/**/*.py",
        "device/activity-center/bridge/*.py",
        "device/activity-center/instrumentation/*.py",
        "automations/ui/**/*.py",
        "toolbar/toolbar.js",
    )
    wizard_patterns = (
        "ui/*.py",
        "dist/workspace/*.py",
        "agents/*.instructions.md",
        "rules/*.md",
        "concepts/*.md",
    )
    files = [path for pattern in patterns for path in root.glob(pattern) if path.is_file()]
    files.extend(
        path for pattern in wizard_patterns for path in wizard_root.glob(pattern) if path.is_file()
    )
    return sorted(set(files), key=lambda path: path.as_posix())


def _actual_python_security_issues(path: Path, text: str) -> list[Issue]:
    """AST checks avoid mistaking safety prompts/linter markers for executable behavior."""

    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError as error:
        return [Issue("runtime.python_syntax", str(path), str(error))]
    issues: list[Issue] = []
    seen: set[str] = set()

    def emit(code: str, message: str) -> None:
        if code not in seen:
            seen.add(code)
            issues.append(Issue(code, str(path), message))

    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "CERT_NONE":
            emit("security.tls_verification_disabled", "runtime selects ssl.CERT_NONE")
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            value = node.value
            if (
                isinstance(value, ast.Constant)
                and value.value is False
                and any(isinstance(target, ast.Attribute) and target.attr == "check_hostname" for target in targets)
            ):
                emit("security.tls_verification_disabled", "runtime disables TLS hostname verification")
        if isinstance(node, ast.Call):
            if (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "_create_unverified_context"
            ):
                emit("security.tls_verification_disabled", "runtime creates an unverified TLS context")
            if any(
                keyword.arg == "shell"
                and isinstance(keyword.value, ast.Constant)
                and keyword.value.value is True
                for keyword in node.keywords
            ):
                emit("runtime.unowned_shell", "runtime executes a subprocess with shell=True")
    return issues


def validate_shipped_runtime_security(root: Path, wizard_root: Path) -> list[Issue]:
    """Validate every Python/JS/document source that enters the client bundle."""

    issues: list[Issue] = []
    for path in _shipped_runtime_files(root, wizard_root):
        text = path.read_text(encoding="utf-8", errors="replace")
        if PERSONAL_PATH.search(text):
            issues.append(Issue("security.personal_path", str(path), "personal path in shipped runtime"))
        if STATIC_AGENT_SCOPE.search(text):
            issues.append(Issue("security.static_agent_scope", str(path), "static account scope in shipped runtime"))
        if SECRET_ASSIGNMENT.search(text):
            issues.append(Issue("security.literal_secret", str(path), "possible literal secret in shipped runtime"))
        if path.suffix == ".py":
            issues.extend(_actual_python_security_issues(path, text))
    return issues


def validate_evidence(root: Path, release: dict[str, Any]) -> list[Issue]:
    path = root / "release/verification-evidence.json"
    try:
        evidence = _read_json(path)
    except (OSError, json.JSONDecodeError) as exc:
        return [Issue("evidence.invalid", str(path), str(exc))]
    issues: list[Issue] = []
    if evidence.get("schemaVersion") != 1 or evidence.get("releaseVersion") != release.get("version"):
        issues.append(Issue("evidence.identity", str(path), "evidence version differs from release"))
    matrix = evidence.get("platformMatrix") if isinstance(evidence.get("platformMatrix"), dict) else {}
    if set(matrix) != SUPPORTED_PLATFORMS:
        issues.append(Issue("evidence.platforms", str(path), "evidence must cover the exact platform matrix"))
    allowed = {"pending", "passed", "failed", "blocked_external"}
    for platform_key, scenarios in matrix.items():
        if not isinstance(scenarios, dict) or not scenarios:
            issues.append(Issue("evidence.scenarios", str(path), f"missing scenarios for {platform_key}"))
            continue
        if set(scenarios) != EVIDENCE_SCENARIOS:
            issues.append(
                Issue(
                    "evidence.scenarios_exact",
                    str(path),
                    f"{platform_key} must cover the exact external scenario contract",
                )
            )
        for scenario, status in scenarios.items():
            if not PLUGIN_ID.fullmatch(str(scenario).replace("_", "-")) or status not in allowed:
                issues.append(Issue("evidence.status", str(path), f"invalid evidence row: {platform_key}/{scenario}"))
    external_runs = evidence.get("externalRuns")
    if not isinstance(external_runs, dict) or not set(external_runs).issubset(SUPPORTED_PLATFORMS):
        issues.append(Issue("evidence.external_runs", str(path), "externalRuns must be keyed by supported platform"))
        external_runs = {}
    fully_passed = {
        platform_key
        for platform_key, scenarios in matrix.items()
        if isinstance(scenarios, dict) and scenarios and all(status == "passed" for status in scenarios.values())
    }
    release_distribution = release.get("distribution") if isinstance(release.get("distribution"), dict) else {}
    for platform_key in fully_passed:
        run = external_runs.get(platform_key)
        if not isinstance(run, dict) or run.get("candidateSha256") != release_distribution.get("sha256"):
            issues.append(
                Issue(
                    "evidence.external_candidate",
                    str(path),
                    f"fully passed row has no exact external candidate evidence: {platform_key}",
                )
            )
            continue
        for track in ("clean", "upgrade"):
            value = run.get(track)
            if not isinstance(value, dict) or not SHA256.fullmatch(str(value.get("evidenceSha256") or "")) or not SHA256.fullmatch(str(value.get("desktopEvidenceSha256") or "")):
                issues.append(
                    Issue(
                        "evidence.external_track",
                        str(path),
                        f"external {track} evidence is incomplete: {platform_key}",
                    )
                )
    if release.get("status") == "released":
        not_passed = [
            f"{platform_key}/{scenario}"
            for platform_key, scenarios in matrix.items()
            for scenario, status in scenarios.items()
            if status != "passed"
        ]
        if not_passed:
            issues.append(
                Issue("evidence.release_incomplete", str(path), f"released evidence is incomplete: {not_passed[:8]}")
            )
        if set(external_runs) != SUPPORTED_PLATFORMS:
            issues.append(
                Issue(
                    "evidence.external_exact",
                    str(path),
                    "released evidence requires accepted clean and upgrade runs on every supported platform",
                )
            )
    return issues


def validate_catalog_policy(root: Path, wizard_root: Path | None = None) -> list[Issue]:
    path = root / "release/catalog-policy.json"
    try:
        policy = _read_json(path)
    except (OSError, json.JSONDecodeError) as exc:
        return [Issue("catalog.policy", str(path), str(exc))]
    issues: list[Issue] = []
    expected = {"_mkt_apps", "_mkt_loc", "_mkt_mcp", "_mkt_models", "_mkt_programs"}
    sources = policy.get("sources") if isinstance(policy.get("sources"), dict) else {}
    if policy.get("schemaVersion") != 1 or set(sources) != expected:
        issues.append(Issue("catalog.policy_exact", str(path), "catalog policy must cover all live sources"))
    if policy.get("supportedOnDemand"):
        issues.append(Issue("catalog.on_demand", str(path), "on-demand catalog is non-empty without release-gated manifests"))
    for key, value in sources.items():
        if not isinstance(value, dict) or value.get("classification") != "third_party_unverified":
            issues.append(Issue("catalog.classification", str(path), f"{key} is not classified"))
        if isinstance(value, dict) and value.get("advertisedAsGuaranteed") is not False:
            issues.append(Issue("catalog.advertisement", str(path), f"{key} is advertised as guaranteed"))
    visibility = policy.get("visibility") if isinstance(policy.get("visibility"), dict) else {}
    if visibility.get("hideField") != "hidden" or visibility.get("hideWhenTrue") is not True:
        issues.append(Issue("catalog.visibility", str(path), "stale-item hiding contract is missing"))

    for filename in ("models_catalog.json", "apps_catalog.json", "mcp_catalog.json"):
        catalog_path = root / filename
        try:
            catalog = _read_json(catalog_path)
        except (OSError, json.JSONDecodeError) as exc:
            issues.append(Issue("catalog.invalid", str(catalog_path), str(exc)))
            continue
        if not isinstance(catalog, dict):
            issues.append(Issue("catalog.root", str(catalog_path), "catalog must be a mapping"))
            continue
        cards = [
            card
            for shard in catalog.values()
            if isinstance(shard, dict)
            for key in ("heroes", "shelf", "items")
            for card in (shard.get(key) or [])
            if isinstance(card, dict)
        ]
        if not cards:
            issues.append(Issue("catalog.empty", str(catalog_path), "catalog has no classified cards"))
        for index, card in enumerate(cards):
            if card.get("classification") != "third_party_unverified":
                issues.append(
                    Issue(
                        "catalog.item_classification",
                        str(catalog_path),
                        f"card {index} is not explicitly third-party unverified",
                    )
                )
            if not isinstance(card.get("hidden"), bool):
                issues.append(
                    Issue(
                        "catalog.item_visibility",
                        str(catalog_path),
                        f"card {index} has no boolean hidden control",
                    )
                )
            label = str(card.get("label") or "").casefold()
            claims_verified = (
                "работает" in label
                or "проверено extella" in label
                or (re.search(r"\bverified\b", label) is not None and "unverified" not in label)
            )
            if claims_verified:
                issues.append(
                    Issue(
                        "catalog.item_advertisement",
                        str(catalog_path),
                        f"card {index} is advertised as verified",
                    )
                )

    composer_path = root / "composer_catalog.json"
    try:
        composer = _read_json(composer_path)
    except (OSError, json.JSONDecodeError) as exc:
        issues.append(Issue("catalog.composer", str(composer_path), str(exc)))
        return issues
    blocks = composer.get("blocks") if isinstance(composer, dict) else None
    if not isinstance(blocks, list) or not blocks:
        issues.append(Issue("catalog.composer", str(composer_path), "composer catalog has no blocks"))
        return issues
    expert_roots = [root / "experts", root / "platform_experts", root / "automations/experts"]
    if wizard_root is not None:
        expert_roots.append(wizard_root / "experts")
    expert_names = {item.stem for directory in expert_roots for item in directory.glob("*.py")}
    for index, block in enumerate(blocks):
        block_id = str(block.get("id") or "") if isinstance(block, dict) else ""
        if block_id not in expert_names:
            issues.append(
                Issue(
                    "catalog.composer_expert",
                    str(composer_path),
                    f"block {index} references missing expert {block_id or '<empty>'}",
                )
            )
        for location, value in _walk_strings(block, f"$.blocks[{index}]"):
            if "~/" in value or PERSONAL_PATH.search(value):
                issues.append(
                    Issue(
                        "catalog.composer_path",
                        str(composer_path),
                        f"block uses a non-native path at {location}",
                    )
                )
    return issues


def validate_lifecycle_entrypoints(root: Path) -> list[Issue]:
    """Reject stale installers and independently mutating component entrypoints."""

    issues: list[Issue] = []
    required_markers = {
        root / "install.py": "legacy_installer_retired",
        root / "install_toolbar.sh": "toolbar/install-all.sh",
        root / "toolbar/install.sh": "install-all.sh",
        root / "toolbar/install.ps1": "install-all.ps1",
        root / "toolbar/Install-Extella.command": "install-all.sh",
        root / "toolbar/Install-Extella.bat": "install-all.ps1",
        root / "toolbar/fix-certs.sh": "legacy_certificate_repair_retired",
        root / "device/activity-center/install.py": "standalone_component_installer_retired",
        root / "device/activity-center/uninstall.py": "standalone_component_uninstaller_retired",
    }
    for path, marker in required_markers.items():
        try:
            source = path.read_text(encoding="utf-8")
        except OSError as exc:
            issues.append(Issue("lifecycle.entrypoint", str(path), str(exc)))
            continue
        if marker not in source:
            issues.append(
                Issue(
                    "lifecycle.stale_entrypoint",
                    str(path),
                    "legacy entrypoint does not delegate to or fail closed for the unified installer",
                )
            )
        if re.search(r"raw\.githubusercontent\.com/.*/(?:main|master)", source):
            issues.append(Issue("security.mutable_source", str(path), "installer fetches a raw branch"))

    forbidden_paths = (
        root / "toolbar/Install-Extella-mac.zip",
        root / "device/boot/restart_local_servers.py",
        root / "automations/registries/extella_contract_agent.json",
        root / "automations/registries/extella_travel_agency.json",
    )
    for path in forbidden_paths:
        if path.exists():
            issues.append(
                Issue(
                    "lifecycle.stale_copy",
                    str(path),
                    "obsolete installer/runtime copy must not coexist with the unified lifecycle",
                )
            )

    version_path = root / "toolbar/version.json"
    try:
        version = _read_json(version_path)
    except (OSError, json.JSONDecodeError) as exc:
        issues.append(Issue("lifecycle.update_policy", str(version_path), str(exc)))
    else:
        if not isinstance(version, dict) or version.get("updatesEnabled") is not False:
            issues.append(
                Issue(
                    "lifecycle.update_policy",
                    str(version_path),
                    "raw toolbar auto-update must remain disabled",
                )
            )
    return issues


def validate_wizard_lifecycle(wizard_root: Path) -> list[Issue]:
    """Ensure Wizard cannot bypass the verified client lifecycle."""

    issues: list[Issue] = []
    retired = {
        wizard_root / "install.py": "legacy_wizard_installer_retired",
        wizard_root / "extella-update.sh": "legacy_wizard_updater_retired",
        wizard_root / "scripts/release.sh": "legacy_wizard_release_script_retired",
        wizard_root / "scripts/deploy.sh": "legacy_wizard_live_deploy_retired",
        wizard_root / "scripts/qa_delta_update.sh": "legacy_wizard_delta_updater_retired",
        wizard_root / "scripts/publish_release.py": "legacy_wizard_kv_publisher_retired",
        wizard_root / "scripts/register_app_cards.py": "legacy_wizard_registry_writer_retired",
    }
    for path, marker in retired.items():
        try:
            source = path.read_text(encoding="utf-8")
        except OSError as exc:
            issues.append(Issue("lifecycle.wizard_entrypoint", str(path), str(exc)))
            continue
        if marker not in source:
            issues.append(
                Issue(
                    "lifecycle.wizard_stale_entrypoint",
                    str(path),
                    "Wizard entrypoint must fail closed for the unified installer",
                )
            )
        if re.search(r"raw\.githubusercontent\.com/.*/(?:main|master)", source):
            issues.append(Issue("security.mutable_source", str(path), "Wizard entrypoint fetches a raw branch"))

    obsolete_manifest = wizard_root / "extella-plugin.json"
    if obsolete_manifest.exists():
        issues.append(
            Issue(
                "lifecycle.wizard_stale_manifest",
                str(obsolete_manifest),
                "standalone Wizard manifest conflicts with the unified plugin contract",
            )
        )

    for relative in ("README.md", "INSTALL.md", "UPDATE_FOR_COLLEAGUES.md", "docs/RELEASE_AND_MERGE.md"):
        path = wizard_root / relative
        try:
            source = path.read_text(encoding="utf-8")
        except OSError as exc:
            issues.append(Issue("lifecycle.wizard_documentation", str(path), str(exc)))
            continue
        if re.search(r"raw\.githubusercontent\.com/.*/(?:main|master)", source):
            issues.append(
                Issue(
                    "security.mutable_source",
                    str(path),
                    "Wizard lifecycle documentation directs users to a mutable branch",
                )
            )
    return issues


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_toolbar_source(
    root: Path,
    toolbar_root: Path | None,
    release: Mapping[str, Any],
) -> list[Issue]:
    issues: list[Issue] = []
    if toolbar_root is None or not toolbar_root.is_dir():
        return [
            Issue(
                "toolbar.source_required",
                str(toolbar_root or ""),
                "candidate gate requires the canonical toolbar source clone",
            )
        ]
    checker = toolbar_root / "scripts/check-reproducible-build.js"
    canonical = toolbar_root / "toolbar/build/toolbar.js"
    distributed = root / "toolbar/toolbar.js"
    if not checker.is_file():
        issues.append(Issue("toolbar.reproducibility_tool", str(checker), "toolbar reproducibility checker is missing"))
        return issues
    try:
        result = subprocess.run(
            ("npm", "run", "test:reproducible"),
            cwd=toolbar_root,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        issues.append(Issue("toolbar.reproducibility", str(toolbar_root), type(error).__name__))
        return issues
    if result.returncode != 0:
        issues.append(Issue("toolbar.reproducibility", str(toolbar_root), "canonical toolbar did not rebuild reproducibly"))
        return issues
    if not canonical.is_file() or not distributed.is_file() or _sha256(canonical) != _sha256(distributed):
        issues.append(
            Issue(
                "toolbar.distribution_drift",
                str(distributed),
                "distributed toolbar bytes differ from the canonical reproducible build",
            )
        )
    try:
        head = subprocess.run(
            ("git", "rev-parse", "HEAD"),
            cwd=toolbar_root,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            shell=False,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        head = ""
    expected = {
        item.get("id"): item.get("revision")
        for item in release.get("sourceRepositories") or []
        if isinstance(item, dict)
    }.get("toolbar")
    if head != expected:
        issues.append(Issue("toolbar.source_revision", str(toolbar_root), "toolbar HEAD differs from the release revision"))
    return issues


def validate_release(
    root: Path,
    manifest_path: Path,
    *,
    wizard_root: Path | None = None,
    toolbar_root: Path | None = None,
    bundle_path: Path | None = None,
) -> list[Issue]:
    issues: list[Issue] = []
    for required_path in (
        root / "release/EXTERNAL_MATRIX.md",
        root / "tools/external_matrix.py",
        root / "tools/import_external_evidence.py",
        root / "installer/client_verify.py",
        root / "installer/verification.py",
    ):
        if not required_path.is_file():
            issues.append(
                Issue(
                    "verification.tooling",
                    str(required_path),
                    "required external release verification tooling is missing",
                )
            )
    try:
        data = _read_json(manifest_path)
    except (OSError, json.JSONDecodeError) as exc:
        return [Issue("release.invalid_json", str(manifest_path), str(exc))]
    if not isinstance(data, dict):
        return [Issue("release.root", str(manifest_path), "release root must be an object")]

    required = {
        "schemaVersion", "releaseId", "version", "status", "supportedPlatforms",
        "distribution", "dependencies", "accountResources", "lifecycle", "services",
        "telemetry", "sourceRepositories", "artifacts", "capabilities", "installers",
        "verification",
    }
    for key in sorted(required - set(data)):
        issues.append(Issue("release.missing", str(manifest_path), f"missing required field: {key}"))
    if data.get("schemaVersion") != 1 or data.get("releaseId") != "extella-client":
        issues.append(Issue("release.identity", str(manifest_path), "unsupported release contract"))
    if not isinstance(data.get("version"), str) or not SEMVER.fullmatch(data.get("version", "")):
        issues.append(Issue("release.version", str(manifest_path), "version must be semantic"))
    if set(data.get("supportedPlatforms") or []) != SUPPORTED_PLATFORMS:
        issues.append(Issue("release.platforms", str(manifest_path), "release must target exactly the approved matrix"))

    distribution = data.get("distribution") if isinstance(data.get("distribution"), dict) else {}
    if data.get("status") == "released" and (
        distribution.get("status") != "released"
        or not SHA256.fullmatch(str(distribution.get("sha256") or ""))
        or not isinstance(distribution.get("bytes"), int)
        or not isinstance(distribution.get("fileCount"), int)
    ):
        issues.append(Issue("distribution.release", str(manifest_path), "released distribution requires exact hash, size, and file count"))
    if distribution.get("status") in {"candidate", "released"}:
        if bundle_path is None or not bundle_path.is_file():
            issues.append(Issue("distribution.bundle_required", str(manifest_path), "candidate gate requires the exact bundle file"))
        else:
            if bundle_path.name != distribution.get("fileName"):
                issues.append(Issue("distribution.filename", str(bundle_path), "bundle filename differs from manifest"))
            if bundle_path.stat().st_size != distribution.get("bytes"):
                issues.append(Issue("distribution.bytes", str(bundle_path), "bundle size differs from manifest"))
            if _sha256(bundle_path) != distribution.get("sha256"):
                issues.append(Issue("distribution.sha256", str(bundle_path), "bundle hash differs from manifest"))
            try:
                with zipfile.ZipFile(bundle_path) as archive:
                    bundled = json.loads(archive.read("bundle-manifest.json"))
                if len(bundled.get("files") or []) != distribution.get("fileCount"):
                    issues.append(Issue("distribution.files", str(bundle_path), "bundle file count differs from manifest"))
                bundled_paths = {
                    item.get("path")
                    for item in bundled.get("files") or []
                    if isinstance(item, dict)
                }
                if not REQUIRED_BUNDLE_PAYLOAD.issubset(bundled_paths):
                    missing_payload = sorted(REQUIRED_BUNDLE_PAYLOAD - bundled_paths)
                    issues.append(
                        Issue(
                            "distribution.required_payload",
                            str(bundle_path),
                            f"bundle is missing required installer/runtime payload: {missing_payload}",
                        )
                    )
                release_sources = {
                    item.get("id"): item.get("revision")
                    for item in data.get("sourceRepositories") or []
                    if isinstance(item, dict)
                }
                bundle_sources = {
                    item.get("id"): item.get("revision")
                    for item in bundled.get("sourceRepositories") or []
                    if isinstance(item, dict)
                }
                if release_sources != bundle_sources:
                    issues.append(Issue("distribution.sources", str(bundle_path), "bundle source SHAs differ from release manifest"))
                packaging_revision = str(bundled.get("packagingRepositoryRevision") or "")
                if not SHA40.fullmatch(packaging_revision):
                    issues.append(
                        Issue(
                            "distribution.packaging_revision",
                            str(bundle_path),
                            "bundle must record the exact packaging repository revision",
                        )
                    )
                elif (root / ".git").exists():
                    try:
                        head = subprocess.run(
                            ("git", "rev-parse", "HEAD"), cwd=root, capture_output=True,
                            text=True, timeout=10, check=False, shell=False,
                        ).stdout.strip()
                        ancestor = subprocess.run(
                            ("git", "merge-base", "--is-ancestor", packaging_revision, head),
                            cwd=root, capture_output=True, text=True, timeout=10,
                            check=False, shell=False,
                        )
                        changed = subprocess.run(
                            ("git", "diff", "--name-only", f"{packaging_revision}..{head}"),
                            cwd=root, capture_output=True, text=True, timeout=10,
                            check=False, shell=False,
                        )
                        allowed_after_packaging = {
                            "release/release-manifest.json",
                            "release/verification-evidence.json",
                        }
                        changed_paths = {value for value in changed.stdout.splitlines() if value}
                        if ancestor.returncode != 0 or changed.returncode != 0 or not changed_paths.issubset(allowed_after_packaging):
                            issues.append(
                                Issue(
                                    "distribution.packaging_drift",
                                    str(bundle_path),
                                    "packaging checkout changed outside approved post-build evidence files",
                                )
                            )
                    except (OSError, subprocess.SubprocessError):
                        issues.append(
                            Issue(
                                "distribution.packaging_revision",
                                str(bundle_path),
                                "could not verify packaging repository revision",
                            )
                        )
                if bundled.get("releaseVersion") != data.get("version"):
                    issues.append(Issue("distribution.version", str(bundle_path), "bundle version differs from release manifest"))
            except (OSError, KeyError, ValueError, zipfile.BadZipFile) as exc:
                issues.append(Issue("distribution.invalid", str(bundle_path), type(exc).__name__))

    dependencies = data.get("dependencies") or []
    dependency_names = [item.get("name") for item in dependencies if isinstance(item, dict)]
    required_dependencies = {
        "python", "uv", "node", "npm", "npx", "uvx", "git", "gh", "brew", "winget",
        "ffmpeg", "ghostscript", "imagemagick", "pandoc", "ollama",
    }
    if set(dependency_names) != required_dependencies or len(dependency_names) != len(set(dependency_names)):
        issues.append(Issue("dependency.exact", str(manifest_path), "dependency contract is incomplete or duplicated"))
    for dependency in dependencies:
        if not isinstance(dependency, dict):
            continue
        name = dependency.get("name")
        if name in {"python", "uv"}:
            if dependency.get("requiredForCore") is not True or dependency.get("resolver") != "pinned_native_bootstrap":
                issues.append(Issue("dependency.core", str(manifest_path), f"{name} must be pinned for core"))
        elif dependency.get("resolver") != "ensure_tool":
            issues.append(Issue("dependency.resolver", str(manifest_path), f"{name} must route through ensure_tool"))

    lifecycle = data.get("lifecycle") if isinstance(data.get("lifecycle"), dict) else {}
    if lifecycle.get("install") != "installer/client_install.py" or lifecycle.get("uninstall") != "installer/client_uninstall.py":
        issues.append(Issue("lifecycle.unified", str(manifest_path), "release lifecycle must use unified install/uninstall"))
    telemetry = data.get("telemetry") if isinstance(data.get("telemetry"), dict) else {}
    if telemetry.get("transport") != "disabled" or telemetry.get("schema") != "release/schemas/stability-telemetry.schema.json":
        issues.append(Issue("telemetry.contract", str(manifest_path), "telemetry must remain local until an approved transport exists"))

    source_revisions: dict[str, str] = {}
    for source in data.get("sourceRepositories") or []:
        if not isinstance(source, dict) or not SHA40.fullmatch(str(source.get("revision", ""))):
            issues.append(Issue("release.source_revision", str(manifest_path), "every source revision must be a full Git SHA"))
        elif isinstance(source.get("id"), str):
            source_revisions[source["id"]] = source["revision"]

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
    capability_ids: set[str] = set()
    referenced_manifests: set[Path] = set()
    local_ports: dict[int, str] = {}
    bundled_local_services: set[str] = set()
    for capability in capabilities:
        if not isinstance(capability, dict):
            issues.append(Issue("capability.object", str(manifest_path), "capability must be an object"))
            continue
        plugin_path = root / str(capability.get("manifest", ""))
        referenced_manifests.add(plugin_path.resolve())
        capability_id = str(capability.get("id") or "")
        if not capability_id or capability_id in capability_ids:
            issues.append(Issue("capability.duplicate", str(manifest_path), capability_id))
        capability_ids.add(capability_id)
        plugin_issues = validate_plugin(plugin_path)
        issues.extend(plugin_issues)
        if plugin_path.is_file():
            plugin = _read_json(plugin_path)
            if plugin.get("id") != capability.get("id"):
                issues.append(Issue("capability.id", str(plugin_path), "capability id differs from plugin manifest"))
            if plugin.get("classification") != capability.get("classification"):
                issues.append(Issue("capability.classification", str(plugin_path), "classification differs from release manifest"))
            component_source = {
                "extella_toolbar": "toolbar",
                "extella_adoption_wizard": "wizard",
            }.get(capability_id)
            plugin_source = plugin.get("source") if isinstance(plugin.get("source"), dict) else {}
            if component_source and plugin_source.get("revision") != source_revisions.get(component_source):
                issues.append(
                    Issue(
                        "capability.source_revision",
                        str(plugin_path),
                        f"{capability_id} revision differs from the release source contract",
                    )
                )
            runtime = plugin.get("runtime") if isinstance(plugin.get("runtime"), dict) else {}
            if runtime.get("kind") == "local_service":
                port_data = runtime.get("port") if isinstance(runtime.get("port"), dict) else {}
                try:
                    port = int(port_data.get("preferred"))
                except (TypeError, ValueError):
                    port = 0
                if port in local_ports:
                    issues.append(
                        Issue("runtime.port_conflict", str(plugin_path), f"port {port} also belongs to {local_ports[port]}")
                    )
                elif port:
                    local_ports[port] = capability_id
                if capability.get("classification") == "bundled" and capability.get("required") is True:
                    bundled_local_services.add(capability_id)
                if port_data.get("bind") != "127.0.0.1":
                    issues.append(Issue("runtime.bind", str(plugin_path), "local services must bind to 127.0.0.1"))

    all_manifests = {path.resolve() for path in (root / "release/plugins").glob("*.json")}
    if referenced_manifests != all_manifests:
        issues.append(
            Issue(
                "capability.manifest_exact",
                str(manifest_path),
                "release capabilities must reference every and only plugin manifest",
            )
        )

    release_services = data.get("services") or []
    release_service_ids = {
        str(item.get("id")) for item in release_services if isinstance(item, dict)
    }
    if release_service_ids != bundled_local_services:
        issues.append(Issue("service.exact", str(manifest_path), "top-level services differ from bundled local runtimes"))
    service_ports: set[int] = set()
    for item in release_services:
        if not isinstance(item, dict):
            continue
        try:
            port = int(item.get("port"))
        except (TypeError, ValueError):
            port = 0
        if not port or port in service_ports:
            issues.append(Issue("service.port", str(manifest_path), f"invalid/duplicate top-level port: {port}"))
        service_ports.add(port)

    wizard = wizard_root or root.parent / "wizard"
    if not wizard.is_dir():
        issues.append(Issue("expert.wizard_root", str(wizard), "wizard source root is required"))
    else:
        issues.extend(validate_expert_contract(root, wizard))
        issues.extend(validate_shipped_expert_portability(root, wizard))
        issues.extend(validate_shipped_runtime_security(root, wizard))
        issues.extend(validate_wizard_lifecycle(wizard))
    issues.extend(validate_cap_dependency_contract(root))
    issues.extend(validate_evidence(root, data))
    issues.extend(validate_catalog_policy(root, wizard))
    issues.extend(validate_lifecycle_entrypoints(root))
    if distribution.get("status") in {"candidate", "released"}:
        issues.extend(validate_toolbar_source(root, toolbar_root, data))

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
    parser.add_argument("--wizard-root", type=Path)
    parser.add_argument("--toolbar-root", type=Path)
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    manifest = args.manifest if args.manifest.is_absolute() else root / args.manifest
    wizard_root = args.wizard_root.resolve() if args.wizard_root else None
    toolbar_root = args.toolbar_root.resolve() if args.toolbar_root else None
    bundle_path = args.bundle.resolve() if args.bundle else None
    issues = validate_release(
        root,
        manifest,
        wizard_root=wizard_root,
        toolbar_root=toolbar_root,
        bundle_path=bundle_path,
    )
    if args.as_json:
        print(json.dumps({"status": "failed" if issues else "passed", "issues": [asdict(i) for i in issues]}, indent=2))
    else:
        for issue in issues:
            print(f"ERROR {issue.code}: {issue.path}: {issue.message}")
        print(f"release gate: {'FAILED' if issues else 'PASSED'} ({len(issues)} issue(s))")
    return 1 if issues else 0


if __name__ == "__main__":
    sys.exit(main())
