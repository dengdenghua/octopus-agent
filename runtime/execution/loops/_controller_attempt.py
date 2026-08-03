from __future__ import annotations

from runtime.core.cerebrum.react_types import ReActResult
from runtime.execution.loops._controller_helpers import (
    _PRODUCT_LOOP_MODES,
    _loop_mode_contract,
    _now_iso,
    _truncate_text,
)
from runtime.execution.loops.models import (
    LoopMode,
    LoopRun,
    LoopRunStatus,
    VerifierResult,
)
from runtime.platform.process.session import Session, session_scope
from runtime.safety.approval.cancellation import CancellationToken, scoped_cancellation


class LoopControllerAttemptMixin:
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
            "codex_mode": run.mode.value if run.mode in _PRODUCT_LOOP_MODES else "",
            "goal_mode": run.policy.goal_mode or run.mode == LoopMode.GOAL,
            "completion_policy": (
                "goal"
                if run.policy.goal_mode or run.mode == LoopMode.GOAL
                else run.mode.value
                if run.mode in {LoopMode.PLAN, LoopMode.SPEC}
                else ""
            ),
            "mode_preset": (
                f"codex.{run.mode.value}" if run.mode in _PRODUCT_LOOP_MODES else run.mode.value
            ),
            "workflow_preset": (
                f"codex.{run.mode.value}" if run.mode in _PRODUCT_LOOP_MODES else ""
            ),
            "mode_contract": _loop_mode_contract(run.mode),
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
