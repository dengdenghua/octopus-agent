from __future__ import annotations

import contextlib
import json
import logging
import queue
import threading
import time
from typing import Any
from uuid import uuid4

from runtime.platform.models import ArmId, Budget, BudgetLimits, ParsedIntent

from ..openai_formatting import (
    summarize_step_for_stream as _summarize_step_for_stream,
)
from .context_manager import _build_messages_for_llm, _runtime_soul_for_agent
from .request_parser import _model_runtime_options, _resolve_custom_model_router


def _commit_direct_llm_cost(
    stack: Any,
    usage: dict[str, int] | None,
    agent: Any,
    *,
    reason: str = "direct_llm_fallback",
) -> None:
    try:
        from uuid import uuid4

        from runtime.memory.journal.journal import Journal  # noqa: F401
        from runtime.platform.models import TaskId
        from runtime.platform.models.primitives import CostEntry
    except (ImportError, ModuleNotFoundError):
        return
    journal = getattr(stack, "journal", None)
    if journal is None or not usage:
        return
    tokens_in = int(usage.get("input_tokens") or 0)
    tokens_out = int(usage.get("output_tokens") or 0)
    if tokens_in == 0 and tokens_out == 0:
        return
    agent_id = getattr(agent, "agent_id", None) if agent else None
    actor = f"arms/{agent_id}" if agent_id else "arms/direct_llm"
    try:
        journal.write_budget(
            "budget_commit",
            task_id=TaskId(uuid4()),
            actor=actor,
            reason=reason,
            cost=CostEntry(tokens_in=tokens_in, tokens_out=tokens_out),
        )
    except Exception as _e:
        _logger = logging.getLogger(__name__)
        _logger.warning("journal write_budget failed: %s", _e)


def _direct_llm_fallback_with_usage(
    stack: Any, intent: ParsedIntent, agent: Any,
    *, model: str | None = None, reasoning_effort: Any = None,
) -> tuple[str | None, dict[str, int]]:
    reply, usage = _direct_llm_fallback_impl(
        stack,
        intent,
        agent,
        model=model,
        reasoning_effort=reasoning_effort,
    )
    return reply, usage


def _direct_llm_fallback(
    stack: Any, intent: ParsedIntent, agent: Any,
    *, model: str | None = None, reasoning_effort: Any = None,
) -> str | None:
    reply, _ = _direct_llm_fallback_impl(
        stack,
        intent,
        agent,
        model=model,
        reasoning_effort=reasoning_effort,
    )
    return reply


def _direct_llm_fallback_impl(
    stack: Any, intent: ParsedIntent, agent: Any,
    *, model: str | None = None, reasoning_effort: Any = None,
) -> tuple[str | None, dict[str, int]]:
    router = getattr(stack.planner, "router", None)
    if router is None:
        return None, {}
    from runtime.sensing.model_router.models import (
        Message,
        ModelRequest,
        normalize_reasoning_effort,
        thinking_budget_for_effort,
    )

    messages: list[Message] = _build_messages_for_llm(intent, agent)

    effective_model = (
        model if model and model not in ("octopus-agent", "")
        else getattr(stack.planner, "planner_model", None) or "molili"
    )
    router, effective_model = _resolve_custom_model_router(
        effective_model, router,
    )
    resolved_model = effective_model
    if hasattr(router, "_resolve"):
        try:
            _sub = router._resolve(effective_model)
            if _sub is not router:
                resolved_model = (
                    getattr(_sub, "default_model", None)
                    or effective_model
                )
        except (AttributeError, TypeError):  # noqa: BLE001 — subrouter doesn't expose default_model; fall back to effective_model
            pass
    wants_thinking, max_tokens = _model_runtime_options(effective_model, resolved_model)
    normalized_effort = normalize_reasoning_effort(
        reasoning_effort or (intent.user_context or {}).get("reasoning_effort"),
    )
    req = ModelRequest(
        model=effective_model,
        messages=messages,
        max_tokens=max_tokens,
        temperature=0.3,
        enable_thinking=wants_thinking,
        reasoning_effort=normalized_effort,
        thinking_budget=thinking_budget_for_effort(normalized_effort, max_tokens),
    )
    try:
        resp = router.call(req)
        from runtime.platform.runtime_policy.identity_filter import filter_text
        from runtime.platform.process.session import current_session
        filtered = filter_text(
            resp.text,
            session=current_session(),
            user_message=intent.normalized_goal,
            agent=agent,
        )
        thinking = (getattr(resp, "thinking", "") or "").strip()
        import logging as _lg
        _tlog = _lg.getLogger("octopus.thinking")
        if _tlog.isEnabledFor(_lg.DEBUG):
            _tlog.debug(
                "direct_llm_fallback · model=%s wants_thinking=%s "
                "thinking_len=%d text_len=%d thinking_head=%r",
                effective_model, wants_thinking, len(thinking),
                len(filtered or ""), thinking[:160],
            )
        usage = {
            "input_tokens": int(getattr(resp, "input_tokens", 0) or 0),
            "output_tokens": int(getattr(resp, "output_tokens", 0) or 0),
        }
        _commit_direct_llm_cost(stack, usage, agent, reason="direct_llm_fallback")
        if thinking:
            from .response_formatter import _wrap_with_thinking_block
            return _wrap_with_thinking_block(thinking, filtered), usage
        return filtered, usage
    except Exception as _exc:  # noqa: BLE001
        import logging as _lg
        _lg.getLogger("octopus.thinking").warning(
            "direct_llm_fallback · EXCEPTION model=%s err=%s",
            effective_model, _exc,
        )
        return None, {}


