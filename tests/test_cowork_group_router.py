"""/api/cowork/* thread-group HTTP layer: reads public, mutations attributed."""

from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from runtime.memory.cowork.async_work import AsyncWorkStore
from runtime.memory.cowork.group import MemberEvent
from runtime.memory.cowork.group_store import GroupStore
from runtime.memory.threads import ThreadStateStore
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


def test_atomic_roster_replace_preserves_humans_and_is_idempotent(tmp_path) -> None:
    c = _client(tmp_path)
    thread_id = "thread-roster"
    c.post(
        f"/api/cowork/{thread_id}/members",
        json={"target_id": "human-owner", "kind": "human"},
    )
    c.post(
        f"/api/cowork/{thread_id}/members",
        json={"target_id": "old-agent", "kind": "agent"},
    )

    replaced = c.put(
        f"/api/cowork/{thread_id}/roster",
        json={"agent_ids": ["new-agent", "critic", "new-agent"], "mode": "swarm"},
    )
    assert replaced.status_code == 200, replaced.json()
    body = replaced.json()
    assert [(item["action"], item["target_id"]) for item in body["events"]] == [
        ("leave", "old-agent"),
        ("invite", "new-agent"),
        ("invite", "critic"),
        ("mode", ""),
    ]
    assert body["state"]["mode"] == "swarm"
    assert {member["id"] for member in body["state"]["roster"]} == {
        "human-owner",
        "new-agent",
        "critic",
    }
    version = body["state"]["event_count"]

    unchanged = c.put(
        f"/api/cowork/{thread_id}/roster",
        json={"agent_ids": ["new-agent", "critic"], "mode": "swarm"},
    )
    assert unchanged.status_code == 200, unchanged.json()
    assert unchanged.json()["events"] == []
    assert unchanged.json()["state"]["event_count"] == version


def test_on_demand_agent_reference_add_remove_is_idempotent(tmp_path) -> None:
    store = GroupStore(base_dir=tmp_path)
    app = FastAPI()
    app.include_router(create_cowork_group_router(store=store))
    client = TestClient(app)

    added = client.post(
        "/api/cowork/thread-members/members",
        json={"target_id": "local_codex_cli", "kind": "agent"},
    )
    assert added.status_code == 200, added.json()
    assert added.json()["added"] is True
    assert added.json()["state"]["event_count"] == 1
    # Membership is only a dispatchable id reference; no clone or per-thread
    # owner/home record is introduced into the group schema. Synthetic local
    # CLI and mobile ids intentionally live outside the built-in AgentRegistry.
    assert store.events("thread-members")[0].target_id == "local_codex_cli"

    retried = client.post(
        "/api/cowork/thread-members/members",
        json={"target_id": "local_codex_cli", "kind": "agent"},
    )
    assert retried.status_code == 200, retried.json()
    assert retried.json()["added"] is False
    assert retried.json()["state"]["event_count"] == 1

    removed = client.delete("/api/cowork/thread-members/members/local_codex_cli")
    assert removed.status_code == 200, removed.json()
    assert removed.json()["removed"] is True
    assert removed.json()["state"]["event_count"] == 2

    remove_retry = client.delete("/api/cowork/thread-members/members/local_codex_cli")
    assert remove_retry.status_code == 200, remove_retry.json()
    assert remove_retry.json()["removed"] is False
    assert remove_retry.json()["state"]["event_count"] == 2


def test_on_demand_roster_accepts_registry_cli_and_mobile_ids_atomically(tmp_path) -> None:
    store = GroupStore(base_dir=tmp_path)
    app = FastAPI()
    app.include_router(create_cowork_group_router(store=store))
    client = TestClient(app)

    replaced = client.put(
        "/api/cowork/thread-roster-registry/roster",
        json={
            "agent_ids": ["advisor", "local_codex_cli", "mobile_phone1"],
            "mode": "swarm",
        },
    )

    assert replaced.status_code == 200, replaced.json()
    assert replaced.json()["state"]["mode"] == "swarm"
    assert {member["id"] for member in replaced.json()["state"]["roster"]} == {
        "advisor",
        "local_codex_cli",
        "mobile_phone1",
    }


