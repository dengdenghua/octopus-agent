import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from runtime.sensing.gateway.config_router import create_config_router
from runtime.sensing.gateway.hotspot_discovery import discover_hotspot, normalize_hotspot_url
from runtime.sensing.model_router.dispatch_router import ModelDispatchRouter
from runtime.sensing.model_router.models import Message, ModelRequest, ModelRouter


def test_discovery_keeps_token_server_side_and_does_not_follow_redirects():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"data": [{"id": "m"}, {"id": "m"}]})

    result = asyncio.run(
        discover_hotspot(
            {"base_url": "http://localhost:18322/v1/", "token": "invite-secret"},
            transport=httpx.MockTransport(handler),
        )
    )
    assert result["models"] == ["m"]
    assert seen[0].headers["authorization"] == "Bearer invite-secret"
    assert "invite-secret" not in json.dumps(result)
    with pytest.raises(HTTPException):
        asyncio.run(
            discover_hotspot(
                {"base_url": "http://localhost:18322/v1", "token": "invite-secret"},
                transport=httpx.MockTransport(
                    lambda _: httpx.Response(
                        302, headers={"Location": "https://other.example/v1/models"}
                    )
                ),
            )
        )


@pytest.mark.parametrize(
    "url",
    [
        "http://remote.example/v1",
        "https://user:secret@example.com/v1",
        "https://example.com/v1?token=secret",
        "file:///v1",
        "http://[invalid/v1",
    ],
)
def test_rejects_unsafe_hotspot_addresses(url):
    with pytest.raises(HTTPException):
        normalize_hotspot_url(url)


def test_echo_custom_model_dispatch_uses_responses_after_restart(tmp_path, monkeypatch):
    from runtime.sensing.model_router import openai_responses_router as transport_module

    original = transport_module.OpenAIResponsesModelRouter
    requests = []

    def upstream(request):
        requests.append(request)
        assert str(request.url).endswith("/v1/responses")
        event = {
            "type": "response.completed",
            "response": {
                "id": "r1",
                "model": "test-model",
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "ECHO_HOTSPOT_OK"}],
                    }
                ],
            },
        }
        return httpx.Response(200, content=("data: " + json.dumps(event) + "\n\n").encode())

    monkeypatch.setattr(
        transport_module,
        "OpenAIResponsesModelRouter",
        lambda **kw: original(**kw, client=httpx.Client(transport=httpx.MockTransport(upstream))),
    )

    class Fallback(ModelRouter):
        def call(self, request):
            raise AssertionError("must use selected hotspot")

    def create():
        dispatcher = ModelDispatchRouter(fallback=Fallback())
        bundle = create_config_router(
            stack=SimpleNamespace(planner=SimpleNamespace(router=dispatcher)),
            custom_models_path=tmp_path / "models.json",
        )
        app = FastAPI()
        app.include_router(bundle.router)
        return dispatcher, TestClient(app)

    dispatcher, client = create()
    response = client.put(
        "/api/config/custom-models/echo_hotspot_test",
        json={
            "name": "团队热点",
            "provider": "openai",
            "base_url": "http://localhost:18322/v1",
            "api_key": "invite-secret",
            "models": ["test-model"],
            "wire_api": "responses",
            "compat_profile": "echo_hotspot",
            "supports_tool_use": True,
        },
    )
    assert response.status_code == 200 and response.json()["_status"]["ok"], response.text
    assert "invite-secret" not in response.text
    selection = response.json()["model"]["selection_ids"][0]
    assert (
        dispatcher.call(
            ModelRequest(model=selection, messages=[Message(role="user", content="hello")])
        ).text
        == "ECHO_HOTSPOT_OK"
    )
    client.close()
    dispatcher, client = create()
    assert (
        dispatcher.call(
            ModelRequest(model=selection, messages=[Message(role="user", content="again")])
        ).text
        == "ECHO_HOTSPOT_OK"
    )
    tested = client.post("/api/config/custom-models/test", json={"id": "echo_hotspot_test"})
    assert tested.json()["ok"], tested.text
    assert tested.json()["message"] == "ECHO_HOTSPOT_OK"
    assert len(requests) == 3
    assert all(request.headers["authorization"] == "Bearer invite-secret" for request in requests)
    assert client.get("/api/config/custom-models").json()["models"][0]["wire_api"] == "responses"
    client.close()
