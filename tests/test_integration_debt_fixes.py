"""Regression tests for the integration-debt batch fixes.

Covers two wiring fixes surfaced by the integration-debt audit:

* #7 — ``BackgroundRunner._invoke`` now runs each task callback inside a
  fresh ``contextvars.copy_context()`` so ContextVars a task sets (e.g.
  ``_current_session``) don't leak into the next task on a reused thread.
* #8 — an empty ephemeral ``tool_allowlist`` now resolves to the atomic-safe
  inheritance set (``ATOMIC_SKILL_NAMES``), not the full skill catalog — no
  silent over-grant of ``exec_shell`` / write / patch skills. The selection
  logic lives in ``layers.select_tool_specs``.
"""

from __future__ import annotations

import contextvars

from runtime.adapters.scheduler import BackgroundRunner
from runtime.execution.suckers.layers import ATOMIC_SKILL_NAMES, select_tool_specs


class _FakeSpec:
    """Minimal stand-in for an anthropic tool spec (only ``.name`` is used)."""

    def __init__(self, name: str) -> None:
        self.name = name


# ═══════════════════════════════════════════════════════════
# #7 — BackgroundRunner ContextVar isolation
# ═══════════════════════════════════════════════════════════


class TestRunnerContextIsolation:
    def test_invoke_runs_callback_in_isolated_context(self):
        probe: contextvars.ContextVar[str] = contextvars.ContextVar(
            "debt_probe", default="clean",
        )

        def cb() -> None:
            probe.set("dirty")

        r = BackgroundRunner()
        r.add_periodic("probe", 60.0, cb)
        task = r._tasks[0]

        # _invoke runs the callback; with copy_context() the mutation stays
        # inside the copy and does NOT bleed into this (the caller's) context.
        r._invoke(task)

        assert probe.get() == "clean", "task ContextVar leaked into caller"
        assert task.stats.success_count == 1
        assert task.stats.last_error is None

    def test_invoke_still_records_callback_errors(self):
        def boom() -> None:
            raise RuntimeError("kaboom")

        r = BackgroundRunner()
        r.add_periodic("boom", 60.0, boom)
        task = r._tasks[0]

        r._invoke(task)  # must swallow + record, not propagate

        assert task.stats.error_count == 1
        assert "RuntimeError" in (task.stats.last_error or "")


# ═══════════════════════════════════════════════════════════
# #8 — empty allowlist → atomic-only (no over-grant)
# ═══════════════════════════════════════════════════════════


class TestSelectToolSpecs:
    def test_empty_allowlist_returns_only_atomic(self):
        specs = [
            _FakeSpec(n)
            for n in (
                "read_file", "grep_text", "bb_write",   # atomic
                "exec_shell", "write_text_file", "edit_file", "propose_patch",  # NOT
            )
        ]
        out = {s.name for s in select_tool_specs((), specs)}

        assert "read_file" in out and "grep_text" in out  # atomic read kept
        assert "bb_write" in out                           # blackboard kept
        assert "exec_shell" not in out                     # dangerous dropped
        assert "write_text_file" not in out
        assert "edit_file" not in out
        assert "propose_patch" not in out
        assert out <= ATOMIC_SKILL_NAMES                   # nothing beyond atomic

    def test_nonempty_allowlist_honours_named_plus_blackboard(self):
        specs = [
            _FakeSpec(n)
            for n in ("read_file", "exec_shell", "bb_read", "bb_write", "bb_keys")
        ]
        out = [s.name for s in select_tool_specs(("read_file", "exec_shell"), specs)]

        # explicitly named skills are honoured (even dangerous ones — the role
        # opted in), and bb_* are always injected for sibling collaboration.
        assert "read_file" in out and "exec_shell" in out
        assert "bb_read" in out and "bb_write" in out and "bb_keys" in out

    def test_nonempty_allowlist_drops_unregistered_names(self):
        specs = [_FakeSpec("read_file")]
        out = [s.name for s in select_tool_specs(("read_file", "ghost_skill"), specs)]
        assert out == ["read_file"]  # ghost_skill not in registry → dropped
