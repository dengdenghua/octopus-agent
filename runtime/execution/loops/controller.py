from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

from runtime.core.cerebrum.react_types import ReActResult
from runtime.execution.loops.learning import build_loop_run_review
from runtime.execution.loops.models import (
    LoopAttempt,
    LoopMode,
    LoopRun,
    LoopRunStatus,
    VerifierFinding,
    VerifierResult,
)
from runtime.execution.loops.recovery import (
    build_loop_run_checkpoint,
    build_loop_run_resume_prompt,
)
from runtime.execution.loops.store import LoopRunStore
from runtime.execution.loops.verifiers import (
    LoopVerifierRegistry,
    build_default_loop_verifier_registry,
)
from runtime.memory.diagnostics.trace_store import AgentTraceStore
from runtime.memory.learning.review_queue import ReviewQueue
from runtime.platform.process.session import Session, session_scope
from runtime.platform.process.task_supervisor import (
    LostTaskLease,
    TaskCapabilityManifest,
    TaskLeaseConflict,
    TaskRunStatus,
    TaskSupervisor,
)
from runtime.platform.runtime_policy.workspaces import WorkspaceManager
from runtime.safety.approval.cancellation import CancellationToken, scoped_cancellation

_LOG = logging.getLogger(__name__)
_TRACE_AGENT_ID = "loop_controller"


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


def _resolve_workspace_path(run: LoopRun, workspace_manager: WorkspaceManager) -> str:
    if run.workspace_path:
        return str(Path(run.workspace_path).expanduser().resolve(strict=False))
    thread_key = run.thread_id or run.run_id
    return str(workspace_manager.allocate(thread_key))


def _truncate_text(value: Any, *, limit: int = 4_000) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


_NON_REPAIRABLE_VERIFIER_CATEGORIES = frozenset(
    {
        "environment_missing_dependency",
        "environment_missing_tool",
        "project_kind_mismatch",
        "verifier_internal_error",
        "verifier_misconfigured",
        "verifier_profile_unknown",
        "verifier_sandbox_violation",
        "verification_cancelled",
    }
)
_ACTIVE_LOOP_STATUSES = frozenset(
    {
        LoopRunStatus.RUNNING,
        LoopRunStatus.VERIFYING,
        LoopRunStatus.REPAIRING,
    }
)


def _failed_verifier_findings(verifier: VerifierResult | None) -> list[VerifierFinding]:
    if verifier is None:
        return []
    return [finding for finding in verifier.findings if not finding.passed]


def _verifier_failure_category(verifier: VerifierResult | None) -> str:
    if verifier is None or verifier.passed:
        return ""
    category = str(verifier.failure_category or "").strip()
    if category:
        return category
    categories = [
        str(finding.category or "").strip()
        for finding in _failed_verifier_findings(verifier)
        if str(finding.category or "").strip()
    ]
    if any(category in _NON_REPAIRABLE_VERIFIER_CATEGORIES for category in categories):
        return next(
            category for category in categories if category in _NON_REPAIRABLE_VERIFIER_CATEGORIES
        )
    return categories[0] if categories else "verification_failure"


def _verifier_failure_repairable(verifier: VerifierResult | None) -> bool:
    if verifier is None or verifier.passed:
        return True
    return _verifier_failure_category(verifier) not in _NON_REPAIRABLE_VERIFIER_CATEGORIES


def _verifier_error_text(verifier: VerifierResult | None) -> str:
    if verifier is None:
        return ""
    category = _verifier_failure_category(verifier)
    summary = str(verifier.summary or "").strip() or "verification failed"
    if category in _NON_REPAIRABLE_VERIFIER_CATEGORIES and category not in summary:
        return f"verification blocker ({category}): {summary}"
    return summary


def _verifier_feedback(verifier: VerifierResult | None) -> str:
    if verifier is None:
        return ""
    failed = _failed_verifier_findings(verifier)
    if not failed:
        return ""
    category = _verifier_failure_category(verifier)
    if not _verifier_failure_repairable(verifier):
        lines = [
            "The previous verification was blocked by the execution environment, not by a repairable code failure.",
            f"Category: {category}",
            "Do not edit application code just to satisfy this signal. Resolve the verifier configuration or toolchain first.",
            "",
            "Verifier evidence:",
        ]
        for finding in failed[:5]:
            output = finding.stderr or finding.stdout or f"exit code {finding.exit_code}"
            lines.append(f"- [{finding.name}] {_truncate_text(output, limit=600)}")
        return "\n".join(lines).strip()
    lines = [
        "The previous attempt did not pass verification.",
        f"Failure category: {category}",
        "Fix the issues below before you finish:",
        "",
    ]
    for finding in failed[:5]:
        output = finding.stderr or finding.stdout or f"exit code {finding.exit_code}"
        lines.append(f"- [{finding.name}] {_truncate_text(output, limit=600)}")
    return "\n".join(lines).strip()


def _unsupported_mode_result(mode: LoopMode) -> VerifierResult:
    return VerifierResult(
        profile="unsupported_mode",
        kind=mode.value,
        failure_category="unsupported_mode",
        passed=False,
        summary=f"unsupported loop mode: {mode.value}",
        findings=[
            VerifierFinding(
                name="unsupported-mode",
                command="",
                category="unsupported_mode",
                passed=False,
                exit_code=-1,
                stderr=f"unsupported loop mode: {mode.value}",
            )
        ],
    )


