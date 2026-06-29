"""Turn lifecycle orchestration for the realtime runtime.

Split out of ``realtime_cerebrum.py``: the ``start_turn`` controller —
validation, slash/topology/model routing, thread setup, prompt hooks,
intent build, resume-intent confirmation, execution dispatch
(topology / reflection fast path / react) and terminal status
finalization — plus the pending resume-intent store it consults.

Every function takes the owning ``CerebrumRuntime`` as its first
argument; cross-method calls go through the runtime so subclass
overrides keep working.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING, Any

from runtime.protocol import (
    ErrorItem,
    ItemStatus,
    ItemType,
    ServerMethod,
    Turn,
    TurnParams,
    TurnStatus,
    VerificationItem,
)
from runtime.safety.approval.approval_gate import ApprovalProvider
from runtime.sensing.gateway.realtime_approval import GatewayApprovalProvider
from runtime.sensing.gateway.realtime_gateway import EventEmitter
from runtime.sensing.gateway.realtime_thread_history import (
    _conversation_messages_for_react,
)
from runtime.sensing.gateway.realtime_turn_input import (
    _build_intent,
    _execution_resume_intent,
    _extract_codex_composer_mode,
    _input_attachments,
    _input_metadata,
    _join_text,
    _parse_resume_confirmation,
    _resume_confirmation_text,
    _safe_int,
    _should_default_planning_mode,
    _should_default_topology,
    _turn_mode,
)
from runtime.sensing.gateway.realtime_turn_outcome import (
    _code_change_paths,
    _file_change_item_ids,
    _turn_has_failed_code_verification,
    _turn_has_unverified_code_changes,
    _verification_plan_for_code_paths,
    _verification_plan_stdout_tail,
)

if TYPE_CHECKING:
    from runtime.sensing.gateway.realtime_cerebrum import CerebrumRuntime

_logger = logging.getLogger(__name__)


def _turn_has_observable_output(turn: Turn) -> bool:
    """Return true once the runtime produced anything visible beyond input.

    A turn that only contains the user's message but no agent text, no
    reasoning, no tool/file/artifact/error item is a silent failure. It
    should not be marked completed because the UI has nothing meaningful
    to render and the user sees a stuck/empty answer.
    """
    for item in turn.items:
        item_type = getattr(item, "type", None)
        if item_type in {
            ItemType.USER_MESSAGE,
            ItemType.STEERING_USER_MESSAGE,
        }:
            continue
        if item_type == ItemType.AGENT_MESSAGE:
            if str(getattr(item, "text", "") or "").strip():
                return True
            continue
        if item_type == ItemType.REASONING:
            if (
                str(getattr(item, "content", "") or "").strip()
                or bool(getattr(item, "summary", None))
            ):
                return True
            continue
        if item_type == ItemType.PLAN:
            if str(getattr(item, "text", "") or "").strip():
                return True
            continue
        if item_type == ItemType.TODO_LIST:
            if bool(getattr(item, "plan", None)):
                return True
            continue
        return True
    return False


def _inject_cowork_turn_plan(
    runtime: Any,
    *,
    thread_id: str,
    text: str,
    intent: Any,
) -> None:
    """Attach cowork turn-planning diagnostics to the realtime intent.

    This is deliberately advisory: realtime still follows the existing stable
    dispatch path, but every downstream driver can now see which cowork members
    were addressed, whether the group mode wants multiple responders, and why.
    """
    store = getattr(runtime, "_cowork_group_store", None)
    if store is None:
        store = getattr(getattr(runtime, "_app_state", None), "cowork_group_store", None)
    if store is None:
        return
    try:
        from runtime.memory.cowork.turn_plan import plan_turn_for_thread

        plan = plan_turn_for_thread(store, thread_id, text).to_dict()
    except Exception as exc:  # noqa: BLE001
        _logger.debug("cowork turn plan skipped: %s", exc, exc_info=True)
        return
    context = getattr(intent, "user_context", None)
    if not isinstance(context, dict):
        return
    context.setdefault("cowork_plan", plan)
    context.setdefault("cowork_mode", plan.get("mode"))
    context.setdefault("cowork_responders", plan.get("responders") or [])
    context.setdefault("cowork_is_multi", bool(plan.get("is_multi")))
    responders = [
        str(agent_id)
        for agent_id in (plan.get("responders") or [])
        if str(agent_id or "").strip()
    ]
    if plan.get("is_multi") and len(responders) > 1:
        context.setdefault(
            "agent_roster",
            [
                {"agent_id": agent_id, "display_name": agent_id}
                for agent_id in responders
            ],
        )


async def _start_turn(
    runtime: CerebrumRuntime,
    params: dict[str, Any],
    emitter: EventEmitter,
) -> Turn:
    """Start a new turn in a realtime thread.

    ╔══════════════════════════════════════════════════════════════╗
    ║ start_turn · navigation (396 lines, async orchestrator).     ║
    ║                                                              ║
    ║   PHASE 1 · validation + slash/topology/model routing ~L1226 ║
    ║   PHASE 2 · thread setup + turn registration          ~L1329 ║
    ║   PHASE 3 · prompt hooks + user message anchor        ~L1352 ║
    ║   PHASE 4 · intent build + resume check               ~L1414 ║
    ║   PHASE 5 · execution dispatch (topology/fast/react)  ~L1458 ║
    ║   PHASE 6 · status finalization + snapshot            ~L1550 ║
    ║                                                              ║
    ║ Extractable: mostly sequential with clear phase boundaries.  ║
    ╚══════════════════════════════════════════════════════════════╝
    """
    # ── PHASE 1 · validation + slash/topology/model routing ────────
    validated = TurnParams.model_validate(params)
    thread_id = runtime._require_thread_id(validated.thread_id)
    text = _join_text(validated.input)
    stripped_text, marker_mode = _extract_codex_composer_mode(text)
    if marker_mode is not None:
        text = stripped_text
        patched_input: list[dict[str, Any]] = []
        marker_applied = False
        for block in validated.input:
            if (
                not marker_applied
                and isinstance(block, dict)
                and block.get("type") == "text"
                and isinstance(block.get("text"), str)
            ):
                next_block = dict(block)
                next_block["text"] = stripped_text
                metadata = dict(next_block.get("metadata") or {})
                context = dict(metadata.get("context") or {})
                context.setdefault("codex_mode", marker_mode)
                context.setdefault("completion_policy", marker_mode)
                context.setdefault("mode_preset", f"codex.{marker_mode}")
                context.setdefault("workflow_preset", f"codex.{marker_mode}")
                if marker_mode == "goal":
                    context.setdefault("goal_mode", True)
                metadata["context"] = context
                next_block["metadata"] = metadata
                patched_input.append(next_block)
                marker_applied = True
                continue
            patched_input.append(block)
        validated = validated.model_copy(
            update={
                "input": patched_input,
                **(
                    {"planning_mode": True}
                    if marker_mode in {"plan", "spec"}
                    else {}
                ),
            },
        )
    if text:
        from runtime.sensing.gateway.slash_command_expansion import (
            maybe_expand_slash_command,
        )

        text = maybe_expand_slash_command(text)
    if _should_default_planning_mode(text, validated):
        validated = validated.model_copy(update={"planning_mode": True})
    # Auto-dispatch to a built-in topology when the user message
    # clearly matches one of the multi-agent categories. Single-
    # agent ReAct stays the default; this only fires for
    # "调研 / 代码评审 / 重构 / 调试"-shaped messages without
    # an explicit topology_id.
    _auto_topology = _should_default_topology(text, validated)
    if _auto_topology is not None:
        validated = validated.model_copy(update={"topology_id": _auto_topology})
        _logger.info(
            "auto-dispatch to topology %r based on user message",
            _auto_topology,
        )

    # Smart model routing — auto-route trivial / simple turns to
    # the cheap tier. Complex / research / topology / code-mode
    # turns stay on the user's primary. Explicit ``model`` pins
    # bypass this entirely.
    try:
        from runtime.core.cerebrum.todo_protocol import (
            should_require_todo_protocol,
        )
        from runtime.core.cerebrum.turn_complexity import (
            estimate_turn_complexity,
            select_model_for_complexity,
        )
        from runtime.sensing.gateway.realtime_turn_routing import (
            looks_like_tool_intent,
        )

        _meta = _input_metadata(validated)
        _user_ctx_for_complexity = (
            _meta.get("context") if isinstance(_meta.get("context"), dict) else _meta
        )
        _mode_str = (
            _user_ctx_for_complexity.get("mode")
            if isinstance(_user_ctx_for_complexity, dict)
            else None
        ) or ""
        _capability_mode_str = (
            _user_ctx_for_complexity.get("capability_mode")
            if isinstance(_user_ctx_for_complexity, dict)
            else None
        ) or ""
        _verdict = estimate_turn_complexity(
            text,
            has_explicit_model=bool(
                "model" in getattr(validated, "model_fields_set", set()) and validated.model
            ),
            has_topology=bool(getattr(validated, "topology_id", None)),
            is_code_mode=bool(_mode_str == "code" or _capability_mode_str),
            is_swarm_mode=str(_mode_str).lower() in {"swarm", "swarms"},
            is_research_mode=str(_mode_str).lower() in {"deep", "deep_research", "research"},
            is_goal_mode=bool(getattr(validated, "planning_mode", False)),
            looks_tool_intent=looks_like_tool_intent(text),
            requires_todo_protocol=should_require_todo_protocol(
                text,
                _user_ctx_for_complexity,
            ),
        )
        # AI mode override (Marvis-style efficiency / privacy).
        # Privacy mode pins every turn to ``local`` regardless of
        # complexity so no data leaves the box. Efficiency is a
        # pass-through.
        try:
            from runtime.core.cerebrum.ai_mode import apply_ai_mode_override

            _verdict = apply_ai_mode_override(_verdict)
        except ImportError:  # noqa: BLE001 — ai mode is optional
            pass
        _routed_model, _route_reason = select_model_for_complexity(
            _verdict,
            user_model=validated.model,
        )
        if _routed_model:
            validated = validated.model_copy(update={"model": _routed_model})
            _logger.info(
                "smart routing: %s → %s (%s)",
                text[:60].replace("\n", " "),
                _routed_model,
                _route_reason,
            )
    except Exception as exc:  # noqa: BLE001 — smart routing is best-effort; never block a turn
        _logger.debug("smart routing skipped: %s", exc, exc_info=True)

    # ── PHASE 2 · thread setup + turn registration ─────────────────
    # Sweep any background command watchers left running from a
    # previous turn on this thread. They're allowed to outlive
    # their own turn (long shells finishing after the LLM said
    # done) but mustn't bleed into the brand-new conversation
    # the user just started.
    with contextlib.suppress(Exception):
        await runtime._reap_stale_background_tasks(thread_id)

    log = await runtime._ensure_thread(thread_id, emitter)
    runtime._require_thread_owner(
        log,
        getattr(emitter, "actor_id", None),
    )

    turn = Turn(threadId=thread_id, params=validated)
    # Register the turn id with the connection's interrupt
    # registry before emitting turn/started. This closes the race
    # where a client's turn/interrupt (matched by id, not sequence)
    # arrives before our first poll.
    emitter.register_turn(turn.id)
    try:
        log.turn_started(thread_id, turn)
        runtime._active_turn_ids.add(turn.id)
        await emitter.notify(
            ServerMethod.TURN_STARTED,
            {
                "threadId": thread_id,
                "turn": turn.model_dump(by_alias=True, mode="json"),
            },
        )
        runtime._record_task_run_started(turn, text=text, params=validated)

        # ── PHASE 3 · prompt hooks + user message anchor ───────────
        from runtime.platform.process.session import current_session
        from runtime.safety.hooks.runner import dispatch_user_prompt

        prompt_decision = dispatch_user_prompt(
            prompt_text=text,
            thread_id=thread_id,
            session=current_session(),
        )
        if prompt_decision.cancelled:
            err = ErrorItem(message=prompt_decision.reason or "prompt rejected")
            turn.items.append(err)
            await runtime._emit_item_started(turn, log, emitter, err)
            err.status = ItemStatus.FAILED
            await runtime._emit_item_completed(turn, log, emitter, err)
            turn.status = TurnStatus.FAILED
            log.turn_completed(thread_id, turn.id, turn.status)
            # ``intent`` isn't built yet on the prompt-rejected path;
            # the snapshot helper accepts None so the legacy thread
            # store still records the failed turn for the sidebar.
            runtime._record_failed_turn_proposal(
                turn,
                intent=None,
                failure_source="prompt_rejected",
            )
            runtime._snapshot_to_thread_store(thread_id, log, None)
            return turn
        if prompt_decision.modified_prompt is not None:
            text = prompt_decision.modified_prompt
        if not text:
            err = ErrorItem(message="empty input")
            turn.items.append(err)
            await runtime._emit_item_started(turn, log, emitter, err)
            await runtime._emit_item_completed(turn, log, emitter, err)
            turn.status = TurnStatus.FAILED
            log.turn_completed(thread_id, turn.id, turn.status)
            runtime._record_failed_turn_proposal(
                turn,
                intent=None,
                failure_source="empty_input",
            )
            return turn

        # Record the user's message as a first-class turn item so
        # ``_flatten_turns_to_messages`` and the realtime adapter
        # both see a HumanMessage anchor. Without this the sidebar
        # title falls back to empty and the chat history starts
        # with the AI's reply only.
        try:
            from runtime.protocol import UserMessageItem

            user_item = UserMessageItem(
                text=text,
                attachments=_input_attachments(validated.input),
            )
            turn.items.append(user_item)
            await runtime._emit_item_started(turn, log, emitter, user_item)
            user_item.status = ItemStatus.COMPLETED
            await runtime._emit_item_completed(turn, log, emitter, user_item)
        except Exception:  # noqa: BLE001
            # Non-fatal: react loop still runs without the anchor.
            _logger.debug("user-message anchor skipped", exc_info=True)

        # ── PHASE 4 · intent build + resume check ──────────────────
        conversation_messages: list[dict[str, str]] = []
        with contextlib.suppress(Exception):
            conversation_messages = _conversation_messages_for_react(log.replay())

        intent = _build_intent(
            text,
            validated,
            workspaces=runtime._workspaces,
            thread_store=runtime._thread_store,
            allow_client_auto_approve=runtime._allow_client_auto_approve,
            conversation_messages=conversation_messages,
        )
        _inject_cowork_turn_plan(
            runtime,
            thread_id=thread_id,
            text=text,
            intent=intent,
        )
        confirmed_resume_intent = await runtime._consume_confirmed_resume_intent(thread_id, text)
        if confirmed_resume_intent is not None:
            intent.user_context["resume_intent"] = confirmed_resume_intent
        resume_intent = intent.user_context.get("resume_intent")
        if isinstance(resume_intent, dict) and resume_intent.get("requires_confirmation") is True:
            await runtime._record_pending_resume_intent(thread_id, resume_intent)
            await runtime._emit_agent_message(
                turn,
                log,
                emitter,
                _resume_confirmation_text(resume_intent),
            )
            turn.status = TurnStatus.COMPLETED
            log.turn_completed(thread_id, turn.id, turn.status)
            await runtime._maybe_compact(thread_id, log, emitter)
            runtime._snapshot_to_thread_store(thread_id, log, intent)
            return turn

        # ── PHASE 5 · execution dispatch (topology/fast/react) ─────
        loop = asyncio.get_running_loop()
        gateway_provider = GatewayApprovalProvider(
            emitter,
            loop,
            thread_id=thread_id,
            turn_id=turn.id,
            trace_store=runtime._trace_store,
        )
        provider: ApprovalProvider = runtime._wrap_with_policy(gateway_provider)
        agent = runtime._resolve_agent(validated)

        try:
            topology_id = getattr(validated, "topology_id", None)
            # Mode-level guard: single-agent modes MUST NOT route
            # through ``_drive_team_topology`` even if a leftover
            # ``topology_id`` slipped through (e.g. settings
            # persisted from a prior swarm turn, an old front-end
            # build, or ``auto-dispatch`` on a stale runtime). The
            # explicit user-facing mode is the source of truth:
            #   chat / react / deep  → single-agent ReAct
            #   swarm                → swarm topology
            # Anything that lands in the first bucket here gets
            # its topology cleared so the swarm path stays
            # unreachable from the Agent / Inspiration modes.
            _mode_str = (_turn_mode(validated) or "").lower()
            if topology_id and _mode_str in {"chat", "react", "deep"}:
                _logger.info(
                    "ignoring topology_id %r in single-agent mode %r",
                    topology_id,
                    _mode_str,
                )
                topology_id = None
                validated = validated.model_copy(
                    update={"topology_id": None},
                )

            # 能力包 / Meta-Skill soft hand-off: if the user's text
            # strongly matches one of the curated workflow packs,
            # surface a hint so the user can switch to the catalog
            # page. ReAct still runs — the hint is informational,
            # not a redirect, until the graph runtime is wired
            # through the realtime gateway.
            try:
                from runtime.memory.skills_lib.meta_skill import match_meta_skill

                _matched = match_meta_skill(text)
            except Exception:  # noqa: BLE001
                _logger.debug("meta-skill match failed", exc_info=True)
                _matched = None
            if _matched is not None:
                await emitter.notify(
                    ServerMethod.TURN_META_SKILL_HINT,
                    {
                        "threadId": thread_id,
                        "turnId": turn.id,
                        "name": _matched.name,
                        "description": _matched.description,
                        "kind": _matched.kind,
                        "affinity": list(_matched.affinity),
                        "stepCount": len(_matched.steps),
                    },
                )

            if runtime._is_local_partner(agent):
                # LocalPartner agent: the user picked a registered external
                # coding-agent CLI (Claude Code / Codex). Drive that CLI
                # directly with their own login instead of the LLM loop. The
                # agent identity is the strongest signal, so this wins even
                # over a stale topology_id.
                await runtime._drive_local_partner(
                    turn,
                    log,
                    emitter,
                    intent,
                    agent,
                    provider,
                    text=text,
                )
            elif (
                str((intent.user_context or {}).get("serve_mesh") or "").strip()
                == "1"
                or (
                    bool((intent.user_context or {}).get("cowork_is_multi"))
                    and len((intent.user_context or {}).get("cowork_responders") or []) > 1
                )
            ):
                # 蜂群 / 冒泡: the user picked the leaderless group mode. Fan the
                # message out to every member agent in parallel — each chimes in
                # with its own persona bubble ("boss speaks, everyone replies").
                # No topology_id needed; degrades to single-agent if <2 members.
                await runtime._drive_group_fanout(
                    turn,
                    log,
                    emitter,
                    intent,
                    text=text,
                )
            elif topology_id:
                # Explicit topology / 集群: orchestrated team — _drive_swarm_mesh
                # auto-picks the boids/SignalBus parallel mesh vs the sequential
                # TeamRunner by the planned graph's shape.
                await runtime._drive_swarm_mesh(
                    turn,
                    log,
                    emitter,
                    intent,
                    text=text,
                    topology_id=topology_id,
                )
            elif runtime._should_use_reflection_fast_path(
                text,
                validated,
                conversation_messages=conversation_messages,
            ):
                await runtime._drive_reflection_fast_path(
                    turn,
                    log,
                    emitter,
                    intent,
                    agent,
                    model=validated.model,
                )
            else:
                await runtime._drive_react(
                    turn,
                    log,
                    emitter,
                    intent,
                    provider,
                    agent,
                    model=validated.model,
                )
        except Exception as exc:
            _logger.exception("CerebrumRuntime: react loop crashed")
            err = ErrorItem(message=str(exc) or exc.__class__.__name__)
            turn.items.append(err)
            await runtime._emit_item_started(turn, log, emitter, err)
            await runtime._emit_item_completed(turn, log, emitter, err)
            turn.status = TurnStatus.FAILED
            log.turn_completed(thread_id, turn.id, turn.status)
            runtime._record_failed_turn_proposal(
                turn,
                intent=intent,
                failure_source="react_exception",
            )
            runtime._snapshot_to_thread_store(thread_id, log, intent)
            return turn

        # ── PHASE 6 · status finalization + snapshot ───────────────
        if turn.status == TurnStatus.INTERRUPTED:
            # Drive-react set this when an interrupt was polled; we
            # respect it rather than flipping back to completed.
            log.turn_completed(thread_id, turn.id, turn.status)
            runtime._snapshot_to_thread_store(thread_id, log, intent)
            return turn
        if turn.status == TurnStatus.FAILED:
            log.turn_completed(thread_id, turn.id, turn.status)
            runtime._record_failed_turn_proposal(
                turn,
                intent=intent,
                failure_source="react_failed",
            )
            runtime._snapshot_to_thread_store(thread_id, log, intent)
            return turn

        if _turn_has_failed_code_verification(turn):
            turn.status = TurnStatus.FAILED
            log.turn_completed(thread_id, turn.id, turn.status)
            runtime._record_failed_turn_proposal(
                turn,
                intent=intent,
                failure_source="verification_failed",
            )
            runtime._snapshot_to_thread_store(thread_id, log, intent)
            return turn

        if _turn_has_unverified_code_changes(turn):
            code_change_paths = _code_change_paths(turn)
            verification_plan = _verification_plan_for_code_paths(
                code_change_paths,
                intent,
            )
            try:
                from runtime.safety.evolution.auto_verifier import (
                    run_highest_priority_verification,
                )

                auto_item = run_highest_priority_verification(
                    verification_plan,
                    sandbox_policy=validated.sandbox_policy,
                )
            except Exception:  # noqa: BLE001 - auto verification is best-effort
                auto_item = None
            if auto_item is not None:
                turn.items.append(auto_item)
                await runtime._emit_item_started(turn, log, emitter, auto_item)
                await runtime._emit_item_completed(turn, log, emitter, auto_item)
                if auto_item.status == ItemStatus.COMPLETED:
                    turn.status = TurnStatus.COMPLETED
                    log.turn_completed(thread_id, turn.id, turn.status)
                    runtime._record_successful_turn_example(turn, intent=intent)
                    await runtime._maybe_compact(thread_id, log, emitter)
                    runtime._snapshot_to_thread_store(thread_id, log, intent)
                    return turn
                turn.status = TurnStatus.FAILED
                log.turn_completed(thread_id, turn.id, turn.status)
                runtime._record_failed_turn_proposal(
                    turn,
                    intent=intent,
                    failure_source="verification_failed",
                )
                runtime._snapshot_to_thread_store(thread_id, log, intent)
                return turn

            verification_item = VerificationItem(
                command="verification required",
                kind="manual",
                status=ItemStatus.FAILED,
                exit_code=None,
                summary=(
                    "Code changes were produced but no verification step "
                    "was recorded before final answer."
                ),
                stdout_tail=_verification_plan_stdout_tail(verification_plan),
                stderr_tail=None,
                related_files=code_change_paths,
                related_change_item_ids=_file_change_item_ids(turn),
            )
            turn.items.append(verification_item)
            await runtime._emit_item_started(turn, log, emitter, verification_item)
            await runtime._emit_item_completed(turn, log, emitter, verification_item)
            turn.status = TurnStatus.FAILED
            log.turn_completed(thread_id, turn.id, turn.status)
            runtime._record_failed_turn_proposal(
                turn,
                intent=intent,
                failure_source="verification_required",
            )
            runtime._snapshot_to_thread_store(thread_id, log, intent)
            return turn

        if not _turn_has_observable_output(turn):
            err = ErrorItem(
                message=(
                    "模型执行结束但没有返回任何可见输出。"
                    "请重试，或切换到其他可用模型后再试。"
                ),
                error_info={
                    "code": "empty_model_output",
                    "model": validated.model,
                },
            )
            turn.items.append(err)
            await runtime._emit_item_started(turn, log, emitter, err)
            await runtime._emit_item_completed(turn, log, emitter, err)
            turn.status = TurnStatus.FAILED
            log.turn_completed(thread_id, turn.id, turn.status)
            runtime._record_failed_turn_proposal(
                turn,
                intent=intent,
                failure_source="empty_model_output",
            )
            runtime._snapshot_to_thread_store(thread_id, log, intent)
            return turn

        turn.status = TurnStatus.COMPLETED
        log.turn_completed(thread_id, turn.id, turn.status)
        runtime._record_successful_turn_example(turn, intent=intent)
        await runtime._maybe_compact(thread_id, log, emitter)
        runtime._snapshot_to_thread_store(thread_id, log, intent)
        return turn
    finally:
        runtime._record_task_run_finished(turn)
        runtime._active_turn_ids.discard(turn.id)
        emitter.unregister_turn(turn.id)


async def _record_pending_resume_intent(
    runtime: CerebrumRuntime,
    thread_id: str,
    resume_intent: dict[str, Any],
) -> None:
    async with runtime._resume_intents_lock:
        runtime._pending_resume_intents[thread_id] = dict(resume_intent)
    if runtime._trace_store is None:
        return
    with contextlib.suppress(Exception):
        runtime._trace_store.record_resume_request(
            thread_id=thread_id,
            checkpoint_id=int(resume_intent.get("checkpoint_id") or 0),
            task_id=resume_intent.get("task_id"),
            status="pending",
            intent=resume_intent,
        )


async def _consume_confirmed_resume_intent(
    runtime: CerebrumRuntime,
    thread_id: str,
    text: str,
) -> dict[str, Any] | None:
    checkpoint_id = _parse_resume_confirmation(text)
    if checkpoint_id is None:
        return None
    async with runtime._resume_intents_lock:
        pending = runtime._pending_resume_intents.get(thread_id)
        pending_request_id: int | None = None
        if not isinstance(pending, dict) and runtime._trace_store is not None:
            with contextlib.suppress(Exception):
                request = runtime._trace_store.latest_pending_resume_request(thread_id=thread_id)
                if isinstance(request, dict):
                    pending = request.get("intent")
                    pending_request_id = _safe_int(request.get("id"))
        if not isinstance(pending, dict):
            return None
        if _safe_int(pending.get("checkpoint_id")) != checkpoint_id:
            return None
        runtime._pending_resume_intents.pop(thread_id, None)
    if runtime._trace_store is not None:
        with contextlib.suppress(Exception):
            confirmed = runtime._trace_store.confirm_resume_request(
                thread_id=thread_id,
                checkpoint_id=checkpoint_id,
                confirmation_text=f"确认恢复 checkpoint #{checkpoint_id}",
            )
            if isinstance(confirmed, dict):
                pending = (
                    confirmed.get("intent")
                    if isinstance(confirmed.get("intent"), dict)
                    else pending
                )
                pending_request_id = _safe_int(confirmed.get("id")) or pending_request_id
            if pending_request_id is not None:
                runtime._trace_store.consume_resume_request(pending_request_id)
    return _execution_resume_intent(pending, checkpoint_id)
