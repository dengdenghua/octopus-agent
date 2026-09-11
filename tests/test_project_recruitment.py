import asyncio
from types import SimpleNamespace

import pytest

from runtime.projectos.initiation import ProjectProposal
from runtime.projectos.recruitment import provisioning_requests
from runtime.sensing.gateway.realtime_project_initiation import initiate_project
from tests.test_project_initiation import setup


def test_new_role_request_is_stable_and_describes_reviewed_scope():
    data = {
        "name": "test",
        "scope": "test",
        "budget": "TBD",
        "milestones": ["one"],
        "staffing": [
            {"role": "Engineer", "responsibilities": "Review designs", "count": 1, "source": "new"}
        ],
    }
    a = provisioning_requests(ProjectProposal.model_validate(data), "thread", {})
    b = provisioning_requests(ProjectProposal.model_validate(data), "thread", {})
    assert a == b
    assert "Review designs" in a[0]["soul"]
    data["staffing"][0]["agent_id"] = "hub:invented"
    with pytest.raises(ValueError):
        provisioning_requests(ProjectProposal.model_validate(data), "thread", {})


@pytest.mark.parametrize("ready", [True, False])
def test_new_role_joins_only_after_preparation_is_verified(tmp_path, monkeypatch, ready):
    monkeypatch.setattr("runtime.projectos.recruitment.hub_candidates", lambda _: [])
    runtime, emitter, kwargs, proposal = setup(tmp_path)
    proposal["staffing"][1].update(source="new", agent_id="")
    agents = runtime._agent_registry.all_agents()
    runtime._agent_registry.has = lambda id: any(a.agent_id == id for a in agents)

    async def approve(method, params, **kw):
        item = params["roleProvisions"][0]
        assert not runtime._cowork_group_store.state("thread").roster
        if ready:
            agents.append(
                SimpleNamespace(
                    agent_id=item["agent_id"],
                    display_name=item["name"],
                    description=item["description"],
                )
            )
        return {"action": "accept", "preparedRoles": {item["key"]: item["agent_id"]}}

    emitter.request_approval.side_effect = approve
    result = asyncio.run(
        initiate_project(runtime, SimpleNamespace(id="turn"), None, emitter, **kwargs)
    )
    assert (result is not None) == ready
    assert bool(runtime._cowork_group_store.state("thread").roster) == ready


def test_cloud_install_hot_loads_the_returned_role(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from runtime.platform.plugins.cloud_expert_store import CloudExpertStore
    from runtime.sensing.gateway import agent_world_router

    root = tmp_path / "agents"
    path = root / "actual_role"
    path.mkdir(parents=True)
    monkeypatch.setattr(agent_world_router, "default_agents_root", lambda: root)
    monkeypatch.setattr(agent_world_router, "resources_root", lambda: tmp_path)
    monkeypatch.setattr(
        CloudExpertStore,
        "install_expert",
        lambda *a, **kw: {"agent_id": "wire_id", "agent_path": str(path), "installed": True},
    )
    monkeypatch.setattr(
        "runtime.execution.suckers.market_skills.immutable_prompt_catalog_required", lambda: False
    )
    loaded = SimpleNamespace(agent_id="actual_role")
    monkeypatch.setattr("runtime.execution.agents.loader.load_agent", lambda *a: loaded)
    registered = []
    sources = []
    registry = SimpleNamespace(has=lambda _: False, register=registered.append, record_hub_source=lambda key, agent: sources.append((key, agent)))
    app = FastAPI()
    app.include_router(
        agent_world_router.create_agent_world_router(registry=registry, runtime=object())
    )
    response = TestClient(app).post("/api/agent-market/cloud/store/wb_test/install")
    assert response.status_code == 200
    assert response.json()["agent_id"] == "actual_role"
    assert registered == [loaded]
    assert sources == [("wb_test", loaded)]


def test_recruitment_uses_visible_catalog_and_current_names(monkeypatch):
    from runtime.platform.plugins.cloud_expert_store import CloudExpertStore
    from runtime.projectos.recruitment import hub_candidates

    monkeypatch.setattr(
        CloudExpertStore,
        "list_experts",
        lambda *a, **kw: {
            "agents": [
                {
                    "id": "wb_hidden-company",
                    "display_name": "企业专属文案",
                    "description": "文案策划" * 100,
                },
                {
                    "id": "wb_content-creator",
                    "display_name": "旧名称",
                    "description": "产品文案策划",
                    "tags": ["文案"],
                },
                {"id": "wb_finance", "display_name": "旧财务名称", "description": "财务会计"},
                {"id": "wb_marketing-growth-team", "display_name": "团队", "is_team": True},
            ]
        },
    )
    rows = hub_candidates("产品文案策划")
    assert [row["agent_id"] for row in rows] == ["hub:wb_content-creator", "hub:wb_finance"]
    assert rows[0]["name"] == "内容创作专家"
    assert rows[0]["skills"] == "文案"


def test_old_proposal_cannot_recruit_hidden_hub_role(tmp_path, monkeypatch):
    monkeypatch.setattr("runtime.projectos.recruitment.hub_candidates", lambda _: [])
    runtime, emitter, kwargs, proposal = setup(tmp_path)
    proposal["staffing"][1].update(source="hub", agent_id="hub:wb_hidden-company")
    result = asyncio.run(
        initiate_project(runtime, SimpleNamespace(id="turn"), None, emitter, **kwargs)
    )
    assert result is None
    emitter.request_approval.assert_not_called()
    assert not runtime._cowork_group_store.state("thread").roster


@pytest.mark.parametrize("source_matches", [True, False])
def test_hub_approval_requires_verified_source(tmp_path, monkeypatch, source_matches):
    monkeypatch.setattr("runtime.projectos.recruitment.hub_candidates", lambda _: [
        {"agent_id": "hub:wb_content-creator", "name": "Writer", "source": "hub"}])
    runtime, emitter, kwargs, proposal = setup(tmp_path)
    proposal["staffing"][1].update(source="hub", agent_id="hub:wb_content-creator")
    runtime._agent_registry.matches_hub_source = lambda expert, actual: source_matches and expert == "wb_content-creator" and actual == "coder"
    emitter.request_approval.side_effect = None
    emitter.request_approval.return_value = {"action": "accept", "preparedRoles": {"hub:wb_content-creator": "coder"}}
    result = asyncio.run(initiate_project(runtime, SimpleNamespace(id="turn"), None, emitter, **kwargs))
    assert (result is not None) == source_matches
    assert bool(runtime._cowork_group_store.state("thread").roster) == source_matches


def test_hub_source_does_not_survive_role_replacement():
    from runtime.execution.agents.base import AgentRegistry
    registry = AgentRegistry()
    original = SimpleNamespace(agent_id="writer")
    registry.register(original)
    registry.record_hub_source("hub-writer", original)
    assert registry.matches_hub_source("hub-writer", "writer")
    assert not registry.matches_hub_source("hub-writer", "other")
    registry.replace(SimpleNamespace(agent_id="writer"))
    assert not registry.matches_hub_source("hub-writer", "writer")
