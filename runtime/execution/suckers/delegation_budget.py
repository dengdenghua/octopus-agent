"""Smart per-turn delegation budget.

Extracted from ``delegation_skills.py`` (2026-06) to keep that file under
the god-file threshold. Implements the budget rules documented in the
parent module's ``_call_agent`` docstring:

  * Absolute cap: ``_PER_TURN_ABSOLUTE_LIMIT`` calls per turn.
  * Success counts; first-time failure is FREE (fingerprint recorded);
    repeat failure (same agent + same prompt) counts.
  * Fingerprint normalization (trim + collapse whitespace + lowercase)
    prevents trivial bypass.

Budget state is process-local — there's no persistence. Restarting the
backend resets all turn counters and fingerprints. Turn IDs are scoped
by ``Session.turn_id`` upstream.
"""

from __future__ import annotations

import hashlib
from collections import OrderedDict

_PER_TURN_ABSOLUTE_LIMIT: int = 5
_MAX_TRACKED_TURNS: int = 1024

# Per-turn state. OrderedDict for LRU eviction.
_TURN_DELEGATIONS: OrderedDict[str, int] = OrderedDict()
_TURN_FAILED_FINGERPRINTS: OrderedDict[str, set[str]] = OrderedDict()


def compute_fingerprint(agent_id: str, prompt: str) -> str:
    """Normalize and hash a delegation spec so repeated identical
    attempts (modulo whitespace / case) share the same fingerprint.

    Prevents trivial bypass: adding a space or changing case won't
    reset the "first failure gets a free pass" counter.
    """
    # Normalize: trim + collapse whitespace + lowercase. We preserve
    # punctuation so semantically different prompts still hash
    # differently. Goal is "same intent" not "same text".
    normalized = " ".join((prompt or "").lower().split())
    key = f"{agent_id}::{normalized}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def check_absolute_cap(turn_id: str | None) -> tuple[int, bool]:
    """Check if we're under the absolute per-turn delegation cap.

    Returns ``(current_count, within_cap)``. When ``turn_id`` is None
    (raw unit tests, no Session) enforcement is OFF.

    Does NOT increment the counter — that happens in ``record_delegation``
    after we know whether the call counts (success vs. first-time
    structural failure).
    """
    if not turn_id:
        return (0, True)
    cur = _TURN_DELEGATIONS.get(turn_id, 0)
    return (cur, cur < _PER_TURN_ABSOLUTE_LIMIT)


def record_delegation(
    turn_id: str | None,
    fingerprint: str,
    *,
    succeeded: bool,
) -> None:
    """Record a delegation attempt. Smart-budget rules:

    * Success → bump counter (counts against absolute cap)
    * First-time failure (fingerprint not seen) → record fingerprint,
      DO NOT bump counter (free retry for the LLM to fix the spec)
    * Repeat failure (fingerprint already seen) → bump counter
      (treat as wasted call, prevents infinite loops)
    """
    if not turn_id:
        return
    failed_fps = _TURN_FAILED_FINGERPRINTS.setdefault(turn_id, set())
    if succeeded:
        # Counts against budget
        _TURN_DELEGATIONS[turn_id] = _TURN_DELEGATIONS.get(turn_id, 0) + 1
        _TURN_DELEGATIONS.move_to_end(turn_id)
    elif fingerprint in failed_fps:
        # Repeat failure — counts (penalizes infinite-loop attempts)
        _TURN_DELEGATIONS[turn_id] = _TURN_DELEGATIONS.get(turn_id, 0) + 1
        _TURN_DELEGATIONS.move_to_end(turn_id)
    else:
        # First-time failure — fingerprint it, DO NOT count
        failed_fps.add(fingerprint)
        _TURN_FAILED_FINGERPRINTS.move_to_end(turn_id)
    # LRU eviction
    while len(_TURN_DELEGATIONS) > _MAX_TRACKED_TURNS:
        _TURN_DELEGATIONS.popitem(last=False)
    while len(_TURN_FAILED_FINGERPRINTS) > _MAX_TRACKED_TURNS:
        _TURN_FAILED_FINGERPRINTS.popitem(last=False)


def bump_and_check(turn_id: str | None) -> tuple[int, bool]:
    """Legacy compat shim: pre-check the absolute cap.

    Kept so existing callers (and tests) work unchanged. Returns the
    same shape but the count is "would-be after this call" — the
    actual increment depends on the result and happens in
    ``record_delegation``.
    """
    cur, within = check_absolute_cap(turn_id)
    return (cur + 1, within)
