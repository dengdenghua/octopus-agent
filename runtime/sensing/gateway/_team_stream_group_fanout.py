"""Group fan-out stream driver — 蜂群 / 冒泡 cowork dispatch.

Extracted from ``realtime_team_stream.py``. Fans a message out to every
member agent in parallel and emits each persona reply as its own
group-chat bubble. Falls back to single-agent ReAct when the room has
<2 member agents or nobody answers, so the turn never stalls.

Public API (re-exported by ``realtime_team_stream``):

* ``_drive_group_fanout`` — fan the message out to every member agent.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import threading
import time
from typing import Any

from runtime.memory.cowork.collaboration_collectors import (
    CollaborationSteeringConflictError,
)
from runtime.memory.threads.event_log import EventLog
from runtime.platform.models import ParsedIntent
from runtime.protocol import (
    AgentMessageItem,
    ItemStatus,
    McpToolCallItem,
    ReasoningItem,
    ServerMethod,
    SubagentItem,
    Turn,
)
from runtime.sensing.gateway.realtime_approval import GatewayApprovalProvider
from runtime.sensing.gateway.realtime_gateway import EventEmitter

_logger = logging.getLogger(__name__)


def _extract_mention_target(body: str, roster_members: list[dict[str, Any]]) -> str | None:
    """③ 从回复正文里解析 @ 到的成员名，用于气泡"回应 @谁"标注。"""
    if not body or not roster_members:
        return None
    for m in roster_members:
        display = str(m.get("display_name") or m.get("name") or "")
        parts = display.split()
        cands = {
            display,
            parts[0] if parts else display,
            display.replace(" ", ""),
        }
        if any(c and ("@" + c) in body for c in cands):
            return display
    return None


# ── 成员失败的错误净化 ──────────────────────────────────────────────
# 蜂群把成员异常(ConnectError/超时/429/权限)原样打进聊天气泡会让用户看到
# 一堆 SSL/traceback 噪音(thread t0Wn5Zhvh3VUFwoAR2uP4M: "⚠️ 钊审财 · 财报
# 研究员 未能回应 · ConnectError: [SSL: UNEXPECTED_EOF_WHILE_READING] …")。
# 用户需要知道"谁没答上、要不要紧",不需要底层异常串。这里把常见异常归类成
# 一句友好话术;原始细节只进日志/审计,不进聊天。
_SANITIZED_ERROR_HINTS: tuple[tuple[str, str], ...] = (
    ("ssl", "网络连接中断"),
    ("unexpected_eof", "网络连接中断"),
    ("timeout", "响应超时"),
    ("timed out", "响应超时"),
    ("connection refused", "服务未启动或拒绝连接"),
    ("connection reset", "连接被重置"),
    ("rate limit", "触发限流(稍后自动重试)"),
    ("429", "触发限流(稍后自动重试)"),
    ("quota", "额度不足"),
    ("auth", "鉴权失败"),
    ("permission", "权限不足"),
    ("model not found", "模型不可用"),
    ("model not found or", "模型不可用"),
    ("no model", "模型未配置"),
    ("context length", "上下文超长"),
    ("exceeds", "上下文超长"),
)


def _friendly_member_error(error: Any) -> str:
    raw = str(error or "").strip()
    if not raw:
        return "未能产生回复"
    lower = raw.lower()
    for hint, label in _SANITIZED_ERROR_HINTS:
        if hint in lower:
            return label
    # 兜底:绝不在气泡里展示原始异常堆栈/长串,只给类型名的简短形式。
    name = raw.splitlines()[0].strip()
    if len(name) <= 60:
        return f"异常({name})"
    return "未知异常(详见审计日志)"


def _fanout_member_context(ctx: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """Clone the parent turn contract for every fan-out member.

    Group fan-out previously forwarded only the generated chat prompt.  That
    made a member silently fall back to its default mode even when the user had
    selected research/build/audit for this turn.  Keep the structured context
    for runtimes that consume it and a compact prompt addendum for lightweight
    persona lanes that only consume text.
    """

    member_context = dict(ctx)
    # Fanout lanes produce short conversational bubbles. The stack runner uses
    # this trusted internal flag to bypass JSON task planning and tool setup.
    member_context["direct_conversation_reply"] = True
    # These are group-driver implementation details, not child work policy.
    member_context.pop("agent_roster", None)
    member_context.pop("conversation_messages", None)
    member_context.pop("cowork_member_context_messages", None)
    member_context.pop("cowork_member_context_authorizations", None)
    member_context.pop("cowork_durable_context", None)
    # The context steward supplies an explicit, bounded history slice below.
    # Disable every implicit parent/per-role memory injection so it cannot
    # silently exceed that budget or bypass a cowork ContextGrant.
    member_context["context_steward_managed"] = True
    member_context["share_history"] = False

    from runtime.core.cerebrum._react_context_code import (
        _build_code_agent_mode_prompt,
        _build_personal_agent_mode_prompt,
        _build_workflow_preset_prompt,
    )
    from runtime.execution.misc.skill_policy import is_enforced_read_only_context

    sections: list[str] = []
    workflow_preset = str(member_context.get("workflow_preset") or "").strip()
    if workflow_preset:
        rendered = _build_workflow_preset_prompt(workflow_preset)
        if rendered:
            sections.append(rendered)
    agent_mode = str(member_context.get("agent_mode") or "").strip()
    if agent_mode:
        sections.append(_build_code_agent_mode_prompt(agent_mode))
    personal_mode = str(member_context.get("personal_mode") or "").strip().lower()
    if personal_mode:
        rendered = _build_personal_agent_mode_prompt(personal_mode)
        if rendered:
            sections.append(rendered)
        elif personal_mode == "research":
            sections.append(
                "<personal-mode>当前任务类型: research。先搜索、读取并交叉核对证据;"
                "优先一手来源,不要把未经验证的印象写成结论。</personal-mode>"
            )
    personal_instructions = str(member_context.get("personal_instructions") or "").strip()
    if personal_instructions:
        sections.append(
            "<inherited-personal-instructions>"
            + personal_instructions[:2000]
            + "</inherited-personal-instructions>"
        )
    mode_contract = str(member_context.get("mode_contract") or "").strip()
    if mode_contract:
        sections.append(
            "<inherited-mode-contract>" + mode_contract[:2000] + "</inherited-mode-contract>"
        )

    if is_enforced_read_only_context(member_context):
        member_context["tool_allowlist_read_only"] = True
    policy_prompt = "\n".join(sections)
    existing_addendum = str(member_context.get("system_addendum") or "").strip()
    if policy_prompt:
        member_context["system_addendum"] = "\n\n".join(
            part for part in (existing_addendum, policy_prompt) if part
        )
    return member_context, policy_prompt


def _select_fanout_members(
    ctx: dict[str, Any],
    members: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Apply the server-owned addressing plan before any model is launched.

    A natural-language group request or swarm turn intentionally includes the
    active roster. Explicit ``@agent`` mentions are narrower: only the validated
    responders may receive context or consume a model call.  The lifecycle
    overwrites ``cowork_plan`` and ``cowork_responders`` from durable membership,
    so this function never trusts a client-provided roster expansion.
    """

    available = [member for member in members if isinstance(member, dict)]
    plan = ctx.get("cowork_plan")
    addressed = plan.get("addressed") if isinstance(plan, dict) else None
    raw_responders = ctx.get("cowork_responders")
    responders = (
        [str(value).strip() for value in raw_responders if str(value or "").strip()]
        if isinstance(raw_responders, list)
        else []
    )
    has_explicit_targets = isinstance(addressed, list) and bool(addressed)
    if has_explicit_targets:
        allowed = set(responders)
        selected = [member for member in available if str(member.get("name") or "") in allowed]
        reason = "explicit_mentions"
    else:
        selected = available
        reason = "group_request_or_mode"
    selected_ids = [str(member.get("name") or "") for member in selected]
    selected_set = set(selected_ids)
    excluded_ids = [
        str(member.get("name") or "")
        for member in available
        if str(member.get("name") or "") not in selected_set
    ]
    return selected, {
        "schema": "octopus.cowork_member_routing.v1",
        "reason": reason,
        "available_member_count": len(available),
        "selected_member_count": len(selected),
        "selected_agent_ids": selected_ids,
        "excluded_agent_ids": excluded_ids,
    }


