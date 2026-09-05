"""Verified artifact handoffs use real files, leases and durable records."""

from __future__ import annotations

import asyncio
import hashlib
import json
import threading
import time
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from runtime.execution.artifact_contracts import HandoffRecorder
from runtime.execution.misc.file_write_leases import (
    FileWriteLeaseConflict,
    WorkspaceContentDriftConflict,
    acquire_file_write_lease,
    file_write_lease_snapshot,
)
from runtime.execution.request import current_execution_request
from runtime.execution.subagents.artifact_handoff import ArtifactHandoff, ArtifactHandoffError
from runtime.execution.subagents.bridge import call_subagent
from runtime.memory.threads.event_log import EventLog
from runtime.platform.process.session import current_session
from tests.test_subagent_execution_context import _parent


def _host(tmp_path, write=None):
    parent = _parent(tmp_path)
    log = EventLog(tmp_path / "events.jsonl")
    parent.metadata["_execution_handoff_recorder"] = HandoffRecorder(
        write or (lambda receipt: log.execution_handoff("parent-thread", "parent-turn", receipt))
    )
    return parent, log


def _events(log):
    rows = [json.loads(line) for line in log.path.read_text(encoding="utf-8").splitlines()]
    return [{**row, **row.get("payload", {})} for row in rows]


def test_missing_output_cannot_be_accepted_or_transfer_back(tmp_path):
    parent, log = _host(tmp_path)
    handoff = ArtifactHandoff.prepare(parent, [], ["missing.txt"])
    handoff.begin("child")
    handoff.finished = True
    with pytest.raises(ArtifactHandoffError, match="missing"):
        handoff.accept()
    assert file_write_lease_snapshot(parent.metadata)["leases"][0]["owner"] == "child"
    assert [row["phase"] for row in _events(log)] == ["assigned"]


def test_failed_durable_assignment_prevents_child_effects(tmp_path):
    def fail(_receipt):
        raise OSError("journal unavailable")

    parent, _ = _host(tmp_path, fail)
    called = []
    result = call_subagent(
        "coder",
        "make output",
        session=parent,
        output_files=["output.txt"],
        runner=lambda *_a, **_kw: called.append(True),
        timeout_seconds=3,
    )
    assert not result["success"]
    assert "journal unavailable" in result["error"]
    assert result["retry_allowed"] is False
    assert called == []
    assert file_write_lease_snapshot(parent.metadata)["leases"] == []


def test_batch_assignment_is_atomic_on_owner_conflict(tmp_path):
    parent, log = _host(tmp_path)
    acquire_file_write_lease(parent, tmp_path / "b.txt", owner="other-child")
    handoff = ArtifactHandoff.prepare(parent, [], ["a.txt", "b.txt"])
    with pytest.raises(FileWriteLeaseConflict, match="owner mismatch"):
        handoff.begin("child")
    leases = file_write_lease_snapshot(parent.metadata)["leases"]
    assert len(leases) == 1 and leases[0]["owner"] == "other-child"
    assert not log.path.exists()


def test_changed_input_blocks_acceptance_after_child_returns(tmp_path):
    parent, log = _host(tmp_path)
    source = tmp_path / "input.txt"
    source.write_text("original", encoding="utf-8")
    handoff = ArtifactHandoff.prepare(parent, ["input.txt"], ["output.txt"])
    handoff.begin("child")
    (tmp_path / "output.txt").write_text("result", encoding="utf-8")
    source.write_text("outside edit", encoding="utf-8")
    handoff.finished = True
    with pytest.raises(ArtifactHandoffError, match="input changed"):
        handoff.accept()
    assert [row["phase"] for row in _events(log)] == ["assigned"]


def test_failed_acceptance_journal_retains_child_ownership(tmp_path):
    parent, _ = _host(tmp_path)
    handoff = ArtifactHandoff.prepare(parent, [], ["out.txt"])
    handoff.begin("child")
    (tmp_path / "out.txt").write_text("output", encoding="utf-8")
    handoff.finished = True
    handoff.recorder = HandoffRecorder(lambda _receipt: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError, match="disk full"):
        handoff.accept()
    assert not handoff.accepted
    assert file_write_lease_snapshot(parent.metadata)["leases"][0]["owner"] == "child"


