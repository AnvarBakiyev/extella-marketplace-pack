"""Transactional installation of Extella cloud-account resources."""

from __future__ import annotations

import ast
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
BOOTSTRAP_AGENT_SCOPE = "agent_XXXXXXXX"
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

    def __init__(
        self,
        token: str,
        *,
        api_base: str = "https://api.extella.ai",
        agent_scope: str = BOOTSTRAP_AGENT_SCOPE,
    ) -> None:
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

    def set_agent_scope(self, agent_id: str) -> None:
        """Bind subsequent account-resource calls to a verified current-account agent."""

        if not SAFE_AGENT_ID.fullmatch(agent_id) or agent_id == BOOTSTRAP_AGENT_SCOPE:
            raise AccountInstallError("invalid current-account API scope agent")
        self.agent_scope = agent_id

    def post(self, endpoint: str, payload: Mapping[str, Any], *, timeout: int = 90) -> dict[str, Any]:
        if not endpoint.startswith("/api/"):
            raise APIError(endpoint, "invalid_endpoint")
        body = dict(payload)
        if endpoint == "/api/token/validate":
            # The live Extella API requires the token in the validation body
            # as well as the auth header. Keep this injection inside the
            # secret-owning client so callers never read, log, or persist it.
            body = {"token": self._token}
        request = urllib.request.Request(
            self.api_base + endpoint,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
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
                if not code and isinstance(parsed.get("detail"), list):
                    details: list[str] = []
                    for item in parsed["detail"][:4]:
                        if not isinstance(item, dict):
                            continue
                        location = item.get("loc")
                        where = ".".join(str(value) for value in location) if isinstance(location, list) else "body"
                        kind = str(item.get("type") or "validation_error")
                        details.append(f"{where}:{kind}")
                    code = "validation:" + ",".join(details) if details else "validation_error"
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


def scope_api_to_agent(api: AccountAPI, agent_id: str) -> None:
    """Use a current-account agent scope when the concrete API supports it."""

    if not SAFE_AGENT_ID.fullmatch(agent_id) or agent_id == BOOTSTRAP_AGENT_SCOPE:
        raise AccountInstallError("a valid current-account API scope agent is required")
    setter = getattr(api, "set_agent_scope", None)
    if callable(setter):
        setter(agent_id)


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
                if isinstance(error, APIError):
                    status = str(error.http_status) if error.http_status is not None else "network"
                    errors.append(f"APIError:{error.error_class}:{status}")
                else:
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
        ("release/catalog-policy.json", "_mkt_release_policy", "release catalog classification policy"),
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


def _delete_success(response: Mapping[str, Any]) -> bool:
    """Accept both documented status responses and the live message-only delete acknowledgement."""

    if _response_success(response):
        return True
    message = str(response.get("message") or "").strip().lower()
    return any(marker in message for marker in ("deleted", "removed", "удален", "удалён"))


def _missing(error: APIError) -> bool:
    message = error.code.lower()
    return error.http_status == 404 or "not found" in message or "не найден" in message


def _normalise_expert(response: Mapping[str, Any]) -> dict[str, Any] | None:
    code = response.get("expert_code") or response.get("code")
    if not isinstance(code, str) or not code.strip():
        return None
    kwargs = response.get("kwargs")
    if not isinstance(kwargs, dict):
        kwargs = response.get("expert_params")
    return {
        "name": str(response.get("name") or response.get("expert_name") or ""),
        "description": str(
            response.get("description") or response.get("expert_description") or ""
        ),
        "code": code,
        "kwargs": kwargs if isinstance(kwargs, dict) else {},
        "cspl": str(response.get("cspl") or "fython"),
        "global": bool(response.get("global", True)),
    }


def _restorable_expert_snapshot(change: AccountChange) -> tuple[dict[str, Any], list[str]]:
    """Validate a snapshot and repair metadata lost by the pre-2.0 live-field parser."""

    if not isinstance(change.previous, dict):
        raise AccountInstallError("expert restore snapshot is invalid")
    payload = dict(change.previous)
    if payload.get("name") != change.identity:
        raise AccountInstallError("expert restore snapshot identity is invalid")
    code = payload.get("code")
    if not isinstance(code, str) or not code.strip():
        raise AccountInstallError("expert restore snapshot code is invalid")
    _name, header_description, header_kwargs = _expert_header(code, change.identity)
    reconstructed: list[str] = []
    if not isinstance(payload.get("description"), str) or not payload["description"].strip():
        payload["description"] = header_description
        reconstructed.append("description")
    if not isinstance(payload.get("kwargs"), dict):
        payload["kwargs"] = header_kwargs
        reconstructed.append("kwargs")
    elif not payload["kwargs"] and header_kwargs:
        payload["kwargs"] = header_kwargs
        reconstructed.append("kwargs")
    if not isinstance(payload.get("cspl"), str) or not payload["cspl"].strip():
        payload["cspl"] = "fython"
        reconstructed.append("cspl")
    payload["global"] = bool(payload.get("global", True))
    return payload, reconstructed


def _canonical_expert_code(code: str) -> str:
    """Match the live API's harmless newline normalization for code identity checks."""

    return code.replace("\r\n", "\n").rstrip("\n") + "\n"


def _retry_transient_api(action: Callable[[], Any]) -> Any:
    """Retry bounded, idempotent account mutations during rollback.

    The live account API can briefly throttle a long clean-account install.
    Rollback mutations are restore-by-identity or delete-by-identity, so they
    are safe to retry without creating duplicate resources.
    """

    last_error: APIError | None = None
    for attempt, delay in enumerate((0.0, 0.5, 1.5, 3.0), start=1):
        if delay:
            time.sleep(delay)
        try:
            return action()
        except APIError as error:
            last_error = error
            retryable = (
                error.http_status is None
                or error.http_status in {408, 425, 429}
                or error.http_status >= 500
            )
            if not retryable or attempt == 4:
                raise
    raise last_error or AccountInstallError("transient account mutation failed")


def _structured_result(value: Any) -> Any:
    """Decode live fython literals and bounded nested result envelopes."""

    for _ in range(6):
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                try:
                    parsed = ast.literal_eval(value)
                except (SyntaxError, ValueError):
                    return value
            if parsed == value:
                return value
            value = parsed
            continue
        if isinstance(value, dict) and "result" in value:
            nested = value.get("result")
            if nested is not value:
                value = nested
                continue
        return value
    return value


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
            not SAFE_AGENT_ID.fullmatch(agent_id) or agent_id == BOOTSTRAP_AGENT_SCOPE
        ):
            raise AccountInstallError("a valid current-account Qwen agent id is required")
        self.api = api
        self.agent_id = agent_id or ""
        self.token_agent_id = ""
        self._smoked_agents: set[str] = set()
        self.release_version = release_version
        self.transaction = AccountTransaction(release_version=release_version, state_root=state_root)
        if self.agent_id:
            self._scope_api(self.agent_id)

    def _scope_api(self, agent_id: str) -> None:
        scope_api_to_agent(self.api, agent_id)

    def validate_token(self) -> None:
        response = _retry_transient_api(
            lambda: self.api.post("/api/token/validate", {})
        )
        if not _response_success(response):
            raise AccountInstallError("Extella token validation failed")
        # A live token validation returns the platform Qwen assigned to the
        # current account. It is already keyless and runnable. API-created
        # Alibaba agents are Pro custom agents and require a provider key, so
        # they must never be used as the clean-account bootstrap path.
        if self.agent_id:
            return
        agent_id = self._agent_id(response)
        if not agent_id:
            raise AccountInstallError("token validation returned no current-account agent")
        self._scope_api(agent_id)
        if not self._verified_qwen(self._get_agent(agent_id)):
            raise AccountInstallError("token-associated agent is not the required Qwen")
        self._smoke_agent(agent_id)
        self.agent_id = agent_id
        self.token_agent_id = agent_id

    def _get_expert(self, name: str) -> dict[str, Any] | None:
        try:
            return _normalise_expert(
                _retry_transient_api(
                    lambda: self.api.post(
                        "/api/expert/get", {"name": name, "global": True}
                    )
                )
            )
        except APIError as error:
            if _missing(error):
                return None
            raise

    def _save_expert_payload(self, payload: Mapping[str, Any]) -> None:
        response = _retry_transient_api(
            lambda: self.api.post("/api/expert/save", payload, timeout=120)
        )
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
            response = _retry_transient_api(
                lambda: self.api.post("/api/agent/get", {"agent_id": agent_id})
            )
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
        if agent_id in self._smoked_agents:
            return
        payload = {
            "agent_id": agent_id,
            "input": "Reply with exactly: EXTELLA_READY",
            "store": False,
            "run_timeout": 90,
        }
        last_error: Exception | None = None
        for attempt, delay in enumerate((0.0, 0.5, 1.5), start=1):
            if delay:
                time.sleep(delay)
            try:
                response = self.api.post("/api/agent/run", payload, timeout=140)
            except APIError as error:
                last_error = error
                code = error.code.lower()
                permanent = any(
                    marker in code
                    for marker in ("pro_key_required", "does not belong", "forbidden", "invalid token")
                )
                retryable = (
                    not permanent
                    and (
                        error.http_status is None
                        or error.http_status in {408, 425, 429}
                        or error.http_status >= 500
                        or "incorrect api key provided" in code
                    )
                )
                if not retryable or attempt == 3:
                    raise AccountInstallError("Qwen agent smoke failed") from error
                continue
            serialized = json.dumps(response, ensure_ascii=False).lower()
            if (
                _response_success(response)
                and "extella_ready" in serialized
                and "pro_key_required" not in serialized
                and "does not belong" not in serialized
            ):
                self._smoked_agents.add(agent_id)
                return
            last_error = AccountInstallError("Qwen agent smoke returned an invalid result")
            break
        raise AccountInstallError("Qwen agent smoke failed") from last_error

    def ensure_agent(self, *, role: str, name: str, instructions: str, existing_id: str = "") -> tuple[str, Callable[[], None] | None]:
        if existing_id:
            try:
                self._scope_api(existing_id)
                current = self._get_agent(existing_id)
                if self._verified_qwen(current):
                    self._smoke_agent(existing_id)
                    return f"Qwen agent verified: {role}:{existing_id}", None
            except (APIError, AccountInstallError):
                # Stale ownership may reference a removed agent or an old Pro
                # custom agent that now requires BYOK. The token-associated
                # platform Qwen remains the deterministic repair path.
                pass
        if not self.token_agent_id:
            raise AccountInstallError(f"no runnable token-associated Qwen is available: {role}")
        self._scope_api(self.token_agent_id)
        current = self._get_agent(self.token_agent_id)
        if not self._verified_qwen(current):
            raise AccountInstallError(f"token-associated agent is not the required Qwen: {role}")
        self._smoke_agent(self.token_agent_id)
        return f"account Qwen verified: {role}:{self.token_agent_id}", None

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
        self._scope_api(self.agent_id)
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
                response = _retry_transient_api(
                    lambda: self.api.post(
                        "/api/expert/delete", {"name": source.name}
                    )
                )
                if not _delete_success(response):
                    raise AccountInstallError("expert rollback delete failed")
            else:
                _retry_transient_api(lambda: self._save_expert_payload(previous))

        self.transaction.register_undo(undo)
        self._save_expert_payload(payload)
        installed = self._get_expert(source.name)
        if installed is None or _canonical_expert_code(installed["code"]) != _canonical_expert_code(code):
            raise AccountInstallError(f"expert verification failed: {source.name}")
        self.transaction.register_change(
            AccountChange(
                "expert",
                source.name,
                previous is not None,
                hashlib.sha256(_canonical_expert_code(code).encode("utf-8")).hexdigest(),
                previous,
            )
        )
        return f"expert verified: {source.name}", None

    def _get_kv(self, key: str) -> str | None:
        try:
            response = _retry_transient_api(
                lambda: self.api.post("/api/kv/get", {"key": key, "global": True})
            )
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
                result = _retry_transient_api(
                    lambda: self.api.post(
                        "/api/kv/remove", {"key": artifact.key}
                    )
                )
                acknowledged = _delete_success(result)
            else:
                result = _retry_transient_api(
                    lambda: self.api.post(
                        "/api/kv/set",
                        {
                            "key": artifact.key,
                            "value": previous,
                            "description": "restored by Extella installer",
                            "global": True,
                        },
                    )
                )
                acknowledged = _response_success(result)
            if not acknowledged:
                raise AccountInstallError("KV rollback failed")

        self.transaction.register_undo(undo)
        response = _retry_transient_api(
            lambda: self.api.post(
                "/api/kv/set",
                {
                    "key": artifact.key,
                    "value": artifact.value,
                    "description": artifact.description,
                    "global": True,
                },
            )
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
        response = _retry_transient_api(
            lambda: self.api.post(
                "/api/expert/run",
                {"expert_name": name, "params": params, "global": True},
                timeout=180,
            )
        )
        if not _response_success(response):
            raise AccountInstallError(f"expert smoke was not acknowledged: {name}")
        result: Any = _structured_result(response.get("result", response))
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
    for raw in state.get("changes") or []:
        if isinstance(raw, dict) and raw.get("kind") == "agent":
            identity = str(raw.get("identity") or "")
            if SAFE_AGENT_ID.fullmatch(identity):
                scope_api_to_agent(api, identity)
                break
    steps: list[dict[str, Any]] = []
    failed = False
    action_required = False

    def current_expert(name: str) -> dict[str, Any] | None:
        try:
            return _normalise_expert(
                _retry_transient_api(
                    lambda: api.post("/api/expert/get", {"name": name, "global": True})
                )
            )
        except APIError as error:
            if _missing(error):
                return None
            raise

    def current_kv(key: str) -> str | None:
        try:
            response = _retry_transient_api(
                lambda: api.post("/api/kv/get", {"key": key, "global": True})
            )
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
                reconstructed_fields: list[str] = []
                if change.kind == "expert":
                    previous_payload: dict[str, Any] | None = None
                    if change.existed:
                        previous_payload, reconstructed_fields = _restorable_expert_snapshot(change)
                    current = current_expert(change.identity)
                    if current is None:
                        status = "already_absent"
                    else:
                        digest = hashlib.sha256(
                            _canonical_expert_code(current["code"]).encode("utf-8")
                        ).hexdigest()
                        previous_digest = ""
                        if change.existed:
                            if previous_payload is None:
                                raise AccountInstallError("expert restore snapshot is invalid")
                            previous_digest = hashlib.sha256(
                                _canonical_expert_code(previous_payload["code"]).encode("utf-8")
                            ).hexdigest()
                        if previous_digest and digest == previous_digest:
                            status = "already_restored"
                        elif digest != change.installed_sha256:
                            status = "preserved_modified"
                            action_required = True
                        elif change.existed:
                            if previous_payload is None:
                                raise AccountInstallError("expert restore snapshot is invalid")
                            response = _retry_transient_api(
                                lambda: api.post(
                                    "/api/expert/save", previous_payload, timeout=120
                                )
                            )
                            if not _response_success(response):
                                raise AccountInstallError("expert restore was not acknowledged")
                            restored = current_expert(change.identity)
                            if restored is None or _canonical_expert_code(
                                restored["code"]
                            ) != _canonical_expert_code(previous_payload["code"]):
                                raise AccountInstallError("expert restore verification failed")
                            status = "restored"
                        else:
                            response = _retry_transient_api(
                                lambda: api.post(
                                    "/api/expert/delete",
                                    {"name": change.identity},
                                )
                            )
                            if not _delete_success(response):
                                raise AccountInstallError("expert removal was not acknowledged")
                            status = "removed"
                elif change.kind == "kv":
                    current = current_kv(change.identity)
                    if current is None:
                        status = "already_absent"
                    elif change.existed and not isinstance(change.previous, str):
                        raise AccountInstallError("KV restore snapshot is invalid")
                    elif change.existed and current == change.previous:
                        status = "already_restored"
                    elif hashlib.sha256(current.encode("utf-8")).hexdigest() != change.installed_sha256:
                        status = "preserved_modified"
                        action_required = True
                    elif change.existed:
                        response = _retry_transient_api(
                            lambda: api.post(
                                "/api/kv/set",
                                {
                                    "key": change.identity,
                                    "value": change.previous,
                                    "description": "restored by Extella uninstaller",
                                    "global": True,
                                },
                            )
                        )
                        if not _response_success(response):
                            raise AccountInstallError("KV restore was not acknowledged")
                        status = "restored"
                    else:
                        response = _retry_transient_api(
                            lambda: api.post(
                                "/api/kv/remove",
                                {"key": change.identity},
                            )
                        )
                        if not _delete_success(response):
                            raise AccountInstallError("KV removal was not acknowledged")
                        status = "removed"
                elif change.kind == "agent":
                    try:
                        _retry_transient_api(
                            lambda: api.post(
                                "/api/agent/get", {"agent_id": change.identity}
                            )
                        )
                    except APIError as error:
                        if _missing(error):
                            status = "already_absent"
                        else:
                            raise
                    else:
                        response = _retry_transient_api(
                            lambda: api.post(
                                "/api/agent/delete", {"agent_id": change.identity}
                            )
                        )
                        if not _delete_success(response):
                            raise AccountInstallError("agent removal was not acknowledged")
                        status = "removed"
                else:
                    raise AccountInstallError(f"unknown account change kind: {change.kind}")
                step = {"kind": change.kind, "identity": change.identity, "status": status}
                if reconstructed_fields:
                    step["reconstructedFields"] = reconstructed_fields
                steps.append(step)
            except Exception as error:
                failed = True
                failure = {
                    "kind": raw.get("kind"),
                    "identity": raw.get("identity"),
                    "status": "failed",
                    "errorClass": type(error).__name__,
                }
                if isinstance(error, APIError):
                    failure["endpoint"] = error.endpoint
                    failure["apiErrorClass"] = error.error_class
                    failure["httpStatus"] = error.http_status
                    if error.code:
                        failure["apiCode"] = error.code
                steps.append(failure)
        previous = current_state.get("previousState")
        if not failed and not action_required and isinstance(previous, dict):
            apply_state(previous)

    apply_state(state)
    status = "failed" if failed else "action_required" if action_required else "uninstalled"
    if status == "uninstalled":
        state_file.unlink(missing_ok=True)
    return {"schemaVersion": 1, "status": status, "steps": steps}


def repair_interrupted_account(api: AccountAPI, state_file: Path) -> dict[str, Any] | None:
    """Finish a durable failed rollback before accepting a new baseline."""

    if not state_file.exists():
        return None
    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise AccountInstallError("interrupted account state is unreadable") from error
    if not isinstance(state, dict) or state.get("status") != "rollback_failed":
        return None
    validator = AccountInstaller(
        api,
        release_version=str(state.get("releaseVersion") or "unknown"),
        state_root=state_file.parent,
    )
    validator.validate_token()
    report = uninstall_account_resources(api, state_file)
    _atomic_json(state_file.parent / "last-account-repair-report.json", report)
    if report.get("status") != "uninstalled":
        statuses = [
            str(step.get("status") or "")
            for step in report.get("steps") or []
            if isinstance(step, dict)
        ]
        raise AccountInstallError(
            "interrupted account rollback did not complete: "
            f"status={report.get('status')}, failed={statuses.count('failed')}, "
            f"preserved_modified={statuses.count('preserved_modified')}"
        )
    return report