class LoopController:
    def __init__(
        self,
        *,
        store: LoopRunStore,
        stack: Any,
        workspace_manager: WorkspaceManager,
        verifier_registry: LoopVerifierRegistry | None = None,
        review_queue: ReviewQueue | None = None,
        trace_store: AgentTraceStore | None = None,
        task_supervisor: TaskSupervisor | None = None,
        react_runner: Any = None,
    ) -> None:
        self.store = store
        self.stack = stack
        self.workspace_manager = workspace_manager
        self.verifier_registry = verifier_registry or build_default_loop_verifier_registry()
        self.review_queue = review_queue
        self.trace_store = trace_store
        self.task_supervisor = task_supervisor
        self.react_runner = react_runner
        self._lock = threading.Lock()
        self._executing: set[str] = set()

    def execute(
        self,
        run_id: str,
        *,
        cancellation_token: CancellationToken | None = None,
    ) -> LoopRun:
        run = self.store.get(run_id)
        if run is None:
            raise KeyError(run_id)
        if run.status in {
            LoopRunStatus.COMPLETED,
            LoopRunStatus.FAILED,
            LoopRunStatus.CANCELLED,
        }:
            return run
        with self._lock:
            if run_id in self._executing:
                current = self.store.get(run_id)
                if current is None:
                    raise KeyError(run_id)
                return current
            self._executing.add(run_id)
        try:
            return self._execute_locked(run_id, cancellation_token=cancellation_token)
        finally:
            with self._lock:
                self._executing.discard(run_id)

    def request_cancel(
        self,
        run_id: str,
        *,
        reason: str = "cancelled by operator",
    ) -> LoopRun:
        run = self.store.get(run_id)
        if run is None:
            raise KeyError(run_id)
        if run.status in {
            LoopRunStatus.COMPLETED,
            LoopRunStatus.FAILED,
            LoopRunStatus.CANCELLED,
        }:
            return run
        cancel_reason = str(reason or "").strip() or "cancelled by operator"
        requested = self.store.mutate(
            run_id,
            lambda current, cancel_reason=cancel_reason: current.model_copy(
                update={
                    "cancel_requested_at": current.cancel_requested_at or _now_iso(),
                    "cancel_reason": cancel_reason,
                    "last_error": cancel_reason,
                }
            ),
        )
        with self._lock:
            executing = run_id in self._executing
        if executing:
            return requested
        if not self._supervisor_heartbeat(run_id):
            return requested
        return self._cancel_run(run_id, cancel_reason)

    def restart(
        self,
        run_id: str,
        *,
        goal: str | None = None,
        thread_id: str | None = None,
        workspace_path: str | None = None,
        reuse_workspace: bool = True,
        policy: Any = None,
    ) -> LoopRun:
        source = self.store.get(run_id)
        if source is None:
            raise KeyError(run_id)
        self._ensure_restartable(source)
        return self._spawn_child_run(
            source,
            goal=goal,
            thread_id=thread_id,
            workspace_path=workspace_path,
            reuse_workspace=reuse_workspace,
            policy=policy,
            resume_checkpoint_id=None,
        )

    def resume(
        self,
        run_id: str,
        *,
        goal: str | None = None,
        thread_id: str | None = None,
        workspace_path: str | None = None,
        reuse_workspace: bool = True,
        policy: Any = None,
    ) -> LoopRun:
        source = self.store.get(run_id)
        if source is None:
            raise KeyError(run_id)
        if source.status not in {LoopRunStatus.FAILED, LoopRunStatus.CANCELLED}:
            raise ValueError("loop run is not resumable")
        return self._spawn_child_run(
            source,
            goal=goal,
            thread_id=thread_id,
            workspace_path=workspace_path,
            reuse_workspace=reuse_workspace,
            policy=policy,
            resume_checkpoint_id=build_loop_run_checkpoint(source)["id"],
        )

    def _execute_locked(
        self,
        run_id: str,
        *,
        cancellation_token: CancellationToken | None = None,
    ) -> LoopRun:
        run = self.store.get(run_id)
        if run is None:
            raise KeyError(run_id)
        if cancelled := self._check_for_cancellation(
            run_id,
            cancellation_token=cancellation_token,
        ):
            return cancelled
        if run.mode != LoopMode.CODE:
            verifier_result = _unsupported_mode_result(run.mode)
            run = self.store.mutate(
                run_id,
                lambda current: current.model_copy(
                    update={
                        "status": LoopRunStatus.FAILED,
                        "completed_at": _now_iso(),
                        "last_error": verifier_result.summary,
                        "last_verifier_result": verifier_result,
                    }
                ),
            )
            return self._finalize_learning(run)
        workspace_path = _resolve_workspace_path(run, self.workspace_manager)
        supervisor_run = run.model_copy(update={"workspace_path": workspace_path})
        if not self._supervisor_start(supervisor_run):
            return self._latest_run(run_id)
        run = self.store.mutate(
            run_id,
            lambda current: current.model_copy(
                update={
                    "workspace_path": workspace_path,
                    "started_at": current.started_at or _now_iso(),
                }
            ),
        )
        self._record_trace_run_started(run)
        run = self._recover_interrupted_attempts(run_id)
        terminal = self._recover_verified_terminal_run(run_id)
        if terminal is not None:
            return terminal
        run = self._latest_run(run_id)
        if run.status == LoopRunStatus.REPAIRING and not self._supervisor_transition(
            run,
            TaskRunStatus.REPAIRING,
        ):
            return self._latest_run(run_id)
        pending_verification = self._pending_verification_attempt(run)
        if pending_verification is not None:
            terminal = self._verify_attempt(
                run_id,
                pending_verification.attempt_index,
                workspace_path,
                cancellation_token=cancellation_token,
            )
            if terminal is not None:
                return terminal
            run = self._latest_run(run_id)
        if self._attempts_exhausted_without_terminal(run):
            run = self._fail_exhausted_after_recovery(run_id)
            return self._finalize_learning(run)
        if cancelled := self._check_for_cancellation(
            run_id,
            cancellation_token=cancellation_token,
        ):
            return cancelled
        max_attempts = run.policy.max_attempts
        for attempt_index in range(len(run.attempts) + 1, max_attempts + 1):
            if cancelled := self._check_for_cancellation(
                run_id,
                cancellation_token=cancellation_token,
            ):
                return cancelled
            run = self.store.mutate(
                run_id,
                lambda current: current.model_copy(
                    update={
                        "status": LoopRunStatus.RUNNING,
                        "last_error": "",
                    }
                ),
            )
            if not self._supervisor_transition(run, TaskRunStatus.RUNNING):
                return self._latest_run(run_id)
            prompt = self._build_attempt_prompt(run)
            attempt = LoopAttempt(
                attempt_index=attempt_index,
                prompt=prompt,
            )
            run = self.store.mutate(
                run_id,
                lambda current, attempt=attempt: current.model_copy(
                    update={"attempts": [*current.attempts, attempt]}
                ),
            )
            try:
                react_result = self._run_attempt(
                    run,
                    prompt,
                    workspace_path,
                    cancellation_token=cancellation_token,
                )
            except Exception as exc:
                if not self._supervisor_heartbeat(run_id):
                    return self._latest_run(run_id)
                error_text = str(exc)
                run = self._record_attempt_exception(run_id, attempt_index, exc)
                if attempt_index >= max_attempts:
                    if not self._supervisor_heartbeat(run_id):
                        return self._latest_run(run_id)
                    run = self.store.mutate(
                        run_id,
                        lambda current, error_text=error_text: current.model_copy(
                            update={
                                "status": LoopRunStatus.FAILED,
                                "completed_at": _now_iso(),
                                "last_error": error_text,
                            }
                        ),
                    )
                    return self._finalize_learning(run)
                run = self.store.mutate(
                    run_id,
                    lambda current, error_text=error_text: current.model_copy(
                        update={
                            "status": LoopRunStatus.REPAIRING,
                            "last_error": error_text,
                        }
                    ),
                )
                if not self._supervisor_transition(run, TaskRunStatus.REPAIRING):
                    return self._latest_run(run_id)
                continue
            if not self._supervisor_heartbeat(run_id):
                return self._latest_run(run_id)
            run = self._record_attempt_result(run_id, attempt_index, react_result)
            if cancelled := self._check_for_cancellation(
                run_id,
                cancellation_token=cancellation_token,
                latest_result=react_result,
            ):
                return cancelled
            terminal = self._verify_attempt(
                run_id,
                attempt_index,
                workspace_path,
                cancellation_token=cancellation_token,
            )
            if terminal is not None:
                return terminal
        final_run = self.store.get(run_id)
        if final_run is None:
            raise KeyError(run_id)
        return final_run

    @staticmethod
    def _ensure_restartable(run: LoopRun) -> None:
        if run.status in {
            LoopRunStatus.PENDING,
            LoopRunStatus.RUNNING,
            LoopRunStatus.VERIFYING,
            LoopRunStatus.REPAIRING,
        }:
            raise ValueError("loop run is still active")

    def _spawn_child_run(
        self,
        source: LoopRun,
        *,
        goal: str | None,
        thread_id: str | None,
        workspace_path: str | None,
        reuse_workspace: bool,
        policy: Any,
        resume_checkpoint_id: str | None,
    ) -> LoopRun:
        next_goal = str(goal or "").strip() or source.goal
        next_thread_id = thread_id if thread_id is not None else source.thread_id
        next_workspace_path = (
            workspace_path
            if workspace_path is not None
            else source.workspace_path
            if reuse_workspace
            else None
        )
        next_policy = (
            policy.model_copy(deep=True)
            if policy is not None
            else source.policy.model_copy(deep=True)
        )
        child = LoopRun(
            owner_id=source.owner_id,
            parent_run_id=source.run_id,
            origin_run_id=source.origin_run_id or source.run_id,
            resume_checkpoint_id=resume_checkpoint_id,
            goal=next_goal,
            mode=source.mode,
            thread_id=next_thread_id,
            workspace_path=next_workspace_path,
            policy=next_policy,
        )
        return self.store.create(child)

    def _recover_interrupted_attempts(self, run_id: str) -> LoopRun:
        run = self.store.get(run_id)
        if run is None:
            raise KeyError(run_id)
        if run.status not in _ACTIVE_LOOP_STATUSES:
            return run
        if not any(
            not attempt.completed_at and str(attempt.status or "") == "running"
            for attempt in run.attempts
        ):
            return run
        return self.store.mutate(run_id, self._recover_interrupted_attempts_for_current)

    def _recover_interrupted_attempts_for_current(self, current: LoopRun) -> LoopRun:
        if current.status not in _ACTIVE_LOOP_STATUSES:
            return current
        reason = "previous loop attempt interrupted before completion"
        recovery_reason = "previous loop attempt recovered from half-written completion"
        recovered = False
        interrupted = False
        attempts: list[LoopAttempt] = []
        for attempt in current.attempts:
            if attempt.completed_at or str(attempt.status or "") != "running":
                attempts.append(attempt)
                continue
            if recovered_status := self._recoverable_attempt_status(attempt):
                recovered = True
                attempts.append(
                    attempt.model_copy(
                        update={
                            "completed_at": attempt.completed_at or _now_iso(),
                            "status": recovered_status,
                            "success": True if recovered_status == "completed" else attempt.success,
                            "terminated_reason": attempt.terminated_reason or recovery_reason,
                            "final_answer": _truncate_text(attempt.final_answer),
                            "error": "",
                        }
                    )
                )
                continue
            interrupted = True
            attempts.append(
                attempt.model_copy(
                    update={
                        "completed_at": attempt.completed_at or _now_iso(),
                        "status": "interrupted",
                        "success": False,
                        "terminated_reason": reason,
                        "error": attempt.error or reason,
                    }
                )
            )
        if not recovered and not interrupted:
            return current
        return current.model_copy(
            update={
                "status": LoopRunStatus.VERIFYING if recovered else LoopRunStatus.REPAIRING,
                "last_error": reason if interrupted and not recovered else "",
                "attempts": attempts,
            }
        )

    @staticmethod
    def _recoverable_attempt_status(attempt: LoopAttempt) -> str | None:
        if attempt.success is True and not str(attempt.error or "").strip():
            return "completed"
        has_completion_snapshot = bool(
            str(attempt.final_answer or "").strip() or attempt.completion_receipt
        )
        if has_completion_snapshot and not str(attempt.error or "").strip():
            return "needs_verify"
        return None

    def _recover_verified_terminal_run(self, run_id: str) -> LoopRun | None:
        run = self.store.get(run_id)
        if run is None:
            raise KeyError(run_id)
        if run.status not in _ACTIVE_LOOP_STATUSES:
            return None
        attempt = self._latest_verified_attempt(run)
        if attempt is None:
            return None
        if attempt.verifier_result is None:
            return None
        should_finalize = False

        def _mutate(current: LoopRun) -> LoopRun:
            nonlocal should_finalize
            if current.status not in _ACTIVE_LOOP_STATUSES:
                return current
            current_attempt = self._latest_verified_attempt(current)
            if current_attempt is None or current_attempt.verifier_result is None:
                return current
            verifier_result = current_attempt.verifier_result
            if verifier_result.passed:
                should_finalize = True
                return current.model_copy(
                    update={
                        "status": LoopRunStatus.COMPLETED,
                        "completed_at": current.completed_at or _now_iso(),
                        "last_error": "",
                        "last_verifier_result": verifier_result,
                    }
                )
            error_text = _verifier_error_text(verifier_result)
            if _verifier_failure_repairable(verifier_result) and (
                current_attempt.attempt_index < current.policy.max_attempts
            ):
                return current.model_copy(
                    update={
                        "status": LoopRunStatus.REPAIRING,
                        "last_error": error_text,
                        "last_verifier_result": verifier_result,
                    }
                )
            should_finalize = True
            return current.model_copy(
                update={
                    "status": LoopRunStatus.FAILED,
                    "completed_at": current.completed_at or _now_iso(),
                    "last_error": error_text,
                    "last_verifier_result": verifier_result,
                }
            )

        recovered = self.store.mutate(run_id, _mutate)
        if should_finalize:
            return self._finalize_learning(recovered)
        return None

    @staticmethod
    def _latest_verified_attempt(run: LoopRun) -> LoopAttempt | None:
        if not run.attempts:
            return None
        attempt = run.attempts[-1]
        return attempt if attempt.verifier_result is not None else None

    @staticmethod
    def _pending_verification_attempt(run: LoopRun) -> LoopAttempt | None:
        if run.status not in {LoopRunStatus.RUNNING, LoopRunStatus.VERIFYING}:
            return None
        for attempt in reversed(run.attempts):
            if attempt.completed_at and attempt.verifier_result is None:
                if attempt.status in {"completed", "needs_verify"}:
                    return attempt
                if attempt.success is True and not attempt.error:
                    return attempt
                return None
        return None

    @staticmethod
    def _attempts_exhausted_without_terminal(run: LoopRun) -> bool:
        if run.status not in _ACTIVE_LOOP_STATUSES:
            return False
        return len(run.attempts) >= run.policy.max_attempts

    def _fail_exhausted_after_recovery(self, run_id: str) -> LoopRun:
        reason = "loop attempts exhausted after recovering interrupted state"
        return self.store.mutate(
            run_id,
            lambda current, reason=reason: current.model_copy(
                update={
                    "status": LoopRunStatus.FAILED,
                    "completed_at": current.completed_at or _now_iso(),
                    "last_error": current.last_error or reason,
                }
            ),
        )

    def _verify_attempt(
        self,
        run_id: str,
        attempt_index: int,
        workspace_path: str,
        *,
        cancellation_token: CancellationToken | None,
    ) -> LoopRun | None:
        run = self.store.mutate(
            run_id,
            lambda current: current.model_copy(update={"status": LoopRunStatus.VERIFYING}),
        )
        if not self._supervisor_transition(run, TaskRunStatus.VERIFYING):
            return self._latest_run(run_id)
        if cancelled := self._check_for_cancellation(
            run_id,
            cancellation_token=cancellation_token,
        ):
            return cancelled
        if not self._supervisor_heartbeat(run_id):
            return self._latest_run(run_id)
        verifier_result = self._run_verifier(run, workspace_path, cancellation_token)
        if not self._supervisor_heartbeat(run_id):
            return self._latest_run(run_id)
        run = self._record_verifier_result(run_id, attempt_index, verifier_result)
        if cancelled := self._check_for_cancellation(
            run_id,
            cancellation_token=cancellation_token,
        ):
            return cancelled
        if verifier_result.passed:
            if not self._supervisor_heartbeat(run_id):
                return self._latest_run(run_id)
            run = self.store.mutate(
                run_id,
                lambda current: current.model_copy(
                    update={
                        "status": LoopRunStatus.COMPLETED,
                        "completed_at": _now_iso(),
                        "last_error": "",
                    }
                ),
            )
            return self._finalize_learning(run)

        error_text = _verifier_error_text(verifier_result)
        if not _verifier_failure_repairable(verifier_result):
            if not self._supervisor_heartbeat(run_id):
                return self._latest_run(run_id)
            run = self.store.mutate(
                run_id,
                lambda current, error_text=error_text: current.model_copy(
                    update={
                        "status": LoopRunStatus.FAILED,
                        "completed_at": _now_iso(),
                        "last_error": error_text,
                    }
                ),
            )
            return self._finalize_learning(run)

        latest = self._latest_run(run_id)
        if attempt_index >= latest.policy.max_attempts:
            if not self._supervisor_heartbeat(run_id):
                return self._latest_run(run_id)
            run = self.store.mutate(
                run_id,
                lambda current, error_text=error_text: current.model_copy(
                    update={
                        "status": LoopRunStatus.FAILED,
                        "completed_at": _now_iso(),
                        "last_error": error_text,
                    }
                ),
            )
            return self._finalize_learning(run)

        run = self.store.mutate(
            run_id,
            lambda current, error_text=error_text: current.model_copy(
                update={
                    "status": LoopRunStatus.REPAIRING,
                    "last_error": error_text,
                }
            ),
        )
        if not self._supervisor_transition(run, TaskRunStatus.REPAIRING):
            return self._latest_run(run_id)
        return None

    def _run_verifier(
        self,
        run: LoopRun,
        workspace_path: str,
        cancellation_token: CancellationToken | None,
    ) -> VerifierResult:
        try:
            with scoped_cancellation(cancellation_token or CancellationToken.none()):
                return self.verifier_registry.run(
                    run.policy.verifier_profile,
                    workspace_path,
                )
        except KeyError:
            profile = str(run.policy.verifier_profile or "").strip() or "<empty>"
            error_text = f"unknown verifier profile: {profile}"
            return VerifierResult(
                profile=profile,
                kind="verifier_error",
                failure_category="verifier_profile_unknown",
                passed=False,
                summary=error_text,
                findings=[
                    VerifierFinding(
                        name="verifier-profile",
                        passed=False,
                        category="verifier_profile_unknown",
                        exit_code=-2,
                        stderr=error_text,
                    )
                ],
            )
        except Exception as exc:
            return VerifierResult(
                profile=run.policy.verifier_profile,
                kind="verifier_error",
                failure_category="verifier_internal_error",
                passed=False,
                summary=str(exc),
                findings=[
                    VerifierFinding(
                        name="verifier-error",
                        passed=False,
                        category="verifier_internal_error",
                        exit_code=-1,
                        stderr=str(exc),
                    )
                ],
            )

    def _task_capabilities_for_run(self, run: LoopRun) -> TaskCapabilityManifest:
        return TaskCapabilityManifest(
            source="loop_policy",
            workspace_paths=[run.workspace_path] if run.workspace_path else [],
            groups={
                "builtin": True,
                "web": True,
                "browser": True,
                "computer": True,
                "fs_write": True,
                "git": True,
                "shell": True,
                "memory": True,
            },
        )

    def _supervisor_start(self, run: LoopRun) -> bool:
        if self.task_supervisor is None:
            return True
        try:
            self.task_supervisor.start_task(
                task_id=run.run_id,
                kind="loop",
                owner_id=run.owner_id,
                thread_id=run.thread_id or run.run_id,
                parent_task_id=run.parent_run_id,
                origin_task_id=run.origin_run_id,
                resume_checkpoint_id=run.resume_checkpoint_id,
                title=run.goal,
                goal=run.goal,
                mode=run.mode.value,
                workspace_path=run.workspace_path,
                capabilities=self._task_capabilities_for_run(run),
                status=self._supervisor_status(run.status),
                metadata={
                    "policy": run.policy.model_dump(mode="json"),
                    "source": "loop_controller",
                },
            )
            return True
        except TaskLeaseConflict as exc:
            _LOG.info("loop task %s is already leased by %s", run.run_id, exc.holder_id)
            return False
        except Exception as exc:  # noqa: BLE001
            _LOG.warning("loop task supervisor start failed for %s: %s", run.run_id, exc)
            return True

    def _supervisor_transition(
        self,
        run: LoopRun,
        status: TaskRunStatus | None = None,
        *,
        checkpoint_id: str | int | None = None,
    ) -> bool:
        if self.task_supervisor is None:
            return True
        try:
            self.task_supervisor.transition(
                run.run_id,
                status or self._supervisor_status(run.status),
                reason=run.cancel_reason or run.last_error,
                checkpoint_id=checkpoint_id,
                metadata_patch={
                    "attempt_count": len(run.attempts),
                    "last_loop_status": run.status.value,
                },
            )
            return True
        except KeyError:
            if not self._supervisor_start(run):
                return False
            try:
                self.task_supervisor.transition(
                    run.run_id,
                    status or self._supervisor_status(run.status),
                    reason=run.cancel_reason or run.last_error,
                    checkpoint_id=checkpoint_id,
                    metadata_patch={
                        "attempt_count": len(run.attempts),
                        "last_loop_status": run.status.value,
                    },
                )
                return True
            except (LostTaskLease, TaskLeaseConflict) as exc:
                _LOG.info("loop task supervisor lease lost for %s: %s", run.run_id, exc)
                return False
            except Exception as exc:  # noqa: BLE001
                _LOG.warning(
                    "loop task supervisor retry transition failed for %s: %s",
                    run.run_id,
                    exc,
                )
                return True
        except LostTaskLease as exc:
            _LOG.info("loop task supervisor lease lost for %s: %s", run.run_id, exc)
            return False
        except Exception as exc:  # noqa: BLE001
            _LOG.warning("loop task supervisor transition failed for %s: %s", run.run_id, exc)
            return True

    def _supervisor_heartbeat(self, run_id: str) -> bool:
        if self.task_supervisor is None:
            return True
        try:
            self.task_supervisor.heartbeat(run_id)
            return True
        except KeyError:
            return True
        except LostTaskLease as exc:
            _LOG.info("loop task supervisor lease lost for %s: %s", run_id, exc)
            return False
        except Exception as exc:  # noqa: BLE001
            _LOG.warning("loop task supervisor heartbeat failed for %s: %s", run_id, exc)
            return True

    def _latest_run(self, run_id: str) -> LoopRun:
        latest = self.store.get(run_id)
        if latest is None:
            raise KeyError(run_id)
        return latest

    @staticmethod
    def _supervisor_status(status: LoopRunStatus) -> TaskRunStatus:
        return {
            LoopRunStatus.PENDING: TaskRunStatus.PENDING,
            LoopRunStatus.RUNNING: TaskRunStatus.RUNNING,
            LoopRunStatus.VERIFYING: TaskRunStatus.VERIFYING,
            LoopRunStatus.REPAIRING: TaskRunStatus.REPAIRING,
            LoopRunStatus.COMPLETED: TaskRunStatus.COMPLETED,
            LoopRunStatus.FAILED: TaskRunStatus.FAILED,
            LoopRunStatus.CANCELLED: TaskRunStatus.CANCELLED,
        }[status]

    def _build_attempt_prompt(self, run: LoopRun) -> str:
        if not run.attempts:
            resume_prompt = self._build_resume_prompt(run)
            return resume_prompt or run.goal
        latest = run.attempts[-1]
        repair = _verifier_feedback(latest.verifier_result)
        if not repair:
            return run.goal
        return f"{run.goal}\n\n{repair}"

    def _build_resume_prompt(self, run: LoopRun) -> str:
        if not run.resume_checkpoint_id or not run.parent_run_id:
            return ""
        source = self.store.get(run.parent_run_id)
        if source is None:
            return ""
        if source.status not in {LoopRunStatus.FAILED, LoopRunStatus.CANCELLED}:
            return ""
        return build_loop_run_resume_prompt(
            source,
            goal=run.goal,
            checkpoint_id=run.resume_checkpoint_id,
        )

    def _record_trace_run_started(self, run: LoopRun) -> None:
        if self.trace_store is None or not run.started_at:
            return
        try:
            existing = self.trace_store.events(
                task_id=run.run_id,
                event_type="TASK_RUN_STARTED",
                limit=1,
            )
            if existing:
                return
            self.trace_store.record_task_run_started(
                task_id=run.run_id,
                thread_id=run.thread_id or run.run_id,
                turn_id=run.run_id,
                agent_id=_TRACE_AGENT_ID,
                title=run.goal,
                goal=run.goal,
                mode=run.mode.value,
                metadata={
                    "workspace_path": run.workspace_path,
                    "parent_run_id": run.parent_run_id,
                    "origin_run_id": run.origin_run_id,
                    "resume_checkpoint_id": run.resume_checkpoint_id,
                },
                ts=run.started_at,
            )
        except Exception as exc:  # noqa: BLE001
            _LOG.warning("loop trace start record failed for %s: %s", run.run_id, exc)

    def _record_trace_terminal_artifacts(self, run: LoopRun) -> int | None:
        if self.trace_store is None:
            return None
        try:
            checkpoint = build_loop_run_checkpoint(run)
            existing_checkpoint_id = self._matching_trace_checkpoint_id(run, checkpoint=checkpoint)
            if existing_checkpoint_id is not None:
                self._ensure_trace_terminal_event(
                    run,
                    checkpoint=checkpoint,
                    checkpoint_id=existing_checkpoint_id,
                )
                return existing_checkpoint_id
            checkpoint_id = self.trace_store.record_checkpoint(
                task_id=run.run_id,
                checkpoint_type=str(checkpoint.get("checkpoint_type") or "loop_run"),
                state=checkpoint.get("state") if isinstance(checkpoint.get("state"), dict) else {},
                thread_id=run.thread_id or run.run_id,
                turn_id=run.run_id,
                agent_id=_TRACE_AGENT_ID,
                iteration=int(checkpoint.get("iteration") or 0),
                summary=str(checkpoint.get("summary") or ""),
                ts=str(checkpoint.get("ts") or "") or None,
            )
            self._ensure_trace_terminal_event(
                run,
                checkpoint=checkpoint,
                checkpoint_id=checkpoint_id,
            )
            return checkpoint_id
        except Exception as exc:  # noqa: BLE001
            _LOG.warning("loop trace terminal record failed for %s: %s", run.run_id, exc)
            return None

    def _matching_trace_checkpoint_id(
        self,
        run: LoopRun,
        *,
        checkpoint: dict[str, Any],
    ) -> int | None:
        if self.trace_store is None:
            return None
        existing = self.trace_store.latest_checkpoint(
            task_id=run.run_id,
            checkpoint_type=str(checkpoint.get("checkpoint_type") or "loop_run"),
        )
        if existing is None:
            return None
        checkpoint_id = existing.get("id")
        if self._terminal_trace_event(run, checkpoint_id=checkpoint_id) is not None:
            try:
                return int(checkpoint_id)
            except (TypeError, ValueError):
                return None
        if int(existing.get("iteration") or 0) != int(checkpoint.get("iteration") or 0):
            return None
        if str(existing.get("summary") or "") != str(checkpoint.get("summary") or ""):
            return None
        state = existing.get("state") if isinstance(existing.get("state"), dict) else {}
        if str(state.get("current_phase") or "") != run.status.value:
            return None
        try:
            return int(checkpoint_id)
        except (TypeError, ValueError):
            return None

    def _ensure_trace_terminal_event(
        self,
        run: LoopRun,
        *,
        checkpoint: dict[str, Any],
        checkpoint_id: int,
    ) -> None:
        if self._terminal_trace_event(run, checkpoint_id=checkpoint_id) is not None:
            return
        if self.trace_store is None:
            return
        self.trace_store.record_task_run_finished(
            task_id=run.run_id,
            status=self._trace_task_status(run.status),
            thread_id=run.thread_id or run.run_id,
            turn_id=run.run_id,
            agent_id=_TRACE_AGENT_ID,
            summary=str(checkpoint.get("summary") or ""),
            reason=run.cancel_reason or run.last_error,
            metadata={
                "checkpoint_id": checkpoint_id,
                "checkpoint_type": str(checkpoint.get("checkpoint_type") or "loop_run"),
                "workspace_path": run.workspace_path,
                "parent_run_id": run.parent_run_id,
                "origin_run_id": run.origin_run_id,
                "resume_checkpoint_id": run.resume_checkpoint_id,
            },
            ts=run.completed_at,
        )

    def _terminal_trace_event(
        self,
        run: LoopRun,
        *,
        checkpoint_id: Any,
    ) -> dict[str, Any] | None:
        if self.trace_store is None:
            return None
        event_type = {
            "completed": "TASK_RUN_COMPLETED",
            "failed": "TASK_RUN_FAILED",
            "cancelled": "TASK_RUN_CANCELLED",
        }.get(self._trace_task_status(run.status), "TASK_RUN_FINISHED")
        for event in self.trace_store.events(
            task_id=run.run_id,
            event_type=event_type,
            limit=20,
        ):
            payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
            metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
            if str(metadata.get("checkpoint_id") or "") == str(checkpoint_id or ""):
                return event
        return None

    @staticmethod
    def _trace_task_status(status: LoopRunStatus) -> str:
        return {
            LoopRunStatus.COMPLETED: "completed",
            LoopRunStatus.FAILED: "failed",
            LoopRunStatus.CANCELLED: "cancelled",
        }.get(status, "unknown")

    @staticmethod
    def _link_trace_checkpoint(review: dict[str, Any], trace_checkpoint_id: int) -> dict[str, Any]:
        payload = dict(review)
        summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
        payload["summary"] = {**summary, "trace_checkpoint_id": trace_checkpoint_id}
        resume = payload.get("resume") if isinstance(payload.get("resume"), dict) else {}
        latest_checkpoint = (
            resume.get("latest_checkpoint")
            if isinstance(resume.get("latest_checkpoint"), dict)
            else {}
        )
        if latest_checkpoint:
            payload["resume"] = {
                **resume,
                "latest_checkpoint": {
                    **latest_checkpoint,
                    "trace_checkpoint_id": trace_checkpoint_id,
                },
            }
        return payload

    def _finalize_learning(self, run: LoopRun) -> LoopRun:
        if not self._supervisor_heartbeat(run.run_id):
            return self._latest_run(run.run_id)
        existing = self._existing_terminal_review(run)
        if existing is not None:
            checkpoint_id = self._review_trace_checkpoint_id(existing.last_review)
            if not self._supervisor_transition(existing, checkpoint_id=checkpoint_id):
                return self._latest_run(run.run_id)
            return existing
        review = build_loop_run_review(run)
        trace_checkpoint_id = self._record_trace_terminal_artifacts(run)
        if trace_checkpoint_id is not None:
            review = self._link_trace_checkpoint(review, trace_checkpoint_id)
        if not self._supervisor_transition(run, checkpoint_id=trace_checkpoint_id):
            return self._latest_run(run.run_id)
        queue_result: dict[str, Any] | None = None
        if self.review_queue is not None and (
            review.get("learning_candidates") or review.get("backlog_candidates")
        ):
            queue_result = self.review_queue.add_from_task_run_review(review)
        return self.store.mutate(
            run.run_id,
            lambda current, review=review, queue_result=queue_result: current.model_copy(
                update={
                    "last_review": review,
                    "last_review_queue_result": queue_result,
                }
            ),
        )

    def _existing_terminal_review(self, run: LoopRun) -> LoopRun | None:
        current = self.store.get(run.run_id)
        if current is None:
            raise KeyError(run.run_id)
        review = current.last_review if isinstance(current.last_review, dict) else None
        if review is None:
            return None
        if str(review.get("status") or "") != run.status.value:
            return None
        if current.status != run.status:
            return None
        return current

    @staticmethod
    def _review_trace_checkpoint_id(review: dict[str, Any] | None) -> int | None:
        if not isinstance(review, dict):
            return None
        summary = review.get("summary") if isinstance(review.get("summary"), dict) else {}
        checkpoint_id = summary.get("trace_checkpoint_id")
        if checkpoint_id is None:
            resume = review.get("resume") if isinstance(review.get("resume"), dict) else {}
            latest = (
                resume.get("latest_checkpoint")
                if isinstance(resume.get("latest_checkpoint"), dict)
                else {}
            )
            checkpoint_id = latest.get("trace_checkpoint_id")
        try:
            return int(checkpoint_id) if checkpoint_id is not None else None
        except (TypeError, ValueError):
            return None

    def _run_attempt(
        self,
        run: LoopRun,
        prompt: str,
        workspace_path: str,
        cancellation_token: CancellationToken | None = None,
    ) -> ReActResult | None:
        if self.stack is None:
            raise RuntimeError("loop controller stack is not available")
        from runtime.core.cerebrum.react_loop import run_react_loop
        from runtime.platform.models import ParsedIntent

        runner = self.react_runner or run_react_loop
        thread_id = run.thread_id or run.run_id
        user_context = {
            "objective": run.goal,
            "workspace_path": workspace_path,
            "mode": run.mode.value,
            "goal_mode": run.policy.goal_mode,
            "completion_policy": "goal" if run.policy.goal_mode else "",
            "budget_auto_pause": run.policy.budget_auto_pause,
            "max_tokens_budget": run.policy.max_tokens_budget,
            "max_usd_budget": run.policy.max_usd_budget,
            "auto_approve": run.policy.auto_approve,
            "thread_id": thread_id,
            "sandbox_mode": run.policy.sandbox_mode,
            "permission_mode": run.policy.permission_mode,
            "execution_environment": run.policy.execution_environment,
        }
        intent = ParsedIntent(
            raw=prompt,
            intent_type="task",
            normalized_goal=prompt,
            user_context=user_context,
        )
        metadata = dict(user_context)
        if self.task_supervisor is not None:
            manifest = self.task_supervisor.task_capabilities(run.run_id)
            if manifest is not None:
                metadata["task_id"] = run.run_id
                metadata["task_capability_manifest"] = manifest.model_dump(mode="json")
            metadata["task_supervisor_store_path"] = str(self.task_supervisor.store.path)
            metadata["task_supervisor_holder_id"] = self.task_supervisor.holder_id
            metadata["task_supervisor_lease_ttl_seconds"] = self.task_supervisor.lease_ttl_seconds
            metadata["enforce_executor_approval"] = True
        with (
            session_scope(
                Session(
                    actor=run.owner_id,
                    thread_id=thread_id,
                    metadata=metadata,
                )
            ),
            scoped_cancellation(cancellation_token or CancellationToken.none()),
        ):
            runner_kwargs = {
                "stack": self.stack,
                "intent": intent,
                "agent": None,
                "model": run.policy.model,
                "max_iterations": run.policy.max_iterations,
                "thread_id": thread_id,
            }
            if self.react_runner is None:
                runner_kwargs.update(
                    {
                        "max_tokens_budget": run.policy.max_tokens_budget,
                        "max_usd_budget": run.policy.max_usd_budget,
                    }
                )
            return runner(
                **runner_kwargs,
            )

    def _check_for_cancellation(
        self,
        run_id: str,
        *,
        cancellation_token: CancellationToken | None = None,
        latest_result: ReActResult | None = None,
    ) -> LoopRun | None:
        run = self.store.get(run_id)
        if run is None:
            raise KeyError(run_id)
        reason = self._cancellation_reason(run, cancellation_token=cancellation_token)
        if latest_result is not None and str(latest_result.terminated_reason or "") == "cancelled":
            reason = reason or str(latest_result.terminated_reason or "").strip() or "cancelled"
        if not reason:
            return None
        return self._cancel_run(run_id, reason)

    @staticmethod
    def _cancellation_reason(
        run: LoopRun,
        *,
        cancellation_token: CancellationToken | None = None,
    ) -> str:
        if cancellation_token is not None and cancellation_token.is_cancelled:
            return str(cancellation_token.reason or "").strip() or "cancelled"
        if run.cancel_requested_at:
            return str(run.cancel_reason or "").strip() or "cancelled"
        return ""

    def _cancel_run(self, run_id: str, reason: str) -> LoopRun:
        cancel_reason = str(reason or "").strip() or "cancelled"
        run = self.store.get(run_id)
        if run is None:
            raise KeyError(run_id)
        if run.status == LoopRunStatus.CANCELLED:
            return run
        if not self._supervisor_heartbeat(run_id):
            return run
        run = self.store.mutate(
            run_id,
            lambda current, cancel_reason=cancel_reason: current.model_copy(
                update={
                    "status": LoopRunStatus.CANCELLED,
                    "completed_at": current.completed_at or _now_iso(),
                    "cancel_requested_at": current.cancel_requested_at or _now_iso(),
                    "cancel_reason": cancel_reason,
                    "last_error": cancel_reason,
                }
            ),
        )
        return self._finalize_learning(run)

    def _record_attempt_exception(
        self,
        run_id: str,
        attempt_index: int,
        exc: Exception,
    ) -> LoopRun:
        return self.store.mutate(
            run_id,
            lambda current: current.model_copy(
                update={
                    "attempts": [
                        attempt.model_copy(
                            update={
                                "completed_at": _now_iso(),
                                "status": "failed",
                                "error": str(exc),
                                "success": False,
                            }
                        )
                        if attempt.attempt_index == attempt_index
                        else attempt
                        for attempt in current.attempts
                    ],
                }
            ),
        )

    def _record_attempt_result(
        self,
        run_id: str,
        attempt_index: int,
        react_result: ReActResult | None,
    ) -> LoopRun:
        final_answer = react_result.final_answer if react_result is not None else ""
        success = react_result.success if react_result is not None else False
        terminated_reason = (
            react_result.terminated_reason if react_result is not None else "runner_returned_none"
        )
        completion_receipt = react_result.completion_receipt if react_result is not None else {}
        return self.store.mutate(
            run_id,
            lambda current: current.model_copy(
                update={
                    "attempts": [
                        attempt.model_copy(
                            update={
                                "completed_at": _now_iso(),
                                "status": (
                                    "cancelled"
                                    if terminated_reason == "cancelled"
                                    else "completed"
                                    if success
                                    else "needs_verify"
                                ),
                                "success": success,
                                "terminated_reason": terminated_reason,
                                "final_answer": _truncate_text(final_answer),
                                "completion_receipt": completion_receipt,
                            }
                        )
                        if attempt.attempt_index == attempt_index
                        else attempt
                        for attempt in current.attempts
                    ],
                }
            ),
        )

    def _record_verifier_result(
        self,
        run_id: str,
        attempt_index: int,
        verifier_result: VerifierResult,
    ) -> LoopRun:
        return self.store.mutate(
            run_id,
            lambda current: current.model_copy(
                update={
                    "last_verifier_result": verifier_result,
                    "attempts": [
                        attempt.model_copy(update={"verifier_result": verifier_result})
                        if attempt.attempt_index == attempt_index
                        else attempt
                        for attempt in current.attempts
                    ],
                }
            ),
        )
