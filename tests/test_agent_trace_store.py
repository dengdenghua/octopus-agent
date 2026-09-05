from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from runtime.memory.diagnostics.trace_store import AgentTraceStore
from runtime.memory.journal import JSONLJournal
from runtime.safety.approval.approval_gate import ApprovalRequest
from runtime.sensing.gateway.realtime_cerebrum import GatewayApprovalProvider


@pytest.fixture
def store(tmp_path: Path) -> AgentTraceStore:
    trace = AgentTraceStore(tmp_path / "trace.sqlite")
    yield trace
    trace.close()


def test_old_trace_schema_migrates_before_store_becomes_ready(tmp_path: Path) -> None:
    from runtime.memory.diagnostics._trace_store_schema import _SCHEMA

    path = tmp_path / "old-trace.sqlite"
    conn = sqlite3.connect(path)
    try:
        # Representative pre-tenant schema: AgentTraceStore must add ownership
        # columns before it creates scope indexes or serves any request.
        old_schema = "\n".join(
            line
            for line in _SCHEMA.splitlines()
            if "tenant_id" not in line and "owner_actor_id" not in line
        )
        conn.executescript(old_schema)
        conn.commit()
    finally:
        conn.close()

    trace = AgentTraceStore(path)
    try:
        status = trace.schema_status()
        assert status == {
            "ready": True,
            "version": 2,
            "requiredVersion": 2,
            "missingColumns": {},
        }
    finally:
        trace.close()


def test_records_messages_events_approvals_checkpoints_and_token_usage(
    store: AgentTraceStore,
) -> None:
    message_id = store.record_message(
        thread_id="thread-1",
        role="user",
        content="build the report",
        turn_id="turn-1",
        agent_id="agent-a",
        metadata={"source": "chat"},
    )
    event_id = store.record_event(
        thread_id="thread-1",
        event_type="TOOL_CALL_START",
        payload={"tool": "web_search"},
        turn_id="turn-1",
        item_id="item-1",
        agent_id="agent-a",
    )
    approval_id = store.record_approval(
        thread_id="thread-1",
        tool_name="exec_shell",
        tool_call_id="call-1",
        decision="approved",
        reason="user accepted",
        args_preview="pytest tests/test_agent_trace_store.py",
        turn_id="turn-1",
        agent_id="agent-a",
    )
    checkpoint_id = store.record_checkpoint(
        task_id="task-1",
        checkpoint_type="react",
        state={"iteration": 3, "phase": "coding"},
        thread_id="thread-1",
        turn_id="turn-1",
        agent_id="agent-a",
        iteration=3,
        summary="implemented trace store",
    )
    token_id = store.record_token_usage(
        task_id="task-1",
        model="gpt-test",
        input_tokens=100,
        output_tokens=40,
        thinking_tokens=7,
        cached_tokens=20,
        cost_usd=0.0123,
        thread_id="thread-1",
        turn_id="turn-1",
        agent_id="agent-a",
        iteration=3,
        is_local=False,
    )

    assert message_id > 0
    assert event_id > 0
    assert approval_id > 0
    assert checkpoint_id > 0
    assert token_id > 0

    assert store.messages(thread_id="thread-1")[0]["content"] == "build the report"
    assert store.events(thread_id="thread-1", event_type="TOOL_CALL_START")[0]["payload"] == {
        "tool": "web_search",
    }
    assert store.approvals(thread_id="thread-1")[0]["decision"] == "approved"
    assert store.checkpoints(thread_id="thread-1")[0]["summary"] == "implemented trace store"
    assert store.latest_checkpoint(task_id="task-1")["state"]["iteration"] == 3
    assert store.token_usage(task_id="task-1")[0]["thinking_tokens"] == 7

    stats = store.stats()
    assert stats["messages"] == 1
    assert stats["events"] == 1
    assert stats["approvals"] == 1
    assert stats["checkpoints"] == 1
    assert stats["token_usage"] == 1
    assert stats["token_totals"]["input_tokens"] == 100
    assert stats["token_totals"]["output_tokens"] == 40
    assert stats["token_totals"]["thinking_tokens"] == 7
    assert stats["token_totals"]["cached_tokens"] == 20


def test_checkpoint_returns_newest_by_iteration_then_id(store: AgentTraceStore) -> None:
    store.record_checkpoint(
        task_id="task-1",
        checkpoint_type="react",
        state={"iteration": 1},
        iteration=1,
    )
    store.record_checkpoint(
        task_id="task-1",
        checkpoint_type="react",
        state={"iteration": 5},
        iteration=5,
    )
    store.record_checkpoint(
        task_id="task-1",
        checkpoint_type="task",
        state={"iteration": 99},
        iteration=99,
    )

    latest_react = store.latest_checkpoint(task_id="task-1", checkpoint_type="react")
    assert latest_react["state"] == {"iteration": 5}

    latest_any = store.latest_checkpoint(task_id="task-1")
    assert latest_any["checkpoint_type"] == "task"

    checkpoints = store.checkpoints(task_id="task-1", checkpoint_type="react")
    assert [checkpoint["iteration"] for checkpoint in checkpoints] == [1, 5]


