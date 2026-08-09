"""Verification-gate narrowing for completed-with-background turns.

Regression coverage for the audit finding that ``realtime_turn_lifecycle``
closed unverified code as COMPLETED whenever *any* background task was in
flight — an unrelated watcher / dev-server / poller could silently green
code changes that never went through the verification gate.

The fix has two halves, both covered here:

1. ``_background_task_is_verification`` (helpers) decides whether a tagged
   background task plausibly runs verification; only those tasks may trigger
   the completed-with-background bypass.
2. ``RealtimeEventBridge.track_background_tool`` tags each watcher task with
   its background command (``octopus-background:<command>``) so the decision
   in (1) has real command text to match against.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Any
from unittest.mock import MagicMock

import pytest

from runtime.protocol.items import CommandExecutionItem
from runtime.sensing.gateway._realtime_turn_lifecycle_helpers import (
    _background_task_is_verification,
)
from runtime.sensing.gateway.realtime_cerebrum import _ReactBridgeState


@pytest.mark.parametrize(
    ("task_name", "expected"),
    [
        # ── verification-looking commands → bypass allowed ─────────
        ("octopus-background:pytest tests/ -q", True),
        ("octopus-background:npm run test", True),
        ("octopus-background:pnpm test", True),
        ("octopus-background:yarn lint", True),
        ("octopus-background:.venv/bin/python -m pytest tests/x.py", True),
        ("octopus-background:python3 -m unittest discover", True),
        ("octopus-background:ruff check runtime/", True),
        ("octopus-background:make lint", True),
        ("octopus-background:ninja test", True),
        ("octopus-background:go test ./...", True),
        ("octopus-background:tsc --noEmit", True),
        ("octopus-background:cmake --build .", True),
        ("octopus-background:pytest", True),
        # ── unrelated watchers / servers → gate runs normally ─────
        ("octopus-background:vite --host", False),
        ("octopus-background:pnpm dev --watch", False),
        ("octopus-background:tail -f logs/app.log", False),
        ("octopus-background:docker compose up", False),
        ("octopus-background:node server.js", False),
        ("octopus-background:python -m http.server", False),
        # ── edge cases ─────────────────────────────────────────────
        ("octopus-background:", False),  # tagged but empty command
        ("", False),  # empty task name
        ("Task-123", True),  # untagged → pre-tagging behavior (hot reload)
    ],
)
def test_background_task_is_verification(task_name: str, expected: bool) -> None:
    assert _background_task_is_verification(task_name) is expected


@pytest.mark.asyncio()
async def test_track_background_tool_tags_watcher_with_command() -> None:
    """The bridge must tag the background watcher with its command so turn
    finalization can distinguish delegated verification from unrelated tasks."""
    state = _ReactBridgeState()

    class _FakeEmitter:
        interrupted: bool = False

        async def notify(self, *args: Any, **kwargs: Any) -> None:
            return None

        def is_turn_interrupted(self, turn_id: str) -> bool:
            return self.interrupted

    class _FakeLog:
        def item_delta(self, *args: Any, **kwargs: Any) -> Any:
            return MagicMock(event_id="e-1")

    turn = MagicMock()
    turn.thread_id = "th-1"
    turn.id = "turn-1"

    item = CommandExecutionItem(command="pytest tests/ --check")
    state.tools["c1"] = item

    emitter = _FakeEmitter()
    log = _FakeLog()
    await state.track_background_tool(
        turn,
        log,
        emitter,
        {
            "tool_call_id": "c1",
            "task_id": "bg-1",
            "snapshot": {"status": "running"},
        },
    )

    assert state.background_tasks, "expected a watcher task to be registered"
    watcher = state.background_tasks[-1]
    try:
        assert watcher.get_name().startswith("octopus-background:")
        assert "pytest tests/ --check" in watcher.get_name()
    finally:
        # The watcher polls a fake background task that will never resolve;
        # cancel it so the test doesn't leave a dangling task behind.
        watcher.cancel()
        with suppress(asyncio.CancelledError):
            await watcher
