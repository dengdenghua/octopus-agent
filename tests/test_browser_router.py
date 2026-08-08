from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from runtime.platform.ui.app import create_app
from runtime.platform.ui.browser_router import create_browser_router
from runtime.safety.auth import Identity, IdentityStore


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OCTOPUS_DATA_DIR", str(tmp_path / "data"))
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


def test_browser_session_health_surfaces_recovery_proof() -> None:
    from runtime.platform.runtime_policy.browser_sessions import BrowserSessionCenter

    center = BrowserSessionCenter({"headless": True}, now=lambda: 100)
    session = center.ensure("recovering")
    session["recovered_from_crash"] = True

    before = center.health_report("recovering")
    center.record_action(session, "navigate", "https://example.test")
    after = center.health_report("recovering")

    assert before["recovery_proof"]["schema"] == ("octopus.browser_session_recovery_proof.v1")
    assert before["recovery_proof"]["recovered_from_crash"] is True
    assert before["recovery_proof"]["requires_operator_review"] is True
    assert "recovered_from_crash" in before["issues"]
    assert before["diagnostics"][0]["code"] == "recovered_from_crash"
    assert "revalidate_session" in before["recommended_actions"]
    assert after["recovery_proof"]["revalidated"] is True
    assert after["recovery_proof"]["requires_operator_review"] is False
    assert "recovered_from_crash" not in after["issues"]
    assert "revalidate_session" not in after["recommended_actions"]


