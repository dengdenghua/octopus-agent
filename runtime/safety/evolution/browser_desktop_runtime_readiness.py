from __future__ import annotations

from pathlib import Path
from typing import Any

from runtime.platform.process.paths import app_paths

SCHEMA = "octopus.browser_desktop_runtime_readiness.v1"


def compute_browser_desktop_runtime_readiness(
    *,
    browser_health: dict[str, Any] | None = None,
    computer_status: dict[str, Any] | None = None,
    computer_preview: dict[str, Any] | None = None,
    computer_execute: dict[str, Any] | None = None,
    computer_replay_case: dict[str, Any] | None = None,
    auth_status: dict[str, Any] | None = None,
    cleanup_status: dict[str, Any] | None = None,
    operation_status: dict[str, Any] | None = None,
    review_queue_path: str | Path | None = None,
) -> dict[str, Any]:
    """Score the live browser/desktop automation loop.

    Static source coverage tells us whether the project has the right modules.
    This report answers the harder question: do we have runtime evidence that
    browser and desktop automation are observable, replayable, and not blocked
    by stale artifacts or leases?
    """

    replay = _replay_queue_snapshot(review_queue_path)
    repair_gate = _repair_recipe_quality_gate(review_queue_path)
    checks = []
    if auth_status is not None:
        checks.append(_auth_status_check(auth_status))
    if operation_status is not None:
        checks.append(_operation_status_check(operation_status))
    if cleanup_status is not None:
        checks.append(_cleanup_status_check(cleanup_status))
    checks.extend([
        _browser_health_check(browser_health),
        _computer_status_check(computer_status),
        _computer_preview_check(computer_preview),
        _computer_execute_check(computer_execute),
        _computer_replay_case_check(computer_replay_case),
        _replay_queue_check(replay),
        _repair_gate_check(repair_gate),
        _runtime_evidence_check(
            browser_health,
            computer_status,
            computer_execute,
            computer_replay_case,
            replay,
        ),
    ])
    passed_weight = sum(
        int(check["weight"])
        for check in checks
        if check["status"] == "pass"
    )
    total_weight = sum(int(check["weight"]) for check in checks)
    blocker_count = sum(1 for check in checks if check["severity"] == "blocker")
    warn_count = sum(1 for check in checks if check["severity"] == "warn")
    score = round(passed_weight / total_weight, 3) if total_weight else 0.0
    ready = blocker_count == 0 and warn_count == 0 and score >= 1.0
    return {
        "schema": SCHEMA,
        "score": score,
        "ready": ready,
        "verdict": "pass" if ready else "review" if blocker_count == 0 else "blocked",
        "passed": sum(1 for check in checks if check["status"] == "pass"),
        "total": len(checks),
        "passed_weight": passed_weight,
        "total_weight": total_weight,
        "blocker_count": blocker_count,
        "warn_count": warn_count,
        "checks": checks,
        "auth_status": auth_status or {"provided": False},
        "operation_status": operation_status or {"provided": False},
        "cleanup_status": cleanup_status or {"provided": False},
        "browser_health": browser_health or {"provided": False},
        "computer_status": computer_status or {"provided": False},
        "computer_preview": computer_preview or {"provided": False},
        "computer_execute": computer_execute or {"provided": False},
        "computer_replay_case": computer_replay_case or {"provided": False},
        "replay_queue": replay,
        "repair_recipe_quality_gate": repair_gate,
        "next_actions": _next_actions(checks),
        "calibration": {
            "schema": "octopus.browser_desktop_runtime_calibration.v1",
            "compares_to": {
                "codex": (
                    "Browser plugin, Chrome extension, Computer Use permission "
                    "model, screenshot control, and Record & Replay product flow"
                ),
            },
            "octopus_edge": (
                "review queue, deterministic repair recipes, stale artifact "
                "rejection, and operator-governed replay promotion"
            ),
        },
    }


