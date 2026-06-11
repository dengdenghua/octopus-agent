# Adapters · MCP

> MCP 客户端 + Trust store · ADR-007 治理 · 未审批 server 的工具拒注册。

**Source**: `runtime/adapters/mcp_client/`

## Exports

- `MCPClient`
- `MCPClientError`
- `MCPInvocationResult`
- `MCPServerConfig`
- `MCPTool`
- `MCPTrustStore`
- `MockMCPClient`
- `PersistentStdioMCPClient`
- `STDIO_AVAILABLE`
- `StdioMCPClient`
- `TrustEntry`
- `close_all_persistent_clients`
- `get_trust_store`
- `register_mcp_tools_as_skills`
- `reset_trust_store_for_tests`

## Modules

| Module | Summary |
| --- | --- |
| `bridge.py` | — |
| `client.py` | — |
| `persistent_client.py` | — |
| `trust.py` | — |
| `types.py` | — |

## Who imports this

**5** file(s) reference this package:

- **`runtime/cli_mcp.py/`** · 1 file(s)
  - `runtime/cli_mcp.py`
- **`runtime/cli_serve.py/`** · 1 file(s)
  - `runtime/cli_serve.py`
- **`runtime/platform/`** · 2 file(s)
  - `runtime/platform/config/builder.py`
  - `runtime/platform/ui/health_router.py`
- **`runtime/sensing/`** · 1 file(s)
  - `runtime/sensing/gateway/mcp_router.py`

