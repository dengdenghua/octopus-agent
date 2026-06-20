from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from runtime.memory.learning.review_queue import ReviewQueue
from runtime.platform.runtime_policy.browser_sessions import BrowserSessionCenter
from runtime.platform.ui.browser_router import create_browser_router
from runtime.safety.replay.browser_desktop_replay import browser_session_replay_identity


def test_browser_session_center_snapshots_without_runtime_objects() -> None:
    config = {"headless": True}
    ticks = iter([10, 11])
    center = BrowserSessionCenter(config, now=lambda: next(ticks))

    session = center.ensure("workspace")
    center.record_action(session, "navigate", "https://example.com")

    snapshot = center.snapshot(session)
    assert snapshot == {
        "session_id": "workspace",
        "project_id": "workspace",
        "profile_id": "workspace",
        "profile_dir": "",
        "automation_mode": "browser_context",
        "uses_system_mouse": False,
        "desktop_lease_required": False,
        "is_launched": True,
        "created_at": 10,
        "last_activity": 11,
        "action_count": 1,
        "headless": True,
        "viewport_width": 1440,
        "viewport_height": 900,
        "mode": "mock",
        "runtime": "mock",
        "has_page": False,
        "healthy": True,
        "current_url": "",
        "current_title": "",
        "browser_regression_enabled": False,
        "browser_regression_mode": "off",
        "browser_regression_preview_url": "",
        "browser_regression_requires_visible_cursor": False,
    }


def test_browser_session_health_reports_recent_actions_and_failures() -> None:
    config = {"headless": True}
    ticks = iter([10, 11, 12, 13, 14, 15])
    center = BrowserSessionCenter(config, now=lambda: next(ticks))

    session = center.ensure("workspace")
    center.record_action(session, "navigate", "https://example.com")
    healthy = center.health_report("workspace")

    assert healthy["schema"] == "octopus.browser_session_health.v1"
    assert healthy["exists"] is True
    assert healthy["healthy"] is True
    assert healthy["score"] == 1.0
    assert healthy["recent_actions"][0]["action"] == "navigate"
    assert healthy["recent_actions"][0]["status"] == "ok"
    assert healthy["replay_ready"] is True

    center.record_action(
        session,
        "click",
        "#submit",
        status="failed",
        error="selector not found",
    )
    failed = center.health_report("workspace")

    assert failed["healthy"] is False
    assert "last_action_failed" in failed["issues"]
    assert failed["recent_actions"][-1]["error"] == "selector not found"


def test_browser_session_health_endpoint_reports_missing_and_ready_sessions() -> None:
    app = FastAPI()
    app.include_router(create_browser_router())
    client = TestClient(app)

    missing = client.get(
        "/api/browser/session/health",
        params={"session_id": "workspace"},
    ).json()
    assert missing["exists"] is False
    assert missing["issues"] == ["session_missing"]

    client.post(
        "/api/browser/session/ensure",
        json={"session_id": "workspace", "headless": True},
    )
    client.post(
        "/api/browser/navigate",
        json={"session_id": "workspace", "url": "https://example.test"},
    )
    ready = client.get(
        "/api/browser/session/health",
        params={"session_id": "workspace"},
    ).json()

    assert ready["exists"] is True
    assert ready["replay_ready"] is True
    assert ready["recent_actions"][-1]["action"] == "navigate"

    replay = client.get(
        "/api/browser/session/replay-case",
        params={"session_id": "workspace"},
    ).json()
    assert replay["schema"] == "octopus.browser_session_replay_case.v1"
    assert replay["case_id"].startswith("browser-session:")
    assert len(replay["fingerprint"]) == 16
    assert replay["replay_ready"] is True
    assert replay["health"]["healthy"] is True
    assert replay["last_action"]["action"] == "navigate"


