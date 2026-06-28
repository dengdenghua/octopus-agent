from __future__ import annotations

from pathlib import Path

from runtime.safety.evolution.browser_desktop_runtime_contract import (
    compute_browser_desktop_runtime_contract,
)


def test_browser_desktop_runtime_contract_is_complete() -> None:
    report = compute_browser_desktop_runtime_contract()

    assert report["schema"] == "octopus.browser_desktop_runtime_contract.v1"
    assert report["ready"] is True
    assert report["score"] == 1.0
    assert report["missing_count"] == 0
    assert {row["id"] for row in report["checks"]} >= {
        "browser_session_control_plane",
        "desktop_preview_execute_contract",
        "runtime_probe_contract",
        "runtime_evidence_cache_contract",
        "runtime_readiness_gate",
        "repair_recipe_gate_contract",
        "runtime_probe_cli",
    }
    assert report["next_actions"] == []


def test_browser_desktop_runtime_contract_detects_missing_root(
    tmp_path: Path,
) -> None:
    report = compute_browser_desktop_runtime_contract(root=tmp_path)

    assert report["ready"] is False
    assert report["score"] == 0.0
    assert report["missing_count"] == report["total"]
    assert report["next_actions"]
