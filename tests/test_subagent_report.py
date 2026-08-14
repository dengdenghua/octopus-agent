"""Subagent report lane tests — dsh ``tool-subagent-report`` port."""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.execution.subagents import bridge
from runtime.execution.subagents.sessions import (
    DEFAULT_MAX_CONSECUTIVE_WAKES,
    SubagentReport,
    SubagentSessionStore,
    get_subagent_session_store,
    set_subagent_session_store,
)


def _store(tmp_path: Path) -> SubagentSessionStore:
    return SubagentSessionStore(base_dir=tmp_path / "sessions")


# ─── store: report persistence ───────────────────────────────────────────


def test_append_report_persists_across_instances(tmp_path: Path) -> None:
    store = _store(tmp_path)
    session = store.create(agent_id="researcher", thread_id="th-1")
    store.append_report(session.session_id, content="找到 3 个专利", delivery="wakeup")
    store.append_report(session.session_id, content="第二个发现", delivery="quiet")

    fresh = SubagentSessionStore(base_dir=tmp_path / "sessions")
    loaded = fresh.get(session.session_id)
    assert loaded is not None
    assert len(loaded.reports) == 2
    assert loaded.reports[0].content == "找到 3 个专利"
    assert loaded.reports[0].delivery == "wakeup"
    assert loaded.reports[1].delivery == "quiet"


def test_append_report_rejects_empty_content(tmp_path: Path) -> None:
    store = _store(tmp_path)
    session = store.create(agent_id="researcher", thread_id="th-1")
    with pytest.raises(ValueError):
        store.append_report(session.session_id, content="   ")
    with pytest.raises(ValueError):
        store.append_report(session.session_id, content="")


def test_append_report_unknown_session_returns_none(tmp_path: Path) -> None:
    assert _store(tmp_path).append_report("missing", content="x") is None


# ─── delivery semantics ───────────────────────────────────────────────────


def test_pending_and_ack_advance_pointer(tmp_path: Path) -> None:
    store = _store(tmp_path)
    session = store.create(agent_id="researcher", thread_id="th-1")
    store.append_report(session.session_id, content="r1")
    store.append_report(session.session_id, content="r2")
    store.append_report(session.session_id, content="r3")

    assert [i for i, _ in store.pending_reports(session.session_id)] == [0, 1, 2]
    store.mark_reports_delivered(session.session_id, up_to_index=1)
    assert [i for i, _ in store.pending_reports(session.session_id)] == [2]

    # default acks through the latest
    store.append_report(session.session_id, content="r4")
    store.mark_reports_delivered(session.session_id)
    assert store.pending_reports(session.session_id) == []


def test_ack_never_moves_pointer_backward(tmp_path: Path) -> None:
    store = _store(tmp_path)
    session = store.create(agent_id="researcher", thread_id="th-1")
    store.append_report(session.session_id, content="r1")
    store.mark_reports_delivered(session.session_id)
    store.mark_reports_delivered(session.session_id, up_to_index=0)
    assert store.pending_reports(session.session_id) == []


def test_reports_prompt_renders_pending_only(tmp_path: Path) -> None:
    store = _store(tmp_path)
    session = store.create(agent_id="researcher", thread_id="th-1")
    assert store.reports_prompt(session) == ""

    store.append_report(session.session_id, content="结论一", delivery="quiet")
    store.append_report(session.session_id, content="结论二", delivery="wakeup")
    prompt = store.reports_prompt(store.get(session.session_id))
    assert "Subagent reports (child → parent)" in prompt
    assert "结论一" in prompt
    assert "(quiet)" in prompt
    assert "(wakeup)" in prompt

    store.mark_reports_delivered(session.session_id, up_to_index=0)
    prompt2 = store.reports_prompt(store.get(session.session_id))
    assert "结论一" not in prompt2
    assert "结论二" in prompt2


def test_reports_prompt_truncates_long_content(tmp_path: Path) -> None:
    store = _store(tmp_path)
    session = store.create(agent_id="researcher", thread_id="th-1")
    store.append_report(session.session_id, content="长" * 5000)
    prompt = store.reports_prompt(store.get(session.session_id))
    assert len(prompt) < 5000


