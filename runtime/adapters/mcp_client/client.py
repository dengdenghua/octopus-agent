from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from runtime.adapters.instrumentation import trace_stage

from .types import MCPServerConfig

try:
    import mcp  # type: ignore[import-untyped]

    STDIO_AVAILABLE = True
except ImportError:  # pragma: no cover
    STDIO_AVAILABLE = False
    mcp = None  # type: ignore[assignment]

# The same ``mcp`` SDK provides the remote (streamable-http / SSE) clients,
# so HTTP availability tracks stdio availability.
HTTP_AVAILABLE = STDIO_AVAILABLE


# ═══════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════


class MCPTool(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str = Field(..., min_length=1)
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)  # JSON Schema
    server_name: str = ""


class MCPInvocationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    tool_name: str
    success: bool
    output: Any = None
    error: str | None = None
    latency_ms: float = 0.0
    raw_content: list[Any] = Field(default_factory=list)  # Implementation note.


class MCPClientError(RuntimeError):
    pass


# ═══════════════════════════════════════════════════════════
# ABC
# ═══════════════════════════════════════════════════════════


class MCPClient(ABC):
    @abstractmethod
    def list_tools(self) -> list[MCPTool]: ...

    @abstractmethod
    def call_tool(self, name: str, args: dict[str, Any]) -> MCPInvocationResult: ...

    @abstractmethod
    def close(self) -> None: ...

    def __enter__(self) -> MCPClient:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()


# ═══════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════


class MockMCPClient(MCPClient):
    def __init__(
        self,
        *,
        server_name: str = "mock-server",
        tools: list[MCPTool] | None = None,
        tool_handlers: dict[str, Any] | None = None,
    ) -> None:
        self.server_name = server_name
        self._tools = list(tools or [])
        self._handlers: dict[str, Any] = dict(tool_handlers or {})
        self._closed = False
        self.call_log: list[tuple[str, dict]] = []

    def list_tools(self) -> list[MCPTool]:
        self._check_open()
        return [t.model_copy(update={"server_name": self.server_name}) for t in self._tools]

    def call_tool(self, name: str, args: dict[str, Any]) -> MCPInvocationResult:
        self._check_open()
        t0 = time.monotonic()
        self.call_log.append((name, dict(args)))
        with trace_stage("mcp.call_tool") as span:
            span.set_attribute("octopus.mcp.server", self.server_name)
            span.set_attribute("octopus.mcp.tool", name)

            handler = self._handlers.get(name)
            if handler is None:
                return MCPInvocationResult(
                    tool_name=name,
                    success=False,
                    error=f"unknown_tool: {name!r}",
                    latency_ms=(time.monotonic() - t0) * 1000,
                )
            try:
                output = handler(args) if callable(handler) else handler
                return MCPInvocationResult(
                    tool_name=name,
                    success=True,
                    output=output,
                    latency_ms=(time.monotonic() - t0) * 1000,
                    raw_content=[{"type": "text", "text": str(output)[:400]}],
                )
            except Exception as e:  # noqa: BLE001
                return MCPInvocationResult(
                    tool_name=name,
                    success=False,
                    error=f"{type(e).__name__}: {e}",
                    latency_ms=(time.monotonic() - t0) * 1000,
                )

    def close(self) -> None:
        self._closed = True

    def _check_open(self) -> None:
        if self._closed:
            raise MCPClientError("client closed")


# ═══════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════


