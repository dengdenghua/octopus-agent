from __future__ import annotations

from pathlib import Path

from runtime.memory.learning.review_queue import ReviewQueue
from runtime.safety.evolution.browser_desktop_runtime_readiness import (
    compute_browser_desktop_runtime_readiness,
)


def _healthy_browser() -> dict[str, object]:
    return {
        "schema": "octopus.browser_session_health.v1",
        "exists": True,
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
        "recent_activity": [
            {"event": "action_executed", "ok": True},
        ],
    }


def _healthy_preview() -> dict[str, object]:
    return {
        "ok": True,
        "token": "preview-token",
        "action": {"action": "wait", "ms": 10},
        "risk": {"level": "low"},
        "lease": {"held": False, "ttl_seconds": 0},
        "expires_in_seconds": 90,
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


def test_runtime_readiness_passes_with_clean_runtime_evidence(tmp_path: Path) -> None:
    report = compute_browser_desktop_runtime_readiness(
        browser_health=_healthy_browser(),
        computer_status=_healthy_computer(),
        computer_preview=_healthy_preview(),
        computer_execute=_healthy_execute(),
        computer_replay_case=_healthy_replay_case(),
        review_queue_path=tmp_path / "review_queue.json",
    )

    assert report["schema"] == "octopus.browser_desktop_runtime_readiness.v1"
    assert report["ready"] is True
    assert report["verdict"] == "pass"
    assert report["score"] == 1.0
    assert report["blocker_count"] == 0
    assert report["warn_count"] == 0
    assert report["next_actions"] == [
        "Browser/desktop runtime automation is replay-ready.",
    ]


def test_runtime_readiness_blocks_stale_replay_artifact(tmp_path: Path) -> None:
    queue_path = tmp_path / "review_queue.json"
    queue = ReviewQueue(queue_path)
    queue.upsert_item(
        source="browser_pixel_replay_gate",
        source_kind="browser_desktop_replay",
        candidate_kind="browser_pixel_replay_gate_case",
        priority="P0",
        target_bucket="browser_desktop_replay",
        title="Review stale browser pixel replay gate",
        text="Browser pixel replay gate needs review.",
        metadata={"artifact": {"local_path": str(tmp_path / "missing.png")}},
    )

    report = compute_browser_desktop_runtime_readiness(
        browser_health=_healthy_browser(),
        computer_status=_healthy_computer(),
        computer_preview=_healthy_preview(),
        computer_execute=_healthy_execute(),
        computer_replay_case=_healthy_replay_case(),
        review_queue_path=queue_path,
    )

    assert report["ready"] is False
    assert report["verdict"] == "blocked"
    assert report["blocker_count"] == 1
    assert report["replay_queue"]["stale_source_artifact_count"] == 1
    assert any(
        check["id"] == "replay_queue_clean" and check["status"] == "fail"
        for check in report["checks"]
    )


def test_runtime_readiness_warns_when_desktop_lease_is_held(tmp_path: Path) -> None:
    computer = _healthy_computer()
    computer["lease"] = {
        "held": True,
        "owner_id": "other",
        "ttl_seconds": 30,
    }

    report = compute_browser_desktop_runtime_readiness(
        browser_health=_healthy_browser(),
        computer_status=computer,
        computer_preview=_healthy_preview(),
        computer_execute=_healthy_execute(),
        computer_replay_case=_healthy_replay_case(),
        review_queue_path=tmp_path / "review_queue.json",
    )

    assert report["ready"] is False
    assert report["verdict"] == "review"
    assert report["blocker_count"] == 0
    assert report["warn_count"] == 1
    assert any(
        check["id"] == "computer_status_observed" and check["status"] == "warn"
        for check in report["checks"]
    )


def test_runtime_readiness_warns_when_runtime_snapshots_are_missing(
    tmp_path: Path,
) -> None:
    report = compute_browser_desktop_runtime_readiness(
        review_queue_path=tmp_path / "review_queue.json",
    )

    assert report["ready"] is False
    assert report["score"] < 1.0
    assert report["warn_count"] >= 1
    assert "Capture /api/browser/session/health" in report["next_actions"][0]


def test_runtime_readiness_blocks_failed_probe_operations(tmp_path: Path) -> None:
    report = compute_browser_desktop_runtime_readiness(
        browser_health=_healthy_browser(),
        computer_status=_healthy_computer(),
        computer_preview=_healthy_preview(),
        computer_execute=_healthy_execute(),
        computer_replay_case=_healthy_replay_case(),
        operation_status={
            "ok": False,
            "total": 3,
            "failed_count": 1,
            "failed_operations": [
                {
                    "method": "POST",
                    "path": "/api/browser/navigate",
                    "status_code": 0,
                    "error": "ReadError: connection reset",
                },
            ],
        },
        review_queue_path=tmp_path / "review_queue.json",
    )

    assert report["ready"] is False
    assert report["verdict"] == "blocked"
    assert any(
        check["id"] == "runtime_probe_operations" and check["status"] == "fail"
        for check in report["checks"]
    )


def test_runtime_readiness_warns_when_preview_is_missing(tmp_path: Path) -> None:
    report = compute_browser_desktop_runtime_readiness(
        browser_health=_healthy_browser(),
        computer_status=_healthy_computer(),
        review_queue_path=tmp_path / "review_queue.json",
    )

    assert report["ready"] is False
    assert report["verdict"] == "review"
    assert any(
        check["id"] == "computer_preview_observed" and check["status"] == "unknown"
        for check in report["checks"]
    )


def test_runtime_readiness_blocks_when_execute_replay_is_missing(tmp_path: Path) -> None:
    report = compute_browser_desktop_runtime_readiness(
        browser_health=_healthy_browser(),
        computer_status=_healthy_computer(),
        computer_preview=_healthy_preview(),
        review_queue_path=tmp_path / "review_queue.json",
    )

    assert report["ready"] is False
    assert any(
        check["id"] == "computer_execute_observed"
        and check["status"] == "unknown"
        for check in report["checks"]
    )
    assert any(
        check["id"] == "computer_replay_case_observed"
        and check["status"] == "unknown"
        for check in report["checks"]
    )
