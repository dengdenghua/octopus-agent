from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from runtime.core.cerebrum.react_types import ReActResult
from runtime.execution.loops.controller import LoopController
from runtime.execution.loops.models import (
    LoopPolicy,
    LoopRun,
    VerifierFinding,
    VerifierResult,
)
from runtime.execution.loops.store import LoopRunStore
from runtime.memory.diagnostics.trace_store import AgentTraceStore
from runtime.platform.runtime_policy.workspaces import WorkspaceManager
from runtime.sensing.gateway.agent_trace_router import create_agent_trace_router


class _DenyIdentityStore:
    def verify_api_key(self, token: str):
        return None


class _StubVerifierRegistry:
    def __init__(self, results: list[VerifierResult]) -> None:
        self._results = list(results)

    def run(self, profile: str, workspace_path: str) -> VerifierResult:
        return self._results.pop(0)


def _client_with_trace(
    tmp_path: Path,
    *,
    include_write_diagnostic: bool = False,
) -> TestClient:
    fake_api_key = "sk-kimi-" + ("A" * 32)
    secret_action = "exec_shell(" + json.dumps({
        "command": (
            'curl -H "Authorization: Bearer '
            f'{fake_api_key}" https://x'
        ),
    }) + ")"
    store = AgentTraceStore(tmp_path / "agent_trace.sqlite")
    store.record_event(
        thread_id="thread-1",
        task_id="task-1",
        agent_id="agent-a",
        event_type="RUN_STARTED",
        payload={"phase": "start"},
    )
    store.record_event(
        thread_id="thread-2",
        task_id="task-2",
        agent_id="agent-b",
        event_type="RUN_FINISHED",
        payload={"phase": "end"},
    )
    store.record_token_usage(
        task_id="task-2",
        thread_id="thread-2",
        agent_id="agent-b",
        model="gpt-other",
        input_tokens=90,
        output_tokens=10,
    )
    store.record_approval(
        thread_id="thread-1",
        tool_name="exec_shell",
        tool_call_id="call-1",
        decision="approved",
    )
    store.record_checkpoint(
        task_id="task-1",
        checkpoint_type="react",
        state={
            "current_phase": "implementation",
            "messages_snapshot": [{"content": "secret message body"}],
            "steps_snapshot": [
                {
                    "iteration": 1,
                    "action": secret_action,
                    "observation": "sent report to ops@example.com",
                },
            ],
            "working_set_snapshot": [{"path": "runtime/memory/trace_store.py"}],
        },
        iteration=2,
        summary="resume here",
    )
    store.record_resume_request(
        thread_id="thread-1",
        task_id="task-1",
        checkpoint_id=1,
        status="pending",
        intent={
            "checkpoint_id": 1,
            "requires_confirmation": True,
            "messages_snapshot": ["secret message body"],
        },
    )
    store.record_token_usage(
        task_id="task-1",
        thread_id="thread-1",
        agent_id="agent-a",
        model="gpt-test",
        input_tokens=10,
        output_tokens=5,
    )
    store.record_task_run_started(
        task_id="turn-1",
        thread_id="thread-1",
        turn_id="turn-1",
        agent_id="agent-a",
        title="Build report",
        mode="code",
    )
    store.record_event(
        thread_id="thread-1",
        turn_id="turn-1",
        task_id="turn-1",
        agent_id="agent-a",
        event_type="TOOL_CALL_START",
        item_id="call-read-1",
        payload={"tool": "read_file", "tool_call_id": "call-read-1"},
    )
    store.record_approval(
        thread_id="thread-1",
        turn_id="turn-1",
        task_id="turn-1",
        agent_id="agent-a",
        tool_name="read_file",
        tool_call_id="call-read-1",
        decision="approved",
        reason="safe read",
        metadata={
            "trust_gateway": {
                "schema": "octopus.trust_decision.v1",
                "source": "risk_policy",
                "action": "allow",
                "risk": {
                    "level": "low",
                    "categories": ["local_read"],
                    "reason": "local_read",
                    "requires_approval": False,
                },
                "risk_policy": {
                    "low": "allow",
                    "medium": "ask",
                    "high": "ask",
                    "critical": "confirm",
                },
            }
        },
    )
    store.record_event(
        thread_id="thread-1",
        turn_id="turn-1",
        task_id="turn-1",
        agent_id="agent-a",
        event_type="TOOL_CALL_END",
        item_id="call-read-1",
        payload={"tool": "read_file", "tool_call_id": "call-read-1", "status": "success"},
    )
    if include_write_diagnostic:
        store.record_event(
            thread_id="thread-1",
            turn_id="turn-1",
            task_id="turn-1",
            agent_id="agent-a",
            event_type="TOOL_CALL_START",
            item_id="call-write-1",
            payload={
                "tool": "write_text_file",
                "tool_call_id": "call-write-1",
                "input_preview": {"path": "runtime/example.py"},
            },
        )
        store.record_event(
            thread_id="thread-1",
            turn_id="turn-1",
            task_id="turn-1",
            agent_id="agent-a",
            event_type="TOOL_CALL_END",
            item_id="call-write-1",
            payload={
                "tool": "write_text_file",
                "tool_call_id": "call-write-1",
                "status": "success",
                "output_preview": (
                    "ok\n\n[post-write diagnostics]\n"
                    "ruff diagnostics (example.py):\n"
                    "E999 SyntaxError: expected ':'"
                ),
            },
        )
    store.record_task_run_finished(
        task_id="turn-1",
        thread_id="thread-1",
        turn_id="turn-1",
        agent_id="agent-a",
        status="completed",
        summary="done",
    )
    app = FastAPI()
    app.include_router(
        create_agent_trace_router(
            store=store,
            experience_ledger_path=tmp_path / "experience_ledger.json",
            review_queue_path=tmp_path / "review_queue.json",
            promotion_audit_path=tmp_path / "promotion_audit.json",
            proposal_ledger_path=tmp_path / "proposal_ledger.jsonl",
        )
    )
    return TestClient(app)


