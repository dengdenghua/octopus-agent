from __future__ import annotations

from pathlib import Path
from typing import Any

SCHEMA = "octopus.browser_desktop_capability_canary.v1"
CAPABILITY_SCHEMA = "octopus.browser_desktop_capability_canary.row.v1"


def compute_browser_desktop_capability_canary(
    *,
    browser_health: dict[str, Any] | None = None,
    computer_status: dict[str, Any] | None = None,
    computer_preview: dict[str, Any] | None = None,
    computer_execute: dict[str, Any] | None = None,
    computer_replay_case: dict[str, Any] | None = None,
    chrome_relay_handshake: dict[str, Any] | None = None,
    real_chrome_relay_probe: dict[str, Any] | None = None,
    operation_status: dict[str, Any] | None = None,
    cleanup_status: dict[str, Any] | None = None,
    runtime_readiness: dict[str, Any] | None = None,
    productization_readiness: dict[str, Any] | None = None,
    cold_start_readiness: dict[str, Any] | None = None,
    repair_recipe_quality_gate: dict[str, Any] | None = None,
    review_queue_path: str | Path | None = None,
) -> dict[str, Any]:
    """Split browser/desktop automation into Codex-comparable capability rows."""

    productization = _dict(productization_readiness)
    productization_probe = _dict(productization.get("probe"))
    cold_start = _dict(cold_start_readiness)
    cold_start_probe = _dict(cold_start.get("probe"))
    runtime = _dict(runtime_readiness)
    replay_queue = _dict(runtime.get("replay_queue"))
    repair_gate = _dict(repair_recipe_quality_gate)

    rows = [
        _local_browser_row(
            browser_health=_dict(browser_health),
            operation_status=_dict(operation_status),
            cleanup_status=_dict(cleanup_status),
        ),
        _chrome_signed_in_row(productization_probe=productization_probe),
        _chrome_relay_runtime_row(
            chrome_relay_handshake=_dict(chrome_relay_handshake),
        ),
        _real_chrome_profile_row(
            real_chrome_relay_probe=_dict(real_chrome_relay_probe),
        ),
        _desktop_control_row(
            computer_status=_dict(computer_status),
            computer_preview=_dict(computer_preview),
            productization_probe=productization_probe,
        ),
        _desktop_execute_replay_row(
            computer_execute=_dict(computer_execute),
            computer_replay_case=_dict(computer_replay_case),
        ),
        _vision_grounding_row(productization=productization),
        _permission_safety_row(
            productization_probe=productization_probe,
            computer_preview=_dict(computer_preview),
        ),
        _replay_repair_row(
            runtime=runtime,
            replay_queue=replay_queue,
            repair_gate=repair_gate,
        ),
        _cold_start_row(cold_start=cold_start, cold_start_probe=cold_start_probe),
    ]
    runtime_verified = [
        row for row in rows
        if row["evidence_level"] == "runtime_verified" and row["passed"]
    ]
    real_chrome_verified = [
        row for row in rows
        if row["evidence_level"] == "real_chrome_profile_verified" and row["passed"]
    ]
    control_plane_verified = [
        row for row in rows
        if row["evidence_level"] == "control_plane_verified" and row["passed"]
    ]
    passed_weight = sum(int(row["weight"]) for row in rows if row["passed"])
    total_weight = sum(int(row["weight"]) for row in rows)
    score = round(passed_weight / total_weight, 3) if total_weight else 0.0
    blockers = [
        str(row["id"])
        for row in rows
        if not row["passed"] and row["severity"] == "blocker"
    ]
    warnings = [
        str(row["id"])
        for row in rows
        if not row["passed"] and row["severity"] == "warn"
    ]
    warning_weight = sum(
        int(row["weight"])
        for row in rows
        if row["severity"] == "warn"
    )
    blocking_weight = sum(
        int(row["weight"])
        for row in rows
        if row["severity"] == "blocker"
    )
    effective_score = (
        round(passed_weight / max(1, total_weight - warning_weight), 3)
        if warning_weight < total_weight
        else score
    )
    ready = (
        effective_score >= 1.0
        and not blockers
        and len(runtime_verified) >= 6
        and len(control_plane_verified) >= 1
    )
    return {
        "schema": SCHEMA,
        "ready": ready,
        "verdict": "pass" if ready else "blocked" if blockers else "review",
        "score": score,
        "effective_score": effective_score,
        "passed": sum(1 for row in rows if row["passed"]),
        "total": len(rows),
        "passed_weight": passed_weight,
        "total_weight": total_weight,
        "blocking_weight": blocking_weight,
        "warning_weight": warning_weight,
        "runtime_verified_count": len(runtime_verified),
        "real_chrome_profile_verified_count": len(real_chrome_verified),
        "control_plane_verified_count": len(control_plane_verified),
        "blockers": blockers,
        "warnings": warnings,
        "capabilities": rows,
        "review_queue_path": str(review_queue_path) if review_queue_path else "",
        "calibration": {
            "schema": "octopus.browser_desktop_capability_calibration.v1",
            "codex_surfaces": [
                "in_app_browser",
                "chrome_extension_signed_in_browser",
                "computer_use_desktop_apps",
                "record_replay",
            ],
            "evidence_levels": {
                "runtime_verified": (
                    "A live or cached runtime probe observed the capability."
                ),
                "control_plane_verified": (
                    "Static/productized control plane is present, but this probe "
                    "did not operate the user's signed-in GUI surface directly."
                ),
                "real_chrome_profile_verified": (
                    "An already-connected Chrome extension or bookmarklet returned "
                    "page evidence from the user's browser context."
                ),
            },
            "score_ceiling_without_runtime": 93,
            "score_ceiling_with_runtime": 94,
            "score_ceiling_with_desktop_execute_replay": 95,
            "score_ceiling_with_real_chrome_profile": 96,
            "signed_in_chrome_note": (
                "The relay runtime handshake proves the extension command/result "
                "transport, not that a human user's Chrome profile has completed "
                "a logged-in website flow."
            ),
        },
        "next_actions": _next_actions(rows),
    }