class StdioMCPClient(MCPClient):
    def __init__(self, config: MCPServerConfig) -> None:
        if not STDIO_AVAILABLE:
            raise MCPClientError("mcp SDK not installed · `pip install mcp` or use MockMCPClient")
        self.config = config
        self._closed = False
        self._tools_cache: list[MCPTool] | None = None

    def list_tools(self) -> list[MCPTool]:
        if self._closed:
            raise MCPClientError("client closed")
        if self._tools_cache is None:
            self._tools_cache = asyncio.run(self._list_tools_async())
        return list(self._tools_cache)

    def call_tool(self, name: str, args: dict[str, Any]) -> MCPInvocationResult:
        if self._closed:
            raise MCPClientError("client closed")
        t0 = time.monotonic()
        with trace_stage("mcp.stdio.call_tool") as span:
            span.set_attribute("octopus.mcp.server", self.config.name)
            span.set_attribute("octopus.mcp.tool", name)
            try:
                result = asyncio.run(self._call_tool_async(name, args))
            except Exception as e:  # noqa: BLE001
                return MCPInvocationResult(
                    tool_name=name,
                    success=False,
                    error=f"{type(e).__name__}: {e}",
                    latency_ms=(time.monotonic() - t0) * 1000,
                )
            return result.model_copy(update={"latency_ms": (time.monotonic() - t0) * 1000})

    def close(self) -> None:
        self._closed = True

    # ─── async implementations ─────────────────────

    async def _list_tools_async(self) -> list[MCPTool]:
        from mcp import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client

        params = StdioServerParameters(
            command=self.config.command,
            args=list(self.config.args),
            env=dict(self.config.env) if self.config.env else None,
        )
        async with (
            stdio_client(params) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            result = await session.list_tools()
            return [
                MCPTool(
                    name=t.name,
                    description=(t.description or ""),
                    input_schema=(t.inputSchema or {}),
                    server_name=self.config.name,
                )
                for t in result.tools
            ]

    async def _call_tool_async(self, name: str, args: dict[str, Any]) -> MCPInvocationResult:
        from mcp import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client

        params = StdioServerParameters(
            command=self.config.command,
            args=list(self.config.args),
            env=dict(self.config.env) if self.config.env else None,
        )
        async with (
            stdio_client(params) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            result = await session.call_tool(name, args)
            text = "\n".join(
                getattr(b, "text", "")
                for b in result.content
                if hasattr(b, "text") and getattr(b, "text", None)
            )
            raw = [b.model_dump() if hasattr(b, "model_dump") else str(b) for b in result.content]
            is_err = bool(getattr(result, "isError", False))
            return MCPInvocationResult(
                tool_name=name,
                success=not is_err,
                output=text if text else None,
                error=text if is_err else None,
                raw_content=raw,
            )


# ═══════════════════════════════════════════════════════════
# Remote (streamable-http / SSE) transport
# ═══════════════════════════════════════════════════════════


class HttpMCPClient(MCPClient):
    """MCP client over a remote HTTP transport (streamable-http or SSE).

    Mirrors ``StdioMCPClient`` but connects to a ``url`` instead of spawning
    a subprocess — this is how most of the hosted MCP ecosystem (GitHub,
    Slack, Linear, Notion, ...) is reached. The transport is picked from
    ``config.transport``: ``"http"`` (default) → streamable-http,
    ``"sse"`` → the legacy SSE transport.
    """

    def __init__(self, config: MCPServerConfig) -> None:
        if not HTTP_AVAILABLE:
            raise MCPClientError("mcp SDK not installed · `pip install mcp` or use MockMCPClient")
        if not config.url:
            raise MCPClientError("HttpMCPClient requires config.url")
        self.config = config
        self._closed = False
        self._tools_cache: list[MCPTool] | None = None

    def list_tools(self) -> list[MCPTool]:
        if self._closed:
            raise MCPClientError("client closed")
        if self._tools_cache is None:
            self._tools_cache = asyncio.run(self._list_tools_async())
        return list(self._tools_cache)

    def call_tool(self, name: str, args: dict[str, Any]) -> MCPInvocationResult:
        if self._closed:
            raise MCPClientError("client closed")
        t0 = time.monotonic()
        with trace_stage("mcp.http.call_tool") as span:
            span.set_attribute("octopus.mcp.server", self.config.name)
            span.set_attribute("octopus.mcp.tool", name)
            try:
                result = asyncio.run(self._call_tool_async(name, args))
            except Exception as e:  # noqa: BLE001
                return MCPInvocationResult(
                    tool_name=name,
                    success=False,
                    error=f"{type(e).__name__}: {e}",
                    latency_ms=(time.monotonic() - t0) * 1000,
                )
            return result.model_copy(update={"latency_ms": (time.monotonic() - t0) * 1000})

    def close(self) -> None:
        self._closed = True

    # ─── async implementations ─────────────────────

    def _transport(self) -> Any:
        """Return the transport async-context-manager for this config.

        ``streamable-http`` yields a 3-tuple ``(read, write, get_id)`` and
        ``sse`` a 2-tuple ``(read, write)``; callers index ``[0]``/``[1]``
        so both shapes work uniformly.
        """
        headers = dict(self.config.headers) if self.config.headers else {}
        # OAuth-authorized servers (see mcp_router.py's /api/mcp/oauth/*
        # endpoints) get their bearer token injected here rather than
        # baked into ``config.headers`` — tokens refresh/expire and are
        # looked up fresh on every connect. An explicit Authorization
        # header the user pasted into the server config always wins
        # (manual token beats auto-OAuth).
        if "Authorization" not in headers and "authorization" not in headers:
            from .oauth import bearer_for_server

            token = bearer_for_server(self.config.name)
            if token:
                headers["Authorization"] = f"Bearer {token}"
        headers = headers or None
        timeout = max(1.0, self.config.timeout_ms / 1000.0)
        if self.config.transport == "sse":
            from mcp.client.sse import sse_client

            return sse_client(self.config.url, headers=headers, timeout=timeout)
        from mcp.client.streamable_http import streamablehttp_client

        return streamablehttp_client(self.config.url, headers=headers, timeout=timeout)

    async def _list_tools_async(self) -> list[MCPTool]:
        from mcp import ClientSession

        async with self._transport() as conn:
            read, write = conn[0], conn[1]
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.list_tools()
                return [
                    MCPTool(
                        name=t.name,
                        description=(t.description or ""),
                        input_schema=(t.inputSchema or {}),
                        server_name=self.config.name,
                    )
                    for t in result.tools
                ]

    async def _call_tool_async(self, name: str, args: dict[str, Any]) -> MCPInvocationResult:
        from mcp import ClientSession

        async with self._transport() as conn:
            read, write = conn[0], conn[1]
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(name, args)
                text = "\n".join(
                    getattr(b, "text", "")
                    for b in result.content
                    if hasattr(b, "text") and getattr(b, "text", None)
                )
                raw = [
                    b.model_dump() if hasattr(b, "model_dump") else str(b) for b in result.content
                ]
                is_err = bool(getattr(result, "isError", False))
                return MCPInvocationResult(
                    tool_name=name,
                    success=not is_err,
                    output=text if text else None,
                    error=text if is_err else None,
                    raw_content=raw,
                )
