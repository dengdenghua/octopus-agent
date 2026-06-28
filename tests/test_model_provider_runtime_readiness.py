from __future__ import annotations

from pathlib import Path

from runtime.safety.evolution.model_provider_runtime_readiness import (
    compute_model_provider_runtime_readiness,
    run_model_provider_runtime_probe,
)


def test_model_provider_runtime_readiness_is_complete() -> None:
    report = compute_model_provider_runtime_readiness()

    assert report["schema"] == "octopus.model_provider_runtime_readiness.v1"
    assert report["ready"] is True
    assert report["score"] == 1.0
    assert report["missing_count"] == 0
    assert report["probe"]["ok"] is True
    assert report["probe"]["matrix_score"] == 100
    assert report["probe"]["builtin_profile_coverage"]["ready"] is True
    assert report["probe"]["payload_shape"]["ok"] is True
    assert report["probe"]["failure_export"]["ok"] is True
    assert report["probe"]["secrets_redacted"] is True
    assert {row["id"] for row in report["checks"]} >= {
        "provider_compatibility_matrix",
        "openai_compat_payload_shaping",
        "domestic_profile_coverage",
        "provider_health_surface",
        "scorecard_provider_runtime_surface",
        "provider_payload_shape_probe",
        "provider_failure_export_probe",
    }
    assert report["next_actions"] == ["Model provider runtime checks are ready."]


def test_model_provider_runtime_probe_validates_domestic_payload_shapes() -> None:
    probe = run_model_provider_runtime_probe()

    assert probe["schema"] == "octopus.model_provider_runtime_probe.v1"
    assert probe["ok"] is True
    requirements = probe["payload_shape"]["requirements"]
    assert requirements["kimi_omits_sampling_parameters"] is True
    assert requirements["qwen_uses_enable_thinking"] is True
    assert requirements["deepseek_reasoner_uses_implicit_thinking"] is True
    assert requirements["glm_strict_omits_system_messages"] is True
    assert probe["failure_export"]["primary_repair_route"] == "provider_thinking_protocol"


def test_model_provider_runtime_readiness_detects_missing_root(tmp_path: Path) -> None:
    report = compute_model_provider_runtime_readiness(root=tmp_path)

    assert report["ready"] is False
    assert report["score"] < 1.0
    assert report["missing_count"] > 0
    assert report["next_actions"]
