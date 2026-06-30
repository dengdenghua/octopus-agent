"""Turn planning: mode + @mentions → who acts this turn (the auto-mode seam)."""

from __future__ import annotations

from runtime.memory.cowork.group import ContextGrant, GroupState, Member
from runtime.memory.cowork.group_store import GroupStore
from runtime.memory.cowork.service import invite_member, set_mode
from runtime.memory.cowork.turn_plan import plan_turn
from runtime.platform.models import ParsedIntent
from runtime.sensing.gateway.realtime_turn_lifecycle import _inject_cowork_turn_plan


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


def test_project_mode_hands_off_to_project_os() -> None:
    state = GroupState(roster=_agents("lead", "helper"), mode="project")
    plan = plan_turn(state, "ship the roadmap")
    assert plan.responders == []
    assert plan.is_multi is False
    assert "milestone engine" in plan.reason


def test_project_mode_ignores_chat_mentions() -> None:
    state = GroupState(roster=_agents("lead", "helper"), mode="project")
    plan = plan_turn(state, "@agent:helper quick answer")
    assert plan.addressed == ["helper"]
    assert plan.responders == []
    assert "milestone engine" in plan.reason


def test_mention_overrides_mode() -> None:
    # Even in swarm, an explicit @mention narrows to that agent.
    state = GroupState(roster=_agents("alice", "bob"), mode="swarm")
    plan = plan_turn(state, "@agent:alice just you")
    assert plan.responders == ["alice"]


def test_realtime_intent_gets_cowork_turn_plan(tmp_path) -> None:
    store = GroupStore(base_dir=tmp_path)
    invite_member(store, "thread-1", actor="u", target_id="db-agent", kind="agent")
    invite_member(store, "thread-1", actor="u", target_id="ui-agent", kind="agent")
    set_mode(store, "thread-1", actor="u", mode="swarm")
    runtime = type("Runtime", (), {"_cowork_group_store": store})()
    intent = ParsedIntent(
        raw="check it",
        intent_type="task",
        normalized_goal="check it",
        user_context={},
    )

    _inject_cowork_turn_plan(
        runtime,
        thread_id="thread-1",
        text="check it",
        intent=intent,
    )

    assert intent.user_context["cowork_mode"] == "swarm"
    assert intent.user_context["cowork_is_multi"] is True
    assert intent.user_context["cowork_responders"] == ["db-agent", "ui-agent"]
    assert intent.user_context["cowork_plan"]["reason"].startswith("swarm")


def test_realtime_intent_marks_project_mode_without_responders(tmp_path) -> None:
    store = GroupStore(base_dir=tmp_path)
    invite_member(store, "thread-1", actor="u", target_id="db-agent", kind="agent")
    invite_member(store, "thread-1", actor="u", target_id="ui-agent", kind="agent")
    set_mode(store, "thread-1", actor="u", mode="project")
    runtime = type("Runtime", (), {"_cowork_group_store": store})()
    intent = ParsedIntent(
        raw="ship it",
        intent_type="task",
        normalized_goal="ship it",
        user_context={},
    )

    _inject_cowork_turn_plan(
        runtime,
        thread_id="thread-1",
        text="ship it",
        intent=intent,
    )

    assert intent.user_context["cowork_mode"] == "project"
    assert intent.user_context["cowork_is_multi"] is False
    assert intent.user_context["cowork_responders"] == []
    assert "milestone engine" in intent.user_context["cowork_plan"]["reason"]
