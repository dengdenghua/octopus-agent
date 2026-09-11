"""Tool contracts are available without constructing the executor import graph."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .executor import StepExecutionError, ToolExecutor
from .tool_protocol import (
    NormalizedToolCall,
    NormalizedToolLifecycleEvent,
    NormalizedToolResult,
    ToolCallOrigin,
    ToolLifecycleKind,
    normalize_step_tool_result,
    normalize_task_node_tool_call,
    normalize_tool_call,
    normalize_tool_lifecycle_event,
    normalize_tool_result,
    output_signals_error,
    render_tool_output,
    tool_lifecycle_event_to_react_event,
    tool_lifecycle_event_to_trace_payload,
)
from .tool_taxonomy import (
    ToolKind,
    ToolTaxonomy,
    classify_skill,
    register_taxonomy,
    reset_overrides,
    taxonomy_to_audit_dict,
)

__all__ = [
    "NormalizedToolCall",
    "NormalizedToolLifecycleEvent",
    "NormalizedToolResult",
    "StepExecutionError",
    "ToolCallOrigin",
    "ToolKind",
    "ToolLifecycleKind",
    "ToolTaxonomy",
    "ToolExecutor",
    "classify_skill",
    "normalize_tool_lifecycle_event",
    "normalize_step_tool_result",
    "normalize_tool_result",
    "normalize_task_node_tool_call",
    "normalize_tool_call",
    "output_signals_error",
    "register_taxonomy",
    "render_tool_output",
    "reset_overrides",
    "taxonomy_to_audit_dict",
    "tool_lifecycle_event_to_react_event",
    "tool_lifecycle_event_to_trace_payload",
]


def __getattr__(name: str) -> Any:
    if name in {"StepExecutionError", "ToolExecutor"}:
        from importlib import import_module

        value = getattr(import_module(".executor", __name__), name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
