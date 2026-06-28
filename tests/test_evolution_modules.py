"""Unit tests for runtime.safety.evolution modules."""
from __future__ import annotations

import json
from unittest.mock import patch

from runtime.platform.config.schema import EvolveConfig, PlannerConfig, _pick_cheaper
from runtime.safety.evolution.canary import (
    CanaryConfig,
    CanaryManager,
    CanaryPhase,
)
from runtime.safety.evolution.drift_monitor import (
    DriftEvent,
    DriftMonitor,
)
from runtime.safety.evolution.federation import (
    FederationConfig,
    FederationHub,
    SharedProposal,
)
from runtime.safety.evolution.fitness import (
    FitnessReport,
    L1Fitness,
    compute_governance_fitness,
    compute_l1,
)
from runtime.safety.evolution.proposal_ledger import (
    ProposalLedger,
    ProposalStatus,
)
from runtime.safety.evolution.strategy import (
    StrategyEngine,
)
from runtime.safety.recovery.gepa_runs import (
    GepaRunRecord,
    enrich_run_records,
    record_from_result,
)

# ═══════════════════════════════════════════════════════════
# EvolveConfig
# ═══════════════════════════════════════════════════════════


class TestPickCheaper:
    def test_known_mapping(self):
        assert _pick_cheaper("mimo-v2.5-pro") == "mimo-v2-flash"
        assert _pick_cheaper("claude-sonnet-4-6") == "claude-haiku-4-5-20251001"
        assert _pick_cheaper("gpt-4o") == "gpt-4o-mini"

    def test_unknown_model_returns_same(self):
        assert _pick_cheaper("unknown-model") == "unknown-model"

    def test_already_cheap_returns_same(self):
        assert _pick_cheaper("gpt-4o-mini") == "gpt-4o-mini"


class TestEvolveConfig:
    def test_default_is_inherit(self):
        cfg = EvolveConfig()
        assert cfg.strategy == "inherit"

    def test_inherit_resolves_to_planner(self):
        cfg = EvolveConfig()
        planner = PlannerConfig(type="llm", model="mimo-v2.5-pro", base_url="https://api.example.com/v1")
        model, url = cfg.resolve(planner)
        assert model == "mimo-v2.5-pro"
        assert url == "https://api.example.com/v1"

    def test_cheaper_same_provider(self):
        cfg = EvolveConfig(strategy="cheaper_same_provider")
        planner = PlannerConfig(type="llm", model="mimo-v2.5-pro", base_url="https://api.example.com/v1")
        model, url = cfg.resolve(planner)
        assert model == "mimo-v2-flash"
        assert url == "https://api.example.com/v1"

    def test_explicit_overrides(self):
        cfg = EvolveConfig(
            strategy="explicit",
            model="mimo-v2-flash",
            base_url="https://api.xiaomimimo.com/v1",
            api_key_env="MIMO_API_KEY",
        )
        planner = PlannerConfig(type="llm", model="gpt-4o")
        model, url = cfg.resolve(planner)
        assert model == "mimo-v2-flash"
        assert url == "https://api.xiaomimimo.com/v1"

    def test_explicit_falls_back_to_planner_when_unset(self):
        cfg = EvolveConfig(strategy="explicit")
        planner = PlannerConfig(type="llm", model="gpt-4o", base_url="https://api.openai.com/v1")
        model, url = cfg.resolve(planner)
        assert model == "gpt-4o"
        assert url == "https://api.openai.com/v1"


# ═══════════════════════════════════════════════════════════
# Fitness
# ═══════════════════════════════════════════════════════════


class TestComputeL1:
    def test_no_scores_returns_defaults(self):
        with patch("runtime.safety.evolution.fitness.read_recent_scores", return_value=[]):
            l1 = compute_l1("nonexistent_agent")
            assert l1.score == 0.5
            assert l1.trend == "stable"

    def test_all_success(self):
        from runtime.memory.learning.turn_scoring import TurnScore
        scores = [TurnScore(ts="t", agent_id="a", score=1.0, reason="success", soul_hash="abc", rounds=3)]
        scores = scores * 10
        with (
            patch("runtime.safety.evolution.fitness.read_recent_scores", return_value=scores),
            patch("runtime.safety.evolution.fitness.analyze_soul_impact", return_value={}),
        ):
            l1 = compute_l1("test_agent", window=10)
            assert l1.score == 1.0
            assert l1.success_rate == 1.0


