"""Two-phase client installation for the supported Extella desktop matrix."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any, Mapping, Sequence
import urllib.error
import urllib.request

from installer.account import (
    AccountInstaller,
    ExtellaAPI,
    catalog_kv_artifacts,
    discover_bundle_experts,
    prompt_token,
    repair_interrupted_account,
    required_experts,
    uninstall_account_resources,
)
from installer.bundle import VerifiedBundle, verify_bundle
from runtime.extella_runtime.autostart import AutostartSpec, install_autostart, remove_autostart
from runtime.extella_runtime.doctor import run_doctor
from runtime.extella_runtime.paths import ClientPaths, client_paths
from runtime.extella_runtime.platforms import PlatformInfo, detect_platform
from runtime.extella_runtime.processes import ProcessSupervisor, RuntimeSpec
from runtime.extella_runtime.transaction import InstallTransaction, InstallationError, uninstall_from_state
from runtime.extella_runtime.telemetry import StabilityEvent, record_local_aggregate


ACTIVITY_ID = "extella_activity_center"


@dataclass(frozen=True)
class PreparedClient:
    transaction: InstallTransaction
    paths: ClientPaths
    python: Path
    service_environment: dict[str, str]
    release_version: str
    doctor_report: dict[str, Any]


def _run(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(argv), capture_output=True, text=True, timeout=30, check=False, shell=False
    )


def _python_candidates(root: Path, platform_info: PlatformInfo) -> list[Path]:
    if platform_info.system == "Windows":
        candidates = root.rglob("python.exe")
    else:
        candidates = root.rglob("python3.12")
    return sorted(
        (path for path in candidates if path.is_file() and "site-packages" not in path.parts),
        key=lambda path: (len(path.parts), path.as_posix()),
    )


def _verify_python(path: Path) -> None:
    if not path.is_absolute() or not path.is_file():
        raise InstallationError("managed Python executable is missing")
    result = subprocess.run(
        (
            str(path),
            "-c",
            "import ctypes, ssl, sqlite3, sys, urllib.request; "
            "ssl.create_default_context(); ctypes.CDLL(None); "
            "raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 4)",
        ),
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
        shell=False,
    )
    if result.returncode != 0:
        raise InstallationError(
            "Extella requires a working Python 3.12 runtime with TLS, SQLite, HTTP, and native-library support"
        )


def _tree_same(transaction: InstallTransaction, source: Path, target: Path) -> bool:
    return target.is_dir() and transaction._tree_manifest_sha256(source) == transaction._tree_manifest_sha256(target)


def _runtime_environment(paths: ClientPaths) -> dict[str, str]:
    return {
        "EXTELLA_DATA_ROOT": str(paths.data_root),
        "EXTELLA_WIZARD_ROOT": str(paths.data_root / "wizard"),
        "EXTELLA_PLUGIN_ROOT": str(paths.plugins_root),
        "EXTELLA_PLUGIN_REGISTRY": str(paths.plugins_root / "_registry"),
        "EXTELLA_ACTIVITY_FILE": str(paths.state_root / "activity" / "events.jsonl"),
        "EXTELLA_SERVICE_STATE": str(paths.state_root / "services.json"),
        "EXTELLA_PROCESS_STATE": str(paths.state_root / "processes.json"),
        "PYTHONPATH": str(paths.runtime_root),
    }


def _record_stability(
    *,
    platform_info: PlatformInfo,
    environment: Mapping[str, str],
    release_version: str,
    stage: str,
    success: bool,
    error: Exception | None = None,
) -> None:
    if not platform_info.supported or platform_info.key is None:
        return
    try:
        paths = client_paths(platform_info=platform_info, env=environment)
        record_local_aggregate(
            paths.state_root / "telemetry" / "stability.json",
            StabilityEvent(
                platform=platform_info.key,
                architecture=platform_info.architecture,
                component="client-installer",
                release_version=release_version,
                error_class=type(error).__name__ if error is not None else "none",
                install_stage=stage,
                success=success,
            ),
        )
    except (OSError, ValueError):
        # Telemetry is deliberately optional and can never make installation fail.
        return


def _listener_import_roots(env: Mapping[str, str]) -> list[Path]:
    home = Path(env.get("USERPROFILE") or env.get("HOME") or Path.home())
    candidates = [home / ".cache" / "uv" / "archive-v0"]
    if env.get("LOCALAPPDATA"):
        candidates.append(Path(env["LOCALAPPDATA"]) / "uv" / "cache" / "archive-v0")
    if env.get("UV_CACHE_DIR"):
        candidates.append(Path(env["UV_CACHE_DIR"]) / "archive-v0")
    roots: set[Path] = set()
    patterns = (
        "*/lib/python*/site-packages/extella_listener",
        "*/*.data/purelib/extella_listener",
        "*/Lib/site-packages/extella_listener",
    )
    for archive in candidates:
        for pattern in patterns:
            roots.update(listener.parent for listener in archive.glob(pattern))
    return sorted(roots, key=lambda path: path.as_posix())


def _managed_site_packages(python_root: Path, platform_info: PlatformInfo) -> Path:
    pattern = "*/Lib/site-packages" if platform_info.system == "Windows" else "*/lib/python3.12/site-packages"
    candidates = sorted(python_root.glob(pattern), key=lambda path: path.as_posix())
    if candidates:
        return candidates[0]
    candidates = _python_candidates(python_root, platform_info)
    if not candidates:
        raise InstallationError("managed Python layout is incomplete")
    if platform_info.system == "Windows":
        return candidates[0].parent / "Lib" / "site-packages"
    return candidates[0].parent.parent / "lib" / "python3.12" / "site-packages"


def _copy_runtime(transaction: InstallTransaction, bundle_root: Path, paths: ClientPaths) -> str:
    source = bundle_root / "payload/marketplace/runtime"
    for item in sorted((source / "extella_runtime").glob("*.py")):
        transaction.atomic_copy(item, paths.runtime_root / "extella_runtime" / item.name)
    transaction.atomic_copy(source / "extella_expert_bridge.py", paths.runtime_root / "extella_expert_bridge.py")
    transaction.atomic_copy(source / "pinokio_recipe_resolver.js", paths.runtime_root / "pinokio_recipe_resolver.js")
    return "shared runtime installed"


def _install_import_hooks(
    transaction: InstallTransaction,
    *,
    paths: ClientPaths,
    python_root: Path | None,
    platform_info: PlatformInfo,
    env: Mapping[str, str],
) -> str:
    roots = _listener_import_roots(env)
    if python_root is not None:
        roots.insert(0, _managed_site_packages(python_root, platform_info))
    roots = list(dict.fromkeys(roots))
    if not roots:
        # Service processes also receive PYTHONPATH explicitly. Listener hooks
        # are added later when a listener environment becomes discoverable.
        return "no listener environment discovered; service PYTHONPATH configured"
    content = (
        str(paths.runtime_root)
        + "\nimport extella_runtime.bootstrap; extella_runtime.bootstrap.activate()\n"
    ).encode("utf-8")
    for root in roots:
        transaction.atomic_write(content, root / "extella_client_runtime.pth", mode=0o644)
    return f"runtime import hook installed in {len(roots)} environment(s)"


def _copy_activity(transaction: InstallTransaction, bundle_root: Path, paths: ClientPaths) -> str:
    source_root = bundle_root / "payload/marketplace/device/activity-center"
    target = paths.data_root / "activity-center"
    for directory in ("bridge", "instrumentation"):
        for source in sorted((source_root / directory).glob("*.py")):
            transaction.atomic_copy(source, target / source.name)
    return "Activity Center installed"


def _install_local_payload(
    transaction: InstallTransaction,
    *,
    bundle_root: Path,
    bundle: VerifiedBundle,
    paths: ClientPaths,
    python: Path,
) -> str:
    marketplace = bundle_root / "payload/marketplace"
    if not _tree_same(transaction, marketplace / "installer", paths.data_root / "installer"):
        transaction.atomic_tree(marketplace / "installer", paths.data_root / "installer")
    transaction.atomic_copy(
        marketplace / "tools" / "external_matrix.py",
        paths.data_root / "installer" / "external_matrix.py",
    )
    transaction.atomic_copy(marketplace / "toolbar/toolbar.js", paths.toolbar_root / "toolbar.js")
    # Конструктор и предметные локальные сервисы входят в подписанный архив,
    # но устанавливаются только по своей карточке. Базовая установка тулбара
    # не копирует, не регистрирует и не запускает их.
    return "toolbar catalog payload installed; on-demand services left untouched"


def prepare_local_client(
    bundle_root: Path,
    *,
    platform_info: PlatformInfo | None = None,
    env: Mapping[str, str] | None = None,
    bootstrap_python_root: Path | None = None,
    python_executable: Path | None = None,
    network_urls: Sequence[str] = ("https://github.com", "https://api.extella.ai"),
) -> tuple[PreparedClient, VerifiedBundle]:
    platform_info = platform_info or detect_platform()
    if not platform_info.supported:
        raise InstallationError(platform_info.reason or "unsupported platform")
    bundle = verify_bundle(bundle_root)
    environment = dict(os.environ if env is None else env)
    paths = client_paths(platform_info=platform_info, env=environment)
    doctor = run_doctor(
        platform_info=platform_info,
        data_root=paths.data_root,
        required_tools=(),
        optional_tools=(
            "node",
            "npm",
            "npx",
            "uv",
            "uvx",
            "git",
            "ffmpeg",
            "ghostscript",
            "imagemagick",
            "pandoc",
            "ollama",
            "brew" if platform_info.system == "Darwin" else "winget",
        ),
        ports=(8799,),
        network_urls=network_urls,
        env=environment,
    )
    if not doctor.ready:
        raise InstallationError("Computer Doctor preflight did not pass")
    transaction = InstallTransaction(
        release_version=bundle.release_version,
        state_root=paths.state_root / "client",
    )
    installed_python_root = paths.runtime_root / "python"
    try:
        transaction.run(
            "doctor.report",
            lambda: (
                transaction.atomic_write(
                    (json.dumps(doctor.to_dict(), ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
                    paths.state_root / "doctor" / "latest.json",
                    mode=0o600,
                )
                and "Computer Doctor report saved"
            ),
        )
        if bootstrap_python_root is not None:
            transaction.run(
                "runtime.python",
                lambda: (
                    "managed Python already matches"
                    if _tree_same(transaction, bootstrap_python_root, installed_python_root)
                    else transaction.atomic_tree(bootstrap_python_root, installed_python_root)
                ),
            )
            candidates = _python_candidates(installed_python_root, platform_info)
            python = candidates[0] if candidates else Path()
            python_root: Path | None = installed_python_root
        elif python_executable is not None:
            python = python_executable.resolve()
            python_root = installed_python_root if installed_python_root.is_dir() else None
        else:
            candidates = _python_candidates(installed_python_root, platform_info)
            if not candidates:
                raise InstallationError("managed Python is absent; native bootstrap is required")
            python = candidates[0]
            python_root = installed_python_root
        _verify_python(python)
        transaction.run("runtime.files", lambda: _copy_runtime(transaction, bundle_root, paths))
        transaction.run(
            "runtime.import_hooks",
            lambda: _install_import_hooks(
                transaction,
                paths=paths,
                python_root=python_root,
                platform_info=platform_info,
                env=environment,
            ),
        )
        transaction.run("activity.files", lambda: _copy_activity(transaction, bundle_root, paths))
        transaction.run(
            "client.payload",
            lambda: _install_local_payload(
                transaction,
                bundle_root=bundle_root,
                bundle=bundle,
                paths=paths,
                python=python,
            ),
        )
    except Exception:
        transaction.rollback(failed_step="local.prepare")
        raise
    return (
        PreparedClient(
            transaction,
            paths,
            python,
            _runtime_environment(paths),
            bundle.release_version,
            doctor.to_dict(),
        ),
        bundle,
    )


def _restrict_secret_file(path: Path, *, platform_info: PlatformInfo) -> None:
    if platform_info.system != "Windows":
        os.chmod(path, 0o600)
        if path.stat().st_mode & 0o077:
            raise InstallationError("secret file permissions could not be restricted")
        return
    powershell = shutil.which("powershell.exe") or shutil.which("pwsh.exe")
    if not powershell:
        raise InstallationError("PowerShell is required to protect the Extella credential file")
    script = (
        "$p=$args[0];$acl=Get-Acl -LiteralPath $p;"
        "$acl.SetAccessRuleProtection($true,$false);"
        "$sid=[Security.Principal.WindowsIdentity]::GetCurrent().User;"
        "$rule=[Security.AccessControl.FileSystemAccessRule]::new"
        "($sid,'FullControl','Allow');$acl.SetAccessRule($rule);"
        "Set-Acl -LiteralPath $p -AclObject $acl"
    )
    result = _run((powershell, "-NoProfile", "-NonInteractive", "-Command", script, str(path)))
    if result.returncode != 0:
        raise InstallationError("Windows credential ACL could not be restricted to the current user")


def _health(url: str, *, timeout: float = 3.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return 200 <= int(response.status) < 400
    except (urllib.error.URLError, OSError, ValueError):
        return False


def _activate_services(
    prepared: PreparedClient,
    *,
    platform_info: PlatformInfo,
) -> str:
    activity_root = prepared.paths.data_root / "activity-center"
    spec = AutostartSpec(
        service_id="activity-center",
        argv=(str(prepared.python), str(activity_root / "server.py")),
        cwd=activity_root,
        environment=prepared.service_environment,
    )
    install_autostart(
        prepared.transaction,
        spec,
        platform_info=platform_info,
        paths=prepared.paths,
    )
    supervisor = ProcessSupervisor(
        state_file=prepared.paths.state_root / "processes.json",
        platform_info=platform_info,
        environment={**os.environ, **prepared.service_environment},
    )
    runtime = RuntimeSpec(
        runtime_id=ACTIVITY_ID,
        name="Extella Activity Center",
        argv=spec.argv,
        cwd=activity_root,
        port=8799,
        health_url="http://127.0.0.1:8799/api/health",
        log_path=prepared.paths.logs_root / "activity-center.log",
        owner=ACTIVITY_ID,
        autostart="native",
    )
    previous = supervisor.status(runtime)
    if previous["status"] != "running":
        prepared.transaction.register_undo(lambda: supervisor.stop(runtime))
        supervisor.start(runtime, timeout=30)
    deadlines = {"activity": ("http://127.0.0.1:8799/api/services", 35)}
    for name, (url, seconds) in deadlines.items():
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline and not _health(url):
            time.sleep(0.25)
        if not _health(url):
            raise InstallationError(f"required UI smoke failed: {name}")
    return "Activity Center is healthy; on-demand local services were not started"


def install_client(
    bundle_root: Path,
    *,
    token: str,
    api_base: str = "https://api.extella.ai",
    platform_info: PlatformInfo | None = None,
    env: Mapping[str, str] | None = None,
    bootstrap_python_root: Path | None = None,
    python_executable: Path | None = None,
    activate_services: bool = True,
    account_api: Any | None = None,
) -> dict[str, Any]:
    platform_info = platform_info or detect_platform()
    environment = dict(os.environ if env is None else env)
    stage = "local-prepare"
    try:
        prepared, _bundle = prepare_local_client(
            bundle_root,
            platform_info=platform_info,
            env=environment,
            bootstrap_python_root=bootstrap_python_root,
            python_executable=python_executable,
        )
    except Exception as error:
        _record_stability(
            platform_info=platform_info,
            environment=environment,
            release_version="unknown",
            stage=stage,
            success=False,
            error=error,
        )
        raise
    account: AccountInstaller | None = None
    account_prepared = False
    try:
        stage = "account-prepare"
        api = account_api or ExtellaAPI(token, api_base=api_base)
        repair_interrupted_account(
            api,
            prepared.paths.state_root / "account" / "account-state.json",
        )
        account = AccountInstaller(
            api,
            release_version=prepared.release_version,
            state_root=prepared.paths.state_root / "account",
        )
        experts = discover_bundle_experts(bundle_root)
        required, smokes = required_experts(bundle_root)
        account.install(
            experts,
            required=required,
            smokes=smokes,
            kv_artifacts=catalog_kv_artifacts(bundle_root),
            agent_instructions=None,
            commit=False,
        )
        account_prepared = True
        if activate_services:
            stage = "service-activation"
            prepared.transaction.run(
                "services.activate",
                lambda: _activate_services(prepared, platform_info=platform_info),
            )
        stage = "commit"
        local_report = prepared.transaction.commit()
        account_report = account.transaction.commit()
    except Exception as error:
        if account is not None and account_prepared:
            account.transaction.rollback(failed_step="client.finalize")
        prepared.transaction.rollback(failed_step="client.finalize")
        _record_stability(
            platform_info=platform_info,
            environment=environment,
            release_version=prepared.release_version,
            stage=stage,
            success=False,
            error=error,
        )
        raise
    _record_stability(
        platform_info=platform_info,
        environment=environment,
        release_version=prepared.release_version,
        stage="complete",
        success=True,
    )
    return {
        "schemaVersion": 1,
        "status": "installed",
        "releaseVersion": prepared.release_version,
        "platform": platform_info.key,
        "doctor": {
            "status": prepared.doctor_report["status"],
            "warnings": sum(
                1 for check in prepared.doctor_report["checks"] if check["status"] == "warning"
            ),
        },
        "local": {"status": local_report["status"], "steps": len(local_report["steps"])},
        "account": {"status": account_report["status"], "steps": len(account_report["steps"])},
    }


def _installed_runtime_spec(
    runtime_id: str,
    *,
    paths: ClientPaths,
    python: Path,
) -> RuntimeSpec:
    if runtime_id != ACTIVITY_ID:
        raise InstallationError(f"runtime is not owned by the toolbar profile: {runtime_id}")
    root = paths.data_root / "activity-center"
    return RuntimeSpec(
        runtime_id,
        "Extella Activity Center",
        (str(python), str(root / "server.py")),
        root,
        8799,
        "http://127.0.0.1:8799/api/health",
        paths.logs_root / "activity-center.log",
        ACTIVITY_ID,
        "native",
    )


def uninstall_client(
    *,
    token: str = "",
    api_base: str = "https://api.extella.ai",
    platform_info: PlatformInfo | None = None,
    env: Mapping[str, str] | None = None,
    account_api: Any | None = None,
) -> dict[str, Any]:
    """Uninstall owned resources while preserving user data and later edits."""

    platform_info = platform_info or detect_platform()
    if not platform_info.supported:
        raise InstallationError(platform_info.reason or "unsupported platform")
    environment = dict(os.environ if env is None else env)
    paths = client_paths(platform_info=platform_info, env=environment)
    account_state = paths.state_root / "account" / "account-state.json"
    local_state = paths.state_root / "client" / "install-state.json"
    if not account_state.exists() and not local_state.exists():
        return {
            "schemaVersion": 1,
            "status": "not_installed",
            "platform": platform_info.key,
        }

    account_report: dict[str, Any] = {"status": "not_installed", "steps": []}
    if account_state.exists():
        if not token.strip() and account_api is None:
            raise InstallationError("Extella token is required to uninstall account-owned resources")
        api = account_api or ExtellaAPI(token, api_base=api_base)
        account_report = uninstall_account_resources(api, account_state)
        if account_report["status"] != "uninstalled":
            return {
                "schemaVersion": 1,
                "status": account_report["status"],
                "platform": platform_info.key,
                "account": account_report,
                "local": {"status": "preserved"},
            }

    local_report: dict[str, Any] = {"status": "not_installed", "steps": []}
    if local_state.exists():
        candidates = _python_candidates(paths.runtime_root / "python", platform_info)
        python = candidates[0] if candidates else (Path(sys.executable).resolve())
        supervisor = ProcessSupervisor(
            state_file=paths.state_root / "processes.json",
            platform_info=platform_info,
            environment={**environment, **_runtime_environment(paths)},
        )
        spec = _installed_runtime_spec(ACTIVITY_ID, paths=paths, python=python)
        supervisor.stop(spec)
        remove_autostart(
            "activity-center", platform_info=platform_info, paths=paths
        )
        preserves = (
            paths.data_root / "wizard" / "sessions",
            paths.data_root / "wizard" / "runs",
            paths.data_root / "wizard" / "reports",
            paths.data_root / "wizard" / "published",
            paths.data_root / "wizard" / "library",
            paths.plugins_root / "extella_contract_agent" / "out",
            paths.plugins_root / "extella_contract_agent" / "kb",
            paths.plugins_root / "extella_travel_agency" / "contracts",
        )
        local_report = uninstall_from_state(local_state, preserve=preserves)
    status = (
        "uninstalled"
        if account_report["status"] in {"uninstalled", "not_installed"}
        and local_report["status"] in {"uninstalled", "not_installed"}
        else "failed"
    )
    return {
        "schemaVersion": 1,
        "status": status,
        "platform": platform_info.key,
        "account": account_report,
        "local": local_report,
    }
