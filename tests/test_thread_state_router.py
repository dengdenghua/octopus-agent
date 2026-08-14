from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from runtime.memory.threads import ThreadStateStore
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

    assert client.post("/threads").status_code == 404
    assert client.get(f"/threads/{thread_id}").status_code == 404


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
    assert store.get("th-realtime") is None
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


def test_thread_create_and_update_cannot_spoof_owner_metadata() -> None:
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

    assert (
        client.post(f"/api/threads/{thread_id}/title/rename", json={}).status_code == 400
    )
    assert (
        client.post(
            f"/api/threads/{thread_id}/title/rename", json={"title": "   "}
        ).status_code
        == 400
    )
    assert (
        client.post("/api/threads/missing/title/rename", json={"title": "x"}).status_code
        == 404
    )


def test_session_title_refresh_endpoint_uses_provider() -> None:
    from runtime.memory.threads.session_title import SessionTitleService

    store = ThreadStateStore()
    thread_id = store.create(values={"title": "New chat"})["thread_id"]
    service = SessionTitleService(store)
    service.register_provider("llm", lambda _thread: "auto title", model="deepseek-v4")
    app = FastAPI()
    app.include_router(
        create_thread_state_router(store=store, session_titles=service)
    )
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
