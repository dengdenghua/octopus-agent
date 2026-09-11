import asyncio
import json
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from runtime.sensing.gateway.codex_hotspot import create_hotspot, owner_token
from runtime.sensing.gateway.hotspot_store import HotspotStore


class Auth:
    def __init__(self, home):
        self.home = home

    async def refresh(self, **kwargs):
        pass

    def headers(self):
        return {"Authorization": "Bearer upstream-private", "ChatGPT-Account-Id": "owner-private"}


def activate(client, root, **kwargs):
    owner = {"Authorization": "Bearer " + owner_token(root)}
    assert client.post("/admin/enabled", json={"enabled": True}, headers=owner).status_code == 200
    response = client.post("/admin/members", json={"label": "colleague", **kwargs}, headers=owner)
    assert response.status_code == 200, response.text
    invitation = response.json()
    return invitation, {"Authorization": "Bearer " + invitation["token"]}, owner


def test_responses_forwards_tools_with_owner_auth_and_preserves_stream(tmp_path):
    seen = []
    events = (
        b'data: {"type":"response.output_item.done","item":{"type":"function_call","name":"lookup","arguments":"{}"}}\n\n'
        b'data: {"type":"response.completed","response":{"usage":{"input_tokens":12,"output_tokens":4}}}\n\n'
    )

    def upstream(request):
        seen.append(request)
        return httpx.Response(200, content=events, headers={"Content-Type": "text/event-stream"})

    app = create_hotspot(tmp_path, auth=Auth(tmp_path), transport=httpx.MockTransport(upstream))
    with TestClient(app, base_url="http://127.0.0.1:8322") as client:
        invitation, headers, owner = activate(client, tmp_path, max_requests=1)
        body = {
            "model": "test-model",
            "input": "hello",
            "stream": True,
            "tools": [{"type": "function", "name": "lookup", "parameters": {"type": "object"}}],
        }
        response = client.post(
            "/v1/responses", json=body, headers={**headers, "ChatGPT-Account-Id": "forged"}
        )
        assert response.status_code == 200, response.text
        assert response.content == events
        assert seen[0].headers["authorization"] == "Bearer upstream-private"
        assert seen[0].headers["chatgpt-account-id"] == "owner-private"
        sent = json.loads(seen[0].content)
        assert sent["tools"] == body["tools"] and sent["store"] is False
        assert "upstream-private" not in response.text
        assert client.post("/v1/responses", json=body, headers=headers).status_code == 429
        status = client.get("/admin/status", headers=owner).json()
        assert status["usage"][0]["input_tokens"] == 12
        assert invitation["token"] not in json.dumps(status)


def test_bad_upstream_is_not_retried_or_leaked(tmp_path):
    calls = []

    def upstream(request):
        calls.append(request)
        return httpx.Response(401, text="sensitive-upstream-body")

    app = create_hotspot(tmp_path, auth=Auth(tmp_path), transport=httpx.MockTransport(upstream))
    with TestClient(app, base_url="http://127.0.0.1:8322") as client:
        _, headers, _ = activate(client, tmp_path)
        result = client.post("/v1/responses", json={"model": "m", "input": "hi"}, headers=headers)
        assert result.status_code == 401 and "sensitive" not in result.text
        assert len(calls) == 1


