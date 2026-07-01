"""Cowork v2 features: agent-initiated invites, catch-up, nomination,
competence, async work, breakout, replay."""

from __future__ import annotations

import sqlite3

from runtime.memory.cowork import async_work, breakout, catchup, nominate, service
from runtime.memory.cowork.group import ContextGrant
from runtime.memory.cowork.group_store import GroupStore


# ── agent-initiated invites (service layer) ──────────────────────────────────
def test_agent_can_invite_another_agent(tmp_path) -> None:
    s = GroupStore(base_dir=tmp_path)
    service.invite_member(s, "t", actor="user", target_id="lead", kind="agent")
    # the lead agent pulls in a specialist — actor is an agent, not a human
    ev = service.invite_member(s, "t", actor="lead", target_id="db-expert", kind="agent")
    assert ev.actor == "lead"
    state = s.state("t")
    assert {m.id for m in state.roster} == {"lead", "db-expert"}
    assert state.member("db-expert").invited_by == "lead"  # agent-initiated


# ── replay / time-travel (fold until_seq) ────────────────────────────────────
def test_replay_to_a_point(tmp_path) -> None:
    s = GroupStore(base_dir=tmp_path)
    service.invite_member(s, "t", actor="u", target_id="a", kind="agent")  # seq 1
    service.invite_member(s, "t", actor="u", target_id="b", kind="agent")  # seq 2
    service.remove_member(s, "t", actor="u", target_id="a")                 # seq 3
    assert {m.id for m in s.state("t").roster} == {"b"}          # now
    assert {m.id for m in s.state("t", until_seq=2).roster} == {"a", "b"}  # before removal
    assert {m.id for m in s.state("t", until_seq=1).roster} == {"a"}


# ── catch-up brief ───────────────────────────────────────────────────────────
def test_catchup_respects_grant_and_lists_board(tmp_path) -> None:
    s = GroupStore(base_dir=tmp_path)
    service.invite_member(s, "t", actor="u", target_id="newbie", kind="agent",
                          grant=ContextGrant(scope="from_join"), at_message=5)
    msgs = [f"m{i}" for i in range(10)]
    cu = catchup.build_catchup(s.state("t"), "newbie", msgs, {"decision": "x", "plan": "y"})
    assert cu is not None
    assert cu.visible_count == 5  # messages 5..9 only (from_join)
    assert cu.blackboard_keys == ["decision", "plan"]
    assert "newbie" in cu.roster
    assert isinstance(cu.render(), str) and "协作" in cu.render()
    assert catchup.build_catchup(s.state("t"), "stranger", msgs, {}) is None


# ── nomination: relevance, gate, competence ──────────────────────────────────
def test_relevance_and_gate() -> None:
    assert nominate.relevance("fix the database query", "db-expert", "database") > 0.4
    assert nominate.relevance("fix the css layout", "db-expert", "database") == 0.0
    # gate keeps only relevant participants; empty text → everyone
    parts = [("db-expert", "database"), ("css-guru", "frontend")]
    assert nominate.gate(parts, "optimize the database index") == ["db-expert"]
    assert set(nominate.gate(parts, "")) == {"db-expert", "css-guru"}


def test_competence_memory_and_suggest(tmp_path) -> None:
    store = nominate.CompetenceStore(base_dir=tmp_path)
    assert store.competence("a", "database") == 0.5  # unseen → neutral prior
    for ok in (True, True, False):
        store.record("a", "database", ok)
    assert abs(store.competence("a", "database") - 2 / 3) < 1e-6
    ranked = nominate.suggest(
        "tune the database", [("a", "database"), ("b", "frontend")], store
    )
    assert ranked and ranked[0]["agent_id"] == "a"
    assert all(r["agent_id"] != "b" for r in ranked)  # b irrelevant → excluded


# ── async coworkers ──────────────────────────────────────────────────────────
def test_async_task_result_lands_on_shared_board(tmp_path) -> None:
    gs = GroupStore(base_dir=tmp_path)
    aw = async_work.AsyncWorkStore(base_dir=tmp_path, group_store=gs)
    task = aw.assign("t", "db-expert", "find the slow query", actor="user")
    assert [x.task_id for x in aw.pending("t")] == [task.task_id]
    assert aw.claim(task.task_id) is True
    assert aw.claim(task.task_id) is False  # already claimed
    aw.complete(task.task_id, "it's the N+1 on orders")
    assert aw.pending("t") == []
    board = gs.blackboard_snapshot("t")
    # result posted to the shared board, attributed to the assignee
    assert any(v == "it's the N+1 on orders" for v in board.values())
    audit = gs.blackboard("t").audit()["writers_by_key"]
    assert any("db-expert" in w for w in audit.values())


def test_async_work_reads_self_heal_missing_schema(tmp_path) -> None:
    gs = GroupStore(base_dir=tmp_path)
    aw = async_work.AsyncWorkStore(base_dir=tmp_path, group_store=gs)
    with sqlite3.connect(str(tmp_path / "async_work.db")) as conn:
        conn.execute("DROP TABLE async_tasks")

    assert aw.list("t") == []
    task = aw.assign("t", "db-expert", "recover schema", actor="user")
    assert [x.task_id for x in aw.pending("t")] == [task.task_id]


# ── breakout threads ─────────────────────────────────────────────────────────
def test_breakout_fork_and_merge_back(tmp_path) -> None:
    s = GroupStore(base_dir=tmp_path)
    service.invite_member(s, "parent", actor="u", target_id="user", kind="human")
    res = breakout.fork(
        s, "parent", "child-1", actor="user",
        members=[{"id": "a", "kind": "agent"}, {"id": "b", "kind": "agent"}],
        grant=ContextGrant(scope="from_join"), at_message=10,
    )
    assert set(res["members"]) == {"a", "b"}
    # child seeded with the subset
    assert {m.id for m in s.state("child-1").roster} == {"a", "b"}
    # parent records the breakout; child knows its origin
    assert s.blackboard("parent").read("breakout:child-1")["status"] == "open"
    assert s.blackboard("child-1").read("forked_from")["parent"] == "parent"
    # merge conclusion back to parent
    breakout.merge_back(s, "child-1", "parent", actor="user", summary="use index X")
    assert s.blackboard("parent").read("breakout:child-1:summary") == "use index X"
    assert s.blackboard("parent").read("breakout:child-1")["status"] == "merged"
