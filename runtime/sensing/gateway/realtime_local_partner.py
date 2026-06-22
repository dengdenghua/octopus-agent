"""Direct execution of LocalPartner agents on the realtime path.

A LocalPartner agent wraps an external coding-agent CLI detected on this
machine (Claude Code, Codex). Instead of running it as an LLM agent that
*might* shell out, this drives the CLI itself for the turn — with the user's
own login/subscription — and returns its answer.

Kept as a free function (mirroring ``_drive_swarm_mesh``) so the dispatch +
fallback decisions are unit-testable with a fake runtime and a fake subprocess
runner — no real CLI install required.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from typing import Any

from runtime.execution.agents.local_partner_bridge import (
    blackboard_brief,
    harvest_to_blackboard,
    partner_identity,
    run_local_partner,
)
from runtime.protocol import TurnStatus

# Default wall-clock ceiling for one CLI run; overridable per deployment.
_DEFAULT_TIMEOUT_S = 240.0


def agent_is_local_partner(agent: Any) -> bool:
    """True when ``agent`` should be driven by spawning its registered
    coding-agent CLI directly rather than the LLM loop."""
    return partner_identity(getattr(agent, "capabilities", None)) is not None


def _resolve_timeout() -> float:
    raw = os.environ.get("OCTOPUS_LOCAL_PARTNER_TIMEOUT", "").strip()
    if raw:
        with contextlib.suppress(ValueError, TypeError):
            return max(5.0, float(raw))
    return _DEFAULT_TIMEOUT_S


async def drive_local_partner(
    runtime: Any,
    turn: Any,
    log: Any,
    emitter: Any,
    intent: Any,
    agent: Any,
    provider: Any,
    *,
    text: str,
) -> None:
    """Dispatch the turn to the agent's external coding-agent CLI
    (``claude -p`` / ``codex exec``). The CLI's answer comes back as one plain
    agentMessage.

    Resilience:
      * *unsupported* partner (no known headless invocation) → fall back to the
        normal ReAct loop, so the agent still works.
      * runs-but-errors / times out / missing binary → report plainly and fail
        the turn. Deliberately NOT falling back to octopus's own model, which
        would defeat "use my own subscription" and could surprise on cost.
    """
    ident = partner_identity(getattr(agent, "capabilities", None))
    if ident is None:  # routing shouldn't send a non-partner here; be safe
        await runtime._drive_react(turn, log, emitter, intent, provider, agent)
        return
    partner_id, command = ident
    timeout = _resolve_timeout()
    label = getattr(agent, "display_name", None) or command

    # Shared-blackboard envelope (octopus-mediated stigmergy): brief this agent
    # FROM the team's blackboard, pass the env so a shell-capable CLI can also
    # read/write it via ``octopus bb``, and harvest its output BACK afterwards —
    # collaboration at the I/O boundary, never touching the agent's internals.
    turn_id = str(getattr(turn, "id", "") or getattr(turn, "thread_id", "") or "")
    agent_id = str(getattr(agent, "agent_id", "") or label)
    prompt = text
    brief = blackboard_brief(turn_id)
    if brief:
        prompt = f"{brief}\n\n---\n\n{text}"
    if turn_id and os.environ.get("OCTOPUS_BLACKBOARD_DB"):
        prompt += (
            "\n\n(You're on a team. The shared workspace blackboard is reachable "
            "with `octopus bb get <key>` / `octopus bb set <key> <value>`.)"
        )
    env = {"OCTOPUS_TURN_ID": turn_id, "OCTOPUS_AGENT_ID": agent_id} if turn_id else None

    result = await asyncio.to_thread(
        run_local_partner,
        partner_id=partner_id,
        command=command,
        prompt=prompt,
        cwd=None,
        timeout=timeout,
        env=env,
    )

    if result.unsupported:
        await runtime._drive_react(turn, log, emitter, intent, provider, agent)
        return

    if result.ok:
        harvest_to_blackboard(turn_id, agent_id, result.output)
        await runtime._emit_agent_message(turn, log, emitter, result.output)
        return

    if result.timed_out:
        msg = f'Local partner "{label}" timed out (no result within {int(timeout)}s).'
    else:
        detail = (result.error or "").strip()
        msg = f'Local partner "{label}" couldn\'t finish this one.'
        if detail:
            msg += f"\n\n```\n{detail}\n```"
    await runtime._emit_agent_message(turn, log, emitter, msg)
    turn.status = TurnStatus.FAILED