@pytest.mark.parametrize("path", ["../outside.txt", "../../outside.txt"])
def test_paths_cannot_expand_parent_scope(tmp_path, path):
    parent, _ = _host(tmp_path)
    with pytest.raises(ArtifactHandoffError, match="outside"):
        ArtifactHandoff.prepare(parent, [], [path])


def test_forged_model_hashes_and_schema_failure_never_accept(tmp_path):
    parent, log = _host(tmp_path)

    def runner(*_args, **_kwargs):
        (tmp_path / "out.txt").write_text("actual bytes", encoding="utf-8")
        return '{"artifacts":[{"sha256":"forged"}]}'

    result = call_subagent(
        "coder",
        "create output",
        session=parent,
        output_files=["out.txt"],
        output_schema={
            "type": "object",
            "properties": {"ok": {"type": "boolean"}},
            "required": ["ok"],
        },
        runner=runner,
        timeout_seconds=3,
    )
    assert not result["success"]
    assert result["schema_ok"] is False
    assert "artifacts" not in result
    assert result["retry_allowed"] is False
    assert [row["phase"] for row in _events(log)] == ["assigned"]


def test_success_records_actual_bytes_before_parent_reacquires(tmp_path):
    parent, log = _host(tmp_path)
    handoff = ArtifactHandoff.prepare(parent, [], ["out.txt"])
    handoff.begin("child")
    path = tmp_path / "out.txt"
    path.write_text("actual bytes", encoding="utf-8")
    handoff.finished = True
    receipt = handoff.accept()
    assert receipt["artifacts"][0]["sha256"] == hashlib.sha256(b"actual bytes").hexdigest()
    assert receipt["artifacts"][0]["producer_task_id"] == "child"
    assert acquire_file_write_lease(parent, path, owner="parent-turn").reentrant
    assert [row["phase"] for row in _events(log)] == ["assigned", "accepted"]
    with pytest.raises(ArtifactHandoffError, match="only one"):
        handoff.accept()


def test_output_edit_during_acceptance_is_detected_before_transfer(tmp_path, monkeypatch):
    from runtime.execution.misc.file_write_leases import WorkspaceContentDriftConflict
    from runtime.execution.subagents import artifact_handoff

    parent, log = _host(tmp_path)
    handoff = ArtifactHandoff.prepare(parent, [], ["out.txt"])
    handoff.begin("child")
    path = tmp_path / "out.txt"
    path.write_text("child output", encoding="utf-8")
    handoff.finished = True
    transfer = artifact_handoff.transfer_file_write_leases

    def race(*args, **kwargs):
        path.write_text("concurrent edit", encoding="utf-8")
        return transfer(*args, **kwargs)

    monkeypatch.setattr(artifact_handoff, "transfer_file_write_leases", race)
    with pytest.raises(WorkspaceContentDriftConflict):
        handoff.accept()
    assert file_write_lease_snapshot(parent.metadata)["leases"][0]["owner"] == "child"
    assert [row["phase"] for row in _events(log)] == ["assigned"]


def test_declared_existing_output_can_be_updated_and_returned(tmp_path):
    parent, _ = _host(tmp_path)
    path = tmp_path / "source.py"
    path.write_text("old code", encoding="utf-8")
    acquire_file_write_lease(parent, path, owner="parent-turn")
    handoff = ArtifactHandoff.prepare(parent, ["source.py"], ["source.py"])
    handoff.begin("child")
    path.write_text("new code", encoding="utf-8")
    handoff.finished = True
    receipt = handoff.accept()
    assert receipt["artifacts"][0]["sha256"] != handoff.contract.inputs[0].sha256
    assert acquire_file_write_lease(parent, path, owner="parent-turn").reentrant


def test_undeclared_executor_write_blocks_acceptance(tmp_path):
    parent, _ = _host(tmp_path)
    handoff = ArtifactHandoff.prepare(parent, [], ["expected.txt"])
    handoff.begin("child")
    (tmp_path / "expected.txt").write_text("ok", encoding="utf-8")
    acquire_file_write_lease(parent, tmp_path / "unexpected.txt", owner="child")
    handoff.finished = True
    with pytest.raises(FileWriteLeaseConflict, match="undeclared"):
        handoff.accept()


