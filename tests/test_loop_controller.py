from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from runtime.core.cerebrum.react_types import ReActResult
from runtime.execution.loops.controller import LoopController
from runtime.execution.loops.models import (
    LoopAttempt,
    LoopPolicy,
    LoopRun,
    LoopRunStatus,
    VerifierFinding,
    VerifierResult,
)
from runtime.execution.loops.replay import (
    build_loop_run_replay_case,
    evaluate_loop_run_replay_case,
)
from runtime.execution.loops.store import LoopRunStore
from runtime.memory.diagnostics.trace_store import AgentTraceStore
from runtime.memory.learning.review_queue import ReviewQueue
from runtime.platform.process.session import current_session
from runtime.platform.process.task_supervisor import TaskRunStatus, TaskSupervisor
from runtime.platform.runtime_policy.workspaces import WorkspaceManager
from runtime.safety.approval.cancellation import CancellationSource


class _StubVerifierRegistry:
    def __init__(self, results: list[VerifierResult]) -> None:
        self._results = list(results)
        self.calls: list[tuple[str, str]] = []

    def run(self, profile: str, workspace_path: str) -> VerifierResult:
        self.calls.append((profile, workspace_path))
        return self._results.pop(0)


def test_loop_controller_retries_with_verifier_feedback(tmp_path) -> None:
    store = LoopRunStore(tmp_path / "loop_runs.json")
    queue = ReviewQueue(tmp_path / "review_queue.json")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    run = LoopRun(
        owner_id="alice",
        goal="Fix the failing authentication tests",
        thread_id="thread-loop",
        workspace_path=str(workspace),
        policy=LoopPolicy(max_attempts=2, max_iterations=3),
    )
    store.create(run)

    runner_calls: list[dict[str, object]] = []

    def runner(*, stack, intent, agent, model=None, max_iterations=0, thread_id=None):
        session = current_session()
        runner_calls.append(
            {
                "stack": stack,
                "prompt": intent.normalized_goal,
                "workspace_path": intent.user_context.get("workspace_path"),
                "thread_id": thread_id,
                "session_workspace": getattr(session, "metadata", {}).get("workspace_path")
                if session is not None
                else None,
            }
        )
        attempt_number = len(runner_calls)
        Path(intent.user_context["workspace_path"], f"attempt-{attempt_number}.txt").write_text(
            f"attempt {attempt_number}\n",
            encoding="utf-8",
        )
        return ReActResult(
            final_answer=f"attempt {attempt_number}",
            terminated_reason="final_answer",
            success=attempt_number > 1,
            completion_receipt={"attempt": attempt_number},
        )

    verifier_registry = _StubVerifierRegistry(
        [
            VerifierResult(
                profile="python_repo_patch",
                kind="python",
                passed=False,
                findings=[
                    VerifierFinding(
                        name="pytest",
                        passed=False,
                        exit_code=1,
                        stderr="AssertionError: expected 200 got 500",
                    )
                ],
                summary="failed checks: pytest",
            ),
            VerifierResult(
                profile="python_repo_patch",
                kind="python",
                passed=True,
                findings=[
                    VerifierFinding(
                        name="pytest",
                        passed=True,
                        exit_code=0,
                    )
                ],
                summary="all checks passed",
            ),
        ]
    )
    controller = LoopController(
        store=store,
        stack=SimpleNamespace(name="stack"),
        workspace_manager=WorkspaceManager(tmp_path / "workspaces"),
        verifier_registry=verifier_registry,
        review_queue=queue,
        react_runner=runner,
    )

    completed = controller.execute(run.run_id)

    assert completed.status == LoopRunStatus.COMPLETED
    assert len(completed.attempts) == 2
    assert completed.last_verifier_result is not None
    assert completed.last_verifier_result.passed is True
    assert runner_calls[0]["workspace_path"] == str(workspace)
    assert runner_calls[0]["session_workspace"] == str(workspace)
    assert runner_calls[1]["prompt"] != runner_calls[0]["prompt"]
    assert "did not pass verification" in str(runner_calls[1]["prompt"])
    assert verifier_registry.calls == [
        ("python_repo_patch", str(workspace)),
        ("python_repo_patch", str(workspace)),
    ]
    assert completed.last_review is not None
    assert completed.last_review["status"] == "completed"
    assert completed.last_review["replay"]["schema"] == "octopus.task_run_replay.v1"
    assert (
        completed.last_review["replay"]["case_id"]
        == f"task-run:{completed.last_review['replay']['fingerprint']}"
    )
    assert completed.last_review["replay"]["replayable"] is True
    assert (
        completed.last_review["replay"]["step_count"]
        == len(completed.last_review["replay"]["steps"])
    )
    assert completed.last_review["replay"]["steps"][0]["kind"] == "task_start"
    assert completed.last_review["replay"]["steps"][-1]["kind"] == "task_event"
    assert completed.last_review["resume"]["available"] is False
    assert completed.last_review["resume"]["latest_checkpoint"] == {}
    replay_case = build_loop_run_replay_case(completed.last_review)
    evaluation = evaluate_loop_run_replay_case(replay_case)
    assert evaluation["passed"] is True
    queued = queue.items(status="pending")
    assert queued["total"] == 1
    assert queued["items"][0]["candidate_kind"] == "success_pattern"
    assert queued["items"][0]["metadata"]["replay"]["replayable"] is True
    assert queued["items"][0]["metadata"]["replay"]["case_id"].startswith("task-run:")


