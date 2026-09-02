from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from runtime.memory.threads import ThreadPermanentlyDeletedError, ThreadStateStore
from runtime.memory.threads.event_log import EventLog, list_threads
from runtime.sensing.gateway.thread_state_router import create_thread_state_router


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(create_thread_state_router(store=ThreadStateStore()))
    return TestClient(app)


def test_thread_state_crud_uses_api_prefix_only() -> None:
    client = _client()

    created = client.post(
        "/api/threads",
        json={"metadata": {"mode": "chat"}, "values": {"title": "Hello"}},
    )
    assert created.status_code == 200
    thread_id = created.json()["thread_id"]

    assert client.get(f"/api/threads/{thread_id}").status_code == 200
    assert client.get(f"/api/threads/{thread_id}/state").status_code == 200

    search = client.post("/api/threads/search", json={"metadata": {"mode": "chat"}})
    assert search.status_code == 200
    assert [item["thread_id"] for item in search.json()] == [thread_id]
    assert search.json()[0]["values"]["title"] == "Hello"

    assert client.post("/threads").status_code == 404
    assert client.get(f"/threads/{thread_id}").status_code == 404


def test_thread_search_projects_dotted_sidebar_fields() -> None:
    client = _client()
    created = client.post(
        "/api/threads",
        json={
            "metadata": {"mode": "chat", "agent": "coder"},
            "values": {
                "title": "New chat",
                "messages": [
                    {"type": "system", "content": "internal"},
                    {"type": "human", "content": "Compact sidebar row"},
                    {"type": "ai", "content": "large history"},
                ],
                "artifacts": ["large artifact"],
            },
        },
    ).json()

    response = client.post(
        "/api/threads/search",
        json={
            "limit": 20,
            "select": [
                "thread_id",
                "updated_at",
                "metadata",
                "values.title",
                "values.sidebar_title_source",
            ],
        },
    )

    assert response.status_code == 200
    assert response.json() == [
        {
            "thread_id": created["thread_id"],
            "updated_at": created["updated_at"],
            "metadata": {"mode": "chat", "agent": "coder"},
            "values": {
                "title": "New chat",
                "sidebar_title_source": "Compact sidebar row",
            },
        }
    ]


def test_thread_state_search_get_returns_sidebar_shape() -> None:
    client = _client()
    created = client.post(
        "/api/threads",
        json={
            "values": {
                "title": "Routing notes",
                "messages": [{"type": "human", "content": "realtime only"}],
            },
        },
    )
    assert created.status_code == 200

    response = client.get("/api/threads/search?q=realtime&limit=5")
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["threads"]) == 1
    assert payload["threads"][0]["title"] == "Routing notes"
    assert payload["threads"][0]["snippet"] == "realtime only"


def test_thread_delete_archives_realtime_event_log(tmp_path) -> None:
    logs_root = tmp_path / "threads"
    log = EventLog(logs_root / "th-realtime.jsonl")
    log.thread_started("th-realtime")

    store = ThreadStateStore()
    store.ensure_thread("th-realtime", values={"title": "Old chat"})
    app = FastAPI()
    app.include_router(create_thread_state_router(store=store, logs_root=logs_root))
    client = TestClient(app)

    response = client.delete("/api/threads/th-realtime")

    assert response.status_code == 204
    with pytest.raises(ThreadPermanentlyDeletedError):
        store.get("th-realtime")
    summaries = list_threads(logs_root)
    assert len(summaries) == 1
    assert summaries[0].thread_id == "th-realtime"
    assert summaries[0].archived is True


def test_archived_thread_is_hidden_from_state_reads(tmp_path) -> None:
    logs_root = tmp_path / "threads"
    log = EventLog(logs_root / "th-hidden.jsonl")
    log.thread_started("th-hidden")

    store = ThreadStateStore()
    store.ensure_thread("th-hidden", values={"title": "Should be gone"})
    app = FastAPI()
    app.include_router(create_thread_state_router(store=store, logs_root=logs_root))
    client = TestClient(app)

    assert client.delete("/api/threads/th-hidden").status_code == 204

    search = client.post("/api/threads/search", json={"limit": 20})
    assert search.status_code == 200
    assert [item["thread_id"] for item in search.json()] == []
    assert client.get("/api/threads/th-hidden").status_code == 404
    assert client.get("/api/threads/th-hidden/state").status_code == 404
    assert client.post("/api/threads/th-hidden/history", json={}).json() == []


