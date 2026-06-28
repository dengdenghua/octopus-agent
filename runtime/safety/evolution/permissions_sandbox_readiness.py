from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from runtime.platform.process.paths import project_root as default_project_root
from runtime.safety.evolution.policy_review_rules import (
    build_policy_review_rule_drafts,
    install_policy_review_rule_draft,
    verify_policy_review_rule_draft,
)
from runtime.safety.evolution.proposal_ledger import ProposalRecord, ProposalStatus
from runtime.safety.evolution.tool_threat_model import compute_tool_threat_model
from runtime.safety.sandboxing.sandbox import (
    DirectBackend,
    SandboxPolicy,
    SandboxRunner,
    SandboxViolation,
    select_process_backend,
)

SCHEMA = "octopus.permissions_sandbox_readiness.v1"


def compute_permissions_sandbox_readiness(
    *,
    root: str | Path | None = None,
) -> dict[str, Any]:
    base = Path(root) if root is not None else default_project_root(Path(__file__))
    threat_model = compute_tool_threat_model(root=base)
    backend_probe = _backend_probe()
    default_runner_probe = _default_runner_probe(base)
    hard_runtime_probe = _hard_runtime_probe(base, backend_probe=backend_probe)
    sandbox_probe = _sandbox_probe(base)
    policy_probe = _policy_review_probe()
    access_log_probe = _access_log_redaction_probe()
    checks = {
        "tool_threat_model_ready": (
            threat_model.get("ready") is True
            and threat_model.get("verdict") == "pass"
            and float(threat_model.get("score") or 0.0) >= 1.0
        ),
        "process_backend_declared": bool(backend_probe.get("backend")),
        "hard_backend_or_soft_fallback_declared": (
            backend_probe.get("hard") is True
            or backend_probe.get("fallback") == "soft_isolation"
        ),
        "default_runner_uses_selected_backend": (
            default_runner_probe.get("ok") is True
            and default_runner_probe.get("backend") == backend_probe.get("backend")
            and default_runner_probe.get("hard") == backend_probe.get("hard")
        ),
        "hard_backend_runtime_probe_pass": hard_runtime_probe.get("ok") is True,
        "sandbox_soft_constraints_pass": sandbox_probe.get("ok") is True,
        "policy_review_signature_gate_pass": policy_probe.get("ok") is True,
        "access_log_secret_redaction_pass": access_log_probe.get("ok") is True,
    }
    passed = sum(1 for value in checks.values() if value is True)
    total = len(checks)
    score = round(passed / total, 3) if total else 0.0
    ready = score >= 1.0
    return {
        "schema": SCHEMA,
        "score": score,
        "ready": ready,
        "verdict": "pass" if ready else "review" if score >= 0.8 else "fail",
        "checks": checks,
        "probe": {
            "backend": backend_probe,
            "default_runner": default_runner_probe,
            "hard_runtime": hard_runtime_probe,
            "sandbox": sandbox_probe,
            "policy_review": policy_probe,
            "access_log_redaction": access_log_probe,
        },
        "tool_threat_model": threat_model,
        "next_actions": _next_actions(
            checks,
            backend_probe=backend_probe,
            hard_runtime_probe=hard_runtime_probe,
            sandbox_probe=sandbox_probe,
            policy_probe=policy_probe,
            access_log_probe=access_log_probe,
        ),
        "policy": {
            "hard_kernel_backend_required_for_zero_warning_claims": True,
            "hard_backend_runtime_probe_required_for_verified_parity": True,
            "direct_backend_is_explicit_soft_fallback": True,
            "soft_fallback_must_pass_env_cwd_timeout_output_and_network_hints": True,
            "policy_review_rules_require_signed_operator_install": True,
            "access_logs_must_redact_query_and_bearer_tokens": True,
        },
    }


def _backend_probe() -> dict[str, Any]:
    try:
        choice = select_process_backend()
        return {
            "schema": "octopus.permissions_sandbox_backend_probe.v1",
            "ok": True,
            "backend": choice.name,
            "hard": choice.hard,
            "strict": choice.strict,
            "fallback": "" if choice.hard else "soft_isolation",
            "warning": (
                ""
                if choice.hard
                else "DirectBackend selected; kernel isolation is unavailable, "
                "so readiness depends on soft constraints and operator-visible policy."
            ),
        }
    except SandboxViolation as exc:
        return {
            "schema": "octopus.permissions_sandbox_backend_probe.v1",
            "ok": False,
            "backend": "",
            "hard": False,
            "strict": True,
            "fallback": "",
            "error": str(exc),
        }


