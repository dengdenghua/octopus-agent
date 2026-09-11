"""Text-only Project OS planning through the selected host execution engine."""

from typing import Any

from runtime.platform.models.llm import ModelResponse


class OpenCodePlanningRouter:
    def __init__(self, stack: Any, agent: Any, interrupted: Any) -> None:
        self.stack = stack
        self.agent = agent
        self.interrupted = interrupted

    def call(self, request: Any) -> ModelResponse:
        from runtime.execution.opencode_roles import run_role_sync

        text = "\n\n".join(f"[{m.role}]\n{m.content}" for m in request.messages)
        result = run_role_sync(
            self.stack, self.agent, text,
            context={"model_name": request.model, "direct_conversation_reply": True},
            tool_ceiling=frozenset(), interrupted=self.interrupted,
        )
        return ModelResponse(text=result)
