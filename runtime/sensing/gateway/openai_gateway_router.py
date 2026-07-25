from __future__ import annotations

import logging
import time
from typing import Any
from uuid import uuid4

from runtime.memory.journal import journal_context

from .openai_gateway.context_manager import (
    _conversation_messages_payload,
    _extract_goal,
    _interaction_profile_prompt,
    _normalize_conversation_messages,
    _profile_memories_payload,
    _render_conversation_history,
    _runtime_soul_for_agent,
)
from .openai_gateway.mix import (
    is_mix_model,
    mix_model_ids,
    mix_sse_frames,
    run_mix_chat,
)
from .openai_gateway.request_parser import _resolve_actor
from .openai_gateway.response_formatter import (
    _assistant_text_from_trajectory,
    _format_research_report_fallback,
    _is_research_report_context,
    _looks_like_complete_research_report,
)
from .openai_gateway.stream_handler import (
    _commit_direct_llm_cost,
    _direct_llm_fallback,
    _reflex_stream_frames,
    _stream_chat_wrapped,
)

try:
    from fastapi import APIRouter, HTTPException, Request
    from fastapi.responses import StreamingResponse

    FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover
    FASTAPI_AVAILABLE = False
    APIRouter = None  # type: ignore[assignment]
    Request = None  # type: ignore[assignment]

from runtime.platform.models import (
    ArmId,
    Budget,
    BudgetLimits,
    ParsedIntent,
)
from runtime.sensing._fastapi_guard import require_fastapi

# Re-export formatting helpers from openai_formatting.py so call
# sites inside this file stay unchanged. The public API of that
# module uses the non-underscored names.
from .openai_formatting import (  # noqa: E402,I001
    _pick_output_keys,  # noqa: F401
    _pick_preview_keys,  # noqa: F401
    _short,  # noqa: F401
)
from .openai_formatting import (
    chat_completion_envelope as _chat_completion_envelope,
)
from .openai_formatting import (
    summarize_step_for_stream as _summarize_step_for_stream,
)


def _reasoning_effort_from_body(body: dict[str, Any]) -> str | None:
    from runtime.sensing.model_router.models import normalize_reasoning_effort

    candidates: list[Any] = [body.get("reasoning_effort"), body.get("effort")]
    reasoning = body.get("reasoning")
    if isinstance(reasoning, dict):
        candidates.append(reasoning.get("effort"))
    context = body.get("context")
    if isinstance(context, dict):
        candidates.append(context.get("reasoning_effort"))
    for candidate in candidates:
        normalized = normalize_reasoning_effort(candidate)
        if normalized:
            return normalized
    return None


def _deep_requested(body: dict[str, Any]) -> bool:
    """Whether the caller explicitly asked for the deep agentic path.

    Trivial inputs otherwise short-circuit through the reflex fast-path and
    never produce a task_id / trace. Setting ``deep`` (or ``execution=deep``,
    or ``context.deep``) forces planner+runtime so the run is verifiable +
    replayable — the contract enterprise relies on to surface a trust trace.
    """
    if bool(body.get("deep")):
        return True
    if str(body.get("execution") or "").lower() == "deep":
        return True
    ctx = body.get("context")
    return bool(isinstance(ctx, dict) and ctx.get("deep"))


def _evict_idle_rate_buckets(
    windows: dict[str, Any],
    semaphores: dict[str, Any],
    cutoff: float,
) -> int:
    """Drop per-actor rate-limit buckets whose sliding window has emptied
    out — no call newer than ``cutoff`` (a monotonic timestamp). Mutates
    both dicts in place and returns the number of buckets evicted.

    Module-level and pure so the eviction invariant (empty windows go,
    active ones stay, the paired semaphore is dropped alongside) is
    unit-testable without standing up the whole gateway router.
    """
    stale: list[str] = []
    for key, window in windows.items():
        while window and window[0] < cutoff:
            window.popleft()
        if not window:
            stale.append(key)
    for key in stale:
        windows.pop(key, None)
        semaphores.pop(key, None)
    return len(stale)


