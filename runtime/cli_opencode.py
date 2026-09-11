"""OpenCode CLI host: tools, scoped execution, and events without a native planner."""

from __future__ import annotations

import asyncio
import contextlib
import json
from types import SimpleNamespace


def run_cli_opencode(
    *, stack, agent, prompt, model, thread_id, metadata, history, provider, args, emit
):
    from runtime.cli_execution import cli_execution_boundary
    from runtime.execution.opencode_backend import OpenCodeError, resolve_zen_model, zen_catalog
    from runtime.execution.opencode_roles import stream_role

    request, session = cli_execution_boundary(
        engine="opencode",
        agent=agent,
        prompt=prompt,
        thread_id=thread_id,
        metadata=metadata,
        provider=provider,
        args=args,
    )
    selected = resolve_zen_model(model, zen_catalog())
    # Each CLI invocation has its own engine task; restore the public conversation
    # as context rather than trusting an engine-private session from a JSON file.
    text = prompt
    if history:
        text = (
            "Previous conversation (context only):\n"
            + json.dumps(history, ensure_ascii=False)
            + "\n\nCurrent request:\n"
            + prompt
        )

    async def run():
        parts = []
        completed = False
        async with contextlib.aclosing(
            stream_role(
                stack,
                agent,
                request=request,
                session=session,
                context=metadata,
                model=selected,
                text=text,
                interrupted=lambda: False,
            )
        ) as stream:
            async for event in stream:
                emit(event)
                if event.get("type") == "text_delta":
                    if event.get("start_new_segment"):
                        parts.append("\n\n")
                    parts.append(str(event.get("delta") or ""))
                elif event.get("type") == "react_completed":
                    completed = event.get("success") is True
        answer = "".join(parts).strip()
        if not completed or not answer:
            raise OpenCodeError("OpenCode did not complete an answer.")
        from runtime.execution.opencode_backend import model_selection_id

        return SimpleNamespace(
            final_answer=answer,
            success=True,
            terminated_reason="completed",
            model=model_selection_id(selected),
        )

    return asyncio.run(run())
