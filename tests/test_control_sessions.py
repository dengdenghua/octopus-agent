from __future__ import annotations

import time

from fastapi import FastAPI
from fastapi.testclient import TestClient

from runtime.memory.control_sessions import ControlSessionStore
from runtime.sensing.gateway.control_sessions_router import create_control_sessions_router


def _client(tmp_path):
    app = FastAPI()
    store = ControlSessionStore(base_dir=tmp_path)
    app.include_router(create_control_sessions_router(store=store))
    return TestClient(app), store


def test_control_session_replay_records_actions_and_evidence(tmp_path) -> None:
    client, _store = _client(tmp_path)

    created = client.post(
        "/api/control-sessions",
        json={
            "session_id": "ctrl-browser-1",
            "owner_id": "agent-1",
            "owner_label": "Agent 1",
            "surface": "browser",
            "target_id": "tab-1",
            "metadata": {"thread_id": "thread-1"},
        },
    )
    assert created.status_code == 200
    assert created.json()["session"]["status"] == "idle"

    action = client.post(
        "/api/control-sessions/ctrl-browser-1/actions",
        json={
            "action_id": "action-1",
            "action_type": "navigate",
            "status": "running",
            "descriptor": {"type": "navigate", "url": "https://example.com"},
        },
    )
    assert action.status_code == 200
    assert action.json()["action"]["status"] == "running"

    evidence = client.post(
        "/api/control-sessions/ctrl-browser-1/evidence",
        json={
            "evidence_id": "evidence-1",
            "action_id": "action-1",
            "kind": "result",
            "action": "navigate",
            "ok": True,
            "summary": "loaded",
            "detail": {"url": "https://example.com"},
        },
    )
    assert evidence.status_code == 200
    assert evidence.json()["evidence"]["seq"] == 1

    updated = client.patch(
        "/api/control-sessions/ctrl-browser-1/actions/action-1",
        json={"status": "done", "result": {"title": "Example"}},
    )
    assert updated.status_code == 200
    assert updated.json()["action"]["status"] == "done"

    replay = client.get("/api/control-sessions/ctrl-browser-1/replay")
    data = replay.json()
    assert data["schema"] == "octopus.control_session_replay.v1"
    assert data["session"]["session_id"] == "ctrl-browser-1"
    assert data["actions"][0]["action_type"] == "navigate"
    assert data["evidence"][0]["summary"] == "loaded"
    assert "page.goto" in data["playwright_script"]


def test_control_session_takeover_pauses_and_counts(tmp_path) -> None:
    client, _store = _client(tmp_path)
    client.post(
        "/api/control-sessions",
        json={
            "session_id": "ctrl-computer-1",
            "owner_id": "agent",
            "owner_label": "Agent",
            "surface": "computer",
            "target_id": "local-pc",
        },
    )

    taken = client.post(
        "/api/control-sessions/ctrl-computer-1/takeover",
        json={
            "reason": "operator moved mouse",
            "owner_id": "human",
            "owner_label": "Human",
        },
    )
    assert taken.status_code == 200
    session = taken.json()["session"]
    assert session["status"] == "paused"
    assert session["paused"] is True
    assert session["owner_id"] == "human"
    assert session["takeover_count"] == 1

    resumed = client.post("/api/control-sessions/ctrl-computer-1/resume", json={})
    assert resumed.status_code == 200
    assert resumed.json()["session"]["status"] == "idle"


def test_control_session_rejects_invalid_surface(tmp_path) -> None:
    client, _store = _client(tmp_path)
    response = client.post(
        "/api/control-sessions",
        json={"session_id": "ctrl-bad-1", "surface": "spaceship"},
    )
    assert response.status_code == 400


def test_control_action_ttl_expires_and_emits_event(tmp_path) -> None:
    client, store = _client(tmp_path)
    created = client.post(
        "/api/control-sessions",
        json={
            "session_id": "ctrl-expiry-1",
            "owner_id": "agent",
            "owner_label": "Agent",
            "surface": "computer",
            "target_id": "local-pc",
        },
    )
    assert created.status_code == 200

    action = client.post(
        "/api/control-sessions/ctrl-expiry-1/actions",
        json={
            "action_id": "action-expiring",
            "action_type": "click",
            "status": "running",
            "descriptor": {"type": "click", "x": 1, "y": 2},
            "ttl_seconds": 0.01,
        },
    )
    assert action.status_code == 200
    time.sleep(0.03)

    replay = client.get("/api/control-sessions/ctrl-expiry-1/replay").json()
    assert replay["session"]["status"] == "paused"
    assert replay["actions"][0]["status"] == "expired"
    assert replay["actions"][0]["error"] == "action expired"

    events = store.events_after("ctrl-expiry-1")
    assert any(event["type"] == "action_expired" for event in events)
