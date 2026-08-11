"""Environment-aware guard gating: execution_degraded signal + downgrade.

The guard system's hard/repair/advisory tiers assume tools can run. When
the execution environment is degraded (sandbox / network / OS-permission
blocks), run-based evidence guards — which demand EXECUTED test/typecheck
evidence — can never be satisfied, so the loop was three-striking turns
whose demanded evidence physically cannot exist. These tests pin the cure:

* a live trajectory signal (≥2 environmental failures) drives repair→
  advisory downgrade for run-evidence guards (language / path /
  signature-typecheck / code-mode "no verification run" branch), while
* HARD-tier guards (secret-leak …) and read/write-based guards
  (test-coverage, wire-schema, dependency-declaration, todo-protocol)
  keep vetoing regardless of execution health.
"""

from __future__ import annotations

from runtime.core.cerebrum import env_health
from runtime.core.cerebrum.react_final_answer_guards import (
    _evaluate_final_answer_guards,
    _trajectory_execution_degraded,
)
from runtime.core.cerebrum.react_guards import (
    _EXECUTION_EVIDENCE_GUARDS,
    GuardContext,
    GuardSpec,
    _guard_effectively_advisory,
    evaluate_guards,
    guard_disposition,
)
from runtime.core.cerebrum.react_in_flight_nudges import _apply_in_flight_nudges
from runtime.core.cerebrum.react_types import ReActStep

# An observation exactly as the dispatcher renders an environment-blocked
# exec (sandbox-exec EPERM): the marker the detector matches on.
_ENV_FAIL = (
    "(工具执行异常) PermissionError: [Errno 1] Operation not permitted "
    "(sandbox-exec: sandbox_apply)"
)

_WRITE_PY = 'edit_file({"path": "runtime/foo.py", "old_string": "x", "new_string": "y"})'


def _step(
    iteration: int,
    *,
    thought: str = "",
    action: str = "",
    observation: str = "",
) -> ReActStep:
    return ReActStep(
        iteration=iteration,
        thought=thought,
        action=action,
        observation=observation,
        actions=[action] if action else [],
    )


class TestTrajectoryExecutionDegraded:
    def test_single_env_failure_is_transient_not_degraded(self) -> None:
        steps = [
            _step(1, action='exec_shell({"cmd": "make test"})', observation=_ENV_FAIL),
        ]
        assert not _trajectory_execution_degraded(steps)

    def test_two_env_failures_is_degraded(self) -> None:
        steps = [
            _step(1, action='exec_shell({"cmd": "make test"})', observation=_ENV_FAIL),
            _step(2, action='exec_shell({"cmd": "make test"})', observation=_ENV_FAIL),
        ]
        assert _trajectory_execution_degraded(steps)

    def test_empty_trajectory_not_degraded(self) -> None:
        assert not _trajectory_execution_degraded([])

    def test_logic_failures_do_not_mark_degraded(self) -> None:
        # A tool FAILED because of a test assertion / compile error the model
        # can fix — not environmental, must not count.
        steps = [
            _step(
                1,
                action='run_tests({"cmd": "pytest"})',
                observation="(工具失败) status=test_failed error=assertion_error",
            ),
        ]
        assert not _trajectory_execution_degraded(steps)


