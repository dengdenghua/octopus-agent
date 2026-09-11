"""成员身份三态 + 驱动轴：纯 AI / 绑定角色（数字员工）/ 真人，托管 vs 接管。

The group roster answers two orthogonal questions that the old binary
``agent|human`` kind could not:

1. 谁是这个成员 —— accountability: bare AI (platform answers), 数字员工
   (a named human answers), or a person.
2. 谁在驾驶 —— driver: the AI itself, or its owner who took over.

The message side records the resolved identity per line, server-side, so the
transcript stays auditable after a takeover changes the roster.
"""

from __future__ import annotations

from runtime.memory.cowork.group import (
    MemberEvent,
    fold_state,
    normalize_member_kind,
    responders,
    sender_identity,
)
from runtime.memory.cowork.room_messages import RoomMessageStore


def _base_events() -> list[MemberEvent]:
    return [
        MemberEvent(action="invite", actor="boss", target_id="U1", target_kind="human", seq=1),
        MemberEvent(action="invite", actor="boss", target_id="A1", target_kind="agent", seq=2),
        MemberEvent(
            action="invite",
            actor="boss",
            target_id="R1",
            target_kind="role",
            owner="U1",
            seq=3,
        ),
    ]


def test_kind_normalization_never_manufactures_a_role() -> None:
    assert normalize_member_kind("agent") == "agent"
    assert normalize_member_kind("role") == "role"
    assert normalize_member_kind("human") == "human"
    # Unknown values collapse to the *narrowest* claim: a bad value can never
    # conjure a 数字员工 that no human answers for.
    assert normalize_member_kind("wat") == "agent"
    assert normalize_member_kind(None) == "agent"


def test_fold_assigns_owners_and_default_drivers() -> None:
    state = fold_state(_base_events())
    human = state.member("U1")
    agent = state.member("A1")
    role = state.member("R1")
    assert (human.kind, human.driver, human.accountable_owner) == ("human", "human", "")
    assert (agent.kind, agent.driver, agent.accountable_owner) == ("agent", "ai", "")
    assert (role.kind, role.driver, role.accountable_owner) == ("role", "ai", "U1")
    assert state.unattributed == []


def test_role_invite_without_owner_is_unattributed() -> None:
    events = [
        MemberEvent(
            action="invite", actor="boss", target_id="R9", target_kind="role", seq=1
        )
    ]
    state = fold_state(events)
    member = state.member("R9")
    assert member.identity_problem() == "role member without an accountable owner"
    assert state.unattributed and state.unattributed[0].id == "R9"
    # The problem surfaces in the wire dict too — the UI can banner it.
    assert member.to_dict()["identity_problem"]


def test_takeover_removes_member_from_responders_and_back() -> None:
    swarm = MemberEvent(action="mode", actor="boss", mode="swarm", seq=4)
    state = fold_state([*_base_events(), swarm])
    assert responders(state) == ["A1", "R1"]

    takeover = MemberEvent(action="drive", actor="U1", target_id="R1", driver="human", seq=5)
    taken = fold_state([*_base_events(), swarm, takeover])
    # While the owner holds the wheel the 数字员工 must stand down: one mouth,
    # one driver. The bare agent keeps responding.
    assert responders(taken) == ["A1"]
    member = taken.member("R1")
    assert member.is_takeover
    assert (member.kind, member.driver) == ("role", "human")
    assert [m.id for m in taken.takeovers] == ["R1"]

    handback = MemberEvent(action="drive", actor="U1", target_id="R1", driver="ai", seq=6)
    handed = fold_state([*_base_events(), swarm, takeover, handback])
    assert responders(handed) == ["A1", "R1"]
    assert handed.takeovers == []


def test_human_member_can_never_be_ai_driven() -> None:
    forged = MemberEvent(action="drive", actor="x", target_id="U1", driver="ai", seq=9)
    state = fold_state([*_base_events(), forged])
    # Refused at fold time: the driver stays human, so there is nothing to
    # report — and the member does not silently become unattributable either.
    member = state.member("U1")
    assert member.driver == "human"
    assert member.identity_problem() is None


