"""Atomic, journalled filesystem transactions for Extella installers."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
from typing import Any, Callable


class InstallationError(RuntimeError):
    """A required installation step failed and the transaction rolled back."""


@dataclass
class InstallStep:
    name: str
    status: str
    required: bool
    message: str = ""
    error_class: str | None = None
    changed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FileChange:
    target: str
    backup: str | None
    existed: bool
    sha256: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DirectoryChange:
    target: str
    backup: str | None
    existed: bool
    manifest_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


Undo = Callable[[], None]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


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
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


class InstallTransaction:
    """Collect reversible changes and commit a durable local install record.

    Creating the transaction writes nothing. Callers must complete native and
    Doctor preflight before the first mutating step.
    """

    def __init__(self, *, release_version: str, state_root: Path) -> None:
        self.release_version = release_version
        self.state_root = state_root
        self.transaction_id = f"{int(time.time())}-{os.getpid()}"
        self.backup_root = state_root / "backups" / self.transaction_id
        self.steps: list[InstallStep] = []
        self.files: list[FileChange] = []
        self.directories: list[DirectoryChange] = []
        self.changes: list[dict[str, Any]] = []
        self._undos: list[tuple[InstallStep, Undo]] = []
        self._committed = False
        self._started_at = int(time.time())

    def _backup_path(self, target: Path) -> Path:
        identity = f"{len(self.files)}:{target}"
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
        return self.backup_root / digest / target.name

    def atomic_copy(self, source: Path, target: Path) -> str:
        if not source.is_file():
            raise FileNotFoundError(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        existed = target.exists()
        backup: Path | None = None
        if existed:
            if not target.is_file():
                raise InstallationError(f"refusing to replace non-file target: {target}")
            backup = self._backup_path(target)
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, backup)
        descriptor, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
        os.close(descriptor)
        temporary_path = Path(temporary)
        try:
            shutil.copy2(source, temporary_path)
            with temporary_path.open("rb") as handle:
                os.fsync(handle.fileno())
            os.replace(temporary_path, target)
        except Exception:
            temporary_path.unlink(missing_ok=True)
            raise
        change = FileChange(
            target=str(target),
            backup=str(backup) if backup else None,
            existed=existed,
            sha256=_sha256(target),
        )
        self.files.append(change)
        self.changes.append({"kind": "file", **change.to_dict()})

        def undo() -> None:
            if backup and backup.is_file():
                os.replace(backup, target)
            elif not existed:
                target.unlink(missing_ok=True)

        self._undos.append((self.steps[-1], undo))
        return change.sha256

    def atomic_write(self, content: bytes, target: Path, *, mode: int = 0o600) -> str:
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, source_name = tempfile.mkstemp(prefix=".extella-source-")
        source = Path(source_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(source, mode)
            return self.atomic_copy(source, target)
        finally:
            source.unlink(missing_ok=True)

    @staticmethod
    def _tree_manifest_sha256(root: Path) -> str:
        digest = hashlib.sha256()
        for item in sorted(root.rglob("*"), key=lambda candidate: candidate.as_posix()):
            relative = item.relative_to(root).as_posix()
            if item.is_symlink():
                kind = "link"
                payload = os.readlink(item).encode("utf-8")
            elif item.is_file():
                kind = "file"
                payload = _sha256(item).encode("ascii")
            elif item.is_dir():
                kind = "dir"
                payload = b""
            else:
                raise InstallationError(f"unsupported filesystem entry: {item}")
            digest.update(kind.encode("ascii") + b"\0" + relative.encode("utf-8") + b"\0")
            digest.update(payload + b"\n")
        return digest.hexdigest()

    def atomic_tree(self, source: Path, target: Path) -> str:
        """Atomically replace a directory tree and retain an uninstall backup."""

        if not source.is_dir():
            raise FileNotFoundError(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        existed = target.exists()
        if existed and (not target.is_dir() or target.is_symlink()):
            raise InstallationError(f"refusing to replace non-directory target: {target}")
        backup: Path | None = None
        staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.staging-", dir=target.parent))
        try:
            shutil.rmtree(staging)
            shutil.copytree(source, staging, symlinks=True)
            manifest_sha256 = self._tree_manifest_sha256(staging)
            if existed:
                backup = self._backup_path(target)
                backup.parent.mkdir(parents=True, exist_ok=True)
                os.replace(target, backup)
            os.replace(staging, target)
        except Exception:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
            if backup and backup.exists() and not target.exists():
                os.replace(backup, target)
            raise
        change = DirectoryChange(
            target=str(target),
            backup=str(backup) if backup else None,
            existed=existed,
            manifest_sha256=manifest_sha256,
        )
        self.directories.append(change)
        self.changes.append({"kind": "directory", **change.to_dict()})

        def undo() -> None:
            if target.exists():
                shutil.rmtree(target)
            if backup and backup.is_dir():
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(backup, target)

        self._undos.append((self.steps[-1], undo))
        return manifest_sha256

    def register_undo(self, undo: Undo) -> None:
        if not self.steps:
            raise RuntimeError("register_undo must be called inside a step")
        self._undos.append((self.steps[-1], undo))

    def run(
        self,
        name: str,
        action: Callable[[], str | None],
        *,
        required: bool = True,
    ) -> bool:
        if self._committed:
            raise RuntimeError("transaction is already committed")
        step = InstallStep(name=name, status="running", required=required)
        self.steps.append(step)
        undo_count = len(self._undos)
        try:
            message = action()
        except Exception as exc:
            step.status = "failed"
            step.message = str(exc)[:500]
            step.error_class = type(exc).__name__
            if not required:
                return False
            self.rollback(failed_step=name)
            raise InstallationError(f"required step failed: {name}") from exc
        step.status = "installed" if len(self._undos) > undo_count else "skipped"
        step.changed = len(self._undos) > undo_count
        step.message = message or "completed"
        return True

    def rollback(self, *, failed_step: str | None = None) -> None:
        rollback_errors: list[str] = []
        for step, undo in reversed(self._undos):
            try:
                undo()
                if step.status in {"installed", "running"}:
                    step.status = "rolled_back"
                    step.changed = False
            except Exception as exc:
                rollback_errors.append(f"{step.name}: {type(exc).__name__}")
        self._undos.clear()
        payload = self.report(status="rollback_failed" if rollback_errors else "rolled_back")
        payload["failedStep"] = failed_step
        payload["rollbackErrors"] = rollback_errors
        _atomic_json(self.state_root / "last-install-report.json", payload)

    def commit(self) -> dict[str, Any]:
        if self._committed:
            raise RuntimeError("transaction is already committed")
        if any(step.required and step.status == "failed" for step in self.steps):
            raise InstallationError("cannot commit a transaction with failed required steps")
        payload = self.report(status="installed")
        _atomic_json(self.state_root / "install-state.json", payload)
        _atomic_json(self.state_root / "last-install-report.json", payload)
        self._committed = True
        return payload

    def report(self, *, status: str) -> dict[str, Any]:
        return {
            "schemaVersion": 1,
            "transactionId": self.transaction_id,
            "releaseVersion": self.release_version,
            "status": status,
            "startedAt": self._started_at,
            "finishedAt": int(time.time()),
            "steps": [step.to_dict() for step in self.steps],
            "files": [change.to_dict() for change in self.files],
            "directories": [change.to_dict() for change in self.directories],
            "changes": self.changes,
        }


def uninstall_from_state(state_file: Path, *, preserve: tuple[Path, ...] = ()) -> dict[str, Any]:
    """Remove owned files or restore their pre-install backups.

    Explicit preserve paths protect user-created data even if a malformed old
    state file accidentally lists them.
    """

    data = json.loads(state_file.read_text(encoding="utf-8"))
    ordered: list[FileChange | DirectoryChange] = []
    if isinstance(data.get("changes"), list):
        for item in data["changes"]:
            if not isinstance(item, dict):
                continue
            payload = {key: value for key, value in item.items() if key != "kind"}
            if item.get("kind") == "directory":
                ordered.append(DirectoryChange(**payload))
            elif item.get("kind") == "file":
                ordered.append(FileChange(**payload))
    else:
        # Compatibility with state written before ordered change journalling.
        ordered.extend(FileChange(**item) for item in data.get("files", []))
        ordered.extend(DirectoryChange(**item) for item in data.get("directories", []))
    preserved = {path.resolve() for path in preserve}
    steps: list[dict[str, Any]] = []
    failed = False
    for change in reversed(ordered):
        target = Path(change.target)
        try:
            resolved = target.resolve()
        except OSError:
            resolved = target.absolute()
        if any(resolved == item or item in resolved.parents for item in preserved):
            steps.append({"target": str(target), "status": "preserved"})
            continue
        try:
            backup = Path(change.backup) if change.backup else None
            if change.existed and backup and backup.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.is_dir() and not target.is_symlink():
                    shutil.rmtree(target)
                else:
                    target.unlink(missing_ok=True)
                os.replace(backup, target)
                status = "restored"
            else:
                if target.is_dir() and not target.is_symlink():
                    shutil.rmtree(target)
                else:
                    target.unlink(missing_ok=True)
                status = "removed"
            steps.append({"target": str(target), "status": status})
        except OSError as exc:
            failed = True
            steps.append(
                {"target": str(target), "status": "failed", "errorClass": type(exc).__name__}
            )
    return {"schemaVersion": 1, "status": "failed" if failed else "uninstalled", "steps": steps}
