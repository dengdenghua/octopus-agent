from __future__ import annotations

import json
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from runtime.company.api import create_company_router  # noqa: E402
from runtime.company.core import project_task_to_team_task_payload  # noqa: E402
from runtime.company.core.models import ProjectTask, TaskAssignee  # noqa: E402
from runtime.platform.process.utils import parse_jsonc  # noqa: E402


def _client(tmp_path: Path) -> TestClient:
    app = FastAPI()
    app.include_router(
        create_company_router(state_path=tmp_path / "company_projects.json"),
    )
    return TestClient(app)


def _client_with_router(tmp_path: Path) -> tuple[TestClient, object]:
    app = FastAPI()
    router = create_company_router(state_path=tmp_path / "company_projects.json")
    app.include_router(router)
    return TestClient(app), router


def _client_with_dispatcher(
    tmp_path: Path,
    calls: list[dict[str, object]],
) -> TestClient:
    app = FastAPI()

    async def _dispatch_team_task(
        _request: object,
        payload: dict[str, object],
        run: bool,
    ) -> dict[str, object]:
        calls.append({"payload": payload, "run": run})
        return {
            "id": "team-task-linked",
            "room_id": payload["room_id"],
            "title": payload["title"],
            "description": payload.get("description", ""),
            "status": "running" if run else "pending",
            "metadata": payload.get("metadata", {}),
        }

    app.include_router(
        create_company_router(
            state_path=tmp_path / "company_projects.json",
            team_task_dispatcher=_dispatch_team_task,
        ),
    )
    return TestClient(app)


def _client_with_team_room_binding(
    tmp_path: Path,
    calls: list[dict[str, object]],
    room_updates: list[dict[str, object]] | None = None,
) -> TestClient:
    app = FastAPI()

    async def _create_team_room(
        _request: object,
        payload: dict[str, object],
    ) -> dict[str, object]:
        return {
            "id": str(payload["id"]),
            "name": payload["name"],
            "members": payload["members"],
            "leaderId": payload["leaderId"],
        }

    async def _dispatch_team_task(
        _request: object,
        payload: dict[str, object],
        run: bool,
    ) -> dict[str, object]:
        calls.append({"payload": payload, "run": run})
        return {
            "id": "team-task-bound",
            "room_id": payload["room_id"],
            "title": payload["title"],
            "status": "pending",
        }

    async def _update_team_room(
        _request: object,
        team_id: str,
        payload: dict[str, object],
    ) -> dict[str, object]:
        if room_updates is not None:
            room_updates.append({"team_id": team_id, "payload": payload})
        return {
            "id": team_id,
            "name": payload["name"],
            "members": payload["members"],
            "leaderId": payload["leaderId"],
        }

    app.include_router(
        create_company_router(
            state_path=tmp_path / "company_projects.json",
            team_room_creator=_create_team_room,
            team_room_updater=_update_team_room,
            team_task_dispatcher=_dispatch_team_task,
        ),
    )
    return TestClient(app)


def test_company_router_creates_project_timeline_and_gantt(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)

    project = client.post(
        "/api/company/projects",
        json={
            "name": "Pilot Project",
            "industry": "hardware",
            "stage": "prototype",
            "start_date": "2026-06-01",
            "target_end_date": "2027-06-01",
        },
    )
    assert project.status_code == 200
    project_body = project.json()
    project_id = project_body["id"]

    milestone = client.post(
        f"/api/company/projects/{project_id}/milestones",
        json={
            "title": "Hardware MVP",
            "planned_start_at": "2026-06-01",
            "planned_end_at": "2026-08-31",
            "sort_order": 1,
        },
    )
    assert milestone.status_code == 200
    milestone_id = milestone.json()["id"]

    sensor_task = client.post(
        f"/api/company/projects/{project_id}/tasks",
        json={
            "milestone_id": milestone_id,
            "title": "Sensor selection",
            "planned_start_at": "2026-06-01",
            "planned_end_at": "2026-06-15",
            "owner_name": "hardware",
        },
    )
    assert sensor_task.status_code == 200
    sensor_id = sensor_task.json()["id"]

    pcb_task = client.post(
        f"/api/company/projects/{project_id}/tasks",
        json={
            "milestone_id": milestone_id,
            "title": "PCB design",
            "planned_start_at": "2026-06-16",
            "planned_end_at": "2026-07-05",
            "owner_name": "ee",
        },
    )
    assert pcb_task.status_code == 200
    pcb_id = pcb_task.json()["id"]

    dependency = client.post(
        f"/api/company/projects/{project_id}/dependencies",
        json={
            "from_task_id": sensor_id,
            "to_task_id": pcb_id,
            "type": "finish_to_start",
        },
    )
    assert dependency.status_code == 200

    updated = client.patch(
        f"/api/company/tasks/{pcb_id}",
        json={"status": "doing", "progress": 25},
    )
    assert updated.status_code == 200
    assert updated.json()["progress"] == 25

    gantt = client.get(f"/api/company/projects/{project_id}/gantt")
    assert gantt.status_code == 200
    items = gantt.json()["items"]
    assert [item["name"] for item in items] == [
        "Hardware MVP",
        "Sensor selection",
        "PCB design",
    ]
    pcb_row = next(item for item in items if item["id"] == pcb_id)
    assert pcb_row["dependencies"] == [sensor_id]
    assert pcb_row["progress"] == 25


