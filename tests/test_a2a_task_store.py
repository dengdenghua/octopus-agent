from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from runtime.memory.a2a_task_store import A2ATaskStore, canonical_a2a_state


def test_state_normalization_matches_a2a_1_0_enum() -> None:
    assert canonical_a2a_state(1) == "submitted"
    assert canonical_a2a_state("TASK_STATE_WORKING") == "working"
    assert canonical_a2a_state(3) == "completed"
    assert canonical_a2a_state("TASK_STATE_AUTH_REQUIRED") == "auth_required"


def test_task_and_events_are_durable_and_filterable(tmp_path) -> None:
    store = A2ATaskStore(tmp_path / "a2a")
    store.create(
        local_task_id="local-1",
        agent_id="remote-agent",
        context_id="ctx-1",
        request={"text": "research"},
    )
    updated = store.update(
        "local-1",
        status="TASK_STATE_WORKING",
        remote_task_id="remote-42",
        result={"id": "remote-42", "status": {"state": 2}},
        event_type="remote_status",
        event_payload={"state": 2},
    )
    assert updated["status"] == "working"
    assert updated["remote_task_id"] == "remote-42"

    reopened = A2ATaskStore(tmp_path / "a2a")
    assert reopened.get("local-1") == updated
    assert [event["event_type"] for event in reopened.events("local-1")] == [
        "submitted",
        "remote_status",
    ]
    assert reopened.list(agent_id="remote-agent", status="working")[0][
        "local_task_id"
    ] == "local-1"


def test_terminal_remote_state_cannot_be_reopened(tmp_path) -> None:
    store = A2ATaskStore(tmp_path / "a2a")
    store.create(local_task_id="local-1", agent_id="remote-agent", request={"text": "x"})
    completed = store.update("local-1", status=3, result={"answer": "done"})
    assert completed["status"] == "completed"
    assert completed["terminal_at"]

    with pytest.raises(ValueError, match="immutable"):
        store.update("local-1", status=2)


def test_unknown_filter_is_rejected_but_protocol_unknown_is_supported(tmp_path) -> None:
    store = A2ATaskStore(tmp_path / "a2a")
    with pytest.raises(ValueError, match="invalid"):
        store.list(status="nonsense")
    assert store.list(status="unknown") == []


def test_create_once_has_one_dispatch_owner_across_store_instances(tmp_path) -> None:
    root = tmp_path / "a2a"
    first = A2ATaskStore(root)
    second = A2ATaskStore(root)

    def claim(store: A2ATaskStore) -> bool:
        _task, created = store.create_once(
            local_task_id="same-request",
            agent_id="remote-agent",
            request={"text": "only once"},
        )
        return created

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, (first, second)))

    assert sorted(results) == [False, True]
    assert len(first.events("same-request")) == 1
