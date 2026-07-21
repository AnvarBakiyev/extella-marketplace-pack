#!/usr/bin/env python3
"""Build a deterministic, allowlisted Extella client release bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import zipfile


ROOT = Path(__file__).resolve().parents[1]
PERSONAL_PATH = re.compile(
    r"(?:/Users/(?!имя(?:/|$))[A-Za-z0-9._-]+(?:/|$)|/home/(?:ubuntu|anvarbakiyev)(?:/|$)|[A-Za-z]:\\[Uu]sers\\(?!имя(?:\\|$))[A-Za-z0-9._-]+(?:\\|$))",
)
DEVICE_ID = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)
ACCOUNT_AGENT = re.compile(r"\bagent_[A-Za-z0-9_-]{8,}\b")
ALLOWED_AGENTS = {"agent_extella_default", "agent_extella_alibaba_default", "agent_XXXXXXXX"}
SECRET_ASSIGNMENT = re.compile(
    r"(?i)(?:auth[_-]?token|api[_-]?key|secret|password)\s*[:=]\s*['\"][A-Za-z0-9_./+\-=]{16,}['\"]"
)
TEXT_SUFFIXES = {".py", ".json", ".js", ".html", ".md", ".txt", ".ps1", ".sh"}


MARKETPLACE_PATTERNS = (
    "installer/**/*.py",
    "runtime/**/*.py",
    "device/activity-center/bridge/*.py",
    "device/activity-center/instrumentation/*.py",
    "automations/experts/*.py",
    "automations/ui/**/*",
    "experts/*.py",
    "platform_experts/*.py",
    "release/plugins/*.json",
    "release/expert-classification.json",
    "release/catalog-policy.json",
    "release/schemas/*.json",
    "toolbar/install-all.sh",
    "toolbar/install-all.ps1",
    "toolbar/toolbar.js",
    "composer_catalog.json",
    "models_catalog.json",
    "mcp_catalog.json",
    "apps_catalog.json",
    "loc_catalog.json",
)
WIZARD_PATTERNS = (
    "ui/*.py",
    "ui/*.html",
    "experts/*.py",
    "catalog/catalog.json",
    "agents/*.instructions.md",
    "rules/*.md",
    "concepts/*.md",
    "dist/workspace/**/*",
)


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ("git", "-C", str(root), *args), capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise SystemExit(f"git failed for {root.name}: {result.stderr.strip()}")
    return result.stdout.strip()


def _require_clean(root: Path) -> str:
    dirty = _git(root, "status", "--porcelain", "--untracked-files=all")
    if dirty:
        raise SystemExit(f"refusing to build from dirty source: {root}")
    revision = _git(root, "rev-parse", "HEAD")
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise SystemExit(f"invalid source revision: {root}")
    return revision


def _files(root: Path, patterns: tuple[str, ...]) -> list[Path]:
    selected: set[Path] = set()
    for pattern in patterns:
        for path in root.glob(pattern):
            if path.is_file() and "__pycache__" not in path.parts:
                selected.add(path)
    return sorted(selected, key=lambda path: path.relative_to(root).as_posix())


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_expert_classification(marketplace_root: Path, wizard_root: Path) -> dict[str, int]:
    inventory_path = marketplace_root / "release/expert-classification.json"
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    if inventory.get("schemaVersion") != 1:
        raise SystemExit("expert classification schemaVersion must be 1")
    keys = ("bundled", "supportedOnDemand", "thirdPartyUnverified")
    classified: dict[str, str] = {}
    for key in keys:
        values = inventory.get(key)
        if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
            raise SystemExit(f"expert classification {key} must be a string list")
        if values != sorted(values) or len(values) != len(set(values)):
            raise SystemExit(f"expert classification {key} must be sorted and unique")
        for value in values:
            if value in classified:
                raise SystemExit(f"expert is classified more than once: {value}")
            classified[value] = key
    source_paths = [
        *marketplace_root.glob("experts/*.py"),
        *marketplace_root.glob("platform_experts/*.py"),
        *marketplace_root.glob("automations/experts/*.py"),
        *wizard_root.glob("experts/*.py"),
    ]
    source_hashes: dict[str, str] = {}
    for path in sorted(source_paths, key=lambda item: item.as_posix()):
        name = path.stem
        digest = _sha256(path)
        if name in source_hashes and source_hashes[name] != digest:
            raise SystemExit(f"conflicting expert sources: {name}")
        source_hashes[name] = digest
    if set(classified) != set(source_hashes):
        missing = sorted(set(source_hashes) - set(classified))
        stale = sorted(set(classified) - set(source_hashes))
        raise SystemExit(f"expert classification is not exact: missing={missing} stale={stale}")
    manifest_bundled: set[str] = set()
    manifest_on_demand: set[str] = set()
    for path in sorted((marketplace_root / "release/plugins").glob("*.json")):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        experts = manifest.get("experts") or {}
        owned = {str(value) for value in [*(experts.get("required") or []), *(experts.get("smoke") or [])]}
        if manifest.get("classification") == "bundled":
            manifest_bundled.update(owned)
        elif manifest.get("classification") == "supported_on_demand":
            manifest_on_demand.update(owned)
    if manifest_bundled != set(inventory["bundled"]):
        raise SystemExit("bundled expert classification differs from bundled plugin contracts")
    if manifest_on_demand != set(inventory["supportedOnDemand"]):
        raise SystemExit("on-demand expert classification differs from plugin contracts")
    return {key: len(inventory[key]) for key in keys}


def _scan(path: Path, relative: str) -> None:
    lower = path.name.lower()
    if lower in {".env", "config.json"} or lower.endswith((".pem", ".key", ".p12", ".pfx")):
        raise SystemExit(f"secret-bearing filename is forbidden in bundle: {relative}")
    if path.suffix.lower() not in TEXT_SUFFIXES:
        return
    text = path.read_text(encoding="utf-8", errors="replace")
    if PERSONAL_PATH.search(text):
        raise SystemExit(f"personal path found in bundle source: {relative}")
    if DEVICE_ID.search(text):
        raise SystemExit(f"device id found in bundle source: {relative}")
    for value in ACCOUNT_AGENT.findall(text):
        suffix = value.removeprefix("agent_")
        looks_like_identity = any(character.isupper() or character.isdigit() or character == "-" for character in suffix)
        if value not in ALLOWED_AGENTS and looks_like_identity:
            raise SystemExit(f"account-specific agent id found in bundle source: {relative}")
    if SECRET_ASSIGNMENT.search(text):
        raise SystemExit(f"possible literal secret found in bundle source: {relative}")


def _copy_sources(
    stage: Path,
    *,
    marketplace_root: Path,
    toolbar_root: Path,
    wizard_root: Path,
) -> list[dict]:
    records: list[dict] = []
    inputs = (
        ("marketplace", marketplace_root, MARKETPLACE_PATTERNS, Path("payload/marketplace")),
        ("wizard", wizard_root, WIZARD_PATTERNS, Path("payload/wizard")),
    )
    for source_id, source_root, patterns, prefix in inputs:
        for source in _files(source_root, patterns):
            source_relative = source.relative_to(source_root)
            target_relative = prefix / source_relative
            target = stage / target_relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            relative_text = target_relative.as_posix()
            _scan(target, relative_text)
            records.append(
                {
                    "path": relative_text,
                    "bytes": target.stat().st_size,
                    "sha256": _sha256(target),
                    "source": source_id,
                    "sourcePath": source_relative.as_posix(),
                }
            )
    # Toolbar source is represented by its compiled artifact in marketplace;
    # record the canonical source revision separately in the manifest.
    if not (toolbar_root / "package.json").is_file():
        raise SystemExit("toolbar source root is not valid")
    return sorted(records, key=lambda record: record["path"])


def _write_zip(stage: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
    try:
        with zipfile.ZipFile(
            temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
        ) as archive:
            for path in sorted(stage.rglob("*"), key=lambda item: item.relative_to(stage).as_posix()):
                if not path.is_file():
                    continue
                relative = path.relative_to(stage).as_posix()
                info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = (0o755 if path.suffix in {".sh", ".py"} else 0o644) << 16
                info.create_system = 3
                archive.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)


def build(
    *,
    marketplace_root: Path,
    toolbar_root: Path,
    wizard_root: Path,
    output: Path,
) -> dict:
    marketplace_root = marketplace_root.resolve()
    toolbar_root = toolbar_root.resolve()
    wizard_root = wizard_root.resolve()
    source_repositories = [
        {"id": "marketplace", "revision": _require_clean(marketplace_root)},
        {"id": "toolbar", "revision": _require_clean(toolbar_root)},
        {"id": "wizard", "revision": _require_clean(wizard_root)},
    ]
    expert_classification = _validate_expert_classification(marketplace_root, wizard_root)
    release = json.loads((marketplace_root / "release/release-manifest.json").read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="extella-bundle-") as directory:
        stage = Path(directory)
        records = _copy_sources(
            stage,
            marketplace_root=marketplace_root,
            toolbar_root=toolbar_root,
            wizard_root=wizard_root,
        )
        manifest = {
            "schemaVersion": 1,
            "releaseVersion": release["version"],
            "supportedPlatforms": release["supportedPlatforms"],
            "sourceRepositories": source_repositories,
            "expertClassification": expert_classification,
            "files": records,
        }
        (stage / "bundle-manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        _write_zip(stage, output)
    return {
        "path": str(output.resolve()),
        "bytes": output.stat().st_size,
        "sha256": _sha256(output),
        "files": len(records),
        "sourceRepositories": source_repositories,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--marketplace-root", type=Path, default=ROOT)
    parser.add_argument("--toolbar-root", type=Path, required=True)
    parser.add_argument("--wizard-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(**vars(args)), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
