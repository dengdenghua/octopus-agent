"""Record → skill closure for the desktop computer-use loop.

Covers the bridge (a successful vision-action run → journal Trajectory over
registered GUI skills) and the governed end-to-end: SkillForge clusters
repeated GUI runs, the immune gate refuses auto-promotion (every GUI
primitive is dangerous), and the candidate is *quarantined* for human
approval rather than silently dropped or auto-granted.
"""
from __future__ import annotations

from typing import Any

import pytest

from runtime.execution.suckers import Skill, SkillRegistry
from runtime.execution.suckers.computer_use_record import (
    loop_result_to_trajectory,
    record_successful_loop,
)
from runtime.memory.journal import InMemoryJournal
from runtime.safety.recovery import ForgeConfig, SkillForge


def _success(actions: list[dict[str, Any]]) -> dict[str, Any]:
    return {"status": "success", "goal": "demo", "actions_taken": actions}


# ── bridge: loop result → trajectory ─────────────────────────────────


def test_maps_actions_to_registered_gui_skills() -> None:
    traj = loop_result_to_trajectory(
        _success([
            {"action": "click", "x": 10, "y": 20, "button": "left"},
            {"action": "type", "text": "hello"},
            {"action": "key", "keys": ["cmd", "s"]},
            {"action": "move", "x": 5, "y": 6},
        ])
    )
    assert traj is not None
    assert traj.strategy_id == "computer_use"
    assert [s.action.sucker_id for s in traj.steps] == [
        "mouse_click", "keyboard_type", "keyboard_press", "mouse_move",
    ]
    # args are preserved for replay (sans the action discriminator).
    assert traj.steps[0].action.args == {"x": 10, "y": 20, "button": "left"}
    assert traj.steps[0].args_template == {"x": 10, "y": 20, "button": "left"}
    assert traj.outcome.success is True


def test_non_success_returns_none() -> None:
    assert loop_result_to_trajectory(
        {"status": "planner_gave_up", "actions_taken": [{"action": "click"}]}
    ) is None
    assert loop_result_to_trajectory({"status": "error"}) is None
    assert loop_result_to_trajectory("nope") is None


def test_wait_and_unknown_actions_are_dropped() -> None:
    traj = loop_result_to_trajectory(
        _success([
            {"action": "click", "x": 1, "y": 2},
            {"action": "wait", "ms": 500},
            {"action": "teleport"},  # unknown
            {"action": "type", "text": "x"},
        ])
    )
    assert traj is not None
    assert [s.action.sucker_id for s in traj.steps] == ["mouse_click", "keyboard_type"]


def test_too_few_mappable_steps_returns_none() -> None:
    # one real action + filler → below the 2-step floor → not recorded.
    assert loop_result_to_trajectory(
        _success([{"action": "click", "x": 1, "y": 2}, {"action": "wait", "ms": 1}])
    ) is None


# ── recorder: write to journal, best-effort ──────────────────────────


def test_records_successful_loop_to_journal() -> None:
    journal = InMemoryJournal()
    traj = record_successful_loop(
        journal,
        _success([{"action": "click", "x": 1, "y": 2}, {"action": "type", "text": "a"}]),
    )
    assert traj is not None
    events = journal.read_by_type("trajectory")
    assert len(events) == 1


def test_none_journal_and_failure_are_swallowed() -> None:
    ok = _success([{"action": "click", "x": 1, "y": 2}, {"action": "type", "text": "a"}])
    assert record_successful_loop(None, ok) is None

    class _Boom:
        def write_trajectory(self, _t: Any) -> None:
            raise RuntimeError("disk full")

    # must not propagate — recording is side-channel
    assert record_successful_loop(_Boom(), ok) is None


# ── full closure: record → forge → immune gate → quarantine ──────────


def _gui_registry() -> SkillRegistry:
    registry = SkillRegistry()
    for name in ("mouse_click", "keyboard_type"):
        registry.register(
            Skill(
                name=name,
                trusted_source=f"skill://public/{name}",
                handler=lambda **kw: {"ok": True},
                affinity=["desktop"],
            ),
            verify_tests=False,
        )
    return registry


def test_recorded_gui_macro_is_quarantined_not_promoted() -> None:
    journal = InMemoryJournal()
    registry = _gui_registry()

    # Three identical successful GUI runs → one clusterable pattern.
    run = _success([
        {"action": "click", "x": 100, "y": 200},
        {"action": "type", "text": "report"},
    ])
    for _ in range(3):
        record_successful_loop(journal, run)

    result = SkillForge(
        journal=journal,
        registry=registry,
        config=ForgeConfig(
            min_hits=3,
            min_success_rate=0.0,
            shadow_runs=1,
            shadow_success_threshold=0.0,
        ),
    ).run()

    # Refused auto-promotion (GUI primitives are dangerous) …
    assert result.promoted == []
    assert not any(n.startswith("forged_") for n in registry.all_names())
    # … but routed to governed quarantine, not silently dropped.
    assert result.quarantined, "dangerous GUI macro should be quarantined"

    decisions = [
        e for e in journal.read_by_type("skill_proposal_decision")
        if getattr(e, "decision", "") == "quarantined"
    ]
    assert decisions, "a quarantine decision should be journaled for approval"
    assert "mouse_click" in (decisions[0].details or {}).get("dangerous_underlying", [])


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
