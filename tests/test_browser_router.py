from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from runtime.platform.ui.app import create_app


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OCTOPUS_BROWSER_EXTENSION_DIR", raising=False)
    return TestClient(create_app())


def test_browser_session_launch_and_list(client: TestClient) -> None:
    response = client.post(
        "/api/browser/launch",
        json={"session_id": "s1", "headless": True},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "launched"
    assert data["session"]["session_id"] == "s1"
    assert data["session"]["project_id"] == "s1"
    assert data["session"]["profile_id"] == "s1"
    assert data["session"]["automation_mode"] == "browser_context"
    assert data["session"]["uses_system_mouse"] is False
    assert data["session"]["desktop_lease_required"] is False

    sessions = client.get("/api/browser/sessions")
    assert sessions.status_code == 200
    assert sessions.json()["count"] == 1

    page_info = client.get("/api/browser/page-info", params={"session_id": "s1"})
    assert page_info.status_code == 200
    assert page_info.json() == {"url": "", "title": ""}


def test_browser_config_update(client: TestClient) -> None:
    response = client.put(
        "/api/browser/config",
        json={
            "connection_mode": "extension",
            "viewport_width": 1024,
            "viewport_height": 768,
            "headless": False,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["connection_mode"] == "extension"
    assert data["viewport_width"] == 1024
    assert data["viewport_height"] == 768
    assert data["headless"] is False


def test_browser_system_info_detects_macos_chrome_path(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_exists = Path.exists
    chrome_path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

    monkeypatch.setattr("shutil.which", lambda _candidate: None)

    def fake_exists(path: Path) -> bool:
        return str(path) == chrome_path or original_exists(path)

    monkeypatch.setattr(Path, "exists", fake_exists)

    response = client.get("/api/browser/system-info")

    assert response.status_code == 200
    browsers = response.json()["browsers"]
    assert any(
        browser["name"] == "chrome"
        and browser["path"] == chrome_path
        and browser["connection_modes"] == ["extension", "cdp"]
        for browser in browsers
    )


def test_browser_relay_heartbeat_and_status(client: TestClient) -> None:
    heartbeat = client.post(
        "/api/browser/relay/heartbeat",
        json={
            "extension_version": "test",
            "active_tab": {"id": 1, "url": "https://example.test", "title": "Example"},
        },
    )

    assert heartbeat.status_code == 200
    assert heartbeat.json()["ok"] is True

    status = client.get("/api/browser/relay/status")
    assert status.status_code == 200
    data = status.json()
    assert data["extension_version"] == "test"
    assert data["active_tab"]["title"] == "Example"


def test_browser_bookmarklet_callback_validation(client: TestClient) -> None:
    bad = client.get(
        "/api/browser/relay/bookmarklet-poll",
        params={"callback": "alert(1)"},
    )
    good = client.get(
        "/api/browser/relay/bookmarklet-poll",
        params={"callback": "octopus.cb", "url": "https://example.test"},
    )

    assert bad.status_code == 400
    assert good.status_code == 200
    assert good.headers["content-type"].startswith("application/javascript")
    assert good.text.startswith("octopus.cb(")


def test_browser_relay_connect_page_loads_bookmarklet(client: TestClient) -> None:
    response = client.get(
        "/api/browser/relay/connect-page",
        params={"api_base_url": "http://127.0.0.1:8000"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Octopus Chrome Relay Probe" in response.text
    assert "/api/browser/relay/bookmarklet.js" in response.text
    assert "browser desktop real Chrome profile relay ready" in response.text


def test_browser_open_real_chrome_relay_opens_local_connect_page(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    launched: list[list[str]] = []
    chrome_path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

    monkeypatch.setattr("shutil.which", lambda _candidate: None)
    original_exists = Path.exists

    def fake_exists(path: Path) -> bool:
        return str(path) == chrome_path or original_exists(path)

    monkeypatch.setattr(Path, "exists", fake_exists)
    monkeypatch.setattr(
        "subprocess.run",
        lambda args, **_kwargs: subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout="Google Chrome 123.0.0.0",
            stderr="",
        ),
    )
    monkeypatch.setattr(
        "subprocess.Popen",
        lambda args: launched.append([str(item) for item in args]),
    )

    response = client.post(
        "/api/browser/open-real-chrome-relay",
        json={"api_base_url": "http://127.0.0.1:8000"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["opened"] is True
    assert data["browser_path"] == chrome_path
    assert data["url"].startswith("http://127.0.0.1:8000/api/browser/relay/connect-page")
    assert launched == [[chrome_path, data["url"]]]


def test_browser_relay_connect_page_threads_relay_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from runtime.safety.auth.identity import Identity, IdentityStore

    store = IdentityStore()
    store.add(Identity(actor_id="user:relay-test"), api_key_plaintext="test-api-key")
    monkeypatch.setattr(
        "subprocess.run",
        lambda args, **_kwargs: subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout="Google Chrome 123.0.0.0",
            stderr="",
        ),
    )
    monkeypatch.setattr("subprocess.Popen", lambda _args: None)
    app = create_app(cocoloop_require_auth=True, cocoloop_identity_store=store)
    client = TestClient(app)

    open_response = client.post(
        "/api/browser/open-real-chrome-relay",
        json={"api_base_url": "http://127.0.0.1:8000"},
        headers={"Authorization": "Bearer test-api-key"},
    )

    assert open_response.status_code == 200
    open_payload = open_response.json()
    assert open_payload["ok"] is True
    assert "#relay_token=" in open_payload["url"]

    page_path = open_payload["url"].replace("http://127.0.0.1:8000", "").split("#", 1)[0]
    page = client.get(page_path)
    assert page.status_code == 200
    assert "octopus_relay_token=" in page.text
    assert "/api/browser/relay/bookmarklet.js" in page.text
    assert "/api/browser/relay/bookmarklet.js?relay_token=" not in page.text

    script = client.get("/api/browser/relay/bookmarklet.js")
    assert script.status_code == 200
    assert "relay_token=" not in script.text

    token = open_payload["url"].split("#relay_token=", 1)[1]
    poll = client.get(
        "/api/browser/relay/bookmarklet-poll",
        params={"callback": "octopus.cb"},
        cookies={"octopus_relay_token": token},
    )
    assert poll.status_code == 200

    bad = client.get("/api/browser/relay/connect-page")
    assert bad.status_code == 200
    bad_poll = client.get(
        "/api/browser/relay/bookmarklet-poll",
        params={"callback": "octopus.cb"},
    )
    assert bad_poll.status_code == 401


def test_browser_extension_path_uses_workspace_fallback(
    client: TestClient,
    tmp_path: Path,
) -> None:
    response = client.get("/api/browser/extension-path")

    assert response.status_code == 200
    data = response.json()
    # Fresh workspace with no env override and no existing dir falls
    # back to the committed product location ``extensions/octopus-browser-relay``.
    assert data["path"] == str(tmp_path / "extensions" / "octopus-browser-relay")
    assert data["exists"] is True
