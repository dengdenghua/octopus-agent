---
type: "AdapterSubsystem"
title: "Adapters · MCP"
description: "MCP 客户端 + Trust store · ADR-007 治理 · 未审批 server 的工具拒注册。"
tags: ["backend", "adapters"]
tier: "standard"
---
# Adapters · MCP

> MCP 客户端 + Trust store · ADR-007 治理 · 未审批 server 的工具拒注册。

**Source**: `runtime/adapters/mcp_client/`

## Exports

- `HTTP_AVAILABLE`
- `HttpMCPClient`
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
| `oauth.py` | MCP OAuth 2.0 (PKCE) client — authorize-on-enable for remote MCP servers. |
| `oauth_discovery.py` | OAuth metadata discovery + dynamic client registration for MCP (step 2). |
| `persistent_client.py` | — |
| `trust.py` | — |
| `types.py` | — |

## Key classes & functions

> AST 自动提取 · 仅列公开顶层 class / function · 签名与真实代码一致。

### `bridge.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def register_mcp_tools_as_skills(registry, client, name_prefix, include_golden_tests, require_trust, server_name)` |  |

### `client.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class MCPTool(BaseModel)` |  |
| class | `class MCPInvocationResult(BaseModel)` |  |
| class | `class MCPClientError(RuntimeError)` |  |
| class | `class MCPClient(ABC)` |  |
| class | `class MockMCPClient(MCPClient)` |  |
| class | `class StdioMCPClient(MCPClient)` |  |
| class | `class HttpMCPClient(MCPClient)` | MCP client over a remote HTTP transport (streamable-http or SSE). |

### `oauth.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def new_pkce()` | Return ``(code_verifier, code_challenge)`` for PKCE S256. |
| func | `def build_authorize_url(authorize_url, client_id, redirect_uri, scopes, state, code_challenge)` |  |
| func | `def exchange_code(token_url, code, code_verifier, client_id, redirect_uri)` |  |
| func | `def refresh_access(token_url, refresh_token, client_id)` |  |
| class | `class MCPOAuthStore` | Thread-safe, JSON-backed per-server OAuth token + pending-flow store. |
| func | `def get_oauth_store()` |  |
| func | `def bearer_for_server(name)` | Valid access token for ``name`` (refreshing if needed), or ``None``. |
| func | `def reset_oauth_store_for_tests()` |  |

### `oauth_discovery.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class OAuthEndpoints` |  |
| func | `def discover(server_url, timeout)` |  |
| func | `def register_client(registration_url, redirect_uri, client_name, timeout)` | Dynamic client registration (RFC 7591) for a public PKCE client. |

### `persistent_client.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def close_all_persistent_clients()` |  |
| class | `class PersistentStdioMCPClient(MCPClient)` |  |

### `trust.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class TrustEntry` |  |
| class | `class MCPTrustStore` | Thread-safe JSON-backed approval registry. |
| func | `def get_trust_store()` | Lazy singleton · first call reads (or creates) the JSON. |
| func | `def reset_trust_store_for_tests()` | Drop the singleton · tests use this to isolate from user's real ~/.octopus directory (pair with monkeypatching $OCTOPUS_HOME). |

### `types.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class MCPServerConfig(BaseModel)` |  |


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