def test_loop_controller_allocates_workspace_when_missing(tmp_path) -> None:
    store = LoopRunStore(tmp_path / "loop_runs.json")
    run = LoopRun(
        goal="Create a passing patch",
        policy=LoopPolicy(max_attempts=1, max_iterations=2),
    )
    store.create(run)

    def runner(*, stack, intent, agent, model=None, max_iterations=0, thread_id=None):
        workspace_path = Path(intent.user_context["workspace_path"])
        workspace_path.mkdir(parents=True, exist_ok=True)
        (workspace_path / "marker.txt").write_text("ok\n", encoding="utf-8")
        return ReActResult(final_answer="done", success=True)

    controller = LoopController(
        store=store,
        stack=SimpleNamespace(name="stack"),
        workspace_manager=WorkspaceManager(tmp_path / "workspaces"),
        verifier_registry=_StubVerifierRegistry(
            [
                VerifierResult(
                    profile="python_repo_patch",
                    kind="unknown",
                    passed=True,
                    summary="all checks passed",
                )
            ]
        ),
        react_runner=runner,
    )

    completed = controller.execute(run.run_id)

    assert completed.status == LoopRunStatus.COMPLETED
    assert completed.workspace_path is not None
    assert completed.workspace_path.startswith(str((tmp_path / "workspaces").resolve()))
    assert Path(completed.workspace_path, "marker.txt").is_file()