def test_thread_delete_accepts_log_only_thread(tmp_path) -> None:
    logs_root = tmp_path / "threads"
    log = EventLog(logs_root / "th-log-only.jsonl")
    log.thread_started("th-log-only")

    app = FastAPI()
    app.include_router(create_thread_state_router(store=ThreadStateStore(), logs_root=logs_root))
    client = TestClient(app)

    response = client.delete("/api/threads/th-log-only")

    assert response.status_code == 204
    assert list_threads(logs_root)[0].archived is True


def test_thread_delete_refuses_canonical_project_binding_then_tombstones_after_detach(
    tmp_path,
) -> None:
    from runtime.projectos.model import Project
    from runtime.projectos.store import ProjectStore, ProjectThreadDeletingError

    thread_store = ThreadStateStore()
    thread_store.ensure_thread("thread-project-bound", values={"title": "Project"})
    project_store = ProjectStore(base_dir=tmp_path / "projects")
    project_store.save_project(Project(id="P-thread-bound", name="bound", goal="g"))
    project_store.bind_thread("thread-project-bound", "P-thread-bound")
    app = FastAPI()
    app.include_router(
        create_thread_state_router(
            store=thread_store,
            project_store=project_store,
        )
    )
    client = TestClient(app)

    refused = client.delete("/api/threads/thread-project-bound")

    assert refused.status_code == 409, refused.json()
    assert refused.json()["detail"]["code"] == "THREAD_PROJECT_BOUND"
    assert refused.json()["detail"]["project_id"] == "P-thread-bound"
    assert thread_store.get("thread-project-bound") is not None
    assert project_store.project_for_thread("thread-project-bound").id == "P-thread-bound"

    project_store.unbind_thread(
        "thread-project-bound",
        expected_project_id="P-thread-bound",
    )
    deleted = client.delete("/api/threads/thread-project-bound")

    assert deleted.status_code == 204
    with pytest.raises(ThreadPermanentlyDeletedError):
        thread_store.get("thread-project-bound")
    with pytest.raises(ProjectThreadDeletingError):
        project_store.bind_thread("thread-project-bound", "P-thread-bound")


def test_thread_delete_retries_after_state_delete_before_project_fence_finalize(
    tmp_path,
    monkeypatch,
) -> None:
    from runtime.projectos.store import ProjectStore

    thread_store = ThreadStateStore()
    thread_store.ensure_thread("thread-delete-retry", values={"title": "Retry"})
    project_store = ProjectStore(base_dir=tmp_path / "projects")
    app = FastAPI()
    app.include_router(
        create_thread_state_router(
            store=thread_store,
            project_store=project_store,
        )
    )
    client = TestClient(app)
    real_finalize = project_store.finalize_thread_delete
    finalize_calls = 0

    def fail_once(thread_id, token):
        nonlocal finalize_calls
        finalize_calls += 1
        if finalize_calls == 1:
            raise RuntimeError("commit boundary unavailable")
        return real_finalize(thread_id, token)

    monkeypatch.setattr(project_store, "finalize_thread_delete", fail_once)

    failed = client.delete("/api/threads/thread-delete-retry")
    retried = client.delete("/api/threads/thread-delete-retry")

    assert failed.status_code == 503
    with pytest.raises(ThreadPermanentlyDeletedError):
        thread_store.get("thread-delete-retry")
    assert retried.status_code == 204
    assert project_store.thread_delete_lease("thread-delete-retry").finalized is True