def _sandbox_probe(root: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="octopus-sandbox-readiness-") as tmp:
        workspace = Path(tmp)
        escaped = workspace.parent
        policy = SandboxPolicy(
            workspace=workspace,
            allow_network=False,
            timeout_s=2,
            max_output_bytes=64,
            extra_env={
                "OCTOPUS_SAFE_FLAG": "allowed",
                "OPENAI_API_KEY": "must_not_leak",
            },
        )
        runner = SandboxRunner(
            policy,
            backend=DirectBackend(),
            warn_on_direct_backend=False,
        )
        env_result = runner.run(
            [
                _python_executable(root),
                "-c",
                (
                    "import os; "
                    "print(os.environ.get('OCTOPUS_SAFE_FLAG','')); "
                    "print(os.environ.get('OPENAI_API_KEY','missing')); "
                    "print(os.environ.get('no_proxy','')); "
                    "print(os.environ.get('http_proxy',''))"
                ),
            ]
        )
        output_result = runner.run(
            [_python_executable(root), "-c", "print('x'*1024)"]
        )
        timeout_result = runner.run(
            [_python_executable(root), "-c", "import time; time.sleep(5)"]
        )
        cwd_blocked = False
        cwd_error = ""
        try:
            runner.run([_python_executable(root), "-c", "print('escape')"], cwd=escaped)
        except SandboxViolation as exc:
            cwd_blocked = True
            cwd_error = str(exc)

    env_lines = env_result.stdout.splitlines()
    env_scrubbed = "must_not_leak" not in env_result.stdout and (
        "missing" in env_lines
    )
    network_hints = "*" in env_lines and "127.0.0.1:1" in env_result.stdout
    constraints = {
        "env_allowlist_preserves_safe_prefix": "allowed" in env_lines,
        "sensitive_env_scrubbed": env_scrubbed,
        "network_proxy_hints_set": network_hints,
        "cwd_escape_blocked": cwd_blocked,
        "output_capped": output_result.truncated is True,
        "timeout_kills_process": timeout_result.timed_out is True
        and timeout_result.killed is True,
    }
    return {
        "schema": "octopus.permissions_sandbox_soft_constraint_probe.v1",
        "ok": all(constraints.values()),
        "constraints": constraints,
        "backend": type(runner.backend).__name__,
        "results": {
            "env_exit_code": env_result.exit_code,
            "output_truncated": output_result.truncated,
            "timeout_timed_out": timeout_result.timed_out,
            "timeout_killed": timeout_result.killed,
            "cwd_escape_error": cwd_error,
        },
    }


def _hard_runtime_probe(
    root: Path,
    *,
    backend_probe: dict[str, Any],
) -> dict[str, Any]:
    if backend_probe.get("hard") is not True:
        return {
            "schema": "octopus.permissions_sandbox_hard_runtime_probe.v1",
            "ok": False,
            "required": True,
            "backend": str(backend_probe.get("backend") or ""),
            "hard": False,
            "reason": str(backend_probe.get("warning") or "hard process sandbox backend is unavailable"),
        }
    with tempfile.TemporaryDirectory(prefix="octopus-hard-sandbox-readiness-") as tmp:
        workspace = Path(tmp)
        escaped = workspace.parent
        policy = SandboxPolicy(
            workspace=workspace,
            allow_network=False,
            timeout_s=3,
            max_output_bytes=2048,
        )
        try:
            runner = SandboxRunner(policy)
            result = runner.run(
                [
                    _python_executable(root),
                    "-c",
                    "import os; print('hard-runner-ok'); print(os.getcwd())",
                ],
            )
            cwd_blocked = False
            cwd_error = ""
            try:
                runner.run(
                    [_python_executable(root), "-c", "print('escape')"],
                    cwd=escaped,
                )
            except SandboxViolation as exc:
                cwd_blocked = True
                cwd_error = str(exc)
        except SandboxViolation as exc:
            return {
                "schema": "octopus.permissions_sandbox_hard_runtime_probe.v1",
                "ok": False,
                "required": True,
                "backend": str(backend_probe.get("backend") or ""),
                "hard": bool(backend_probe.get("hard") is True),
                "error": str(exc),
            }
    ok = (
        result.exit_code == 0
        and "hard-runner-ok" in result.stdout
        and result.hard is True
        and result.backend == backend_probe.get("backend")
        and cwd_blocked
    )
    return {
        "schema": "octopus.permissions_sandbox_hard_runtime_probe.v1",
        "ok": ok,
        "required": True,
        "backend": result.backend,
        "hard": result.hard,
        "exit_code": result.exit_code,
        "cwd_escape_blocked": cwd_blocked,
        "cwd_escape_error": cwd_error,
        "stdout_contains_marker": "hard-runner-ok" in result.stdout,
    }