def test_loop_controller_failed_run_queues_failure_review(tmp_path) -> None:
    store = LoopRunStore(tmp_path / "loop_runs.json")
    queue = ReviewQueue(tmp_path / "review_queue.json")
    run = LoopRun(
        goal="Repair the flaky test suite",
        policy=LoopPolicy(max_attempts=1, max_iterations=2),
    )
    store.create(run)

    def runner(*, stack, intent, agent, model=None, max_iterations=0, thread_id=None):
        return ReActResult(final_answer="not fixed", success=False)

    controller = LoopController(
        store=store,
        stack=SimpleNamespace(name="stack"),
        workspace_manager=WorkspaceManager(tmp_path / "workspaces"),
        verifier_registry=_StubVerifierRegistry(
            [
                VerifierResult(
                    profile="python_repo_patch",
                    kind="python",
                    passed=False,
                    findings=[
                        VerifierFinding(
                            name="pytest",
                            passed=False,
                            exit_code=1,
                            stderr="1 failing test remains",
                        )
                    ],
                    summary="failed checks: pytest",
                )
            ]
        ),
        review_queue=queue,
        react_runner=runner,
    )

    failed = controller.execute(run.run_id)

    assert failed.status == LoopRunStatus.FAILED
    assert failed.last_review is not None
    assert failed.last_review["status"] == "failed"
    assert failed.last_review["replay"]["replayable"] is True
    assert failed.last_review["resume"]["available"] is True
    assert failed.last_review["resume"]["latest_checkpoint"]["id"].startswith("loop-run:")
    assert any(
        finding["type"] == "tool_error"
        for finding in failed.last_review["findings"]
    )
    replay_case = build_loop_run_replay_case(failed.last_review)
    evaluation = evaluate_loop_run_replay_case(replay_case)
    assert evaluation["passed"] is True
    assert (
        replay_case["resume"]["latest_checkpoint_id"]
        == failed.last_review["resume"]["latest_checkpoint"]["id"]
    )
    assert failed.last_review_queue_result is not None
    summary = queue.summary()
    assert summary["pending_count"] == 2
    queued = queue.items(status="pending")
    assert all(
        item["metadata"]["replay"]["replayable"] is True
        for item in queued["items"]
    )


def test_loop_controller_can_cancel_pending_run(tmp_path) -> None:
    store = LoopRunStore(tmp_path / "loop_runs.json")
    queue = ReviewQueue(tmp_path / "review_queue.json")
    run = LoopRun(
        goal="Cancel before execution begins",
        policy=LoopPolicy(max_attempts=1, max_iterations=1),
    )
    store.create(run)
    controller = LoopController(
        store=store,
        stack=SimpleNamespace(name="stack"),
        workspace_manager=WorkspaceManager(tmp_path / "workspaces"),
        review_queue=queue,
    )

    cancelled = controller.request_cancel(run.run_id, reason="operator stop")

    assert cancelled.status == LoopRunStatus.CANCELLED
    assert cancelled.cancel_reason == "operator stop"
    assert cancelled.cancel_requested_at is not None
    assert cancelled.completed_at is not None
    assert cancelled.last_review is not None
    assert cancelled.last_review["status"] == "cancelled"
    assert cancelled.last_review["resume"]["available"] is True
    assert cancelled.last_review_queue_result is None


def test_loop_controller_honors_cooperative_cancellation_token(tmp_path) -> None:
    store = LoopRunStore(tmp_path / "loop_runs.json")
    queue = ReviewQueue(tmp_path / "review_queue.json")
    run = LoopRun(
        goal="Stop when asked",
        policy=LoopPolicy(max_attempts=2, max_iterations=3),
    )
    store.create(run)
    cancellation = CancellationSource()
    verifier_registry = _StubVerifierRegistry([])

    def runner(*, stack, intent, agent, model=None, max_iterations=0, thread_id=None):
        from runtime.safety.approval.cancellation import current_cancellation_token

        token = current_cancellation_token()
        assert token.is_cancelled is False
        cancellation.cancel(reason="operator requested stop")
        assert token.is_cancelled is True
        return ReActResult(
            final_answer="",
            terminated_reason="cancelled",
            success=False,
        )

    controller = LoopController(
        store=store,
        stack=SimpleNamespace(name="stack"),
        workspace_manager=WorkspaceManager(tmp_path / "workspaces"),
        verifier_registry=verifier_registry,
        review_queue=queue,
        react_runner=runner,
    )

    cancelled = controller.execute(run.run_id, cancellation_token=cancellation.token)

    assert cancelled.status == LoopRunStatus.CANCELLED
    assert cancelled.cancel_reason == "operator requested stop"
    assert cancelled.last_review is not None
    assert cancelled.last_review["status"] == "cancelled"
    assert len(cancelled.attempts) == 1
    assert cancelled.last_review["resume"]["available"] is True
    assert cancelled.attempts[0].status == "cancelled"
    assert cancelled.attempts[0].terminated_reason == "cancelled"
    assert verifier_registry.calls == []


