from __future__ import annotations

import platform
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from runtime.execution.suckers import computer_skills, computer_uia_skills
from runtime.memory.learning.review_queue import ReviewQueue
from runtime.safety.auth import Identity, IdentityStore
from runtime.safety.replay.browser_desktop_replay import computer_activity_replay_identity
from runtime.sensing.gateway.computer_router import create_computer_router


class _Rect:
    left = 0
    top = 0
    right = 200
    bottom = 100


class _Control:
    Name = "Router Button"
    ControlTypeName = "ButtonControl"
    ClassName = "Button"
    AutomationId = "routerButton"
    BoundingRectangle = _Rect()
    IsEnabled = True
    IsOffscreen = False

    def GetChildren(self) -> list[Any]:  # noqa: N802 - mirrors uiautomation API
        return []


class _FakeUia:
    def GetRootControl(self) -> _Control:  # noqa: N802 - mirrors uiautomation API
        return _Control()

    def GetForegroundControl(self) -> _Control:  # noqa: N802 - mirrors uiautomation API
        return _Control()


class _DynamicRect:
    def __init__(self, left: int, top: int, right: int, bottom: int) -> None:
        self.left = left
        self.top = top
        self.right = right
        self.bottom = bottom


class _DynamicControl:
    def __init__(
        self,
        name: str,
        control_type: str,
        rect: _DynamicRect,
        *,
        children: list[Any] | None = None,
    ) -> None:
        self.Name = name
        self.ControlTypeName = control_type
        self.ClassName = control_type.replace("Control", "")
        self.AutomationId = name.replace(" ", "")
        self.BoundingRectangle = rect
        self.IsEnabled = True
        self.IsOffscreen = False
        self._children = children or []

    def GetChildren(self) -> list[Any]:  # noqa: N802 - mirrors uiautomation API
        return self._children


class _FakeRankedUia:
    def __init__(self) -> None:
        self.button = _DynamicControl(
            "Router Button",
            "ButtonControl",
            _DynamicRect(300, 200, 420, 260),
        )
        self.root = _DynamicControl(
            "Router",
            "WindowControl",
            _DynamicRect(0, 0, 800, 600),
            children=[self.button],
        )

    def GetRootControl(self) -> _DynamicControl:  # noqa: N802 - mirrors uiautomation API
        return self.root

    def GetForegroundControl(self) -> _DynamicControl:  # noqa: N802 - mirrors uiautomation API
        return self.root


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(create_computer_router())
    return app


def _secured_app() -> FastAPI:
    store = IdentityStore()
    store.add(Identity(actor_id="alice"), api_key_plaintext="sk-alice")
    app = FastAPI()
    app.include_router(
        create_computer_router(
            identity_store=store,
            require_auth=True,
        )
    )
    return app


