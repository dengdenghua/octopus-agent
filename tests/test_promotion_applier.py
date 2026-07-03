from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from runtime.memory.learning.experience_ledger import ExperienceLedger
from runtime.memory.learning.promotion_applier import PromotionApplier
from runtime.memory.learning.review_queue import ReviewQueue
from runtime.safety.evolution.proposal_ledger import ProposalLedger


def _review(task_id: str = "turn-1") -> dict:
    return {
        "schema": "octopus.task_run_review.v1",
        "task_id": task_id,
        "thread_id": "thread-1",
        "turn_id": task_id,
        "agent_id": "agent-a",
        "status": "completed",
        "replay": {
            "schema": "octopus.task_run_replay_case.v1",
            "case_id": f"task-run:{task_id}",
            "fingerprint": "abc123",
            "replayable": True,
            "step_count": 3,
        },
        "learning_candidates": [
            {
                "kind": "success_pattern",
                "priority": "P1",
                "memory_bucket": "experience",
                "title": "Useful tool sequence",
                "text": "Read the relevant files before editing.",
            }
        ],
        "backlog_candidates": [
            {
                "priority": "P0",
                "experiment": "Replay fixture",
                "hypothesis": "Replay prevents repeating the failure.",
                "minimal_implementation": "Convert the replay to a fixture.",
                "validation_metric": "Replay passes.",
            }
        ],
    }


def _applier(tmp_path: Path, queue: ReviewQueue) -> PromotionApplier:
    return PromotionApplier(
        review_queue=queue,
        experience_ledger=ExperienceLedger(tmp_path / "experience.json"),
        proposal_ledger=ProposalLedger(tmp_path / "proposal_ledger.jsonl"),
        audit_path=tmp_path / "promotion_audit.json",
    )


def test_promotion_applier_plans_and_applies_experience_items(tmp_path: Path) -> None:
    queue = ReviewQueue(tmp_path / "review_queue.json")
    queue.add_from_task_run_review(_review())
    item = queue.items(target_bucket="experience")["items"][0]
    queue.decide(item["id"], action="promoted", promoted_to="experience")
    applier = _applier(tmp_path, queue)

    plan = applier.plan()
    applied = applier.apply(
        decision_context={
            "schema": "octopus.promotion_decision_context.v1",
            "replay_gate": {"passed": True},
            "override_replay_gate": False,
        },
        now=datetime(2026, 6, 7, 3, 0, tzinfo=UTC),
    )
    second_plan = applier.plan()
    audit = applier.audit()
    summary = applier.audit_summary()
    ledger_rows = ExperienceLedger(tmp_path / "experience.json").records()

    assert plan["dry_run"] is True
    assert plan["applicable"] == 1
    assert applied["applied"] == 1
    assert applied["results"][0]["artifact"]["type"] == "experience_ledger"
    assert second_plan["skipped"] == 1
    assert second_plan["actions"][0]["reason"] == "already applied"
    assert audit["total"] == 1
    assert audit["records"][0]["review_queue_item_id"] == item["id"]
    assert audit["records"][0]["agent_id"] == "agent-a"
    assert audit["records"][0]["decision_context"]["replay_gate"]["passed"] is True
    assert audit["records"][0]["decision_context"]["override_replay_gate"] is False
    assert summary["schema"] == "octopus.promotion_audit_summary.v1"
    assert summary["total"] == 1
    assert summary["by_event_type"]["promotion_apply"] == 1
    assert summary["override_count"] == 0
    assert summary["gate_failed_count"] == 0
    assert summary["topology_policy_block_count"] == 0
    assert ledger_rows["total"] == 1
    assert ledger_rows["records"][0]["memory_bucket"] == "experience"
    assert ledger_rows["records"][0]["metadata"]["citation"] == {
        "schema": "octopus.experience_replay_citation.v1",
        "task_id": "turn-1",
        "thread_id": "thread-1",
        "turn_id": "turn-1",
        "agent_id": "agent-a",
        "replay_case_id": "task-run:turn-1",
        "replay_fingerprint": "abc123",
        "replayable": True,
    }