def test_resume_proposal_is_sanitized(store: AgentTraceStore) -> None:
    fake_api_key = "sk-kimi-" + ("A" * 32)
    secret_action = (
        "exec_shell("
        + json.dumps(
            {
                "command": (f"pytest tests/test_agent_trace_store.py -q --token {fake_api_key}"),
            }
        )
        + ")"
    )
    checkpoint_id = store.record_checkpoint(
        task_id="task-1",
        checkpoint_type="react",
        thread_id="thread-1",
        agent_id="agent-a",
        iteration=3,
        summary="implemented trace store",
        state={
            "current_phase": "implementation",
            "progress_summary": "trace store wired",
            "messages_snapshot": [{"role": "user", "content": "secret message body"}],
            "steps_snapshot": [
                {
                    "iteration": 1,
                    "action": 'read_file({"path": "runtime/memory/trace_store.py"})',
                    "observation": "read 120 lines",
                },
                {
                    "iteration": 2,
                    "action": secret_action,
                    "observation": "36 passed; notified ops@example.com",
                },
            ],
            "working_set_snapshot": [
                {"path": "runtime/memory/trace_store.py"},
                {"path": "runtime/sensing/siphon/agent_trace_router.py"},
            ],
        },
    )

    proposal = store.resume_proposal(checkpoint_id)

    assert proposal is not None
    assert proposal["checkpoint"]["id"] == checkpoint_id
    assert proposal["checkpoint"]["type"] == "react"
    assert proposal["recovery_hints"]["phase"] == "implementation"
    assert proposal["recovery_hints"]["message_count"] == 1
    assert proposal["recovery_hints"]["step_count"] == 2
    assert proposal["recovery_hints"]["recent_tool_calls"] == [
        {
            "iteration": 1,
            "tool": "read_file",
            "input_preview": '{"path": "runtime/memory/trace_store.py"}',
            "observation_preview": "read 120 lines",
        },
        {
            "iteration": 2,
            "tool": "exec_shell",
            "input_preview": (
                '{"command": "pytest tests/test_agent_trace_store.py -q '
                '--token [REDACTED:api_key]"}'
            ),
            "observation_preview": "36 passed; notified [REDACTED:email]",
        },
    ]
    assert proposal["resume_plan"]["steps"][1] == "Continue from iteration 4."
    assert proposal["safety"]["raw_state_included"] is False
    assert proposal["safety"]["raw_message_snapshots_included"] is False
    assert "secret message body" not in str(proposal)
    assert "sk-kimi-" not in str(proposal)
    assert "ops@example.com" not in str(proposal)
    assert store.resume_proposal(99999) is None


def test_resume_proposals_returns_sanitized_candidates(store: AgentTraceStore) -> None:
    for iteration in range(1, 4):
        store.record_checkpoint(
            task_id="task-1",
            checkpoint_type="react",
            thread_id="thread-1",
            iteration=iteration,
            summary=f"checkpoint {iteration}",
            state={
                "current_phase": "implementation",
                "messages_snapshot": [{"content": f"secret {iteration}"}],
                "steps_snapshot": [{"iteration": iteration}],
            },
        )

    proposals = store.resume_proposals(thread_id="thread-1", limit=2, offset=1)

    assert [proposal["checkpoint"]["iteration"] for proposal in proposals] == [2, 3]
    assert proposals[0]["resume_plan"]["steps"][1] == "Continue from iteration 3."
    assert "secret" not in str(proposals)


def test_resume_requests_track_pending_confirmed_and_consumed_state(
    store: AgentTraceStore,
) -> None:
    request_id = store.record_resume_request(
        thread_id="thread-1",
        checkpoint_id=7,
        task_id="task-1",
        status="pending",
        intent={
            "schema": "octopus.resume_intent.v1",
            "requires_confirmation": True,
            "checkpoint_id": 7,
            "progress": "private message body",
            "messages_snapshot": ["message body"],
        },
    )

    pending = store.latest_pending_resume_request(thread_id="thread-1")

    assert request_id > 0
    assert pending is not None
    assert pending["id"] == request_id
    assert pending["status"] == "pending"
    assert pending["intent"]["checkpoint_id"] == 7
    assert pending["intent"]["requires_confirmation"] is True
    assert "message body" not in str(pending)

    assert (
        store.confirm_resume_request(
            thread_id="thread-1",
            checkpoint_id=7,
            confirmation_text="确认恢复 checkpoint #7",
        )
        is not None
    )
    confirmed = store.resume_requests(thread_id="thread-1")[0]
    assert confirmed["status"] == "confirmed"
    assert confirmed["confirmed_at"] is not None
    assert confirmed["intent"]["requires_confirmation"] is False
    assert confirmed["intent"]["confirmed"] is True
    assert "message body" not in str(confirmed)

    assert store.consume_resume_request(request_id) is not None
    consumed = store.resume_requests(thread_id="thread-1")[0]
    assert consumed["status"] == "consumed"
    assert consumed["consumed_at"] is not None
    assert store.latest_pending_resume_request(thread_id="thread-1") is None


def test_filters_by_thread_task_and_agent(store: AgentTraceStore) -> None:
    store.record_event(
        thread_id="thread-a",
        task_id="task-a",
        agent_id="agent-a",
        event_type="RUN_STARTED",
        payload={},
    )
    store.record_event(
        thread_id="thread-b",
        task_id="task-b",
        agent_id="agent-b",
        event_type="RUN_STARTED",
        payload={},
    )

    assert len(store.events(thread_id="thread-a")) == 1
    assert len(store.events(task_id="task-b")) == 1
    assert len(store.events(agent_id="agent-a")) == 1
    assert store.events(thread_id="missing") == []


