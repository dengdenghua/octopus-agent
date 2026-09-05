"""Risk policy for optional dual-engine shadow reviews.

The primary engine is deliberately the normal execution path.  This module
only answers whether an *automatic* shadow review is justified; it never
starts a model call or mutates a workspace.  Keeping the decision pure makes
the policy easy to audit and prevents a future caller from turning shadow
review into an implicit second execution path.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

AUTO_SHADOW_FEATURE_FLAG = "evolution.dual_helix_shadow_auto"
LOW_CONFIDENCE_THRESHOLD = 0.55
REPEATED_FAILURE_THRESHOLD = 2

# Only a freshly validated candidate is eligible for an automatic review.
# Later rollout states already have their own canary/rollback controls.
_CANDIDATE_STATES = frozenset({"validated"})


@dataclass(frozen=True)
class ShadowTriggerDecision:
    """Auditable result of one automatic-shadow policy evaluation."""

    should_trigger: bool
    reason: str
    signals: tuple[str, ...] = ()

    def to_wire(self) -> dict[str, Any]:
        return asdict(self) | {"signals": list(self.signals)}


def _normalise(value: Any) -> str:
    return str(value or "").strip().lower()


def _confidence_is_low(confidence: Any) -> bool:
    if isinstance(confidence, (int, float)) and not isinstance(confidence, bool):
        return float(confidence) < LOW_CONFIDENCE_THRESHOLD
    return _normalise(confidence) in {"low", "very_low", "insufficient", "uncertain"}


def decide_shadow_trigger(
    *,
    auto_enabled: bool,
    candidate_status: Any = None,
    risk_level: Any = None,
    failure_count: int = 0,
    confidence: Any = None,
) -> ShadowTriggerDecision:
    """Decide if an automatic shadow review is warranted.

    ``auto_enabled`` is intentionally required by the caller.  A false value
    always wins, so adding a new trigger signal cannot silently enable model
    calls in an existing deployment.

    A validated evolution candidate, high/critical risk, repeated failures,
    or low confidence is enough to request a review.  The first matching
    reason is stable for logs and metrics while ``signals`` preserves every
    reason that matched.
    """

    if not auto_enabled:
        return ShadowTriggerDecision(False, "disabled")

    signals: list[str] = []
    state = _normalise(candidate_status)
    if state in _CANDIDATE_STATES:
        signals.append("candidate_stage")

    risk = _normalise(risk_level)
    if risk in {"high", "critical"}:
        signals.append("high_risk")

    try:
        failures = max(0, int(failure_count))
    except (TypeError, ValueError):
        failures = 0
    if failures >= REPEATED_FAILURE_THRESHOLD:
        signals.append("repeated_failure")

    if _confidence_is_low(confidence):
        signals.append("low_confidence")

    if not signals:
        return ShadowTriggerDecision(False, "ordinary_task")

    reason = signals[0]
    return ShadowTriggerDecision(True, reason, tuple(signals))


__all__ = [
    "AUTO_SHADOW_FEATURE_FLAG",
    "LOW_CONFIDENCE_THRESHOLD",
    "REPEATED_FAILURE_THRESHOLD",
    "ShadowTriggerDecision",
    "decide_shadow_trigger",
]
