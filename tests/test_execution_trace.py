from __future__ import annotations

from runtime.memory.diagnostics.execution_trace import build_execution_trace
from runtime.memory.diagnostics.trace_store import AgentTraceStore


def test_execution_trace_pairs_codex_tool_events_and_terminal() -> None:
    trace = build_execution_trace(
        [
            {
                "id": 1,
                "ts": "2026-09-05T00:00:00Z",
                "event_type": "TOOL_CALL_START",
                "item_id": "call-1",
                "payload": {
                    "engine": "codex",
                    "model": "gpt-5.6-sol",
                    "tool": "exec_shell",
                    "input": {"command": "pytest -q"},
                },
            },
            {
                "id": 2,
                "ts": "2026-09-05T00:00:01Z",
                "event_type": "TOOL_CALL_END",
                "item_id": "call-1",
                "payload": {
                    "engine": "codex",
                    "tool": "exec_shell",
                    "status": "success",
                    "output_preview": "2 passed",
                    "duration_ms": 1000,
                },
            },
            {
                "id": 3,
                "ts": "2026-09-05T00:00:02Z",
                "event_type": "REACT_COMPLETED",
                "payload": {"engine": "codex", "success": True},
            },
        ],
        thread_id="thread-1",
        turn_id="turn-1",
        task_id="task-1",
        agent_id="coder",
    )

    assert trace["schema"] == "octopus.execution_trace.v1"
    assert trace["engine"] == "codex"
    assert trace["model"] == "gpt-5.6-sol"
    assert trace["steps"][0]["status"] == "completed"
    assert trace["steps"][0]["output"] == "2 passed"
    assert trace["outcome"]["status"] == "completed"
    assert trace["integrity"]["complete"] is True


def test_execution_trace_marks_missing_lifecycle_as_incomplete() -> None:
    trace = build_execution_trace(
        [
            {
                "id": 1,
                "ts": "2026-09-05T00:00:00Z",
                "event_type": "TOOL_CALL_START",
                "item_id": "call-open",
                "payload": {"engine": "octopus", "tool": "read_file"},
            },
            {
                "id": 2,
                "ts": "2026-09-05T00:00:01Z",
                "event_type": "REACT_COMPLETED",
                "payload": {"engine": "octopus", "success": True},
            },
        ],
        turn_id="turn-2",
    )

    assert trace["integrity"]["orphan_start_count"] == 1
    assert trace["integrity"]["complete"] is False


def test_trace_store_exposes_the_same_read_model(tmp_path) -> None:
    store = AgentTraceStore(tmp_path / "trace.sqlite")
    store.record_event(
        event_type="TOOL_CALL_START",
        payload={"engine": "octopus", "tool": "read_file", "input": {"path": "a.txt"}},
        thread_id="thread-3",
        turn_id="turn-3",
        item_id="call-3",
    )
    store.record_event(
        event_type="TOOL_CALL_END",
        payload={"engine": "octopus", "tool": "read_file", "status": "success"},
        thread_id="thread-3",
        turn_id="turn-3",
        item_id="call-3",
    )
    store.record_event(
        event_type="REACT_COMPLETED",
        payload={"engine": "octopus", "success": True},
        thread_id="thread-3",
        turn_id="turn-3",
    )

    trace = store.execution_trace(thread_id="thread-3", turn_id="turn-3")
    assert trace["engine"] == "octopus"
    assert trace["integrity"]["complete"] is True