def test_handoff_records_survive_log_coalescing(tmp_path):
    from runtime.memory.threads.event_log import LoggedEvent, coalesce_events

    parent, log = _host(tmp_path)
    handoff = ArtifactHandoff.prepare(parent, [], ["out.txt"])
    handoff.begin("child")
    (tmp_path / "out.txt").write_text("ok", encoding="utf-8")
    handoff.finished = True
    handoff.accept()
    rows = [
        LoggedEvent.model_validate_json(line)
        for line in log.path.read_text(encoding="utf-8").splitlines()
    ]
    compacted = coalesce_events(list(enumerate(rows)))
    assert [event.payload["phase"] for _, event in compacted] == ["assigned", "accepted"]


def test_delegation_skill_never_retries_by_dropping_an_artifact_contract(tmp_path, monkeypatch):
    from runtime.execution.suckers import delegation_skills
    from runtime.execution.suckers._delegation_skills_agent import _call_agent

    calls = []

    def failed(**kwargs):
        calls.append(kwargs)
        return {"agent_id": "coder", "output": "", "success": False, "error": "connection timeout"}

    monkeypatch.setattr("runtime.execution.subagents.call_subagent", failed)
    monkeypatch.setattr(delegation_skills, "_allowed_agent_ids", lambda: {"coder"})
    monkeypatch.setattr(delegation_skills, "_check_absolute_cap", lambda *_a, **_kw: (0, True))
    monkeypatch.setattr(delegation_skills, "_record_delegation", lambda *_a, **_kw: None)
    result = _call_agent("coder", "write code", output_files=["code.py"])
    assert not result["success"]
    assert len(calls) == 1
    assert calls[0]["output_files"] == ["code.py"]


def test_timed_out_child_output_is_not_accepted_after_it_finishes(tmp_path):
    from runtime.safety.approval.cancellation import current_cancellation_token

    parent, log = _host(tmp_path)
    finished = threading.Event()

    def runner(*_args, **_kwargs):
        (tmp_path / "out.txt").write_text("partial", encoding="utf-8")
        token = current_cancellation_token()
        try:
            while not token.is_cancelled:
                time.sleep(0.005)
            return "late completion"
        finally:
            finished.set()

    result = call_subagent(
        "coder",
        "write output",
        session=parent,
        output_files=["out.txt"],
        runner=runner,
        timeout_seconds=0.15,
    )
    assert result["status"] == "timeout"
    assert not result["success"] and "artifacts" not in result
    assert finished.wait(1)
    assert [row["phase"] for row in _events(log)] == ["assigned"]
    assert file_write_lease_snapshot(parent.metadata)["leases"][0]["owner"] != "parent-turn"


def test_handoff_rejects_oversized_files_and_forged_recorder(tmp_path):
    parent, _ = _host(tmp_path)
    with (tmp_path / "large.bin").open("wb") as handle:
        handle.truncate(32 * 1024 * 1024 + 1)
    with pytest.raises(ArtifactHandoffError, match="32 MiB"):
        ArtifactHandoff.prepare(parent, ["large.bin"], [])
    parent.metadata["_execution_handoff_recorder"] = {"write": "accept"}
    with pytest.raises(ArtifactHandoffError, match="durable host journal"):
        ArtifactHandoff.prepare(parent, [], ["out.txt"])


@pytest.mark.parametrize("existing", [False, True])
def test_failed_child_returns_unchanged_outputs_without_retry(tmp_path, existing):
    parent, log = _host(tmp_path)
    output = tmp_path / "out.txt"
    if existing:
        output.write_text("original", encoding="utf-8")
    calls = []

    def fail(*_args, **_kwargs):
        calls.append(True)
        raise RuntimeError("engine unavailable")

    result = call_subagent(
        "coder",
        "update output",
        session=parent,
        output_files=["out.txt"],
        runner=fail,
        timeout_seconds=3,
    )
    assert calls == [True]
    assert not result["success"] and result["retry_allowed"] is False
    assert result["artifact_handoff"]["phase"] == "aborted"
    assert "artifacts" not in result
    assert [row["phase"] for row in _events(log)] == ["assigned", "aborted"]
    assert acquire_file_write_lease(parent, output, owner="parent-turn").reentrant
    assert output.read_text(encoding="utf-8") == "original" if existing else not output.exists()