def create_openai_router(
    stack: Any,
    *,
    default_arm: str = "code_arm",
    reflex_router: Any = None,
    prompt_optimizer: Any = None,
    identity_store: Any = None,
    require_auth: bool = False,
    jwt_secret: str | None = None,
    jwt_issuer: str | None = None,
    jwt_audience: str | None = None,
    jwt_leeway_seconds: int = 0,
    agent_registry: Any = None,
    max_concurrent_completions_per_actor: int = 4,
    max_completions_per_minute_per_actor: int = 30,
) -> Any:
    require_fastapi(__name__)

    router = APIRouter()

    # ── Per-actor rate limiting ──────────────────────────────
    #
    # /v1/chat/completions runs a planner + LLM round-trip per call.
    # A small bot can burn quota fast. Limit (a) concurrent in-flight
    # completions per actor (semaphore) and (b) calls/minute per actor
    # (sliding window). Anonymous callers (require_auth=False) are all
    # bucketed under a single shared key — they collectively can't
    # exceed one actor's allotment.
    import threading as _threading
    import time as _rl_time
    from collections import deque as _rl_deque

    _completion_semaphores: dict[str, _threading.Semaphore] = {}
    _completion_call_windows: dict[str, _rl_deque[float]] = {}
    _rate_limit_lock = _threading.Lock()
    _CONCURRENT_LIMIT = max(1, int(max_concurrent_completions_per_actor))  # noqa: N806
    _PER_MIN_LIMIT = max(1, int(max_completions_per_minute_per_actor))  # noqa: N806
    # Without this, one bucket per distinct anon:<ip> key accumulates
    # forever — an attacker rotating source IPs would grow both dicts
    # unbounded. Prune buckets whose sliding window has gone empty (no
    # calls in the last 60s). Amortized: swept at most once per interval
    # (or when we blow past a hard cap) so it never becomes O(buckets)
    # per request under a rotating-IP flood.
    _MAX_RATE_BUCKETS = 4096  # noqa: N806
    _BUCKET_SWEEP_INTERVAL = 30.0  # noqa: N806
    _last_bucket_sweep = [0.0]  # 1-elem box: mutable across closure calls

    def _prune_rate_buckets_locked(now: float) -> None:
        # Caller holds _rate_limit_lock. Cheap gate first: sweep on a
        # cadence, or sooner if we've blown past the hard cap — but never
        # more than ~once/sec, so a sustained flood of *active* IPs (where
        # a sweep frees nothing) can't turn this into O(buckets)/request.
        elapsed = now - _last_bucket_sweep[0]
        if elapsed < 1.0:
            return
        over_cap = len(_completion_call_windows) > _MAX_RATE_BUCKETS
        if not over_cap and elapsed < _BUCKET_SWEEP_INTERVAL:
            return
        _last_bucket_sweep[0] = now
        # Only keys with an empty window (no call in 60s) are dropped, so
        # in the normal case no slot is held. The one edge case — a single
        # completion running >60s — would at worst reset that key's
        # concurrency cap once; the later release() lands on an orphaned
        # semaphore, which is harmless.
        _evict_idle_rate_buckets(_completion_call_windows, _completion_semaphores, now - 60.0)

    def _actor_bucket_key(actor: str | None, request: Any) -> str:
        if actor:
            return f"actor:{actor}"
        # Fall back to the client IP for anonymous calls. When even
        # that's unknown (rare), share a single anonymous bucket.
        try:
            host = getattr(getattr(request, "client", None), "host", None) or "anon"
        except Exception:  # noqa: BLE001 — best-effort; fail-open
            host = "anon"
        return f"anon:{host}"

    def _acquire_completion_slot(
        actor: str | None,
        request: Any,
    ) -> _threading.Semaphore:
        key = _actor_bucket_key(actor, request)
        with _rate_limit_lock:
            sem = _completion_semaphores.get(key)
            if sem is None:
                sem = _threading.Semaphore(_CONCURRENT_LIMIT)
                _completion_semaphores[key] = sem
            window = _completion_call_windows.get(key)
            if window is None:
                window = _rl_deque()
                _completion_call_windows[key] = window
            # Sliding 60s window. Drop stale calls.
            now = _rl_time.monotonic()
            cutoff = now - 60.0
            while window and window[0] < cutoff:
                window.popleft()
            if len(window) >= _PER_MIN_LIMIT:
                raise HTTPException(
                    429,
                    f"rate limit: max {_PER_MIN_LIMIT} completions/min per actor",
                )
            window.append(now)
            # Bound the bucket dicts against a rotating-IP flood.
            _prune_rate_buckets_locked(now)
        # Acquire outside the lock so a saturated actor doesn't block
        # everyone else.
        if not sem.acquire(blocking=False):
            raise HTTPException(
                429,
                f"rate limit: max {_CONCURRENT_LIMIT} concurrent completions per actor",
            )
        return sem

    def _agent_owned_by_actor(agent_id: str, actor: str | None) -> bool:
        if not agent_id:
            return True  # no agent scope to police
        if agent_registry is None:
            # No registry -> can't check ownership. Fail closed only
            # if auth is actually required (otherwise authoring with
            # the global memory namespace stays open).
            return not require_auth
        try:
            owner = None
            for attr in ("owner_of", "owner", "get_owner", "actor_of"):
                fn = getattr(agent_registry, attr, None)
                if callable(fn):
                    owner = fn(agent_id) if attr != "owner" else fn
                    break
            if owner is None:
                # Registry doesn't expose ownership at all. Treat
                # "any registered agent" as global-writable when
                # unauthenticated, but if we have an actor, only allow
                # writes against agents prefixed with that actor.
                if actor and not agent_id.startswith(actor):  # noqa: SIM103
                    return False
                return True
            return owner == actor
        except Exception:  # noqa: BLE001 — best-effort; fail-open
            return False

    def _list_openai_models() -> dict[str, Any]:
        now = int(time.time())
        return {
            "object": "list",
            "data": [
                {
                    "id": f"octopus-agent/{name}",
                    "object": "model",
                    "created": now,
                    "owned_by": "octopus-agent",
                }
                for name in stack.registry.all_names()
            ]
            + [
                {
                    "id": "octopus-agent",
                    "object": "model",
                    "created": now,
                    "owned_by": "octopus-agent",
                }
            ]
            + [
                {
                    "id": _mix_id,
                    "object": "model",
                    "created": now,
                    "owned_by": "octopus-agent",
                }
                for _mix_id in mix_model_ids()
            ],
        }

    @router.get("/v1/models")
    def list_models(request: Request) -> dict[str, Any]:
        _resolve_actor(
            request,
            identity_store,
            require_auth,
            jwt_secret=jwt_secret,
            jwt_issuer=jwt_issuer,
            jwt_audience=jwt_audience,
            jwt_leeway_seconds=jwt_leeway_seconds,
        )
        return _list_openai_models()

    @router.get("/api/models")
    def list_models_alias(request: Request) -> dict[str, Any]:
        _resolve_actor(
            request,
            identity_store,
            require_auth,
            jwt_secret=jwt_secret,
            jwt_issuer=jwt_issuer,
            jwt_audience=jwt_audience,
            jwt_leeway_seconds=jwt_leeway_seconds,
        )
        return {
            "models": [
                {
                    "id": model["id"],
                    "name": model["id"],
                    "provider": model["owned_by"],
                }
                for model in _list_openai_models()["data"]
            ]
        }

    # ── Mix preset config (proposer pool / aggregator / count) ──
    # Read+write the user's octopus-mix mixture so the settings UI can
    # compose its own pool. Resolution at run time is config → env →
    # default (see openai_gateway/mix.py).
    @router.get("/api/mix-config")
    def get_mix_config(request: Request) -> dict[str, Any]:
        _resolve_actor(
            request,
            identity_store,
            require_auth,
            jwt_secret=jwt_secret,
            jwt_issuer=jwt_issuer,
            jwt_audience=jwt_audience,
            jwt_leeway_seconds=jwt_leeway_seconds,
        )
        from .openai_gateway.mix import _DEFAULT_N, load_mix_config

        cfg = load_mix_config()
        return {
            "proposers": cfg.get("proposers") or [],
            "aggregator": cfg.get("aggregator") or "",
            "n": cfg.get("n") or _DEFAULT_N,
        }

    @router.put("/api/mix-config")
    def put_mix_config(body: dict[str, Any], request: Request) -> dict[str, Any]:
        _resolve_actor(
            request,
            identity_store,
            require_auth,
            jwt_secret=jwt_secret,
            jwt_issuer=jwt_issuer,
            jwt_audience=jwt_audience,
            jwt_leeway_seconds=jwt_leeway_seconds,
        )
        from .openai_gateway.mix import save_mix_config

        return save_mix_config(body if isinstance(body, dict) else {})

    @router.post("/v1/chat/completions")
    def chat_completions(body: dict[str, Any], request: Request) -> Any:
        messages = body.get("messages") or []
        if not isinstance(messages, list) or not messages:
            raise HTTPException(400, "messages must be a non-empty list")

        # Auth + rate-limit at the top so spammers don't get to touch
        # planner / memory / journal at all.
        actor = _resolve_actor(
            request,
            identity_store,
            require_auth,
            jwt_secret=jwt_secret,
            jwt_issuer=jwt_issuer,
            jwt_audience=jwt_audience,
            jwt_leeway_seconds=jwt_leeway_seconds,
        )
        _completion_slot = _acquire_completion_slot(actor, request)
        try:
            return _chat_completions_impl(body, request, messages, actor)
        finally:
            try:  # noqa: SIM105
                _completion_slot.release()
            except Exception:  # noqa: BLE001 — completion slot release; lock might already be released
                pass

    def _chat_completions_impl(
        body: dict[str, Any],
        request: Request,
        messages: list[Any],
        actor: str | None,
    ) -> Any:
        conversation_messages = _normalize_conversation_messages(messages)
        from runtime.memory.users.profile import (
            memories_from_messages,
            merge_profile_memories,
        )

        explicit_memories = memories_from_messages(conversation_messages)
        stored_memories: list[str] = []
        written_memory_count = 0
        request_context = body.get("context") if isinstance(body.get("context"), dict) else {}
        page_memory_mode = str(request_context.get("page_agent_memory_mode") or "").strip()
        agent_name_for_memory = str(
            request_context.get("agent")
            or request_context.get("agent_id")
            or body.get("agent")
            or "",
        ).strip()
        project_for_memory = str(request_context.get("project") or "").strip()
        allow_memory_read = page_memory_mode != "ephemeral"
        allow_memory_write = page_memory_mode in ("", "write_allowed")
        # ACL: never let an authenticated actor write into a different
        # actor's per-agent memory by passing context.agent. When the
        # ownership check fails, demote to global scope (don't fully
        # disable writes — backwards compat for non-authed deployments).
        if (
            allow_memory_write
            and agent_name_for_memory
            and not _agent_owned_by_actor(agent_name_for_memory, actor)
        ):
            agent_name_for_memory = ""
        try:
            from runtime.memory.users.user_store import (
                add_fact,
                read_config,
                relevant_memory_texts,
            )

            memory_config = read_config()
            if allow_memory_write and memory_config.get("auto_capture_enabled", True):
                memory_scope = (
                    "project"
                    if project_for_memory
                    else ("agent" if agent_name_for_memory else "global")
                )
                source = (
                    f"page-agent:{agent_name_for_memory}"
                    if page_memory_mode == "write_allowed" and agent_name_for_memory
                    else ("page-agent" if page_memory_mode == "write_allowed" else "chat")
                )
                for memory in explicit_memories:
                    if (
                        add_fact(
                            memory,
                            category="profile",
                            source=source,
                            scope=memory_scope,
                            agent_id=agent_name_for_memory or None,
                            project=project_for_memory or None,
                        )
                        is not None
                    ):
                        written_memory_count += 1
            if allow_memory_read:
                stored_memories = relevant_memory_texts(
                    _extract_goal(messages),
                    limit=8,
                    agent_id=agent_name_for_memory or None,
                    project=project_for_memory or None,
                )
        except (OSError, ValueError) as _e:
            _logger = logging.getLogger(__name__)
            _logger.warning("memory read/write failed: %s", _e)
            stored_memories = []
            written_memory_count = 0
        profile_memories = merge_profile_memories(
            stored_memories,
            explicit_memories if page_memory_mode != "ephemeral" else [],
        )

        goal = _extract_goal(messages)
        if not goal:
            raise HTTPException(400, "no user message found in messages")

        # ``actor`` was already resolved by the wrapper above.

        stream = bool(body.get("stream", False))
        stream_mode = str(body.get("stream_mode") or "full").lower()
        if stream_mode not in ("full", "values"):
            stream_mode = "full"
        requested_model = body.get("model", "octopus-agent")
        reasoning_effort = _reasoning_effort_from_body(body)
        force_deep = _deep_requested(body)

        agent_id = body.get("agent")
        selected_agent: Any = None
        if agent_id is not None:
            if agent_registry is None:
                raise HTTPException(
                    400,
                    "agent parameter given but no agent_registry configured",
                )
            if not isinstance(agent_id, str) or not agent_id:
                raise HTTPException(400, "agent must be a non-empty string")
            if agent_registry.has(agent_id):
                selected_agent = agent_registry.get(agent_id)
            else:
                import logging as _lg

                _lg.info(
                    "unknown agent %r · falling back to no-agent mode",
                    agent_id,
                )
                selected_agent = None

        conversation_id = body.get("conversation_id")
        if conversation_id is not None and (
            not isinstance(conversation_id, str) or not conversation_id
        ):
            raise HTTPException(
                400,
                "conversation_id must be a non-empty string",
            )
        if conversation_id is None:
            conversation_id = uuid4().hex

        intent = ParsedIntent(
            raw=goal,
            intent_type="task",
            normalized_goal=goal,
            user_context={
                "conversation_messages": conversation_messages,
                "profile_memories": profile_memories,
                "memory_written_count": written_memory_count,
                **({"reasoning_effort": reasoning_effort} if reasoning_effort else {}),
            },
        )

        # Mix virtual model: explicit request for mixture-of-agents
        # orchestration. Runs BEFORE reflex so it's never short-circuited by
        # the trivial-input fast path.
        if is_mix_model(requested_model):
            from runtime.sensing.model_router.actor_context import (
                current_actor as _molili_actor_ctx,
            )

            _mix_agent_ctx = selected_agent.agent_id if selected_agent is not None else None
            _mix_token = _molili_actor_ctx.set(actor)
            try:
                with journal_context(
                    agent_id=_mix_agent_ctx,
                    conversation_id=conversation_id,
                ):
                    mix_result = run_mix_chat(
                        stack,
                        intent,
                        requested_model,
                        default_arm,
                        actor=actor,
                        agent=selected_agent,
                        run_chat=_run_chat,
                        optimizer=prompt_optimizer,
                    )
            finally:
                _molili_actor_ctx.reset(_mix_token)
            mix_meta = mix_result.setdefault("octopus", {})
            mix_meta["conversation_id"] = conversation_id
            if selected_agent is not None:
                mix_meta["agent"] = selected_agent.agent_id
            if stream:
                return StreamingResponse(
                    mix_sse_frames(mix_result, requested_model),
                    media_type="text/event-stream",
                )
            return mix_result

        # Deep runs must not be short-circuited by the reflex fast-path —
        # that's what makes a trivial prompt come back with no task_id/trace.
        reflex_response = (
            None
            if force_deep
            else _maybe_reflex_chat(
                reflex_router,
                intent,
                stack,
                requested_model,
                actor=actor,
            )
        )
        if reflex_response is not None:
            if reflex_response.get("octopus") is not None:
                reflex_response["octopus"]["conversation_id"] = conversation_id
                if selected_agent is not None:
                    reflex_response["octopus"]["agent"] = selected_agent.agent_id
            if stream:
                return StreamingResponse(
                    _reflex_stream_frames(reflex_response, requested_model),
                    media_type="text/event-stream",
                )
            return reflex_response

        agent_id_for_ctx = selected_agent.agent_id if selected_agent is not None else None

        from runtime.sensing.model_router.actor_context import current_actor as _molili_actor_ctx

        if stream:
            return StreamingResponse(
                _stream_chat_wrapped(
                    stack,
                    intent,
                    requested_model,
                    default_arm,
                    actor=actor,
                    agent=selected_agent,
                    agent_id=agent_id_for_ctx,
                    conversation_id=conversation_id,
                    stream_mode=stream_mode,
                ),
                media_type="text/event-stream",
            )
        _molili_token = _molili_actor_ctx.set(actor)
        try:
            with journal_context(
                agent_id=agent_id_for_ctx,
                conversation_id=conversation_id,
            ):
                response = _run_chat(
                    stack,
                    intent,
                    requested_model,
                    default_arm,
                    optimizer=prompt_optimizer,
                    actor=actor,
                    agent=selected_agent,
                    force_deep=force_deep,
                    conversation_id=conversation_id,
                )
        finally:
            _molili_actor_ctx.reset(_molili_token)
        response.setdefault("octopus", {})["conversation_id"] = conversation_id
        return response

    return router


