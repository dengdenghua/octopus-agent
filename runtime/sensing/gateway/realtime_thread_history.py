"""Realtime turn ↔ legacy conversation history adapters.

Split out of ``realtime_cerebrum.py``: flatten a realtime ``Turn[]``
snapshot into the legacy ``AgentThreadState`` triple for the sidebar's
thread store, and into OpenAI-style chat history for
``stream_react_loop`` follow-up turns.
"""

from __future__ import annotations

from typing import Any

from runtime.protocol import Turn, TurnStatus


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
