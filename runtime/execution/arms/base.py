
from __future__ import annotations

from typing import Any

from runtime.adapters.instrumentation import trace_stage
from runtime.core.graph_runtime import GraphRuntime
from runtime.platform.models import (
    ArmAssignment,
    ArmId,
    ArmResult,
    ArmResultStatus,
    Budget,
    CostEntry,
    SkillId,
)

# ═══════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════


class Worker:

    def __init__(
        self,
        arm_id: ArmId,
        affinity: list[str],
        allowed_skills: list[SkillId],
        runtime: GraphRuntime,
        *,
        display_name: str = "",
        description: str = "",
        soul: str = "",
        icon: str = "",
    ) -> None:
        self.arm_id: ArmId = arm_id
        self.affinity: list[str] = list(affinity)
        self.allowed_skills: list[SkillId] = list(allowed_skills)
        self.runtime: GraphRuntime = runtime
        self.display_name: str = display_name or str(arm_id)
        self.description: str = description
        self.soul: str = soul
        self.icon: str = icon


    def can_use(self, skill_ref: Any) -> bool:
        from runtime.execution.suckers.layers import is_atomic

        if skill_ref is None:
            return True
        if is_atomic(skill_ref):
            return True
        allowed = {str(skill) for skill in self.allowed_skills}
        if "*" in allowed:
            return True
        return str(skill_ref) in allowed

    def can_handle(self, task: ArmAssignment) -> bool:
        for node in task.subgraph.nodes:
            if node.skill_ref is None:
                continue
            if not self.can_use(node.skill_ref):
                return False
        return True


    def handle(self, task: ArmAssignment, budget: Budget) -> ArmResult:
        with trace_stage(
            "arm.handle",
            arm_id=str(self.arm_id),
            task_id=str(task.subgraph.task_id),
        ) as span:
            span.set_attribute("octopus.arm.affinity_count", len(self.affinity))
            span.set_attribute("octopus.arm.subgraph_nodes", len(task.subgraph.nodes))

            if not self.can_handle(task):
                span.set_attribute("octopus.arm.rejected", True)
                return ArmResult(
                    arm_id=self.arm_id,
                    task_id=task.subgraph.task_id,
                    status="failed",
                    reason="skill_ref not in allowed_skills",
                )

            try:
                trajectory = self.runtime.run(
                    task.subgraph,
                    budget=budget,
                    caller=f"arms/{self.arm_id}",
                    arm_id=self.arm_id,
                )
            except Exception as e:  # noqa: BLE001
                span.record_exception(e)
                return ArmResult(
                    arm_id=self.arm_id,
                    task_id=task.subgraph.task_id,
                    status="failed",
                    reason=f"{type(e).__name__}: {e}",
                )

            status = _status_from_trajectory(trajectory)
            total_cost = _sum_cost(trajectory.steps)

            span.set_attribute("octopus.arm.status", status)
            span.set_attribute("octopus.arm.steps_run", len(trajectory.steps))

            outputs: dict[str, object] = {}
            for step in trajectory.steps:
                if step.success:
                    outputs[step.node_id] = step.result.output

            reason = ""
            if status != "success":
                for step in trajectory.steps:
                    if not step.success:
                        reason = (
                            f"step {step.step_id} ({step.node_id}) "
                            f"{step.result.status}"
                            + (f": {step.result.error_type}" if step.result.error_type else "")
                        )
                        break
                if not reason and len(trajectory.steps) < len(task.subgraph.nodes):
                    reason = "pipeline halted before all nodes ran"

            return ArmResult(
                arm_id=self.arm_id,
                task_id=task.subgraph.task_id,
                status=status,
                outputs=outputs,
                trajectory_id=trajectory.trajectory_id,
                cost=total_cost,
                reason=reason,
                # Carry steps so SwarmRuntime can aggregate them into
                # a full-task Trajectory. Without this, a per_node
                # split produces N separate 1-step Trajectories, each
                # below SkillForge's ``step_count >= 2`` gate, and
                # multi-step patterns are never learned from parallel
                # swarm execution. See
                # tests/test_swarm_to_skill_forge_integration.py.
                steps=list(trajectory.steps),
            )

    # ─── Dunder ────────────────────────────────────────

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return (
            f"Worker(arm_id={self.arm_id!r}, "
            f"affinity={self.affinity!r}, "
            f"skills={len(self.allowed_skills)})"
        )


# ═══════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════


class ArmPool:

    def __init__(self, arms: list[Worker]) -> None:
        self._arms: list[Worker] = list(arms)


    def add(self, arm: Worker) -> None:
        self._arms.append(arm)

    def all_arms(self) -> list[Worker]:
        return list(self._arms)

    def __len__(self) -> int:
        return len(self._arms)

    def __iter__(self):
        return iter(self._arms)


    def pick_for(self, task: ArmAssignment) -> Worker | None:
        needed = {
            node.skill_ref
            for node in task.subgraph.nodes
            if node.skill_ref is not None
        }

        candidates: list[tuple[int, int, int, Worker]] = []
        for idx, arm in enumerate(self._arms):
            if not arm.can_handle(task):
                continue
            allow = {str(skill) for skill in arm.allowed_skills}
            from runtime.execution.suckers.layers import is_atomic
            non_atomic_needed = {str(s) for s in needed if not is_atomic(s)}
            coverage = (
                len(non_atomic_needed)
                if "*" in allow
                else len(non_atomic_needed & allow)
            )
            candidates.append((coverage, len(arm.affinity), -idx, arm))

        if not candidates:
            return None
        candidates.sort(key=lambda t: (t[0], t[1], t[2]), reverse=True)
        return candidates[0][3]

    def pick_for_intent(self, intent: Any) -> Worker | None:
        goal = ""
        intent_type = ""
        for attr in ("normalized_goal", "raw"):
            v = getattr(intent, attr, None)
            if isinstance(v, str) and v:
                goal = v.lower()
                break
        itype = getattr(intent, "intent_type", None)
        if isinstance(itype, str):
            intent_type = itype.lower()

        if not goal and not intent_type:
            return None

        haystack = f"{goal} {intent_type}".lower()

        scored: list[tuple[int, int, int, Worker]] = []
        for idx, arm in enumerate(self._arms):
            score = sum(
                1 for tag in arm.affinity
                if isinstance(tag, str) and tag.lower() in haystack
            )
            if score > 0:
                scored.append((score, len(arm.affinity), -idx, arm))

        if not scored:
            return None
        scored.sort(key=lambda t: (t[0], t[1], t[2]), reverse=True)
        return scored[0][3]


# ═══════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════


def _status_from_trajectory(trajectory) -> ArmResultStatus:
    if trajectory.outcome.success:
        return "success"
    statuses = [s.result.status for s in trajectory.steps]
    if "immune_reject" in statuses:
        return "immune_reject"
    if "circuit_broken" in statuses:
        return "circuit_broken"
    has_success = any(s.success for s in trajectory.steps)
    if has_success:
        return "partial"
    return "failed"


def _sum_cost(steps) -> CostEntry:
    total = CostEntry()
    for step in steps:
        total = total + step.result.cost
    return total