def _run_chat(
    stack: Any,
    intent: ParsedIntent,
    model: str,
    default_arm: str,
    *,
    optimizer: Any = None,
    actor: str | None = None,
    agent: Any = None,
    force_deep: bool = False,
    conversation_id: str | None = None,
) -> dict[str, Any]:
    task_id = uuid4()
    variant_name: str | None = None

    # Hint the planner/optimizer that the caller wants a real multi-step run
    # (not a trivial direct answer), so the graph is worth tracing/replaying.
    if force_deep and isinstance(getattr(intent, "user_context", None), dict):
        intent.user_context["force_deep"] = True

    plan_kwargs: dict[str, Any] = {}
    if agent is not None:
        plan_kwargs["allowed_skills"] = agent.allowed_skill_union()
        runtime_soul = _runtime_soul_for_agent(agent)
        if runtime_soul:
            plan_kwargs["soul"] = runtime_soul
    if model and model not in ("octopus-agent", "", None):
        plan_kwargs["model"] = model

    if optimizer is not None:
        try:
            graph = optimizer.plan(intent, task_id=task_id, **plan_kwargs)
            variant_name = optimizer.variant_for_task(task_id)
        except TypeError:
            try:
                graph = optimizer.plan(intent, task_id=task_id)
                variant_name = optimizer.variant_for_task(task_id)
            except Exception as e:  # noqa: BLE001
                raise HTTPException(500, f"optimizer plan failed: {e}") from e
        except Exception as e:  # noqa: BLE001
            raise HTTPException(500, f"optimizer plan failed: {e}") from e
    else:
        try:
            graph = stack.planner.plan(intent, **plan_kwargs)
        except TypeError:
            try:
                graph = stack.planner.plan(intent)
            except Exception as e:  # noqa: BLE001
                reply = _direct_llm_fallback(stack, intent, agent, model=model)
                if reply is not None:
                    return _chat_completion_envelope(
                        reply,
                        model=model,
                        actor=actor,
                        agent=agent,
                        extra={"fallback": f"planner_error: {e}", "deep_requested": force_deep},
                    )
                raise HTTPException(500, f"planner failed: {e}") from e
        except Exception as e:  # noqa: BLE001
            reply = _direct_llm_fallback(stack, intent, agent, model=model)
            if reply is not None:
                return _chat_completion_envelope(
                    reply,
                    model=model,
                    actor=actor,
                    agent=agent,
                    extra={"fallback": f"planner_error: {e}", "deep_requested": force_deep},
                )
            raise HTTPException(500, f"planner failed: {e}") from e

    arm_id_str = default_arm
    if agent is not None and len(agent.arms) > 0:
        first = next(iter(agent.arms))
        arm_id_str = str(first.arm_id)

    budget = Budget(
        task_id=graph.task_id,
        limits=BudgetLimits(tokens=50_000, usd=0.50),
    )
    # The compat gateway never binds a Session for native-thread callers,
    # so without this the executor's scope/sandbox/plan-mode-write-block,
    # task-capability manifest, and approval gates (all keyed on
    # ``current_session() is not None``) are silent no-ops here — a
    # write/exec skill run through this path had no workspace
    # confinement at all. ``mode`` defaults to "chat", which confines
    # writes to this turn's own thread-artifact root instead of the
    # unconfined legacy contract.
    from runtime.platform.process.session import Session, session_scope

    with session_scope(
        Session(
            actor=actor,
            thread_id=conversation_id,
            metadata={"enforce_executor_approval": True},
        )
    ):
        traj = stack.runtime.run(
            graph,
            budget=budget,
            caller=f"arms/{arm_id_str}",
            arm_id=ArmId(arm_id_str),
            actor=actor,
        )

    if optimizer is not None:
        try:
            optimizer.record_outcome(task_id, success=traj.outcome.success)
        except Exception as _e:  # noqa: BLE001
            _logger = logging.getLogger(__name__)
            _logger.debug("optimizer.record_outcome failed: %s", _e)

    assistant_text = synthesize_reply(
        stack,
        goal=intent.normalized_goal,
        trajectory=traj,
        model=model,
        agent=agent,
        conversation_messages=_conversation_messages_payload(intent),
        profile_memories=_profile_memories_payload(intent),
        user_context=intent.user_context if intent is not None else None,
    )
    finish_reason = "stop" if traj.outcome.success else "failed"
    planner_usage = getattr(graph, "planner_usage", None)
    if not isinstance(planner_usage, dict):
        planner_usage = {}
    planner_prompt_tokens = int(planner_usage.get("input_tokens") or 0)
    planner_completion_tokens = int(planner_usage.get("output_tokens") or 0)
    completion_tokens = budget.tokens_spent + planner_completion_tokens
    total_tokens = planner_prompt_tokens + completion_tokens

    octopus_meta: dict[str, Any] = {
        "task_id": str(graph.task_id),
        "strategy": graph.strategy,
        "step_count": traj.step_count,
        "usd_spent": round(budget.usd_spent, 6),
        "success": traj.outcome.success,
    }
    if planner_usage:
        octopus_meta["planner_usage"] = {
            "input_tokens": planner_prompt_tokens,
            "output_tokens": planner_completion_tokens,
        }
    if variant_name is not None:
        octopus_meta["variant"] = variant_name
    if force_deep:
        octopus_meta["deep_requested"] = True
    if actor is not None:
        octopus_meta["actor"] = actor
    if agent is not None:
        octopus_meta["agent"] = agent.agent_id

    return {
        "id": f"chatcmpl-{uuid4().hex[:16]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": assistant_text},
                "finish_reason": finish_reason,
            }
        ],
        "usage": {
            "prompt_tokens": planner_prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
        },
        "octopus": octopus_meta,
    }


