"""Explicit file handoff around the existing subagent bridge.

Only the host fingerprints inputs, claims outputs and accepts a completed
child's files. Model prose and model-supplied hashes never establish success.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from runtime.execution.artifact_contracts import (
    ArtifactContract,
    ArtifactReference,
    HandoffRecorder,
)
from runtime.execution.misc.file_write_leases import (
    _content_fingerprint,
    transfer_file_write_leases,
)
from runtime.execution.request import ExecutionTask
from runtime.execution.subagents.execution_context import parent_execution_task
from runtime.platform.process.session import Session

_MAX_FILES = 64
_MAX_FILE_BYTES = 32 * 1024 * 1024


class ArtifactHandoffError(RuntimeError):
    pass


def _fingerprint(path: Path, *, required: bool) -> dict[str, Any]:
    try:
        if path.resolve(strict=False) != path:
            raise ArtifactHandoffError("artifact path changed through a symbolic link")
        if path.exists() and path.stat().st_size > _MAX_FILE_BYTES:
            raise ArtifactHandoffError("artifact exceeds the 32 MiB handoff limit")
        fingerprint = _content_fingerprint(path, max_bytes=_MAX_FILE_BYTES)
        if path.resolve(strict=False) != path:
            raise ArtifactHandoffError("artifact path changed during inspection")
    except OSError as exc:
        raise ArtifactHandoffError("artifact could not be inspected") from exc
    allowed = {"file"} if required else {"file", "missing"}
    if fingerprint.get("kind") not in allowed or not fingerprint.get("stable", True):
        raise ArtifactHandoffError(f"artifact is missing, unreadable or changing: {path}")
    return fingerprint


def _paths(values: Any, task: ExecutionTask, *, write: bool) -> tuple[Path, ...]:
    if values is None:
        return ()
    if not isinstance(values, (list, tuple)) or len(values) > _MAX_FILES:
        raise ArtifactHandoffError("artifact paths must be a list of at most 64 files")
    root = task.permissions.primary_write if write else task.permissions.primary_read
    result: list[Path] = []
    for raw in values:
        if not isinstance(raw, str) or not raw.strip() or "\x00" in raw:
            raise ArtifactHandoffError("artifact paths must be nonempty strings")
        path = Path(raw).expanduser()
        if not path.is_absolute():
            if root is None:
                raise ArtifactHandoffError("artifact path requires an approved workspace")
            path = root / path
        path = path.resolve(strict=False)
        allowed = task.permissions.allows_read(path) and (
            not write or task.permissions.allows_write(path)
        )
        if not allowed:
            raise ArtifactHandoffError("artifact path is outside the parent task scope")
        if path not in result:
            result.append(path)
    return tuple(result)


@dataclass(slots=True)
class ArtifactHandoff:
    parent: Session
    parent_task: ExecutionTask
    contract: ArtifactContract
    output_baselines: dict[Path, dict[str, Any]]
    recorder: HandoffRecorder
    child_id: str | None = None
    finished: bool = False
    accepted: bool = False
    aborted: bool = False
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False, compare=False)

    @classmethod
    def prepare(cls, parent: Any, input_files: Any, output_files: Any) -> ArtifactHandoff:
        task = parent_execution_task(parent)
        if task is None or not isinstance(parent, Session):
            raise ArtifactHandoffError("artifact handoff requires a host-scoped task")
        recorder = parent.metadata.get("_execution_handoff_recorder")
        if not isinstance(recorder, HandoffRecorder):
            raise ArtifactHandoffError("artifact handoff requires a durable host journal")
        inputs = []
        for path in _paths(input_files, task, write=False):
            snapshot = _fingerprint(path, required=True)
            inputs.append(ArtifactReference(path, snapshot["sha256"], snapshot["size"]))
        outputs = _paths(output_files, task, write=True)
        baselines = {path: _fingerprint(path, required=False) for path in outputs}
        return cls(parent, task, ArtifactContract(tuple(inputs), outputs), baselines, recorder)

    def instruction(self) -> str:
        lines = ["\n\nArtifact handoff contract:", "Input files (read these exact versions):"]
        lines.extend(f"- {ref.path} (sha256={ref.sha256})" for ref in self.contract.inputs)
        lines.append("Required output files:")
        lines.extend(f"- {path}" for path in self.contract.output_paths)
        lines.append(
            "Complete these files before reporting success. The host verifies their bytes."
        )
        return "\n".join(lines)

    def _verify_inputs(self, *, allow_outputs: bool) -> None:
        for ref in self.contract.inputs:
            if allow_outputs and ref.path in self.contract.output_paths:
                continue
            current = _fingerprint(ref.path, required=True)
            if current["sha256"] != ref.sha256 or current["size"] != ref.size:
                raise ArtifactHandoffError(f"handoff input changed: {ref.path}")

    def begin(self, child_id: str) -> None:
        if self.child_id is not None:
            raise ArtifactHandoffError("artifact handoff cannot be retried implicitly")
        self.parent_task.resources.remaining_seconds()
        self._verify_inputs(allow_outputs=False)
        transfer_file_write_leases(
            self.parent,
            self.output_baselines,
            from_owner=self.parent_task.task_id,
            to_owner=child_id,
            allow_unowned=True,
            before_transfer=lambda: self.recorder.write(
                {
                    "phase": "assigned",
                    "parent_task_id": self.parent_task.task_id,
                    "child_task_id": child_id,
                    "inputs": [ref.to_dict() for ref in self.contract.inputs],
                    "outputs": [str(path) for path in self.contract.output_paths],
                }
            ),
        )
        self.child_id = child_id

    def accept(self) -> dict[str, Any]:
        with self._lock:
            return self._accept()

    def _accept(self) -> dict[str, Any]:
        if not self.finished or self.child_id is None or self.accepted or self.aborted:
            raise ArtifactHandoffError("only one completed child can hand back its artifacts")
        self.parent_task.resources.remaining_seconds()
        self._verify_inputs(allow_outputs=True)
        snapshots = {path: _fingerprint(path, required=True) for path in self.contract.output_paths}
        artifacts = [
            ArtifactReference(path, value["sha256"], value["size"], self.child_id).to_dict()
            for path, value in snapshots.items()
        ]
        receipt = {
            "phase": "accepted",
            "parent_task_id": self.parent_task.task_id,
            "child_task_id": self.child_id,
            "artifacts": artifacts,
        }
        transfer_file_write_leases(
            self.parent,
            snapshots,
            from_owner=self.child_id,
            to_owner=self.parent_task.task_id,
            before_transfer=lambda: self.recorder.write(receipt),
            require_all_owned=True,
        )
        self.accepted = True
        return receipt

    def abort_unchanged(self) -> dict[str, Any] | None:
        """Return unchanged files after the child runner has unwound.

        This is cleanup, never acceptance or a retry. It may run after the
        parent's deadline. Changed files, undeclared leases and failed durable
        writes leave ownership with the child for explicit reconciliation.
        """
        with self._lock:
            if self.accepted or self.aborted or self.child_id is None or not self.finished:
                return None
            receipt = {
                "phase": "aborted",
                "reason": "outputs_unchanged",
                "parent_task_id": self.parent_task.task_id,
                "child_task_id": self.child_id,
                "outputs": [str(path) for path in self.contract.output_paths],
            }
            transfer_file_write_leases(
                self.parent,
                self.output_baselines,
                from_owner=self.child_id,
                to_owner=self.parent_task.task_id,
                before_transfer=lambda: self.recorder.write(receipt),
                require_all_owned=True,
            )
            self.aborted = True
            return receipt
