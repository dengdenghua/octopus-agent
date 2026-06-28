from __future__ import annotations

from runtime.safety.evolution.tool_threat_model import compute_tool_threat_model


def test_tool_threat_model_covers_high_risk_tool_classes() -> None:
    report = compute_tool_threat_model()

    assert report["schema"] == "octopus.tool_threat_model.v1"
    assert report["class_count"] >= 6
    assert report["score"] >= 0.9
    assert report["verdict"] in {"pass", "review"}
    classes = {row["id"]: row for row in report["classes"]}
    assert classes["shell_execution"]["score"] >= 0.9
    assert classes["plugin_lifecycle"]["score"] >= 0.9
    assert "plugin_lifecycle_audit" not in classes["plugin_lifecycle"]["missing_controls"]
    assert classes["subagent_delegation"]["score"] >= 0.9


def test_tool_threat_model_reports_missing_controls_for_partial_tree(tmp_path) -> None:
    (tmp_path / "runtime/safety/approval").mkdir(parents=True)
    (tmp_path / "runtime/safety/approval/approval_gate.py").write_text(
        "class ApprovalGate: pass\n# deny\n",
        encoding="utf-8",
    )

    report = compute_tool_threat_model(root=tmp_path)

    assert report["verdict"] == "fail"
    assert report["coverage_gaps"]
    shell = next(row for row in report["classes"] if row["id"] == "shell_execution")
    assert "sandbox_runner" in shell["missing_controls"]