def synthesize_reply(
    stack: Any,
    *,
    goal: str,
    trajectory: Any,
    model: str | None = None,
    agent: Any = None,
    conversation_messages: list[dict[str, str]] | None = None,
    profile_memories: list[str] | None = None,
    user_context: dict[str, Any] | None = None,
    usage_out: dict[str, int] | None = None,
) -> str:
    wants_research_report = _is_research_report_context(goal, user_context)

    if not getattr(trajectory, "steps", None):
        return _assistant_text_from_trajectory(trajectory)

    router = getattr(stack.planner, "router", None)
    if router is None:
        if wants_research_report:
            return _format_research_report_fallback(
                goal=goal,
                trajectory=trajectory,
                user_context=user_context,
            )
        return _assistant_text_from_trajectory(trajectory)

    tool_calls: list[str] = []
    for i, step in enumerate(trajectory.steps, 1):
        tool_calls.append(f"{i}. {_summarize_step_for_stream(step)}")
    tool_summary = "\n".join(tool_calls) if tool_calls else "(none)"

    from runtime.sensing.model_router.models import Message, ModelRequest

    system_soul = (
        _runtime_soul_for_agent(agent)
        or "You are a helpful assistant. The user asked a question, and "
        "the system already ran the necessary tools to answer it. Read "
        "the tool outputs and respond in natural language, concise and "
        "to the point. Do NOT mention the tools by name. If the tool "
        "outputs are structured data (file lists, JSON, etc.), summarize "
        "them rather than pasting raw content. Use the user's language."
    )
    team_section = ""
    try:
        from runtime.core.cerebrum.llm_planner import _render_team_roster_section

        uc = user_context or {}
        if isinstance(uc, dict):
            team_section = _render_team_roster_section(uc)
    except (ImportError, AttributeError):
        team_section = ""
    if team_section:
        system_soul = f"{system_soul}\n\n{team_section}"
    interaction_profile = _interaction_profile_prompt(user_context)
    if interaction_profile:
        system_soul = f"{system_soul}\n\n{interaction_profile}"
    from runtime.memory.users.profile import render_profile_memories

    profile_section = render_profile_memories(profile_memories or [])
    profile_block = f"{profile_section}\n\n" if profile_section else ""
    history = _render_conversation_history(conversation_messages or [])
    history_block = f"Conversation history:\n{history}\n\n" if history else ""
    research_instruction = ""
    if wants_research_report:
        research_instruction = (
            "\n\nThe user is asking for a deep research style report. "
            "Do not return a tool log, JSON plan, or brief answer. "
            "Write a complete Markdown report in the user's language with these sections: "
            "title, executive summary, scope and method, key findings, evidence/sources, "
            "uncertainties and gaps, conclusion and recommendations. "
            "If evidence is thin, say that explicitly and label claims as preliminary."
        )

    synthesis_user = (
        f"{profile_block}{history_block}"
        f"Latest user question:\n{goal}\n\n"
        f"Tool outputs:\n{tool_summary}\n\n"
        "Write the final reply to the user based on the conversation and "
        f"these outputs.{research_instruction}"
    )

    effective_model = (
        model
        if model and model not in ("octopus-agent", "")
        else getattr(stack.planner, "planner_model", None) or "molili"
    )
    req = ModelRequest(
        model=effective_model,
        messages=[
            Message(role="system", content=system_soul),
            Message(role="user", content=synthesis_user),
        ],
        max_tokens=4096 if wants_research_report else 1024,
        temperature=0.3,
    )
    try:
        resp = router.call(req)
        if usage_out is not None:
            usage_out["input_tokens"] = int(getattr(resp, "input_tokens", 0) or 0)
            usage_out["output_tokens"] = int(getattr(resp, "output_tokens", 0) or 0)
        _synth_usage_local = {
            "input_tokens": int(getattr(resp, "input_tokens", 0) or 0),
            "output_tokens": int(getattr(resp, "output_tokens", 0) or 0),
        }
        _commit_direct_llm_cost(
            stack,
            _synth_usage_local,
            agent,
            reason="synthesize_reply",
        )
        text = (resp.text or "").strip()
        if text:
            from runtime.platform.process.session import current_session
            from runtime.platform.runtime_policy.identity_filter import filter_text

            filtered = filter_text(
                text,
                session=current_session(),
                user_message=goal,
                agent=agent,
            )
            if wants_research_report and not _looks_like_complete_research_report(filtered):
                return _format_research_report_fallback(
                    goal=goal,
                    trajectory=trajectory,
                    user_context=user_context,
                )
            return filtered
    except (ConnectionError, TimeoutError, OSError, ValueError, TypeError) as exc:  # noqa: BLE001
        import logging

        logging.getLogger(__name__).warning(
            "synthesize_reply failed: %s: %s",
            type(exc).__name__,
            exc,
        )

    if wants_research_report:
        return _format_research_report_fallback(
            goal=goal,
            trajectory=trajectory,
            user_context=user_context,
        )
    return _assistant_text_from_trajectory(trajectory)