def test_sender_identity_is_read_off_the_roster_not_the_message() -> None:
    taken = fold_state(
        [
            *_base_events(),
            MemberEvent(action="drive", actor="U1", target_id="R1", driver="human", seq=5),
        ]
    )
    assert sender_identity(taken, "R1") == ("role", "human")
    assert sender_identity(taken, "A1") == ("agent", "ai")
    assert sender_identity(taken, "U1") == ("human", "human")
    # An unknown sender stays unknown — guessing "agent" would fabricate an
    # attribution in the audit trail.
    assert sender_identity(taken, "ghost") == ("unknown", "unknown")
    assert sender_identity(taken, "") == ("unknown", "unknown")
    assert sender_identity(None, "A1") == ("unknown", "unknown")


def test_takeover_does_not_rewritten_history_only_new_lines() -> None:
    tmp = _tmp_store()
    store = RoomMessageStore(base_dir=tmp)
    state = fold_state(_base_events())
    kind_before, driver_before = sender_identity(state, "R1")
    store.append(
        "room-1",
        text="AI 阶段产出",
        participant_id="R1",
        sender_kind=kind_before,
        sender_driver=driver_before,
    )
    taken = fold_state(
        [
            *_base_events(),
            MemberEvent(action="drive", actor="U1", target_id="R1", driver="human", seq=5),
        ]
    )
    kind_after, driver_after = sender_identity(taken, "R1")
    store.append(
        "room-1",
        text="接管后的产出",
        participant_id="R1",
        sender_kind=kind_after,
        sender_driver=driver_after,
    )
    history = store.history("room-1")
    # 接管绝不改写历史归属：接管前 AI 发的仍是 (role, ai)。
    assert (history[0]["sender_kind"], history[0]["sender_driver"]) == ("role", "ai")
    assert (history[1]["sender_kind"], history[1]["sender_driver"]) == ("role", "human")


def test_message_store_validates_and_defaults_sender_fields() -> None:
    tmp = _tmp_store()
    store = RoomMessageStore(base_dir=tmp)
    store.append("room-1", text="旧库迁移的行")  # legacy row: no attribution
    row = store.history("room-1")[0]
    assert row["sender_kind"] == "unknown"
    assert row["sender_driver"] == "unknown"
    try:
        store.append("room-1", text="x", sender_kind="ai")
    except ValueError as exc:
        assert "sender_kind" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("invalid sender_kind must be rejected")


def test_is_one_to_one_counts_digital_employees_on_the_ai_side() -> None:
    # A 数字员工 and its owner is still a 1:1, not a team.
    state = fold_state(_base_events()[:1] + _base_events()[2:])
    assert state.is_one_to_one
    both = fold_state([*_base_events()[:1], *_base_events()[1:]])
    assert not both.is_one_to_one


def test_service_set_driver_enforces_takeover_gates(tmp_path) -> None:
    import pytest

    from runtime.memory.cowork.group_store import GroupStore
    from runtime.memory.cowork.service import invite_member, set_driver

    store = GroupStore(base_dir=tmp_path)
    thread_id = "t-service-driver"
    invite_member(store, thread_id, actor="boss", target_id="U1", kind="human")
    invite_member(store, thread_id, actor="boss", target_id="A1", kind="agent")
    # A role invite without an owner is refused at the write path: an
    # unattributable 数字员工 must not be creatable.
    with pytest.raises(ValueError, match="accountable owner"):
        invite_member(store, thread_id, actor="boss", target_id="R1", kind="role")
    invite_member(
        store, thread_id, actor="boss", target_id="R1", kind="role", owner="U1"
    )

    # 接管 → the roster answers "who is driving" and responders drop the member.
    set_driver(store, thread_id, actor="U1", target_id="R1", driver="human")
    state = store.state(thread_id)
    assert state.member("R1").is_takeover
    assert "R1" not in responders(state)

    # 交还 → back to 托管.
    set_driver(store, thread_id, actor="U1", target_id="R1", driver="ai")
    assert not store.state(thread_id).member("R1").is_takeover

    # A human is never AI-driven, and garbage drivers are refused.
    with pytest.raises(ValueError, match="human"):
        set_driver(store, thread_id, actor="x", target_id="U1", driver="ai")
    with pytest.raises(ValueError, match="driver"):
        set_driver(store, thread_id, actor="x", target_id="A1", driver="manual")
    with pytest.raises(ValueError, match="not a member"):
        set_driver(store, thread_id, actor="x", target_id="ghost", driver="ai")


def _tmp_store():
    import tempfile
    from pathlib import Path

    return Path(tempfile.mkdtemp())
