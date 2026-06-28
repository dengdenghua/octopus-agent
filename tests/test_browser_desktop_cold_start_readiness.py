from __future__ import annotations

from pathlib import Path

from runtime.safety.evolution.browser_desktop_cold_start_readiness import (
    SCHEMA,
    compute_browser_desktop_cold_start_readiness,
)


def test_browser_desktop_cold_start_readiness_is_complete(
    tmp_path: Path,
) -> None:
    report = compute_browser_desktop_cold_start_readiness(
        review_queue_path=tmp_path / "review_queue.json",
    )

    assert report["schema"] == SCHEMA
    assert report["ready"] is True
    assert report["score"] == 1.0
    assert report["verdict"] == "pass"
    assert report["checks"] == {
        "runtime_contract_ready": True,
        "productization_ready": True,
        "repair_recipe_gate_ready": True,
        "offline_bootstrap_probe_ready": True,
    }
    assert report["probe"]["ok"] is True
    assert report["probe"]["checks"]["browser_has_session_bootstrap"] is True
    assert report["probe"]["checks"]["desktop_has_preview_policy_and_replay"] is True
    assert report["calibration"]["cold_start_score_cap"] == 93
    assert report["calibration"]["live_runtime_score_cap"] == 94


def test_browser_desktop_cold_start_readiness_detects_missing_root(
    tmp_path: Path,
) -> None:
    report = compute_browser_desktop_cold_start_readiness(root=tmp_path)

    assert report["ready"] is False
    assert report["score"] < 1.0
    assert report["checks"]["runtime_contract_ready"] is False
    assert report["checks"]["productization_ready"] is False
    assert report["checks"]["offline_bootstrap_probe_ready"] is False
    assert report["next_actions"]
