"""Scoped child isolation through real Git worktrees and the real bridge."""

from __future__ import annotations

import asyncio
import hashlib
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from runtime.execution.artifact_contracts import HandoffRecorder
from runtime.execution.request import current_execution_request
from runtime.execution.subagents.bridge import call_subagent
from runtime.memory.threads.event_log import EventLog
from runtime.platform.process.session import current_session
from runtime.safety.approval.cancellation import CancellationSource, scoped_cancellation
from tests.test_artifact_handoff import _events
from tests.test_subagent_execution_context import _parent
from tests.test_worktree_loop import _init_repo, _worktree_count


def _git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, check=True, timeout=15
    ).stdout


def _host(tmp_path):
    repo = _init_repo(tmp_path)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    parent = _parent(repo)
    task = parent.metadata["_execution_task"]
    parent.metadata["_execution_task"] = replace(
        task,
        permissions=replace(
            task.permissions, readable_roots=(repo, artifacts), writable_roots=(repo, artifacts)
        ),
    )
    parent.metadata["_artifact_output_root"] = str(artifacts)
    log = EventLog(tmp_path / "events.jsonl")
    parent.metadata["_execution_handoff_recorder"] = HandoffRecorder(
        lambda receipt: log.execution_handoff(task.thread_id, task.task_id, receipt),
        lambda: tuple(
            dict(event.payload)
            for event in log.iter_events()
            if event.event == "execution_handoff" and event.thread_id == task.thread_id
        ),
    )
    return repo, parent, log


def test_snapshot_retains_dirty_working_files_without_touching_head_or_index(tmp_path):
    repo, parent, log = _host(tmp_path)
    (repo / "deleted.txt").write_text("old")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "tracked input")
    (repo / "README.md").write_text("staged\n")
    _git(repo, "add", "README.md")
    (repo / "README.md").write_text("actual working version\n")
    (repo / "input.txt").write_text("untracked input\n")
    (repo / "deleted.txt").unlink()
    head = _git(repo, "rev-parse", "HEAD")
    index = (repo / ".git" / "index").read_bytes()
    workspaces = []

    def runner(*_args, **_kwargs):
        request = current_execution_request()
        workspace = Path(current_session().metadata["workspace_path"])
        workspaces.append(workspace)
        assert workspace != repo and request.task.permissions.allows_write(workspace)
        assert not request.task.permissions.allows_write(repo)
        assert request.task.artifacts.inputs[0].path == workspace / "README.md"
        assert (workspace / "README.md").read_text() == "actual working version\n"
        assert (workspace / "input.txt").read_text() == "untracked input\n"
        assert not (workspace / "deleted.txt").exists()
        (workspace / "README.md").write_text("implemented\n")
        (workspace / "asset.bin").write_bytes(b"\x00\xff\x01binary")
        return "implemented candidate"

    result = call_subagent(
        "coder",
        "implement",
        session=parent,
        isolate=True,
        runner=runner,
        input_files=["README.md"],
        output_files=["README.md", "asset.bin"],
        timeout_seconds=15,
    )
    assert result["success"], result
    assert result["worktree"]["contract_valid"] is True
    assert result["worktree"]["applied"] is False
    patch = Path(result["worktree"]["patch"]["path"])
    assert patch.exists() and "GIT binary patch" in patch.read_text()
    assert result["worktree"]["patch"]["sha256"] == hashlib.sha256(patch.read_bytes()).hexdigest()
    assert set(result["files_touched"]) == {"README.md", "asset.bin"}
    assert not workspaces[0].exists() and _worktree_count(repo) == 1
    assert (repo / "README.md").read_text() == "actual working version\n"
    assert (repo / ".git" / "index").read_bytes() == index
    assert _git(repo, "rev-parse", "HEAD") == head
    assert (
        _git(repo, "rev-parse", result["worktree"]["baseline_ref"]).decode().strip()
        == result["worktree"]["baseline_commit"]
    )
    _git(repo, "apply", "--check", str(patch))
    assert [row["phase"] for row in _events(log)] == ["worktree_assigned", "worktree_exported"]
    assert result["worktree"]["child_task_id"] != "parent-turn"