def _local_browser_row(
    *,
    browser_health: dict[str, Any],
    operation_status: dict[str, Any],
    cleanup_status: dict[str, Any],
) -> dict[str, Any]:
    healthy = (
        browser_health.get("healthy") is True
        and browser_health.get("replay_ready") is True
        and float(browser_health.get("score") or 0.0) >= 0.8
    )
    operations_ok = operation_status.get("ok") is True
    cleanup_ok = cleanup_status.get("ok") is True
    return _row(
        "in_app_browser_runtime",
        "Local/in-app browser runtime",
        healthy and operations_ok and cleanup_ok,
        "runtime_verified",
        3,
        "Run a browser session probe that navigates, acts, checks health, and cleans up.",
        details={
            "healthy": healthy,
            "operations_ok": operations_ok,
            "cleanup_ok": cleanup_ok,
            "browser_score": float(browser_health.get("score") or 0.0),
            "replay_ready": browser_health.get("replay_ready") is True,
        },
    )


def _chrome_signed_in_row(*, productization_probe: dict[str, Any]) -> dict[str, Any]:
    ready = (
        productization_probe.get("manifest_ready") is True
        and productization_probe.get("relay_loop_ready") is True
        and productization_probe.get("chrome_control_plane_ready") is True
    )
    return _row(
        "chrome_signed_in_control_plane",
        "Signed-in Chrome control plane",
        ready,
        "control_plane_verified",
        2,
        (
            "Verify the Chrome relay against a real signed-in Chrome profile before "
            "claiming full Chrome parity."
        ),
        details={
            "manifest_ready": productization_probe.get("manifest_ready") is True,
            "relay_loop_ready": productization_probe.get("relay_loop_ready") is True,
            "chrome_control_plane_ready": (
                productization_probe.get("chrome_control_plane_ready") is True
            ),
        },
    )


def _chrome_relay_runtime_row(
    *,
    chrome_relay_handshake: dict[str, Any],
) -> dict[str, Any]:
    command_result = _dict(chrome_relay_handshake.get("command_result"))
    status = _dict(chrome_relay_handshake.get("status"))
    ready = (
        chrome_relay_handshake.get("schema")
        == "octopus.browser_chrome_relay_handshake.v1"
        and chrome_relay_handshake.get("ok") is True
        and command_result.get("ok") is True
        and bool(str(chrome_relay_handshake.get("command_id") or ""))
        and status.get("connected") is True
    )
    return _row(
        "chrome_relay_runtime_handshake",
        "Chrome relay runtime handshake",
        ready,
        "runtime_verified",
        2,
        "Run the relay heartbeat, command delivery, result callback, and status loop.",
        details={
            "handshake_ok": chrome_relay_handshake.get("ok") is True,
            "command_result_ok": command_result.get("ok") is True,
            "connected": status.get("connected") is True,
            "command_id_present": bool(str(chrome_relay_handshake.get("command_id") or "")),
            "error": str(chrome_relay_handshake.get("error") or ""),
        },
    )