def _auth_status_check(auth_status: dict[str, Any]) -> dict[str, Any]:
    if auth_status.get("auth_blocked") is True:
        return _check(
            "runtime_probe_auth",
            "Runtime probe authentication",
            "blocker",
            "fail",
            1,
            (
                "Provide a backend bearer token or enable passwordless local auth "
                "before claiming browser/desktop runtime parity."
            ),
            details={
                "bearer_token_provided": bool(auth_status.get("bearer_token_provided")),
                "auto_local_auth_enabled": bool(auth_status.get("auto_local_auth_enabled")),
                "local_auth_attempted": bool(auth_status.get("local_auth_attempted")),
                "local_auth_succeeded": bool(auth_status.get("local_auth_succeeded")),
                "auth_blocked_count": int(auth_status.get("auth_blocked_count") or 0),
            },
        )
    return _check(
        "runtime_probe_auth",
        "Runtime probe authentication",
        "info",
        "pass",
        1,
        "Runtime probe authentication is usable or not required.",
        details={
            "bearer_token_provided": bool(auth_status.get("bearer_token_provided")),
            "auto_local_auth_enabled": bool(auth_status.get("auto_local_auth_enabled")),
            "local_auth_attempted": bool(auth_status.get("local_auth_attempted")),
            "local_auth_succeeded": bool(auth_status.get("local_auth_succeeded")),
        },
    )


def _cleanup_status_check(cleanup_status: dict[str, Any]) -> dict[str, Any]:
    enabled = cleanup_status.get("enabled") is True
    required = cleanup_status.get("required") is True
    attempted = cleanup_status.get("attempted") is True
    ok = cleanup_status.get("ok") is True
    status_code = int(cleanup_status.get("status_code") or 0)
    if required and not enabled:
        return _check(
            "runtime_probe_cleanup",
            "Runtime probe browser session cleanup",
            "warn",
            "warn",
            1,
            "Enable probe browser session cleanup before claiming durable automation readiness.",
            details={
                "enabled": enabled,
                "required": required,
                "attempted": attempted,
                "ok": ok,
                "status_code": status_code,
                "error": str(cleanup_status.get("error") or ""),
            },
        )
    if required and (not attempted or not ok):
        return _check(
            "runtime_probe_cleanup",
            "Runtime probe browser session cleanup",
            "blocker",
            "fail",
            1,
            "Fix /api/browser/session/reset so runtime probes do not leak browser sessions.",
            details={
                "enabled": enabled,
                "required": required,
                "attempted": attempted,
                "ok": ok,
                "status_code": status_code,
                "error": str(cleanup_status.get("error") or ""),
            },
        )
    return _check(
        "runtime_probe_cleanup",
        "Runtime probe browser session cleanup",
        "info",
        "pass",
        1,
        "Runtime probe cleanup is usable or not required.",
        details={
            "enabled": enabled,
            "required": required,
            "attempted": attempted,
            "ok": ok,
            "status_code": status_code,
        },
    )


def _operation_status_check(operation_status: dict[str, Any]) -> dict[str, Any]:
    ok = operation_status.get("ok") is True
    failed_count = int(operation_status.get("failed_count") or 0)
    failed_operations = (
        operation_status.get("failed_operations")
        if isinstance(operation_status.get("failed_operations"), list)
        else []
    )
    return _check(
        "runtime_probe_operations",
        "Runtime probe operations",
        "info" if ok else "blocker",
        "pass" if ok else "fail",
        2,
        (
            "Runtime probe HTTP operations completed successfully."
            if ok
            else "Fix failing browser/desktop runtime probe operation(s) before claiming parity."
        ),
        details={
            "ok": ok,
            "total": int(operation_status.get("total") or 0),
            "failed_count": failed_count,
            "failed_operations": failed_operations[:5],
        },
    )


def _browser_health_check(browser_health: dict[str, Any] | None) -> dict[str, Any]:
    if not browser_health or browser_health.get("provided") is False:
        return _check(
            "browser_health_observed",
            "Browser health observed",
            "warn",
            "unknown",
            2,
            "Capture /api/browser/session/health from a real or mock browser session.",
            details={"provided": False},
        )
    healthy = browser_health.get("healthy") is True
    exists = browser_health.get("exists") is not False
    issues = _string_list(browser_health.get("issues"))
    score = float(browser_health.get("score") or 0.0)
    replay_ready = browser_health.get("replay_ready") is True
    passed = healthy and exists and score >= 0.8 and replay_ready and not issues
    severity = "info" if passed else "blocker"
    return _check(
        "browser_health_observed",
        "Browser health observed",
        severity,
        "pass" if passed else "fail",
        2,
        "Recover the browser session and capture successful replay-ready browser actions.",
        details={
            "exists": exists,
            "healthy": healthy,
            "score": score,
            "issues": issues,
            "replay_ready": replay_ready,
        },
    )


