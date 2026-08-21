"""Tests for lane-H subagent isolation telemetry.

The bridge now attaches structured telemetry to every subagent
result so the caller can introspect what happened without seeing
the subagent's intermediate ReAct steps:

  * ``iteration_count`` — how many rounds the subagent ran
  * ``files_touched`` — paths the subagent wrote/edited

These fields complement the existing ``output`` (Final Answer text)
and ``success`` flag. Together they give the caller everything it
needs to decide what to do next, without polluting parent context.
"""

from __future__ import annotations

from typing import Any

from runtime.execution.subagents import bridge
from runtime.execution.suckers.blackboard_skills import _bb_write
from runtime.memory.runtime_state.blackboard import get_blackboard
from runtime.platform.process.session import Session, current_session, session_scope


def _restore_runner(orig):
    bridge._RUNNER = orig


def test_no_op_runner_returns_files_touched_empty(monkeypatch) -> None:
    """No file writes → files_touched is an empty list, not missing."""
    captured: dict[str, Any] = {}

    def _runner(prompt, *, subagent_name, context):
        captured["prompt"] = prompt
        captured["context"] = context
        return "I read some stuff. Final Answer: ok."

    orig = bridge._RUNNER
    bridge._RUNNER = _runner
    try:
        result = bridge.call_subagent(agent_id="explore", prompt="look around")
        assert result["success"] is True
        assert result["files_touched"] == []
        assert result["iteration_count"] == 0
        assert "ok" in result["output"]
    finally:
        _restore_runner(orig)


def test_files_touched_captured_via_emitter(monkeypatch) -> None:
    """When the subagent emits sub_tool_end events for write skills,
    bridge captures the touched paths into the augmented result."""

    def _runner(prompt, *, subagent_name, context):
        emitter = context.get("event_emitter")
        # Simulate three tool calls: read_file (not write), write_text_file,
        # then edit_file (success), then read_file again
        emitter(
            {
                "type": "sub_tool_end",
                "skill": "read_file",
                "args": {"path": "src/a.py"},
                "status": "success",
                "round": 1,
            }
        )
        emitter(
            {
                "type": "sub_tool_end",
                "skill": "write_text_file",
                "args": {"path": "out/report.md"},
                "status": "success",
                "round": 2,
            }
        )
        emitter(
            {
                "type": "sub_tool_end",
                "skill": "edit_file",
                "args": {"path": "src/a.py"},
                "status": "success",
                "round": 3,
            }
        )
        # A failed write should NOT be counted
        emitter(
            {
                "type": "sub_tool_end",
                "skill": "edit_file",
                "args": {"path": "src/b.py"},
                "status": "failed",
                "round": 4,
            }
        )
        return "Final Answer: done."

    orig = bridge._RUNNER
    bridge._RUNNER = _runner
    try:
        result = bridge.call_subagent(agent_id="explore", prompt="patch the bug")
        assert result["success"] is True
        # Both successful writes captured, in emission order, no dups.
        assert result["files_touched"] == ["out/report.md", "src/a.py"]
        # The skill we counted highest round on
        assert result["iteration_count"] >= 3
    finally:
        _restore_runner(orig)


def test_files_touched_dedups(monkeypatch) -> None:
    """Same file written twice → only one entry."""

    def _runner(prompt, *, subagent_name, context):
        emitter = context.get("event_emitter")
        emitter(
            {
                "type": "sub_tool_end",
                "skill": "edit_file",
                "args": {"path": "x.py"},
                "status": "success",
                "round": 1,
            }
        )
        emitter(
            {
                "type": "sub_tool_end",
                "skill": "edit_file",
                "args": {"path": "x.py"},
                "status": "success",
                "round": 2,
            }
        )
        return "ok"

    orig = bridge._RUNNER
    bridge._RUNNER = _runner
    try:
        result = bridge.call_subagent(agent_id="x", prompt="p")
        assert result["files_touched"] == ["x.py"]
    finally:
        _restore_runner(orig)


