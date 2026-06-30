"""Group-level replayable search across blackboard + tasks + event log."""

from __future__ import annotations

from runtime.memory.cowork.async_work import AsyncWorkStore
from runtime.memory.cowork.group import MemberEvent
from runtime.memory.cowork.group_store import GroupStore
from runtime.memory.cowork.search import search_group


def test_empty_query_returns_nothing(tmp_path) -> None:
    store = GroupStore(base_dir=tmp_path)
    store.blackboard("t1").write("k", "v", writer="u")
    assert search_group(store, "t1", "") == []
    assert search_group(store, "t1", "   ") == []


def test_blackboard_match_with_writer_attribution(tmp_path) -> None:
    store = GroupStore(base_dir=tmp_path)
    board = store.blackboard("t1")
    board.write("decision", "ship the nutrition report", writer="alice")
    board.write("owner", "bob", writer="bob")

    hits = search_group(store, "t1", "nutrition")
    assert len(hits) == 1
    hit = hits[0]
    assert hit.kind == "blackboard"
    assert hit.title == "decision"
    assert hit.actor == "alice"
    assert "nutrition" in hit.snippet.lower()
    assert hit.ref == {"key": "decision", "state": "current"}


def test_key_match_outranks_value_match(tmp_path) -> None:
    store = GroupStore(base_dir=tmp_path)
    board = store.blackboard("t1")
    board.write("budget", "n/a", writer="u")  # term in the KEY (weight 3)
    board.write("notes", "watch the budget closely", writer="u")  # in VALUE (weight 1)

    hits = search_group(store, "t1", "budget")
    assert [h.title for h in hits] == ["budget", "notes"]
    assert hits[0].score > hits[1].score


def test_task_match_on_prompt_and_result(tmp_path) -> None:
    store = GroupStore(base_dir=tmp_path)
    async_store = AsyncWorkStore(base_dir=store.base_dir, group_store=store)
    task = async_store.assign("t1", "researcher", "scan competitor pricing", actor="u")
    async_store.complete(task.task_id, "found three rivals undercutting us")

    by_prompt = search_group(store, "t1", "competitor", async_store=async_store)
    assert any(h.kind == "task" for h in by_prompt)

    by_result = search_group(store, "t1", "rivals", async_store=async_store)
    hit = next(h for h in by_result if h.kind == "task")
    assert hit.actor == "researcher"
    assert hit.ref["task_id"] == task.task_id
    assert hit.ref["status"] == "done"


def test_event_log_is_searchable(tmp_path) -> None:
    store = GroupStore(base_dir=tmp_path)
    store.append("t1", MemberEvent(action="invite", actor="user",
                                   target_id="database-expert", target_kind="agent"))
    hits = search_group(store, "t1", "database-expert")
    hit = next(h for h in hits if h.kind == "event")
    assert hit.actor == "user"
    assert "database-expert" in hit.snippet
    assert hit.ref["seq"] == 1


def test_until_seq_bounds_event_search_for_replay(tmp_path) -> None:
    store = GroupStore(base_dir=tmp_path)
    store.append("t1", MemberEvent(action="invite", actor="u",
                                   target_id="alice", target_kind="agent"))  # seq 1
    store.append("t1", MemberEvent(action="invite", actor="u",
                                   target_id="zoltan", target_kind="agent"))  # seq 2

    # Searching the full log finds zoltan.
    assert any(h.title.startswith("u") and "zoltan" in h.snippet
               for h in search_group(store, "t1", "zoltan"))
    # Replaying to seq 1 hides the later event.
    assert search_group(store, "t1", "zoltan", until_seq=1) == []


def test_kinds_filter_restricts_surfaces(tmp_path) -> None:
    store = GroupStore(base_dir=tmp_path)
    store.blackboard("t1").write("topic", "alpha signal", writer="u")
    store.append("t1", MemberEvent(action="invite", actor="alpha",
                                   target_id="x", target_kind="agent"))

    only_board = search_group(store, "t1", "alpha", kinds=("blackboard",))
    assert {h.kind for h in only_board} == {"blackboard"}

    only_events = search_group(store, "t1", "alpha", kinds=("event",))
    assert {h.kind for h in only_events} == {"event"}


def test_cjk_substring_search(tmp_path) -> None:
    store = GroupStore(base_dir=tmp_path)
    store.blackboard("t1").write("结论", "进入个性化营养赛道", writer="eve")
    hits = search_group(store, "t1", "营养")
    assert len(hits) == 1
    assert hits[0].title == "结论"
    assert hits[0].actor == "eve"


def test_limit_caps_results(tmp_path) -> None:
    store = GroupStore(base_dir=tmp_path)
    board = store.blackboard("t1")
    for i in range(10):
        board.write(f"note-{i}", "shared keyword here", writer="u")
    hits = search_group(store, "t1", "keyword", limit=3)
    assert len(hits) == 3


def test_results_span_all_three_surfaces(tmp_path) -> None:
    store = GroupStore(base_dir=tmp_path)
    async_store = AsyncWorkStore(base_dir=store.base_dir, group_store=store)
    store.blackboard("t1").write("merger", "merger plan v2", writer="u")
    async_store.assign("t1", "analyst", "evaluate the merger", actor="u")
    store.append("t1", MemberEvent(action="mode", actor="merger", mode="project"))

    hits = search_group(store, "t1", "merger", async_store=async_store)
    assert {h.kind for h in hits} == {"blackboard", "task", "event"}
