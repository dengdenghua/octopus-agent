import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from runtime.sensing.gateway.team_connections import TeamConnections
from runtime.sensing.gateway.team_gateway import create_team_gateway
from runtime.sensing.gateway.team_store import TeamStore


def published(root):
    gateway = create_team_gateway(root)
    store = gateway.state.store
    store.save_model(
        "assistant",
        {
            "name": "助手",
            "base_url": "https://source.example/v1",
            "api_key": "upstream-secret",
            "upstream_model": "source-model",
            "wire_api": "responses",
        },
    )
    store.publish("assistant", 1)
    store.set_enabled(True)
    invite = store.invitation("member", 24, 10, ["assistant"], 2)
    return gateway, store, invite


def test_exchange_receipt_recovers_same_client_only_and_obeys_revocation(tmp_path):
    _, store, invite = published(tmp_path)
    proof = "a" * 43
    first = store.exchange(invite["code"], proof)
    restarted = TeamStore(tmp_path)
    assert restarted.exchange(invite["code"], proof) == first
    for key in ("", "b" * 43):
        with pytest.raises(HTTPException):
            restarted.exchange(invite["code"], key)
    # Gateway recovery records contain no plaintext token or proof.
    with restarted.connect() as db:
        receipt = dict(db.execute("SELECT * FROM team_exchanges").fetchone())
    assert first["token"] not in json.dumps(receipt) and proof not in json.dumps(receipt)
    restarted.revoke(first["member_id"])
    with pytest.raises(HTTPException):
        restarted.exchange(invite["code"], proof)


def test_lost_exchange_response_recovers_after_restart_without_new_invite(tmp_path):
    async def scenario():
        gateway, store, invite = published(tmp_path / "gateway")
        upstream = httpx.ASGITransport(app=gateway)
        drop = True

        async def handler(request):
            nonlocal drop
            response = await upstream.handle_async_request(request)
            await response.aread()
            if request.url.path == "/join" and drop:
                drop = False
                raise httpx.ReadTimeout("response lost after redemption")
            return response

        applied = []
        path = tmp_path / "connections.db"
        service = TeamConnections(
            path, lambda c, m: applied.append(m), transport=httpx.MockTransport(handler)
        )
        connection_id = service.start("http://localhost:8333/v1", invite["code"])
        failed = await service.sync(connection_id)
        assert failed["error"] and not failed["connected"]
        assert store.members()[0]["redeemed"]
        restored = TeamConnections(
            path, lambda c, m: applied.append(m), transport=httpx.MockTransport(handler)
        )
        assert restored.start("http://localhost:8333/v1", invite["code"]) == connection_id
        result = await restored.sync(connection_id)
        assert result["connected"] and not result["error"]
        assert result["models"][0]["id"] == "assistant"
        token = restored.rows(private=True)[0]["token"]
        assert token not in json.dumps(restored.rows())
        assert not restored.rows(private=True)[0]["code"]
        store.pause("assistant")
        await restored.sync(connection_id)
        assert applied[-1] == []
        store.publish("assistant", 2)
        await restored.sync(connection_id)
        assert applied[-1][0]["id"] == "assistant"
        store.revoke(invite["id"])
        revoked = await restored.sync(connection_id)
        assert revoked["error"] and applied[-1] == []
        await restored.disconnect(connection_id)
        assert restored.rows() == []

    asyncio.run(scenario())