def _stream_direct_llm_fallback(
    stack: Any, intent: ParsedIntent, agent: Any,
    *, model: str | None = None, reasoning_effort: Any = None,
):
    router = getattr(stack.planner, "router", None)
    if router is None:
        return
    from runtime.sensing.model_router.models import (
        ModelRequest,
        normalize_reasoning_effort,
        thinking_budget_for_effort,
    )

    messages = _build_messages_for_llm(intent, agent)

    # "auto" / "octopus-agent" / "" are non-pin sentinels — defer to
    # the planner default + smart routing. Anything else is a user
    # pick from model_picker and should pass through verbatim.
    _is_auto_or_default = (
        not model
        or model in ("octopus-agent", "auto")
    )
    effective_model = (
        getattr(stack.planner, "planner_model", None) or "molili"
        if _is_auto_or_default
        else model
    )
    # Smart routing: in the chat fast-path, classify the prompt and
    # let select_model_for_complexity pick the configured tier
    # model (OCTOPUS_MODEL_LOCAL / smart_routing.local etc.) if
    # one is set. Falls through unchanged when the user pinned a
    # model, when smart_routing is disabled, or when no tier is
    # configured.
    try:
        from runtime.core.cerebrum.turn_complexity import (
            estimate_turn_complexity,
            select_model_for_complexity,
        )
        _verdict = estimate_turn_complexity(
            getattr(intent, "normalized_goal", "") or "",
            has_explicit_model=not _is_auto_or_default,
        )
        # ``user_model`` is what select_model_for_complexity uses
        # to detect a pin; pass the sentinel through so it sees
        # "auto" / "octopus-agent" as "no pin" via its existing
        # check at turn_complexity.py:395.
        _smart_model, _ = select_model_for_complexity(
            _verdict, user_model=model,
        )
        if _smart_model:
            effective_model = _smart_model
    except (ImportError, AttributeError):  # noqa: BLE001 — OctopusRouter/turn_complexity is optional; fall back to user-supplied model
        pass
    # _resolve_custom_model_router needs a concrete name — never
    # the "auto" sentinel (which has no custom_models.json entry).
    router, effective_model = _resolve_custom_model_router(
        effective_model, router,
    )
    resolved_model = effective_model
    if hasattr(router, "_resolve"):
        try:
            _sub = router._resolve(effective_model)
            if _sub is not router:
                resolved_model = (
                    getattr(_sub, "default_model", None)
                    or effective_model
                )
        except (AttributeError, TypeError):  # noqa: BLE001 — subrouter doesn't expose default_model; fall back to effective_model
            pass
    wants_thinking, max_tokens = _model_runtime_options(effective_model, resolved_model)
    normalized_effort = normalize_reasoning_effort(
        reasoning_effort or (intent.user_context or {}).get("reasoning_effort"),
    )
    req = ModelRequest(
        model=effective_model,
        messages=messages,
        max_tokens=max_tokens,
        temperature=0.3,
        enable_thinking=wants_thinking,
        reasoning_effort=normalized_effort,
        thinking_budget=thinking_budget_for_effort(normalized_effort, max_tokens),
    )

    from runtime.platform.runtime_policy.identity_filter import filter_text
    from runtime.platform.process.session import current_session

    text_buf: list[str] = []
    thinking_buf: list[str] = []

    def _display_deltas(text: str):
        if len(text) <= 40:
            yield text
            return
        chunk_size = 18
        for i in range(0, len(text), chunk_size):
            yield text[i:i + chunk_size]

    def _clean_final_text(text: str) -> str:
        import re as _re
        stripped = _re.sub(
            r"<thinking>.*?</thinking>\s*", "",
            text, flags=_re.DOTALL,
        )
        stripped = _re.sub(
            r"<thinking>.*$", "", stripped, flags=_re.DOTALL,
        ).lstrip()
        return filter_text(
            stripped,
            session=current_session(),
            user_message=intent.normalized_goal,
            agent=agent,
        ) or ""

    def _normalize_markdown(text: str) -> str:
        import re as _re
        out = text.strip()
        out = _re.sub(r"(?<!^)(?<!\n)(#{1,4}\s+)", r"\n\n\1", out)
        out = _re.sub(r"(?<!\n)(\n?---\n?)", "\n\n---\n\n", out)
        out = _re.sub(r"(?<!\n)(\n?```)", r"\n\1", out)
        out = _re.sub(r"([^\n])(\s+\|[^|\n]+\|)", r"\1\n\n\2", out)
        out = _re.sub(r"([^\n])(\s+[-*]\s+)", r"\1\n\2", out)
        out = _re.sub(r"([^\n])(\s+\d+\.\s+)", r"\1\n\2", out)
        out = _re.sub(r"\n{3,}", "\n\n", out)
        return out.strip()

    def _sync_call_as_stream(reason: str):
        resp = router.call(req)
        raw_text = getattr(resp, "text", "") or ""
        final_text = _normalize_markdown(_clean_final_text(raw_text))
        for _piece in _display_deltas(final_text):
            yield ("text", _piece, None)
            if len(final_text) > 40:
                time.sleep(0.004)
        _usage_dict = {
            "input_tokens": int(getattr(resp, "input_tokens", 0) or 0),
            "output_tokens": int(getattr(resp, "output_tokens", 0) or 0),
        }
        _commit_direct_llm_cost(stack, _usage_dict, agent, reason=reason)
        yield ("done", json.dumps(_usage_dict), final_text)

    try:
        _pseudo_stream_models: set[str] = set()
        if str(resolved_model or effective_model).lower() in _pseudo_stream_models:
            yield from _sync_call_as_stream("pseudo_stream_direct_llm_fallback")
            return

        for event in router.call_stream(req):
            etype = event.type
            if etype == "text_delta":
                text_buf.append(event.delta)
                for _piece in _display_deltas(event.delta):
                    yield ("text", _piece, None)
                    if len(event.delta) > 40:
                        time.sleep(0.012)
            elif etype == "thinking_delta":
                thinking_buf.append(event.delta)
                yield ("reasoning", event.delta, None)
            elif etype == "done":
                final = event.final
                raw_text = (
                    (final.text if final else "".join(text_buf)) or ""
                )
                final_text = _clean_final_text(raw_text)
                if not final_text.strip() and not text_buf:
                    yield from _sync_call_as_stream(
                        "empty_stream_direct_llm_fallback",
                    )
                    return
                _usage_dict = {
                    "input_tokens": int(
                        getattr(final, "input_tokens", 0) or 0,
                    ),
                    "output_tokens": int(
                        getattr(final, "output_tokens", 0) or 0,
                    ),
                }
                _usage_json = json.dumps(_usage_dict)
                _commit_direct_llm_cost(
                    stack, _usage_dict, agent,
                    reason="stream_direct_llm_fallback",
                )
                yield ("done", _usage_json, final_text)
    except (ConnectionError, TimeoutError) as _exc:
        import logging as _lg
        _lg.getLogger("octopus.thinking").warning(
            "stream_direct_llm_fallback · EXCEPTION model=%s err=%s",
            effective_model, _exc,
        )
        try:
            yield from _sync_call_as_stream("stream_error_direct_llm_fallback")
        except (ConnectionError, TimeoutError) as _fallback_exc:
            _lg.getLogger("octopus.thinking").warning(
                "stream_direct_llm_fallback sync fallback failed "
                "model=%s err=%s",
                effective_model, _fallback_exc,
            )
            raise _fallback_exc
        return