def test_parallel_lanes_edit_the_same_file_in_distinct_workspaces(tmp_path, monkeypatch):
    from runtime.execution.subagents import bridge
    from runtime.execution.suckers import delegation_skills as skills

    repo, parent, _ = _host(tmp_path)
    ready = threading.Barrier(2, timeout=15)
    scopes = []

    def runner(prompt, **_kwargs):
        workspace = Path(current_session().metadata["workspace_path"])
        request = current_execution_request()
        scopes.append((workspace, request.task))
        ready.wait()
        for other, _task in scopes:
            if other != workspace:
                assert not request.task.permissions.allows_write(other)
        label = "alpha" if "alpha" in prompt else "beta"
        (workspace / "README.md").write_text(label + "\n")
        return label

    monkeypatch.setattr(bridge, "_RUNNER", runner)
    monkeypatch.setattr(bridge, "_REGISTRY", None)
    monkeypatch.setattr(skills, "_allowed_agent_ids", lambda: {"coder"})
    result = skills._call_agent_parallel(
        [
            {"agent_id": "coder", "prompt": label, "isolate": True, "output_files": ["README.md"]}
            for label in ("alpha", "beta")
        ],
        session=parent,
        timeout_s=20,
    )
    assert result["success_count"] == 2, result
    assert len({path for path, _task in scopes}) == 2
    assert len({task.task_id for _path, task in scopes}) == 2
    patches = [Path(item["worktree"]["patch"]["path"]).read_text() for item in result["successes"]]
    assert any("+alpha" in patch for patch in patches)
    assert any("+beta" in patch for patch in patches)
    assert (repo / "README.md").read_text() == "base\n"
    assert _worktree_count(repo) == 1


def test_cancelled_worker_keeps_checkout_until_it_stops_then_exports_partial_patch(tmp_path):
    repo, parent, log = _host(tmp_path)
    started = threading.Event()
    release = threading.Event()
    paths = []
    cancellation = CancellationSource()

    def runner(*_args, **_kwargs):
        workspace = Path(current_session().metadata["workspace_path"])
        paths.append(workspace)
        (workspace / "README.md").write_text("partial\n")
        started.set()
        assert release.wait(10)
        return "late success"

    with ThreadPoolExecutor(max_workers=1) as pool:
        with scoped_cancellation(cancellation.token):
            future = pool.submit(
                copy_context().run,
                lambda: call_subagent(
                    "coder",
                    "write",
                    session=parent,
                    isolate=True,
                    runner=runner,
                    timeout_seconds=20,
                ),
            )
        try:
            assert started.wait(15)
            cancellation.cancel(reason="user stopped")
            result = future.result(timeout=2)
            assert result["status"] == "cancelled" and result["retry_allowed"] is False
            assert paths[0].exists() and _worktree_count(repo) == 2
            assert [row["phase"] for row in _events(log)] == ["worktree_assigned"]
        finally:
            release.set()
    deadline = time.monotonic() + 10
    while paths[0].exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert not paths[0].exists() and _worktree_count(repo) == 1
    receipt = _events(log)[-1]
    assert receipt["phase"] == "worktree_exported" and not receipt["contract_valid"]
    assert "+partial" in Path(receipt["patch"]["path"]).read_text()
    assert (repo / "README.md").read_text() == "base\n"


def test_export_journal_failure_retains_checkout_for_reconciliation(tmp_path):
    repo, parent, log = _host(tmp_path)
    write = parent.metadata["_execution_handoff_recorder"].write

    def record(receipt):
        if receipt["phase"] == "worktree_exported":
            raise OSError("journal full")
        write(receipt)

    parent.metadata["_execution_handoff_recorder"] = HandoffRecorder(record)

    def runner(*_args, **_kwargs):
        (Path(current_session().metadata["workspace_path"]) / "README.md").write_text("candidate\n")
        return "done"

    result = call_subagent(
        "coder", "write", session=parent, isolate=True, runner=runner, timeout_seconds=15
    )
    assert not result["success"] and "journal full" in result["error"]
    assigned = _events(log)[0]
    retained = Path(assigned["workspace"])
    assert retained.is_relative_to(tmp_path.resolve())
    assert retained.exists() and (retained / "README.md").read_text() == "candidate\n"
    assert _worktree_count(repo) == 2
    _git(repo, "worktree", "remove", "--force", str(retained))
    _git(repo, "branch", "-D", assigned["branch"])