def _maybe_reflex_chat(
    reflex_router: Any,
    intent: ParsedIntent,
    stack: Any,
    model: str,
    *,
    actor: str | None = None,
) -> dict[str, Any] | None:
    if reflex_router is None:
        return None
    try:
        result = reflex_router.try_match(intent)
    except (ConnectionError, TimeoutError, OSError, TypeError, ValueError):  # noqa: BLE001
        return None
    from runtime.core.nerves.reflex.reflex_router import ReflexMatch

    if not isinstance(result, ReflexMatch):
        return None

    try:
        stack.journal.write_reflex_hit(
            actor=actor,
            rule_id=result.rule_id,
            kind=result.kind,
            latency_ms=result.latency_ms,
            intent_goal=intent.normalized_goal,
            response=str(result.response)[:500],
        )
    except Exception as _e:  # noqa: BLE001
        _logger = logging.getLogger(__name__)
        _logger.warning("journal write_reflex_hit failed: %s", _e)

    if isinstance(result.response, dict):
        if "reply" in result.response:
            content = str(result.response["reply"])
        else:
            content = ", ".join(f"{k}={v}" for k, v in result.response.items())
    else:
        content = str(result.response)

    return {
        "id": f"chatcmpl-reflex-{uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        },
        "octopus": {
            "strategy": "reflex",
            "step_count": 0,
            "success": True,
            "reflex_rule": result.rule_id,
            "reflex_latency_ms": result.latency_ms,
            "reflex": True,
            "rule_id": result.rule_id,
            "kind": result.kind,
            "latency_ms": result.latency_ms,
        },
    }
