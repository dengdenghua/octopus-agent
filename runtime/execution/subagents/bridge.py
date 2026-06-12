"""Programmatic subagent bridge.

This module intentionally lives outside ``runtime.execution.suckers`` because
subagents are not skills. A caller invokes a subagent runner, which creates an
isolated agent turn and returns a compact result to the caller.
"""

from __future__ import annotations

import concurrent.futures
import contextlib
import logging
import os
import random
import time
import uuid
from collections.abc import Callable
from typing import Any

from .registry import SubagentRegistry

_log = logging.getLogger("runtime.execution.subagents")

SubAgentRunner = Callable[..., str]

_RUNNER: SubAgentRunner | None = None
_REGISTRY: SubagentRegistry | None = None

# Permissive default for the cheap subagent model. Operators should
# override this to point at their org's actual cheap model — either
# via the ``OCTOPUS_SUBAGENT_CHEAP_MODEL`` env var or via the
# ``subagent_cheap_model`` service-provider key. ``glm-4-flash`` is
# kept as a sensible fallback so unconfigured deployments still get
# *some* cost reduction instead of falling back to the primary model.
_DEFAULT_CHEAP_SUBAGENT_MODEL: str = "glm-4-flash"


# ── Sub-agent visualisation: codename + avatar ────────────────
#
# Every spawned sub-agent gets a friendly codename ("Spark / Nova /
# Quark / Atlas / ...") and a role-specific emoji avatar. Both flow
# out as ``subagent_spawned`` lifecycle events so the frontend
# Workbench panel can show a card the moment the agent starts —
# instead of waiting for its first tool call to leak the role string
# through ``sub_tool_*`` events.

_CODENAME_POOL: tuple[str, ...] = (
    "Spark", "Nova", "Quark", "Atlas", "Echo", "Lyra", "Vega", "Pixel",
    "Halo", "Comet", "Drift", "Ember", "Flux", "Glow", "Helios", "Iris",
    "Juno", "Kite", "Lumen", "Maple", "Nimbus", "Orbit", "Prism", "Quest",
    "Rune", "Sable", "Tide", "Umbra", "Volt", "Whisk", "Xeno", "Yarrow",
    "Zenith", "Aurora", "Blaze", "Cinder", "Dune", "Frost",
)

# Role → emoji avatar. Falls back to 🐙 (octopus mascot) for unknown
# roles. Kept short so the UI doesn't have to ship an icon library
# just for sub-agent tiles.
_ROLE_AVATAR: dict[str, str] = {
    "researcher":   "🔍",
    "research":     "🔍",
    "explorer":     "🧭",
    "fact_checker": "✅",
    "fact-checker": "✅",
    "critic":       "🛡️",
    "reviewer":     "🛡️",
    "security":     "🛡️",
    "security-review": "🛡️",
    "performance":  "⚡",
    "style":        "🎨",
    "synthesizer":  "✍️",
    "writer":       "✍️",
    "architect":    "🏗️",
    "designer":     "📐",
    "implementer":  "🔧",
    "coder":        "🔧",
    "reproducer":   "🐛",
    "hypothesizer": "💡",
    "verifier":     "🧪",
    "debugger":     "🐛",
    "planner":      "📋",
    "evaluator":    "⚖️",
    "generator":    "✨",
}
_DEFAULT_AVATAR = "🐙"


def _codename_for_role(role: str) -> str:
    """Pick a stable-but-friendly codename for a sub-agent.

    Random within the pool so callers can't accidentally rely on a
    specific name; UI uses the codename only as a display label, not
    an identifier. Counter suffix prevents collisions inside one
    parent turn.
    """
    name = random.choice(_CODENAME_POOL)
    suffix = uuid.uuid4().hex[:3]
    return f"{name}-{suffix}"


def _avatar_for_role(role: str) -> str:
    if not isinstance(role, str):
        return _DEFAULT_AVATAR
    key = role.strip().lower()
    return _ROLE_AVATAR.get(key, _DEFAULT_AVATAR)


