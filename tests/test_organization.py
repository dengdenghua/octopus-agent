"""Tests for runtime.safety.organization — team topology evolution."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from runtime.safety.organization import (
    AgentSpec,
    CoordinationProtocol,
    Role,
    TeamTopology,
)
from runtime.safety.organization.evolver import TopologyEvolver
from runtime.safety.organization.forge import (
    PromoteResult,
    TopologyForge,
    load_registry,
    save_registry,
)
from runtime.safety.organization.performance_log import (
    read_runs,
    record_run,
)
from runtime.safety.organization.team_runner import (
    TeamRunner,
    _parse_evaluator_score,
)

# ── Topology data model ──────────────────────────────────────


def test_sequential_topology_requires_planner_or_generator() -> None:
    with pytest.raises(ValueError, match="planner or generator"):
        TeamTopology(
            name="bad",
            protocol=CoordinationProtocol.SEQUENTIAL,
            agents={Role.EVALUATOR: AgentSpec(agent_id="a")},
        )


def test_evaluator_optimizer_requires_both_roles() -> None:
    with pytest.raises(ValueError, match="evaluator_optimizer"):
        TeamTopology(
            name="bad",
            protocol=CoordinationProtocol.EVALUATOR_OPTIMIZER,
            agents={Role.GENERATOR: AgentSpec(agent_id="g")},
        )


def test_topology_fingerprint_stable() -> None:
    a = TeamTopology(
        name="t1",
        protocol=CoordinationProtocol.SEQUENTIAL,
        agents={Role.PLANNER: AgentSpec(agent_id="p")},
    )
    b = TeamTopology(
        name="t1-rename",  # name doesn't enter fingerprint
        protocol=CoordinationProtocol.SEQUENTIAL,
        agents={Role.PLANNER: AgentSpec(agent_id="p")},
    )
    assert a.fingerprint == b.fingerprint


def test_topology_fingerprint_changes_on_agent_swap() -> None:
    a = TeamTopology(
        name="t",
        protocol=CoordinationProtocol.SEQUENTIAL,
        agents={Role.PLANNER: AgentSpec(agent_id="alice")},
    )
    b = TeamTopology(
        name="t",
        protocol=CoordinationProtocol.SEQUENTIAL,
        agents={Role.PLANNER: AgentSpec(agent_id="bob")},
    )
    assert a.fingerprint != b.fingerprint


def test_topology_roundtrips_through_dict() -> None:
    a = TeamTopology(
        name="trip",
        protocol=CoordinationProtocol.EVALUATOR_OPTIMIZER,
        agents={
            Role.GENERATOR: AgentSpec(agent_id="g", temperature=0.7),
            Role.EVALUATOR: AgentSpec(agent_id="e"),
        },
        quality_threshold=0.75,
        max_iterations=2,
        task_bucket="bench",
    )
    b = TeamTopology.from_dict(a.to_dict())
    assert b.fingerprint == a.fingerprint
    assert b.protocol == CoordinationProtocol.EVALUATOR_OPTIMIZER
    assert b.agents[Role.GENERATOR].temperature == 0.7
    assert b.quality_threshold == 0.75


# ── Score parser ─────────────────────────────────────────────


@pytest.mark.parametrize(
    "text, expected",
    [
        ("score: 0.85\nreason: good", 0.85),
        ("Quality 0.40 — needs work", 0.40),
        ("rating: 85/100", 0.85),
        ("no score here", None),
        ("score: 1.5", 1.0),  # clamp
    ],
)
def test_parse_evaluator_score(text, expected) -> None:
    assert _parse_evaluator_score(text) == expected


# ── TeamRunner: sequential ───────────────────────────────────


def _stub_caller(scripts: dict[str, dict[str, Any]]):
    """Build a role caller that returns a scripted reply per agent_id."""

    def caller(**kwargs):
        agent_id = kwargs["agent_id"]
        return scripts.get(agent_id, {"output": f"<{agent_id}>", "success": True})

    return caller


def _seed_subagent_reviews(queue: Any, *, role: str, statuses: list[str]) -> None:
    for idx, status in enumerate(statuses):
        added = queue.add_from_task_run_review(
            {
                "status": "completed",
                "task_id": f"task-{idx}",
                "thread_id": "thread-1",
                "turn_id": f"turn-{idx}",
                "agent_id": role,
                "learning_candidates": [
                    {
                        "kind": "subagent_output",
                        "priority": "P2",
                        "memory_bucket": "experience",
                        "title": f"{role} sample {idx}",
                        "text": f"{role} output {idx}",
                        "subagent": {
                            "role": role,
                            "agent_id": role,
                            "files_touched": [],
                        },
                    }
                ],
            }
        )
        item_id = added["items"][0]["id"]
        if status != "pending":
            queue.decide(item_id, action=status, reason="test")


def test_team_runner_sequential_chains_outputs() -> None:
    topology = TeamTopology(
        name="chain",
        protocol=CoordinationProtocol.SEQUENTIAL,
        agents={
            Role.PLANNER: AgentSpec(agent_id="planner"),
            Role.GENERATOR: AgentSpec(agent_id="gen"),
            Role.EVALUATOR: AgentSpec(agent_id="judge"),
        },
    )
    runner = TeamRunner(
        role_caller=_stub_caller(
            {
                "planner": {"output": "plan: outline", "success": True},
                "gen": {"output": "draft v1", "success": True},
                "judge": {"output": "score: 0.8\nlooks good", "success": True},
            }
        )
    )
    result = runner.run(topology, "build foo")
    assert result.success is True
    assert result.final_output == "score: 0.8\nlooks good"
    assert [str(o.role) for o in result.role_outputs] == [
        "planner",
        "generator",
        "evaluator",
    ]
    assert result.quality_score == 0.8


def test_team_runner_sequential_isolates_role_failure() -> None:
    """① 失败隔离: 单个角色失败不再中断流水线, 部分产出继续交付."""
    topology = TeamTopology(
        name="isolate",
        protocol=CoordinationProtocol.SEQUENTIAL,
        agents={
            Role.PLANNER: AgentSpec(agent_id="p"),
            Role.GENERATOR: AgentSpec(agent_id="g"),
        },
    )
    runner = TeamRunner(
        role_caller=_stub_caller(
            {
                "p": {"output": "", "success": False, "error": "boom"},
                "g": {"output": "generator still delivers", "success": True},
            }
        )
    )
    result = runner.run(topology, "x")
    # 失败隔离: 流水线继续跑完, generator 的交付被保留为最终产出。
    assert result.success is True
    assert len(result.role_outputs) == 2
    assert result.final_output == "generator still delivers"
    assert result.degraded_roles == ["planner"]
    assert result.role_outputs[0].error == "boom"


def test_team_runner_continues_after_advisory_critic_error() -> None:
    topology = TeamTopology(
        name="critic-degraded",
        protocol=CoordinationProtocol.SEQUENTIAL,
        agents={
            Role.PLANNER: AgentSpec(agent_id="p"),
            Role.CRITIC: AgentSpec(agent_id="c"),
            Role.SYNTHESIZER: AgentSpec(agent_id="s"),
        },
    )
    runner = TeamRunner(
        role_caller=_stub_caller(
            {
                "p": {"output": "plan", "success": True},
                "c": {
                    "output": "partial fact check",
                    "success": False,
                    "error": "round cap",
                },
                "s": {"output": "verified final artifact", "success": True},
            }
        )
    )

    result = runner.run(topology, "x")

    assert result.success is True
    assert result.final_output == "verified final artifact"
    assert [output.role for output in result.role_outputs] == [
        Role.PLANNER,
        Role.CRITIC,
        Role.SYNTHESIZER,
    ]
    assert result.role_outputs[1].error == "round cap"


def test_team_runner_blocks_retired_subagent_for_high_risk_task(tmp_path: Path) -> None:
    from runtime.memory.learning.review_queue import ReviewQueue

    path = tmp_path / "review_queue.json"
    _seed_subagent_reviews(
        ReviewQueue(path),
        role="weak_delegate",
        statuses=["rejected", "rejected", "rejected"],
    )
    called = {"hit": False}
    events: list[dict[str, Any]] = []

    def caller(**kwargs):
        called["hit"] = True
        return {"output": "should not run", "success": True}

    topology = TeamTopology(
        name="fitness-block",
        protocol=CoordinationProtocol.SEQUENTIAL,
        agents={Role.PLANNER: AgentSpec(agent_id="weak_delegate")},
    )
    runner = TeamRunner(role_caller=caller, event_emitter=events.append)
    result = runner.run(
        topology,
        "change production policy",
        context={
            "task_risk_level": "high",
            "review_queue_path": str(path),
        },
    )

    assert called["hit"] is False
    assert result.success is False
    assert result.error is not None
    assert result.error.startswith("planner(weak_delegate):")
    assert result.role_outputs[0].error
    assert result.role_outputs[0].metadata["subagent_route_decision"]["action"] == "block"
    assert events[0]["type"] == "team_role_blocked"


def test_strong_subagent_generates_team_promotion_proposal(tmp_path: Path) -> None:
    from runtime.memory.learning.review_queue import ReviewQueue
    from runtime.safety.evolution.subagent_team_promotion import (
        build_subagent_team_promotion_proposals,
    )

    base = TeamTopology(
        name="base-code-team",
        protocol=CoordinationProtocol.SEQUENTIAL,
        agents={Role.GENERATOR: AgentSpec(agent_id="legacy-generator")},
        task_bucket="code",
    )
    review_queue_path = tmp_path / "review_queue.json"
    _seed_subagent_reviews(
        ReviewQueue(review_queue_path),
        role="generator",
        statuses=["promoted", "promoted", "promoted"],
    )

    report = build_subagent_team_promotion_proposals(
        registry={base.fingerprint: base},
        review_queue_path=review_queue_path,
        subagent_policy_path=tmp_path / "subagent_policy.json",
    )

    assert report["schema"] == "octopus.subagent_team_promotion.v1"
    assert report["proposal_count"] == 1
    proposal = report["proposals"][0]
    assert proposal["kind"] == "swap_agent"
    assert proposal["base_topology"] == base.fingerprint
    assert proposal["detail"]["role"] == "generator"
    assert proposal["detail"]["old_agent"] == "legacy-generator"
    assert proposal["detail"]["new_agent"] == "generator"
    assert proposal["detail"]["source"] == "subagent_fitness"


def test_retired_strong_subagent_is_not_promoted_to_team(tmp_path: Path) -> None:
    from runtime.memory.learning.review_queue import ReviewQueue
    from runtime.safety.evolution.subagent_policy import SubagentPolicyStore
    from runtime.safety.evolution.subagent_team_promotion import (
        build_subagent_team_promotion_proposals,
    )

    base = TeamTopology(
        name="base-code-team",
        protocol=CoordinationProtocol.SEQUENTIAL,
        agents={Role.GENERATOR: AgentSpec(agent_id="legacy-generator")},
        task_bucket="code",
    )
    review_queue_path = tmp_path / "review_queue.json"
    policy_path = tmp_path / "subagent_policy.json"
    _seed_subagent_reviews(
        ReviewQueue(review_queue_path),
        role="generator",
        statuses=["promoted", "promoted", "promoted"],
    )
    SubagentPolicyStore(policy_path).decide(
        "generator",
        action="retire",
        reason="operator retired generator",
    )

    report = build_subagent_team_promotion_proposals(
        registry={base.fingerprint: base},
        review_queue_path=review_queue_path,
        subagent_policy_path=policy_path,
    )

    assert report["proposal_count"] == 0
    assert report["skipped"][0]["reason"] == "operator policy retired this subagent"


def test_topology_promotion_lift_tracks_after_vs_baseline(tmp_path: Path) -> None:
    import json

    from runtime.safety.organization.promotion_lift import (
        compute_topology_promotion_lift,
    )

    base = TeamTopology(
        name="base-code-team",
        protocol=CoordinationProtocol.SEQUENTIAL,
        agents={Role.GENERATOR: AgentSpec(agent_id="legacy-generator")},
        task_bucket="code",
    )
    promoted = TeamTopology(
        name="base-code-team+swap(generator:generator)",
        protocol=CoordinationProtocol.SEQUENTIAL,
        agents={Role.GENERATOR: AgentSpec(agent_id="generator")},
        task_bucket="code",
        metadata={
            "derived_from": base.fingerprint,
            "mutation": "swap_agent",
            "promotion_source": "subagent_fitness",
            "promotion_detail": {"role": "generator"},
        },
    )
    perf_path = tmp_path / "topology_performance.jsonl"
    rows = [
        {
            "fingerprint": base.fingerprint,
            "success": False,
            "quality_score": 0.4,
            "total_duration_ms": 1000,
        },
        {
            "fingerprint": base.fingerprint,
            "success": True,
            "quality_score": 0.6,
            "total_duration_ms": 1200,
        },
        {
            "fingerprint": promoted.fingerprint,
            "success": True,
            "quality_score": 0.9,
            "total_duration_ms": 900,
        },
        {
            "fingerprint": promoted.fingerprint,
            "success": True,
            "quality_score": 0.8,
            "total_duration_ms": 850,
        },
    ]
    perf_path.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )

    report = compute_topology_promotion_lift(
        registry={
            base.fingerprint: base,
            promoted.fingerprint: promoted,
        },
        performance_path=perf_path,
    )

    assert report["schema"] == "octopus.topology_promotion_lift.v1"
    assert report["count"] == 1
    lift = report["reports"][0]
    assert lift["promotion_source"] == "subagent_fitness"
    assert lift["before"]["success_rate"] == 0.5
    assert lift["after"]["success_rate"] == 1.0
    assert lift["lift"]["success_rate_delta"] == 0.5
    assert lift["verdict"] == "improved"


def test_merged_topology_proposals_rank_by_historical_lift() -> None:
    from runtime.safety.evolution.subagent_team_promotion import (
        merged_topology_proposals,
    )

    proposals = [
        {
            "kind": "swap_agent",
            "base_topology": "base-a",
            "bucket": "code",
            "detail": {"role": "generator", "new_agent": "slow-agent"},
            "confidence": 0.8,
            "rationale": "slow has high local fitness",
        },
        {
            "kind": "swap_agent",
            "base_topology": "base-b",
            "bucket": "code",
            "detail": {"role": "generator", "new_agent": "fast-agent"},
            "confidence": 0.74,
            "rationale": "fast has lower local fitness",
        },
    ]
    lift_report = {
        "schema": "octopus.topology_promotion_lift.v1",
        "reports": [
            {
                "promotion_detail": {"role": "generator", "new_agent": "fast-agent"},
                "lift": {"success_rate_delta": 0.4, "quality_score_delta": 0.2},
                "verdict": "improved",
            },
            {
                "promotion_detail": {"role": "generator", "new_agent": "slow-agent"},
                "lift": {"success_rate_delta": -0.3, "quality_score_delta": -0.1},
                "verdict": "regressed",
            },
        ],
    }

    merged = merged_topology_proposals(
        proposals,
        registry={},
        promotion_lift_report=lift_report,
    )

    assert merged["proposals"][0]["detail"]["new_agent"] == "fast-agent"
    assert merged["proposals"][0]["detail"]["historical_lift"]["improved_count"] == 1
    assert merged["proposals"][0]["rank_score"] > merged["proposals"][1]["rank_score"]


def test_team_runner_allows_retired_subagent_for_low_risk_with_warning(
    tmp_path: Path,
) -> None:
    from runtime.memory.learning.review_queue import ReviewQueue

    path = tmp_path / "review_queue.json"
    _seed_subagent_reviews(
        ReviewQueue(path),
        role="weak_delegate",
        statuses=["rejected", "rejected", "rejected"],
    )
    captured: dict[str, Any] = {}

    def caller(**kwargs):
        captured.update(kwargs)
        return {"output": "low risk ok", "success": True}

    topology = TeamTopology(
        name="fitness-warn",
        protocol=CoordinationProtocol.SEQUENTIAL,
        agents={Role.PLANNER: AgentSpec(agent_id="weak_delegate")},
    )
    result = TeamRunner(role_caller=caller).run(
        topology,
        "summarize a note",
        context={
            "task_risk_level": "low",
            "review_queue_path": str(path),
        },
    )

    decision = captured["context"]["subagent_route_decision"]
    assert result.success is True
    assert decision["action"] == "allow_with_warning"
    assert decision["verdict"] == "retire_candidate"


def test_team_runner_blocks_operator_retired_subagent(tmp_path: Path) -> None:
    from runtime.safety.evolution.subagent_policy import SubagentPolicyStore

    policy_path = tmp_path / "subagent_policy.json"
    SubagentPolicyStore(policy_path).decide(
        "manually_retired",
        action="retire",
        reason="operator retired this subagent",
        evidence_item_ids=["route-1"],
        actor="operator-test",
    )
    called = {"hit": False}

    def caller(**kwargs):
        called["hit"] = True
        return {"output": "should not run", "success": True}

    topology = TeamTopology(
        name="operator-policy-block",
        protocol=CoordinationProtocol.SEQUENTIAL,
        agents={Role.PLANNER: AgentSpec(agent_id="manually_retired")},
    )
    result = TeamRunner(role_caller=caller).run(
        topology,
        "summarize a note",
        context={
            "task_risk_level": "low",
            "subagent_policy_path": str(policy_path),
        },
    )

    assert called["hit"] is False
    assert result.success is False
    decision = result.role_outputs[0].metadata["subagent_route_decision"]
    assert decision["action"] == "block"
    assert decision["verdict"] == "operator_retired"


# ── TeamRunner: evaluator_optimizer ──────────────────────────


def test_team_runner_evaluator_optimizer_passes_first_try() -> None:
    topology = TeamTopology(
        name="eo",
        protocol=CoordinationProtocol.EVALUATOR_OPTIMIZER,
        agents={
            Role.GENERATOR: AgentSpec(agent_id="g"),
            Role.EVALUATOR: AgentSpec(agent_id="e"),
        },
        quality_threshold=0.5,
    )
    runner = TeamRunner(
        role_caller=_stub_caller(
            {
                "g": {"output": "answer A", "success": True},
                "e": {"output": "score: 0.8 great", "success": True},
            }
        )
    )
    result = runner.run(topology, "task")
    assert result.iterations == 1
    assert result.final_output == "answer A"
    assert result.success is True


def test_team_runner_evaluator_optimizer_retries_on_low_score() -> None:
    """Force two iterations: first eval is 0.2, second is 0.9."""
    call_count = {"e": 0, "g": 0}

    def caller(**kwargs):
        aid = kwargs["agent_id"]
        if aid == "g":
            call_count["g"] += 1
            return {"output": f"draft {call_count['g']}", "success": True}
        if aid == "e":
            call_count["e"] += 1
            score = 0.2 if call_count["e"] == 1 else 0.9
            return {"output": f"score: {score}", "success": True}
        return {"output": "", "success": True}

    topology = TeamTopology(
        name="eo-retry",
        protocol=CoordinationProtocol.EVALUATOR_OPTIMIZER,
        agents={
            Role.GENERATOR: AgentSpec(agent_id="g"),
            Role.EVALUATOR: AgentSpec(agent_id="e"),
        },
        quality_threshold=0.5,
        max_iterations=3,
    )
    runner = TeamRunner(role_caller=caller)
    result = runner.run(topology, "task")
    assert result.iterations == 2
    assert result.final_output == "draft 2"
    assert result.quality_score == 0.9


def test_team_runner_evaluator_optimizer_exhausts_iterations() -> None:
    """All iterations below threshold — still returns latest draft."""

    def caller(**kwargs):
        aid = kwargs["agent_id"]
        if aid == "g":
            return {"output": "weak draft", "success": True}
        return {"output": "score: 0.1", "success": True}

    topology = TeamTopology(
        name="eo-exhaust",
        protocol=CoordinationProtocol.EVALUATOR_OPTIMIZER,
        agents={
            Role.GENERATOR: AgentSpec(agent_id="g"),
            Role.EVALUATOR: AgentSpec(agent_id="e"),
        },
        quality_threshold=0.8,
        max_iterations=2,
    )
    runner = TeamRunner(role_caller=caller)
    result = runner.run(topology, "task")
    assert result.iterations == 2
    assert result.final_output == "weak draft"
    assert result.quality_score == 0.1


def test_team_runner_emits_role_lifecycle_events() -> None:
    """Live observability: every role start / end must reach the
    emitter so the realtime gateway can show the swarm's progress
    instead of a 60-second blank stream. Regression guard for the
    "deep mode is opaque, ends with 本次回复已中断" report."""
    topology = TeamTopology(
        name="observable_chain",
        protocol=CoordinationProtocol.SEQUENTIAL,
        agents={
            Role.PLANNER: AgentSpec(agent_id="p"),
            Role.GENERATOR: AgentSpec(agent_id="g"),
        },
    )

    captured: list[dict[str, Any]] = []

    def _emitter(event: dict[str, Any]) -> None:
        captured.append(event)

    runner = TeamRunner(
        role_caller=_stub_caller(
            {
                "p": {"output": "outline", "success": True},
                "g": {"output": "answer", "success": True},
            }
        ),
        event_emitter=_emitter,
    )
    runner.run(topology, "x")

    starts = [e for e in captured if e["type"] == "team_role_start"]
    ends = [e for e in captured if e["type"] == "team_role_end"]
    assert len(starts) == 2, captured
    assert len(ends) == 2, captured
    # Roles must come through in the canonical sequential order.
    assert [e["role"] for e in starts] == ["planner", "generator"]
    assert [e["role"] for e in ends] == ["planner", "generator"]
    assert all(e["status"] == "success" for e in ends)
    # Output payload rides the end event so the gateway can render
    # the role's verdict without waiting on the final aggregated result.
    assert ends[0]["output"] == "outline"
    assert ends[1]["output"] == "answer"


def test_team_runner_emits_error_event_on_role_exception() -> None:
    """A role that raises must surface as ``team_role_end`` with
    status=error. Without this the gateway's stream would silently
    swallow the exception and the user would see a vanished stream."""
    topology = TeamTopology(
        name="fault",
        protocol=CoordinationProtocol.SEQUENTIAL,
        agents={
            Role.PLANNER: AgentSpec(agent_id="p"),
        },
    )

    def boom(**_kwargs):
        raise RuntimeError("subagent crashed")

    captured: list[dict[str, Any]] = []
    runner = TeamRunner(
        role_caller=boom,
        event_emitter=captured.append,
    )
    runner.run(topology, "x")

    ends = [e for e in captured if e["type"] == "team_role_end"]
    assert len(ends) == 1
    assert ends[0]["status"] == "error"
    assert "subagent crashed" in ends[0]["error"]


def test_team_runner_event_emitter_failures_dont_break_run() -> None:
    """The emitter is best-effort: a buggy emitter must not abort a run."""
    topology = TeamTopology(
        name="resilient",
        protocol=CoordinationProtocol.SEQUENTIAL,
        agents={Role.PLANNER: AgentSpec(agent_id="p")},
    )

    def bad_emitter(_event: dict[str, Any]) -> None:
        raise RuntimeError("emitter went bang")

    runner = TeamRunner(
        role_caller=_stub_caller({"p": {"output": "ok", "success": True}}),
        event_emitter=bad_emitter,
    )
    result = runner.run(topology, "x")
    assert result.success is True
    assert result.final_output == "ok"


# ── performance_log ──────────────────────────────────────────


def test_performance_log_roundtrip(tmp_path: Path) -> None:
    topology = TeamTopology(
        name="log-test",
        protocol=CoordinationProtocol.SEQUENTIAL,
        agents={Role.GENERATOR: AgentSpec(agent_id="g")},
    )
    runner = TeamRunner(
        role_caller=_stub_caller(
            {
                "g": {"output": "out", "success": True},
            }
        )
    )
    log_path = tmp_path / "perf.jsonl"
    result = runner.run(topology, "x")
    record_run(result, path=log_path)
    record_run(result, path=log_path)
    rows = read_runs(path=log_path)
    assert len(rows) == 2
    assert rows[0]["topology"] == "log-test"
    assert rows[0]["fingerprint"] == topology.fingerprint


# ── Evolver ──────────────────────────────────────────────────


def test_evolver_proposes_swap_when_other_agent_wins(tmp_path: Path) -> None:
    # Two topologies, same bucket, different generator agent.
    losing = TeamTopology(
        name="losing",
        protocol=CoordinationProtocol.SEQUENTIAL,
        agents={Role.GENERATOR: AgentSpec(agent_id="alice")},
        task_bucket="bucket-A",
    )
    winning = TeamTopology(
        name="winning",
        protocol=CoordinationProtocol.SEQUENTIAL,
        agents={Role.GENERATOR: AgentSpec(agent_id="bob")},
        task_bucket="bucket-A",
    )
    registry = {losing.fingerprint: losing, winning.fingerprint: winning}

    log_path = tmp_path / "perf.jsonl"
    # 6 losing runs (1 success), 6 winning runs (6 successes)
    for i in range(6):
        from runtime.safety.organization.team_runner import (
            RoleOutput,
            TeamRunResult,
        )

        rl = TeamRunResult(
            topology_name=losing.name,
            topology_fingerprint=losing.fingerprint,
            task_bucket="bucket-A",
            success=(i == 0),
            final_output="x" if i == 0 else "",
            role_outputs=[RoleOutput(role=Role.GENERATOR, agent_id="alice", output="x")],
        )
        record_run(rl, path=log_path)
        rw = TeamRunResult(
            topology_name=winning.name,
            topology_fingerprint=winning.fingerprint,
            task_bucket="bucket-A",
            success=True,
            final_output="y",
            role_outputs=[RoleOutput(role=Role.GENERATOR, agent_id="bob", output="y")],
        )
        record_run(rw, path=log_path)

    evolver = TopologyEvolver(
        log_path=log_path,
        proposals_path=tmp_path / "proposals.json",
        registry=registry,
    )
    report = evolver.analyse()
    swap_props = [p for p in report.proposals if p.kind == "swap_agent"]
    assert any(
        p.detail.get("old_agent") == "alice" and p.detail.get("new_agent") == "bob"
        for p in swap_props
    )


# ── Forge ────────────────────────────────────────────────────


def test_forge_swap_promotes_and_writes_registry(tmp_path: Path) -> None:
    base = TeamTopology(
        name="orig",
        protocol=CoordinationProtocol.SEQUENTIAL,
        agents={Role.GENERATOR: AgentSpec(agent_id="alice")},
        task_bucket="b",
    )
    reg_path = tmp_path / "registry.json"
    save_registry({base.fingerprint: base}, path=reg_path)

    from runtime.safety.organization.evolver import Proposal

    forge = TopologyForge(registry_path=reg_path)
    result: PromoteResult = forge.promote(
        Proposal(
            kind="swap_agent",
            base_topology=base.fingerprint,
            bucket="b",
            detail={"role": "generator", "old_agent": "alice", "new_agent": "bob"},
            confidence=0.8,
            rationale="test",
        )
    )
    assert result.accepted is True
    assert result.new_topology is not None
    new_reg = load_registry(path=reg_path)
    # Original is still there + new one is added (not a replacement).
    assert base.fingerprint in new_reg
    assert result.new_topology.fingerprint in new_reg
    assert new_reg[result.new_topology.fingerprint].agents[Role.GENERATOR].agent_id == "bob"


def test_forge_rejects_unknown_proposal_kind(tmp_path: Path) -> None:
    base = TeamTopology(
        name="x",
        protocol=CoordinationProtocol.SEQUENTIAL,
        agents={Role.GENERATOR: AgentSpec(agent_id="a")},
    )
    reg_path = tmp_path / "r.json"
    save_registry({base.fingerprint: base}, path=reg_path)

    from runtime.safety.organization.evolver import Proposal

    forge = TopologyForge(registry_path=reg_path)
    result = forge.promote(
        Proposal(
            kind="weird_unknown_kind",
            base_topology=base.fingerprint,
            bucket="b",
            detail={},
            confidence=0.5,
        )
    )
    assert result.accepted is False
    assert "unknown proposal kind" in result.reason


def test_forge_rejects_missing_base(tmp_path: Path) -> None:
    forge = TopologyForge(registry_path=tmp_path / "empty.json")
    from runtime.safety.organization.evolver import Proposal

    result = forge.promote(
        Proposal(
            kind="swap_agent",
            base_topology="does-not-exist",
            bucket="b",
            detail={"role": "generator", "new_agent": "x"},
            confidence=0.5,
        )
    )
    assert result.accepted is False
    assert "base topology not found" in result.reason


def test_forge_rejects_operator_retired_agent(tmp_path: Path) -> None:
    from runtime.safety.evolution.subagent_policy import SubagentPolicyStore
    from runtime.safety.organization.evolver import Proposal

    base = TeamTopology(
        name="orig",
        protocol=CoordinationProtocol.SEQUENTIAL,
        agents={Role.GENERATOR: AgentSpec(agent_id="alice")},
        task_bucket="b",
    )
    reg_path = tmp_path / "registry.json"
    policy_path = tmp_path / "subagent_policy.json"
    save_registry({base.fingerprint: base}, path=reg_path)
    SubagentPolicyStore(policy_path).decide(
        "bob",
        action="retire",
        reason="operator retired bob",
        actor="operator-test",
    )

    forge = TopologyForge(
        registry_path=reg_path,
        subagent_policy_path=policy_path,
    )
    result = forge.promote(
        Proposal(
            kind="swap_agent",
            base_topology=base.fingerprint,
            bucket="b",
            detail={"role": "generator", "old_agent": "alice", "new_agent": "bob"},
            confidence=0.8,
            rationale="test",
        )
    )

    assert result.accepted is False
    assert "retired agents in operator policy" in result.reason
    assert "generator:bob" in result.reason


# ── gene_locks integration ───────────────────────────────────


def test_gene_locks_has_topology_mutation_kinds() -> None:
    from runtime.safety.gene_locks import MutationKind

    assert hasattr(MutationKind, "EVOLVE_TOPOLOGY")
    assert hasattr(MutationKind, "PROMOTE_TOPOLOGY")
    assert MutationKind.EVOLVE_TOPOLOGY == "evolve_topology"
    assert MutationKind.PROMOTE_TOPOLOGY == "promote_topology"


# ── End-to-end: realtime → topology route ─────────────────────


def test_turn_params_carries_topology_id() -> None:
    """``turn/start`` payload's ``topologyId`` must decode into TurnParams."""
    from runtime.protocol.items import TurnParams

    params = TurnParams.model_validate(
        {
            "threadId": "thr_1",
            "input": [],
            "topologyId": "team-A",
        }
    )
    assert params.topology_id == "team-A"