def _stream_chat_wrapped(
    stack: Any,
    intent: ParsedIntent,
    model: str,
    default_arm: str,
    *,
    actor: str | None = None,
    agent: Any = None,
    agent_id: str | None = None,
    conversation_id: str | None = None,
    stream_mode: str = "full",
):
    import json

    from runtime.memory.journal.journal_context import _AGENT_ID, _CONVERSATION_ID
    from runtime.sensing.model_router.molili_router import current_actor as _molili_actor_ctx

    # ContextVars are shared across coroutines that reuse the same
    # OS thread (Starlette's SSE streams live in a threadpool). If we
    # ``.set()`` without keeping the token, the following turn served
    # by the same thread inherits this turn's actor — a cross-user
    # identity leak. Capture the tokens and reset in ``finally``.
    _agent_token = _AGENT_ID.set(agent_id)
    _convo_token = _CONVERSATION_ID.set(conversation_id)
    _actor_token = _molili_actor_ctx.set(actor) if actor else None
    try:

        meta_chunk = {
            "id": f"chatcmpl-{uuid4().hex[:16]}",
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": model,
            "choices": [{"index": 0, "delta": {}, "finish_reason": None}],
            "octopus": {
                "conversation_id": conversation_id,
                "agent": agent.agent_id if agent is not None else None,
            },
        }
        yield f"data: {json.dumps(meta_chunk)}\n\n"
        yield from _stream_chat(
            stack, intent, model, default_arm,
            actor=actor, agent=agent,
            stream_mode=stream_mode,
        )
    finally:
        try:  # noqa: SIM105
            _AGENT_ID.reset(_agent_token)
        except Exception:  # noqa: BLE001 — ContextVar.reset on a foreign token raises; benign on hand-off
            pass
        try:  # noqa: SIM105
            _CONVERSATION_ID.reset(_convo_token)
        except Exception:  # noqa: BLE001 — ContextVar.reset on a foreign token raises; benign on hand-off
            pass
        if _actor_token is not None:
            try:  # noqa: SIM105
                _molili_actor_ctx.reset(_actor_token)
            except Exception:  # noqa: BLE001 — ContextVar.reset on a foreign token raises; benign on hand-off
                pass


