"""Project OS API: plan / tick / run / report over HTTP (stub hooks, no LLM)."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from runtime.projectos.store import ProjectStore
from runtime.sensing.gateway.projects_router import create_projects_router


def _client(tmp_path) -> TestClient:
    app = FastAPI()
    app.include_router(create_projects_router(store=ProjectStore(base_dir=tmp_path)))
    return TestClient(app)


def test_plan_run_report_flow(tmp_path) -> None:
    c = _client(tmp_path)

    planned = c.post("/api/projects", json={"name": "sleep", "goal": "smart sleep system"})
    assert planned.status_code == 200
    pid = planned.json()["project"]["id"]
    assert planned.json()["milestones"]  # at least one milestone generated (stub: 1)

    run = c.post(f"/api/projects/{pid}/run", json={"max_ticks": 20})
    assert run.status_code == 200
    assert run.json()["final_status"] == "done"

    report = c.get(f"/api/projects/{pid}/report").json()
    assert report["status"] == "done"
    assert report["milestones"][0]["tasks"][0]["status"] == "done"

    # appears in the list
    assert pid in [p["id"] for p in c.get("/api/projects").json()["projects"]]


def test_tick_advances_incrementally(tmp_path) -> None:
    c = _client(tmp_path)
    pid = c.post("/api/projects", json={"name": "x", "goal": "g"}).json()["project"]["id"]
    r = c.post(f"/api/projects/{pid}/tick").json()
    assert "events" in r and r["project_status"] in ("running", "done")


def test_404s(tmp_path) -> None:
    c = _client(tmp_path)
    assert c.get("/api/projects/nope").status_code == 404
    assert c.post("/api/projects/nope/tick").status_code == 404
    assert c.get("/api/projects/nope/report").status_code == 404
