"""MCP-style tool registry — declarative tool registration pattern.

Tools are registered with a name, description, input schema, and
handler function. The registry handles validation, dispatch, and
lifecycle so individual tools can stay focused on their domain.

Key features
~~~~~~~~~~~~
- **Declarative schema**: Tools define their input schema as a dict.
- **Typed handlers**: Handlers receive typed input and return results.
- **Event hooks**: on_will_call_tool / on_did_call_tool for observability.
- **Provider abstraction**: Tools are grouped into providers.

Usage
~~~~~
    registry = ToolRegistry()

    # Register a tool
    registry.register_tool(
        name="execute_shell",
        description="Execute a shell command",
        input_schema={
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "timeout": {"type": "number"},
            },
            "required": ["command"],
        },
        handler=execute_shell_handler,
    )

    # Call a tool
    result = await registry.call_tool("execute_shell", {
        "command": "ls -la",
    })
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from runtime.adapters.instrumentation import trace_stage

_logger = logging.getLogger(__name__)


@dataclass
class ToolDefinition:
    """Declarative definition of a tool."""

    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[[dict[str, Any]], Awaitable[Any]]


@dataclass
class ToolCallContext:
    """Context passed to tool call event handlers."""

    tool_name: str
    input: dict[str, Any]
    session_id: str | None = None
    chat_session_id: str | None = None


@dataclass
class ToolCallResult:
    """Result of a tool call."""

    tool_name: str
    success: bool
    output: Any
    error: str | None = None
    elapsed_ms: float = 0.0


@dataclass
class ToolProvider:
    """A group of tools registered under a single provider."""

    id: str
    display_name: str
    tools: list[ToolDefinition] = field(default_factory=list)
    feature_flags: list[str] = field(default_factory=list)
    is_ready: bool = False


# Event handler types
WillCallToolHandler = Callable[[ToolCallContext], Awaitable[None]]
DidCallToolHandler = Callable[[ToolCallResult], Awaitable[None]]


class ToolRegistry:
    """Registry for MCP-style tools.

    Manages tool registration, validation, and execution with
    event hooks for observability and pre/post processing.
    """

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}
        self._providers: dict[str, ToolProvider] = {}
        self._on_will_call: list[WillCallToolHandler] = []
        self._on_did_call: list[DidCallToolHandler] = []
        self._call_count = 0

    @property
    def tool_names(self) -> list[str]:
        """List of all registered tool names."""
        return list(self._tools.keys())

    @property
    def providers(self) -> dict[str, ToolProvider]:
        """All registered providers."""
        return dict(self._providers)

    def register_provider(
        self,
        provider_id: str,
        display_name: str,
        *,
        feature_flags: list[str] | None = None,
    ) -> ToolProvider:
        """Register a tool provider.

        Args:
            provider_id: Unique provider identifier.
            display_name: Human-readable name.
            feature_flags: Optional feature flags for this provider.

        Returns:
            The created ToolProvider.
        """
        provider = ToolProvider(
            id=provider_id,
            display_name=display_name,
            feature_flags=feature_flags or [],
        )
        self._providers[provider_id] = provider
        return provider

    def register_tool(
        self,
        name: str,
        description: str,
        input_schema: dict[str, Any],
        handler: Callable[[dict[str, Any]], Awaitable[Any]],
        *,
        provider_id: str | None = None,
    ) -> None:
        """Register a tool.

        Args:
            name: Unique tool name.
            description: Human-readable description.
            input_schema: JSON Schema for tool input.
            handler: Async function that executes the tool.
            provider_id: Optional provider to associate with.
        """
        if name in self._tools:
            raise ValueError(f"Tool '{name}' is already registered")

        tool = ToolDefinition(
            name=name,
            description=description,
            input_schema=input_schema,
            handler=handler,
        )
        self._tools[name] = tool

        if provider_id and provider_id in self._providers:
            self._providers[provider_id].tools.append(tool)

        _logger.info("registered tool: %s", name)

    def on_will_call_tool(self, handler: WillCallToolHandler) -> None:
        """Register a pre-call event handler."""
        self._on_will_call.append(handler)

    def on_did_call_tool(self, handler: DidCallToolHandler) -> None:
        """Register a post-call event handler."""
        self._on_did_call.append(handler)

    async def call_tool(
        self,
        tool_name: str,
        input: dict[str, Any],
        *,
        context: ToolCallContext | None = None,
    ) -> ToolCallResult:
        """Call a registered tool by name.

        Args:
            tool_name: The tool to call.
            input: Input parameters for the tool.
            context: Optional call context for event handlers.

        Returns:
            ToolCallResult with output and timing info.
        """
        if tool_name not in self._tools:
            return ToolCallResult(
                tool_name=tool_name,
                success=False,
                output=None,
                error=f"Tool '{tool_name}' is not registered",
            )

        self._call_count += 1

        # Build call context
        if context is None:
            context = ToolCallContext(
                tool_name=tool_name,
                input=input,
            )

        # Fire pre-call events
        for handler in self._on_will_call:
            try:
                await handler(context)
            except Exception as e:
                return ToolCallResult(
                    tool_name=tool_name,
                    success=False,
                    output=None,
                    error=f"Pre-call hook failed: {e}",
                )

        # Execute the tool
        start_time = time.perf_counter()
        try:
            tool = self._tools[tool_name]
            with trace_stage(
                "tool.call",
                tool_name=tool_name,
            ) as span:
                span.set_attribute("octopus.tool.input_keys", list(input.keys()))
                output = await tool.handler(input)
                elapsed_ms = (time.perf_counter() - start_time) * 1000
                span.set_attribute("octopus.tool.elapsed_ms", elapsed_ms)

            result = ToolCallResult(
                tool_name=tool_name,
                success=True,
                output=output,
                elapsed_ms=elapsed_ms,
            )
        except Exception as e:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            _logger.exception("tool call failed: %s", tool_name)
            result = ToolCallResult(
                tool_name=tool_name,
                success=False,
                output=None,
                error=str(e),
                elapsed_ms=elapsed_ms,
            )

        # Fire post-call events
        for handler in self._on_did_call:
            try:
                await handler(result)
            except (TypeError, ValueError, RuntimeError):
                _logger.warning("Post-call hook failed for tool: %s", tool_name)

        return result

    def get_tool_schema(self, tool_name: str) -> dict[str, Any] | None:
        """Get the input schema for a tool."""
        tool = self._tools.get(tool_name)
        if not tool:
            return None
        return {
            "name": tool.name,
            "description": tool.description,
            "inputSchema": tool.input_schema,
        }

    def get_all_tool_schemas(self) -> list[dict[str, Any]]:
        """Get schemas for all registered tools."""
        return [
            self.get_tool_schema(name)
            for name in self.tool_names
            if self.get_tool_schema(name) is not None
        ]

    def mark_provider_ready(self, provider_id: str) -> None:
        """Mark a provider as ready for tool calls."""
        if provider_id in self._providers:
            self._providers[provider_id].is_ready = True

    @property
    def call_count(self) -> int:
        """Total number of tool calls made."""
        return self._call_count


# Global registry instance
_global_registry: ToolRegistry | None = None


def get_tool_registry() -> ToolRegistry:
    """Get or create the global tool registry."""
    global _global_registry
    if _global_registry is None:
        _global_registry = ToolRegistry()
    return _global_registry