def test_task_run_read_model_aggregates_events_tools_tokens_and_approvals(
    store: AgentTraceStore,
) -> None:
    store.record_task_run_started(
        task_id="turn-1",
        thread_id="thread-1",
        turn_id="turn-1",
        agent_id="agent-a",
        title="Build report",
        goal="Build the weekly report",
        mode="code",
        ts="2026-06-07T00:00:00+00:00",
    )
    store.record_event(
        thread_id="thread-1",
        turn_id="turn-1",
        task_id="turn-1",
        agent_id="agent-a",
        event_type="TOOL_CALL_START",
        payload={"tool": "read_file"},
        ts="2026-06-07T00:00:01+00:00",
    )
    store.record_event(
        thread_id="thread-1",
        turn_id="turn-1",
        task_id="turn-1",
        agent_id="agent-a",
        event_type="TOOL_CALL_END",
        payload={"tool": "read_file", "status": "success"},
        ts="2026-06-07T00:00:02+00:00",
    )
    store.record_event(
        thread_id="thread-1",
        turn_id="turn-1",
        task_id="turn-1",
        agent_id="agent-a",
        event_type="TOOL_CALL_END",
        payload={"tool": "exec_shell", "status": "error"},
        ts="2026-06-07T00:00:03+00:00",
    )
    store.record_approval(
        thread_id="thread-1",
        turn_id="turn-1",
        task_id="turn-1",
        agent_id="agent-a",
        tool_name="exec_shell",
        tool_call_id="call-1",
        decision="rejected",
    )
    store.record_checkpoint(
        task_id="turn-1",
        thread_id="thread-1",
        turn_id="turn-1",
        agent_id="agent-a",
        checkpoint_type="react",
        state={"phase": "verify"},
        iteration=2,
    )
    store.record_token_usage(
        task_id="turn-1",
        thread_id="thread-1",
        turn_id="turn-1",
        agent_id="agent-a",
        model="gpt-test",
        input_tokens=100,
        output_tokens=50,
        cost_usd=0.25,
    )
    store.record_task_run_finished(
        task_id="turn-1",
        thread_id="thread-1",
        turn_id="turn-1",
        agent_id="agent-a",
        status="failed",
        reason="verification_failed",
        summary="tests failed",
        ts="2026-06-07T00:00:04+00:00",
    )

    run = store.task_run("turn-1")

    assert run is not None
    assert run["status"] == "failed"
    assert run["title"] == "Build report"
    assert run["goal"] == "Build the weekly report"
    assert run["mode"] == "code"
    assert run["summary"] == "tests failed"
    assert run["reason"] == "verification_failed"
    assert run["tool_calls_started"] == 1
    assert run["tool_calls_finished"] == 2
    assert run["tool_errors"] == 1
    assert run["tool_names"] == ["exec_shell", "read_file"]
    assert run["approval_count"] == 1
    assert run["approval_rejections"] == 1
    assert run["checkpoint_count"] == 1
    assert run["latest_checkpoint"]["id"] is not None
    assert run["latest_checkpoint"]["type"] == "react"
    assert run["latest_checkpoint"]["integrity"]["resume_safe"] is True
    assert run["latest_checkpoint"]["safety"]["raw_state_included"] is False
    assert run["token_totals"]["input_tokens"] == 100
    assert run["token_totals"]["output_tokens"] == 50
    assert run["token_totals"]["cost_usd"] == 0.25
    assert len(run["events"]) == 5


