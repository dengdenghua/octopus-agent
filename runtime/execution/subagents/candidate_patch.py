"""Inspect, apply, and reconcile isolated candidate patches under host control.

An engine may return a patch hash, but it never chooses the patch path, source
workspace, baseline, backup location, or file ownership.  Those coordinates
come from the authenticated turn's append-only handoff journal.  Application
is a write-ahead transaction: journal and lease the complete file set, apply
once, verify exact bytes, and either commit or restore byte-for-byte backups.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import uuid4

from runtime.execution.artifact_contracts import HandoffRecorder
from runtime.execution.misc.file_write_leases import (
    _content_fingerprint,
    _same_content_fingerprint,
    transfer_file_write_leases,
)
from runtime.execution.request import ExecutionTask
from runtime.execution.subagents.execution_context import parent_execution_task
from runtime.execution.subagents.isolated_worktree import _git
from runtime.execution.subagents.worktree_loop import _cap_diff
from runtime.platform.io.atomic import _cross_process_lock, atomic_write_bytes
from runtime.platform.process.session import Session
from runtime.safety.approval.cancellation import current_cancellation_token
from runtime.safety.auth import check_file_write, check_path

_MAX_CHANGED_FILES = 64
_MAX_FILE_BYTES = 32 * 1024 * 1024
_MAX_BACKUP_BYTES = 64 * 1024 * 1024
_PROJECT_APPLY_LOCK = threading.RLock()
_REGULAR_MODES = frozenset({"100644", "100755"})
_MISSING_MODE = "000000"
_SETTLED_PHASES = frozenset({"patch_applied", "patch_apply_rolled_back"})


class CandidatePatchError(RuntimeError):
    """A candidate failed a host-owned validation or transaction rule."""


@dataclass(slots=True)
class CandidateChange:
    relative_path: str
    path: Path
    status: str
    old_mode: str
    new_mode: str
    old_blob: str
    new_blob: str
    before: dict[str, Any] | None = None
    expected_after: dict[str, Any] | None = None
    backup: dict[str, Any] | None = None

    def to_receipt(self) -> dict[str, Any]:
        return {
            "path": self.relative_path,
            "target": str(self.path),
            "status": self.status,
            "old_mode": self.old_mode,
            "new_mode": self.new_mode,
            "old_blob": self.old_blob,
            "new_blob": self.new_blob,
            "before": dict(self.before or {}),
            "expected_after": dict(self.expected_after or {}),
            "backup": dict(self.backup) if self.backup is not None else None,
        }


@dataclass(frozen=True, slots=True)
class CandidateAnalysis:
    candidate_sha256: str
    source: Path
    baseline: str
    baseline_ref: str
    patch_path: Path
    patch_ref: dict[str, Any]
    contract_valid: bool
    changes: tuple[CandidateChange, ...]


def _safe_error(exc: BaseException) -> str:
    if isinstance(exc, subprocess.CalledProcessError):
        raw = exc.stderr
        if isinstance(raw, bytes):
            detail = raw.decode("utf-8", errors="replace").strip()
        else:
            detail = str(raw or "").strip()
        if detail:
            return detail[-600:]
    text = str(exc).strip() or type(exc).__name__
    return text[-600:]


def _require_host(session: Any) -> tuple[Session, ExecutionTask, HandoffRecorder]:
    if not isinstance(session, Session):
        raise CandidatePatchError("candidate patches require an active host Session")
    task = parent_execution_task(session)
    if task is None:
        raise CandidatePatchError("candidate patches require a host-scoped task")
    recorder = session.metadata.get("_execution_handoff_recorder")
    if not isinstance(recorder, HandoffRecorder) or recorder.read is None:
        raise CandidatePatchError("candidate patches require a readable durable host journal")
    return session, task, recorder


def _records(recorder: HandoffRecorder) -> tuple[dict[str, Any], ...]:
    assert recorder.read is not None
    rows = recorder.read()
    if not isinstance(rows, tuple) or any(not isinstance(row, dict) for row in rows):
        raise CandidatePatchError("host handoff journal returned an invalid snapshot")
    return tuple(dict(row) for row in rows)


def _valid_sha256(value: Any, *, label: str) -> str:
    text = str(value or "").strip().lower()
    if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
        raise CandidatePatchError(f"{label} must be a SHA-256 digest")
    return text


def _valid_git_oid(value: Any, *, label: str) -> str:
    text = str(value or "").strip().lower()
    if len(text) not in {40, 64} or any(char not in "0123456789abcdef" for char in text):
        raise CandidatePatchError(f"{label} is not a valid Git object id")
    return text


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(str(left)) == os.path.normcase(str(right))


def _trusted_source(session: Session, task: ExecutionTask, *, write: bool) -> Path:
    raw = session.metadata.get("workspace_path")
    if not isinstance(raw, str) or not raw.strip() or not Path(raw).is_absolute():
        raise CandidatePatchError("candidate patch requires the approved project directory")
    selected = Path(raw).expanduser().resolve(strict=True)
    if not task.permissions.allows_read(selected):
        raise PermissionError("project directory is outside the task read scope")
    source = Path(_git(selected, "rev-parse", "--show-toplevel").strip()).resolve(strict=True)
    if not task.permissions.allows_read(source):
        raise PermissionError("repository root is outside the task read scope")
    if write and not task.permissions.allows_write(source):
        raise PermissionError("repository root is outside the task write scope")
    return source


def _artifact_root(session: Session, task: ExecutionTask) -> Path:
    raw = session.metadata.get("_artifact_output_root") or task.permissions.primary_write
    if raw is None:
        raise PermissionError("candidate patch requires an approved artifact directory")
    root = Path(raw).expanduser()
    if not root.is_absolute():
        raise PermissionError("candidate artifact directory must be absolute")
    root = root.resolve(strict=False)
    if not task.permissions.allows_read(root) or not task.permissions.allows_write(root):
        raise PermissionError("candidate artifact directory is outside the task scope")
    root.mkdir(parents=True, exist_ok=True)
    resolved = root.resolve(strict=True)
    if not _same_path(root, resolved) or not resolved.is_dir():
        raise CandidatePatchError("candidate artifact directory changed through a symbolic link")
    return resolved


def _candidate_storage(root: Path) -> Path:
    storage = (root / ".execution" / "candidate-patches").resolve(strict=False)
    if not storage.is_relative_to(root):
        raise CandidatePatchError("candidate storage escaped the artifact directory")
    storage.mkdir(parents=True, exist_ok=True)
    resolved = storage.resolve(strict=True)
    if not _same_path(storage, resolved):
        raise CandidatePatchError("candidate storage changed through a symbolic link")
    return resolved


def _find_export(records: tuple[dict[str, Any], ...], candidate_sha256: str) -> dict[str, Any]:
    for row in reversed(records):
        patch = row.get("patch")
        if (
            row.get("phase") == "worktree_exported"
            and isinstance(patch, dict)
            and str(patch.get("sha256") or "").strip().lower() == candidate_sha256
        ):
            return row
    raise CandidatePatchError("candidate hash was not issued by this thread's host journal")


def _find_inspection(records: tuple[dict[str, Any], ...], inspection_id: str) -> dict[str, Any]:
    for row in reversed(records):
        if row.get("phase") == "patch_inspected" and row.get("inspection_id") == inspection_id:
            return row
    raise CandidatePatchError("inspection id was not issued by this thread's host journal")


def _find_start(records: tuple[dict[str, Any], ...], operation_id: str) -> dict[str, Any]:
    for row in reversed(records):
        if row.get("phase") == "patch_apply_started" and row.get("operation_id") == operation_id:
            return row
    raise CandidatePatchError("operation id was not issued by this thread's host journal")


def _latest_inspection_operation(
    records: tuple[dict[str, Any], ...], inspection_id: str
) -> tuple[dict[str, Any], dict[str, Any] | None] | None:
    start_index = -1
    start: dict[str, Any] | None = None
    for index, row in enumerate(records):
        if row.get("phase") == "patch_apply_started" and row.get("inspection_id") == inspection_id:
            start_index = index
            start = row
    if start is None:
        return None
    operation_id = start.get("operation_id")
    outcome = None
    for row in records[start_index + 1 :]:
        if row.get("operation_id") == operation_id and row.get("phase") in _SETTLED_PHASES:
            outcome = row
    return start, outcome


def _validate_patch_reference(
    reference: Any,
    *,
    task: ExecutionTask,
    artifact_root: Path,
) -> tuple[Path, dict[str, Any]]:
    if not isinstance(reference, dict):
        raise CandidatePatchError("candidate receipt has no patch reference")
    raw_path = reference.get("path")
    if not isinstance(raw_path, str) or not raw_path or not Path(raw_path).is_absolute():
        raise CandidatePatchError("candidate patch reference is not absolute")
    lexical = Path(raw_path).expanduser()
    path = lexical.resolve(strict=True)
    if not _same_path(lexical, path) or not path.is_relative_to(artifact_root):
        raise CandidatePatchError("candidate patch reference escaped trusted artifact storage")
    if not task.permissions.allows_read(path):
        raise PermissionError("candidate patch is outside the task read scope")
    expected_sha = _valid_sha256(reference.get("sha256"), label="candidate patch hash")
    expected_size = reference.get("size")
    if type(expected_size) is not int or expected_size < 0 or expected_size > _MAX_FILE_BYTES:
        raise CandidatePatchError("candidate patch size is invalid or exceeds 32 MiB")
    actual = _capture_fingerprint(path, expected_mode="100644")
    if actual["sha256"] != expected_sha or actual["size"] != expected_size:
        raise CandidatePatchError("candidate patch bytes no longer match the host receipt")
    return path, {
        "path": str(path),
        "sha256": expected_sha,
        "size": expected_size,
        "producer_task_id": reference.get("producer_task_id"),
    }


def _validate_baseline(source: Path, receipt: dict[str, Any]) -> tuple[str, str]:
    raw_source = receipt.get("source_workspace")
    if not isinstance(raw_source, str) or not Path(raw_source).is_absolute():
        raise CandidatePatchError("candidate receipt has no source workspace")
    issued_source = Path(raw_source).expanduser().resolve(strict=True)
    if not _same_path(source, issued_source):
        raise CandidatePatchError("candidate belongs to a different project workspace")
    baseline = _valid_git_oid(receipt.get("baseline_commit"), label="candidate baseline")
    baseline_ref = str(receipt.get("baseline_ref") or "").strip()
    if not baseline_ref.startswith("refs/octopus/execution-snapshots/") or any(
        part in {"", ".", ".."} for part in baseline_ref.split("/")
    ):
        raise CandidatePatchError("candidate baseline reference is invalid")
    resolved = _git(source, "rev-parse", "--verify", f"{baseline_ref}^{{commit}}").strip()
    if resolved.lower() != baseline:
        raise CandidatePatchError("candidate baseline reference changed after export")
    return baseline, baseline_ref


def _validate_relative_path(raw: Any) -> str:
    if not isinstance(raw, str) or not raw or "\x00" in raw or "\\" in raw or ":" in raw:
        raise CandidatePatchError("candidate contains an unsafe file path")
    relative = PurePosixPath(raw)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise CandidatePatchError("candidate contains a path outside the project")
    if any(part.casefold() == ".git" for part in relative.parts):
        raise CandidatePatchError("candidate cannot modify Git control files")
    return relative.as_posix()


def _declared_write_allowed(session: Session, source: Path, target: Path) -> bool:
    if "allowed_write_paths" not in session.metadata:
        return True
    declared = session.metadata.get("allowed_write_paths")
    workspace_raw = session.metadata.get("workspace_path")
    if not isinstance(declared, list) or not declared:
        return False
    if not isinstance(workspace_raw, str) or not Path(workspace_raw).is_absolute():
        return False
    workspace = Path(workspace_raw).expanduser().resolve(strict=False)
    allowed: set[str] = set()
    for item in declared:
        if not isinstance(item, str) or not item.strip():
            continue
        raw_relative = item.strip().replace("\\", "/")
        try:
            relative = PurePosixPath(raw_relative)
        except ValueError:
            continue
        if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
            continue
        candidate = (workspace / Path(*relative.parts)).resolve(strict=False)
        if candidate.is_relative_to(workspace):
            allowed.add(os.path.normcase(str(candidate)))
    return target.is_relative_to(source) and os.path.normcase(str(target)) in allowed


def _validate_target(
    session: Session,
    task: ExecutionTask,
    source: Path,
    storage: Path,
    relative_path: str,
    *,
    require_write: bool,
) -> Path:
    relative = PurePosixPath(relative_path)
    target = source.joinpath(*relative.parts)
    resolved = target.resolve(strict=False)
    if not _same_path(target, resolved) or not resolved.is_relative_to(source):
        raise CandidatePatchError(
            f"candidate path changed through a symbolic link: {relative_path}"
        )
    if resolved.is_relative_to(storage):
        raise CandidatePatchError("candidate cannot modify host transaction storage")
    if not task.permissions.allows_read(resolved):
        raise PermissionError(f"candidate path is outside the task read scope: {relative_path}")
    if require_write and not task.permissions.allows_write(resolved):
        raise PermissionError(f"candidate path is outside the task write scope: {relative_path}")
    path_verdict = check_path(resolved, sandbox_dir=source)
    if not path_verdict.allow:
        raise PermissionError(f"candidate path is blocked: {path_verdict.reason}")
    write_verdict = check_file_write(resolved)
    if not write_verdict.allow:
        raise PermissionError(f"candidate write is blocked: {write_verdict.reason}")
    if not _declared_write_allowed(session, source, resolved):
        raise PermissionError(
            f"candidate path is outside the task write allowlist: {relative_path}"
        )
    return resolved


def _parse_tree_changes(raw: str) -> list[tuple[str, str, str, str, str, str]]:
    parts = raw.split("\x00")
    if parts and parts[-1] == "":
        parts.pop()
    if len(parts) % 2:
        raise CandidatePatchError("Git returned an invalid candidate tree diff")
    result: list[tuple[str, str, str, str, str, str]] = []
    for index in range(0, len(parts), 2):
        metadata, path = parts[index], parts[index + 1]
        fields = metadata.split()
        if len(fields) != 5 or not fields[0].startswith(":"):
            raise CandidatePatchError("Git returned an invalid candidate tree entry")
        old_mode = fields[0][1:]
        new_mode, old_blob, new_blob, status = fields[1:]
        if status not in {"A", "M", "D"}:
            raise CandidatePatchError(f"candidate change type is unsupported: {status}")
        if old_mode not in _REGULAR_MODES | {_MISSING_MODE}:
            raise CandidatePatchError("candidate old file type is unsupported")
        if new_mode not in _REGULAR_MODES | {_MISSING_MODE}:
            raise CandidatePatchError("candidate new file type is unsupported")
        transition = (old_mode == _MISSING_MODE, new_mode == _MISSING_MODE)
        if transition == (True, False) and status != "A":
            raise CandidatePatchError("candidate add transition is invalid")
        if transition == (False, True) and status != "D":
            raise CandidatePatchError("candidate delete transition is invalid")
        if transition == (False, False) and status != "M":
            raise CandidatePatchError("candidate modify transition is invalid")
        if transition == (True, True):
            raise CandidatePatchError("candidate file transition is invalid")
        result.append((path, status, old_mode, new_mode, old_blob, new_blob))
    if len(result) > _MAX_CHANGED_FILES:
        raise CandidatePatchError("candidate changes more than 64 files")
    return result


def _index_entries(
    source: Path,
    baseline: str,
    relative_paths: list[str],
    temporary: Path,
) -> dict[str, tuple[str, str]]:
    env = {"GIT_INDEX_FILE": str(temporary / "current.index")}
    _git(source, "read-tree", baseline, env=env)
    if relative_paths:
        pathspecs = [f":(literal){path}" for path in relative_paths]
        _git(source, "add", "-A", "--", *pathspecs, env=env)
        raw = _git(source, "ls-files", "--stage", "-z", "--", *pathspecs, env=env)
    else:
        raw = ""
    entries: dict[str, tuple[str, str]] = {}
    for item in raw.split("\x00"):
        if not item:
            continue
        try:
            metadata, relative_path = item.split("\t", 1)
            mode, blob, stage = metadata.split()
        except ValueError as exc:
            raise CandidatePatchError("Git returned an invalid current-tree entry") from exc
        if stage != "0":
            raise CandidatePatchError("candidate target has an unresolved Git index stage")
        entries[relative_path] = (mode, blob.lower())
    return entries


def _clean_fingerprint(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "exists": bool(value.get("exists")),
        "kind": value.get("kind"),
        "size": value.get("size"),
        "sha256": value.get("sha256"),
        "stable": bool(value.get("stable", True)),
    }


def _capture_fingerprint(path: Path, *, expected_mode: str) -> dict[str, Any]:
    try:
        before_resolve = path.resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise CandidatePatchError(f"file path could not be resolved: {path}") from exc
    if not _same_path(path, before_resolve):
        raise CandidatePatchError(f"file path changed through a symbolic link: {path}")
    value = _content_fingerprint(path, max_bytes=_MAX_FILE_BYTES)
    try:
        after_resolve = path.resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise CandidatePatchError(f"file path could not be resolved: {path}") from exc
    if not _same_path(path, after_resolve):
        raise CandidatePatchError(f"file path changed during inspection: {path}")
    expected_kind = "missing" if expected_mode == _MISSING_MODE else "file"
    if value.get("kind") != expected_kind or not value.get("stable", True):
        raise CandidatePatchError(
            f"candidate file is missing, unsafe, too large, or changing: {path}"
        )
    if expected_kind == "file" and os.name != "nt":
        executable = bool(path.stat().st_mode & stat.S_IXUSR)
        if executable != (expected_mode == "100755"):
            raise CandidatePatchError(f"candidate file mode differs from its Git baseline: {path}")
    return _clean_fingerprint(value)


def _validate_fingerprint(value: Any, *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CandidatePatchError(f"{label} fingerprint is missing")
    kind = value.get("kind")
    exists = value.get("exists")
    size = value.get("size")
    sha = value.get("sha256")
    if type(exists) is not bool or kind not in {"file", "missing"}:
        raise CandidatePatchError(f"{label} fingerprint is invalid")
    if type(size) is not int or size < 0 or size > _MAX_FILE_BYTES:
        raise CandidatePatchError(f"{label} fingerprint size is invalid")
    if kind == "file":
        sha = _valid_sha256(sha, label=f"{label} content hash")
        if not exists:
            raise CandidatePatchError(f"{label} fingerprint is inconsistent")
    elif exists or size != 0 or sha is not None:
        raise CandidatePatchError(f"{label} fingerprint is inconsistent")
    return {
        "exists": exists,
        "kind": kind,
        "size": size,
        "sha256": sha,
        "stable": True,
    }


def _analyze_export(
    session: Session,
    task: ExecutionTask,
    export: dict[str, Any],
    *,
    require_write: bool,
) -> CandidateAnalysis:
    task.resources.remaining_seconds()
    current_cancellation_token().throw_if_cancelled()
    source = _trusted_source(session, task, write=require_write)
    artifact_root = _artifact_root(session, task)
    storage = _candidate_storage(artifact_root)
    baseline, baseline_ref = _validate_baseline(source, export)
    patch_path, patch_ref = _validate_patch_reference(
        export.get("patch"), task=task, artifact_root=artifact_root
    )
    candidate_sha256 = _valid_sha256(patch_ref["sha256"], label="candidate patch hash")

    with tempfile.TemporaryDirectory(prefix="inspect-", dir=storage) as raw_temporary:
        temporary = Path(raw_temporary).resolve(strict=True)
        target_env = {"GIT_INDEX_FILE": str(temporary / "target.index")}
        _git(source, "read-tree", baseline, env=target_env)
        _git(
            source,
            "apply",
            "--cached",
            "--binary",
            "--whitespace=nowarn",
            str(patch_path),
            env=target_env,
        )
        target_tree = _git(source, "write-tree", env=target_env).strip()
        raw_changes = _git(
            source,
            "diff-tree",
            "-r",
            "--no-renames",
            "--raw",
            "-z",
            "--format=",
            baseline,
            target_tree,
        )
        parsed = _parse_tree_changes(raw_changes)
        changes: list[CandidateChange] = []
        casefolded: set[str] = set()
        for raw_path, status, old_mode, new_mode, old_blob, new_blob in parsed:
            relative_path = _validate_relative_path(raw_path)
            key = relative_path.casefold()
            if key in casefolded:
                raise CandidatePatchError("candidate contains case-colliding file paths")
            casefolded.add(key)
            target = _validate_target(
                session,
                task,
                source,
                storage,
                relative_path,
                require_write=require_write,
            )
            changes.append(
                CandidateChange(
                    relative_path,
                    target,
                    status,
                    old_mode,
                    new_mode,
                    old_blob.lower(),
                    new_blob.lower(),
                )
            )

        issued_files = export.get("files")
        if not isinstance(issued_files, list) or any(
            not isinstance(item, str) for item in issued_files
        ):
            raise CandidatePatchError("candidate receipt has an invalid file inventory")
        issued = {_validate_relative_path(item) for item in issued_files}
        actual = {change.relative_path for change in changes}
        if issued != actual:
            raise CandidatePatchError("candidate patch differs from its host file inventory")

        index_paths = [
            change.relative_path
            for change in changes
            if change.old_mode != _MISSING_MODE or change.path.exists()
        ]
        current_entries = _index_entries(source, baseline, index_paths, temporary)
        for change in changes:
            current = current_entries.get(change.relative_path)
            expected = (
                None if change.old_mode == _MISSING_MODE else (change.old_mode, change.old_blob)
            )
            if current != expected:
                raise CandidatePatchError(
                    f"project file changed since candidate snapshot: {change.relative_path}"
                )
            change.before = _capture_fingerprint(change.path, expected_mode=change.old_mode)

        _git(
            source,
            "apply",
            "--check",
            "--binary",
            "--whitespace=nowarn",
            str(patch_path),
        )

        simulation = temporary / "simulation"
        simulation.mkdir()
        for change in changes:
            if change.old_mode == _MISSING_MODE:
                continue
            simulated = simulation.joinpath(*PurePosixPath(change.relative_path).parts)
            simulated.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(change.path, simulated)
            if os.name != "nt":
                os.chmod(simulated, 0o755 if change.old_mode == "100755" else 0o644)
        if changes:
            _git(
                simulation,
                "apply",
                "--binary",
                "--whitespace=nowarn",
                str(patch_path),
            )
        for change in changes:
            simulated = simulation.joinpath(*PurePosixPath(change.relative_path).parts)
            change.expected_after = _capture_fingerprint(
                simulated,
                expected_mode=change.new_mode,
            )

    task.resources.remaining_seconds()
    current_cancellation_token().throw_if_cancelled()
    return CandidateAnalysis(
        candidate_sha256,
        source,
        baseline,
        baseline_ref,
        patch_path,
        patch_ref,
        export.get("contract_valid") is True,
        tuple(changes),
    )


def _inspection_receipt(analysis: CandidateAnalysis, inspection_id: str) -> dict[str, Any]:
    return {
        "phase": "patch_inspected",
        "inspection_id": inspection_id,
        "candidate_sha256": analysis.candidate_sha256,
        "source_workspace": str(analysis.source),
        "baseline_commit": analysis.baseline,
        "baseline_ref": analysis.baseline_ref,
        "patch": dict(analysis.patch_ref),
        "contract_valid": analysis.contract_valid,
        "files": [change.relative_path for change in analysis.changes],
        "changes": [change.to_receipt() for change in analysis.changes],
        "applied": False,
    }


def inspect_candidate_patch(
    candidate_sha256: str,
    *,
    session: Session | None = None,
) -> dict[str, Any]:
    """Verify a host-exported patch and issue an opaque inspection id."""

    try:
        host, task, recorder = _require_host(session)
        digest = _valid_sha256(candidate_sha256, label="candidate hash")
        export = _find_export(_records(recorder), digest)
        analysis = _analyze_export(host, task, export, require_write=False)
        inspection_id = "inspection-" + uuid4().hex
        receipt = _inspection_receipt(analysis, inspection_id)
        recorder.write(receipt)
        return {
            "ok": True,
            "status": "inspected",
            "inspection_id": inspection_id,
            "candidate_sha256": digest,
            "contract_valid": analysis.contract_valid,
            "requires_invalid_contract_ack": not analysis.contract_valid,
            "files": [change.relative_path for change in analysis.changes],
            "changes": [
                {
                    "path": change.relative_path,
                    "status": change.status,
                    "before_sha256": (change.before or {}).get("sha256"),
                    "after_sha256": (change.expected_after or {}).get("sha256"),
                }
                for change in analysis.changes
            ],
            "diff": _cap_diff(analysis.patch_path.read_text(encoding="utf-8", errors="replace")),
        }
    except Exception as exc:  # noqa: BLE001 — tool returns a bounded rejection
        return {"ok": False, "status": "rejected", "error": _safe_error(exc)}


def _inspection_candidate(inspection: dict[str, Any]) -> str:
    return _valid_sha256(inspection.get("candidate_sha256"), label="inspection candidate hash")


def _validate_inspection_link(inspection: dict[str, Any], analysis: CandidateAnalysis) -> None:
    if _inspection_candidate(inspection) != analysis.candidate_sha256:
        raise CandidatePatchError("inspection no longer identifies this candidate")
    if inspection.get("source_workspace") != str(analysis.source):
        raise CandidatePatchError("inspection belongs to a different source workspace")
    if inspection.get("baseline_commit") != analysis.baseline:
        raise CandidatePatchError("inspection baseline differs from the candidate")
    if inspection.get("contract_valid") is not analysis.contract_valid:
        raise CandidatePatchError("inspection contract result differs from the candidate")


def _create_backups(
    storage: Path,
    operation_id: str,
    changes: tuple[CandidateChange, ...],
) -> Path:
    operation_root = (storage / f"apply-{operation_id}").resolve(strict=False)
    if not operation_root.is_relative_to(storage):
        raise CandidatePatchError("candidate backup directory escaped transaction storage")
    operation_root.mkdir(parents=False, exist_ok=False)
    total = 0
    for index, change in enumerate(changes):
        assert change.before is not None
        if change.before["kind"] == "missing":
            change.backup = None
            continue
        current = _capture_fingerprint(change.path, expected_mode=change.old_mode)
        if not _same_content_fingerprint(change.before, current):
            raise CandidatePatchError(f"project file changed before backup: {change.relative_path}")
        data = change.path.read_bytes()
        total += len(data)
        if len(data) > _MAX_FILE_BYTES or total > _MAX_BACKUP_BYTES:
            raise CandidatePatchError("candidate backups exceed the 64 MiB transaction limit")
        after_read = _capture_fingerprint(change.path, expected_mode=change.old_mode)
        if not _same_content_fingerprint(change.before, after_read):
            raise CandidatePatchError(
                f"project file changed while backing up: {change.relative_path}"
            )
        backup_path = operation_root / f"{index:04d}.bin"
        atomic_write_bytes(backup_path, data, keep_backup=False, mode=0o600)
        backup_value = _capture_fingerprint(backup_path, expected_mode="100644")
        if backup_value["sha256"] != change.before["sha256"]:
            raise CandidatePatchError("candidate backup does not match its source bytes")
        change.backup = {
            "path": str(backup_path),
            "sha256": backup_value["sha256"],
            "size": backup_value["size"],
        }
    return operation_root


def _state(change: CandidateChange) -> str:
    assert change.before is not None and change.expected_after is not None
    try:
        current = _capture_fingerprint(
            change.path,
            expected_mode=(
                change.old_mode
                if change.before["kind"] == "file"
                else change.new_mode
                if change.expected_after["kind"] == "file"
                else _MISSING_MODE
            ),
        )
    except (CandidatePatchError, OSError, RuntimeError):
        current = _content_fingerprint(change.path, max_bytes=_MAX_FILE_BYTES)
    if _same_content_fingerprint(change.before, current) and _mode_matches(
        change.path, change.old_mode
    ):
        return "old"
    if _same_content_fingerprint(change.expected_after, current) and _mode_matches(
        change.path, change.new_mode
    ):
        return "new"
    return "unknown"


def _mode_matches(path: Path, mode: str) -> bool:
    if mode == _MISSING_MODE:
        return not path.exists() and not path.is_symlink()
    if not path.is_file() or path.is_symlink():
        return False
    if os.name == "nt":
        return True
    return bool(path.stat().st_mode & stat.S_IXUSR) == (mode == "100755")


def _restore_old(change: CandidateChange) -> None:
    assert change.before is not None and change.expected_after is not None
    if _state(change) != "new":
        raise CandidatePatchError(f"refusing to overwrite a drifting file: {change.relative_path}")
    if change.old_mode == _MISSING_MODE:
        change.path.unlink()
        return
    if not isinstance(change.backup, dict):
        raise CandidatePatchError(f"candidate backup is missing: {change.relative_path}")
    backup_path = Path(str(change.backup.get("path") or ""))
    backup_value = _capture_fingerprint(backup_path, expected_mode="100644")
    if (
        backup_value["sha256"] != change.backup.get("sha256")
        or backup_value["size"] != change.backup.get("size")
        or backup_value["sha256"] != change.before["sha256"]
    ):
        raise CandidatePatchError(f"candidate backup changed: {change.relative_path}")
    data = backup_path.read_bytes()
    change.path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(change.path, data, keep_backup=False)
    if os.name != "nt":
        os.chmod(change.path, 0o755 if change.old_mode == "100755" else 0o644)


def _lock_target(source: Path) -> Path:
    digest = hashlib.sha256(os.path.normcase(str(source)).encode("utf-8")).hexdigest()
    return Path(tempfile.gettempdir()) / "octopus-candidate-locks" / digest


def _write_reconciliation_required(
    recorder: HandoffRecorder,
    *,
    operation_id: str,
    inspection_id: str,
    states: dict[str, str],
    reason: str,
) -> bool:
    try:
        recorder.write(
            {
                "phase": "patch_apply_reconciliation_required",
                "operation_id": operation_id,
                "inspection_id": inspection_id,
                "states": states,
                "reason": reason[-600:],
            }
        )
    except Exception:  # noqa: BLE001 — retain ownership; caller reports journal failure
        return False
    return True


def _settle(
    session: Session,
    task: ExecutionTask,
    recorder: HandoffRecorder,
    *,
    operation_id: str,
    inspection_id: str,
    candidate_sha256: str,
    changes: tuple[CandidateChange, ...],
    phase: str,
    allow_unowned: bool,
    reason: str = "",
) -> dict[str, Any]:
    expected = {
        change.path: _capture_fingerprint(
            change.path,
            expected_mode=change.new_mode if phase == "patch_applied" else change.old_mode,
        )
        for change in changes
    }
    receipt = {
        "phase": phase,
        "operation_id": operation_id,
        "inspection_id": inspection_id,
        "candidate_sha256": candidate_sha256,
        "parent_task_id": task.task_id,
        "files": [change.relative_path for change in changes],
        "content": {change.relative_path: dict(expected[change.path]) for change in changes},
        **({"reason": reason[-600:]} if reason else {}),
    }
    transfer_file_write_leases(
        session,
        expected,
        from_owner=operation_id,
        to_owner=task.task_id,
        allow_unowned=allow_unowned,
        before_transfer=lambda: recorder.write(receipt),
    )
    return receipt


def _rollback(
    session: Session,
    task: ExecutionTask,
    recorder: HandoffRecorder,
    *,
    operation_id: str,
    inspection_id: str,
    candidate_sha256: str,
    changes: tuple[CandidateChange, ...],
    reason: str,
    allow_unowned: bool,
) -> dict[str, Any]:
    states = {change.relative_path: _state(change) for change in changes}
    restore_errors: list[str] = []
    for change in changes:
        if states[change.relative_path] != "new":
            continue
        try:
            _restore_old(change)
        except Exception as exc:  # noqa: BLE001 — collect all uncertain files
            restore_errors.append(f"{change.relative_path}: {_safe_error(exc)}")
    final_states = {change.relative_path: _state(change) for change in changes}
    if all(state == "old" for state in final_states.values()):
        try:
            _settle(
                session,
                task,
                recorder,
                operation_id=operation_id,
                inspection_id=inspection_id,
                candidate_sha256=candidate_sha256,
                changes=changes,
                phase="patch_apply_rolled_back",
                allow_unowned=allow_unowned,
                reason=reason,
            )
        except Exception as exc:  # noqa: BLE001 — bytes are old; durable settlement is pending
            journaled = _write_reconciliation_required(
                recorder,
                operation_id=operation_id,
                inspection_id=inspection_id,
                states=final_states,
                reason=f"rollback restored bytes but settlement failed: {_safe_error(exc)}",
            )
            return {
                "ok": False,
                "status": "reconciliation_required",
                "operation_id": operation_id,
                "states": final_states,
                "journaled": journaled,
                "error": _safe_error(exc),
            }
        return {
            "ok": False,
            "status": "rolled_back",
            "operation_id": operation_id,
            "states": final_states,
            "error": reason[-600:],
        }
    detail = "; ".join(restore_errors) or reason
    journaled = _write_reconciliation_required(
        recorder,
        operation_id=operation_id,
        inspection_id=inspection_id,
        states=final_states,
        reason=detail,
    )
    return {
        "ok": False,
        "status": "reconciliation_required",
        "operation_id": operation_id,
        "states": final_states,
        "journaled": journaled,
        "error": detail[-600:],
    }


def _validate_operation_changes(
    session: Session,
    task: ExecutionTask,
    start: dict[str, Any],
    source: Path,
    artifact_root: Path,
    storage: Path,
) -> tuple[CandidateChange, ...]:
    raw_changes = start.get("changes")
    if not isinstance(raw_changes, list) or len(raw_changes) > _MAX_CHANGED_FILES:
        raise CandidatePatchError("candidate operation has an invalid file inventory")
    operation_id = str(start.get("operation_id") or "")
    operation_root_raw = start.get("backup_root")
    if not isinstance(operation_root_raw, str) or not Path(operation_root_raw).is_absolute():
        raise CandidatePatchError("candidate operation has no backup directory")
    lexical_operation_root = Path(operation_root_raw)
    operation_root = lexical_operation_root.resolve(strict=True)
    expected_root = (storage / f"apply-{operation_id}").resolve(strict=False)
    if (
        not _same_path(lexical_operation_root, operation_root)
        or not _same_path(operation_root, expected_root)
        or not operation_root.is_relative_to(storage)
    ):
        raise CandidatePatchError("candidate operation backup directory is invalid")
    changes: list[CandidateChange] = []
    seen: set[str] = set()
    for raw in raw_changes:
        if not isinstance(raw, dict):
            raise CandidatePatchError("candidate operation file entry is invalid")
        relative_path = _validate_relative_path(raw.get("path"))
        key = relative_path.casefold()
        if key in seen:
            raise CandidatePatchError("candidate operation repeats a file path")
        seen.add(key)
        old_mode = str(raw.get("old_mode") or "")
        new_mode = str(raw.get("new_mode") or "")
        if old_mode not in _REGULAR_MODES | {_MISSING_MODE}:
            raise CandidatePatchError("candidate operation old mode is invalid")
        if new_mode not in _REGULAR_MODES | {_MISSING_MODE}:
            raise CandidatePatchError("candidate operation new mode is invalid")
        target = _validate_target(
            session,
            task,
            source,
            storage,
            relative_path,
            require_write=True,
        )
        if raw.get("target") != str(target):
            raise CandidatePatchError("candidate operation target coordinate changed")
        before = _validate_fingerprint(raw.get("before"), label="candidate before")
        expected_after = _validate_fingerprint(raw.get("expected_after"), label="candidate after")
        status = str(raw.get("status") or "")
        expected_status = (
            "A" if old_mode == _MISSING_MODE else "D" if new_mode == _MISSING_MODE else "M"
        )
        if status != expected_status:
            raise CandidatePatchError("candidate operation transition is invalid")
        change = CandidateChange(
            relative_path,
            target,
            status,
            old_mode,
            new_mode,
            _valid_git_oid(raw.get("old_blob"), label="candidate old blob"),
            _valid_git_oid(raw.get("new_blob"), label="candidate new blob"),
            before,
            expected_after,
        )
        raw_backup = raw.get("backup")
        if before["kind"] == "file":
            backup_path, backup_ref = _validate_patch_reference(
                raw_backup,
                task=task,
                artifact_root=artifact_root,
            )
            if not backup_path.is_relative_to(operation_root):
                raise CandidatePatchError("candidate backup escaped its operation directory")
            if backup_ref["sha256"] != before["sha256"]:
                raise CandidatePatchError("candidate backup does not match the original file")
            change.backup = backup_ref
        elif raw_backup is not None:
            raise CandidatePatchError("new candidate file has an unexpected backup")
        changes.append(change)
    return tuple(changes)


def apply_candidate_patch(
    inspection_id: str,
    *,
    allow_invalid_contract: bool = False,
    session: Session | None = None,
) -> dict[str, Any]:
    """Apply one inspected patch transactionally; never accepts a model path."""

    try:
        host, task, recorder = _require_host(session)
        if not isinstance(inspection_id, str) or not inspection_id.startswith("inspection-"):
            raise CandidatePatchError("inspection id is invalid")
        source = _trusted_source(host, task, write=True)
        remaining = task.resources.remaining_seconds()
        lock_timeout = min(10.0, remaining) if remaining is not None else 10.0
        with (
            _PROJECT_APPLY_LOCK,
            _cross_process_lock(_lock_target(source), required=True, timeout_s=lock_timeout),
        ):
            records = _records(recorder)
            inspection = _find_inspection(records, inspection_id)
            existing = _latest_inspection_operation(records, inspection_id)
            if existing is not None:
                start, outcome = existing
                if outcome is not None and outcome.get("phase") == "patch_applied":
                    return {
                        "ok": True,
                        "status": "already_applied",
                        "operation_id": start.get("operation_id"),
                        "inspection_id": inspection_id,
                    }
                if outcome is None:
                    return {
                        "ok": False,
                        "status": "reconciliation_required",
                        "operation_id": start.get("operation_id"),
                        "inspection_id": inspection_id,
                        "error": "a prior apply attempt must be reconciled first",
                    }

            digest = _inspection_candidate(inspection)
            export = _find_export(records, digest)
            analysis = _analyze_export(host, task, export, require_write=True)
            _validate_inspection_link(inspection, analysis)
            if not analysis.contract_valid and allow_invalid_contract is not True:
                raise CandidatePatchError(
                    "candidate failed its declared output contract; set "
                    "allow_invalid_contract=true only after reviewing the diff"
                )
            task.resources.remaining_seconds()
            current_cancellation_token().throw_if_cancelled()

            artifact_root = _artifact_root(host, task)
            storage = _candidate_storage(artifact_root)
            operation_id = "patch-" + uuid4().hex
            operation_root = _create_backups(storage, operation_id, analysis.changes)
            before = {change.path: dict(change.before or {}) for change in analysis.changes}
            start = {
                "phase": "patch_apply_started",
                "operation_id": operation_id,
                "inspection_id": inspection_id,
                "candidate_sha256": analysis.candidate_sha256,
                "parent_task_id": task.task_id,
                "source_workspace": str(analysis.source),
                "baseline_commit": analysis.baseline,
                "baseline_ref": analysis.baseline_ref,
                "patch": dict(analysis.patch_ref),
                "contract_valid": analysis.contract_valid,
                "allow_invalid_contract": allow_invalid_contract is True,
                "backup_root": str(operation_root),
                "changes": [change.to_receipt() for change in analysis.changes],
            }
            transfer_file_write_leases(
                host,
                before,
                from_owner=task.task_id,
                to_owner=operation_id,
                allow_unowned=True,
                before_transfer=lambda: recorder.write(start),
            )
            try:
                if analysis.changes:
                    _git(
                        analysis.source,
                        "apply",
                        "--binary",
                        "--whitespace=nowarn",
                        str(analysis.patch_path),
                        cleanup=True,
                    )
                states = {change.relative_path: _state(change) for change in analysis.changes}
                if any(state != "new" for state in states.values()):
                    raise CandidatePatchError(
                        f"candidate application verification failed: {states}"
                    )
                _settle(
                    host,
                    task,
                    recorder,
                    operation_id=operation_id,
                    inspection_id=inspection_id,
                    candidate_sha256=analysis.candidate_sha256,
                    changes=analysis.changes,
                    phase="patch_applied",
                    allow_unowned=False,
                )
                return {
                    "ok": True,
                    "status": "applied",
                    "operation_id": operation_id,
                    "inspection_id": inspection_id,
                    "candidate_sha256": analysis.candidate_sha256,
                    "files": [change.relative_path for change in analysis.changes],
                }
            except Exception as exc:  # noqa: BLE001 — effects require rollback/reconciliation
                return _rollback(
                    host,
                    task,
                    recorder,
                    operation_id=operation_id,
                    inspection_id=inspection_id,
                    candidate_sha256=analysis.candidate_sha256,
                    changes=analysis.changes,
                    reason=_safe_error(exc),
                    allow_unowned=False,
                )
    except Exception as exc:  # noqa: BLE001 — tool returns a bounded rejection
        return {"ok": False, "status": "rejected", "error": _safe_error(exc)}


def reconcile_candidate_patch(
    operation_id: str,
    *,
    session: Session | None = None,
) -> dict[str, Any]:
    """Settle a started apply from durable coordinates after interruption."""

    try:
        host, task, recorder = _require_host(session)
        if not isinstance(operation_id, str) or not operation_id.startswith("patch-"):
            raise CandidatePatchError("operation id is invalid")
        source = _trusted_source(host, task, write=True)
        remaining = task.resources.remaining_seconds()
        lock_timeout = min(10.0, remaining) if remaining is not None else 10.0
        with (
            _PROJECT_APPLY_LOCK,
            _cross_process_lock(_lock_target(source), required=True, timeout_s=lock_timeout),
        ):
            records = _records(recorder)
            start = _find_start(records, operation_id)
            for row in reversed(records):
                if row.get("operation_id") != operation_id:
                    continue
                if row.get("phase") == "patch_applied":
                    return {
                        "ok": True,
                        "status": "already_applied",
                        "operation_id": operation_id,
                    }
                if row.get("phase") == "patch_apply_rolled_back":
                    return {
                        "ok": True,
                        "status": "already_rolled_back",
                        "operation_id": operation_id,
                    }

            if start.get("source_workspace") != str(source):
                raise CandidatePatchError("candidate operation belongs to a different project")
            digest = _valid_sha256(start.get("candidate_sha256"), label="operation candidate hash")
            _validate_baseline(source, start)
            artifact_root = _artifact_root(host, task)
            storage = _candidate_storage(artifact_root)
            _validate_patch_reference(start.get("patch"), task=task, artifact_root=artifact_root)
            changes = _validate_operation_changes(
                host,
                task,
                start,
                source,
                artifact_root,
                storage,
            )
            inspection_id = str(start.get("inspection_id") or "")
            states = {change.relative_path: _state(change) for change in changes}
            if all(state == "new" for state in states.values()):
                _settle(
                    host,
                    task,
                    recorder,
                    operation_id=operation_id,
                    inspection_id=inspection_id,
                    candidate_sha256=digest,
                    changes=changes,
                    phase="patch_applied",
                    allow_unowned=True,
                    reason="reconciled from durable transaction coordinates",
                )
                return {"ok": True, "status": "applied", "operation_id": operation_id}
            return _rollback(
                host,
                task,
                recorder,
                operation_id=operation_id,
                inspection_id=inspection_id,
                candidate_sha256=digest,
                changes=changes,
                reason="reconciled an interrupted candidate application",
                allow_unowned=True,
            )
    except Exception as exc:  # noqa: BLE001 — tool returns a bounded rejection
        return {"ok": False, "status": "rejected", "error": _safe_error(exc)}


__all__ = [
    "CandidatePatchError",
    "apply_candidate_patch",
    "inspect_candidate_patch",
    "reconcile_candidate_patch",
]
