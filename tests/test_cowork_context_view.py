"""Context-grant enforcement: a member only sees the history their grant permits."""

from __future__ import annotations

from runtime.memory.cowork.context_view import (
    materialize_messages,
    resolve_view,
    slice_messages,
    summarize_messages,
)
from runtime.memory.cowork.group import ContextGrant, GroupState, Member


def _member(scope, join=10, f=None, t=None):
    return Member(
        "spec",
        "agent",
        "participant",
        joined_at_message=join,
        grant=ContextGrant(scope=scope, from_msg=f, to_msg=t),
    )


def _state(member):
    return GroupState(roster=[member], mode="chat")


MSGS = [f"m{i}" for i in range(20)]  # 20 messages, indices 0..19


def test_all_grant_sees_everything() -> None:
    view = resolve_view(_state(_member("all")), "spec", max_message=19)
    assert view and view.message_range == (0, 19)
    assert slice_messages(view, MSGS) == MSGS


def test_from_join_hides_prior_private_context() -> None:
    view = resolve_view(_state(_member("from_join", join=8)), "spec", max_message=19)
    assert view.message_range == (8, 19)
    sliced = slice_messages(view, MSGS)
    assert sliced == MSGS[8:]  # nothing before message 8 leaks
    assert "m0" not in sliced and "m7" not in sliced


def test_range_grant_clamps_to_bounds() -> None:
    view = resolve_view(_state(_member("range", f=5, t=9)), "spec", max_message=19)
    assert slice_messages(view, MSGS) == ["m5", "m6", "m7", "m8", "m9"]
    # out-of-range hi is clamped, never raises
    wide = resolve_view(_state(_member("range", f=18, t=999)), "spec", max_message=19)
    assert slice_messages(wide, MSGS) == ["m18", "m19"]


def test_summary_grant_yields_no_raw_history() -> None:
    view = resolve_view(_state(_member("summary")), "spec", max_message=19)
    assert view.summary_only is True
    assert view.message_range is None
    assert slice_messages(view, MSGS) == []  # caller substitutes a summary


def test_summary_projection_keeps_milestones_but_not_chat_or_credentials() -> None:
    messages = [
        {"role": "user", "content": "午饭吃什么？"},
        {"role": "user", "content": "目标：周五完成发布"},
        {"role": "assistant", "content": "决定采用蓝绿发布，API_KEY=secret-value-123456"},
        {"role": "assistant", "content": "风险：数据库回滚尚未演练"},
    ]
    view = resolve_view(_state(_member("summary")), "spec", max_message=3)
    assert view is not None

    projected = materialize_messages(view, messages)
    text = "\n".join(str(item["content"]) for item in projected)
    assert "仅摘要授权" in text
    assert "周五完成发布" in text
    assert "蓝绿发布" in text
    assert "数据库回滚" in text
    assert "午饭吃什么" not in text
    assert "secret-value" not in text
    assert "已隐藏凭据" in text
    assert projected != messages


def test_summary_projection_is_bounded_and_prefers_latest_milestones() -> None:
    projected = summarize_messages(
        [{"content": f"决定：里程碑 {index}"} for index in range(10)],
        max_facts=3,
    )
    text = "\n".join(item["content"] for item in projected)
    assert len(projected) == 4  # stable authorization marker + three facts
    assert "里程碑 0" not in text
    assert "里程碑 7" in text
    assert "里程碑 9" in text


def test_summary_projection_does_not_repeat_current_request() -> None:
    current = "决定：立即切换到新的实现"
    view = resolve_view(_state(_member("summary")), "spec", max_message=1)
    assert view is not None
    projected = materialize_messages(
        view,
        [
            {"role": "assistant", "content": "目标：完成迁移"},
            {"role": "user", "content": current},
        ],
        current_message=current,
    )
    text = "\n".join(item["content"] for item in projected)
    assert "完成迁移" in text
    assert "新的实现" not in text


def test_non_member_has_no_view() -> None:
    assert resolve_view(_state(_member("all")), "stranger", max_message=19) is None


def test_empty_range_never_raises() -> None:
    view = resolve_view(_state(_member("range", f=50, t=60)), "spec", max_message=19)
    assert slice_messages(view, MSGS) == []  # entirely past the end
