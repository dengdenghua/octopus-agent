# ruff: noqa: E402 — optional FastAPI import guard precedes route imports

from __future__ import annotations

from types import SimpleNamespace

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi import FastAPI
from fastapi.testclient import TestClient

from runtime.execution.agents import AgentRegistry
from runtime.execution.all_skills import register_group, skills_in_group
from runtime.execution.suckers import SkillRegistry
from runtime.platform import capabilities as caps_mod
from runtime.platform.runtime_policy.capabilities import Capabilities
from runtime.sensing.gateway._agents_endpoints_system import (
    _reconcile_automation_registry,
)
from runtime.sensing.gateway.agents_router import create_agents_router

_GROUPS = ("browser", "browser_act", "computer")


def _assert_skills(registry: SkillRegistry, skills: set[str], *, present: bool) -> None:
    for skill_id in skills:
        assert registry.has(skill_id) is present, skill_id


def _registered_automation_skills(registry: SkillRegistry) -> set[str]:
    expected = {skill_id for group in _GROUPS for skill_id in skills_in_group(group)}
    return {skill_id for skill_id in expected if registry.has(skill_id)}


def test_reconcile_removes_and_restores_automation_groups() -> None:
    registry = SkillRegistry()
    for group in _GROUPS:
        register_group(registry, group)
    initially_registered = _registered_automation_skills(registry)
    assert initially_registered

    removed = _reconcile_automation_registry(
        registry,
        Capabilities(browser_automation=False, desktop_automation=False),
    )
    assert removed["removed"]
    _assert_skills(registry, initially_registered, present=False)

    restored = _reconcile_automation_registry(registry, Capabilities.defaults())
    assert restored["registered"]
    _assert_skills(registry, initially_registered, present=True)


def test_settings_capability_put_hot_applies_without_restart(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(caps_mod, "_store_path", lambda: tmp_path / "capabilities.json")
    skill_registry = SkillRegistry()
    for group in _GROUPS:
        register_group(skill_registry, group)
    initially_registered = _registered_automation_skills(skill_registry)
    assert initially_registered

    app = FastAPI()
    app.state.octopus_state = SimpleNamespace(registry=skill_registry)
    app.include_router(create_agents_router(registry=AgentRegistry()))
    client = TestClient(app)

    disabled = client.put(
        "/api/settings/capabilities",
        json={"browser_automation": False, "desktop_automation": False},
    )
    assert disabled.status_code == 200
    assert disabled.json()["restart_required"] is False
    _assert_skills(skill_registry, initially_registered, present=False)

    enabled = client.put(
        "/api/settings/capabilities",
        json={"browser_automation": True, "desktop_automation": True},
    )
    assert enabled.status_code == 200
    assert enabled.json()["restart_required"] is False
    assert caps_mod.load() == Capabilities.defaults()
    _assert_skills(skill_registry, initially_registered, present=True)