def test_abort_requires_finished_runner_and_survives_expired_parent(tmp_path):
    parent, log = _host(tmp_path)
    handoff = ArtifactHandoff.prepare(parent, [], ["out.txt"])
    handoff.begin("child")
    assert handoff.abort_unchanged() is None
    assert file_write_lease_snapshot(parent.metadata)["leases"][0]["owner"] == "child"
    handoff.parent_task = replace(
        handoff.parent_task,
        resources=replace(handoff.parent_task.resources, deadline=time.monotonic() - 1),
    )
    handoff.finished = True
    assert handoff.abort_unchanged()["phase"] == "aborted"
    assert handoff.abort_unchanged() is None
    with pytest.raises(ArtifactHandoffError, match="completed child"):
        handoff.accept()
    assert [row["phase"] for row in _events(log)] == ["assigned", "aborted"]


def test_partial_failure_keeps_all_output_leases_for_reconciliation(tmp_path):
    parent, log = _host(tmp_path)
    handoff = ArtifactHandoff.prepare(parent, [], ["unchanged.txt", "changed.txt"])
    handoff.begin("child")
    (tmp_path / "changed.txt").write_text("partial result", encoding="utf-8")
    handoff.finished = True
    with pytest.raises(WorkspaceContentDriftConflict, match="content changed"):
        handoff.abort_unchanged()
    assert not handoff.aborted and not handoff.accepted
    assert all(
        lease["owner"] == "child" for lease in file_write_lease_snapshot(parent.metadata)["leases"]
    )
    assert [row["phase"] for row in _events(log)] == ["assigned"]


def test_failed_abort_journal_cannot_return_ownership(tmp_path):
    parent, log = _host(tmp_path)
    handoff = ArtifactHandoff.prepare(parent, [], ["out.txt"])
    handoff.begin("child")
    handoff.finished = True
    handoff.recorder = HandoffRecorder(lambda _receipt: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError, match="disk full"):
        handoff.abort_unchanged()
    assert not handoff.aborted
    assert file_write_lease_snapshot(parent.metadata)["leases"][0]["owner"] == "child"
    assert [row["phase"] for row in _events(log)] == ["assigned"]


def test_undeclared_child_lease_prevents_unchanged_abort(tmp_path):
    parent, log = _host(tmp_path)
    handoff = ArtifactHandoff.prepare(parent, [], ["out.txt"])
    handoff.begin("child")
    acquire_file_write_lease(parent, tmp_path / "unexpected.txt", owner="child")
    handoff.finished = True
    with pytest.raises(FileWriteLeaseConflict, match="undeclared"):
        handoff.abort_unchanged()
    assert [row["phase"] for row in _events(log)] == ["assigned"]


def test_timed_out_unchanged_child_returns_lease_only_after_runner_stops(tmp_path, monkeypatch):
    parent, log = _host(tmp_path)
    release_worker = threading.Event()
    reclaimed = threading.Event()
    original = ArtifactHandoff.abort_unchanged

    def observe_reconciliation(self):
        receipt = original(self)
        if receipt is not None:
            reclaimed.set()
        return receipt

    monkeypatch.setattr(ArtifactHandoff, "abort_unchanged", observe_reconciliation)

    def runner(*_args, **_kwargs):
        assert release_worker.wait(3)
        return "late result"

    try:
        result = call_subagent(
            "coder",
            "write output",
            session=parent,
            output_files=["out.txt"],
            runner=runner,
            timeout_seconds=0.15,
        )
        assert result["status"] == "timeout" and result["retry_allowed"] is False
        assert not reclaimed.is_set()
        with pytest.raises(FileWriteLeaseConflict):
            acquire_file_write_lease(parent, tmp_path / "out.txt", owner="parent-turn")
    finally:
        release_worker.set()
    assert reclaimed.wait(2)
    assert acquire_file_write_lease(parent, tmp_path / "out.txt", owner="parent-turn").reentrant
    assert [row["phase"] for row in _events(log)] == ["assigned", "aborted"]
    assert "artifacts" not in result and not result["success"]


