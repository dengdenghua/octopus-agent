"""Run foreground text helpers on the engine already bound to the host task."""

from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4


class AuxiliaryModelRouter:
    def __init__(self, stack, native_router):
        self.stack = stack
        self.native_router = native_router

    def call(self, request):
        from runtime.execution.request import (
            ExecutionRequest,
            current_execution_request,
            execution_request_scope,
        )
        from runtime.platform.process.session import current_session, session_scope
        from runtime.safety.approval.cancellation import current_cancellation_token

        parent = current_execution_request()
        if parent is None or parent.task.execution_engine not in {"opencode", "codex"}:
            return self.native_router.call(request)
        session = current_session()
        task = parent.task
        if session is None or session.metadata.get("_execution_task") is not task:
            raise ValueError("auxiliary model requires the bound host session")
        if session.actor != task.actor_id or session.metadata.get("tenant_id") != task.tenant_id:
            raise ValueError("auxiliary model principal does not match host task")
        task.resources.remaining_seconds()
        cancellation = current_cancellation_token()
        cancellation.throw_if_cancelled()
        if any(not isinstance(message.content, str) for message in request.messages):
            raise ValueError("auxiliary external calls support text messages only")
        system = "\n\n".join(
            message.content for message in request.messages if message.role == "system"
        )
        prompt = "\n\n".join(
            f"{message.role}:\n{message.content}"
            for message in request.messages
            if message.role != "system"
        )
        agent = SimpleNamespace(
            agent_id="host_text_helper",
            display_name="Text helper",
            soul=system,
            model=None,
            arms=(),
            extra_skills=(),
            capabilities={},
        )
        context = {**session.metadata, "caller_session": session, "direct_conversation_reply": True}
        # request.model belongs to the legacy helper configuration. External
        # helpers use the host's selected engine model, never that native hint.
        model = context.get("model_name")
        usage = {"input_tokens": None, "output_tokens": None}

        def receipt(event):
            nonlocal model
            if event.get("type") == "react_completed":
                reported = event.get("completion_receipt")
                if not isinstance(reported, dict):
                    return
                model = reported.get("model") or model
                tokens = reported.get("tokens", {})
                if not isinstance(tokens, dict):
                    return
                cache = tokens.get("cache", {})
                cache = cache if isinstance(cache, dict) else {}
                inputs = [tokens.get("input"), cache.get("read", 0), cache.get("write", 0)]
                if all(type(value) is int and value >= 0 for value in inputs):
                    usage["input_tokens"] = sum(inputs)
                if type(tokens.get("output")) is int and tokens["output"] >= 0:
                    usage["output_tokens"] = tokens["output"]
            elif event.get("type") == "throughput":
                reported = event.get("usage", {})
                total = reported.get("total") if isinstance(reported, dict) else None
                if isinstance(total, dict):
                    for source, target in (
                        ("inputTokens", "input_tokens"),
                        ("outputTokens", "output_tokens"),
                    ):
                        if type(total.get(source)) is int and total[source] >= 0:
                            usage[target] = total[source]

        if task.execution_engine == "opencode":
            from runtime.execution.opencode_roles import run_role_sync

            text = run_role_sync(
                self.stack,
                agent,
                prompt,
                context=context,
                interrupted=lambda: cancellation.is_cancelled,
                tool_ceiling=frozenset(),
                on_event=receipt,
            )
        else:
            from runtime.execution.codex_backend.role_runner import run_agent_role_sync

            identity = f"helper_{uuid4().hex}"
            child_task = replace(
                task, task_id=identity, thread_id=identity, parent_task_id=task.task_id, goal=prompt
            )
            child = replace(
                session,
                agent=agent,
                thread_id=identity,
                turn_id=identity,
                metadata={**session.metadata, "_execution_task": child_task},
            )
            context["caller_session"] = child
            with (
                session_scope(child),
                execution_request_scope(ExecutionRequest(child_task, prompt)),
            ):
                result = run_agent_role_sync(
                    self.stack,
                    agent,
                    prompt,
                    context=context,
                    is_interrupted=lambda: cancellation.is_cancelled,
                    event_callback=receipt,
                )
            if not result.success:
                raise RuntimeError(f"Codex auxiliary call failed: {result.status}")
            text, model = result.output, result.model
        cancellation.throw_if_cancelled()
        task.resources.remaining_seconds()
        if not text.strip():
            raise RuntimeError("auxiliary model returned an empty response")
        return SimpleNamespace(text=text, model=model, **usage)