def test_thread_delete_refuses_active_realtime_turn_claim(tmp_path) -> None:
    from runtime.platform.process.thread_turn_claim import acquire_thread_turn_claim

    logs_root = tmp_path / "logs"
    store = ThreadStateStore(path=tmp_path / "threads.jsonl")
    store.ensure_thread("thread-active-turn", values={"title": "Active"})
    app = FastAPI()
    app.include_router(create_thread_state_router(store=store, logs_root=logs_root))
    client = TestClient(app)

    claim = acquire_thread_turn_claim(logs_root, "thread-active-turn")
    try:
        refused = client.delete("/api/threads/thread-active-turn")
    finally:
        claim.release()

    assert refused.status_code == 409, refused.json()
    assert refused.json()["detail"]["code"] == "THREAD_TURN_ACTIVE"
    assert store.get("thread-active-turn") is not None
    assert client.delete("/api/threads/thread-active-turn").status_code == 204


def test_thread_delete_refuses_durable_group_state_and_releases_project_preflight(
    tmp_path,
) -> None:
    from runtime.memory.cowork.group import MemberEvent
    from runtime.memory.cowork.group_store import GroupStore
    from runtime.projectos.store import ProjectStore

    thread_id = "thread-group-owned"
    group_store = GroupStore(base_dir=tmp_path / "groups")
    group_store.append(
        thread_id,
        MemberEvent(action="invite", actor="owner", target_id="worker"),
    )
    project_store = ProjectStore(base_dir=tmp_path / "projects")
    thread_store = ThreadStateStore(path=tmp_path / "threads.jsonl")
    thread_store.ensure_thread(thread_id, values={"title": "Group"})
    app = FastAPI()
    app.include_router(
        create_thread_state_router(
            store=thread_store,
            logs_root=tmp_path / "logs",
            project_store=project_store,
            group_store=group_store,
        )
    )

    refused = TestClient(app).delete(f"/api/threads/{thread_id}")

    assert refused.status_code == 409, refused.json()
    assert refused.json()["detail"]["code"] == "THREAD_GROUP_LINKED"
    assert project_store.thread_delete_lease(thread_id) is None
    assert thread_store.thread_delete_lease(thread_id) is None
    assert thread_store.get(thread_id) is not None
    assert [event.action for event in group_store.events(thread_id)] == ["invite"]


def test_thread_delete_refuses_active_async_work_and_releases_project_preflight(tmp_path) -> None:
    from runtime.memory.cowork.async_work import AsyncWorkStore
    from runtime.memory.cowork.group_store import GroupStore
    from runtime.projectos.store import ProjectStore

    thread_id = "thread-async-active"
    group_store = GroupStore(base_dir=tmp_path / "groups")
    async_store = AsyncWorkStore(base_dir=group_store.base_dir, group_store=group_store)
    task = async_store.assign(thread_id, "worker", "finish this", actor="owner")
    project_store = ProjectStore(base_dir=tmp_path / "projects")
    thread_store = ThreadStateStore(path=tmp_path / "threads.jsonl")
    thread_store.ensure_thread(thread_id, values={"title": "Async"})
    app = FastAPI()
    app.include_router(
        create_thread_state_router(
            store=thread_store,
            logs_root=tmp_path / "logs",
            project_store=project_store,
            group_store=group_store,
        )
    )
    client = TestClient(app)

    refused = client.delete(f"/api/threads/{thread_id}")

    assert refused.status_code == 409, refused.json()
    assert refused.json()["detail"]["code"] == "THREAD_ASYNC_WORK_ACTIVE"
    assert project_store.thread_delete_lease(thread_id) is None
    assert group_store.thread_delete_lease(thread_id) is None
    assert thread_store.thread_delete_lease(thread_id) is None
    assert async_store.get(task.task_id).status == "pending"