def test_loop_controller_restart_creates_child_run_with_lineage(tmp_path) -> None:
    store = LoopRunStore(tmp_path / "loop_runs.json")
    workspace = tmp_path / "workspace"
    controller = LoopController(
        store=store,
        stack=SimpleNamespace(name="stack"),
        workspace_manager=WorkspaceManager(tmp_path / "workspaces"),
    )
    source = LoopRun(
        owner_id="alice",
        origin_run_id="root-run",
        goal="Ship the loop runtime",
        thread_id="thread-loop",
        workspace_path=str(workspace),
        policy=LoopPolicy(max_attempts=3, max_iterations=4),
        status=LoopRunStatus.COMPLETED,
        attempts=[
            LoopAttempt(
                attempt_index=1,
                prompt="Ship the loop runtime",
                status="completed",
                success=True,
                final_answer="done",
            )
        ],
        last_verifier_result=VerifierResult(
            profile="python_repo_patch",
            kind="python",
            passed=True,
            summary="all checks passed",
        ),
        last_review={"status": "completed"},
        last_review_queue_result={"enqueued": True},
        completed_at="2026-06-25T00:00:00+00:00",
    )
    store.create(source)

    child = controller.restart(source.run_id)

    assert child.run_id != source.run_id
    assert child.owner_id == source.owner_id
    assert child.parent_run_id == source.run_id
    assert child.origin_run_id == "root-run"
    assert child.resume_checkpoint_id is None
    assert child.goal == source.goal
    assert child.mode == source.mode
    assert child.thread_id == source.thread_id
    assert child.workspace_path == source.workspace_path
    assert child.status == LoopRunStatus.PENDING
    assert child.attempts == []
    assert child.last_verifier_result is None
    assert child.last_review is None
    assert child.last_review_queue_result is None
    assert child.cancel_requested_at is None
    assert child.cancel_reason == ""
    assert child.last_error == ""
    assert child.started_at is None
    assert child.completed_at is None
    assert child.policy == source.policy
    assert child.policy is not source.policy
    assert store.get(child.run_id) is not None


def test_loop_controller_resume_requires_failed_or_cancelled(tmp_path) -> None:
    store = LoopRunStore(tmp_path / "loop_runs.json")
    controller = LoopController(
        store=store,
        stack=SimpleNamespace(name="stack"),
        workspace_manager=WorkspaceManager(tmp_path / "workspaces"),
    )
    completed = LoopRun(
        goal="Already fixed",
        workspace_path=str(tmp_path / "completed-workspace"),
        status=LoopRunStatus.COMPLETED,
    )
    failed = LoopRun(
        goal="Retry the verifier failure",
        thread_id="thread-failed",
        workspace_path=str(tmp_path / "failed-workspace"),
        status=LoopRunStatus.FAILED,
    )
    cancelled = LoopRun(
        goal="Continue after cancellation",
        origin_run_id="root-run",
        workspace_path=str(tmp_path / "cancelled-workspace"),
        status=LoopRunStatus.CANCELLED,
    )
    store.create(completed)
    store.create(failed)
    store.create(cancelled)

    with pytest.raises(ValueError, match="not resumable"):
        controller.resume(completed.run_id)

    resumed_failed = controller.resume(
        failed.run_id,
        goal="Retry with verifier context",
        reuse_workspace=False,
    )
    resumed_cancelled = controller.resume(
        cancelled.run_id,
        thread_id="thread-resumed",
    )

    assert resumed_failed.parent_run_id == failed.run_id
    assert resumed_failed.origin_run_id == failed.run_id
    assert resumed_failed.resume_checkpoint_id is not None
    assert resumed_failed.goal == "Retry with verifier context"
    assert resumed_failed.thread_id == failed.thread_id
    assert resumed_failed.workspace_path is None
    assert resumed_failed.status == LoopRunStatus.PENDING

    assert resumed_cancelled.parent_run_id == cancelled.run_id
    assert resumed_cancelled.origin_run_id == "root-run"
    assert resumed_cancelled.resume_checkpoint_id is not None
    assert resumed_cancelled.goal == cancelled.goal
    assert resumed_cancelled.thread_id == "thread-resumed"
    assert resumed_cancelled.workspace_path == cancelled.workspace_path
    assert resumed_cancelled.status == LoopRunStatus.PENDING


