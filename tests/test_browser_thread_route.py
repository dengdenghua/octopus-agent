import threading
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from runtime.platform.ui._browser_thread_route import BrowserThreadRoute


def test_browser_requests_share_owner_thread_and_preserve_validation():
    app = FastAPI()
    router = APIRouter(route_class=BrowserThreadRoute)

    @router.get("/owner")
    def owner(value: int):
        return {"thread": threading.get_ident(), "value": value}

    app.include_router(router)
    with TestClient(app) as client:
        with ThreadPoolExecutor(max_workers=4) as callers:
            responses = list(callers.map(lambda i: client.get(f"/owner?value={i}"), range(8)))
        assert all(response.status_code == 200 for response in responses)
        assert len({response.json()["thread"] for response in responses}) == 1
        assert [response.json()["value"] for response in responses] == list(range(8))
        assert client.get("/owner?value=invalid").status_code == 422
