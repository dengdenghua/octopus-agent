"""Cerebrum-backed realtime runtime.

Bridges the existing :func:`runtime.core.cerebrum.react_loop.stream_react_loop`
to the JSON-RPC ``item/*`` protocol. Translation rules:

  ``text_delta``           → ``item/agentMessage/delta`` on the active
                             agentMessage item (created lazily).
  ``thinking_delta``       → ``item/reasoning/textDelta`` on the active
                             reasoning item (created lazily).
  ``tool_start``           → emits ``item/started`` for a new
                             commandExecution / mcpToolCall item; record
                             the tool call id so subsequent events bind.
  ``tool_approval_request``→ converted into a server-initiated
                             ``item/commandExecution/requestApproval``
                             via the gateway's approval channel; the
                             returned decision is forwarded to the
                             :class:`ApprovalProvider` blocking the
                             react loop's thread.
  ``tool_end``             → emits ``item/completed`` for the matching
                             tool item, propagating status/exit code.
  ``react_step_complete``  → flushes any open agentMessage/reasoning
                             items and finalizes them.
  ``react_completed``      → triggers turn close; ``turn/completed`` is
                             emitted by the gateway after start_turn
                             returns.
  ``react_error``          → final ``error`` item.

The ``GatewayApprovalProvider`` runs the react loop's blocking
``request`` call on the asyncio event loop's executor, then awaits the
gateway's :meth:`EventEmitter.request_approval` from the running loop.
This is the only place where async↔sync handoff happens; the rest of
the bridge stays in the runtime's coroutine.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
from collections.abc import Callable, Iterator
from concurrent.futures import CancelledError
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from runtime.memory.threads.event_log import EventLog
from runtime.platform.models import ParsedIntent, TaskId
from runtime.platform.models.primitives import now_utc
from runtime.protocol import (
    AgentMessageItem,
    AgentPhaseSnapshot,
    CommandExecutionItem,
    ErrorItem,
    FileChange,
    FileChangeItem,
    FileHunk,
    ItemStatus,
    JsonRpcErrorCode,
    ReasoningItem,
    ServerMethod,
    SubagentItem,
    Turn,
    TurnParams,
    TurnStatus,
    VerificationItem,
    WorkbenchSnapshotV2,
    WorkspaceFocus,
)
from runtime.protocol.diff_parser import parse_unified_diff
from runtime.protocol.items import diff_is_truncated
from runtime.safety.approval.approval_gate import (
    ApprovalDecision,
    ApprovalProvider,
    ApprovalRequest,
)
from runtime.safety.approval.approval_policy_store import load_policy
from runtime.sensing.gateway.realtime_gateway import (
    EventEmitter,
    RealtimeRuntime,
    _ApprovalError,
    _RpcError,
)

_logger = logging.getLogger(__name__)

_RESUME_PROPOSAL_BLOCK_RE = re.compile(
    r"<octopus_resume_proposal>\s*(\{.*?\})\s*</octopus_resume_proposal>",
    re.DOTALL,
)
_RESUME_CONFIRM_RE = re.compile(
    r"(?:确认|同意|开始|继续)\s*恢复\s*checkpoint\s*#?\s*(\d+)",
    re.IGNORECASE,
)


def _resume_task_id_from_intent(intent: ParsedIntent) -> TaskId | None:
    resume_intent = (intent.user_context or {}).get("resume_intent")
    if not isinstance(resume_intent, dict):
        return None
    if resume_intent.get("confirmed") is not True:
        return None
    if (resume_intent.get("checkpoint_type") or "").lower() != "react":
        return None
    raw_task_id = str(resume_intent.get("task_id") or "").strip()
    if not raw_task_id:
        return None
    try:
        return TaskId(UUID(raw_task_id))
    except (TypeError, ValueError):
        _logger.debug("resume intent has non-UUID react task_id: %s", raw_task_id)
        return None


def _agentic_stream_event_to_react_event(
    kind: str,
    delta: Any,
    final: Any,
) -> dict[str, Any] | None:
    """Translate native tool-loop tuple events into realtime bridge events."""

    if kind == "text":
        return {"type": "text_delta", "delta": str(delta or "")}
    if kind == "reasoning":
        return {"type": "thinking_delta", "delta": str(delta or "")}
    if kind == "tool_start" and isinstance(delta, dict):
        return {
            "type": "tool_start",
            "tool_call_id": str(delta.get("id") or ""),
            "tool_name": str(delta.get("name") or "tool"),
            "input_preview": delta.get("input"),
            "iteration": delta.get("iteration"),
        }
    if kind == "tool_end" and isinstance(delta, dict):
        is_error = bool(delta.get("is_error"))
        return {
            "type": "tool_end",
            "tool_call_id": str(delta.get("id") or ""),
            "tool_name": str(delta.get("name") or "tool"),
            "status": "error" if is_error else "success",
            "output_preview": str(delta.get("output") or ""),
            "iteration": delta.get("iteration"),
        }
    if kind == "stats" and isinstance(delta, dict):
        return {"type": "throughput", "usage": delta}
    if kind == "done":
        if final and not isinstance(final, str):
            return {"type": "text_delta", "delta": str(final)}
        return {"type": "react_completed"}
    return None


def _should_use_native_tool_loop(
    stack: Any,
    intent: ParsedIntent,
    *,
    planning_mode: bool,
) -> bool:
    """Whether this turn should use protocol-native tool calls first."""

    if planning_mode:
        return False
    flag = os.environ.get("OCTOPUS_NATIVE_TOOL_LOOP", "1").strip().lower()
    if flag in {"0", "false", "off", "no"}:
        return False

    user_context = intent.user_context or {}
    explicit = user_context.get("native_tool_loop")
    if explicit is False:
        return False
    metadata = user_context.get("metadata")
    if isinstance(metadata, dict) and metadata.get("native_tool_loop") is False:
        return False

    from runtime.core.cerebrum.todo_protocol import context_mode

    if context_mode(user_context) == "chat":
        return False

    executor = getattr(stack, "executor", None)
    router = getattr(getattr(stack, "planner", None), "router", None)
    if executor is None or router is None or not hasattr(router, "call_stream"):
        return False

    caps = getattr(router, "capabilities", None)
    supports = getattr(caps, "supports_tool_use", None)
    if supports is True:
        return True
    if supports is False:
        return False

    primary = getattr(router, "primary", None)
    primary_caps = getattr(primary, "capabilities", None)
    return getattr(primary_caps, "supports_tool_use", None) is True


def _should_default_planning_mode(text: str, params: TurnParams) -> bool:
    """Default complex execution turns into plan-mode (write plan first
    before tool work). Plan-mode no longer blocks tool execution as of
    2026-05-31 — it just nudges the prompt; see ``react_loop`` for
    the new semantics. So this can return True freely without
    stranding a turn in "(未执行观察) 本次 ReAct 未启用工具执行".
    """
    if getattr(params, "planning_mode", False):
        return False
    if "planning_mode" in getattr(params, "model_fields_set", set()):
        return False
    if "planningMode" in getattr(params, "model_fields_set", set()):
        return False
    mode = _turn_mode(params)
    # Chat = casual conversation, never auto-plan.
    # React = single-agent tool use; planning mode is overkill for
    # one-shot tool invocations like "测试工具链：请调用 list_cwd".
    if mode in ("chat", "react"):
        return False
    from runtime.core.cerebrum.todo_protocol import should_require_todo_protocol

    metadata = _input_metadata(params)
    context = metadata.get("context")
    user_context = context if isinstance(context, dict) else metadata
    return should_require_todo_protocol(text, user_context)


# Keyword → built-in topology id auto-dispatch.
# When the user message strongly suggests a category of work that
# benefits from a multi-agent topology, route to the matching
# built-in (seeded by ``runtime.safety.organization.builtin_topologies``).
# The user can override by explicitly setting ``topology_id`` in the
# turn params; this default only fires when no topology was specified
# AND the message clearly matches one of the categories below.
#
# Order matters — ``code_review`` must come before ``refactor`` because
# "review the refactor PR" mentions both keywords; the more specific
# match wins.
import re as _re_topology

_TOPOLOGY_KEYWORD_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "code_review_team_v1",
        _re_topology.compile(
            r"代码评审|代码审查|代码 review|"
            r"\bcode\s*review\b|\bsecurity\s*audit\b|"
            r"安全审查|安全审计|"
            r"PR review|review (?:the |this )?PR",
            _re_topology.IGNORECASE,
        ),
    ),
    (
        "debug_team_v1",
        _re_topology.compile(
            r"调试|排查|debug\b|找出.*bug|"
            r"\bstack\s*trace\b|\btraceback\b|"
            r"为什么.*报错|为什么.*失败|"
            r"重现.*问题|reproduce.*bug",
            _re_topology.IGNORECASE,
        ),
    ),
    (
        "refactor_pair_v1",
        _re_topology.compile(
            r"重构|refactor\b|"
            r"重新组织.*代码|重新设计.*结构|"
            r"拆分.*文件|拆分.*模块|"
            r"提取.*公共|抽取.*函数",
            _re_topology.IGNORECASE,
        ),
    ),
    (
        "research_swarm_v1",
        _re_topology.compile(
            r"调研|研究报告|市场研究|行业报告|竞品分析|竞争分析|"
            r"\bdeep\s*research\b|\bmarket\s*research\b|\bresearch\s*report\b|"
            r"\bcompetitive\s*analysis\b|"
            r"做.*调研|做一份.*报告|写.*研究",
            _re_topology.IGNORECASE,
        ),
    ),
)


def _should_default_topology(text: str, params: TurnParams) -> str | None:
    """Pick a built-in topology id for unscoped multi-agent dispatch.

    Auto-dispatch is **disabled by default** as of 2026-05-31. The
    swarm path (``_drive_team_topology`` → ``TeamRunner`` →
    ``ephemeral_runner``) is a separate operating mode from the
    single-agent ReAct loop, with different model-capability needs
    (native ``tools`` support) and different observability semantics.
    Letting a keyword silently flip the user from "single agent" to
    "swarm" caused recurring "the model says it can't call tools"
    reports — the upstream model didn't support native function
    calling, but the swarm path requires it.

    The two modes stay decoupled: users opt into swarm by setting
    ``topology_id`` explicitly (UI selector, API param, or via the
    ``deep-research-swarm`` skill the model can invoke from inside
    the single-agent loop). When that opt-in is absent we always
    return ``None`` and ride the single-agent path.

    Kept the keyword rules around because the operator-tunable opt-in
    flag (``user_ctx["enable_auto_topology"] = True``) re-enables the
    classifier for power users who want it back. We also still honor
    the explicit ``disable_auto_topology`` for operators who built on
    top of the old behaviour and want to lock it off forever.
    """
    if not isinstance(text, str) or not text.strip():
        return None
    # Explicit topology beats everything else — that's how the user
    # opts into swarm now.
    if getattr(params, "topology_id", None):
        return None
    if "topology_id" in getattr(params, "model_fields_set", set()):
        return None
    if _turn_mode(params) == "chat":
        return None
    metadata = _input_metadata(params)
    user_ctx = metadata.get("context") if isinstance(metadata.get("context"), dict) else metadata
    enable_auto = False
    if isinstance(user_ctx, dict):
        if user_ctx.get("disable_auto_topology") is True:
            return None
        if user_ctx.get("enable_auto_topology") is True:
            enable_auto = True
        meta_inner = user_ctx.get("metadata")
        if isinstance(meta_inner, dict):
            if meta_inner.get("disable_auto_topology") is True:
                return None
            if meta_inner.get("enable_auto_topology") is True:
                enable_auto = True
    # Default: do NOT auto-dispatch. Single-agent stays single-agent.
    if not enable_auto:
        return None
    for topology_id, pattern in _TOPOLOGY_KEYWORD_RULES:
        if pattern.search(text):
            return topology_id
    return None


def _flatten_turns_to_messages(
    turns: list[Turn],
) -> tuple[list[dict[str, Any]], list[str], list[dict[str, Any]] | None]:
    """Translate a realtime ``Turn[]`` snapshot into the legacy
    ``AgentThreadState`` triple (messages, artifacts, todos).

    Mirrors the frontend ``conversationToAgentThreadState`` in
    ``src/core/threads/realtime-adapter.ts`` so a thread looks the same
    whether the sidebar loads it from the legacy store (this snapshot)
    or rehydrates it live from the WebSocket.

    Rules:
      * userMessage     → ``HumanMessage``
      * reasoning+plan  → folded into ``additional_kwargs`` of the next
                          ``AIMessage`` in the same turn
      * agentMessage    → ``AIMessage`` (Thought/Action/Observation
                          prefixes pass through; the frontend's
                          ``splitReactTrace`` handles cleanup at render
                          time)
      * commandExecution / mcpToolCall / fileChange → tool_calls on the
                          trailing AIMessage of the turn
      * todo-list       → flat list at thread level (last write wins)
      * fileChange      → paths collected into ``artifacts``
      * error           → final synthetic AIMessage with
                          ``additional_kwargs.error``
    """
    messages: list[dict[str, Any]] = []
    artifacts: list[str] = []
    todos: list[dict[str, Any]] | None = None

    for turn in turns:
        pending_reasoning: list[str] = []
        pending_plan: str | None = None
        pending_tool_calls: list[dict[str, Any]] = []

        def merge_into_last_ai(
            reasoning: list[str],
            plan: str | None,
            tool_calls: list[dict[str, Any]],
        ) -> bool:
            for message in reversed(messages):
                if message.get("type") == "human":
                    return False
                if message.get("type") != "ai":
                    continue
                content = message.get("content")
                if not isinstance(content, str) or not content.strip():
                    continue

                incoming_kwargs = _build_ai_kwargs(reasoning, plan)
                if incoming_kwargs:
                    existing_kwargs = message.setdefault("additional_kwargs", {})
                    if not isinstance(existing_kwargs, dict):
                        existing_kwargs = {}
                        message["additional_kwargs"] = existing_kwargs
                    incoming_reasoning = incoming_kwargs.get("reasoning_content")
                    if isinstance(incoming_reasoning, str) and incoming_reasoning.strip():
                        existing_reasoning = existing_kwargs.get("reasoning_content")
                        parts = [
                            part
                            for part in (
                                existing_reasoning if isinstance(existing_reasoning, str) else "",
                                incoming_reasoning,
                            )
                            if part.strip()
                        ]
                        existing_kwargs["reasoning_content"] = "\n\n".join(parts)
                    if "thinking_plan" in incoming_kwargs:
                        existing_kwargs["thinking_plan"] = incoming_kwargs["thinking_plan"]
                if tool_calls:
                    calls = message.setdefault("tool_calls", [])
                    if not isinstance(calls, list):
                        calls = []
                        message["tool_calls"] = calls
                    seen = {
                        str(call.get("id") or "")
                        for call in calls
                        if isinstance(call, dict) and call.get("id")
                    }
                    for call in tool_calls:
                        call_id = str(call.get("id") or "")
                        if call_id and call_id in seen:
                            continue
                        calls.append(dict(call))
                        if call_id:
                            seen.add(call_id)
                return True
            return False

        def flush_trailing_ai(current_turn_status: TurnStatus) -> None:
            nonlocal pending_reasoning, pending_plan, pending_tool_calls
            if not pending_reasoning and pending_plan is None and not pending_tool_calls:
                return
            if current_turn_status == TurnStatus.COMPLETED and merge_into_last_ai(
                pending_reasoning, pending_plan, pending_tool_calls
            ):
                pending_reasoning = []
                pending_plan = None
                pending_tool_calls = []
                return
            ai: dict[str, Any] = {
                "type": "ai",
                "content": "",
                "additional_kwargs": _build_ai_kwargs(pending_reasoning, pending_plan),
            }
            if pending_tool_calls:
                ai["tool_calls"] = list(pending_tool_calls)
            messages.append(ai)
            pending_reasoning = []
            pending_plan = None
            pending_tool_calls = []

        for item in turn.items:
            t = getattr(item, "type", None)
            if t == "userMessage":
                flush_trailing_ai(turn.status)
                messages.append(
                    {
                        "type": "human",
                        "id": getattr(item, "id", None),
                        "content": getattr(item, "text", "") or "",
                    }
                )
            elif t == "reasoning":
                content = getattr(item, "content", "") or ""
                if content:
                    pending_reasoning.append(content)
                else:
                    summary = getattr(item, "summary", None) or []
                    if summary:
                        pending_reasoning.append("\n".join(summary))
            elif t == "plan":
                pending_plan = getattr(item, "text", "") or pending_plan
            elif t == "commandExecution":
                command = getattr(item, "command", "") or "command"
                input_preview = getattr(item, "input_preview", None)
                args: dict[str, Any] = {}
                if isinstance(input_preview, dict):
                    args.update(input_preview)
                elif input_preview is not None:
                    args["inputPreview"] = input_preview
                args.setdefault("command", command)
                args.setdefault("tool", command)
                args.update(
                    {
                        "cwd": getattr(item, "cwd", None),
                        "output": getattr(item, "aggregated_output", "") or "",
                        "exit_code": getattr(item, "exit_code", None),
                        "networkAccess": getattr(item, "network_access", None),
                    }
                )
                pending_tool_calls.append(
                    {
                        "id": getattr(item, "id", ""),
                        "name": command,
                        "args": args,
                        "type": "tool_call",
                    }
                )
            elif t == "mcpToolCall":
                pending_tool_calls.append(
                    {
                        "id": getattr(item, "id", ""),
                        "name": f"{getattr(item, 'server', '')}.{getattr(item, 'tool', '')}",
                        "args": getattr(item, "arguments", {}) or {},
                        "type": "tool_call",
                    }
                )
            elif t == "agentMessage":
                ai = {
                    "type": "ai",
                    "id": getattr(item, "id", None),
                    "content": getattr(item, "text", "") or "",
                    "additional_kwargs": _build_ai_kwargs(pending_reasoning, pending_plan),
                }
                if pending_tool_calls:
                    ai["tool_calls"] = list(pending_tool_calls)
                messages.append(ai)
                pending_reasoning = []
                pending_plan = None
                pending_tool_calls = []
            elif t == "fileChange":
                changes = getattr(item, "changes", None) or []
                for ch in changes:
                    p = getattr(ch, "path", None) if not isinstance(ch, dict) else ch.get("path")
                    if p:
                        artifacts.append(p)
                pending_tool_calls.append(
                    {
                        "id": getattr(item, "id", ""),
                        "name": "file_change",
                        "args": {
                            "changes": changes,
                            "grant_root": getattr(item, "grant_root", None),
                        },
                        "type": "tool_call",
                    }
                )
            elif t == "todo-list":
                plan = getattr(item, "plan", None) or []
                snapshot: list[dict[str, Any]] = []
                for entry in plan:
                    title = (
                        entry.get("title")
                        if isinstance(entry, dict)
                        else getattr(entry, "title", "")
                    )
                    status = (
                        entry.get("status")
                        if isinstance(entry, dict)
                        else getattr(entry, "status", "pending")
                    )
                    snapshot.append({"content": title or "", "status": status or "pending"})
                todos = snapshot
            elif t == "error":
                flush_trailing_ai(turn.status)
                message = getattr(item, "message", "") or ""
                messages.append(
                    {
                        "type": "ai",
                        "id": getattr(item, "id", None),
                        "content": f"出错了：{message}" if message else "出错了。",
                        "additional_kwargs": {
                            "error": {
                                "message": message,
                                "will_retry": bool(getattr(item, "will_retry", False)),
                                "info": getattr(item, "error_info", None),
                            },
                        },
                    }
                )

        flush_trailing_ai(turn.status)

    return messages, artifacts, todos


def _conversation_messages_for_react(
    turns: list[Turn],
    *,
    max_messages: int = 24,
) -> list[dict[str, str]]:
    """Return recent OpenAI-style chat history for ``stream_react_loop``.

    The realtime UI reconstructs visible history from the EventLog, but
    the react loop only sees previous turns when they are placed in
    ``intent.user_context["conversation_messages"]``. This adapter keeps
    follow-up replies like "yes" or "go check it" anchored to the same
    thread without making the frontend resend the whole transcript.
    """

    legacy_messages, _, _ = _flatten_turns_to_messages(turns)
    role_by_type = {
        "human": "user",
        "ai": "assistant",
        "system": "system",
    }
    history: list[dict[str, str]] = []
    for item in legacy_messages:
        if not isinstance(item, dict):
            continue
        role = role_by_type.get(str(item.get("type") or ""))
        content = item.get("content")
        if role is None or not isinstance(content, str) or not content.strip():
            continue
        history.append({"role": role, "content": content.strip()})
    if max_messages > 0 and len(history) > max_messages:
        return history[-max_messages:]
    return history


def _build_ai_kwargs(
    reasoning: list[str],
    plan: str | None,
) -> dict[str, Any]:
    kw: dict[str, Any] = {}
    if reasoning:
        kw["reasoning_content"] = "\n\n".join(reasoning)
    if plan is not None:
        kw["thinking_plan"] = plan
    return kw


def _title_from_messages(messages: list[dict[str, Any]]) -> str | None:
    """Pull the first user message text as a 60-char title.

    The sidebar already has its own ``titleOfThread`` fallback, but
    seeding ``values.title`` here means the legacy threads.jsonl is
    self-descriptive and search/sort works without resolving the full
    message list.
    """
    for msg in messages:
        if msg.get("type") != "human":
            continue
        raw = msg.get("content")
        if isinstance(raw, str) and raw.strip():
            text = raw.strip()
            return text if len(text) <= 60 else text[:57] + "…"
        if isinstance(raw, list):
            for part in raw:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    text = part["text"].strip()
                    if text:
                        return text if len(text) <= 60 else text[:57] + "…"
    return None


# ── Approval bridge ───────────────────────────────────────────


class GatewayApprovalProvider(ApprovalProvider):
    """Blocking provider that delegates to a running asyncio gateway.

    The react loop is iterator-based and runs on a worker thread, but
    the gateway's ``request_approval`` is a coroutine. We bridge with
    :func:`asyncio.run_coroutine_threadsafe` against the loop the
    ``CerebrumRuntime.start_turn`` coroutine was scheduled on.
    """

    def __init__(
        self,
        emitter: EventEmitter,
        loop: asyncio.AbstractEventLoop,
        *,
        thread_id: str,
        turn_id: str,
        trace_store: Any = None,
    ) -> None:
        self._emitter = emitter
        self._loop = loop
        self._thread_id = thread_id
        self._turn_id = turn_id
        self._trace_store = trace_store

    def request(self, req: ApprovalRequest, *, timeout: float = 120.0) -> ApprovalDecision:
        coro = self._emitter.request_approval(
            ServerMethod.REQ_COMMAND_APPROVAL,
            {
                "threadId": self._thread_id,
                "turnId": self._turn_id,
                "itemId": req.tool_call_id,
                "tool": req.tool_name,
                "argsPreview": req.args_preview,
                "detail": req.detail,
                # Lets the client run its own countdown and expire the
                # dialog in lockstep instead of leaving a zombie prompt
                # after the server has already given up.
                "timeoutMs": int(timeout * 1000),
            },
            timeout=timeout,
        )
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        # Every failure denies, but the *reason* is part of the contract:
        # "timeout" / "connection_lost" are machine-readable so the UI
        # and journal can distinguish "user said no" from "nobody was
        # there to answer".
        try:
            decision = future.result(timeout=timeout + 5.0)
        except _ApprovalError as exc:
            code = getattr(exc.error, "code", None)
            timed_out = code == JsonRpcErrorCode.APPROVAL_TIMEOUT
            label = "timeout" if timed_out else "error"
            return self._deny(req, reason=label if timed_out else f"error: {exc}", label=label)
        except CancelledError:
            # ApprovalManager.cancel_all() on connection close cancels the
            # pending future. CancelledError is a BaseException — without
            # this clause it would crash the react worker thread.
            return self._deny(req, reason="connection_lost", label="connection_lost")
        except TimeoutError:
            return self._deny(req, reason="timeout", label="timeout")
        except (ConnectionError, OSError, RuntimeError) as exc:
            return self._deny(req, reason=f"error: {exc}", label="error")
        action = (decision or {}).get("action", "decline")
        result = ApprovalDecision(
            approved=(action == "accept"),
            reason=action,
        )
        self._record_approval(req, result)
        return result

    def _deny(self, req: ApprovalRequest, *, reason: str, label: str) -> ApprovalDecision:
        _logger.warning("approval bridge: %s denied (%s)", req.tool_name, label)
        result = ApprovalDecision(approved=False, reason=reason)
        self._record_approval(req, result, decision_label=label)
        return result

    def _record_approval(
        self,
        req: ApprovalRequest,
        decision: ApprovalDecision,
        *,
        decision_label: str | None = None,
    ) -> None:
        if self._trace_store is None:
            return
        label = decision_label or ("approved" if decision.approved else "rejected")
        try:
            from runtime.safety.audit.trust_gateway import trace_metadata_for_tool

            self._trace_store.record_approval(
                thread_id=self._thread_id or req.thread_id,
                turn_id=self._turn_id,
                tool_name=req.tool_name,
                tool_call_id=req.tool_call_id,
                args_preview=req.args_preview,
                decision=label,
                reason=decision.reason or "",
                metadata=trace_metadata_for_tool(req, detail=req.detail),
            )
        except Exception:  # noqa: BLE001
            _logger.debug("approval bridge: trace record failed", exc_info=True)


# ── Cerebrum runtime ──────────────────────────────────────────


class CerebrumRuntime:
    """Realtime runtime backed by the project's ReAct planner.

    Construct with the same execution stack the rest of the runtime
    uses. ``logs_root`` is the per-thread JSONL directory (same shape
    as :class:`EchoRuntime`).
    """

    def __init__(
        self,
        stack: Any,
        *,
        agent: Any = None,
        agent_registry: Any = None,
        logs_root: str = "data/threads",
        max_iterations: int = 30,
        policy_path: Any = None,
        workspace_root: Any = None,
        compaction_policy: Any = None,
        summary_router: Any = None,
        thread_store: Any = None,
        allow_client_auto_approve: bool = False,
        reflex_router: Any = None,
        trace_store: Any = None,
    ) -> None:
        """Wire a CerebrumRuntime onto an existing octopus stack.

        ``agent`` is the default agent — used when the turn params don't
        specify one. ``agent_registry`` lets the runtime resolve a
        per-turn agent from ``params['agent']`` (typically the assistant
        id picked by the UI). Either or both may be ``None``; the
        underlying react_loop also accepts a None agent and falls back
        to its catch-all skill catalogue.

        ``policy_path`` points at the ``permissions.json`` the UI writes
        to when the user clicks "always trust". None = no static layer,
        every approval round-trips through the gateway.

        ``workspace_root`` is the directory where per-thread isolated
        workspaces are allocated. When None, the runtime does not
        auto-allocate: turns use whatever ``cwd`` the client supplies
        (or None). When set, turns without an explicit cwd default to
        ``<workspace_root>/<thread_id>/``, giving parallel threads
        collision-free filesystem scope — each thread gets its own
        directory, so two concurrent threads can't write to the
        same file.

        ``compaction_policy`` enables automatic turn-compaction after
        each completed turn (bounded context window). None disables
        compaction entirely. When ``summary_router`` is also
        provided, an LLM-backed summariser is wired in — otherwise the
        mechanical default (deterministic prose) is used.
        """
        self._stack = stack
        self._default_agent = agent
        self._agent_registry = agent_registry
        self._logs_root = logs_root
        self._max_iterations = max_iterations
        self._policy_path = policy_path
        self._compaction_policy = compaction_policy
        self._summary_router = summary_router
        # Optional handle to the legacy ``ThreadStateStore`` so each
        # completed realtime turn can write a flattened AgentThreadState
        # snapshot. The workspace sidebar's "recent chats" list reads
        # from that store; without this bridge, realtime conversations
        # would never appear in the history grouping (today / 7d / 30d).
        self._thread_store = thread_store
        self._reflex_router = reflex_router
        self._trace_store = trace_store
        # Server-side authority over auto-approval. When False (default),
        # a client setting ``approvalPolicy="never"`` is downgraded to
        # ``"on-request"`` server-side — the client never gets to silently
        # disable approval gates. Operators who genuinely want headless
        # batches must opt in at config time.
        self._allow_client_auto_approve = bool(allow_client_auto_approve)
        from pathlib import Path

        Path(logs_root).mkdir(parents=True, exist_ok=True)
        self._proposal_ledger_path = Path(logs_root).parent / "proposal_ledger.jsonl"
        self._workspaces: Any = None
        if workspace_root is not None:
            from runtime.platform.runtime_policy.workspaces import WorkspaceManager

            self._workspaces = WorkspaceManager(Path(workspace_root))
        self._known_threads: set[str] = set()
        self._lock = asyncio.Lock()
        self._active_turn_ids: set[str] = set()
        self._compaction_locks: dict[str, asyncio.Lock] = {}
        self._compaction_locks_guard = asyncio.Lock()
        self._pending_resume_intents: dict[str, dict[str, Any]] = {}
        self._resume_intents_lock = asyncio.Lock()
        # Per-thread registry of background command watchers. Each
        # ``track_background_tool`` call registers its asyncio task
        # here; the next turn on the same thread reaps any still-
        # running entries before it begins. Without this, watchers
        # outlive their turn (by design — long shells must keep
        # streaming after the LLM finalises) but they CAN bleed into
        # a brand-new conversation when the user reuses the thread.
        self._thread_background_tasks: dict[str, list[asyncio.Task[None]]] = {}

    def _make_bridge_state(self, thread_id: str) -> _ReactBridgeState:
        """Build a ``_ReactBridgeState`` wired to the per-thread
        background-task registry, so the next turn on this thread can
        sweep any watchers the previous turn left running."""

        def _register(task: asyncio.Task[None]) -> None:
            bucket = self._thread_background_tasks.setdefault(thread_id, [])
            bucket.append(task)
            # Auto-clean when the task finishes naturally — keeps the
            # bucket bounded for long-lived threads.
            task.add_done_callback(lambda t: _safe_list_remove(bucket, t))

        return _ReactBridgeState(on_background_task_start=_register)

    def _record_task_run_started(
        self,
        turn: Turn,
        *,
        text: str,
        params: TurnParams,
    ) -> None:
        if self._trace_store is None:
            return
        with contextlib.suppress(Exception):
            self._trace_store.record_task_run_started(
                task_id=turn.id,
                thread_id=turn.thread_id,
                turn_id=turn.id,
                agent_id=_agent_id_from_params(params),
                title=_preview_text(text, limit=80),
                goal=text,
                mode=_turn_mode(params) or "react",
                metadata={
                    "topology_id": getattr(params, "topology_id", None),
                    "model": getattr(params, "model", None),
                    "planning_mode": bool(getattr(params, "planning_mode", False)),
                },
            )

    def _record_task_run_finished(self, turn: Turn) -> None:
        if self._trace_store is None:
            return
        status_value = str(getattr(turn.status, "value", turn.status) or "").lower()
        if status_value in {"in_progress", "in-progress", "pending", ""}:
            return
        status = {
            "completed": "completed",
            "failed": "failed",
            "interrupted": "interrupted",
            "cancelled": "cancelled",
            "canceled": "cancelled",
        }.get(status_value, "unknown")
        with contextlib.suppress(Exception):
            self._trace_store.record_task_run_finished(
                task_id=turn.id,
                thread_id=turn.thread_id,
                turn_id=turn.id,
                agent_id=_agent_id_from_params(turn.params),
                status=status,
                reason=status_value,
                metadata={
                    "item_count": len(getattr(turn, "items", []) or []),
                    "error": getattr(turn, "error", None),
                },
            )

    def _record_react_trace_event(self, turn: Turn, evt: dict[str, Any]) -> None:
        if self._trace_store is None:
            return
        kind = str(evt.get("type") or "")
        event_type = {
            "tool_start": "TOOL_CALL_START",
            "tool_end": "TOOL_CALL_END",
            "tool_background": "TOOL_CALL_BACKGROUND",
            "react_completed": "REACT_COMPLETED",
            "react_cancelled": "REACT_CANCELLED",
            "react_error": "REACT_ERROR",
        }.get(kind)
        if event_type is None:
            return
        payload = dict(evt)
        if "tool_name" in payload and "tool" not in payload:
            payload["tool"] = payload.get("tool_name")
        with contextlib.suppress(Exception):
            self._trace_store.record_event(
                event_type=event_type,
                payload=payload,
                thread_id=turn.thread_id,
                turn_id=turn.id,
                task_id=turn.id,
                agent_id=_agent_id_from_params(turn.params),
                item_id=str(evt.get("tool_call_id") or evt.get("item_id") or "") or None,
            )

    def _record_failed_turn_proposal(
        self,
        turn: Turn,
        *,
        intent: ParsedIntent | None,
        failure_source: str,
    ) -> None:
        """Persist a failed turn as evolution fuel.

        This is deliberately best-effort and non-blocking from the
        user's perspective: learning infrastructure must never make a
        failed turn fail harder. The record is small but carries enough
        structured metadata for GEPA/canary pipelines to sample real
        failures instead of synthetic anecdotes.
        """

        try:
            from runtime.safety.evolution.proposal_ledger import ProposalLedger

            ledger = ProposalLedger(self._proposal_ledger_path)
            metadata = _failed_turn_metadata(
                turn,
                intent=intent,
                failure_source=failure_source,
            )
            ledger.propose(
                kind="turn_failure",
                description=_failed_turn_description(metadata),
                proposer="realtime_cerebrum",
                model=_turn_model(turn),
                metadata=metadata,
            )
        except Exception as exc:  # noqa: BLE001
            _logger.debug("failed-turn proposal record skipped: %s", exc, exc_info=True)

    def _record_successful_turn_example(
        self,
        turn: Turn,
        *,
        intent: ParsedIntent | None,
    ) -> None:
        """Persist a compact successful turn as positive evolution fuel."""

        try:
            from runtime.safety.evolution.proposal_ledger import ProposalLedger

            metadata = _successful_turn_metadata(turn, intent=intent)
            ProposalLedger(self._proposal_ledger_path).propose(
                kind="turn_success",
                description=_successful_turn_description(metadata),
                proposer="realtime_cerebrum",
                model=_turn_model(turn),
                metadata=metadata,
            )
        except Exception as exc:  # noqa: BLE001
            _logger.debug("successful-turn example record skipped: %s", exc, exc_info=True)

    async def _reap_stale_background_tasks(self, thread_id: str) -> None:
        """Cancel and reap any background watchers from prior turns
        on this thread before a new turn begins.

        Called at the top of ``start_turn``. ``done`` tasks are
        already pruned by the registration done-callback, so this
        loop only fires for actually-still-running watchers — the
        common case (new turn after the prior one finished cleanly)
        is a no-op.
        """
        bucket = self._thread_background_tasks.get(thread_id)
        if not bucket:
            return
        stale = [t for t in bucket if not t.done()]
        if not stale:
            self._thread_background_tasks.pop(thread_id, None)
            return
        for task in stale:
            task.cancel()
        for task in stale:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        # Drop the whole bucket; done-callbacks may still fire and
        # try to remove from a stale list, but ``_safe_list_remove``
        # tolerates missing entries.
        self._thread_background_tasks.pop(thread_id, None)

    def _resolve_agent(self, params: TurnParams) -> Any:
        """Pick the agent for this turn.

        Lookup order:
          1. Realtime input metadata (``agent_id`` / ``agent`` /
             ``agent_name``), including the nested ``context`` bag the
             web UI sends on ``turn/start``.
          2. The registry's match for that id, if any.
          3. The default agent passed at construction time.
          4. ``None``.
        """
        agent_id: str | None = None
        for block in params.input:
            md = block.get("metadata") if isinstance(block, dict) else None
            if not isinstance(md, dict):
                continue
            candidates: list[Any] = [md.get("agent_id"), md.get("agent"), md.get("agent_name")]
            context = md.get("context")
            if isinstance(context, dict):
                candidates.extend(
                    [
                        context.get("agent_id"),
                        context.get("agent"),
                        context.get("agent_name"),
                    ]
                )
            agent_id = next(
                (value.strip() for value in candidates if isinstance(value, str) and value.strip()),
                None,
            )
            if agent_id:
                break
        if agent_id and self._agent_registry is not None:
            try:
                if self._agent_registry.has(agent_id):
                    return self._agent_registry.get(agent_id)
            except (AttributeError, TypeError, OSError):  # noqa: BLE001 — agent lookup failed; fall back to default
                pass
        return self._default_agent

    def _wrap_with_policy(self, fallback: ApprovalProvider) -> ApprovalProvider:
        """Two-layer permission: static rules first, fallback otherwise.

        Reads ``permissions.json`` on every turn so UI-initiated edits
        (the "always trust" button) take effect immediately without
        bouncing the runtime. The file is small (a handful of rules)
        so the IO cost is irrelevant compared to a turn's LLM calls.
        """
        from pathlib import Path

        if self._policy_path is None:
            return fallback
        path = Path(self._policy_path)
        policy = load_policy(path)
        if not policy.rules:
            return fallback
        from runtime.safety.audit.trust_gateway import TrustGatewayApprovalProvider

        return TrustGatewayApprovalProvider(
            static_policy=policy,
            fallback=fallback,
            trace_store=getattr(self, "_trace_store", None),
            turn_id=getattr(fallback, "_turn_id", None),
            agent_id=getattr(getattr(self, "_default_agent", None), "agent_id", None),
        )

    async def _maybe_compact(
        self,
        thread_id: str,
        log: EventLog,
        emitter: EventEmitter,
    ) -> None:
        lock = await self._compaction_lock_for(thread_id)
        async with lock:
            await self._maybe_compact_locked(thread_id, log, emitter)

    async def _compaction_lock_for(self, thread_id: str) -> asyncio.Lock:
        async with self._compaction_locks_guard:
            lock = self._compaction_locks.get(thread_id)
            if lock is None:
                lock = asyncio.Lock()
                self._compaction_locks[thread_id] = lock
            return lock

    async def _maybe_compact_locked(
        self,
        thread_id: str,
        log: EventLog,
        emitter: EventEmitter,
    ) -> None:
        """After a turn completes, check whether the thread warrants
        compaction. If yes, build a summary (possibly via LLM, off the
        event loop) and append a ``turn_compacted`` event.

        Failure is swallowed: a failed compaction must never break the
        turn that just succeeded. The runtime will try again next
        turn, and in the meantime the extra turn stays live context.
        """
        if self._compaction_policy is None:
            return
        from runtime.memory.threads.compaction import (
            CompactionPolicy,
            compact,
            should_compact,
        )

        policy: CompactionPolicy = self._compaction_policy
        # Replay walks the JSONL once; acceptable cost after a turn.
        try:
            turns = log.replay()
        except (OSError, ValueError, TypeError):
            _logger.exception("compaction: replay failed")
            return
        if not should_compact(turns, policy):
            return

        def do_compact() -> Any:
            # Bind LLM summariser at call time so a freshly-swapped
            # router is picked up without rebuilding the runtime.
            effective = policy
            if self._summary_router is not None and policy.custom_summariser is None:
                from runtime.memory.threads.compaction import _default_summariser
                from runtime.memory.threads.llm_summariser import (
                    make_llm_summariser,
                )

                llm_summariser = make_llm_summariser(
                    self._summary_router,
                    fallback=_default_summariser,
                )
                import dataclasses

                effective = dataclasses.replace(policy, custom_summariser=llm_summariser)
            return compact(thread_id, turns, effective)

        try:
            result = await asyncio.to_thread(do_compact)
        except (OSError, ValueError, TypeError):
            _logger.exception("compaction: summariser failed")
            return
        if result is None:
            return
        try:
            log.turn_compacted(thread_id, result.summary_turn, result.superseded_ids)
        except (OSError, ValueError, TypeError):
            _logger.exception("compaction: failed to persist turn_compacted")
            return
        try:
            await emitter.notify(
                ServerMethod.THREAD_STATUS_CHANGED,
                {
                    "threadId": thread_id,
                    "status": {
                        "type": "compacted",
                        "supersededTurnIds": list(result.superseded_ids),
                        "summaryTurnId": result.summary_turn.id,
                    },
                },
            )
        except (ConnectionError, OSError, RuntimeError, TypeError):
            # The compaction is durable on disk already; a failed
            # notification is recoverable via ``thread/resume``.
            _logger.debug("compaction: notify failed", exc_info=True)

    def _log_for(self, thread_id: str) -> EventLog:
        from runtime.memory.threads.event_log import thread_log_path

        return EventLog(thread_log_path(self._logs_root, thread_id))

    def _require_thread_id(self, value: Any) -> str:
        from runtime.memory.threads.event_log import validate_thread_id

        if not isinstance(value, str):
            raise _RpcError(JsonRpcErrorCode.INVALID_PARAMS, "threadId required")
        try:
            return validate_thread_id(value)
        except ValueError as exc:
            raise _RpcError(JsonRpcErrorCode.INVALID_PARAMS, str(exc)) from exc

    def _require_thread_owner(self, log: EventLog, actor_id: str | None) -> None:
        from runtime.memory.threads.event_log import owner_actor_id_from_turns

        owner = owner_actor_id_from_turns(log.replay())
        if owner is not None and actor_id != owner:
            raise _RpcError(JsonRpcErrorCode.THREAD_NOT_FOUND, f"unknown thread {log.path.stem}")

    def _resume_turns(self, log: EventLog) -> list[Turn]:
        """Replay and close in-progress turns left by an older process."""
        turns = log.replay()
        if not turns:
            return turns
        stale = [
            turn
            for turn in turns
            if turn.status == TurnStatus.IN_PROGRESS and turn.id not in self._active_turn_ids
        ]
        for turn in stale:
            turn.status = TurnStatus.FAILED
            turn.error = {
                "message": "上次执行在后端重启或连接中断时未完成，已自动结束。请重新发送或点击重试。",
                "code": "stale_in_progress_turn",
            }
            turn.completed_at = now_utc()
            for item in turn.items:
                if item.status == ItemStatus.IN_PROGRESS:
                    item.status = ItemStatus.FAILED
            log.turn_completed(turn.thread_id, turn.id, turn.status, error=turn.error)
        return turns

    def _snapshot_to_thread_store(
        self,
        thread_id: str,
        log: EventLog,
        intent: ParsedIntent | None = None,
    ) -> None:
        """Flatten the realtime conversation into the legacy
        ``AgentThreadState`` shape and upsert it into ``ThreadStateStore``.

        Without this bridge, realtime turns live only in the per-thread
        JSONL event log under ``data/threads/`` and never surface in the
        sidebar's "recent chats" list, which reads ``ThreadStateStore``
        (``agents/<agent>/sessions/<thread>.jsonl`` + the legacy
        ``data/threads.jsonl`` index).

        Called after every turn — completed, failed, or interrupted —
        so a half-completed conversation still shows up in history.
        Failures here are swallowed: the realtime event log is the
        durable record; the legacy store is a derived cache for the
        sidebar.
        """
        store = self._thread_store
        if store is None:
            return
        try:
            turns = log.replay()
            messages, artifacts, todos = _flatten_turns_to_messages(turns)
            title = _title_from_messages(messages) or ""
            values: dict[str, Any] = {
                "title": title,
                "messages": messages,
                "artifacts": artifacts,
            }
            if todos is not None:
                values["todos"] = todos
            uc = (intent.user_context or {}) if intent is not None else {}
            metadata: dict[str, Any] = {}
            for key in (
                "mode",
                "agent",
                "agent_name",
                "workspace_path",
                "owner_actor_id",
                "actor_id",
            ):
                v = uc.get(key) if isinstance(uc, dict) else None
                if v is not None:
                    # ThreadStateStore.search() filters by ``metadata.agent``
                    # so we normalise the key name the sidebar expects.
                    metadata[
                        "agent"
                        if key == "agent_name"
                        else "owner_actor_id"
                        if key == "actor_id"
                        else key
                    ] = v
            store.ensure_thread(thread_id, metadata=metadata, values=values)
            store.update_state(
                thread_id,
                values=values,
                metadata=metadata if metadata else None,
            )
        except Exception as exc:  # noqa: BLE001
            _logger.debug(
                "snapshot to thread_store skipped (%s: %s)",
                type(exc).__name__,
                exc,
                exc_info=True,
            )

    async def _ensure_thread(self, thread_id: str, emitter: EventEmitter) -> EventLog:
        log = self._log_for(thread_id)
        async with self._lock:
            if thread_id in self._known_threads:
                return log
            existed = log.path.exists() and log.path.stat().st_size > 0
            if not existed:
                log.thread_started(thread_id)
                await emitter.notify(
                    ServerMethod.THREAD_STARTED,
                    {"thread": {"id": thread_id}},
                )
            self._known_threads.add(thread_id)
        return log

    # ── RealtimeRuntime ──────────────────────────────────────

    async def start_turn(
        self,
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
        thread_id = self._require_thread_id(validated.thread_id)
        text = _join_text(validated.input)
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
            await self._reap_stale_background_tasks(thread_id)

        log = await self._ensure_thread(thread_id, emitter)
        self._require_thread_owner(
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
            self._active_turn_ids.add(turn.id)
            await emitter.notify(
                ServerMethod.TURN_STARTED,
                {
                    "threadId": thread_id,
                    "turn": turn.model_dump(by_alias=True, mode="json"),
                },
            )
            self._record_task_run_started(turn, text=text, params=validated)

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
                await self._emit_item_started(turn, log, emitter, err)
                err.status = ItemStatus.FAILED
                await self._emit_item_completed(turn, log, emitter, err)
                turn.status = TurnStatus.FAILED
                log.turn_completed(thread_id, turn.id, turn.status)
                # ``intent`` isn't built yet on the prompt-rejected path;
                # the snapshot helper accepts None so the legacy thread
                # store still records the failed turn for the sidebar.
                self._record_failed_turn_proposal(
                    turn,
                    intent=None,
                    failure_source="prompt_rejected",
                )
                self._snapshot_to_thread_store(thread_id, log, None)
                return turn
            if prompt_decision.modified_prompt is not None:
                text = prompt_decision.modified_prompt
            if not text:
                err = ErrorItem(message="empty input")
                turn.items.append(err)
                await self._emit_item_started(turn, log, emitter, err)
                await self._emit_item_completed(turn, log, emitter, err)
                turn.status = TurnStatus.FAILED
                log.turn_completed(thread_id, turn.id, turn.status)
                self._record_failed_turn_proposal(
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
                await self._emit_item_started(turn, log, emitter, user_item)
                user_item.status = ItemStatus.COMPLETED
                await self._emit_item_completed(turn, log, emitter, user_item)
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
                workspaces=self._workspaces,
                thread_store=self._thread_store,
                allow_client_auto_approve=self._allow_client_auto_approve,
                conversation_messages=conversation_messages,
            )
            confirmed_resume_intent = await self._consume_confirmed_resume_intent(thread_id, text)
            if confirmed_resume_intent is not None:
                intent.user_context["resume_intent"] = confirmed_resume_intent
            resume_intent = intent.user_context.get("resume_intent")
            if (
                isinstance(resume_intent, dict)
                and resume_intent.get("requires_confirmation") is True
            ):
                await self._record_pending_resume_intent(thread_id, resume_intent)
                await self._emit_agent_message(
                    turn,
                    log,
                    emitter,
                    _resume_confirmation_text(resume_intent),
                )
                turn.status = TurnStatus.COMPLETED
                log.turn_completed(thread_id, turn.id, turn.status)
                await self._maybe_compact(thread_id, log, emitter)
                self._snapshot_to_thread_store(thread_id, log, intent)
                return turn

            # ── PHASE 5 · execution dispatch (topology/fast/react) ─────
            loop = asyncio.get_running_loop()
            gateway_provider = GatewayApprovalProvider(
                emitter,
                loop,
                thread_id=thread_id,
                turn_id=turn.id,
                trace_store=self._trace_store,
            )
            provider: ApprovalProvider = self._wrap_with_policy(gateway_provider)
            agent = self._resolve_agent(validated)

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

                if topology_id:
                    await self._drive_team_topology(
                        turn,
                        log,
                        emitter,
                        intent,
                        text=text,
                        topology_id=topology_id,
                    )
                elif self._should_use_reflection_fast_path(
                    text,
                    validated,
                    conversation_messages=conversation_messages,
                ):
                    await self._drive_reflection_fast_path(
                        turn,
                        log,
                        emitter,
                        intent,
                        agent,
                        model=validated.model,
                    )
                else:
                    await self._drive_react(turn, log, emitter, intent, provider, agent)
            except Exception as exc:
                _logger.exception("CerebrumRuntime: react loop crashed")
                err = ErrorItem(message=str(exc) or exc.__class__.__name__)
                turn.items.append(err)
                await self._emit_item_started(turn, log, emitter, err)
                await self._emit_item_completed(turn, log, emitter, err)
                turn.status = TurnStatus.FAILED
                log.turn_completed(thread_id, turn.id, turn.status)
                self._record_failed_turn_proposal(
                    turn,
                    intent=intent,
                    failure_source="react_exception",
                )
                self._snapshot_to_thread_store(thread_id, log, intent)
                return turn

            # ── PHASE 6 · status finalization + snapshot ───────────────
            if turn.status == TurnStatus.INTERRUPTED:
                # Drive-react set this when an interrupt was polled; we
                # respect it rather than flipping back to completed.
                log.turn_completed(thread_id, turn.id, turn.status)
                self._snapshot_to_thread_store(thread_id, log, intent)
                return turn
            if turn.status == TurnStatus.FAILED:
                log.turn_completed(thread_id, turn.id, turn.status)
                self._record_failed_turn_proposal(
                    turn,
                    intent=intent,
                    failure_source="react_failed",
                )
                self._snapshot_to_thread_store(thread_id, log, intent)
                return turn

            if _turn_has_failed_code_verification(turn):
                turn.status = TurnStatus.FAILED
                log.turn_completed(thread_id, turn.id, turn.status)
                self._record_failed_turn_proposal(
                    turn,
                    intent=intent,
                    failure_source="verification_failed",
                )
                self._snapshot_to_thread_store(thread_id, log, intent)
                return turn

            if _turn_has_unverified_code_changes(turn):
                verification_item = VerificationItem(
                    command="verification required",
                    kind="manual",
                    status=ItemStatus.FAILED,
                    exit_code=None,
                    summary=(
                        "Code changes were produced but no verification step "
                        "was recorded before final answer."
                    ),
                    stdout_tail=(
                        "Run an appropriate test, lint, typecheck, or build "
                        "command and retry the final answer."
                    ),
                    stderr_tail=None,
                    related_files=_code_change_paths(turn),
                    related_change_item_ids=_file_change_item_ids(turn),
                )
                turn.items.append(verification_item)
                await self._emit_item_started(turn, log, emitter, verification_item)
                await self._emit_item_completed(turn, log, emitter, verification_item)
                turn.status = TurnStatus.FAILED
                log.turn_completed(thread_id, turn.id, turn.status)
                self._record_failed_turn_proposal(
                    turn,
                    intent=intent,
                    failure_source="verification_required",
                )
                self._snapshot_to_thread_store(thread_id, log, intent)
                return turn

            turn.status = TurnStatus.COMPLETED
            log.turn_completed(thread_id, turn.id, turn.status)
            self._record_successful_turn_example(turn, intent=intent)
            await self._maybe_compact(thread_id, log, emitter)
            self._snapshot_to_thread_store(thread_id, log, intent)
            return turn
        finally:
            self._record_task_run_finished(turn)
            self._active_turn_ids.discard(turn.id)
            emitter.unregister_turn(turn.id)

    async def _record_pending_resume_intent(
        self,
        thread_id: str,
        resume_intent: dict[str, Any],
    ) -> None:
        async with self._resume_intents_lock:
            self._pending_resume_intents[thread_id] = dict(resume_intent)
        if self._trace_store is None:
            return
        with contextlib.suppress(Exception):
            self._trace_store.record_resume_request(
                thread_id=thread_id,
                checkpoint_id=int(resume_intent.get("checkpoint_id") or 0),
                task_id=resume_intent.get("task_id"),
                status="pending",
                intent=resume_intent,
            )

    async def _consume_confirmed_resume_intent(
        self,
        thread_id: str,
        text: str,
    ) -> dict[str, Any] | None:
        checkpoint_id = _parse_resume_confirmation(text)
        if checkpoint_id is None:
            return None
        async with self._resume_intents_lock:
            pending = self._pending_resume_intents.get(thread_id)
            pending_request_id: int | None = None
            if not isinstance(pending, dict) and self._trace_store is not None:
                with contextlib.suppress(Exception):
                    request = self._trace_store.latest_pending_resume_request(thread_id=thread_id)
                    if isinstance(request, dict):
                        pending = request.get("intent")
                        pending_request_id = _safe_int(request.get("id"))
            if not isinstance(pending, dict):
                return None
            if _safe_int(pending.get("checkpoint_id")) != checkpoint_id:
                return None
            self._pending_resume_intents.pop(thread_id, None)
        if self._trace_store is not None:
            with contextlib.suppress(Exception):
                confirmed = self._trace_store.confirm_resume_request(
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
                    self._trace_store.consume_resume_request(pending_request_id)
        return _execution_resume_intent(pending, checkpoint_id)

    async def handle_request(
        self,
        method: str,
        params: dict[str, Any],
        emitter: EventEmitter,
    ) -> Any:
        if method in ("thread/resume", "thread/read"):
            thread_id = self._require_thread_id(params.get("threadId"))
            log = self._log_for(thread_id)
            self._require_thread_owner(log, getattr(emitter, "actor_id", None))
            summary = log.summary()
            if summary is not None and summary.archived:
                raise _RpcError(JsonRpcErrorCode.THREAD_NOT_FOUND, f"unknown thread {thread_id}")
            turns = self._resume_turns(log)
            return {
                "thread": {"id": thread_id, "path": str(log.path)},
                "turns": [t.model_dump(by_alias=True, mode="json") for t in turns],
            }
        if method == "thread/compact":
            thread_id = self._require_thread_id(params.get("threadId"))
            self._require_thread_owner(self._log_for(thread_id), getattr(emitter, "actor_id", None))
            return await self.compact_thread(thread_id, emitter)
        if method == "thread/list":
            from runtime.memory.threads.event_log import list_threads

            include_archived = bool(params.get("includeArchived"))
            actor_id = getattr(emitter, "actor_id", None)
            summaries = list_threads(self._logs_root)
            items = []
            for summary in summaries:
                if not include_archived and summary.archived:
                    continue
                log = self._log_for(summary.thread_id)
                try:
                    self._require_thread_owner(log, actor_id)
                except _RpcError:
                    continue
                items.append(summary.model_dump(by_alias=True, mode="json"))
            return {"threads": items}
        if method == "thread/archive":
            from runtime.memory.threads.event_log import archive_thread

            thread_id = self._require_thread_id(params.get("threadId"))
            self._require_thread_owner(self._log_for(thread_id), getattr(emitter, "actor_id", None))
            if not archive_thread(self._logs_root, thread_id):
                raise _RpcError(JsonRpcErrorCode.THREAD_NOT_FOUND, f"unknown thread {thread_id}")
            return {"threadId": thread_id, "archived": True}
        if method == "item/fileChange/hunkDecide":
            return await self._handle_hunk_decide(params, emitter)
        raise _RpcError(JsonRpcErrorCode.METHOD_NOT_FOUND, method)

    async def compact_thread(
        self,
        thread_id: str,
        emitter: EventEmitter | None = None,
    ) -> dict[str, Any]:
        """Manually compact a thread using the same durable event-log path
        as automatic compaction.

        This is intentionally conservative: it only compacts history older
        than the configured ``keep_recent`` window, so clicking the UI on a
        short conversation is a no-op instead of summarising away everything.
        """
        if self._compaction_policy is None:
            return {"threadId": thread_id, "compacted": False, "reason": "disabled"}

        from dataclasses import replace

        from runtime.memory.threads.compaction import (
            CompactionPolicy,
            compact,
        )

        log = self._log_for(thread_id)
        lock = await self._compaction_lock_for(thread_id)
        async with lock:
            turns = log.replay()
            policy: CompactionPolicy = self._compaction_policy
            if len(turns) <= policy.keep_recent:
                return {
                    "threadId": thread_id,
                    "compacted": False,
                    "reason": "below_keep_recent",
                    "turnCount": len(turns),
                    "keepRecent": policy.keep_recent,
                }

            effective = replace(policy, trigger_at=policy.keep_recent + 1)
            if self._summary_router is not None and effective.custom_summariser is None:
                from runtime.memory.threads.compaction import _default_summariser
                from runtime.memory.threads.llm_summariser import make_llm_summariser

                effective = replace(
                    effective,
                    custom_summariser=make_llm_summariser(
                        self._summary_router,
                        fallback=_default_summariser,
                    ),
                )

            result = await asyncio.to_thread(compact, thread_id, turns, effective)
            if result is None:
                return {"threadId": thread_id, "compacted": False, "reason": "no_stale_turns"}

            log.turn_compacted(thread_id, result.summary_turn, result.superseded_ids)

        if emitter is not None:
            with contextlib.suppress(Exception):
                await emitter.notify(
                    ServerMethod.THREAD_STATUS_CHANGED,
                    {
                        "threadId": thread_id,
                        "status": {
                            "type": "compacted",
                            "supersededTurnIds": list(result.superseded_ids),
                            "summaryTurnId": result.summary_turn.id,
                        },
                    },
                )
        return {
            "threadId": thread_id,
            "compacted": True,
            "supersededTurnIds": list(result.superseded_ids),
            "summaryTurnId": result.summary_turn.id,
        }

    async def _handle_hunk_decide(
        self,
        params: dict[str, Any],
        emitter: EventEmitter,
    ) -> dict[str, Any]:
        """Reject (revert) or accept a single hunk after a FileChange item.

        ``rejected`` reverse-applies just that hunk's diff against the
        current file content; ``accepted`` is informational — the file
        already contains the patched version. The decision is broadcast
        as ``item/fileChange/hunkDecision`` so other connected clients
        update their UI state.
        """
        path_value = params.get("path")
        decision = params.get("decision")
        diff_text = params.get("diff")
        thread_id_value = params.get("threadId")
        thread_id = (
            self._require_thread_id(thread_id_value) if isinstance(thread_id_value, str) else None
        )
        turn_id = params.get("turnId")
        item_id = params.get("itemId")
        hunk_id = params.get("hunkId")
        if not isinstance(path_value, str) or not path_value.strip():
            raise _RpcError(JsonRpcErrorCode.INVALID_PARAMS, "path is required")
        if decision not in ("accepted", "rejected"):
            raise _RpcError(
                JsonRpcErrorCode.INVALID_PARAMS,
                "decision must be 'accepted' or 'rejected'",
            )

        if decision == "rejected" and thread_id is None:
            raise _RpcError(JsonRpcErrorCode.INVALID_PARAMS, "threadId required")
        if thread_id is not None:
            self._require_thread_owner(self._log_for(thread_id), getattr(emitter, "actor_id", None))
            file_path = self._resolve_hunk_path(thread_id, path_value)
        else:
            from pathlib import Path

            file_path = Path(path_value)
        reverted_bytes = 0
        if decision == "rejected":
            if not isinstance(diff_text, str) or not diff_text.strip():
                raise _RpcError(
                    JsonRpcErrorCode.INVALID_PARAMS,
                    "diff is required to reject a hunk",
                )
            from runtime.sensing.gateway.fs_router import (
                _DiffApplyConflict,
                _DiffFormatError,
                _reverse_unified_diff,
            )

            try:
                current = (
                    file_path.read_text(encoding="utf-8", errors="replace")
                    if file_path.exists()
                    else ""
                )
                reverted = _reverse_unified_diff(current, diff_text)
            except _DiffFormatError as exc:
                raise _RpcError(JsonRpcErrorCode.INVALID_PARAMS, str(exc)) from exc
            except _DiffApplyConflict as exc:
                raise _RpcError(
                    JsonRpcErrorCode.APPROVAL_DENIED,
                    f"hunk no longer applies cleanly: {exc}",
                ) from exc
            except OSError as exc:
                raise _RpcError(JsonRpcErrorCode.INTERNAL_ERROR, f"read failed: {exc}") from exc
            try:
                file_path.parent.mkdir(parents=True, exist_ok=True)
                file_path.write_text(reverted, encoding="utf-8")
                reverted_bytes = len(reverted.encode("utf-8"))
            except OSError as exc:
                raise _RpcError(JsonRpcErrorCode.INTERNAL_ERROR, f"write failed: {exc}") from exc

        await emitter.notify(
            ServerMethod.ITEM_FILE_CHANGE_HUNK_DECISION,
            {
                "threadId": thread_id,
                "turnId": turn_id,
                "itemId": item_id,
                "hunkId": hunk_id,
                "decision": decision,
                "path": str(file_path),
            },
        )
        return {
            "decision": decision,
            "path": str(file_path),
            "bytes": reverted_bytes,
        }

    def _resolve_hunk_path(self, thread_id: str, path_value: str) -> Path:
        raw = Path(path_value).expanduser()
        if self._workspaces is None:
            return raw
        workspace_root = self._workspaces.layout(thread_id).root.resolve()
        candidate = raw if raw.is_absolute() else workspace_root / raw
        try:
            resolved = candidate.resolve(strict=False)
            # Reject symlinks that escape the workspace — a symlink
            # inside the tree can point outside, and relative_to alone
            # does not catch this because it operates on the
            # already-resolved path.
            if resolved.is_symlink():
                link_target = resolved.resolve()
                link_target.relative_to(workspace_root)
            resolved.relative_to(workspace_root)
        except (OSError, ValueError) as exc:
            raise _RpcError(
                JsonRpcErrorCode.INVALID_PARAMS,
                "path must stay within the thread workspace",
            ) from exc
        return resolved

    # ── Driver ────────────────────────────────────────────────

    def _should_use_reflection_fast_path(
        self,
        text: str,
        params: TurnParams,
        *,
        conversation_messages: list[dict[str, object]] | None = None,
    ) -> bool:
        """Route simple, non-tool turns through the reflective direct path."""
        router = getattr(getattr(self._stack, "planner", None), "router", None)
        if router is None:
            return False
        mode = _turn_mode(params)
        from runtime.sensing.gateway.realtime_turn_routing import (
            looks_like_contextual_tool_followup,
            looks_like_plain_chat,
        )

        history = conversation_messages or _conversation_messages_from_params(params)
        if mode == "chat":
            return not looks_like_contextual_tool_followup(text, history)
        if looks_like_contextual_tool_followup(text, history):
            return False
        if mode in {"", "react"}:
            return looks_like_plain_chat(text)
        return mode not in {"deep", "swarm"}

    async def _drive_reflection_fast_path(
        self,
        turn: Turn,
        log: EventLog,
        emitter: EventEmitter,
        intent: ParsedIntent,
        agent: Any,
        *,
        model: str | None = None,
    ) -> None:
        """Pump direct-LLM reflection output into realtime item events."""
        reflex_reply = self._try_reflex_reply(intent)
        if reflex_reply:
            await self._emit_agent_message(turn, log, emitter, reflex_reply)
            return

        from runtime.safety.approval.cancellation import (
            CancellationSource,
            scoped_cancellation,
        )
        from runtime.sensing.gateway.openai_gateway.stream_handler import (
            _stream_direct_llm_fallback,
        )
        from runtime.sensing.gateway.realtime_turn_routing import local_non_tool_reply

        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(maxsize=64)
        loop = asyncio.get_running_loop()
        cancel_source = CancellationSource()

        def _safe_put(event: dict[str, Any] | None, *, timeout: float = 10.0) -> None:
            try:
                asyncio.run_coroutine_threadsafe(
                    queue.put(event),
                    loop,
                ).result(timeout=timeout)
            except (RuntimeError, TimeoutError):
                _logger.debug("reflection bridge enqueue dropped")

        def producer() -> None:
            # Chat fast-path (direct LLM, no ReAct). Feed journal_context
            # so token-usage events emitted here carry the thread_id
            # instead of None — this path has no Session/session_scope.
            from runtime.memory.journal.journal_context import journal_context

            _jagent = getattr(agent, "agent_id", None) if agent is not None else None
            with (
                journal_context(
                    conversation_id=turn.thread_id,
                    agent_id=_jagent,
                ),
                scoped_cancellation(cancel_source.token),
            ):
                try:
                    for kind, payload, _final in (
                        _stream_direct_llm_fallback(
                            self._stack,
                            intent,
                            agent,
                            model=model,
                            reasoning_effort=(intent.user_context or {}).get(
                                "reasoning_effort",
                            ),
                        )
                        or ()
                    ):
                        if cancel_source.is_cancelled:
                            _safe_put({"type": "react_cancelled"})
                            return
                        if kind == "text":
                            evt = {"type": "text_delta", "delta": payload or ""}
                        elif kind == "reasoning":
                            evt = {"type": "thinking_delta", "delta": payload or ""}
                        elif kind == "done":
                            evt = {"type": "throughput", "usage": payload}
                        else:
                            continue
                        _safe_put(evt)
                except Exception as exc:  # noqa: BLE001
                    if cancel_source.is_cancelled:
                        _safe_put({"type": "react_cancelled"})
                        return
                    fallback = _model_error_reply(exc) or (
                        local_non_tool_reply(intent.raw) if _is_auth_context_error(exc) else None
                    )
                    if fallback:
                        _safe_put({"type": "text_delta", "delta": fallback})
                        return
                    _safe_put(
                        {
                            "type": "react_error",
                            "kind": exc.__class__.__name__,
                            "message": str(exc),
                        }
                    )
                finally:
                    _safe_put(None, timeout=5.0)

        worker = asyncio.create_task(asyncio.to_thread(producer))
        state = self._make_bridge_state(turn.thread_id)

        async def _interrupt_watcher() -> None:
            # Polls the gateway's interrupt registry. Consumer-side polling
            # alone isn't enough: if the producer is blocked inside a long
            # subprocess.wait, no events reach the queue and the consumer
            # never wakes to notice. This task trips cancellation the
            # instant the flag flips, unblocking the subprocess wait via
            # current_cancellation_token() inside stream_run.
            try:
                while not cancel_source.is_cancelled:
                    if emitter.is_turn_interrupted(turn.id):
                        cancel_source.cancel(reason="user interrupted turn")
                        return
                    await asyncio.sleep(0.1)
            except asyncio.CancelledError:
                return

        watcher = asyncio.create_task(_interrupt_watcher())
        try:
            while True:
                evt = await queue.get()
                if evt is None:
                    break
                if emitter.is_turn_interrupted(turn.id):
                    if not cancel_source.is_cancelled:
                        cancel_source.cancel(reason="user interrupted turn")
                    turn.status = TurnStatus.INTERRUPTED
                    # Drain rather than break — the producer must reach
                    # its ``None`` sentinel for the worker thread to
                    # finish cleanly.
                    continue
                try:
                    await self._apply_react_event(turn, log, emitter, state, evt)
                except Exception as exc:  # noqa: BLE001
                    _logger.warning(
                        "reflection event apply failed (kind=%s): %s",
                        evt.get("type") if isinstance(evt, dict) else "?",
                        exc,
                        exc_info=True,
                    )
        finally:
            # Trip cancellation so the producer THREAD (asyncio.to_thread,
            # which task cancellation can't reach) observes it and bails
            # fast instead of looping to completion against a dead queue.
            # Without this, a consumer cancelled by ws disconnect leaves
            # the worker piling up pending Queue.put() tasks.
            cancel_source.cancel(reason="consumer teardown")
            watcher.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await watcher
            with contextlib.suppress(Exception):
                await worker
        with contextlib.suppress(Exception):
            await state.flush(turn, log, emitter)

    def _try_reflex_reply(self, intent: ParsedIntent) -> str | None:
        router = self._reflex_router
        if router is None:
            return None
        try:
            result = router.try_match(intent)
        except Exception:  # noqa: BLE001
            _logger.debug("realtime reflex match skipped", exc_info=True)
            return None
        if not hasattr(result, "response"):
            return None
        return _reflex_response_to_text(getattr(result, "response", None))

    async def _emit_item_started(
        self,
        turn: Turn,
        log: EventLog,
        emitter: EventEmitter,
        item: Any,
    ) -> None:
        log.item_started(turn.thread_id, turn.id, item)
        await emitter.notify(
            ServerMethod.ITEM_STARTED,
            {
                "threadId": turn.thread_id,
                "turnId": turn.id,
                "item": item.model_dump(by_alias=True, mode="json"),
            },
        )

    async def _emit_item_completed(
        self,
        turn: Turn,
        log: EventLog,
        emitter: EventEmitter,
        item: Any,
    ) -> None:
        log.item_completed(turn.thread_id, turn.id, item)
        await emitter.notify(
            ServerMethod.ITEM_COMPLETED,
            {
                "threadId": turn.thread_id,
                "turnId": turn.id,
                "item": item.model_dump(by_alias=True, mode="json"),
            },
        )

    async def _emit_agent_message(
        self,
        turn: Turn,
        log: EventLog,
        emitter: EventEmitter,
        text: str,
    ) -> None:
        item = AgentMessageItem(text=text)
        turn.items.append(item)
        await self._emit_item_started(turn, log, emitter, item)
        item.status = ItemStatus.COMPLETED
        await self._emit_item_completed(turn, log, emitter, item)

    async def _drive_team_topology(
        self,
        turn: Turn,
        log: EventLog,
        emitter: EventEmitter,
        intent: ParsedIntent,
        *,
        text: str,
        topology_id: str,
    ) -> None:
        """Run the turn through a multi-agent ``TeamTopology``.

        ╔═══════════════════════════════════════════════════════════════╗
        ║ _drive_team_topology · navigation (523 lines, async bridge).  ║
        ║                                                               ║
        ║   PHASE 1 · topology resolution + fallback       ~L2182      ║
        ║   PHASE 2 · queue bridge setup                   ~L2230      ║
        ║   PHASE 3 · producer thread definition           ~L2281      ║
        ║   PHASE 4 · interrupt watcher + helpers          ~L2360      ║
        ║   PHASE 5 · consumer loop (event dispatch)       ~L2480      ║
        ║   PHASE 6 · finalization + perf log              ~L2635      ║
        ║                                                               ║
        ║ Why one big async method: producer thread + asyncio queue     ║
        ║ bridge + nested async closures sharing ~10 state vars.        ║
        ╚═══════════════════════════════════════════════════════════════╝

        The topology id resolves through the organization registry by
        fingerprint *or* by name. On miss we fall back to single-agent
        ReAct so a stale ``topology_id`` never aborts the turn.

        Each role's output emits as a separate ``AgentMessageItem`` so
        the client sees the team's reasoning trace; the team's final
        output becomes the trailing AgentMessageItem and the run gets
        recorded into ``data/topology_performance.jsonl`` for the
        evolver to score next tick.
        """
        # ── PHASE 1 · topology resolution + fallback ────────────────
        from runtime.safety.organization import TeamTopology
        from runtime.safety.organization.forge import load_registry
        from runtime.safety.organization.performance_log import record_run
        from runtime.safety.organization.team_runner import (
            TeamRunner,
            TeamRunResult,
        )

        registry = load_registry()
        topology: TeamTopology | None = registry.get(topology_id)
        if topology is None:
            # Allow name lookup as a convenience (UI users will refer
            # to topologies by their human-readable name, not the
            # fingerprint).
            for t in registry.values():
                if t.name == topology_id:
                    topology = t
                    break
        if topology is None:
            _logger.warning(
                "topology_id %r not in registry · falling back to react",
                topology_id,
            )
            # Build a provider / agent and run the single-agent path so
            # the client never sees an empty turn just because of a
            # stale id.
            loop = asyncio.get_running_loop()
            gateway_provider = GatewayApprovalProvider(
                emitter,
                loop,
                thread_id=intent.user_context.get("thread_id", turn.thread_id),
                turn_id=turn.id,
                trace_store=self._trace_store,
            )
            provider = self._wrap_with_policy(gateway_provider)
            from runtime.protocol.items import TurnParams  # local

            agent = None
            try:
                agent = self._resolve_agent(
                    TurnParams(threadId=turn.thread_id, input=[]),  # type: ignore[call-arg]
                )
            except Exception:  # noqa: BLE001
                _logger.debug("agent resolution failed, using default", exc_info=True)
                agent = None
            await self._drive_react(turn, log, emitter, intent, provider, agent)
            return

        # ── PHASE 2 · queue bridge setup ────────────────────────────
        thread_id = turn.thread_id
        runner_timeout = int(self._max_iterations * 30)

        # Live-event bridge: TeamRunner -> emitter (this coroutine).
        #
        # Why this exists: ``TeamRunner.run`` is synchronous and used to
        # be invoked through ``asyncio.to_thread(...)`` followed by a
        # batch flush of every role's output. For a 3-role research swarm
        # that meant the user saw nothing for 60-120 seconds, then a
        # wall of text — and during the silent window the WS often
        # closed because the frontend treated "no events for N seconds"
        # as an interrupted stream ("本次回复已中断").
        #
        # Now: producer thread runs ``runner.run`` with an emitter that
        # marshals every progress event onto the asyncio queue; this
        # coroutine drains the queue and translates events into
        # ``item/*`` notifications using the same ``_ReactBridgeState``
        # the ReAct path uses, so subagents in a swarm appear in the
        # UI's tool timeline alongside regular tool calls.
        from runtime.safety.approval.cancellation import (
            CancellationSource,
            scoped_cancellation,
        )

        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(maxsize=128)
        loop = asyncio.get_running_loop()
        cancel_source = CancellationSource()

        def _push(event: dict[str, Any]) -> None:
            # Producer side: marshal events back to the asyncio loop.
            # Use ``run_coroutine_threadsafe(...).result()`` so the
            # producer thread blocks if the consumer can't keep up
            # (instead of fire-and-forget which silently drops events
            # when the queue is full). Bounded blocking is safe here
            # because the consumer drains continuously; the only way
            # we'd block forever is consumer dead, which would surface
            # as a hung turn anyway.
            try:
                asyncio.run_coroutine_threadsafe(
                    queue.put(event),
                    loop,
                ).result(timeout=10.0)
            except (RuntimeError, TimeoutError):
                # RuntimeError: loop closed mid-call.
                # TimeoutError: consumer stuck — drop this event rather
                # than block the producer indefinitely. Telemetry only;
                # the run keeps going.
                _logger.debug(
                    "team_runner emitter push failed/timed out",
                )

        # ── PHASE 3 · producer thread definition ────────────────────
        def producer() -> TeamRunResult:
            from runtime.memory.journal.journal_context import journal_context
            from runtime.platform.process.session import Session, session_scope

            session_metadata = dict(intent.user_context or {})
            turn_session = Session(
                agent=None,
                thread_id=thread_id,
                conversation_id=thread_id,
                turn_id=turn.id,
                metadata=session_metadata,
            )
            # Install the cancellation scope on the worker thread so
            # ``call_subagent`` inside the runner sees the same token
            # as react_loop does — every long-running subprocess /
            # network call inside a role checks
            # ``current_cancellation_token()`` and bails out fast.
            # journal_context feeds the journal's conversation_id
            # contextvar (separate from session_scope) so trace rows
            # carry thread_id instead of None.
            with (
                session_scope(turn_session),
                journal_context(conversation_id=thread_id),
                scoped_cancellation(cancel_source.token),
            ):
                try:
                    runner = TeamRunner(
                        timeout_seconds=runner_timeout,
                        event_emitter=_push,
                    )
                    return runner.run(
                        topology,
                        text,
                        context={
                            "thread_id": thread_id,
                            "turn_id": turn.id,
                        },
                    )
                except Exception as exc:  # noqa: BLE001 - surface as event
                    with contextlib.suppress(RuntimeError, TimeoutError):
                        asyncio.run_coroutine_threadsafe(
                            queue.put(
                                {
                                    "type": "team_runner_error",
                                    "kind": exc.__class__.__name__,
                                    "message": str(exc),
                                }
                            ),
                            loop,
                        ).result(timeout=5.0)
                    return TeamRunResult(
                        topology_name=topology.name,
                        topology_fingerprint=topology.fingerprint,
                        task_bucket=topology.task_bucket,
                        success=False,
                        final_output="",
                        error=f"{type(exc).__name__}: {exc}",
                    )
                finally:
                    # Always send the sentinel even if the consumer has
                    # already gone away — suppress so we don't deadlock
                    # the worker thread when the loop is torn down.
                    with contextlib.suppress(RuntimeError, TimeoutError):
                        asyncio.run_coroutine_threadsafe(
                            queue.put(None),
                            loop,
                        ).result(timeout=5.0)

        worker = asyncio.create_task(asyncio.to_thread(producer))
        state = self._make_bridge_state(turn.thread_id)
        # Track how many characters of role text streamed in via
        # ``sub_text_delta`` for the currently-open role. ``team_role_end``
        # uses this to decide whether to dump the role's full output as a
        # one-shot bubble (zero streamed → we never got live text, fall
        # back to the post-hoc dump) or skip it (already streamed).
        streamed_chars: dict[str, int] = {"count": 0}
        subagent_items: dict[str, SubagentItem] = {}
        subagent_seq = 0

        # ── PHASE 4 · interrupt watcher + helpers ───────────────────
        async def _interrupt_watcher() -> None:
            # Trip cancellation the instant the gateway records a
            # ``turn/interrupt`` for this turn id. Without this the
            # swarm runs to natural completion (or to the
            # ``runner_timeout`` of ``max_iterations * 30`` seconds)
            # even after the user clicks "stop".
            try:
                while not cancel_source.is_cancelled:
                    if emitter.is_turn_interrupted(turn.id):
                        cancel_source.cancel(reason="user interrupted turn")
                        return
                    await asyncio.sleep(0.1)
            except asyncio.CancelledError:
                return

        watcher = asyncio.create_task(_interrupt_watcher())

        async def _safe_notify(method: Any, params: dict[str, Any]) -> None:
            # WS may close while we're mid-stream. Notify is best-effort
            # at the consumer layer — we don't want a single ws.send
            # failure to abort processing of the rest of the queue
            # (and the run_result we're waiting on).
            try:
                await emitter.notify(method, params)
            except Exception as exc:  # noqa: BLE001
                _logger.debug("emitter.notify failed: %s", exc, exc_info=True)

        async def _safe_emit_started(turn: Turn, log: EventLog, item: Any) -> None:
            log.item_started(turn.thread_id, turn.id, item)
            await _safe_notify(
                ServerMethod.ITEM_STARTED,
                {
                    "threadId": turn.thread_id,
                    "turnId": turn.id,
                    "item": item.model_dump(by_alias=True, mode="json"),
                },
            )

        async def _safe_emit_completed(turn: Turn, log: EventLog, item: Any) -> None:
            log.item_completed(turn.thread_id, turn.id, item)
            await _safe_notify(
                ServerMethod.ITEM_COMPLETED,
                {
                    "threadId": turn.thread_id,
                    "turnId": turn.id,
                    "item": item.model_dump(by_alias=True, mode="json"),
                },
            )

        def _coerce_str_list(value: Any) -> list[str]:
            if not isinstance(value, list):
                return []
            return [str(item) for item in value if item is not None]

        def _subagent_key(evt: dict[str, Any]) -> str:
            raw = str(evt.get("agent_id") or evt.get("role") or "subagent")
            return raw or "subagent"

        async def _emit_subagent_lifecycle(evt: dict[str, Any]) -> None:
            nonlocal subagent_seq
            ekind = str(evt.get("type") or "")
            agent_key = _subagent_key(evt)
            role = str(evt.get("role") or "") or None
            codename = str(evt.get("codename") or "") or None
            avatar = str(evt.get("avatar") or "") or None
            status = str(evt.get("status") or "") or None
            existing = subagent_items.get(agent_key)
            if existing is None:
                subagent_seq += 1
                safe_agent = re.sub(r"[^A-Za-z0-9_.:-]+", "_", agent_key).strip("_")
                item_id = f"sub_{safe_agent or 'agent'}_{subagent_seq}"[:80]
                existing = SubagentItem(
                    id=item_id,
                    subagent_id=agent_key,
                    role=role,
                    name=codename,
                    codename=codename,
                    avatar=avatar,
                    status=ItemStatus.IN_PROGRESS,
                )
                subagent_items[agent_key] = existing
                turn.items.append(existing)
                await _safe_emit_started(turn, log, existing)
            elif ekind == "subagent_spawned":
                existing = existing.model_copy(
                    update={
                        "role": role or existing.role,
                        "name": codename or existing.name,
                        "codename": codename or existing.codename,
                        "avatar": avatar or existing.avatar,
                    }
                )
                subagent_items[agent_key] = existing
                turn.items = [existing if item.id == existing.id else item for item in turn.items]
                await _safe_emit_started(turn, log, existing)
            if ekind != "subagent_finished":
                return

            ok = bool(evt.get("ok", True)) and not evt.get("error")
            try:
                iteration_count = int(evt.get("iteration_count"))
            except (TypeError, ValueError):
                iteration_count = existing.iteration_count
            completed = existing.model_copy(
                update={
                    "status": ItemStatus.COMPLETED if ok else ItemStatus.FAILED,
                    "role": role or existing.role,
                    "name": codename or existing.name,
                    "codename": codename or existing.codename,
                    "avatar": avatar or existing.avatar,
                    "summary": status or existing.summary,
                    "error": str(evt.get("error")) if evt.get("error") else None,
                    "iteration_count": iteration_count,
                    "files_touched": _coerce_str_list(evt.get("files_touched")),
                }
            )
            subagent_items[agent_key] = completed
            turn.items = [completed if item.id == completed.id else item for item in turn.items]
            await _safe_emit_completed(turn, log, completed)

        # ── PHASE 5 · consumer loop (event dispatch) ────────────────
        run_result: TeamRunResult | None = None
        try:
            while True:
                evt = await queue.get()
                if evt is None:
                    break
                if emitter.is_turn_interrupted(turn.id):
                    if not cancel_source.is_cancelled:
                        cancel_source.cancel(reason="user interrupted turn")
                    turn.status = TurnStatus.INTERRUPTED
                    # Keep draining so the producer can finish cleanly
                    # (and emit its final None sentinel) — don't break
                    # mid-queue or the worker hangs on its put().
                    continue
                ekind = evt.get("type")
                if ekind == "team_role_start":
                    # Close any running role bubble first.
                    await state.flush(turn, log, emitter)
                    role_label = str(evt.get("role") or "role")
                    agent_id = str(evt.get("agent_id") or "")
                    header = f"[{role_label}] starting · agent={agent_id}\n"
                    await state.append_agent_message(
                        turn,
                        log,
                        emitter,
                        header,
                    )
                    # Reset the streamed-chars counter for this role so
                    # the team_role_end completion check below can tell
                    # whether the role's text already streamed in vs.
                    # needs a one-shot dump.
                    streamed_chars["count"] = 0
                elif ekind == "sub_text_delta":
                    # Live role text. Each chunk lands on the currently-
                    # open AgentMessageItem (opened by team_role_start).
                    # Without this, role text only appeared after the
                    # role finished — the user saw a 30s gap between
                    # "role starting" and the role's verdict.
                    chunk = str(evt.get("delta") or "")
                    if chunk:
                        await state.append_agent_message(
                            turn,
                            log,
                            emitter,
                            chunk,
                        )
                        streamed_chars["count"] += len(chunk)
                elif ekind == "team_role_end":
                    await state.flush(turn, log, emitter)
                    if evt.get("status") == "error":
                        err_text = str(evt.get("error") or "role failed")
                        body = f"[{evt.get('role')}] FAILED · {err_text}"
                        item = AgentMessageItem(
                            text=body,
                            status=ItemStatus.COMPLETED,
                        )
                        turn.items.append(item)
                        await _safe_emit_started(turn, log, item)
                        await _safe_emit_completed(turn, log, item)
                    else:
                        # Two completion paths:
                        #
                        # 1. ``streamed_chars["count"] > 0``: text already
                        #    landed via ``sub_text_delta`` chunks. Just
                        #    flush the open AgentMessageItem so the UI
                        #    marks it complete; the body is already there.
                        #
                        # 2. ``streamed_chars["count"] == 0``: the
                        #    underlying router didn't stream (synthetic
                        #    fallback, or this role used ``call`` not
                        #    ``call_stream``). Fall back to a one-shot
                        #    AgentMessageItem with the role's full output
                        #    so the user still sees the verdict instead
                        #    of just the header.
                        await state.flush(turn, log, emitter)
                        if streamed_chars["count"] == 0:
                            out_text = str(evt.get("output") or "").strip()
                            if out_text:
                                body = f"[{evt.get('role')}] {out_text[:8000]}"
                                item = AgentMessageItem(
                                    text=body,
                                    status=ItemStatus.COMPLETED,
                                )
                                turn.items.append(item)
                                await _safe_emit_started(turn, log, item)
                                await _safe_emit_completed(turn, log, item)
                        # Reset for the next role.
                        streamed_chars["count"] = 0
                elif ekind == "sub_tool_start":
                    # Translate to the react_loop tool_start shape so
                    # ``state.start_tool`` can render this in the UI's
                    # live tool timeline alongside react-mode tools.
                    # Prefer the upstream ``tool_call_id`` (the LLM's
                    # ToolCall.id, guaranteed unique within a round)
                    # and fall back to a synthetic key only when the
                    # producer didn't supply one (older path / mocks).
                    call_id = str(evt.get("tool_call_id") or "") or (
                        f"{evt.get('agent_id', 'role')}-r"
                        f"{evt.get('round', 0)}-{evt.get('skill', 'tool')}"
                    )
                    await state.start_tool(
                        turn,
                        log,
                        emitter,
                        {
                            "tool_call_id": call_id,
                            "tool_name": str(evt.get("skill") or "tool"),
                            "input_preview": evt.get("args_preview"),
                            "iteration": evt.get("round"),
                        },
                    )
                elif ekind == "sub_tool_end":
                    call_id = str(evt.get("tool_call_id") or "") or (
                        f"{evt.get('agent_id', 'role')}-r"
                        f"{evt.get('round', 0)}-{evt.get('skill', 'tool')}"
                    )
                    await state.complete_tool(
                        turn,
                        log,
                        emitter,
                        {
                            "tool_call_id": call_id,
                            "status": evt.get("status", "success"),
                            "duration_ms": evt.get("duration_ms"),
                        },
                    )
                elif ekind in {"subagent_spawned", "subagent_finished"}:
                    await _emit_subagent_lifecycle(evt)
                elif ekind == "team_heartbeat":
                    # Lightweight keepalive: prevents the frontend's
                    # pong-timeout (70s) from killing the WS during
                    # long-running roles that don't produce text deltas
                    # (e.g. a researcher doing multi-step web_search).
                    # Emit an empty agent message delta so the frontend
                    # sees activity without polluting the message body.
                    await _safe_notify(
                        ServerMethod.TURN_HEARTBEAT,
                        {
                            "threadId": thread_id,
                            "turnId": turn.id,
                            "role": str(evt.get("role") or ""),
                            "agentId": str(evt.get("agent_id") or ""),
                            "elapsedS": evt.get("elapsed_s", 0),
                        },
                    )
                elif ekind == "team_runner_error":
                    await state.flush(turn, log, emitter)
                    err = ErrorItem(
                        message=str(evt.get("message") or "team runner error"),
                        will_retry=False,
                    )
                    turn.status = TurnStatus.FAILED
                    turn.items.append(err)
                    await _safe_emit_started(turn, log, err)
                    await _safe_emit_completed(turn, log, err)
        finally:
            # ── PHASE 6 · finalization + perf log ───────────────────
            # Trip cancellation so the producer THREAD bails fast (task
            # cancellation can't reach an asyncio.to_thread worker). On a
            # ws-disconnect teardown this is what stops the runner from
            # looping against a dead queue and orphaning the thread.
            cancel_source.cancel(reason="consumer teardown")
            watcher.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await watcher
            with contextlib.suppress(Exception):
                await state.flush(turn, log, emitter)
            # Always reap the worker so the thread can't outlive the turn.
            with contextlib.suppress(Exception):
                run_result = await worker
        if run_result is None:
            # Consumer was torn down before the worker produced a result
            # (e.g. ws disconnect). Nothing more to finalize.
            return

        # If the watcher tripped cancellation, prefer that over the
        # natural success/fail outcome — the user explicitly stopped.
        if cancel_source.is_cancelled:
            turn.status = TurnStatus.INTERRUPTED
        elif run_result.success:
            turn.status = TurnStatus.COMPLETED
        else:
            turn.status = TurnStatus.FAILED

        with contextlib.suppress(Exception):
            await state.finalize_workbench(
                turn,
                log,
                emitter,
                terminal_status=turn.status,
            )

        # Record into the topology performance log so the evolver has
        # something to score. Best-effort: a write failure must not
        # take down the turn that just succeeded.
        with contextlib.suppress(Exception):
            record_run(
                run_result,
                extra={
                    "thread_id": thread_id,
                    "turn_id": turn.id,
                },
            )

    async def _drive_react(
        self,
        turn: Turn,
        log: EventLog,
        emitter: EventEmitter,
        intent: ParsedIntent,
        provider: ApprovalProvider,
        agent: Any,
    ) -> None:
        """Pump the react_loop iterator, mapping each event to ``item/*``.

        The loop runs on a worker thread (``asyncio.to_thread``) so
        synchronous LLM calls inside ``stream_react_loop`` don't block
        the event loop. Each yielded event is delivered back to the
        coroutine via a queue.
        """
        from runtime.core.cerebrum.react_loop import stream_react_loop
        from runtime.safety.approval.cancellation import (
            CancellationSource,
            scoped_cancellation,
        )

        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(maxsize=64)
        loop = asyncio.get_running_loop()

        # Per-turn cancellation source. Tripped when the gateway records a
        # ``turn/interrupt`` for this turn id; every tool call inside
        # ``stream_react_loop`` sees the same token via the
        # ``scoped_cancellation`` contextvar and bails out fast.
        cancel_source = CancellationSource()

        def _safe_put(event: dict[str, Any] | None, *, timeout: float = 10.0) -> None:
            """Bounded blocking ``queue.put`` from the worker thread.

            ``run_coroutine_threadsafe(...).result()`` without a timeout
            deadlocks the worker if the consumer exits early (exception
            in the dispatch loop, ws error, etc.). Bounded blocking
            preserves backpressure for the normal case while leaving a
            kill-switch when something downstream is wedged.
            """
            try:
                asyncio.run_coroutine_threadsafe(
                    queue.put(event),
                    loop,
                ).result(timeout=timeout)
            except (RuntimeError, TimeoutError):
                # RuntimeError: loop closed.
                # TimeoutError: consumer stuck — drop this event rather
                # than block the worker indefinitely.
                _logger.debug(
                    "react bridge enqueue failed/timed out (event=%s)",
                    event.get("type") if isinstance(event, dict) else event,
                )

        def _push_chunk(call_id: str, stream: str, chunk: str) -> None:
            # Called from a reader sub-thread inside the tool's subprocess
            # plumbing. Hop back to the asyncio loop so the queue stays
            # single-producer-from-the-event-loop's-perspective.
            #
            # We use a SHORT timeout here (vs the 10s in _safe_put):
            # tool stdout chunks are high-frequency and individually
            # disposable — better to drop a chunk than block the
            # subprocess reader thread for 10s if the consumer is slow.
            evt = {
                "type": "tool_output_delta",
                "tool_call_id": call_id,
                "stream": stream,
                "delta": chunk,
            }
            try:
                asyncio.run_coroutine_threadsafe(
                    queue.put(evt),
                    loop,
                ).result(timeout=2.0)
            except (RuntimeError, TimeoutError):
                _logger.debug("tool_output_delta drop (consumer slow)")

        def producer() -> None:
            # ``asyncio.to_thread`` copies ContextVars from the calling
            # task, so installing the cancellation scope here makes the
            # token visible to every subprocess call downstream.
            from runtime.memory.journal.journal_context import journal_context
            from runtime.platform.process.session import Session, session_scope

            session_metadata = dict(intent.user_context or {})
            if self._workspaces is not None:
                session_metadata["_artifact_output_root"] = str(
                    self._workspaces.layout(turn.thread_id).final,
                )
            session_agent = agent if hasattr(agent, "agent_id") else None
            turn_session = Session(
                agent=session_agent,
                thread_id=turn.thread_id,
                conversation_id=turn.thread_id,
                turn_id=turn.id,
                metadata=session_metadata,
            )
            # journal_context drives a SEPARATE contextvar that journal
            # write_* methods read for conversation_id/agent_id; without
            # it every journal/trace row lands with thread_id=None.
            # session_scope alone does not feed it.
            _journal_agent_id = getattr(session_agent, "agent_id", None)
            with (
                session_scope(turn_session),
                journal_context(
                    conversation_id=turn.thread_id,
                    agent_id=_journal_agent_id,
                ),
                scoped_cancellation(cancel_source.token),
            ):
                try:
                    _planning_mode = bool(
                        (intent.user_context or {}).get("planning_mode", False),
                    )
                    if _should_use_native_tool_loop(
                        self._stack,
                        intent,
                        planning_mode=_planning_mode,
                    ):
                        from runtime.sensing.gateway.tool_bridge import (
                            stream_agentic_fallback,
                        )

                        for kind, delta, final in stream_agentic_fallback(
                            self._stack,
                            intent,
                            agent,
                        ):
                            evt = _agentic_stream_event_to_react_event(
                                kind,
                                delta,
                                final,
                            )
                            if evt is not None:
                                _safe_put(evt)
                    else:
                        _resume_task_id = _resume_task_id_from_intent(intent)
                        events: Iterator[dict[str, Any]] = stream_react_loop(
                            self._stack,
                            intent,
                            agent,
                            thread_id=turn.thread_id,
                            max_iterations=self._max_iterations,
                            resume_task_id=_resume_task_id,
                            approval_provider=provider,
                            output_chunk_sink=_push_chunk,
                            planning_mode=_planning_mode,
                            reasoning_effort=(intent.user_context or {}).get(
                                "reasoning_effort",
                            ),
                        )
                        for evt in events:
                            _safe_put(evt)
                except Exception as exc:
                    _safe_put(
                        {
                            "type": "react_error",
                            "kind": exc.__class__.__name__,
                            "message": str(exc),
                        }
                    )
                finally:
                    _safe_put(None, timeout=5.0)

        worker = asyncio.create_task(asyncio.to_thread(producer))
        state = self._make_bridge_state(turn.thread_id)

        async def _interrupt_watcher() -> None:
            # Polls the gateway's interrupt registry. Consumer-side polling
            # alone isn't enough: if the producer is blocked inside a long
            # subprocess.wait, no events reach the queue and the consumer
            # never wakes to notice. This task trips cancellation the
            # instant the flag flips, unblocking the subprocess wait via
            # current_cancellation_token() inside stream_run.
            try:
                while not cancel_source.is_cancelled:
                    if emitter.is_turn_interrupted(turn.id):
                        cancel_source.cancel(reason="user interrupted turn")
                        return
                    await asyncio.sleep(0.1)
            except asyncio.CancelledError:
                return

        watcher = asyncio.create_task(_interrupt_watcher())
        try:
            while True:
                evt = await queue.get()
                if evt is None:
                    break
                if emitter.is_turn_interrupted(turn.id):
                    if not cancel_source.is_cancelled:
                        cancel_source.cancel(reason="user interrupted turn")
                    turn.status = TurnStatus.INTERRUPTED
                    # Keep draining so the producer's bounded ``put``
                    # calls succeed and it can reach its ``None`` sentinel
                    # cleanly. Breaking here would leave the worker
                    # blocked on a full queue.
                    continue
                try:
                    await self._apply_react_event(turn, log, emitter, state, evt)
                except Exception as exc:  # noqa: BLE001
                    # A single bad event shouldn't kill the dispatch
                    # loop — swallow and keep draining so the producer
                    # can finish (and so we still emit the trailing
                    # ``state.flush`` for whatever made it through).
                    _logger.warning(
                        "react event apply failed (kind=%s): %s",
                        evt.get("type") if isinstance(evt, dict) else "?",
                        exc,
                        exc_info=True,
                    )
        finally:
            # Trip cancellation so the producer THREAD (asyncio.to_thread)
            # observes it and bails — task cancellation alone can't stop a
            # real OS thread. On ws-disconnect teardown this is what stops
            # the react loop from running to completion against a dead
            # queue and flooding pending Queue.put() tasks.
            cancel_source.cancel(reason="consumer teardown")
            watcher.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await watcher
            with contextlib.suppress(Exception):
                await worker

        # Finalize anything still open. Wrapped in suppress so a torn-
        # down ws doesn't take the whole turn-completion path with it.
        with contextlib.suppress(Exception):
            await state.flush(turn, log, emitter)
        if turn.status == TurnStatus.IN_PROGRESS:
            with contextlib.suppress(Exception):
                await state.finalize_workbench(
                    turn,
                    log,
                    emitter,
                    terminal_status=TurnStatus.COMPLETED,
                )
        # Note: background tool watchers (started by ``track_background_tool``)
        # are intentionally NOT cancelled here. They're designed to outlive
        # the current turn — the user starts a long-running shell command,
        # the LLM finalises with ``react_completed``, and the watcher keeps
        # streaming output deltas onto the open ``commandExecution`` item
        # until the process exits. See ``test_background_tool_item_completes
        # _after_turn_response``.

    async def _apply_react_event(
        self,
        turn: Turn,
        log: EventLog,
        emitter: EventEmitter,
        state: _ReactBridgeState,
        evt: dict[str, Any],
    ) -> None:
        self._record_react_trace_event(turn, evt)
        kind = evt.get("type")
        if kind == "text_delta":
            await state.append_agent_message(turn, log, emitter, evt.get("delta", ""))
            return
        if kind == "thinking_delta":
            await state.append_reasoning(turn, log, emitter, evt.get("delta", ""))
            return
        if kind == "tool_start":
            await state.start_tool(turn, log, emitter, evt)
            return
        if kind == "tool_output_delta":
            await state.append_tool_output(turn, log, emitter, evt)
            return
        if kind == "tool_background":
            await state.track_background_tool(turn, log, emitter, evt)
            return
        if kind == "tool_end":
            await state.complete_tool(turn, log, emitter, evt)
            return
        if kind == "react_cancelled":
            # Producer already decided the loop is done. Flush any open
            # prose and mark the turn as interrupted so the gateway's
            # turn/completed wrapper preserves that status.
            await state.flush(turn, log, emitter)
            turn.status = TurnStatus.INTERRUPTED
            return
        if kind == "throughput":
            # Piggyback on thread/tokenUsage/updated — the frontend
            # reducer already routes this to a free-form ``tokenUsage``
            # record, so we can ship any shape without a schema bump.
            usage = evt.get("usage")
            if isinstance(usage, str) and usage.strip():
                import json

                try:
                    parsed = json.loads(usage)
                    token_usage = parsed if isinstance(parsed, dict) else {}
                except json.JSONDecodeError:
                    token_usage = {}
            elif isinstance(usage, dict):
                token_usage = usage
            else:
                token_usage = {
                    "chars": evt.get("chars", 0),
                    "elapsedMs": evt.get("elapsed_ms", 0),
                    "charsPerSec": evt.get("chars_per_sec", 0.0),
                }
            await emitter.notify(
                ServerMethod.THREAD_TOKEN_USAGE_UPDATED,
                {
                    "threadId": turn.thread_id,
                    "tokenUsage": token_usage,
                },
            )
            return
        if kind == "react_step_complete":
            await state.flush(turn, log, emitter)
            return
        if kind == "react_completed":
            await state.flush(turn, log, emitter)
            if evt.get("success") is False:
                turn.status = TurnStatus.FAILED
            return
        if kind == "react_paused":
            await state.flush(turn, log, emitter)
            turn.status = TurnStatus.INTERRUPTED
            return
        if kind == "react_resumed":
            await emitter.notify(
                ServerMethod.THREAD_STATUS_CHANGED,
                {
                    "threadId": turn.thread_id,
                    "status": {
                        "type": "resumed",
                        "taskId": evt.get("task_id"),
                        "checkpointIteration": evt.get("checkpoint_iteration"),
                        "resumeFromIteration": evt.get("resume_from_iteration"),
                        "restoredStepCount": evt.get("restored_step_count"),
                        "hasFinalAnswer": evt.get("has_final_answer"),
                        "currentPhase": evt.get("current_phase"),
                    },
                },
            )
            return
        if kind in ("react_error",):
            await state.flush(turn, log, emitter)
            err = ErrorItem(
                message=str(evt.get("message") or evt.get("kind") or "react error"),
                will_retry=False,
            )
            turn.status = TurnStatus.FAILED
            turn.items.append(err)
            log.item_started(turn.thread_id, turn.id, err)
            await emitter.notify(
                ServerMethod.ITEM_STARTED,
                {
                    "threadId": turn.thread_id,
                    "turnId": turn.id,
                    "item": err.model_dump(by_alias=True, mode="json"),
                },
            )
            log.item_completed(turn.thread_id, turn.id, err)
            await emitter.notify(
                ServerMethod.ITEM_COMPLETED,
                {
                    "threadId": turn.thread_id,
                    "turnId": turn.id,
                    "item": err.model_dump(by_alias=True, mode="json"),
                },
            )


# ── Bridge state — open agentMessage / reasoning / tool items ─


class _ReactBridgeState:
    """Tracks which items are currently open per (turn, kind).

    The react loop streams ``text_delta`` / ``thinking_delta`` chunks
    that should land on a single ongoing item. ``tool_start``/``tool_end``
    bind by ``tool_call_id``. ``flush`` finalizes any open prose items
    so subsequent steps start fresh.
    """

    def __init__(
        self,
        on_background_task_start: Callable[[asyncio.Task[None]], None] | None = None,
    ) -> None:
        self.agent_message: AgentMessageItem | None = None
        self.reasoning: ReasoningItem | None = None
        self.tools: dict[str, CommandExecutionItem] = {}
        self.phases: list[AgentPhaseSnapshot] = []
        self.workbench_snapshot_version = 0
        self.background_tasks: list[asyncio.Task[None]] = []
        # Optional sink for cross-turn ownership of background watchers.
        # When set, each task created by ``track_background_tool`` is
        # also pushed through this callback so the runtime can sweep
        # leftovers when the user starts a brand-new turn on the same
        # thread (the watcher lives on by design — see
        # ``test_background_tool_item_completes_after_turn_response`` —
        # but we don't want it bleeding into the NEXT conversation).
        self._on_background_task_start = on_background_task_start

    # ── Lifecycle helpers ──────────────────────────────────────────────
    # Every method in this class emits item lifecycle events as a pair:
    # journal write + WS notify. Inlining the 5-line ``notify`` payload
    # at every site obscured the actual logic and made the ServerMethod
    # name a search-and-replace hazard. These helpers centralize the
    # boilerplate; behaviour is byte-identical to the previous inline form.
    @staticmethod
    def _item_payload(turn: Turn, item: Any) -> dict[str, Any]:
        return {
            "threadId": turn.thread_id,
            "turnId": turn.id,
            "item": item.model_dump(by_alias=True, mode="json"),
        }

    async def _emit_started(
        self,
        turn: Turn,
        log: EventLog,
        emitter: EventEmitter,
        item: Any,
    ) -> None:
        log.item_started(turn.thread_id, turn.id, item)
        await emitter.notify(
            ServerMethod.ITEM_STARTED,
            self._item_payload(turn, item),
        )

    async def _emit_completed(
        self,
        turn: Turn,
        log: EventLog,
        emitter: EventEmitter,
        item: Any,
    ) -> None:
        log.item_completed(turn.thread_id, turn.id, item)
        await emitter.notify(
            ServerMethod.ITEM_COMPLETED,
            self._item_payload(turn, item),
        )

    async def append_agent_message(
        self,
        turn: Turn,
        log: EventLog,
        emitter: EventEmitter,
        delta: str,
    ) -> None:
        if not delta:
            return
        if self.agent_message is None:
            self.agent_message = AgentMessageItem(text="")
            turn.items.append(self.agent_message)
            await self._emit_started(turn, log, emitter, self.agent_message)
        self.agent_message.text += delta
        log.item_delta(turn.thread_id, turn.id, self.agent_message.id, "agentMessage", delta)
        await emitter.notify(
            ServerMethod.ITEM_AGENT_MESSAGE_DELTA,
            {
                "threadId": turn.thread_id,
                "turnId": turn.id,
                "itemId": self.agent_message.id,
                "delta": delta,
            },
        )

    async def append_reasoning(
        self,
        turn: Turn,
        log: EventLog,
        emitter: EventEmitter,
        delta: str,
    ) -> None:
        if not delta:
            return
        if self.reasoning is None:
            self.reasoning = ReasoningItem(content="")
            turn.items.append(self.reasoning)
            await self._emit_started(turn, log, emitter, self.reasoning)
        self.reasoning.content += delta
        log.item_delta(turn.thread_id, turn.id, self.reasoning.id, "reasoning", delta)
        await emitter.notify(
            ServerMethod.ITEM_REASONING_TEXT_DELTA,
            {
                "threadId": turn.thread_id,
                "turnId": turn.id,
                "itemId": self.reasoning.id,
                "delta": delta,
                "contentIndex": 0,
            },
        )

    async def start_tool(
        self,
        turn: Turn,
        log: EventLog,
        emitter: EventEmitter,
        evt: dict[str, Any],
    ) -> None:
        # Flush any open prose so the tool item appears after the
        # reasoning that produced it.
        await self.flush(turn, log, emitter)
        call_id = str(evt.get("tool_call_id") or "")
        # Disambiguate when the same tool_call_id appears twice (e.g.
        # swarm sub_tool ids built from ``agent-round-skill`` collide
        # if the same role calls the same skill twice in a round).
        # Without this the second start silently orphans the first
        # CommandExecutionItem — it never gets a tool_end since the
        # dict slot is overwritten.
        if call_id and call_id in self.tools:
            suffix = 2
            while f"{call_id}#{suffix}" in self.tools:
                suffix += 1
            call_id = f"{call_id}#{suffix}"
        item = CommandExecutionItem(
            id=call_id or CommandExecutionItem().id,
            command=str(evt.get("tool_name", "tool")),
            input_preview=evt.get("input_preview"),
        )
        self.tools[call_id] = item
        turn.items.append(item)
        await self._emit_started(turn, log, emitter, item)
        phases = _phases_from_todo_preview(item.input_preview, active_item_id=item.id)
        if phases is not None:
            self.phases = phases
        await self._emit_turn_update(
            turn,
            log,
            emitter,
            workspace_focus=_workspace_focus_for_tool(item),
        )

    async def append_tool_output(
        self,
        turn: Turn,
        log: EventLog,
        emitter: EventEmitter,
        evt: dict[str, Any],
    ) -> None:
        call_id = str(evt.get("tool_call_id") or "")
        item = self.tools.get(call_id)
        delta = evt.get("delta")
        if item is None or not isinstance(delta, str) or not delta:
            return
        item.aggregated_output = (item.aggregated_output or "") + delta
        log.item_delta(turn.thread_id, turn.id, item.id, "commandOutput", delta)
        await emitter.notify(
            ServerMethod.ITEM_COMMAND_OUTPUT_DELTA,
            {
                "threadId": turn.thread_id,
                "turnId": turn.id,
                "itemId": item.id,
                "delta": delta,
            },
        )

    async def track_background_tool(
        self,
        turn: Turn,
        log: EventLog,
        emitter: EventEmitter,
        evt: dict[str, Any],
    ) -> None:
        call_id = str(evt.get("tool_call_id") or "")
        task_id = str(evt.get("task_id") or "")
        item = self.tools.get(call_id)
        if item is None or not task_id:
            return

        preview = item.input_preview if isinstance(item.input_preview, dict) else {}
        snapshot = evt.get("snapshot")
        if not isinstance(snapshot, dict):
            snapshot = {}
        item.input_preview = {
            **preview,
            "background": True,
            "task_id": task_id,
            "status": "running",
            "argv": snapshot.get("argv"),
            "cwd": snapshot.get("cwd") or item.cwd,
        }
        item.process_id = task_id
        # Re-emit ITEM_STARTED so the UI picks up the background metadata
        # we just added; the journal already has the original start record
        # from ``start_tool`` so we skip the journal write here.
        await emitter.notify(
            ServerMethod.ITEM_STARTED,
            self._item_payload(turn, item),
        )
        with contextlib.suppress(ConnectionError, OSError, RuntimeError, TypeError):
            await self.append_tool_output(
                turn,
                log,
                emitter,
                {
                    "tool_call_id": call_id,
                    "delta": f"background process started: {task_id}\n",
                },
            )

        async def _watch_background() -> None:
            last_stdout = ""
            last_stderr = ""
            try:
                from runtime.execution.suckers.write_skills import (
                    _kill_background_exec,
                    _read_background_output,
                )

                while True:
                    if emitter.is_turn_interrupted(turn.id):
                        snap = _kill_background_exec(task_id=task_id)
                    else:
                        snap = _read_background_output(task_id=task_id)
                    if not isinstance(snap, dict):
                        snap = {"status": "failed", "error": "invalid background snapshot"}

                    stdout = str(snap.get("stdout") or "")
                    stderr = str(snap.get("stderr") or "")
                    delta = ""
                    if len(stdout) > len(last_stdout):
                        delta += stdout[len(last_stdout) :]
                    if len(stderr) > len(last_stderr):
                        stderr_delta = stderr[len(last_stderr) :]
                        delta += stderr_delta if not delta else "\n[stderr]\n" + stderr_delta
                    last_stdout = stdout
                    last_stderr = stderr
                    if delta:
                        with contextlib.suppress(
                            ConnectionError,
                            OSError,
                            RuntimeError,
                            TypeError,
                        ):
                            await self.append_tool_output(
                                turn,
                                log,
                                emitter,
                                {"tool_call_id": call_id, "delta": delta},
                            )

                    status = str(snap.get("status") or "")
                    if status != "running":
                        if status == "cancelled":
                            end_status = "cancelled"
                        elif status == "completed":
                            end_status = "success"
                        else:
                            end_status = "error"
                        with contextlib.suppress(
                            ConnectionError,
                            OSError,
                            RuntimeError,
                            TypeError,
                        ):
                            await self.complete_tool(
                                turn,
                                log,
                                emitter,
                                {
                                    "tool_call_id": call_id,
                                    "tool_name": evt.get("tool_name") or item.command,
                                    "status": end_status,
                                    "output_preview": "",
                                    "duration_ms": evt.get("duration_ms"),
                                },
                            )
                        return
                    await asyncio.sleep(0.5)
            except Exception:  # noqa: BLE001
                _logger.debug("background command watcher failed", exc_info=True)

        self.background_tasks.append(asyncio.create_task(_watch_background()))
        if self._on_background_task_start is not None:
            with contextlib.suppress(Exception):
                self._on_background_task_start(self.background_tasks[-1])

    async def complete_tool(
        self,
        turn: Turn,
        log: EventLog,
        emitter: EventEmitter,
        evt: dict[str, Any],
    ) -> None:
        call_id = str(evt.get("tool_call_id") or "")
        item = self.tools.pop(call_id, None)
        if item is None:
            # Unknown tool_call_id — skip rather than synthesize.
            return
        status = evt.get("status", "success")
        if status == "rejected":
            item.status = ItemStatus.DECLINED
        elif status == "cancelled":
            item.status = ItemStatus.INTERRUPTED
        elif status == "error":
            item.status = ItemStatus.FAILED
        else:
            item.status = ItemStatus.COMPLETED
        if isinstance(evt.get("output_preview"), str) and not item.aggregated_output:
            # If the tool already streamed output incrementally, keep the
            # streamed text — ``output_preview`` is a *summary* that loses
            # detail, so overwriting would regress the live view.
            item.aggregated_output = evt["output_preview"]
        await self._emit_completed(turn, log, emitter, item)

        # Apply-patch first-class item: when a file-editing tool ran
        # successfully and surfaced a unified diff, promote it to a
        # dedicated FileChangeItem so the UI can render hunks with
        # per-hunk accept/reject. We only do this on success — a
        # failed tool call has nothing to show.
        if item.status == ItemStatus.COMPLETED:
            related_change_item_ids: list[str] = []
            related_files: list[str] = []
            file_item = _file_change_item_from_tool_evt(evt)
            if file_item is not None:
                related_change_item_ids.append(file_item.id)
                related_files = [change.path for change in file_item.changes]
                turn.items.append(file_item)
                started_file_item = FileChangeItem(
                    id=file_item.id,
                    changes=[],
                    grant_root=file_item.grant_root,
                )
                await self._emit_started(turn, log, emitter, started_file_item)
                file_focus = _workspace_focus_for_file_change(file_item)
                await self._emit_turn_update(
                    turn,
                    log,
                    emitter,
                    workspace_focus=file_focus,
                )
                await self._emit_file_change_hunks(
                    turn,
                    log,
                    emitter,
                    file_item,
                    workspace_focus=file_focus,
                )
                # ``_emit_item_completed`` lives on ``CerebrumRuntime`` and
                # isn't reachable from here — use the local ``_emit_completed``
                # so we don't reach across class boundaries.
                await self._emit_completed(turn, log, emitter, file_item)

            verification_item = _verification_item_from_tool_evt(
                item,
                evt,
                related_change_item_ids=related_change_item_ids,
                related_files=related_files,
            )
            if verification_item is not None:
                turn.items.append(verification_item)
                await self._emit_started(turn, log, emitter, verification_item)
                await self._emit_completed(turn, log, emitter, verification_item)
        else:
            verification_item = _verification_item_from_tool_evt(
                item,
                evt,
                related_change_item_ids=[],
                related_files=[],
            )
            if verification_item is not None:
                turn.items.append(verification_item)
                await self._emit_started(turn, log, emitter, verification_item)
                await self._emit_completed(turn, log, emitter, verification_item)

    async def flush(self, turn: Turn, log: EventLog, emitter: EventEmitter) -> None:
        if self.agent_message is not None:
            self.agent_message.status = ItemStatus.COMPLETED
            await self._emit_completed(turn, log, emitter, self.agent_message)
            self.agent_message = None
        if self.reasoning is not None:
            self.reasoning.status = ItemStatus.COMPLETED
            await self._emit_completed(turn, log, emitter, self.reasoning)
            self.reasoning = None

    async def finalize_workbench(
        self,
        turn: Turn,
        log: EventLog,
        emitter: EventEmitter,
        *,
        terminal_status: TurnStatus,
    ) -> None:
        """Emit the terminal workbench snapshot for ``turn``.

        Called when the orchestrating turn reaches a terminal state
        (COMPLETED / FAILED / INTERRUPTED). ``_terminal_workbench_phases``
        rewrites pending/running phases into the appropriate terminal
        shape and clears every ``active_item_id`` so the UI stops
        highlighting items owned by long-lived background watchers
        (e.g. a long-running shell command whose output keeps
        streaming after the turn finishes).

        We do NOT bail when ``self.tools`` is non-empty — those are
        background watchers by design (see
        ``track_background_tool``); the user's *turn* is over even if
        the watcher process isn't. Bailing here used to leave the UI
        stuck at "running" forever.
        """
        if not self.phases:
            return
        terminal_phases = _terminal_workbench_phases(
            self.phases,
            terminal_status,
        )
        if terminal_phases == self.phases and turn.workbench_snapshot is not None:
            return
        self.phases = terminal_phases
        await self._emit_turn_update(
            turn,
            log,
            emitter,
            workspace_focus=turn.workspace_focus,
        )

    async def _emit_turn_update(
        self,
        turn: Turn,
        log: EventLog,
        emitter: EventEmitter,
        *,
        workspace_focus: WorkspaceFocus | None = None,
    ) -> None:
        phases = _phases_with_active_item(self.phases, workspace_focus)
        turn.phases = phases
        if workspace_focus is not None:
            turn.workspace_focus = workspace_focus
        self.workbench_snapshot_version += 1
        snapshot = _workbench_snapshot(
            version=self.workbench_snapshot_version,
            phases=phases,
            workspace_focus=turn.workspace_focus,
        )
        turn.workbench_snapshot = snapshot
        phases_payload = [phase.model_dump(by_alias=True, mode="json") for phase in phases]
        focus_payload = (
            workspace_focus.model_dump(by_alias=True, mode="json")
            if workspace_focus is not None
            else None
        )
        snapshot_payload = snapshot.model_dump(by_alias=True, mode="json")
        log.turn_updated(
            turn.thread_id,
            turn.id,
            phases=phases_payload,
            workspace_focus=focus_payload,
            workbench_snapshot=snapshot_payload,
        )
        # MIGRATION (sunset target: v0.3): we currently emit the snapshot on
        # BOTH ``turn/plan/updated`` (legacy clients) and ``workbench/snapshot``
        # (new clients). Once every shipped frontend is on the new method,
        # drop ``workbenchSnapshot`` from the ``turn/plan/updated`` payload
        # so the wire is half the size for plan-only updates. Track removal
        # in CHANGELOG when the tap is closed.
        await emitter.notify(
            ServerMethod.TURN_PLAN_UPDATED,
            {
                "threadId": turn.thread_id,
                "turnId": turn.id,
                "phases": phases_payload,
                **({"workspaceFocus": focus_payload} if focus_payload is not None else {}),
                "workbenchSnapshot": snapshot_payload,
            },
        )
        await emitter.notify(
            ServerMethod.WORKBENCH_SNAPSHOT,
            {
                "threadId": turn.thread_id,
                "turnId": turn.id,
                "snapshot": snapshot_payload,
            },
        )

    async def _emit_file_change_hunks(
        self,
        turn: Turn,
        log: EventLog,
        emitter: EventEmitter,
        item: FileChangeItem,
        *,
        workspace_focus: WorkspaceFocus | None = None,
    ) -> None:
        focus_payload = (
            workspace_focus.model_dump(by_alias=True, mode="json")
            if workspace_focus is not None
            else None
        )
        for change in item.changes:
            for hunk in change.hunks:
                hunk_payload = hunk.model_dump(by_alias=True, mode="json")
                delta_payload = {
                    "path": change.path,
                    "op": change.op,
                    "hunk": hunk_payload,
                }
                log.item_delta(
                    turn.thread_id,
                    turn.id,
                    item.id,
                    "fileChangeHunk",
                    delta_payload,
                )
                await emitter.notify(
                    ServerMethod.ITEM_FILE_CHANGE_HUNK_DELTA,
                    {
                        "threadId": turn.thread_id,
                        "turnId": turn.id,
                        "itemId": item.id,
                        "path": change.path,
                        "op": change.op,
                        "hunk": hunk_payload,
                        **({"workspaceFocus": focus_payload} if focus_payload is not None else {}),
                    },
                )


# ── Helpers ───────────────────────────────────────────────────


def _phases_from_todo_preview(
    preview: Any,
    *,
    active_item_id: str | None = None,
) -> list[AgentPhaseSnapshot] | None:
    data = _coerce_preview_record(preview)
    if data is None:
        return None
    raw = data.get("items") or data.get("todos") or data.get("plan")
    if not isinstance(raw, list) or len(raw) < 2:
        return None
    parsed: list[tuple[str, str]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        title = _first_string(
            entry,
            ("activeForm", "active_form", "content", "text", "title", "task"),
        )
        if not title:
            continue
        parsed.append((title, _todo_phase_status(entry.get("status"))))
    if len(parsed) < 2:
        return None
    total = len(parsed)
    return [
        AgentPhaseSnapshot(
            id=f"todo-phase:{index}",
            index=index + 1,
            total=total,
            title=_phase_title(title, index),
            status=status,  # type: ignore[arg-type]
            active_item_id=active_item_id if status == "running" else None,
        )
        for index, (title, status) in enumerate(parsed)
    ]


def _phases_with_active_item(
    phases: list[AgentPhaseSnapshot],
    workspace_focus: WorkspaceFocus | None,
) -> list[AgentPhaseSnapshot]:
    if workspace_focus is None:
        return list(phases)
    return [
        phase.model_copy(update={"active_item_id": workspace_focus.item_id})
        if phase.status == "running"
        else phase
        for phase in phases
    ]


def _terminal_workbench_phases(
    phases: list[AgentPhaseSnapshot],
    terminal_status: TurnStatus,
) -> list[AgentPhaseSnapshot]:
    if terminal_status == TurnStatus.COMPLETED:
        return [
            phase.model_copy(update={"status": "done", "active_item_id": None})
            if phase.status in {"pending", "running", "waiting_approval"}
            else phase.model_copy(update={"active_item_id": None})
            for phase in phases
        ]
    if terminal_status == TurnStatus.FAILED:
        marked = False
        terminal_phases: list[AgentPhaseSnapshot] = []
        for phase in phases:
            if phase.status == "done":
                terminal_phases.append(phase.model_copy(update={"active_item_id": None}))
                continue
            if not marked:
                marked = True
                terminal_phases.append(
                    phase.model_copy(update={"status": "error", "active_item_id": None})
                )
                continue
            terminal_phases.append(phase.model_copy(update={"active_item_id": None}))
        return terminal_phases
    if terminal_status == TurnStatus.INTERRUPTED:
        return [
            phase.model_copy(update={"active_item_id": None})
            if phase.status != "running"
            else phase.model_copy(update={"status": "waiting_approval", "active_item_id": None})
            for phase in phases
        ]
    return list(phases)


def _workbench_snapshot(
    *,
    version: int,
    phases: list[AgentPhaseSnapshot],
    workspace_focus: WorkspaceFocus | None,
) -> WorkbenchSnapshotV2:
    current_phase = _current_workbench_phase(phases)
    current_item_id = (
        workspace_focus.item_id
        if workspace_focus is not None
        else current_phase.active_item_id
        if current_phase is not None
        else None
    )
    return WorkbenchSnapshotV2(
        version=version,
        status=_workbench_status(phases),
        phases=phases,
        current_phase_id=current_phase.id if current_phase is not None else None,
        current_item_id=current_item_id,
        workspace_focus=workspace_focus,
    )


def _workbench_status(
    phases: list[AgentPhaseSnapshot],
) -> Literal["pending", "running", "done", "error", "waiting_approval"]:
    if any(phase.status == "error" for phase in phases):
        return "error"
    if any(phase.status == "waiting_approval" for phase in phases):
        return "waiting_approval"
    if any(phase.status == "running" for phase in phases):
        return "running"
    if phases and all(phase.status == "done" for phase in phases):
        return "done"
    return "pending" if phases else "running"


def _current_workbench_phase(
    phases: list[AgentPhaseSnapshot],
) -> AgentPhaseSnapshot | None:
    for status in ("running", "waiting_approval", "error", "pending"):
        for phase in phases:
            if phase.status == status:
                return phase
    return phases[-1] if phases else None


def _coerce_preview_record(preview: Any) -> dict[str, Any] | None:
    if isinstance(preview, dict):
        return preview
    if isinstance(preview, str) and preview.strip():
        with contextlib.suppress(json.JSONDecodeError):
            parsed = json.loads(preview)
            if isinstance(parsed, dict):
                return parsed
    return None


def _todo_phase_status(value: Any) -> str:
    if value in ("completed", "done"):
        return "done"
    if value in ("in_progress", "running"):
        return "running"
    if value in ("blocked", "waiting_approval"):
        return "waiting_approval"
    if value in ("error", "failed"):
        return "error"
    return "pending"


def _phase_title(title: str, index: int) -> str:
    clean = re.sub(r"\s+", " ", title).strip()
    if re.match(r"^phase\s+\d+", clean, flags=re.IGNORECASE):
        return clean
    return f"Phase {index + 1}: {clean}"


def _workspace_focus_for_tool(item: CommandExecutionItem) -> WorkspaceFocus:
    preview = _coerce_preview_record(item.input_preview) or {}
    name = item.command or "tool"
    target = _first_string(
        preview,
        (
            "command",
            "cmd",
            "path",
            "file_path",
            "filepath",
            "url",
            "query",
            "pattern",
            "cwd",
        ),
    )
    lower = name.lower()
    if name == "todo_write":
        view = "trace"
        title = "Updating plan"
    elif re.search(r"shell|bash|terminal|cmd|exec|python|powershell|cli", lower):
        view = "terminal"
        title = f"Running {name}"
    elif re.search(r"browser|url|web|fetch|screenshot", lower):
        view = "browser"
        title = f"Browsing with {name}"
    elif re.search(r"edit|write|replace|patch|diff|create|delete|artifact", lower):
        view = "diff"
        title = f"Editing with {name}"
    else:
        view = "trace"
        title = name.replace("_", " ")
    return WorkspaceFocus(
        itemId=item.id,
        view=view,  # type: ignore[arg-type]
        title=title,
        subtitle=target or None,
    )


def _workspace_focus_for_file_change(item: FileChangeItem) -> WorkspaceFocus:
    first_path = item.changes[0].path if item.changes else ""
    title = f"Editing {first_path}" if first_path else "File changes"
    return WorkspaceFocus(
        itemId=item.id,
        view="diff",
        title=title,
        subtitle=first_path or None,
    )


def _first_string(record: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _safe_list_remove(bucket: list[Any], item: Any) -> None:
    """Remove ``item`` from ``bucket`` if present. Tolerant of races
    (the bucket may have been swept out from under us by a concurrent
    reap)."""
    with contextlib.suppress(ValueError):
        bucket.remove(item)


_CODE_CHANGE_SUFFIXES = frozenset(
    {
        ".py",
        ".js",
        ".jsx",
        ".ts",
        ".tsx",
        ".mjs",
        ".cjs",
        ".go",
        ".rs",
        ".java",
        ".kt",
        ".kts",
        ".swift",
        ".cs",
        ".cpp",
        ".cc",
        ".cxx",
        ".c",
        ".h",
        ".hpp",
        ".rb",
        ".php",
        ".sh",
        ".ps1",
        ".sql",
        ".vue",
        ".svelte",
    }
)

_CODE_CHANGE_FILENAMES = frozenset(
    {
        "package.json",
        "pnpm-lock.yaml",
        "package-lock.json",
        "yarn.lock",
        "pyproject.toml",
        "pytest.ini",
        "ruff.toml",
        "tsconfig.json",
        "vite.config.ts",
        "vite.config.js",
        "next.config.js",
        "next.config.mjs",
        "go.mod",
        "go.sum",
        "cargo.toml",
        "cargo.lock",
        "dockerfile",
        "docker-compose.yml",
        "docker-compose.yaml",
    }
)


def _is_code_change_path(path: str) -> bool:
    normalized = path.replace("\\", "/").rsplit("/", 1)[-1].lower()
    if normalized in _CODE_CHANGE_FILENAMES:
        return True
    _, ext = os.path.splitext(normalized)
    return ext.lower() in _CODE_CHANGE_SUFFIXES


def _file_change_items(turn: Turn) -> list[FileChangeItem]:
    return [item for item in turn.items if isinstance(item, FileChangeItem)]


def _verification_items(turn: Turn) -> list[VerificationItem]:
    return [item for item in turn.items if isinstance(item, VerificationItem)]


def _code_change_paths(turn: Turn) -> list[str]:
    paths: list[str] = []
    for item in _file_change_items(turn):
        for change in item.changes:
            if _is_code_change_path(change.path) and change.path not in paths:
                paths.append(change.path)
    return paths


def _file_change_item_ids(turn: Turn) -> list[str]:
    return [item.id for item in _file_change_items(turn)]


def _normalized_path_key(path: str) -> str:
    return path.replace("\\", "/").lower()


def _verification_matches_code_changes(
    item: VerificationItem,
    *,
    code_paths: list[str],
    change_item_ids: list[str],
) -> bool:
    if not code_paths:
        return False

    code_path_keys = {_normalized_path_key(path) for path in code_paths}
    change_id_set = set(change_item_ids)
    related_ids = set(item.related_change_item_ids)
    if related_ids:
        return bool(related_ids & change_id_set)

    related_path_keys = {
        _normalized_path_key(path)
        for path in item.related_files
        if isinstance(path, str) and path.strip()
    }
    if related_path_keys:
        return bool(related_path_keys & code_path_keys)

    # No explicit relationship means a completed verification command is
    # a turn-level check. Once relationship metadata exists, it must match.
    return True


def _turn_has_passing_code_verification(turn: Turn) -> bool:
    code_paths = _code_change_paths(turn)
    if not code_paths:
        return True
    change_item_ids = _file_change_item_ids(turn)
    return any(
        item.status == ItemStatus.COMPLETED
        and _verification_matches_code_changes(
            item,
            code_paths=code_paths,
            change_item_ids=change_item_ids,
        )
        for item in _verification_items(turn)
    )


def _turn_has_failed_code_verification(turn: Turn) -> bool:
    code_paths = _code_change_paths(turn)
    change_item_ids = _file_change_item_ids(turn)
    for item in _verification_items(turn):
        if item.status != ItemStatus.FAILED:
            continue
        if _verification_matches_code_changes(
            item,
            code_paths=code_paths,
            change_item_ids=change_item_ids,
        ):
            return True
        if not code_paths and any(_is_code_change_path(path) for path in item.related_files):
            return True
    return False


def _turn_has_unverified_code_changes(turn: Turn) -> bool:
    return bool(_code_change_paths(turn)) and not _turn_has_passing_code_verification(turn)


def _turn_model(turn: Turn) -> str | None:
    model = getattr(turn.params, "model", None) if getattr(turn, "params", None) else None
    return model if isinstance(model, str) and model.strip() else None


def _turn_goal_text(turn: Turn, intent: ParsedIntent | None) -> str:
    if intent is not None:
        goal = getattr(intent, "normalized_goal", None)
        if isinstance(goal, str) and goal.strip():
            return goal.strip()
    params = getattr(turn, "params", None)
    if params is not None:
        parts: list[str] = []
        for block in getattr(params, "input", []) or []:
            if not isinstance(block, dict):
                continue
            text = block.get("text")
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())
        if parts:
            return "\n".join(parts).strip()
    return ""


def _turn_failure_text(turn: Turn) -> str:
    if isinstance(turn.error, dict):
        message = turn.error.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()
    for item in reversed(turn.items):
        if isinstance(item, ErrorItem) and item.message.strip():
            return item.message.strip()
        if isinstance(item, VerificationItem) and item.status == ItemStatus.FAILED:
            for candidate in (item.summary, item.stderr_tail, item.stdout_tail):
                if isinstance(candidate, str) and candidate.strip():
                    return candidate.strip()
    return "turn failed"


def _turn_item_counts(turn: Turn) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in turn.items:
        item_type = getattr(item.type, "value", str(item.type))
        counts[item_type] = counts.get(item_type, 0) + 1
    return counts


def _failed_turn_metadata(
    turn: Turn,
    *,
    intent: ParsedIntent | None,
    failure_source: str,
) -> dict[str, Any]:
    verification_items = _verification_items(turn)
    failed_verifications = [
        {
            "command": item.command,
            "kind": item.kind,
            "summary": item.summary,
            "exit_code": item.exit_code,
            "related_files": list(item.related_files),
            "related_change_item_ids": list(item.related_change_item_ids),
        }
        for item in verification_items
        if item.status == ItemStatus.FAILED
    ]
    return {
        "turn_id": turn.id,
        "thread_id": turn.thread_id,
        "failure_source": failure_source,
        "goal": _turn_goal_text(turn, intent),
        "error": _turn_failure_text(turn),
        "status": str(turn.status.value if hasattr(turn.status, "value") else turn.status),
        "item_counts": _turn_item_counts(turn),
        "code_change_paths": _code_change_paths(turn),
        "verification_count": len(verification_items),
        "failed_verifications": failed_verifications,
        "has_code_changes": bool(_code_change_paths(turn)),
    }


def _failed_turn_description(metadata: dict[str, Any]) -> str:
    goal = str(metadata.get("goal") or "").strip()
    error = str(metadata.get("error") or "").strip()
    source = str(metadata.get("failure_source") or "turn_failure").strip()
    goal_part = goal[:120] if goal else "(no goal)"
    error_part = error[:120] if error else "turn failed"
    return f"{source}: {error_part} | goal={goal_part}"


def _successful_turn_metadata(
    turn: Turn,
    *,
    intent: ParsedIntent | None,
) -> dict[str, Any]:
    return {
        "turn_id": turn.id,
        "thread_id": turn.thread_id,
        "goal": _turn_goal_text(turn, intent),
        "status": str(turn.status.value if hasattr(turn.status, "value") else turn.status),
        "item_counts": _turn_item_counts(turn),
        "code_change_paths": _code_change_paths(turn),
        "verification_count": len(_verification_items(turn)),
        "has_code_changes": bool(_code_change_paths(turn)),
    }


def _successful_turn_description(metadata: dict[str, Any]) -> str:
    goal = str(metadata.get("goal") or "").strip()
    goal_part = goal[:120] if goal else "(no goal)"
    return f"turn_success | goal={goal_part}"


def _file_change_item_from_tool_evt(evt: dict[str, Any]) -> FileChangeItem | None:
    """Build a structured FileChangeItem from a react_loop ``tool_end`` event.

    Two input shapes are accepted:

      * ``evt["diff"]``               — a raw unified-diff string (multi-file ok).
      * ``evt["file_changes"]``       — a pre-parsed list of
        ``{path, op, diff?, hunks?}`` dicts; skills that already know
        the shape can emit these directly to avoid a re-parse.

    Returns ``None`` when neither is present or both are empty — the
    caller must not emit an empty FileChangeItem.
    """
    raw_diff = evt.get("diff")
    if isinstance(raw_diff, str) and raw_diff.strip():
        changes = parse_unified_diff(raw_diff)
        if changes:
            if diff_is_truncated(raw_diff):
                # The marker sits at the tail of the combined diff, so
                # only the last file's diff is known-incomplete.
                changes[-1].diff_truncated = True
            return FileChangeItem(changes=changes)

    raw_list = evt.get("file_changes")
    if isinstance(raw_list, list) and raw_list:
        parsed: list[FileChange] = []
        for entry in raw_list:
            if not isinstance(entry, dict):
                continue
            path = entry.get("path")
            op = entry.get("op")
            if not isinstance(path, str) or op not in ("create", "update", "delete"):
                continue
            diff_str = entry.get("diff") if isinstance(entry.get("diff"), str) else None
            hunks_raw = entry.get("hunks")
            hunks: list[FileHunk] = []
            if isinstance(hunks_raw, list):
                for h in hunks_raw:
                    if not isinstance(h, dict):
                        continue
                    hunks.append(
                        FileHunk(
                            old_start=int(h.get("old_start", h.get("oldStart", 0)) or 0),
                            old_lines=int(h.get("old_lines", h.get("oldLines", 0)) or 0),
                            new_start=int(h.get("new_start", h.get("newStart", 0)) or 0),
                            new_lines=int(h.get("new_lines", h.get("newLines", 0)) or 0),
                            body=str(h.get("body", "")),
                        )
                    )
            if not hunks and diff_str:
                sub = parse_unified_diff(diff_str)
                if sub:
                    hunks = sub[0].hunks
            parsed.append(
                FileChange(
                    path=path,
                    op=op,
                    diff=diff_str,
                    diff_truncated=diff_is_truncated(diff_str),
                    hunks=hunks,
                )
            )
        if parsed:
            return FileChangeItem(changes=parsed)
    return None


def _verification_item_from_tool_evt(
    command_item: CommandExecutionItem,
    evt: dict[str, Any],
    *,
    related_change_item_ids: list[str] | None = None,
    related_files: list[str] | None = None,
) -> VerificationItem | None:
    """Promote embedded post-write diagnostics to a first-class item."""

    explicit = evt.get("verification")
    if isinstance(explicit, dict):
        kind = explicit.get("kind")
        if kind not in {"test", "lint", "typecheck", "build", "diagnostic", "manual"}:
            kind = "manual"
        success = explicit.get("success")
        exit_code = explicit.get("exit_code")
        if not isinstance(exit_code, int):
            exit_code = 0 if success is True else None
        if success is True:
            status = ItemStatus.COMPLETED
        elif success is False:
            status = ItemStatus.FAILED
        elif isinstance(exit_code, int):
            status = ItemStatus.COMPLETED if exit_code == 0 else ItemStatus.FAILED
        else:
            status = (
                ItemStatus.COMPLETED
                if evt.get("status") == "success"
                else ItemStatus.FAILED
            )
        stdout_tail = explicit.get("stdout_tail")
        stderr_tail = explicit.get("stderr_tail")
        stdout_tail = stdout_tail[-4000:] if isinstance(stdout_tail, str) else None
        stderr_tail = stderr_tail[-4000:] if isinstance(stderr_tail, str) else None
        summary_src = stderr_tail or stdout_tail or command_item.aggregated_output
        summary = None
        if isinstance(summary_src, str) and summary_src.strip():
            summary = summary_src.strip().splitlines()[0][:240]
        command = explicit.get("command")
        if not isinstance(command, str) or not command.strip():
            command = command_item.command
        explicit_related_files = explicit.get("related_files")
        if not isinstance(explicit_related_files, list):
            explicit_related_files = explicit.get("relatedFiles")
        verification_related_files: list[str] = []
        if isinstance(explicit_related_files, list):
            verification_related_files = [
                path for path in explicit_related_files if isinstance(path, str) and path.strip()
            ]
        if not verification_related_files:
            verification_related_files = list(related_files or [])
        return VerificationItem(
            command=command,
            kind=kind,
            status=status,
            exit_code=exit_code,
            summary=summary,
            stdout_tail=stdout_tail,
            stderr_tail=stderr_tail,
            related_files=verification_related_files,
            related_change_item_ids=list(related_change_item_ids or []),
        )

    output = ""
    if isinstance(evt.get("output_preview"), str):
        output = evt["output_preview"]
    if command_item.aggregated_output:
        output = command_item.aggregated_output
    if not output:
        return None

    markers = (
        "[post-write diagnostics]",
        "[自动诊断结果]",
        "ruff diagnostics",
        "eslint diagnostics",
    )
    if not any(marker in output for marker in markers):
        return None

    diagnostic_related_files: list[str] = list(related_files or [])
    file_item = _file_change_item_from_tool_evt(evt)
    if file_item is not None:
        for change in file_item.changes:
            if change.path not in diagnostic_related_files:
                diagnostic_related_files.append(change.path)
    preview = command_item.input_preview
    if isinstance(preview, dict):
        path = preview.get("path") or preview.get("file_path")
        if isinstance(path, str) and path and path not in diagnostic_related_files:
            diagnostic_related_files.append(path)

    tail = output[-4000:]
    stripped = tail.strip()
    summary = stripped.splitlines()[0][:240] if stripped else None
    return VerificationItem(
        command="post-write diagnostics",
        kind="diagnostic",
        status=ItemStatus.FAILED,
        exit_code=1,
        summary=summary,
        stdout_tail=tail,
        stderr_tail=None,
        related_files=diagnostic_related_files,
        related_change_item_ids=list(related_change_item_ids or []),
    )


def _join_text(blocks: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for block in blocks:
        if isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "\n".join(parts).strip()


def _input_attachments(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    attachments: list[dict[str, Any]] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        raw = block.get("attachments")
        if not isinstance(raw, list):
            continue
        attachments.extend(item for item in raw if isinstance(item, dict))
    return attachments


def _input_metadata(params: TurnParams) -> dict[str, Any]:
    for block in params.input:
        if not isinstance(block, dict):
            continue
        metadata = block.get("metadata")
        if isinstance(metadata, dict):
            return metadata
    return {}


def _agent_id_from_params(params: TurnParams) -> str | None:
    metadata = _input_metadata(params)
    candidates: list[Any] = [
        metadata.get("agent_id"),
        metadata.get("agent"),
        metadata.get("agent_name"),
    ]
    context = metadata.get("context")
    if isinstance(context, dict):
        candidates.extend([
            context.get("agent_id"),
            context.get("agent"),
            context.get("agent_name"),
        ])
    for value in candidates:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _preview_text(text: str, *, limit: int = 120) -> str:
    value = " ".join(str(text or "").split())
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 1)].rstrip() + "..."


def _conversation_messages_from_params(params: TurnParams) -> list[dict[str, object]]:
    metadata = _input_metadata(params)
    candidates: object = None
    context = metadata.get("context")
    if isinstance(context, dict):
        candidates = context.get("conversation_messages") or context.get("messages")
    if not isinstance(candidates, list):
        candidates = metadata.get("conversation_messages") or metadata.get("messages")
    if not isinstance(candidates, list):
        return []
    return [message for message in candidates if isinstance(message, dict)]


def _reflex_response_to_text(response: Any) -> str | None:
    if isinstance(response, str):
        return response.strip() or None
    if isinstance(response, dict):
        for key in ("reply", "text", "message", "response"):
            value = response.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _parse_resume_intent(text: str) -> dict[str, Any] | None:
    match = _RESUME_PROPOSAL_BLOCK_RE.search(text or "")
    if match is None:
        return None
    try:
        raw = json.loads(match.group(1))
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None

    checkpoint_id = _safe_int(raw.get("checkpoint_id"))
    iteration = _safe_int(raw.get("iteration"))
    if checkpoint_id is None or iteration is None:
        return None

    resume_plan = [
        str(step).strip()
        for step in raw.get("resume_plan", [])
        if isinstance(step, str) and step.strip()
    ][:12]
    working_set = [
        str(path).strip()
        for path in raw.get("working_set", [])
        if isinstance(path, str) and path.strip()
    ][:32]

    return {
        "schema": "octopus.resume_intent.v1",
        "requires_confirmation": True,
        "source": "resume_proposal_block",
        "checkpoint_id": checkpoint_id,
        "task_id": _safe_str(raw.get("task_id")),
        "checkpoint_type": _safe_str(raw.get("checkpoint_type")) or "unknown",
        "iteration": iteration,
        "continue_from_iteration": iteration + 1,
        "phase": _safe_str(raw.get("phase")),
        "progress": _safe_str(raw.get("progress")),
        "working_set": working_set,
        "resume_plan": resume_plan,
        "safety": {
            "raw_state_included": bool(raw.get("raw_state_included") is True),
            "raw_message_snapshots_included": bool(
                raw.get("raw_message_snapshots_included") is True,
            ),
        },
    }


def _parse_resume_confirmation(text: str) -> int | None:
    match = _RESUME_CONFIRM_RE.search(text or "")
    if match is None:
        return None
    return _safe_int(match.group(1))


def _execution_resume_intent(
    pending: dict[str, Any],
    checkpoint_id: int,
) -> dict[str, Any]:
    return {
        "schema": "octopus.resume_intent.v1",
        "requires_confirmation": False,
        "confirmed": True,
        "source": pending.get("source") or "resume_proposal_block",
        "checkpoint_id": checkpoint_id,
        "task_id": _safe_str(pending.get("task_id")),
        "checkpoint_type": _safe_str(pending.get("checkpoint_type")) or "unknown",
        "iteration": _safe_int(pending.get("iteration")),
        "continue_from_iteration": _safe_int(
            pending.get("continue_from_iteration"),
        ),
        "phase": _safe_str(pending.get("phase")),
        "working_set": [
            path
            for path in pending.get("working_set", [])
            if isinstance(path, str) and path.strip()
        ][:32],
        "safety": {
            "raw_state_included": bool(
                (pending.get("safety") or {}).get("raw_state_included") is True,
            )
            if isinstance(pending.get("safety"), dict)
            else False,
            "raw_message_snapshots_included": bool(
                (pending.get("safety") or {}).get("raw_message_snapshots_included") is True,
            )
            if isinstance(pending.get("safety"), dict)
            else False,
        },
        "confirmation_text": f"确认恢复 checkpoint #{checkpoint_id}",
    }


def _resume_confirmation_text(resume_intent: dict[str, Any]) -> str:
    checkpoint_id = resume_intent.get("checkpoint_id")
    iteration = resume_intent.get("iteration")
    continue_from = resume_intent.get("continue_from_iteration")
    task_id = resume_intent.get("task_id") or "unknown"
    checkpoint_type = resume_intent.get("checkpoint_type") or "unknown"
    phase = resume_intent.get("phase") or "unknown"
    working_set = [
        path
        for path in resume_intent.get("working_set", [])
        if isinstance(path, str) and path.strip()
    ][:8]
    resume_plan = [
        step
        for step in resume_intent.get("resume_plan", [])
        if isinstance(step, str) and step.strip()
    ][:6]

    lines = [
        f"恢复请求已准备：checkpoint #{checkpoint_id}，需要你明确确认后才会继续执行。",
        "",
        f"- 任务：{task_id}",
        f"- 类型：{checkpoint_type}",
        f"- 迭代：{iteration} -> {continue_from}",
        f"- 阶段：{phase}",
        "- 进展：已读取安全恢复摘要",
    ]
    if working_set:
        lines.append(f"- 工作文件：{', '.join(working_set)}")
    if resume_plan:
        lines.append("")
        lines.append(f"建议恢复计划：{len(resume_plan)} 步")
    lines.append("")
    lines.append(f"如需继续，请回复：确认恢复 checkpoint #{checkpoint_id}")
    return "\n".join(lines)


def _safe_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def _safe_str(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _is_auth_context_error(exc: BaseException) -> bool:
    text = f"{type(exc).__name__}: {exc}"
    return (
        "current_actor" in text
        or "登录态" in text
        or "Unauthorized" in text
        or "Credentials" in text
        or "Auth" in text
    )


def _model_error_reply(exc: BaseException) -> str | None:
    text = f"{type(exc).__name__}: {exc}"
    lower = text.lower()
    if "http_402" in lower or "insufficient_balance" in lower or "模型账户余额不足" in text:
        return "当前模型账户余额不足，所以这次没有完成。请给当前模型供应商账户充值，或切换到其他可用模型后重试。"
    if "http_401" in lower or "http_403" in lower or "api key" in lower:
        return "当前模型 API Key 无效或没有权限，所以这次没有完成。请在模型设置里更新 Key，或切换到其他可用模型后重试。"
    return None


def _turn_mode(params: TurnParams) -> str:
    metadata = _input_metadata(params)
    context = metadata.get("context")
    if isinstance(context, dict) and isinstance(context.get("mode"), str):
        return context["mode"].strip().lower()
    mode = metadata.get("mode")
    if isinstance(mode, str):
        return mode.strip().lower()
    return ""


def _build_intent(
    text: str,
    params: TurnParams,
    *,
    workspaces: Any = None,
    thread_store: Any = None,
    allow_client_auto_approve: bool = False,
    conversation_messages: list[dict[str, str]] | None = None,
) -> ParsedIntent:
    cwd = params.cwd
    if workspaces is not None:
        cwd = workspaces.resolve_cwd(params.thread_id, params.cwd)
    metadata = _input_metadata(params)
    context = metadata.get("context")
    context_payload = context if isinstance(context, dict) else {}
    if thread_store is not None:
        from runtime.sensing.gateway.turn_session import build_turn_metadata

        context_payload = build_turn_metadata(
            thread_id=params.thread_id,
            body={"context": context_payload},
            store=thread_store,
        )
    context_payload = dict(context_payload)
    actor_id = metadata.get("actor_id") or metadata.get("actorId")
    if isinstance(actor_id, str) and actor_id.strip():
        context_payload.setdefault("owner_actor_id", actor_id.strip())
    if conversation_messages and not isinstance(
        context_payload.get("conversation_messages"),
        list,
    ):
        context_payload["conversation_messages"] = conversation_messages
    resume_intent = _parse_resume_intent(text)
    if resume_intent is not None:
        context_payload["resume_intent"] = resume_intent
    if "effort" in getattr(params, "model_fields_set", set()):
        context_payload["reasoning_effort"] = params.effort
    # Defense in depth: ``RealtimeGateway._sanitize_turn_params`` already
    # rewrites ``approvalPolicy="never"`` to ``"on-request"`` when the
    # operator hasn't opted in. We re-check here so tests that drive
    # CerebrumRuntime directly (bypassing the gateway) cannot silently
    # disable approval gates either.
    approval_policy = params.approval_policy
    if approval_policy == "never" and not allow_client_auto_approve:
        approval_policy = "on-request"
    return ParsedIntent(
        raw=text,
        intent_type="task",
        normalized_goal=text,
        user_context={
            **context_payload,
            "approval_policy": approval_policy,
            "auto_approve": approval_policy == "never",
            "cwd": cwd,
            "mode": _turn_mode(params) or context_payload.get("mode"),
            "planning_mode": bool(getattr(params, "planning_mode", False)),
            # Pass attachments through so react_loop can fold image-typed
            # ones into the user message as OpenAI image_url content
            # blocks (vision models then actually "see" the image).
            "attachments": _input_attachments(params.input),
        },
    )


# Static check: this class fulfills the realtime contract.
_: RealtimeRuntime = CerebrumRuntime.__new__(CerebrumRuntime)  # type: ignore[arg-type]
del _


__all__ = ["CerebrumRuntime", "GatewayApprovalProvider"]
