from __future__ import annotations

from runtime.safety.evolution.browser_desktop_capability_canary import (
    compute_browser_desktop_capability_canary,
)


def _healthy_browser() -> dict[str, object]:
    return {
        "healthy": True,
        "score": 1.0,
        "issues": [],
        "replay_ready": True,
    }


def _healthy_computer() -> dict[str, object]:
    return {
        "ok": True,
        "pyautogui_available": True,
        "uia_available": True,
        "lease": {"held": False, "ttl_seconds": 0},
        "recent_activity": [{"event": "action_executed", "ok": True}],
    }


def _healthy_preview() -> dict[str, object]:
    return {
        "ok": True,
        "token": "preview-token",
        "action": {"action": "wait", "ms": 10},
        "risk": {"level": "low"},
        "lease": {"held": False},
    }


def _healthy_execute() -> dict[str, object]:
    return {
        "ok": True,
        "action": {"action": "wait", "ms": 10},
        "risk": {"level": "low"},
        "result": {"waited_ms": 10},
        "lease": {"held": True},
    }


def _healthy_replay_case() -> dict[str, object]:
    return {
        "schema": "octopus.computer_activity_replay_case.v1",
        "replay_ready": True,
        "case_id": "computer-activity:abc123",
        "fingerprint": "0123456789abcdef",
        "activity_count": 2,
        "pending_count": 0,
        "last_activity": {"event": "action_executed", "ok": True},
    }


def _productization() -> dict[str, object]:
    return {
        "schema": "octopus.browser_desktop_productization_readiness.v1",
        "ready": True,
        "score": 1.0,
        "probe": {
            "ok": True,
            "manifest_ready": True,
            "relay_loop_ready": True,
            "chrome_control_plane_ready": True,
            "computer_policy_endpoint_ready": True,
            "policy_probe": {
                "ok": True,
                "denied_decision": {"decision": "denied"},
                "prompt_decision": {"decision": "prompt"},
            },
        },
        "checks": [
            {"id": "desktop_grounding_modes", "passed": True, "missing_terms": []},
        ],
    }


def _runtime_readiness() -> dict[str, object]:
    return {
        "ready": True,
        "score": 1.0,
        "blocker_count": 0,
        "warn_count": 0,
        "replay_queue": {
            "pending_count": 0,
            "stale_source_artifact_count": 0,
        },
    }


def _relay_handshake() -> dict[str, object]:
    return {
        "schema": "octopus.browser_chrome_relay_handshake.v1",
        "ok": True,
        "command_id": "cmd-1",
        "command_result": {"ok": True, "id": "cmd-1"},
        "status": {"connected": True},
    }


def _real_relay() -> dict[str, object]:
    return {
        "schema": "octopus.real_chrome_relay_probe.v1",
        "enabled": True,
        "ok": True,
        "connected": True,
        "extension_version": "0.2.0",
        "active_tab": {"id": 1, "url": "https://example.test", "title": "Example"},
        "command_result": {
            "ok": True,
            "id": "real-cmd-1",
            "title": "Example",
            "url": "https://example.test",
            "nodes": {"role": "document"},
        },
    }


def test_browser_desktop_capability_canary_splits_codex_surfaces() -> None:
    report = compute_browser_desktop_capability_canary(
        browser_health=_healthy_browser(),
        computer_status=_healthy_computer(),
        computer_preview=_healthy_preview(),
        computer_execute=_healthy_execute(),
        computer_replay_case=_healthy_replay_case(),
        chrome_relay_handshake=_relay_handshake(),
        real_chrome_relay_probe=_real_relay(),
        operation_status={"ok": True},
        cleanup_status={"ok": True},
        runtime_readiness=_runtime_readiness(),
        productization_readiness=_productization(),
        cold_start_readiness={
            "ready": True,
            "verdict": "pass",
            "score": 1.0,
            "probe": {"ok": True},
        },
        repair_recipe_quality_gate={
            "schema": "octopus.browser_desktop_repair_recipe_quality_gate.v1",
            "ready": True,
            "score": 1.0,
            "blockers": [],
        },
    )

    assert report["schema"] == "octopus.browser_desktop_capability_canary.v1"
    assert report["ready"] is True
    assert report["score"] == 1.0
    assert report["effective_score"] == 1.0
    assert report["runtime_verified_count"] == 6
    assert report["real_chrome_profile_verified_count"] == 1
    assert report["control_plane_verified_count"] == 3
    assert {row["id"] for row in report["capabilities"]} == {
        "in_app_browser_runtime",
        "chrome_signed_in_control_plane",
        "chrome_relay_runtime_handshake",
        "real_chrome_profile_flow",
        "desktop_control_preview_lease",
        "desktop_execute_replay_flow",
        "vision_and_uia_grounding",
        "permission_and_policy_safety",
        "record_replay_repair_loop",
        "offline_bootstrap_recoverability",
    }
    chrome = next(
        row for row in report["capabilities"]
        if row["id"] == "chrome_signed_in_control_plane"
    )
    assert chrome["evidence_level"] == "control_plane_verified"
    real = next(
        row for row in report["capabilities"]
        if row["id"] == "real_chrome_profile_flow"
    )
    assert real["evidence_level"] == "real_chrome_profile_verified"
    assert real["weight"] == 1