def test_task_run_replay_accepts_normalized_tool_trace_payload(
    store: AgentTraceStore,
) -> None:
    store.record_task_run_started(
        task_id="turn-normalized",
        thread_id="thread-1",
        turn_id="turn-normalized",
        title="Inspect file",
        mode="code",
        ts="2026-06-07T00:00:00+00:00",
    )
    store.record_event(
        thread_id="thread-1",
        turn_id="turn-normalized",
        task_id="turn-normalized",
        event_type="TOOL_CALL_START",
        item_id="call-read",
        payload={
            "id": "call-read",
            "name": "read_file",
            "input": {"path": "README.md"},
            "origin": "react_compat",
        },
        ts="2026-06-07T00:00:01+00:00",
    )
    store.record_event(
        thread_id="thread-1",
        turn_id="turn-normalized",
        task_id="turn-normalized",
        event_type="TOOL_CALL_END",
        item_id="call-read",
        payload={
            "id": "call-read",
            "name": "read_file",
            "status": "success",
            "is_error": False,
            "output": {"ok": True, "chars": 42},
            "origin": "react_compat",
        },
        ts="2026-06-07T00:00:02+00:00",
    )
    store.record_task_run_finished(
        task_id="turn-normalized",
        thread_id="thread-1",
        turn_id="turn-normalized",
        status="completed",
        summary="done",
        ts="2026-06-07T00:00:03+00:00",
    )

    run = store.task_run("turn-normalized")
    review = store.task_run_review("turn-normalized")
    replay_case = store.task_run_replay_case("turn-normalized")
    replay_evaluation = store.evaluate_task_run_replay_case("turn-normalized")
    corpus = store.task_run_replay_cases(thread_id="thread-1", status="completed")
    evaluation_corpus = store.evaluate_task_run_replay_cases(
        thread_id="thread-1",
        status="completed",
    )
    replay_gate = store.replay_gate(thread_id="thread-1", status="completed")
    strict_replay_gate = store.replay_gate(
        thread_id="thread-1",
        status="completed",
        min_cases=2,
    )

    assert run is not None
    assert run["tool_names"] == ["read_file"]
    assert run["tool_errors"] == 0
    assert review is not None
    assert review["replay"]["schema"] == "octopus.task_run_replay.v1"
    assert len(review["replay"]["fingerprint"]) == 16
    assert review["replay"]["case_id"] == f"task-run:{review['replay']['fingerprint']}"
    steps = review["replay"]["steps"]
    assert steps[1]["tool_call_id"] == "call-read"
    assert steps[1]["tool"] == "read_file"
    assert steps[1]["input_preview"] == '{"path": "README.md"}'
    assert steps[2]["tool_call_id"] == "call-read"
    assert steps[2]["output_preview"] == '{"chars": 42, "ok": true}'
    assert replay_case is not None
    assert replay_case["schema"] == "octopus.task_run_replay_case.v1"
    assert replay_case["case_id"] == review["replay"]["case_id"]
    assert replay_case["replay"]["steps"] == review["replay"]["steps"]
    assert replay_case["expectations"]["status"] == "completed"
    assert replay_case["safety"]["raw_messages_included"] is False
    assert corpus["schema"] == "octopus.task_run_replay_case_corpus.v1"
    assert corpus["total"] == 1
    assert corpus["cases"][0]["case_id"] == replay_case["case_id"]
    assert replay_evaluation is not None
    assert replay_evaluation["schema"] == "octopus.task_run_replay_evaluation.v1"
    assert replay_evaluation["case_id"] == replay_case["case_id"]
    assert replay_evaluation["passed"] is True
    assert replay_evaluation["score"] == 1.0
    assert {check["name"] for check in replay_evaluation["checks"]} >= {
        "fingerprint",
        "step_count",
        "status_expectation",
        "tool_error_count",
        "task_boundary",
        "safety",
    }
    assert evaluation_corpus["schema"] == "octopus.task_run_replay_evaluation_corpus.v1"
    assert evaluation_corpus["passed"] == 1
    assert evaluation_corpus["failed"] == 0
    assert evaluation_corpus["evaluations"][0]["case_id"] == replay_case["case_id"]
    assert replay_gate["schema"] == "octopus.replay_gate.v1"
    assert replay_gate["passed"] is True
    assert replay_gate["summary"]["total"] == 1
    assert replay_gate["reason"] == "all_replay_evaluations_passed"
    assert strict_replay_gate["passed"] is False
    assert strict_replay_gate["reason"] == "insufficient_cases:1<2"


def test_connection_lost_approval_counts_as_rejection(store: AgentTraceStore) -> None:
    # The approval lifecycle change added 'connection_lost' as a
    # distinct decision label; the task-run rollup must count it among
    # rejections alongside rejected/timeout/error, not silently drop it.
    store.record_task_run_started(
        task_id="turn-cl",
        thread_id="thread-1",
        ts="2026-06-07T00:00:00+00:00",
    )
    for decision in ("rejected", "timeout", "connection_lost", "error", "approved"):
        store.record_approval(
            thread_id="thread-1",
            turn_id="turn-cl",
            task_id="turn-cl",
            agent_id="agent-a",
            tool_name="exec_shell",
            tool_call_id=f"call-{decision}",
            decision=decision,
        )
    store.record_task_run_finished(
        task_id="turn-cl",
        thread_id="thread-1",
        turn_id="turn-cl",
        agent_id="agent-a",
        status="failed",
        ts="2026-06-07T00:00:04+00:00",
    )

    run = store.task_run("turn-cl")
    assert run is not None
    assert run["approval_count"] == 5
    # rejected + timeout + connection_lost + error = 4 (approved excluded)
    assert run["approval_rejections"] == 4


def test_task_runs_lists_latest_runs_and_filters_status(store: AgentTraceStore) -> None:
    store.record_task_run_started(
        task_id="task-old",
        thread_id="thread-1",
        ts="2026-06-07T00:00:00+00:00",
    )
    store.record_task_run_started(
        task_id="task-new",
        thread_id="thread-1",
        ts="2026-06-07T00:01:00+00:00",
    )
    store.record_task_run_finished(
        task_id="task-new",
        thread_id="thread-1",
        status="completed",
        ts="2026-06-07T00:02:00+00:00",
    )

    runs = store.task_runs(thread_id="thread-1")
    completed = store.task_runs(thread_id="thread-1", status="completed")

    assert [run["task_id"] for run in runs] == ["task-new", "task-old"]
    assert [run["task_id"] for run in completed] == ["task-new"]


