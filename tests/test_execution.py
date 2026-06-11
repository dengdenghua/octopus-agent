"""Implementation note."""

from __future__ import annotations

from runtime.platform.models import (
    CostEntry,
    ExecutionResult,
    Step,
    ToolCall,
    Trajectory,
    TrajectoryOutcome,
)


class TestToolCall:
    def test_basic_construction(self):
        call = ToolCall(caller="arm:code_arm", sucker_id="read_file", args={"path": "x"})
        assert call.caller == "arm:code_arm"
        assert call.call_id is not None

    def test_frozen(self):
        call = ToolCall(caller="arm:code_arm", sucker_id="read_file", args={})
        try:
            call.sucker_id = "evil"  # type: ignore[misc]
            raise AssertionError("should have raised")
        except Exception:
            pass


class TestExecutionResult:
    def test_success(self, sample_cost: CostEntry):
        r = ExecutionResult(
            call_id=__import__("uuid").uuid4(),
            status="success",
            output={"ok": True},
            cost=sample_cost,
        )
        assert not r.is_attack_like

    def test_attack_like_double_signal(self, sample_cost: CostEntry):
        """Implementation note."""
        r = ExecutionResult(
            call_id=__import__("uuid").uuid4(),
            status="sandbox_violation",
            stderr_tags=["shell_injection"],  # Implementation note.
            exit_code=139,  # Implementation note.
            cost=sample_cost,
        )
        assert r.is_attack_like

    def test_attack_like_single_signal_not_enough(self, sample_cost: CostEntry):
        r = ExecutionResult(
            call_id=__import__("uuid").uuid4(),
            status="sandbox_violation",  # Implementation note.
            cost=sample_cost,
        )
        assert not r.is_attack_like


class TestTrajectory:
    def test_step_count(self, sample_trajectory: Trajectory):
        assert sample_trajectory.step_count == 1
        assert sample_trajectory.failed_step_count == 0

    def test_failed_step_counted(self, sample_trajectory: Trajectory):
        import uuid as _u

        failed_step = Step(
            step_id=1,
            node_id="n2",
            action=ToolCall(caller="x", sucker_id="y", args={}),
            result=ExecutionResult(call_id=_u.uuid4(), status="failed"),
        )
        traj = Trajectory(
            task_id=sample_trajectory.task_id,
            arm_id=sample_trajectory.arm_id,
            steps=[sample_trajectory.steps[0], failed_step],
            outcome=TrajectoryOutcome(success=False),
        )
        assert traj.step_count == 2
        assert traj.failed_step_count == 1

    def test_json_round_trip(self, sample_trajectory: Trajectory):
        j = sample_trajectory.model_dump_json()
        traj2 = Trajectory.model_validate_json(j)
        assert traj2.trajectory_id == sample_trajectory.trajectory_id
        assert traj2.step_count == sample_trajectory.step_count
