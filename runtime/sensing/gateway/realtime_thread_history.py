"""Realtime turn ↔ legacy conversation history adapters.

Split out of ``realtime_cerebrum.py``: flatten a realtime ``Turn[]``
snapshot into the legacy ``AgentThreadState`` triple for the sidebar's
thread store, and into OpenAI-style chat history for
``stream_react_loop`` follow-up turns.
"""

from __future__ import annotations

from typing import Any

from runtime.protocol import Turn, TurnStatus


def _json_safe(value: Any) -> Any:
    """Recursively normalise objects into JSON-serialisable plain data.

    The legacy ``ThreadStateStore`` snapshot is written with
    ``json.dumps`` (no ``default=`` hook), so any pydantic model or
    other non-JSON object nested inside a flattened message (e.g.
    ``FileChange`` under ``tool_calls[].args.changes``) would raise
    ``TypeError`` and silently abort the turn-state write. Converting
    here keeps the snapshot writer robust without changing its wire
    contract.
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "model_dump"):
        try:
            return _json_safe(value.model_dump(by_alias=True, mode="json"))
        except Exception:  # noqa: BLE001 - best-effort flatten
            try:
                return _json_safe(value.model_dump())
            except Exception:  # noqa: BLE001
                return repr(value)
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    # datetime / Enum / any remaining non-JSON leaf: fall back to str.
    return str(value)


def _limit_text(text: str, limit: int) -> str:
    """Truncate a long text, keeping the head and marking the omitted tail.

    Progress anchors injected for failed turns must stay cheap; the tail is
    the least likely to carry actionable state (the conclusion preamble is).
    """
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n…（后文已省略）"


def _flatten_turns_to_messages(
    turns: list[Turn],
    *,
    include_failed_drafts: bool = True,
) -> tuple[list[dict[str, Any]], list[str], list[dict[str, Any]] | None]:
    """Translate a realtime ``Turn[]`` snapshot into the legacy
    ``AgentThreadState`` triple (messages, artifacts, todos).

    Mirrors the frontend ``conversationToAgentThreadState`` in
    ``src/core/threads/realtime-adapter.ts`` so a thread looks the same
    whether the sidebar loads it from the legacy store (this snapshot)
    or rehydrates it live from the WebSocket.

    Rules:
      * userMessage     → ``HumanMessage``
      * public reasoning summary + plan → folded into ``additional_kwargs``
                          of the next ``AIMessage`` in the same turn; raw
                          provider reasoning content is never copied
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

    ``include_failed_drafts`` controls how a FAILED / INTERRUPTED turn's
    intermediate agentMessage drafts are treated. When ``False`` (used by
    the model-context adapter ``_conversation_messages_for_react``), only
    the turn's user prompt and its final error are kept — the half-built
    commentary / reasoning / tool chain of a failed turn would otherwise
    leak stale task narrative into the next turn and make the model answer
    the *previous* (unfinished) question instead of the user's new one.
    The sidebar keeps ``True`` so the user can still review what happened.
    """
    messages: list[dict[str, Any]] = []
    artifacts: list[str] = []
    todos: list[dict[str, Any]] | None = None

    for turn in turns:
        turn_failed = turn.status in (
            TurnStatus.FAILED,
            TurnStatus.PAUSED,
            TurnStatus.CANCELLED,
            TurnStatus.INTERRUPTED,
        )
        # When not including failed drafts, drop every intermediate AI
        # message (commentary / reasoning / tool chain) of a failed turn
        # up front. The user prompt and any trailing error item are still
        # appended below; the model context then only sees the *failed*
        # fact, not the stale in-progress narrative it was building.
        if turn_failed and not include_failed_drafts:
            # Keep the task objective (user prompt), the last concrete
            # ``answer`` the turn produced (progress anchor) and the error
            # (when present). Commentary checkpoints are still dropped —
            # they are mid-flight narration, not a conclusion — but without
            # the anchor the next turn cannot tell what the previous run was
            # doing or how far it got.
            failed_user = ""
            user_id: Any = None
            last_answer: str | None = None
            error_item: Any = None
            for item in turn.items:
                t = getattr(item, "type", None)
                if t == "userMessage":
                    failed_user = getattr(item, "text", "") or ""
                    user_id = getattr(item, "id", None)
                elif t == "agentMessage" and (
                    getattr(item, "message_kind", "answer") == "answer"
                ):
                    text = (getattr(item, "text", "") or "").strip()
                    if text:
                        last_answer = text
                elif t == "error":
                    error_item = item
            if failed_user:
                messages.append(
                    {
                        "type": "human",
                        "id": user_id,
                        "content": failed_user,
                    }
                )
            if last_answer:
                messages.append(
                    {
                        "type": "ai",
                        "id": None,
                        "content": (
                            "[上一轮任务进行到：]\n"
                            f"{_limit_text(last_answer, 600)}"
                        ),
                    }
                )
            if error_item is not None:
                message = getattr(error_item, "message", "") or ""
                messages.append(
                    {
                        "type": "ai",
                        "id": getattr(error_item, "id", None),
                        "content": f"[上一轮任务失败。] {message}"
                        if message
                        else "[上一轮任务失败。]",
                        "additional_kwargs": {
                            "error": {
                                "message": message,
                                "will_retry": False,
                                "info": getattr(error_item, "error_info", None),
                            },
                        },
                    }
                )
            continue
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
                    incoming_reasoning = incoming_kwargs.get("public_reasoning_summary")
                    if isinstance(incoming_reasoning, str) and incoming_reasoning.strip():
                        existing_reasoning = existing_kwargs.get("public_reasoning_summary")
                        parts = [
                            part
                            for part in (
                                existing_reasoning if isinstance(existing_reasoning, str) else "",
                                incoming_reasoning,
                            )
                            if part.strip()
                        ]
                        existing_kwargs["public_reasoning_summary"] = "\n\n".join(parts)
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
                # ``content`` contains provider chain-of-thought and is
                # intentionally excluded from every user-facing legacy
                # snapshot. ``summary`` is the protocol's explicit public lane.
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
                            # FileChange is a pydantic model — the legacy
                            # ThreadStateStore json.dumps()s this snapshot, so
                            # raw model objects would raise TypeError and the
                            # whole turn-state write gets silently swallowed
                            # (updated_at frozen at thread creation). Normalise
                            # to plain dicts before handing off.
                            "changes": _json_safe(changes),
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
                    snapshot.append(
                        {
                            "content": title or "",
                            "status": status or "pending",
                            "objective_id": getattr(item, "objective_id", None)
                            or turn.objective_id,
                            "task_id": getattr(item, "task_id", None) or turn.task_id,
                            "turn_id": turn.id,
                        }
                    )
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

    For AI turns that executed tools, a compact ``[上轮操作: ...]`` summary
    is prepended to the content so the next round's model can see what was
    actually done without inflating the transcript with raw tool I/O.
    """

    legacy_messages, _, _ = _flatten_turns_to_messages(
        turns,
        include_failed_drafts=False,
    )
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
        content = content.strip()
        # Attach a compact tool-action summary so the next turn's model
        # understands what the previous round actually did, not just the
        # final prose. This is the cheapest way to give multi-turn
        # conversations continuity without rehydrating full step history.
        if role == "assistant":
            tool_calls = item.get("tool_calls")
            if isinstance(tool_calls, list) and tool_calls:
                tool_names: list[str] = []
                for call in tool_calls:
                    if not isinstance(call, dict):
                        continue
                    name = call.get("name")
                    if isinstance(name, str) and name and name not in tool_names:
                        tool_names.append(name)
                if tool_names:
                    summary = "、".join(tool_names[:6])
                    if len(tool_names) > 6:
                        summary += f" 等 {len(tool_names)} 个操作"
                    content = f"[上轮操作: {summary}]\n{content}"
        history.append({"role": role, "content": content})
    if max_messages > 0 and len(history) > max_messages:
        return history[-max_messages:]
    return history


def _build_ai_kwargs(
    reasoning: list[str],
    plan: str | None,
) -> dict[str, Any]:
    kw: dict[str, Any] = {}
    if reasoning:
        kw["public_reasoning_summary"] = "\n\n".join(reasoning)
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
