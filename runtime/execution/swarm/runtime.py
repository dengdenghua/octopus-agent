
from __future__ import annotations

import contextlib
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from runtime.adapters.instrumentation import trace_stage
from runtime.core.cerebrum.completion_receipt import build_completion_receipt
from runtime.execution.misc.multiagent_contracts import validate_work_plan
from runtime.memory.journal import Journal
from runtime.platform.models import (
    ArmAssignment,
    ArmId,
    ArmResult,
    Budget,
    ContextPacketRef,
    TaskGraph,
    TaskId,
    Trajectory,
    TrajectoryOutcome,
    new_id,
    now_utc,
)

if TYPE_CHECKING:
    from runtime.execution.arms.base import ArmPool, Worker
    from runtime.safety.chromatophores.boids import BoidsArbitrator
    from runtime.safety.chromatophores.signal_bus import SignalBus


# ═══════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════

SplitStrategy = Literal["per_node", "single", "topo_layers"]


SwarmEventLane = Literal["workflow", "agent", "timeline"]


class WorkContract(BaseModel):

    model_config = ConfigDict(frozen=True)

    contract_id: str
    agent_id: str
    role: str
    node_ids: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    owned_scope: list[str] = Field(default_factory=list)
    forbidden_scope: list[str] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)


class SwarmPhase(BaseModel):

    model_config = ConfigDict(frozen=True)

    phase_index: int = Field(ge=0)
    assignment_ids: list[str] = Field(default_factory=list)
    node_ids: list[str] = Field(default_factory=list)
    parallel: bool = False


class SwarmPlan(BaseModel):

    model_config = ConfigDict(frozen=True)

    task_id: TaskId
    strategy: SplitStrategy
    max_workers: int = Field(ge=1)
    phases: list[SwarmPhase] = Field(default_factory=list)
    contracts: list[WorkContract] = Field(default_factory=list)
    validation_issues: list[str] = Field(default_factory=list)
    validation_warnings: list[str] = Field(default_factory=list)


class SwarmEvent(BaseModel):

    model_config = ConfigDict(frozen=True)

    type: str
    lane: SwarmEventLane
    task_id: TaskId | None = None
    phase_index: int | None = Field(default=None, ge=0)
    agent_id: str | None = None
    node_ids: list[str] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)
    ts: datetime = Field(default_factory=now_utc)


class AgentHandoff(BaseModel):

    model_config = ConfigDict(frozen=True)

    agent_id: str
    task_id: TaskId
    phase_index: int = Field(ge=0)
    node_ids: list[str] = Field(default_factory=list)
    status: str
    summary: str = ""
    artifacts: list[str] = Field(default_factory=list)
    cost_usd: float = Field(default=0.0, ge=0.0)
    reason: str = ""


class SwarmPhaseReport(BaseModel):

    model_config = ConfigDict(frozen=True)

    phase_index: int = Field(ge=0)
    node_ids: list[str] = Field(default_factory=list)
    assignment_count: int = Field(default=0, ge=0)
    handoff_count: int = Field(default=0, ge=0)
    succeeded: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)
    status: Literal["success", "partial", "failed", "empty"] = "empty"
    wall_ms: float = Field(default=0.0, ge=0.0)
    cost_usd: float = Field(default=0.0, ge=0.0)


class SwarmResult(BaseModel):

    model_config = ConfigDict(frozen=True)

    task_id: TaskId
    arm_results: list[ArmResult] = Field(default_factory=list)
    parallelism_achieved: int = Field(default=0, ge=0)
    total_wall_ms: float = Field(default=0.0, ge=0.0)
    total_cost_usd: float = Field(default=0.0, ge=0.0)
    all_successful: bool = False
    plan: SwarmPlan | None = None
    events: list[SwarmEvent] = Field(default_factory=list)
    handoffs: list[AgentHandoff] = Field(default_factory=list)
    phase_reports: list[SwarmPhaseReport] = Field(default_factory=list)
    contract_validation_issues: list[str] = Field(default_factory=list)
    contract_validation_warnings: list[str] = Field(default_factory=list)
    completion_receipt: dict[str, Any] = Field(default_factory=dict)


