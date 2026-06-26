from __future__ import annotations

import subprocess
import sys
import time

from runtime.execution.loops.models import (
    LoopAttempt,
    LoopRun,
    LoopRunStatus,
    VerifierFinding,
    VerifierResult,
)
from runtime.execution.loops.store import LoopRunStore
from runtime.execution.loops.verifiers import (
    _classify_finding,
    build_default_loop_verifier_registry,
)
from runtime.platform.io.atomic import _cross_process_lock


def test_loop_store_create_get_filter_and_mutate(tmp_path) -> None:
    store = LoopRunStore(tmp_path / "loop_runs.json")
    execution_policy = {
        "schema": "octopus.execution_policy.v1",
        "sandbox_requested": True,
        "workspace": str(tmp_path),
        "cwd": str(tmp_path),
        "backend": "seatbelt",
        "hard": True,
        "allow_network": False,
        "env_mode": "allowlist",
        "process_group": True,
        "process_tree_kill": True,
        "timeout_s": 60,
    }
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
                            execution_policy=execution_policy,
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
    assert fetched.last_verifier_result.findings[0].execution_policy == execution_policy
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


def test_loop_store_write_lock_serializes_cross_process_writers(tmp_path) -> None:
    path = tmp_path / "loop_runs.json"
    started = tmp_path / "child-started"
    done = tmp_path / "child-done"
    script = f"""
from pathlib import Path
from runtime.execution.loops.models import LoopRun
from runtime.execution.loops.store import LoopRunStore

Path({str(started)!r}).write_text("started", encoding="utf-8")
LoopRunStore({str(path)!r}).create(LoopRun(run_id="child-run", goal="child write"))
Path({str(done)!r}).write_text("done", encoding="utf-8")
"""

    with _cross_process_lock(path.parent / f"{path.name}.rw"):
        child = subprocess.Popen([sys.executable, "-c", script])
        deadline = time.monotonic() + 5
        while not started.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert started.exists()
        time.sleep(0.2)
        assert done.exists() is False
        assert child.poll() is None

    child.wait(timeout=5)
    assert child.returncode == 0
    assert done.exists()
    assert LoopRunStore(path).get("child-run") is not None


def test_default_loop_verifier_registry_exposes_auto_and_legacy_profiles() -> None:
    registry = build_default_loop_verifier_registry()

    for profile in {
        "auto",
        "python_repo_patch",
        "python",
        "node",
        "node-ts",
        "rust",
        "go",
        "unknown",
    }:
        assert profile in registry._handlers


def test_loop_verifier_classifies_failures_for_repair_policy() -> None:
    assert (
        _classify_finding(
            name="typecheck",
            command="npx --no-install tsc --noEmit",
            exit_code=-3,
            stdout="",
            stderr="executable not found: npx",
        )
        == "environment_missing_tool"
    )
    assert (
        _classify_finding(
            name="typecheck",
            command="python -m mypy .",
            exit_code=1,
            stdout="",
            stderr="/usr/bin/python: No module named mypy",
        )
        == "environment_missing_dependency"
    )
    assert (
        _classify_finding(
            name="test",
            command="python -m pytest -q",
            exit_code=1,
            stdout="",
            stderr="AssertionError: expected 200 got 500",
        )
        == "test_failure"
    )
    assert (
        _classify_finding(
            name="package-json",
            command='python -c "parse package.json"',
            exit_code=2,
            stdout="",
            stderr="package.json: invalid JSON: Expecting property name",
        )
        == "project_manifest_error"
    )
    assert (
        _classify_finding(
            name="package-json",
            command='python -c "parse package.json"',
            exit_code=-1,
            stdout="",
            stderr="timeout",
        )
        == "verification_timeout"
    )
    assert (
        _classify_finding(
            name="slow",
            command="tool",
            exit_code=-5,
            stdout="partial output",
            stderr="cancelled",
        )
        == "verification_cancelled"
    )
    assert (
        _classify_finding(
            name="cwd",
            command="python -c cwd",
            exit_code=-4,
            stdout="",
            stderr="sandbox_violation: cwd escapes workspace",
        )
        == "verifier_sandbox_violation"
    )
    assert (
        _classify_finding(
            name="odd",
            command="tool",
            exit_code=-6,
            stdout="",
            stderr="verifier runner returned no exit_code",
        )
        == "verifier_internal_error"
    )