def test_echo_join_persists_routes_and_sync_preserves_unrelated_models(tmp_path, monkeypatch):
    from runtime.sensing.gateway import team_connections as module
    from runtime.sensing.gateway.config_router import create_config_router
    from runtime.sensing.model_router import openai_responses_router
    from runtime.sensing.model_router.dispatch_router import ModelDispatchRouter
    from runtime.sensing.model_router.models import Message, ModelRequest, ModelRouter

    gateway, store, invite = published(tmp_path / "gateway")
    original = module.TeamConnections
    monkeypatch.setattr(
        module,
        "TeamConnections",
        lambda path, apply: original(path, apply, transport=httpx.ASGITransport(app=gateway)),
    )
    router_type = openai_responses_router.OpenAIResponsesModelRouter

    def response(request):
        assert request.url.path == "/v1/responses"
        assert json.loads(request.content)["model"] == "assistant"
        return httpx.Response(
            200,
            content="data: "
            + json.dumps(
                {
                    "type": "response.completed",
                    "response": {
                        "id": "r",
                        "model": "assistant",
                        "status": "completed",
                        "output": [
                            {
                                "type": "message",
                                "role": "assistant",
                                "content": [{"type": "output_text", "text": "TEAM_SYNC_OK"}],
                            }
                        ],
                    },
                }
            )
            + "\n\n",
        )

    monkeypatch.setattr(
        openai_responses_router,
        "OpenAIResponsesModelRouter",
        lambda **kw: router_type(
            **kw, client=httpx.Client(transport=httpx.MockTransport(response))
        ),
    )

    class Fallback(ModelRouter):
        def call(self, request):
            raise AssertionError("unexpected fallback")

    def echo():
        dispatcher = ModelDispatchRouter(fallback=Fallback())
        bundle = create_config_router(
            stack=SimpleNamespace(planner=SimpleNamespace(router=dispatcher)),
            custom_models_path=tmp_path / "models.json",
        )
        app = FastAPI()
        app.include_router(bundle.router)
        return TestClient(app), dispatcher

    client, dispatcher = echo()
    unrelated = {
        "provider": "openai",
        "base_url": "https://unrelated.example/v1",
        "api_key": "personal",
        "models": ["private"],
    }
    client.put("/api/config/custom-models/personal", json=unrelated).raise_for_status()
    joined = client.post(
        "/api/team-gateway/join",
        json={"base_url": "http://localhost:8333/v1", "code": invite["code"]},
    )
    assert joined.status_code == 200 and not joined.json()["error"], joined.text
    assert "token" not in joined.text and "upstream-secret" not in joined.text
    connection_id = joined.json()["id"]
    models = client.get("/api/config/custom-models").json()["models"]
    selection = next(m for m in models if m["id"].startswith("echo_team_"))["selection_ids"][0]
    assert (
        dispatcher.call(
            ModelRequest(model=selection, messages=[Message(role="user", content="hello")])
        ).text
        == "TEAM_SYNC_OK"
    )
    client.close()
    client, dispatcher = echo()
    assert client.get("/api/team-gateway/connections").json()["connections"][0]["connected"]
    assert (
        dispatcher.call(
            ModelRequest(model=selection, messages=[Message(role="user", content="again")])
        ).text
        == "TEAM_SYNC_OK"
    )
    store.pause("assistant")
    client.post(f"/api/team-gateway/connections/{connection_id}/sync", json={}).raise_for_status()
    models = client.get("/api/config/custom-models").json()["models"]
    assert [m["id"] for m in models] == ["personal"]
    request = ModelRequest(
        model=selection, messages=[Message(role="user", content="stale selection")]
    )
    with pytest.raises(ValueError, match="所选模型已下线"):
        dispatcher.call(request)
    with pytest.raises(ValueError, match="所选模型已下线"):
        list(dispatcher.call_stream(request))
    store.publish("assistant", 2)
    client.post(f"/api/team-gateway/connections/{connection_id}/sync", json={}).raise_for_status()
    assert (
        dispatcher.call(
            ModelRequest(model=selection, messages=[Message(role="user", content="restored")])
        ).text
        == "TEAM_SYNC_OK"
    )
    client.delete(f"/api/team-gateway/connections/{connection_id}").raise_for_status()
    assert [m["id"] for m in client.get("/api/config/custom-models").json()["models"]] == [
        "personal"
    ]
    client.close()


def test_model_config_and_publication_read_together(tmp_path):
    _, store, invite = published(tmp_path)
    member = store.exchange(invite["code"])["member_id"]
    old = store.permitted_model(member, "assistant")
    store.save_model("assistant", {**old, "upstream_model": "untested"})
    with pytest.raises(HTTPException):
        store.permitted_model(member, "assistant")
    assert old["upstream_model"] == "source-model"
    with pytest.raises(HTTPException):
        store.publish("assistant", old["version"])


def test_background_sync_starts_and_stops(tmp_path):
    async def scenario():
        gateway, _, invite = published(tmp_path / 'gateway')
        applied = asyncio.Event()
        service = TeamConnections(tmp_path / 'connections.db', lambda c, m: applied.set(),
                                  transport=httpx.ASGITransport(app=gateway))
        service.start('http://localhost:8333/v1', invite['code'])
        await service.start_worker()
        try:
            await asyncio.wait_for(applied.wait(), 3)
            assert service.rows()[0]['connected']
        finally:
            await service.stop_worker()
        assert service.worker.done()
    asyncio.run(scenario())
