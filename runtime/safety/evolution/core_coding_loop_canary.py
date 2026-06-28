from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from runtime.memory.learning.review_queue import ReviewQueue
from runtime.safety.evolution.auto_verifier import run_highest_priority_verification
from runtime.safety.evolution.auto_verifier_metrics import (
    queue_verifier_drift_backlog,
    rank_verification_commands,
    recent_auto_verifier_decisions,
    record_auto_verifier_metric,
    summarize_auto_verifier_metrics,
)
from runtime.safety.evolution.proposal_ledger import ProposalLedger
from runtime.safety.evolution.repair_route_quality import (
    compute_repair_route_quality,
    queue_repair_route_promotion_candidates,
)

SCHEMA = "octopus.core_coding_loop_canary.v1"


def run_core_coding_loop_canary() -> dict[str, Any]:
    previous_data_dir = os.environ.get("OCTOPUS_DATA_DIR")
    with tempfile.TemporaryDirectory(prefix="octopus-core-loop-canary-") as tmp:
        root = Path(tmp)
        data_dir = root / "data"
        workspace = root / "workspace"
        workspace.mkdir(parents=True)
        target = workspace / "test_canary_target.py"
        target.write_text(
            "def test_canary_target():\n"
            "    assert 1 + 1 == 2\n",
            encoding="utf-8",
        )
        metrics_path = data_dir / "auto_verifier_metrics.jsonl"
        review_queue_path = data_dir / "review_queue.json"
        ledger_path = data_dir / "proposal_ledger.jsonl"
        data_dir.mkdir(parents=True, exist_ok=True)
        os.environ["OCTOPUS_DATA_DIR"] = str(data_dir)
        try:
            ranking_probe = _ranking_probe(metrics_path)
            execution_probe = _execution_probe(workspace)
            drift_probe = _drift_probe(
                metrics_path=metrics_path,
                review_queue_path=review_queue_path,
            )
            repair_probe = _repair_route_probe(
                ledger_path=ledger_path,
                review_queue_path=review_queue_path,
            )
            promotion_probe = _repair_route_promotion_probe(
                ledger_path=ledger_path,
                review_queue_path=review_queue_path,
            )
        finally:
            if previous_data_dir is None:
                os.environ.pop("OCTOPUS_DATA_DIR", None)
            else:
                os.environ["OCTOPUS_DATA_DIR"] = previous_data_dir

    checks = {
        "history_ranking_selects_stable_verifier": ranking_probe.get("ok") is True,
        "sandboxed_verifier_executes": execution_probe.get("ok") is True,
        "decision_and_metric_recorded": execution_probe.get("telemetry_ok") is True,
        "verifier_drift_routes_to_backlog": drift_probe.get("ok") is True,
        "repair_route_quality_gate_clean": repair_probe.get("ok") is True,
        "repair_route_promotion_evidence_queued": promotion_probe.get("ok") is True,
    }
    passed = sum(1 for value in checks.values() if value is True)
    total = len(checks)
    score = round(passed / total, 3) if total else 0.0
    ready = score >= 1.0
    return {
        "schema": SCHEMA,
        "score": score,
        "ready": ready,
        "verdict": "pass" if ready else "review" if score >= 0.8 else "fail",
        "checks": checks,
        "probe": {
            "ranking": ranking_probe,
            "execution": execution_probe,
            "drift": drift_probe,
            "repair_route": repair_probe,
            "repair_route_promotion": promotion_probe,
        },
        "next_actions": _next_actions(checks),
    }


def _ranking_probe(metrics_path: Path) -> dict[str, Any]:
    for ok in (False, False, False):
        record_auto_verifier_metric(
            command="python -m ruff check canary_target.py",
            kind="lint",
            ok=ok,
            exit_code=1,
            duration_ms=200,
            target="canary_target.py",
            path=metrics_path,
        )
    record_auto_verifier_metric(
        command="python -m pytest test_canary_target.py -q",
        kind="test",
        ok=True,
        exit_code=0,
        duration_ms=80,
        target="test_canary_target.py",
        path=metrics_path,
    )
    commands = [
        {
            "command": "python -m ruff check canary_target.py",
            "kind": "lint",
            "priority": 1,
        },
        {
            "command": "python -m pytest test_canary_target.py -q",
            "kind": "test",
            "priority": 2,
        },
    ]
    ranked = rank_verification_commands(commands, path=metrics_path)
    selected = str(ranked[0].get("command") or "") if ranked else ""
    return {
        "schema": "octopus.core_loop_ranking_canary.v1",
        "ok": selected.startswith("python -m pytest"),
        "selected_command": selected,
        "ranked_commands": [str(item.get("command") or "") for item in ranked],
    }


def _execution_probe(workspace: Path) -> dict[str, Any]:
    plan = {
        "schema": "octopus.verification_plan.v1",
        "workspace": str(workspace),
        "commands": [
            {
                "command": "python -m pytest test_canary_target.py -q",
                "target": "test_canary_target.py",
                "kind": "test",
                "priority": 1,
            }
        ],
    }
    item = run_highest_priority_verification(
        plan,
        sandbox_policy={"type": "workspaceWrite", "networkAccess": False},
    )
    metrics = summarize_auto_verifier_metrics(limit=50)
    decisions = recent_auto_verifier_decisions(limit=5)
    selected = decisions[-1].get("selected_command") if decisions else ""
    ok = (
        item is not None
        and item.exit_code == 0
        and str(item.status) == "completed"
    )
    telemetry_ok = (
        metrics.get("total", 0) >= 1
        and bool(decisions)
        and str(selected).startswith("python -m pytest")
    )
    return {
        "schema": "octopus.core_loop_execution_canary.v1",
        "ok": ok,
        "telemetry_ok": telemetry_ok,
        "selected_command": selected,
        "metric_total": metrics.get("total", 0),
        "decision_count": len(decisions),
        "exit_code": item.exit_code if item is not None else None,
        "status": str(item.status) if item is not None else "",
    }


