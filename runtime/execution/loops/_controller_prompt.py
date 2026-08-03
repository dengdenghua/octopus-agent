from __future__ import annotations

from typing import Any

from runtime.execution.loops._controller_helpers import _verifier_feedback
from runtime.execution.loops.learning import build_loop_run_review
from runtime.execution.loops.models import LoopRun, LoopRunStatus
from runtime.execution.loops.recovery import build_loop_run_resume_prompt


class LoopControllerPromptMixin:
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