@pytest.mark.parametrize("change_input", [False, True])
def test_missing_output_or_modified_input_does_not_validate_candidate(tmp_path, change_input):
    repo, parent, log = _host(tmp_path)

    def runner(*_args, **_kwargs):
        if change_input:
            workspace = Path(current_session().metadata["workspace_path"])
            (workspace / "README.md").write_text("changed input\n")
            (workspace / "output.txt").write_text("output\n")
        return "done"

    result = call_subagent(
        "coder",
        "write",
        session=parent,
        isolate=True,
        runner=runner,
        input_files=["README.md"],
        output_files=["output.txt"],
        timeout_seconds=15,
    )
    assert not result["success"]
    assert not result["worktree"]["contract_valid"]
    assert _events(log)[-1]["phase"] == "worktree_exported"
    assert _worktree_count(repo) == 1


def test_codex_role_receives_the_isolated_workspace_and_shared_scope(tmp_path, monkeypatch):
    from runtime.execution.codex_backend import role_runner
    from runtime.execution.parallel_agents.stack_runner import make_stack_subagent_runner

    repo, parent, _ = _host(tmp_path)
    stack = SimpleNamespace(planner=SimpleNamespace(plan=lambda: None), runtime=object())
    coder = SimpleNamespace(
        display_name="Coder", capabilities={"execution_backend": "codex_app_server"}
    )
    registry = SimpleNamespace(has=lambda _name: True, get=lambda _name: coder)

    def codex(_stack, _agent, _goal, *, context, **_kwargs):
        session = current_session()
        workspace = role_runner._workspace(context, session)
        request = current_execution_request()
        assert workspace != repo and context["workspace_path"] == str(workspace)
        assert request.task.permissions.writable_roots == (workspace,)
        assert (
            role_runner.resolve_codex_sandbox_mode(
                context, trusted_parent_metadata=session.metadata
            )
            == "workspace-write"
        )
        assert request.task.parent_task_id == "parent-turn"
        (workspace / "README.md").write_text("Codex candidate\n")
        return role_runner.CodexRoleExecution("candidate complete", True, "completed")

    monkeypatch.setattr(role_runner, "run_agent_role_sync", codex)
    result = call_subagent(
        "coder",
        "implement",
        session=parent,
        isolate=True,
        output_files=["README.md"],
        runner=make_stack_subagent_runner(stack, agent_registry=registry),
        timeout_seconds=15,
    )
    assert result["success"], result
    assert "+Codex candidate" in Path(result["worktree"]["patch"]["path"]).read_text()
    assert (repo / "README.md").read_text() == "base\n"


def test_git_pointer_cannot_redirect_export_into_parent_index(tmp_path):
    from runtime.execution.subagents.worktree_loop import _restore_worktree_gitfile

    repo, parent, log = _host(tmp_path)
    index = (repo / ".git" / "index").read_bytes()
    original = []

    def runner(*_args, **_kwargs):
        workspace = Path(current_session().metadata["workspace_path"])
        pointer = workspace / ".git"
        original.append(pointer.read_text().split(":", 1)[1].strip())
        with pointer.open("r+", encoding="utf-8") as handle:
            handle.write(f"gitdir: {repo / '.git'}\n")
            handle.truncate()
        (workspace / "README.md").write_text("must not enter parent index\n")
        return "done"

    result = call_subagent(
        "coder", "write", session=parent, isolate=True, runner=runner, timeout_seconds=15
    )
    assert not result["success"] and "gitdir changed" in result["error"]
    assert (repo / ".git" / "index").read_bytes() == index
    assigned = _events(log)[0]
    retained = Path(result["retained_workspace"])
    assert retained.is_relative_to(tmp_path.resolve())
    _restore_worktree_gitfile(str(retained), original[0])
    _git(repo, "worktree", "remove", "--force", str(retained))
    _git(repo, "branch", "-D", assigned["branch"])


def test_initial_journal_failure_does_not_start_engine_or_leave_checkout(tmp_path):
    repo, parent, _ = _host(tmp_path)
    parent.metadata["_execution_handoff_recorder"] = HandoffRecorder(
        lambda _receipt: (_ for _ in ()).throw(OSError("disk full"))
    )
    called = []
    result = call_subagent(
        "coder",
        "write",
        session=parent,
        isolate=True,
        runner=lambda *_args, **_kwargs: called.append(True),
        timeout_seconds=15,
    )
    assert not result["success"] and "disk full" in result["error"]
    assert called == [] and _worktree_count(repo) == 1


