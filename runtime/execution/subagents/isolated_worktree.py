"""Host-created workspaces and durable candidate patches for delegated tasks.

The caller runs this scope on the actual child worker thread. A timeout in
the caller therefore cannot delete the checkout underneath a running child.
Only the host selects directories; no project permissions are expanded.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
from uuid import uuid4

from runtime.execution.artifact_contracts import (
    ArtifactContract,
    ArtifactReference,
    HandoffRecorder,
)
from runtime.execution.request import ExecutionTask
from runtime.execution.subagents.artifact_handoff import ArtifactHandoffError, _fingerprint, _paths
from runtime.execution.subagents.execution_context import parent_execution_task
from runtime.execution.subagents.worktree_loop import (
    _GIT_HARDENING,
    _cap_diff,
    _resolve_worktree_gitdir,
    worktree_scope,
)
from runtime.platform.process.session import Session
from runtime.platform.process.tree import process_group_kwargs, terminate_process_tree
from runtime.safety.approval.cancellation import current_cancellation_token


def _git(
    root: Path,
    *args: str,
    env: dict[str, str] | None = None,
    output: Path | None = None,
    cleanup: bool = False,
) -> str:
    token = current_cancellation_token()
    if not cleanup:
        token.throw_if_cancelled()
    # Parent shell variables must not redirect the source repository or index.
    git_env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    git_env.update(env or {})
    handle = output.open("wb") if output is not None else None
    try:
        proc = subprocess.Popen(
            ["git", "-C", str(root), *_GIT_HARDENING, *args],
            env=git_env,
            stdin=subprocess.DEVNULL,
            stdout=handle if handle is not None else subprocess.PIPE,
            stderr=subprocess.PIPE,
            **process_group_kwargs(),
        )

        def stop(_reason: str) -> None:
            terminate_process_tree(proc, grace_s=0.2, kill_wait_s=0.5)

        unlink = (lambda: None) if cleanup else token.on_cancelled(stop)
        try:
            try:
                stdout, stderr = proc.communicate(timeout=60)
            except subprocess.TimeoutExpired:
                terminate_process_tree(proc, grace_s=0.2, kill_wait_s=0.5)
                proc.communicate()
                raise
        finally:
            unlink()
        if not cleanup:
            token.throw_if_cancelled()
        if proc.returncode:
            raise subprocess.CalledProcessError(proc.returncode, proc.args, stderr=stderr)
        return (stdout or b"").decode("utf-8", errors="strict")
    finally:
        if handle is not None:
            handle.close()


def _snapshot(source: Path, storage: Path, task: ExecutionTask) -> str:
    """Snapshot working files with a private index, leaving HEAD/index intact."""
    task.resources.remaining_seconds()
    head = _git(source, "rev-parse", "--verify", "HEAD").strip()
    excluded: list[str] = []
    if storage.is_relative_to(source):
        excluded.append(f":(exclude,literal){storage.relative_to(source).as_posix()}")
    with tempfile.TemporaryDirectory(prefix="snapshot-", dir=storage) as temporary:
        env = {
            "GIT_INDEX_FILE": str(Path(temporary) / "index"),
            "GIT_AUTHOR_NAME": "Octopus Workspace",
            "GIT_AUTHOR_EMAIL": "workspace@localhost",
            "GIT_COMMITTER_NAME": "Octopus Workspace",
            "GIT_COMMITTER_EMAIL": "workspace@localhost",
        }
        _git(source, "read-tree", head, env=env)
        _git(source, "add", "-A", "--", ".", *excluded, env=env)
        tree = _git(source, "write-tree", env=env).strip()
        # Reject a moving starting state before allowing any engine effects.
        _git(source, "add", "-A", "--", ".", *excluded, env=env)
        if (
            tree != _git(source, "write-tree", env=env).strip()
            or head != _git(source, "rev-parse", "HEAD").strip()
        ):
            raise ArtifactHandoffError("project changed while preparing its execution snapshot")
        task.resources.remaining_seconds()
        return _git(
            source, "commit-tree", tree, "-p", head, "-m", "Octopus execution snapshot", env=env
        ).strip()


@dataclass(slots=True)
class IsolatedWorktree:
    source: Path
    path: Path
    export_root: Path
    baseline: str
    session: Session
    recorder: HandoffRecorder
    contract: ArtifactContract
    gitdir: Path
    enforce_outputs: bool
    producer_task_id: str | None = None

    def _worktree_git(self, *args: str, output: Path | None = None) -> str:
        gitdir = _resolve_worktree_gitdir(str(self.path), str(self.source))
        if Path(gitdir).resolve(strict=True) != self.gitdir:
            raise ArtifactHandoffError("isolated gitdir changed during execution")
        return _git(
            self.path,
            f"--git-dir={gitdir}",
            f"--work-tree={self.path}",
            *args,
            output=output,
            cleanup=True,
        )

    def export(self, result: dict[str, Any], *, cancelled: bool) -> dict[str, Any]:
        """Keep candidate changes even on failure; never apply them to source."""
        if self.path.resolve(strict=True) != self.path:
            raise ArtifactHandoffError("isolated worktree path changed during execution")
        result = dict(result)
        result.pop("artifacts", None)
        result.pop("artifact_handoff", None)
        result.pop("worktree", None)
        valid = bool(result.get("success")) and not result.get("error")
        valid = valid and result.get("schema_ok") is not False and not cancelled
        if valid:
            try:
                for ref in self.contract.inputs:
                    if ref.path in self.contract.output_paths:
                        continue
                    current = _fingerprint(ref.path, required=True)
                    if (current["sha256"], current["size"]) != (ref.sha256, ref.size):
                        raise ArtifactHandoffError(f"isolated input changed: {ref.path}")
                for path in self.contract.output_paths:
                    _fingerprint(path, required=True)
            except (ArtifactHandoffError, OSError) as exc:
                result.update(success=False, error=str(exc), status="artifact_handoff_failed")
                valid = False
        if cancelled:
            result.update(success=False, status="cancelled", error="isolated child was cancelled")
        # Diff against the actual initial working files, including uncommitted
        # edits. A worker commit cannot redefine that baseline.
        self._worktree_git("add", "-A", "--", ".")
        if self.contract.output_paths:
            present = [
                str(path.relative_to(self.path))
                for path in self.contract.output_paths
                if path.exists()
            ]
            if present:
                self._worktree_git("add", "-f", "--", *present)
        patch_path = self.export_root / "changes.patch"
        self._worktree_git(
            "diff",
            "--cached",
            "--binary",
            "--no-ext-diff",
            "--no-textconv",
            self.baseline,
            "--",
            ".",
            output=patch_path,
        )
        patch = _fingerprint(patch_path, required=True)
        files = self._worktree_git(
            "diff",
            "--cached",
            "--name-only",
            "-z",
            "--no-ext-diff",
            "--no-textconv",
            self.baseline,
            "--",
            ".",
        ).split("\x00")
        files = [name for name in files if name]
        declared = {path.relative_to(self.path).as_posix() for path in self.contract.output_paths}
        if self.enforce_outputs and set(files) - declared:
            valid = False
            result.update(
                success=False,
                status="artifact_handoff_failed",
                error="isolated child changed undeclared output files",
            )
        patch_ref = ArtifactReference(
            patch_path, patch["sha256"], patch["size"], self.producer_task_id
        ).to_dict()
        parent_task = parent_execution_task(self.session)
        if parent_task is None:
            raise ArtifactHandoffError("isolated workspace lost its host task")
        baseline_ref = f"refs/octopus/execution-snapshots/{self.export_root.name}"
        # The temporary worktree branch is removed during cleanup. Keep its
        # initial version reachable so later verification survives Git GC.
        _git(self.source, "update-ref", baseline_ref, self.baseline, cleanup=True)
        receipt = {
            "phase": "worktree_exported",
            "parent_task_id": parent_task.task_id,
            "child_task_id": self.producer_task_id,
            "source_workspace": str(self.source),
            "baseline_commit": self.baseline,
            "baseline_ref": baseline_ref,
            "patch": patch_ref,
            "files": files,
            "contract_valid": valid,
            "applied": False,
        }
        self.recorder.write(receipt)
        result.update(
            isolated=True,
            retry_allowed=False,
            worktree=receipt,
            diff=_cap_diff(patch_path.read_text(encoding="utf-8", errors="replace")),
            files_touched=receipt["files"],
        )
        return result


@contextmanager
def isolated_worktree_scope(
    parent: Session,
    *,
    input_files: Any = None,
    output_files: Any = None,
) -> Iterator[IsolatedWorktree]:
    task = parent_execution_task(parent)
    if task is None:
        raise ArtifactHandoffError("isolation requires a host-scoped task")
    recorder = parent.metadata.get("_execution_handoff_recorder")
    if not isinstance(recorder, HandoffRecorder):
        raise ArtifactHandoffError("isolation requires a durable host journal")
    raw_source = parent.metadata.get("workspace_path")
    if not isinstance(raw_source, str) or not Path(raw_source).is_absolute():
        raise ArtifactHandoffError("isolation requires the task's approved project directory")
    source = Path(raw_source).resolve(strict=True)
    if not task.permissions.allows_read(source):
        raise PermissionError("isolated source is outside the parent read scope")
    source = Path(_git(source, "rev-parse", "--show-toplevel").strip()).resolve(strict=True)
    if not task.permissions.allows_read(source):
        raise PermissionError("repository root is outside the parent read scope")
    root = parent.metadata.get("_artifact_output_root") or task.permissions.primary_write
    if root is None:
        raise PermissionError("isolation requires an approved output directory")
    storage = (Path(root) / ".execution" / "isolated").resolve(strict=False)
    if not task.permissions.allows_write(storage) or not task.permissions.allows_read(storage):
        raise PermissionError("isolated workspace storage is outside the parent scope")
    storage.mkdir(parents=True, exist_ok=True)
    baseline = _snapshot(source, storage, task)
    run_id = uuid4().hex[:16]
    export_root = storage / f"result-{run_id}"
    export_root.mkdir()
    child_admitted = False
    # Persistence failures retain the checkout rather than deleting the only
    # copy of a child's output. The assigned record identifies retained trees.
    with worktree_scope(
        str(source),
        run_id,
        base_dir=str(storage),
        revision=baseline,
        preserve_on_error=lambda: child_admitted,
    ) as (raw_path, branch):
        path = Path(raw_path).resolve(strict=True)
        gitdir = Path(_resolve_worktree_gitdir(str(path), str(source))).resolve(strict=True)
        permissions = replace(
            task.permissions,
            readable_roots=(path, *task.permissions.readable_roots),
            writable_roots=(path,),
        )
        scoped_task = replace(task, permissions=permissions)
        metadata = {
            **parent.metadata,
            "workspace_path": str(path),
            "_locked_write_root": str(path),
            "_artifact_output_root": str(path),
            # This checkout is itself the approved sandbox; avoid creating a
            # second nested project sandbox. The immutable policy stays intact.
            "sandbox_mode": "full",
            "_execution_task": scoped_task,
        }
        session = replace(parent, metadata=metadata)

        def mapped(values: Any) -> Any:
            if not isinstance(values, (list, tuple)):
                return values
            return [
                str(path / Path(raw).relative_to(source))
                if isinstance(raw, str)
                and Path(raw).is_absolute()
                and Path(raw).is_relative_to(source)
                else raw
                for raw in values
            ]

        inputs = []
        for input_path in _paths(mapped(input_files), scoped_task, write=False):
            value = _fingerprint(input_path, required=True)
            inputs.append(ArtifactReference(input_path, value["sha256"], value["size"]))
        outputs = _paths(mapped(output_files), scoped_task, write=True)
        contract = ArtifactContract(tuple(inputs), outputs)
        recorder.write(
            {
                "phase": "worktree_assigned",
                "parent_task_id": task.task_id,
                "source_workspace": str(source),
                "workspace": str(path),
                "branch": branch,
                "baseline_commit": baseline,
                "export_root": str(export_root),
                "inputs": [ref.to_dict() for ref in inputs],
                "outputs": [str(item) for item in outputs],
            }
        )
        task.resources.remaining_seconds()
        current_cancellation_token().throw_if_cancelled()
        child_admitted = True
        yield IsolatedWorktree(
            source,
            path,
            export_root,
            baseline,
            session,
            recorder,
            contract,
            gitdir,
            output_files is not None,
        )