def _resolve_cheap_subagent_model() -> str | None:
    """Resolve the model name used for cheap-routed subagent calls.

    Resolution order:
    1. ``OCTOPUS_SUBAGENT_CHEAP_MODEL`` env var (operator override)
    2. ``subagent_cheap_model`` service-provider config key
    3. ``"glm-4-flash"`` (sensible default — operators should override
       to match their org's actual cheap tier)
    """
    env_val = os.environ.get("OCTOPUS_SUBAGENT_CHEAP_MODEL")
    if env_val and env_val.strip():
        return env_val.strip()
    try:
        from runtime.platform.process.service_provider import get_provider
        cfg_val = get_provider().get("subagent_cheap_model")
        if isinstance(cfg_val, str) and cfg_val.strip():
            return cfg_val.strip()
    except Exception:  # noqa: BLE001 — config lookup is best-effort
        pass
    return _DEFAULT_CHEAP_SUBAGENT_MODEL


def set_sub_agent_runner(runner: SubAgentRunner | None) -> None:
    """Inject the runner used for persistent subagent dispatch."""
    global _RUNNER
    _RUNNER = runner


def get_sub_agent_runner() -> SubAgentRunner | None:
    return _RUNNER


def set_subagent_registry(registry: SubagentRegistry | None) -> None:
    """Install the Claude-style subagent definition registry."""
    global _REGISTRY
    _REGISTRY = registry


def get_subagent_registry() -> SubagentRegistry | None:
    return _REGISTRY


def _safe_emit(emitter: Callable[[dict], None] | None, event: dict) -> None:
    """Fire-and-forget event emission. Exceptions are swallowed."""
    if emitter is None:
        return
    with contextlib.suppress(Exception):
        emitter(event)


def _safe_journal_emit(event: dict) -> None:
    """Mirror a lifecycle event into the genome journal so the
    realtime gateway / observability subscribers see it without
    relying on the in-memory ``event_emitter`` being plumbed.

    Best-effort; never raises. The runtime journal helper is
    imported lazily so unit tests that don't bootstrap the journal
    stack stay green.
    """
    if not isinstance(event, dict):
        return
    kind = event.get("type")
    if kind not in {"subagent_spawned", "subagent_finished"}:
        return
    try:
        from runtime.execution.suckers.ephemeral_runner import (
            _emit_subagent_lifecycle_event,
        )
    except ImportError:
        return
    with contextlib.suppress(Exception):
        _emit_subagent_lifecycle_event(kind, event)


