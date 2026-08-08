"""Project OS tenant/owner isolation regression tests."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from runtime.projectos.model import Milestone, Project
from runtime.projectos.store import ProjectStore
from runtime.safety.auth import Identity, IdentityStore
from runtime.safety.auth.scope import TenantScope
from runtime.sensing.gateway.projects_router import create_projects_router


def _client(tmp_path):
    identities = IdentityStore()
    identities.add(
        Identity(actor_id="alice", metadata={"tenant_id": "tenant-a"}), api_key_plaintext="sk-alice"
    )
    identities.add(
        Identity(actor_id="bob", metadata={"tenant_id": "tenant-b"}), api_key_plaintext="sk-bob"
    )
    store = ProjectStore(base_dir=tmp_path)
    app = FastAPI()
    app.include_router(
        create_projects_router(
            store=store,
            identity_store=identities,
            require_auth=True,
        )
    )
    return TestClient(app), store


def test_project_reads_and_mutations_are_owner_and_tenant_scoped(tmp_path) -> None:
    client, store = _client(tmp_path)
    store.save_project(
        Project(
            id="P-alice",
            name="Alice project",
            goal="private",
            owner_id="alice",
            tenant_id="tenant-a",
        )
    )

    alice = {"Authorization": "Bearer sk-alice"}
    bob = {"Authorization": "Bearer sk-bob"}
    assert client.get("/api/projects", headers=alice).json()["projects"]
    assert client.get("/api/projects", headers=bob).json()["projects"] == []
    assert client.get("/api/projects/P-alice", headers=alice).status_code == 200
    assert client.get("/api/projects/P-alice", headers=bob).status_code == 404
    assert client.post("/api/projects/P-alice/tick", headers=bob).status_code == 404


def test_authenticated_plan_stamps_principal_owner_and_tenant(tmp_path) -> None:
    client, _ = _client(tmp_path)
    response = client.post(
        "/api/projects",
        headers={"Authorization": "Bearer sk-alice"},
        json={"name": "owned", "goal": "ship safely"},
    )
    assert response.status_code == 200
    project = response.json()["project"]
    assert project["owner_id"] == "alice"
    assert project["tenant_id"] == "tenant-a"


def test_scoped_store_blocks_cross_tenant_reads_writes_and_bindings(tmp_path) -> None:
    store = ProjectStore(base_dir=tmp_path)
    alice_scope = TenantScope(tenant_id="tenant-a", actor_id="alice")
    bob_scope = TenantScope(tenant_id="tenant-b", actor_id="bob")
    alice = store.with_scope(alice_scope)
    bob = store.with_scope(bob_scope)

    project = alice.save_project(Project(id="P-scope", name="private", goal="g"))
    alice.save_milestone(project.id, Milestone(id="M-scope", name="phase", goal="g"))
    assert bob.get_project(project.id) is None
    assert bob.list_projects() == []
    assert bob.milestones_for(project.id) == []
    assert bob.delete_project(project.id) is False
    try:
        bob.bind_thread("thread-bob", project.id)
    except PermissionError:
        pass
    else:
        raise AssertionError("cross-tenant thread binding must be rejected")
    assert alice.project_for_thread("thread-bob") is None
