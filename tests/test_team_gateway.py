import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from runtime.sensing.gateway.codex_hotspot import owner_token
from runtime.sensing.gateway.team_gateway import create_team_gateway
from runtime.sensing.gateway.team_store import TeamStore


def setup(tmp_path, *, protocol="chat_completions", handler=None):
    seen = []

    def upstream(request):
        seen.append(request)
        assert request.headers["authorization"] == "Bearer upstream-secret"
        if handler:
            return handler(request)
        body = json.loads(request.content)
        assert body["model"] == "upstream-model"
        if request.url.path.endswith("/responses"):
            return httpx.Response(
                200,
                content="data: "
                + json.dumps(
                    {
                        "type": "response.completed",
                        "response": {"status": "completed", "output": []},
                    }
                )
                + "\n\n",
            )
        return httpx.Response(
            200, json={"choices": [{"message": {"role": "assistant", "content": "OK"}}]}
        )

    app = create_team_gateway(tmp_path, transport=httpx.MockTransport(upstream))
    client = TestClient(app)
    admin = {"Authorization": "Bearer " + owner_token(tmp_path)}
    config = {
        "name": "Team model",
        "base_url": "http://localhost:9900/v1",
        "api_key": "upstream-secret",
        "upstream_model": "upstream-model",
        "wire_api": protocol,
    }
    assert client.put("/admin/models/team", json=config, headers=admin).status_code == 200
    return app, client, admin, seen, config


def activate(client, admin, *, budget=3):
    assert client.post("/admin/models/team/publish", json={}, headers=admin).status_code == 200
    assert client.post("/admin/enabled", json={"enabled": True}, headers=admin).status_code == 200
    invite = client.post(
        "/admin/invitations",
        headers=admin,
        json={
            "label": "member",
            "models": ["team"],
            "max_requests": budget,
        },
    ).json()
    joined = client.post("/join", json={"code": invite["code"]})
    assert joined.status_code == 200
    return invite, joined.json(), {"Authorization": "Bearer " + joined.json()["token"]}


def test_exchange_authorization_budget_and_restart(tmp_path):
    app, client, admin, seen, config = setup(tmp_path)
    assert client.get("/admin/status").status_code == 401
    invite, joined, member = activate(client, admin, budget=1)
    assert client.post("/join", json={"code": invite["code"]}).status_code == 401
    assert (
        client.get("/v1/models", headers={"Authorization": "Bearer " + invite["code"]}).status_code
        == 401
    )
    catalog = client.get("/v1/models", headers=member)
    assert catalog.json()["data"][0]["id"] == "team"
    assert "upstream-secret" not in catalog.text + client.get("/admin/status", headers=admin).text
    assert "upstream-model" not in catalog.text
    body = {"model": "team", "messages": [{"role": "user", "content": "hello"}]}
    response = client.post(
        "/v1/chat/completions", json=body, headers={**member, "Idempotency-Key": "one"}
    )
    assert response.json()["choices"][0]["message"]["content"] == "OK"
    assert (
        client.post(
            "/v1/chat/completions", json=body, headers={**member, "Idempotency-Key": "one"}
        ).status_code
        == 409
    )
    assert client.post("/v1/chat/completions", json=body, headers=member).status_code == 429
    assert len(seen) == 2  # publish + one authorized request
    restarted = TeamStore(tmp_path)
    assert restarted.authorize(joined["token"])["used"] == 1
    assert restarted.catalog(joined["member_id"])[0]["id"] == "team"
    assert client.delete("/admin/members/" + invite["id"], headers=admin).status_code == 200
    assert client.get("/v1/models", headers=member).status_code == 401


def test_draft_pause_scope_and_failed_publication(tmp_path):
    app, client, admin, seen, config = setup(tmp_path)
    assert (
        client.post(
            "/admin/invitations", headers=admin, json={"label": "member", "models": ["team"]}
        ).status_code
        == 400
    )
    _, _, member = activate(client, admin)
    assert (
        client.post(
            "/v1/responses", headers=member, json={"model": "team", "input": "hi"}
        ).status_code
        == 400
    )
    assert (
        client.post("/v1/chat/completions", headers=member, json={"model": "secret"}).status_code
        == 403
    )
    assert (
        client.put("/admin/models/team", json={**config, "api_key": ""}, headers=admin).status_code
        == 200
    )
    assert client.get("/v1/models", headers=member).json()["data"] == []
    assert app.state.store.model("team")["api_key"] == "upstream-secret"
    app.state.store.publish("team", 2)
    client.post("/admin/models/team/pause", headers=admin, json={})
    assert client.get("/v1/models", headers=member).json()["data"] == []

    _, failing, auth, _, _ = setup(
        tmp_path / "failure", handler=lambda _: httpx.Response(401, text="upstream-secret")
    )
    result = failing.post("/admin/models/team/publish", headers=auth, json={})
    assert result.status_code == 502 and "upstream-secret" not in result.text
    assert not failing.get("/admin/status", headers=auth).json()["models"][0]["published"]