def test_promotion_audit_summary_counts_topology_policy_blocks(
    tmp_path: Path,
) -> None:
    from runtime.safety.evolution.governance_audit import (
        append_governance_audit_event,
    )

    queue = ReviewQueue(tmp_path / "review_queue.json")
    applier = _applier(tmp_path, queue)
    append_governance_audit_event(
        event_type="topology_policy_block",
        target="topology_policy",
        status="blocked",
        artifact={"topology_id": "research_swarm_v1"},
        decision_context={"source": "test"},
        audit_path=tmp_path / "promotion_audit.json",
    )

    summary = applier.audit_summary()

    assert summary["total"] == 1
    assert summary["by_event_type"]["topology_policy_block"] == 1
    assert summary["by_target"]["topology_policy"] == 1
    assert summary["topology_policy_block_count"] == 1
    assert summary["integrity"]["ok"] is True
    assert summary["integrity"]["entries_checked"] == 1


def test_promotion_applier_applies_experiment_backlog_to_experience_ledger(
    tmp_path: Path,
) -> None:
    queue = ReviewQueue(tmp_path / "review_queue.json")
    queue.add_from_task_run_review(_review())
    item = queue.items(target_bucket="experiment_backlog")["items"][0]
    queue.decide(item["id"], action="promoted", promoted_to="experiment_backlog")
    applier = _applier(tmp_path, queue)

    result = applier.apply()
    rows = ExperienceLedger(tmp_path / "experience.json").records(
        bucket="experiment_backlog",
    )

    assert result["applied"] == 1
    assert rows["total"] == 1
    assert rows["records"][0]["kind"] == "backlog_candidate"


def test_promotion_applier_applies_rule_candidates_to_proposal_ledger(
    tmp_path: Path,
) -> None:
    queue = ReviewQueue(tmp_path / "review_queue.json")
    queue.add_from_task_run_review(_review())
    item = queue.items(target_bucket="experience")["items"][0]
    queue.decide(item["id"], action="promoted", promoted_to="rule_candidate")
    applier = _applier(tmp_path, queue)

    result = applier.apply()
    proposals = ProposalLedger(tmp_path / "proposal_ledger.jsonl").query(
        kind="review_queue_rule_candidate",
    )

    assert result["applied"] == 1
    assert result["results"][0]["artifact"]["type"] == "proposal_ledger"
    assert len(proposals) == 1
    assert proposals[0].metadata["review_queue_item_id"] == item["id"]


def test_promotion_applier_applies_browser_desktop_repair_recipe_to_proposal_ledger(
    tmp_path: Path,
) -> None:
    queue = ReviewQueue(tmp_path / "review_queue.json")
    queued = queue.upsert_item(
        source="browser_desktop_repair_recipe",
        source_kind="browser_desktop_repair_recipe",
        candidate_kind="browser_desktop_repair_recipe:abc123",
        priority="P0",
        target_bucket="browser_desktop_repair_recipe",
        title="Stabilize browser pixel replay gate",
        text="Repeated browser pixel replay failures need a deterministic repair.",
        metadata={
            "schema": "octopus.browser_desktop_repair_recipe.v1",
            "recipe": {
                "schema": "octopus.browser_desktop_repair_recipe.v1",
                "recipe_id": "browser-desktop-recipe:abc123",
                "candidate_kind": "browser_pixel_replay_gate_case",
                "occurrences": 3,
                "case_ids": ["browser-pixel::one.png", "browser-pixel::two.png"],
                "fingerprints": ["fp-one", "fp-two"],
                "recommended_steps": [
                    "Replay the browser action that produced the failing screenshot.",
                    "Capture a fresh before/after screenshot pair for the same viewport.",
                ],
                "verification_plan": {
                    "schema": "octopus.browser_desktop_recipe_verification.v1",
                    "api_checks": ["/api/evolution/browser-desktop-quality"],
                    "evidence_required": ["fresh_screenshot", "pixel_comparison"],
                },
                "promotion_gate": {
                    "schema": "octopus.browser_desktop_repair_recipe_gate.v1",
                    "requires_operator_review": True,
                    "requires_replay_rerun": True,
                    "blocks_auto_promotion": True,
                },
            },
        },
    )
    item = queued["items"][0]
    queue.decide(
        item["id"],
        action="promoted",
        promoted_to="browser_desktop_repair_recipe",
    )
    applier = _applier(tmp_path, queue)

    result = applier.apply()
    proposals = ProposalLedger(tmp_path / "proposal_ledger.jsonl").query(
        kind="review_queue_browser_desktop_repair_recipe",
    )

    assert result["applied"] == 1
    assert result["results"][0]["artifact"]["type"] == "proposal_ledger"
    assert len(proposals) == 1
    evidence = proposals[0].metadata["evidence"]
    assert evidence["schema"] == ("octopus.browser_desktop_repair_recipe_promotion_evidence.v1")
    assert evidence["recipe_id"] == "browser-desktop-recipe:abc123"
    assert evidence["occurrences"] == 3
    assert evidence["case_ids"] == ["browser-pixel::one.png", "browser-pixel::two.png"]
    assert evidence["promotion_gate"]["requires_replay_rerun"] is True
    assert evidence["verification_plan"]["evidence_required"] == [
        "fresh_screenshot",
        "pixel_comparison",
    ]


