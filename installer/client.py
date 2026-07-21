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
    required_experts,
)
from installer.bundle import VerifiedBundle, verify_bundle
from runtime.extella_runtime.autostart import AutostartSpec, install_autostart
from runtime.extella_runtime.doctor import run_doctor
from runtime.extella_runtime.paths import ClientPaths, client_paths
from runtime.extella_runtime.platforms import PlatformInfo, detect_platform
from runtime.extella_runtime.processes import ProcessSupervisor, RuntimeSpec
from runtime.extella_runtime.transaction import InstallTransaction, InstallationError


ACTIVITY_ID = "extella_activity_center"
LOCAL_SERVICE_IDS = (
    "extella_adoption_wizard",
    "extella_travel_agency",
    "extella_contract_agent",
)


@dataclass(frozen=True)
class PreparedClient:
    transaction: InstallTransaction
    paths: ClientPaths
    python: Path
    service_environment: dict[str, str]
    release_version: str


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
        (str(path), "-c", "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 4)"),
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
        shell=False,
    )
    if result.returncode != 0:
        raise InstallationError("Extella requires a working Python 3.12 runtime")


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


def _copy_plugin_files(transaction: InstallTransaction, source: Path, target: Path) -> None:
    for item in sorted(source.iterdir(), key=lambda path: path.name):
        if item.is_file() and item.name != "config.json":
            transaction.atomic_copy(item, target / item.name)


def _plugin_manifest(bundle_root: Path, plugin_id: str) -> dict[str, Any]:
    path = bundle_root / "payload/marketplace/release/plugins" / f"{plugin_id}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _service_root(paths: ClientPaths, plugin_id: str) -> Path:
    if plugin_id == "extella_adoption_wizard":
        return paths.wizard_root
    return paths.plugins_root / plugin_id


def _registry_payload(
    manifest: Mapping[str, Any],
    *,
    root: Path,
    python: Path,
    source_revisions: Mapping[str, str],
) -> dict[str, Any]:
    runtime = manifest["runtime"]
    port = int(runtime["port"]["preferred"])
    ui = manifest["ui"]
    command = [
        str(python) if value == "${PYTHON}" else str(root / "server.py") if value.endswith("/server.py") else value
        for value in runtime["command"]
    ]
    return {
        "schemaVersion": 1,
        "id": manifest["id"],
        "name": manifest["name"],
        "version": manifest["version"],
        "purpose": manifest.get("description") or manifest.get("name"),
        "installed": True,
        "source": {
            "repository": "marketplace" if manifest["id"] != "extella_adoption_wizard" else "wizard",
            "revision": source_revisions["marketplace" if manifest["id"] != "extella_adoption_wizard" else "wizard"],
        },
        "ui": {
            "type": "local_server",
            "port": port,
            "rootPath": str(root),
            "mainFile": str(ui.get("entrypoint") or "").lstrip("/"),
            "openInBrowser": False,
        },
        "service": {
            "argv": command,
            "cwd": str(root),
            "port": port,
            "healthPath": runtime["health"]["path"],
            "owner": runtime["owner"],
            "autostart": "activity_center",
        },
    }


def _install_local_payload(
    transaction: InstallTransaction,
    *,
    bundle_root: Path,
    bundle: VerifiedBundle,
    paths: ClientPaths,
    python: Path,
) -> str:
    marketplace = bundle_root / "payload/marketplace"
    wizard = bundle_root / "payload/wizard"
    transaction.atomic_copy(marketplace / "toolbar/toolbar.js", paths.toolbar_root / "toolbar.js")
    if not _tree_same(transaction, wizard / "ui", paths.wizard_root):
        transaction.atomic_tree(wizard / "ui", paths.wizard_root)
    transaction.atomic_copy(wizard / "catalog/catalog.json", paths.data_root / "wizard/catalog/catalog.json")
    transaction.atomic_copy(wizard / "catalog/catalog.json", paths.wizard_root / "catalog.json")
    for plugin_id in ("extella_travel_agency", "extella_contract_agent"):
        _copy_plugin_files(
            transaction,
            marketplace / "automations/ui" / plugin_id,
            paths.plugins_root / plugin_id,
        )
    revisions = {item["id"]: item["revision"] for item in bundle.source_repositories}
    for plugin_id in LOCAL_SERVICE_IDS:
        manifest = _plugin_manifest(bundle_root, plugin_id)
        payload = _registry_payload(
            manifest,
            root=_service_root(paths, plugin_id),
            python=python,
            source_revisions=revisions,
        )
        transaction.atomic_write(
            (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
            paths.plugins_root / "_registry" / f"{plugin_id}.json",
            mode=0o600,
        )
    return "toolbar, wizard, plugin UIs, and registries installed"


def prepare_local_client(
    bundle_root: Path,
    *,
    platform_info: PlatformInfo | None = None,
    env: Mapping[str, str] | None = None,
    bootstrap_python_root: Path | None = None,
    python_executable: Path | None = None,
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
        optional_tools=(),
        ports=(8765, 8766, 8767, 8799),
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
        ),
        bundle,
    )