def test_loop_controller_resume_uses_checkpoint_context_on_first_attempt(tmp_path) -> None:
    store = LoopRunStore(tmp_path / "loop_runs.json")
    source = LoopRun(
        owner_id="alice",
        goal="Repair the verifier failure",
        workspace_path=str(tmp_path / "workspace"),
        status=LoopRunStatus.FAILED,
        attempts=[
            LoopAttempt(
                attempt_index=1,
                prompt="Repair the verifier failure",
                status="completed",
                success=False,
                final_answer="patched once",
                terminated_reason="final_answer",
                verifier_result=VerifierResult(
                    profile="python_repo_patch",
                    kind="python",
                    passed=False,
                    findings=[
                        VerifierFinding(
                            name="pytest",
                            passed=False,
                            exit_code=1,
                            stderr="1 failing test remains",
                        )
                    ],
                    summary="failed checks: pytest",
                ),
            )
        ],
        last_verifier_result=VerifierResult(
            profile="python_repo_patch",
            kind="python",
            passed=False,
            findings=[
                VerifierFinding(
                    name="pytest",
                    passed=False,
                    exit_code=1,
                    stderr="1 failing test remains",
                )
            ],
            summary="failed checks: pytest",
        ),
        last_error="failed checks: pytest",
    )
    store.create(source)
    seen_prompts: list[str] = []

    def runner(*, stack, intent, agent, model=None, max_iterations=0, thread_id=None):
        seen_prompts.append(intent.normalized_goal)
        return ReActResult(final_answer="fixed", success=True)

    controller = LoopController(
        store=store,
        stack=SimpleNamespace(name="stack"),
        workspace_manager=WorkspaceManager(tmp_path / "workspaces"),
        verifier_registry=_StubVerifierRegistry(
            [
                VerifierResult(
                    profile="python_repo_patch",
                    kind="python",
                    passed=True,
                    summary="all checks passed",
                )
            ]
        ),
        react_runner=runner,
    )

    resumed = controller.resume(source.run_id, goal="Finish the remaining repair work")
    completed = controller.execute(resumed.run_id)

    assert completed.status == LoopRunStatus.COMPLETED
    assert len(seen_prompts) == 1
    assert seen_prompts[0].startswith("Finish the remaining repair work")
    assert "Resume context from previous loop run" in seen_prompts[0]
    assert source.run_id in seen_prompts[0]
    assert resumed.resume_checkpoint_id in seen_prompts[0]
    assert "failed checks: pytest" in seen_prompts[0]


