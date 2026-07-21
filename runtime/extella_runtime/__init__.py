"""Shared Extella client runtime and preflight primitives."""

from .doctor import DoctorReport, run_doctor
from .ensure_tool import EnsureResult, ensure_many, ensure_tool
from .platforms import PlatformInfo, detect_platform
from .transaction import InstallTransaction, InstallationError, uninstall_from_state

__all__ = [
    "DoctorReport",
    "EnsureResult",
    "InstallTransaction",
    "InstallationError",
    "PlatformInfo",
    "detect_platform",
    "ensure_many",
    "ensure_tool",
    "run_doctor",
    "uninstall_from_state",
]
