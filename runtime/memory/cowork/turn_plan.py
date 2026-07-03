"""Turn planning: the seam from group *state* to "who acts this turn".

This is the bridge that turns collaboration *mode* into *behaviour* — the
"automatic modes" the design called for. Given a thread's folded group state and
the incoming user message, it composes:

  1. @addressing  — parse ``@agent:<id>`` tokens (the existing input_mentions
     parser, the same tokens the chat box's mention autocomplete inserts), and
  2. the mode policy (``responders``)

into a small, side-effect-free ``TurnPlan`` the realtime driver can act on:
single-agent ReAct, a leader-orchestrated cluster, or a parallel swarm — without
the user manually flipping a mode.

Kept pure (operates on ``GroupState``, not the store) so the decision is fully
unit-tested; ``plan_turn_for_thread`` is the thin store-backed convenience.
"""

from __future__ import annotations

from dataclasses import dataclass

from runtime.core.cerebrum.input_mentions import parse_input_mentions
from runtime.memory.cowork.group import GroupState, responders


@dataclass
class TurnPlan:
    mode: str
    responders: list[str]  # agent ids to run this turn (already mode-filtered)
    addressed: list[str]  # @-addressed agent ids parsed from the message
    is_multi: bool  # >1 responder → run them in parallel (swarm-style)
    reason: str  # human-readable rationale (debugging / UI hint)

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "responders": self.responders,
            "addressed": self.addressed,
            "is_multi": self.is_multi,
            "reason": self.reason,
        }


def plan_turn(state: GroupState, text: str) -> TurnPlan:
    """Decide who acts this turn from the group state + the message's @mentions.

    Pure. The realtime driver reads ``responders``/``is_multi`` to choose between
    single-agent ReAct (1 responder) and parallel execution (N), and ``mode`` for
    the orchestration style."""
    addressed = list(parse_input_mentions(text or "").agents)
    resp = responders(state, addressed)
    is_multi = len(resp) > 1

    if state.mode == "project":
        reason = "project mode — the milestone engine dispatches tasks"
    elif not resp:
        reason = (
            "addressed agents are not active members"
            if addressed
            else "group chat with multiple members — waiting for an @mention"
        )
    elif addressed and set(resp) & set(addressed):
        reason = f"@addressed: {', '.join(resp)}"
    elif state.mode == "swarm":
        reason = f"swarm — all {len(resp)} participant agent(s) in parallel"
    elif state.mode == "cluster":
        reason = f"cluster — leader {resp[0]} orchestrates"
    else:
        reason = f"1:1 — {resp[0]} responds"

    return TurnPlan(
        mode=state.mode,
        responders=resp,
        addressed=addressed,
        is_multi=is_multi,
        reason=reason,
    )


def plan_turn_for_thread(store, thread_id: str, text: str) -> TurnPlan:
    """Store-backed convenience: fold the thread's group state, then plan."""
    return plan_turn(store.state(thread_id), text)
