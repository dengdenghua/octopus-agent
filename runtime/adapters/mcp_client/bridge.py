from __future__ import annotations

import re
from typing import Any

from runtime.execution.suckers import Skill, SkillExpect, SkillRegistry, SkillTestCase

from .client import MCPClient


def register_mcp_tools_as_skills(
    registry: SkillRegistry,
    client: MCPClient,
    *,
    name_prefix: str | None = None,
    include_golden_tests: bool = True,
    require_trust: bool = True,
    server_name: str | None = None,
) -> list[str]:
    registered: list[str] = []
    tools = client.list_tools()
    inferred_name = server_name
    if inferred_name is None and tools:
        inferred_name = getattr(tools[0], "server_name", None)
    effective_prefix = (
        name_prefix
        if name_prefix is not None
        else f"mcp_{_safe_name(str(inferred_name or 'server'))}_"
    )

    # Trust gate · supply-chain protection. An unknown MCP server
    # is untrusted until the user explicitly approves it via the
    # ``/api/mcp/trust`` endpoint (or programmatically via
    # ``get_trust_store().approve(...)``). This mirrors the
    if require_trust:
        if not inferred_name:
            import logging

            logging.getLogger("runtime.adapters.mcp_client.bridge").warning(
                "MCP server name missing; refusing to register %d tool(s)",
                len(tools),
            )
            return []
        if inferred_name:
            from .trust import get_trust_store

            store = get_trust_store()
            tool_names = [t.name for t in tools]
            if not store.is_approved(inferred_name, tool_names):
                import logging

                logging.getLogger(
                    "runtime.adapters.mcp_client.bridge",
                ).warning(
                    "MCP server %r not approved in trust store · "
                    "refusing to register its %d tool(s). Approve via "
                    "get_trust_store().approve(%r, tool_names).",
                    inferred_name,
                    len(tool_names),
                    inferred_name,
                )
                return []
    for tool in tools:
        skill_name = f"{effective_prefix}{tool.name}"
        handler = _make_handler_for(client, tool.name)

        tests = []
        if include_golden_tests:
            tests.append(
                SkillTestCase(
                    name="returns_or_errors_cleanly",
                    tier="golden",
                    args={},
                    expect=SkillExpect(no_exception=True),
                )
            )

        skill = Skill(
            name=skill_name,
            description=tool.description or f"MCP tool from {tool.server_name}",
            affinity=["mcp", "external"],
            cost_profile="mid",
            trusted_source=f"mcp://{tool.server_name}/{tool.name}",
            handler=handler,
            tests=tests,
        )
        try:
            registry.register(skill)
            registered.append(skill_name)
        except Exception:  # noqa: BLE001 - skill test failed, skip but don't crash
            continue
    return registered


def _safe_name(name: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z_]+", "_", name.strip())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned or "server"


def _make_handler_for(client: MCPClient, tool_name: str) -> Any:

    def handler(**kwargs: Any) -> Any:
        filtered = {k: v for k, v in kwargs.items() if not k.startswith("_") and k != "intent_goal"}
        result = client.call_tool(tool_name, filtered)
        if not result.success:
            return {"error": result.error or "mcp_call_failed", "tool": tool_name}
        return {
            "output": result.output,
            "tool": tool_name,
            "latency_ms": result.latency_ms,
        }

    handler.__name__ = f"mcp_{tool_name}_handler"
    return handler
