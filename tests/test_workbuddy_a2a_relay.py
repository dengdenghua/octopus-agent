from __future__ import annotations

from a2a.types import (
    Artifact,
    Message,
    Part,
    Role,
    StreamResponse,
    Task,
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient

from runtime.sensing.gateway import a2a_router


def test_proto_status_is_not_mistaken_for_empty_task():
    event = StreamResponse(
        status_update=TaskStatusUpdateEvent(
            task_id="t1",
            context_id="ctx",
            status=TaskStatus(state=TaskState.TASK_STATE_COMPLETED),
        )
    )
    result, state, kind = a2a_router._stream_snapshot(event)
    assert kind == "remote_status"
    assert state == "completed"
    assert result["id"] == "t1"


def test_relay_fetches_final_snapshot_and_preserves_file(tmp_path, monkeypatch):
    task = Task(id="t1", context_id="ctx")
    task.status.state = TaskState.TASK_STATE_COMPLETED
    task.history.append(Message(role=Role.ROLE_AGENT, parts=[Part(text="file ready")]))
    task.artifacts.append(
        Artifact(
            artifact_id="report",
            name="report.txt",
            parts=[Part(raw=b"proof", filename="report.txt", media_type="text/plain")],
        )
    )

    class Client:
        async def send_message(self, request):
            initial = Task(id="t1", context_id="ctx")
            initial.status.state = TaskState.TASK_STATE_SUBMITTED
            yield StreamResponse(task=initial)
            yield StreamResponse(
                artifact_update=TaskArtifactUpdateEvent(
                    task_id="t1", context_id="ctx", artifact=task.artifacts[0]
                )
            )
            yield StreamResponse(
                status_update=TaskStatusUpdateEvent(
                    task_id="t1", context_id="ctx", status=task.status
                )
            )

        async def get_task(self, request):
            assert request.id == "t1"
            return task

    async def create(*args, **kwargs):
        return Client()

    monkeypatch.setattr("a2a.client.ClientFactory.create_from_url", create)
    monkeypatch.setattr(a2a_router, "_REGISTRY_DIR", tmp_path)
    monkeypatch.setattr(a2a_router, "_REGISTRY_FILE", tmp_path / "registry.json")
    a2a_router._save_registry([{"agent_id": "workbuddy", "base_url": "http://127.0.0.1:8321"}])
    app = FastAPI()
    app.include_router(a2a_router.create_a2a_router())
    with TestClient(app) as client:
        response = client.post("/api/a2a/agents/workbuddy/send", json={"text": "make report"})
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["lifecycle_status"] == "completed"
        assert result["messages"][-1]["parts"][0]["text"] == "file ready"
        assert result["artifacts"][0]["parts"][0]["raw"] == "cHJvb2Y="
        persisted = client.get(f"/api/a2a/tasks/{result['local_task_id']}").json()
        assert persisted["result"]["artifacts"] == result["artifacts"]
