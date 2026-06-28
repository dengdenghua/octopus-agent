from __future__ import annotations

from pathlib import Path

from runtime.safety.evolution.record_replay_audit_readiness import (
    compute_record_replay_audit_readiness,
    run_record_replay_audit_probe,
)


def test_record_replay_audit_readiness_passes() -> None:
    report = compute_record_replay_audit_readiness()

    assert report["schema"] == "octopus.record_replay_audit_readiness.v1"
    assert report["ready"] is True
    assert report["verdict"] == "pass"
    assert report["score"] == 1.0
    assert report["missing_count"] == 0
    assert report["probe"]["ok"] is True
    assert report["probe"]["trace_replay"]["gate"]["passed"] is True
    assert report["probe"]["governance_audit"]["tamper_detected"] is True
    assert report["probe"]["native_replay"]["ok"] is True
    assert report["next_actions"] == []


def test_record_replay_audit_probe_covers_all_runtime_gates() -> None:
    probe = run_record_replay_audit_probe()

    assert probe["schema"] == "octopus.record_replay_audit_probe.v1"
    assert probe["ok"] is True
    assert probe["trace_replay"]["evaluation"]["score"] == 1.0
    assert probe["governance_audit"]["bundle"]["integrity_ok"] is True
    assert probe["native_replay"]["heuristic_total"] >= 0.6
    assert probe["native_replay"]["sandbox_total"] >= 0.6
    assert probe["native_replay"]["turn_total"] >= 0.6


def test_record_replay_audit_readiness_detects_missing_root(tmp_path: Path) -> None:
    report = compute_record_replay_audit_readiness(root=tmp_path, include_probe=False)

    assert report["ready"] is False
    assert report["score"] == 0.0
    assert report["missing_count"] == report["total"]
    assert report["next_actions"]