def test_task_lane_authenticated_and_isolated(tmp_path):
    workspaces = []

    async def runner(config, **kwargs):
        workspaces.append(kwargs["workspace"])
        (kwargs["workspace"] / "proof.txt").write_text("CODEX_TASK_OK")
        yield {"type": "result", "subtype": "success", "result": "CODEX_TASK_OK"}

    app = create_hotspot(tmp_path, auth=Auth(tmp_path), task_runner=runner)
    with TestClient(app, base_url="http://127.0.0.1:8322") as client:
        first, headers, owner = activate(client, tmp_path)
        second, headers2, _ = activate(client, tmp_path)
        path = f"/members/{first['id']}"
        assert client.get(path + "/.well-known/agent-card.json").status_code == 401
        card = client.get(path + "/.well-known/agent-card.json", headers=headers).json()
        assert card["name"] == "Codex"
        assert path in card["supportedInterfaces"][0]["url"]
        body = {
            "jsonrpc": "2.0",
            "id": "one",
            "method": "SendMessage",
            "params": {
                "message": {
                    "messageId": "m",
                    "contextId": "same-context",
                    "role": "ROLE_USER",
                    "parts": [{"text": "write proof"}],
                }
            },
        }
        response = client.post(
            path + "/a2a/rpc", json=body, headers={**headers, "A2A-Version": "1.0"}
        )
        assert response.status_code == 200, response.text
        task = response.json()["result"]["task"]
        assert task["status"]["state"] == "TASK_STATE_COMPLETED"
        assert task["history"][-1]["parts"][0]["text"] == "CODEX_TASK_OK"
        assert client.post(path + "/a2a/rpc", json=body, headers=headers2).status_code == 403
        response2 = client.post(
            f"/members/{second['id']}/a2a/rpc",
            json=body,
            headers={**headers2, "A2A-Version": "1.0"},
        )
        assert response2.status_code == 200
        assert workspaces[0] != workspaces[1]
        assert client.get("/admin/status", headers=owner).json()["members"][0]["used"] == 1
        client.delete("/admin/members/" + first["id"], headers=owner)
        assert client.get(path + "/.well-known/agent-card.json", headers=headers).status_code == 401


def test_disabled_expired_and_atomic_budget(tmp_path):
    store = HotspotStore(tmp_path)
    member = store.invite("team", max_requests=1)
    with pytest.raises(HTTPException):
        store.authorize(member["token"])
    store.set_enabled(True)

    def reserve(_):
        try:
            store.authorize(member["token"], reserve=True)
            return True
        except HTTPException:
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(reserve, range(8))) == 1
    with store.connect() as db:
        db.execute("UPDATE grants SET expires=0")
    with pytest.raises(HTTPException) as error:
        store.authorize(member["token"])
    assert error.value.status_code == 401


@pytest.mark.asyncio
async def test_revoke_stops_an_active_remote_task(tmp_path):
    started, stopped = asyncio.Event(), asyncio.Event()

    async def runner(*args, **kwargs):
        started.set()
        try:
            await asyncio.Event().wait()
            yield {"type": "result"}
        finally:
            stopped.set()

    app = create_hotspot(tmp_path, auth=Auth(tmp_path), task_runner=runner)
    async with app.router.lifespan_context(app):
        app.state.store.set_enabled(True)
        invite = app.state.store.invite("running")
        owner = {"Authorization": "Bearer " + owner_token(tmp_path)}
        headers = {"Authorization": "Bearer " + invite["token"], "A2A-Version": "1.0"}
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://127.0.0.1:8322"
        ) as client:
            pending = asyncio.create_task(
                client.post(
                    f"/members/{invite['id']}/a2a/rpc",
                    headers=headers,
                    json={
                        "jsonrpc": "2.0",
                        "id": "x",
                        "method": "SendMessage",
                        "params": {
                            "message": {
                                "messageId": "x",
                                "role": "ROLE_USER",
                                "parts": [{"text": "wait"}],
                            }
                        },
                    },
                )
            )
            await asyncio.wait_for(started.wait(), 3)
            await client.delete("/admin/members/" + invite["id"], headers=owner)
            response = await asyncio.wait_for(pending, 5)
            assert stopped.is_set()
            assert response.json()["result"]["task"]["status"]["state"] == "TASK_STATE_CANCELED"


