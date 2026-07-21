"""Strict verification for an extracted Extella release bundle."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any

from runtime.extella_runtime.platforms import SUPPORTED_PLATFORM_KEYS


SHA256 = re.compile(r"^[0-9a-f]{64}$")
SHA40 = re.compile(r"^[0-9a-f]{40}$")


class BundleVerificationError(RuntimeError):
    """The bundle is incomplete, modified, or structurally unsafe."""


@dataclass(frozen=True)
class VerifiedBundle:
    release_version: str
    files: int
    bytes: int
    source_repositories: tuple[dict[str, str], ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _portable_relative_path(value: Any) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value:
        raise BundleVerificationError("bundle contains an invalid relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise BundleVerificationError(f"bundle path escapes its root: {value}")
    return path


def verify_bundle(root: Path) -> VerifiedBundle:
    root = root.resolve()
    manifest_path = root / "bundle-manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise BundleVerificationError("bundle-manifest.json is missing or invalid") from error
    if not isinstance(manifest, dict) or manifest.get("schemaVersion") != 1:
        raise BundleVerificationError("unsupported bundle manifest schema")
    release_version = manifest.get("releaseVersion")
    if not isinstance(release_version, str) or not release_version:
        raise BundleVerificationError("bundle releaseVersion is missing")
    if set(manifest.get("supportedPlatforms") or []) != set(SUPPORTED_PLATFORM_KEYS):
        raise BundleVerificationError("bundle platform matrix differs from the approved matrix")

    sources: list[dict[str, str]] = []
    for source in manifest.get("sourceRepositories") or []:
        if not isinstance(source, dict) or not SHA40.fullmatch(str(source.get("revision", ""))):
            raise BundleVerificationError("bundle source revision is not a full Git SHA")
        sources.append({
            "id": str(source.get("id", "")),
            "revision": str(source["revision"]),
        })
    if {source["id"] for source in sources} != {"marketplace", "toolbar", "wizard"}:
        raise BundleVerificationError("bundle must identify marketplace, toolbar, and wizard sources")

    records = manifest.get("files")
    if not isinstance(records, list) or not records:
        raise BundleVerificationError("bundle has no file inventory")
    expected: set[str] = set()
    total_bytes = 0
    for record in records:
        if not isinstance(record, dict):
            raise BundleVerificationError("bundle file record must be an object")
        relative = _portable_relative_path(record.get("path"))
        relative_text = relative.as_posix()
        if relative_text in expected:
            raise BundleVerificationError(f"duplicate bundle path: {relative_text}")
        expected.add(relative_text)
        target = root.joinpath(*relative.parts)
        if target.is_symlink() or not target.is_file():
            raise BundleVerificationError(f"bundle file is missing or unsafe: {relative_text}")
        expected_bytes = record.get("bytes")
        expected_hash = record.get("sha256")
        if not isinstance(expected_bytes, int) or expected_bytes < 0:
            raise BundleVerificationError(f"invalid size for bundle file: {relative_text}")
        if target.stat().st_size != expected_bytes:
            raise BundleVerificationError(f"bundle size mismatch: {relative_text}")
        if not isinstance(expected_hash, str) or not SHA256.fullmatch(expected_hash):
            raise BundleVerificationError(f"invalid hash for bundle file: {relative_text}")
        if sha256_file(target) != expected_hash:
            raise BundleVerificationError(f"bundle hash mismatch: {relative_text}")
        total_bytes += expected_bytes

    actual = {
        item.relative_to(root).as_posix()
        for item in root.rglob("*")
        if item.is_file() and item != manifest_path
    }
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        detail = f"missing={missing[:3]} extra={extra[:3]}"
        raise BundleVerificationError(f"bundle inventory is not exact: {detail}")
    return VerifiedBundle(release_version, len(records), total_bytes, tuple(sources))