class TestGovernanceFitness:
    def test_empty_audit_has_no_penalty(self, tmp_path):
        audit_path = tmp_path / "promotion_audit.json"
        audit_path.write_text(
            json.dumps({"schema": "octopus.promotion_audit.v1", "records": []}),
            encoding="utf-8",
        )

        risk = compute_governance_fitness(audit_path=audit_path)

        assert risk.score == 1.0
        assert risk.penalty == 0.0
        assert risk.reasons == []

    def test_malformed_records_field_has_no_penalty(self, tmp_path):
        for payload in ({}, {"records": None}):
            audit_path = tmp_path / f"promotion_audit_{len(payload)}.json"
            audit_path.write_text(json.dumps(payload), encoding="utf-8")

            risk = compute_governance_fitness(audit_path=audit_path)

            assert risk.score == 1.0
            assert risk.penalty == 0.0
            assert risk.audit_total == 0

    def test_blocked_replay_override_penalizes_fitness(self, tmp_path):
        audit_path = tmp_path / "promotion_audit.json"
        audit_path.write_text(
            json.dumps({
                "schema": "octopus.promotion_audit.v1",
                "records": [
                    {
                        "id": "p1",
                        "review_queue_item_id": "rq-1",
                        "agent_id": "test_agent",
                        "target": "experience",
                        "status": "applied",
                        "applied_at": "2026-06-19T00:00:00",
                        "decision_context": {
                            "replay_gate": {"passed": False},
                            "override_replay_gate": True,
                        },
                    }
                ],
            }),
            encoding="utf-8",
        )

        risk = compute_governance_fitness(audit_path=audit_path)

        assert risk.gate_blocked_override_count == 1
        assert risk.gate_failed_count == 1
        assert risk.override_count == 1
        assert risk.penalty == 0.25
        assert "1 blocked replay override(s)" in risk.reasons

    def test_governance_audit_event_round_trips(self, tmp_path):
        from runtime.memory.learning.experience_ledger import ExperienceLedger
        from runtime.memory.learning.promotion_applier import PromotionApplier
        from runtime.memory.learning.review_queue import ReviewQueue
        from runtime.safety.evolution.governance_audit import (
            append_governance_audit_event,
            verify_governance_audit_chain,
        )
        from runtime.safety.evolution.proposal_ledger import ProposalLedger

        audit_path = tmp_path / "promotion_audit.json"

        record = append_governance_audit_event(
            event_type="topology_policy_block",
            target="topology_policy",
            status="blocked",
            artifact={"topology_id": "team-a"},
            decision_context={"turn_id": "turn-1"},
            audit_path=audit_path,
        )
        audit = PromotionApplier(
            review_queue=ReviewQueue(tmp_path / "review_queue.json"),
            experience_ledger=ExperienceLedger(tmp_path / "experience.json"),
            proposal_ledger=ProposalLedger(tmp_path / "proposals.jsonl"),
            audit_path=audit_path,
        ).audit()

        assert record["event_type"] == "topology_policy_block"
        assert audit["total"] == 1
        assert audit["records"][0]["event_type"] == "topology_policy_block"
        assert audit["records"][0]["artifact"]["topology_id"] == "team-a"
        integrity = verify_governance_audit_chain(audit_path=audit_path)
        assert integrity["ok"] is True
        assert integrity["entries_checked"] == 1

    def test_governance_audit_chain_detects_tamper(self, tmp_path):
        from runtime.safety.evolution.governance_audit import (
            append_governance_audit_event,
            verify_governance_audit_chain,
        )

        audit_path = tmp_path / "promotion_audit.json"
        chain_path = tmp_path / "promotion_audit_chain.jsonl"

        append_governance_audit_event(
            event_type="topology_policy_block",
            target="topology_policy",
            status="blocked",
            artifact={"topology_id": "team-a"},
            decision_context={"turn_id": "turn-1"},
            audit_path=audit_path,
        )
        append_governance_audit_event(
            event_type="topology_policy_block",
            target="topology_policy",
            status="blocked",
            artifact={"topology_id": "team-b"},
            decision_context={"turn_id": "turn-2"},
            audit_path=audit_path,
        )

        clean = verify_governance_audit_chain(audit_path=audit_path)
        assert clean["ok"] is True
        assert clean["entries_checked"] == 2

        lines = chain_path.read_text(encoding="utf-8").splitlines()
        first = json.loads(lines[0])
        first["payload"]["status"] = "applied"
        lines[0] = json.dumps(first)
        chain_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        tampered = verify_governance_audit_chain(audit_path=audit_path)
        assert tampered["ok"] is False
        assert tampered["broken_at"] == 0

    def test_governance_audit_chain_detects_json_mismatch(self, tmp_path):
        from runtime.safety.evolution.governance_audit import (
            append_governance_audit_event,
            verify_governance_audit_chain,
        )

        audit_path = tmp_path / "promotion_audit.json"
        append_governance_audit_event(
            event_type="topology_policy_block",
            target="topology_policy",
            status="blocked",
            artifact={"topology_id": "team-a"},
            decision_context={"turn_id": "turn-1"},
            audit_path=audit_path,
        )
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        audit["records"][0]["status"] = "applied"
        audit_path.write_text(json.dumps(audit), encoding="utf-8")

        integrity = verify_governance_audit_chain(audit_path=audit_path)

        assert integrity["ok"] is False
        assert "payload mismatch" in integrity["error"]

    def test_governance_audit_export_bundle_contains_chain_and_hashes(self, tmp_path):
        from runtime.safety.evolution.governance_audit import (
            append_governance_audit_event,
            export_governance_audit_bundle,
        )

        audit_path = tmp_path / "promotion_audit.json"
        append_governance_audit_event(
            event_type="topology_policy_block",
            target="topology_policy",
            status="blocked",
            artifact={"topology_id": "team-a"},
            decision_context={"turn_id": "turn-1"},
            audit_path=audit_path,
        )

        bundle = export_governance_audit_bundle(audit_path=audit_path)

        assert bundle["schema"] == "octopus.governance_audit_export.v1"
        assert bundle["integrity"]["ok"] is True
        assert bundle["audit"]["records"][0]["event_type"] == "topology_policy_block"
        assert bundle["chain"]["line_count"] == 1
        assert len(bundle["audit_sha256"]) == 64
        assert len(bundle["chain_sha256"]) == 64

    def test_governance_penalty_is_scoped_to_agent(self, tmp_path):
        audit_path = tmp_path / "promotion_audit.json"
        audit_path.write_text(
            json.dumps({
                "schema": "octopus.promotion_audit.v1",
                "records": [
                    {
                        "id": "p1",
                        "review_queue_item_id": "rq-1",
                        "agent_id": "other_agent",
                        "target": "experience",
                        "status": "applied",
                        "applied_at": "2026-06-19T00:00:00",
                        "decision_context": {
                            "replay_gate": {"passed": False},
                            "override_replay_gate": True,
                        },
                    }
                ],
            }),
            encoding="utf-8",
        )

        risk = compute_governance_fitness(
            agent_id="test_agent",
            audit_path=audit_path,
        )

        assert risk.audit_total == 0
        assert risk.penalty == 0.0

    def test_governance_window_zero_uses_all_records(self, tmp_path):
        audit_path = tmp_path / "promotion_audit.json"
        audit_path.write_text(
            json.dumps({
                "schema": "octopus.promotion_audit.v1",
                "records": [
                    {
                        "id": "p1",
                        "review_queue_item_id": "rq-1",
                        "agent_id": "test_agent",
                        "target": "experience",
                        "status": "failed",
                        "applied_at": "2026-06-19T00:00:00",
                        "decision_context": {
                            "replay_gate": {"passed": True},
                            "override_replay_gate": False,
                        },
                    },
                    {
                        "id": "p2",
                        "review_queue_item_id": "rq-2",
                        "agent_id": "test_agent",
                        "target": "experience",
                        "status": "applied",
                        "applied_at": "2026-06-19T00:00:01",
                        "decision_context": {
                            "replay_gate": {"passed": False},
                            "override_replay_gate": True,
                        },
                    },
                ],
            }),
            encoding="utf-8",
        )

        risk = compute_governance_fitness(
            agent_id="test_agent",
            audit_path=audit_path,
            window=0,
        )

        assert risk.recent_total == 2
        assert risk.failed_apply_count == 1
        assert risk.gate_blocked_override_count == 1

    def test_governance_mixed_window_penalty_is_stable(self, tmp_path):
        audit_path = tmp_path / "promotion_audit.json"
        records = [
            {
                "id": f"p{i}",
                "review_queue_item_id": f"rq-{i}",
                "agent_id": "test_agent",
                "target": "experience",
                "status": "applied",
                "applied_at": f"2026-06-19T00:00:{i:02d}",
                "decision_context": {
                    "replay_gate": {"passed": i >= 3},
                    "override_replay_gate": i < 3,
                },
            }
            for i in range(20)
        ]
        audit_path.write_text(
            json.dumps({"schema": "octopus.promotion_audit.v1", "records": records}),
            encoding="utf-8",
        )

        risk = compute_governance_fitness(
            agent_id="test_agent",
            audit_path=audit_path,
            window=20,
        )

        assert risk.recent_total == 20
        assert risk.gate_blocked_override_count == 3
        assert risk.override_count == 3
        assert risk.penalty == 0.046
        assert risk.score == 0.954


