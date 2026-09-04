"""Deterministic selection and role assignment for internal team patterns."""

from __future__ import annotations

from runtime.execution.agents.team_patterns import (
    is_explicit_group_work_request,
    pattern_member_role,
    select_team_pattern,
)


def test_presence_uses_roster_state_in_every_mode() -> None:
    decision = select_team_pattern("大家都在线么？", mode="cluster", member_count=4)

    assert decision.spec.id == "presence_check"
    assert decision.spec.execution == "presence"
    assert decision.spec.debate_rounds == 0


def test_group_greeting_does_not_wake_the_team() -> None:
    assert is_explicit_group_work_request("大家好") is False
    assert is_explicit_group_work_request("大家一起吃饭") is False

    decision = select_team_pattern("大家好", mode="chat", member_count=4)

    assert decision.spec.id == "focused_reply"
    assert decision.spec.execution == "focused"


def test_natural_group_work_request_uses_parallel_roundtable() -> None:
    assert is_explicit_group_work_request("大家一起看下这个方案") is True

    decision = select_team_pattern(
        "大家一起看下这个方案",
        mode="chat",
        member_count=4,
    )

    assert decision.spec.id == "parallel_roundtable"
    assert decision.spec.execution == "fanout"
    assert decision.spec.debate_rounds == 1


def test_review_request_uses_two_round_adversarial_pattern() -> None:
    decision = select_team_pattern(
        "大家评审这个方案，找出风险并验证",
        mode="chat",
        member_count=4,
    )

    assert decision.spec.id == "adversarial_review"
    assert decision.spec.execution == "fanout"
    assert decision.spec.debate_rounds == 2


def test_swarm_is_parallel_unless_review_depth_is_needed() -> None:
    parallel = select_team_pattern("给我几个方向", mode="swarm", member_count=3)
    review = select_team_pattern("验证边界和失败路径", mode="swarm", member_count=3)

    assert parallel.spec.id == "parallel_roundtable"
    assert review.spec.id == "adversarial_review"


def test_single_mention_stays_focused_even_in_swarm() -> None:
    decision = select_team_pattern(
        "@agent:alice 只看这个问题",
        mode="swarm",
        member_count=4,
        addressed_count=1,
    )

    assert decision.spec.id == "focused_reply"
    assert decision.spec.execution == "focused"


def test_cluster_uses_coordinator_without_creating_a_public_mode() -> None:
    decision = select_team_pattern("推进实现", mode="cluster", member_count=4)

    assert decision.spec.id == "coordinated_execution"
    assert decision.spec.execution == "orchestrated"


def test_adversarial_roles_are_stable_and_bounded() -> None:
    roles = [pattern_member_role("adversarial_review", index) for index in range(6)]

    assert roles == [
        "proposer",
        "critic",
        "verifier",
        "alternative",
        "alternative",
        "alternative",
    ]