def test_task_runs_limit_bounds_task_run_materialization(
    store: AgentTraceStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for i in range(80):
        task_id = f"task-{i:03d}"
        hour = i // 60
        minute = i % 60
        store.record_task_run_started(
            task_id=task_id,
            thread_id="thread-1",
            ts=f"2026-06-07T{hour:02d}:{minute:02d}:00+00:00",
        )
        store.record_task_run_finished(
            task_id=task_id,
            thread_id="thread-1",
            status="completed",
            ts=f"2026-06-07T{hour:02d}:{minute:02d}:01+00:00",
        )

    original_task_run = store.task_run
    calls: list[str] = []

    def counted_task_run(task_id: str):
        calls.append(task_id)
        return original_task_run(task_id)

    monkeypatch.setattr(store, "task_run", counted_task_run)

    runs = store.task_runs(thread_id="thread-1", limit=5, offset=10)

    assert len(runs) == 5
    assert len(calls) == 5
    assert [run["task_id"] for run in runs] == [
        "task-069",
        "task-068",
        "task-067",
        "task-066",
        "task-065",
    ]


def test_task_run_review_extracts_findings_replay_and_learning_candidates(
    store: AgentTraceStore,
) -> None:
    store.record_task_run_started(
        task_id="turn-review",
        thread_id="thread-1",
        turn_id="turn-review",
        title="Fix failing test",
        goal="Fix the failing pytest case",
        mode="code",
        ts="2026-06-07T00:00:00+00:00",
    )
    store.record_event(
        thread_id="thread-1",
        turn_id="turn-review",
        task_id="turn-review",
        event_type="TOOL_CALL_START",
        item_id="call-1",
        payload={
            "tool_call_id": "call-1",
            "tool_name": "exec_shell",
            "input_preview": "pytest tests/test_x.py",
        },
        ts="2026-06-07T00:00:01+00:00",
    )
    store.record_approval(
        thread_id="thread-1",
        turn_id="turn-review",
        task_id="turn-review",
        tool_name="exec_shell",
        tool_call_id="call-1",
        decision="approved",
        reason="accept",
        metadata={
            "trust_gateway": {
                "schema": "octopus.trust_decision.v1",
                "source": "risk_policy",
                "risk": {"level": "high", "categories": ["shell_execution"]},
                "action": "ask",
            }
        },
    )
    store.record_event(
        thread_id="thread-1",
        turn_id="turn-review",
        task_id="turn-review",
        event_type="TOOL_CALL_END",
        item_id="call-1",
        payload={
            "tool_call_id": "call-1",
            "tool_name": "exec_shell",
            "status": "error",
            "output_preview": "AssertionError: expected 1 got 2",
        },
        ts="2026-06-07T00:00:02+00:00",
    )
    store.record_task_run_finished(
        task_id="turn-review",
        thread_id="thread-1",
        turn_id="turn-review",
        status="failed",
        reason="tests_failed",
        ts="2026-06-07T00:00:03+00:00",
    )

    review = store.task_run_review("turn-review")

    assert review is not None
    assert review["schema"] == "octopus.task_run_review.v1"
    assert review["status"] == "failed"
    assert review["score"] < 0.5
    finding_types = [finding["type"] for finding in review["findings"]]
    assert "terminal_status" in finding_types
    assert "tool_error" in finding_types
    assert "high_risk_approval" in finding_types
    assert review["replay"]["replayable"] is True
    assert len(review["replay"]["fingerprint"]) == 16
    assert review["replay"]["steps"][1]["approval"]["risk_level"] == "high"
    assert review["resume"]["available"] is False
    assert any(item["kind"] == "failure_pattern" for item in review["learning_candidates"])
    assert review["backlog_candidates"][0]["priority"] == "P0"


def test_task_run_review_exposes_resume_readiness_without_raw_checkpoint_state(
    store: AgentTraceStore,
) -> None:
    store.record_task_run_started(
        task_id="turn-resume",
        thread_id="thread-1",
        turn_id="turn-resume",
        mode="code",
        ts="2026-06-07T00:00:00+00:00",
    )
    checkpoint_id = store.record_checkpoint(
        task_id="turn-resume",
        thread_id="thread-1",
        turn_id="turn-resume",
        agent_id="agent-a",
        checkpoint_type="react",
        iteration=3,
        summary="ready to verify",
        state={
            "current_phase": "verification",
            "progress_summary": "ran focused tests",
            "messages_snapshot": [
                {"role": "user", "content": "private user text"},
                {"role": "assistant", "content": "private assistant text"},
            ],
            "steps_snapshot": [
                {
                    "iteration": 3,
                    "thought": "verify",
                    "action": "shell(command='pytest tests/test_x.py')",
                    "observation": "2 passed",
                }
            ],
            "working_set_snapshot": [{"path": "tests/test_x.py"}],
        },
    )
    store.record_task_run_finished(
        task_id="turn-resume",
        thread_id="thread-1",
        turn_id="turn-resume",
        status="interrupted",
        ts="2026-06-07T00:00:02+00:00",
    )

    review = store.task_run_review("turn-resume")

    assert review is not None
    resume = review["resume"]
    assert resume["available"] is True
    assert resume["source"] == "trace_store"
    assert resume["latest_checkpoint"]["id"] == checkpoint_id
    assert resume["latest_checkpoint"]["integrity"]["continue_from_iteration"] == 4
    assert resume["latest_checkpoint"]["recovery_hints"]["phase"] == "verification"
    rendered = repr(resume)
    assert "private user text" not in rendered
    assert "messages_snapshot" not in rendered
    assert resume["safety"]["raw_message_snapshots_included"] is False


def test_task_run_review_uses_loop_native_review_when_latest_checkpoint_is_loop_run(
    store: AgentTraceStore,
    tmp_path: Path,
) -> None:
    from runtime.core.cerebrum.react_types import ReActResult
    from runtime.execution.loops.controller import LoopController
    from runtime.execution.loops.models import (
        LoopPolicy,
        LoopRun,
        VerifierFinding,
        VerifierResult,
    )
    from runtime.execution.loops.store import LoopRunStore
    from runtime.platform.runtime_policy.workspaces import WorkspaceManager

    class _StubVerifierRegistry:
        def __init__(self, results: list[VerifierResult]) -> None:
            self._results = list(results)

        def run(self, profile: str, workspace_path: str) -> VerifierResult:
            return self._results.pop(0)

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
        trace_store=store,
        react_runner=runner,
    )
    controller.execute(run.run_id)

    review = store.task_run_review(run.run_id)
    replay_case = store.task_run_replay_case(run.run_id)
    replay_evaluation = store.evaluate_task_run_replay_case(run.run_id)

    assert review is not None
    assert review["status"] == "failed"
    assert review["resume"]["source"] == "trace_store"
    assert review["resume"]["latest_checkpoint"]["trace_checkpoint_id"] > 0
    assert any(step["kind"] == "loop_attempt" for step in review["replay"]["steps"])
    assert any(finding["type"] == "tool_error" for finding in review["findings"])
    assert any(item["kind"] == "failure_pattern" for item in review["learning_candidates"])
    assert (
        review["summary"]["trace_checkpoint_id"]
        == review["resume"]["latest_checkpoint"]["trace_checkpoint_id"]
    )

    assert replay_case is not None
    assert replay_case["expectations"]["status"] == "failed"
    assert replay_case["resume"]["source"] == "trace_store"
    assert replay_evaluation is not None
    assert replay_evaluation["passed"] is True


