"""Codex CLI adapter using the shared scoped App Server lifecycle."""

import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace


def run_cli_codex(
    *, stack, agent, prompt, model, thread_id, metadata, history, provider, args, emit
):
    from runtime.cli_execution import cli_execution_boundary
    from runtime.execution.codex_backend.role_runner import (
        ServerCodexExecutionOverride,
        run_agent_role,
    )
    from runtime.execution.request import execution_request_scope
    from runtime.platform.process.session import session_scope

    request, session = cli_execution_boundary(
        engine="codex",
        agent=agent,
        prompt=prompt,
        thread_id=thread_id,
        metadata=metadata,
        provider=provider,
        args=args,
    )
    session = replace(
        session,
        metadata={
            **session.metadata,
            "_approval_provider": provider,
            "_server_codex_execution_override": ServerCodexExecutionOverride(
                model=None if model == "auto" else model
            ),
        },
    )
    context = {
        **metadata,
        "caller_session": session,
        "conversation_messages": history,
        "timeout_s": float(getattr(args, "timeout", 900)),
    }
    text = prompt
    if history:
        text = (
            "Previous conversation (context only):\n"
            + json.dumps(history, ensure_ascii=False)
            + "\n\nCurrent request:\n"
            + prompt
        )
    with execution_request_scope(request), session_scope(session):
        result = asyncio.run(
            run_agent_role(
                stack,
                agent,
                text,
                context=context,
                event_callback=emit,
                server_auto_approve=request.task.server_auto_approve,
            )
        )
    return SimpleNamespace(
        final_answer=result.output,
        success=result.success and bool(result.output.strip()),
        terminated_reason=result.status,
        model=result.model or model,
    )
