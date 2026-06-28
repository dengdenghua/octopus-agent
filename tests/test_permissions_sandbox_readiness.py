from __future__ import annotations

from pathlib import Path

import pytest

from runtime.safety.evolution.permissions_sandbox_readiness import (
    SCHEMA,
    compute_permissions_sandbox_readiness,
)
from runtime.safety.sandboxing.sandbox import BubblewrapBackend, SeatbeltBackend


def test_permissions_sandbox_readiness_proves_soft_constraints() -> None:
    report = compute_permissions_sandbox_readiness()

    assert report["schema"] == SCHEMA
    assert report["ready"] is True
    assert report["score"] == 1.0
    assert report["verdict"] == "pass"
    assert report["checks"] == {
        "tool_threat_model_ready": True,
        "process_backend_declared": True,
        "hard_backend_or_soft_fallback_declared": True,
        "default_runner_uses_selected_backend": True,
        "hard_backend_runtime_probe_pass": True,
        "sandbox_soft_constraints_pass": True,
        "policy_review_signature_gate_pass": True,
        "access_log_secret_redaction_pass": True,
    }
    backend = report["probe"]["backend"]
    assert backend["hard"] is True
    assert report["probe"]["default_runner"]["ok"] is True
    assert report["probe"]["default_runner"]["backend"] == (
        backend["backend"]
    )
    hard = report["probe"]["hard_runtime"]
    assert hard["ok"] is True
    assert hard["hard"] is True
    assert hard["backend"] == backend["backend"]
    assert hard["cwd_escape_blocked"] is True
    sandbox = report["probe"]["sandbox"]
    assert sandbox["ok"] is True
    assert sandbox["constraints"] == {
        "env_allowlist_preserves_safe_prefix": True,
        "sensitive_env_scrubbed": True,
        "network_proxy_hints_set": True,
        "cwd_escape_blocked": True,
        "output_capped": True,
        "timeout_kills_process": True,
    }
    policy = report["probe"]["policy_review"]
    assert policy["signature_ok"] is True
    assert policy["confirmation_required"] is True
    assert policy["install_ok"] is True
    access_log = report["probe"]["access_log_redaction"]
    assert access_log["ok"] is True
    assert access_log["requirements"] == {
        "query_token_redacted": True,
        "nested_encoded_query_token_redacted": True,
        "safe_query_param_preserved": True,
        "non_secret_polling_ids_preserved": True,
        "bearer_token_redacted": True,
        "noisy_success_polling_dropped": True,
    }


def test_permissions_sandbox_readiness_reports_partial_tree_gaps(
    tmp_path: Path,
) -> None:
    report = compute_permissions_sandbox_readiness(root=tmp_path)

    assert report["ready"] is False
    assert report["checks"]["tool_threat_model_ready"] is False
    assert report["checks"]["sandbox_soft_constraints_pass"] is True
    assert report["probe"]["policy_review"]["ok"] is True
    assert "Bring every high-risk tool class" in report["next_actions"][0]


def test_permissions_sandbox_readiness_demotes_without_hard_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OCTOPUS_PROCESS_SANDBOX", "auto")
    monkeypatch.setattr(BubblewrapBackend, "available", staticmethod(lambda: False))
    monkeypatch.setattr(SeatbeltBackend, "available", staticmethod(lambda: False))

    report = compute_permissions_sandbox_readiness()

    assert report["ready"] is False
    assert report["verdict"] == "review"
    assert report["checks"]["hard_backend_or_soft_fallback_declared"] is True
    assert report["checks"]["hard_backend_runtime_probe_pass"] is False
    assert report["probe"]["backend"]["fallback"] == "soft_isolation"
    assert report["probe"]["hard_runtime"]["ok"] is False
    assert any(
        "Fix the hard process sandbox runtime probe" in action
        for action in report["next_actions"]
    )