def test_loop_controller_records_loop_trace_checkpoints_and_task_run(tmp_path) -> None:
    store = LoopRunStore(tmp_path / "loop_runs.json")
    trace = AgentTraceStore(tmp_path / "agent_trace.sqlite")
    run = LoopRun(
        owner_id="alice",
        goal="Repair the flaky verifier failure",
        thread_id="thread-loop",
        workspace_path=str(tmp_path / "workspace"),
        policy=LoopPolicy(max_attempts=1, max_iterations=2),
    )
    store.create(run)

    def runner(*, stack, intent, agent, model=None, max_iterations=0, thread_id=None):
        return ReActResult(final_answer="not fixed", success=False)

    controller = LoopController(
        store=store,
        stack=SimpleNamespace(name="stack"),
        workspace_manager=WorkspaceManager(tmp_path / "workspaces"),
        verifier_registry=_StubVerifierRegistry(
            [
                VerifierResult(
                    profile="python_repo_patch",
                    kind="python",
                    passed=False,
                    findings=[
                        VerifierFinding(
                            name="pytest",
                            passed=False,
                            exit_code=1,
                            stderr="1 failing test remains",
                        )
                    ],
                    summary="failed checks: pytest",
                )
            ]
        ),
        trace_store=trace,
        react_runner=runner,
    )

    failed = controller.execute(run.run_id)

    checkpoints = trace.checkpoints(task_id=run.run_id, checkpoint_type="loop_run")
    assert len(checkpoints) == 1
    checkpoint = checkpoints[0]
    assert checkpoint["thread_id"] == "thread-loop"
    assert checkpoint["agent_id"] == "loop_controller"
    assert checkpoint["iteration"] == 1
    assert checkpoint["state"]["current_phase"] == "failed"
    assert checkpoint["state"]["parent_run_id"] is None
    assert checkpoint["state"]["steps_snapshot"][0]["action"].startswith("react_attempt(")
    assert checkpoint["state"]["steps_snapshot"][1]["action"].startswith("verifier:")

    proposals = trace.resume_proposals(task_id=run.run_id, checkpoint_type="loop_run")
    assert len(proposals) == 1
    assert proposals[0]["checkpoint"]["type"] == "loop_run"
    assert proposals[0]["recovery_hints"]["phase"] == "failed"
    assert proposals[0]["recovery_hints"]["step_count"] == 2
    assert proposals[0]["safety"]["integrity"]["resume_safe"] is True

    task_run = trace.task_run(run.run_id)
    assert task_run is not None
    assert task_run["status"] == "failed"
    assert task_run["checkpoint_count"] == 1
    assert task_run["latest_checkpoint"]["type"] == "loop_run"

    assert failed.last_review is not None
    assert failed.last_review["summary"]["trace_checkpoint_id"] == checkpoint["id"]
    assert (
        failed.last_review["resume"]["latest_checkpoint"]["trace_checkpoint_id"]
        == checkpoint["id"]
    )

    trace.close()


def test_loop_controller_writes_task_supervisor_record(tmp_path) -> None:
    store = LoopRunStore(tmp_path / "loop_runs.json")
    trace = AgentTraceStore(tmp_path / "agent_trace.sqlite")
    supervisor = TaskSupervisor.from_path(
        tmp_path / "task_runs.json",
        holder_id="loop-worker",
    )
    workspace = tmp_path / "repo"
    workspace.mkdir()
    run = LoopRun(
        owner_id="alice",
        goal="Fix task supervisor wiring",
        thread_id="thread-loop",
        workspace_path=str(workspace),
        policy=LoopPolicy(max_attempts=1, max_iterations=2),
    )
    store.create(run)
    session_metadata: list[dict[str, object]] = []

    def runner(*, stack, intent, agent, model=None, max_iterations=0, thread_id=None):
        session = current_session()
        session_metadata.append(dict(session.metadata) if session is not None else {})
        return ReActResult(final_answer="fixed", success=True)

    controller = LoopController(
        store=store,
        stack=SimpleNamespace(name="stack"),
        workspace_manager=WorkspaceManager(tmp_path / "workspaces"),
        verifier_registry=_StubVerifierRegistry(
            [
                VerifierResult(
                    profile="python_repo_patch",
                    kind="python",
                    passed=True,
                    summary="ok",
                )
            ]
        ),
        trace_store=trace,
        task_supervisor=supervisor,
        react_runner=runner,
    )

    completed = controller.execute(run.run_id)
    record = supervisor.store.get(run.run_id)

    assert completed.status == LoopRunStatus.COMPLETED
    assert record is not None
    assert record.kind == "loop"
    assert record.status == TaskRunStatus.COMPLETED
    assert record.owner_id == "alice"
    assert record.thread_id == "thread-loop"
    assert record.workspace_path == str(workspace)
    assert record.lease is None
    assert record.latest_checkpoint_id is not None
    assert record.capabilities.allows_group("shell") is True
    assert session_metadata
    assert session_metadata[0]["task_id"] == run.run_id
    assert "task_capability_manifest" in session_metadata[0]

    trace.close()


