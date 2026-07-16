from __future__ import annotations

import json
import shutil
import socket
import threading
import time
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from runtime.platform.ui.browser_router import create_browser_router
from runtime.safety.auth import Identity, IdentityStore

playwright = pytest.importorskip("playwright.sync_api")
uvicorn = pytest.importorskip("uvicorn")

ROOT = Path(__file__).resolve().parents[1]
SOURCE_EXTENSION = ROOT / "extensions" / "octopus-browser-relay"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def request_json(
    base_url: str,
    path: str,
    body: dict[str, Any] | None = None,
    timeout: float = 8,
    token: str = "",
) -> dict[str, Any]:
    payload = None if body is None else json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        f"{base_url}{path}",
        data=payload,
        method="GET" if body is None else "POST",
        headers=headers,
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def wait_until(predicate: Any, timeout: float = 8) -> Any:
    deadline = time.time() + timeout
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            result = predicate()
            if result:
                return result
        except Exception as exc:  # noqa: BLE001 - retry startup races
            last_error = exc
        time.sleep(0.1)
    if last_error:
        raise AssertionError(f"condition did not become true: {last_error}") from last_error
    raise AssertionError("condition did not become true")


def loaded_extension_id(context: Any) -> str:
    if context.service_workers:
        return str(context.service_workers[0].url).split("/")[2]
    page = context.new_page()
    try:
        page.goto("chrome://extensions")
        extension_ids = page.evaluate(
            """() => {
              const manager = document.querySelector('extensions-manager');
              const list = manager?.shadowRoot?.querySelector('extensions-item-list');
              return [...(list?.shadowRoot?.querySelectorAll('extensions-item') || [])]
                .filter(item => item.data?.name === 'Octopus Agent')
                .map(item => item.id);
            }"""
        )
    finally:
        page.close()
    if not extension_ids:
        raise AssertionError("Octopus extension was not loaded by Chromium")
    return str(extension_ids[0])


@pytest.fixture
def live_extension_runtime(
    request: pytest.FixtureRequest,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[str, Any, Path, str]]:
    require_auth = bool(getattr(request, "param", False))
    api_key = "sk-chrome-extension" if require_auth else ""
    port = free_port()
    extension = tmp_path / "extension"
    shutil.copytree(SOURCE_EXTENSION, extension)
    for filename in ("background.js", "manifest.json"):
        path = extension / filename
        path.write_text(
            path.read_text(encoding="utf-8").replace(":8000", f":{port}"),
            encoding="utf-8",
        )

    monkeypatch.setenv("OCTOPUS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("OCTOPUS_BROWSER_EXTENSION_DIR", str(extension))
    app = FastAPI()
    identity_store = None
    if require_auth:
        identity_store = IdentityStore()
        identity_store.add(
            Identity(actor_id="chrome-extension"),
            api_key_plaintext=api_key,
        )
    app.include_router(
        create_browser_router(
            require_auth=require_auth,
            identity_store=identity_store,
        )
    )

    @app.get("/fixture", response_class=HTMLResponse)
    def fixture_page() -> str:
        return """
        <!doctype html>
        <title>Relay fixture</title>
        <form id="search-form">
          <label for="query">Query</label>
          <input id="query" value="before">
          <input id="password" type="password" value="secret">
          <button type="submit">Search</button>
        </form>
        <output id="submitted">0</output>
        <script>
          const query = document.querySelector("#query");
          query.addEventListener("input", () => document.title = `Query: ${query.value}`);
          document.querySelector("#search-form").addEventListener("submit", event => {
            event.preventDefault();
            const output = document.querySelector("#submitted");
            output.textContent = String(Number(output.textContent) + 1);
          });
        </script>
        """

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()
    wait_until(lambda: server.started)

    context = None
    runtime = playwright.sync_playwright().start()
    try:
        context = runtime.chromium.launch_persistent_context(
            user_data_dir=str(tmp_path / "profile"),
            channel="chromium",
            headless=True,
            args=[
                f"--disable-extensions-except={extension}",
                f"--load-extension={extension}",
            ],
        )
    except playwright.Error as exc:
        runtime.stop()
        server.should_exit = True
        server_thread.join(timeout=5)
        pytest.skip(f"Chromium extension mode is unavailable: {exc}")

    try:
        yield f"http://127.0.0.1:{port}", context, extension, api_key
    finally:
        context.close()
        runtime.stop()
        server.should_exit = True
        server_thread.join(timeout=5)


def test_real_chrome_extension_observes_and_operates_active_tab(
    live_extension_runtime: tuple[str, Any, Path, str],
) -> None:
    base_url, context, _extension, _api_key = live_extension_runtime
    page = context.pages[0] if context.pages else context.new_page()
    page.goto(f"{base_url}/fixture")

    status = wait_until(
        lambda: (
            current
            if (current := request_json(base_url, "/api/browser/relay/status")).get(
                "push_connected"
            )
            and "/fixture" in str(current.get("active_tab", {}).get("url", ""))
            else None
        ),
        timeout=10,
    )
    assert status["connected"] is True
    assert status["push_connected"] is True

    state = request_json(
        base_url,
        "/api/browser/relay/command",
        {"action": "state", "max_items": 10, "timeout_seconds": 5},
    )
    assert state["ok"] is True
    assert state["inputs"][0]["selector"] == "#query"
    assert state["inputs"][0]["value"] == "before"
    assert state["inputs"][1]["value"] is None

    typed = request_json(
        base_url,
        "/api/browser/relay/command",
        {
            "action": "type",
            "selector": "#query",
            "text": "after",
            "clear": True,
            "timeout_seconds": 5,
        },
    )
    assert typed["ok"] is True
    assert page.locator("#query").input_value() == "after"
    assert page.title() == "Query: after"

    pressed = request_json(
        base_url,
        "/api/browser/relay/command",
        {
            "action": "press",
            "selector": "#query",
            "key": "Enter",
            "timeout_seconds": 5,
        },
    )
    assert pressed["ok"] is True
    assert page.locator("#submitted").text_content() == "1"


@pytest.mark.parametrize("live_extension_runtime", [True], indirect=True)
def test_sidepanel_pairing_connects_extension_to_authenticated_gateway(
    live_extension_runtime: tuple[str, Any, Path, str],
) -> None:
    base_url, context, _extension, api_key = live_extension_runtime
    extension_id = loaded_extension_id(context)

    sidepanel = context.new_page()
    sidepanel.goto(f"chrome-extension://{extension_id}/sidepanel.html")
    sidepanel.locator("#authToggleButton").click()
    sidepanel.locator("#authTokenInput").fill(api_key)
    sidepanel.locator('#authForm button[type="submit"]').click()
    sidepanel.locator("#authStatus").get_by_text("连接密钥已保存并重新连接。").wait_for()

    page = context.new_page()
    page.goto(f"{base_url}/fixture")
    status = wait_until(
        lambda: (
            current
            if (
                current := request_json(
                    base_url,
                    "/api/browser/relay/status",
                    token=api_key,
                )
            ).get("push_connected")
            and "/fixture" in str(current.get("active_tab", {}).get("url", ""))
            else None
        ),
        timeout=10,
    )
    assert status["connected"] is True

    state = request_json(
        base_url,
        "/api/browser/relay/command",
        {"action": "state", "max_items": 10, "timeout_seconds": 5},
        token=api_key,
    )
    assert state["ok"] is True
    assert state["inputs"][0]["selector"] == "#query"