def _computer_status_check(computer_status: dict[str, Any] | None) -> dict[str, Any]:
    if not computer_status or computer_status.get("provided") is False:
        return _check(
            "computer_status_observed",
            "Computer automation status observed",
            "warn",
            "unknown",
            2,
            "Capture /api/computer/status before claiming desktop automation parity.",
            details={"provided": False},
        )
    ok = computer_status.get("ok") is True
    pyautogui_available = computer_status.get("pyautogui_available") is True
    uia_available = computer_status.get("uia_available") is True
    lease = computer_status.get("lease") if isinstance(computer_status.get("lease"), dict) else {}
    held = lease.get("held") is True
    ttl_seconds = int(lease.get("ttl_seconds") or 0)
    recent_activity = (
        computer_status.get("recent_activity")
        if isinstance(computer_status.get("recent_activity"), list)
        else []
    )
    if not ok or not pyautogui_available:
        status = "fail"
        severity = "blocker"
        next_action = "Restore screen capture and input automation before desktop execution."
    elif held and ttl_seconds > 0:
        status = "warn"
        severity = "warn"
        next_action = "Release the active desktop automation lease or wait for it to expire."
    else:
        status = "pass"
        severity = "info"
        next_action = "Computer automation status is usable."
    return _check(
        "computer_status_observed",
        "Computer automation status observed",
        severity,
        status,
        2,
        next_action,
        details={
            "ok": ok,
            "pyautogui_available": pyautogui_available,
            "uia_available": uia_available,
            "lease_held": held,
            "lease_ttl_seconds": ttl_seconds,
            "recent_activity_count": len(recent_activity),
        },
    )


def _computer_preview_check(computer_preview: dict[str, Any] | None) -> dict[str, Any]:
    if not computer_preview or computer_preview.get("provided") is False:
        return _check(
            "computer_preview_observed",
            "Computer preview authorization observed",
            "warn",
            "unknown",
            1,
            "Capture /api/computer/actions/preview to prove desktop actions are gated before execution.",
            details={"provided": False},
        )
    ok = computer_preview.get("ok") is True
    token = str(computer_preview.get("token") or "")
    action = computer_preview.get("action") if isinstance(computer_preview.get("action"), dict) else {}
    risk = computer_preview.get("risk") if isinstance(computer_preview.get("risk"), dict) else {}
    lease = computer_preview.get("lease") if isinstance(computer_preview.get("lease"), dict) else {}
    action_kind = str(action.get("action") or "")
    risk_level = str(risk.get("level") or "")
    passed = (
        ok
        and bool(token)
        and action_kind == "wait"
        and risk_level == "low"
        and lease.get("held") is not True
    )
    return _check(
        "computer_preview_observed",
        "Computer preview authorization observed",
        "info" if passed else "blocker",
        "pass" if passed else "fail",
        1,
        (
            "Computer preview authorization is usable."
            if passed
            else "Restore low-risk desktop preview tokens before claiming Computer Use parity."
        ),
        details={
            "ok": ok,
            "token_present": bool(token),
            "action": action_kind,
            "risk_level": risk_level,
            "lease_held": lease.get("held") is True,
            "expires_in_seconds": int(computer_preview.get("expires_in_seconds") or 0),
        },
    )


def _computer_execute_check(computer_execute: dict[str, Any] | None) -> dict[str, Any]:
    if not computer_execute or computer_execute.get("provided") is False:
        return _check(
            "computer_execute_observed",
            "Computer low-risk execute observed",
            "warn",
            "unknown",
            2,
            "Execute a low-risk wait action through the preview token before claiming Computer Use parity.",
            details={"provided": False},
        )
    ok = computer_execute.get("ok") is True
    action = (
        computer_execute.get("action")
        if isinstance(computer_execute.get("action"), dict)
        else {}
    )
    risk = (
        computer_execute.get("risk")
        if isinstance(computer_execute.get("risk"), dict)
        else {}
    )
    result = (
        computer_execute.get("result")
        if isinstance(computer_execute.get("result"), dict)
        else {}
    )
    lease = (
        computer_execute.get("lease")
        if isinstance(computer_execute.get("lease"), dict)
        else {}
    )
    action_kind = str(action.get("action") or "")
    risk_level = str(risk.get("level") or "")
    passed = (
        ok
        and action_kind == "wait"
        and risk_level == "low"
        and "error" not in result
        and lease.get("held") is True
    )
    return _check(
        "computer_execute_observed",
        "Computer low-risk execute observed",
        "info" if passed else "blocker",
        "pass" if passed else "fail",
        2,
        (
            "Low-risk desktop execute completed through the preview token."
            if passed
            else "Restore preview-token desktop execution before claiming Computer Use parity."
        ),
        details={
            "ok": ok,
            "action": action_kind,
            "risk_level": risk_level,
            "lease_held": lease.get("held") is True,
            "result_keys": sorted(str(key) for key in result.keys()),
            "error": str(result.get("error") or computer_execute.get("error") or ""),
        },
    )