def test_loop_controller_skips_execution_when_task_lease_is_foreign(tmp_path) -> None:
    store = LoopRunStore(tmp_path / "loop_runs.json")
    run = LoopRun(
        owner_id="alice",
        goal="Do not duplicate this task",
        policy=LoopPolicy(max_attempts=1, max_iterations=2),
    )
    store.create(run)
    task_runs_path = tmp_path / "task_runs.json"
    owner = TaskSupervisor.from_path(task_runs_path, holder_id="worker-a")
    owner.start_task(task_id=run.run_id, kind="loop", status=TaskRunStatus.RUNNING)
    contender = TaskSupervisor.from_path(task_runs_path, holder_id="worker-b")
    runner_calls: list[str] = []

    def runner(*, stack, intent, agent, model=None, max_iterations=0, thread_id=None):
        runner_calls.append(intent.normalized_goal)
        return ReActResult(final_answer="should not run", success=True)

    controller = LoopController(
        store=store,
        stack=SimpleNamespace(name="stack"),
        workspace_manager=WorkspaceManager(tmp_path / "workspaces"),
        verifier_registry=_StubVerifierRegistry([]),
        task_supervisor=contender,
        react_runner=runner,
    )

    latest = controller.execute(run.run_id)
    record = owner.store.get(run.run_id)

    assert latest.status == LoopRunStatus.PENDING
    assert latest.attempts == []
    assert runner_calls == []
    assert record is not None
    assert record.lease is not None
    assert record.lease.holder_id == "worker-a"


def test_loop_controller_stops_writing_after_task_lease_is_lost(tmp_path) -> None:
    store = LoopRunStore(tmp_path / "loop_runs.json")
    supervisor = TaskSupervisor.from_path(tmp_path / "task_runs.json", holder_id="worker-a")
    run = LoopRun(
        owner_id="alice",
        goal="Stop after lease loss",
        workspace_path=str(tmp_path / "workspace"),
        policy=LoopPolicy(max_attempts=1, max_iterations=2),
    )
    store.create(run)
    verifier_registry = _StubVerifierRegistry(
        [
            VerifierResult(
                profile="python_repo_patch",
                kind="python",
                passed=True,
                summary="should not verify",
            )
        ]
    )

    def runner(*, stack, intent, agent, model=None, max_iterations=0, thread_id=None):
        def _steal(record):
            assert record.lease is not None
            return record.model_copy(
                update={
                    "lease": record.lease.model_copy(update={"holder_id": "worker-b"}),
                },
                deep=True,
            )

        supervisor.store.mutate(run.run_id, _steal)
        return ReActResult(final_answer="fixed", success=True)

    controller = LoopController(
        store=store,
        stack=SimpleNamespace(name="stack"),
        workspace_manager=WorkspaceManager(tmp_path / "workspaces"),
        verifier_registry=verifier_registry,
        task_supervisor=supervisor,
        react_runner=runner,
    )

    latest = controller.execute(run.run_id)
    record = supervisor.store.get(run.run_id)

    assert latest.status == LoopRunStatus.RUNNING
    assert len(latest.attempts) == 1
    assert latest.attempts[0].status == "running"
    assert latest.last_verifier_result is None
    assert latest.completed_at is None
    assert verifier_registry.calls == []
    assert record is not None
    assert record.lease is not None
    assert record.lease.holder_id == "worker-b"
    assert record.status == TaskRunStatus.RUNNING