def test_browser_desktop_capability_canary_blocks_without_runtime_browser() -> None:
    report = compute_browser_desktop_capability_canary(
        computer_status=_healthy_computer(),
        computer_preview=_healthy_preview(),
        computer_execute=_healthy_execute(),
        computer_replay_case=_healthy_replay_case(),
        chrome_relay_handshake=_relay_handshake(),
        operation_status={"ok": True},
        cleanup_status={"ok": True},
        runtime_readiness=_runtime_readiness(),
        productization_readiness=_productization(),
        cold_start_readiness={
            "ready": True,
            "verdict": "pass",
            "score": 1.0,
            "probe": {"ok": True},
        },
        repair_recipe_quality_gate={
            "schema": "octopus.browser_desktop_repair_recipe_quality_gate.v1",
            "ready": True,
            "score": 1.0,
            "blockers": [],
        },
    )

    assert report["ready"] is False
    assert "in_app_browser_runtime" in report["blockers"]


def test_browser_desktop_capability_canary_surfaces_missing_real_chrome_as_warning() -> None:
    report = compute_browser_desktop_capability_canary(
        browser_health=_healthy_browser(),
        computer_status=_healthy_computer(),
        computer_preview=_healthy_preview(),
        computer_execute=_healthy_execute(),
        computer_replay_case=_healthy_replay_case(),
        chrome_relay_handshake=_relay_handshake(),
        operation_status={"ok": True},
        cleanup_status={"ok": True},
        runtime_readiness=_runtime_readiness(),
        productization_readiness=_productization(),
        cold_start_readiness={
            "ready": True,
            "verdict": "pass",
            "score": 1.0,
            "probe": {"ok": True},
        },
        repair_recipe_quality_gate={
            "schema": "octopus.browser_desktop_repair_recipe_quality_gate.v1",
            "ready": True,
            "score": 1.0,
            "blockers": [],
        },
    )

    real = next(
        row for row in report["capabilities"]
        if row["id"] == "real_chrome_profile_flow"
    )
    assert report["ready"] is True
    assert report["score"] < 1.0
    assert report["effective_score"] == 1.0
    assert report["real_chrome_profile_verified_count"] == 0
    assert real["passed"] is False
    assert real["severity"] == "warn"
    assert "real_chrome_profile_flow" not in report["blockers"]


def test_browser_desktop_capability_canary_blocks_without_desktop_execute_replay() -> None:
    report = compute_browser_desktop_capability_canary(
        browser_health=_healthy_browser(),
        computer_status=_healthy_computer(),
        computer_preview=_healthy_preview(),
        chrome_relay_handshake=_relay_handshake(),
        real_chrome_relay_probe=_real_relay(),
        operation_status={"ok": True},
        cleanup_status={"ok": True},
        runtime_readiness=_runtime_readiness(),
        productization_readiness=_productization(),
        cold_start_readiness={
            "ready": True,
            "verdict": "pass",
            "score": 1.0,
            "probe": {"ok": True},
        },
        repair_recipe_quality_gate={
            "schema": "octopus.browser_desktop_repair_recipe_quality_gate.v1",
            "ready": True,
            "score": 1.0,
            "blockers": [],
        },
    )

    assert report["ready"] is False
    assert "desktop_execute_replay_flow" in report["blockers"]
