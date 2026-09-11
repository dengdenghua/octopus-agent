import asyncio
import contextlib

import httpx
import pytest
from fastapi.testclient import TestClient

from runtime.sensing.gateway.codex_hotspot import create_hotspot
from tests.test_codex_hotspot import Auth, activate


@pytest.mark.parametrize(
    "extra",
    [
        {"tools": [{"type": "code_interpreter"}]},
        {"input": [{"type": "item_reference", "id": "private-id"}]},
        {
            "input": [
                {"role": "user", "content": [{"type": "input_file", "file_id": "private-file"}]}
            ]
        },
        {"previous_response_id": "private-response"},
    ],
)
def test_rejects_hosted_tools_and_owner_state_before_spending(tmp_path, extra):
    def upstream(_):
        raise AssertionError("must reject before upstream")

    with TestClient(
        create_hotspot(tmp_path, auth=Auth(tmp_path), transport=httpx.MockTransport(upstream)),
        base_url="http://127.0.0.1:8322",
    ) as client:
        _, headers, owner = activate(client, tmp_path)
        response = client.post(
            "/v1/responses", headers=headers, json={"model": "m", "input": "hi", **extra}
        )
        assert response.status_code == 400
        assert client.get("/admin/status", headers=owner).json()["members"][0]["used"] == 0


def test_cancellation_before_response_headers_releases_capacity(tmp_path):
    calls = 0

    async def upstream(_):
        nonlocal calls
        calls += 1
        if calls <= 2:
            raise asyncio.CancelledError
        return httpx.Response(
            200,
            content=b'data: {"type":"response.completed"}\n\n',
            headers={"content-type": "text/event-stream"},
        )

    with TestClient(
        create_hotspot(tmp_path, auth=Auth(tmp_path), transport=httpx.MockTransport(upstream)),
        base_url="http://127.0.0.1:8322",
    ) as client:
        _, headers, _ = activate(client, tmp_path)
        for _ in range(2):
            with contextlib.suppress(Exception, asyncio.CancelledError):
                client.post("/v1/responses", headers=headers, json={"model": "m", "input": "hi"})
        response = client.post("/v1/responses", headers=headers, json={"model": "m", "input": "hi"})
        assert response.status_code == 200
        assert calls == 3


def test_tool_result_and_string_content_pass_through(tmp_path):
    seen = []

    def upstream(request):
        seen.append(request.content)
        # Some upstream transports omit Content-Type; retain valid SSE support.
        return httpx.Response(200, content=b'data: {"type":"response.completed"}\n\n')

    with TestClient(
        create_hotspot(tmp_path, auth=Auth(tmp_path), transport=httpx.MockTransport(upstream)),
        base_url="http://127.0.0.1:8322",
    ) as client:
        _, headers, _ = activate(client, tmp_path)
        response = client.post(
            "/v1/responses",
            headers=headers,
            json={
                "model": "m",
                "input": [
                    {"role": "user", "content": "hello"},
                    {"type": "function_call", "name": "probe", "call_id": "c1", "arguments": "{}"},
                    {"type": "function_call_output", "call_id": "c1", "output": "LOCAL_TOOL_OK"},
                ],
            },
        )
        assert response.status_code == 200
        assert b"LOCAL_TOOL_OK" in seen[0]