def test_trace_promotion_apply_requires_auth_when_identity_store_exists(
    tmp_path: Path,
) -> None:
    store = AgentTraceStore(tmp_path / "agent_trace.sqlite")
    app = FastAPI()
    app.include_router(
        create_agent_trace_router(
            store=store,
            experience_ledger_path=tmp_path / "experience_ledger.json",
            review_queue_path=tmp_path / "review_queue.json",
            promotion_audit_path=tmp_path / "promotion_audit.json",
            proposal_ledger_path=tmp_path / "proposal_ledger.jsonl",
            identity_store=_DenyIdentityStore(),
        )
    )
    client = TestClient(app)

    response = client.post("/api/agent-trace/review-queue/promotions/apply", json={})

    assert response.status_code == 401
    assert response.json()["detail"] == "missing Authorization: Bearer <token>"


def test_trace_stats_exposes_ledger_totals(tmp_path: Path) -> None:
    client = _client_with_trace(tmp_path)

    response = client.get("/api/agent-trace/stats")

    assert response.status_code == 200
    data = response.json()
    assert data["events"] == 6
    assert data["approvals"] == 2
    assert data["checkpoints"] == 1
    assert data["token_totals"]["input_tokens"] == 100


def test_trace_stats_supports_thread_scope(tmp_path: Path) -> None:
    client = _client_with_trace(tmp_path)

    response = client.get("/api/agent-trace/stats", params={"thread_id": "thread-1"})

    assert response.status_code == 200
    data = response.json()
    assert data["events"] == 5
    assert data["approvals"] == 2
    assert data["checkpoints"] == 0
    assert data["token_totals"]["input_tokens"] == 10


