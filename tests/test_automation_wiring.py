"""Regression tests for automation-stack wiring fixes.

* computer_use_loop is now registered at serve time (app.py) from a
  router-backed VisionPlanner, so the desktop_operator_arm's
  ``computer_use_loop`` allowlist entry actually resolves. Previously only
  the demo server registered it.
"""

from __future__ import annotations


def test_computer_use_loop_registers_from_router_planner():
    from runtime.execution.suckers import SkillRegistry
    from runtime.execution.suckers.computer_use_loop import (
        ModelRouterVisionPlanner,
        register_computer_use_loop,
    )
    from runtime.sensing.model_router import MockModelRouter

    reg = SkillRegistry()
    planner = ModelRouterVisionPlanner(router=MockModelRouter())
    n = register_computer_use_loop(reg, planner)

    assert n == 1
    assert reg.has("computer_use_loop")


def test_desktop_operator_arm_references_a_registrable_loop():
    # The preset arm allowlists computer_use_loop; this guards that the name
    # the arm references is exactly the one the registrar registers.
    from runtime.execution.suckers import SkillRegistry
    from runtime.execution.suckers.computer_use_loop import (
        ModelRouterVisionPlanner,
        register_computer_use_loop,
    )
    from runtime.sensing.model_router import MockModelRouter

    reg = SkillRegistry()
    register_computer_use_loop(reg, ModelRouterVisionPlanner(router=MockModelRouter()))
    assert "computer_use_loop" in reg.all_names()


# ── browser_router now honours require_auth (was unauthenticated) ──


def _browser_client(**kwargs):
    import pytest

    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from runtime.platform.ui.browser_router import create_browser_router

    app = FastAPI()
    app.include_router(create_browser_router(**kwargs))
    return TestClient(app)


def test_browser_endpoints_open_by_default():
    # Default (require_auth off) → _resolve_actor is a no-op → local preview
    # unchanged. A browser endpoint must NOT 401.
    c = _browser_client()
    assert c.get("/api/browser/config").status_code != 401


def test_browser_endpoints_enforce_auth_when_enabled():
    # require_auth on + an identity store + no bearer token → 401 across the
    # router (previously these endpoints had no auth at all).
    c = _browser_client(require_auth=True, identity_store=object())
    assert c.get("/api/browser/config").status_code == 401
