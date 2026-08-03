from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from runtime.execution.loops.models import (
    LoopMode,
    LoopRun,
    LoopRunStatus,
    VerifierFinding,
    VerifierResult,
)
from runtime.platform.runtime_policy.workspaces import WorkspaceManager

_LOG = logging.getLogger("runtime.execution.loops.controller")
_TRACE_AGENT_ID = "loop_controller"


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


def _resolve_workspace_path(run: LoopRun, workspace_manager: WorkspaceManager) -> str:
    if run.workspace_path:
        return str(Path(run.workspace_path).expanduser().resolve(strict=False))
    thread_key = run.thread_id or run.run_id
    return str(workspace_manager.allocate(thread_key))


def _truncate_text(value: Any, *, limit: int = 4_000) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


_NON_REPAIRABLE_VERIFIER_CATEGORIES = frozenset(
    {
        "environment_missing_dependency",
        "environment_missing_tool",
        "project_kind_mismatch",
        "verifier_internal_error",
        "verifier_misconfigured",
        "verifier_profile_unknown",
        "verifier_sandbox_violation",
        "verification_cancelled",
    }
)
_ACTIVE_LOOP_STATUSES = frozenset(
    {
        LoopRunStatus.RUNNING,
        LoopRunStatus.VERIFYING,
        LoopRunStatus.REPAIRING,
    }
)
_VERIFIED_LOOP_MODES = frozenset({LoopMode.CODE})
_PRODUCT_LOOP_MODES = frozenset({LoopMode.PLAN, LoopMode.SPEC, LoopMode.GOAL})


def _loop_mode_contract(mode: LoopMode) -> str:
    if mode == LoopMode.PLAN:
        return (
            "Codex Plan 模式：先读上下文、澄清风险和约束，输出可执行计划与验收标准；"
            "除非用户明确要求执行，不进入实现或写文件。"
        )
    if mode == LoopMode.SPEC:
        return (
            "Codex Spec 模式：把需求沉淀成规格说明，包含目标、非目标、约束、"
            "接口/数据契约、验收标准和开放问题；默认不实现。"
        )
    if mode == LoopMode.GOAL:
        return (
            "Codex Goal 模式：围绕一个可审计 objective 持续推进，受预算和迭代上限约束；"
            "完成前必须逐项核验证据，不把部分进展说成完成。"
        )
    return ""


def _failed_verifier_findings(verifier: VerifierResult | None) -> list[VerifierFinding]:
    if verifier is None:
        return []
    return [finding for finding in verifier.findings if not finding.passed]


def _verifier_failure_category(verifier: VerifierResult | None) -> str:
    if verifier is None or verifier.passed:
        return ""
    category = str(verifier.failure_category or "").strip()
    if category:
        return category
    categories = [
        str(finding.category or "").strip()
        for finding in _failed_verifier_findings(verifier)
        if str(finding.category or "").strip()
    ]
    if any(category in _NON_REPAIRABLE_VERIFIER_CATEGORIES for category in categories):
        return next(
            category for category in categories if category in _NON_REPAIRABLE_VERIFIER_CATEGORIES
        )
    return categories[0] if categories else "verification_failure"


def _verifier_failure_repairable(verifier: VerifierResult | None) -> bool:
    if verifier is None or verifier.passed:
        return True
    return _verifier_failure_category(verifier) not in _NON_REPAIRABLE_VERIFIER_CATEGORIES


def _verifier_error_text(verifier: VerifierResult | None) -> str:
    if verifier is None:
        return ""
    category = _verifier_failure_category(verifier)
    summary = str(verifier.summary or "").strip() or "verification failed"
    if category in _NON_REPAIRABLE_VERIFIER_CATEGORIES and category not in summary:
        return f"verification blocker ({category}): {summary}"
    return summary


def _verifier_feedback(verifier: VerifierResult | None) -> str:
    if verifier is None:
        return ""
    failed = _failed_verifier_findings(verifier)
    if not failed:
        return ""
    category = _verifier_failure_category(verifier)
    if not _verifier_failure_repairable(verifier):
        lines = [
            "The previous verification was blocked by the execution environment, not by a repairable code failure.",
            f"Category: {category}",
            "Do not edit application code just to satisfy this signal. Resolve the verifier configuration or toolchain first.",
            "",
            "Verifier evidence:",
        ]
        for finding in failed[:5]:
            output = finding.stderr or finding.stdout or f"exit code {finding.exit_code}"
            lines.append(f"- [{finding.name}] {_truncate_text(output, limit=600)}")
        return "\n".join(lines).strip()
    lines = [
        "The previous attempt did not pass verification.",
        f"Failure category: {category}",
        "Fix the issues below before you finish:",
        "",
    ]
    for finding in failed[:5]:
        output = finding.stderr or finding.stdout or f"exit code {finding.exit_code}"
        lines.append(f"- [{finding.name}] {_truncate_text(output, limit=600)}")
    return "\n".join(lines).strip()


def _unsupported_mode_result(mode: LoopMode) -> VerifierResult:
    return VerifierResult(
        profile="unsupported_mode",
        kind=mode.value,
        failure_category="unsupported_mode",
        passed=False,
        summary=f"unsupported loop mode: {mode.value}",
        findings=[
            VerifierFinding(
                name="unsupported-mode",
                command="",
                category="unsupported_mode",
                passed=False,
                exit_code=-1,
                stderr=f"unsupported loop mode: {mode.value}",
            )
        ],
    )