def test_thread_delete_claim_blocks_late_room_link_before_state_cleanup(
    tmp_path,
    monkeypatch,
) -> None:
    from runtime.memory.cowork.group_store import GroupStore, GroupThreadDeletingError
    from runtime.projectos.store import ProjectStore

    thread_id = "thread-delete-before-link"
    group_store = GroupStore(base_dir=tmp_path / "groups")
    project_store = ProjectStore(base_dir=tmp_path / "projects")
    thread_store = ThreadStateStore(path=tmp_path / "threads.jsonl")
    thread_store.ensure_thread(thread_id, values={"title": "Delete"})
    state_fence_entered = Event()
    release_state_fence = Event()
    real_begin = thread_store.begin_permanent_delete

    def delayed_state_fence(*args, **kwargs):
        state_fence_entered.set()
        assert release_state_fence.wait(timeout=5)
        return real_begin(*args, **kwargs)

    monkeypatch.setattr(thread_store, "begin_permanent_delete", delayed_state_fence)
    app = FastAPI()
    app.include_router(
        create_thread_state_router(
            store=thread_store,
            logs_root=tmp_path / "logs",
            project_store=project_store,
            group_store=group_store,
        )
    )
    client = TestClient(app)
    with ThreadPoolExecutor(max_workers=1) as pool:
        deleting = pool.submit(client.delete, f"/api/threads/{thread_id}")
        assert state_fence_entered.wait(timeout=5)
        with pytest.raises(GroupThreadDeletingError):
            GroupStore(base_dir=tmp_path / "groups").link_room_if_absent(
                thread_id,
                "late-room",
                actor="late",
            )
        release_state_fence.set()
        deleted = deleting.result(timeout=5)

    assert deleted.status_code == 204, deleted.text
    assert group_store.state(thread_id).room_id is None
    assert group_store.thread_delete_lease(thread_id).finalized is True
    assert project_store.thread_delete_lease(thread_id).finalized is True
    assert thread_store.thread_delete_lease(thread_id).finalized is True


def test_thread_state_rejects_invalid_thread_id() -> None:
    client = _client()

    assert client.get("/api/threads/bad.thread").status_code == 400


def test_thread_state_owner_metadata_blocks_other_actor() -> None:
    from runtime.safety.auth import Identity, IdentityStore

    identity_store = IdentityStore()
    identity_store.add(Identity(actor_id="alice"), api_key_plaintext="sk-alice")
    identity_store.add(Identity(actor_id="bob"), api_key_plaintext="sk-bob")
    store = ThreadStateStore()
    store.ensure_thread(
        "owned-thread",
        metadata={"owner_actor_id": "alice"},
        values={"title": "Alice"},
    )
    app = FastAPI()
    app.include_router(
        create_thread_state_router(
            store=store,
            identity_store=identity_store,
            require_auth=True,
        )
    )
    client = TestClient(app)

    ok = client.get(
        "/api/threads/owned-thread",
        headers={"Authorization": "Bearer sk-alice"},
    )
    denied = client.get(
        "/api/threads/owned-thread",
        headers={"Authorization": "Bearer sk-bob"},
    )

    assert ok.status_code == 200
    assert denied.status_code == 404


def test_optional_auth_search_projection_keeps_owner_check_internal() -> None:
    from runtime.safety.auth import Identity, IdentityStore

    identity_store = IdentityStore()
    identity_store.add(Identity(actor_id="alice"), api_key_plaintext="sk-alice")
    store = ThreadStateStore()
    store.ensure_thread(
        "owned-thread",
        metadata={"owner_actor_id": "alice"},
        values={"title": "Private"},
    )
    store.ensure_thread("public-thread", values={"title": "Public"})
    app = FastAPI()
    app.include_router(
        create_thread_state_router(
            store=store,
            identity_store=identity_store,
            require_auth=False,
        )
    )

    response = TestClient(app).post(
        "/api/threads/search",
        json={"select": ["thread_id", "values.title"]},
    )

    assert response.status_code == 200
    assert response.json() == [{"thread_id": "public-thread", "values": {"title": "Public"}}]


def test_thread_create_and_update_cannot_spoof_owner_metadata(tmp_path: Path) -> None:
    from runtime.safety.auth import Identity, IdentityStore

    identity_store = IdentityStore()
    identity_store.add(Identity(actor_id="alice"), api_key_plaintext="sk-alice")
    store = ThreadStateStore()
    app = FastAPI()
    app.include_router(
        create_thread_state_router(
            store=store,
            identity_store=identity_store,
            require_auth=True,
            workspace_root=tmp_path / "managed-workspaces",
        )
    )
    client = TestClient(app)
    headers = {"Authorization": "Bearer sk-alice"}

    created = client.post(
        "/api/threads",
        headers=headers,
        json={"metadata": {"owner_actor_id": "bob"}, "values": {"title": "x"}},
    )
    assert created.status_code == 200
    thread_id = created.json()["thread_id"]
    assert store.get(thread_id)["metadata"]["owner_actor_id"] == "alice"

    updated = client.post(
        f"/api/threads/{thread_id}/state",
        headers=headers,
        json={"metadata": {"owner_actor_id": "bob", "label": "kept"}},
    )
    assert updated.status_code == 200
    assert updated.json()["metadata"]["owner_actor_id"] == "alice"
    assert updated.json()["metadata"]["label"] == "kept"


