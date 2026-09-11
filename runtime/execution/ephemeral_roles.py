"""Bind temporary roles to the configured host member engine."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any


def make_host_ephemeral_runner(stack: Any):
    from runtime.execution.parallel_agents.stack_runner import member_execution_backend

    if member_execution_backend(stack, None) == "native":

        def run_native(call):
            from runtime.execution.suckers.ephemeral_runner import make_llm_ephemeral_runner

            planner = getattr(stack, "planner", None)
            router = getattr(planner, "router", None)
            if router is None:
                raise RuntimeError("native temporary roles require a model router")

            runner = make_llm_ephemeral_runner(
                router,
                registry=stack.executor.registry,
                default_model=getattr(planner, "planner_model", None),
            )
            return runner(call)

        return run_native

    def run(call):
        from runtime.execution.opencode_roles import run_role_sync
        from runtime.execution.suckers.layers import EPHEMERAL_MEMORY_SKILLS, select_tool_specs
        from runtime.safety.approval.cancellation import current_cancellation_token

        context = dict(call.context or {})
        raw = context.get("tool_allowlist", call.role.tool_allowlist)
        allowlist = (
            tuple(str(name).strip() for name in raw) if isinstance(raw, (list, tuple, set)) else ()
        )
        # Reuse the temporary-role selector: empty means atomic inheritance,
        # blackboard tools are included, and read-only filtering happens last.
        specs = select_tool_specs(
            allowlist,
            [SimpleNamespace(name=name) for name in stack.executor.registry.list_enabled()],
            read_only=bool(context.get("tool_allowlist_read_only")),
        )
        ceiling = frozenset(spec.name for spec in specs) - EPHEMERAL_MEMORY_SKILLS
        agent = SimpleNamespace(
            agent_id=call.role.id,
            display_name=call.role.display_name,
            soul=call.composed_system_prompt,
            model=None,
            arms=(),
            extra_skills=tuple(ceiling),
            capabilities={"execution_backend": "opencode_server"},
        )
        cancellation = current_cancellation_token()
        tool_inputs: dict[str, dict[str, Any]] = {}

        def emit(event):
            from runtime.execution.suckers._ephemeral_events import (
                _emit_sub_text_delta,
                _emit_sub_tool_event,
                _safe_ctx_emit,
            )

            emitter = context.get("event_emitter")
            if event.get("type") == "text_delta":
                _emit_sub_text_delta(
                    call.role.id, 0, str(event.get("delta") or ""), emitter=emitter
                )
            elif event.get("type") in {"tool_start", "tool_end"}:
                kind = "sub_tool_start" if event["type"] == "tool_start" else "sub_tool_end"
                try:
                    preview = event.get("input_preview")
                    args = preview if isinstance(preview, dict) else json.loads(preview or "{}")
                except (ValueError, TypeError):
                    args = {}
                if not isinstance(args, dict):
                    args = {}
                call_id = str(event.get("tool_call_id") or "")
                if event["type"] == "tool_start":
                    tool_inputs[call_id] = args
                else:
                    args = tool_inputs.pop(call_id, args)
                _safe_ctx_emit(
                    emitter,
                    {
                        "type": kind,
                        "skill": event.get("tool_name"),
                        "args": args,
                        "status": "started"
                        if kind == "sub_tool_start"
                        else ("success" if event.get("success") else "error"),
                        "execution_engine": "opencode",
                    },
                )
                _emit_sub_tool_event(
                    kind,
                    role_id=call.role.id,
                    iteration=0,
                    tool_call=SimpleNamespace(
                        id=event.get("tool_call_id"), name=event.get("tool_name"), input=args
                    ),
                    output=event.get("output_preview"),
                    is_error=event.get("success") is False,
                )

        return run_role_sync(
            stack,
            agent,
            call.user_prompt,
            context=context,
            interrupted=lambda: cancellation.is_cancelled,
            tool_ceiling=ceiling,
            on_event=emit,
        )

    run.execution_backend = "opencode_server"
    return run
