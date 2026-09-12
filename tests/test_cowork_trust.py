"""成员信任分：外包/外部成员进群前"这个人靠不靠谱"要有可解释的依据。

分数必须可解释（components 全量暴露）、分母不可造假（事件源走封签链）、
无记录时如实报"无记录"而不是编一个中立证据。
"""

from __future__ import annotations

from runtime.memory.cowork.group import ContextGrant, GroupState, Member, MemberEvent
from runtime.memory.cowork.trust import (
    BASE_NO_RECORD,
    member_trust,
    takeover_counts,
    trust_report,
)


def _member(member_id: str, kind: str = "agent", driver: str = "ai") -> Member:
    return Member(
        id=member_id,
        kind=kind,  # type: ignore[arg-type]
        role="participant",
        joined_at_message=None,
        grant=ContextGrant(),
        driver=driver,  # type: ignore[arg-type]
    )


def _state(*members: Member) -> GroupState:
    return GroupState(roster=list(members))


def _task(**overrides: object) -> dict:
    task = {
        "id": "t1",
        "status": "done",
        "assigned_agent": "",
        "assigned_role": "",
        "attempts": 1,
        "review_mode": "ai_auto",
        "reviewed_by": "",
        "output": None,
    }
    task.update(overrides)
    return task


def _drive_event(target_id: str, driver: str = "human") -> MemberEvent:
    return MemberEvent(
        action="drive",
        actor="owner-1",
        target_id=target_id,
        driver=driver,  # type: ignore[arg-type]
    )


# ── 无记录 ──────────────────────────────────────────


def test_no_record_is_honest():
    report = member_trust(_member("bot-a"), [])
    assert report["score"] == BASE_NO_RECORD
    assert report["label"] == "无记录"
    assert report["sample_size"] == 0


def test_no_record_reports_member_kind():
    report = member_trust(_member("alice", kind="human", driver="human"), [])
    assert report["kind"] == "human"
    assert report["label"] == "无记录"


# ── 交付归因 ──────────────────────────────────────────


def test_agent_attribution_prefers_assigned_agent():
    member = _member("bot-a")
    tasks = [
        _task(assigned_agent="bot-a", status="done"),
        _task(assigned_role="bot-a", status="failed"),  # 无人认领时按角色退回
        _task(assigned_agent="bot-b", assigned_role="bot-a", status="done"),
    ]
    report = member_trust(member, tasks)
    # assigned_agent 命中优先：task1 → bot-a，task2 角色退回 → bot-a，
    # task3 已派给 bot-b，不再按角色重复归因。
    assert report["components"]["completed"] == 1
    assert report["components"]["failed"] == 1


def test_human_attribution_requires_signature():
    member = _member("alice", kind="human", driver="human")
    tasks = [
        _task(review_mode="human_run", output={"completed_by": "alice"}),
        _task(review_mode="human_run", output={"completed_by": "bob"}),
        _task(review_mode="human_run", output=None),
        _task(assigned_agent="alice", status="done"),  # AI 派单不算真人执行
    ]
    report = member_trust(member, tasks)
    assert report["components"]["completed"] == 1


# ── 评分方向 ──────────────────────────────────────────


def test_all_done_scores_high():
    member = _member("bot-a")
    tasks = [_task(assigned_agent="bot-a") for _ in range(4)]
    report = member_trust(member, tasks)
    assert report["score"] == 95  # floor + span，全完成封顶
    assert report["label"] == "可靠"


def test_all_failed_floors_low():
    member = _member("bot-a")
    tasks = [_task(assigned_agent="bot-a", status="failed") for _ in range(3)]
    report = member_trust(member, tasks)
    assert report["score"] == 40
    assert report["label"] == "高风险"


def test_rework_penalty_applies_and_caps():
    member = _member("bot-a")
    tasks = [_task(assigned_agent="bot-a", attempts=1)]
    base = member_trust(member, tasks)["score"]
    reworked = member_trust(
        member, [_task(assigned_agent="bot-a", attempts=9)]
    )["score"]
    assert reworked == base - 15  # 封顶 -15


def test_human_signed_bonus():
    member = _member("bot-a")
    plain = [_task(assigned_agent="bot-a") for _ in range(3)]
    signed = [_task(assigned_agent="bot-a", review_mode="operator") for _ in range(3)]
    assert member_trust(member, signed)["score"] > member_trust(member, plain)["score"]


def test_takeover_penalty_applies_and_caps():
    member = _member("bot-a")
    good = [_task(assigned_agent="bot-a") for _ in range(5)]
    clean = member_trust(member, good, takeovers=0)["score"]
    once = member_trust(member, good, takeovers=1)["score"]
    capped = member_trust(member, good, takeovers=10)["score"]
    assert once == clean - 5
    assert capped == clean - 20  # 封顶 -20


def test_takeover_only_still_penalized():
    # 没有交付记录但被接管过：不能装作"无记录"
    report = member_trust(_member("bot-a"), [], takeovers=2)
    assert report["sample_size"] == 0
    assert report["score"] < BASE_NO_RECORD
    assert report["label"] != "无记录"


def test_score_clamped_to_zero():
    member = _member("bot-a")
    tasks = [_task(assigned_agent="bot-a", status="failed", attempts=9)]
    report = member_trust(member, tasks, takeovers=10)
    assert 0 <= report["score"] <= 100


# ── 事件计数 ──────────────────────────────────────────


def test_takeover_counts_only_human_drives():
    events = [
        _drive_event("bot-a"),
        _drive_event("bot-a", driver="ai"),  # 交还
        _drive_event("bot-b"),
        MemberEvent(action="mode", actor="owner-1"),
    ]
    assert takeover_counts(events) == {"bot-a": 1, "bot-b": 1}


# ── 整群报告 ──────────────────────────────────────────


def test_trust_report_sorts_and_exposes_weights():
    state = _state(_member("bot-b"), _member("bot-a"))
    tasks = [
        _task(id="t1", assigned_agent="bot-a", status="done"),
        _task(id="t2", assigned_agent="bot-b", status="failed"),
    ]
    report = trust_report(state, tasks, [_drive_event("bot-b")])
    scores = report["scores"]
    assert [s["member_id"] for s in scores] == ["bot-a", "bot-b"]
    assert scores[0]["score"] > scores[1]["score"]
    assert report["weights"]["takeover_penalty"] > 0
    assert report["basis"] == "sealed_events+review_chain"