def test_atomic_roster_replace_rolls_back_the_whole_diff_on_validation_error(tmp_path) -> None:
    c = _client(tmp_path)
    thread_id = "thread-roster-rollback"
    for member_id, kind in (("human-owner", "human"), ("old-agent", "agent")):
        c.post(
            f"/api/cowork/{thread_id}/members",
            json={"target_id": member_id, "kind": kind},
        )
    before = c.get(f"/api/cowork/{thread_id}").json()["state"]

    rejected = c.put(
        f"/api/cowork/{thread_id}/roster",
        json={"agent_ids": ["human-owner"], "mode": "swarm"},
    )
    assert rejected.status_code == 400
    after = c.get(f"/api/cowork/{thread_id}").json()["state"]
    assert after == before


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
    thread_store = ThreadStateStore()
    thread_store.ensure_thread(
        "thread-auth",
        metadata={"owner_actor_id": "alice", "tenant_id": "legacy:alice"},
    )
    app = FastAPI()
    app.include_router(
        create_cowork_group_router(
            store=GroupStore(base_dir=tmp_path),
            runtime=SimpleNamespace(thread_store=thread_store),
            identity_store=store,
            require_auth=True,
        )
    )
    client = TestClient(app)
    headers = {"Authorization": "Bearer sk-alice"}

    assert client.get("/api/cowork/thread-auth").status_code == 401
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
        headers=headers,
    )
    assert ok.status_code == 200
    body = client.get("/api/cowork/thread-auth", headers=headers).json()
    assert body["events"][0]["actor"] == "alice"


def test_cowork_and_collab_are_bound_to_thread_owner_and_tenant(tmp_path) -> None:
    identities = IdentityStore()
    identities.add(
        Identity(actor_id="alice", metadata={"tenant_id": "tenant-a"}),
        api_key_plaintext="sk-alice",
    )
    identities.add(
        Identity(actor_id="bob", metadata={"tenant_id": "tenant-b"}),
        api_key_plaintext="sk-bob",
    )
    thread_store = ThreadStateStore()
    thread_store.ensure_thread(
        "alice-private",
        metadata={"owner_actor_id": "alice", "tenant_id": "tenant-a"},
    )
    group_store = GroupStore(base_dir=tmp_path)
    group_store.append(
        "alice-private",
        MemberEvent(action="invite", actor="alice", target_id="seed-agent"),
    )
    group_store.blackboard("alice-private").write("private", "alice-only", writer="alice")
    async_store = AsyncWorkStore(base_dir=tmp_path, group_store=group_store)
    async_store.assign("alice-private", "seed-agent", "private task", actor="alice")

    app = FastAPI()
    app.include_router(
        create_cowork_group_router(
            store=group_store,
            async_store=async_store,
            runtime=SimpleNamespace(thread_store=thread_store),
            identity_store=identities,
            require_auth=True,
        )
    )
    client = TestClient(app)
    alice = {"Authorization": "Bearer sk-alice"}
    bob = {"Authorization": "Bearer sk-bob"}

    for path in (
        "/api/cowork/alice-private",
        "/api/collab/alice-private",
        "/api/cowork/alice-private/tasks",
    ):
        assert client.get(path, headers=bob).status_code == 404
        assert client.get(path, headers=alice).status_code == 200

    attacks = (
        (
            "/api/cowork/alice-private/members",
            {"target_id": "bob-agent", "kind": "agent"},
        ),
        ("/api/cowork/alice-private/mode", {"mode": "swarm"}),
        ("/api/cowork/alice-private/blackboard", {"key": "hijack", "value": True}),
        (
            "/api/cowork/alice-private/tasks",
            {"assignee": "bob-agent", "prompt": "steal context"},
        ),
    )
    event_count = len(group_store.events("alice-private"))
    task_count = len(async_store.list("alice-private"))
    for path, body in attacks:
        assert client.post(path, json=body, headers=bob).status_code == 404
    assert len(group_store.events("alice-private")) == event_count
    assert len(async_store.list("alice-private")) == task_count
    assert "hijack" not in group_store.blackboard_snapshot("alice-private")

    assert client.post(attacks[0][0], json=attacks[0][1], headers=alice).status_code == 200
    assert client.post(attacks[1][0], json=attacks[1][1], headers=alice).status_code == 200
    assert client.post(attacks[2][0], json=attacks[2][1], headers=alice).status_code == 200
    assert client.post(attacks[3][0], json=attacks[3][1], headers=alice).status_code == 200

    # Cowork cannot claim an arbitrary id and bypass the managed-thread path.
    assert client.get("/api/cowork/not-managed", headers=alice).status_code == 404