def test_registration_keeps_invitation_secret_out_of_agent_directory(tmp_path, monkeypatch):
    from fastapi import FastAPI

    from runtime.sensing.gateway import a2a_router
    from runtime.sensing.gateway.remote_credentials import read_token

    monkeypatch.setattr(a2a_router, "_REGISTRY_DIR", tmp_path)
    monkeypatch.setattr(a2a_router, "_REGISTRY_FILE", tmp_path / "registry.json")
    token = "private-invitation-token-123456"

    async def resolve(url, bearer_token=None):
        assert bearer_token == token
        return {"name": "Codex", "description": "remote"}

    monkeypatch.setattr(a2a_router, "_resolve_agent_card", resolve)
    app = FastAPI()
    app.include_router(a2a_router.create_a2a_router())
    with TestClient(app) as client:
        response = client.post(
            "/api/a2a/agents/register",
            json={"url": "https://example.com/member", "bearer_token": token},
        )
        assert response.status_code == 200
        assert token not in response.text
        assert token not in client.get("/api/a2a/agents").text
        assert token not in (tmp_path / "registry.json").read_text()
        assert read_token(response.json()) == token


@pytest.mark.asyncio
async def test_revoke_closes_an_active_model_stream(tmp_path):
    started, closed = asyncio.Event(), asyncio.Event()

    class Slow(httpx.AsyncByteStream):
        async def __aiter__(self):
            started.set()
            yield b'data: {"type":"response.created"}\n\n'
            await asyncio.Event().wait()

        async def aclose(self):
            closed.set()

    app = create_hotspot(
        tmp_path,
        auth=Auth(tmp_path),
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, headers={"Content-Type": "text/event-stream"}, stream=Slow()
            )
        ),
    )
    async with app.router.lifespan_context(app):
        app.state.store.set_enabled(True)
        member = app.state.store.invite("streaming")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://127.0.0.1:8322"
        ) as client:
            pending = asyncio.create_task(
                client.post(
                    "/v1/responses",
                    headers={"Authorization": "Bearer " + member["token"]},
                    json={"model": "m", "input": "wait"},
                )
            )
            await asyncio.wait_for(started.wait(), 3)
            app.state.store.revoke(member["id"])
            await asyncio.wait_for(closed.wait(), 3)
            await asyncio.wait_for(asyncio.gather(pending, return_exceptions=True), 3)
            assert app.state.store.usage()[0]["status"] != "running"


def test_opencode_invitation_persists_engine_and_card(tmp_path, monkeypatch):
    from runtime.execution import opencode_backend

    monkeypatch.setattr(opencode_backend, "executable", lambda: "opencode")
    app = create_hotspot(tmp_path, auth=Auth(tmp_path))
    with TestClient(app, base_url="http://127.0.0.1:8322") as client:
        grant, headers, owner = activate(client, tmp_path, task_engine="opencode")
        assert grant["task_engine"] == "opencode"
        assert HotspotStore(tmp_path).task_engine(grant["id"]) == "opencode"
        response = client.get(grant["task_url"] + "/.well-known/agent-card.json", headers=headers)
        assert response.status_code == 200
        assert response.json()["name"] == "OpenCode"
        assert (
            client.post(
                "/admin/members", json={"label": "bad", "task_engine": "unknown"}, headers=owner
            ).status_code
            == 400
        )
    app = create_hotspot(tmp_path, auth=Auth(tmp_path))
    with TestClient(app, base_url="http://127.0.0.1:8322") as client:
        assert (
            client.get(grant["task_url"] + "/.well-known/agent-card.json", headers=headers).json()[
                "name"
            ]
            == "OpenCode"
        )


def test_opencode_output_limit_is_normalized(tmp_path):
    seen = []

    def upstream(request):
        seen.append(json.loads(request.content))
        return httpx.Response(
            200,
            content=b'data: {"type":"response.completed","response":{}}\n\n',
            headers={"content-type": "text/event-stream"},
        )

    app = create_hotspot(tmp_path, auth=Auth(tmp_path), transport=httpx.MockTransport(upstream))
    with TestClient(app, base_url="http://127.0.0.1:8322") as client:
        _, headers, _ = activate(client, tmp_path)
        assert (
            client.post(
                "/v1/responses",
                headers=headers,
                json={"model": "test", "input": "hello", "stream": True, "max_output_tokens": 32000},
            ).status_code
            == 200
        )
    assert "max_output_tokens" not in seen[0]
    assert seen[0]["store"] is False
