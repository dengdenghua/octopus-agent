"""Implementation note."""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest

from runtime.memory.journal import (
    InMemoryJournal,
    JournalTransactionError,
    JSONLJournal,
    StepEvent,
    journal_context,
)
from runtime.memory.journal._journal_models import TokenUsageEvent
from runtime.platform.models import (
    ArmId,
    ExecutionResult,
    Step,
    TaskId,
    ToolCall,
    Trajectory,
    TrajectoryOutcome,
)
from runtime.safety.auth.scope import TenantScope
from runtime.sensing.gateway import StreamingJournal

# ═══════════════════════════════════════════════════════════
# helpers
# ═══════════════════════════════════════════════════════════


def _mk_step() -> Step:
    call = ToolCall(caller="arms/x", sucker_id="list_cwd", args={})
    return Step(
        step_id=0,
        node_id="n0",
        action=call,
        result=ExecutionResult(call_id=call.call_id, status="success"),
    )


def _mk_traj() -> Trajectory:
    return Trajectory(
        task_id=TaskId(uuid4()),
        arm_id=ArmId("a"),
        steps=[_mk_step()],
        outcome=TrajectoryOutcome(success=True),
    )


# ═══════════════════════════════════════════════════════════
# Implementation note.
# ═══════════════════════════════════════════════════════════


class TestSubscription:
    def test_subscriber_receives_write(self):
        base = InMemoryJournal()
        j = StreamingJournal(base)

        received = []
        j.subscribe(lambda e: received.append(e))
        j.write_trajectory(_mk_traj())

        assert len(received) == 1
        assert received[0].event_type == "trajectory"

    def test_multiple_subscribers_all_notified(self):
        j = StreamingJournal(InMemoryJournal())
        a, b = [], []
        j.subscribe(lambda e: a.append(e))
        j.subscribe(lambda e: b.append(e))

        j.write_trajectory(_mk_traj())
        assert len(a) == 1
        assert len(b) == 1

    def test_unsubscribe_stops_delivery(self):
        j = StreamingJournal(InMemoryJournal())
        seen = []
        unsub = j.subscribe(lambda e: seen.append(e))
        j.write_trajectory(_mk_traj())
        unsub()
        j.write_trajectory(_mk_traj())
        assert len(seen) == 1  # Implementation note.
        assert j.subscriber_count == 0

    def test_subscriber_exception_swallowed(self):
        j = StreamingJournal(InMemoryJournal())
        good = []

        def bad(e):
            raise RuntimeError("boom")

        j.subscribe(bad)
        j.subscribe(lambda e: good.append(e))
        # Implementation note.
        j.write_trajectory(_mk_traj())
        assert len(good) == 1
        assert len(j.read_all()) == 1  # Implementation note.

    def test_unsubscribe_twice_is_noop(self):
        j = StreamingJournal(InMemoryJournal())
        unsub = j.subscribe(lambda e: None)
        unsub()
        unsub()  # Implementation note.
        assert j.subscriber_count == 0


# ═══════════════════════════════════════════════════════════
# Implementation note.
# ═══════════════════════════════════════════════════════════


class TestReadPassThrough:
    def test_read_all_delegates(self):
        base = InMemoryJournal()
        j = StreamingJournal(base)
        traj = _mk_traj()
        j.write_trajectory(traj)

        # Implementation note.
        assert len(base.read_all()) == 1
        assert len(j.read_all()) == 1

    def test_len_delegates(self):
        j = StreamingJournal(InMemoryJournal())
        j.write_trajectory(_mk_traj())
        j.write_trajectory(_mk_traj())
        assert len(j) == 2

    def test_read_by_type_delegates(self):
        j = StreamingJournal(InMemoryJournal())
        j.write_trajectory(_mk_traj())
        assert len(j.read_by_type("trajectory")) == 1
        assert len(j.read_by_type("step")) == 0

    def test_scoped_reads_are_forwarded_to_inner_journal(self):
        j = StreamingJournal(InMemoryJournal())
        alice = TenantScope("tenant-a", "alice")
        bob = TenantScope("tenant-b", "bob")
        j.write(
            TokenUsageEvent(
                tenant_id="tenant-a",
                owner_actor_id="alice",
                input_tokens=1,
                output_tokens=2,
            )
        )
        j.write(
            TokenUsageEvent(
                tenant_id="tenant-b",
                owner_actor_id="bob",
                input_tokens=3,
                output_tokens=4,
            )
        )

        assert len(j.read_all(scope=alice)) == 1
        assert len(j.read_by_type("token_usage", scope=alice)) == 1
        assert len(j.read_by_type("token_usage", scope=bob)) == 1


# ═══════════════════════════════════════════════════════════
# Implementation note.
# ═══════════════════════════════════════════════════════════