async def _drive_group_fanout(
    runtime: Any,
    turn: Turn,
    log: EventLog,
    emitter: EventEmitter,
    intent: ParsedIntent,
    *,
    text: str,
) -> None:
    """蜂群 / 冒泡: fan the message out to every member agent in parallel and
    emit each persona reply as its own group-chat bubble — the "boss speaks,
    everyone chimes in" experience. Falls back to single-agent ReAct when the
    room has <2 member agents or nobody answers, so the turn never stalls.
    """
    ctx = getattr(intent, "user_context", None) or {}
    raw_team_pattern = ctx.get("team_pattern")
    team_pattern = dict(raw_team_pattern) if isinstance(raw_team_pattern, dict) else {}
    try:
        from runtime.platform.process.session import Session, current_session

        parent_session = current_session()
        if parent_session is None:
            # ``TurnParams.owner_actor_id`` / ``tenant_id`` are server-only
            # fields stamped by RealtimeGateway. This gives worker-thread
            # members a trusted principal without trusting user_context.
            params = getattr(turn, "params", None)
            actor = str(getattr(params, "owner_actor_id", None) or "").strip()
            tenant = str(getattr(params, "tenant_id", None) or "").strip()
            if actor and tenant:
                metadata = dict(ctx)
                metadata["tenant_id"] = tenant
                parent_session = Session(
                    actor=actor,
                    thread_id=turn.thread_id,
                    conversation_id=turn.thread_id,
                    turn_id=turn.id,
                    metadata=metadata,
                )
    except (ImportError, LookupError):
        parent_session = None
    member_context, _member_policy_prompt = _fanout_member_context(ctx)
    # Standard Coder members execute on worker threads, but approvals must
    # still round-trip through this parent realtime turn.  This object is
    # server-created and deliberately replaces any similarly named client key.
    group_gateway_provider = GatewayApprovalProvider(
        emitter,
        asyncio.get_running_loop(),
        thread_id=str(ctx.get("thread_id") or turn.thread_id),
        turn_id=turn.id,
        trace_store=runtime._trace_store,
    )
    member_context["_codex_approval_provider"] = runtime._wrap_with_policy(group_gateway_provider)
    roster = ctx.get("agent_roster") or []
    raw_authorizations = ctx.get("cowork_member_context_authorizations")
    member_authorizations = raw_authorizations if isinstance(raw_authorizations, dict) else {}
    members = [
        {
            "name": str(r.get("agent_id")),
            "display_name": str(r.get("display_name") or r.get("agent_id")),
            "description": str(r.get("description") or ""),
            "affinity": list(r.get("affinity") or [])
            if isinstance(r.get("affinity"), list)
            else [],
            "authorization": dict(member_authorizations.get(str(r.get("agent_id"))) or {}),
        }
        for r in roster
        if isinstance(r, dict) and r.get("agent_id")
    ]
    members, fanout_routing = _select_fanout_members(ctx, members)
    from runtime.execution.agents.team_patterns import pattern_member_role

    pattern_id = str(team_pattern.get("id") or "parallel_roundtable")
    for index, member in enumerate(members):
        role = pattern_member_role(pattern_id, index)
        # Independent candidate generation should not inherit conversational
        # anchoring. Critics/verifiers remain selective so they can use prior
        # decisions; the current debate transcript is still passed explicitly.
        member["context_mode"] = (
            "isolated" if role in {"explorer", "proposer", "alternative"} else "selective"
        )
    context_plan = None
    try:
        from runtime.memory.cowork.context_steward import plan_group_context

        raw_messages = ctx.get("conversation_messages")
        raw_histories = ctx.get("cowork_member_context_messages")
        durable_context = ctx.get("cowork_durable_context")
        context_plan = plan_group_context(
            text,
            members,
            list(raw_messages) if isinstance(raw_messages, list) else [],
            member_histories=(
                {
                    str(agent_id): list(history)
                    for agent_id, history in raw_histories.items()
                    if isinstance(history, list)
                }
                if isinstance(raw_histories, dict)
                else None
            ),
            durable_context=(dict(durable_context) if isinstance(durable_context, dict) else None),
            selection_engine=getattr(runtime, "_cowork_context_engine", None),
        )
    except Exception as exc:  # noqa: BLE001 — current-message-only is the safe fallback
        _logger.warning("cowork context planning failed: %s", exc, exc_info=True)

    team_trace_item: McpToolCallItem | None = None
    member_trace_items: dict[str, SubagentItem] = {}
    team_trace_started = 0.0
    planned_group_capacity: dict[str, Any] = {}
    collaboration_run_id: str | None = None
    collaboration_run_worker = f"realtime:{os.getpid()}:{turn.id}"

    def _run_store() -> Any:
        store = getattr(runtime, "_collaboration_store", None)
        if store is not None:
            return store
        return getattr(getattr(runtime, "_app_state", None), "collaboration_store", None)

    async def _emit(
        body: str,
        *,
        display_name: str | None = None,
        agent_id: str | None = None,
        icon: str | None = None,
        reply_to: str | None = None,
    ) -> None:
        # Tag the bubble with its real author so the UI shows that member's
        # avatar + name instead of the turn leader's. Use the shared resolver so
        # the URL carries ``?v=<mtime>`` — that cache-busts when an agent's
        # avatar file changes (e.g. swapping in a brand logo).
        avatar_url: str | None = None
        if agent_id:
            try:
                from runtime.sensing.gateway.agents_router import _avatar_url_for

                avatar_url = _avatar_url_for(agent_id)
            except Exception:  # noqa: BLE001 — avatar is decoration; never break the turn
                avatar_url = None
            avatar_url = avatar_url or f"/api/agents/{agent_id}/avatar"
        item = AgentMessageItem(
            text=body,
            status=ItemStatus.COMPLETED,
            agent_display_name=display_name,
            agent_avatar_url=avatar_url,
            agent_icon=icon,
            reply_to=reply_to,
        )
        store = _run_store()
        enqueue = getattr(store, "enqueue_collaboration_delivery", None)
        if collaboration_run_id and callable(enqueue):
            delivery_id = f"cowork-delivery:{item.id}"
            try:
                from runtime.sensing.gateway.collaboration_delivery_outbox import (
                    persist_collaboration_delivery,
                )

                delivery = enqueue(
                    delivery_id=delivery_id,
                    run_id=str(collaboration_run_id or ""),
                    session_id=turn.thread_id,
                    turn_id=turn.id,
                    payload={
                        "schema": "octopus.collaboration_delivery_payload.v1",
                        "item": item.model_dump(by_alias=True, mode="json"),
                    },
                )
                persist_collaboration_delivery(
                    store,
                    delivery,
                    log=log,
                    worker_id=collaboration_run_worker,
                )
            except Exception as exc:  # noqa: BLE001 — retained for automatic/manual retry
                _logger.warning(
                    "cowork reply delivery queued for retry (%s): %s",
                    delivery_id,
                    exc,
                    exc_info=True,
                )
                return
        else:
            try:
                log.item_started(turn.thread_id, turn.id, item, durable=True)
                log.item_completed(turn.thread_id, turn.id, item, durable=True)
            except Exception as exc:  # noqa: BLE001 — do not announce non-durable output
                _logger.warning("cowork reply event-log write failed: %s", exc, exc_info=True)
                return
        turn.items.append(item)
        payload = {
            "threadId": turn.thread_id,
            "turnId": turn.id,
            "item": item.model_dump(by_alias=True, mode="json"),
        }
        with contextlib.suppress(Exception):
            await emitter.notify(ServerMethod.ITEM_STARTED, payload)
            await emitter.notify(ServerMethod.ITEM_COMPLETED, payload)

    # Availability is roster state, not a reasoning task. Answer it once from
    # the server-owned active roster instead of launching every model and then
    # waiting for the slowest one to say "在线".
    from runtime.execution.agents.group_fanout import (
        format_group_presence_reply,
        is_group_presence_query,
    )

    if is_group_presence_query(text):
        await _emit(
            format_group_presence_reply(members),
            display_name="协作状态",
            icon="●",
        )
        return

    async def _fallback_to_react() -> None:
        loop = asyncio.get_running_loop()
        gateway_provider = GatewayApprovalProvider(
            emitter,
            loop,
            thread_id=intent.user_context.get("thread_id", turn.thread_id),
            turn_id=turn.id,
            trace_store=runtime._trace_store,
        )
        provider = runtime._wrap_with_policy(gateway_provider)
        from runtime.protocol.items import TurnParams

        agent = None
        with contextlib.suppress(Exception):
            agent = runtime._resolve_agent(
                TurnParams(threadId=turn.thread_id, input=[]),  # type: ignore[call-arg]
            )
        await runtime._drive_react(turn, log, emitter, intent, provider, agent)

    def _record_fallback_audit(reason: str, exc: BaseException | None = None) -> None:
        payload: dict[str, Any] = {
            "schema": "octopus.group_fanout_fallback.v1",
            "reason": reason,
            "fallback": "react",
        }
        if exc is not None:
            payload.update(
                {
                    "exception_type": type(exc).__name__,
                    "message": str(exc),
                }
            )
        with contextlib.suppress(Exception):
            audit_item = ReasoningItem(
                summary=["Group fanout fallback"],
                content=json.dumps(payload, ensure_ascii=False, sort_keys=True),
                status=ItemStatus.COMPLETED,
            )
            turn.items.append(audit_item)
            log.item_started(turn.thread_id, turn.id, audit_item)
            log.item_completed(turn.thread_id, turn.id, audit_item)

    async def _notify_started(item: Any) -> None:
        turn.items.append(item)
        with contextlib.suppress(Exception):
            log.item_started(turn.thread_id, turn.id, item)
        payload = {
            "threadId": turn.thread_id,
            "turnId": turn.id,
            "item": item.model_dump(by_alias=True, mode="json"),
        }
        with contextlib.suppress(Exception):
            await emitter.notify(ServerMethod.ITEM_STARTED, payload)

    async def _notify_completed(item: Any) -> None:
        with contextlib.suppress(Exception):
            log.item_completed(turn.thread_id, turn.id, item)
        payload = {
            "threadId": turn.thread_id,
            "turnId": turn.id,
            "item": item.model_dump(by_alias=True, mode="json"),
        }
        with contextlib.suppress(Exception):
            await emitter.notify(ServerMethod.ITEM_COMPLETED, payload)

    async def _drain_pending_deliveries() -> None:
        """Replay due results from interrupted prior turns before new work starts."""

        store = _run_store()
        due = getattr(store, "due_collaboration_deliveries", None)
        if not callable(due):
            return
        try:
            from runtime.sensing.gateway.collaboration_delivery_outbox import (
                persist_collaboration_delivery,
            )

            for delivery in due(session_id=turn.thread_id, limit=100):
                item = persist_collaboration_delivery(
                    store,
                    delivery,
                    log=log,
                    worker_id=collaboration_run_worker,
                )
                payload = {
                    "threadId": str(delivery.get("session_id") or turn.thread_id),
                    "turnId": str(delivery.get("turn_id") or turn.id),
                    "item": item.model_dump(by_alias=True, mode="json"),
                }
                with contextlib.suppress(Exception):
                    await emitter.notify(ServerMethod.ITEM_STARTED, payload)
                    await emitter.notify(ServerMethod.ITEM_COMPLETED, payload)
        except Exception as exc:  # noqa: BLE001 — remaining rows stay queued
            _logger.warning("cowork delivery replay deferred: %s", exc, exc_info=True)

    def _finish_persistent_run(
        status: str,
        *,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        """Close the durable run without making observability a failure source."""

        if not collaboration_run_id:
            return
        store = _run_store()
        transition = getattr(store, "transition_collaboration_run", None)
        if not callable(transition):
            return
        try:
            read_collector = getattr(store, "collaboration_collector", None)
            close_collector = getattr(store, "close_collaboration_collector", None)
            collector = read_collector(collaboration_run_id) if callable(read_collector) else None
            if (
                isinstance(collector, dict)
                and collector.get("status") == "collecting"
                and callable(close_collector)
            ):
                close_collector(
                    collaboration_run_id,
                    status="cancelled" if status == "cancelled" else "failed",
                    reason=(
                        "collaboration cancelled by user"
                        if status == "cancelled"
                        else "parent fanout terminated before every registered member result arrived"
                    ),
                )
            transition(
                collaboration_run_id,
                status=status,
                result=result,
                error=error,
                worker_id=collaboration_run_worker,
                payload={"turn_id": turn.id},
            )
        except Exception as exc:  # noqa: BLE001 — trace persistence is best effort
            _logger.warning("cowork collaboration run finalization failed: %s", exc, exc_info=True)

    def _start_persistent_collector(group_members: list[dict[str, Any]]) -> None:
        """Register first-round member lanes before any worker can finish."""

        if not collaboration_run_id:
            return
        store = _run_store()
        create_collector = getattr(store, "create_collaboration_collector", None)
        if not callable(create_collector):
            return
        child_ids = [str(member.get("name") or "") for member in group_members]
        child_ids = [child_id for child_id in child_ids if child_id]
        if not child_ids:
            return
        try:
            create_collector(
                run_id=collaboration_run_id,
                child_ids=child_ids,
                completion_policy="all",
            )
        except Exception as exc:  # noqa: BLE001 - execution remains authoritative
            _logger.warning("cowork collaboration collector setup failed: %s", exc, exc_info=True)

    def _record_persistent_reply(reply: dict[str, Any]) -> bool:
        """Atomically persist a lane unless a newer correction superseded it."""

        if (
            not collaboration_run_id
            or int(reply.get("round") or 1) != 1
            or bool(reply.get("cancelled"))
        ):
            return True
        store = _run_store()
        record = getattr(store, "record_collaboration_collector_result", None)
        if not callable(record):
            return True
        child_id = str(reply.get("agent_id") or "")
        if not child_id:
            return True
        try:
            record(
                collaboration_run_id,
                child_id=child_id,
                status=(
                    "cancelled"
                    if bool(reply.get("cancelled"))
                    else "success"
                    if bool(reply.get("ok"))
                    else "failed"
                ),
                result={
                    "response_id": reply.get("response_id"),
                    "agent_id": child_id,
                    "display_name": reply.get("display_name"),
                    "reply": str(reply.get("reply") or "")[:16_000],
                    "error": str(reply.get("error") or "")[:4_000] or None,
                    "validation": reply.get("validation"),
                    "pattern_role": reply.get("pattern_role"),
                    "round": 1,
                    "context_delivery": reply.get("context_delivery"),
                    "session_compaction": reply.get("session_compaction"),
                    "steering_count": reply.get("steering_count", 0),
                    "steering_generation": reply.get("steering_generation"),
                    "steering_seq": reply.get("steering_seq", 0),
                },
                expected_generation=reply.get("steering_generation"),
                expected_steering_seq=reply.get("steering_seq", 0),
            )
        except CollaborationSteeringConflictError:
            # The correction won the transaction race. The fanout worker will
            # discard this obsolete reply and invoke the member again.
            return False
        except Exception as exc:  # noqa: BLE001 - execution remains authoritative
            _logger.warning(
                "cowork collaboration result persistence failed: %s",
                exc,
                exc_info=True,
            )
        return True

    async def _start_group_trace(
        group_members: list[dict[str, Any]],
        *,
        max_members: int,
        max_concurrency: int,
        scale_mode: str,
    ) -> None:
        """Expose lightweight cowork fanout as a first-class team run.

        Kimi-style swarm UX depends on the user seeing who was dispatched before
        the replies arrive. The fanout itself is still conversational, but the
        runtime now records a replayable parent ``team_swarm`` item plus one
        ``SubagentItem`` lane per member.
        """
        nonlocal team_trace_item, team_trace_started, collaboration_run_id
        if not group_members:
            return
        nonlocal planned_group_capacity
        team_trace_started = time.monotonic()
        dispatched_members = group_members[:max_members]
        planned_group_capacity = {
            "schema": "octopus.group_fanout_capacity.v1",
            "requested_members": len(group_members),
            "dispatched_members": len(dispatched_members),
            "dropped_members": max(0, len(group_members) - len(dispatched_members)),
            "max_members": max_members,
            "max_concurrency": max_concurrency,
            "concurrency": max(1, min(len(dispatched_members), max_concurrency)),
            "scale_mode": scale_mode,
            "capacity_tier": "kimi_scale"
            if len(group_members) >= 300
            else "large"
            if len(dispatched_members) >= 64
            else "team_scale"
            if len(dispatched_members) >= 16
            else "room_scale"
            if len(dispatched_members) >= 2
            else "single",
        }
        specs = []
        for index, member in enumerate(dispatched_members):
            planned_member = (
                context_plan.for_agent(member["name"]) if context_plan is not None else None
            )
            member_context_audit = (
                planned_member.audit_dict() if planned_member is not None else None
            )
            specs.append(
                {
                    "agent_id": member["name"],
                    "display_name": member["display_name"],
                    "role": "cowork",
                    "pattern_role": pattern_member_role(pattern_id, index),
                    "task": text[:500],
                    "context": member_context_audit,
                }
            )
        team_trace_item = McpToolCallItem(
            server="team",
            tool="team_swarm",
            arguments={
                "schema": "octopus.group_fanout_run.v1",
                "mode": "cowork_swarm",
                "message": text[:1000],
                "specs": specs,
                "capacity": planned_group_capacity,
                "pattern": team_pattern or None,
                "routing": fanout_routing,
                "context_plan": context_plan.audit_dict() if context_plan is not None else None,
            },
            status=ItemStatus.IN_PROGRESS,
        )
        store = _run_store()
        create_run = getattr(store, "create_collaboration_run", None)
        claim_run = getattr(store, "claim_collaboration_run", None)
        if callable(create_run) and callable(claim_run):
            candidate_run_id = f"cowork-fanout:{turn.id}"
            try:
                create_run(
                    run_id=candidate_run_id,
                    session_id=turn.thread_id,
                    room_id=str(ctx.get("cowork_room_id") or ""),
                    turn_id=turn.id,
                    kind="group_fanout",
                    input={
                        "schema": "octopus.group_fanout_run_input.v1",
                        "message": text[:1000],
                        "selected_agent_ids": [
                            str(member.get("name") or "") for member in dispatched_members
                        ],
                        "capacity": planned_group_capacity,
                        "pattern": team_pattern or None,
                        "routing": fanout_routing,
                        "context_plan": (
                            context_plan.audit_dict() if context_plan is not None else None
                        ),
                    },
                )
                claim_run(
                    candidate_run_id,
                    worker_id=collaboration_run_worker,
                    # A single member may wait up to 90 seconds and debate has
                    # at most three rounds. Leave room for scheduling overhead.
                    lease_seconds=360,
                )
                collaboration_run_id = candidate_run_id
            except Exception as exc:  # noqa: BLE001 — event log/UI still proceed
                _logger.warning(
                    "cowork collaboration run persistence failed: %s", exc, exc_info=True
                )
        if collaboration_run_id:
            # The browser uses this opaque coordinate to subscribe to the
            # durable collector. Keep it on the public team event rather than
            # asking the UI to guess which ledger row belongs to this turn.
            team_trace_item.arguments["collaboration_run_id"] = collaboration_run_id
        await _notify_started(team_trace_item)
        for member in dispatched_members:
            agent_id = member["name"]
            display = member["display_name"]
            item = SubagentItem(
                subagent_id=agent_id,
                role="cowork",
                name=display,
                codename=display,
                parent_item_id=team_trace_item.id,
                summary="waiting for cowork fanout reply",
                status=ItemStatus.IN_PROGRESS,
            )
            member_trace_items[agent_id] = item
            await _notify_started(item)

    async def _complete_group_trace(result: dict[str, Any]) -> None:
        cancelled = bool(result.get("cancelled"))
        replies = [reply for reply in result.get("replies", []) if isinstance(reply, dict)]
        by_agent = {str(reply.get("agent_id") or ""): reply for reply in replies}
        for agent_id, item in member_trace_items.items():
            reply = by_agent.get(agent_id, {})
            body = str(reply.get("reply") or "").strip()
            err = str(reply.get("error") or "").strip()
            ok = bool(reply.get("ok")) and bool(body)
            item.status = (
                ItemStatus.INTERRUPTED
                if bool(reply.get("cancelled"))
                else ItemStatus.COMPLETED
                if ok
                else ItemStatus.FAILED
            )
            item.summary = body[:2000] if body else None
            item.error = None if ok else (err or "empty cowork fanout reply")
            validation = reply.get("validation")
            item.iteration_count = max(
                1,
                int(validation.get("attempt_count") or 1) if isinstance(validation, dict) else 1,
            )
            await _notify_completed(item)
        if team_trace_item is not None:
            ok = bool(result.get("ok"))
            team_trace_item.status = (
                ItemStatus.INTERRUPTED
                if cancelled
                else ItemStatus.COMPLETED
                if ok
                else ItemStatus.FAILED
            )
            team_trace_item.result = {
                "schema": "octopus.group_fanout_result.v1",
                "collaboration_run_id": collaboration_run_id,
                "cancelled": cancelled,
                "count": result.get("count"),
                "spoke": result.get("spoke"),
                "attempt_count": result.get("attempt_count"),
                "quality_retry_count": result.get("quality_retry_count", 0),
                "recovered_after_retry_count": result.get("recovered_after_retry_count", 0),
                "dropped": result.get("dropped", 0),
                "capacity": result.get("capacity") or planned_group_capacity,
                "arbitration": result.get("arbitration"),
                "synthesis": result.get("synthesis"),
                "quality": result.get("quality"),
                "delivery": result.get("delivery"),
                "pattern": result.get("pattern") or team_pattern or None,
                "routing": result.get("routing") or fanout_routing,
                "context_plan": result.get("context_plan"),
                "replies": replies,
            }
            team_trace_item.error = None if ok else str(result.get("error") or "no member replied")
            team_trace_item.duration_ms = max(
                0,
                int((time.monotonic() - team_trace_started) * 1000),
            )
            await _notify_completed(team_trace_item)
        compact_result = {
            "schema": "octopus.group_fanout_durable_result.v1",
            "collaboration_run_id": collaboration_run_id,
            "ok": bool(result.get("ok")),
            "cancelled": cancelled,
            "count": result.get("count"),
            "spoke": result.get("spoke"),
            "attempt_count": result.get("attempt_count"),
            "quality_retry_count": result.get("quality_retry_count", 0),
            "recovered_after_retry_count": result.get("recovered_after_retry_count", 0),
            "dropped": result.get("dropped", 0),
            "capacity": result.get("capacity") or planned_group_capacity,
            "arbitration": result.get("arbitration"),
            "synthesis": result.get("synthesis"),
            "quality": result.get("quality"),
            "delivery": result.get("delivery"),
            "pattern": result.get("pattern") or team_pattern or None,
            "routing": result.get("routing") or fanout_routing,
            "context_plan": result.get("context_plan"),
            # Preserve identity/status for replay and recovery without copying
            # every potentially large response body into the lifecycle row.
            "outcomes": [
                {
                    "response_id": reply.get("response_id"),
                    "agent_id": reply.get("agent_id"),
                    "display_name": reply.get("display_name"),
                    "ok": bool(reply.get("ok")),
                    "round": reply.get("round"),
                    "pattern_role": reply.get("pattern_role"),
                    "validation": reply.get("validation"),
                    "context_delivery": reply.get("context_delivery"),
                    "session_compaction": reply.get("session_compaction"),
                    "error": reply.get("error"),
                }
                for reply in replies
            ],
        }
        _finish_persistent_run(
            "cancelled" if cancelled else "completed" if bool(result.get("ok")) else "failed",
            result=compact_result if bool(result.get("ok")) else None,
            error=(
                "collaboration cancelled by user"
                if cancelled
                else None
                if bool(result.get("ok"))
                else str(result.get("error") or "no reply")
            ),
        )

    async def _fail_group_trace(exc: BaseException) -> None:
        for item in member_trace_items.values():
            if item.status == ItemStatus.IN_PROGRESS:
                item.status = ItemStatus.FAILED
                item.error = f"{type(exc).__name__}: {exc}"
                await _notify_completed(item)
        if team_trace_item is not None and team_trace_item.status == ItemStatus.IN_PROGRESS:
            team_trace_item.status = ItemStatus.FAILED
            team_trace_item.error = f"{type(exc).__name__}: {exc}"
            team_trace_item.duration_ms = max(
                0,
                int((time.monotonic() - team_trace_started) * 1000),
            )
            await _notify_completed(team_trace_item)
        _finish_persistent_run("failed", error=f"{type(exc).__name__}: {exc}")

    def _group_summary(result: dict[str, Any]) -> str | None:
        arbitration = result.get("arbitration")
        if not isinstance(arbitration, dict):
            return None
        synthesis = result.get("synthesis")
        answered = arbitration.get("answered_agent_ids")
        failed = arbitration.get("failed_agent_ids")
        empty = arbitration.get("empty_agent_ids")
        if isinstance(synthesis, dict):
            recommended = str(
                synthesis.get("recommended_next_action") or "",
            ).strip()
        else:
            recommended = str(arbitration.get("recommended_next_action") or "").strip()
        if not isinstance(answered, list):
            answered = []
        if not isinstance(failed, list):
            failed = []
        if not isinstance(empty, list):
            empty = []
        if len(answered) < 2 and not failed and not empty:
            return None
        # Multi-round debate double-counts the same member across rounds —
        # the summary should report distinct members, not bubble count.
        distinct_answered = list(dict.fromkeys(answered))
        parts = [
            f"协作汇总: {len(distinct_answered)} 位成员已回应",
        ]
        pattern = result.get("pattern")
        pattern_label = str(pattern.get("label") or "").strip() if isinstance(pattern, dict) else ""
        if pattern_label:
            parts.append(f"采用{pattern_label}")
        debate = result.get("debate")
        debate_rounds = debate.get("rounds") if isinstance(debate, dict) else None
        rounds = int(debate_rounds or arbitration.get("rounds") or 1)
        if rounds > 1:
            parts.append(f"共 {rounds} 轮成员互见辩论")
        delivery = result.get("delivery")
        if isinstance(delivery, dict):
            semantic_review = delivery.get("semantic_review")
            verdict = (
                str(semantic_review.get("verdict") or "").strip()
                if isinstance(semantic_review, dict)
                else ""
            )
            if verdict == "pass":
                parts.append("独立语义验证已通过")
            elif delivery.get("semantic_review_required"):
                parts.append("仍需语义或事实复核")
        recovered = int(result.get("recovered_after_retry_count") or 0)
        if recovered:
            parts.append(f"{recovered} 位成员经自动返工后通过验收")
        # Arbitration's deterministic primary is a transport fallback (today
        # it mostly prefers a successful, fuller reply), not a semantic quality
        # judgment. Do not present it to users as "the best viewpoint".
        if recommended and recommended != "use_primary_response":
            parts.append(f"下一步建议: {_group_next_action_label(recommended)}")
        blocked = [str(x) for x in [*failed, *empty] if x]
        if blocked:
            parts.append(f"{len(blocked)} 位成员需要补看")
        return "；".join(parts) + "。"

    def _group_next_action_label(action: str) -> str:
        labels = {
            "use_primary_response": "采纳主视角继续",
            "use_primary_and_retry_failed_members": "采纳主视角，同时补看失败成员",
            "ask_members_to_expand": "请成员补充展开",
            "retry_or_fallback_to_single_agent": "重试成员或回退单 Agent",
            "fallback_to_single_agent": "回退单 Agent",
        }
        return labels.get(action, action.replace("_", " "))

    if len(members) < 2:
        # Not a real group → one agent answers (the normal single-agent path).
        _record_fallback_audit("insufficient_members")
        await _fallback_to_react()
        return

    try:
        from runtime.execution.agents.group_fanout import run_group_fanout
        from runtime.execution.suckers.delegation_skills import _call_agent

        def _mentioned(display: str) -> bool:
            parts = display.split()
            cands = {display, parts[0] if parts else display, display.replace(" ", "")}
            return any(c and ("@" + c) in text for c in cands)

        # 辩论意图检测：消息含辩论 cue（辩论/反驳/挑战/谁不同意/互怼/打擂台等）
        # 或上下文显式传 swarm_debate_rounds/debate_rounds（>=2 强制多轮）。
        # 用户 @ 了谁 → 这些成员在第二轮被点名优先回应（成员互见 + @反驳）。
        debate_cues = (
            "辩论",
            "反驳",
            "挑战",
            "谁不同意",
            "谁反对",
            "互怼",
            "打擂台",
            "互驳",
            "观点交锋",
            "battle",
            "debate",
            "rebut",
        )

        def _wants_debate() -> int:
            # The server-selected declarative pattern is the normal source of
            # verification depth. Explicit bounded context remains available
            # to internal callers and tests.
            try:
                pattern_rounds = int(team_pattern.get("debate_rounds") or 0)
            except (TypeError, ValueError):
                pattern_rounds = 0
            if pattern_rounds >= 2:
                return min(pattern_rounds, 3)
            # Explicit context flag wins.
            for key in ("swarm_debate_rounds", "debate_rounds"):
                raw = ctx.get(key)
                if raw is not None:
                    try:
                        val = int(raw)
                    except (TypeError, ValueError):
                        val = 0
                    if val >= 2:
                        return min(val, 3)
            low = text.lower()
            if any(cue.lower() in low for cue in debate_cues):
                return 2
            return 0

        def _mentioned_names() -> list[str]:
            """Display names the boss @-mentioned in the message (dedup)."""
            found: list[str] = []
            for m in members:
                display = str(m.get("display_name") or m.get("name") or "")
                parts = display.split()
                cands = {
                    display,
                    parts[0] if parts else display,
                    display.replace(" ", ""),
                }
                if any(c and ("@" + c) in text for c in cands):
                    found.append(display)
            return found

        chat_members = list(members)
        # @-mentioned chat members first so a small fan-out cap never drops them.
        chat_members.sort(key=lambda m: 0 if _mentioned(str(m.get("display_name") or "")) else 1)

        steering_cursors: dict[tuple[str, int], int] = {}
        steering_cursor_lock = threading.Lock()

        def _drain_member_steering(agent_id: str) -> list[str]:
            """Read this member's durable corrections exactly once per live worker."""

            if not collaboration_run_id:
                return []
            store = _run_store()
            read = getattr(store, "collaboration_collector_steering", None)
            collector = store.collaboration_collector(collaboration_run_id)
            if not callable(read) or not isinstance(collector, dict):
                return []
            generation = int(collector.get("generation") or 1)
            key = (agent_id, generation)
            with steering_cursor_lock:
                after_seq = steering_cursors.get(key, 0)
            try:
                rows = read(
                    collaboration_run_id,
                    child_id=agent_id,
                    generation=generation,
                    after_seq=after_seq,
                )
            except (KeyError, ValueError):
                return []
            if not rows:
                return []
            newest = max(int(row.get("seq") or 0) for row in rows)
            with steering_cursor_lock:
                steering_cursors[key] = max(steering_cursors.get(key, 0), newest)
            return [str(row.get("text") or "").strip() for row in rows if row.get("text")]

        def _member_steering_position(agent_id: str) -> tuple[int, int]:
            """Return the generation and highest correction sequence this lane saw."""

            if not collaboration_run_id:
                return (1, 0)
            collector = _run_store().collaboration_collector(collaboration_run_id)
            generation = int(collector.get("generation") or 1) if isinstance(collector, dict) else 1
            with steering_cursor_lock:
                return (generation, steering_cursors.get((agent_id, generation), 0))

        def _steering_addendum(corrections: list[str]) -> str:
            if not corrections:
                return ""
            return (
                "\n\n<user-steering>用户刚刚只对你追加了以下纠偏要求。"
                "它们优先于更早的任务描述；不要复述纠偏过程，直接按新要求完成：\n"
                + "\n".join(f"- {text}" for text in corrections)
                + "\n</user-steering>"
            )

        def _member_caller_unlocked(
            agent_id: str,
            prompt: str,
            timeout_s: int = 90,
        ) -> dict[str, Any]:
            """Run every group member through the in-process agent boundary."""
            member_plan = context_plan.for_agent(agent_id) if context_plan is not None else None
            runtime_checkpoint = None
            checkpoint_reader = getattr(_run_store(), "collaboration_member_runtime", None)
            if member_plan is not None and callable(checkpoint_reader):
                try:
                    runtime_checkpoint = checkpoint_reader(turn.thread_id, agent_id)
                except Exception:  # noqa: BLE001 - fall back to a fresh private session
                    _logger.warning(
                        "cowork member continuation lookup failed · member=%s",
                        agent_id,
                        exc_info=True,
                    )
            current_hashes = member_plan.context_section_hashes() if member_plan is not None else {}
            previous_hashes = (
                dict(runtime_checkpoint.get("context_hashes") or {})
                if isinstance(runtime_checkpoint, dict)
                else {}
            )
            safe_continuation = False
            continuation_reset_reason: str | None = None
            if member_plan is not None and runtime_checkpoint:
                safe_continuation, continuation_reset_reason = member_plan.continuation_safety(
                    previous_hashes
                )
            continuation_id = (
                str(runtime_checkpoint.get("subagent_session_id") or "").strip()
                if safe_continuation and isinstance(runtime_checkpoint, dict)
                else ""
            )
            if runtime_checkpoint and not safe_continuation:
                clear_checkpoint = getattr(
                    _run_store(),
                    "clear_collaboration_member_runtime",
                    None,
                )
                if callable(clear_checkpoint):
                    with contextlib.suppress(Exception):
                        clear_checkpoint(turn.thread_id, agent_id)
            if member_plan is not None:
                planned_context, current_hashes, context_delivery = (
                    member_plan.render_incremental_prompt(
                        previous_hashes if continuation_id else None
                    )
                )
            else:
                planned_context = ""
                context_delivery = {
                    "schema": "octopus.cowork_context_delivery.v1",
                    "mode": "unavailable",
                    "included_sections": [],
                    "omitted_unchanged_sections": [],
                    "full_estimated_tokens": 0,
                    "sent_estimated_tokens": 0,
                    "avoided_estimated_tokens": 0,
                }
            context_delivery["continued_session"] = bool(continuation_id)
            if runtime_checkpoint and not safe_continuation and continuation_reset_reason:
                context_delivery["reset_reason"] = continuation_reset_reason
            base_prompt = planned_context + "\n\n" + prompt if planned_context else prompt
            corrections = _drain_member_steering(agent_id)
            final_prompt = base_prompt + _steering_addendum(corrections)
            result: dict[str, Any] = {}
            # A direct conversational provider call cannot be modified in
            # place. If steering lands while it is running, discard that
            # obsolete answer and restart with the accumulated corrections.
            # Two restarts bound adversarial click-spam and actual model cost.
            for restart in range(3):
                scoped_context = dict(member_context)
                scoped_context["steering_drain"] = lambda: _drain_member_steering(agent_id)
                result = _call_agent(
                    agent_id=agent_id,
                    # The member's persona is injected by the runner. Repeating
                    # the coordinator's full mode contract in every 1–3 sentence
                    # bubble only burns context and can steer it back into task
                    # planning.
                    prompt=final_prompt,
                    timeout_s=timeout_s,
                    context=scoped_context,
                    session=parent_session,
                    continue_session_id=continuation_id or None,
                )
                if continuation_id and result.get("session_error") == "unknown_session":
                    clear_checkpoint = getattr(
                        _run_store(),
                        "clear_collaboration_member_runtime",
                        None,
                    )
                    if callable(clear_checkpoint):
                        with contextlib.suppress(Exception):
                            clear_checkpoint(
                                turn.thread_id,
                                agent_id,
                                subagent_session_id=continuation_id,
                            )
                    continuation_id = ""
                    if member_plan is not None:
                        planned_context, current_hashes, context_delivery = (
                            member_plan.render_incremental_prompt(None)
                        )
                    context_delivery["continued_session"] = False
                    context_delivery["reset_reason"] = "subagent_session_missing"
                    base_prompt = planned_context + "\n\n" + prompt if planned_context else prompt
                    final_prompt = base_prompt + _steering_addendum(corrections)
                    continue
                returned_session_id = str(result.get("session_id") or "").strip()
                if returned_session_id:
                    continuation_id = returned_session_id
                arrived_during_call = _drain_member_steering(agent_id)
                if not arrived_during_call:
                    break
                corrections.extend(arrived_during_call)
                final_prompt = base_prompt + _steering_addendum(corrections)
                if restart == 2:
                    return {
                        **result,
                        "success": False,
                        "output": "",
                        "error": "member steering restart limit exceeded; retry the member",
                    }
            if result.get("success") and continuation_id and member_plan is not None:
                save_checkpoint = getattr(
                    _run_store(),
                    "save_collaboration_member_runtime",
                    None,
                )
                if callable(save_checkpoint):
                    try:
                        save_checkpoint(
                            turn.thread_id,
                            agent_id,
                            subagent_session_id=continuation_id,
                            context_hashes=current_hashes,
                        )
                    except Exception:  # noqa: BLE001 - reply remains usable without reuse
                        _logger.warning(
                            "cowork member continuation save failed · member=%s",
                            agent_id,
                            exc_info=True,
                        )
            context_delivery["continued_session"] = bool(
                context_delivery.get("continued_session") and continuation_id
            )
            result["context_delivery"] = context_delivery
            steering_generation, steering_seq = _member_steering_position(agent_id)
            result["steering_generation"] = steering_generation
            result["steering_seq"] = steering_seq
            result["steering_count"] = steering_seq
            return result

        def _member_caller(agent_id: str, prompt: str, timeout_s: int = 90) -> dict[str, Any]:
            """Serialize only turns that target the same durable member session."""

            lease_store = _run_store()
            acquire_lease = getattr(
                lease_store,
                "acquire_collaboration_member_runtime_lease",
                None,
            )
            release_lease = getattr(
                lease_store,
                "release_collaboration_member_runtime_lease",
                None,
            )
            if not callable(acquire_lease) or not callable(release_lease):
                return _member_caller_unlocked(agent_id, prompt, timeout_s)

            lease_owner = f"member-turn:{os.getpid()}:{threading.get_ident()}:{time.time_ns()}"
            wait_started = time.monotonic()
            # Waiting indefinitely would consume the whole fan-out pool. A
            # short bounded wait preserves turn order in normal overlap; a
            # longer conflict becomes an explicit retryable lane failure.
            wait_deadline = wait_started + min(15.0, max(1.0, timeout_s / 3))
            lease = None
            while lease is None:
                try:
                    lease = acquire_lease(
                        turn.thread_id,
                        agent_id,
                        owner_id=lease_owner,
                        # One steering-aware call may restart three times and
                        # each delegated call may perform one transient retry.
                        lease_seconds=min(3600.0, timeout_s * 7 + 120.0),
                    )
                except Exception:  # noqa: BLE001 - fail closed for session mutation
                    _logger.warning(
                        "cowork member session lease failed · member=%s",
                        agent_id,
                        exc_info=True,
                    )
                    return {
                        "success": False,
                        "output": "",
                        "error": "member private session could not be locked; retry the member",
                        "error_type": "member_session_lock_error",
                        "retryable": True,
                    }
                if lease is not None:
                    break
                if time.monotonic() >= wait_deadline:
                    return {
                        "success": False,
                        "output": "",
                        "error": "member private session is handling an earlier turn; retry the member",
                        "error_type": "member_session_busy",
                        "retryable": True,
                        "session_serialization_wait_ms": round(
                            (time.monotonic() - wait_started) * 1000,
                            3,
                        ),
                    }
                time.sleep(0.05)
            try:
                result = _member_caller_unlocked(agent_id, prompt, timeout_s)
                result["session_serialization_wait_ms"] = round(
                    (time.monotonic() - wait_started) * 1000,
                    3,
                )
                return result
            finally:
                with contextlib.suppress(Exception):
                    release_lease(
                        turn.thread_id,
                        agent_id,
                        owner_id=lease_owner,
                    )

        verifier_agent_id = next(
            (
                str(member.get("name") or "")
                for index, member in enumerate(chat_members)
                if pattern_member_role(str(team_pattern.get("id") or ""), index) == "verifier"
            ),
            "",
        )

        def _semantic_reviewer(prompt: str, timeout_s: int = 120) -> dict[str, Any]:
            review_context = dict(member_context)
            # The verifier may need tools to inspect cited sources. It remains
            # context-steward managed and cannot inherit the full parent chat.
            review_context["direct_conversation_reply"] = False
            planned_context = (
                context_plan.prompt_for(verifier_agent_id) if context_plan is not None else ""
            )
            final_prompt = planned_context + "\n\n" + prompt if planned_context else prompt
            return _call_agent(
                agent_id=verifier_agent_id,
                prompt=final_prompt,
                timeout_s=timeout_s,
                context=review_context,
                session=parent_session,
            )

        spoke = 0
        fanout_cancelled = False
        if chat_members:
            await _drain_pending_deliveries()
            scale_mode = (
                str(ctx.get("swarm_scale_mode") or ctx.get("fanout_scale_mode") or "safe")
                .strip()
                .lower()
            )
            if scale_mode not in {"safe", "full"}:
                scale_mode = "safe"
            requested_limit = ctx.get("swarm_max_members") or ctx.get("max_members")
            try:
                requested_limit_int = int(requested_limit) if requested_limit is not None else 0
            except (TypeError, ValueError):
                requested_limit_int = 0
            fanout_limit = (
                min(512, max(2, requested_limit_int or len(chat_members)))
                if scale_mode == "full"
                else min(32, max(2, requested_limit_int or len(chat_members)))
            )
            try:
                fanout_concurrency = int(ctx.get("swarm_max_concurrency") or 32)
            except (TypeError, ValueError):
                fanout_concurrency = 32
            fanout_concurrency = max(1, min(64, fanout_concurrency))
            await _start_group_trace(
                chat_members,
                max_members=fanout_limit,
                max_concurrency=fanout_concurrency,
                scale_mode=scale_mode,
            )
            _start_persistent_collector(chat_members[:fanout_limit])
            from runtime.safety.approval.cancellation import current_cancellation_token

            ambient_cancellation = current_cancellation_token()

            def _group_fanout_cancelled() -> bool:
                if ambient_cancellation.is_cancelled:
                    return True
                if not collaboration_run_id:
                    return False
                store = _run_store()
                run = store.collaboration_run(collaboration_run_id)
                collector = store.collaboration_collector(collaboration_run_id)
                return bool(
                    (isinstance(run, dict) and run.get("status") == "cancelled")
                    or (isinstance(collector, dict) and collector.get("status") == "cancelled")
                )

            def _group_fanout_member_cancelled(agent_id: str) -> bool:
                if not collaboration_run_id:
                    return False
                collector = _run_store().collaboration_collector(collaboration_run_id)
                if not isinstance(collector, dict):
                    return False
                if agent_id in collector.get("cancellation_requested_child_ids", []):
                    return True
                return any(
                    isinstance(item, dict)
                    and item.get("child_id") == agent_id
                    and item.get("status") == "cancelled"
                    for item in collector.get("results") or []
                )

            debate_rounds = _wants_debate()
            mentioned = _mentioned_names()
            result = await asyncio.to_thread(
                run_group_fanout,
                text,
                chat_members,
                agent_caller=_member_caller,
                # Cover the whole roster (a small hard cap would silently drop
                # members ordered last).
                max_members=fanout_limit,
                max_concurrency=fanout_concurrency,
                scale_mode=scale_mode,
                turn_id=turn.id,
                debate_rounds=debate_rounds,
                mentioned=mentioned,
                speaker=str(
                    ctx.get("speaker_display_name") or ctx.get("human_display_name") or "用户"
                ),
                pattern=team_pattern or None,
                semantic_reviewer=(
                    _semantic_reviewer
                    if verifier_agent_id
                    and str(team_pattern.get("id") or "") == "adversarial_review"
                    else None
                ),
                semantic_reviewer_agent_id=verifier_agent_id or None,
                result_committer=_record_persistent_reply,
                should_cancel=_group_fanout_cancelled,
                should_cancel_member=_group_fanout_member_cancelled,
            )
            fanout_cancelled = bool(result.get("cancelled"))
            if context_plan is not None:
                result["context_plan"] = context_plan.audit_dict()
            result["routing"] = fanout_routing
            arbitration = result.get("arbitration")
            if isinstance(arbitration, dict):
                with contextlib.suppress(Exception):
                    audit_item = ReasoningItem(
                        content=json.dumps(
                            {
                                "schema": "octopus.group_fanout_audit.v1",
                                "arbitration": arbitration,
                                "quality": result.get("quality"),
                                "delivery": result.get("delivery"),
                                "capacity": result.get("capacity") or planned_group_capacity,
                                "pattern": result.get("pattern") or team_pattern or None,
                                "routing": result.get("routing") or fanout_routing,
                                "context_plan": result.get("context_plan"),
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        status=ItemStatus.COMPLETED,
                    )
                    turn.items.append(audit_item)
                    log.item_started(turn.thread_id, turn.id, audit_item)
                    log.item_completed(turn.thread_id, turn.id, audit_item)
            last_round_emitted = 0
            for reply in result.get("replies", []):
                body = str(reply.get("reply") or "").strip()
                round_no = int(reply.get("round") or 1)
                if round_no > 1 and round_no != last_round_emitted:
                    last_round_emitted = round_no
                    await _emit(
                        "⚔️ 第 "
                        + str(round_no)
                        + " 轮 · 成员互见辩论 —— 大家看到彼此观点后点名回应：",
                        display_name="主持人",
                        agent_id="swarm-moderator",
                        icon="⚔️",
                    )
                if reply.get("ok") and body:
                    reply_to = _extract_mention_target(body, chat_members)
                    await _emit(
                        body,
                        display_name=str(reply.get("display_name") or ""),
                        agent_id=str(reply.get("agent_id") or ""),
                        reply_to=reply_to,
                    )
                    spoke += 1
                elif not reply.get("ok") and not reply.get("cancelled"):
                    err = str(reply.get("error") or "no reply")
                    await _emit(
                        "⚠️ "
                        + str(reply.get("display_name") or reply.get("agent_id") or "成员")
                        + " 未能回应 · "
                        + _friendly_member_error(err),
                        display_name=str(reply.get("display_name") or ""),
                        agent_id=str(reply.get("agent_id") or ""),
                    )
            summary = None if fanout_cancelled else _group_summary(result)
            if summary:
                await _emit(summary)
            await _complete_group_trace(result)

        if spoke == 0 and not fanout_cancelled:
            _record_fallback_audit("no_member_response")
            await _fallback_to_react()
    except Exception as exc:  # noqa: BLE001 — never break the turn on a fan-out fault
        _logger.warning(
            "group fan-out failed (%s: %s) — falling back to react",
            type(exc).__name__,
            exc,
        )
        await _fail_group_trace(exc)
        _record_fallback_audit("exception", exc)
        await _fallback_to_react()
