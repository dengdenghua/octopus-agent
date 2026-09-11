from pathlib import Path

import pytest

from runtime.memory.threads._event_log_helpers import thread_log_path
from runtime.memory.threads.event_log import EventLog
from runtime.memory.threads.store import ForkUnavailableError
from runtime.protocol.items import AgentMessageItem, Turn, TurnStatus, UserMessageItem
from runtime.sensing.gateway._thread_history_fork import seed_history
from runtime.sensing.gateway.realtime_thread_history import _flatten_turns_to_messages


def source(root):
    log = EventLog(thread_log_path(root, "parent"))
    log.thread_started("parent")
    turn = Turn(id="done", threadId="parent")
    log.turn_started("parent", turn)
    log.item_completed("parent", turn.id, UserMessageItem(text="hello"))
    log.item_completed("parent", turn.id, AgentMessageItem(text="answer"))
    log.turn_completed("parent", turn.id, TurnStatus.COMPLETED)
    expected, _, _ = _flatten_turns_to_messages(log.replay())
    log.turn_started("parent", Turn(id="running", threadId="parent"))
    log.item_started("parent", "running", UserMessageItem(text="unfinished"))
    return log, {"thread_id": "child", "values": {"messages": expected}}


def test_fork_only_seeds_verified_closed_prefix_and_leaves_files(tmp_path: Path):
    log, child = source(tmp_path)
    original = log._path.read_bytes()
    file = tmp_path / "work.txt"
    file.write_text("keep edits")
    seed_history(tmp_path, "parent", child)
    restored = EventLog(thread_log_path(tmp_path, "child")).replay()
    assert [t.id for t in restored] == ["done"]
    assert restored[0].thread_id == "child"
    assert restored[0].status == TurnStatus.COMPLETED
    assert _flatten_turns_to_messages(restored)[0] == child["values"]["messages"]
    assert log._path.read_bytes() == original
    assert file.read_text() == "keep edits"


def test_fork_refuses_mismatched_history_without_partial_log(tmp_path: Path):
    _, child = source(tmp_path)
    child["values"]["messages"][1]["content"] = "changed"
    with pytest.raises(ForkUnavailableError):
        seed_history(tmp_path, "parent", child)
    assert not thread_log_path(tmp_path, "child").exists()


def test_fork_refuses_active_turn_even_with_partial_assistant(tmp_path: Path):
    log, child = source(tmp_path)
    log.item_started("parent", "running", AgentMessageItem(text="partial"))
    child["values"]["messages"] = _flatten_turns_to_messages(log.replay())[0]
    with pytest.raises(ForkUnavailableError, match="active"):
        seed_history(tmp_path, "parent", child)


def test_failed_fork_does_not_leave_a_child_thread(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from runtime.memory.threads.store import ThreadStateStore
    from runtime.sensing.gateway.thread_state_router import create_thread_state_router

    store = ThreadStateStore()
    parent = store.create(
        values={
            "messages": [
                {"type": "human", "content": "hello"},
                {"type": "ai", "content": "stale answer"},
            ]
        }
    )
    source_log, _ = source(tmp_path)
    # Use a real source ID while preserving a deliberately mismatched snapshot.
    path = thread_log_path(tmp_path, parent["thread_id"])
    path.write_text(
        source_log._path.read_text().replace('"parent"', f'"{parent["thread_id"]}"'),
        encoding="utf-8",
    )
    created = []
    original = store.fork_thread

    def fork(*args, **kwargs):
        child = original(*args, **kwargs)
        created.append(child)
        return child

    monkeypatch.setattr(store, "fork_thread", fork)
    app = FastAPI()
    app.include_router(create_thread_state_router(store=store, logs_root=tmp_path))
    with TestClient(app) as client:
        response = client.post(f"/api/threads/{parent['thread_id']}/fork", json={})
    assert response.status_code == 409
    assert len(created) == 1
    assert store.get(created[0]["thread_id"]) is None
    assert not thread_log_path(tmp_path, created[0]["thread_id"]).exists()
    assert store.get(parent["thread_id"]) is not None