def test_uia_status_endpoint_reports_unavailable(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    monkeypatch.setattr(computer_uia_skills, "UIA_AVAILABLE", False)
    monkeypatch.setattr(computer_uia_skills, "uiautomation", None)
    monkeypatch.setattr(computer_uia_skills, "_UIA_LOAD_ERROR", None)

    data = TestClient(_app()).get("/api/computer/uia/status").json()
    assert data["ok"] is False
    assert data["available"] is False
    assert "uiautomation not installed" in data["error"]


def test_router_requires_auth_when_enabled() -> None:
    client = TestClient(_secured_app())

    assert client.get("/api/computer/status").status_code == 401
    assert client.get(
        "/api/computer/status",
        headers={"Authorization": "Bearer sk-alice"},
    ).status_code == 200


def test_status_reports_runtime_readiness_with_degraded_uia(monkeypatch):
    monkeypatch.setattr(
        computer_skills,
        "_screen_info",
        lambda: {"width": 1440, "height": 900, "cursor_x": 20, "cursor_y": 30},
    )
    monkeypatch.setattr(
        computer_uia_skills,
        "_computer_uia_status",
        lambda: {
            "ok": False,
            "available": False,
            "platform": "Darwin",
            "error": "uiautomation not installed",
        },
    )

    data = TestClient(_app()).get("/api/computer/status").json()

    assert data["schema"] == "octopus.computer_runtime_status.v1"
    assert data["ok"] is True
    assert data["ready"] is True
    assert data["health"] == "degraded"
    assert data["readiness"]["schema"] == "octopus.computer_runtime_readiness.v1"
    assert data["readiness"]["ready"] is True
    degraded_ids = {item["id"] for item in data["degraded_capabilities"]}
    assert degraded_ids == {"uia_semantic_grounding"}
    capability_ids = {item["id"] for item in data["capabilities"]}
    assert {
        "screen_observation",
        "preview_execute_contract",
        "lease_coordination",
        "uia_semantic_grounding",
        "replay_evidence",
    } <= capability_ids
    assert "install_or_enable_uia_backend" in data["recommended_actions"]
    assert data["replay_evidence"]["schema"] == "octopus.computer_replay_evidence_hint.v1"


def test_status_reports_blocked_when_screen_observation_fails(monkeypatch):
    monkeypatch.setattr(
        computer_skills,
        "_screen_info",
        lambda: {"error": "screen_info_failed: display unavailable"},
    )
    monkeypatch.setattr(
        computer_uia_skills,
        "_computer_uia_status",
        lambda: {"ok": True, "available": True, "platform": "Windows"},
    )

    data = TestClient(_app()).get("/api/computer/status").json()

    assert data["ok"] is False
    assert data["ready"] is False
    assert data["health"] == "blocked"
    assert [item["id"] for item in data["critical_blockers"]] == ["screen_observation"]
    assert "check_display_or_desktop_permissions" in data["recommended_actions"]


def test_uia_tree_and_find_endpoints(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    monkeypatch.setattr(computer_uia_skills, "UIA_AVAILABLE", True)
    monkeypatch.setattr(computer_uia_skills, "uiautomation", _FakeUia())
    monkeypatch.setattr(computer_uia_skills, "_UIA_LOAD_ERROR", None)

    client = TestClient(_app())
    tree = client.get("/api/computer/uia/tree").json()
    assert tree["ok"] is True
    assert tree["nodes"][0]["name"] == "Router Button"

    found = client.get("/api/computer/uia/find", params={"query": "router"}).json()
    assert found["ok"] is True
    assert found["count"] == 1
    assert found["matches"][0]["automation_id"] == "routerButton"


def test_plan_actions_uses_uia_grounding(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    monkeypatch.setattr(computer_uia_skills, "UIA_AVAILABLE", True)
    monkeypatch.setattr(computer_uia_skills, "uiautomation", _FakeUia())
    monkeypatch.setattr(computer_uia_skills, "_UIA_LOAD_ERROR", None)

    data = TestClient(_app()).post(
        "/api/computer/actions/plan",
        json={"goal": "click Router", "capture": False},
    ).json()
    assert data["ok"] is True
    action = data["suggestions"][0]["action"]
    assert action["action"] == "click"
    assert action["x"] == 100
    assert action["y"] == 50
    assert action["source"] == "uia"
    assert action["matched_control"]["name"] == "Router Button"
    assert action["replay_assertion"]["schema"] == "octopus.computer_uia_replay_assertion.v1"
    assert action["replay_assertion"]["trace_id"]
    assert action["replay_assertion"]["source_trace"]["schema"] == (
        "octopus.computer_uia_grounding_trace.v1"
    )
    assert action["replay_assertion"]["source_trace"]["matched_control"]["automation_id"] == (
        "routerButton"
    )
    assert action["replay_assertion"]["ok"] is True
    assert data["suggestions"][0]["preview_contract"]["schema"] == (
        "octopus.computer_preview_contract.v1"
    )
    assert data["suggestions"][0]["token"]


def test_plan_actions_prefers_interactive_uia_match(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    monkeypatch.setattr(computer_uia_skills, "UIA_AVAILABLE", True)
    monkeypatch.setattr(computer_uia_skills, "uiautomation", _FakeRankedUia())
    monkeypatch.setattr(computer_uia_skills, "_UIA_LOAD_ERROR", None)

    data = TestClient(_app()).post(
        "/api/computer/actions/plan",
        json={"goal": "click Router", "capture": False},
    ).json()
    action = data["suggestions"][0]["action"]
    assert action["x"] == 360
    assert action["y"] == 230
    assert action["matched_control"]["name"] == "Router Button"
    assert action["matched_control"]["score"] > 100
    assert action["replay_assertion"]["trace_id"]
    assert action["replay_assertion"]["ok"] is True


def test_execute_claims_computer_lease(monkeypatch):
    monkeypatch.setattr(
        computer_skills,
        "_mouse_move",
        lambda **kwargs: {"moved": True, **kwargs},
    )
    client = TestClient(_app())

    preview = client.post(
        "/api/computer/actions/preview",
        json={
            "action": "move",
            "x": 10,
            "y": 20,
            "lease_owner_id": "project-a",
            "lease_owner_label": "Project A",
        },
    ).json()
    assert preview["preview_contract"]["schema"] == (
        "octopus.computer_preview_contract.v1"
    )
    assert preview["preview_contract"]["requires_execute_token"] is True
    result = client.post(
        "/api/computer/actions/execute",
        json={"token": preview["token"], "lease_owner_id": "project-a"},
    ).json()

    assert result["ok"] is True
    assert result["preview_contract"]["contract_id"] == preview["preview_contract"]["contract_id"]
    assert result["execution_proof"]["schema"] == "octopus.computer_execution_proof.v1"
    assert result["execution_proof"]["preview_contract_id"] == preview["preview_contract"]["contract_id"]
    assert result["lease"]["held"] is True
    assert result["lease"]["owner_id"] == "project-a"
    status = client.get("/api/computer/status").json()
    assert status["lease"]["owner_label"] == "Project A"
    assert status["activity_count"] == 2
    assert status["recent_activity"][-1]["event"] == "action_executed"

    activity = client.get("/api/computer/activity").json()
    assert activity["schema"] == "octopus.computer_activity.v1"
    assert activity["count"] == 2
    assert [item["event"] for item in activity["items"]] == [
        "preview_queued",
        "action_executed",
    ]
    assert activity["items"][-1]["action"]["action"] == "move"
    assert activity["items"][-1]["ok"] is True
    assert activity["items"][-1]["proof"]["execution_proof"]["proof_id"] == (
        result["execution_proof"]["proof_id"]
    )

    replay = client.get("/api/computer/activity/replay-case").json()
    assert replay["schema"] == "octopus.computer_activity_replay_case.v1"
    assert replay["case_id"].startswith("computer-activity:")
    assert len(replay["fingerprint"]) == 16
    assert replay["replay_ready"] is True
    assert replay["last_activity"]["event"] == "action_executed"
    assert replay["last_activity"]["proof"]["execution_proof"]["schema"] == (
        "octopus.computer_execution_proof.v1"
    )


def test_computer_activity_replay_case_can_queue_operator_review(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("OCTOPUS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(
        computer_skills,
        "_mouse_move",
        lambda **kwargs: {"moved": True, **kwargs},
    )
    client = TestClient(_app())

    preview = client.post(
        "/api/computer/actions/preview",
        json={
            "action": "move",
            "x": 10,
            "y": 20,
            "lease_owner_id": "project-a",
            "lease_owner_label": "Project A",
        },
    ).json()
    client.post(
        "/api/computer/actions/execute",
        json={"token": preview["token"], "lease_owner_id": "project-a"},
    )
    response = client.post(
        "/api/computer/activity/replay-case/queue",
        json={"reason": "operator wants to inspect desktop replay"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["schema"] == "octopus.computer_activity_replay_case_queue.v1"
    assert body["queue"]["created"] == 1
    item = body["queue"]["items"][0]
    assert item["target_bucket"] == "browser_desktop_replay"
    assert "review_queue" in item["tags"]
    assert item["metadata"]["schema"] == "octopus.computer_activity_replay_case.v1"
    assert item["metadata"]["case_id"].startswith("computer-activity:")
    assert len(item["metadata"]["fingerprint"]) == 16
    assert item["metadata"]["last_activity"]["event"] == "action_executed"

    summary = ReviewQueue(tmp_path / "data" / "review_queue.json").summary()
    assert summary["pending_count"] == 1


def test_failed_uia_replay_assertion_enters_operator_review_queue(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("OCTOPUS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(
        computer_skills,
        "_mouse_move",
        lambda **kwargs: {"moved": True, **kwargs},
    )
    client = TestClient(_app())

    preview = client.post(
        "/api/computer/actions/preview",
        json={
            "action": "move",
            "x": 10,
            "y": 20,
            "replay_assertion": {
                "schema": "octopus.computer_uia_replay_assertion.v1",
                "ok": False,
                "reason": "target coordinate drifted outside matched control",
                "matched_control": {
                    "name": "Router Button",
                    "automation_id": "routerButton",
                },
            },
        },
    ).json()
    result = client.post(
        "/api/computer/actions/execute",
        json={"token": preview["token"]},
    ).json()

    assert result["ok"] is True
    assert result["replay_assertion_queue"]["created"] == 1
    item = result["replay_assertion_queue"]["items"][0]
    assert item["candidate_kind"] == "computer_uia_replay_assertion"
    assert item["priority"] == "P0"
    assert item["target_bucket"] == "browser_desktop_replay"
    assert item["metadata"]["replay_assertion"]["ok"] is False
    assert item["metadata"]["trace_id"] == result["action"]["replay_assertion"]["trace_id"]
    assert item["metadata"]["source_trace"]["schema"] == (
        "octopus.computer_uia_grounding_trace.v1"
    )
    assert item["metadata"]["matched_control"]["automation_id"] == "routerButton"

    summary = ReviewQueue(tmp_path / "data" / "review_queue.json").summary()
    assert summary["pending_count"] == 1
    assert summary["by_target_bucket"]["browser_desktop_replay"] == 1


def test_computer_activity_replay_identity_ignores_volatile_fields():
    first = computer_activity_replay_identity(
        pending_count=0,
        items=[
            {
                "id": "one",
                "event": "action_executed",
                "ok": True,
                "token": "token-a",
                "created_at": 10,
                "action": {"action": "move", "x": 10, "y": 20},
            }
        ],
    )
    second = computer_activity_replay_identity(
        pending_count=0,
        items=[
            {
                "id": "two",
                "event": "action_executed",
                "ok": True,
                "token": "token-b",
                "created_at": 999,
                "action": {"action": "move", "x": 10, "y": 20},
            }
        ],
    )

    assert first == second


def test_execute_rejection_points_to_replay_evidence():
    client = TestClient(_app())

    response = client.post(
        "/api/computer/actions/execute",
        json={"token": "missing-token"},
    )

    assert response.status_code == 404
    detail = response.json()["detail"]
    assert detail["diagnostic"]["schema"] == "octopus.computer_automation_diagnostic.v1"
    assert detail["diagnostic"]["code"] == "preview_token_missing"
    assert detail["diagnostic"]["recommended_action"] == "create_new_preview"
    assert detail["recommended_actions"] == ["create_new_preview"]
    evidence = detail["replay_evidence"]
    assert evidence["schema"] == "octopus.computer_replay_evidence_hint.v1"
    assert evidence["case_id"].startswith("computer-activity:")
    assert len(evidence["fingerprint"]) == 16
    assert evidence["replay_ready"] is True
    assert evidence["replay_case_url"] == "/api/computer/activity/replay-case"
    assert evidence["queue_url"] == "/api/computer/activity/replay-case/queue"


def test_execute_failure_points_to_replay_evidence(monkeypatch):
    monkeypatch.setattr(
        computer_skills,
        "_mouse_move",
        lambda **kwargs: {"error": "display unavailable", **kwargs},
    )
    client = TestClient(_app())

    preview = client.post(
        "/api/computer/actions/preview",
        json={"action": "move", "x": 10, "y": 20},
    ).json()
    response = client.post(
        "/api/computer/actions/execute",
        json={"token": preview["token"]},
    ).json()

    assert response["ok"] is False
    assert response["diagnostic"]["code"] == "action_execution_failed"
    assert response["diagnostic"]["metadata"]["error_category"] == "display_unavailable"
    assert response["recommended_actions"] == ["check_display_or_permissions"]
    evidence = response["replay_evidence"]
    assert evidence["case_id"].startswith("computer-activity:")
    assert evidence["replay_ready"] is True


def test_execute_rejects_when_another_project_holds_lease(monkeypatch):
    monkeypatch.setattr(
        computer_skills,
        "_mouse_move",
        lambda **kwargs: {"moved": True, **kwargs},
    )
    client = TestClient(_app())

    first = client.post(
        "/api/computer/actions/preview",
        json={
            "action": "move",
            "x": 10,
            "y": 20,
            "lease_owner_id": "project-a",
            "lease_owner_label": "Project A",
        },
    ).json()
    client.post(
        "/api/computer/actions/execute",
        json={"token": first["token"], "lease_owner_id": "project-a"},
    )

    second = client.post(
        "/api/computer/actions/preview",
        json={
            "action": "move",
            "x": 30,
            "y": 40,
            "lease_owner_id": "project-b",
            "lease_owner_label": "Project B",
        },
    ).json()
    blocked = client.post(
        "/api/computer/actions/execute",
        json={"token": second["token"], "lease_owner_id": "project-b"},
    )

    assert blocked.status_code == 409
    detail = blocked.json()["detail"]
    assert detail["lease"]["owner_id"] == "project-a"
    assert detail["diagnostic"]["code"] == "lease_conflict"
    assert detail["diagnostic"]["metadata"]["requested_owner_id"] == "project-b"
    assert detail["diagnostic"]["metadata"]["current_owner_id"] == "project-a"
    assert detail["recommended_actions"] == ["wait_or_release_lease"]


def test_execute_rejects_preview_owner_mismatch_with_recovery_hint(monkeypatch):
    monkeypatch.setattr(
        computer_skills,
        "_mouse_move",
        lambda **kwargs: {"moved": True, **kwargs},
    )
    client = TestClient(_app())

    preview = client.post(
        "/api/computer/actions/preview",
        json={
            "action": "move",
            "x": 10,
            "y": 20,
            "lease_owner_id": "project-a",
        },
    ).json()
    blocked = client.post(
        "/api/computer/actions/execute",
        json={"token": preview["token"], "lease_owner_id": "project-b"},
    )

    assert blocked.status_code == 409
    detail = blocked.json()["detail"]
    assert detail["diagnostic"]["code"] == "preview_owner_mismatch"
    assert detail["diagnostic"]["metadata"]["preview_owner_id"] == "project-a"
    assert detail["diagnostic"]["metadata"]["requested_owner_id"] == "project-b"
    assert detail["recommended_actions"] == ["create_new_preview"]


def test_release_lease_allows_next_project_to_execute(monkeypatch):
    monkeypatch.setattr(
        computer_skills,
        "_mouse_move",
        lambda **kwargs: {"moved": True, **kwargs},
    )
    client = TestClient(_app())

    first = client.post(
        "/api/computer/actions/preview",
        json={
            "action": "move",
            "x": 10,
            "y": 20,
            "lease_owner_id": "project-a",
        },
    ).json()
    client.post(
        "/api/computer/actions/execute",
        json={"token": first["token"], "lease_owner_id": "project-a"},
    )
    released = client.post(
        "/api/computer/lease/release",
        json={"lease_owner_id": "project-a"},
    ).json()
    assert released["lease"]["held"] is False

    second = client.post(
        "/api/computer/actions/preview",
        json={
            "action": "move",
            "x": 30,
            "y": 40,
            "lease_owner_id": "project-b",
        },
    ).json()
    result = client.post(
        "/api/computer/actions/execute",
        json={"token": second["token"], "lease_owner_id": "project-b"},
    ).json()
    assert result["ok"] is True
    assert result["lease"]["owner_id"] == "project-b"

    activity = client.get("/api/computer/activity").json()
    assert activity["items"][-3]["event"] == "lease_released"
    assert activity["items"][-1]["lease"]["owner_id"] == "project-b"


def test_release_lease_conflict_includes_recovery_hint(monkeypatch):
    monkeypatch.setattr(
        computer_skills,
        "_mouse_move",
        lambda **kwargs: {"moved": True, **kwargs},
    )
    client = TestClient(_app())

    first = client.post(
        "/api/computer/actions/preview",
        json={
            "action": "move",
            "x": 10,
            "y": 20,
            "lease_owner_id": "project-a",
        },
    ).json()
    client.post(
        "/api/computer/actions/execute",
        json={"token": first["token"], "lease_owner_id": "project-a"},
    )

    blocked = client.post(
        "/api/computer/lease/release",
        json={"lease_owner_id": "project-b"},
    )

    assert blocked.status_code == 409
    detail = blocked.json()["detail"]
    assert detail["diagnostic"]["code"] == "lease_release_conflict"
    assert detail["diagnostic"]["metadata"]["requested_owner_id"] == "project-b"
    assert detail["diagnostic"]["metadata"]["current_owner_id"] == "project-a"
    assert detail["recommended_actions"] == ["release_with_owner_or_force"]