def _real_chrome_profile_row(
    *,
    real_chrome_relay_probe: dict[str, Any],
) -> dict[str, Any]:
    enabled = real_chrome_relay_probe.get("enabled") is True
    result = _dict(real_chrome_relay_probe.get("command_result"))
    active_tab = _dict(real_chrome_relay_probe.get("active_tab"))
    ready = (
        enabled
        and real_chrome_relay_probe.get("schema") == "octopus.real_chrome_relay_probe.v1"
        and real_chrome_relay_probe.get("ok") is True
        and real_chrome_relay_probe.get("connected") is True
        and result.get("ok") is True
    )
    return _row(
        "real_chrome_profile_flow",
        "Real Chrome profile relay flow",
        ready,
        "real_chrome_profile_verified",
        1,
        "Run --real-chrome-relay with the Chrome extension or bookmarklet already connected.",
        details={
            "enabled": enabled,
            "connected": real_chrome_relay_probe.get("connected") is True,
            "command_result_ok": result.get("ok") is True,
            "extension_version": str(real_chrome_relay_probe.get("extension_version") or ""),
            "active_tab_title": str(active_tab.get("title") or ""),
            "active_tab_url": str(active_tab.get("url") or ""),
            "error": str(real_chrome_relay_probe.get("error") or ""),
        },
        severity="info" if ready else "warn",
    )


def _desktop_control_row(
    *,
    computer_status: dict[str, Any],
    computer_preview: dict[str, Any],
    productization_probe: dict[str, Any],
) -> dict[str, Any]:
    status_ok = (
        computer_status.get("ok") is True
        and computer_status.get("pyautogui_available") is True
    )
    preview_ok = (
        computer_preview.get("ok") is True
        and bool(str(computer_preview.get("token") or ""))
        and _dict(computer_preview.get("risk")).get("level") == "low"
    )
    policy_ready = productization_probe.get("computer_policy_endpoint_ready") is True
    return _row(
        "desktop_control_preview_lease",
        "Desktop control preview and lease",
        status_ok and preview_ok and policy_ready,
        "runtime_verified",
        3,
        "Capture desktop status plus a low-risk preview token under the app policy.",
        details={
            "status_ok": status_ok,
            "preview_ok": preview_ok,
            "policy_ready": policy_ready,
            "uia_available": computer_status.get("uia_available") is True,
            "recent_activity_count": len(_list(computer_status.get("recent_activity"))),
        },
    )


def _desktop_execute_replay_row(
    *,
    computer_execute: dict[str, Any],
    computer_replay_case: dict[str, Any],
) -> dict[str, Any]:
    action = _dict(computer_execute.get("action"))
    risk = _dict(computer_execute.get("risk"))
    result = _dict(computer_execute.get("result"))
    last_activity = _dict(computer_replay_case.get("last_activity"))
    execute_ok = (
        computer_execute.get("ok") is True
        and action.get("action") == "wait"
        and risk.get("level") == "low"
        and "error" not in result
    )
    replay_ok = (
        computer_replay_case.get("schema")
        == "octopus.computer_activity_replay_case.v1"
        and computer_replay_case.get("replay_ready") is True
        and int(computer_replay_case.get("activity_count") or 0) >= 2
        and last_activity.get("event") == "action_executed"
        and last_activity.get("ok") is True
    )
    return _row(
        "desktop_execute_replay_flow",
        "Desktop execute and replay flow",
        execute_ok and replay_ok,
        "runtime_verified",
        3,
        "Run preview -> execute(wait) -> replay-case in the runtime probe.",
        details={
            "execute_ok": execute_ok,
            "replay_ok": replay_ok,
            "action": str(action.get("action") or ""),
            "risk_level": str(risk.get("level") or ""),
            "activity_count": int(computer_replay_case.get("activity_count") or 0),
            "last_event": str(last_activity.get("event") or ""),
            "case_id_present": bool(str(computer_replay_case.get("case_id") or "")),
        },
    )