def test_topology_id_round_trips_through_alias() -> None:
    from runtime.protocol.items import TurnParams

    p = TurnParams.model_validate(
        {
            "threadId": "t",
            "input": [],
            "topologyId": "abc",
        }
    )
    dumped = p.model_dump(by_alias=True)
    assert dumped["topologyId"] == "abc"


def test_team_runner_records_run_to_perf_log(tmp_path: Path) -> None:
    """Smoke: TeamRunner + record_run end-to-end writes JSONL."""
    from runtime.safety.organization.performance_log import (
        read_runs,
        record_run,
    )

    topology = TeamTopology(
        name="e2e-team",
        protocol=CoordinationProtocol.SEQUENTIAL,
        agents={Role.GENERATOR: AgentSpec(agent_id="g")},
        task_bucket="e2e",
    )
    runner = TeamRunner(
        role_caller=_stub_caller(
            {
                "g": {"output": "answered", "success": True},
            }
        )
    )
    result = runner.run(topology, "do thing")
    assert result.success is True

    log_path = tmp_path / "perf.jsonl"
    record_run(result, path=log_path, extra={"smoke": True})
    rows = read_runs(path=log_path)
    assert len(rows) == 1
    assert rows[0]["topology"] == "e2e-team"
    assert rows[0]["task_bucket"] == "e2e"
    assert rows[0]["extra"]["smoke"] is True