def test_isolation_does_not_expand_parent_scope(tmp_path):
    repo, parent, _ = _host(tmp_path)
    task = parent.metadata["_execution_task"]
    parent.metadata["_execution_task"] = replace(
        task, permissions=replace(task.permissions, writable_roots=())
    )
    called = []
    result = call_subagent(
        "coder",
        "write",
        session=parent,
        isolate=True,
        runner=lambda *_args, **_kwargs: called.append(True),
        timeout_seconds=15,
    )
    assert not result["success"] and "outside the parent scope" in result["error"]
    assert called == [] and _worktree_count(repo) == 1


def test_undeclared_changes_are_exported_but_not_validated(tmp_path):
    _repo, parent, _log = _host(tmp_path)

    def runner(*_args, **_kwargs):
        workspace = Path(current_session().metadata["workspace_path"])
        (workspace / "README.md").write_text("declared\n")
        (workspace / "unexpected.txt").write_text("unexpected\n")
        return "done"

    result = call_subagent(
        "coder",
        "write",
        session=parent,
        isolate=True,
        output_files=["README.md"],
        runner=runner,
        timeout_seconds=15,
    )
    assert not result["success"] and "undeclared" in result["error"]
    assert not result["worktree"]["contract_valid"]
    assert "unexpected.txt" in result["worktree"]["files"]


def test_async_cancellation_exports_partial_patch_before_cleanup(tmp_path):
    repo, parent, log = _host(tmp_path)

    def runner(*_args, **_kwargs):
        workspace = Path(current_session().metadata["workspace_path"])
        (workspace / "README.md").write_text("partial implementation\n")
        raise asyncio.CancelledError()

    result = call_subagent(
        "coder", "implement", session=parent, isolate=True, runner=runner, timeout_seconds=15
    )
    assert not result["success"] and result["status"] == "cancelled"
    assert not result["worktree"]["contract_valid"] and result["retry_allowed"] is False
    assert "partial implementation" in Path(result["worktree"]["patch"]["path"]).read_text()
    assert _worktree_count(repo) == 1
    assert "partial implementation" not in (repo / "README.md").read_text()
    assert _events(log)[-1]["phase"] == "worktree_exported"


def test_parallel_parent_cancellation_reaches_both_isolated_children(tmp_path, monkeypatch):
    from runtime.execution.subagents import bridge
    from runtime.execution.suckers import delegation_skills as skills

    repo, parent, log = _host(tmp_path)
    started = threading.Barrier(3, timeout=20)
    release = threading.Event()
    paths = []
    cancellation = CancellationSource()

    def runner(*_args, **_kwargs):
        workspace = Path(current_session().metadata["workspace_path"])
        paths.append(workspace)
        (workspace / "README.md").write_text("unfinished\n")
        started.wait()
        assert release.wait(10)
        return "late completion"

    monkeypatch.setattr(bridge, "_RUNNER", runner)
    monkeypatch.setattr(bridge, "_REGISTRY", None)
    monkeypatch.setattr(skills, "_allowed_agent_ids", lambda: {"coder"})
    with ThreadPoolExecutor(max_workers=1) as pool:
        with scoped_cancellation(cancellation.token):
            future = pool.submit(
                copy_context().run,
                lambda: skills._call_agent_parallel(
                    [
                        {"agent_id": "coder", "prompt": label, "isolate": True}
                        for label in ("one", "two")
                    ],
                    session=parent,
                    timeout_s=30,
                ),
            )
        try:
            started.wait()
            cancellation.cancel(reason="parent stopped")
            result = future.result(timeout=2)
            assert result["success_count"] == 0 and len(result["failures"]) == 2
            assert all(
                item["status"] == "cancelled" and item["retry_allowed"] is False
                for item in result["failures"]
            )
            assert all(path.exists() for path in paths)
        finally:
            release.set()
    deadline = time.monotonic() + 10
    while any(path.exists() for path in paths) and time.monotonic() < deadline:
        time.sleep(0.02)
    assert all(not path.exists() for path in paths) and _worktree_count(repo) == 1
    exports = [row for row in _events(log) if row["phase"] == "worktree_exported"]
    assert len(exports) == 2 and all(not row["contract_valid"] for row in exports)
