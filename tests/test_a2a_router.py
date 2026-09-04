"""A2A router coverage — register/list/health/send with mocked SDK."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from runtime.sensing.gateway.a2a_router import create_a2a_router


@pytest.fixture()
def a2a_app(tmp_path, monkeypatch) -> TestClient:
    # Point the registry away from the real ~/.octopus/a2a/registry.json.
    import runtime.sensing.gateway.a2a_router as mod

    monkeypatch.setattr(mod, "_REGISTRY_DIR", tmp_path / "a2a")
    monkeypatch.setattr(mod, "_REGISTRY_FILE", tmp_path / "a2a" / "registry.json")

    app = FastAPI()
    app.include_router(create_a2a_router())
    return TestClient(app)


def _make_card(name: str = "Test Agent", *, version: str = "2.1.0"):
    from a2a.types import AgentCard

    card = AgentCard()
    card.name = name
    card.description = "a test remote agent"
    card.version = version
    skill = card.skills.add()
    skill.id = "skill-1"
    skill.name = "Skill One"
    skill.description = "does things"
    card.capabilities.streaming = True
    card.capabilities.push_notifications = False
    return card


class _FakeTask:
    id = "task-123"
    status = None

    def __init__(self, state=None) -> None:
        from a2a.types import Role, Task, TaskState

        self._t = Task()
        self._t.id = "task-123"
        self._t.status.state = state or TaskState.TASK_STATE_COMPLETED
        # Task 新版用 history(非 messages)承载对话;TaskStatus.message
        # 赋值被 protobuf 拦截(SDK 字段名与 Message 基类冲突),读取走 dict。
        msg = self._t.history.add()
        msg.message_id = "m1"
        msg.role = Role.ROLE_AGENT
        part = msg.parts.add()
        part.text = "the reply"
        art = self._t.artifacts.add()
        art.name = "report"
        ap = art.parts.add()
        ap.text = "artifact text"


class _FakeStreamResponse:
    def __init__(self, task) -> None:
        self.task = task


class _FakeClient:
    def __init__(self, card, *, send_state=None, refresh_state=None) -> None:
        self.agent_card = card
        self.card = card
        self.sent: list = []
        self.send_state = send_state
        self.refresh_state = refresh_state

    async def send_message(self, request):
        self.sent.append(request)
        task = _FakeTask(self.send_state)
        yield _FakeStreamResponse(task._t)

    async def get_task(self, request):
        return _FakeTask(self.refresh_state)._t

    async def cancel_task(self, request):
        from a2a.types import TaskState

        return _FakeTask(TaskState.TASK_STATE_CANCELED)._t

    async def subscribe(self, request):
        from a2a.types import TaskState

        yield _FakeStreamResponse(_FakeTask(TaskState.TASK_STATE_COMPLETED)._t)


def _install_sdk_mock(
    monkeypatch,
    *,
    card=None,
    fail=False,
    send_state=None,
    refresh_state=None,
):
    """Replace a2a.client.ClientFactory with a fake that resolves one card."""

    class FakeFactory:
        def __init__(self):
            pass

        async def create_from_url(self, url):
            if fail:
                raise RuntimeError("boom: card unreachable")
            return _FakeClient(
                card or _make_card(),
                send_state=send_state,
                refresh_state=refresh_state,
            )

    monkeypatch.setattr(
        "a2a.client.ClientFactory",
        FakeFactory,
    )


class TestRegisterAndList:
    def test_register_resolves_card_and_persists(self, a2a_app, monkeypatch):
        _install_sdk_mock(monkeypatch)
        r = a2a_app.post("/api/a2a/agents/register", json={"url": "https://remote.example/agent"})
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["agent_id"].startswith("a2a_")
        assert data["base_url"] == "https://remote.example/agent"
        assert data["name"] == "Test Agent"
        assert data["version"] == "2.1.0"
        assert data["status"] == "active"
        assert data["skills"][0]["name"] == "Skill One"
        assert data["capabilities"]["streaming"] is True
        # multiTurn 已从新版 AgentCard 移除 — 返回 False 是契约默认值。
        assert data["capabilities"]["multiTurn"] is False

    def test_register_rejects_bad_url(self, a2a_app):
        r = a2a_app.post("/api/a2a/agents/register", json={"url": "not-a-url"})
        assert r.status_code == 400
        r = a2a_app.post("/api/a2a/agents/register", json={"url": ""})
        assert r.status_code == 400

    def test_register_failure_surfaces_502(self, a2a_app, monkeypatch):
        _install_sdk_mock(monkeypatch, fail=True)
        r = a2a_app.post("/api/a2a/agents/register", json={"url": "https://dead.example/x"})
        assert r.status_code == 502

    def test_list_agents(self, a2a_app, monkeypatch):
        _install_sdk_mock(monkeypatch)
        a2a_app.post("/api/a2a/agents/register", json={"url": "https://a.example/x"})
        a2a_app.post("/api/a2a/agents/register", json={"url": "https://b.example/x"})
        r = a2a_app.get("/api/a2a/agents")
        assert r.status_code == 200
        data = r.json()
        assert data["count"] == 2
        assert {a["base_url"] for a in data["agents"]} == {
            "https://a.example/x",
            "https://b.example/x",
        }

    def test_unregister_removes_agent(self, a2a_app, monkeypatch):
        _install_sdk_mock(monkeypatch)
        reg = a2a_app.post("/api/a2a/agents/register", json={"url": "https://a.example/x"}).json()
        r = a2a_app.delete(f"/api/a2a/agents/{reg['agent_id']}")
        assert r.status_code == 200
        r = a2a_app.delete(f"/api/a2a/agents/{reg['agent_id']}")
        assert r.status_code == 404


class TestHealthAndSend:
    def test_health_check_marks_active(self, a2a_app, monkeypatch):
        _install_sdk_mock(monkeypatch)
        reg = a2a_app.post("/api/a2a/agents/register", json={"url": "https://a.example/x"}).json()
        r = a2a_app.post(f"/api/a2a/agents/{reg['agent_id']}/health")
        assert r.status_code == 200
        assert r.json()["healthy"] is True
        assert r.json()["status"] == "active"

    def test_health_check_marks_unreachable(self, a2a_app, monkeypatch):
        _install_sdk_mock(monkeypatch, fail=True)
        # Register with a working card, then break the SDK to simulate outage.
        _install_sdk_mock(monkeypatch)
        reg = a2a_app.post("/api/a2a/agents/register", json={"url": "https://a.example/x"}).json()
        _install_sdk_mock(monkeypatch, fail=True)
        r = a2a_app.post(f"/api/a2a/agents/{reg['agent_id']}/health")
        assert r.status_code == 200
        assert r.json()["healthy"] is False
        assert r.json()["status"] == "unreachable"

    def test_send_task_returns_flattened_result(self, a2a_app, monkeypatch):
        _install_sdk_mock(monkeypatch)
        reg = a2a_app.post("/api/a2a/agents/register", json={"url": "https://a.example/x"}).json()
        r = a2a_app.post(
            f"/api/a2a/agents/{reg['agent_id']}/send",
            json={"text": "hello remote agent", "stream": False},
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["id"] == "task-123"
        # protobuf 枚举经 MessageToDict 序列化为数字(3 = TASK_STATE_COMPLETED)。
        assert str(data["status"]["state"]) == "3"
        assert data["messages"][0]["parts"][0]["text"] == "the reply"
        assert data["artifacts"][0]["name"] == "report"

    def test_send_task_missing_text(self, a2a_app, monkeypatch):
        _install_sdk_mock(monkeypatch)
        reg = a2a_app.post("/api/a2a/agents/register", json={"url": "https://a.example/x"}).json()
        r = a2a_app.post(f"/api/a2a/agents/{reg['agent_id']}/send", json={"text": ""})
        assert r.status_code == 400

    def test_send_task_unknown_agent(self, a2a_app):
        r = a2a_app.post("/api/a2a/agents/nope/send", json={"text": "hi"})
        assert r.status_code == 404


class TestTaskLifecycle:
    def test_send_persists_task_events_and_is_idempotent(self, a2a_app, monkeypatch):
        _install_sdk_mock(monkeypatch)
        reg = a2a_app.post("/api/a2a/agents/register", json={"url": "https://a.example/x"}).json()
        payload = {"text": "durable work", "local_task_id": "request-42"}

        first = a2a_app.post(f"/api/a2a/agents/{reg['agent_id']}/send", json=payload)
        assert first.status_code == 200, first.text
        assert first.json()["local_task_id"] == "request-42"
        assert first.json()["lifecycle_status"] == "completed"

        detail = a2a_app.get("/api/a2a/tasks/request-42")
        assert detail.status_code == 200
        assert detail.json()["remote_task_id"] == "task-123"
        listed = a2a_app.get("/api/a2a/tasks", params={"status": "completed"}).json()
        assert listed["count"] == 1
        events = a2a_app.get("/api/a2a/tasks/request-42/events").json()["events"]
        assert [event["event_type"] for event in events] == ["submitted", "remote_task"]

        replay = a2a_app.post(f"/api/a2a/agents/{reg['agent_id']}/send", json=payload)
        assert replay.status_code == 200
        assert replay.json()["replayed"] is True
        assert a2a_app.get("/api/a2a/tasks/request-42/events").json()["count"] == 2

    def test_refresh_advances_remote_task(self, a2a_app, monkeypatch):
        from a2a.types import TaskState

        _install_sdk_mock(
            monkeypatch,
            send_state=TaskState.TASK_STATE_WORKING,
            refresh_state=TaskState.TASK_STATE_COMPLETED,
        )
        reg = a2a_app.post("/api/a2a/agents/register", json={"url": "https://a.example/x"}).json()
        sent = a2a_app.post(
            f"/api/a2a/agents/{reg['agent_id']}/send",
            json={"text": "long work", "local_task_id": "refresh-me"},
        )
        assert sent.json()["lifecycle_status"] == "working"

        refreshed = a2a_app.post("/api/a2a/tasks/refresh-me/refresh")
        assert refreshed.status_code == 200, refreshed.text
        assert refreshed.json()["status"] == "completed"
        assert refreshed.json()["result"]["status"]["state"] == "3"

    def test_cancel_running_remote_task(self, a2a_app, monkeypatch):
        from a2a.types import TaskState

        _install_sdk_mock(monkeypatch, send_state=TaskState.TASK_STATE_WORKING)
        reg = a2a_app.post("/api/a2a/agents/register", json={"url": "https://a.example/x"}).json()
        a2a_app.post(
            f"/api/a2a/agents/{reg['agent_id']}/send",
            json={"text": "cancel work", "local_task_id": "cancel-me"},
        )

        canceled = a2a_app.post("/api/a2a/tasks/cancel-me/cancel")
        assert canceled.status_code == 200, canceled.text
        assert canceled.json()["status"] == "canceled"
        assert canceled.json()["result"]["status"]["state"] == "5"

    def test_subscribe_streams_snapshot_and_persists_updates(self, a2a_app, monkeypatch):
        from a2a.types import TaskState

        _install_sdk_mock(monkeypatch, send_state=TaskState.TASK_STATE_WORKING)
        reg = a2a_app.post("/api/a2a/agents/register", json={"url": "https://a.example/x"}).json()
        a2a_app.post(
            f"/api/a2a/agents/{reg['agent_id']}/send",
            json={"text": "watch work", "local_task_id": "watch-me"},
        )

        with a2a_app.stream("GET", "/api/a2a/tasks/watch-me/subscribe") as response:
            assert response.status_code == 200
            stream = "".join(response.iter_text())
        assert "event: snapshot" in stream
        assert "event: update" in stream
        assert a2a_app.get("/api/a2a/tasks/watch-me").json()["status"] == "completed"
