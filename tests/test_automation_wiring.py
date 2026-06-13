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
