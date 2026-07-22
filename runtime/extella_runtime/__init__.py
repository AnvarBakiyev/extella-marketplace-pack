"""Shared Extella client runtime and preflight primitives."""

from .doctor import DoctorReport, run_doctor
from .ensure_tool import EnsureResult, ensure_many, ensure_tool
from .platforms import PlatformInfo, detect_platform
from .paths import ClientPaths, client_paths
from .transaction import InstallTransaction, InstallationError, uninstall_from_state
from .processes import ProcessSupervisor, RuntimeSpec
from .autostart import AutostartSpec, install_autostart, remove_autostart
from .telemetry import StabilityEvent, record_local_aggregate

__all__ = [
    "DoctorReport",
    "ClientPaths",
    "EnsureResult",
    "InstallTransaction",
    "InstallationError",
    "PlatformInfo",
    "ProcessSupervisor",
    "RuntimeSpec",
    "StabilityEvent",
    "AutostartSpec",
    "detect_platform",
    "client_paths",
    "ensure_many",
    "ensure_tool",
    "run_doctor",
    "install_autostart",
    "remove_autostart",
    "record_local_aggregate",
    "uninstall_from_state",
]