@dataclass(frozen=True)
class _PreparedLayer:
    phase: SwarmPhase
    pairs: list[tuple[ArmAssignment, Worker]]
    unmatched: list[tuple[ArmAssignment, ArmResult]]


# ═══════════════════════════════════════════════════════════
# SwarmRuntime
# ═══════════════════════════════════════════════════════════


_DEFAULT_MAX_WORKERS = 4


class SwarmRuntime:

    def __init__(
        self,
        arm_pool: ArmPool,
        signal_bus: SignalBus | None = None,
        boids: BoidsArbitrator | None = None,
        journal: Journal | None = None,
        max_workers: int = _DEFAULT_MAX_WORKERS,
    ) -> None:
        if max_workers < 1:
            raise ValueError(f"max_workers must be >= 1, got {max_workers}")
        self._arm_pool = arm_pool
        self._signal_bus = signal_bus
        self._boids = boids
        self._journal = journal
        self._max_workers = max_workers


    def run(
        self,
        graph: TaskGraph,
        budget: Budget,
        *,
        split_strategy: SplitStrategy = "per_node",
    ) -> SwarmResult:
        with trace_stage(
            "swarm.run",
            task_id=str(graph.task_id),
        ) as span:
            span.set_attribute("octopus.swarm.strategy", split_strategy)
            span.set_attribute("octopus.swarm.max_workers", self._max_workers)

            layers = self._split_layers(graph, split_strategy)
            total_assignments = sum(len(lyr) for lyr in layers)
            span.set_attribute("octopus.swarm.assignment_count", total_assignments)
            span.set_attribute("octopus.swarm.layer_count", len(layers))

            prepared_layers, plan = self._prepare_plan(
                graph=graph,
                layers=layers,
                strategy=split_strategy,
            )
            validation = validate_work_plan(plan)
            plan = plan.model_copy(update={
                "validation_issues": list(validation.errors),
                "validation_warnings": list(validation.warnings),
            })
            events: list[SwarmEvent] = [
                SwarmEvent(
                    type="plan_created",
                    lane="workflow",
                    task_id=graph.task_id,
                    payload={
                        "strategy": split_strategy,
                        "phase_count": len(plan.phases),
                        "contract_count": len(plan.contracts),
                    },
                )
            ]
            started_at = time.perf_counter()
            all_results: list[ArmResult] = []
            all_handoffs: list[AgentHandoff] = []
            phase_reports: list[SwarmPhaseReport] = []
            max_layer_parallelism = 0
            for prepared in prepared_layers:
                phase = prepared.phase
                phase_started_at = time.perf_counter()
                events.append(
                    SwarmEvent(
                        type="phase_started",
                        lane="workflow",
                        task_id=graph.task_id,
                        phase_index=phase.phase_index,
                        node_ids=phase.node_ids,
                        payload={
                            "phase_index": phase.phase_index,
                            "parallel": phase.parallel,
                        },
                    )
                )
                events.extend(
                    _agent_assigned_events(
                        graph.task_id, phase.phase_index, prepared.pairs,
                    )
                )
                events.extend(
                    _agent_started_events(
                        graph.task_id, phase.phase_index, prepared.pairs,
                    )
                )
                dispatched_results = self._dispatch(prepared.pairs, budget)
                layer_results = [
                    *dispatched_results,
                    *(result for _assignment, result in prepared.unmatched),
                ]
                all_results.extend(layer_results)
                phase_handoffs = _agent_handoffs(
                    graph.task_id,
                    phase.phase_index,
                    [
                        *(
                            (assignment, result)
                            for (assignment, _arm), result
                            in zip(prepared.pairs, dispatched_results, strict=False)
                        ),
                        *prepared.unmatched,
                    ],
                )
                all_handoffs.extend(phase_handoffs)
                events.extend(
                    _agent_finished_events(
                        graph.task_id, phase.phase_index, layer_results,
                    )
                )
                max_layer_parallelism = max(
                    max_layer_parallelism, self._count_parallelism(prepared.pairs),
                )
                phase_report = _phase_report(
                    phase=phase,
                    results=layer_results,
                    handoffs=phase_handoffs,
                    wall_ms=(time.perf_counter() - phase_started_at) * 1000.0,
                )
                phase_reports.append(phase_report)
                events.append(
                    SwarmEvent(
                        type="phase_finished",
                        lane="workflow",
                        task_id=graph.task_id,
                        phase_index=phase.phase_index,
                        node_ids=phase.node_ids,
                        payload={
                            "phase_index": phase.phase_index,
                            "result_count": len(layer_results),
                            "succeeded": phase_report.succeeded,
                            "failed": phase_report.failed,
                            "handoff_count": phase_report.handoff_count,
                            "cost_usd": phase_report.cost_usd,
                            "wall_ms": phase_report.wall_ms,
                        },
                    )
                )
            elapsed_ms = (time.perf_counter() - started_at) * 1000.0

            if self._journal is not None:
                self._record_trajectories(graph.task_id, all_results)

            total_cost_usd = sum(r.cost.usd for r in all_results)
            all_success = bool(all_results) and all(
                r.status == "success" for r in all_results
            )

            span.set_attribute(
                "octopus.swarm.parallelism", max_layer_parallelism,
            )
            span.set_attribute("octopus.swarm.total_cost_usd", total_cost_usd)
            span.set_attribute("octopus.swarm.all_successful", all_success)
            events.append(
                SwarmEvent(
                    type="swarm_finished",
                    lane="timeline",
                    task_id=graph.task_id,
                payload={
                        "all_successful": all_success,
                        "total_cost_usd": total_cost_usd,
                        "total_wall_ms": elapsed_ms,
                        "parallelism_achieved": max_layer_parallelism,
                        "handoff_count": len(all_handoffs),
                        "phase_report_count": len(phase_reports),
                    },
                )
            )

            return SwarmResult(
                task_id=graph.task_id,
                arm_results=all_results,
                parallelism_achieved=max_layer_parallelism,
                total_wall_ms=elapsed_ms,
                total_cost_usd=total_cost_usd,
                all_successful=all_success,
                plan=plan,
                events=events,
                handoffs=all_handoffs,
                phase_reports=phase_reports,
                contract_validation_issues=list(validation.errors),
                contract_validation_warnings=list(validation.warnings),
                completion_receipt=build_completion_receipt(
                    [
                        "completed" if r.status == "success" else r.status
                        for r in all_results
                    ],
                    contract_issues=list(validation.errors),
                    contract_warnings=list(validation.warnings),
                    artifact_count=sum(len(h.artifacts) for h in all_handoffs),
                    output_present=any(bool(h.summary) for h in all_handoffs),
                ).to_dict(),
            )


    def _split_layers(
        self,
        graph: TaskGraph,
        strategy: SplitStrategy,
    ) -> list[list[ArmAssignment]]:
        if strategy == "per_node":
            return [_split_per_node(graph)]
        if strategy == "single":
            return [_split_single(graph)]
        if strategy == "topo_layers":
            return _split_topo_layers(graph)
        raise ValueError(f"unknown split_strategy: {strategy!r}")

    def _prepare_plan(
        self,
        *,
        graph: TaskGraph,
        layers: list[list[ArmAssignment]],
        strategy: SplitStrategy,
    ) -> tuple[list[_PreparedLayer], SwarmPlan]:
        prepared_layers: list[_PreparedLayer] = []
        phases: list[SwarmPhase] = []
        contracts: list[WorkContract] = []
        all_node_ids = [node.node_id for node in graph.nodes]

        for phase_index, layer in enumerate(layers):
            pairs: list[tuple[ArmAssignment, Worker]] = []
            unmatched: list[tuple[ArmAssignment, ArmResult]] = []
            assignment_ids: list[str] = []
            phase_node_ids: list[str] = []

            for assignment_index, assignment in enumerate(layer):
                node_ids = _assignment_node_ids(assignment)
                phase_node_ids.extend(node_ids)
                arm = self._arm_pool.pick_for(assignment)
                agent_id = str(getattr(arm, "arm_id", ArmId("unassigned")))
                assignment_id = f"p{phase_index}:a{assignment_index}"
                assignment_ids.append(assignment_id)
                contracts.append(
                    _make_contract(
                        assignment_id=assignment_id,
                        assignment=assignment,
                        agent_id=agent_id,
                        all_node_ids=all_node_ids,
                        graph=graph,
                    )
                )
                if arm is None:
                    unmatched.append(
                        (
                            assignment,
                            ArmResult(
                                arm_id=ArmId("unassigned"),
                                task_id=assignment.subgraph.task_id,
                                status="failed",
                                reason="no_arm_matched",
                            ),
                        )
                    )
                else:
                    pairs.append((assignment, arm))

            phase = SwarmPhase(
                phase_index=phase_index,
                assignment_ids=assignment_ids,
                node_ids=phase_node_ids,
                parallel=len(layer) > 1,
            )
            phases.append(phase)
            prepared_layers.append(
                _PreparedLayer(phase=phase, pairs=pairs, unmatched=unmatched)
            )

        return prepared_layers, SwarmPlan(
            task_id=graph.task_id,
            strategy=strategy,
            max_workers=self._max_workers,
            phases=phases,
            contracts=contracts,
        )


    def _dispatch(
        self,
        pairs: list[tuple[ArmAssignment, Worker]],
        budget: Budget,
    ) -> list[ArmResult]:
        if not pairs:
            return []

        results: list[ArmResult] = []
        with ThreadPoolExecutor(max_workers=self._max_workers) as executor:
            futures: list[Future[ArmResult]] = [
                executor.submit(self._run_one, assignment, arm, budget)
                for assignment, arm in pairs
            ]
            for fut in futures:
                try:
                    results.append(fut.result())
                except Exception as e:  # Implementation note.
                    results.append(
                        ArmResult(
                            arm_id=ArmId("unknown"),
                            task_id=TaskId(new_id()),
                            status="failed",
                            reason=f"executor_error:{e!s}",
                        )
                    )
        return results

    def _run_one(
        self,
        assignment: ArmAssignment,
        arm: Worker,
        budget: Budget,
    ) -> ArmResult:
        arm_id = getattr(arm, "arm_id", ArmId("unknown"))
        task_id = assignment.subgraph.task_id

        self._publish(
            "arm.busy",
            {"arm_id": str(arm_id), "task_id": str(task_id)},
        )
        try:
            return arm.handle(assignment, budget)
        except Exception as e:
            return ArmResult(
                arm_id=arm_id,
                task_id=task_id,
                status="failed",
                reason=f"arm_exception:{e!s}",
            )
        finally:
            self._publish(
                "arm.idle",
                {"arm_id": str(arm_id), "task_id": str(task_id)},
            )


    def _publish(self, topic: str, payload: dict[str, Any]) -> None:
        if self._signal_bus is None:
            return
        with contextlib.suppress(Exception):
            self._signal_bus.publish(topic, payload, publisher="swarm")

    def _count_parallelism(
        self,
        pairs: list[tuple[ArmAssignment, Worker]],
    ) -> int:
        if not pairs:
            return 0
        return min(len(pairs), self._max_workers)

    def _record_trajectories(
        self,
        task_id: TaskId,
        results: list[ArmResult],
    ) -> None:
        """Write a single aggregated Trajectory per task.

        Before 2026-04 this wrote one ``Trajectory(steps=[])`` per
        ArmResult · the empty-steps form made the event useless to
        SkillForge (``step_count < 2`` gate). Worse: when ``per_node``
        split dispatched N nodes to N arms, each arm's internal
        GraphRuntime wrote a 1-step Trajectory too — all of which
        SkillForge also filtered — so **multi-step patterns
        executed in parallel were never learned**.

        Fix: each ArmResult now carries the steps its Arm executed
        (see ``arms/base.py``). Here we collect them from all arms
        of the same task, sort by ``step_id`` to recover the
        original node order, and emit one Trajectory that
        represents the whole task at once. SkillForge clusters on
        this aggregated form and can learn the full sequence.

        The per-arm GraphRuntime-internal Trajectories remain in
        the journal (useful for per-arm debugging), but the forging
        loop only clusters on aggregates with ``step_count >= 2``.
        """
        if self._journal is None:
            return
        now = now_utc()

        # Collect every step from every arm of this task, then order
        # by step_id so the aggregated Trajectory looks like a
        # single-arm sequential run to SkillForge's signature hasher.
        # Ties on step_id (two arms each assigned step_id=0 after
        # per-node split) must use the numeric node index, not raw
        # string order, otherwise ``n10`` sorts before ``n2`` and the
        # learned path signature becomes unstable once graphs exceed
        # 9 nodes.
        all_steps = []
        total_tokens_in = 0
        total_tokens_out = 0
        total_usd = 0.0
        total_latency_ms = 0.0
        all_success = True
        degraded = False
        for r in results:
            all_steps.extend(r.steps)
            total_tokens_in += r.cost.tokens_in
            total_tokens_out += r.cost.tokens_out
            total_usd += r.cost.usd
            total_latency_ms += r.cost.latency_ms
            if r.status != "success":
                all_success = False
            if r.status in {"partial", "failed"}:
                degraded = True

        all_steps.sort(
            key=lambda s: (s.step_id, _node_sort_key(s.node_id), s.node_id)
        )

        # Aggregated swarm trajectories represent the swarm as a
        # whole, not any one contributing arm. Using a "lead" arm_id
        # here fragments downstream consumers that group by arm_id
        # (for example MemoryConsolidator), because equivalent swarm
        # runs can land in different buckets depending on scheduling.
        aggregate_arm_id = ArmId("swarm")

        # Wire the accumulated cost into the Trajectory outcome ·
        # pre-2026-05 this file accumulated ``total_usd`` etc into
        # local variables and then silently dropped them when
        # building ``TrajectoryOutcome`` · making every swarm-run
        # trajectory appear free to downstream consumers (memory
        # consolidation / recipe evaluation). Caught in second-pass
        # review · fix is just "pass the accumulation in".
        from runtime.platform.models import CostEntry

        aggregated_cost = CostEntry(
            tokens_in=total_tokens_in,
            tokens_out=total_tokens_out,
            usd=total_usd,
            latency_ms=total_latency_ms,
        )

        aggregated = Trajectory(
            task_id=task_id,
            arm_id=aggregate_arm_id,
            strategy_id="swarm",
            steps=all_steps,
            outcome=TrajectoryOutcome(
                success=all_success,
                cost=aggregated_cost,
                degraded=degraded,
            ),
            started_at=now,
            completed_at=now,
        )
        self._journal.write_trajectory(aggregated)


