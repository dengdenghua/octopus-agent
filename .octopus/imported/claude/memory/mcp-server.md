---
name: mcp-server
description: octopus-mobile 内置 MCP server —— 把 ToolRegistry 暴露为标准 MCP 工具，供 Claude Desktop/Cursor 等驱动手机；端点/鉴权/接入方式
metadata: 
  node_type: memory
  type: project
  originSessionId: 4b7f74ae-59f7-4bf4-af69-e3bd239ec3fb
---

octopus-mobile 自带一个 **MCP（Model Context Protocol）server**，把本机 `ToolRegistry` 的全部工具暴露成标准 MCP 工具，任意 MCP 客户端（Claude Desktop / Cursor / OpenClaw）一行配置即可把这台手机当"数字员工"驱动。借鉴自竞品**侠客工坊**（xiake.cn，闭源企业级同类产品，它也是 MCP server `api.xiake.cn/mcp/KEY`）。2026-06-26 加入。

**实现**：`server/routes/McpRouteHandler.kt`（在 `ConfigServer.handlers` 注册）。JSON-RPC 2.0 over HTTP（MCP Streamable HTTP，单 `POST /mcp` 端点）。按客户端 `Accept` 头**双封装**：`application/json` 回即时 JSON；`text/event-stream` 把同一响应包成单个 SSE 事件返回（兼容要求 SSE 的客户端）。GET /mcp 回 405（不提供 server→client 推流）。实现方法：`initialize` / `notifications/initialized`(回 202) / `tools/list` / `tools/call` / `ping`。

**分层（为可测）**：协议分发在纯对象 `McpServerCore`（无 Android/HTTP 依赖，依赖 `McpToolProvider` 抽象）；handler 只做 HTTP 传输 + 把 ToolRegistry 适配成 provider。Schema 映射在纯对象 `McpSchema`。**离线握手已单测**：`McpServerCoreTest`(7 例，mock provider 完整跑 initialize/tools.list/tools.call(成功+失败+缺名)/ping/未知方法) + `McpSchemaTest`(4 例)。

**端点 & 接入**：
- URL：`http://<手机LAN-IP>:9527/mcp`（端口 9527，冲突时顺延 9527-9536；ConfigServer 绑定当前 WiFi IP）
- **前提**：WiFi 已连 + 设置里开启"局域网控制"（`KVUtils.isLanControlEnabled()`，见 TrustCenter 局域网开关）。`ConfigServerManager` 仅在此条件下启动。
- **鉴权**：复用 ConfigServer token（`Authorization: Bearer <token>` 或 `?token=<token>`）。token = `ConfigServer.authToken`，持久化在 KVUtils key `config_server_auth_token`（首次启动 lazy 生成，见 [[web-control-console]]）。`/mcp` 非公开 URI → 自动强制鉴权。
- MCP 客户端配置示例：`{ "url": "http://192.168.x.x:9527/mcp?token=<token>" }`

**安全**：`tools/call` 一律包在 `ToolRegistry.withUntrustedSource{}` 内 —— 外部 MCP 客户端视为"不可信来源"，高危工具走来源闸门/审批流程（与 [[security-audit-2026-06]] 的高危来源闸门一致；远程放行需开 `isRemoteHighRiskAllowed`，UI 在 ChannelAclActivity）。

**待验证（真机）**：协议层（握手/schema/SSE 分支）已离线单测覆盖；**仍未用真 MCP 客户端 + 真机网络端到端连过一次**——需 Claude Desktop/Cursor 真连，验证 ConfigServer 在设备上起、token、tools.call 真实执行手机工具。SSE 已支持（早先"只回 JSON"的兼容缺口已补）。

**"claw" 线索**：侠客工坊明确把 **OpenClaw** 列为兼容 MCP 客户端，而本项目命名空间是 `com.apk.claw.android`（claw）。两者是否同源/可互通值得查证。

Related: [[web-control-console]]（ConfigServer :9527 / token 来源）、[[security-audit-2026-06]]（来源闸门）、[[tentacle-mother-control]]。
