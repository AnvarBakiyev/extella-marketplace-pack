"""Transactional installation of Extella cloud-account resources."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import getpass
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time
from typing import Any, Callable, Iterable, Mapping, Protocol
import urllib.error
import urllib.parse
import urllib.request


EXPERT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{1,127}$")
SAFE_AGENT_ID = re.compile(r"^agent_[A-Za-z0-9_-]{6,128}$")
QWEN_PROVIDER = "alibaba"
QWEN_MODEL = "qwen3.7-max-2026-06-08"
AGENTS_KV_KEY = "extella:client:agents:v1"
INSTALL_SMOKE_PARAM = "__extella_install_smoke"
INSTALL_SMOKE_MARKER = "extella-install-smoke-v1"


class AccountInstallError(RuntimeError):
    pass


class APIError(AccountInstallError):
    def __init__(self, endpoint: str, error_class: str, *, http_status: int | None = None, code: str = ""):
        self.endpoint = endpoint
        self.error_class = error_class
        self.http_status = http_status
        self.code = code[:120]
        super().__init__(f"{endpoint}: {error_class}" + (f" ({http_status})" if http_status else ""))


class AccountAPI(Protocol):
    def post(self, endpoint: str, payload: Mapping[str, Any], *, timeout: int = 90) -> dict[str, Any]: ...


class ExtellaAPI:
    """Small API client that never exposes the auth token in errors or reports."""

    def __init__(self, token: str, *, api_base: str = "https://api.extella.ai", agent_scope: str = "agent_extella_default") -> None:
        token = token.strip()
        if len(token) < 20 or any(character.isspace() for character in token):
            raise AccountInstallError("Extella token is missing or malformed")
        parsed = urllib.parse.urlsplit(api_base)
        if parsed.scheme != "https" or not parsed.netloc:
            raise AccountInstallError("Extella API base must be an HTTPS origin")
        if not SAFE_AGENT_ID.fullmatch(agent_scope):
            raise AccountInstallError("invalid API scope agent")
        self._token = token
        self.api_base = api_base.rstrip("/")
        self.agent_scope = agent_scope

    def post(self, endpoint: str, payload: Mapping[str, Any], *, timeout: int = 90) -> dict[str, Any]:
        if not endpoint.startswith("/api/"):
            raise APIError(endpoint, "invalid_endpoint")
        request = urllib.request.Request(
            self.api_base + endpoint,
            data=json.dumps(dict(payload), ensure_ascii=False).encode("utf-8"),
            headers={
                "X-Auth-Token": self._token,
                "Content-Type": "application/json",
                "X-Profile-Id": "default",
                "X-Agent-Id": self.agent_scope,
                "User-Agent": "ExtellaClientInstaller/2",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            code = ""
            try:
                parsed = json.loads(error.read().decode("utf-8", "replace"))
                code = str(parsed.get("code") or parsed.get("error") or parsed.get("message") or "")
            except (ValueError, OSError):
                pass
            raise APIError(endpoint, "http_error", http_status=error.code, code=code) from error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise APIError(endpoint, type(error).__name__) from error
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError as error:
            raise APIError(endpoint, "invalid_json") from error
        if not isinstance(parsed, dict):
            raise APIError(endpoint, "invalid_response")
        return parsed


@dataclass(frozen=True)
class ExpertSource:
    name: str
    path: Path
    code: str
    description: str
    kwargs: dict[str, str]
    sha256: str
    cspl: str = "fython"


@dataclass(frozen=True)
class KVArtifact:
    key: str
    value: str
    description: str


@dataclass
class AccountStep:
    name: str
    status: str
    message: str = ""
    error_class: str | None = None


@dataclass
class AccountChange:
    kind: str
    identity: str
    existed: bool
    installed_sha256: str
    previous: Any = None


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


class AccountTransaction:
    def __init__(self, *, release_version: str, state_root: Path) -> None:
        self.release_version = release_version
        self.state_root = state_root
        self.steps: list[AccountStep] = []
        self.changes: list[AccountChange] = []
        self._undos: list[Callable[[], None]] = []
        self.started_at = int(time.time())
        self._committed = False
        self._state_file = self.state_root / "account-state.json"
        self._previous_state: dict[str, Any] | None = None
        try:
            previous = json.loads(self._state_file.read_text(encoding="utf-8"))
            if isinstance(previous, dict) and previous.get("status") == "installed":
                self._previous_state = previous
        except (OSError, ValueError):
            pass

    def register_undo(self, undo: Callable[[], None]) -> None:
        if not self.steps or self.steps[-1].status != "running":
            raise RuntimeError("account undo must be registered inside a running step")
        self._undos.append(undo)

    def register_change(self, change: AccountChange) -> None:
        if not self.steps or self.steps[-1].status != "running":
            raise RuntimeError("account change must be registered inside a running step")
        self.changes.append(change)

    def run(self, name: str, action: Callable[[], tuple[str, Callable[[], None] | None]]) -> None:
        step = AccountStep(name, "running")
        self.steps.append(step)
        undo_count = len(self._undos)
        try:
            message, undo = action()
            if undo is not None:
                self._undos.append(undo)
            step.status = "installed" if len(self._undos) > undo_count else "skipped"
            step.message = message[:300]
        except Exception as error:
            step.status = "failed"
            step.error_class = type(error).__name__
            step.message = str(error)[:300]
            self.rollback(failed_step=name)
            raise AccountInstallError(f"account step failed: {name}") from error

    def _report(self, status: str, *, failed_step: str | None = None, rollback_errors: list[str] | None = None) -> dict[str, Any]:
        return {
            "schemaVersion": 1,
            "releaseVersion": self.release_version,
            "status": status,
            "startedAt": self.started_at,
            "finishedAt": int(time.time()),
            "failedStep": failed_step,
            "rollbackErrors": rollback_errors or [],
            "steps": [asdict(step) for step in self.steps],
        }

    def rollback(self, *, failed_step: str) -> None:
        errors: list[str] = []
        for undo in reversed(self._undos):
            try:
                undo()
            except Exception as error:
                errors.append(type(error).__name__)
        for step in self.steps:
            if step.status == "installed":
                step.status = "rolled_back"
        _atomic_json(
            self.state_root / "last-account-report.json",
            self._report("rollback_failed" if errors else "rolled_back", failed_step=failed_step, rollback_errors=errors),
        )
        if errors:
            state = self._report("rollback_failed", failed_step=failed_step, rollback_errors=errors)
            state["changes"] = [asdict(change) for change in self.changes]
            if self._previous_state is not None:
                state["previousState"] = self._previous_state
            _atomic_json(self._state_file, state)
        elif self._committed:
            if self._previous_state is not None:
                _atomic_json(self._state_file, self._previous_state)
            else:
                self._state_file.unlink(missing_ok=True)
        self._committed = False

    def commit(self) -> dict[str, Any]:
        report = self._report("installed")
        state = dict(report)
        state["changes"] = [asdict(change) for change in self.changes]
        if self._previous_state is not None:
            state["previousState"] = self._previous_state
        _atomic_json(self._state_file, state)
        _atomic_json(self.state_root / "last-account-report.json", report)
        self._committed = True
        return report

    def prepared_report(self) -> dict[str, Any]:
        return self._report("prepared")


def _expert_header(code: str, fallback: str) -> tuple[str, str, dict[str, str]]:
    name = fallback
    description = fallback
    kwargs: dict[str, str] = {}
    for line in code.splitlines()[:12]:
        if line.startswith("# expert:"):
            name = line.split(":", 1)[1].strip()
        elif line.startswith("# description:"):
            description = line.split(":", 1)[1].strip() or fallback
        elif line.startswith("# params:"):
            kwargs = {
                item.strip(): ""
                for item in line.split(":", 1)[1].split(",")
                if item.strip()
            }
    return name, description, kwargs


def load_expert_sources(paths: Iterable[Path]) -> dict[str, ExpertSource]:
    selected: dict[str, ExpertSource] = {}
    for path in sorted(paths, key=lambda item: item.as_posix()):
        code = path.read_text(encoding="utf-8")
        if "$extens(" not in "\n".join(code.splitlines()[:20]):
            compile(code, str(path), "exec")
        name, description, kwargs = _expert_header(code, path.stem)
        if name != path.stem or not EXPERT_NAME.fullmatch(name):
            raise AccountInstallError(f"expert identity differs from filename: {path}")
        digest = hashlib.sha256(code.encode("utf-8")).hexdigest()
        candidate = ExpertSource(name, path, code, description, kwargs, digest)
        previous = selected.get(name)
        if previous and previous.sha256 != digest:
            raise AccountInstallError(
                f"conflicting canonical sources for expert {name}: {previous.path} and {path}"
            )
        selected[name] = candidate
    return selected


def discover_bundle_experts(bundle_root: Path) -> dict[str, ExpertSource]:
    locations = (
        bundle_root / "payload/marketplace/experts",
        bundle_root / "payload/marketplace/platform_experts",
        bundle_root / "payload/marketplace/automations/experts",
        bundle_root / "payload/wizard/experts",
    )
    paths = [path for location in locations for path in location.glob("*.py")]
    return load_expert_sources(paths)


def required_experts(bundle_root: Path) -> tuple[set[str], set[str]]:
    required: set[str] = set()
    smoke: set[str] = set()
    for path in sorted((bundle_root / "payload/marketplace/release/plugins").glob("*.json")):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if manifest.get("classification") != "bundled":
            continue
        experts = manifest.get("experts") or {}
        required.update(str(name) for name in experts.get("required") or [])
        smoke.update(str(name) for name in experts.get("smoke") or [])
    return required, smoke


def catalog_kv_artifacts(bundle_root: Path) -> list[KVArtifact]:
    marketplace = bundle_root / "payload/marketplace"
    inputs = (
        ("composer_catalog.json", "composer:catalog", "composer catalog"),
        ("models_catalog.json", None, "verified model catalog"),
        ("mcp_catalog.json", None, "verified MCP catalog"),
        ("apps_catalog.json", None, "third-party application catalog"),
        ("loc_catalog.json", None, "local capability catalog"),
    )
    artifacts: list[KVArtifact] = []
    for filename, fixed_key, description in inputs:
        path = marketplace / filename
        value = json.loads(path.read_text(encoding="utf-8"))
        if fixed_key:
            artifacts.append(KVArtifact(fixed_key, json.dumps(value, ensure_ascii=False), description))
            continue
        if not isinstance(value, dict):
            raise AccountInstallError(f"catalog must be a mapping: {filename}")
        for key, shard in sorted(value.items()):
            artifacts.append(KVArtifact(str(key), json.dumps(shard, ensure_ascii=False), description))
    return artifacts


def _response_success(response: Mapping[str, Any]) -> bool:
    status = str(response.get("status") or "").lower()
    return status in {"success", "ok", "completed", "done"} or response.get("ok") is True


def _missing(error: APIError) -> bool:
    message = error.code.lower()
    return error.http_status == 404 or "not found" in message or "не найден" in message


def _normalise_expert(response: Mapping[str, Any]) -> dict[str, Any] | None:
    code = response.get("expert_code") or response.get("code")
    if not isinstance(code, str) or not code.strip():
        return None
    return {
        "name": str(response.get("name") or response.get("expert_name") or ""),
        "description": str(response.get("description") or ""),
        "code": code,
        "kwargs": response.get("kwargs") if isinstance(response.get("kwargs"), dict) else {},
        "cspl": str(response.get("cspl") or "fython"),
        "global": bool(response.get("global", True)),
    }


def instrument_expert_code(source: ExpertSource, agent_id: str) -> str:
    """Add one reserved, side-effect-free cloud execution probe.

    The wrapper is deterministic and delegates every normal invocation to the
    canonical expert unchanged. The reserved parameter is intentionally absent
    from the published expert kwargs so it is not exposed as a user feature.
    """

    code = source.code.replace("__EXTELLA_AGENT__", agent_id).rstrip() + "\n"
    if INSTALL_SMOKE_MARKER in code or INSTALL_SMOKE_PARAM in code:
        raise AccountInstallError(f"reserved install-smoke symbol exists in expert: {source.name}")
    match = re.search(rf"(?m)^(?P<indent>[ \t]*)def[ \t]+{re.escape(source.name)}[ \t]*\(", code)
    if match is None:
        raise AccountInstallError(f"expert entrypoint was not found: {source.name}")
    index = match.end()
    depth = 1
    quote = ""
    escaped = False
    while index < len(code) and depth:
        character = code[index]
        if quote:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = ""
        elif character in {"'", '"'}:
            quote = character
        elif character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
        index += 1
    if depth or index <= match.end():
        raise AccountInstallError(f"expert signature is incomplete: {source.name}")
    close = index - 1
    parameters = code[match.end():close]
    if "*" in parameters:
        raise AccountInstallError(f"expert signature uses unsupported variadic parameters: {source.name}")
    separator = ", " if parameters.strip() else ""
    code = code[:close] + separator + f"{INSTALL_SMOKE_PARAM}=False" + code[close:]
    colon = code.find(":", close + len(separator) + len(INSTALL_SMOKE_PARAM))
    newline = code.find("\n", colon)
    if colon < 0 or newline < 0:
        raise AccountInstallError(f"expert function body is incomplete: {source.name}")
    body_indent = match.group("indent") + "    "
    guard = (
        f"{body_indent}if {INSTALL_SMOKE_PARAM}:\n"
        + f"{body_indent}    return {{'status': 'success', 'ok': True, "
        + f"'installSmoke': {source.name!r}, 'contract': {INSTALL_SMOKE_MARKER!r}}}\n"
    )
    return code[: newline + 1] + guard + code[newline + 1 :]


class AccountInstaller:
    def __init__(self, api: AccountAPI, *, release_version: str, state_root: Path, agent_id: str | None = None) -> None:
        if agent_id is not None and (
            not SAFE_AGENT_ID.fullmatch(agent_id) or agent_id == "agent_extella_default"
        ):
            raise AccountInstallError("a valid current-account Qwen agent id is required")
        self.api = api
        self.agent_id = agent_id or ""
        self.release_version = release_version
        self.transaction = AccountTransaction(release_version=release_version, state_root=state_root)

    def validate_token(self) -> None:
        response = self.api.post("/api/token/validate", {})
        if not _response_success(response):
            raise AccountInstallError("Extella token validation failed")

    def _get_expert(self, name: str) -> dict[str, Any] | None:
        try:
            return _normalise_expert(self.api.post("/api/expert/get", {"name": name, "global": True}))
        except APIError as error:
            if _missing(error):
                return None
            raise

    def _save_expert_payload(self, payload: Mapping[str, Any]) -> None:
        response = self.api.post("/api/expert/save", payload, timeout=120)
        if not _response_success(response):
            raise AccountInstallError("expert save was not acknowledged")

    @staticmethod
    def _agent_id(response: Mapping[str, Any]) -> str:
        candidates = [response.get("agent_id"), response.get("id")]
        nested = response.get("result")
        if isinstance(nested, dict):
            candidates.extend((nested.get("agent_id"), nested.get("id")))
        for candidate in candidates:
            if isinstance(candidate, str) and SAFE_AGENT_ID.fullmatch(candidate):
                return candidate
        return ""

    def _get_agent(self, agent_id: str) -> dict[str, Any] | None:
        try:
            response = self.api.post("/api/agent/get", {"agent_id": agent_id})
        except APIError as error:
            if _missing(error):
                return None
            raise
        nested = response.get("result")
        return dict(nested) if isinstance(nested, dict) else dict(response)

    @staticmethod
    def _verified_qwen(agent: Mapping[str, Any] | None) -> bool:
        if not agent:
            return False
        provider = str(agent.get("provider") or "").lower()
        model = str(agent.get("model") or "").lower()
        return provider == QWEN_PROVIDER and model.startswith("qwen3.7")

    def _smoke_agent(self, agent_id: str) -> None:
        response = self.api.post(
            "/api/agent/run",
            {
                "agent_id": agent_id,
                "input": "Reply with exactly: EXTELLA_READY",
                "store": False,
                "run_timeout": 90,
            },
            timeout=140,
        )
        serialized = json.dumps(response, ensure_ascii=False).lower()
        if not _response_success(response) or "pro_key_required" in serialized or "does not belong" in serialized:
            raise AccountInstallError("Qwen agent smoke failed")

    def ensure_agent(self, *, role: str, name: str, instructions: str, existing_id: str = "") -> tuple[str, Callable[[], None] | None]:
        if existing_id:
            current = self._get_agent(existing_id)
            if self._verified_qwen(current):
                self._smoke_agent(existing_id)
                return f"Qwen agent verified: {role}:{existing_id}", None
        response = self.api.post(
            "/api/agent/create",
            {
                "name": name,
                "provider": QWEN_PROVIDER,
                "model": QWEN_MODEL,
                "instructions": instructions,
                "tools": [],
                "model_parameters": {"temperature": 0.2},
            },
            timeout=120,
        )
        agent_id = self._agent_id(response)
        if not agent_id:
            raise AccountInstallError(f"agent create returned no id: {role}")

        def undo() -> None:
            result = self.api.post("/api/agent/delete", {"agent_id": agent_id})
            if not _response_success(result):
                raise AccountInstallError("agent rollback delete failed")

        self.transaction.register_undo(undo)
        self.transaction.register_change(
            AccountChange("agent", agent_id, False, hashlib.sha256(agent_id.encode("utf-8")).hexdigest())
        )
        created = self._get_agent(agent_id)
        if not self._verified_qwen(created):
            raise AccountInstallError(f"created agent is not the required Qwen: {role}")
        self._smoke_agent(agent_id)
        return f"Qwen agent created and verified: {role}:{agent_id}", None

    def ensure_agents(self, instructions: Mapping[str, str]) -> tuple[dict[str, str], list[KVArtifact]]:
        if {"wizard", "builder"} - set(instructions):
            raise AccountInstallError("wizard and builder agent instructions are required")
        existing: dict[str, Any] = {}
        previous = self._get_kv(AGENTS_KV_KEY)
        if previous:
            try:
                parsed = json.loads(previous)
                if isinstance(parsed, dict):
                    existing = parsed
            except json.JSONDecodeError:
                pass
        resolved: dict[str, str] = {}
        roles = (("wizard", "Extella — Визард внедрения"), ("builder", "Extella — Строитель"))
        for role, name in roles:
            holder: dict[str, str] = {}

            def action(role=role, name=name, holder=holder):
                message, undo = self.ensure_agent(
                    role=role,
                    name=name,
                    instructions=instructions[role],
                    existing_id=str(existing.get(role) or ""),
                )
                match = re.search(r"(agent_[A-Za-z0-9_-]{6,128})$", message)
                if not match:
                    raise AccountInstallError(f"could not record agent id: {role}")
                holder["id"] = match.group(1)
                return message, undo

            self.transaction.run(f"agent:{role}", action)
            resolved[role] = holder["id"]
        self.agent_id = resolved["wizard"]
        payload = {
            "schemaVersion": 1,
            "releaseVersion": self.release_version,
            "provider": QWEN_PROVIDER,
            "model": QWEN_MODEL,
            **resolved,
        }
        return resolved, [
            KVArtifact(AGENTS_KV_KEY, json.dumps(payload, ensure_ascii=False), "Extella client agent ownership")
        ]

    def install_expert(self, source: ExpertSource) -> tuple[str, Callable[[], None] | None]:
        previous = self._get_expert(source.name)
        code = instrument_expert_code(source, self.agent_id)
        payload = {
            "name": source.name,
            "description": source.description,
            "code": code,
            "kwargs": source.kwargs,
            "cspl": source.cspl,
            "global": True,
        }
        def undo() -> None:
            if previous is None:
                response = self.api.post("/api/expert/delete", {"name": source.name, "global": True})
                if not _response_success(response):
                    raise AccountInstallError("expert rollback delete failed")
            else:
                self._save_expert_payload(previous)

        self.transaction.register_undo(undo)
        self._save_expert_payload(payload)
        installed = self._get_expert(source.name)
        if installed is None or installed["code"].replace("\r\n", "\n") != code.replace("\r\n", "\n"):
            raise AccountInstallError(f"expert verification failed: {source.name}")
        self.transaction.register_change(
            AccountChange(
                "expert",
                source.name,
                previous is not None,
                hashlib.sha256(code.replace("\r\n", "\n").encode("utf-8")).hexdigest(),
                previous,
            )
        )
        return f"expert verified: {source.name}", None

    def _get_kv(self, key: str) -> str | None:
        try:
            response = self.api.post("/api/kv/get", {"key": key, "global": True})
        except APIError as error:
            if _missing(error):
                return None
            raise
        value = response.get("value")
        return value if isinstance(value, str) else None

    def install_kv(self, artifact: KVArtifact) -> tuple[str, Callable[[], None] | None]:
        previous = self._get_kv(artifact.key)

        def undo() -> None:
            if previous is None:
                result = self.api.post("/api/kv/remove", {"key": artifact.key, "global": True})
            else:
                result = self.api.post(
                    "/api/kv/set",
                    {"key": artifact.key, "value": previous, "description": "restored by Extella installer", "global": True},
                )
            if not _response_success(result):
                raise AccountInstallError("KV rollback failed")

        self.transaction.register_undo(undo)
        response = self.api.post(
            "/api/kv/set",
            {
                "key": artifact.key,
                "value": artifact.value,
                "description": artifact.description,
                "global": True,
            },
        )
        if not _response_success(response) or self._get_kv(artifact.key) != artifact.value:
            raise AccountInstallError(f"KV verification failed: {artifact.key}")
        self.transaction.register_change(
            AccountChange(
                "kv",
                artifact.key,
                previous is not None,
                hashlib.sha256(artifact.value.encode("utf-8")).hexdigest(),
                previous,
            )
        )
        return f"KV verified: {artifact.key}", None

    def smoke_expert(self, name: str, *, install_contract: bool = False) -> tuple[str, None]:
        params = {INSTALL_SMOKE_PARAM: True} if install_contract else {}
        response = self.api.post(
            "/api/expert/run",
            {"expert_name": name, "params": params, "global": True},
            timeout=180,
        )
        if not _response_success(response):
            raise AccountInstallError(f"expert smoke was not acknowledged: {name}")
        result: Any = response.get("result", response)
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except json.JSONDecodeError:
                pass
        if isinstance(result, dict):
            if result.get("ok") is False or str(result.get("status") or "").lower() in {"error", "failed"}:
                raise AccountInstallError(f"expert smoke failed: {name}")
        if install_contract and (
            not isinstance(result, dict)
            or result.get("installSmoke") != name
            or result.get("contract") != INSTALL_SMOKE_MARKER
        ):
            raise AccountInstallError(f"expert install smoke identity mismatch: {name}")
        kind = "install smoke" if install_contract else "functional smoke"
        return f"{kind} passed: {name}", None

    def install(
        self,
        experts: Mapping[str, ExpertSource],
        *,
        required: set[str],
        smokes: set[str],
        kv_artifacts: Iterable[KVArtifact],
        agent_instructions: Mapping[str, str] | None = None,
        commit: bool = True,
    ) -> dict[str, Any]:
        missing = sorted((required | smokes) - set(experts))
        if missing:
            raise AccountInstallError(f"required expert sources are missing: {', '.join(missing[:10])}")
        self.validate_token()
        owned_agent_kv: list[KVArtifact] = []
        if agent_instructions is not None:
            _, owned_agent_kv = self.ensure_agents(agent_instructions)
        if not self.agent_id:
            raise AccountInstallError("current-account Qwen agent was not resolved")
        # Source discovery intentionally sees bundled, supported-on-demand, and
        # unverified experts. A base install owns only the explicit release
        # contract; merely being present in the source tree is never consent to
        # advertise or install an expert into every account.
        for name in sorted(required | smokes):
            source = experts[name]
            self.transaction.run(f"expert:{name}", lambda source=source: self.install_expert(source))
            self.transaction.run(
                f"install-smoke:{name}",
                lambda name=name: self.smoke_expert(name, install_contract=True),
            )
        for artifact in [*kv_artifacts, *owned_agent_kv]:
            self.transaction.run(f"kv:{artifact.key}", lambda artifact=artifact: self.install_kv(artifact))
        for name in sorted(smokes):
            self.transaction.run(
                f"functional-smoke:{name}",
                lambda name=name: self.smoke_expert(name),
            )
        return self.transaction.commit() if commit else self.transaction.prepared_report()


def prompt_token() -> str:
    return getpass.getpass("Extella token (input is hidden): ").strip()


def uninstall_account_resources(api: AccountAPI, state_file: Path) -> dict[str, Any]:
    """Restore or remove installer-owned account resources from durable state.

    A resource changed after installation is preserved and reported as requiring
    action. This prevents uninstall from overwriting later user edits.
    """

    state = json.loads(state_file.read_text(encoding="utf-8"))
    steps: list[dict[str, Any]] = []
    failed = False
    action_required = False

    def current_expert(name: str) -> dict[str, Any] | None:
        try:
            return _normalise_expert(api.post("/api/expert/get", {"name": name, "global": True}))
        except APIError as error:
            if _missing(error):
                return None
            raise

    def current_kv(key: str) -> str | None:
        try:
            response = api.post("/api/kv/get", {"key": key, "global": True})
        except APIError as error:
            if _missing(error):
                return None
            raise
        value = response.get("value")
        return value if isinstance(value, str) else None

    def apply_state(current_state: dict[str, Any]) -> None:
        nonlocal failed, action_required
        raw_changes = current_state.get("changes")
        if not isinstance(raw_changes, list):
            raise AccountInstallError("account state has no reversible change inventory")
        for raw in reversed(raw_changes):
            if not isinstance(raw, dict):
                failed = True
                steps.append({"status": "failed", "errorClass": "InvalidChange"})
                continue
            try:
                change = AccountChange(**raw)
                status = "failed"
                if change.kind == "expert":
                    current = current_expert(change.identity)
                    if current is None:
                        status = "already_absent"
                    else:
                        digest = hashlib.sha256(
                            current["code"].replace("\r\n", "\n").encode("utf-8")
                        ).hexdigest()
                        if digest != change.installed_sha256:
                            status = "preserved_modified"
                            action_required = True
                        elif change.existed:
                            if not isinstance(change.previous, dict):
                                raise AccountInstallError("expert restore snapshot is invalid")
                            response = api.post("/api/expert/save", change.previous, timeout=120)
                            if not _response_success(response):
                                raise AccountInstallError("expert restore was not acknowledged")
                            status = "restored"
                        else:
                            response = api.post(
                                "/api/expert/delete", {"name": change.identity, "global": True}
                            )
                            if not _response_success(response):
                                raise AccountInstallError("expert removal was not acknowledged")
                            status = "removed"
                elif change.kind == "kv":
                    current = current_kv(change.identity)
                    if current is None:
                        status = "already_absent"
                    elif hashlib.sha256(current.encode("utf-8")).hexdigest() != change.installed_sha256:
                        status = "preserved_modified"
                        action_required = True
                    elif change.existed:
                        if not isinstance(change.previous, str):
                            raise AccountInstallError("KV restore snapshot is invalid")
                        response = api.post(
                            "/api/kv/set",
                            {
                                "key": change.identity,
                                "value": change.previous,
                                "description": "restored by Extella uninstaller",
                                "global": True,
                            },
                        )
                        if not _response_success(response):
                            raise AccountInstallError("KV restore was not acknowledged")
                        status = "restored"
                    else:
                        response = api.post(
                            "/api/kv/remove", {"key": change.identity, "global": True}
                        )
                        if not _response_success(response):
                            raise AccountInstallError("KV removal was not acknowledged")
                        status = "removed"
                elif change.kind == "agent":
                    try:
                        api.post("/api/agent/get", {"agent_id": change.identity})
                    except APIError as error:
                        if _missing(error):
                            status = "already_absent"
                        else:
                            raise
                    else:
                        response = api.post("/api/agent/delete", {"agent_id": change.identity})
                        if not _response_success(response):
                            raise AccountInstallError("agent removal was not acknowledged")
                        status = "removed"
                else:
                    raise AccountInstallError(f"unknown account change kind: {change.kind}")
                steps.append({"kind": change.kind, "identity": change.identity, "status": status})
            except Exception as error:
                failed = True
                steps.append(
                    {
                        "kind": raw.get("kind"),
                        "identity": raw.get("identity"),
                        "status": "failed",
                        "errorClass": type(error).__name__,
                    }
                )
        previous = current_state.get("previousState")
        if not failed and not action_required and isinstance(previous, dict):
            apply_state(previous)

    apply_state(state)
    status = "failed" if failed else "action_required" if action_required else "uninstalled"
    if status == "uninstalled":
        state_file.unlink(missing_ok=True)
    return {"schemaVersion": 1, "status": status, "steps": steps}