# ═══════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════


def _make_context_ref(graph: TaskGraph) -> ContextPacketRef:
    return ContextPacketRef(
        packet_id=new_id(),
        budget_tokens=graph.budget.tokens,
    )


def _make_deadline(graph: TaskGraph) -> datetime:
    return now_utc() + timedelta(milliseconds=graph.budget.latency_ms)


def _node_sort_key(node_id: str) -> tuple[int, str]:
    """Prefer numeric ``n12`` ordering over raw lexicographic sort."""
    if node_id.startswith("n") and node_id[1:].isdigit():
        return (int(node_id[1:]), node_id)
    return (10**9, node_id)


def _split_per_node(graph: TaskGraph) -> list[ArmAssignment]:
    if graph.edges:
        raise ValueError(
            f"per_node requires edgeless graph (got {len(graph.edges)} edges) · "
            "use split_strategy='topo_layers' to respect dependencies"
        )
    assignments: list[ArmAssignment] = []
    for node in graph.nodes:
        sub_graph = TaskGraph(
            nodes=[node],
            edges=[],
            budget=graph.budget,
            task_type=graph.task_type,
        )
        assignments.append(
            ArmAssignment(
                arm_id=ArmId("unassigned"),  # Implementation note.
                subgraph=sub_graph,
                context_ref=_make_context_ref(graph),
                deadline=_make_deadline(graph),
            )
        )
    return assignments


