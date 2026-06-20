from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from runtime.memory.learning.review_queue import ReviewQueue
from runtime.sensing.gateway.evolution_router import create_evolution_router


def test_auto_verifier_metrics_endpoint(monkeypatch) -> None:
    def fake_summary(*, limit: int = 1000):
        return {
            "schema": "octopus.auto_verifier_metrics.v1",
            "total": limit,
            "families": [],
        }

    monkeypatch.setattr(
        "runtime.safety.evolution.auto_verifier_metrics.summarize_auto_verifier_metrics",
        fake_summary,
    )
    app = FastAPI()
    app.include_router(create_evolution_router())
    client = TestClient(app)

    response = client.get("/api/evolution/auto-verifier-metrics?limit=7")

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["total"] == 7


def test_auto_verifier_drift_queue_endpoint(monkeypatch) -> None:
    def fake_queue(*, limit: int = 1000):
        return {
            "schema": "octopus.verifier_drift_repair_queue.v1",
            "created": 1,
            "updated": 0,
            "alerts": [{"family": "ruff"}],
            "items": [{"candidate_kind": "verifier_drift:ruff"}],
        }

    monkeypatch.setattr(
        "runtime.safety.evolution.auto_verifier_metrics.queue_verifier_drift_backlog",
        fake_queue,
    )
    app = FastAPI()
    app.include_router(create_evolution_router())
    client = TestClient(app)

    response = client.post(
        "/api/evolution/auto-verifier-metrics/drift/queue",
        json={"limit": 7},
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["schema"] == "octopus.verifier_drift_repair_queue.v1"
    assert response.json()["created"] == 1


def test_agent_scorecard_endpoint() -> None:
    app = FastAPI()
    app.include_router(create_evolution_router())
    client = TestClient(app)

    response = client.get("/api/evolution/agent-scorecard?target_score=90")
    data = response.json()

    assert response.status_code == 200
    assert data["ok"] is True
    assert data["schema"] == "octopus.agent_competitor_scorecard.v1"
    assert data["target_score"] == 90
    assert data["overall"]["octopus"] == 93
    assert data["overall"]["codex"] == 93
    assert data["overall"]["cursor"] == 86
    assert data["verdict"] == "competitive"
    assert data["evidence_adjusted_overall"]["octopus"] == 93
    assert data["evidence_adjusted_verdict"] == "competitive"
    assert data["scorecard_policy"]["certification_floors_do_not_change_overall"] is True
    assert data["octopus_below_target"] == []
    assert data["ecosystem_readiness"]["score"] == 1.0
    assert data["parity_certification"]["ready"] is True
    assert data["parity_certification"]["passed"] == 14
    assert data["parity_certification"]["by_kind"]["operational_excellence"]["passed"] == 4
    assert data["parity_certification"]["by_kind"]["advantage"]["passed"] == 4


def test_agent_scorecard_gaps_can_queue_real_baseline_backlog(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("OCTOPUS_DATA_DIR", str(tmp_path / "data"))
    app = FastAPI()
    app.include_router(create_evolution_router())
    client = TestClient(app)

    response = client.post(
        "/api/evolution/agent-scorecard/gaps/queue",
        json={"target_score": 95, "limit": 3, "reason": "close real gaps"},
    )
    data = response.json()

    assert response.status_code == 200
    assert data["ok"] is True
    assert data["schema"] == "octopus.agent_scorecard_gap_queue.v1"
    assert data["created"] == 3
    assert data["scorecard"]["overall"]["octopus"] == 93
    assert data["scorecard"]["evidence_adjusted_overall"]["octopus"] == 95
    assert data["items"][0]["priority"] == "P1"
    assert data["items"][0]["target_bucket"] == "scorecard_gap_backlog"
    assert "real_baseline" in data["items"][0]["tags"]
    assert data["items"][0]["metadata"]["schema"] == "octopus.agent_scorecard_gap.v1"

    summary = ReviewQueue(tmp_path / "data" / "review_queue.json").summary()
    assert summary["pending_count"] == 3
    assert summary["by_target_bucket"]["scorecard_gap_backlog"] == 3


def test_repair_route_promotion_candidates_can_queue_from_router(
    monkeypatch,
) -> None:
    def fake_queue(*, limit: int = 1000):
        return {
            "schema": "octopus.repair_route_promotion_queue.v1",
            "created": 1,
            "updated": 0,
            "candidates": [{"route": "test_driven_repair", "limit": limit}],
            "items": [{"candidate_kind": "repair_route_promotion:test_driven_repair"}],
        }

    monkeypatch.setattr(
        "runtime.safety.evolution.repair_route_quality.queue_repair_route_promotion_candidates",
        fake_queue,
    )
    app = FastAPI()
    app.include_router(create_evolution_router())
    client = TestClient(app)

    response = client.post(
        "/api/evolution/repair-route-quality/promotions/queue",
        json={"limit": 50},
    )
    data = response.json()

    assert response.status_code == 200
    assert data["ok"] is True
    assert data["schema"] == "octopus.repair_route_promotion_queue.v1"
    assert data["created"] == 1
    assert data["candidates"][0]["route"] == "test_driven_repair"
    assert data["candidates"][0]["limit"] == 50


def test_agent_scorecard_gap_queue_can_target_single_dimension(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("OCTOPUS_DATA_DIR", str(tmp_path / "data"))
    app = FastAPI()
    app.include_router(create_evolution_router())
    client = TestClient(app)

    response = client.post(
        "/api/evolution/agent-scorecard/gaps/queue",
        json={
            "target_score": 95,
            "limit": 10,
            "dimension_id": "ecosystem_maturity",
            "reason": "operator drilldown remediation",
        },
    )
    data = response.json()

    assert response.status_code == 200
    assert data["ok"] is True
    assert data["created"] == 1
    assert data["items"][0]["candidate_kind"] == "scorecard_gap:ecosystem_maturity"
    assert data["items"][0]["metadata"]["dimension_id"] == "ecosystem_maturity"
    assert data["items"][0]["metadata"]["remediation"]["schema"] == (
        "octopus.scorecard_gap_remediation.v1"
    )
    assert data["items"][0]["metadata"]["remediation"]["primary_action"] == (
        "Publish plugin compatibility examples for common MCP and app surfaces."
    )

    summary = ReviewQueue(tmp_path / "data" / "review_queue.json").summary()
    assert summary["pending_count"] == 1
    assert summary["by_target_bucket"]["scorecard_gap_backlog"] == 1


def test_browser_desktop_quality_endpoint() -> None:
    app = FastAPI()
    app.include_router(create_evolution_router())
    client = TestClient(app)

    response = client.get("/api/evolution/browser-desktop-quality")
    data = response.json()

    assert response.status_code == 200
    assert data["ok"] is True
    assert data["schema"] == "octopus.browser_desktop_quality.v1"
    assert data["ready"] is True
    assert data["score"] == 1.0


def test_browser_desktop_repair_recipe_queue_endpoint(monkeypatch) -> None:
    def fake_queue(*, limit: int = 1000, min_occurrences: int = 1):
        return {
            "schema": "octopus.browser_desktop_repair_recipe_queue.v1",
            "created": 1,
            "updated": 0,
            "recipes": [
                {
                    "candidate_kind": "browser_pixel_replay_gate_case",
                    "limit": limit,
                    "min_occurrences": min_occurrences,
                }
            ],
            "items": [
                {
                    "candidate_kind": "browser_desktop_repair_recipe:abcdef",
                    "target_bucket": "browser_desktop_repair_recipe",
                }
            ],
        }

    monkeypatch.setattr(
        "runtime.safety.evolution.browser_desktop_repair_recipes.queue_browser_desktop_repair_recipes",
        fake_queue,
    )
    app = FastAPI()
    app.include_router(create_evolution_router())
    client = TestClient(app)

    response = client.post(
        "/api/evolution/browser-desktop-repair-recipes/queue",
        json={"limit": 50, "min_occurrences": 2},
    )
    data = response.json()

    assert response.status_code == 200
    assert data["ok"] is True
    assert data["schema"] == "octopus.browser_desktop_repair_recipe_queue.v1"
    assert data["created"] == 1
    assert data["recipes"][0]["limit"] == 50
    assert data["recipes"][0]["min_occurrences"] == 2


def test_browser_desktop_stale_artifact_rejection_endpoint(monkeypatch) -> None:
    def fake_reject(*, limit: int = 1000):
        return {
            "schema": "octopus.browser_desktop_stale_replay_artifact_rejection.v1",
            "inspected": limit,
            "rejected_count": 2,
            "archived_recipe_count": 1,
            "skipped_count": 1,
            "rejected": [{"id": "rq_stale"}],
            "archived_recipes": [{"id": "rq_recipe"}],
        }

    monkeypatch.setattr(
        "runtime.safety.evolution.browser_desktop_repair_recipes.reject_stale_browser_desktop_replay_artifacts",
        fake_reject,
    )
    app = FastAPI()
    app.include_router(create_evolution_router())
    client = TestClient(app)

    response = client.post(
        "/api/evolution/browser-desktop-repair-recipes/stale-artifacts/reject",
        json={"limit": 3},
    )
    data = response.json()

    assert response.status_code == 200
    assert data["ok"] is True
    assert data["schema"] == "octopus.browser_desktop_stale_replay_artifact_rejection.v1"
    assert data["inspected"] == 3
    assert data["rejected_count"] == 2
    assert data["archived_recipe_count"] == 1


def test_browser_desktop_repair_recipe_verifications_endpoint(monkeypatch) -> None:
    def fake_verifications(*, limit: int = 1000):
        return {
            "schema": "octopus.browser_desktop_repair_recipe_verifications.v1",
            "total": limit,
            "verified_count": 0,
            "blocked_count": 1,
            "ready": False,
            "verifications": [{"status": "needs_rerun_evidence"}],
            "next_actions": ["Attach rerun evidence."],
        }

    monkeypatch.setattr(
        "runtime.safety.evolution.browser_desktop_repair_recipes.compute_browser_desktop_repair_recipe_verifications",
        fake_verifications,
    )
    app = FastAPI()
    app.include_router(create_evolution_router())
    client = TestClient(app)

    response = client.get(
        "/api/evolution/browser-desktop-repair-recipes/verifications?limit=7",
    )
    data = response.json()

    assert response.status_code == 200
    assert data["ok"] is True
    assert data["schema"] == "octopus.browser_desktop_repair_recipe_verifications.v1"
    assert data["total"] == 7
    assert data["ready"] is False


def test_browser_desktop_repair_recipe_evidence_endpoint(monkeypatch) -> None:
    def fake_attach(
        *,
        item_id: str,
        passed: bool,
        provided: list[str],
        artifacts: list[dict],
        notes: str,
        actor: str,
    ):
        return {
            "schema": "octopus.browser_desktop_repair_recipe_evidence_attachment.v1",
            "item": {"id": item_id},
            "evidence": {
                "passed": passed,
                "provided": provided,
                "artifacts": artifacts,
                "notes": notes,
                "actor": actor,
            },
            "verification": {"status": "verified"},
        }

    monkeypatch.setattr(
        "runtime.safety.evolution.browser_desktop_repair_recipes.attach_browser_desktop_repair_recipe_evidence",
        fake_attach,
    )
    app = FastAPI()
    app.include_router(create_evolution_router())
    client = TestClient(app)

    response = client.post(
        "/api/evolution/browser-desktop-repair-recipes/verifications/evidence",
        json={
            "item_id": "rq_recipe",
            "passed": True,
            "provided": ["fresh_screenshot"],
            "artifacts": [{"type": "screenshot", "ok": True}],
            "notes": "rerun passed",
            "actor": "operator_test",
        },
    )
    data = response.json()

    assert response.status_code == 200
    assert data["ok"] is True
    assert data["schema"] == (
        "octopus.browser_desktop_repair_recipe_evidence_attachment.v1"
    )
    assert data["item"]["id"] == "rq_recipe"
    assert data["evidence"]["provided"] == ["fresh_screenshot"]
    assert data["verification"]["status"] == "verified"


def test_browser_desktop_repair_recipe_rerun_endpoint(monkeypatch) -> None:
    def fake_rerun(
        *,
        item_id: str,
        api_base_url: str,
        promote_source_cases: bool,
        actor: str,
    ):
        return {
            "schema": "octopus.browser_desktop_repair_recipe_rerun.v1",
            "item_id": item_id,
            "passed": True,
            "provided": ["browser_session_replay_case", "session_health"],
            "missing": [],
            "promoted_source_count": 1 if promote_source_cases else 0,
            "artifacts": [{"url": api_base_url, "ok": True}],
            "attachment": {"evidence": {"actor": actor}},
        }

    monkeypatch.setattr(
        "runtime.safety.evolution.browser_desktop_repair_recipes.rerun_browser_desktop_repair_recipe_evidence",
        fake_rerun,
    )
    app = FastAPI()
    app.include_router(create_evolution_router())
    client = TestClient(app)

    response = client.post(
        "/api/evolution/browser-desktop-repair-recipes/verifications/rerun",
        json={
            "item_id": "rq_recipe",
            "api_base_url": "http://127.0.0.1:8000",
            "promote_source_cases": True,
            "actor": "operator_test",
        },
    )
    data = response.json()

    assert response.status_code == 200
    assert data["ok"] is True
    assert data["schema"] == "octopus.browser_desktop_repair_recipe_rerun.v1"
    assert data["passed"] is True
    assert data["promoted_source_count"] == 1
    assert data["attachment"]["evidence"]["actor"] == "operator_test"


def test_browser_desktop_repair_recipe_rerun_batch_endpoint(monkeypatch) -> None:
    def fake_batch(
        *,
        api_base_url: str,
        promote_source_cases: bool,
        actor: str,
        limit: int,
    ):
        return {
            "schema": "octopus.browser_desktop_repair_recipe_rerun_batch.v1",
            "attempted": limit,
            "passed": 1,
            "failed": limit - 1,
            "results": [
                {
                    "passed": True,
                    "promoted_source_cases": promote_source_cases,
                    "api_base_url": api_base_url,
                    "actor": actor,
                }
            ],
        }

    monkeypatch.setattr(
        "runtime.safety.evolution.browser_desktop_repair_recipes.rerun_browser_desktop_repair_recipe_batch",
        fake_batch,
    )
    app = FastAPI()
    app.include_router(create_evolution_router())
    client = TestClient(app)

    response = client.post(
        "/api/evolution/browser-desktop-repair-recipes/verifications/rerun-batch",
        json={
            "api_base_url": "http://127.0.0.1:8000",
            "promote_source_cases": True,
            "actor": "operator_test",
            "limit": 3,
        },
    )
    data = response.json()

    assert response.status_code == 200
    assert data["ok"] is True
    assert data["schema"] == "octopus.browser_desktop_repair_recipe_rerun_batch.v1"
    assert data["attempted"] == 3
    assert data["passed"] == 1
    assert data["failed"] == 2