def test_trace_events_support_runtime_filters(tmp_path: Path) -> None:
    client = _client_with_trace(tmp_path)

    response = client.get(
        "/api/agent-trace/events",
        params={"thread_id": "thread-1", "event_type": "RUN_STARTED"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["limit"] == 100
    assert len(data["events"]) == 1
    assert data["events"][0]["task_id"] == "task-1"
    assert data["events"][0]["payload"] == {"phase": "start"}


def test_trace_task_runs_are_readable_as_run_summaries(tmp_path: Path) -> None:
    client = _client_with_trace(tmp_path)

    listing = client.get(
        "/api/agent-trace/task-runs",
        params={"thread_id": "thread-1", "status": "completed"},
    )
    detail = client.get("/api/agent-trace/task-runs/turn-1")
    missing = client.get("/api/agent-trace/task-runs/missing")

    assert listing.status_code == 200
    runs = listing.json()["task_runs"]
    assert [run["task_id"] for run in runs] == ["turn-1"]
    assert runs[0]["status"] == "completed"
    assert runs[0]["title"] == "Build report"
    assert runs[0]["tool_calls_started"] == 1
    assert detail.status_code == 200
    assert detail.json()["task_run"]["summary"] == "done"
    assert len(detail.json()["task_run"]["events"]) == 4
    assert missing.status_code == 404


def test_trace_task_run_review_endpoint_exposes_replay_and_candidates(
    tmp_path: Path,
) -> None:
    client = _client_with_trace(tmp_path)

    response = client.get("/api/agent-trace/task-runs/turn-1/review")
    replay_case_response = client.get("/api/agent-trace/task-runs/turn-1/replay-case")
    replay_evaluation_response = client.get(
        "/api/agent-trace/task-runs/turn-1/replay-evaluation",
    )
    replay_cases_response = client.get(
        "/api/agent-trace/replay-cases",
        params={"thread_id": "thread-1", "status": "completed"},
    )
    replay_evaluations_response = client.get(
        "/api/agent-trace/replay-evaluations",
        params={"thread_id": "thread-1", "status": "completed"},
    )
    replay_gate_response = client.get(
        "/api/agent-trace/replay-gate",
        params={"thread_id": "thread-1", "status": "completed"},
    )
    missing = client.get("/api/agent-trace/task-runs/missing/review")
    missing_replay_case = client.get("/api/agent-trace/task-runs/missing/replay-case")
    missing_replay_evaluation = client.get(
        "/api/agent-trace/task-runs/missing/replay-evaluation",
    )

    assert response.status_code == 200
    review = response.json()["review"]
    assert review["schema"] == "octopus.task_run_review.v1"
    assert review["task_id"] == "turn-1"
    assert review["status"] == "completed"
    assert review["replay"]["schema"] == "octopus.task_run_replay.v1"
    assert len(review["replay"]["fingerprint"]) == 16
    assert review["replay"]["case_id"] == f"task-run:{review['replay']['fingerprint']}"
    assert review["replay"]["replayable"] is True
    assert review["resume"]["available"] is False
    assert review["summary"]["tool_calls_started"] == 1
    assert any(
        finding["type"] == "success_pattern"
        for finding in review["findings"]
    )
    assert any(
        item["kind"] == "success_pattern"
        for item in review["learning_candidates"]
    )
    assert replay_case_response.status_code == 200
    replay_case = replay_case_response.json()["replay_case"]
    assert replay_case["schema"] == "octopus.task_run_replay_case.v1"
    assert replay_case["case_id"] == review["replay"]["case_id"]
    assert replay_case["expectations"]["status"] == "completed"
    assert replay_case["safety"]["raw_checkpoint_state_included"] is False
    assert replay_evaluation_response.status_code == 200
    replay_evaluation = replay_evaluation_response.json()["evaluation"]
    assert replay_evaluation["schema"] == "octopus.task_run_replay_evaluation.v1"
    assert replay_evaluation["case_id"] == replay_case["case_id"]
    assert replay_evaluation["passed"] is True
    assert replay_evaluation["score"] == 1.0
    assert replay_cases_response.status_code == 200
    replay_cases = replay_cases_response.json()
    assert replay_cases["schema"] == "octopus.task_run_replay_case_corpus.v1"
    assert replay_cases["total"] == 1
    assert replay_cases["cases"][0]["case_id"] == replay_case["case_id"]
    assert replay_evaluations_response.status_code == 200
    replay_evaluations = replay_evaluations_response.json()
    assert replay_evaluations["schema"] == "octopus.task_run_replay_evaluation_corpus.v1"
    assert replay_evaluations["passed"] == 1
    assert replay_evaluations["failed"] == 0
    assert replay_evaluations["evaluations"][0]["case_id"] == replay_case["case_id"]
    assert replay_gate_response.status_code == 200
    replay_gate = replay_gate_response.json()
    assert replay_gate["schema"] == "octopus.replay_gate.v1"
    assert replay_gate["passed"] is True
    assert replay_gate["summary"]["total"] == 1
    assert missing.status_code == 404
    assert missing_replay_case.status_code == 404
    assert missing_replay_evaluation.status_code == 404


def test_trace_task_run_review_can_commit_to_experience_ledger(
    tmp_path: Path,
) -> None:
    client = _client_with_trace(tmp_path)

    committed = client.post("/api/agent-trace/task-runs/turn-1/review/commit")
    listed = client.get("/api/agent-trace/experience-ledger")
    # Use today's date as the week anchor so commit timestamps
    # (== "now") fall inside the half-open [week_start, week_start+7)
    # window regardless of which day of the week the test runs.
    from datetime import UTC, datetime
    today_iso = datetime.now(UTC).date().isoformat()
    summary = client.get(
        "/api/agent-trace/experience-ledger/weekly-summary",
        params={"week_start": today_iso},
    )
    quality = client.get("/api/agent-trace/experience-ledger/quality-summary")
    missing = client.post("/api/agent-trace/task-runs/missing/review/commit")

    assert committed.status_code == 200
    assert committed.json()["commit"]["created"] == 2
    assert listed.status_code == 200
    records = listed.json()["records"]
    assert {record["kind"] for record in records} == {
        "success_pattern",
        "backlog_candidate",
    }
    assert all(
        record["metadata"]["replay"]["case_id"].startswith("task-run:")
        for record in records
    )
    assert all(
        len(record["metadata"]["replay"]["fingerprint"]) == 16
        for record in records
    )
    assert all(
        record["metadata"]["citation"]["schema"]
        == "octopus.experience_replay_citation.v1"
        for record in records
    )
    assert all(
        record["metadata"]["citation"]["replay_case_id"].startswith("task-run:")
        for record in records
    )
    assert summary.status_code == 200
    assert summary.json()["record_count"] == 2
    assert quality.status_code == 200
    assert quality.json()["schema"] == "octopus.experience_memory_quality_summary.v1"
    assert quality.json()["active_count"] == 2
    assert missing.status_code == 404


def test_trace_task_run_review_can_enter_review_queue(
    tmp_path: Path,
) -> None:
    client = _client_with_trace(tmp_path)

    queued = client.post("/api/agent-trace/task-runs/turn-1/review/queue")
    listed = client.get("/api/agent-trace/review-queue", params={"status": "pending"})
    summary = client.get("/api/agent-trace/review-queue/summary")
    missing = client.post("/api/agent-trace/task-runs/missing/review/queue")

    assert queued.status_code == 200
    assert queued.json()["queue"]["created"] == 2
    assert listed.status_code == 200
    items = listed.json()["items"]
    assert len(items) == 2
    assert {item["target_bucket"] for item in items} == {
        "experience",
        "experiment_backlog",
    }
    assert all(
        item["metadata"]["replay"]["case_id"].startswith("task-run:")
        for item in items
    )
    assert all(item["metadata"]["resume"]["available"] is False for item in items)
    assert summary.status_code == 200
    assert summary.json()["pending_count"] == 2
    assert missing.status_code == 404


def test_trace_review_queue_item_can_be_decided(tmp_path: Path) -> None:
    client = _client_with_trace(tmp_path)
    client.post("/api/agent-trace/task-runs/turn-1/review/queue")
    items = client.get("/api/agent-trace/review-queue").json()["items"]
    item_id = items[0]["id"]

    decided = client.post(
        f"/api/agent-trace/review-queue/{item_id}/decision",
        json={
            "action": "promoted",
            "reason": "Useful enough to keep.",
            "promoted_to": "experience",
        },
    )
    summary = client.get("/api/agent-trace/review-queue/summary")
    missing = client.post(
        "/api/agent-trace/review-queue/missing/decision",
        json={"action": "archived"},
    )
    invalid = client.post(
        f"/api/agent-trace/review-queue/{item_id}/decision",
        json={"action": "unknown"},
    )

    assert decided.status_code == 200
    assert decided.json()["item"]["status"] == "promoted"
    assert decided.json()["item"]["promoted_to"] == "experience"
    assert summary.status_code == 200
    assert summary.json()["pending_count"] == 1
    assert summary.json()["by_status"] == {"pending": 1, "promoted": 1}
    assert missing.status_code == 404
    assert invalid.status_code == 400


def test_trace_review_queue_promotions_can_plan_apply_and_audit(
    tmp_path: Path,
) -> None:
    client = _client_with_trace(tmp_path)
    client.post("/api/agent-trace/task-runs/turn-1/review/queue")
    items = client.get("/api/agent-trace/review-queue").json()["items"]
    item_id = items[0]["id"]
    client.post(
        f"/api/agent-trace/review-queue/{item_id}/decision",
        json={
            "action": "promoted",
            "reason": "Ready to apply.",
            "promoted_to": "experience",
        },
    )

    plan = client.post("/api/agent-trace/review-queue/promotions/plan")
    applied = client.post("/api/agent-trace/review-queue/promotions/apply")
    audit = client.get("/api/agent-trace/review-queue/promotions/audit")
    second_plan = client.post("/api/agent-trace/review-queue/promotions/plan")
    ledger = client.get("/api/agent-trace/experience-ledger")

    assert plan.status_code == 200
    assert plan.json()["dry_run"] is True
    assert plan.json()["applicable"] == 1
    assert plan.json()["replay_gate"]["schema"] == "octopus.replay_gate.v1"
    assert plan.json()["replay_gate"]["passed"] is True
    assert applied.status_code == 200
    assert applied.json()["applied"] == 1
    assert applied.json()["replay_gate"]["passed"] is True
    assert applied.json()["override_replay_gate"] is False
    assert audit.status_code == 200
    assert audit.json()["total"] == 1
    assert audit.json()["records"][0]["review_queue_item_id"] == item_id
    assert second_plan.status_code == 200
    assert second_plan.json()["skipped"] == 1
    assert ledger.status_code == 200
    assert ledger.json()["total"] == 1
    promoted_record = ledger.json()["records"][0]
    assert promoted_record["metadata"]["replay"]["case_id"].startswith("task-run:")
    assert len(promoted_record["metadata"]["replay"]["fingerprint"]) == 16


def test_trace_review_queue_promotion_apply_requires_replay_gate_or_override(
    tmp_path: Path,
) -> None:
    client = _client_with_trace(tmp_path)
    client.post("/api/agent-trace/task-runs/turn-1/review/queue")
    items = client.get("/api/agent-trace/review-queue").json()["items"]
    item_id = items[0]["id"]
    client.post(
        f"/api/agent-trace/review-queue/{item_id}/decision",
        json={
            "action": "promoted",
            "reason": "Ready to apply.",
            "promoted_to": "experience",
        },
    )

    blocked = client.post(
        "/api/agent-trace/review-queue/promotions/apply",
        json={"min_replay_cases": 2},
    )
    audit_after_block = client.get("/api/agent-trace/review-queue/promotions/audit")
    override_missing_reason = client.post(
        "/api/agent-trace/review-queue/promotions/apply",
        json={"min_replay_cases": 2, "override_replay_gate": True},
    )
    overridden = client.post(
        "/api/agent-trace/review-queue/promotions/apply",
        json={
            "min_replay_cases": 2,
            "override_replay_gate": True,
            "override_reason": "Reviewed blocked replay gate and accepting risk.",
            "override_actor": "operator-test",
        },
    )
    audit_after_override = client.get("/api/agent-trace/review-queue/promotions/audit")
    audit_summary = client.get("/api/agent-trace/review-queue/promotions/audit/summary")

    assert blocked.status_code == 409
    detail = blocked.json()["detail"]
    assert detail["message"] == "replay gate did not pass"
    assert detail["replay_gate"]["passed"] is False
    assert detail["replay_gate"]["reason"] == "insufficient_cases:1<2"
    assert audit_after_block.json()["total"] == 0
    assert override_missing_reason.status_code == 400
    assert (
        override_missing_reason.json()["detail"]["message"]
        == "override_reason is required when replay gate is blocked"
    )
    assert overridden.status_code == 200
    assert overridden.json()["applied"] == 1
    assert overridden.json()["replay_gate"]["passed"] is False
    assert overridden.json()["override_replay_gate"] is True
    override_audit = audit_after_override.json()["records"][0]
    assert override_audit["decision_context"]["replay_gate"]["passed"] is False
    assert override_audit["decision_context"]["override_replay_gate"] is True
    assert (
        override_audit["decision_context"]["override_reason"]
        == "Reviewed blocked replay gate and accepting risk."
    )
    assert override_audit["decision_context"]["override_actor"] == "local_operator"
    assert override_audit["agent_id"] == "agent-a"
    assert audit_summary.status_code == 200
    assert audit_summary.json()["override_count"] == 1
    assert audit_summary.json()["gate_blocked_override_count"] == 1
    assert audit_summary.json()["gate_failed_count"] == 1


def test_policy_review_promotion_cannot_override_missing_replay_evidence(
    tmp_path: Path,
) -> None:
    from runtime.memory.learning.review_queue import ReviewQueue

    store = AgentTraceStore(tmp_path / "agent_trace.sqlite")
    review_queue_path = tmp_path / "review_queue.json"
    queue = ReviewQueue(review_queue_path)
    queued = queue.upsert_item(
        source="trust_denials",
        source_kind="tool_policy_denial",
        candidate_kind="policy_review",
        priority="P1",
        target_bucket="policy_review",
        title="Review repeated denials for exec_shell",
        text="Tool exec_shell was denied repeatedly.",
        source_task_ids=["missing-task"],
    )
    queue.decide(
        queued["items"][0]["id"],
        action="promoted",
        promoted_to="policy_review",
    )
    app = FastAPI()
    app.include_router(
        create_agent_trace_router(
            store=store,
            review_queue_path=review_queue_path,
            promotion_audit_path=tmp_path / "promotion_audit.json",
            proposal_ledger_path=tmp_path / "proposal_ledger.jsonl",
        )
    )
    client = TestClient(app)

    try:
        response = client.post(
            "/api/agent-trace/review-queue/promotions/apply",
            json={
                "override_replay_gate": True,
                "override_reason": "Accepting the policy risk.",
            },
        )
    finally:
        store.close()

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["message"] == "policy_review promotion requires replay evidence"
    assert detail["replay_gate"]["passed"] is False


def test_policy_review_rule_drafts_endpoint_returns_verified_drafts(
    tmp_path: Path,
) -> None:
    from runtime.safety.evolution.proposal_ledger import ProposalLedger

    proposal_ledger_path = tmp_path / "proposal_ledger.jsonl"
    ProposalLedger(proposal_ledger_path).propose(
        kind="review_queue_policy_review",
        description="Review repeated denials for exec_shell",
        metadata={
            "review_queue_item_id": "rq_1",
            "item": {
                "title": "Review repeated denials for exec_shell",
                "text": "Tool exec_shell was denied repeatedly.",
                "metadata": {
                    "tool_name": "exec_shell",
                    "latest_denial": {
                        "tool_name": "exec_shell",
                        "reason": "no destructive shell",
                    },
                },
            },
            "evidence": {
                "schema": "octopus.policy_review_promotion_evidence.v1",
                "replay": {
                    "case_id": "task-run:abc123",
                    "fingerprint": "abc123",
                    "replayable": True,
                },
                "replay_gate": {"passed": True},
            },
        },
    )
    app = FastAPI()
    app.include_router(
        create_agent_trace_router(
            store=AgentTraceStore(tmp_path / "agent_trace.sqlite"),
            proposal_ledger_path=proposal_ledger_path,
        )
    )
    client = TestClient(app)

    response = client.get("/api/agent-trace/policy-review/rule-drafts")

    assert response.status_code == 200
    body = response.json()
    assert body["schema"] == "octopus.policy_review_rule_drafts.v1"
    assert body["total"] == 1
    assert body["verified"] == 1
    draft = body["drafts"][0]
    assert draft["signed_payload"]["rule"]["tool"] == "exec_shell"
    assert draft["signed_payload"]["rule"]["reason"] == "no destructive shell"


def test_policy_review_rule_draft_install_endpoint_requires_confirmation_and_audits(
    tmp_path: Path,
) -> None:
    from runtime.safety.approval.approval_policy_store import load_policy
    from runtime.safety.evolution.proposal_ledger import ProposalLedger

    proposal_ledger_path = tmp_path / "proposal_ledger.jsonl"
    approval_policy_path = tmp_path / "permissions.json"
    audit_path = tmp_path / "promotion_audit.json"
    ProposalLedger(proposal_ledger_path).propose(
        kind="review_queue_policy_review",
        description="Review repeated denials for exec_shell",
        metadata={
            "review_queue_item_id": "rq_1",
            "item": {
                "title": "Review repeated denials for exec_shell",
                "text": "Tool exec_shell was denied repeatedly.",
                "metadata": {
                    "tool_name": "exec_shell",
                    "latest_denial": {
                        "tool_name": "exec_shell",
                        "reason": "no destructive shell",
                    },
                },
            },
            "evidence": {
                "schema": "octopus.policy_review_promotion_evidence.v1",
                "replay_gate": {"passed": True},
            },
        },
    )
    app = FastAPI()
    app.include_router(
        create_agent_trace_router(
            store=AgentTraceStore(tmp_path / "agent_trace.sqlite"),
            proposal_ledger_path=proposal_ledger_path,
            approval_policy_path=approval_policy_path,
            promotion_audit_path=audit_path,
        )
    )
    client = TestClient(app)
    draft_id = client.get(
        "/api/agent-trace/policy-review/rule-drafts",
    ).json()["drafts"][0]["draft_id"]

    missing_confirm = client.post(
        "/api/agent-trace/policy-review/rule-drafts/install",
        json={"draft_id": draft_id},
    )
    installed = client.post(
        "/api/agent-trace/policy-review/rule-drafts/install",
        json={"draft_id": draft_id, "confirm_install": True},
    )
    audit = client.get("/api/agent-trace/review-queue/promotions/audit")

    assert missing_confirm.status_code == 400
    assert missing_confirm.json()["detail"] == "confirm_install=true is required"
    assert installed.status_code == 200
    assert installed.json()["installed"] is True
    assert installed.json()["rule"]["tool"] == "exec_shell"
    rules = load_policy(approval_policy_path).rules
    assert len(rules) == 1
    assert rules[0].effect == "deny"
    assert rules[0].tool == "exec_shell"
    assert audit.json()["total"] == 1
    assert audit.json()["records"][0]["event_type"] == "policy_review_rule_install"
    assert audit.json()["records"][0]["target"] == "approval_policy"


def test_trace_promotion_audit_export_includes_verified_chain(
    tmp_path: Path,
) -> None:
    from runtime.safety.evolution.governance_audit import (
        append_governance_audit_event,
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
    client = _client_with_trace(tmp_path)

    response = client.get("/api/agent-trace/review-queue/promotions/audit/export")
    body = response.json()

    assert response.status_code == 200
    assert body["schema"] == "octopus.governance_audit_export.v1"
    assert body["integrity"]["ok"] is True
    assert body["chain"]["line_count"] == 1
    assert body["audit"]["records"][0]["event_type"] == "topology_policy_block"


def test_trace_task_run_process_timeline_merges_review_and_ledger(
    tmp_path: Path,
) -> None:
    client = _client_with_trace(tmp_path, include_write_diagnostic=True)

    client.post("/api/agent-trace/task-runs/turn-1/review/commit")
    response = client.get("/api/agent-trace/task-runs/turn-1/process-timeline")
    missing = client.get("/api/agent-trace/task-runs/missing/process-timeline")

    assert response.status_code == 200
    timeline = response.json()["timeline"]
    assert timeline["schema"] == "octopus.process_timeline.v1"
    assert timeline["task_id"] == "turn-1"
    assert timeline["overview"]["status"] == "completed"
    assert timeline["overview"]["approval_count"] == 1
    assert timeline["overview"]["experience_record_count"] == 2
    assert timeline["overview"]["post_write_diagnostic_count"] == 1
    lanes = {node["lane"] for node in timeline["timeline"]}
    assert {"execution", "permission", "verification", "review", "learning"}.issubset(lanes)
    kinds = {node["kind"] for node in timeline["timeline"]}
    assert "approval" in kinds
    assert "post_write_diagnostic" in kinds
    assert "success_pattern" in kinds
    assert "experience_record" in kinds
    diagnostic = next(
        node for node in timeline["timeline"]
        if node["kind"] == "post_write_diagnostic"
    )
    assert diagnostic["status"] == "failed"
    assert diagnostic["tool"] == "write_text_file"
    assert "ruff diagnostics" in diagnostic["summary"]
    read_file = next(item for item in timeline["capabilities"] if item["tool"] == "read_file")
    assert read_file["risk"]["level"] == "low"
    assert timeline["safety"]["raw_messages_included"] is False
    assert missing.status_code == 404


def test_trace_approvals_tokens_and_latest_checkpoint_are_readable(tmp_path: Path) -> None:
    client = _client_with_trace(tmp_path)

    approvals = client.get("/api/agent-trace/approvals", params={"thread_id": "thread-1"})
    tokens = client.get("/api/agent-trace/token-usage", params={"task_id": "task-1"})
    checkpoints = client.get("/api/agent-trace/checkpoints", params={"task_id": "task-1"})
    checkpoint = client.get(
        "/api/agent-trace/checkpoints/latest",
        params={"task_id": "task-1", "checkpoint_type": "react"},
    )
    missing = client.get(
        "/api/agent-trace/checkpoints/latest",
        params={"task_id": "unknown"},
    )

    assert approvals.json()["approvals"][0]["decision"] == "approved"
    assert tokens.json()["usage"][0]["model"] == "gpt-test"
    assert checkpoints.json()["checkpoints"][0]["checkpoint_type"] == "react"
    assert checkpoint.status_code == 200
    assert checkpoint.json()["checkpoint"]["state"]["current_phase"] == "implementation"
    assert missing.status_code == 404


def test_trace_trust_denials_summary_is_readable(tmp_path: Path) -> None:
    store = AgentTraceStore(tmp_path / "agent_trace.sqlite")
    store.record_approval(
        thread_id="thread-1",
        turn_id="turn-deny",
        task_id="task-1",
        agent_id="agent-a",
        tool_name="exec_shell",
        tool_call_id="call-deny",
        decision="rejected",
        reason="no destructive shell",
        metadata={
            "trust_gateway": {
                "schema": "octopus.trust_decision.v1",
                "tool_name": "exec_shell",
                "source": "static_policy",
                "action": "deny",
                "reason": "no destructive shell",
                "risk": {"level": "critical"},
                "risk_policy": {},
                "static_decision": "deny",
            }
        },
    )
    app = FastAPI()
    app.include_router(create_agent_trace_router(store=store))
    client = TestClient(app)

    try:
        response = client.get(
            "/api/agent-trace/trust-denials/summary",
            params={"thread_id": "thread-1"},
        )
    finally:
        store.close()

    assert response.status_code == 200
    data = response.json()
    assert data["schema"] == "octopus.trust_denial_summary.v1"
    assert data["total"] == 1
    assert data["by_tool"] == {"exec_shell": 1}
    assert data["by_action"] == {"deny": 1}
    assert data["recent"][0]["reason"] == "no destructive shell"


def test_repeated_trust_denials_can_enter_review_queue(tmp_path: Path) -> None:
    store = AgentTraceStore(tmp_path / "agent_trace.sqlite")
    for call_id in ("call-deny-1", "call-deny-2"):
        store.record_approval(
            thread_id="thread-1",
            turn_id=f"turn-{call_id}",
            task_id="task-1",
            agent_id="agent-a",
            tool_name="exec_shell",
            tool_call_id=call_id,
            decision="rejected",
            reason="no destructive shell",
            metadata={
                "trust_gateway": {
                    "schema": "octopus.trust_decision.v1",
                    "tool_name": "exec_shell",
                    "source": "static_policy",
                    "action": "deny",
                    "reason": "no destructive shell",
                    "risk": {"level": "critical"},
                    "risk_policy": {},
                    "static_decision": "deny",
                }
            },
        )
    review_queue_path = tmp_path / "review_queue.json"
    app = FastAPI()
    app.include_router(
        create_agent_trace_router(
            store=store,
            review_queue_path=review_queue_path,
        )
    )
    client = TestClient(app)

    try:
        first = client.get(
            "/api/agent-trace/trust-denials/summary",
            params={
                "thread_id": "thread-1",
                "queue_repeated": "true",
                "min_occurrences": 2,
            },
        )
        second = client.get(
            "/api/agent-trace/trust-denials/summary",
            params={
                "thread_id": "thread-1",
                "queue_repeated": "true",
                "min_occurrences": 2,
            },
        )
        listed = client.get(
            "/api/agent-trace/review-queue",
            params={"target_bucket": "policy_review"},
        )
    finally:
        store.close()

    assert first.status_code == 200
    assert first.json()["queue"]["created"] == 1
    assert second.json()["queue"]["updated"] == 1
    items = listed.json()["items"]
    assert len(items) == 1
    assert items[0]["source"] == "trust_denials"
    assert items[0]["candidate_kind"] == "policy_review"
    assert items[0]["title"] == "Review repeated denials for exec_shell"
    assert items[0]["occurrences"] == 2


def test_trace_resume_proposal_is_sanitized(tmp_path: Path) -> None:
    client = _client_with_trace(tmp_path)
    checkpoints = client.get("/api/agent-trace/checkpoints", params={"task_id": "task-1"})
    checkpoint_id = checkpoints.json()["checkpoints"][0]["id"]

    response = client.get(f"/api/agent-trace/checkpoints/{checkpoint_id}/resume-proposal")
    missing = client.get("/api/agent-trace/checkpoints/99999/resume-proposal")

    assert response.status_code == 200
    proposal = response.json()["proposal"]
    assert proposal["checkpoint"]["id"] == checkpoint_id
    assert proposal["recovery_hints"]["phase"] == "implementation"
    assert proposal["resume_plan"]["steps"][1] == "Continue from iteration 3."
    assert proposal["safety"]["raw_state_included"] is False
    assert "secret message body" not in str(proposal)
    assert "sk-kimi-" not in str(proposal)
    assert "ops@example.com" not in str(proposal)
    assert "[REDACTED:api_key]" in str(proposal)
    assert "[REDACTED:email]" in str(proposal)
    assert missing.status_code == 404


def test_trace_resume_proposals_supports_thread_scope(tmp_path: Path) -> None:
    client = _client_with_trace(tmp_path)

    response = client.get("/api/agent-trace/resume-proposals", params={"task_id": "task-1"})

    assert response.status_code == 200
    data = response.json()
    assert data["limit"] == 5
    assert len(data["proposals"]) == 1
    proposal = data["proposals"][0]
    assert proposal["checkpoint"]["type"] == "react"
    assert proposal["recovery_hints"]["phase"] == "implementation"
    assert "secret message body" not in str(data)
    assert "sk-kimi-" not in str(data)
    assert "ops@example.com" not in str(data)


def test_trace_router_exposes_loop_run_checkpoints_and_resume_proposals(tmp_path: Path) -> None:
    trace = AgentTraceStore(tmp_path / "agent_trace.sqlite")
    loop_store = LoopRunStore(tmp_path / "loop_runs.json")
    run = LoopRun(
        owner_id="alice",
        goal="Fix remaining verifier failures",
        thread_id="thread-loop",
        workspace_path=str(tmp_path / "workspace"),
        policy=LoopPolicy(max_attempts=1, max_iterations=2),
    )
    loop_store.create(run)

    def runner(*, stack, intent, agent, model=None, max_iterations=0, thread_id=None):
        return ReActResult(final_answer="not fixed", success=False)

    controller = LoopController(
        store=loop_store,
        stack=SimpleNamespace(name="stack"),
        workspace_manager=WorkspaceManager(tmp_path / "workspaces"),
        verifier_registry=_StubVerifierRegistry(
            [
                VerifierResult(
                    profile="python_repo_patch",
                    kind="python",
                    passed=False,
                    findings=[
                        VerifierFinding(
                            name="pytest",
                            passed=False,
                            exit_code=1,
                            stderr="1 failing test remains",
                        )
                    ],
                    summary="failed checks: pytest",
                )
            ]
        ),
        trace_store=trace,
        react_runner=runner,
    )
    controller.execute(run.run_id)

    app = FastAPI()
    app.include_router(create_agent_trace_router(store=trace))
    client = TestClient(app)

    checkpoints = client.get(
        "/api/agent-trace/checkpoints",
        params={"task_id": run.run_id, "checkpoint_type": "loop_run"},
    )
    proposals = client.get(
        "/api/agent-trace/resume-proposals",
        params={"task_id": run.run_id, "checkpoint_type": "loop_run"},
    )
    task_run = client.get(f"/api/agent-trace/task-runs/{run.run_id}")
    review = client.get(f"/api/agent-trace/task-runs/{run.run_id}/review")
    replay_case = client.get(f"/api/agent-trace/task-runs/{run.run_id}/replay-case")
    replay_evaluation = client.get(
        f"/api/agent-trace/task-runs/{run.run_id}/replay-evaluation",
    )

    assert checkpoints.status_code == 200
    assert len(checkpoints.json()["checkpoints"]) == 1
    assert checkpoints.json()["checkpoints"][0]["checkpoint_type"] == "loop_run"
    assert checkpoints.json()["checkpoints"][0]["state"]["current_phase"] == "failed"

    assert proposals.status_code == 200
    assert len(proposals.json()["proposals"]) == 1
    assert proposals.json()["proposals"][0]["checkpoint"]["type"] == "loop_run"
    assert proposals.json()["proposals"][0]["recovery_hints"]["phase"] == "failed"

    assert task_run.status_code == 200
    assert task_run.json()["task_run"]["status"] == "failed"
    assert task_run.json()["task_run"]["latest_checkpoint"]["type"] == "loop_run"

    assert review.status_code == 200
    review_body = review.json()["review"]
    assert review_body["status"] == "failed"
    assert any(
        step["kind"] == "loop_attempt"
        for step in review_body["replay"]["steps"]
    )
    assert review_body["resume"]["source"] == "trace_store"
    assert review_body["resume"]["latest_checkpoint"]["trace_checkpoint_id"] > 0

    assert replay_case.status_code == 200
    assert replay_case.json()["replay_case"]["expectations"]["status"] == "failed"
    assert replay_case.json()["replay_case"]["resume"]["source"] == "trace_store"

    assert replay_evaluation.status_code == 200
    assert replay_evaluation.json()["evaluation"]["passed"] is True


def test_trace_router_review_prefers_loop_checkpoint_under_newer_generic_checkpoint(
    tmp_path: Path,
) -> None:
    trace = AgentTraceStore(tmp_path / "agent_trace.sqlite")
    loop_store = LoopRunStore(tmp_path / "loop_runs.json")
    run = LoopRun(
        owner_id="alice",
        goal="Keep loop review stable under extra checkpoints",
        thread_id="thread-loop",
        workspace_path=str(tmp_path / "workspace"),
        policy=LoopPolicy(max_attempts=1, max_iterations=2),
    )
    loop_store.create(run)

    def runner(*, stack, intent, agent, model=None, max_iterations=0, thread_id=None):
        return ReActResult(final_answer="not fixed", success=False)

    controller = LoopController(
        store=loop_store,
        stack=SimpleNamespace(name="stack"),
        workspace_manager=WorkspaceManager(tmp_path / "workspaces"),
        verifier_registry=_StubVerifierRegistry(
            [
                VerifierResult(
                    profile="python_repo_patch",
                    kind="python",
                    passed=False,
                    findings=[
                        VerifierFinding(
                            name="pytest",
                            passed=False,
                            exit_code=1,
                            stderr="1 failing test remains",
                        )
                    ],
                    summary="failed checks: pytest",
                )
            ]
        ),
        trace_store=trace,
        react_runner=runner,
    )
    controller.execute(run.run_id)

    loop_checkpoint = trace.latest_checkpoint(
        task_id=run.run_id,
        checkpoint_type="loop_run",
    )
    assert loop_checkpoint is not None

    generic_checkpoint_id = trace.record_checkpoint(
        task_id=run.run_id,
        checkpoint_type="react",
        state={
            "current_phase": "postmortem",
            "messages_snapshot": [],
            "steps_snapshot": [{"iteration": 9, "action": "summarize_failure()"}],
            "working_set_snapshot": [],
        },
        thread_id="thread-loop",
        turn_id=run.run_id,
        agent_id="observer",
        iteration=9,
        summary="observer note",
    )

    app = FastAPI()
    app.include_router(create_agent_trace_router(store=trace))
    client = TestClient(app)

    task_run = client.get(f"/api/agent-trace/task-runs/{run.run_id}")
    review = client.get(f"/api/agent-trace/task-runs/{run.run_id}/review")
    replay_case = client.get(f"/api/agent-trace/task-runs/{run.run_id}/replay-case")
    replay_evaluation = client.get(
        f"/api/agent-trace/task-runs/{run.run_id}/replay-evaluation",
    )

    assert task_run.status_code == 200
    assert task_run.json()["task_run"]["latest_checkpoint"]["id"] == generic_checkpoint_id
    assert task_run.json()["task_run"]["latest_checkpoint"]["type"] == "react"

    assert review.status_code == 200
    review_body = review.json()["review"]
    assert review_body["status"] == "failed"
    assert any(
        step["kind"] == "loop_attempt"
        for step in review_body["replay"]["steps"]
    )
    assert review_body["summary"]["trace_checkpoint_id"] == loop_checkpoint["id"]
    assert review_body["resume"]["latest_checkpoint"]["trace_checkpoint_id"] == loop_checkpoint["id"]

    assert replay_case.status_code == 200
    assert replay_case.json()["replay_case"]["resume"]["source"] == "trace_store"

    assert replay_evaluation.status_code == 200
    assert replay_evaluation.json()["evaluation"]["passed"] is True


def test_trace_resume_requests_are_readable_and_sanitized(tmp_path: Path) -> None:
    client = _client_with_trace(tmp_path)

    response = client.get(
        "/api/agent-trace/resume-requests",
        params={"thread_id": "thread-1", "status": "pending"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["limit"] == 100
    assert len(data["requests"]) == 1
    request = data["requests"][0]
    assert request["status"] == "pending"
    assert request["intent"]["checkpoint_id"] == 1
    assert request["intent"]["requires_confirmation"] is True
    assert "secret message body" not in str(data)


def test_create_app_mounts_agent_trace_router(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from runtime.platform.ui import create_app

    monkeypatch.setenv("OCTOPUS_DATA_DIR", str(tmp_path / "data"))
    app = create_app(journal_path=tmp_path / "data" / "events.jsonl")
    client = TestClient(app)

    response = client.get("/api/agent-trace/stats")

    assert response.status_code == 200
    assert response.json()["events"] == 0