def _split_single(graph: TaskGraph) -> list[ArmAssignment]:
    return [
        ArmAssignment(
            arm_id=ArmId("unassigned"),
            subgraph=graph,
            context_ref=_make_context_ref(graph),
            deadline=_make_deadline(graph),
        )
    ]


def _split_topo_layers(graph: TaskGraph) -> list[list[ArmAssignment]]:
    node_by_id = {n.node_id: n for n in graph.nodes}
    if len(node_by_id) != len(graph.nodes):
        raise ValueError("duplicate node_id in graph")

    indeg: dict[str, int] = {nid: 0 for nid in node_by_id}
    children: dict[str, list[str]] = {nid: [] for nid in node_by_id}
    for e in graph.edges:
        if e.from_node not in node_by_id or e.to_node not in node_by_id:
            raise ValueError(f"edge references unknown node: {e}")
        indeg[e.to_node] += 1
        children[e.from_node].append(e.to_node)

    layers: list[list[ArmAssignment]] = []
    remaining = dict(indeg)
    while remaining:
        ready = [nid for nid, d in remaining.items() if d == 0]
        if not ready:
            raise ValueError(
                f"cycle in TaskGraph (unresolved nodes: {sorted(remaining)})"
            )
        ready.sort()
        layer: list[ArmAssignment] = []
        for nid in ready:
            sub_graph = TaskGraph(
                nodes=[node_by_id[nid]],
                edges=[],
                budget=graph.budget,
                task_type=graph.task_type,
            )
            layer.append(
                ArmAssignment(
                    arm_id=ArmId("unassigned"),
                    subgraph=sub_graph,
                    context_ref=_make_context_ref(graph),
                    deadline=_make_deadline(graph),
                )
            )
            del remaining[nid]
            for child in children[nid]:
                if child in remaining:
                    remaining[child] -= 1
        layers.append(layer)
    return layers