def test_native_codex_native_handoff_through_real_bridge_and_executor(tmp_path, monkeypatch):
    from runtime.execution.codex_backend import role_runner
    from runtime.execution.engines import select_execution_route
    from runtime.execution.parallel_agents import make_stack_subagent_runner
    from runtime.execution.suckers.registry import Skill, SkillRegistry
    from runtime.execution.tool_engine import ToolExecutor
    from runtime.execution.tool_engine.native_tool_execution import execute_native_tool_call
    from runtime.memory.journal import InMemoryJournal
    from runtime.platform.models import ParsedIntent
    from runtime.protocol import Turn
    from runtime.protocol.items import TurnParams
    from runtime.safety.auth import TrustEngine
    from runtime.sensing.gateway.realtime_execution import TurnExecutionRequest, bind_turn_execution

    stack = SimpleNamespace(
        planner=SimpleNamespace(plan=lambda: None),
        runtime=object(),
        executor=ToolExecutor(
            registry=SkillRegistry(),
            immunity=TrustEngine(trusted_sources=["skill://public/*"]),
            journal=InMemoryJournal(),
        ),
    )
    coder = SimpleNamespace(
        display_name="Coder", capabilities={"execution_backend": "codex_app_server"}
    )
    registry = SimpleNamespace(has=lambda name: name == "coder", get=lambda _name: coder)

    def write_report(path: str, content: str, **_kwargs):
        from pathlib import Path

        Path(path).write_text(content, encoding="utf-8")
        return {"path": path, "written": True}

    stack.executor.registry.register(
        Skill(
            name="write_report",
            description="Write a declared report file",
            trusted_source="skill://public/write_report",
            affinity=["file", "write"],
            handler=write_report,
        ),
        verify_tests=False,
    )
    trace = []

    def write(name, content):
        output, error = execute_native_tool_call(
            stack,
            {
                "id": name,
                "name": "write_report",
                "arguments": {"path": str(tmp_path / name), "content": content},
            },
        )
        assert not error, output

    def codex(_stack, _agent, goal, **_kwargs):
        shared = current_execution_request()
        trace.append("codex:implement")
        assert shared.task.parent_task_id
        assert (
            shared.task.artifacts.inputs[0].path.read_text(encoding="utf-8")
            == "Implement add(a, b)"
        )
        assert shared.task.artifacts.output_paths == (tmp_path / "code.py",)
        write("code.py", "def add(a, b):\n    return a + b\n")
        return role_runner.CodexRoleExecution("Implementation ready", True, "completed")

    monkeypatch.setattr(role_runner, "run_agent_role_sync", codex)
    runner = make_stack_subagent_runner(stack, agent_registry=registry)
    result = {}

    async def native(*_args, **_kwargs):
        trace.append("octopus:prepare")
        write("brief.txt", "Implement add(a, b)")
        result.update(
            await asyncio.to_thread(
                call_subagent,
                "coder",
                "Implement the brief",
                runner=runner,
                input_files=["brief.txt"],
                output_files=["code.py"],
                timeout_seconds=5,
            )
        )
        assert result["success"], result
        trace.append("octopus:verify")
        namespace = {}
        exec((tmp_path / "code.py").read_text(encoding="utf-8"), namespace)
        assert namespace["add"](2, 3) == 5
        parent = current_session()
        assert acquire_file_write_lease(
            parent, tmp_path / "code.py", owner=current_execution_request().task.task_id
        ).reentrant
        write("verification.txt", "add(2, 3) == 5: passed")

    turn = Turn(
        threadId="thread",
        params=TurnParams(threadId="thread", owner_actor_id="alice", tenant_id="tenant"),
    )
    turn.execution_workspace_path = str(tmp_path)
    log = EventLog(tmp_path / "events.jsonl")
    log.turn_started(turn.thread_id, turn)
    runtime = SimpleNamespace(_drive_react=native, _stack=stack)
    emitter = SimpleNamespace(notify=AsyncMock(), is_turn_interrupted=lambda _id: False)
    supervisor = bind_turn_execution(
        runtime, turn, log, emitter, object(), object(), select_execution_route()
    )
    intent = ParsedIntent(
        raw="build add",
        intent_type="task",
        normalized_goal="build add",
        user_context={"mode": "code", "workspace_path": str(tmp_path)},
    )
    asyncio.run(supervisor.execute(TurnExecutionRequest(intent, "build add", None)))
    assert trace == ["octopus:prepare", "codex:implement", "octopus:verify"]
    receipt = result["artifact_handoff"]
    assert (
        receipt["artifacts"][0]["sha256"]
        == hashlib.sha256((tmp_path / "code.py").read_bytes()).hexdigest()
    )
    handoffs = [row for row in _events(log) if row["event"] == "execution_handoff"]
    assert [row["phase"] for row in handoffs] == ["assigned", "accepted"]