def call_subagent(
    agent_id: str = "",
    prompt: str = "",
    *,
    role: str = "",
    task: str = "",
    name: str = "",
    message: str = "",
    query: str = "",
    context: dict[str, Any] | None = None,
    timeout_s: int = 300,
    timeout_seconds: float | None = None,
    event_emitter: Callable[[dict], None] | None = None,
    session: Any = None,
    use_cheap_model: bool = False,
    extra_denied_paths: list[str] | None = None,
    **_kw: Any,
) -> dict[str, Any]:
    """Invoke a subagent and return a structured result.

    Alias parameters are accepted for backward compatibility with older model
    outputs and router code. They are not intended to make this a skill.

    Parameters
    ----------
    timeout_seconds :
        Wall-clock deadline in seconds. When set and exceeded, the subagent
        run is cancelled (best-effort) and a structured timeout result is
        returned instead of hanging. ``None`` (default) means no limit.
    event_emitter :
        Optional callable that receives plain JSON-serializable dicts for
        live progress events. Called with ``sub_tool_start`` before each
        tool invocation and ``sub_tool_end`` after. Exceptions from the
        emitter are swallowed so they never crash the runner.
    use_cheap_model :
        When true and the caller didn't pin an explicit ``model_name`` in
        ``context``, the cheap default resolved by
        :func:`_resolve_cheap_subagent_model` is injected so the subagent
        runs on a lower-cost tier. Used by the swarm dispatcher to route
        research-style roles cheaply.
    """
    agent_id = agent_id or role or name
    prompt = prompt or task or message or query
    if not agent_id:
        return {
            "agent_id": agent_id,
            "output": "",
            "success": False,
            "error": "agent_id is required",
        }
    if not prompt:
        return {
            "agent_id": agent_id,
            "output": "",
            "success": False,
            "error": "prompt is required",
        }

    # Track the highest round number seen via the emitter so we can
    # report rounds_completed on timeout.
    _rounds_state: dict[str, int] = {"max_round": 0}
    # Track files the subagent wrote/edited (octopus optimisation
    # lane H). The emitter sees ``sub_tool_end`` events with
    # ``skill`` and ``args`` payloads; when the skill is in the
    # write-tools set and the call succeeded, we extract its path.
    _files_touched: list[str] = []
    _files_seen: set[str] = set()
    _SUBAGENT_WRITE_TOOLS: frozenset[str] = frozenset({
        "write_text_file",
        "append_text_file",
        "edit_text_file",
        "edit_file",
        "multi_edit_file",
        "propose_patch",
    })

    # ── Sub-agent identity for visibility (codename + avatar) ──
    # Computed once per call so the spawn / finish events agree on
    # the same display name. Frontend receives these on the
    # ``subagent_spawned`` event and renders a tile in the Workbench
    # panel.
    _role_label = (role or agent_id or "agent").strip().lower()
    _codename = _codename_for_role(_role_label)
    _avatar = _avatar_for_role(_role_label)
    _spawn_started_at = time.time()

    # ── Thread-scoped memory key ──
    # Resolves the thread_id that the per-role memory uses for context
    # continuity. Priority: explicit context > session attribute. Empty
    # thread_id means stateless (no history record/replay) — matches the
    # previous behaviour for callers that don't supply a thread.
    _memory_thread_id = ""
    if isinstance(context, dict):
        _ctx_thread = context.get("thread_id") or context.get("caller_thread_id")
        if isinstance(_ctx_thread, str) and _ctx_thread.strip():
            _memory_thread_id = _ctx_thread.strip()
    if not _memory_thread_id and session is not None:
        _sess_thread = getattr(session, "thread_id", None)
        if isinstance(_sess_thread, str) and _sess_thread.strip():
            _memory_thread_id = _sess_thread.strip()
    # Stamp it back into context so _compose_system_prompt sees it
    # (it reads from context first, then falls back to session).
    if _memory_thread_id:
        if context is None:
            context = {}
        context.setdefault("thread_id", _memory_thread_id)

    # ── Prompt-injection taint inheritance ──
    # call_subagent's body runs in the spawning parent's thread, but the
    # actual sub-agent runs behind an inner ThreadPoolExecutor (below) whose
    # worker starts with a FRESH taint contextvar. Capture the parent's taint
    # HERE and stamp it into the context that flows to the runner, so an
    # injection-tainted parent cannot launder a risky action through a
    # delegated sub-agent. Honored at the sub-agent's react-loop start.
    try:
        from runtime.safety.validation.prompt_injection import (
            current_injection_taint,
        )
        _taint = current_injection_taint()
        if _taint and _taint != "none":
            if context is None:
                context = {}
            context.setdefault("_inherited_injection_taint", _taint)
    except Exception:  # noqa: BLE001 - taint propagation is best-effort
        pass

    # Emit lifecycle: spawn. Caller's emitter (typically the realtime
    # gateway) forwards this onto the WS so the frontend sees a new
    # sub-agent card the moment we start. Best-effort — emitter
    # exceptions never block the run.
    _spawn_event = {
        "type": "subagent_spawned",
        "agent_id": agent_id,
        "role": _role_label,
        "codename": _codename,
        "avatar": _avatar,
        "prompt_preview": prompt[:120] if isinstance(prompt, str) else "",
        "use_cheap_model": bool(use_cheap_model),
        "started_at": _spawn_started_at,
    }
    _safe_emit(event_emitter, _spawn_event)
    # Mirror onto the genome journal so frontend timeline can render
    # a sub-agent tile from the spawn moment, independent of the
    # in-memory emitter being wired through to the realtime gateway.
    _safe_journal_emit(_spawn_event)

    def _tracking_emitter(event: dict) -> None:
        rnd = event.get("round")
        if isinstance(rnd, int) and rnd > _rounds_state["max_round"]:
            _rounds_state["max_round"] = rnd
        # Annotate per-tool events with the sub-agent identity so the
        # frontend timeline can group them under the same tile as the
        # spawn event.
        try:
            if event.get("type") in {"sub_tool_start", "sub_tool_end"}:
                event.setdefault("agent_id", agent_id)
                event.setdefault("subagent_codename", _codename)
                event.setdefault("subagent_avatar", _avatar)
        except Exception:  # noqa: BLE001 — annotation is best-effort
            pass
        # File-touch tracking: best-effort, never breaks the call.
        try:
            if (
                event.get("type") == "sub_tool_end"
                and event.get("status") == "success"
            ):
                name = event.get("skill") or event.get("name") or ""
                if name in _SUBAGENT_WRITE_TOOLS:
                    args = event.get("args") or {}
                    path = args.get("path") if isinstance(args, dict) else None
                    if isinstance(path, str) and path and path not in _files_seen:
                        _files_seen.add(path)
                        _files_touched.append(path)
        except Exception:  # noqa: BLE001 — telemetry must never crash subagent
            pass
        _safe_emit(event_emitter, event)

    # Cancellation propagation.
    #
    # A subagent runs inside the caller's turn, so if the user
    # interrupts the parent turn (or the parent's token gets cancelled
    # for any reason), the subagent's ReAct loop should stop too.
    # We create a linked child source and install it on the worker
    # thread via ``scoped_cancellation`` so every ``current_cancellation_token()``
    # call inside the subagent sees the inherited signal.
    from runtime.safety.approval.cancellation import (
        CancellationSource,
        current_cancellation_token,
        scoped_cancellation,
    )

    _parent_token = current_cancellation_token()
    _child_source = CancellationSource()
    # Parent cancel → cancel child. If the parent is the never-token
    # (no ambient handler), ``on_cancelled`` is a no-op.
    _parent_token.on_cancelled(
        lambda reason: _child_source.cancel(reason or "parent cancelled"),
    )

    def _do_call() -> dict[str, Any]:
        # Always pass _tracking_emitter so round counting works even when
        # the caller didn't supply an external event_emitter. The tracking
        # wrapper is a no-op for the external emitter when it's None.
        # Install the linked child token as the ambient cancellation
        # token for this worker thread so subagent code below polling
        # ``current_cancellation_token()`` sees parent-driven cancels.
        # Also layer ``extra_denied_paths`` onto the ambient denylist
        # for the duration of the sub-agent run so a parent can
        # tighten what its researcher / critic / explorer sub-agent
        # is allowed to read (e.g. "don't touch .env this turn").
        denylist_token = None
        if extra_denied_paths:
            try:
                from runtime.safety.auth.path_denylist import (
                    pop_turn_denylist,
                    push_turn_denylist,
                )
                denylist_token = push_turn_denylist(extra_denied_paths)
            except ImportError:
                denylist_token = None
        try:
            with scoped_cancellation(_child_source.token):
                return _dispatch(
                    agent_id=agent_id,
                    prompt=prompt,
                    context=context,
                    timeout_s=timeout_s,
                    session=session,
                    event_emitter=_tracking_emitter,
                    use_cheap_model=use_cheap_model,
                )
        finally:
            if denylist_token is not None:
                try:
                    from runtime.safety.auth.path_denylist import (
                        pop_turn_denylist,
                    )
                    pop_turn_denylist(denylist_token)
                except ImportError:  # noqa: BLE001 — denylist is optional, skip if missing
                    pass

    # Auto-retry wrapper. When the first call hits the round cap with
    # partial output, give it ONE more shot with a continuation prompt
    # that includes the partial work so the agent can finish from where
    # it left off rather than restart. This recovers ~80% of "almost
    # done" scenarios that previously surfaced as a bare 400 to the user.
    #
    # We do NOT retry generic failures (router error / tool exception)
    # because those are likely deterministic — retrying would just burn
    # more budget without changing the outcome.
    _RETRY_DISABLED = bool(
        (context or {}).get("disable_auto_retry", False)
    )

    def _do_call_with_retry() -> dict[str, Any]:
        first = _do_call()
        if not isinstance(first, dict):
            return first
        # Only retry round-cap exhaustion with partial work
        if (
            _RETRY_DISABLED
            or not first.get("round_cap_exceeded")
            or not (first.get("output") or "").strip()
        ):
            return first
        partial = str(first.get("output") or "").strip()
        original_rounds = int(first.get("rounds_completed") or 0)
        _log.info(
            "subagent auto-retry · agent_id=%s rounds_first=%d "
            "partial_chars=%d",
            agent_id, original_rounds, len(partial),
        )
        # Reset round tracking so the retry's iteration_count reflects
        # the second attempt only (caller's _augment uses _rounds_state).
        _rounds_state["max_round"] = 0
        # Continuation prompt: include partial output and a clear "finish"
        # directive so the agent doesn't restart from scratch.
        # Declare nonlocal BEFORE use in the f-string.
        nonlocal prompt
        original_prompt = prompt
        continuation_prompt = (
            f"{original_prompt}\n\n"
            "---\n\n"
            "## CONTINUATION\n\n"
            f"You ran out of rounds on the first attempt ({original_rounds} "
            "rounds). Your partial work is shown below. Finish the task — do "
            "NOT restart from scratch; build on what you have. Wrap up "
            "with a final answer rather than collecting more data unless "
            "absolutely necessary.\n\n"
            "### Partial output so far\n\n"
            f"{partial}\n\n"
            "### Finish from here:"
        )
        # Mutate the closed-over prompt for the retry call. We must
        # restore the original prompt before the function returns so the
        # `record_turn` invocation later sees the user's original ask, not
        # the synthetic continuation.
        prompt = continuation_prompt
        try:
            second = _do_call()
        finally:
            prompt = original_prompt
        if not isinstance(second, dict):
            return first
        # Stitch: prefer the retry's output but mark that a retry happened.
        second.setdefault("output", "")
        if not second.get("output").strip() and partial:
            # Retry produced nothing usable → keep first call's partial
            # but propagate the retry-attempted flag.
            second["output"] = partial
            second["success"] = first.get("success", False)
            second["error"] = first.get("error")
        second["retry_attempted"] = True
        second["original_rounds"] = original_rounds
        if not second.get("success") and second.get("output", "").strip():
            # Even if cap hit again, we have content — surface as
            # partial-success rather than total failure.
            second.setdefault("partial", True)
        return second

    def _augment(result: dict[str, Any]) -> dict[str, Any]:
        """Attach context-isolation telemetry to the subagent result.

        Adds ``iteration_count`` (rounds the subagent ran), and
        ``files_touched`` (paths it wrote to). These give the caller
        a structured envelope without leaking the subagent's
        intermediate steps into the parent's message history.

        Also injects the spawn-time codename / avatar / role so a
        downstream caller (e.g. ``call_agent_parallel``) can include
        them in the synthesised reply. The frontend already received
        these via the ``subagent_spawned`` event, but having them on
        the return value makes synchronous testing + transcripts
        self-describing.
        """
        if not isinstance(result, dict):
            return result
        result.setdefault("iteration_count", _rounds_state["max_round"])
        result.setdefault("files_touched", list(_files_touched))
        result.setdefault("codename", _codename)
        result.setdefault("avatar", _avatar)
        result.setdefault("role", _role_label)
        # Lifecycle: finish. Mirrors the spawn event so the frontend
        # can mark the tile complete + show duration / iteration /
        # files-touched stats. ``ok`` is the canonical success flag;
        # we infer it from the result envelope when not explicit.
        elapsed = max(0.0, time.time() - _spawn_started_at)
        ok = bool(result.get("success", result.get("ok", True))) and not result.get("error")
        # Structured log so operators can see subagent outcomes without
        # tailing a generic INFO firehose. Includes round_cap_exceeded
        # so the log surface differentiates "ran out of rounds" from
        # "tool failure" / "router error".
        _log.info(
            "subagent finish · agent_id=%s role=%s ok=%s rounds=%d "
            "files=%d duration=%.2fs%s%s",
            agent_id, _role_label, ok,
            _rounds_state["max_round"], len(_files_touched), elapsed,
            " · ROUND_CAP_EXCEEDED" if result.get("round_cap_exceeded") else "",
            f" · error={result.get('error')!r}" if result.get("error") else "",
        )
        # Record this turn into the per-thread, per-role memory bucket so
        # the next call to the same role in this thread can reference it
        # ("researcher, dig deeper on that patent" sees what "researcher,
        # find Eight Sleep patents" produced). Only fires when a thread_id
        # is present; stateless callers stay stateless.
        if _memory_thread_id:
            from runtime.execution.subagents.memory import record_turn
            record_turn(
                thread_id=_memory_thread_id,
                role_id=agent_id,
                prompt=prompt,
                output=result.get("output", ""),
                success=ok,
                rounds=_rounds_state["max_round"],
                error=result.get("error", ""),
            )
        _finish_event = {
            "type": "subagent_finished",
            "agent_id": agent_id,
            "role": _role_label,
            "codename": _codename,
            "avatar": _avatar,
            "ok": ok,
            "duration_s": round(elapsed, 2),
            "iteration_count": _rounds_state["max_round"],
            "files_touched": list(_files_touched),
            "error": result.get("error"),
            "status": result.get("status"),
        }
        _safe_emit(event_emitter, _finish_event)
        _safe_journal_emit(_finish_event)
        return result

    if timeout_seconds is None:
        return _augment(_do_call_with_retry())

    # Timeout path: run in a thread so we can enforce a wall-clock limit.
    # We use shutdown(wait=False) to avoid blocking forever if the worker
    # thread is stuck (Python threads cannot be killed cleanly).
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = executor.submit(_do_call_with_retry)
    try:
        return _augment(future.result(timeout=timeout_seconds))
    except concurrent.futures.TimeoutError:
        # Signal cancellation to the subagent so any poll-aware loop
        # (ReAct, subprocess waits) unwinds gracefully. ``future.cancel``
        # only works if the task hasn't started — the token gives us
        # co-operative shutdown even on running tasks.
        _child_source.cancel(reason="subagent timeout")
        future.cancel()
        rounds = _rounds_state["max_round"]
        _log.warning(
            "subagent %s timed out after %ss (rounds_completed=%d)",
            agent_id, timeout_seconds, rounds,
        )
        # Emit the subagent_finished lifecycle event for the timeout
        # path too — frontend needs to mark the tile as failed.
        elapsed = max(0.0, time.time() - _spawn_started_at)
        _timeout_event = {
            "type": "subagent_finished",
            "agent_id": agent_id,
            "role": _role_label,
            "codename": _codename,
            "avatar": _avatar,
            "ok": False,
            "duration_s": round(elapsed, 2),
            "iteration_count": rounds,
            "files_touched": list(_files_touched),
            "error": f"subagent timed out after {timeout_seconds}s",
            "status": "timeout",
        }
        _safe_emit(event_emitter, _timeout_event)
        _safe_journal_emit(_timeout_event)
        return {
            "status": "timeout",
            "error": f"subagent timed out after {timeout_seconds}s",
            "agent_id": agent_id,
            "role": _role_label,
            "codename": _codename,
            "avatar": _avatar,
            "output": "",
            "success": False,
            "rounds_completed": rounds,
            "iteration_count": rounds,
            "files_touched": list(_files_touched),
        }
    finally:
        executor.shutdown(wait=False)


