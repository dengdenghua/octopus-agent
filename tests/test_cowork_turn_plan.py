"""Turn planning: mode + @mentions → who acts this turn (the auto-mode seam)."""

from __future__ import annotations

from runtime.memory.cowork.group import ContextGrant, GroupState, Member
from runtime.memory.cowork.turn_plan import plan_turn


def _agents(*ids, role="participant", muted=False):
    return [Member(i, "agent", role, 0, ContextGrant(), muted) for i in ids]


def test_one_to_one_responds_without_mention() -> None:
    state = GroupState(roster=_agents("alice"), mode="chat")
    plan = plan_turn(state, "hi there")
    assert plan.responders == ["alice"]
    assert plan.is_multi is False
    assert "1:1" in plan.reason


def test_group_chat_waits_for_mention() -> None:
    state = GroupState(roster=_agents("alice", "bob"), mode="chat")
    plan = plan_turn(state, "what does everyone think?")
    assert plan.responders == []  # no @ → wait
    assert "waiting" in plan.reason


def test_at_mention_routes_to_addressed_agent() -> None:
    state = GroupState(roster=_agents("alice", "bob"), mode="chat")
    plan = plan_turn(state, "hey @agent:bob can you take this")
    assert plan.responders == ["bob"]
    assert plan.addressed == ["bob"]
    assert plan.is_multi is False


def test_swarm_runs_all_agents_in_parallel() -> None:
    state = GroupState(roster=_agents("alice", "bob"), mode="swarm")
    plan = plan_turn(state, "divide and conquer")
    assert set(plan.responders) == {"alice", "bob"}
    assert plan.is_multi is True
    assert "swarm" in plan.reason


def test_cluster_routes_to_leader() -> None:
    state = GroupState(roster=_agents("lead", "helper"), mode="cluster")
    plan = plan_turn(state, "let's plan this")
    assert plan.responders == ["lead"]
    assert plan.is_multi is False
    assert "cluster" in plan.reason


def test_mention_overrides_mode() -> None:
    # Even in swarm, an explicit @mention narrows to that agent.
    state = GroupState(roster=_agents("alice", "bob"), mode="swarm")
    plan = plan_turn(state, "@agent:alice just you")
    assert plan.responders == ["alice"]
