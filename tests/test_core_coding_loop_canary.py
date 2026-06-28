from __future__ import annotations

from runtime.safety.evolution.core_coding_loop_canary import (
    SCHEMA,
    run_core_coding_loop_canary,
)


def test_core_coding_loop_canary_runs_full_verifier_repair_loop() -> None:
    report = run_core_coding_loop_canary()

    assert report["schema"] == SCHEMA
    assert report["ready"] is True
    assert report["score"] == 1.0
    assert report["checks"] == {
        "history_ranking_selects_stable_verifier": True,
        "sandboxed_verifier_executes": True,
        "decision_and_metric_recorded": True,
        "verifier_drift_routes_to_backlog": True,
        "repair_route_quality_gate_clean": True,
        "repair_route_promotion_evidence_queued": True,
    }
    assert report["probe"]["ranking"]["selected_command"].startswith(
        "python -m pytest"
    )
    assert report["probe"]["execution"]["telemetry_ok"] is True
    assert report["probe"]["drift"]["backlog_count"] >= 1
    assert report["probe"]["repair_route"]["blockers"] == []
    promotion = report["probe"]["repair_route_promotion"]
    assert promotion["created"] == 1
    assert promotion["requires_passing_rerun"] is True
    assert promotion["passing_rerun_attached"] is False
    assert promotion["quality_ready_after_queue"] is False
    assert "pending_repair_route_review" in promotion["quality_blockers_after_queue"]