def test_company_router_persists_json_state(tmp_path: Path) -> None:
    first = _client(tmp_path)
    project = first.post(
        "/api/company/projects",
        json={"name": "Persistent Project"},
    ).json()

    second = _client(tmp_path)
    listed = second.get("/api/company/projects")

    assert listed.status_code == 200
    assert listed.json()["projects"][0]["id"] == project["id"]


def test_company_blueprint_creates_project_timeline_and_dependencies(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)

    response = client.post(
        "/api/company/projects/blueprint",
        json={
            "prompt": "Build a human-agent company for a new product line",
            "budget_tier": "lean",
            "horizon_days": 90,
            "start_date": "2026-06-01",
        },
    )

    assert response.status_code == 200
    body = response.json()
    project = body["project"]
    assert project["name"].startswith("Build a human-agent")
    assert project["metadata"]["blueprint"]["budget_tier"] == "lean"
    assert project["metadata"]["blueprint"]["budget_profile"]["team_size"] == "1-3"
    assert (
        project["metadata"]["blueprint"]["capability_model"][
            "recommended_parallel_agents"
        ]
        == 1
    )
    assert len(project["metadata"]["blueprint"]["team_roles"]) == 3
    assert (
        project["metadata"]["blueprint"]["team_roles"][0]["metadata"]["pricing"][
            "monthly_low"
        ]
        == 6000
    )
    assert (
        project["metadata"]["blueprint"]["team_roles"][0]["metadata"]["skill_pack"][
            "level"
        ]
        == "mid"
    )
    assert (
        project["metadata"]["blueprint"]["team_roles"][0]["display_name"]
        == "项目规划 Agent"
    )
    assert (
        project["metadata"]["blueprint"]["team_roles"][0]["skills"][0]
        == "goal_breakdown"
    )
    assert len(body["milestones"]) == 4
    assert len(body["tasks"]) == 4
    assert len(body["dependencies"]) == 3
    assert body["tasks"][0]["milestone_id"] == body["milestones"][0]["id"]
    assert body["dependencies"][0]["from_task_id"] == body["tasks"][0]["id"]
    assert body["dependencies"][0]["to_task_id"] == body["tasks"][1]["id"]

    gantt = client.get(f"/api/company/projects/{project['id']}/gantt")
    assert gantt.status_code == 200
    assert gantt.json()["count"] == 8


def test_company_blueprint_budget_tier_changes_team_shape(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)

    lean = client.post(
        "/api/company/projects/blueprint",
        json={
            "prompt": "Plan a lean company project",
            "budget_tier": "lean",
            "horizon_days": 90,
        },
    ).json()["blueprint"]
    premium = client.post(
        "/api/company/projects/blueprint",
        json={
            "prompt": "Plan a premium company project",
            "budget_tier": "premium",
            "horizon_days": 90,
        },
    ).json()["blueprint"]
    enterprise = client.post(
        "/api/company/projects/blueprint",
        json={
            "prompt": "Plan an enterprise company project",
            "budget_tier": "enterprise",
            "horizon_days": 90,
        },
    ).json()["blueprint"]

    assert len(lean["team_roles"]) == 3
    assert len(premium["team_roles"]) == 6
    assert len(enterprise["team_roles"]) == 8
    assert premium["capability_model"]["recommended_parallel_agents"] == 4
    assert enterprise["budget_profile"]["monthly_budget_max"] is None
    assert any(
        role["role"] == "governance_controller"
        for role in enterprise["team_roles"]
    )