def _assignment_node_ids(assignment: ArmAssignment) -> list[str]:
    return [node.node_id for node in assignment.subgraph.nodes]


def _assignment_role(assignment: ArmAssignment) -> str:
    skills = [
        str(node.skill_ref)
        for node in assignment.subgraph.nodes
        if node.skill_ref is not None
    ]
    if not skills:
        return assignment.subgraph.task_type
    if len(set(skills)) == 1:
        return skills[0]
    return " + ".join(skills)


def _make_contract(
    *,
    assignment_id: str,
    assignment: ArmAssignment,
    agent_id: str,
    all_node_ids: list[str],
    graph: TaskGraph,
) -> WorkContract:
    node_ids = _assignment_node_ids(assignment)
    depends_on = [
        edge.from_node
        for edge in graph.edges
        if edge.to_node in node_ids and edge.from_node not in node_ids
    ]
    return WorkContract(
        contract_id=assignment_id,
        agent_id=agent_id,
        role=_assignment_role(assignment),
        node_ids=node_ids,
        depends_on=depends_on,
        owned_scope=[f"node:{node_id}" for node_id in node_ids],
        forbidden_scope=[
            f"node:{node_id}" for node_id in all_node_ids if node_id not in node_ids
        ],
        success_criteria=[
            f"Complete node {node_id}" for node_id in node_ids
        ] + ["Return an ArmResult with status=success"],
    )


