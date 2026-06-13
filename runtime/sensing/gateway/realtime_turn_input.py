"""Turn-input shaping for the realtime runtime.

Split out of ``realtime_cerebrum.py``: everything that turns the raw
``turn/start`` params into structured execution inputs — text/attachment
extraction, metadata/mode lookup, resume-intent parsing and confirmation
texts, default planning-mode / topology routing, and the final
``ParsedIntent`` assembly via :func:`_build_intent`.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any
from uuid import UUID

from runtime.platform.models import ParsedIntent, TaskId
from runtime.protocol import TurnParams

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
_TOPOLOGY_KEYWORD_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "code_review_team_v1",
        re.compile(
            r"代码评审|代码审查|代码 review|"
            r"\bcode\s*review\b|\bsecurity\s*audit\b|"
            r"安全审查|安全审计|"
            r"PR review|review (?:the |this )?PR",
            re.IGNORECASE,
        ),
    ),
    (
        "debug_team_v1",
        re.compile(
            r"调试|排查|debug\b|找出.*bug|"
            r"\bstack\s*trace\b|\btraceback\b|"
            r"为什么.*报错|为什么.*失败|"
            r"重现.*问题|reproduce.*bug",
            re.IGNORECASE,
        ),
    ),
    (
        "refactor_pair_v1",
        re.compile(
            r"重构|refactor\b|"
            r"重新组织.*代码|重新设计.*结构|"
            r"拆分.*文件|拆分.*模块|"
            r"提取.*公共|抽取.*函数",
            re.IGNORECASE,
        ),
    ),
    (
        "research_swarm_v1",
        re.compile(
            r"调研|研究报告|市场研究|行业报告|竞品分析|竞争分析|"
            r"\bdeep\s*research\b|\bmarket\s*research\b|\bresearch\s*report\b|"
            r"\bcompetitive\s*analysis\b|"
            r"做.*调研|做一份.*报告|写.*研究",
            re.IGNORECASE,
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
        candidates.extend(
            [
                context.get("agent_id"),
                context.get("agent"),
                context.get("agent_name"),
            ]
        )
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