class TestWithJSONLInner:
    def test_jsonl_persistence_preserved(self, tmp_path: Path):
        path = tmp_path / "events.jsonl"
        base = JSONLJournal(path)
        j = StreamingJournal(base)

        received = []
        j.subscribe(lambda e: received.append(e))
        j.write_trajectory(_mk_traj())
        j.write_step(_mk_traj().task_id, ArmId("a"), _mk_step())

        assert len(received) == 2
        # Implementation note.
        content = path.read_text(encoding="utf-8").strip()
        assert len(content.splitlines()) == 2

        # Implementation note.
        reopened = JSONLJournal(path)
        assert len(reopened.read_all()) == 2

    def test_attr_forwarding(self, tmp_path: Path):
        """Implementation note."""
        path = tmp_path / "events.jsonl"
        j = StreamingJournal(JSONLJournal(path))
        assert Path(j._path) == path

    def test_step_broadcast_matches_durable_redacted_scoped_event(
        self,
        tmp_path: Path,
    ) -> None:
        from runtime.platform.observability.redactor import Redactor

        canary = "sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123456789ABC"
        call = ToolCall(
            caller="arms/x",
            sucker_id="secret_echo",
            args={"token": canary},
        )
        step = Step(
            step_id=0,
            node_id="n0",
            action=call,
            result=ExecutionResult(
                call_id=call.call_id,
                status="success",
                output={"echo": canary},
            ),
        )
        path = tmp_path / "events.jsonl"
        inner = JSONLJournal(path, redactor=Redactor())
        journal = StreamingJournal(inner)
        received: list[StepEvent] = []
        journal.subscribe(lambda event: received.append(event))

        with journal_context(tenant_id="tenant-a", owner_actor_id="owner-a"):
            journal.write_step(TaskId(uuid4()), ArmId("arm-a"), step)

        stored = inner.read_by_type("step")
        assert len(received) == len(stored) == 1
        assert received[0].model_dump(mode="json") == stored[0].model_dump(mode="json")
        assert received[0].tenant_id == "tenant-a"
        assert received[0].owner_actor_id == "owner-a"
        assert canary not in received[0].model_dump_json()
        assert canary not in path.read_text(encoding="utf-8")
        assert "[REDACTED:api_key]" in received[0].model_dump_json()
        assert "[REDACTED:api_key]" in path.read_text(encoding="utf-8")

    def test_step_is_not_broadcast_when_durable_fsync_fails(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        journal = StreamingJournal(JSONLJournal(tmp_path / "events.jsonl"))
        received = []
        journal.subscribe(received.append)

        def fail_fsync(_fd: int) -> None:
            raise OSError("simulated durable write failure")

        monkeypatch.setattr(os, "fsync", fail_fsync)
        with pytest.raises(JournalTransactionError, match="durable journal data"):
            journal.write_step(TaskId(uuid4()), ArmId("arm-a"), _mk_step())

        assert received == []


class TestLegacyWriteCompatibility:
    def test_write_only_duck_is_called_once_without_replay(self) -> None:
        class LegacyJournal:
            def __init__(self, existing: StepEvent) -> None:
                self.events = [existing]
                self.write_calls = 0

            def write(self, event: StepEvent) -> None:
                self.write_calls += 1
                self.events.append(event)

        existing = StepEvent(
            task_id=TaskId(uuid4()),
            arm_id=ArmId("arm-a"),
            step=_mk_step(),
        )
        inner = LegacyJournal(existing)
        journal = StreamingJournal(inner)  # type: ignore[arg-type]
        received: list[StepEvent] = []
        journal.subscribe(lambda event: received.append(event))
        new_event = StepEvent(
            task_id=TaskId(uuid4()),
            arm_id=ArmId("arm-a"),
            step=_mk_step(),
        )

        with journal_context(tenant_id="tenant-a", owner_actor_id="owner-a"):
            journal.write(new_event)

        assert inner.write_calls == 1
        assert len(inner.events) == 2
        assert received == [inner.events[-1]]
        assert existing not in received
        assert received[0].tenant_id == "tenant-a"
        assert received[0].owner_actor_id == "owner-a"

    def test_canonical_hook_failure_is_not_retried_through_legacy_write(self) -> None:
        class FailingCanonicalJournal:
            def __init__(self) -> None:
                self.canonical_calls = 0
                self.write_calls = 0

            def write_canonical(self, _event: StepEvent) -> StepEvent:
                self.canonical_calls += 1
                raise OSError("commit failed")

            def write(self, _event: StepEvent) -> None:
                self.write_calls += 1

        inner = FailingCanonicalJournal()
        journal = StreamingJournal(inner)  # type: ignore[arg-type]
        received = []
        journal.subscribe(received.append)
        event = StepEvent(
            task_id=TaskId(uuid4()),
            arm_id=ArmId("arm-a"),
            step=_mk_step(),
        )

        with pytest.raises(OSError, match="commit failed"):
            journal.write(event)

        assert inner.canonical_calls == 1
        assert inner.write_calls == 0
        assert received == []


# ═══════════════════════════════════════════════════════════
# Implementation note.
# ═══════════════════════════════════════════════════════════


fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from runtime.platform.ui import create_app  # noqa: E402


class TestSSEEndpoint:
    def test_stream_route_registered_with_correct_content_type(self):
        """Implementation note."""
        app = create_app(journal_path=None)
        # Implementation note.
        from tests.route_utils import route_paths

        assert "/api/stream" in route_paths(app)

    def test_app_uses_streaming_journal(self):
        """Implementation note."""
        app = create_app(journal_path=None)
        # Implementation note.
        client = TestClient(app)
        r = client.get("/api/journal")
        # Implementation note.
        assert r.status_code == 200
        client.post("/api/run", json={"goal": "list stuff"})
        r2 = client.get("/api/journal")
        assert r2.json()["total"] > 0
