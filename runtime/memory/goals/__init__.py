"""Durable goal domain with compare-and-swap lifecycle guard (dsh goal port).

The goal is a first-class durable object owned by one session: a strict
phase machine (``active`` / ``paused`` / ``blocked`` / ``complete``) whose
every mutation must advance the current revision by exactly one and survive
a strict transition table. Replaying the append-only goal changes yields the
current projection; a stale or malformed change fails the fold loudly —
``GOAL_STALE_REVISION`` and friends are never silently swallowed.
"""

from __future__ import annotations

from .domain import (
    FoldedGoal,
    GoalBlockReason,
    GoalDomainError,
    GoalOperation,
    GoalPhase,
    GoalRef,
    GoalSnapshot,
)
from .fold import (
    apply_goal_change,
    apply_goal_event,
    decode_goal_change,
    empty_goal_fold_state,
    fold_goal,
    goal_change_ref,
)
from .projection import GoalProjection, GoalProjectionCache
from .service import GoalChanged, GoalService

__all__ = [
    "FoldedGoal",
    "GoalBlockReason",
    "GoalDomainError",
    "GoalOperation",
    "GoalPhase",
    "GoalRef",
    "GoalProjection",
    "GoalProjectionCache",
    "GoalChanged",
    "GoalService",
    "GoalSnapshot",
    "apply_goal_change",
    "apply_goal_event",
    "decode_goal_change",
    "empty_goal_fold_state",
    "fold_goal",
    "goal_change_ref",
]