# ── ① 失败隔离 + 部分产出继续 ─────────────────────────────────


def test_team_runner_sequential_keeps_partial_output_on_error() -> None:
    """角色失败但有部分产出时, 该产出仍传给下游并被采用."""
    topology = TeamTopology(
        name="partial",
        protocol=CoordinationProtocol.SEQUENTIAL,
        agents={
            Role.PLANNER: AgentSpec(agent_id="p"),
            Role.GENERATOR: AgentSpec(agent_id="g"),
        },
    )
    runner = TeamRunner(
        role_caller=_stub_caller(
            {
                "p": {"output": "partial plan", "success": False, "error": "timeout"},
                "g": {"output": "built on partial plan", "success": True},
            }
        )
    )
    result = runner.run(topology, "x")
    assert result.success is True
    assert result.final_output == "built on partial plan"
    assert result.degraded_roles == ["planner"]
    # 下游 generator 的 prompt 里应包含上一角色的部分产出 + 失败标注。
    prompts: list[str] = []
    for out in result.role_outputs:
        prompts.append(out.output)
    assert "partial plan" in prompts[0]


def test_team_runner_all_failed_is_fatal() -> None:
    """所有角色都失败且无产出 → 判整体失败."""
    topology = TeamTopology(
        name="allfail",
        protocol=CoordinationProtocol.SEQUENTIAL,
        agents={
            Role.PLANNER: AgentSpec(agent_id="p"),
            Role.GENERATOR: AgentSpec(agent_id="g"),
        },
    )
    runner = TeamRunner(
        role_caller=_stub_caller(
            {
                "p": {"output": "", "success": False, "error": "boom"},
                "g": {"output": "", "success": False, "error": "quota"},
            }
        )
    )
    result = runner.run(topology, "x")
    assert result.success is False
    assert result.error is not None
    assert set(result.degraded_roles) == {"planner", "generator"}


