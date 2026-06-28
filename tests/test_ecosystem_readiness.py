from __future__ import annotations

from runtime.safety.evolution.ecosystem_readiness import (
    compute_ecosystem_readiness,
    run_ecosystem_probe,
)


def test_ecosystem_probe_verifies_signed_plugin_compatibility() -> None:
    probe = run_ecosystem_probe()

    assert probe["schema"] == "octopus.ecosystem_plugin_compatibility_probe.v1"
    assert probe["ok"] is True
    assert probe["requirements"] == {
        "signed_plugin_provenance": True,
        "explicit_permission_resolution": True,
        "lifecycle_audit_pass": True,
        "compatibility_summary_pass": True,
    }
    assert probe["compatibility_verdict"] == "pass"


def test_ecosystem_readiness_includes_plugin_compatibility_probe() -> None:
    report = compute_ecosystem_readiness()

    assert report["score"] == 1.0
    assert report["probe_ready"] is True
    assert report["probe"]["ok"] is True
    assert report["next_actions"] == []