class TestDowngradeInEvaluateGuards:
    def test_run_evidence_guard_blocks_when_env_healthy(self) -> None:
        ctx = GuardContext(
            steps=[_step(1, action=_WRITE_PY)],
            final_answer="done",
            is_code_mode=True,
        )
        hit = evaluate_guards(ctx)
        assert hit is not None
        assert hit[0] in _EXECUTION_EVIDENCE_GUARDS

    def test_run_evidence_guard_downgraded_when_env_degraded(self) -> None:
        ctx = GuardContext(
            steps=[_step(1, action=_WRITE_PY)],
            final_answer="done",
            is_code_mode=True,
            execution_degraded=True,
        )
        # No run-evidence veto; no other guard fires for this trajectory.
        assert evaluate_guards(ctx) is None

    def test_hard_guard_survives_degradation(self) -> None:
        sk = "sk-abcdefghijklmnopqrstuvwxyz1234567890"
        action = (
            'edit_file({"path": "runtime/foo.py", '
            '"old_string": "x = 1", '
            '"new_string": "print(x)\\nAPI_KEY = \\"' + sk + '\\""})'
        )
        ctx = GuardContext(
            steps=[_step(1, action=action)],
            final_answer="done",
            is_code_mode=True,
            execution_degraded=True,
        )
        hit = evaluate_guards(ctx)
        assert hit is not None
        assert hit[0] == "secret-leak guard"
        assert guard_disposition(hit[0], "security") == "hard"

    def test_todo_contract_still_enforced_when_degraded(self) -> None:
        # code-mode guard's checklist branch is a file/state contract and
        # must NOT be waived by a degraded environment.
        steps = [
            _step(1, action=_WRITE_PY),
            _step(2, action='read_file({"path": "runtime/foo.py"})', observation="y"),
            _step(3, action='read_file({"path": "runtime/foo.py"})', observation="y"),
        ]
        ctx = GuardContext(
            steps=steps,
            final_answer="done",
            is_code_mode=True,
            todo_protocol_required=True,
            execution_degraded=True,
        )
        hit = evaluate_guards(ctx)
        assert hit is not None
        assert hit[0] == "code-mode guard"
        assert "no todo_write checklist" in hit[1]

    def test_write_based_guards_not_in_eviction_set(self) -> None:
        # Guards whose evidence contract is satisfied by WRITING a file
        # (test / contract test / dep manifest / checklist) stay enforceable
        # even when exec is blocked — the model can still write them.
        for label in (
            "test-coverage guard",
            "wire-schema guard",
            "dependency-declaration guard",
            "todo-protocol guard",
        ):
            assert label not in _EXECUTION_EVIDENCE_GUARDS


class TestEffectivelyAdvisory:
    def _spec(self, label: str, category: str) -> GuardSpec:
        return GuardSpec(label, category, lambda _ctx: None)

    def test_run_evidence_downgraded_only_when_degraded(self) -> None:
        healthy = GuardContext(
            steps=[], final_answer="", is_code_mode=True, execution_degraded=False
        )
        degraded = GuardContext(
            steps=[], final_answer="", is_code_mode=True, execution_degraded=True
        )
        spec = self._spec("path-verification guard", "verification")
        assert not _guard_effectively_advisory(healthy, spec)
        assert _guard_effectively_advisory(degraded, spec)

    def test_hard_guard_never_downgraded(self) -> None:
        degraded = GuardContext(
            steps=[], final_answer="", is_code_mode=True, execution_degraded=True
        )
        spec = self._spec("secret-leak guard", "security")
        assert not _guard_effectively_advisory(degraded, spec)

    def test_write_based_verification_guard_never_downgraded(self) -> None:
        degraded = GuardContext(
            steps=[], final_answer="", is_code_mode=True, execution_degraded=True
        )
        spec = self._spec("test-coverage guard", "verification")
        assert not _guard_effectively_advisory(degraded, spec)

    def test_inherently_advisory_stays_advisory(self) -> None:
        healthy = GuardContext(
            steps=[], final_answer="", is_code_mode=True, execution_degraded=False
        )
        spec = self._spec("long-function guard", "code-smell")
        assert _guard_effectively_advisory(healthy, spec)


class TestWireThroughEvaluateFinalAnswer:
    def test_loop_level_auto_downgrade_on_env_failures(self) -> None:
        # The REAL production path: steps contain two environmental exec
        # failures, so _evaluate_final_answer_guards computes
        # execution_degraded itself and the run-evidence veto disappears.
        steps = [
            _step(1, action=_WRITE_PY),
            _step(2, action='exec_shell({"cmd": "make test"})', observation=_ENV_FAIL),
            _step(3, action='exec_shell({"cmd": "make test"})', observation=_ENV_FAIL),
        ]
        final_step = _step(4, thought="wrap up", action="final_answer")
        hit = _evaluate_final_answer_guards(
            steps=steps,
            step=final_step,
            final_answer="done",
            is_code_mode=True,
            todo_protocol_required=False,
            todo_protocol_visible=True,
            file_inspection_tools_visible=True,
            tools_active=True,
            goal="",
        )
        assert hit is None

    def test_loop_level_keeps_run_evidence_when_healthy(self) -> None:
        # Same trajectory minus the environmental failures: the run-evidence
        # guard fires as usual.
        steps = [_step(1, action=_WRITE_PY)]
        final_step = _step(2, thought="wrap up", action="final_answer")
        hit = _evaluate_final_answer_guards(
            steps=steps,
            step=final_step,
            final_answer="done",
            is_code_mode=True,
            todo_protocol_required=False,
            todo_protocol_visible=True,
            file_inspection_tools_visible=True,
            tools_active=True,
            goal="",
        )
        assert hit is not None
        assert hit[0] in _EXECUTION_EVIDENCE_GUARDS


