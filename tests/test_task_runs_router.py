from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from runtime.platform.process.task_supervisor import TaskRunStatus, TaskSupervisor
from runtime.sensing.gateway.task_runs_router import create_task_runs_router


def test_task_runs_router_lists_and_reads_supervisor_records(tmp_path):
    supervisor = TaskSupervisor.from_path(tmp_path / "task_runs.json", holder_id="worker-a")
    supervisor.start_task(
        task_id="task-1",
        kind="loop",
        owner_id="alice",
        thread_id="thread-1",
        title="Fix tests",
        goal="Fix tests",
        mode="code",
    )
    supervisor.transition("task-1", TaskRunStatus.COMPLETED, checkpoint_id=7)
    supervisor.start_task(
        task_id="task-2",
        kind="background",
        owner_id="bob",
        thread_id="thread-2",
        title="Sync",
        goal="Sync",
    )

    app = FastAPI()
    app.include_router(create_task_runs_router(supervisor=supervisor))
    client = TestClient(app)

    listed = client.get("/api/task-runs", params={"kind": "loop"})
    detail = client.get("/api/task-runs/task-1")
    missing = client.get("/api/task-runs/missing")

    assert listed.status_code == 200
    body = listed.json()
    assert body["schema"] == "octopus.task_runs.v1"
    assert body["total"] == 1
    assert body["tasks"][0]["task_id"] == "task-1"
    assert body["tasks"][0]["status"] == "completed"

    assert detail.status_code == 200
    assert detail.json()["task_run"]["latest_checkpoint_id"] == 7

    assert missing.status_code == 404