def _write_config(
    prepared: PreparedClient,
    *,
    token: str,
    api_base: str,
    wizard_agent: str,
    builder_agent: str,
) -> str:
    payload = {
        "schemaVersion": 1,
        "auth_token": token,
        "api_base": api_base,
        "port": 8765,
        "agent_id": wizard_agent,
        "llm_agent_id": builder_agent,
    }
    prepared.transaction.atomic_write(
        (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        prepared.paths.wizard_root / "config.json",
        mode=0o600,
    )
    return "local account configuration installed"


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
    deadlines = {
        "activity": ("http://127.0.0.1:8799/api/services", 35),
        "wizard": ("http://127.0.0.1:8765/wizard.html", 75),
        "travel": ("http://127.0.0.1:8766/onboarding.html", 45),
        "contract": ("http://127.0.0.1:8767/onboarding.html", 45),
    }
    for name, (url, seconds) in deadlines.items():
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline and not _health(url):
            time.sleep(0.25)
        if not _health(url):
            raise InstallationError(f"required UI smoke failed: {name}")
    return "Activity Center and all required local UIs are healthy"


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
    prepared, _bundle = prepare_local_client(
        bundle_root,
        platform_info=platform_info,
        env=env,
        bootstrap_python_root=bootstrap_python_root,
        python_executable=python_executable,
    )
    account: AccountInstaller | None = None
    account_prepared = False
    try:
        api = account_api or ExtellaAPI(token, api_base=api_base)
        account = AccountInstaller(
            api,
            release_version=prepared.release_version,
            state_root=prepared.paths.state_root / "account",
        )
        experts = discover_bundle_experts(bundle_root)
        required, smokes = required_experts(bundle_root)
        wizard = bundle_root / "payload/wizard/agents/wizard_agent.instructions.md"
        builder = bundle_root / "payload/wizard/agents/builder_agent.instructions.md"
        account.install(
            experts,
            required=required,
            smokes=smokes,
            kv_artifacts=catalog_kv_artifacts(bundle_root),
            agent_instructions={
                "wizard": wizard.read_text(encoding="utf-8"),
                "builder": builder.read_text(encoding="utf-8"),
            },
            commit=False,
        )
        account_prepared = True
        ownership = json.loads(account._get_kv("extella:client:agents:v1") or "{}")
        wizard_agent = account.agent_id
        builder_agent = str(ownership.get("builder") or "")
        if not builder_agent:
            # The ownership KV is written later in the prepared account transaction;
            # resolve the just-created/reused builder from the transaction message.
            for step in account.transaction.steps:
                if step.name == "agent:builder":
                    builder_agent = step.message.rsplit(":", 1)[-1]
        prepared.transaction.run(
            "client.config",
            lambda: _write_config(
                prepared,
                token=token,
                api_base=api_base,
                wizard_agent=wizard_agent,
                builder_agent=builder_agent,
            ),
        )
        if activate_services:
            prepared.transaction.run(
                "services.activate",
                lambda: _activate_services(prepared, platform_info=platform_info),
            )
        local_report = prepared.transaction.commit()
        account_report = account.transaction.commit()
    except Exception:
        if account is not None and account_prepared:
            account.transaction.rollback(failed_step="client.finalize")
        prepared.transaction.rollback(failed_step="client.finalize")
        raise
    return {
        "schemaVersion": 1,
        "status": "installed",
        "releaseVersion": prepared.release_version,
        "platform": platform_info.key,
        "local": {"status": local_report["status"], "steps": len(local_report["steps"])},
        "account": {"status": account_report["status"], "steps": len(account_report["steps"])},
    }