def test_responses_roundtrip_keeps_tool_payloads_and_rejects_account_references(tmp_path):
    _, client, admin, seen, _ = setup(tmp_path, protocol="responses")
    _, _, member = activate(client, admin)
    tool = {
        "type": "function",
        "name": "lookup",
        "parameters": {"type": "object", "properties": {}},
    }
    body = {
        "model": "team",
        "input": [{"type": "function_call_output", "call_id": "c1", "output": "result"}],
        "tools": [tool],
        "stream": True,
    }
    response = client.post("/v1/responses", headers=member, json=body)
    assert response.status_code == 200 and "response.completed" in response.text
    forwarded = json.loads(seen[-1].content)
    assert forwarded["input"] == body["input"] and forwarded["tools"] == [tool]
    assert forwarded["store"] is False
    for extra in ({"previous_response_id": "private"}, {"input": [{"file_id": "private"}]}):
        assert (
            client.post("/v1/responses", headers=member, json={**body, **extra}).status_code == 400
        )


def test_failed_upstream_consumes_once_without_retry(tmp_path):
    calls = 0

    def handler(_):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}]})
        return httpx.Response(503, text="upstream-secret")

    _, client, admin, seen, _ = setup(tmp_path, handler=handler)
    _, _, member = activate(client, admin)
    response = client.post(
        "/v1/chat/completions", headers=member, json={"model": "team", "messages": []}
    )
    assert response.status_code == 502 and "upstream-secret" not in response.text
    assert len(seen) == 2
    status = client.get("/admin/status", headers=admin).json()
    assert status["members"][0]["used"] == 1 and status["usage"][0]["status"] == "failed"


def test_atomic_single_use_exchange(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    from fastapi import HTTPException

    app, client, admin, _, _ = setup(tmp_path)
    client.post("/admin/models/team/publish", headers=admin, json={})
    invite = app.state.store.invitation("member", 1, 2, ["team"], 1)

    def exchange():
        try:
            return app.state.store.exchange(invite["code"])["token"]
        except HTTPException:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: exchange(), range(2)))
    assert sum(result is not None for result in results) == 1


def test_echo_management_requires_local_admin(tmp_path, monkeypatch):
    from fastapi import FastAPI

    from runtime.safety.auth import Identity, IdentityStore
    from runtime.sensing.gateway import team_control
    from runtime.sensing.gateway.config_router import create_config_router

    store = IdentityStore()
    store.add(Identity(actor_id="boss", roles=("admin",)), api_key_plaintext="admin-key")
    store.add(Identity(actor_id="member", roles=()), api_key_plaintext="member-key")
    reached = []

    async def running():
        reached.append(True)

    async def control(*args):
        return {"enabled": False}

    monkeypatch.setattr(team_control, "ensure_running", running)
    monkeypatch.setattr(team_control, "control", control)
    bundle = create_config_router(
        require_auth=True, identity_store=store, custom_models_path=tmp_path / "models.json"
    )
    app = FastAPI()
    app.include_router(bundle.router)
    with TestClient(app) as client:
        path = "/api/team-gateway/admin/status"
        assert client.get(path).status_code == 401
        assert client.get(path, headers={"Authorization": "Bearer member-key"}).status_code == 403
        assert not reached
        assert (
            client.get(
                path,
                headers={"Authorization": "Bearer admin-key", "Origin": "https://outside.example"},
            ).status_code
            == 403
        )
        assert client.get(path, headers={"Authorization": "Bearer admin-key"}).status_code == 200
        assert reached == [True]


def test_truncated_stream_is_not_silently_successful(tmp_path):
    class BrokenStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'data: {"choices": [{"delta": {"content": "start"}}]}\n\n'
            raise httpx.ReadError("upstream-secret")

    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}]})
        return httpx.Response(200, stream=BrokenStream())

    app, client, admin, _, _ = setup(tmp_path, handler=handler)
    _, _, member = activate(client, admin)
    with pytest.raises(Exception) as error:
        client.post(
            "/v1/chat/completions",
            headers=member,
            json={"model": "team", "messages": [], "stream": True},
        )
    assert "upstream-secret" not in str(error.value)
    assert app.state.store.usage()[0]["status"] == "failed"


@pytest.mark.parametrize("action", ["revoke", "disable"])
def test_pending_request_cancellation_and_concurrency(tmp_path, action):
    async def scenario():
        pending = asyncio.Event()
        cancelled = asyncio.Event()

        async def handler(request):
            pending.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        app = create_team_gateway(tmp_path, transport=httpx.MockTransport(handler))
        store = app.state.store
        store.save_model(
            "team",
            {
                "name": "Team",
                "base_url": "http://localhost/v1",
                "api_key": "key",
                "upstream_model": "m",
                "wire_api": "chat_completions",
            },
        )
        store.publish("team", 1)
        store.set_enabled(True)
        invite = store.invitation("member", 1, 3, ["team"], 1)
        token = store.exchange(invite["code"])["token"]
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            headers = {"Authorization": "Bearer " + token}
            body = {"model": "team", "messages": [{"role": "user", "content": "hi"}]}
            task = asyncio.create_task(
                client.post("/v1/chat/completions", headers=headers, json=body)
            )
            await asyncio.wait_for(pending.wait(), 3)
            rejected = await client.post("/v1/chat/completions", headers=headers, json=body)
            assert rejected.status_code == 429
            auth = {"Authorization": "Bearer " + owner_token(tmp_path)}
            if action == "revoke":
                await client.delete("/admin/members/" + invite["id"], headers=auth)
            else:
                await client.post("/admin/enabled", headers=auth, json={"enabled": False})
            response = await asyncio.wait_for(task, 3)
            assert response.status_code == 503
            assert cancelled.is_set() and store.usage()[0]["status"] == "cancelled"

    asyncio.run(scenario())
