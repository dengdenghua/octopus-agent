"""Single-boundary project-group creation and compensation."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from runtime.memory.cowork.collaboration_store import CollaborationStore
from runtime.memory.cowork.group_store import GroupStore
from runtime.memory.threads import ThreadStateStore
from runtime.projectos.store import ProjectStore
from runtime.safety.auth import Identity, IdentityStore
from runtime.sensing.gateway.cowork_group_router import create_cowork_group_router
from runtime.sensing.gateway.projects_router import create_projects_router
from runtime.sensing.gateway.team_rooms_router import create_team_rooms_router
from runtime.sensing.gateway.thread_workspace import verified_managed_workspace


def _stack(tmp_path: Path):
    projects = ProjectStore(base_dir=tmp_path / "projects")
    groups = GroupStore(base_dir=tmp_path / "cowork")
    collaboration = CollaborationStore(base_dir=tmp_path / "cowork")
    threads = ThreadStateStore(
        path=tmp_path / "threads.jsonl",
        index_enabled=False,
        search_enabled=False,
        feedback_enabled=False,
    )
    rooms = create_team_rooms_router(state_path=tmp_path / "rooms.json")
    app = FastAPI()
    app.include_router(rooms)
    app.include_router(
        create_cowork_group_router(
            store=groups,
            collaboration_store=collaboration,
            team_rooms_router=rooms,
        )
    )
    app.include_router(
        create_projects_router(
            store=projects,
            group_store=groups,
            collaboration_store=collaboration,
            team_rooms_router=rooms,
            thread_store=threads,
        )
    )
    return TestClient(app), projects, groups, collaboration, threads, rooms


def _create_body() -> dict:
    return {
        "name": "Atomic launch",
        "goal": "Ship without ghost state",
        "initialAgents": [
            {"id": "general", "displayName": "General"},
            {"id": "coder", "displayName": "Coder", "description": "Builds it"},
        ],
    }


def test_create_project_group_commits_every_surface(tmp_path: Path) -> None:
    client, projects, groups, collaboration, threads, _rooms = _stack(tmp_path)

    response = client.post("/api/projects/group", json=_create_body())

    assert response.status_code == 200, response.json()
    payload = response.json()
    project_id = payload["project"]["id"]
    thread_id = payload["thread_id"]
    room_id = payload["room"]["id"]
    assert len(payload["milestones"]) == 3
    assert projects.project_for_thread(thread_id).id == project_id
    thread = threads.get(thread_id)
    assert thread is not None
    assert thread["metadata"]["project_home"] is True
    assert thread["metadata"]["project_id"] == project_id
    assert thread["values"]["project_id"] == project_id
    state = groups.state(thread_id)
    assert state.room_id == room_id
    assert state.mode == "cluster"
    assert [member.id for member in state.roster] == ["general", "coder"]
    assert payload["room"]["thread_id"] == thread_id
    assert collaboration.session_id_for_room(room_id) == thread_id
    assert collaboration.room_for_session(thread_id)["metadata"]["project_id"] == project_id


@pytest.mark.parametrize(
    "failure_stage",
    [
        "thread_after_commit",
        "project_binding",
        "roster",
        "room_creation_after_commit",
        "room_binding_after_commit",
        "projection_after_commit",
    ],
)
def test_create_project_group_compensates_injected_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
) -> None:
    client, projects, groups, collaboration, threads, rooms = _stack(tmp_path)
    created_thread_ids: list[str] = []
    real_ensure = threads.ensure_thread

    def capture_thread(thread_id, **kwargs):
        thread = real_ensure(thread_id, **kwargs)
        created_thread_ids.append(thread["thread_id"])
        return thread

    monkeypatch.setattr(threads, "ensure_thread", capture_thread)

    def fail(*_args, **_kwargs):
        raise RuntimeError(f"injected {failure_stage} failure")

    if failure_stage == "thread_after_commit":

        def fail_after_thread_commit(thread_id, **kwargs):
            capture_thread(thread_id, **kwargs)
            fail()

        monkeypatch.setattr(threads, "ensure_thread", fail_after_thread_commit)
    elif failure_stage == "project_binding":
        monkeypatch.setattr(projects, "bind_thread", fail)
    elif failure_stage == "roster":
        monkeypatch.setattr(groups, "replace_agent_roster", fail)
    elif failure_stage == "room_creation_after_commit":
        real_room_create = rooms.create_team_from_payload

        def fail_after_room_creation(*args, **kwargs):
            real_room_create(*args, **kwargs)
            fail()

        rooms.create_team_from_payload = fail_after_room_creation
    elif failure_stage == "room_binding_after_commit":
        real_room_bind = rooms.bind_team_thread

        def fail_after_room_binding(*args, **kwargs):
            real_room_bind(*args, **kwargs)
            fail()

        rooms.bind_team_thread = fail_after_room_binding
    else:
        real_projection = collaboration.upsert_room

        def fail_after_projection(*args, **kwargs):
            real_projection(*args, **kwargs)
            fail()

        monkeypatch.setattr(collaboration, "upsert_room", fail_after_projection)

    response = client.post("/api/projects/group", json=_create_body())

    assert response.status_code == 500
    assert projects.list_projects() == []
    assert len(created_thread_ids) == 1
    thread_id = created_thread_ids[0]
    assert threads.get(thread_id) is None
    assert groups.events(thread_id) == []
    assert client.get("/api/teams").json()["teams"] == []
    assert collaboration.room_for_session(thread_id) is None
    assert collaboration.room_by_id(f"collab-{thread_id}") is None


def test_link_room_rejects_both_room_and_thread_double_binding(tmp_path: Path) -> None:
    client, _projects, groups, collaboration, _threads, _rooms = _stack(tmp_path)
    room_a = client.post(
        "/api/teams",
        json={"name": "A", "members": [{"name": "general"}]},
    ).json()
    room_b = client.post(
        "/api/teams",
        json={"name": "B", "members": [{"name": "general"}]},
    ).json()

    linked = client.post("/api/collab/thread-a/link-room", json={"room_id": room_a["id"]})
    assert linked.status_code == 200, linked.json()

    room_conflict = client.post(
        "/api/collab/thread-b/link-room",
        json={"room_id": room_a["id"]},
    )
    assert room_conflict.status_code == 409
    assert groups.state("thread-b").room_id is None

    thread_conflict = client.post(
        "/api/collab/thread-a/link-room",
        json={"room_id": room_b["id"]},
    )
    assert thread_conflict.status_code == 409
    assert groups.state("thread-a").room_id == room_a["id"]
    assert collaboration.session_id_for_room(room_a["id"]) == "thread-a"

    listed = {room["id"]: room for room in client.get("/api/teams").json()["teams"]}
    assert listed[room_a["id"]]["thread_id"] == "thread-a"
    assert listed[room_b["id"]]["thread_id"] is None


def test_authenticated_project_group_owns_and_cleans_managed_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identities = IdentityStore()
    identities.add(
        Identity(actor_id="alice", metadata={"tenant_id": "tenant-a"}),
        api_key_plaintext="sk-alice",
    )
    projects = ProjectStore(base_dir=tmp_path / "projects")
    groups = GroupStore(base_dir=tmp_path / "cowork")
    collaboration = CollaborationStore(base_dir=tmp_path / "cowork")
    threads = ThreadStateStore(
        path=tmp_path / "threads.jsonl",
        index_enabled=False,
        search_enabled=False,
        feedback_enabled=False,
    )
    workspace_root = tmp_path / "workspaces"
    rooms = create_team_rooms_router(
        state_path=tmp_path / "rooms.json",
        identity_store=identities,
        require_auth=True,
    )
    app = FastAPI()
    app.include_router(rooms)
    app.include_router(
        create_projects_router(
            store=projects,
            group_store=groups,
            collaboration_store=collaboration,
            team_rooms_router=rooms,
            thread_store=threads,
            workspace_root=workspace_root,
            identity_store=identities,
            require_auth=True,
        )
    )
    client = TestClient(app)
    headers = {"Authorization": "Bearer sk-alice"}

    created = client.post("/api/projects/group", headers=headers, json=_create_body())
    assert created.status_code == 200, created.json()
    payload = created.json()
    thread_id = payload["thread_id"]
    thread = threads.get(thread_id)
    assert payload["project"]["owner_id"] == "alice"
    assert payload["project"]["tenant_id"] == "tenant-a"
    assert thread["metadata"]["owner_actor_id"] == "alice"
    assert thread["metadata"]["tenant_id"] == "tenant-a"
    assert (
        verified_managed_workspace(
            workspace_root,
            thread_id=thread_id,
            metadata=thread["metadata"],
        )
        is not None
    )

    failed_workspace: list[Path] = []

    def fail_projection(*_args, **_kwargs):
        latest = threads.search(limit=1)[0]
        failed_workspace.append(Path(latest["metadata"]["workspace_path"]))
        raise RuntimeError("injected authenticated projection failure")

    monkeypatch.setattr(collaboration, "upsert_room", fail_projection)
    failed = client.post("/api/projects/group", headers=headers, json=_create_body())
    assert failed.status_code == 500
    assert len(projects.list_projects()) == 1
    assert len(failed_workspace) == 1
    assert not failed_workspace[0].exists()
