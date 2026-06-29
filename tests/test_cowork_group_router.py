"""/api/cowork/* thread-group HTTP layer: reads public, mutations attributed."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from runtime.memory.cowork.group_store import GroupStore
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
        json={"target_id": "bob", "kind": "agent", "grant": {"scope": "from_join"},
              "at_message": 12},
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


def test_invite_requires_target(tmp_path) -> None:
    c = _client(tmp_path)
    assert c.post("/api/cowork/t/members", json={"kind": "agent"}).status_code == 422