class TestEnvDegradationNudge:
    """Round-early guidance: after the first environmental failure, tell the
    model once to pivot to static evidence (never re-fire)."""

    def _apply(self, *, step, env_degradation_signaled: bool) -> bool:
        flags = _apply_in_flight_nudges(
            steps=[],
            step=step,
            i=1,
            known_background_tasks={},
            todo_protocol_required=False,
            todo_protocol_visible=False,
            is_code_mode=True,
            messages=[],
            effective_model="opus",
            context_pressure_signaled=False,
            green_verification_convergence_active=False,
            force_convergence_next=False,
            env_degradation_signaled=env_degradation_signaled,
        )
        return flags.env_degradation_signaled

    def test_first_env_failure_injects_nudge(self) -> None:
        step = _step(1, action='exec_shell({"cmd": "make test"})', observation=_ENV_FAIL)
        assert self._apply(step=step, env_degradation_signaled=False) is True
        assert "[environment-degraded]" in step.observation
        assert "dynamic verification" in step.observation

    def test_already_signaled_does_not_refire(self) -> None:
        step = _step(1, action='exec_shell({"cmd": "make test"})', observation=_ENV_FAIL)
        obs_before = step.observation
        assert self._apply(step=step, env_degradation_signaled=True) is True
        # No new nudge text appended to the observation.
        assert step.observation == obs_before

    def test_clean_step_injects_nothing(self) -> None:
        step = _step(1, action='exec_shell({"cmd": "echo ok"})', observation="ok")
        assert self._apply(step=step, env_degradation_signaled=False) is False
        assert "[environment-degraded]" not in (step.observation or "")

    def test_logic_failure_injects_nothing(self) -> None:
        # A failed test assertion is a fixable logic error, not an
        # environment block — the model should keep working, not pivot.
        step = _step(
            1,
            action='run_tests({"cmd": "pytest"})',
            observation="(工具失败) status=test_failed error=assertion_error",
        )
        assert self._apply(step=step, env_degradation_signaled=False) is False
        assert "[environment-degraded]" not in (step.observation or "")


class TestStartupCanary:
    """Startup probe: a serve that boots into a blocked environment knows it
    is degraded immediately — no need to burn two failed tool calls."""

    def test_unknown_canary_falls_back_to_trajectory(self, monkeypatch) -> None:
        # Canary never probed (None) → trajectory threshold still decides.
        monkeypatch.setattr(env_health, "_CANARY_DEGRADED", None)
        steps = [_step(1, action="exec_shell", observation=_ENV_FAIL)]
        assert not _trajectory_execution_degraded(steps)  # only 1 failure
        steps.append(_step(2, action="exec_shell", observation=_ENV_FAIL))
        assert _trajectory_execution_degraded(steps)  # ≥2

    def test_degraded_canary_short_circuits_empty_trajectory(self, monkeypatch) -> None:
        monkeypatch.setattr(env_health, "_CANARY_DEGRADED", True)
        # Even with zero steps, a degraded canary means execution is blocked.
        assert _trajectory_execution_degraded([])

    def test_healthy_canary_does_not_force_degradation(self, monkeypatch) -> None:
        monkeypatch.setattr(env_health, "_CANARY_DEGRADED", False)
        assert not _trajectory_execution_degraded([])

    def test_probe_does_not_raise_on_normal_host(self) -> None:
        # The harmless echo runs (or the probe swallows its own failure) —
        # the contract is "never raises", not a specific verdict.
        assert isinstance(env_health.probe_execution_health(), bool)

    def test_run_startup_canary_records_result(self, monkeypatch) -> None:
        monkeypatch.setattr(env_health, "_CANARY_DEGRADED", None)
        env_health.run_startup_canary()
        # After a real probe the recorded cell is a bool (probe returned one).
        assert env_health.execution_canary() in (True, False)