def test_runner_exception_still_includes_envelope(monkeypatch) -> None:
    """Even on runner failure, the augmented envelope keeps a stable
    shape so callers always see iteration_count / files_touched
    fields.
    """

    def _runner(prompt, *, subagent_name, context):
        raise RuntimeError("boom")

    orig = bridge._RUNNER
    bridge._RUNNER = _runner
    try:
        result = bridge.call_subagent(agent_id="x", prompt="p")
        assert result["success"] is False
        assert "boom" in result["error"]
        # Envelope still complete
        assert result["files_touched"] == []
        assert result["iteration_count"] == 0
    finally:
        _restore_runner(orig)


def test_external_emitter_still_called(monkeypatch) -> None:
    """The bridge's tracking emitter must NOT swallow events; the
    user-supplied emitter still gets every call."""
    received: list[dict] = []

    def _emitter(event: dict) -> None:
        received.append(event)

    def _runner(prompt, *, subagent_name, context):
        emitter = context.get("event_emitter")
        emitter(
            {
                "type": "sub_tool_end",
                "skill": "read_file",
                "args": {"path": "x"},
                "status": "success",
                "round": 1,
            }
        )
        return "ok"

    orig = bridge._RUNNER
    bridge._RUNNER = _runner
    try:
        bridge.call_subagent(
            agent_id="x",
            prompt="p",
            event_emitter=_emitter,
        )
        # Bridge now emits subagent_spawned (before run) + the runner's
        # sub_tool_end + subagent_finished (after run). The user-supplied
        # emitter must see all three (annotated with the codename).
        types = [e.get("type") for e in received]
        assert types == ["subagent_spawned", "sub_tool_end", "subagent_finished"]
        # The runner-emitted tool event still passes through with its
        # original payload intact.
        tool_evt = received[1]
        assert tool_evt["skill"] == "read_file"
        # Annotated with subagent identity for downstream timeline grouping.
        assert tool_evt.get("subagent_codename")
        assert tool_evt.get("subagent_avatar")
    finally:
        _restore_runner(orig)


def test_trace_context_is_attached_to_result_and_events(monkeypatch) -> None:
    received: list[dict[str, Any]] = []

    def _runner(prompt, *, subagent_name, context):
        assert context["thread_id"] == "thread-1"
        assert context["turn_id"] == "turn-1"
        assert context["parent_task_id"] == "task-parent"
        emitter = context.get("event_emitter")
        emitter(
            {
                "type": "sub_tool_end",
                "skill": "read_file",
                "args": {"path": "x"},
                "status": "success",
                "round": 1,
            }
        )
        return "ok"

    orig = bridge._RUNNER
    bridge._RUNNER = _runner
    try:
        result = bridge.call_subagent(
            agent_id="x",
            prompt="p",
            context={
                "thread_id": "thread-1",
                "turn_id": "turn-1",
                "parent_task_id": "task-parent",
                "run_id": "run-1",
                "trace_id": "trace-1",
                "source": "unit-test",
            },
            event_emitter=received.append,
        )
    finally:
        _restore_runner(orig)

    assert result["trace"] == {
        "thread_id": "thread-1",
        "turn_id": "turn-1",
        "parent_task_id": "task-parent",
        "run_id": "run-1",
        "trace_id": "trace-1",
        "source": "unit-test",
    }
    assert result["thread_id"] == "thread-1"
    assert result["turn_id"] == "turn-1"
    assert [event["type"] for event in received] == [
        "subagent_spawned",
        "sub_tool_end",
        "subagent_finished",
    ]
    assert all(event["trace"]["thread_id"] == "thread-1" for event in received)
    assert all(event["trace"]["turn_id"] == "turn-1" for event in received)
    assert received[1]["parent_task_id"] == "task-parent"


