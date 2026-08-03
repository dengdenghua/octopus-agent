"""Trajectory persistence + planner learning throttles for the ReAct loop.

Extracted from ``react_execution.py``. Persists the beak trajectory to the
journal and throttles the planner's per-journal learning (rules, memories,
knowledge-graph refresh, recipe self-assessment) so they don't run on every
single turn. Leaf module: imports only from platform layers — never imports
react_loop or react_execution.
"""

from __future__ import annotations

import logging
from typing import Any

_logger = logging.getLogger(__name__)

_KG_REFRESH_EVERY = 5
_KG_COUNTERS: dict[int, int] = {}

_RECIPE_REFRESH_EVERY = 5
_RECIPE_COUNTERS: dict[int, int] = {}


def _persist_react_trajectory(
    stack: Any,
    *,
    react_task_id: Any,
    beak_steps: list[Any],
    success: bool,
) -> None:
    if not beak_steps or react_task_id is None:
        return
    journal = getattr(stack, "journal", None)
    if journal is None or not hasattr(journal, "write_trajectory"):
        return

    try:
        from runtime.platform.models import (
            ArmId,
            CostEntry,
            Trajectory,
            TrajectoryOutcome,
        )
    except ImportError:
        return

    thread_id: str | None = None
    try:
        from runtime.platform.process.session import current_session

        _sess = current_session()
        thread_id = _sess.thread_id if _sess else None
    except Exception:  # noqa: BLE001 — thread tagging is best-effort
        thread_id = None

    try:
        traj = Trajectory(
            task_id=react_task_id,
            thread_id=thread_id,
            arm_id=ArmId("react_arm"),
            strategy_id="react_loop",
            steps=list(beak_steps),
            outcome=TrajectoryOutcome(
                success=success,
                cost=CostEntry(),
            ),
        )
        journal.write_trajectory(traj, actor="react_loop")
    except Exception as exc:  # noqa: BLE001
        _logger.debug("react_loop trajectory persist skipped: %s", exc)
        return

    planner = getattr(stack, "planner", None)
    if planner is None:
        return

    if not success:
        learn_rules = getattr(planner, "learn_from_journal", None)
        if learn_rules is not None:
            try:
                learn_rules(journal)
            except Exception as exc:  # noqa: BLE001
                _logger.debug(
                    "react_loop learn_from_journal skipped: %s",
                    exc,
                )

    learn_memories = getattr(planner, "learn_memories_from_journal", None)
    if learn_memories is not None:
        try:
            learn_memories(journal)
        except Exception as exc:  # noqa: BLE001
            _logger.debug(
                "react_loop learn_memories_from_journal skipped: %s",
                exc,
            )

    _react_kg_throttle(stack, journal, planner)
    _react_recipe_throttle(journal, planner)


def _react_kg_throttle(stack: Any, journal: Any, planner: Any) -> None:
    learn_kg = getattr(planner, "learn_kg_from_journal", None)
    if learn_kg is None:
        return
    key = id(journal)
    cnt = _KG_COUNTERS.get(key, 0) + 1
    if cnt < _KG_REFRESH_EVERY:
        _KG_COUNTERS[key] = cnt
        return
    _KG_COUNTERS[key] = 0
    try:
        learn_kg(journal)
    except Exception as exc:  # noqa: BLE001
        _logger.debug("react_loop learn_kg_from_journal skipped: %s", exc)


def _reset_kg_throttle_for_tests() -> None:
    _KG_COUNTERS.clear()


def _react_recipe_throttle(journal: Any, planner: Any) -> None:
    """Refresh the planner's recipe self-assessment from accumulating
    experience, throttled like the KG refresh.

    Without this the recipe verdict (which drives 'prefer a stronger model' +
    the losing-recipe warning) is only ever set at startup and never reflects
    how the current prompt recipe is actually performing this session. Parallels
    the per-turn rules/memory/KG learning already wired here.
    """
    assess = getattr(planner, "assess_recipe_from_journal", None)
    if assess is None:
        return
    key = id(journal)
    cnt = _RECIPE_COUNTERS.get(key, 0) + 1
    if cnt < _RECIPE_REFRESH_EVERY:
        _RECIPE_COUNTERS[key] = cnt
        return
    _RECIPE_COUNTERS[key] = 0
    try:
        assess(journal)
    except Exception as exc:  # noqa: BLE001
        _logger.debug("react_loop assess_recipe_from_journal skipped: %s", exc)


def _reset_recipe_throttle_for_tests() -> None:
    _RECIPE_COUNTERS.clear()