def test_task_run_review_prefers_loop_checkpoint_even_if_newer_generic_checkpoint_exists(
    store: AgentTraceStore,
    tmp_path: Path,
) -> None:
    from runtime.core.cerebrum.react_types import ReActResult
    from runtime.execution.loops.controller import LoopController
    from runtime.execution.loops.models import (
        LoopPolicy,
        LoopRun,
        VerifierFinding,
        VerifierResult,
    )
    from runtime.execution.loops.store import LoopRunStore
    from runtime.platform.runtime_policy.workspaces import WorkspaceManager

    class _StubVerifierRegistry:
        def __init__(self, results: list[VerifierResult]) -> None:
            self._results = list(results)

        def run(self, profile: str, workspace_path: str) -> VerifierResult:
            return self._results.pop(0)

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
        trace_store=store,
        react_runner=runner,
    )
    controller.execute(run.run_id)

    loop_checkpoint = store.latest_checkpoint(
        task_id=run.run_id,
        checkpoint_type="loop_run",
    )
    assert loop_checkpoint is not None

    generic_checkpoint_id = store.record_checkpoint(
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

    task_run = store.task_run(run.run_id)
    review = store.task_run_review(run.run_id)
    replay_case = store.task_run_replay_case(run.run_id)
    replay_evaluation = store.evaluate_task_run_replay_case(run.run_id)

    assert task_run is not None
    assert task_run["latest_checkpoint"]["id"] == generic_checkpoint_id
    assert task_run["latest_checkpoint"]["type"] == "react"

    assert review is not None
    assert review["status"] == "failed"
    assert any(step["kind"] == "loop_attempt" for step in review["replay"]["steps"])
    assert review["summary"]["trace_checkpoint_id"] == loop_checkpoint["id"]
    assert review["resume"]["latest_checkpoint"]["trace_checkpoint_id"] == loop_checkpoint["id"]

    assert replay_case is not None
    assert replay_case["resume"]["source"] == "trace_store"
    assert replay_evaluation is not None
    assert replay_evaluation["passed"] is True


def test_stats_can_be_scoped_to_thread_task_and_agent(store: AgentTraceStore) -> None:
    store.record_message(thread_id="thread-a", role="user", content="a")
    store.record_message(thread_id="thread-b", role="user", content="b")
    store.record_event(
        thread_id="thread-a",
        task_id="task-a",
        agent_id="agent-a",
        event_type="RUN_STARTED",
        payload={},
    )
    store.record_event(
        thread_id="thread-b",
        task_id="task-b",
        agent_id="agent-b",
        event_type="RUN_STARTED",
        payload={},
    )
    store.record_approval(
        thread_id="thread-a",
        task_id="task-a",
        agent_id="agent-a",
        tool_name="exec_shell",
        tool_call_id="call-a",
        decision="approved",
    )
    store.record_checkpoint(
        task_id="task-a",
        checkpoint_type="react",
        thread_id="thread-a",
        agent_id="agent-a",
        state={},
    )
    store.record_token_usage(
        task_id="task-a",
        thread_id="thread-a",
        agent_id="agent-a",
        input_tokens=11,
        output_tokens=3,
    )
    store.record_token_usage(
        task_id="task-b",
        thread_id="thread-b",
        agent_id="agent-b",
        input_tokens=99,
        output_tokens=1,
    )

    stats = store.stats(thread_id="thread-a")

    assert stats["messages"] == 1
    assert stats["events"] == 1
    assert stats["approvals"] == 1
    assert stats["checkpoints"] == 1
    assert stats["token_usage"] == 1
    assert stats["token_totals"]["input_tokens"] == 11
    assert stats["token_totals"]["output_tokens"] == 3
    assert store.stats(task_id="task-b")["token_totals"]["input_tokens"] == 99
    assert store.stats(agent_id="missing")["events"] == 0


def test_wal_mode_is_enabled(tmp_path: Path) -> None:
    trace = AgentTraceStore(tmp_path / "trace.sqlite")
    try:
        row = trace._conn.execute("PRAGMA journal_mode;").fetchone()  # noqa: SLF001
        assert str(row[0]).lower() == "wal"
    finally:
        trace.close()


def test_jsonl_journal_mirrors_token_usage_and_checkpoint_to_trace_store(
    tmp_path: Path,
) -> None:
    trace = AgentTraceStore(tmp_path / "trace.sqlite")
    task_id = uuid4()
    try:
        journal = JSONLJournal(tmp_path / "events.jsonl", trace_store=trace)
        journal.write_token_usage(
            task_id=str(task_id),
            iteration=2,
            input_tokens=120,
            output_tokens=45,
            cost_usd=0.02,
            model="gpt-test",
        )
        journal.write_react_checkpoint(
            task_id=task_id,
            iteration_completed=2,
            max_iterations=8,
            messages_snapshot=[{"role": "user", "content": "continue"}],
            steps_snapshot=[{"iteration": 2, "action": "read_file"}],
            has_final_answer=False,
            working_set_snapshot=[{"path": "runtime/memory/trace_store.py"}],
            progress_summary="trace store added",
            current_phase="implementation",
        )

        tokens = trace.token_usage(task_id=str(task_id))
        assert len(tokens) == 1
        assert tokens[0]["input_tokens"] == 120
        assert tokens[0]["output_tokens"] == 45
        assert tokens[0]["model"] == "gpt-test"

        checkpoint = trace.latest_checkpoint(task_id=str(task_id), checkpoint_type="react")
        assert checkpoint is not None
        assert checkpoint["iteration"] == 2
        assert checkpoint["summary"] == "trace store added"
        assert checkpoint["state"]["current_phase"] == "implementation"
        assert checkpoint["state"]["messages_snapshot"][0]["content"] == "continue"

        event_types = [event["event_type"] for event in trace.events(task_id=str(task_id))]
        assert event_types == ["token_usage", "react_checkpoint"]
        assert (tmp_path / "events.jsonl").read_text(encoding="utf-8").count("\n") == 2
    finally:
        trace.close()


def test_jsonl_journal_trace_store_failure_does_not_block_jsonl(
    tmp_path: Path,
) -> None:
    class BrokenTraceStore:
        def record_event(self, **kwargs: object) -> int:
            raise RuntimeError("trace unavailable")

    journal = JSONLJournal(tmp_path / "events.jsonl", trace_store=BrokenTraceStore())
    journal.write_token_usage(
        task_id=str(uuid4()),
        iteration=1,
        input_tokens=1,
        output_tokens=2,
    )

    assert (tmp_path / "events.jsonl").read_text(encoding="utf-8").count("\n") == 1


def test_gateway_approval_provider_records_decision_to_trace_store(tmp_path: Path) -> None:
    import asyncio

    class FakeEmitter:
        async def request_approval(
            self,
            method: object,
            params: dict[str, object],
            *,
            timeout: float,
        ) -> dict[str, str]:
            assert params["tool"] == "exec_shell"
            return {"action": "accept"}

    async def run() -> None:
        trace = AgentTraceStore(tmp_path / "trace.sqlite")
        try:
            provider = GatewayApprovalProvider(
                FakeEmitter(),
                asyncio.get_running_loop(),
                thread_id="thread-1",
                turn_id="turn-1",
                trace_store=trace,
            )
            decision = await asyncio.to_thread(
                provider.request,
                ApprovalRequest(
                    thread_id="thread-1",
                    tool_name="exec_shell",
                    tool_call_id="call-1",
                    args_preview="rm -rf nope",
                    detail="dangerous command",
                ),
            )

            assert decision.approved is True
            approvals = trace.approvals(thread_id="thread-1")
            assert len(approvals) == 1
            assert approvals[0]["tool_name"] == "exec_shell"
            assert approvals[0]["tool_call_id"] == "call-1"
            assert approvals[0]["decision"] == "approved"
            assert approvals[0]["reason"] == "accept"
            assert approvals[0]["turn_id"] == "turn-1"
            assert approvals[0]["metadata"]["detail"] == "dangerous command"
            trust = approvals[0]["metadata"]["trust_gateway"]
            assert trust["schema"] == "octopus.trust_decision.v1"
            assert trust["tool_name"] == "exec_shell"
            assert trust["risk"]["level"] == "critical"
        finally:
            trace.close()

    asyncio.run(run())


def test_gateway_approval_provider_converts_gateway_timeout_to_rejection(tmp_path: Path) -> None:
    import asyncio

    from runtime.protocol import JsonRpcError, JsonRpcErrorCode
    from runtime.sensing.gateway.realtime_gateway import _ApprovalError

    class TimeoutEmitter:
        async def request_approval(
            self,
            method: object,
            params: dict[str, object],
            *,
            timeout: float,
        ) -> dict[str, str]:
            raise _ApprovalError(
                JsonRpcError(
                    code=JsonRpcErrorCode.APPROVAL_TIMEOUT,
                    message="timed out waiting for item/commandExecution/requestApproval",
                )
            )

    async def run() -> None:
        trace = AgentTraceStore(tmp_path / "trace.sqlite")
        try:
            provider = GatewayApprovalProvider(
                TimeoutEmitter(),
                asyncio.get_running_loop(),
                thread_id="thread-1",
                turn_id="turn-1",
                trace_store=trace,
            )
            decision = await asyncio.to_thread(
                provider.request,
                ApprovalRequest(
                    thread_id="thread-1",
                    tool_name="write_text_file",
                    tool_call_id="call-1",
                    args_preview="plan.md",
                    detail="write_text_file wants to execute",
                ),
            )

            assert decision.approved is False
            # Machine-readable reason: the UI and journal must be able
            # to tell "nobody answered" apart from "user said no".
            assert decision.reason == "timeout"
            approvals = trace.approvals(thread_id="thread-1")
            assert approvals[0]["decision"] == "timeout"
            assert approvals[0]["reason"] == "timeout"
        finally:
            trace.close()

    asyncio.run(run())


def test_gateway_approval_provider_converts_connection_loss_to_rejection(tmp_path: Path) -> None:
    import asyncio

    class CancelledEmitter:
        async def request_approval(
            self,
            method: object,
            params: dict[str, object],
            *,
            timeout: float,
        ) -> dict[str, str]:
            # ApprovalManager.cancel_all() on connection close cancels
            # the pending future; awaiting it raises CancelledError.
            raise asyncio.CancelledError()

    async def run() -> None:
        trace = AgentTraceStore(tmp_path / "trace.sqlite")
        try:
            provider = GatewayApprovalProvider(
                CancelledEmitter(),
                asyncio.get_running_loop(),
                thread_id="thread-1",
                turn_id="turn-1",
                trace_store=trace,
            )
            decision = await asyncio.to_thread(
                provider.request,
                ApprovalRequest(
                    thread_id="thread-1",
                    tool_name="exec_shell",
                    tool_call_id="call-1",
                    args_preview="ls",
                    detail="exec_shell wants to execute",
                ),
            )

            assert decision.approved is False
            assert decision.reason == "connection_lost"
            approvals = trace.approvals(thread_id="thread-1")
            assert approvals[0]["decision"] == "connection_lost"
        finally:
            trace.close()

    asyncio.run(run())


def test_gateway_approval_provider_sends_timeout_to_client(tmp_path: Path) -> None:
    import asyncio

    captured: dict[str, object] = {}

    class CapturingEmitter:
        async def request_approval(
            self,
            method: object,
            params: dict[str, object],
            *,
            timeout: float,
        ) -> dict[str, str]:
            captured.update(params)
            return {"action": "accept"}

    async def run() -> None:
        provider = GatewayApprovalProvider(
            CapturingEmitter(),
            asyncio.get_running_loop(),
            thread_id="thread-1",
            turn_id="turn-1",
        )
        await asyncio.to_thread(
            provider.request,
            ApprovalRequest(
                thread_id="thread-1",
                tool_name="exec_shell",
                tool_call_id="call-1",
                args_preview="ls",
                detail="",
            ),
        )
        # The client mirrors the server timeout to expire its dialog in
        # lockstep instead of leaving a zombie prompt.
        assert captured["timeoutMs"] == 120_000

    asyncio.run(run())


def test_app_state_wires_trace_store_into_default_jsonl_journal(tmp_path: Path) -> None:
    from runtime.platform.ui.state import AppState

    state = AppState(
        journal_path=tmp_path / "events.jsonl",
        trace_store_path=tmp_path / "agent_trace.sqlite",
    )

    task_id = uuid4()
    state.journal.write_token_usage(
        task_id=str(task_id),
        iteration=1,
        input_tokens=9,
        output_tokens=4,
        model="gpt-test",
    )

    trace = AgentTraceStore(tmp_path / "agent_trace.sqlite")
    try:
        tokens = trace.token_usage(task_id=str(task_id))
        assert len(tokens) == 1
        assert tokens[0]["input_tokens"] == 9
    finally:
        trace.close()


def test_app_state_attaches_trace_store_to_injected_jsonl_journal(tmp_path: Path) -> None:
    from runtime.platform.ui.state import AppState

    injected = JSONLJournal(tmp_path / "injected.jsonl")
    state = AppState(
        journal=injected,
        trace_store_path=tmp_path / "agent_trace.sqlite",
    )
    assert state.journal_path == tmp_path / "injected.jsonl"

    task_id = uuid4()
    state.journal.write_token_usage(
        task_id=str(task_id),
        iteration=1,
        input_tokens=12,
        output_tokens=3,
        model="serve-model",
    )

    trace = AgentTraceStore(tmp_path / "agent_trace.sqlite")
    try:
        tokens = trace.token_usage(task_id=str(task_id))
        assert len(tokens) == 1
        assert tokens[0]["model"] == "serve-model"
    finally:
        trace.close()


def test_create_app_uses_default_agent_trace_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fastapi = pytest.importorskip("fastapi")
    assert fastapi is not None
    from runtime.platform.ui import create_app

    monkeypatch.setenv("OCTOPUS_DATA_DIR", str(tmp_path / "data"))

    app = create_app(journal_path=tmp_path / "data" / "events.jsonl")
    state = app.state.octopus_state

    assert state.trace_store_path == (tmp_path / "data" / "agent_trace.sqlite").resolve()


def test_create_app_wires_trace_store_into_loop_controller(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fastapi = pytest.importorskip("fastapi")
    assert fastapi is not None
    from runtime.execution.suckers import SkillRegistry
    from runtime.platform.ui import create_app

    monkeypatch.setenv("OCTOPUS_DATA_DIR", str(tmp_path / "data"))
    stack = SimpleNamespace(
        journal=None,
        executor=SimpleNamespace(
            journal=None,
            registry=SkillRegistry(),
        ),
        runtime=SimpleNamespace(journal=None),
    )

    app = create_app(
        journal_path=tmp_path / "data" / "events.jsonl",
        stack=stack,
    )
    state = app.state.octopus_state

    assert app.state.loop_controller is not None
    assert app.state.loop_controller.trace_store is state.trace_store
    assert state.task_supervisor is not None
    assert app.state.task_supervisor is state.task_supervisor
    assert app.state.loop_controller.task_supervisor is state.task_supervisor
