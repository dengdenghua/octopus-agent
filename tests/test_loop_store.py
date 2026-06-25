from __future__ import annotations

from runtime.execution.loops.models import (
    LoopAttempt,
    LoopRun,
    LoopRunStatus,
    VerifierFinding,
    VerifierResult,
)
from runtime.execution.loops.store import LoopRunStore


def test_loop_store_create_get_filter_and_mutate(tmp_path) -> None:
    store = LoopRunStore(tmp_path / "loop_runs.json")
    alice = LoopRun(
        owner_id="alice",
        parent_run_id=" parent-1 ",
        origin_run_id=" origin-1 ",
        resume_checkpoint_id=" checkpoint-1 ",
        goal="fix auth flow",
        thread_id=" th-alice ",
    )
    bob = LoopRun(owner_id="bob", goal="refactor worker", thread_id="th-bob")

    store.create(alice)
    store.create(bob)

    updated = store.mutate(
        alice.run_id,
        lambda current: current.model_copy(
            update={
                "status": LoopRunStatus.VERIFYING,
                "attempts": [
                    LoopAttempt(
                        attempt_index=1,
                        prompt=current.goal,
                        success=False,
                        status="needs_verify",
                    )
                ],
                "last_verifier_result": VerifierResult(
                    profile="python_repo_patch",
                    kind="python",
                    passed=False,
                    findings=[
                        VerifierFinding(
                            name="syntax",
                            passed=False,
                            exit_code=1,
                            stderr="SyntaxError: bad indent",
                        )
                    ],
                    summary="failed checks: syntax",
                ),
            }
        ),
    )

    fetched = store.get(alice.run_id)
    assert fetched is not None
    assert fetched.status == LoopRunStatus.VERIFYING
    assert fetched.last_verifier_result is not None
    assert fetched.last_verifier_result.findings[0].name == "syntax"
    assert fetched.parent_run_id == "parent-1"
    assert fetched.origin_run_id == "origin-1"
    assert fetched.resume_checkpoint_id == "checkpoint-1"
    assert fetched.thread_id == "th-alice"
    assert fetched.attempts[0].prompt == "fix auth flow"
    assert fetched.updated_at != alice.updated_at
    assert updated.updated_at == fetched.updated_at

    alice_only = store.list(owner_id="alice")
    assert [run.run_id for run in alice_only] == [alice.run_id]
    assert store.count(owner_id="alice") == 1
    assert store.count(status="verifying") == 1
    assert store.list(status="verifying")[0].run_id == alice.run_id