def test_policy_review_promotion_requires_replay_evidence(tmp_path: Path) -> None:
    queue = ReviewQueue(tmp_path / "review_queue.json")
    queued = queue.upsert_item(
        source="trust_denials",
        source_kind="tool_policy_denial",
        candidate_kind="policy_review",
        priority="P1",
        target_bucket="policy_review",
        title="Review repeated denials for exec_shell",
        text="Tool exec_shell was denied repeatedly.",
        source_task_ids=["turn-denied"],
    )
    item = queued["items"][0]
    queue.decide(
        item["id"],
        action="promoted",
        promoted_to="policy_review",
    )
    applier = _applier(tmp_path, queue)

    result = applier.apply()
    proposals = ProposalLedger(tmp_path / "proposal_ledger.jsonl").query(
        kind="review_queue_policy_review",
    )
    audit = applier.audit()

    assert result["applied"] == 0
    assert result["failed"] == 1
    assert result["results"][0]["error"] == "policy_review promotion requires replay evidence"
    assert proposals == []
    assert audit["records"][0]["status"] == "failed"


def test_policy_review_promotion_creates_proposal_with_replay_evidence(
    tmp_path: Path,
) -> None:
    queue = ReviewQueue(tmp_path / "review_queue.json")
    queued = queue.upsert_item(
        source="trust_denials",
        source_kind="tool_policy_denial",
        candidate_kind="policy_review",
        priority="P1",
        target_bucket="policy_review",
        title="Review repeated denials for exec_shell",
        text="Tool exec_shell was denied repeatedly.",
        metadata={
            "replay": {
                "schema": "octopus.task_run_replay.v1",
                "case_id": "task-run:abc123",
                "fingerprint": "abc123",
                "replayable": True,
                "step_count": 2,
            },
        },
        source_task_ids=["turn-denied"],
    )
    item = queued["items"][0]
    queue.decide(
        item["id"],
        action="promoted",
        promoted_to="policy_review",
    )
    applier = _applier(tmp_path, queue)

    result = applier.apply()
    proposals = ProposalLedger(tmp_path / "proposal_ledger.jsonl").query(
        kind="review_queue_policy_review",
    )

    assert result["applied"] == 1
    assert result["results"][0]["artifact"]["type"] == "proposal_ledger"
    assert len(proposals) == 1
    assert proposals[0].metadata["review_queue_item_id"] == item["id"]
    assert proposals[0].metadata["evidence"]["replay"]["case_id"] == "task-run:abc123"


def test_policy_review_promotion_uses_item_replay_gate_evidence(
    tmp_path: Path,
) -> None:
    queue = ReviewQueue(tmp_path / "review_queue.json")
    queued = queue.upsert_item(
        source="browser_pixel_replay_gate",
        source_kind="browser_desktop_replay",
        candidate_kind="policy_review",
        priority="P0",
        target_bucket="policy_review",
        title="Review browser pixel replay gate",
        text="Browser pixel replay gate needs policy review.",
        metadata={
            "replay": {
                "schema": "octopus.browser_pixel_replay_gate_case.v1",
                "case_id": "browser-pixel::artifact.png",
                "fingerprint": "0123456789abcdef",
                "replayable": False,
                "step_count": 1,
            },
            "replay_gate": {
                "passed": True,
                "reason": "operator_verified_browser_pixel_case",
            },
        },
        source_task_ids=["turn-browser"],
    )
    item = queued["items"][0]
    queue.decide(item["id"], action="promoted", promoted_to="policy_review")
    applier = _applier(tmp_path, queue)

    result = applier.apply()
    proposals = ProposalLedger(tmp_path / "proposal_ledger.jsonl").query(
        kind="review_queue_policy_review",
    )

    assert result["applied"] == 1
    assert proposals[0].metadata["evidence"]["replay"]["case_id"] == ("browser-pixel::artifact.png")
    assert proposals[0].metadata["evidence"]["replay_gate"]["reason"] == (
        "operator_verified_browser_pixel_case"
    )
