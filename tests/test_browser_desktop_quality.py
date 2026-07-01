from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from runtime.memory.learning.review_queue import ReviewQueue
from runtime.safety.evolution.automation_radar import compute_automation_radar
from runtime.safety.evolution.browser_desktop_quality import (
    compute_browser_desktop_quality,
)
from runtime.sensing.gateway.evolution_router import create_evolution_router


def test_browser_desktop_quality_reports_all_local_checks() -> None:
    report = compute_browser_desktop_quality()

    assert report["schema"] == "octopus.browser_desktop_quality.v1"
    assert report["ready"] is True
    assert report["passed"] == report["total"]
    assert report["browser_relay_bridge"]["schema"] == "octopus.browser_relay_bridge.v1"
    assert report["browser_relay_bridge"]["base_url"].endswith("/api/browser/relay")
    assert report["computer_api_bridge"]["schema"] == "octopus.computer_api_bridge.v1"
    assert report["computer_api_bridge"]["base_url"].endswith("/api/computer")
    assert report["replay_trends"]["schema"] == "octopus.browser_desktop_replay_trends.v1"
    assert {row["id"] for row in report["checks"]} == {
        "browser_session_lifecycle",
        "browser_pixel_replay_gate",
        "thread_native_browser_activation",
        "thread_native_external_chrome_activation",
        "desktop_preview_execute_lease",
        "desktop_uia_grounding",
        "operator_visibility",
    }


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

    data = client.get("/api/evolution/browser-desktop-quality").json()

    assert data["ok"] is True
    assert data["schema"] == "octopus.browser_desktop_quality.v1"
    assert data["ready"] is True


def test_automation_radar_reports_browser_desktop_advantage() -> None:
    report = compute_automation_radar()

    assert report["schema"] == "octopus.automation_radar.v1"
    assert report["scope"] == "browser_desktop_visual_automation"
    assert report["overall"]["octopus"] == 96
    assert report["overall"]["codex"] == 93
    assert report["verdict"] == "leading"
    assert report["browser_desktop_quality"]["ready"] is True
    assert report["parity_certification"]["ready"] is True
    assert report["policy_rule_drafts"]["schema"] == (
        "octopus.automation_policy_rule_drafts.v1"
    )
    assert report["policy_rule_drafts"]["ready"] is True
    assert report["policy_rule_drafts"]["verified"] == report["policy_rule_drafts"]["total"]
    assert report["policy_rule_coverage"]["schema"] == (
        "octopus.automation_policy_rule_coverage.v1"
    )
    assert report["policy_rule_coverage"]["ready"] is True
    session_control = next(
        row
        for row in report["dimensions"]
        if row["id"] == "browser_session_control"
    )
    assert session_control["scores"]["octopus"] > session_control["scores"]["codex"]
    safety = next(
        row
        for row in report["dimensions"]
        if row["id"] == "automation_safety"
    )
    assert safety["scores"]["octopus"] > safety["scores"]["codex"]
    assert {row["id"] for row in report["octopus_strengths"]} >= {
        "browser_session_control",
        "desktop_preview_execute",
        "visual_replay_validation",
        "repair_recipe_learning",
        "thread_native_browser_mode",
        "external_chrome_mode",
        "automation_safety",
        "productized_api_bridge",
    }
    assert all(row["evidence_ready"] for row in report["octopus_strengths"])
    visual = next(
        row
        for row in report["dimensions"]
        if row["id"] == "visual_replay_validation"
    )
    assert visual["scores"]["octopus"] > visual["scores"]["codex"]
    assert visual["operator_drilldown"]["schema"] == (
        "octopus.automation_radar_drilldown.v1"
    )
    assert any(
        link["href"] == "/api/evolution/browser-desktop-repair-recipes"
        for link in visual["operator_drilldown"]["links"]
    )


def test_automation_radar_detects_missing_workspace(tmp_path: Path) -> None:
    report = compute_automation_radar(root=tmp_path)

    assert report["browser_desktop_quality"]["ready"] is False
    assert report["octopus_gaps"]
    assert any(not row["evidence_ready"] for row in report["octopus_gaps"])


def test_automation_radar_endpoint() -> None:
    app = FastAPI()
    app.include_router(create_evolution_router())
    client = TestClient(app)

    data = client.get("/api/evolution/automation-radar?target_score=95").json()

    assert data["ok"] is True
    assert data["schema"] == "octopus.automation_radar.v1"
    assert data["overall"]["octopus"] == 96
    assert data["ranking"][0]["competitor"] == "octopus"
