"""Fail-closed detection for the supported Extella desktop matrix."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import platform
import re
import subprocess
from typing import Any


SUPPORTED_PLATFORM_KEYS = frozenset(
    {
        "macos-x86_64",
        "macos-arm64",
        "windows11-x86_64",
    }
)


@dataclass(frozen=True)
class PlatformInfo:
    key: str | None
    supported: bool
    system: str
    architecture: str
    version: str
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _normalise_architecture(value: str) -> str:
    arch = value.strip().lower().replace(" ", "")
    aliases = {
        "amd64": "x86_64",
        "x64": "x86_64",
        "x86-64": "x86_64",
        "aarch64": "arm64",
    }
    return aliases.get(arch, arch)


def _windows_build(version: str) -> int | None:
    numbers = [int(value) for value in re.findall(r"\d+", version)]
    if len(numbers) >= 3:
        return numbers[2]
    return None


def _native_macos_architecture(reported_architecture: str) -> str:
    """Return the physical Mac architecture, including under Rosetta.

    ``platform.machine()`` and ``uname -m`` report ``x86_64`` to translated
    processes on Apple Silicon. External release evidence must describe the
    physical platform, so use Apple's read-only sysctls before accepting an
    Intel row. Failure to query them leaves a genuinely reported Intel Mac as
    Intel; either positive Apple Silicon signal changes the result to arm64.
    """

    arch = _normalise_architecture(reported_architecture)
    if arch != "x86_64":
        return arch
    for name in ("sysctl.proc_translated", "hw.optional.arm64"):
        try:
            result = subprocess.run(
                ("/usr/sbin/sysctl", "-in", name),
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if result.returncode == 0 and result.stdout.strip() == "1":
            return "arm64"
    return arch


def detect_platform(
    *,
    system: str | None = None,
    architecture: str | None = None,
    release: str | None = None,
    version: str | None = None,
    physical_architecture: str | None = None,
) -> PlatformInfo:
    """Return a supported platform key or an explicit rejection reason.

    Windows 11 still commonly reports kernel version 10.0, so build 22000 is
    the lower boundary when the marketing release is not reported as ``11``.
    """

    raw_system = (system or platform.system()).strip()
    raw_arch = architecture or platform.machine()
    raw_release = (release or platform.release()).strip()
    raw_version = (version or platform.version()).strip()
    arch = _normalise_architecture(raw_arch)
    combined_version = " ".join(part for part in (raw_release, raw_version) if part)

    if raw_system == "Darwin":
        if physical_architecture is not None:
            arch = _normalise_architecture(physical_architecture)
        elif architecture is None:
            arch = _native_macos_architecture(arch)
        if arch == "x86_64":
            return PlatformInfo(
                "macos-x86_64", True, raw_system, arch, combined_version
            )
        if arch == "arm64":
            return PlatformInfo("macos-arm64", True, raw_system, arch, combined_version)
        return PlatformInfo(
            None,
            False,
            raw_system,
            arch,
            combined_version,
            f"Unsupported macOS architecture: {arch or 'unknown'}",
        )

    if raw_system == "Windows":
        if arch != "x86_64":
            return PlatformInfo(
                None,
                False,
                raw_system,
                arch,
                combined_version,
                "Only Windows 11 x64 is supported",
            )
        build = _windows_build(raw_version)
        is_windows_11 = raw_release == "11" or (build is not None and build >= 22000)
        if is_windows_11:
            return PlatformInfo(
                "windows11-x86_64", True, raw_system, arch, combined_version
            )
        return PlatformInfo(
            None,
            False,
            raw_system,
            arch,
            combined_version,
            "Only Windows 11 build 22000 or newer is supported",
        )

    return PlatformInfo(
        None,
        False,
        raw_system or "unknown",
        arch or "unknown",
        combined_version,
        "Supported platforms are macOS Intel, macOS Apple Silicon, and Windows 11 x64",
    )