def _default_runner_probe(root: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="octopus-default-runner-readiness-") as tmp:
        workspace = Path(tmp)
        policy = SandboxPolicy(
            workspace=workspace,
            allow_network=False,
            timeout_s=2,
            max_output_bytes=2048,
        )
        try:
            runner = SandboxRunner(policy)
            result = runner.run(
                [_python_executable(root), "-c", "print('default-runner-ok')"],
            )
        except SandboxViolation as exc:
            return {
                "schema": "octopus.permissions_default_runner_probe.v1",
                "ok": False,
                "backend": "",
                "hard": False,
                "error": str(exc),
            }
    return {
        "schema": "octopus.permissions_default_runner_probe.v1",
        "ok": result.exit_code == 0 and "default-runner-ok" in result.stdout,
        "backend": result.backend,
        "hard": result.hard,
        "exit_code": result.exit_code,
        "timed_out": result.timed_out,
    }


def _policy_review_probe() -> dict[str, Any]:
    record = ProposalRecord(
        proposal_id="sandbox-readiness-policy-review",
        kind="review_queue_policy_review",
        description="Replay-backed policy review for exec_shell.",
        status=ProposalStatus.PROPOSED,
        proposer="permissions_sandbox_readiness",
        ts="2026-01-01T00:00:00",
        metadata={
            "review_queue_item_id": "rq-sandbox-readiness",
            "item": {
                "title": "Review repeated denials for exec_shell",
                "text": "Deny repeated unsafe shell execution.",
                "metadata": {
                    "tool_name": "exec_shell",
                    "latest_denial": {
                        "tool_name": "exec_shell",
                        "reason": "destructive command denied",
                    },
                },
            },
            "evidence": {
                "schema": "octopus.policy_review_promotion_evidence.v1",
                "replay_case_id": "sandbox-readiness",
            },
        },
    )
    report = build_policy_review_rule_drafts(records=[record])
    drafts = report.get("drafts") if isinstance(report.get("drafts"), list) else []
    draft = drafts[0] if drafts and isinstance(drafts[0], dict) else {}
    signature = verify_policy_review_rule_draft(draft)
    confirm_blocked = False
    install_ok = False
    with tempfile.TemporaryDirectory(prefix="octopus-policy-readiness-") as tmp:
        policy_path = Path(tmp) / "approval_policy.json"
        try:
            install_policy_review_rule_draft(
                draft,
                policy_path=policy_path,
                confirm_install=False,
            )
        except ValueError:
            confirm_blocked = True
        if signature.get("ok") is True:
            installed = install_policy_review_rule_draft(
                draft,
                policy_path=policy_path,
                confirm_install=True,
            )
            install_ok = installed.get("installed") is True
    return {
        "schema": "octopus.permissions_policy_review_probe.v1",
        "ok": bool(draft)
        and signature.get("ok") is True
        and confirm_blocked
        and install_ok,
        "draft_count": len(drafts),
        "signature_ok": signature.get("ok") is True,
        "confirmation_required": confirm_blocked,
        "install_ok": install_ok,
    }