def _computer_replay_case_check(
    computer_replay_case: dict[str, Any] | None,
) -> dict[str, Any]:
    if not computer_replay_case or computer_replay_case.get("provided") is False:
        return _check(
            "computer_replay_case_observed",
            "Computer replay case observed",
            "warn",
            "unknown",
            2,
            "Read /api/computer/activity/replay-case after execution to prove desktop actions are replayable.",
            details={"provided": False},
        )
    schema_ok = (
        computer_replay_case.get("schema")
        == "octopus.computer_activity_replay_case.v1"
    )
    replay_ready = computer_replay_case.get("replay_ready") is True
    activity_count = int(computer_replay_case.get("activity_count") or 0)
    last_activity = (
        computer_replay_case.get("last_activity")
        if isinstance(computer_replay_case.get("last_activity"), dict)
        else {}
    )
    passed = (
        schema_ok
        and replay_ready
        and activity_count >= 2
        and last_activity.get("event") == "action_executed"
        and last_activity.get("ok") is True
    )
    return _check(
        "computer_replay_case_observed",
        "Computer replay case observed",
        "info" if passed else "blocker",
        "pass" if passed else "fail",
        2,
        (
            "Desktop action replay case is available."
            if passed
            else "Capture an action_executed desktop replay case after the low-risk probe."
        ),
        details={
            "schema_ok": schema_ok,
            "replay_ready": replay_ready,
            "activity_count": activity_count,
            "pending_count": int(computer_replay_case.get("pending_count") or 0),
            "last_event": str(last_activity.get("event") or ""),
            "case_id_present": bool(str(computer_replay_case.get("case_id") or "")),
            "fingerprint_present": bool(str(computer_replay_case.get("fingerprint") or "")),
        },
    )


def _replay_queue_check(replay: dict[str, Any]) -> dict[str, Any]:
    stale = int(replay.get("stale_source_artifact_count") or 0)
    pending = int(replay.get("pending_count") or 0)
    reviewed = int(replay.get("reviewed_count") or 0)
    total = int(replay.get("total") or 0)
    if stale:
        status = "fail"
        severity = "blocker"
        next_action = f"Regenerate or reject {stale} stale browser/desktop replay artifact(s)."
    elif pending:
        status = "warn"
        severity = "warn"
        next_action = f"Review {pending} pending browser/desktop replay case(s)."
    else:
        status = "pass"
        severity = "info"
        next_action = "Replay queue has no blocking browser/desktop cases."
    return _check(
        "replay_queue_clean",
        "Replay queue clean",
        severity,
        status,
        2,
        next_action,
        details={
            "total": total,
            "pending_count": pending,
            "reviewed_count": reviewed,
            "stale_source_artifact_count": stale,
            "by_status": replay.get("by_status") or {},
        },
    )


def _repair_gate_check(repair_gate: dict[str, Any]) -> dict[str, Any]:
    ready = repair_gate.get("ready") is True
    blockers = _string_list(repair_gate.get("blockers"))
    score = float(repair_gate.get("score") or 0.0)
    passed = ready and not blockers and score >= 1.0
    return _check(
        "repair_recipe_gate_ready",
        "Repair recipe gate ready",
        "info" if passed else "blocker",
        "pass" if passed else "fail",
        2,
        "Attach rerun evidence to browser/desktop repair recipes before promotion.",
        details={
            "ready": ready,
            "score": score,
            "blockers": blockers,
            "recipe_count": int(repair_gate.get("recipe_count") or 0),
            "pending_count": int(repair_gate.get("pending_count") or 0),
        },
    )