def test_trace_context_falls_back_to_session(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def _runner(prompt, *, subagent_name, context):
        captured["context"] = context
        return "ok"

    orig = bridge._RUNNER
    bridge._RUNNER = _runner
    try:
        result = bridge.call_subagent(
            agent_id="x",
            prompt="p",
            session=Session(thread_id="thread-session", turn_id="turn-session"),
        )
    finally:
        _restore_runner(orig)

    assert captured["context"]["thread_id"] == "thread-session"
    assert captured["context"]["turn_id"] == "turn-session"
    assert result["trace"] == {
        "thread_id": "thread-session",
        "turn_id": "turn-session",
    }


def test_timeout_worker_inherits_ambient_session_and_blackboard_scope() -> None:
    captured: dict[str, Any] = {}
    turn_id = "turn-ambient-timeout-worker"

    def _runner(prompt, *, subagent_name, context):
        del prompt, subagent_name, context
        active = current_session()
        captured["turn_id"] = active.turn_id if active is not None else None
        captured["write"] = _bb_write("worker-result", {"ok": True})
        return "ok"

    orig = bridge._RUNNER
    bridge._RUNNER = _runner
    try:
        with session_scope(Session(thread_id="thread-ambient", turn_id=turn_id)):
            result = bridge.call_subagent(
                agent_id="x",
                prompt="p",
                timeout_seconds=2,
            )
    finally:
        _restore_runner(orig)

    assert result["success"] is True
    assert captured["turn_id"] == turn_id
    assert captured["write"]["ok"] is True
    assert get_blackboard(turn_id).read("worker-result") == {"ok": True}


def test_flipped_child_keeps_parent_artifact_root(tmp_path, monkeypatch) -> None:
    captured: dict[str, Any] = {}
    monkeypatch.setenv("OCTOPUS_DATA_DIR", str(tmp_path))

    def _runner(prompt, *, subagent_name, context):
        del prompt, subagent_name, context
        active = current_session()
        assert active is not None
        captured["thread_id"] = active.thread_id
        captured["artifact_root"] = active.metadata.get("_artifact_output_root")
        return "ok"

    orig = bridge._RUNNER
    bridge._RUNNER = _runner
    try:
        result = bridge.call_subagent(
            agent_id="x",
            prompt="p",
            session=Session(
                thread_id="parent-thread",
                turn_id="parent-turn",
                metadata={"mode": "code"},
            ),
            context={"flip_subagent_thread": True},
        )
    finally:
        _restore_runner(orig)

    assert result["success"] is True
    assert captured["thread_id"] != "parent-thread"
    assert captured["artifact_root"] == str(
        tmp_path / "workspaces" / "parent-thread" / "output" / "final"
    )


def test_parent_message_count_unchanged(monkeypatch) -> None:
    """The parent agent observes the subagent through ONE return
    value, not N steps. The bridge contract is exactly: caller gets
    a single dict back regardless of how many internal sub-tool
    rounds happened. (This is implicit in the API, but pin it
    against accidental future shape changes.)
    """

    def _runner(prompt, *, subagent_name, context):
        emitter = context.get("event_emitter")
        # 20 rounds of internal tool calls
        for i in range(20):
            emitter(
                {
                    "type": "sub_tool_end",
                    "skill": "read_file",
                    "args": {"path": f"f{i}.py"},
                    "status": "success",
                    "round": i + 1,
                }
            )
        return "Synthesised summary."

    orig = bridge._RUNNER
    bridge._RUNNER = _runner
    try:
        result = bridge.call_subagent(agent_id="x", prompt="p")
        # The parent's "view" is exactly this dict — no list of steps
        # exposed. Files_touched is empty because read_file isn't a
        # write tool.
        assert isinstance(result, dict)
        assert result["output"] == "Synthesised summary."
        assert result["files_touched"] == []
        assert result["iteration_count"] == 20
        # Sanity: no leakage of N step entries into result
        assert "steps" not in result
        assert "messages" not in result
    finally:
        _restore_runner(orig)
