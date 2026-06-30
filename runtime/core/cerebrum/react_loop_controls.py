"""Operator controls + run-budget knobs for the ReAct loop.

Moved from ``react_loop.py``: guard-hit telemetry, the per-guard
operator kill-switch (env var + settings.yaml union, with audit
logging), context-window pressure estimation, long-task budget limits,
and the A/B recipe splitter that assigns loop variants per task.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Callable
from typing import Any

from runtime.core.cerebrum.react_context import (
    _estimate_messages_tokens,
    context_budget_tokens_for_model,
)
from runtime.core.cerebrum.react_types import _DEFAULT_REACT_RECIPES, ReActRecipe
from runtime.safety.experiments.variant import ABSplitter

_logger = logging.getLogger(__name__)

# ── Guard telemetry (P1 evolution-loop feed) ──────────────────────
# Lazily-initialised singleton sink. evaluate_guards() calls the
# returned recorder with (label, category) for every firing guard.
# Disabled by env var OCTOPUS_DISABLE_GUARD_TELEMETRY=1 so tests and
# air-gapped runs can opt out. Initialisation failures degrade to a
# no-op — telemetry must never break the loop.
_GUARD_TELEMETRY_SINGLETON: Any = None
_GUARD_TELEMETRY_INIT_DONE = False


def _guard_hit_recorder() -> Callable[[str, str], None] | None:
    """Return a ``recorder(label, category)`` callable, or None when
    telemetry is disabled / unavailable."""
    global _GUARD_TELEMETRY_SINGLETON, _GUARD_TELEMETRY_INIT_DONE
    import os

    if os.environ.get("OCTOPUS_DISABLE_GUARD_TELEMETRY") == "1":
        return None
    if not _GUARD_TELEMETRY_INIT_DONE:
        _GUARD_TELEMETRY_INIT_DONE = True
        try:
            from runtime.safety.evolution.guard_telemetry import GuardTelemetry

            _GUARD_TELEMETRY_SINGLETON = GuardTelemetry()
        except Exception as _exc:  # noqa: BLE001 — telemetry must not break loop
            _logger.debug("guard telemetry unavailable: %s", _exc)
            _GUARD_TELEMETRY_SINGLETON = None
    sink = _GUARD_TELEMETRY_SINGLETON
    if sink is None:
        return None
    return lambda label, category: sink.record(label, category)


def _reset_guard_telemetry_for_tests() -> None:
    """Reset the telemetry singleton — used by tests for isolation."""
    global _GUARD_TELEMETRY_SINGLETON, _GUARD_TELEMETRY_INIT_DONE
    _GUARD_TELEMETRY_SINGLETON = None
    _GUARD_TELEMETRY_INIT_DONE = False


# ── Operator kill-switch for individual guards ────────────────────
# Two-layer source — env var is the emergency knob, settings.yaml is
# the persistent project-level baseline.
#
# Env var: OCTOPUS_DISABLED_GUARDS="label1,label2"
# YAML:    safety:
#            disabled_guards:
#              - label1
#              - label2
#
# Both sources are MERGED (union) — env var adds to whatever YAML
# already disables, never replaces. Operators can flip env at runtime
# to add to the persistent list without editing the file.
#
# Whitespace around labels is stripped so an env var like
# 'magic-number guard, long-function guard' works.
# Re-read fresh on each call so an operator changing the env or
# YAML at runtime takes effect on the next turn.
#
# Audit trail: when the disabled set CHANGES we emit one log line and
# (when telemetry is wired) one structured record so a future operator
# can answer "when did this guard get turned off and by whom".

_LAST_DISABLED_SET: frozenset[str] | None = None
_DEFAULT_SETTINGS_PATHS: tuple[str, ...] = (
    "config.local.yaml",
    "config.yaml",
    "config.example.yaml",
)


def _disabled_guards_from_yaml(
    candidate_paths: tuple[str, ...] = _DEFAULT_SETTINGS_PATHS,
) -> frozenset[str]:
    """Read ``safety.disabled_guards`` from the first existing config.

    Returns frozenset on success; empty frozenset on any failure
    (file missing / unreadable / no PyYAML / wrong shape). Never
    raises — settings being broken must not break the loop.
    """
    import os

    for raw_path in candidate_paths:
        try:
            if not os.path.exists(raw_path):
                continue
        except Exception:  # noqa: BLE001
            continue
        try:
            import yaml  # type: ignore[import-untyped]
        except ImportError:
            return frozenset()
        try:
            with open(raw_path, encoding="utf-8") as fh:
                data = yaml.safe_load(fh.read()) or {}
        except Exception:  # noqa: BLE001
            return frozenset()
        if not isinstance(data, dict):
            return frozenset()
        safety = data.get("safety") or {}
        if not isinstance(safety, dict):
            return frozenset()
        # Source A: safety.disabled_guards: [label, label, ...]
        out: set[str] = set()
        raw = safety.get("disabled_guards") or []
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, str) and item.strip():
                    out.add(item.strip())
        # Source B: safety.guard_overrides: {label: bool}
        # Per-spec on/off knob — operators can selectively re-enable
        # guards that the project baseline disabled, or vice versa.
        # Only the "False" entries contribute to the disabled set;
        # explicit "True" wins over a same-label disabled_guards entry.
        overrides = safety.get("guard_overrides") or {}
        if isinstance(overrides, dict):
            for label, enabled in overrides.items():
                if not isinstance(label, str) or not label.strip():
                    continue
                clean = label.strip()
                if isinstance(enabled, bool):
                    if enabled:
                        out.discard(clean)
                    else:
                        out.add(clean)
        return frozenset(out)
    return frozenset()


def _disabled_guard_labels() -> frozenset[str]:
    """Return labels of guards disabled via env var OR settings.yaml.

    Sources are unioned: env-var entries add to the YAML baseline.
    """
    import os

    raw = os.environ.get("OCTOPUS_DISABLED_GUARDS", "")
    if not raw.strip():
        env_set: frozenset[str] = frozenset()
    else:
        env_set = frozenset(part.strip() for part in raw.split(",") if part.strip())
    yaml_set = _disabled_guards_from_yaml()
    current = env_set | yaml_set
    _audit_disabled_set_change(current)
    return current


def _audit_disabled_set_change(current: frozenset[str]) -> None:
    """Log + record telemetry when the disabled-guard set changes.

    Idempotent: only fires when ``current`` differs from the last
    observed value. The very first call after process start ALSO
    fires when the set is non-empty so a fresh process inheriting
    OCTOPUS_DISABLED_GUARDS leaves a trail.
    """
    global _LAST_DISABLED_SET
    if current == _LAST_DISABLED_SET:
        return
    previous = _LAST_DISABLED_SET
    _LAST_DISABLED_SET = current
    if previous is None and not current:
        # Process start with empty set — nothing notable to record.
        return
    added = sorted(current - (previous or frozenset()))
    removed = sorted((previous or frozenset()) - current)
    _logger.warning(
        "OCTOPUS_DISABLED_GUARDS changed: now=%s added=%s removed=%s",
        sorted(current),
        added,
        removed,
    )
    sink = _GUARD_TELEMETRY_SINGLETON
    if sink is None:
        return
    with contextlib.suppress(Exception):
        sink.record(
            label="__kill_switch_change__",
            category="audit",
            metadata={
                "now": sorted(current),
                "added": added,
                "removed": removed,
            },
        )


def _reset_disabled_set_for_tests() -> None:
    """Reset the cached last-seen set — used by tests for isolation."""
    global _LAST_DISABLED_SET
    _LAST_DISABLED_SET = None


def _estimate_context_fullness(messages: list, model: str | None) -> float:
    """Rough fraction of the model's context budget consumed by ``messages``.

    Uses the same approximate token counter and model-name-keyed budget as
    context compression. Returned value is clamped to ``[0.0, 1.0]``.
    """
    try:
        used_tokens = _estimate_messages_tokens(messages)
    except (TypeError, AttributeError):
        used_tokens = 0

    budget = context_budget_tokens_for_model(model)

    if budget <= 0:
        return 0.0
    ratio = used_tokens / budget
    if ratio < 0.0:
        return 0.0
    if ratio > 1.0:
        return 1.0
    return ratio


_CONTEXT_PRESSURE_NUDGE = (
    "[context-pressure] (level={level})\n"
    "You are approaching the context window. Before this turn ends:\n"
    "1. Update todo_write so every in-flight item shows accurate status.\n"
    '2. In your next Thought, write a one-paragraph "resume state":\n'
    "   - what you were about to do\n"
    "   - any file paths you've written to\n"
    "   - the next concrete action you'd take if continuing\n"
    "This message survives compaction; raw step history may not."
)


def _long_task_budget_limits(
    *,
    is_research_mode: bool,
    is_swarm_mode: bool,
    max_tokens_budget: int,
    max_usd_budget: float,
) -> tuple[int, float, float]:
    """Return accounting limits and pause threshold for this ReAct turn."""
    if is_swarm_mode:
        return (
            max(max_tokens_budget, 250_000),
            max(max_usd_budget, 5.0),
            0.95,
        )
    if is_research_mode:
        return (
            max(max_tokens_budget, 150_000),
            max(max_usd_budget, 3.0),
            0.95,
        )
    return max_tokens_budget, max_usd_budget, 0.8


_REACT_SPLITTER: ABSplitter | None = None


def _build_default_splitter() -> ABSplitter:
    from runtime.safety.experiments.variant import ABSplitter, Variant

    return ABSplitter(
        [Variant(name=r.name, payload=r, weight=1.0) for r in _DEFAULT_REACT_RECIPES],
        seed=42,
    )


def _get_splitter() -> ABSplitter:
    global _REACT_SPLITTER
    if _REACT_SPLITTER is None:
        _REACT_SPLITTER = _build_default_splitter()
    return _REACT_SPLITTER


def pick_react_variant(
    *,
    task_id: str | None = None,
) -> ReActRecipe:
    splitter = _get_splitter()
    v = splitter.next_variant() if task_id is None else splitter.assign_for(task_id)
    return v.payload  # type: ignore[return-value]


def record_react_variant_result(variant_name: str, *, success: bool) -> None:
    splitter = _get_splitter()
    with contextlib.suppress(KeyError):
        splitter.record_outcome(variant_name, success=success)


def get_react_variant_stats() -> list[dict[str, Any]]:
    splitter = _get_splitter()
    out: list[dict[str, Any]] = []
    for name in splitter.names:
        s = splitter.stats[name]
        v = splitter.get(name)
        recipe: ReActRecipe = v.payload
        out.append(
            {
                "name": name,
                "max_iterations": recipe.max_iterations,
                "temperature": recipe.temperature,
                "assignments": s.assignments,
                "successes": s.successes,
                "failures": s.failures,
                "success_rate": round(s.success_rate, 3),
            }
        )
    return out


def _reset_react_variants_for_tests() -> None:
    global _REACT_SPLITTER
    _REACT_SPLITTER = None