def _runtime_evidence_check(
    browser_health: dict[str, Any] | None,
    computer_status: dict[str, Any] | None,
    computer_execute: dict[str, Any] | None,
    computer_replay_case: dict[str, Any] | None,
    replay: dict[str, Any],
) -> dict[str, Any]:
    browser_evidence = bool(browser_health and browser_health.get("replay_ready") is True)
    computer_recent = 0
    if isinstance(computer_status, dict):
        recent = computer_status.get("recent_activity")
        computer_recent = len(recent) if isinstance(recent, list) else 0
    desktop_execute = bool(computer_execute and computer_execute.get("ok") is True)
    desktop_replay = bool(
        computer_replay_case
        and computer_replay_case.get("schema")
        == "octopus.computer_activity_replay_case.v1"
        and computer_replay_case.get("replay_ready") is True
    )
    replay_total = int(replay.get("total") or 0)
    has_evidence = (
        browser_evidence
        or computer_recent > 0
        or desktop_execute
        or desktop_replay
        or replay_total > 0
    )
    return _check(
        "runtime_evidence_available",
        "Runtime evidence available",
        "info" if has_evidence else "warn",
        "pass" if has_evidence else "unknown",
        1,
        "Run one browser or desktop automation flow and queue replay evidence.",
        details={
            "browser_replay_ready": browser_evidence,
            "computer_recent_activity_count": computer_recent,
            "computer_execute_ok": desktop_execute,
            "computer_replay_ready": desktop_replay,
            "replay_case_count": replay_total,
        },
    )


def _replay_queue_snapshot(review_queue_path: str | Path | None) -> dict[str, Any]:
    try:
        from runtime.memory.learning.review_queue import ReviewQueue

        queue = ReviewQueue(
            Path(review_queue_path)
            if review_queue_path is not None
            else app_paths().review_queue_path,
        )
        rows = queue.items(target_bucket="browser_desktop_replay", limit=1000)["items"]
    except Exception as exc:  # noqa: BLE001
        return {
            "schema": "octopus.browser_desktop_runtime_replay_queue.v1",
            "available": False,
            "error": str(exc),
            "total": 0,
            "pending_count": 0,
            "reviewed_count": 0,
            "stale_source_artifact_count": 0,
            "by_status": {},
        }

    by_status: dict[str, int] = {}
    stale = 0
    for row in rows:
        status = str(row.get("status") or "pending")
        by_status[status] = by_status.get(status, 0) + 1
        if status == "pending" and _has_stale_source_artifact(row):
            stale += 1
    reviewed = (
        by_status.get("promoted", 0)
        + by_status.get("rejected", 0)
        + by_status.get("archived", 0)
    )
    return {
        "schema": "octopus.browser_desktop_runtime_replay_queue.v1",
        "available": True,
        "total": len(rows),
        "pending_count": by_status.get("pending", 0),
        "reviewed_count": reviewed,
        "stale_source_artifact_count": stale,
        "by_status": dict(sorted(by_status.items())),
    }


def _repair_recipe_quality_gate(
    review_queue_path: str | Path | None,
) -> dict[str, Any]:
    try:
        from runtime.safety.evolution.browser_desktop_repair_recipes import (
            compute_browser_desktop_repair_recipe_quality_gate,
        )

        return compute_browser_desktop_repair_recipe_quality_gate(
            review_queue_path=review_queue_path,
            limit=1000,
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "schema": "octopus.browser_desktop_repair_recipe_quality_gate.v1",
            "score": 0.0,
            "ready": False,
            "blockers": ["quality_gate_unavailable"],
            "signals": {},
            "error": str(exc),
        }


def _has_stale_source_artifact(row: dict[str, Any]) -> bool:
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    kind = str(row.get("candidate_kind") or "")
    if kind == "browser_pixel_replay_gate_case":
        artifact = metadata.get("artifact") if isinstance(metadata.get("artifact"), dict) else {}
        local_path = str(artifact.get("local_path") or "").strip()
        return bool(local_path) and not Path(local_path).is_file()
    if kind == "computer_activity_replay_case":
        last_activity = (
            metadata.get("last_activity")
            if isinstance(metadata.get("last_activity"), dict)
            else {}
        )
        return bool(last_activity.get("stale") is True)
    return False


def _check(
    check_id: str,
    title: str,
    severity: str,
    status: str,
    weight: int,
    next_action: str,
    *,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": check_id,
        "title": title,
        "severity": severity,
        "status": status,
        "passed": status == "pass",
        "weight": weight,
        "details": details or {},
        "next_action": next_action,
    }


def _next_actions(checks: list[dict[str, Any]]) -> list[str]:
    actions = [
        str(check["next_action"])
        for check in checks
        if check["status"] != "pass"
    ]
    if not actions:
        return ["Browser/desktop runtime automation is replay-ready."]
    return actions


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    if value:
        return [str(value)]
    return []


__all__ = [
    "SCHEMA",
    "compute_browser_desktop_runtime_readiness",
]