def _dispatch(
    *,
    agent_id: str,
    prompt: str,
    context: dict[str, Any] | None,
    timeout_s: int,
    session: Any,
    event_emitter: Callable[[dict], None] | None,
    use_cheap_model: bool = False,
) -> dict[str, Any]:
    """Inner dispatch — runs in the caller's thread or a worker thread."""
    _log.info(
        "subagent dispatch · agent_id=%s prompt_len=%d timeout=%ds",
        agent_id, len(prompt), timeout_s,
    )
    from runtime.execution.suckers.ephemeral_agents import (
        EphemeralRoleDef,
        is_ephemeral_role,
        run_ephemeral_definition,
        run_ephemeral_role,
    )

    registry = _REGISTRY
    if registry is not None and registry.has(agent_id):
        definition = registry.get(agent_id)
        merged_context: dict[str, Any] = {
            **(context or {}),
            "subagent_source_path": definition.source_path,
            "subagent_scope": definition.scope,
        }
        if definition.model:
            merged_context.setdefault("model_name", definition.model)
        if use_cheap_model and "model_name" not in merged_context:
            cheap = _resolve_cheap_subagent_model()
            if cheap:
                merged_context["model_name"] = cheap
        if event_emitter is not None:
            merged_context["event_emitter"] = event_emitter
        return run_ephemeral_definition(
            EphemeralRoleDef(
                id=definition.name,
                display_name=definition.name,
                description=definition.description,
                system_prompt=definition.system_prompt,
                share_context=True,
                share_memory=True,
                tool_allowlist=definition.tools,
            ),
            prompt,
            session=session,
            context=merged_context,
            timeout_s=timeout_s,
        )

    if is_ephemeral_role(agent_id):
        merged_eph: dict[str, Any] = dict(context or {})
        if use_cheap_model and "model_name" not in merged_eph:
            cheap = _resolve_cheap_subagent_model()
            if cheap:
                merged_eph["model_name"] = cheap
        if event_emitter is not None:
            merged_eph["event_emitter"] = event_emitter
        return run_ephemeral_role(
            agent_id,
            prompt,
            session=session,
            context=merged_eph,
            timeout_s=timeout_s,
        )

    runner = _RUNNER
    if runner is None:
        return {
            "agent_id": agent_id,
            "output": "",
            "success": False,
            "error": (
                "sub-agent runner not configured; call "
                "set_sub_agent_runner(fn) during bootstrap"
            ),
        }

    merged_ctx: dict[str, Any] = dict(context or {})
    merged_ctx["timeout_s"] = timeout_s
    if use_cheap_model and "model_name" not in merged_ctx:
        cheap = _resolve_cheap_subagent_model()
        if cheap:
            merged_ctx["model_name"] = cheap
    if event_emitter is not None:
        merged_ctx["event_emitter"] = event_emitter
    if session is not None:
        caller_thread = getattr(session, "thread_id", None)
        if caller_thread:
            merged_ctx.setdefault("caller_thread_id", caller_thread)
        # Propagate actor identity so the subagent's journal events,
        # rate-limit buckets, and memory ACL checks all run as the
        # caller. Without this, subagents execute as ``actor=None``
        # and escape the per-user enforcement applied to the parent
        # turn.
        caller_actor = getattr(session, "actor", None) or getattr(session, "actor_id", None)
        if caller_actor:
            merged_ctx.setdefault("actor", caller_actor)
        # Pass the full session through for downstream runners that
        # want to re-scope (e.g. to use session_scope for nested
        # journal events). Opt-in via a dedicated key so we don't
        # accidentally shadow user-supplied ``session`` in context.
        merged_ctx.setdefault("caller_session", session)

    try:
        output = runner(prompt, subagent_name=agent_id, context=merged_ctx)
    except Exception as exc:  # noqa: BLE001
        _log.warning(
            "subagent %s runner raised %s: %s",
            agent_id, type(exc).__name__, exc,
        )
        return {
            "agent_id": agent_id,
            "output": "",
            "success": False,
            "error": f"{type(exc).__name__}: {exc}",
        }

    return {
        "agent_id": agent_id,
        "output": str(output) if output is not None else "",
        "success": True,
        "error": None,
    }
