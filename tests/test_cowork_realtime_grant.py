"""Realtime single-responder path enforces the cowork context grant.

Closes the gap where the realtime react path fed a responder the full thread
history regardless of their grant (async already sliced via context_view, the
realtime path did not).
"""

from __future__ import annotations

from types import SimpleNamespace

from runtime.memory.cowork.group import ContextGrant, MemberEvent
from runtime.memory.cowork.group_store import GroupStore
from runtime.memory.cowork.service import set_mode
from runtime.sensing.gateway._team_stream_group_fanout import _select_fanout_members
from runtime.sensing.gateway.realtime_turn_lifecycle import _inject_cowork_turn_plan

MSGS = [{"role": "user", "content": f"m{i}"} for i in range(6)]


def _runtime(store: GroupStore) -> SimpleNamespace:
    return SimpleNamespace(_cowork_group_store=store)


def _intent() -> SimpleNamespace:
    return SimpleNamespace(user_context={"conversation_messages": list(MSGS)})


def test_from_join_responder_only_sees_post_join_history(tmp_path) -> None:
    store = GroupStore(base_dir=tmp_path)
    # Sole agent, pulled in at message 3 with a from_join grant.
    store.append(
        "t1",
        MemberEvent(
            action="invite",
            actor="u",
            target_id="alice",
            target_kind="agent",
            grant=ContextGrant(scope="from_join"),
            at_message=3,
        ),
    )
    intent = _intent()
    _inject_cowork_turn_plan(_runtime(store), thread_id="t1", text="hi", intent=intent)

    msgs = intent.user_context["conversation_messages"]
    assert [m["content"] for m in msgs] == ["m3", "m4", "m5"]  # nothing pre-join leaks


def test_all_grant_responder_keeps_full_history(tmp_path) -> None:
    store = GroupStore(base_dir=tmp_path)
    store.append(
        "t2",
        MemberEvent(
            action="invite",
            actor="u",
            target_id="bob",
            target_kind="agent",
            grant=ContextGrant(scope="all"),
            at_message=3,
        ),
    )
    intent = _intent()
    _inject_cowork_turn_plan(_runtime(store), thread_id="t2", text="hi", intent=intent)

    msgs = intent.user_context["conversation_messages"]
    assert [m["content"] for m in msgs] == ["m0", "m1", "m2", "m3", "m4", "m5"]


def test_focused_responder_gets_durable_manifest_without_chat_duplication(tmp_path) -> None:
    store = GroupStore(base_dir=tmp_path)
    store.append(
        "t-focused",
        MemberEvent(
            action="invite",
            actor="u",
            target_id="alice",
            target_kind="agent",
            grant=ContextGrant(scope="all"),
            at_message=0,
        ),
    )
    store.blackboard("t-focused").write(
        "decision:api",
        "继续使用事件流协议",
        writer="u",
    )
    intent = _intent()

    _inject_cowork_turn_plan(
        _runtime(store),
        thread_id="t-focused",
        text="下一步怎么做",
        intent=intent,
    )

    manifest = intent.user_context["cowork_context_manifest"]
    assert "octopus.cowork_context_manifest.v1" in manifest
    assert "继续使用事件流协议" in manifest
    assert "m0" not in manifest and "m5" not in manifest
    assert intent.user_context["cowork_context_plan_audit"]["durable_source_count"] == 1
    assert [m["content"] for m in intent.user_context["conversation_messages"]] == [
        "m0",
        "m1",
        "m2",
        "m3",
        "m4",
        "m5",
    ]


def test_multi_responder_history_is_pre_sliced_for_each_member(tmp_path) -> None:
    store = GroupStore(base_dir=tmp_path)
    store.append(
        "t3",
        MemberEvent(
            action="invite",
            actor="u",
            target_id="alice",
            target_kind="agent",
            grant=ContextGrant(scope="all"),
            at_message=0,
        ),
    )
    store.append(
        "t3",
        MemberEvent(
            action="invite",
            actor="u",
            target_id="bob",
            target_kind="agent",
            grant=ContextGrant(scope="from_join"),
            at_message=3,
        ),
    )
    set_mode(store, "t3", actor="u", mode="swarm")
    intent = _intent()

    _inject_cowork_turn_plan(_runtime(store), thread_id="t3", text="hi", intent=intent)

    histories = intent.user_context["cowork_member_context_messages"]
    assert [m["content"] for m in histories["alice"]] == [
        "m0",
        "m1",
        "m2",
        "m3",
        "m4",
        "m5",
    ]
    assert [m["content"] for m in histories["bob"]] == ["m3", "m4", "m5"]
    # Multi-member planning keeps the canonical conversation intact; only the
    # private copies handed to the steward are sliced.
    assert [m["content"] for m in intent.user_context["conversation_messages"]] == [
        "m0",
        "m1",
        "m2",
        "m3",
        "m4",
        "m5",
    ]


def test_no_group_store_is_a_noop(tmp_path) -> None:
    intent = _intent()
    _inject_cowork_turn_plan(SimpleNamespace(), thread_id="t1", text="hi", intent=intent)
    # No store → advisory no-op, history untouched.
    assert len(intent.user_context["conversation_messages"]) == 6


def test_explicit_mentions_route_context_and_calls_only_to_validated_responders() -> None:
    members = [
        {"name": "alice", "display_name": "Alice"},
        {"name": "bob", "display_name": "Bob"},
        {"name": "carol", "display_name": "Carol"},
    ]
    selected, audit = _select_fanout_members(
        {
            "cowork_plan": {"addressed": ["alice", "carol"]},
            "cowork_responders": ["alice", "carol"],
        },
        members,
    )

    assert [member["name"] for member in selected] == ["alice", "carol"]
    assert audit == {
        "schema": "octopus.cowork_member_routing.v1",
        "reason": "explicit_mentions",
        "available_member_count": 3,
        "selected_member_count": 2,
        "selected_agent_ids": ["alice", "carol"],
        "excluded_agent_ids": ["bob"],
    }


def test_group_request_without_mentions_keeps_the_active_roster() -> None:
    members = [
        {"name": "alice", "display_name": "Alice"},
        {"name": "bob", "display_name": "Bob"},
    ]
    selected, audit = _select_fanout_members(
        {
            "cowork_plan": {"addressed": []},
            "cowork_responders": [],
        },
        members,
    )

    assert selected == members
    assert audit["reason"] == "group_request_or_mode"
    assert audit["excluded_agent_ids"] == []