def test_browser_config_update(client: TestClient) -> None:
    response = client.put(
        "/api/browser/config",
        json={
            "connection_mode": "extension",
            "viewport_width": 1024,
            "viewport_height": 768,
            "headless": False,
            "relay_allowed_hosts": ["https://Example.test/path", "*.trusted.test"],
            "relay_blocked_hosts": "blocked.test, https://evil.test/x",
            "relay_require_allowlist": True,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["connection_mode"] == "extension"
    assert data["viewport_width"] == 1024
    assert data["viewport_height"] == 768
    assert data["headless"] is False
    assert data["relay_allowed_hosts"] == ["example.test", "*.trusted.test"]
    assert data["relay_blocked_hosts"] == ["blocked.test", "evil.test"]
    assert data["relay_require_allowlist"] is True


def test_browser_relay_policy_persists_across_app_restart(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OCTOPUS_DATA_DIR", str(data_dir))
    monkeypatch.delenv("OCTOPUS_BROWSER_EXTENSION_DIR", raising=False)

    first = TestClient(create_app())
    response = first.put(
        "/api/browser/config",
        json={
            "relay_allowed_hosts": ["https://Example.test/path", "*.trusted.test"],
            "relay_blocked_hosts": "blocked.test, https://evil.test/x",
            "relay_require_allowlist": True,
        },
    )

    policy_path = data_dir / "browser_policy.json"
    assert response.status_code == 200
    assert policy_path.exists()
    persisted = json.loads(policy_path.read_text(encoding="utf-8"))
    assert persisted["schema"] == "octopus.browser_relay_site_policy.v1"
    assert persisted["relay_allowed_hosts"] == ["example.test", "*.trusted.test"]
    assert persisted["relay_blocked_hosts"] == ["blocked.test", "evil.test"]
    assert persisted["relay_require_allowlist"] is True

    second = TestClient(create_app())
    loaded = second.get("/api/browser/config").json()

    assert loaded["relay_allowed_hosts"] == ["example.test", "*.trusted.test"]
    assert loaded["relay_blocked_hosts"] == ["blocked.test", "evil.test"]
    assert loaded["relay_require_allowlist"] is True


def test_browser_relay_policy_recovers_from_backup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OCTOPUS_DATA_DIR", str(data_dir))
    monkeypatch.delenv("OCTOPUS_BROWSER_EXTENSION_DIR", raising=False)
    (data_dir / "browser_policy.json").write_text("{not json", encoding="utf-8")
    (data_dir / "browser_policy.json.bak").write_text(
        json.dumps(
            {
                "schema": "octopus.browser_relay_site_policy.v1",
                "relay_allowed_hosts": ["https://trusted.test/path"],
                "relay_blocked_hosts": ["blocked.test"],
                "relay_require_allowlist": True,
            },
        ),
        encoding="utf-8",
    )

    restored = TestClient(create_app()).get("/api/browser/config").json()

    assert restored["relay_allowed_hosts"] == ["trusted.test"]
    assert restored["relay_blocked_hosts"] == ["blocked.test"]
    assert restored["relay_require_allowlist"] is True


def test_browser_relay_persisted_strict_allowlist_blocks_after_restart(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OCTOPUS_DATA_DIR", str(data_dir))
    monkeypatch.delenv("OCTOPUS_BROWSER_EXTENSION_DIR", raising=False)
    first = TestClient(create_app())
    first.put(
        "/api/browser/config",
        json={
            "relay_require_allowlist": True,
            "relay_allowed_hosts": ["*.trusted.test"],
        },
    )

    second = TestClient(create_app())
    second.post(
        "/api/browser/relay/heartbeat",
        json={
            "extension_version": "test",
            "active_tab": {"id": 1, "url": "https://example.test", "title": "Example"},
        },
    )

    response = second.post(
        "/api/browser/relay/command",
        json={
            "action": "navigate",
            "url": "https://example.test/path",
            "timeout_seconds": 0.1,
        },
    )

    assert response.status_code == 403
    detail = response.json()["detail"]
    assert detail["site_policy"]["decision"] == "block"
    assert detail["site_policy"]["reason"] == "host_not_allowed"
    assert detail["site_policy"]["persisted"] is True
    assert detail["site_policy"]["policy_path"].endswith("browser_policy.json")


def test_browser_system_info_detects_macos_chrome_path(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_exists = Path.exists
    chrome_path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

    monkeypatch.setattr("shutil.which", lambda _candidate: None)

    def fake_exists(path: Path) -> bool:
        # as_posix: on Windows str() yields backslashes and would never
        # match the posix literal above.
        return path.as_posix() == chrome_path or original_exists(path)

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
    assert data["site_policy"]["schema"] == "octopus.browser_relay_site_policy.v1"


def test_browser_relay_websocket_respects_gateway_auth() -> None:
    store = IdentityStore()
    store.add(
        Identity(actor_id="extension", roles=("operator",)),
        api_key_plaintext="sk-extension",
    )
    app = FastAPI()
    app.include_router(create_browser_router(identity_store=store, require_auth=True))
    client = TestClient(app)

    with (
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect("/api/browser/relay/ws"),
    ):
        pass

    with client.websocket_connect("/api/browser/relay/ws?token=sk-extension") as websocket:
        websocket.send_json(
            {
                "type": "heartbeat",
                "extension_version": "auth-test",
                "active_tab": {"id": 3, "url": "https://example.test"},
            }
        )
        deadline = time.time() + 1
        while time.time() < deadline:
            response = client.get(
                "/api/browser/relay/status",
                headers={"Authorization": "Bearer sk-extension"},
            )
            if response.json().get("active_tab", {}).get("id") == 3:
                break
            time.sleep(0.02)
        else:
            pytest.fail("authenticated websocket heartbeat was not observed")

    assert response.status_code == 200
    assert response.json()["extension_version"] == "auth-test"


def test_authenticated_browser_sessions_are_owner_bound() -> None:
    store = IdentityStore()
    store.add(Identity(actor_id="alice"), api_key_plaintext="sk-alice")
    store.add(Identity(actor_id="bob"), api_key_plaintext="sk-bob")
    app = FastAPI()
    app.include_router(create_browser_router(identity_store=store, require_auth=True))
    client = TestClient(app)

    assert (
        client.post(
            "/api/browser/launch",
            headers={"Authorization": "Bearer sk-alice"},
            json={"session_id": "alice-session"},
        ).status_code
        == 200
    )
    assert (
        client.get(
            "/api/browser/page-info",
            headers={"Authorization": "Bearer sk-bob"},
            params={"session_id": "alice-session"},
        ).status_code
        == 404
    )


def test_browser_relay_command_includes_site_policy(client: TestClient) -> None:
    client.post(
        "/api/browser/relay/heartbeat",
        json={
            "extension_version": "test",
            "active_tab": {"id": 1, "url": "https://example.test", "title": "Example"},
        },
    )
    holder: dict[str, object] = {}

    def send_command() -> None:
        holder["response"] = client.post(
            "/api/browser/relay/command",
            json={
                "action": "navigate",
                "url": "https://example.test/page",
                "timeout_seconds": 1,
            },
        )

    thread = threading.Thread(target=send_command)
    thread.start()
    command = None
    deadline = time.time() + 1
    while time.time() < deadline and command is None:
        heartbeat = client.post("/api/browser/relay/heartbeat", json={})
        commands = heartbeat.json()["commands"]
        command = commands[0] if commands else None
        if command is None:
            time.sleep(0.02)
    assert command is not None
    assert command["site_policy"]["decision"] == "allow"
    client.post(
        "/api/browser/relay/result",
        json={"id": command["id"], "result": {"ok": True, "url": "https://example.test/page"}},
    )
    thread.join(timeout=2)
    assert "response" in holder
    response = holder["response"]
    assert response.status_code == 200
    assert response.json()["site_policy"]["target_host"] == "example.test"


def test_browser_relay_websocket_pushes_command_and_accepts_result(
    client: TestClient,
) -> None:
    with client.websocket_connect("/api/browser/relay/ws") as websocket:
        websocket.send_json(
            {
                "type": "heartbeat",
                "extension_version": "test-ws",
                "active_tab": {
                    "id": 11,
                    "url": "https://example.test",
                    "title": "Example",
                },
            }
        )
        deadline = time.time() + 1
        while time.time() < deadline:
            status = client.get("/api/browser/relay/status").json()
            if status.get("active_tab", {}).get("id") == 11:
                break
            time.sleep(0.02)
        else:
            pytest.fail("websocket heartbeat was not observed")
        assert status["push_connected"] is True

        invalid_timeout = client.post(
            "/api/browser/relay/command",
            json={"action": "click", "selector": "#go", "timeout_seconds": "never"},
        )
        assert invalid_timeout.status_code == 400

        holder: dict[str, object] = {}

        def send_command() -> None:
            holder["response"] = client.post(
                "/api/browser/relay/command",
                json={
                    "action": "click",
                    "selector": "#go",
                    "timeout_seconds": 2,
                },
            )

        thread = threading.Thread(target=send_command)
        thread.start()
        pushed = websocket.receive_json()
        assert pushed["type"] == "commands"
        assert len(pushed["commands"]) == 1
        command = pushed["commands"][0]
        assert command["action"] == "click"
        assert command["lease"]["tab"]["id"] == 11
        assert time.time() < command["deadline_at"] <= time.time() + 2

        websocket.send_json(
            {
                "type": "result",
                "id": command["id"],
                "active_tab": {
                    "id": 11,
                    "url": "https://example.test/done",
                    "title": "Done",
                },
                "result": {"ok": True, "url": "https://example.test/done"},
            }
        )
        thread.join(timeout=3)

    assert "response" in holder
    response = holder["response"]
    assert response.status_code == 200
    assert response.json()["url"] == "https://example.test/done"
    assert client.get("/api/browser/relay/status").json()["push_connected"] is False


def test_browser_relay_command_carries_tab_control_lease(client: TestClient) -> None:
    client.post(
        "/api/browser/relay/heartbeat",
        json={
            "extension_version": "test",
            "active_tab": {"id": 7, "url": "https://example.test", "title": "Example"},
        },
    )
    holder: dict[str, object] = {}

    def send_command() -> None:
        holder["response"] = client.post(
            "/api/browser/relay/command",
            json={"action": "state", "max_items": 10, "timeout_seconds": 1},
        )

    thread = threading.Thread(target=send_command)
    thread.start()
    command = None
    deadline = time.time() + 1
    while time.time() < deadline and command is None:
        heartbeat = client.post("/api/browser/relay/heartbeat", json={})
        commands = heartbeat.json()["commands"]
        command = commands[0] if commands else None
        if command is None:
            time.sleep(0.02)

    assert command is not None
    assert command["lease"]["schema"] == "octopus.browser_relay_tab_lease.v1"
    assert command["lease"]["tab"]["id"] == 7
    assert command["lease"]["require_same_tab"] is True
    assert command["lease"]["read_only"] is True

    status = client.get("/api/browser/relay/status").json()
    assert status["control"]["mode"] == "agent_active"

    client.post(
        "/api/browser/relay/result",
        json={"id": command["id"], "result": {"ok": True}},
    )
    thread.join(timeout=2)

    assert holder["response"].status_code == 200
    assert holder["response"].json()["control"]["mode"] == "idle"


def test_browser_relay_stop_interrupts_active_lease(client: TestClient) -> None:
    client.post(
        "/api/browser/relay/heartbeat",
        json={
            "extension_version": "test",
            "active_tab": {"id": 7, "url": "https://example.test", "title": "Example"},
        },
    )
    holder: dict[str, object] = {}

    def send_command() -> None:
        holder["response"] = client.post(
            "/api/browser/relay/command",
            json={"action": "type", "selector": "#q", "text": "hello", "timeout_seconds": 2},
        )

    thread = threading.Thread(target=send_command)
    thread.start()
    command = None
    deadline = time.time() + 1
    while time.time() < deadline and command is None:
        heartbeat = client.post("/api/browser/relay/heartbeat", json={})
        commands = heartbeat.json()["commands"]
        command = commands[0] if commands else None
        if command is None:
            time.sleep(0.02)

    assert command is not None

    stopped = client.post(
        "/api/browser/relay/control",
        json={"action": "stop", "reason": "operator_stop"},
    )
    thread.join(timeout=2)

    assert stopped.status_code == 200
    assert stopped.json()["control"]["mode"] == "interrupted"
    assert holder["response"].status_code == 500
    assert "interrupted" in holder["response"].text

    blocked = client.post(
        "/api/browser/relay/command",
        json={"action": "extract", "timeout_seconds": 0.1},
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["control"]["mode"] == "interrupted"

    resumed = client.post("/api/browser/relay/control", json={"action": "resume"})
    assert resumed.status_code == 200
    assert resumed.json()["control"]["mode"] == "idle"


def test_browser_relay_blocklist_blocks_navigation(client: TestClient) -> None:
    client.post(
        "/api/browser/relay/heartbeat",
        json={
            "extension_version": "test",
            "active_tab": {"id": 1, "url": "https://example.test", "title": "Example"},
        },
    )
    client.put("/api/browser/config", json={"relay_blocked_hosts": ["blocked.test"]})

    response = client.post(
        "/api/browser/relay/command",
        json={
            "action": "navigate",
            "url": "https://blocked.test/path",
            "timeout_seconds": 0.1,
        },
    )

    assert response.status_code == 403
    detail = response.json()["detail"]
    assert detail["site_policy"]["decision"] == "block"
    assert detail["site_policy"]["reason"] == "host_blocked"


def test_browser_relay_require_allowlist(client: TestClient) -> None:
    client.post(
        "/api/browser/relay/heartbeat",
        json={
            "extension_version": "test",
            "active_tab": {"id": 1, "url": "https://example.test", "title": "Example"},
        },
    )
    client.put(
        "/api/browser/config",
        json={
            "relay_require_allowlist": True,
            "relay_allowed_hosts": ["*.trusted.test"],
        },
    )

    blocked = client.post(
        "/api/browser/relay/command",
        json={
            "action": "navigate",
            "url": "https://example.test/path",
            "timeout_seconds": 0.1,
        },
    )
    allowed_holder: dict[str, object] = {}

    def send_allowed() -> None:
        allowed_holder["response"] = client.post(
            "/api/browser/relay/command",
            json={
                "action": "navigate",
                "url": "https://app.trusted.test/path",
                "timeout_seconds": 1,
            },
        )

    thread = threading.Thread(target=send_allowed)
    thread.start()
    command = None
    deadline = time.time() + 1
    while time.time() < deadline and command is None:
        heartbeat = client.post("/api/browser/relay/heartbeat", json={})
        commands = heartbeat.json()["commands"]
        command = commands[0] if commands else None
        if command is None:
            time.sleep(0.02)
    assert command is not None
    client.post(
        "/api/browser/relay/result",
        json={"id": command["id"], "result": {"ok": True}},
    )
    thread.join(timeout=2)

    assert blocked.status_code == 403
    assert blocked.json()["detail"]["site_policy"]["reason"] == "host_not_allowed"
    assert allowed_holder["response"].status_code == 200


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