def test_thread_state_enforces_explicit_tenant_metadata() -> None:
    from runtime.safety.auth import Identity, IdentityStore

    identities = IdentityStore()
    identities.add(
        Identity(actor_id="alice", metadata={"tenant_id": "tenant-a"}),
        api_key_plaintext="sk-alice-tenant",
    )
    identities.add(
        Identity(actor_id="bob", metadata={"tenant_id": "tenant-b"}),
        api_key_plaintext="sk-bob-tenant",
    )
    store = ThreadStateStore()
    store.ensure_thread(
        "tenant-thread",
        metadata={"owner_actor_id": "alice", "tenant_id": "tenant-a"},
        values={"title": "private"},
    )
    app = FastAPI()
    app.include_router(
        create_thread_state_router(
            store=store,
            identity_store=identities,
            require_auth=True,
        )
    )
    client = TestClient(app)

    assert (
        client.get(
            "/api/threads/tenant-thread",
            headers={"Authorization": "Bearer sk-alice-tenant"},
        ).status_code
        == 200
    )
    assert (
        client.get(
            "/api/threads/tenant-thread",
            headers={"Authorization": "Bearer sk-bob-tenant"},
        ).status_code
        == 404
    )


def test_session_title_rename_endpoint_pins() -> None:
    client = _client()
    thread_id = client.post("/api/threads", json={}).json()["thread_id"]

    response = client.post(
        f"/api/threads/{thread_id}/title/rename",
        json={"title": "  手工   标题 "},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["title"] == "手工 标题"
    assert payload["source"] == "user"
    assert payload["pinned"] is True

    state = client.get(f"/api/threads/{thread_id}/state").json()
    assert state["values"]["title"] == "手工 标题"
    assert state["metadata"]["title_source"] == "user"
    assert state["metadata"]["title_pinned"] is True


def test_session_title_rename_endpoint_validates() -> None:
    client = _client()
    thread_id = client.post("/api/threads", json={}).json()["thread_id"]

    assert client.post(f"/api/threads/{thread_id}/title/rename", json={}).status_code == 400
    assert (
        client.post(f"/api/threads/{thread_id}/title/rename", json={"title": "   "}).status_code
        == 400
    )
    assert client.post("/api/threads/missing/title/rename", json={"title": "x"}).status_code == 404


def test_session_title_refresh_endpoint_uses_provider() -> None:
    from runtime.memory.threads.session_title import SessionTitleService

    store = ThreadStateStore()
    thread_id = store.create(values={"title": "New chat"})["thread_id"]
    service = SessionTitleService(store)
    service.register_provider("llm", lambda _thread: "auto title", model="deepseek-v4")
    app = FastAPI()
    app.include_router(create_thread_state_router(store=store, session_titles=service))
    client = TestClient(app)

    response = client.post(f"/api/threads/{thread_id}/title/refresh", json={})
    assert response.status_code == 200
    payload = response.json()
    assert payload["title"] == "auto title"
    assert payload["source"] == "provider"
    assert payload["provider"] == "llm"
    assert payload["model"] == "deepseek-v4"


def test_session_title_refresh_respects_pin() -> None:
    store = ThreadStateStore()
    thread_id = store.create(values={"title": "New chat"})["thread_id"]
    store.update_state(
        thread_id,
        values={"title": "pinned"},
        metadata={"title_source": "user", "title_pinned": True},
    )
    app = FastAPI()
    app.include_router(create_thread_state_router(store=store))
    client = TestClient(app)
    response = client.post(f"/api/threads/{thread_id}/title/refresh", json={})
    assert response.status_code == 200
    assert response.json()["title"] == "pinned"
    assert response.json()["source"] == "user"
