"""Incremental goal projection cache (dsh session-surface goal fold).

dsh serves the current goal as a session projection: a last-wins fold
maintained incrementally over ``goal/change`` rows, seeded once from the
history and advanced by every committed change, with an as-of watermark so
consumers know how fresh the view is. ``GoalService.current()`` folds the
whole scoped event list on every call (O(n) per read, correct for CAS but
expensive as a read surface). This cache is that surface: seed once, then
O(1) reads and incremental updates — via the journal's live subscription
when available, or via explicit pushes for the service's own writes on a
base journal. Malformed rows are skipped with a warning (dsh projection
posture: a bad event never breaks the surface for other events).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from runtime.memory.goals.domain import FoldedGoal
from runtime.memory.goals.fold import apply_goal_change, decode_goal_change, empty_goal_fold_state

_logger = logging.getLogger("octopus.goals.projection")

_GOAL_EVENT_TYPE = "goal_change"


@dataclass(frozen=True)
class GoalProjection:
    """One point-in-time view of a service's goal fold (dsh projection frame).

    ``folded`` is the current goal (``goal=None`` when none is active or a
    clear tombstone is current); ``as_of`` is the watermark — the number of
    scoped ``goal_change`` rows applied — so consumers can tell how fresh
    the view is and a later frame supersedes an earlier one by watermark.
    """

    folded: FoldedGoal
    as_of: int


class GoalProjectionCache:
    """Seed-once, advance-incrementally fold of one scope's goal changes."""

    def __init__(
        self,
        journal: Any,
        *,
        agent_id: str | None = None,
        conversation_id: str | None = None,
    ) -> None:
        self._journal = journal
        self._agent_id = agent_id
        self._conversation_id = conversation_id
        self._state = empty_goal_fold_state()
        self._as_of = 0
        self._lock = threading.RLock()
        self._closed = False
        from runtime.memory.journal.journal import Journal

        self._live = type(journal).subscribe is not Journal.subscribe
        self._unsub: Callable[[], None] = lambda: None
        if self._live:
            self._unsub = journal.subscribe(self._on_event)
        self._seed()

    # ─── public surface ──────────────────────────────────────────────────

    def current(self) -> GoalProjection:
        """O(1) read of the projected goal without re-reading the journal."""
        with self._lock:
            return GoalProjection(folded=self._folded(), as_of=self._as_of)

    def apply_change(self, change: Any) -> None:
        """Advance the fold with one committed change (base-journal path).

        Live journals already deliver the change through the subscription,
        so callers must only push on journals without live fan-out — pushing
        twice would fail the strict transition validation on the second
        application.
        """
        with self._lock:
            if self._closed:
                return
            try:
                apply_goal_change(self._state, change)
            except Exception:  # noqa: BLE001 — a bad push never breaks the surface
                _logger.warning(
                    "goal projection: change rejected by fold, skipped (operation=%s)",
                    getattr(change, "operation", "?"),
                    exc_info=True,
                )
                return
            self._as_of += 1

    def close(self) -> None:
        """Stop receiving live events and release the journal subscription."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            if self._live:
                self._unsub()

    # ─── internals ───────────────────────────────────────────────────────

    def _seed(self) -> None:
        for event in self._journal.read_all():
            self._apply_event(event)

    def _on_event(self, event: Any) -> None:
        with self._lock:
            if self._closed:
                return
            self._apply_event(event)

    def _apply_event(self, event: Any) -> None:
        if getattr(event, "event_type", "") != _GOAL_EVENT_TYPE:
            return
        if self._agent_id is not None and getattr(event, "agent_id", None) != self._agent_id:
            return
        if (
            self._conversation_id is not None
            and getattr(event, "conversation_id", None) != self._conversation_id
        ):
            return
        try:
            change = decode_goal_change(getattr(event, "change", None))
        except Exception:  # noqa: BLE001 — malformed row is skipped
            _logger.warning(
                "goal projection: malformed goal_change row skipped (event_id=%s)",
                getattr(event, "event_id", None),
                exc_info=True,
            )
            return
        if change is None:
            return
        self.apply_change(change)

    def _folded(self) -> FoldedGoal:
        state = self._state
        return FoldedGoal(
            goal=state.goal,
            rounds_started=state.rounds_started,
            created_at=state.created_at,
            updated_at=state.updated_at,
            last_ref=state.last_ref,
        )


__all__ = ["GoalProjection", "GoalProjectionCache"]