def test_collab_room_projection_preserves_team_room_membership(tmp_path) -> None:
    from runtime.memory.cowork.session import link_room
    from runtime.sensing.gateway.team_rooms_router import create_team_rooms_router

    identities = IdentityStore()
    identities.add(
        Identity(actor_id="alice", metadata={"tenant_id": "tenant-a"}),
        api_key_plaintext="sk-alice",
    )
    identities.add(
        Identity(actor_id="bob", metadata={"tenant_id": "tenant-b"}),
        api_key_plaintext="sk-bob",
    )
    thread_store = ThreadStateStore()
    thread_store.ensure_thread(
        "alice-room-thread",
        metadata={"owner_actor_id": "alice", "tenant_id": "tenant-a"},
    )
    group_store = GroupStore(base_dir=tmp_path / "cowork")
    rooms = create_team_rooms_router(
        state_path=tmp_path / "team_rooms.json",
        identity_store=identities,
        require_auth=True,
    )
    app = FastAPI()
    app.include_router(rooms)
    app.include_router(
        create_cowork_group_router(
            store=group_store,
            team_rooms_state_path=tmp_path / "team_rooms.json",
            team_rooms_router=rooms,
            runtime=SimpleNamespace(thread_store=thread_store),
            identity_store=identities,
            require_auth=True,
        )
    )
    client = TestClient(app)
    alice = {"Authorization": "Bearer sk-alice"}
    bob = {"Authorization": "Bearer sk-bob"}

    bob_room = client.post(
        "/api/teams",
        headers=bob,
        json={"name": "Bob private", "members": [{"name": "worker"}]},
    ).json()
    link_room(group_store, "alice-room-thread", bob_room["id"], actor="seed")

    # The thread owner may still use the room-independent group surface, but
    # cannot project or relink a Team Room they do not belong to.
    assert client.get("/api/cowork/alice-room-thread", headers=alice).status_code == 200
    assert client.get("/api/collab/alice-room-thread", headers=alice).status_code == 403
    assert (
        client.get("/api/cowork/alice-room-thread/search?q=private", headers=alice).status_code
        == 403
    )
    assert (
        client.post(
            "/api/collab/alice-room-thread/link-room",
            headers=alice,
            json={"room_id": bob_room["id"]},
        ).status_code
        == 403
    )

    alice_room = client.post(
        "/api/teams",
        headers=alice,
        json={"name": "Alice room", "members": [{"name": "worker"}]},
    ).json()
    assert (
        client.post(
            "/api/collab/alice-room-thread/link-room",
            headers=alice,
            json={"room_id": alice_room["id"]},
        ).status_code
        == 200
    )
    assert client.get("/api/collab/alice-room-thread", headers=alice).status_code == 200


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


def test_project_mode_auto_binds_project_for_workbench_tab(tmp_path) -> None:
    """Regression: switching a thread to 'project' mode previously only flipped
    the group mode — no Project OS project was ever created/bound, so the
    workbench 项目 tab (GET /api/projects/by-thread) had nothing to render
    (thread t0Wn5Zhvh3VUFwoAR2uP4M switched to project mode but by-thread 404'd).
    Entering project mode must ensure a real project exists and is bound."""
    from runtime.projectos.store import ProjectStore

    (tmp_path / "projects").mkdir(parents=True, exist_ok=True)
    project_store = ProjectStore(base_dir=str(tmp_path / "projects"))
    app = FastAPI()
    app.include_router(
        create_cowork_group_router(
            store=GroupStore(base_dir=tmp_path),
            project_store=project_store,
        )
    )
    c = TestClient(app)
    t = "thread-proj-mode"
    c.post(f"/api/cowork/{t}/members", json={"target_id": "alice", "kind": "agent"})
    c.post(f"/api/cowork/{t}/members", json={"target_id": "bob", "kind": "agent"})

    r = c.post(f"/api/cowork/{t}/mode", json={"mode": "project"})
    assert r.status_code == 200
    body = r.json()
    assert body["state"]["mode"] == "project"
    assert "bound_project_id" in body["state"]

    # The project is now visible via the workbench tab's by-thread lookup.
    state = project_store.project_for_thread(t)
    assert state is not None
    assert state.id == body["state"]["bound_project_id"]

    # Switching again reuses the same project (no duplicate creation).
    r2 = c.post(f"/api/cowork/{t}/mode", json={"mode": "project"})
    assert r2.json()["state"]["bound_project_id"] == state.id
