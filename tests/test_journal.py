"""Implementation note."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from runtime.memory.journal import (
    BudgetBreakerResetEvent,
    BudgetEvent,
    CurriculumGoalDecisionEvent,
    ImmuneEvent,
    InMemoryJournal,
    JournalEvent,
    JSONLJournal,
    McpProposalDecisionEvent,
    ProtocolDriftDecisionEvent,
    SkillProposalDecisionEvent,
    TrajectoryEvent,
)
from runtime.platform.models import (
    AntigenSignature,
    CostEntry,
    ExecutionResult,
    Step,
    ToolCall,
)
from runtime.safety.invariants import InvariantViolation


@pytest.fixture
def sample_step_for_journal(sample_cost):
    call = ToolCall(caller="arm:code_arm", sucker_id="read_file", args={})
    r = ExecutionResult(call_id=call.call_id, status="success", cost=sample_cost)
    return Step(step_id=0, node_id="n0", action=call, result=r)


class TestInMemoryJournal:
    def test_write_and_read(self, sample_step_for_journal, sample_trajectory):
        j = InMemoryJournal()
        j.write_step(
            task_id=sample_trajectory.task_id,
            arm_id=sample_trajectory.arm_id,
            step=sample_step_for_journal,
        )
        j.write_trajectory(sample_trajectory)
        all_events = j.read_all()
        assert len(all_events) == 2

    def test_read_by_task(self, sample_trajectory, sample_step_for_journal):
        j = InMemoryJournal()
        j.write_step(sample_trajectory.task_id, "code_arm", sample_step_for_journal)
        j.write_trajectory(sample_trajectory)
        only = j.read_by_task(sample_trajectory.task_id)
        assert len(only) == 2

    def test_read_by_type(self, sample_trajectory, sample_step_for_journal):
        j = InMemoryJournal()
        j.write_step(sample_trajectory.task_id, "code_arm", sample_step_for_journal)
        j.write_trajectory(sample_trajectory)
        steps = j.read_by_type("step")
        trajs = j.read_by_type("trajectory")
        assert len(steps) == 1
        assert len(trajs) == 1

    def test_append_only_backbone(self):
        """Implementation note."""
        j = InMemoryJournal()
        # Implementation note.
        with pytest.raises(InvariantViolation):
            j._events.pop()


class TestJSONLJournal:
    def test_write_and_read_roundtrip(self, tmp_path: Path, sample_trajectory):
        j = JSONLJournal(tmp_path / "journal.jsonl")
        j.write_trajectory(sample_trajectory)

        reloaded = j.read_all()
        assert len(reloaded) == 1
        assert isinstance(reloaded[0], TrajectoryEvent)
        assert reloaded[0].trajectory.trajectory_id == sample_trajectory.trajectory_id

    def test_append_survives_process_boundary(self, tmp_path: Path, sample_trajectory):
        path = tmp_path / "journal.jsonl"
        # Implementation note.
        j1 = JSONLJournal(path)
        j1.write_trajectory(sample_trajectory)
        # Implementation note.
        j2 = JSONLJournal(path)
        j2.write_trajectory(sample_trajectory)
        # Implementation note.
        reader = JSONLJournal(path)
        assert len(reader.read_all()) == 2

    def test_immune_event_serialization(self, tmp_path: Path):
        j = JSONLJournal(tmp_path / "j.jsonl")
        sig = AntigenSignature(
            entity_id="skill://public/x",
            entity_type="skill",
            content_hash="abc",
        )
        j.write_immune("allow", sig, reason="test")
        events = j.read_all()
        assert len(events) == 1
        assert isinstance(events[0], ImmuneEvent)
        assert events[0].verdict == "allow"

    def test_budget_event_serialization(self, tmp_path: Path, sample_trajectory):
        j = JSONLJournal(tmp_path / "j.jsonl")
        j.write_budget(
            "budget_commit",
            task_id=sample_trajectory.task_id,
            cost=CostEntry(tokens_in=100, tokens_out=50, usd=0.001),
        )
        events = j.read_all()
        assert len(events) == 1
        assert isinstance(events[0], BudgetEvent)
        assert events[0].cost.tokens == 150

    def test_budget_breaker_reset_serialization(self, tmp_path: Path):
        j = JSONLJournal(tmp_path / "j.jsonl")
        j.write_budget_breaker_reset(
            component="runtime",
            reason="operator reset",
            actor="operator",
        )

        events = j.read_all()
        assert len(events) == 1
        assert isinstance(events[0], BudgetBreakerResetEvent)
        assert events[0].component == "runtime"
        assert events[0].reason == "operator reset"

    def test_skill_proposal_decision_serialization(self, tmp_path: Path):
        j = JSONLJournal(tmp_path / "j.jsonl")
        j.write_skill_proposal_decision(
            proposal_name="forged_demo",
            candidate_id="abc12345",
            decision="rejected",
            reason="operator rejected",
            details={"source_sample_count": 3},
        )

        events = j.read_all()
        assert len(events) == 1
        assert isinstance(events[0], SkillProposalDecisionEvent)
        assert events[0].proposal_name == "forged_demo"
        assert events[0].decision == "rejected"
        assert events[0].details["source_sample_count"] == 3

    def test_curriculum_goal_decision_serialization(self, tmp_path: Path):
        j = JSONLJournal(tmp_path / "j.jsonl")
        j.write_curriculum_goal_decision(
            goal_id=123,
            cluster_key="skill:read_file:failed:FileNotFoundError",
            status="in_progress",
            covered_by="forged_reader",
            details={"failure_count": 3},
        )

        events = j.read_all()
        assert len(events) == 1
        assert isinstance(events[0], CurriculumGoalDecisionEvent)
        assert events[0].goal_id == 123
        assert events[0].status == "in_progress"
        assert events[0].covered_by == "forged_reader"

    def test_mcp_proposal_decision_serialization(self, tmp_path: Path):
        j = JSONLJournal(tmp_path / "j.jsonl")
        j.write_mcp_proposal_decision(
            server_name="github",
            status="vetted",
            reason="operator_vet",
            details={"risk_level": "high"},
        )

        events = j.read_all()
        assert len(events) == 1
        assert isinstance(events[0], McpProposalDecisionEvent)
        assert events[0].server_name == "github"
        assert events[0].status == "vetted"
        assert events[0].details["risk_level"] == "high"

    def test_protocol_drift_decision_serialization(self, tmp_path: Path):
        j = JSONLJournal(tmp_path / "j.jsonl")
        j.write_protocol_drift_decision(
            drift_id=42,
            protocol_id="http_api_contract",
            status="acknowledged",
            reason="operator_acknowledged",
            details={"summary": "404 on /api/example"},
        )

        events = j.read_all()
        assert len(events) == 1
        assert isinstance(events[0], ProtocolDriftDecisionEvent)
        assert events[0].drift_id == 42
        assert events[0].protocol_id == "http_api_contract"
        assert events[0].status == "acknowledged"


class TestInMemoryJournalRing:
    """Audit R-04: the in-memory journal is a ring buffer when capped."""

    def test_ring_drops_oldest_beyond_cap(self):
        from uuid import uuid4

        j = InMemoryJournal(max_events=3)
        ids = [str(uuid4()) for _ in range(5)]
        for i, tid in enumerate(ids):
            j.write(
                JournalEvent(
                    event_type="task_started",
                    ts=datetime(2026, 1, 1, 0, 0, i % 60),
                    thread_id="t",
                    task_id=tid,
                )
            )
        assert len(j) == 3
        kept = {str(e.task_id) for e in j.read_all()}
        assert kept == set(ids[2:])  # oldest two evicted, newest three kept

    def test_unbounded_default_keeps_all(self):
        from uuid import uuid4

        j = InMemoryJournal()
        for _ in range(10):
            j.write(
                JournalEvent(
                    event_type="task_started",
                    ts=datetime(2026, 1, 1, 0, 0, 0),
                    thread_id="t",
                    task_id=str(uuid4()),
                )
            )
        assert len(j) == 10

    def test_append_only_invariant_still_guards_writes(self):
        from uuid import uuid4

        j = InMemoryJournal(max_events=5)
        j.write(
            JournalEvent(
                event_type="task_started",
                ts=datetime(2026, 1, 1, 0, 0, 0),
                thread_id="t",
                task_id=str(uuid4()),
            )
        )
        before = list(j._events)
        with pytest.raises(InvariantViolation):
            j._events.pop()
        assert list(j._events) == before


class TestSessionIndex:
    """Audit P-04: read_by_session consumes only a session's rows and
    refreshes incrementally (O(new events) after the first scan)."""

    def _session_event(self, session_id: str, seq: int) -> JournalEvent:
        from uuid import uuid4

        from runtime.memory.journal._journal_models import SubTextDeltaEvent

        return SubTextDeltaEvent(
            ts=datetime(2026, 1, 1, 0, 0, seq),
            thread_id="t",
            task_id=str(uuid4()),
            session_id=session_id,
            delta=f"{session_id}-{seq}",
        )

    def test_inmemory_read_by_session_incremental(self) -> None:
        j = InMemoryJournal()
        j.write(self._session_event("A", 1))
        j.write(self._session_event("B", 1))
        assert [e.delta for e in j.read_by_session("A")] == ["A-1"]
        # Incremental: new A + B events; only A is returned, both A rows.
        j.write(self._session_event("A", 2))
        j.write(self._session_event("B", 2))
        assert [e.delta for e in j.read_by_session("A")] == ["A-1", "A-2"]
        assert j.read_by_session("missing") == []

    def test_jsonl_read_by_session_incremental(self, tmp_path: Path) -> None:
        j = JSONLJournal(tmp_path / "j.jsonl")
        j.write(self._session_event("A", 1))
        j.write(self._session_event("B", 1))
        assert [e.delta for e in j.read_by_session("A")] == ["A-1"]
        j.write(self._session_event("A", 2))
        assert [e.delta for e in j.read_by_session("A")] == ["A-1", "A-2"]
        # A fresh instance reads the persisted file correctly too.
        j2 = JSONLJournal(tmp_path / "j.jsonl")
        assert [e.delta for e in j2.read_by_session("B")] == ["B-1"]

    def test_surface_events_uses_session_rows(self) -> None:
        from uuid import uuid4

        from runtime.memory.journal._journal_models import UserMessageEvent
        from runtime.memory.journal.derive import surface_events_from_journal

        j = InMemoryJournal()
        j.write(
            UserMessageEvent(
                ts=datetime(2026, 1, 1, 0, 0, 0),
                thread_id="t",
                task_id=str(uuid4()),
                session_id="A",
                text="ask A",
            )
        )
        j.write(self._session_event("A", 1))
        j.write(self._session_event("B", 1))
        j.write(self._session_event("A", 2))
        surface = surface_events_from_journal(j, session_id="A")
        # Only A's deltas are projected, interleaved; B never leaks.

        def _text(e):
            data = e.get("data") or {}
            if e.get("type") == "user/message":
                return "".join(c.get("text", "") for c in data.get("content") or [])
            msg = data.get("message") or {}
            return "".join(c.get("text", "") for c in (msg.get("content") or []))

        texts = [_text(e) for e in surface]
        assert any("A-1" in t for t in texts)
        assert any("A-2" in t for t in texts)
        assert not any("B-1" in t for t in texts)