def test_company_team_assembly_matches_blueprint_roles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agents_root = tmp_path / "agents"
    general_dir = agents_root / "general"
    researcher_dir = agents_root / "market_researcher"
    (general_dir / "agent-core").mkdir(parents=True)
    (researcher_dir / "agent-core").mkdir(parents=True)
    (general_dir / "profile.jsonc").write_text(
        """
        {
          "id": "general",
          "name": "General Planner",
          "category": "assistant",
          "tags": ["planning", "synthesis"]
        }
        """,
        encoding="utf-8",
    )
    (general_dir / "agent-core" / "tool-registry.jsonc").write_text(
        """
        {
          "arms": ["file_read", "file_write"],
          "extra_affinity": ["goal_breakdown", "gantt_planning"],
          "private_skills": ["goal_breakdown", "project_planning"]
        }
        """,
        encoding="utf-8",
    )
    (researcher_dir / "profile.jsonc").write_text(
        """
        {
          "id": "market_researcher",
          "name": "Market Researcher",
          "category": "researcher",
          "tags": ["market", "research"]
        }
        """,
        encoding="utf-8",
    )
    (researcher_dir / "agent-core" / "tool-registry.jsonc").write_text(
        """
        {
          "arms": ["web_read", "web_search"],
          "extra_affinity": ["market_research", "evidence_digest"],
          "private_skills": ["market_research", "competitive_scan"]
        }
        """,
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "runtime.company.core.store.default_agents_root",
        lambda: agents_root,
    )
    client = _client(tmp_path)
    project = client.post(
        "/api/company/projects/blueprint",
        json={
            "prompt": "Launch a project with a team assembly",
            "budget_tier": "standard",
            "horizon_days": 90,
        },
    ).json()["project"]

    response = client.post(
        f"/api/company/projects/{project['id']}/team-assembly",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["available_agents_count"] == 2
    assert body["summary"]["total_slots"] == 4
    assert body["summary"]["matched_agents"] >= 2
    assert body["summary"]["estimated_monthly_low"] == 26000
    assert body["summary"]["estimated_monthly_high"] == 63000
    assert body["summary"]["estimated_monthly_label"] == "CNY 26,000-63,000 / month"
    assert body["summary"]["budget_fit"] == "within_budget"
    assert body["summary"]["human_cost_excluded"] is True
    assert body["summary"]["level_counts"]["owner"] == 1
    members = body["members"]
    planner = next(member for member in members if member["role"] == "planner")
    researcher = next(
        member for member in members if member["role"] == "researcher"
    )
    owner = next(member for member in members if member["kind"] == "human")
    assert planner["source_agent_id"] == "general"
    assert planner["metadata"]["pricing"]["monthly_low"] == 8000
    assert planner["metadata"]["skill_pack"]["level"] == "senior"
    assert researcher["source_agent_id"] == "market_researcher"
    assert "market_research" in researcher["installed_skills"]
    assert owner["status"] == "requires_human"

    persisted = client.get(f"/api/company/projects/{project['id']}").json()
    assembly = persisted["metadata"]["team_assembly"]
    assert assembly["summary"]["total_slots"] == 4
    assert assembly["members"][0]["project_id"] == project["id"]


def test_company_materializes_team_assembly_member_as_agent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agents_root = tmp_path / "agents"
    agents_root.mkdir()
    monkeypatch.setattr(
        "runtime.company.core.store.default_agents_root",
        lambda: agents_root,
    )
    monkeypatch.setattr(
        "runtime.execution.agents.scaffold.default_agents_root",
        lambda: agents_root,
    )
    client = _client(tmp_path)
    project = client.post(
        "/api/company/projects/blueprint",
        json={
            "prompt": "Launch a company project with a missing agent slot",
            "budget_tier": "standard",
            "horizon_days": 90,
        },
    ).json()["project"]
    assembly = client.post(
        f"/api/company/projects/{project['id']}/team-assembly",
    ).json()
    member = next(
        item
        for item in assembly["members"]
        if item["status"] in {"needs_agent", "needs_digital_twin"}
    )

    response = client.post(
        f"/api/company/projects/{project['id']}/team-assembly/{member['id']}/materialize",
        json={"agent_id": "company_test_planner", "display_name": "Company Test Planner"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["created"] is True
    assert body["hot_loaded"] is False
    assert body["requires_reload"] is True
    assert body["agent"]["id"] == "company_test_planner"
    assert body["agent"]["identity_card"]["agent_id"] == "company_test_planner"
    assert body["agent"]["identity_card"]["identity_number"].startswith("HA-")
    profile_path = agents_root / "company_test_planner" / "profile.jsonc"
    assert profile_path.is_file()
    profile = parse_jsonc(profile_path.read_text(encoding="utf-8"))
    assert profile["creator"] == "company_workbench"
    assert profile["metadata"]["project_id"] == project["id"]
    assert (
        profile["metadata"]["identity_card"]["identity_number"]
        == body["agent"]["identity_card"]["identity_number"]
    )
    assert (agents_root / "company_test_planner" / "agent-core" / "SOUL.md").is_file()
    role_contract = (
        agents_root / "company_test_planner" / "agent-core" / "COMPANY_ROLE.md"
    )
    assert role_contract.is_file()
    assert body["agent"]["identity_card"]["identity_number"] in role_contract.read_text(
        encoding="utf-8",
    )
    identity_memory = json.loads(
        (
            agents_root / "company_test_planner" / "memory" / "company_identity.json"
        ).read_text(encoding="utf-8"),
    )
    assert identity_memory["agent_id"] == "company_test_planner"

    persisted = client.get(f"/api/company/projects/{project['id']}").json()
    updated_member = next(
        item
        for item in persisted["metadata"]["team_assembly"]["members"]
        if item["id"] == member["id"]
    )
    assert updated_member["status"] == "matched"
    assert updated_member["source_agent_id"] == "company_test_planner"
    assert updated_member["metadata"]["materialized"]["agent_id"] == "company_test_planner"
    assert (
        updated_member["metadata"]["identity_card"]["identity_number"]
        == body["agent"]["identity_card"]["identity_number"]
    )


def test_company_materialize_rejects_human_roles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agents_root = tmp_path / "agents"
    agents_root.mkdir()
    monkeypatch.setattr(
        "runtime.company.core.store.default_agents_root",
        lambda: agents_root,
    )
    monkeypatch.setattr(
        "runtime.execution.agents.scaffold.default_agents_root",
        lambda: agents_root,
    )
    client = _client(tmp_path)
    project = client.post(
        "/api/company/projects/blueprint",
        json={
            "prompt": "Launch a company project with a human owner",
            "budget_tier": "standard",
            "horizon_days": 90,
        },
    ).json()["project"]
    assembly = client.post(
        f"/api/company/projects/{project['id']}/team-assembly",
    ).json()
    human = next(item for item in assembly["members"] if item["kind"] == "human")

    response = client.post(
        f"/api/company/projects/{project['id']}/team-assembly/{human['id']}/materialize",
        json={"agent_id": "should_not_exist"},
    )

    assert response.status_code == 409
    assert not (agents_root / "should_not_exist").exists()


def test_company_materialize_syncs_existing_team_room_members(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agents_root = tmp_path / "agents"
    agents_root.mkdir()
    monkeypatch.setattr(
        "runtime.company.core.store.default_agents_root",
        lambda: agents_root,
    )
    monkeypatch.setattr(
        "runtime.execution.agents.scaffold.default_agents_root",
        lambda: agents_root,
    )
    calls: list[dict[str, object]] = []
    room_updates: list[dict[str, object]] = []
    client = _client_with_team_room_binding(tmp_path, calls, room_updates)
    project = client.post(
        "/api/company/projects/blueprint",
        json={
            "prompt": "Launch a project and sync its team room",
            "budget_tier": "standard",
            "horizon_days": 90,
        },
    ).json()["project"]
    assembly = client.post(
        f"/api/company/projects/{project['id']}/team-assembly",
    ).json()
    bound = client.post(f"/api/company/projects/{project['id']}/team-room", json={})
    assert bound.status_code == 200
    member = next(
        item
        for item in assembly["members"]
        if item["status"] in {"needs_agent", "needs_digital_twin"}
    )

    response = client.post(
        f"/api/company/projects/{project['id']}/team-assembly/{member['id']}/materialize",
        json={"agent_id": "company_synced_agent"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["team_room_synced"] is True
    assert body["team_room_id"] == f"company-{project['id']}"
    assert len(room_updates) == 1
    payload = room_updates[0]["payload"]
    assert isinstance(payload, dict)
    names = [item["name"] for item in payload["members"]]
    assert "general" in names
    assert "company_synced_agent" in names


def test_company_project_delete_cascades_planning_state(tmp_path: Path) -> None:
    client = _client(tmp_path)
    project = client.post(
        "/api/company/projects/blueprint",
        json={
            "prompt": "Temporary project",
            "budget_tier": "standard",
            "horizon_days": 90,
        },
    ).json()["project"]

    initial_gantt = client.get(f"/api/company/projects/{project['id']}/gantt")
    assert initial_gantt.json()["count"] == 8

    deleted = client.delete(f"/api/company/projects/{project['id']}")
    assert deleted.status_code == 200
    assert deleted.json() == {"deleted": True, "project_id": project["id"]}

    assert client.get(f"/api/company/projects/{project['id']}").status_code == 404
    assert client.get(f"/api/company/projects/{project['id']}/tasks").status_code == 404
    assert client.get(f"/api/company/projects/{project['id']}/gantt").status_code == 404
    listed = client.get("/api/company/projects").json()
    assert listed["count"] == 0


def test_company_router_rejects_invalid_dependency(tmp_path: Path) -> None:
    client = _client(tmp_path)
    project_id = client.post(
        "/api/company/projects",
        json={"name": "Pilot Project"},
    ).json()["id"]

    response = client.post(
        f"/api/company/projects/{project_id}/dependencies",
        json={
            "from_task_id": "missing-a",
            "to_task_id": "missing-b",
        },
    )

    assert response.status_code == 400


def test_project_task_to_team_task_payload_keeps_execution_boundary() -> None:
    task = ProjectTask(
        project_id="project-1",
        title="Run FTO scan",
        description="Search high-risk patents",
        assignees=[
            TaskAssignee(kind="agent", ref="patent_agent"),
            TaskAssignee(kind="human", ref="ceo"),
        ],
    )

    payload = project_task_to_team_task_payload(
        task,
        room_id="room-1",
        sop_template="patent_fto",
    )

    assert payload == {
        "room_id": "room-1",
        "title": "Run FTO scan",
        "description": "Search high-risk patents",
        "sop_template": "patent_fto",
        "assignees": [{"kind": "agent", "ref": "patent_agent"}],
    }


def test_company_task_dispatch_creates_and_links_team_task(tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []
    client = _client_with_dispatcher(tmp_path, calls)
    project_id = client.post(
        "/api/company/projects",
        json={"name": "Dispatch Project"},
    ).json()["id"]
    task = client.post(
        f"/api/company/projects/{project_id}/tasks",
        json={
            "title": "Assemble launch plan",
            "description": "Break down roles and milestones",
            "assignees": [{"kind": "agent", "ref": "planner"}],
        },
    ).json()

    response = client.post(
        f"/api/company/tasks/{task['id']}/dispatch",
        json={"room_id": "room-42", "sop_template": "launch_plan", "run": True},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["created"] is True
    assert body["run_requested"] is True
    assert body["team_task_id"] == "team-task-linked"
    assert body["project_task"]["team_task_id"] == "team-task-linked"
    assert body["project_task"]["status"] == "doing"
    assert calls == [
        {
            "run": True,
            "payload": {
                "room_id": "room-42",
                "title": "Assemble launch plan",
                "description": "Break down roles and milestones",
                "sop_template": "launch_plan",
                "assignees": [{"kind": "agent", "ref": "planner"}],
                "metadata": {
                    "source": "company_workbench",
                    "company_project_id": project_id,
                    "company_task_id": task["id"],
                    "company_milestone_id": None,
                    "output_contract": {
                        "name": "project_update_v1",
                        "instructions": [
                            "Keep the normal answer concise and useful for the task.",
                            "If you identify project management updates, include one fenced json block.",
                            "Use empty arrays when a category has no concrete update.",
                            "Do not invent risks, actions, or decisions that are not supported by the work.",
                        ],
                        "schema": {
                            "risks": [
                                {
                                    "title": "short risk title",
                                    "description": "why it matters",
                                    "severity": "low | medium | high",
                                    "owner": "optional owner",
                                    "status": "open | watching | mitigated",
                                },
                            ],
                            "next_actions": [
                                {
                                    "title": "concrete next step",
                                    "description": "optional detail",
                                    "owner": "optional owner",
                                    "due_at": "optional ISO date",
                                    "status": "todo | doing | done",
                                },
                            ],
                            "decisions": [
                                {
                                    "title": "decision made or proposed",
                                    "rationale": "why this decision is recommended",
                                    "status": "proposed | accepted | rejected",
                                },
                            ],
                        },
                    },
                },
            },
        },
    ]

    duplicate = client.post(f"/api/company/tasks/{task['id']}/dispatch", json={})
    assert duplicate.status_code == 200
    assert duplicate.json()["created"] is False
    assert len(calls) == 1


def test_company_project_team_room_binding_drives_task_dispatch_room(
    tmp_path: Path,
) -> None:
    calls: list[dict[str, object]] = []
    client = _client_with_team_room_binding(tmp_path, calls)
    project_id = client.post(
        "/api/company/projects",
        json={"name": "Bound Project"},
    ).json()["id"]

    bound = client.post(f"/api/company/projects/{project_id}/team-room", json={})

    assert bound.status_code == 200
    bound_body = bound.json()
    assert bound_body["created"] is True
    assert bound_body["team_room_id"] == f"company-{project_id}"
    assert bound_body["project"]["team_room_id"] == f"company-{project_id}"
    assert bound_body["team"]["members"][0]["name"] == "general"

    task = client.post(
        f"/api/company/projects/{project_id}/tasks",
        json={"title": "Execute through bound room"},
    ).json()
    dispatched = client.post(f"/api/company/tasks/{task['id']}/dispatch", json={})

    assert dispatched.status_code == 200
    assert calls[0]["payload"]["room_id"] == f"company-{project_id}"


def test_company_project_team_room_binding_uses_assembly_members(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agents_root = tmp_path / "agents"
    general_dir = agents_root / "general"
    researcher_dir = agents_root / "market_researcher"
    (general_dir / "agent-core").mkdir(parents=True)
    (researcher_dir / "agent-core").mkdir(parents=True)
    (general_dir / "profile.jsonc").write_text(
        """
        {
          "id": "general",
          "name": "General Planner",
          "category": "assistant",
          "tags": ["planning", "synthesis"]
        }
        """,
        encoding="utf-8",
    )
    (general_dir / "agent-core" / "tool-registry.jsonc").write_text(
        """
        {
          "arms": ["file_read"],
          "extra_affinity": ["goal_breakdown"],
          "private_skills": ["project_planning"]
        }
        """,
        encoding="utf-8",
    )
    (researcher_dir / "profile.jsonc").write_text(
        """
        {
          "id": "market_researcher",
          "name": "Market Researcher",
          "category": "researcher",
          "tags": ["market", "research"]
        }
        """,
        encoding="utf-8",
    )
    (researcher_dir / "agent-core" / "tool-registry.jsonc").write_text(
        """
        {
          "arms": ["web_read", "web_search"],
          "extra_affinity": ["market_research"],
          "private_skills": ["competitive_scan"]
        }
        """,
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "runtime.company.core.store.default_agents_root",
        lambda: agents_root,
    )
    calls: list[dict[str, object]] = []
    client = _client_with_team_room_binding(tmp_path, calls)
    project = client.post(
        "/api/company/projects/blueprint",
        json={
            "prompt": "Create a company project with assembled agents",
            "budget_tier": "standard",
            "horizon_days": 90,
        },
    ).json()["project"]
    assembled = client.post(
        f"/api/company/projects/{project['id']}/team-assembly",
    )
    assert assembled.status_code == 200

    bound = client.post(f"/api/company/projects/{project['id']}/team-room", json={})

    assert bound.status_code == 200
    names = [member["name"] for member in bound.json()["team"]["members"]]
    assert "general" in names
    assert "market_researcher" in names
    assert "planner" not in names


def test_company_task_syncs_from_team_task_events(tmp_path: Path) -> None:
    client, router = _client_with_router(tmp_path)
    project_id = client.post(
        "/api/company/projects",
        json={"name": "Sync Project"},
    ).json()["id"]
    task = client.post(
        f"/api/company/projects/{project_id}/tasks",
        json={"title": "Track runner state"},
    ).json()
    sync = getattr(router, "sync_team_task_event")

    running = sync({
        "type": "task:progress",
        "event": "run_started",
        "task_id": "team-task-sync",
        "room_id": "team-room",
        "server_time": "2026-06-07T00:00:00+00:00",
        "progress": 0.4,
        "task": {
            "id": "team-task-sync",
            "room_id": "team-room",
            "status": "running",
            "metadata": {
                "source": "company_workbench",
                "company_project_id": project_id,
                "company_task_id": task["id"],
            },
        },
    })

    assert running["status"] == "doing"
    assert running["progress"] == 40
    assert running["team_task_id"] == "team-task-sync"
    assert running["actual_start_at"] == "2026-06-07T00:00:00+00:00"

    done = sync({
        "type": "task:progress",
        "event": "run_done",
        "task_id": "team-task-sync",
        "room_id": "team-room",
        "server_time": "2026-06-07T00:05:00+00:00",
        "task": {
            "id": "team-task-sync",
            "room_id": "team-room",
            "status": "done",
            "produced_artifacts": [
                {
                    "type": "team_runner_output",
                    "content": "finished",
                    "risks": [
                        {
                            "title": "Supply delay",
                            "severity": "high",
                            "description": "Key supplier lead time is unknown.",
                        },
                    ],
                    "next_actions": [
                        {
                            "title": "Call two suppliers",
                            "owner": "ops",
                            "due_at": "2026-06-08",
                        },
                    ],
                    "decisions": [
                        {
                            "title": "Use regional supplier first",
                            "rationale": "Lower logistics uncertainty.",
                        },
                    ],
                },
            ],
            "metadata": {
                "source": "company_workbench",
                "company_project_id": project_id,
                "company_task_id": task["id"],
            },
        },
    })

    assert done["status"] == "done"
    assert done["progress"] == 100
    assert done["actual_end_at"] == "2026-06-07T00:05:00+00:00"
    assert done["metadata"]["team_task_artifacts"][0]["content"] == "finished"

    artifacts = client.get(
        f"/api/company/projects/{project_id}/artifacts",
    ).json()
    assert artifacts["count"] == 1
    assert artifacts["artifacts"][0]["task_id"] == task["id"]
    assert artifacts["artifacts"][0]["team_task_id"] == "team-task-sync"
    assert artifacts["artifacts"][0]["type"] == "team_runner_output"
    assert artifacts["artifacts"][0]["title"] == "Track runner state"
    assert artifacts["artifacts"][0]["content"] == "finished"

    insights = client.get(
        f"/api/company/projects/{project_id}/insights",
    ).json()
    assert insights["count"] == 3
    assert insights["counts"] == {
        "risk": 1,
        "next_action": 1,
        "decision": 1,
    }
    by_kind = {item["kind"]: item for item in insights["insights"]}
    assert by_kind["risk"]["title"] == "Supply delay"
    assert by_kind["risk"]["severity"] == "high"
    assert by_kind["next_action"]["owner"] == "ops"
    assert by_kind["next_action"]["due_at"] == "2026-06-08"
    assert by_kind["decision"]["detail"] == "Lower logistics uncertainty."


def test_company_insights_parse_fenced_project_update_json(tmp_path: Path) -> None:
    client, router = _client_with_router(tmp_path)
    project_id = client.post(
        "/api/company/projects",
        json={"name": "JSON Project"},
    ).json()["id"]
    task = client.post(
        f"/api/company/projects/{project_id}/tasks",
        json={"title": "Return structured update"},
    ).json()
    sync = getattr(router, "sync_team_task_event")

    sync({
        "type": "task:progress",
        "event": "run_done",
        "task_id": "team-task-json",
        "room_id": "team-room",
        "server_time": "2026-06-07T01:00:00+00:00",
        "task": {
            "id": "team-task-json",
            "room_id": "team-room",
            "status": "done",
            "produced_artifacts": [
                {
                    "type": "team_runner_output",
                    "content": (
                        "Summary first.\n"
                        "```json\n"
                        "{"
                        "\"project_update\": {"
                        "\"risks\": [],"
                        "\"next_actions\": ["
                        "{"
                        "\"title\": \"Validate budget owner\","
                        "\"owner\": \"pm\""
                        "}"
                        "],"
                        "\"decisions\": []"
                        "}"
                        "}\n"
                        "```"
                    ),
                },
            ],
            "metadata": {
                "source": "company_workbench",
                "company_project_id": project_id,
                "company_task_id": task["id"],
            },
        },
    })

    insights = client.get(
        f"/api/company/projects/{project_id}/insights",
    ).json()
    assert insights["count"] == 1
    assert insights["insights"][0]["kind"] == "next_action"
    assert insights["insights"][0]["title"] == "Validate budget owner"
    assert insights["insights"][0]["owner"] == "pm"