def _access_log_redaction_probe() -> dict[str, Any]:
    from runtime.platform.observability.access_log_redactor import (
        SensitiveAccessLogFilter,
        redact_access_log_text,
    )

    redacted = redact_access_log_text(
        '127.0.0.1:50123 - "GET /api/realtime?token=jwt.secret.value&surface=chat HTTP/1.1" 403'
    )
    query_redacted = "jwt.secret.value" not in redacted and "token=<redacted>" in redacted
    safe_param_preserved = "surface=chat" in redacted

    nested_redacted = redact_access_log_text(
        "GET /api/browser/relay/bookmarklet-poll"
        "?url=http%3A%2F%2F127.0.0.1%3A8000%2Fconnect%3Fapi_base_url%3Dhttp"
        "%26relay_token%3Dencoded-secret-value&relay_token=plain-secret HTTP/1.1"
    )
    nested_token_redacted = (
        "encoded-secret-value" not in nested_redacted
        and "plain-secret" not in nested_redacted
        and "relay_token%3D%3Credacted%3E" in nested_redacted
        and "relay_token=<redacted>" in nested_redacted
    )
    polling_id_redacted = redact_access_log_text(
        "GET /api/browser/relay/bookmarklet-poll"
        "?callback=__octopusBookmarkletPoll_1782654045773_f8ve3mrrqkf"
        "&title=Octopus%20Chrome%20Relay%20Probe&t=1782654045793 HTTP/1.1"
    )
    polling_ids_preserved = (
        "[REDACTED:phone]" not in polling_id_redacted
        and "1782654045773" in polling_id_redacted
        and "1782654045793" in polling_id_redacted
    )

    bearer_redacted = redact_access_log_text(
        "Authorization: Bearer sk-kimi-abcdefghijklmnopqrstuvwxyz0123456789ABCDE"
    )
    bearer_token_redacted = (
        "sk-kimi" not in bearer_redacted
        and "Bearer <redacted>" in bearer_redacted
    )

    import logging

    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        (
            "127.0.0.1:50123",
            "GET",
            "/api/preview/stream?token=preview-token-value",
            "1.1",
            200,
        ),
        None,
    )
    noisy_success_dropped = SensitiveAccessLogFilter().filter(record) is False
    requirements = {
        "query_token_redacted": query_redacted,
        "nested_encoded_query_token_redacted": nested_token_redacted,
        "safe_query_param_preserved": safe_param_preserved,
        "non_secret_polling_ids_preserved": polling_ids_preserved,
        "bearer_token_redacted": bearer_token_redacted,
        "noisy_success_polling_dropped": noisy_success_dropped,
    }
    return {
        "schema": "octopus.permissions_access_log_redaction_probe.v1",
        "ok": all(requirements.values()),
        "requirements": requirements,
    }


def _python_executable(root: Path) -> str:
    candidate = root / ".venv" / "bin" / "python"
    if candidate.is_file():
        return str(candidate)
    return sys.executable or os.environ.get("PYTHON", "python3")


def _next_actions(
    checks: dict[str, bool],
    *,
    backend_probe: dict[str, Any],
    hard_runtime_probe: dict[str, Any],
    sandbox_probe: dict[str, Any],
    policy_probe: dict[str, Any],
    access_log_probe: dict[str, Any],
) -> list[str]:
    actions: list[str] = []
    if checks.get("tool_threat_model_ready") is not True:
        actions.append("Bring every high-risk tool class in the threat model to pass.")
    if backend_probe.get("hard") is not True:
        actions.append(
            "Install or configure a hard process sandbox backend for zero-warning local execution claims."
        )
    if hard_runtime_probe.get("ok") is not True:
        actions.append("Fix the hard process sandbox runtime probe before claiming Codex-level isolation.")
    if sandbox_probe.get("ok") is not True:
        actions.append("Fix sandbox soft-constraint probes before promoting autonomous execution.")
    if policy_probe.get("ok") is not True:
        actions.append("Keep policy-review rule drafts signed and operator-confirmed before install.")
    if access_log_probe.get("ok") is not True:
        actions.append("Redact query, bearer, and provider tokens from backend access logs.")
    if not actions:
        actions.append("Permissions and sandbox readiness is verified.")
    return actions


__all__ = [
    "SCHEMA",
    "compute_permissions_sandbox_readiness",
]
