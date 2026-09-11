"""Application and operator routes resolve native services after authorization."""

import traceback
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from runtime.execution.suckers import SkillRegistry
from runtime.memory.journal import InMemoryJournal
from runtime.platform.config import builder
from runtime.platform.config.schema import AgentConfig, PlannerConfig
from runtime.safety.auth.identity import Identity, IdentityStore
from runtime.sensing.gateway.evolution_ops_router import create_evolution_ops_router
from runtime.sensing.gateway.observability_router import create_observability_router


@pytest.mark.parametrize("web_skills", [False, True])
def test_web_lifecycle_keeps_native_planner_deferred(tmp_path, monkeypatch, web_skills):
    from runtime.core.cerebrum import LLMPlanner
    from runtime.platform.ui.app import create_app

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OCTOPUS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("OCTOPUS_DATA_DIR", str(tmp_path / "data"))
    build_planner = builder._build_planner
    construction_traces = []

    def construct(*args):
        construction_traces.append("".join(traceback.format_stack(limit=12)))
        return build_planner(*args)

    factory = Mock(side_effect=construct)
    monkeypatch.setattr(builder, "_build_planner", factory)
    stack = builder.build_from_config(
        AgentConfig(
            enable_web_skills=web_skills,
            planner=PlannerConfig(type="llm", model="native-model"),
        )
    )
    app = create_app(
        stack=stack, journal=stack.journal, registry=stack.registry, tentacle_enabled=False
    )
    assert not construction_traces, "\n".join(construction_traces)
    with TestClient(app) as client:
        assert client.get("/api/journal").status_code == 200
        factory.assert_not_called()
        response = client.get("/api/evolution/status")
        assert response.status_code == 200
        assert response.json()["enabled"] is True
        factory.assert_called_once()
        assert isinstance(stack.peek_native_planner(), LLMPlanner)
        assert stack.planner.registry is stack.registry


def test_unauthorized_observability_request_never_resolves_planner():
    identities = IdentityStore()
    identities.add(Identity(actor_id="alice"), api_key_plaintext="alice-token")
    provider = Mock(side_effect=AssertionError("unauthorized planner access"))
    app = FastAPI()
    app.include_router(
        create_observability_router(
            journal=InMemoryJournal(),
            registry=SkillRegistry(),
            planner_provider=provider,
            identity_store=identities,
            require_auth=True,
        )
    )
    with TestClient(app) as client:
        assert client.get("/api/evolution/status").status_code == 401
        assert (
            client.get(
                "/api/evolution/status", headers={"Authorization": "Bearer alice-token"}
            ).status_code
            == 403
        )
    provider.assert_not_called()


def test_tenant_evolution_projection_does_not_resolve_global_planner():
    identities = IdentityStore()
    identities.add(
        Identity(actor_id="alice", roles=("operator",), metadata={"tenant_id": "tenant-a"}),
        api_key_plaintext="alice-token",
    )
    provider = Mock(side_effect=AssertionError("tenant accessed global planner"))
    app = FastAPI()
    app.include_router(
        create_evolution_ops_router(
            journal=InMemoryJournal(),
            registry=SkillRegistry(),
            planner_provider=provider,
            identity_store=identities,
            require_auth=True,
        )
    )
    with TestClient(app) as client:
        assert client.get("/api/evolution/overview").status_code == 401
        assert (
            client.get(
                "/api/evolution/overview", headers={"Authorization": "Bearer alice-token"}
            ).status_code
            == 200
        )
    provider.assert_not_called()


def test_operator_edit_mutates_resolved_planner():
    planner = SimpleNamespace(learned_rules_section="  - [R1] verify the result")
    provider = Mock(return_value=planner)
    app = FastAPI()
    app.include_router(
        create_observability_router(
            journal=InMemoryJournal(), registry=SkillRegistry(), planner_provider=provider
        )
    )
    provider.assert_not_called()
    with TestClient(app) as client:
        response = client.delete("/api/evolution/rules/0")
        assert response.status_code == 200
        assert response.json()["remaining"] == 0
    provider.assert_called_once()
    assert "verify the result" not in planner.learned_rules_section