def _vision_grounding_row(*, productization: dict[str, Any]) -> dict[str, Any]:
    checks = _checks_by_id(productization.get("checks"))
    grounding = checks.get("desktop_grounding_modes", {})
    passed = grounding.get("passed") is True
    return _row(
        "vision_and_uia_grounding",
        "Vision and UIA grounding",
        passed,
        "control_plane_verified",
        2,
        "Keep UIA and vision grounding contracts wired and covered by router tests.",
        details={
            "desktop_grounding_modes": passed,
            "missing_terms": grounding.get("missing_terms") or [],
        },
    )


def _permission_safety_row(
    *,
    productization_probe: dict[str, Any],
    computer_preview: dict[str, Any],
) -> dict[str, Any]:
    policy_probe = _dict(productization_probe.get("policy_probe"))
    preview_low_risk = _dict(computer_preview.get("risk")).get("level") == "low"
    ready = policy_probe.get("ok") is True and preview_low_risk
    return _row(
        "permission_and_policy_safety",
        "Permission and policy safety",
        ready,
        "runtime_verified",
        3,
        "Keep allow/deny/prompt policy and low-risk preview enforcement passing.",
        details={
            "policy_probe_ok": policy_probe.get("ok") is True,
            "preview_low_risk": preview_low_risk,
            "denied_decision": _dict(policy_probe.get("denied_decision")).get("decision"),
            "prompt_decision": _dict(policy_probe.get("prompt_decision")).get("decision"),
        },
    )


def _replay_repair_row(
    *,
    runtime: dict[str, Any],
    replay_queue: dict[str, Any],
    repair_gate: dict[str, Any],
) -> dict[str, Any]:
    runtime_ready = (
        runtime.get("ready") is True
        and int(runtime.get("blocker_count") or 0) == 0
        and int(runtime.get("warn_count") or 0) == 0
    )
    replay_clean = (
        int(replay_queue.get("pending_count") or 0) == 0
        and int(replay_queue.get("stale_source_artifact_count") or 0) == 0
    )
    repair_ready = (
        repair_gate.get("ready") is True
        and float(repair_gate.get("score") or 0.0) >= 1.0
        and not repair_gate.get("blockers")
    )
    return _row(
        "record_replay_repair_loop",
        "Record/replay repair loop",
        runtime_ready and replay_clean and repair_ready,
        "runtime_verified",
        3,
        "Clear replay blockers and keep deterministic repair recipe gates green.",
        details={
            "runtime_ready": runtime_ready,
            "replay_clean": replay_clean,
            "repair_ready": repair_ready,
            "pending_count": int(replay_queue.get("pending_count") or 0),
            "stale_source_artifact_count": int(
                replay_queue.get("stale_source_artifact_count") or 0
            ),
        },
    )


def _cold_start_row(
    *,
    cold_start: dict[str, Any],
    cold_start_probe: dict[str, Any],
) -> dict[str, Any]:
    ready = (
        cold_start.get("ready") is True
        and cold_start.get("verdict") == "pass"
        and float(cold_start.get("score") or 0.0) >= 1.0
        and cold_start_probe.get("ok") is True
    )
    return _row(
        "offline_bootstrap_recoverability",
        "Offline bootstrap recoverability",
        ready,
        "control_plane_verified",
        1,
        "Keep offline browser/desktop bootstrap and recovery probes complete.",
        details={
            "cold_start_ready": cold_start.get("ready") is True,
            "cold_start_probe_ok": cold_start_probe.get("ok") is True,
        },
    )


def _row(
    row_id: str,
    title: str,
    passed: bool,
    evidence_level: str,
    weight: int,
    next_action: str,
    *,
    details: dict[str, Any],
    severity: str | None = None,
) -> dict[str, Any]:
    return {
        "schema": CAPABILITY_SCHEMA,
        "id": row_id,
        "title": title,
        "passed": bool(passed),
        "severity": severity or ("info" if passed else "blocker"),
        "evidence_level": evidence_level,
        "weight": weight,
        "details": details,
        "next_action": next_action,
    }


def _next_actions(rows: list[dict[str, Any]]) -> list[str]:
    actions = [
        str(row["next_action"])
        for row in rows
        if row.get("passed") is not True and row.get("next_action")
    ]
    if not actions:
        actions.append("Browser/desktop capability canary is ready.")
    return actions


def _checks_by_id(value: Any) -> dict[str, dict[str, Any]]:
    checks = {}
    for row in _list(value):
        if isinstance(row, dict):
            checks[str(row.get("id") or "")] = row
    return checks


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


__all__ = [
    "CAPABILITY_SCHEMA",
    "SCHEMA",
    "compute_browser_desktop_capability_canary",
]