def _agent_assigned_events(
    task_id: TaskId,
    phase_index: int,
    pairs: list[tuple[ArmAssignment, Worker]],
) -> list[SwarmEvent]:
    events: list[SwarmEvent] = []
    for assignment, arm in pairs:
        agent_id = str(getattr(arm, "arm_id", ArmId("unknown")))
        node_ids = _assignment_node_ids(assignment)
        events.append(
            SwarmEvent(
                type="agent_assigned",
                lane="agent",
                task_id=task_id,
                phase_index=phase_index,
                agent_id=agent_id,
                node_ids=node_ids,
                payload={"role": _assignment_role(assignment)},
            )
        )
    return events


def _agent_started_events(
    task_id: TaskId,
    phase_index: int,
    pairs: list[tuple[ArmAssignment, Worker]],
) -> list[SwarmEvent]:
    events: list[SwarmEvent] = []
    for assignment, arm in pairs:
        agent_id = str(getattr(arm, "arm_id", ArmId("unknown")))
        events.append(
            SwarmEvent(
                type="agent_started",
                lane="timeline",
                task_id=task_id,
                phase_index=phase_index,
                agent_id=agent_id,
                node_ids=_assignment_node_ids(assignment),
                payload={"role": _assignment_role(assignment)},
            )
        )
    return events