def test_wakeup_hook_fires_and_failure_is_swallowed(tmp_path: Path) -> None:
    seen: list[tuple[str, SubagentReport]] = []
    store = SubagentSessionStore(
        base_dir=tmp_path / "sessions",
        on_report=lambda sid, report: seen.append((sid, report)),
    )
    session = store.create(agent_id="researcher", thread_id="th-1")
    store.append_report(session.session_id, content="wake me")
    assert len(seen) == 1
    assert seen[0][1].content == "wake me"

    bad = SubagentSessionStore(
        base_dir=tmp_path / "sessions",
        on_report=lambda sid, report: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    bad.append_report(session.session_id, content="still lands")
    loaded = bad.get(session.session_id)
    assert loaded is not None and loaded.reports[-1].content == "still lands"


# ─── bounded consecutive-wake budget (dsh tool-jobs.maxConsecutiveWakes) ────


def test_wake_budget_default_is_three(tmp_path: Path) -> None:
    assert DEFAULT_MAX_CONSECUTIVE_WAKES == 3


def test_wake_budget_limits_consecutive_wakes(tmp_path: Path) -> None:
    seen: list[str] = []
    store = SubagentSessionStore(
        base_dir=tmp_path / "sessions",
        on_report=lambda sid, report: seen.append(report.content),
        max_consecutive_wakes=2,
    )
    session = store.create(agent_id="researcher", thread_id="th-1")
    # Two wakeups within budget → both wake the parent.
    store.append_report(session.session_id, content="wake-1", delivery="wakeup")
    store.append_report(session.session_id, content="wake-2", delivery="wakeup")
    assert seen == ["wake-1", "wake-2"]
    # Third wakeup exceeds the budget → downgraded to quiet (no new wake).
    store.append_report(session.session_id, content="wake-3", delivery="wakeup")
    assert seen == ["wake-1", "wake-2"]
    loaded = store.get(session.session_id)
    assert loaded is not None
    assert loaded.reports[-1].delivery == "quiet"
    # Quiet reports never spend the budget and never wake.
    store.append_report(session.session_id, content="quiet-1", delivery="quiet")
    assert seen == ["wake-1", "wake-2"]


def test_wake_budget_untouched_by_quiet_reports(tmp_path: Path) -> None:
    seen: list[str] = []
    store = SubagentSessionStore(
        base_dir=tmp_path / "sessions",
        on_report=lambda sid, report: seen.append(report.content),
        max_consecutive_wakes=1,
    )
    session = store.create(agent_id="researcher", thread_id="th-1")
    store.append_report(session.session_id, content="quiet-a", delivery="quiet")
    # The single budget slot is still available for the next wakeup.
    store.append_report(session.session_id, content="wake-b", delivery="wakeup")
    assert seen == ["wake-b"]


def test_refill_wake_budget_resets_after_human_turn(tmp_path: Path) -> None:
    seen: list[str] = []
    store = SubagentSessionStore(
        base_dir=tmp_path / "sessions",
        on_report=lambda sid, report: seen.append(report.content),
        max_consecutive_wakes=1,
    )
    session = store.create(agent_id="researcher", thread_id="th-1")
    store.append_report(session.session_id, content="wake-1", delivery="wakeup")
    assert seen == ["wake-1"]
    # Budget exhausted → downgraded to quiet.
    store.append_report(session.session_id, content="wake-2", delivery="wakeup")
    assert seen == ["wake-1"]
    assert store.get(session.session_id).reports[-1].delivery == "quiet"
    # Parent claims a human turn → budget refills → wakeup works again.
    store.refill_wake_budget(session.session_id)
    store.append_report(session.session_id, content="wake-3", delivery="wakeup")
    assert seen == ["wake-1", "wake-3"]


def test_refill_wake_budget_unknown_session_is_noop(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.refill_wake_budget("not-a-real-session")  # no raise


def test_invalid_wake_budget_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        SubagentSessionStore(base_dir=tmp_path / "sessions", max_consecutive_wakes=-1)
    with pytest.raises(ValueError):
        SubagentSessionStore(base_dir=tmp_path / "sessions", max_consecutive_wakes=2.5)
    with pytest.raises(ValueError):
        SubagentSessionStore(base_dir=tmp_path / "sessions", max_consecutive_wakes=True)


def test_zero_wake_budget_never_wakes(tmp_path: Path) -> None:
    seen: list[str] = []
    store = SubagentSessionStore(
        base_dir=tmp_path / "sessions",
        on_report=lambda sid, report: seen.append(report.content),
        max_consecutive_wakes=0,
    )
    session = store.create(agent_id="researcher", thread_id="th-1")
    store.append_report(session.session_id, content="never", delivery="wakeup")
    assert seen == []
    assert store.get(session.session_id).reports[-1].delivery == "quiet"


# ─── busy owner semantics (dsh ``inject`` vs ``followup``) ───────────────


def test_wakeup_while_owner_busy_is_queued_not_woken(tmp_path: Path) -> None:
    seen: list[str] = []
    store = SubagentSessionStore(
        base_dir=tmp_path / "sessions",
        on_report=lambda sid, report: seen.append(report.content),
    )
    session = store.create(agent_id="researcher", thread_id="th-1")
    store.mark_owner_busy(session.session_id)
    store.append_report(session.session_id, content="mid-turn finding", delivery="wakeup")

    # No wake while the owner is mid-turn; the report is injected as queued.
    assert seen == []
    report = store.get(session.session_id).reports[-1]
    assert report.delivery == "queued"
    prompt = store.reports_prompt(store.get(session.session_id))
    assert "(queued)" in prompt


def test_busy_owner_does_not_consume_wake_budget(tmp_path: Path) -> None:
    seen: list[str] = []
    store = SubagentSessionStore(
        base_dir=tmp_path / "sessions",
        on_report=lambda sid, report: seen.append(report.content),
        max_consecutive_wakes=1,
    )
    session = store.create(agent_id="researcher", thread_id="th-1")
    store.mark_owner_busy(session.session_id)
    store.append_report(session.session_id, content="busy-1", delivery="wakeup")
    store.append_report(session.session_id, content="busy-2", delivery="wakeup")
    assert seen == []
    assert [r.delivery for r in store.get(session.session_id).reports] == [
        "queued",
        "queued",
    ]

    # The single budget slot was untouched: once the owner is idle again a
    # wakeup report still wakes (dsh ``inject`` never spends ``spentWakes``).
    store.mark_owner_idle(session.session_id)
    store.append_report(session.session_id, content="after-idle", delivery="wakeup")
    assert seen == ["after-idle"]


def test_quiet_while_owner_busy_stays_quiet(tmp_path: Path) -> None:
    seen: list[str] = []
    store = SubagentSessionStore(
        base_dir=tmp_path / "sessions",
        on_report=lambda sid, report: seen.append(report.content),
    )
    session = store.create(agent_id="researcher", thread_id="th-1")
    store.mark_owner_busy(session.session_id)
    store.append_report(session.session_id, content="quiet note", delivery="quiet")
    assert seen == []
    assert store.get(session.session_id).reports[-1].delivery == "quiet"


def test_mark_owner_idle_restores_wakeup(tmp_path: Path) -> None:
    seen: list[str] = []
    store = SubagentSessionStore(
        base_dir=tmp_path / "sessions",
        on_report=lambda sid, report: seen.append(report.content),
    )
    session = store.create(agent_id="researcher", thread_id="th-1")
    store.mark_owner_busy(session.session_id)
    store.append_report(session.session_id, content="queued-1", delivery="wakeup")
    assert seen == []
    store.mark_owner_idle(session.session_id)
    store.append_report(session.session_id, content="woken-2", delivery="wakeup")
    assert seen == ["woken-2"]


def test_owner_busy_state_is_live_not_persisted(tmp_path: Path) -> None:
    seen: list[str] = []
    store = SubagentSessionStore(
        base_dir=tmp_path / "sessions",
        on_report=lambda sid, report: seen.append(report.content),
    )
    session = store.create(agent_id="researcher", thread_id="th-1")
    store.mark_owner_busy(session.session_id)
    store.append_report(session.session_id, content="queued-1", delivery="wakeup")
    assert seen == []

    # A restarted store starts every owner idle (dsh restart-into-idle): the
    # queued report stays queued, but a new wakeup may open a parent turn.
    fresh = SubagentSessionStore(
        base_dir=tmp_path / "sessions",
        on_report=lambda sid, report: seen.append(report.content),
    )
    assert fresh.get(session.session_id).reports[-1].delivery == "queued"
    fresh.append_report(session.session_id, content="after-restart", delivery="wakeup")
    assert seen == ["after-restart"]


def test_mark_owner_unknown_session_noop(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.mark_owner_busy("not-a-real-session")  # no raise
    store.mark_owner_idle("not-a-real-session")  # no raise


def test_queued_report_round_trips_across_instances(tmp_path: Path) -> None:
    store = _store(tmp_path)
    session = store.create(agent_id="researcher", thread_id="th-1")
    store.mark_owner_busy(session.session_id)
    store.append_report(session.session_id, content="queued finding", delivery="wakeup")

    fresh = SubagentSessionStore(base_dir=tmp_path / "sessions")
    loaded = fresh.get(session.session_id)
    assert loaded is not None
    assert loaded.reports[-1].delivery == "queued"


def test_legacy_session_without_reports_loads(tmp_path: Path) -> None:
    store = _store(tmp_path)
    session = store.create(agent_id="researcher", thread_id="th-1")
    store.append_turn(session.session_id, prompt="p", output="o", success=True)
    raw = (tmp_path / "sessions" / f"{session.session_id}.json").read_text(encoding="utf-8")
    (tmp_path / "sessions" / f"{session.session_id}.json").write_text(
        raw.replace('"reports": []', '"reports": null'), encoding="utf-8"
    )
    fresh = SubagentSessionStore(base_dir=tmp_path / "sessions")
    loaded = fresh.get(session.session_id)
    assert loaded is not None
    assert loaded.reports == []
    assert loaded.reports_delivered_up_to == 0


# ─── bridge wiring ────────────────────────────────────────────────────────


def test_call_subagent_attaches_pending_reports_and_acks(tmp_path: Path) -> None:
    previous_runner = bridge.get_sub_agent_runner()
    previous_store = get_subagent_session_store()
    store = _store(tmp_path)
    try:
        bridge.set_sub_agent_runner(lambda prompt, **kw: "the answer")  # type: ignore[arg-type]
        set_subagent_session_store(store)
        result = bridge.call_subagent(agent_id="zzz_custom_report_role", prompt="go")
    finally:
        bridge.set_sub_agent_runner(previous_runner)
        set_subagent_session_store(previous_store)

    assert result["success"] is True
    session_id = result["session_id"]
    assert session_id

    # Seed two undelivered reports as a continuable child would have.
    store.append_report(session_id, content="部分发现", delivery="quiet")
    store.append_report(session_id, content="最终结论", delivery="wakeup")

    previous_runner = bridge.get_sub_agent_runner()
    previous_store = get_subagent_session_store()
    try:
        bridge.set_sub_agent_runner(lambda prompt, **kw: "next answer")  # type: ignore[arg-type]
        set_subagent_session_store(store)
        second = bridge.call_subagent(
            agent_id="zzz_custom_report_role",
            prompt="继续",
            continue_session_id=session_id,
        )
    finally:
        bridge.set_sub_agent_runner(previous_runner)
        set_subagent_session_store(previous_store)

    pending = second.get("pending_reports")
    assert pending is not None
    assert [p["content"] for p in pending] == ["部分发现", "最终结论"]
    assert [p["delivery"] for p in pending] == ["quiet", "wakeup"]
    assert "最终结论" in second.get("reports_prompt", "")
    # Acked: the next call no longer sees them.
    assert store.pending_reports(session_id) == []