def _drift_probe(*, metrics_path: Path, review_queue_path: Path) -> dict[str, Any]:
    for ok in (False, False, True):
        record_auto_verifier_metric(
            command="python -m ruff check drift.py",
            kind="lint",
            ok=ok,
            exit_code=0 if ok else 1,
            duration_ms=150,
            target="drift.py",
            path=metrics_path,
        )
    result = queue_verifier_drift_backlog(
        metrics_path=metrics_path,
        review_queue_path=review_queue_path,
    )
    queue = ReviewQueue(review_queue_path)
    rows = queue.items(target_bucket="experiment_backlog", limit=20)["items"]
    return {
        "schema": "octopus.core_loop_drift_canary.v1",
        "ok": int(result.get("created") or 0) >= 1
        and any(str(row.get("candidate_kind") or "").startswith("verifier_drift:") for row in rows),
        "created": result.get("created"),
        "updated": result.get("updated"),
        "backlog_count": len(rows),
    }


def _repair_route_probe(*, ledger_path: Path, review_queue_path: Path) -> dict[str, Any]:
    quality = compute_repair_route_quality(
        ledger_path=ledger_path,
        review_queue_path=review_queue_path,
    )
    gate = quality.get("quality_gate") if isinstance(quality.get("quality_gate"), dict) else {}
    return {
        "schema": "octopus.core_loop_repair_route_canary.v1",
        "ok": quality.get("ready") is True
        and gate.get("ready") is True
        and not gate.get("blockers"),
        "score": quality.get("score"),
        "blockers": gate.get("blockers") or [],
        "total_failures": quality.get("total_failures"),
    }


def _repair_route_promotion_probe(
    *,
    ledger_path: Path,
    review_queue_path: Path,
) -> dict[str, Any]:
    ledger = ProposalLedger(ledger_path)
    for index in range(2):
        ledger.propose(
            kind="turn_failure",
            description=f"canary repeated verifier drift {index}",
            proposer="core_coding_loop_canary",
            metadata={
                "failure_source": "verifier_drift",
                "primary_repair_route": "verifier_drift_repair",
                "goal": "stabilize repeated verifier drift",
                "has_code_changes": True,
                "verification_count": 1,
                "failed_verifications": [{"command": "python -m pytest tests/test_canary.py -q"}],
                "verification_plan": {
                    "schema": "octopus.verification_plan.v1",
                    "commands": [
                        {
                            "kind": "test",
                            "command": "python -m pytest tests/test_canary.py -q",
                            "reason": "reproduce repeated verifier drift before promotion",
                        }
                    ],
                },
            },
        )
    queued = queue_repair_route_promotion_candidates(
        ledger_path=ledger_path,
        review_queue_path=review_queue_path,
    )
    quality = compute_repair_route_quality(
        ledger_path=ledger_path,
        review_queue_path=review_queue_path,
    )
    items = queued.get("items") if isinstance(queued.get("items"), list) else []
    item = items[0] if items and isinstance(items[0], dict) else {}
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    candidate = (
        metadata.get("promotion_candidate")
        if isinstance(metadata.get("promotion_candidate"), dict)
        else {}
    )
    gate = (
        candidate.get("promotion_gate")
        if isinstance(candidate.get("promotion_gate"), dict)
        else {}
    )
    quality_gate = quality.get("quality_gate") if isinstance(quality.get("quality_gate"), dict) else {}
    ok = (
        int(queued.get("created") or 0) >= 1
        and item.get("candidate_kind") == "repair_route_promotion:verifier_drift_repair"
        and metadata.get("requires_passing_rerun") is True
        and metadata.get("passing_rerun_attached") is False
        and gate.get("requires_operator_review") is True
        and gate.get("requires_passing_rerun") is True
        and gate.get("blocks_auto_promotion") is True
        and quality.get("ready") is False
        and "pending_repair_route_review" in (quality_gate.get("blockers") or [])
    )
    return {
        "schema": "octopus.core_loop_repair_route_promotion_canary.v1",
        "ok": ok,
        "created": queued.get("created"),
        "candidate_kind": item.get("candidate_kind", ""),
        "requires_passing_rerun": metadata.get("requires_passing_rerun") is True,
        "passing_rerun_attached": metadata.get("passing_rerun_attached") is True,
        "promotion_gate": gate,
        "quality_ready_after_queue": quality.get("ready") is True,
        "quality_blockers_after_queue": quality_gate.get("blockers") or [],
    }


def _next_actions(checks: dict[str, bool]) -> list[str]:
    actions = []
    if checks.get("history_ranking_selects_stable_verifier") is not True:
        actions.append("Fix history-aware verifier ranking canary.")
    if checks.get("sandboxed_verifier_executes") is not True:
        actions.append("Fix sandboxed verifier execution canary.")
    if checks.get("decision_and_metric_recorded") is not True:
        actions.append("Record verifier decisions and metrics during canary execution.")
    if checks.get("verifier_drift_routes_to_backlog") is not True:
        actions.append("Route verifier drift alerts into repair backlog.")
    if checks.get("repair_route_quality_gate_clean") is not True:
        actions.append("Keep repair-route quality gate clean for the canary ledger.")
    if checks.get("repair_route_promotion_evidence_queued") is not True:
        actions.append("Queue repair-route promotion evidence for repeated verifier drift.")
    if not actions:
        actions.append("Core coding loop canary is verified.")
    return actions


__all__ = [
    "SCHEMA",
    "run_core_coding_loop_canary",
]
