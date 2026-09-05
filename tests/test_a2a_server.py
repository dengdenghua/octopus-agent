from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from runtime.sensing.gateway.a2a_server import mount_a2a_server


def _app(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setattr(
        "runtime.execution.suckers.delegation_skills._call_agent",
        lambda **_kwargs: {
            "success": True,
            "output": "verified inbound response",
            "error": None,
        },
    )
    app = FastAPI()
    mount_a2a_server(app, data_dir=tmp_path)
    return TestClient(app)


def _send(client: TestClient, *, request_id: str = "req-1"):
    return client.post(
        "/api/a2a/rpc",
        headers={"A2A-Version": "1.0"},
        json={
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "SendMessage",
            "params": {
                "message": {
                    "messageId": "msg-user-1",
                    "role": "ROLE_USER",
                    "parts": [{"text": "review this plan"}],
                }
            },
        },
    )


def test_well_known_card_and_jsonrpc_send_are_official_a2a_v1(tmp_path, monkeypatch) -> None:
    with _app(tmp_path, monkeypatch) as client:
        card = client.get("/.well-known/agent-card.json")
        assert card.status_code == 200, card.text
        body = card.json()
        assert body["name"] == "Octopus Multi-Agent Workspace"
        assert body["supportedInterfaces"][0]["protocolVersion"] == "1.0"
        assert body["capabilities"]["streaming"] is True

        response = _send(client)
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["id"] == "req-1"
        assert payload["result"]["task"]["status"]["state"] == "TASK_STATE_COMPLETED"
        assert (
            payload["result"]["task"]["history"][-1]["parts"][0]["text"]
            == "verified inbound response"
        )


def test_inbound_task_survives_app_restart_and_is_queryable(tmp_path, monkeypatch) -> None:
    with _app(tmp_path, monkeypatch) as first:
        sent = _send(first)
        assert sent.status_code == 200, sent.text
        task = sent.json()["result"]["task"]
        task_id = task["id"]

    with _app(tmp_path, monkeypatch) as reopened:
        response = reopened.post(
            "/api/a2a/rpc",
            headers={"A2A-Version": "1.0"},
            json={
                "jsonrpc": "2.0",
                "id": "get-1",
                "method": "GetTask",
                "params": {"id": task_id},
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["result"]["id"] == task_id
        assert response.json()["result"]["status"]["state"] == "TASK_STATE_COMPLETED"


def test_a2a_tenant_mount_does_not_shadow_later_application_routes(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "runtime.execution.suckers.delegation_skills._call_agent",
        lambda **_kwargs: {"success": True, "output": "ok", "error": None},
    )
    app = FastAPI()
    mount_a2a_server(app, data_dir=tmp_path)

    @app.get("/api/later-route")
    def later_route() -> dict[str, bool]:
        return {"reachable": True}

    with TestClient(app) as client:
        response = client.get("/api/later-route")
        assert response.status_code == 200
        assert response.json() == {"reachable": True}

        tenant_card = client.get(
            "/api/a2a/server/acme/v1/card",
            headers={"A2A-Version": "0.3"},
        )
        # This handler deliberately has no authenticated extended card, so the
        # protocol returns 400; importantly, the namespaced tenant route was
        # reached instead of Starlette's generic 404.
        assert tenant_card.status_code == 400
        assert "extended cards" in tenant_card.text