def _agent_finished_events(
    task_id: TaskId,
    phase_index: int,
    results: list[ArmResult],
) -> list[SwarmEvent]:
    events: list[SwarmEvent] = []
    for result in results:
        agent_id = str(result.arm_id)
        events.append(
            SwarmEvent(
                type="agent_finished",
                lane="timeline",
                task_id=task_id,
                phase_index=phase_index,
                agent_id=agent_id,
                payload={
                    "arm_task_id": str(result.task_id),
                    "status": result.status,
                    "reason": result.reason,
                    "cost_usd": result.cost.usd,
                },
            )
        )
    return events


def _agent_handoffs(
    task_id: TaskId,
    phase_index: int,
    assignment_results: list[tuple[ArmAssignment, ArmResult]],
) -> list[AgentHandoff]:
    handoffs: list[AgentHandoff] = []
    for assignment, result in assignment_results:
        handoffs.append(
            AgentHandoff(
                agent_id=str(result.arm_id),
                task_id=task_id,
                phase_index=phase_index,
                node_ids=_result_node_ids(result) or _assignment_node_ids(assignment),
                status=result.status,
                summary=_result_summary(result),
                artifacts=_result_artifacts(result),
                cost_usd=result.cost.usd,
                reason=result.reason,
            )
        )
    return handoffs


def _phase_report(
    *,
    phase: SwarmPhase,
    results: list[ArmResult],
    handoffs: list[AgentHandoff],
    wall_ms: float,
) -> SwarmPhaseReport:
    succeeded = sum(1 for result in results if result.status == "success")
    failed = sum(1 for result in results if result.status != "success")
    if not results:
        status: Literal["success", "partial", "failed", "empty"] = "empty"
    elif succeeded == len(results):
        status = "success"
    elif succeeded == 0:
        status = "failed"
    else:
        status = "partial"

    return SwarmPhaseReport(
        phase_index=phase.phase_index,
        node_ids=phase.node_ids,
        assignment_count=len(phase.assignment_ids),
        handoff_count=len(handoffs),
        succeeded=succeeded,
        failed=failed,
        status=status,
        wall_ms=wall_ms,
        cost_usd=sum(result.cost.usd for result in results),
    )


def _result_node_ids(result: ArmResult) -> list[str]:
    if result.steps:
        node_ids: list[str] = []
        for step in result.steps:
            if step.node_id not in node_ids:
                node_ids.append(step.node_id)
        return node_ids
    raw = result.outputs.get("node_ids") or result.outputs.get("task_ids")
    if isinstance(raw, list):
        return [str(item) for item in raw]
    raw = result.outputs.get("node_id") or result.outputs.get("task_id")
    if raw:
        return [str(raw)]
    return []


def _result_summary(result: ArmResult) -> str:
    for key in ("summary", "handoff", "result", "message"):
        value = result.outputs.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    if result.reason:
        return result.reason
    if result.status == "success":
        return "completed"
    return result.status


def _result_artifacts(result: ArmResult) -> list[str]:
    artifacts: list[str] = []
    for key in ("artifacts", "files", "modified_files", "deliverables"):
        value = result.outputs.get(key)
        if isinstance(value, str) and value:
            artifacts.append(value)
        elif isinstance(value, list):
            artifacts.extend(str(item) for item in value if item)
    for step in result.steps:
        artifacts.extend(step.result.files_modified)
    return list(dict.fromkeys(artifacts))