# ── ③ critic 反驳 → generator 重写 ────────────────────────────


def test_critic_rewrite_loop_runs_when_critic_flags_issues() -> None:
    """critic 提出问题时, generator 会被要求重写并计入 revision_rounds."""
    topology = TeamTopology(
        name="revise",
        protocol=CoordinationProtocol.SEQUENTIAL,
        agents={
            Role.PLANNER: AgentSpec(agent_id="p"),
            Role.GENERATOR: AgentSpec(agent_id="g"),
            Role.CRITIC: AgentSpec(agent_id="c"),
            Role.SYNTHESIZER: AgentSpec(agent_id="s"),
        },
    )
    calls: list[tuple[str, str]] = []

    def caller(*, agent_id, prompt, **_kw):
        calls.append((agent_id, prompt))
        if agent_id == "p":
            return {"output": "plan", "success": True}
        if agent_id == "g":
            n_gen = sum(1 for (aid, _) in calls if aid == "g")
            if n_gen == 1:
                return {"output": "draft v1", "success": True}
            return {"output": "draft v2 revised", "success": True}
        if agent_id == "c":
            return {"output": "问题: 缺少风险分析, 需补充", "success": True}
        # synthesizer
        return {"output": "final report", "success": True}

    events: list[dict[str, Any]] = []
    runner = TeamRunner(role_caller=caller, event_emitter=events.append)
    result = runner.run(topology, "x")
    assert result.revision_rounds >= 1
    assert result.final_output == "final report"
    # ③ 修订轮次以 team_revision_start 事件显式发出, 供网关渲染"修订 #N"标记。
    rev_events = [e for e in events if e["type"] == "team_revision_start"]
    assert rev_events, "expected team_revision_start marker events"
    assert rev_events[0]["round_no"] == 1
    # generator 至少被调用 2 次 (初始 + 修订)。
    gen_calls = sum(1 for (aid, _) in calls if aid == "g")
    assert gen_calls >= 2
    # 修订 prompt 应包含批评意见。
    rev_prompts = [pr for (aid, pr) in calls if aid == "g" and "critic-revision" in pr]
    assert rev_prompts, "expected a critic-revision prompt"
    assert "问题" in rev_prompts[0]