def _stream_chat(
    stack: Any,
    intent: ParsedIntent,
    model: str,
    default_arm: str,
    *,
    actor: str | None = None,
    agent: Any = None,
    keepalive_interval_s: float = 15.0,
    stream_mode: str = "full",
):
    import json

    cid = f"chatcmpl-{uuid4().hex[:16]}"
    created = int(time.time())

    def _frame(delta: dict[str, Any], finish_reason: str | None = None) -> str:
        chunk = {
            "id": cid,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "delta": delta,
                    "finish_reason": finish_reason,
                }
            ],
        }
        return f"data: {json.dumps(chunk)}\n\n"

    def _failure_content(kind: str, exc: BaseException) -> str:
        reason = str(exc).strip() or type(exc).__name__
        if kind == "planning":
            return (
                f"Planning failed before execution: {reason}. "
                "The stream closed cleanly; check the planner or model "
                "configuration and retry."
            )
        return (
            f"Runtime failed during execution: {reason}. "
            "The stream closed cleanly; inspect the tool logs and retry."
        )

    yield _frame({"role": "assistant", "content": ""})

    plan_kwargs: dict[str, Any] = {}
    if agent is not None:
        plan_kwargs["allowed_skills"] = agent.allowed_skill_union()
        runtime_soul = _runtime_soul_for_agent(agent)
        if runtime_soul:
            plan_kwargs["soul"] = runtime_soul
    if model and model not in ("octopus-agent", "", None):
        plan_kwargs["model"] = model

    try:
        try:
            graph = stack.planner.plan(intent, **plan_kwargs)
        except TypeError:
            graph = stack.planner.plan(intent)
    except Exception as e:  # noqa: BLE001
        yield _frame({"content": _failure_content("planning", e)}, "failed")
        yield "data: [DONE]\n\n"
        return

    arm_id_str = default_arm
    if agent is not None and len(agent.arms) > 0:
        first = next(iter(agent.arms))
        arm_id_str = str(first.arm_id)

    budget = Budget(
        task_id=graph.task_id,
        limits=BudgetLimits(tokens=50_000, usd=0.50),
    )
    event_queue: queue.Queue[Any] = queue.Queue(maxsize=1000)
    done = threading.Event()
    result_holder: dict[str, Any] = {}
    seen_event_ids: set[str] = set()

    def _enqueue_event(event: Any) -> None:
        with contextlib.suppress(queue.Full):
            event_queue.put_nowait(event)

    def _matches(event: Any) -> bool:
        return getattr(event, "task_id", None) == graph.task_id

    unsubscribe = None
    if hasattr(stack.journal, "subscribe"):
        unsubscribe = stack.journal.subscribe(
            lambda event: _enqueue_event(event) if _matches(event) else None,
        )

    def _worker() -> None:
        try:
            traj = stack.runtime.run(
                graph, budget=budget,
                caller=f"arms/{arm_id_str}", arm_id=ArmId(arm_id_str),
                actor=actor,
            )
            result_holder["trajectory"] = traj
        except Exception as exc:  # noqa: BLE001
            result_holder["error"] = exc
        finally:
            done.set()
            while True:
                try:
                    event_queue.put_nowait(None)
                    break
                except queue.Full:
                    try:
                        event_queue.get_nowait()
                    except queue.Empty:
                        break

    def _poll_journal_events() -> None:
        if unsubscribe is not None or not hasattr(stack.journal, "read_by_task"):
            return
        try:
            events = stack.journal.read_by_task(graph.task_id)
        except (OSError, ValueError, TypeError):  # noqa: BLE001
            return
        for event in events:
            event_id = str(getattr(event, "event_id", id(event)))
            if event_id in seen_event_ids:
                continue
            seen_event_ids.add(event_id)
            _enqueue_event(event)

    worker = threading.Thread(target=_worker, daemon=True)
    worker.start()

    try:
        keepalive_interval_s = max(0.0, float(keepalive_interval_s))
        wait_timeout = min(0.25, max(0.01, keepalive_interval_s or 0.25))
        last_keepalive = time.monotonic()
        while True:
            _poll_journal_events()
            try:
                event = event_queue.get(timeout=wait_timeout)
            except queue.Empty:
                if done.is_set():
                    break
                if (
                    keepalive_interval_s > 0
                    and time.monotonic() - last_keepalive >= keepalive_interval_s
                ):
                    last_keepalive = time.monotonic()
                    yield ": keepalive\n\n"
                continue
            if event is None:
                _poll_journal_events()
                if not event_queue.empty():
                    continue
                break
            if stream_mode == "values":
                continue
            if getattr(event, "event_type", "") == "step":
                line = _summarize_step_for_stream(event.step)
                yield _frame({"content": line + "\n"})

        if "error" in result_holder:
            exc = result_holder["error"]
            yield _frame({"content": _failure_content("runtime", exc)}, "failed")
        else:
            traj = result_holder.get("trajectory")
            success = bool(getattr(getattr(traj, "outcome", None), "success", False))
            yield _frame({}, "stop" if success else "failed")
        yield "data: [DONE]\n\n"
    finally:
        if unsubscribe is not None:
            unsubscribe()


def _reflex_stream_frames(completion: dict[str, Any], model: str):
    import json as _json

    content = completion["choices"][0]["message"]["content"]
    cid = completion["id"]
    created = completion["created"]

    def _mk_chunk(delta: dict[str, Any], finish_reason: str | None = None) -> str:
        chunk = {
            "id": cid, "object": "chat.completion.chunk",
            "created": created, "model": model,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
        }
        return f"data: {_json.dumps(chunk)}\n\n"

    yield _mk_chunk({"role": "assistant", "content": ""})
    yield _mk_chunk({"content": content})
    yield _mk_chunk({}, "stop")
    yield "data: [DONE]\n\n"
