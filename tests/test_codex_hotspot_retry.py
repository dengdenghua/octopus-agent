from concurrent.futures import ThreadPoolExecutor

import httpx
from fastapi import HTTPException
from fastapi.testclient import TestClient

from runtime.sensing.gateway.codex_hotspot import create_hotspot
from runtime.sensing.gateway.hotspot_store import HotspotStore
from tests.test_codex_hotspot import Auth, activate


def test_identical_request_is_never_resent_or_charged_twice(tmp_path):
    seen = []

    def upstream(request):
        seen.append(request)
        return httpx.Response(503, text="temporary outage")

    with TestClient(
        create_hotspot(tmp_path, auth=Auth(tmp_path), transport=httpx.MockTransport(upstream)),
        base_url="http://127.0.0.1:8322",
    ) as client:
        _, headers, owner = activate(client, tmp_path)
        headers["Idempotency-Key"] = "logical-request-1"
        body = {"model": "m", "input": "hello"}
        assert client.post("/v1/responses", headers=headers, json=body).status_code == 503
        assert client.post("/v1/responses", headers=headers, json=body).status_code == 409
        assert (
            client.post(
                "/v1/responses", headers=headers, json={**body, "input": "changed"}
            ).status_code
            == 409
        )
        assert len(seen) == 1
        assert client.get("/admin/status", headers=owner).json()["members"][0]["used"] == 1


def test_receipt_is_atomic_durable_and_member_scoped(tmp_path):
    store = HotspotStore(tmp_path)
    first = store.invite("a")
    second = store.invite("b")
    store.set_enabled(True)

    def reserve(_):
        try:
            store.authorize(first["token"], reserve=True, request_key="same", body_digest="digest")
            return 200
        except HTTPException as exc:
            return exc.status_code

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(reserve, range(8)))
    assert results.count(200) == 1 and results.count(409) == 7
    reopened = HotspotStore(tmp_path)
    reopened.authorize(second["token"], reserve=True, request_key="same", body_digest="digest")
    assert all(member["used"] == 1 for member in reopened.list())
    try:
        reopened.authorize(first["token"], reserve=True, request_key="same", body_digest="digest")
    except HTTPException as exc:
        assert exc.status_code == 409
    else:
        raise AssertionError("receipt was lost on reopen")
