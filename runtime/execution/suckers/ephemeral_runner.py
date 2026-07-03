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

import contextlib
import logging
import time
from collections.abc import Callable
from typing import Any

from runtime.execution.suckers.ephemeral_injection_gate import (
    ephemeral_injection_taint_block,
    mark_inherited_ephemeral_taint,
    scan_and_escalate_ephemeral_taint,
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
            stream_fn_single = getattr(router, "call_stream", None)
            if callable(stream_fn_single):
                accumulated = ""
                try:
                    for event in stream_fn_single(req):
                        if event.type == "text_delta":
                            chunk = event.delta or ""
                            if chunk:
                                accumulated += chunk
                                _safe_ctx_emit(
                                    _ctx_emitter_single,
                                    {
                                        "type": "sub_text_delta",
                                        "agent_id": call.role.id,
                                        "round": 1,
                                        "delta": chunk,
                                    },
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

        # Pull the optional event_emitter injected by the bridge.
        # It's a plain Callable[[dict], None] — fire-and-forget.
        _ctx_emitter = call.context.get("event_emitter") if call.context else None

        # Role-specific round cap (align with Claude Code depth for research tasks)
        max_rounds = EPHEMERAL_MAX_ROUNDS_BY_ROLE.get(call.role.id, EPHEMERAL_MAX_ROUNDS)

        messages: list[Any] = [
            Message(role="system", content=call.composed_system_prompt),
            Message(role="user", content=call.user_prompt),
        ]
        accumulated_text = ""
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
                    return accumulated_text or ""
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
                                # ``text_delta``.
                                _safe_ctx_emit(
                                    _ctx_emitter,
                                    {
                                        "type": "sub_text_delta",
                                        "agent_id": call.role.id,
                                        "round": round_i + 1,
                                        "delta": chunk,
                                    },
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
                    return accumulated_text + text or accumulated_text

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
                    _safe_ctx_emit(
                        _ctx_emitter,
                        {
                            "type": "sub_text_delta",
                            "agent_id": call.role.id,
                            "round": round_i + 1,
                            "delta": notice,
                        },
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

        # Hit the round cap. Raise so the bridge can surface a real
        # failure (success=false + error) instead of returning a
        # placeholder string that callers misinterpret as success.
        raise EphemeralRoundCapExceeded(
            partial_text=accumulated_text,
            rounds=max_rounds,
            role_id=call.role.id,
        )

    return _runner


def _safe_ctx_emit(emitter: Any, event: dict) -> None:
    """Fire-and-forget call to a caller-supplied event emitter.

    Silently no-ops when ``emitter`` is ``None`` or raises. The runner
    must never crash because of a buggy emitter callback.
    """
    if emitter is None:
        return
    with contextlib.suppress(Exception):
        emitter(event)


def _emit_sub_tool_event(
    kind: str,
    *,
    role_id: str,
    tool_call: Any,
    iteration: int,
    output: str | None = None,
    is_error: bool = False,
    duration_ms: int | None = None,
) -> None:
    """Best-effort push of a sub-agent tool event to the active stream
    queue so the frontend LiveToolTimeline can nest it under the
    parent's ``call_agent_parallel`` / ``call_agent`` tool_use row.

    Wiring:
        * ``tool_bridge.stream_agentic_fallback`` stashes the stream
          queue on ``session.metadata["sub_tool_event_queue"]``
          AND the currently-running parent tool_use id on
          ``session.metadata["_active_parent_tool_use_id"]`` before
          invoking each handler.
        * Inside the sub-agent handler → ephemeral runner → here:
          we look up both and push a ``(kind, payload, None)`` tuple.
        * The active realtime bridge drains the tuple and emits the
          corresponding tool event.

    Silently no-ops when:
        * No session is bound (unit tests calling the runner directly)
        * No queue was stashed (older bootstrap paths)
        * Queue put fails (full / closed)

    The sub-agent keeps running regardless · losing telemetry beats
    deadlocking the worker thread.
    """
    try:
        from runtime.platform.process.session import current_session

        sess = current_session()
    except (ImportError, TypeError, AttributeError, OSError):  # noqa: BLE001
        return
    if sess is None:
        return
    meta = getattr(sess, "metadata", None) or {}
    if not isinstance(meta, dict):
        return
    q = meta.get("sub_tool_event_queue")
    parent_id = meta.get("_active_parent_tool_use_id") or ""
    payload: dict[str, Any] = {
        "id": getattr(tool_call, "id", "") or "",
        "name": getattr(tool_call, "name", "") or "",
        "input": getattr(tool_call, "input", {}) or {},
        "iteration": iteration,
        "parent_tool_use_id": parent_id,
        "sub_agent_role": role_id,
    }
    if kind == "sub_tool_end":
        # Truncate output preview · same 200-char cap as parent
        # loop's tool_end event so the SSE frame stays small.
        if output is not None:
            payload["output"] = str(output)[:200]
        payload["is_error"] = bool(is_error)
        payload["status"] = "error" if is_error else "success"
        if duration_ms is not None:
            payload["duration_ms"] = int(duration_ms)
    if q is not None:
        with contextlib.suppress(Exception):
            q.put_nowait((kind, payload, None))

    # ── Mirror to journal as well ───────────────────────────
    # The above queue path requires the SSE pump to have stashed a
    # queue in session.metadata — which only the agentic-fallback
    # code path does. Most production turns route through the
    # OpenAI-gateway worker which subscribes to the journal
    # instead. Writing a JournalEvent here surfaces sub-tool
    # progress on BOTH paths uniformly.
    journal = meta.get("journal")
    if journal is None:
        try:
            stack = meta.get("stack")
            if stack is not None:
                journal = getattr(stack, "journal", None)
        except (AttributeError, TypeError):  # noqa: BLE001
            journal = None
    if journal is None:
        return
    try:
        from runtime.memory.journal import (
            SubToolEndEvent,
            SubToolStartEvent,
        )

        task_id_obj = meta.get("task_id")
        if kind == "sub_tool_start":
            ev = SubToolStartEvent(
                task_id=task_id_obj,
                role_id=role_id,
                tool_call_id=str(getattr(tool_call, "id", "") or ""),
                tool_name=str(getattr(tool_call, "name", "") or ""),
                iteration=int(iteration),
                args_preview=str(payload.get("input") or "")[:200],
                parent_tool_use_id=parent_id or None,
            )
        else:
            ev = SubToolEndEvent(
                task_id=task_id_obj,
                role_id=role_id,
                tool_call_id=str(getattr(tool_call, "id", "") or ""),
                tool_name=str(getattr(tool_call, "name", "") or ""),
                iteration=int(iteration),
                is_error=bool(is_error),
                duration_ms=int(duration_ms or 0),
                output_preview=(output or "")[:200] if output else "",
                parent_tool_use_id=parent_id or None,
            )
        journal.write(ev)
    except (OSError, TypeError, ValueError):  # noqa: BLE001
        # Mirroring is best-effort; never break the runner.
        pass


def _emit_subagent_lifecycle_event(
    kind: str,
    payload: dict[str, Any] | None,
) -> None:
    """Best-effort push of a sub-agent lifecycle event to the genome
    journal so the realtime gateway / observability panel can render
    a sub-agent tile from the moment the agent spawns instead of
    waiting for its first ``sub_tool_*`` event.

    ``kind`` is ``"subagent_spawned"`` or ``"subagent_finished"``.
    ``payload`` mirrors the dict the bridge fires through its
    ``event_emitter`` (codename, avatar, role, prompt_preview, ok,
    duration_s, iteration_count, files_touched, error, status).

    Convention
    ----------
    Reuses the existing ``SubToolStartEvent`` / ``SubToolEndEvent``
    journal-event shape — same wire used by ``_emit_sub_tool_event``
    above — but stamps the ``tool_name`` with one of the
    ``ItemMarker`` magic strings (``__subagent_spawned__`` /
    ``__subagent_finished__``). Subscribers that don't care about
    lifecycle simply ignore the marker; the realtime gateway uses it
    to synthesise an ``McpToolCallItem`` the frontend's
    ``mcpItemToLiveEvent`` recognises and renders as a lifecycle tile.

    Silently no-ops when no session / journal is bound, so unit tests
    calling the bridge directly stay green. Empty / malformed
    payloads are tolerated — the helper coerces missing fields to
    safe defaults rather than raising.
    """
    import json as _json

    from runtime.protocol.items import ItemMarker

    payload = payload or {}
    try:
        from runtime.platform.process.session import current_session

        sess = current_session()
    except (ImportError, TypeError, AttributeError, OSError):  # noqa: BLE001
        return
    if sess is None:
        return
    meta = getattr(sess, "metadata", None) or {}
    if not isinstance(meta, dict):
        return
    journal = meta.get("journal")
    if journal is None:
        try:
            stack = meta.get("stack")
            if stack is not None:
                journal = getattr(stack, "journal", None)
        except (AttributeError, TypeError):  # noqa: BLE001
            journal = None
    if journal is None:
        return

    role_id = str(payload.get("role") or payload.get("agent_id") or "")
    parent_id = meta.get("_active_parent_tool_use_id") or None
    task_id_obj = meta.get("task_id")
    try:
        args_preview = _json.dumps(
            {
                "codename": payload.get("codename"),
                "avatar": payload.get("avatar"),
                "role": payload.get("role"),
                "agent_id": payload.get("agent_id"),
                "prompt_preview": payload.get("prompt_preview"),
                "use_cheap_model": payload.get("use_cheap_model"),
                "started_at": payload.get("started_at"),
            },
            ensure_ascii=False,
            default=str,
        )[:1000]
    except (TypeError, ValueError):
        args_preview = ""

    try:
        from runtime.memory.journal import (
            SubToolEndEvent,
            SubToolStartEvent,
        )

        if kind == "subagent_spawned":
            ev = SubToolStartEvent(
                task_id=task_id_obj,
                role_id=role_id,
                tool_call_id=str(payload.get("agent_id") or ""),
                tool_name=ItemMarker.SUBAGENT_SPAWNED.value,
                iteration=0,
                args_preview=args_preview,
                parent_tool_use_id=parent_id,
            )
        elif kind == "subagent_finished":
            try:
                output_preview = _json.dumps(
                    {
                        "codename": payload.get("codename"),
                        "avatar": payload.get("avatar"),
                        "role": payload.get("role"),
                        "agent_id": payload.get("agent_id"),
                        "ok": payload.get("ok"),
                        "duration_s": payload.get("duration_s"),
                        "iteration_count": payload.get("iteration_count"),
                        "files_touched": payload.get("files_touched"),
                        "error": payload.get("error"),
                        "status": payload.get("status"),
                    },
                    ensure_ascii=False,
                    default=str,
                )[:1000]
            except (TypeError, ValueError):
                output_preview = ""
            ok = bool(payload.get("ok", True))
            duration_s = payload.get("duration_s") or 0
            try:
                duration_ms = int(float(duration_s) * 1000)
            except (TypeError, ValueError):
                duration_ms = 0
            ev = SubToolEndEvent(
                task_id=task_id_obj,
                role_id=role_id,
                tool_call_id=str(payload.get("agent_id") or ""),
                tool_name=ItemMarker.SUBAGENT_FINISHED.value,
                iteration=int(payload.get("iteration_count") or 0),
                is_error=not ok,
                duration_ms=duration_ms,
                output_preview=output_preview,
                parent_tool_use_id=parent_id,
            )
        else:
            return
        journal.write(ev)
    except (OSError, TypeError, ValueError):  # noqa: BLE001
        # Lifecycle mirroring is best-effort; never break the run.
        pass


def _ephemeral_write_confine_block(call: Any, skill: Any) -> str | None:
    """Confine a sub-agent's file writes to a locked worktree.

    Ephemeral runs bypass the executor's sandbox-arg injector, so a write skill
    would otherwise run with ``sandbox_dir=None`` (no confinement → it can write
    anywhere, verified live). When the Session pins ``_locked_write_root`` (set
    by ``call_subagent(workspace_path=...)``), we replicate the injector here:
    inject the locked root as ``sandbox_dir`` so the skill's own ``check_path``
    confines relative writes into the worktree and blocks escapes. A write skill
    that can't take a sandbox_dir is blocked (fail-closed) rather than allowed to
    escape. Returns a block message, or None to proceed.
    """
    from runtime.platform.process.session import current_session

    meta = getattr(current_session(), "metadata", None) or {}
    locked = meta.get("_locked_write_root")
    if not locked:
        return None
    name = (getattr(call, "name", "") or "").lower()
    affinity = [str(a).lower() for a in (getattr(skill, "affinity", None) or [])]
    is_write = any(tok in name for tok in ("write", "edit", "patch", "create", "append")) or any(
        a in ("write", "edit", "filesystem", "file-write") for a in affinity
    )
    if not is_write:
        return None
    try:
        import inspect

        params = inspect.signature(skill.handler).parameters
    except (TypeError, ValueError):
        params = {}
    if "sandbox_dir" not in params:
        return (
            f"(blocked: '{getattr(call, 'name', '?')}' can't be confined to the "
            f"locked worktree — refusing to write unsandboxed)"
        )
    if isinstance(getattr(call, "input", None), dict) and not call.input.get("sandbox_dir"):
        call.input["sandbox_dir"] = str(locked)
    return None


def _execute_tool_in_subagent(
    registry: Any,
    call: Any,
) -> tuple[str, bool]:
    """Run one tool_use call inside an ephemeral sub-agent.

    Mirrors the simpler shape of ``tool_bridge._execute_tool_call``
    but doesn't go through ``stack.executor`` — sub-agents already
    inherit the parent's Session via ContextVar, and we want their
    skill calls to see the SHARED ``current_session()`` so blackboard
    + memory skills resolve to the parent's turn_id / agent. Going
    through executor would re-set Session and break this.

    Returns ``(output_text, is_error)``.
    """
    import json

    try:
        if not registry.has(call.name):
            return (f"(skill not found: {call.name})", True)
        skill = registry.get(call.name)
    except Exception as exc:  # noqa: BLE001
        return (f"(registry error: {exc})", True)

    # Injection-taint gate — ephemeral runs bypass the executor chokepoint, so
    # enforce here, fail-closed (block, since there's no approval channel).
    _taint_block = ephemeral_injection_taint_block(call, call.name)
    if _taint_block is not None:
        return (_taint_block, True)

    _confine_block = _ephemeral_write_confine_block(call, skill)
    if _confine_block is not None:
        return (_confine_block, True)

    # Direct-dispatch hardening — ephemeral runs bypass the executor
    # chokepoint, so apply the same pre-execution safety gates here (SEC-1/2).
    if isinstance(getattr(call, "input", None), dict):
        from runtime.execution.tool_engine.skill_gate import gate_inner_dispatch
        from runtime.safety.auth import MODEL_FORBIDDEN_ARGS

        # Drop model-controllable privilege flags (allow_sensitive /
        # allow_private) the model must never set — same as the executor.
        # ``call`` is a frozen model, so mutate the input dict in place rather
        # than rebinding the attribute (cf. the sandbox_dir injection above).
        for _forbidden in MODEL_FORBIDDEN_ARGS:
            call.input.pop(_forbidden, None)
        # Capability denylist + immunity (when a TrustEngine is ambiently
        # bound) + credential-file denylist (check_file_write). Without these
        # an unsandboxed sub-agent could write ./.env / ./id_rsa, or run an
        # operator-disabled tool — the executor blocks both. Reuse the shared
        # primitive the other direct-dispatch points already use so this path
        # stays in lock-step with the executor instead of re-implementing gates.
        _gate = gate_inner_dispatch(skill, call.input, caller="ephemeral_subagent")
        if _gate is not None:
            return (f"(blocked: {_gate.message})", True)

    try:
        output = skill.handler(**call.input)
    except TypeError as exc:
        return (f"(TypeError: {exc})", True)
    except Exception as exc:  # noqa: BLE001
        return (f"(skill error: {type(exc).__name__}: {exc})", True)

    if isinstance(output, str):
        rendered = output
    else:
        try:
            rendered = json.dumps(output, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            rendered = repr(output)

    # If this tool ingested untrusted content carrying injection markers,
    # escalate the turn taint so a LATER risky tool in the same ephemeral run
    # is gated too — mirrors the executor chokepoint's post-success scan.
    scan_and_escalate_ephemeral_taint(
        call.name,
        getattr(skill, "affinity", None),
        rendered,
    )
    # Same 4kB cap as parent agentic loop · keeps sub-agent context
    # from blowing up on a single huge tool result (e.g. a full-page
    # web_search output).
    if len(rendered) > 4000:
        rendered = rendered[:4000] + f"\n\n...(truncated, {len(rendered) - 4000} more chars)"
    return (rendered, False)


__all__ = [
    "EPHEMERAL_MAX_ROUNDS",
    "EPHEMERAL_MAX_ROUNDS_BY_ROLE",
    "EphemeralRoundCapExceeded",
    "_emit_subagent_lifecycle_event",
    "make_llm_ephemeral_runner",
]
