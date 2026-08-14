"""Durable goal service — append-only journal + CAS lifecycle verbs.

Each mutation writes one ``goal/change`` event (full next snapshot or clear
tombstone) to the journal and returns the fresh projection. The pure fold in
``fold.py`` is the only reader, so a stale or concurrent mutation fails the
next fold loudly instead of being silently applied — the compare-and-swap
guard lives in the data, not in the service instance.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from .domain import (
    GOAL_ALREADY_EXISTS,
    GOAL_INVALID_MAX_ROUNDS,
    GOAL_INVALID_OBJECTIVE,
    GOAL_NOT_FOUND,
    FoldedGoal,
    GoalBlockReason,
    GoalClearChange,
    GoalDomainError,
    GoalOperation,
    GoalRef,
    GoalSnapshot,
    GoalSnapshotChange,
)
from .fold import fold_goal

GOAL_EVENT_TYPE = "goal_change"

_logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class GoalChanged:
    """Live notification after one durable goal mutation commits (dsh ``goal/changed``).

    ``goal`` is absent for a clear tombstone; ``ref`` always carries the
    freshly committed revision identity.
    """

    operation: str
    ref: GoalRef
    goal: GoalSnapshot | None = None


def _now_ms() -> int:
    return int(datetime.now(UTC).timestamp() * 1000)


def _validate_objective(objective: Any) -> str:
    if not isinstance(objective, str) or not objective.strip() or objective != objective.strip():
        raise GoalDomainError(
            GOAL_INVALID_OBJECTIVE, "goal.objective must be non-empty and normalized"
        )
    return objective


def _validate_max_rounds(max_goal_rounds: Any) -> int:
    if (
        not isinstance(max_goal_rounds, int)
        or isinstance(max_goal_rounds, bool)
        or max_goal_rounds < 1
    ):
        raise GoalDomainError(
            GOAL_INVALID_MAX_ROUNDS, "goal.maxGoalRounds must be a positive integer"
        )
    return max_goal_rounds


class GoalService:
    """Journal-backed goal lifecycle with dsh CAS semantics.

    ``journal`` must expose ``write(event)`` and ``read_all()`` (the
    project's ``Journal`` base or any compatible substitute). Events of
    type ``goal_change`` carry the raw dsh change dict under ``change``.
    """

    def __init__(self, journal: Any) -> None:
        self._journal = journal
        self._lock = threading.RLock()
        self._listeners: list[Callable[[GoalChanged], None]] = []

    def subscribe(self, callback: Callable[[GoalChanged], None]) -> Callable[[], None]:
        """Register a listener for committed goal mutations.

        Returns an unsubscribe callable. Listener failures are contained —
        one throwing listener never blocks the write or other listeners
        (dsh: "listener failures are contained").
        """
        with self._lock:
            self._listeners.append(callback)

        def _unsubscribe() -> None:
            with self._lock:
                self._listeners[:] = [fn for fn in self._listeners if fn is not callback]

        return _unsubscribe

    # ─── projection ──────────────────────────────────────────────────────

    def current(self) -> FoldedGoal:
        """Fold the current goal from the journal's goal changes."""
        events = [
            e for e in self._journal.read_all() if getattr(e, "event_type", "") == GOAL_EVENT_TYPE
        ]
        return fold_goal(events)

    def get(self) -> GoalSnapshot | None:
        """Current goal snapshot, or ``None`` when none is active/complete."""
        return self.current().goal

    # ─── lifecycle verbs ─────────────────────────────────────────────────

    def create(self, objective: str, *, max_goal_rounds: int = 5) -> FoldedGoal:
        """Create a fresh active revision-one goal with zero rounds."""
        objective = _validate_objective(objective)
        max_goal_rounds = _validate_max_rounds(max_goal_rounds)
        with self._lock:
            folded = self.current()
            if folded.goal is not None and folded.goal.phase != "complete":
                raise GoalDomainError(
                    GOAL_ALREADY_EXISTS,
                    "goal create requires no current goal or a completed one",
                )
            now = _now_ms()
            change = GoalSnapshotChange(
                operation="create",
                goal=GoalSnapshot(
                    id=uuid4().hex,
                    revision=1,
                    objective=objective,
                    phase="active",
                    max_goal_rounds=max_goal_rounds,
                ),
                rounds_started=0,
                created_at=now,
                updated_at=now,
            )
            self._write(change)
            return self.current()

    def edit(self, objective: str) -> FoldedGoal:
        """Replace the objective; phase, rounds and timestamps are preserved."""
        objective = _validate_objective(objective)
        with self._lock:
            folded = self.current()
            current = folded.goal
            if current is None:
                raise GoalDomainError(GOAL_NOT_FOUND, "goal edit requires a current goal")
            change = GoalSnapshotChange(
                operation="edit",
                goal=GoalSnapshot(
                    id=current.id,
                    revision=current.revision + 1,
                    objective=objective,
                    phase=current.phase,
                    max_goal_rounds=current.max_goal_rounds,
                    blocked_reason=current.blocked_reason,
                ),
                rounds_started=folded.rounds_started,
                created_at=folded.created_at if folded.created_at is not None else _now_ms(),
                updated_at=max(_now_ms(), folded.updated_at or 0),
            )
            self._write(change)
            return self.current()

    def pause(self) -> FoldedGoal:
        """active → paused (definition unchanged)."""
        return self._transition("pause")

    def resume(self) -> FoldedGoal:
        """active/paused/blocked → active, within the round budget."""
        return self._transition("resume")

    def complete(self) -> FoldedGoal:
        """any non-complete phase → complete."""
        return self._transition("complete")

    def block(self, *, code: str, message: str) -> FoldedGoal:
        """active → blocked with a canonical blocker explanation."""
        reason = GoalBlockReason(code=code, message=message)
        with self._lock:
            folded = self.current()
            current = folded.goal
            if current is None:
                raise GoalDomainError(GOAL_NOT_FOUND, "goal block requires a current goal")
            if current.phase != "active":
                raise GoalDomainError(GOAL_ALREADY_EXISTS, "goal block requires an active goal")
            change = GoalSnapshotChange(
                operation="block",
                goal=GoalSnapshot(
                    id=current.id,
                    revision=current.revision + 1,
                    objective=current.objective,
                    phase="blocked",
                    max_goal_rounds=current.max_goal_rounds,
                    blocked_reason=reason,
                ),
                rounds_started=folded.rounds_started,
                created_at=folded.created_at if folded.created_at is not None else _now_ms(),
                updated_at=max(_now_ms(), folded.updated_at or 0),
            )
            self._write(change)
            return self.current()

    def clear(self) -> FoldedGoal:
        """Tombstone the current goal; the next create starts fresh."""
        with self._lock:
            folded = self.current()
            current = folded.goal
            if current is None:
                raise GoalDomainError(GOAL_NOT_FOUND, "goal clear requires a current goal")
            change = GoalClearChange(
                cleared=GoalRef(id=current.id, revision=current.revision + 1),
                cleared_at=max(_now_ms(), folded.updated_at or 0),
            )
            self._write(change)
            return self.current()

    # ─── internals ───────────────────────────────────────────────────────

    def _transition(self, operation: GoalOperation) -> FoldedGoal:
        """Shared non-create snapshot transition (pause/resume/complete)."""
        with self._lock:
            folded = self.current()
            current = folded.goal
            if current is None:
                raise GoalDomainError(GOAL_NOT_FOUND, f"goal {operation} requires a current goal")
            target_phase = {
                "pause": "paused",
                "resume": "active",
                "complete": "complete",
            }[operation]
            change = GoalSnapshotChange(
                operation=operation,
                goal=GoalSnapshot(
                    id=current.id,
                    revision=current.revision + 1,
                    objective=current.objective,
                    phase=target_phase,  # type: ignore[arg-type]
                    max_goal_rounds=current.max_goal_rounds,
                    blocked_reason=(None if operation == "resume" else current.blocked_reason),
                ),
                rounds_started=folded.rounds_started,
                created_at=folded.created_at if folded.created_at is not None else _now_ms(),
                updated_at=max(_now_ms(), folded.updated_at or 0),
            )
            self._write(change)
            return self.current()

    def _write(self, change: GoalSnapshotChange | GoalClearChange) -> None:
        from runtime.memory.journal._journal_models import GoalChangeEvent

        self._journal.write(GoalChangeEvent(change=change.to_dict()))
        is_snapshot = isinstance(change, GoalSnapshotChange)
        self._notify(
            GoalChanged(
                operation=change.operation if is_snapshot else "clear",
                ref=change.goal.ref if is_snapshot else change.cleared,
                goal=change.goal if is_snapshot else None,
            )
        )

    def _notify(self, change: GoalChanged) -> None:
        with self._lock:
            listeners = list(self._listeners)
        for listener in listeners:
            try:
                listener(change)
            except Exception:  # noqa: BLE001 — listener failures are contained
                _logger.warning("goal/changed listener failed", exc_info=True)


__all__ = ["GOAL_EVENT_TYPE", "GoalChanged", "GoalService"]
