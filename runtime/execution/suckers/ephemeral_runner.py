"""
LLM-backed runner for ephemeral sub-agent roles.

Bridges ``ephemeral_agents.EphemeralCall`` to any ``ModelRouter``
subclass. Bootstrap wires it with::

    from runtime.sensing.model_router.anthropic_router import AnthropicModelRouter
    from runtime.execution.suckers.ephemeral_agents import (
        set_ephemeral_role_runner,
    )
    from runtime.execution.suckers.ephemeral_runner import (
        make_llm_ephemeral_runner,
    )

    router = AnthropicModelRouter(api_key=..., default_model="claude-haiku-4-5")
    set_ephemeral_role_runner(make_llm_ephemeral_runner(router, registry=registry))

The runner is kept in its own module (not in ``ephemeral_agents.py``)
because it imports ``runtime.sensing.model_router`` · which pulls in the
LLM provider SDK. ``ephemeral_agents.py`` stays dependency-light so
the catalog + dispatch layer loads cleanly on deployments without
anthropic / openai SDKs installed.

Mini agentic loop
-----------------

The runner is NOT just a single-shot LLM call. When a ``registry``
is provided, the runner exposes filtered tools to the sub-agent and
runs a small bounded loop (max ``EPHEMERAL_MAX_ROUNDS``) of:

    LLM emits tool_use blocks → executor runs each → tool_results
    feed back → LLM either calls more tools or replies with text.

Why this matters: without tool access, sub-agents are pure-LLM
"opinion machines" that can't web-search, read files, or — most
importantly for the Kimi-style swarm — write to the shared
blackboard (``bb_write``) so siblings can see their findings. With
tool access, parallel sub-agents really collaborate.

The tool catalog is filtered by the call's effective ``tool_allowlist``:

* Empty tuple ``()`` → full atomic-safe inheritance (the role gets
  all ATOMIC_SKILL_NAMES).
* Non-empty → only the named skills (still intersected with what's
  registered, in case a role names a skill that isn't loaded).

Sub-agent tool budgets
----------------------

Sub-agents are short-form helpers, not deep-thinkers — they get a
much lower round cap than the parent (5 vs 30 in the parent's
``tool_bridge.MAX_TOOL_ROUNDS``). If a sub-agent burns 5 rounds
without converging, it returns whatever text it produced so far;
the parent decides whether to re-spawn or move on.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from runtime.execution.suckers._ephemeral_events import (
    _emit_sub_text_delta,
    _emit_sub_tool_event,
    _emit_sub_user_message,
    _emit_subagent_lifecycle_event,
    _safe_ctx_emit,
)
from runtime.execution.suckers._ephemeral_tool_exec import (
    _ephemeral_write_confine_block,  # noqa: F401  (re-exported for tests)
    _execute_tool_in_subagent,
)
from runtime.execution.suckers.ephemeral_injection_gate import (
    mark_inherited_ephemeral_taint,
)

_log = logging.getLogger("runtime.execution.ephemeral_runner")

# Bound on the per-sub-agent tool-use loop. Role-specific caps allow
# research/implementation agents to run deeper while keeping simple roles
# (reviewer/arbiter) bounded. The parent's MAX_TOOL_ROUNDS (currently 300)
# is the ultimate ceiling for true long-running work.
EPHEMERAL_MAX_ROUNDS: int = 5  # default for simple roles

# Per-role overrides for roles that need deeper exploration/execution.
# Target: align with Claude Code depth (20-30 rounds for research tasks).
EPHEMERAL_MAX_ROUNDS_BY_ROLE: dict[str, int] = {
    "researcher": 25,  # web_search + fetch + synthesize
    "synthesizer": 12,  # gather sibling evidence + write/read-back artifact
    "explorer": 15,  # file traversal + grep + read
    "implementer": 30,  # edit + verify + test cycles
    "debugger": 20,  # trace + hypothesis + verify
    "architect": 15,  # read + analyze + design
    "designer": 20,  # read + plan + decompose
    "planner": 12,  # breakdown + estimate
    # reviewer/arbiter/synthesizer stay at 5 (single-shot opinion)
}

# Legacy per-sub-agent token ceiling. Kept as a public constant for
# compatibility, but no longer enforced: long research helpers should
# be bounded by the round cap and the parent/session budget, not by a
# hidden 10k sub-agent cutoff that can replace useful output with a
# budget-exhausted placeholder.
EPHEMERAL_TOKEN_BUDGET: int = 0

# Convergence guard. If the agent runs this many consecutive rounds where it
# only re-invokes tools it has already called (no new tool signature), it is
# looping rather than exploring. Stop early and hand back the partial work as
# converged instead of burning the whole round cap and surfacing a hard
# "exceeded round cap" error to the user.
EPHEMERAL_STALL_ROUNDS: int = 3


def _tool_call_signature(tool_call: Any) -> tuple[str, str]:
    """Stable identity for one tool call, used for repeat-loop detection."""
    name = getattr(tool_call, "name", "") or ""
    raw = getattr(tool_call, "input", None) or {}
    try:
        import json as _json

        return (str(name), _json.dumps(raw, sort_keys=True, ensure_ascii=False))
    except (TypeError, ValueError):  # non-serializable args -> fall back to repr
        return (str(name), repr(raw))


# ── Child→parent report tool (dsh ``tool-subagent-report``) ──────────────
# Installed into every continuable in-process child's tool surface (i.e. when
# ``call.context["subagent_session_id"]`` is present): the child can deliver
# self-contained findings to its direct parent MID-round, not only via the
# transcript the bridge pulls afterwards. Roots, one-shot children, remote
# providers, and agentless executions never see the registration (dsh scope).

REPORT_TOOL_GUIDANCE = (
    "Deliver your result with the report tool before you finish: call it once "
    "with a self-contained answer. The agent that started you shares your "
    "workspace but does not automatically receive your transcript, tool "
    'output, or reasoning, so a closing remark such as "done" leaves it '
    "nothing it can use. Report earlier as well whenever a partial finding "
    "changes what that agent should do next; reporting never ends your turn."
)


def _report_tool_spec() -> Any:
    """The ``report`` tool definition (dsh ``tool-subagent-report``)."""
    from runtime.platform.models.llm import ToolSpec

    return ToolSpec(
        name="report",
        description=(
            "Report selected content to the agent that started you. Call this "
            "once before you finish, with a self-contained final result, and "
            "earlier for progress or findings that change what that agent "
            "does next. That agent shares your workspace but does not "
            "automatically receive your transcript, tool output, or "
            "reasoning, so finishing your work is not itself a result. "
            "Reporting does not end your turn or finish your work, and only "
            "your direct parent receives it. A failed call may still have "
            "arrived, so do not blindly repeat it."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "output": {
                    "type": "string",
                    "description": (
                        "Actionable content for your parent; summarize "
                        "conclusions and reference relevant shared paths."
                    ),
                }
            },
            "required": ["output"],
            "additionalProperties": False,
        },
    )


def _handle_report_tool(
    tc: Any,
    session_id: str,
    *,
    delivery: str = "wakeup",
) -> tuple[str, bool]:
    """Deliver one ``report`` tool call to the child's report lane.

    Best-effort + at-least-once like dsh: a storage failure returns an error
    result to the child (which must not blindly repeat — the report may still
    have arrived), but never crashes the child round.
    """
    args = getattr(tc, "input", None) or {}
    content = args.get("output") if isinstance(args, dict) else None
    if not isinstance(content, str) or not content.strip():
        return (
            '(report failed) parameter "output" must be a non-empty string '
            "with the content to deliver.",
            True,
        )
    try:
        from runtime.execution.subagents.sessions import (
            get_subagent_session_store,
        )

        store = get_subagent_session_store()
        if store is None:
            return "(report failed) subagent session store unavailable.", True
        session = store.append_report(
            session_id,
            content=content,
            delivery="wakeup" if delivery != "quiet" else "quiet",
        )
        if session is None:
            return f"(report failed) no subagent session {session_id!r}.", True
    except ValueError as exc:
        return f"(report failed) {exc}", True
    except Exception as exc:  # noqa: BLE001 — never crash the child round
        _log.warning(
            "report tool failed for session %s: %s: %s",
            session_id,
            type(exc).__name__,
            exc,
        )
        return f"(report failed) {type(exc).__name__}: {exc}", True
    message_id = f"report-{len(session.reports) - 1}"
    effective = session.reports[-1].delivery if session.reports else "quiet"
    if effective == "quiet":
        note = (
            "Delivered to the parent's report lane, but queued quietly: "
            "the parent was not woken (the consecutive-wake budget is spent). "
            "Do not keep reporting — the parent will read this on its next turn."
        )
    elif effective == "queued":
        note = (
            "Delivered to the parent's report lane, queued into its running "
            "turn: the parent is busy and was not woken. Do not keep reporting "
            "— the parent will read this when it next continues this session "
            "or starts a turn."
        )
    else:
        note = "The parent has been woken to read this."
    return (
        f"Report delivered (messageId={message_id}). {note} "
        "A failed call may still have arrived, so do not blindly repeat it.",
        False,
    )


class EphemeralRoundCapExceeded(RuntimeError):
    """Raised when the ephemeral sub-agent loop hits its round cap.

    Carries any partial text the agent produced before the cap so callers
    can decide whether to surface partial work or propagate the failure.
    Previously the runner returned a placeholder string with success=True,
    which caused parent agents to silently accept empty answers.
    """

    def __init__(self, partial_text: str, rounds: int, role_id: str) -> None:
        super().__init__(
            f"sub-agent {role_id!r} exceeded round cap ({rounds}) "
            f"without converging · {len(partial_text)} chars of partial output"
        )
        self.partial_text = partial_text
        self.rounds = rounds
        self.role_id = role_id


_LENGTH_LIMIT_FINISH_REASONS = {
    "length",
    "max_tokens",
    "max_output_tokens",
    "output_limit",
    "token_limit",
}


def _is_length_limited_finish(reason: str | None) -> bool:
    normalized = (reason or "").strip().lower()
    return normalized in _LENGTH_LIMIT_FINISH_REASONS


_CONTINUE_AFTER_LENGTH_LIMIT = (
    "Your previous response was cut off by the output length limit. "
    "Continue exactly where it stopped, do not repeat earlier text, "
    "and finish every missing requirement."
)

_TRUNCATION_ENDINGS = (
    ".",
    "!",
    "?",
    "。",
    "！",
    "？",
    ")",
    "]",
    "】",
    "」",
    "”",
    "'",
    '"',
    "`",
    "…",
)


def _looks_truncated_text(
    text: str,
    *,
    output_tokens: int,
    max_tokens: int,
) -> bool:
    """Best-effort fallback when a provider omits a truncation finish_reason."""
    stripped = text.rstrip()
    if not stripped:
        return False
    if (
        max_tokens > 0
        and output_tokens > 0
        and (
            output_tokens >= max(1, int(max_tokens * 0.9))
            and len(stripped) >= max(1200, int(max_tokens * 0.75))
        )
    ):
        return True
    if max_tokens > 0 and len(stripped) >= max(2000, int(max_tokens * 1.5)):
        return not stripped.endswith(_TRUNCATION_ENDINGS)
    return bool(len(stripped) >= 1200 and not stripped.endswith(_TRUNCATION_ENDINGS))


def _select_call_model(default_model: str, context: Any) -> str:
    """Pick the model for ONE ephemeral sub-agent run.

    The dispatch bridge stamps ``context["model_name"]`` for BOTH explicit
    per-dispatch overrides (caller passed ``context={"model_name": ...}``) AND
    ``use_cheap_model`` routing (bridge injects the resolved cheap model). The
    runner must honor it; the factory-captured ``default_model`` (the
    planner/stack default) is only the fallback when no override is present.

    This is the lever that actually changes the backend: ``ModelDispatchRouter``
    resolves the provider/host from ``request.model``, so returning the override
    here is what makes the sub-agent reach the requested model's host instead of
    silently running on the planner default (the bug this fixes — the override
    was carried all the way into ``call.context`` but never consulted).
    """
    if isinstance(context, dict):
        override = context.get("model_name")
        if isinstance(override, str) and override.strip():
            return override.strip()
    return default_model


def make_llm_ephemeral_runner(
    router: Any,
    *,
    registry: Any = None,
    default_model: str | None = None,
    max_tokens: int = 2048,
    temperature: float = 0.3,
    system_provider: str = "anthropic",
    token_budget: int = EPHEMERAL_TOKEN_BUDGET,
) -> Callable[[Any], str]:
    """Build an ephemeral runner that calls ``router.call(request)``
    per invocation.

    Parameters
    ----------
    router :
        Any ``runtime.sensing.model_router.ModelRouter`` subclass · Anthropic /
        OpenAI / Molili / Mock.
    registry :
        Optional ``SkillRegistry``. When provided, the runner switches
        from single-shot mode to a mini agentic loop (see module
        docstring). When ``None`` (legacy callers / tests), behaves
        like the original single-shot runner.
    default_model :
        Model identifier to use. Falls back to ``router.default_model``
        when the router exposes one · else the caller MUST pass this.
    max_tokens :
        Upper bound for the sub-agent's reply. Ephemeral roles are
        single-shot so a modest cap keeps cost + latency predictable.
    temperature :
        Slight creativity for roles like ``researcher`` / ``architect`` ·
        set to 0 for deterministic review tasks if desired.
    system_provider :
        Provider hint for ``ModelRequest`` · match the router class.
    token_budget :
        Deprecated compatibility parameter. Sub-agent token budgets are
        no longer enforced; the mini-loop is bounded by
        ``EPHEMERAL_MAX_ROUNDS`` and parent/session-level accounting.

    Returns
    -------
    A ``EphemeralRunner`` callable that takes an ``EphemeralCall`` and
    returns the text reply.
    """
    # Resolve the model identifier ONCE at factory time · avoids
    # re-probing ``router`` on every call.
    model = default_model or getattr(router, "default_model", None) or ""
    if not model:
        raise ValueError(
            "make_llm_ephemeral_runner: could not determine model · "
            "pass default_model explicitly or use a router that "
            "exposes a ``default_model`` attribute."
        )

    def _runner(call: Any) -> str:
        """Call the LLM with a composed (system + user) message pair.

        ``call.composed_system_prompt`` already has the role persona
        + caller conversation + caller memory glued together (see
        ``ephemeral_agents._compose_system_prompt``). We just
        translate to ``Message`` objects and dispatch.

        When a registry is wired up, run a bounded agentic loop so
        the sub-agent can actually USE tools (web_search / bb_write /
        read_file etc.) rather than being a pure-LLM opinion box.
        """
        # Lazy import · keeps module-level dep light (see module doc).
        from runtime.sensing.model_router import Message, ModelRequest

        # ── Prompt-injection taint inheritance ──
        # The spawning parent stamps its taint into ``call.context`` (see
        # bridge.call_subagent). The timeout dispatch path runs this runner in
        # a fresh thread whose taint contextvar started clean, so re-mark it
        # here. Gated risky tools are then blocked in
        # ``_execute_tool_in_subagent`` (ephemeral runs bypass the executor
        # chokepoint, so the gate lives there).
        mark_inherited_ephemeral_taint(getattr(call, "context", None))

        # Per-dispatch model override. ``model`` (resolved at factory time) is
        # only the default; the bridge carries the caller's requested model —
        # explicit override or cheap-routing — in ``call.context["model_name"]``.
        # Honor it so this run reaches the requested backend.
        effective_model = _select_call_model(
            model,
            getattr(call, "context", None),
        )

        # Single-shot fallback path · used when no registry was
        # plumbed through (legacy bootstrap, unit tests).
        if registry is None:
            req = ModelRequest(
                model=effective_model,
                messages=[
                    Message(role="system", content=call.composed_system_prompt),
                    Message(role="user", content=call.user_prompt),
                ],
                max_tokens=max_tokens,
                temperature=temperature,
                system_provider=system_provider,
            )
            # Pull the optional event_emitter injected by the bridge so
            # we can forward role text as ``sub_text_delta`` chunks the
            # parent gateway can render live.
            _ctx_emitter_single = call.context.get("event_emitter") if call.context else None
            _ctx_session_id_single = call.context.get("subagent_session_id") if call.context else ""
            _emit_sub_user_message(_ctx_session_id_single, call.user_prompt)
            stream_fn_single = getattr(router, "call_stream", None)
            if callable(stream_fn_single):
                accumulated = ""
                try:
                    for event in stream_fn_single(req):
                        if event.type == "text_delta":
                            chunk = event.delta or ""
                            if chunk:
                                accumulated += chunk
                                _emit_sub_text_delta(
                                    call.role.id,
                                    1,
                                    chunk,
                                    session_id=_ctx_session_id_single,
                                    emitter=_ctx_emitter_single,
                                )
                        elif event.type == "done":
                            fin = event.final
                            if fin is not None and not accumulated:
                                accumulated = str(getattr(fin, "text", "") or "")
                            break
                except (ConnectionError, TimeoutError, OSError, ValueError, TypeError) as exc:  # noqa: BLE001
                    _log.warning(
                        "ephemeral LLM runner (single-shot stream) · role=%s model=%s · %s: %s",
                        call.role.id,
                        effective_model,
                        type(exc).__name__,
                        exc,
                    )
                    raise
                return accumulated
            _log.warning(
                "ephemeral LLM runner (single-shot) · role=%s "
                "model=%s · call_stream unavailable, falling back "
                "to non-streaming call() — no live token streaming",
                call.role.id,
                effective_model,
            )
            try:
                resp = router.call(req)
            except (ConnectionError, TimeoutError, OSError, ValueError, TypeError) as exc:  # noqa: BLE001
                _log.warning(
                    "ephemeral LLM runner (single-shot) · role=%s model=%s · %s: %s",
                    call.role.id,
                    effective_model,
                    type(exc).__name__,
                    exc,
                )
                raise
            return str(getattr(resp, "text", None) or "")

        # ── Agentic loop path ────────────────────────────────
        # Build the tool spec list (filtered by role allowlist).
        from runtime.execution.suckers.layers import select_tool_specs
        from runtime.execution.tool_spec_builder import (
            build_anthropic_tool_specs,
        )

        all_specs = build_anthropic_tool_specs(registry)
        ctx_allowlist = call.context.get("tool_allowlist") if call.context else None
        if isinstance(ctx_allowlist, (list, tuple, set)):
            allowlist = tuple(str(name).strip() for name in ctx_allowlist if str(name).strip())
        else:
            allowlist = tuple(call.role.tool_allowlist) if call.role.tool_allowlist else ()
        tool_specs = select_tool_specs(allowlist, all_specs)

        if not tool_specs:
            # No tools to expose · degrade to single-shot.
            req = ModelRequest(
                model=effective_model,
                messages=[
                    Message(role="system", content=call.composed_system_prompt),
                    Message(role="user", content=call.user_prompt),
                ],
                max_tokens=max_tokens,
                temperature=temperature,
                system_provider=system_provider,
            )
            resp = router.call(req)
            return str(getattr(resp, "text", None) or "")

        # Child→parent report lane (dsh ``tool-subagent-report``): a
        # continuable in-process child gets the ``report`` tool plus its
        # usage guidance so it can deliver findings to its direct parent
        # mid-round. Only exposed when the bridge stamped a session id;
        # roots / one-shot children / remote providers never see it.
        report_session_id = call.context.get("subagent_session_id") if call.context else None
        report_delivery = (
            str(call.context.get("subagent_report_delivery") or "wakeup")
            if call.context
            else "wakeup"
        )
        if report_session_id:
            tool_specs = list(tool_specs) + [_report_tool_spec()]
            call.composed_system_prompt = (
                f"{call.composed_system_prompt}\n\n## report tool\n{REPORT_TOOL_GUIDANCE}"
            )

        # Pull the optional event_emitter injected by the bridge.
        # It's a plain Callable[[dict], None] — fire-and-forget.
        _ctx_emitter = call.context.get("event_emitter") if call.context else None
        _ctx_session_id = call.context.get("subagent_session_id") if call.context else ""
        # Journal the session's user prompt (dsh session-log invariant) so
        # the surface user lane is reconstructable from the log alone.
        _emit_sub_user_message(_ctx_session_id, call.user_prompt)

        # Role-specific round cap (align with Claude Code depth for research tasks)
        max_rounds = EPHEMERAL_MAX_ROUNDS_BY_ROLE.get(call.role.id, EPHEMERAL_MAX_ROUNDS)

        messages: list[Any] = [
            Message(role="system", content=call.composed_system_prompt),
            Message(role="user", content=call.user_prompt),
        ]
        accumulated_text = ""
        seen_tool_signatures: set[tuple[str, str]] = set()
        stall_rounds = 0
        for round_i in range(max_rounds):
            req = ModelRequest(
                model=effective_model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                system_provider=system_provider,
                tools=tool_specs,
            )
            # Stream the round so the parent gateway can show role
            # text as it lands instead of buffering the whole reply
            # for 30+ seconds. ``call_stream`` is uniform across
            # routers (real streaming where supported, synthetic
            # one-shot fallback elsewhere) so we don't need to
            # branch on the provider here. We still need the final
            # ``ModelResponse`` for tool_calls + token counts, which
            # ``done`` carries.
            #
            # Some test routers / minimal mocks don't implement
            # ``call_stream`` — fall back to the non-streaming ``call``
            # path so they keep working unchanged.
            text = ""
            tool_calls: list[Any] = []
            output_tokens_round = 0
            finish_reason_round = "stop"
            stream_fn = getattr(router, "call_stream", None)
            if not callable(stream_fn):
                _log.warning(
                    "ephemeral agentic runner · role=%s model=%s "
                    "round=%d · call_stream unavailable, falling back "
                    "to non-streaming call() — UI will show no "
                    "live token streaming for this role",
                    call.role.id,
                    effective_model,
                    round_i,
                )
                try:
                    resp = router.call(req)
                except (ConnectionError, TimeoutError, OSError, ValueError, TypeError) as exc:  # noqa: BLE001
                    _log.warning(
                        "ephemeral agentic runner · role=%s model=%s round=%d · %s: %s",
                        call.role.id,
                        effective_model,
                        round_i,
                        type(exc).__name__,
                        exc,
                    )
                    if not accumulated_text:
                        raise
                    return accumulated_text
                text = str(getattr(resp, "text", None) or "")
                tool_calls = list(getattr(resp, "tool_calls", []) or [])
                int(getattr(resp, "input_tokens", 0) or 0)
                output_tokens_round = int(getattr(resp, "output_tokens", 0) or 0)
                finish_reason_round = str(getattr(resp, "finish_reason", "stop") or "stop")
            else:
                try:
                    for event in stream_fn(req):
                        etype = event.type
                        if etype == "text_delta":
                            chunk = event.delta or ""
                            if chunk:
                                text += chunk
                                # Forward to the parent's emitter so
                                # swarm consumers can render the role's
                                # prose live. ``sub_text_delta`` is the
                                # role-scoped equivalent of react_loop's
                                # ``text_delta``; the journal mirror
                                # keeps the stream reconstructable.
                                _emit_sub_text_delta(
                                    call.role.id,
                                    round_i + 1,
                                    chunk,
                                    session_id=_ctx_session_id,
                                    emitter=_ctx_emitter,
                                )
                        elif etype == "tool_use" and event.tool_call is not None:
                            tool_calls.append(event.tool_call)
                        elif etype == "done":
                            fin = event.final
                            if fin is not None:
                                int(getattr(fin, "input_tokens", 0) or 0)
                                output_tokens_round = int(getattr(fin, "output_tokens", 0) or 0)
                                finish_reason_round = str(
                                    getattr(fin, "finish_reason", "stop") or "stop"
                                )
                            break
                except (ConnectionError, TimeoutError, OSError, ValueError, TypeError) as exc:  # noqa: BLE001
                    _log.warning(
                        "ephemeral agentic runner · role=%s model=%s round=%d · %s: %s",
                        call.role.id,
                        effective_model,
                        round_i,
                        type(exc).__name__,
                        exc,
                    )
                    partial = accumulated_text + text
                    if not partial:
                        raise
                    return partial

            if text:
                accumulated_text += text

            # Done · LLM produced text but no more tool calls.
            if not tool_calls:
                if _is_length_limited_finish(finish_reason_round) and round_i + 1 < max_rounds:
                    _log.info(
                        "ephemeral agentic runner · role=%s model=%s "
                        "round=%d · continuing after finish_reason=%s",
                        call.role.id,
                        effective_model,
                        round_i,
                        finish_reason_round,
                    )
                    messages.append(Message(role="assistant", content=text))
                    messages.append(
                        Message(
                            role="user",
                            content=_CONTINUE_AFTER_LENGTH_LIMIT,
                        )
                    )
                    continue
                if (
                    not _is_length_limited_finish(finish_reason_round)
                    and round_i + 1 < max_rounds
                    and _looks_truncated_text(
                        text,
                        output_tokens=output_tokens_round,
                        max_tokens=max_tokens,
                    )
                ):
                    _log.info(
                        "ephemeral agentic runner · role=%s model=%s "
                        "round=%d · continuing after inferred truncation",
                        call.role.id,
                        effective_model,
                        round_i,
                    )
                    messages.append(Message(role="assistant", content=text))
                    messages.append(
                        Message(
                            role="user",
                            content=_CONTINUE_AFTER_LENGTH_LIMIT,
                        )
                    )
                    continue
                if _is_length_limited_finish(finish_reason_round):
                    notice = "\n\n[response truncated: model stopped at the output length limit]"
                    _emit_sub_text_delta(
                        call.role.id,
                        round_i + 1,
                        notice,
                        session_id=_ctx_session_id,
                        emitter=_ctx_emitter,
                    )
                    return accumulated_text + notice
                return accumulated_text

            # Re-materialize the assistant turn (text + tool_use
            # blocks) so the next LLM round sees its own prior
            # response. Same shape as ``tool_bridge``.
            assistant_blocks: list[dict[str, Any]] = []
            if text:
                assistant_blocks.append({"type": "text", "text": text})
            for tc in tool_calls:
                assistant_blocks.append(
                    {
                        "type": "tool_use",
                        "id": tc.id,
                        "name": tc.name,
                        "input": tc.input,
                    }
                )
            messages.append(
                Message(
                    role="assistant",
                    content=assistant_blocks,
                )
            )

            # Execute each tool through the registry's handler.
            # Emit sub-tool-start/end events around each call so the
            # parent SSE stream can forward them to the UI with a
            # ``parent_tool_use_id`` correlation (set by the parent
            # loop in ``tool_bridge.stream_agentic_fallback`` via
            # ``session.metadata["_active_parent_tool_use_id"]``).
            tool_results: list[dict[str, Any]] = []
            for tc in tool_calls:
                _emit_sub_tool_event(
                    "sub_tool_start",
                    role_id=call.role.id,
                    tool_call=tc,
                    iteration=round_i + 1,
                )
                # Also fire the caller-supplied event_emitter (bridge path).
                _args_preview = ""
                try:
                    import json as _json

                    _args_preview = _json.dumps(
                        getattr(tc, "input", {}) or {},
                        ensure_ascii=False,
                    )[:200]
                except (TypeError, ValueError):  # noqa: BLE001
                    _args_preview = repr(getattr(tc, "input", {}))[:200]
                _safe_ctx_emit(
                    _ctx_emitter,
                    {
                        "type": "sub_tool_start",
                        "agent_id": call.role.id,
                        "round": round_i + 1,
                        "skill": getattr(tc, "name", "") or "",
                        "tool_call_id": getattr(tc, "id", "") or "",
                        "args_preview": _args_preview,
                    },
                )
                _sub_tool_t0 = time.monotonic()
                if getattr(tc, "name", "") == "report" and report_session_id:
                    output, is_error = _handle_report_tool(
                        tc,
                        report_session_id,
                        delivery=report_delivery,
                    )
                else:
                    output, is_error = _execute_tool_in_subagent(
                        registry,
                        tc,
                    )
                _duration_ms = int((time.monotonic() - _sub_tool_t0) * 1000)
                _emit_sub_tool_event(
                    "sub_tool_end",
                    role_id=call.role.id,
                    tool_call=tc,
                    iteration=round_i + 1,
                    output=output,
                    is_error=is_error,
                    duration_ms=_duration_ms,
                )
                _safe_ctx_emit(
                    _ctx_emitter,
                    {
                        "type": "sub_tool_end",
                        "agent_id": call.role.id,
                        "round": round_i + 1,
                        "skill": getattr(tc, "name", "") or "",
                        "tool_call_id": getattr(tc, "id", "") or "",
                        "status": "failed" if is_error else "success",
                        "duration_ms": _duration_ms,
                        "output_preview": output[:1000],
                    },
                )
                block: dict[str, Any] = {
                    "type": "tool_result",
                    "tool_use_id": tc.id,
                    "content": output,
                }
                if is_error:
                    block["is_error"] = True
                tool_results.append(block)
            messages.append(
                Message(
                    role="user",
                    content=tool_results,
                )
            )

            # Convergence guard: consecutive rounds that only repeat
            # previously-seen tool calls (zero new signatures) are a loop,
            # not progress. Treat them as converged and return the partial
            # work instead of exhausting the round cap on a dead spin.
            new_signatures = [
                sig
                for sig in (_tool_call_signature(tc) for tc in tool_calls)
                if sig not in seen_tool_signatures
            ]
            if new_signatures:
                seen_tool_signatures.update(new_signatures)
                stall_rounds = 0
            elif tool_calls:
                stall_rounds += 1
                if stall_rounds >= EPHEMERAL_STALL_ROUNDS:
                    notice = (
                        "\n\n[已提前收敛:连续多轮重复相同工具调用且无新进展,"
                        "保留当前结果,停止继续探索]"
                    )
                    _emit_sub_text_delta(
                        call.role.id,
                        round_i + 1,
                        notice,
                        session_id=_ctx_session_id,
                        emitter=_ctx_emitter,
                    )
                    return accumulated_text + notice

        # Hit the round cap. Raise so the bridge can surface a real
        # failure (success=false + error) instead of returning a
        # placeholder string that callers misinterpret as success.
        raise EphemeralRoundCapExceeded(
            partial_text=accumulated_text,
            rounds=max_rounds,
            role_id=call.role.id,
        )

    return _runner


__all__ = [
    "EPHEMERAL_MAX_ROUNDS",
    "EPHEMERAL_MAX_ROUNDS_BY_ROLE",
    "EphemeralRoundCapExceeded",
    "_emit_subagent_lifecycle_event",
    "make_llm_ephemeral_runner",
]
