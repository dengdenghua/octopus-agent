"""GroupStore persistence: ordered event log + thread-scoped shared blackboard."""

from __future__ import annotations

import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from runtime.memory.cowork.group import MemberEvent
from runtime.memory.cowork.group_store import GroupStore


def test_append_assigns_monotonic_seq_and_folds(tmp_path) -> None:
    store = GroupStore(base_dir=tmp_path)
    store.append(
        "t1", MemberEvent(action="invite", actor="u", target_id="user", target_kind="human")
    )
    store.append(
        "t1", MemberEvent(action="invite", actor="u", target_id="alice", target_kind="agent")
    )
    events = store.events("t1")
    assert [e.seq for e in events] == [1, 2]
    assert all(e.ts for e in events)  # store stamps timestamps
    state = store.state("t1")
    assert {m.id for m in state.roster} == {"user", "alice"}


def test_member_reference_retries_are_cross_store_idempotent(tmp_path) -> None:
    first = GroupStore(base_dir=tmp_path)
    second = GroupStore(base_dir=tmp_path)
    ready = Barrier(2)

    def add(store: GroupStore) -> bool:
        ready.wait(timeout=5)
        changed, _state = store.ensure_member(
            "thread-members",
            MemberEvent(
                action="invite",
                actor="owner",
                target_id="advisor",
                target_kind="agent",
            ),
        )
        return changed is not None

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(add, (first, second)))

    assert sorted(outcomes) == [False, True]
    assert [event.action for event in first.events("thread-members")] == ["invite"]

    removed, state = first.remove_member_if_present(
        "thread-members",
        actor="owner",
        member_id="advisor",
    )
    assert removed is not None and state.member("advisor") is None
    removed_again, unchanged = second.remove_member_if_present(
        "thread-members",
        actor="owner",
        member_id="advisor",
    )
    assert removed_again is None and unchanged.event_count == 2


def test_threads_are_isolated(tmp_path) -> None:
    store = GroupStore(base_dir=tmp_path)
    store.append(
        "t1", MemberEvent(action="invite", actor="u", target_id="alice", target_kind="agent")
    )
    store.append(
        "t2", MemberEvent(action="invite", actor="u", target_id="bob", target_kind="agent")
    )
    assert {m.id for m in store.state("t1").roster} == {"alice"}
    assert {m.id for m in store.state("t2").roster} == {"bob"}
    # seq restarts per thread
    assert store.events("t2")[0].seq == 1


def test_shared_blackboard_is_thread_scoped_and_survives_leave(tmp_path) -> None:
    store = GroupStore(base_dir=tmp_path)
    store.append(
        "t1", MemberEvent(action="invite", actor="u", target_id="alice", target_kind="agent")
    )
    board = store.blackboard("t1")
    board.write("decision", "ship it", writer="alice")

    # A different thread sees its own (empty) board.
    assert store.blackboard_snapshot("t2") == {}
    assert store.blackboard_snapshot("t1")["decision"] == "ship it"

    # Remove alice — her blackboard write must remain (attributed).
    store.append("t1", MemberEvent(action="leave", actor="u", target_id="alice"))
    assert "alice" not in {m.id for m in store.state("t1").roster}
    assert store.blackboard_snapshot("t1")["decision"] == "ship it"


def test_state_survives_a_fresh_store_instance(tmp_path) -> None:
    GroupStore(base_dir=tmp_path).append(
        "t1", MemberEvent(action="mode", actor="u", mode="cluster")
    )
    # A new instance over the same dir reads the persisted log.
    assert GroupStore(base_dir=tmp_path).state("t1").mode == "cluster"


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows cannot delete an open sqlite file; removed-under-live-store is a POSIX-only scenario",
)
def test_store_recovers_if_base_dir_is_removed(tmp_path) -> None:
    store = GroupStore(base_dir=tmp_path / "cowork")
    shutil.rmtree(store.base_dir)

    assert store.events("missing-thread") == []