class TestFitnessReport:
    def test_verdict_healthy(self):
        report = FitnessReport(
            agent_id="test", ts="t", l1=L1Fitness(0.9, "stable", 0.9, 3.0, {}),
            l2=None, combined=0.9, verdict="healthy",
        )
        assert report.verdict == "healthy"

    def test_verdict_critical(self):
        report = FitnessReport(
            agent_id="test", ts="t", l1=L1Fitness(0.1, "regressing", 0.1, 20.0, {}),
            l2=None, combined=0.1, verdict="critical",
        )
        assert report.verdict == "critical"


# ═══════════════════════════════════════════════════════════
# DriftMonitor
# ═══════════════════════════════════════════════════════════


class TestDriftMonitor:
    def test_no_drift_on_first_check(self):
        monitor = DriftMonitor("test_agent")
        with (
            patch.object(monitor, "_check_soul_drift", return_value=None),
            patch.object(monitor, "_check_genome_drift", return_value=None),
            patch.object(monitor, "_check_score_drift", return_value=None),
        ):
            report = monitor.check()
            assert report.has_drift is False
            assert report.max_severity == "none"

    def test_soul_change_detected(self):
        monitor = DriftMonitor("test_agent")
        monitor._last_soul_hash = "old_hash"
        with patch.object(monitor, "_check_soul_drift") as mock_soul:
            mock_soul.return_value = DriftEvent(
                kind="soul_change", severity="info",
                detail="changed", ts="t",
            )
            with (
                patch.object(monitor, "_check_genome_drift", return_value=None),
                patch.object(monitor, "_check_score_drift", return_value=None),
            ):
                report = monitor.check()
                assert report.has_drift is True
                assert report.max_severity == "info"


# ═══════════════════════════════════════════════════════════
# CodexGap
# ═══════════════════════════════════════════════════════════


