"""/api/cowork/* thread-group HTTP layer: reads public, mutations attributed."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from runtime.memory.cowork.group_store import GroupStore
from runtime.platform.ui.app import create_app
from runtime.safety.auth import Identity, IdentityStore
from runtime.sensing.gateway.cowork_group_router import create_cowork_group_router


def _client(tmp_path) -> TestClient:
    app = FastAPI()
    app.include_router(create_cowork_group_router(store=GroupStore(base_dir=tmp_path)))
    return TestClient(app)


def test_full_wechat_like_flow(tmp_path) -> None:
    c = _client(tmp_path)
    t = "thread-xyz"

    # Start a 1:1: pull in the human + one agent.
    c.post(f"/api/cowork/{t}/members", json={"target_id": "user", "kind": "human"})
    c.post(f"/api/cowork/{t}/members", json={"target_id": "alice", "kind": "agent"})
    state = c.get(f"/api/cowork/{t}").json()["state"]
    assert state["is_one_to_one"] is True
    assert {m["id"] for m in state["roster"]} == {"user", "alice"}

    # Mid-conversation, pull in a specialist with a from-join grant.
    r = c.post(
        f"/api/cowork/{t}/members",
        json={
            "target_id": "bob",
            "kind": "agent",
            "grant": {"scope": "from_join"},
            "at_message": 12,
        },
    )
    assert r.status_code == 200
    assert {m["id"] for m in r.json()["state"]["roster"]} == {"user", "alice", "bob"}

    # Switch to swarm and check responders follow the mode.
    c.post(f"/api/cowork/{t}/mode", json={"mode": "swarm"})
    body = c.get(f"/api/cowork/{t}").json()
    assert body["state"]["mode"] == "swarm"
    assert set(body["responders"]) == {"alice", "bob"}

    # Shared blackboard write is attributed and visible to the group.
    c.post(f"/api/cowork/{t}/blackboard", json={"key": "plan", "value": ["a", "b"]})
    assert c.get(f"/api/cowork/{t}").json()["blackboard"]["plan"] == ["a", "b"]

    # Remove alice — roster folds, blackboard survives.
    c.request("DELETE", f"/api/cowork/{t}/members/alice")
    after = c.get(f"/api/cowork/{t}").json()
    assert {m["id"] for m in after["state"]["roster"]} == {"user", "bob"}
    assert after["blackboard"]["plan"] == ["a", "b"]


def test_invalid_mode_rejected(tmp_path) -> None:
    c = _client(tmp_path)
    assert c.post("/api/cowork/t/mode", json={"mode": "bogus"}).status_code == 400


def test_search_endpoint_spans_surfaces_and_filters(tmp_path) -> None:
    c = _client(tmp_path)
    t = "thread-search"
    c.post(f"/api/cowork/{t}/members", json={"target_id": "nutrition-expert", "kind": "agent"})
    c.post(f"/api/cowork/{t}/blackboard", json={"key": "decision", "value": "enter nutrition"})

    body = c.get(f"/api/cowork/{t}/search", params={"q": "nutrition"}).json()
    assert body["query"] == "nutrition"
    kinds = {h["kind"] for h in body["hits"]}
    assert "blackboard" in kinds and "event" in kinds

    # kinds filter narrows the surfaces searched.
    only_board = c.get(
        f"/api/cowork/{t}/search", params={"q": "nutrition", "kinds": "blackboard"}
    ).json()["hits"]
    assert {h["kind"] for h in only_board} == {"blackboard"}

    # Empty query is a clean empty result, not an error.
    empty = c.get(f"/api/cowork/{t}/search", params={"q": ""})
    assert empty.status_code == 200
    assert empty.json()["hits"] == []


def test_presence_unread_and_read_receipts(tmp_path) -> None:
    c = _client(tmp_path)
    t = "thread-presence"
    c.post(f"/api/cowork/{t}/members", json={"target_id": "user", "kind": "human"})
    c.post(f"/api/cowork/{t}/members", json={"target_id": "alice", "kind": "agent"})
    c.post(f"/api/cowork/{t}/mode", json={"mode": "swarm"})  # more activity

    pres = c.get(f"/api/cowork/{t}/presence").json()["members"]
    user = next(m for m in pres if m["member_id"] == "user")
    assert user["unread"] > 0
    assert user["online"] is False

    # Heartbeat → online; mark-read → unread clears.
    assert c.post(f"/api/cowork/{t}/heartbeat", json={"member_id": "user"}).status_code == 200
    assert c.post(f"/api/cowork/{t}/read", json={"member_id": "user"}).status_code == 200

    after = c.get(f"/api/cowork/{t}/presence").json()["members"]
    user2 = next(m for m in after if m["member_id"] == "user")
    assert user2["unread"] == 0
    assert user2["online"] is True


def test_invite_requires_target(tmp_path) -> None:
    c = _client(tmp_path)
    assert c.post("/api/cowork/t/members", json={"kind": "agent"}).status_code == 422


def test_advanced_cowork_endpoints(tmp_path) -> None:
    c = _client(tmp_path)
    t = "thread-advanced"

    c.post(f"/api/cowork/{t}/members", json={"target_id": "db-agent"})
    c.post(f"/api/cowork/{t}/members", json={"target_id": "ui-agent"})

    nominated = c.get(
        f"/api/cowork/{t}/nominate",
        params={"text": "database indexing latency"},
    ).json()
    assert nominated["nominated"][0] == "db-agent"

    task = c.post(
        f"/api/cowork/{t}/tasks",
        json={"assignee": "db-agent", "prompt": "check indexes"},
    ).json()["task"]
    done = c.post(
        f"/api/cowork/{t}/tasks/{task['task_id']}/complete",
        json={"result": "indexes checked", "blackboard_key": "indexes"},
    ).json()
    assert done["blackboard"]["indexes"] == "indexes checked"
    assert c.get(f"/api/cowork/{t}/tasks").json()["tasks"][0]["status"] == "done"

    forked = c.post(
        f"/api/cowork/{t}/breakout",
        json={
            "child_thread": "child-advanced",
            "members": [{"id": "db-agent"}],
            "grant": {"scope": "summary"},
        },
    ).json()
    assert forked["members"] == ["db-agent"]

    merged = c.post(
        f"/api/cowork/{t}/breakout/child-advanced/merge",
        json={"summary": "side thread result"},
    ).json()
    assert merged["blackboard"]["breakout:child-advanced"]["status"] == "merged"

    catchup = c.get("/api/cowork/child-advanced/catchup/db-agent").json()
    assert catchup["member_id"] == "db-agent"
    assert catchup["summary_only"] is True


def test_mutations_require_auth_when_enabled(tmp_path) -> None:
    store = IdentityStore()
    store.add(Identity(actor_id="alice"), api_key_plaintext="sk-alice")
    app = FastAPI()
    app.include_router(
        create_cowork_group_router(
            store=GroupStore(base_dir=tmp_path),
            identity_store=store,
            require_auth=True,
        )
    )
    client = TestClient(app)

    assert client.get("/api/cowork/thread-auth").status_code == 200
    assert (
        client.post(
            "/api/cowork/thread-auth/members",
            json={"target_id": "alice", "kind": "agent"},
        ).status_code
        == 401
    )

    ok = client.post(
        "/api/cowork/thread-auth/members",
        json={"target_id": "alice", "kind": "agent"},
        headers={"Authorization": "Bearer sk-alice"},
    )
    assert ok.status_code == 200
    body = client.get("/api/cowork/thread-auth").json()
    assert body["events"][0]["actor"] == "alice"


def test_app_cowork_router_uses_shared_runtime_store(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OCTOPUS_DATA_DIR", str(tmp_path / "data"))
    app = create_app(journal_path=tmp_path / "data" / "events.jsonl")
    client = TestClient(app)

    response = client.post(
        "/api/cowork/thread-shared/tasks",
        json={"assignee": "worker", "prompt": "background check"},
    )

    assert response.status_code == 200
    task = response.json()["task"]
    stored = app.state.cowork_async_store.get(task["task_id"])
    assert stored is not None
    assert stored.prompt == "background check"
    assert app.state.cowork_runtime.async_store is app.state.cowork_async_store

    summary = client.get("/api/cowork/thread-shared/tasks/summary").json()
    assert summary["task_counts"]["pending"] == 1
    assert summary["runner_enabled"] is False


def test_health_endpoint_aggregates_runner_tasks_presence(tmp_path) -> None:
    from runtime.memory.cowork.async_work import AsyncWorkStore

    store = GroupStore(base_dir=tmp_path)
    app = FastAPI()
    app.include_router(create_cowork_group_router(store=store))
    c = TestClient(app)
    t = "thread-health"
    c.post(f"/api/cowork/{t}/members", json={"target_id": "user", "kind": "human"})
    c.post(f"/api/cowork/{t}/members", json={"target_id": "alice", "kind": "agent"})

    # Seed a failed task via the same-dir store the router reads.
    aw = AsyncWorkStore(base_dir=store.base_dir, group_store=store)
    task = aw.assign(t, "alice", "do x", actor="user")
    assert aw.claim(task.task_id)
    aw.fail(task.task_id, "boom")

    h = c.get(f"/api/cowork/{t}/health").json()
    assert h["roster_size"] == 2
    assert h["mode"] in ("chat", "cluster", "swarm", "project")
    assert h["runner"]["enabled"] is False  # no runtime attached in this client
    assert h["tasks"]["counts"]["failed"] == 1
    assert h["tasks"]["failures"][0]["error"] == "boom"
    assert h["presence"]["members"] == 2
    assert len(h["recent_events"]) >= 2


def test_health_endpoint_includes_runner_status_when_runtime_attached(tmp_path) -> None:
    from runtime.memory.cowork.async_runner import AsyncWorkRunner
    from runtime.memory.cowork.async_work import AsyncWorkStore
    from runtime.memory.cowork.collaboration_store import CollaborationStore
    from runtime.memory.cowork.runtime import CoworkRuntime

    store = GroupStore(base_dir=tmp_path)
    async_store = AsyncWorkStore(base_dir=store.base_dir, group_store=store)
    runner = AsyncWorkRunner(async_store, store, lambda _task, _context: "done")
    runtime = CoworkRuntime(
        group_store=store,
        async_store=async_store,
        collaboration_store=CollaborationStore(base_dir=store.base_dir),
        runner=runner,
        runner_enabled=True,
        runner_reason="test runner",
    )
    app = FastAPI()
    app.include_router(create_cowork_group_router(store=store, runtime=runtime))
    c = TestClient(app)
    t = "thread-runner-health"
    async_store.assign(t, "worker", "background work", actor="user")
    assert runner.tick_once() == 1

    h = c.get(f"/api/cowork/{t}/health").json()

    assert h["runner"]["enabled"] is True
    assert h["runner"]["reason"] == "test runner"
    assert h["runner"]["status"]["total_ticks"] == 1
    assert h["runner"]["status"]["last_ran_count"] == 1
    assert h["runner"]["status"]["last_error"] is None
