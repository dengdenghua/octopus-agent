"""Local code-mode runtime health probes.

These checks are deliberately offline: they use scripted routers and fake HTTP
clients so readiness can verify the agent runtime's invariants without spending
tokens or depending on a model provider being reachable.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from runtime.platform.observability.health import HealthCheck, HealthStatus


@dataclass
class _ScriptedResponse:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    finish_reason: str = "stop"


class _CapturingScriptedRouter:
    def __init__(self, scripts: list[str]) -> None:
        self.scripts = list(scripts)
        self.requests: list[Any] = []

    def call(self, request: Any) -> _ScriptedResponse:
        self.requests.append(request)
        if not self.scripts:
            raise RuntimeError("scripted router exhausted")
        return _ScriptedResponse(text=self.scripts.pop(0))

    def call_stream(self, request: Any) -> Any:
        from runtime.sensing.model_router.models import CostEntry, ModelResponse, ModelStreamEvent

        response = self.call(request)
        if response.text:
            yield ModelStreamEvent(type="text_delta", delta=response.text)
        yield ModelStreamEvent(
            type="done",
            final=ModelResponse(
                text=response.text,
                model="code-mode-health-probe",
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                finish_reason=response.finish_reason,
                cost=CostEntry(),
            ),
        )


class _ProbePlanner:
    def __init__(self, router: Any) -> None:
        self.router = router
        self.planner_model = "code-mode-health-probe"


class _ProbeStack:
    def __init__(self, router: Any) -> None:
        self.planner = _ProbePlanner(router)


class _FakeOpenAIResponse:
    status_code = 200

    def __init__(self) -> None:
        self._payload = {
            "model": "probe-model",
            "choices": [
                {
                    "message": {"role": "assistant", "content": "ok"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 1,
                "completion_tokens": 1,
                "total_tokens": 2,
            },
        }
        self.text = json.dumps(self._payload)

    def json(self) -> dict[str, Any]:
        return self._payload


class _CapturingOpenAIClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def post(self, url: str, *, json: Any = None, headers: Any = None) -> _FakeOpenAIResponse:
        self.calls.append({"url": url, "json": json, "headers": headers})
        return _FakeOpenAIResponse()


def code_mode_runtime_check(
    *,
    name: str = "code_mode_runtime",
    timeout_seconds: float = 5.0,
    critical: bool = True,
) -> HealthCheck:
    """Return a readiness check for core code-mode invariants."""
    return HealthCheck(
        name=name,
        check=lambda: run_code_mode_runtime_probe(name=name),
        kind="readiness",
        timeout_seconds=timeout_seconds,
        critical=critical,
    )


def run_code_mode_runtime_probe(*, name: str = "code_mode_runtime") -> HealthStatus:
    checks = {
        "react_empty_assistant_history": _probe_react_empty_assistant_history(),
        "openai_compat_payload_hygiene": _probe_openai_compat_payload_hygiene(),
    }
    failures = {
        key: value
        for key, value in checks.items()
        if not bool(value.get("passed"))
    }
    if failures:
        return HealthStatus(
            name=name,
            status="fail",
            detail="; ".join(f"{key}: {value.get('detail', '')}" for key, value in failures.items()),
            metadata={"checks": checks},
        )
    return HealthStatus(name=name, status="pass", metadata={"checks": checks})


def _probe_react_empty_assistant_history() -> dict[str, Any]:
    from runtime.core.cerebrum.react_loop import run_react_loop
    from runtime.platform.models import ParsedIntent

    router = _CapturingScriptedRouter(["", "Final Answer: recovered"])
    intent = ParsedIntent(
        raw="code-mode health probe",
        intent_type="task",
        normalized_goal="code-mode health probe",
        user_context={"mode": "code"},
    )
    result = run_react_loop(_ProbeStack(router), intent, agent=None, max_iterations=3)
    if result is None or result.final_answer != "recovered":
        return {
            "passed": False,
            "detail": "react loop did not recover from an empty model turn",
            "request_count": len(router.requests),
        }
    if len(router.requests) < 2:
        return {
            "passed": False,
            "detail": "react loop did not issue a follow-up request",
            "request_count": len(router.requests),
        }
    second_messages = router.requests[1].messages
    empty_assistant_count = sum(
        1
        for message in second_messages
        if getattr(message, "role", "") == "assistant"
        and isinstance(getattr(message, "content", None), str)
        and not str(getattr(message, "content", "")).strip()
    )
    if empty_assistant_count:
        return {
            "passed": False,
            "detail": "empty assistant history reached the next model request",
            "empty_assistant_count": empty_assistant_count,
        }
    return {
        "passed": True,
        "request_count": len(router.requests),
        "step_count": len(result.steps),
    }


def _probe_openai_compat_payload_hygiene() -> dict[str, Any]:
    from runtime.sensing.model_router import Message, ModelRequest, OpenAIModelRouter

    client = _CapturingOpenAIClient()
    router = OpenAIModelRouter(base_url="http://probe.invalid/v1", client=client)
    router.call(
        ModelRequest(
            model="probe-model",
            messages=[
                Message(role="system", content=""),
                Message(role="user", content="start"),
                Message(role="assistant", content=""),
                Message(
                    role="assistant",
                    content=[
                        {
                            "type": "tool_use",
                            "id": "call_read",
                            "name": "read_file",
                            "input": {"path": "README.md"},
                        }
                    ],
                ),
                Message(
                    role="user",
                    content=[
                        {
                            "type": "tool_result",
                            "tool_use_id": "call_read",
                            "content": "ok",
                        }
                    ],
                ),
                Message(
                    role="user",
                    content=[
                        {
                            "type": "tool_result",
                            "tool_use_id": "missing_call",
                            "content": "orphan",
                        }
                    ],
                ),
            ],
            max_tokens=128,
            temperature=0.0,
        )
    )
    if not client.calls:
        return {"passed": False, "detail": "router did not issue a request"}
    messages = client.calls[0]["json"].get("messages") or []
    invalid_empty_assistant = [
        msg
        for msg in messages
        if msg.get("role") == "assistant"
        and not str(msg.get("content") or "").strip()
        and not msg.get("tool_calls")
    ]
    if invalid_empty_assistant:
        return {
            "passed": False,
            "detail": "payload contains empty assistant without tool_calls",
            "count": len(invalid_empty_assistant),
        }
    orphan_tool_messages = [
        msg
        for msg in messages
        if msg.get("role") == "tool" and msg.get("tool_call_id") == "missing_call"
    ]
    if orphan_tool_messages:
        return {
            "passed": False,
            "detail": "payload contains orphan tool result",
            "count": len(orphan_tool_messages),
        }
    return {
        "passed": True,
        "message_count": len(messages),
        "roles": [msg.get("role") for msg in messages],
    }


__all__ = ["code_mode_runtime_check", "run_code_mode_runtime_probe"]