class TestCodexGap:
    def test_report_scores_missing_evidence(self, tmp_path):
        from runtime.safety.evolution.codex_gap import compute_codex_gap_report

        (tmp_path / "runtime/core/cerebrum").mkdir(parents=True)
        (tmp_path / "runtime/core/cerebrum/react_loop.py").write_text(
            "# loop\n",
            encoding="utf-8",
        )

        report = compute_codex_gap_report(root=tmp_path)
        code_loop = next(
            item for item in report["capabilities"]
            if item["id"] == "code_execution_loop"
        )

        assert report["schema"] == "octopus.codex_gap_report.v1"
        assert report["combined_score"] < 1.0
        assert code_loop["status"] == "gap"
        assert "runtime/execution/tool_engine/executor.py" in (
            code_loop["evidence"]["implementation"]["missing"]
        )
        assert report["top_gaps"]

    def test_router_exposes_report(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from runtime.sensing.gateway.evolution_router import create_evolution_router

        app = FastAPI()
        app.include_router(create_evolution_router())
        data = TestClient(app).get("/api/evolution/codex-gap").json()

        assert data["ok"] is True
        assert data["schema"] == "octopus.codex_gap_report.v1"
        assert data["parity_score"] > 0
        assert data["advantage_score"] > 0
        assert {item["area"] for item in data["capabilities"]} == {
            "codex_parity",
            "octopus_advantage",
        }
        assert isinstance(data["next_focus"], list)


# ═══════════════════════════════════════════════════════════
# AgentCompetitorScorecard
# ═══════════════════════════════════════════════════════════


class TestAgentCompetitorScorecard:
    def test_ecosystem_readiness_requires_public_operator_guide(self, tmp_path):
        from runtime.safety.evolution.ecosystem_readiness import (
            compute_ecosystem_readiness,
        )

        missing = compute_ecosystem_readiness(root=tmp_path)

        assert missing["score"] == 0.0
        assert missing["missing_count"] == 5

        guide = tmp_path / "docs/guide/operator-readiness.md"
        guide.parent.mkdir(parents=True)
        guide.write_text(
            "\n".join([
                "# Operator Readiness",
                "Code mode inspect edit verify.",
                "Permission approval sandbox override.",
                "Replay gate promotion evidence audit.",
                "Plugin smoke permission review hook.",
            ]),
            encoding="utf-8",
        )

        partial = compute_ecosystem_readiness(root=tmp_path)

        assert partial["passed"] == 4
        assert partial["missing_count"] == 1

        migration = tmp_path / "docs/guide/plugin-author-migration.md"
        migration.write_text(
            "\n".join([
                "# Plugin Author Migration",
                "Compatibility checks guide plugin migration.",
                "Permission review is required before release.",
                "Release checklist covers hooks and tests.",
            ]),
            encoding="utf-8",
        )

        ready = compute_ecosystem_readiness(root=tmp_path)

        assert ready["score"] == 1.0
        assert ready["passed"] == 5
        assert ready["next_actions"] == []

    def test_scorecard_weights_and_gaps_are_stable(self):
        from runtime.safety.evolution.agent_competitor_scorecard import (
            DIMENSIONS,
            compute_agent_competitor_scorecard,
        )

        report = compute_agent_competitor_scorecard()

        assert report["schema"] == "octopus.agent_competitor_scorecard.v1"
        assert sum(dimension.weight for dimension in DIMENSIONS) == 100
        assert report["overall"] == {
            "codex": 93,
            "claude_code": 91,
            "cursor": 86,
            "octopus": 96,
        }
        assert report["verdict"] == "leading"
        assert report["ranking"][0] == {"competitor": "octopus", "score": 96}
        assert report["evidence_adjusted_overall"]["octopus"] == 96
        assert report["evidence_adjusted_verdict"] == "leading"
        assert report["evidence_adjusted_ranking"][0] == {
            "competitor": "octopus",
            "score": 96,
        }
        assert report["scorecard_policy"] == {
            "schema": "octopus.agent_scorecard_policy.v1",
            "overall": "external_calibrated_baseline",
            "evidence_adjusted_overall": "internal_certification_floor",
            "certification_floors_do_not_change_overall": True,
        }
        assert report["octopus_below_target"] == []
        product = next(
            row for row in report["dimensions"]
            if row["id"] == "product_experience"
        )
        assert product["octopus_baseline_score"] == 95
        assert product["scores"]["octopus"] == 95
        assert product["octopus_score_source"] == "external_calibrated_baseline"
        assert product["octopus_evidence_adjusted_score"] == 95
        assert product["octopus_evidence_adjusted_score_source"] == "baseline"
        assert product["octopus_certified_score_floor"] == 97
        assert product["octopus_certification_score_applied"] is False
        assert product["octopus_certification_adjustment_available"] is False
        assert any(
            link["id"] == "product_experience_quality"
            and link["href"] == "/api/evolution/product-experience-quality"
            for link in product["operator_drilldown"]["links"]
        )
        repo_context = next(
            row for row in report["dimensions"]
            if row["id"] == "repo_context"
        )
        assert repo_context["scores"]["octopus"] == 96
        assert repo_context["scores"]["codex"] == 94
        assert repo_context["octopus_certified_score_floor"] == 97
        assert any(
            link["id"] == "repo_context_quality"
            and link["href"] == "/api/evolution/repo-context-quality"
            for link in repo_context["operator_drilldown"]["links"]
        )
        permissions = next(
            row for row in report["dimensions"]
            if row["id"] == "permissions_sandbox"
        )
        assert permissions["scores"]["octopus"] == 96
        assert permissions["scores"]["codex"] == 95
        assert permissions["octopus_certified_score_floor"] == 96
        assert any(
            link["id"] == "permission_sandbox_quality"
            and link["href"] == "/api/evolution/permission-sandbox-quality"
            for link in permissions["operator_drilldown"]["links"]
        )
        browser = next(
            row for row in report["dimensions"]
            if row["id"] == "browser_desktop"
        )
        assert browser["scores"]["cursor"] == 82
        assert browser["octopus_baseline_score"] == 95
        assert browser["scores"]["octopus"] == 95
        assert browser["octopus_evidence_adjusted_score"] == 95
        assert browser["octopus_certified_score_floor"] == 97
        assert browser["octopus_certification_score_applied"] is False
        assert browser["octopus_certification_adjustment_available"] is False
        differentiated = next(
            row for row in report["dimensions"]
            if row["id"] == "differentiated_agent_os"
        )
        assert differentiated["scores"]["octopus"] == 97
        assert differentiated["octopus_certified_score_floor"] == 97
        assert differentiated["octopus_certification_score_applied"] is False
        ecosystem = next(
            row for row in report["dimensions"]
            if row["id"] == "ecosystem_maturity"
        )
        assert ecosystem["octopus_baseline_score"] == 96
        assert ecosystem["scores"]["octopus"] == 96
        assert ecosystem["octopus_evidence_adjusted_score"] == 96
        assert ecosystem["octopus_certified_score_floor"] == 96
        assert ecosystem["octopus_certification_score_applied"] is False
        assert ecosystem["octopus_certification_adjustment_available"] is False
        assert ecosystem["octopus_evidence_checklist"]
        assert ecosystem["octopus_missing_evidence_count"] == 0
        assert ecosystem["octopus_ecosystem_readiness"]["score"] == 1.0
        drilldown = ecosystem["operator_drilldown"]
        assert drilldown["schema"] == "octopus.scorecard_operator_drilldown.v1"
        assert drilldown["dimension_id"] == "ecosystem_maturity"
        assert any(
            link["id"] == "plugin_permission_rule_drafts"
            and link["href"] == "/api/plugins/permission-rule-drafts"
            for link in drilldown["links"]
        )
        assert any(
            link["id"] == "plugin_migration_readiness"
            and link["href"] == "/api/plugins/migration-readiness"
            for link in drilldown["links"]
        )
        subagents = next(
            row for row in report["dimensions"]
            if row["id"] == "subagents_parallelism"
        )
        assert any(
            link["id"] == "team_task_process_timeline"
            and link["href_template"] == "/api/team-tasks/{task_id}/process-timeline"
            for link in subagents["operator_drilldown"]["links"]
        )
        assert report["ecosystem_readiness"]["passed"] == 5
        assert report["parity_certification"]["passed"] == 14
        assert report["parity_certification"]["ready"] is True
        assert report["parity_certification"]["by_kind"]["operational_excellence"] == {
            "passed": 4,
            "total": 4,
        }
        assert report["parity_certification"]["by_kind"]["advantage"] == {
            "passed": 4,
            "total": 4,
        }
        assert report["octopus_strengths"]
        assert report["next_focus"] == []

    def test_repo_context_quality_reports_release_evidence(self):
        from runtime.safety.evolution.repo_context_quality import (
            compute_repo_context_quality,
        )

        report = compute_repo_context_quality()

        assert report["schema"] == "octopus.repo_context_quality.v1"
        assert report["ready"] is True
        assert report["score"] == 1.0
        assert report["passed"] == report["total"]
        assert report["dirty_worktree"]["schema"] == (
            "octopus.dirty_worktree_awareness.v1"
        )
        assert report["dirty_worktree"]["command"] == "git status --short"

    def test_permission_sandbox_quality_reports_policy_coverage(self):
        from runtime.safety.evolution.permission_sandbox_quality import (
            compute_permission_sandbox_quality,
        )

        report = compute_permission_sandbox_quality()

        assert report["schema"] == "octopus.permission_sandbox_quality.v1"
        assert report["ready"] is True
        assert report["score"] == 1.0
        assert report["passed"] == report["total"]
        assert report["automation_policy_coverage"]["ready"] is True
        assert report["automation_policy_coverage"]["installable_deny_count"] == (
            report["automation_policy_coverage"]["total"]
        )
        assert report["automation_policy_coverage"]["missing_controls"] == {}
        assert report["plugin_policy_coverage"]["ready"] is True

    def test_product_experience_quality_reports_operator_surfaces(self):
        from runtime.safety.evolution.product_experience_quality import (
            compute_product_experience_quality,
        )

        report = compute_product_experience_quality()

        assert report["schema"] == "octopus.product_experience_quality.v1"
        assert report["ready"] is True
        assert report["score"] == 1.0
        assert report["passed"] == report["total"]

    def test_scorecard_includes_local_evidence_readiness(self, tmp_path):
        from runtime.safety.evolution.agent_competitor_scorecard import (
            compute_agent_competitor_scorecard,
        )

        (tmp_path / "runtime/core/cerebrum").mkdir(parents=True)
        (tmp_path / "runtime/core/cerebrum/react_loop.py").write_text(
            "# loop\n",
            encoding="utf-8",
        )

        report = compute_agent_competitor_scorecard(root=tmp_path)
        code_loop = next(
            item for item in report["dimensions"]
            if item["id"] == "core_coding_loop"
        )

        assert code_loop["scores"]["octopus"] == 97
        assert code_loop["octopus_evidence_readiness"] < 0.5
        assert code_loop["octopus_missing_evidence_count"] > 0
        assert "runtime/execution/tool_engine/executor.py" in (
            code_loop["octopus_evidence_checklist"][0]["implementation"]["missing"]
        )
        assert "tests/test_react_loop.py" in (
            code_loop["octopus_evidence_checklist"][0]["tests"]["missing"]
        )
        assert report["codex_gap"]["combined_score"] < 1.0


# ═══════════════════════════════════════════════════════════
# SubagentFitness
# ═══════════════════════════════════════════════════════════


class TestSubagentFitness:
    def test_empty_review_queue_has_no_roles(self, tmp_path):
        from runtime.safety.evolution.subagent_fitness import (
            compute_subagent_fitness,
        )

        report = compute_subagent_fitness(
            review_queue_path=tmp_path / "review_queue.json",
        )

        assert report["schema"] == "octopus.subagent_fitness.v1"
        assert report["roles"] == []
        assert report["top_risks"] == []

    def test_scores_roles_from_subagent_review_items(self, tmp_path):
        from runtime.memory.learning.review_queue import ReviewQueue
        from runtime.safety.evolution.subagent_fitness import (
            compute_subagent_fitness,
        )

        path = tmp_path / "review_queue.json"
        queue = ReviewQueue(path)
        queue.add_from_task_run_review(_subagent_review(
            "task-1",
            role="researcher",
            title="strong finding",
            output="strong reusable result",
            files=["report.md"],
        ))
        queue.add_from_task_run_review(_subagent_review(
            "task-2",
            role="researcher",
            title="weak finding",
            output="weak result",
        ))
        queue.add_from_task_run_review(_subagent_review(
            "task-3",
            role="researcher",
            title="neutral finding",
            output="neutral result",
        ))

        items = queue.items()["items"]
        queue.decide(items[0]["id"], action="promoted", reason="useful")
        queue.decide(items[1]["id"], action="rejected", reason="wrong")

        report = compute_subagent_fitness(review_queue_path=path)
        role = report["roles"][0]

        assert role["role"] == "researcher"
        assert role["sample_count"] == 3
        assert role["by_status"] == {
            "pending": 1,
            "promoted": 1,
            "rejected": 1,
        }
        assert role["confidence"] == 0.6
        assert role["verdict"] in {"developing", "watch"}
        assert report["role_count"] == 1

    def test_scores_deep_research_route_blocks_as_retirement_evidence(self, tmp_path):
        from runtime.safety.evolution.subagent_fitness import (
            compute_subagent_fitness,
        )

        job_store = tmp_path / "deep-research-jobs.jsonl"
        _write_deep_research_route_jobs(
            job_store,
            role="virtual-research-competitor-analyst",
            actions=["block", "block", "block"],
        )

        report = compute_subagent_fitness(
            review_queue_path=tmp_path / "review_queue.json",
            deep_research_job_store_path=job_store,
        )
        role = report["roles"][0]

        assert role["role"] == "virtual-research-competitor-analyst"
        assert role["sample_count"] == 3
        assert role["routing_evidence_count"] == 3
        assert role["by_evidence_source"] == {
            "deep_research_route_decision": 3,
        }
        assert role["by_status"] == {"rejected": 3}
        assert role["verdict"] == "retire_candidate"
        assert all(item.startswith("route-research-") for item in role["evidence_item_ids"])

    def test_scores_deep_research_warnings_without_promotion_inflation(self, tmp_path):
        from runtime.safety.evolution.subagent_fitness import (
            compute_subagent_fitness,
        )

        job_store = tmp_path / "deep-research-jobs.jsonl"
        _write_deep_research_route_jobs(
            job_store,
            role="virtual-research-market",
            actions=["allow_with_warning", "allow_with_warning"],
        )

        report = compute_subagent_fitness(
            review_queue_path=tmp_path / "review_queue.json",
            deep_research_job_store_path=job_store,
        )
        role = report["roles"][0]

        assert role["role"] == "virtual-research-market"
        assert role["routing_evidence_count"] == 2
        assert role["by_status"] == {"archived": 2}
        assert role["promoted_count"] == 0
        assert role["score"] < 0.7
        assert role["verdict"] == "watch"

    def test_router_exposes_subagent_fitness(self, tmp_path, monkeypatch):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from runtime.memory.learning.review_queue import ReviewQueue
        from runtime.sensing.gateway.evolution_router import create_evolution_router

        data_dir = tmp_path / "data"
        data_dir.mkdir()
        monkeypatch.setenv("OCTOPUS_DATA_DIR", str(data_dir))
        ReviewQueue(data_dir / "review_queue.json").add_from_task_run_review(
            _subagent_review(
                "task-1",
                role="researcher",
                title="router finding",
                output="router output",
            ),
        )

        app = FastAPI()
        app.include_router(create_evolution_router())
        data = TestClient(app).get("/api/evolution/subagent-fitness").json()

        assert data["ok"] is True
        assert data["schema"] == "octopus.subagent_fitness.v1"
        assert data["roles"][0]["role"] == "researcher"


class TestSubagentRouting:
    def test_allows_when_no_fitness_samples(self, tmp_path):
        from runtime.safety.evolution.subagent_routing import decide_subagent_route

        decision = decide_subagent_route(
            role="researcher",
            risk_level="critical",
            review_queue_path=tmp_path / "review_queue.json",
        )

        assert decision.action == "allow"
        assert decision.verdict == "unknown"
        assert decision.risk_level == "critical"

    def test_can_disable_fitness_routing(self, tmp_path):
        from runtime.safety.evolution.subagent_routing import decide_subagent_route

        decision = decide_subagent_route(
            role="researcher",
            risk_level="critical",
            review_queue_path=tmp_path / "review_queue.json",
            enabled=False,
        )

        assert decision.action == "allow"
        assert decision.reason == "subagent fitness routing disabled"

    def test_blocks_retire_candidate_for_high_risk(self, tmp_path):
        from runtime.memory.learning.review_queue import ReviewQueue
        from runtime.safety.evolution.subagent_routing import decide_subagent_route

        path = tmp_path / "review_queue.json"
        queue = ReviewQueue(path)
        for i in range(3):
            added = queue.add_from_task_run_review(_subagent_review(
                f"task-{i}",
                role="researcher",
                title=f"bad {i}",
                output=f"bad output {i}",
            ))
            queue.decide(added["items"][0]["id"], action="rejected", reason="bad")

        decision = decide_subagent_route(
            role="researcher",
            risk_level="high",
            review_queue_path=path,
        )

        assert decision.action == "block"
        assert decision.verdict == "retire_candidate"
        assert decision.score is not None and decision.score < 0.4

    def test_operator_retirement_policy_blocks_before_fitness(self, tmp_path):
        from runtime.safety.evolution.subagent_policy import SubagentPolicyStore
        from runtime.safety.evolution.subagent_routing import decide_subagent_route

        policy_path = tmp_path / "subagent_policy.json"
        SubagentPolicyStore(policy_path).decide(
            "researcher",
            action="retire",
            reason="bad route evidence",
            evidence_item_ids=["route-1"],
        )

        decision = decide_subagent_route(
            role="researcher",
            risk_level="low",
            review_queue_path=tmp_path / "review_queue.json",
            subagent_policy_path=policy_path,
        )

        assert decision.action == "block"
        assert decision.verdict == "operator_retired"
        assert decision.evidence_item_ids == ["route-1"]

    def test_operator_watch_policy_warns(self, tmp_path):
        from runtime.safety.evolution.subagent_policy import SubagentPolicyStore
        from runtime.safety.evolution.subagent_routing import decide_subagent_route

        policy_path = tmp_path / "subagent_policy.json"
        SubagentPolicyStore(policy_path).decide(
            "researcher",
            action="watch",
            reason="monitor next run",
        )

        decision = decide_subagent_route(
            role="researcher",
            risk_level="low",
            review_queue_path=tmp_path / "review_queue.json",
            subagent_policy_path=policy_path,
        )

        assert decision.action == "allow_with_warning"
        assert decision.verdict == "operator_watch"


class TestSubagentPolicy:
    def test_policy_store_decide_summary_and_clear(self, tmp_path):
        from runtime.safety.evolution.subagent_policy import SubagentPolicyStore

        store = SubagentPolicyStore(tmp_path / "subagent_policy.json")
        retired = store.decide(
            "researcher",
            action="retire",
            reason="bad evidence",
            evidence_item_ids=["route-1"],
            actor="tester",
        )

        assert retired["policy"]["status"] == "retired"
        assert store.summary()["retired_count"] == 1
        assert store.get("researcher")["reason"] == "bad evidence"

        cleared = store.decide("researcher", action="clear", reason="restored")

        assert cleared["policy"] is None
        assert store.summary()["policy_count"] == 0

    def test_router_exposes_subagent_policy_decisions(self, tmp_path, monkeypatch):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from runtime.sensing.gateway.evolution_router import create_evolution_router

        data_dir = tmp_path / "data"
        data_dir.mkdir()
        monkeypatch.setenv("OCTOPUS_DATA_DIR", str(data_dir))

        app = FastAPI()
        app.include_router(create_evolution_router())
        client = TestClient(app)

        response = client.post(
            "/api/evolution/subagent-policy/researcher/decision",
            json={
                "action": "retire",
                "reason": "operator reviewed route evidence",
                "evidence_item_ids": ["route-1"],
            },
        )
        summary = client.get("/api/evolution/subagent-policy")

        assert response.status_code == 200
        assert response.json()["policy"]["status"] == "retired"
        assert summary.json()["retired_count"] == 1
        assert summary.json()["policies"]["researcher"]["evidence_item_ids"] == ["route-1"]


def _subagent_review(
    task_id: str,
    *,
    role: str,
    title: str,
    output: str,
    files: list[str] | None = None,
) -> dict:
    return {
        "status": "completed",
        "task_id": task_id,
        "thread_id": "thread-1",
        "turn_id": task_id,
        "agent_id": role,
        "learning_candidates": [
            {
                "kind": "subagent_output",
                "priority": "P1" if files else "P2",
                "memory_bucket": "experience",
                "title": title,
                "text": output,
                "subagent": {
                    "role": role,
                    "agent_id": role,
                    "files_touched": files or [],
                },
            }
        ],
    }


def _write_deep_research_route_jobs(path, *, role: str, actions: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for index, action in enumerate(actions):
        lines.append(json.dumps({
            "job_id": f"research-{index}",
            "thread_id": "thread-1",
            "route_decisions": [
                {
                    "schema": "octopus.subagent_route_decision.v1",
                    "step_id": f"step-{index}",
                    "task_id": f"step-{index}",
                    "role": role,
                    "action": action,
                    "reason": f"{role} route {action}",
                    "risk_level": "high" if action == "block" else "low",
                    "verdict": "retire_candidate",
                    "score": 0.1,
                    "confidence": 0.6,
                    "evidence_item_ids": [f"review-{index}"],
                    "phase": "subagent_route_blocked" if action == "block" else "completed",
                    "created_at": f"2026-06-19T00:00:0{index}Z",
                }
            ],
        }))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ═══════════════════════════════════════════════════════════
# ProposalLedger
# ═══════════════════════════════════════════════════════════


class TestProposalLedger:
    def test_propose_and_query(self, tmp_path):
        ledger = ProposalLedger(tmp_path / "ledger.jsonl")
        r = ledger.propose(kind="add_lesson", description="test", fitness_before=0.7)
        assert r.status == ProposalStatus.PROPOSED
        assert r.kind == "add_lesson"

        records = ledger.query(status=ProposalStatus.PROPOSED)
        assert len(records) == 1

    def test_mark_applied(self, tmp_path):
        ledger = ProposalLedger(tmp_path / "ledger.jsonl")
        r = ledger.propose(kind="add_lesson", description="test")
        ledger.mark_applied(r.proposal_id, fitness_after=0.85)
        records = ledger.query(status=ProposalStatus.APPLIED)
        assert len(records) == 1
        assert records[0].fitness_after == 0.85

    def test_reject_with_reason(self, tmp_path):
        ledger = ProposalLedger(tmp_path / "ledger.jsonl")
        r = ledger.propose(kind="add_lesson", description="bad")
        ledger.reject(r.proposal_id, reason="too risky")
        records = ledger.query(status=ProposalStatus.REJECTED)
        assert len(records) == 1

    def test_stats(self, tmp_path):
        ledger = ProposalLedger(tmp_path / "ledger.jsonl")
        ledger.propose(kind="a", description="1")
        ledger.propose(kind="b", description="2")
        stats = ledger.stats()
        assert stats["total"] == 2

    def test_rollback(self, tmp_path):
        ledger = ProposalLedger(tmp_path / "ledger.jsonl")
        r = ledger.propose(kind="add_lesson", description="test")
        ledger.mark_applied(r.proposal_id)
        ledger.mark_rolled_back(r.proposal_id)
        records = ledger.query(status=ProposalStatus.ROLLED_BACK)
        assert len(records) == 1

    def test_enrich_run_records_attaches_lifecycle(self, tmp_path):
        ledger_path = tmp_path / "ledger.jsonl"
        canary_config = CanaryConfig(state_dir=str(tmp_path / "canary"))
        ledger = ProposalLedger(ledger_path)
        proposal = ledger.propose(
            kind="prompt_optimizer_winner",
            description="test winner",
            metadata={"recipe_id": "planner", "candidate_id": "cand-1"},
        )
        ledger.mark_applied(proposal.proposal_id)
        cm = CanaryManager(canary_config)
        cm.register(
            "planner__cand-1",
            metadata={
                "recipe_id": "planner",
                "candidate_id": "cand-1",
                "proposal_id": proposal.proposal_id,
                "last_rollback_reason": "bad canary",
            },
        )
        cm.force_rollback("planner__cand-1")

        run = GepaRunRecord(
            ts=123.0,
            trigger="manual",
            recipe_id="planner",
            iterations_run=3,
            elapsed_s=1.2,
            front_size=1,
            best_candidate_id="cand-1",
            best_avg_score=0.91,
            best_rationale="tighten verification",
            best_prompt="prompt",
            applied=True,
        )
        enriched = enrich_run_records([run], ledger_path=ledger_path, canary_config=canary_config)
        assert enriched[0]["winner_proposal_id"] == proposal.proposal_id
        assert enriched[0]["winner_proposal_status"] == ProposalStatus.APPLIED.value
        assert enriched[0]["winner_canary_phase"] == CanaryPhase.ROLLED_BACK.value
        assert enriched[0]["winner_lifecycle_state"] == CanaryPhase.ROLLED_BACK.value
        assert enriched[0]["winner_rollback_reason"] == "bad canary"

    def test_record_from_result_keeps_native_evidence(self):
        class Candidate:
            candidate_id = "cand-1"
            avg_score = 0.91
            rationale = "tighten verification"
            prompt = "Verify before completion."

        class Result:
            iterations_run = 2
            elapsed_s = 1.0
            final_front = [Candidate()]
            best_avg = Candidate()
            history = [{"iter": 0, "front_size": 1, "best_avg": 0.5}]
            native_evaluation = [{
                "candidate_id": "cand-1",
                "total": 0.82,
                "verdict": "promote",
                "task_score": 0.9,
                "constraint_score": 1.0,
                "failure_coverage": 0.75,
                "positive_preservation": 0.8,
                "efficiency": 0.95,
                "reasons": ["balanced candidate"],
                "constraint_results": [{"verbose": "omitted"}],
            }]
            native_replay = {
                "cases": [{"case_id": "case-1"}, {"case_id": "case-2"}],
                "candidates": [{
                    "candidate_id": "cand-1",
                    "total": 0.77,
                    "reasons": ["replay coverage is strong"],
                    "case_results": [{
                        "case_id": "case-2",
                        "kind": "failure",
                        "score": 0.4,
                        "reason": "missing failure-specific guidance",
                        "missing_signals": ["continue", "checkpoint"],
                    }],
                }],
            }
            native_sandbox_replay = {
                "case_count": 2,
                "candidates": [{
                    "candidate_id": "cand-1",
                    "total": 0.72,
                    "passed": False,
                    "reasons": ["sandbox replay weak cases: case-2"],
                    "case_results": [{
                        "case_id": "case-2",
                        "kind": "failure",
                        "score": 0.5,
                        "sandbox_passed": True,
                        "reason": "missing failure-specific guidance",
                    }],
                }],
            }
            native_turn_replay = {
                "cases": [{"case_id": "turn-1"}, {"case_id": "turn-2"}],
                "candidates": [{
                    "candidate_id": "cand-1",
                    "total": 0.69,
                    "passed": False,
                    "reasons": ["turn replay weak cases: turn-2"],
                    "case_results": [{
                        "case_id": "turn-2",
                        "kind": "final_step_stuck",
                        "score": 0.4,
                        "passed": False,
                        "reason": "final_step_stuck missing: close-after-final",
                        "missing_signals": ["close-after-final"],
                    }],
                }],
            }
            native_llm_replay = {
                "cases": [{"case_id": "llm-1"}],
                "candidates": [{
                    "candidate_id": "cand-1",
                    "total": 0.81,
                    "passed": False,
                    "reasons": ["llm replay weak cases: llm-1"],
                    "case_results": [{
                        "case_id": "llm-1",
                        "kind": "report_truncation",
                        "score": 0.2,
                        "passed": False,
                        "reason": "model output was truncated",
                    }],
                }],
            }
            winner_proposal = {
                "ok": False,
                "reason": "native_replay_rejected",
                "candidate_id": "cand-1",
                "native_replay": {"too_large": "omitted"},
            }

        rec = record_from_result(Result(), trigger="manual", recipe_id="planner")

        assert rec.native_evaluation[0]["candidate_id"] == "cand-1"
        assert rec.native_evaluation[0]["verdict"] == "promote"
        assert "constraint_results" not in rec.native_evaluation[0]
        assert rec.native_replay["case_count"] == 2
        assert rec.native_replay["candidates"][0]["weak_cases"][0]["case_id"] == "case-2"
        assert rec.native_sandbox_replay["case_count"] == 2
        assert rec.native_sandbox_replay["candidates"][0]["weak_cases"][0]["case_id"] == "case-2"
        assert rec.native_turn_replay["case_count"] == 2
        assert rec.native_turn_replay["candidates"][0]["weak_cases"][0]["case_id"] == "turn-2"
        assert rec.native_llm_replay["case_count"] == 1
        assert rec.native_llm_replay["candidates"][0]["weak_cases"][0]["case_id"] == "llm-1"
        assert rec.winner_proposal == {
            "ok": False,
            "reason": "native_replay_rejected",
            "candidate_id": "cand-1",
        }

    def test_ledger_proposal_endpoint_returns_related_canary_and_rollback(self, tmp_path, monkeypatch):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from runtime.sensing.gateway.evolution_router import create_evolution_router

        monkeypatch.chdir(tmp_path)
        ledger = ProposalLedger()
        proposal = ledger.propose(
            kind="prompt_optimizer_winner",
            description="test winner",
            metadata={"recipe_id": "planner", "candidate_id": "cand-1"},
        )
        ledger.mark_rolled_back(proposal.proposal_id)
        rollback = ledger.propose(
            kind="canary_rollback",
            description="rollback winner",
            metadata={"source_proposal_id": proposal.proposal_id},
        )
        ledger.mark_rolled_back(rollback.proposal_id)
        cm = CanaryManager()
        cm.register(
            "planner__cand-1",
            metadata={"proposal_id": proposal.proposal_id, "candidate_id": "cand-1"},
        )

        app = FastAPI()
        app.include_router(create_evolution_router())
        data = TestClient(app).get(f"/api/evolution/ledger/{proposal.proposal_id}").json()

        assert data["ok"] is True
        assert data["proposal"]["id"] == proposal.proposal_id
        assert data["proposal"]["status"] == ProposalStatus.ROLLED_BACK.value
        assert data["canaries"][0]["skill_name"] == "planner__cand-1"
        assert data["rollbacks"][0]["id"] == rollback.proposal_id


# ═══════════════════════════════════════════════════════════
# Canary
# ═══════════════════════════════════════════════════════════


class TestCanaryManager:
    def test_register_new_skill(self, tmp_path):
        cm = CanaryManager(CanaryConfig(state_dir=str(tmp_path / "canary")))
        state = cm.register("my_skill")
        assert state.phase == CanaryPhase.SHADOW
        assert state.skill_name == "my_skill"

    def test_register_idempotent(self, tmp_path):
        cm = CanaryManager(CanaryConfig(state_dir=str(tmp_path / "canary")))
        s1 = cm.register("skill_a")
        s2 = cm.register("skill_a")
        assert s1 is s2

    def test_promote_after_enough_successes(self, tmp_path):
        cm = CanaryManager(CanaryConfig(state_dir=str(tmp_path / "canary")))
        cm.register("skill_b")
        for _ in range(15):
            cm.record_outcome("skill_b", True)
        state = cm.get_state("skill_b")
        assert state.phase == CanaryPhase.CANARY_5

    def test_rollback_on_high_failure(self, tmp_path):
        cm = CanaryManager(CanaryConfig(state_dir=str(tmp_path / "canary")))
        cm.register("skill_c")
        for _ in range(8):
            cm.record_outcome("skill_c", False)
        state = cm.get_state("skill_c")
        assert state.phase == CanaryPhase.ROLLED_BACK

    def test_force_rollback(self, tmp_path):
        cm = CanaryManager(CanaryConfig(state_dir=str(tmp_path / "canary")))
        cm.register("skill_d")
        state = cm.force_rollback("skill_d")
        assert state.phase == CanaryPhase.ROLLED_BACK

    def test_rolled_back_skill_not_routed(self, tmp_path):
        cm = CanaryManager(CanaryConfig(state_dir=str(tmp_path / "canary")))
        cm.register("skill_e")
        cm.force_rollback("skill_e")
        assert cm.should_route_to_skill("skill_e") is False

    def test_full_skill_always_routed(self, tmp_path):
        cm = CanaryManager(CanaryConfig(state_dir=str(tmp_path / "canary")))
        cm.register("skill_f")
        state = cm.get_state("skill_f")
        state.phase = CanaryPhase.FULL
        assert cm.should_route_to_skill("skill_f") is True

    def test_list_active(self, tmp_path):
        cm = CanaryManager(CanaryConfig(state_dir=str(tmp_path / "canary")))
        cm.register("g1")
        cm.register("g2")
        cm.force_rollback("g2")
        active = cm.list_active()
        names = [s.skill_name for s in active]
        assert "g1" in names
        assert "g2" not in names

    def test_list_all_keeps_terminal_states_visible(self, tmp_path):
        cm = CanaryManager(CanaryConfig(state_dir=str(tmp_path / "canary")))
        cm.register("active_skill")
        full = cm.register("full_skill")
        full.phase = CanaryPhase.FULL
        cm.register("rolled_skill")
        cm.force_rollback("rolled_skill")
        all_names = {s.skill_name for s in cm.list_all()}
        active_names = {s.skill_name for s in cm.list_active()}
        assert all_names == {"active_skill", "full_skill", "rolled_skill"}
        assert active_names == {"active_skill"}

    def test_canary_router_lists_full_and_rolled_back_states(self, tmp_path, monkeypatch):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from runtime.sensing.gateway.evolution_router import create_evolution_router

        cm = CanaryManager(CanaryConfig(state_dir=str(tmp_path / "canary")))
        cm.register("active_skill", metadata={"candidate_id": "cand_1"})
        full = cm.register("full_skill", metadata={"proposal_id": "prop_1"})
        full.phase = CanaryPhase.FULL
        cm.register("rolled_skill", metadata={"last_rollback_reason": "bad canary"})
        cm.force_rollback("rolled_skill")
        monkeypatch.setattr("runtime.safety.evolution.canary.CanaryManager", lambda: cm)

        app = FastAPI()
        app.include_router(create_evolution_router())
        data = TestClient(app).get("/api/evolution/canary").json()

        phases = {row["skill_name"]: row["phase"] for row in data["canaries"]}
        assert data["ok"] is True
        assert data["active_count"] == 1
        assert data["full_count"] == 1
        assert data["rolled_back_count"] == 1
        assert phases["active_skill"] == CanaryPhase.SHADOW.value
        assert phases["full_skill"] == CanaryPhase.FULL.value
        assert phases["rolled_skill"] == CanaryPhase.ROLLED_BACK.value


# ═══════════════════════════════════════════════════════════
# Federation
# ═══════════════════════════════════════════════════════════


class TestFederationHub:
    def test_publish_and_discover(self, tmp_path):
        hub = FederationHub(FederationConfig(shared_dir=str(tmp_path / "fed")))
        proposal = SharedProposal(
            proposal_id="p1", source_agent="agent_a",
            kind="add_lesson", description="test lesson",
            fitness_delta=0.15, ts="2026-01-01T00:00:00",
        )
        hub.publish("agent_a", proposal)
        discovered = hub.discover("agent_b")
        assert len(discovered) == 1
        assert discovered[0].source_agent == "agent_a"

    def test_agent_does_not_discover_own(self, tmp_path):
        hub = FederationHub(FederationConfig(shared_dir=str(tmp_path / "fed")))
        proposal = SharedProposal(
            proposal_id="p2", source_agent="agent_a",
            kind="add_lesson", description="test",
            fitness_delta=0.1, ts="2026-01-01T00:00:00",
        )
        hub.publish("agent_a", proposal)
        discovered = hub.discover("agent_a")
        assert len(discovered) == 0

    def test_adopt_success(self, tmp_path):
        hub = FederationHub(FederationConfig(shared_dir=str(tmp_path / "fed")))
        proposal = SharedProposal(
            proposal_id="p3", source_agent="agent_a",
            kind="add_lesson", description="good lesson",
            fitness_delta=0.2, ts="2026-01-01T00:00:00",
        )
        hub.publish("agent_a", proposal)
        discovered = hub.discover("agent_b")
        result = hub.adopt("agent_b", discovered[0])
        assert result is True

    def test_adopt_rejects_low_fitness_delta(self, tmp_path):
        hub = FederationHub(FederationConfig(
            shared_dir=str(tmp_path / "fed"),
            adoption_threshold=0.5,
        ))
        proposal = SharedProposal(
            proposal_id="p4", source_agent="agent_a",
            kind="add_lesson", description="marginal",
            fitness_delta=0.05, ts="2026-01-01T00:00:00",
        )
        hub.publish("agent_a", proposal)
        discovered = hub.discover("agent_b")
        result = hub.adopt("agent_b", discovered[0])
        assert result is False

    def test_stats(self, tmp_path):
        hub = FederationHub(FederationConfig(shared_dir=str(tmp_path / "fed")))
        proposal = SharedProposal(
            proposal_id="p5", source_agent="agent_a",
            kind="add_lesson", description="test",
            fitness_delta=0.1, ts="2026-01-01T00:00:00",
        )
        hub.publish("agent_a", proposal)
        stats = hub.stats()
        assert stats["agents"] == 1
        assert stats["proposals"] == 1


# ═══════════════════════════════════════════════════════════
# StrategyEngine
# ═══════════════════════════════════════════════════════════


class TestStrategyEngine:
    def _make_report(self, combined: float, verdict: str) -> FitnessReport:
        return FitnessReport(
            agent_id="test", ts="t",
            l1=L1Fitness(score=combined, trend="stable", success_rate=combined, avg_rounds=5.0, soul_impact={}),
            l2=None, combined=combined, verdict=verdict,
        )

    def test_critical_triggers_revert(self):
        engine = StrategyEngine()
        decision = engine.decide(self._make_report(0.1, "critical"))
        assert decision.action == "revert"
        assert decision.confidence == "high"

    def test_low_fitness_triggers_evolve(self):
        engine = StrategyEngine()
        decision = engine.decide(self._make_report(0.3, "unhealthy"))
        assert decision.action == "evolve"

    def test_high_stable_triggers_explore(self):
        engine = StrategyEngine()
        for _ in range(6):
            engine.decide(self._make_report(0.85, "healthy"))
        decision = engine.decide(self._make_report(0.85, "healthy"))
        assert decision.action == "explore"

    def test_medium_fitness_triggers_hold(self):
        engine = StrategyEngine()
        decision = engine.decide(self._make_report(0.65, "degraded"))
        assert decision.action == "hold"

    def test_regressing_trend_triggers_evolve(self):
        engine = StrategyEngine()
        engine._history = [
            self._make_report(0.80, "degraded"),
            self._make_report(0.72, "degraded"),
            self._make_report(0.64, "degraded"),
            self._make_report(0.56, "degraded"),
        ]
        decision = engine.decide(self._make_report(0.48, "unhealthy"))
        assert decision.action == "evolve"