def test_browser_session_replay_case_can_queue_operator_review(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("OCTOPUS_DATA_DIR", str(tmp_path / "data"))
    app = FastAPI()
    app.include_router(create_browser_router())
    client = TestClient(app)

    client.post(
        "/api/browser/session/ensure",
        json={"session_id": "workspace", "headless": True},
    )
    client.post(
        "/api/browser/navigate",
        json={"session_id": "workspace", "url": "https://example.test"},
    )
    response = client.post(
        "/api/browser/session/replay-case/queue",
        json={"session_id": "workspace", "reason": "operator wants to inspect replay"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["schema"] == "octopus.browser_session_replay_case_queue.v1"
    assert body["queue"]["created"] == 1
    item = body["queue"]["items"][0]
    assert item["target_bucket"] == "browser_desktop_replay"
    assert "review_queue" in item["tags"]
    assert item["metadata"]["schema"] == "octopus.browser_session_replay_case.v1"
    assert item["metadata"]["case_id"].startswith("browser-session:")
    assert len(item["metadata"]["fingerprint"]) == 16
    assert item["metadata"]["last_action"]["action"] == "navigate"

    summary = ReviewQueue(tmp_path / "data" / "review_queue.json").summary()
    assert summary["pending_count"] == 1


def test_browser_session_replay_identity_ignores_timestamps() -> None:
    first = browser_session_replay_identity(
        session_id="workspace",
        health={"healthy": True, "score": 1.0, "issues": []},
        actions=[
            {
                "action": "navigate",
                "detail": "https://example.test",
                "status": "ok",
                "timestamp": 10,
            }
        ],
    )
    second = browser_session_replay_identity(
        session_id="workspace",
        health={"healthy": True, "score": 1.0, "issues": []},
        actions=[
            {
                "action": "navigate",
                "detail": "https://example.test",
                "status": "ok",
                "timestamp": 999,
            }
        ],
    )

    assert first == second


def test_browser_session_status_does_not_launch_missing_session() -> None:
    app = FastAPI()
    app.include_router(create_browser_router())
    client = TestClient(app)

    response = client.get("/api/browser/session/status", params={"session_id": "workspace"})

    assert response.status_code == 200
    body = response.json()
    assert body["exists"] is False
    assert body["session"]["session_id"] == "workspace"
    assert body["session"]["uses_system_mouse"] is False
    assert body["session"]["desktop_lease_required"] is False
    assert body["session"]["is_launched"] is False
    assert body["session"]["viewport_width"] == 1440
    assert body["session"]["viewport_height"] == 900

    sessions = client.get("/api/browser/sessions").json()
    assert sessions == {"sessions": [], "count": 0}


def test_browser_session_ensure_and_reset_are_reflected_in_legacy_sessions() -> None:
    app = FastAPI()
    app.include_router(create_browser_router())
    client = TestClient(app)

    ensured = client.post(
        "/api/browser/session/ensure",
        json={"session_id": "workspace", "headless": False},
    )
    assert ensured.status_code == 200
    assert ensured.json()["session"]["headless"] is False

    sessions = client.get("/api/browser/sessions").json()
    assert sessions["count"] == 1
    assert sessions["sessions"][0]["session_id"] == "workspace"

    reset = client.post("/api/browser/session/reset", json={"session_id": "workspace"})
    assert reset.status_code == 200
    assert reset.json()["status"] == "closed"

    status = client.get(
        "/api/browser/session/status",
        params={"session_id": "workspace"},
    ).json()
    assert status["exists"] is False


def test_browser_session_ensure_persists_regression_settings() -> None:
    app = FastAPI()
    app.include_router(create_browser_router())
    client = TestClient(app)

    response = client.post(
        "/api/browser/session/ensure",
        json={
            "session_id": "workspace",
            "browser_regression_enabled": True,
            "browser_regression_mode": "human_cursor",
            "browser_regression_preview_url": "http://localhost:3000/preview",
            "browser_regression_requires_visible_cursor": True,
        },
    )

    assert response.status_code == 200
    session = response.json()["session"]
    assert session["browser_regression_enabled"] is True
    assert session["browser_regression_mode"] == "human_cursor"
    assert session["browser_regression_preview_url"] == "http://localhost:3000/preview"
    assert session["browser_regression_requires_visible_cursor"] is True

    status = client.get(
        "/api/browser/session/status",
        params={"session_id": "workspace"},
    ).json()
    assert status["session"]["browser_regression_enabled"] is True


def test_browser_session_viewport_is_session_scoped() -> None:
    app = FastAPI()
    app.include_router(create_browser_router())
    client = TestClient(app)

    alpha = client.post(
        "/api/browser/session/ensure",
        json={"session_id": "alpha"},
    ).json()["session"]
    beta = client.post(
        "/api/browser/session/ensure",
        json={"session_id": "beta"},
    ).json()["session"]

    assert alpha["viewport_width"] == 1440
    assert alpha["viewport_height"] == 900
    assert beta["viewport_width"] == 1440
    assert beta["viewport_height"] == 900

    response = client.post(
        "/api/browser/session/viewport",
        json={"session_id": "alpha", "width": 390, "height": 844},
    )

    assert response.status_code == 200
    resized = response.json()["session"]
    assert resized["viewport_width"] == 390
    assert resized["viewport_height"] == 844

    alpha_status = client.get(
        "/api/browser/session/status",
        params={"session_id": "alpha"},
    ).json()
    beta_status = client.get(
        "/api/browser/session/status",
        params={"session_id": "beta"},
    ).json()
    assert alpha_status["session"]["viewport_width"] == 390
    assert alpha_status["session"]["viewport_height"] == 844
    assert beta_status["session"]["viewport_width"] == 1440
    assert beta_status["session"]["viewport_height"] == 900

    log = client.get(
        "/api/browser/action-log",
        params={"session_id": "alpha"},
    ).json()
    assert log["actions"][-1]["action"] == "viewport"
    assert log["actions"][-1]["detail"] == "390x844"


def test_browser_sessions_are_project_scoped_profiles() -> None:
    app = FastAPI()
    app.include_router(create_browser_router())
    client = TestClient(app)

    alpha = client.post(
        "/api/browser/session/ensure",
        json={
            "session_id": "browser-alpha",
            "project_id": "Project Alpha",
            "profile_id": "Project Alpha",
        },
    ).json()["session"]
    beta = client.post(
        "/api/browser/session/ensure",
        json={
            "session_id": "browser-beta",
            "project_id": "Project Beta",
            "profile_id": "Project Beta",
        },
    ).json()["session"]

    assert alpha["project_id"] == "Project Alpha"
    assert beta["project_id"] == "Project Beta"
    assert alpha["profile_id"] == "project-alpha"
    assert beta["profile_id"] == "project-beta"
    assert alpha["profile_id"] != beta["profile_id"]
    assert alpha["automation_mode"] == "browser_context"
    assert alpha["uses_system_mouse"] is False
    assert alpha["desktop_lease_required"] is False
