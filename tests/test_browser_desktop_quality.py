from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from runtime.memory.learning.review_queue import ReviewQueue
from runtime.safety.evolution.browser_desktop_quality import (
    compute_browser_desktop_quality,
)
from runtime.sensing.gateway.evolution_router import create_evolution_router


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
        "recent_activity": [{"event": "action_executed", "ok": True}],
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


def _healthy_relay() -> dict[str, object]:
    return {
        "schema": "octopus.browser_chrome_relay_handshake.v1",
        "ok": True,
        "command_id": "cmd-1",
        "command_result": {"ok": True, "id": "cmd-1"},
        "status": {"connected": True},
    }


def test_browser_desktop_quality_reports_all_local_checks() -> None:
    report = compute_browser_desktop_quality(use_runtime_evidence_cache=False)

    assert report["schema"] == "octopus.browser_desktop_quality.v1"
    assert report["ready"] is False
    assert report["static_ready"] is True
    assert report["runtime_contract_ready"] is True
    assert report["runtime_contract"]["ready"] is True
    assert report["runtime_contract"]["score"] == 1.0
    assert report["runtime_readiness"]["ready"] is False
    assert report["cold_start_ready"] is True
    assert report["cold_start_readiness"]["ready"] is True
    assert report["cold_start_readiness"]["probe"]["ok"] is True
    assert report["capability_canary_ready"] is False
    assert report["capability_canary"]["blockers"]
    assert report["passed"] == report["total"]
    assert 0.82 <= report["effective_score"] < 1.0
    assert report["replay_trends"]["schema"] == "octopus.browser_desktop_replay_trends.v1"
    assert report["repair_recipe_quality_gate"]["schema"] == (
        "octopus.browser_desktop_repair_recipe_quality_gate.v1"
    )
    assert report["repair_recipe_quality_gate"]["ready"] is True
    assert {row["id"] for row in report["checks"]} == {
        "browser_session_lifecycle",
        "browser_pixel_replay_gate",
        "desktop_preview_execute_lease",
        "desktop_uia_grounding",
        "operator_visibility",
        "deterministic_repair_recipe_gate",
    }


def test_browser_desktop_quality_ready_when_runtime_evidence_is_clean(
    tmp_path: Path,
) -> None:
    report = compute_browser_desktop_quality(
        browser_health=_healthy_browser(),
        computer_status=_healthy_computer(),
        computer_preview=_healthy_preview(),
        computer_execute=_healthy_execute(),
        computer_replay_case=_healthy_replay_case(),
        chrome_relay_handshake=_healthy_relay(),
        operation_status={"ok": True},
        cleanup_status={"ok": True},
        review_queue_path=tmp_path / "review_queue.json",
    )

    assert report["ready"] is True
    assert report["static_ready"] is True
    assert report["runtime_contract_ready"] is True
    assert report["runtime_readiness"]["ready"] is True
    assert report["cold_start_ready"] is True
    assert report["capability_canary_ready"] is True
    assert report["capability_canary"]["runtime_verified_count"] == 6
    assert report["effective_score"] == 1.0
    assert report["next_actions"] == []


def test_browser_desktop_quality_detects_missing_workspace(tmp_path: Path) -> None:
    report = compute_browser_desktop_quality(root=tmp_path)

    assert report["ready"] is False
    assert report["score"] == 0.0
    assert report["next_actions"]
    assert report["checks"][0]["missing_paths"]


def test_browser_desktop_quality_summarizes_replay_trends(tmp_path: Path) -> None:
    queue = ReviewQueue(tmp_path / "review_queue.json")
    pending = queue.upsert_item(
        source="browser_pixel_replay_gate",
        source_kind="browser_desktop_replay",
        candidate_kind="browser_pixel_replay_gate_case",
        priority="P1",
        target_bucket="browser_desktop_replay",
        title="Review browser pixel replay gate",
        text="Browser pixel replay gate needs review.",
    )["items"][0]
    promoted = queue.upsert_item(
        source="browser_session_replay",
        source_kind="browser_desktop_replay",
        candidate_kind="browser_session_replay_case",
        priority="P1",
        target_bucket="browser_desktop_replay",
        title="Review browser session replay",
        text="Browser session replay needs review.",
    )["items"][0]
    queue.decide(promoted["id"], action="promoted", reason="operator accepted")

    report = compute_browser_desktop_quality(
        review_queue_path=tmp_path / "review_queue.json",
    )
    trends = report["replay_trends"]

    assert trends["total"] == 2
    assert trends["pending_count"] == 1
    assert trends["promoted_count"] == 1
    assert trends["review_rate"] == 0.5
    assert trends["stale_source_artifact_count"] == 0
    assert trends["by_candidate_kind"] == {
        "browser_pixel_replay_gate_case": 1,
        "browser_session_replay_case": 1,
    }
    assert trends["repair_recipe_summary"]["schema"] == (
        "octopus.browser_desktop_repair_recipe_summary.v1"
    )
    assert trends["repair_recipe_summary"]["recipe_count"] == 1
    assert trends["repair_recipe_summary"]["top_recipes"][0]["candidate_kind"] == (
        "browser_pixel_replay_gate_case"
    )
    assert trends["latest"][0]["id"] == pending["id"]
    assert trends["next_actions"] == [
        "Review 1 pending browser/desktop replay case(s) before promotion.",
    ]
    assert report["repair_recipe_quality_gate"]["schema"] == (
        "octopus.browser_desktop_repair_recipe_quality_gate.v1"
    )
    assert report["repair_recipe_quality_gate"]["ready"] is True
    assert report["repair_recipe_quality_gate"]["recipe_count"] == 1


def test_browser_desktop_quality_surfaces_stale_source_artifacts(tmp_path: Path) -> None:
    queue_path = tmp_path / "review_queue.json"
    queue = ReviewQueue(queue_path)
    queue.upsert_item(
        source="browser_pixel_replay_gate",
        source_kind="browser_desktop_replay",
        candidate_kind="browser_pixel_replay_gate_case",
        priority="P1",
        target_bucket="browser_desktop_replay",
        title="Review stale browser pixel replay gate",
        text="Browser pixel replay gate needs review.",
        metadata={
            "artifact": {
                "local_path": str(tmp_path / "missing" / "screenshot.png"),
            },
        },
    )

    report = compute_browser_desktop_quality(review_queue_path=queue_path)
    trends = report["replay_trends"]

    assert trends["pending_count"] == 1
    assert trends["stale_source_artifact_count"] == 1
    assert trends["next_actions"] == [
        "Regenerate or reject 1 stale browser/desktop replay artifact(s).",
    ]


def test_browser_desktop_quality_endpoint() -> None:
    app = FastAPI()
    app.include_router(create_evolution_router())
    client = TestClient(app)

    data = client.get(
        "/api/evolution/browser-desktop-quality?use_runtime_evidence_cache=false",
    ).json()

    assert data["ok"] is True
    assert data["schema"] == "octopus.browser_desktop_quality.v1"
    assert data["ready"] is False
    assert data["static_ready"] is True
    assert data["runtime_readiness"]["ready"] is False
    assert data["repair_recipe_quality_gate"]["ready"] is True