def test_critic_clean_verdict_skips_rewrite() -> None:
    """critic 判定没有问题 → 不触发重写."""
    topology = TeamTopology(
        name="norevise",
        protocol=CoordinationProtocol.SEQUENTIAL,
        agents={
            Role.PLANNER: AgentSpec(agent_id="p"),
            Role.GENERATOR: AgentSpec(agent_id="g"),
            Role.CRITIC: AgentSpec(agent_id="c"),
            Role.SYNTHESIZER: AgentSpec(agent_id="s"),
        },
    )
    calls: list[tuple[str, str]] = []

    def caller(*, agent_id, prompt, **_kw):
        calls.append((agent_id, prompt))
        if agent_id == "p":
            return {"output": "plan", "success": True}
        if agent_id == "g":
            return {"output": "draft", "success": True}
        if agent_id == "c":
            return {"output": "未发现问题, 一切正常", "success": True}
        return {"output": "final", "success": True}

    runner = TeamRunner(role_caller=caller)
    result = runner.run(topology, "x")
    assert result.revision_rounds == 0
    assert result.final_output == "final"
    gen_calls = sum(1 for (aid, _) in calls if aid == "g")
    assert gen_calls == 1


# ── ② 并行副本交叉验证 ────────────────────────────────────────


def test_parallel_replicas_cross_validate_via_critic() -> None:
    """多副本角色跑完后, critic 对全部副本产出做交叉核查."""
    topology = TeamTopology(
        name="xcheck",
        protocol=CoordinationProtocol.PARALLEL,
        agents={
            Role.PLANNER: AgentSpec(agent_id="p"),
            Role.RESEARCHER: AgentSpec(agent_id="r", parallel_replicas=2),
            Role.CRITIC: AgentSpec(agent_id="c"),
            Role.SYNTHESIZER: AgentSpec(agent_id="s"),
        },
    )
    calls: list[tuple[str, str]] = []

    def caller(*, agent_id, prompt, **_kw):
        calls.append((agent_id, prompt))
        if agent_id == "p":
            return {"output": "plan: 3 subproblems", "success": True}
        if agent_id == "r":
            return {"output": f"researcher {prompt.count('replica_index')}", "success": True}
        if agent_id == "c":
            return {"output": "交叉核查: 副本1与副本2结论重叠", "success": True}
        return {"output": "final report", "success": True}

    events: list[dict[str, Any]] = []
    runner = TeamRunner(role_caller=caller, event_emitter=events.append)
    result = runner.run(topology, "x")
    assert result.final_output == "final report"
    # ② 并行阶段与交叉核查都以事件显式发出, 供网关渲染阶段标记。
    types = [e["type"] for e in events]
    assert "team_parallel_start" in types
    assert "team_cross_check_start" in types
    par = next(e for e in events if e["type"] == "team_parallel_start")
    assert par["replicas"] == 2
    # critic 被交叉核查 prompt 调用过。
    xcheck_prompts = [pr for (aid, pr) in calls if aid == "c" and "cross-validation" in pr]
    assert xcheck_prompts, "expected a cross-validation critic pass"
    assert "replica 1" in xcheck_prompts[0]
    # 交叉核查产出带 metadata 标记。
    cross_outputs = [o for o in result.role_outputs if o.metadata.get("cross_validation")]
    assert len(cross_outputs) == 1
