from __future__ import annotations

import shlex
import sys
from pathlib import Path
from typing import Any

from runtime.protocol import ItemStatus, VerificationItem
from runtime.safety.evolution.auto_verifier_metrics import (
    explain_verification_ranking,
    rank_verification_commands,
    record_auto_verifier_decision,
    record_auto_verifier_metric,
)
from runtime.safety.sandboxing.sandbox import (
    SandboxPolicy,
    SandboxRunner,
    SandboxViolation,
)

_OUTPUT_CAP = 4000
_TIMEOUT_S = 45.0


def run_highest_priority_verification(
    plan: dict[str, Any],
    *,
    sandbox_policy: dict[str, Any] | None,
) -> VerificationItem | None:
    if not _sandbox_allows_auto_verification(sandbox_policy):
        return None
    workspace = _workspace(plan)
    if workspace is None:
        return None
    commands = plan.get("commands")
    if not isinstance(commands, list):
        return None
    candidates = [item for item in commands if isinstance(item, dict)]
    ranking = explain_verification_ranking(candidates)
    for command in rank_verification_commands(candidates):
        item = _run_command(command, workspace, sandbox_policy or {})
        if item is not None:
            _record_decision(ranking, item.command)
            return item
    return None


def _sandbox_allows_auto_verification(policy: dict[str, Any] | None) -> bool:
    if not isinstance(policy, dict):
        return False
    return str(policy.get("type") or "") == "workspaceWrite"


def _workspace(plan: dict[str, Any]) -> Path | None:
    raw = plan.get("workspace")
    if not isinstance(raw, str) or not raw.strip():
        return None
    path = Path(raw).expanduser().resolve(strict=False)
    return path if path.is_dir() else None


def _run_command(
    command: dict[str, Any],
    workspace: Path,
    sandbox_policy: dict[str, Any],
) -> VerificationItem | None:
    raw = str(command.get("command") or "").strip()
    target = str(command.get("target") or "").strip()
    if not raw or not _target_exists(workspace, target):
        return None
    parsed = _parse_allowed_command(raw, workspace)
    if parsed is None:
        return None
    argv, cwd = parsed
    policy = SandboxPolicy(
        workspace=workspace,
        allow_network=bool(sandbox_policy.get("networkAccess")),
        timeout_s=_TIMEOUT_S,
        max_output_bytes=_OUTPUT_CAP,
    )
    try:
        result = SandboxRunner(policy).run(argv, cwd=cwd)
    except SandboxViolation as exc:
        _record_metric(
            command,
            ok=False,
            exit_code=None,
            duration_ms=0,
            reason=str(exc),
        )
        return VerificationItem(
            command=raw,
            kind=_verification_kind(command),
            status=ItemStatus.FAILED,
            exit_code=None,
            summary="Auto verification was blocked by sandbox policy.",
            stdout_tail=None,
            stderr_tail=str(exc)[:_OUTPUT_CAP],
            related_files=[target] if target else [],
        )

    ok = result.exit_code == 0 and not result.timed_out
    _record_metric(
        command,
        ok=ok,
        exit_code=result.exit_code,
        duration_ms=result.duration_ms,
        reason="timed_out" if result.timed_out else "",
    )
    output = (result.stdout or "").strip()
    error = (result.stderr or "").strip()
    summary = (
        "Auto verification passed."
        if ok
        else "Auto verification failed."
        if not result.timed_out
        else "Auto verification timed out."
    )
    return VerificationItem(
        command=raw,
        kind=_verification_kind(command),
        status=ItemStatus.COMPLETED if ok else ItemStatus.FAILED,
        exit_code=result.exit_code,
        summary=summary,
        stdout_tail=output[:_OUTPUT_CAP] if output else None,
        stderr_tail=error[:_OUTPUT_CAP] if error else None,
        related_files=[target] if target else [],
    )


def _target_exists(workspace: Path, target: str) -> bool:
    if not target:
        return False
    path = (workspace / target).resolve(strict=False)
    try:
        path.relative_to(workspace)
    except ValueError:
        return False
    return path.exists()


def _parse_allowed_command(raw: str, workspace: Path) -> tuple[list[str], Path] | None:
    try:
        parts = shlex.split(raw)
    except ValueError:
        return None
    if not parts:
        return None
    cwd = workspace
    if len(parts) >= 5 and parts[0] == "cd" and parts[2] == "&&":
        cwd = (workspace / parts[1]).resolve(strict=False)
        try:
            cwd.relative_to(workspace)
        except ValueError:
            return None
        if not cwd.is_dir():
            return None
        parts = parts[3:]
    if _is_allowed_python_command(parts):
        if parts[0] == "python":
            parts = [sys.executable, *parts[1:]]
        return parts, cwd
    if _is_allowed_pnpm_command(parts):
        return parts, cwd
    return None


def _is_allowed_python_command(parts: list[str]) -> bool:
    if len(parts) < 4 or parts[0] not in {"python", sys.executable} or parts[1] != "-m":
        return False
    module = parts[2]
    if module == "ruff":
        return len(parts) >= 5 and parts[3] == "check"
    return module == "pytest"


def _is_allowed_pnpm_command(parts: list[str]) -> bool:
    if len(parts) < 2 or parts[0] != "pnpm":
        return False
    if parts[1] == "check":
        return True
    return len(parts) >= 4 and parts[1:3] == ["vitest", "run"]


def _verification_kind(command: dict[str, Any]) -> str:
    kind = str(command.get("kind") or "manual")
    return kind if kind in {"test", "lint", "typecheck", "build", "diagnostic", "manual"} else "manual"


def _record_metric(
    command: dict[str, Any],
    *,
    ok: bool,
    exit_code: int | None,
    duration_ms: int,
    reason: str = "",
) -> None:
    try:
        record_auto_verifier_metric(
            command=str(command.get("command") or ""),
            kind=_verification_kind(command),
            ok=ok,
            exit_code=exit_code,
            duration_ms=duration_ms,
            target=str(command.get("target") or ""),
            reason=reason or str(command.get("reason") or ""),
        )
    except Exception:  # noqa: BLE001 - metrics must not affect verification
        return


def _record_decision(ranking: list[dict[str, Any]], selected_command: str) -> None:
    try:
        record_auto_verifier_decision(
            candidates=ranking,
            selected_command=selected_command,
        )
    except Exception:  # noqa: BLE001 - decision telemetry must not affect verification
        return


__all__ = ["run_highest_priority_verification"]
