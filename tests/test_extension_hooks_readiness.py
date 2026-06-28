from __future__ import annotations

from pathlib import Path

from runtime.safety.evolution.extension_hooks_readiness import (
    compute_extension_hooks_readiness,
    run_extension_hooks_probe,
)


def test_extension_hooks_probe_accepts_signed_provenance_lifecycle() -> None:
    report = run_extension_hooks_probe()

    assert report["schema"] == "octopus.extension_hooks_probe.v1"
    assert report["ok"] is True
    assert report["signed_provenance"] is True
    assert report["permission_review"] is True
    assert report["lifecycle_audit"] is True
    assert report["compatibility_summary"] is True
    assert report["compatibility_verdict"] == "pass"


def test_extension_hooks_readiness_passes_current_repo() -> None:
    report = compute_extension_hooks_readiness()

    assert report["schema"] == "octopus.extension_hooks_readiness.v1"
    assert report["ready"] is True
    assert report["verdict"] == "pass"
    assert report["score"] == 1.0
    assert report["passed"] == report["total"]
    assert report["next_actions"] == []
    assert {
        item["id"] for item in report["capabilities"] if item["passed"]
    } >= {
        "signed_provenance_manifest",
        "permission_lifecycle_audit",
        "operator_compatibility_summary",
        "threat_model_coverage",
        "plugin_regression_tests",
        "signed_provenance_probe",
        "permission_lifecycle_probe",
        "compatibility_summary_probe",
    }


def test_extension_hooks_readiness_reports_missing_evidence(
    tmp_path: Path,
) -> None:
    report = compute_extension_hooks_readiness(root=tmp_path, include_probe=False)

    assert report["ready"] is False
    assert report["verdict"] == "review"
    assert report["score"] == 0.0
    assert report["missing_count"] == report["total"]
    assert report["next_actions"][0].startswith(
        "Add runtime/platform/plugins/codex_discovery.py"
    )
