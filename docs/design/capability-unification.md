# 插件统一(连接器 = 插件)

> **结论**:WorkBuddy 连接器(108)与 Codex 插件本质是同一类东西 —— **插件**:
> 元数据 + skills + 工具(MCP/CLI) + 认证编排。现已归一为**一套模型、一个市场、
> 一条生命周期**,统一对外只叫「插件」,不再叫「连接器」。

## 为什么是同一类

| 维度 | WorkBuddy 连接器 | Codex 插件 |
|---|---|---|
| 元数据 | `.codebuddy-connector/connectors.json` | `.codex-plugin/plugin.json` |
| 技能 | `connectors/<id>/skills/**/SKILL.md` | `skills/**/SKILL.md` |
| 工具 | `mcp.json`(MCP 服务器)/ `cli.json` | MCP / node_repl / command |
| 认证 | token / oauth / server-side / oneid | 一般无需(或插件自带) |
| 本质 | 给 agent 加外部能力 | 给 agent 加外部能力 |

## 统一模型

`runtime/platform/capabilities/capability_registry.py` —— `CapabilityRegistry`

```
CapabilityItem {
  id, name, name_zh, description, description_zh,
  source: "connector" | "codex_plugin",
  type: "mcp" | "cli" | "skill-only" | "plugin",
  auth_mode: token | oauth | server-side | oneid-token | none,
  mcp_servers[], skill_count, author, version,
  installed, enabled, connected
}
```

- 连接器 → `ConnectorRegistry`(WorkBuddy fork)委托
- 插件 → 扫描 `~/.codex/plugins/cache/**/.codex-plugin/plugin.json`
- 统一生命周期:`install → 复制 skills 到 ~/.octopus/skills`(连接器额外登记 MCP),
  `enable/disable`,`connect → 认证编排`(连接器走 AuthOrchestrator;插件无需认证直接就绪)

## 统一市场

后端 `runtime/sensing/gateway/capability_router.py`:

```
GET    /api/capabilities                   统一列表(连接器 + 插件,支持 source/type/search 过滤)
GET    /api/capabilities/{id}
POST   /api/capabilities/{id}/install
DELETE /api/capabilities/{id}/install
POST   /api/capabilities/{id}/enable|disable
GET    /api/capabilities/{id}/status
POST   /api/capabilities/{id}/connect|disconnect
GET    /api/capabilities/{id}/headers
```

前端 Hub「连接器/插件」tab = `frontend/src/components/store/capability-market-panel.tsx`,
一个市场同时展示 108 连接器 + 15 插件(来源徽标 + 类型 + 认证 + 技能/MCP 计数 +
安装/启用/连接/断开/卸载),统一操作。

## 兼容

- 旧的 `/api/connectors/*` 路由与 `ConnectorMarketPanel` 保留,向后兼容。
- 插件安装后其 skill 进 `~/.octopus/skills`,与连接器 skill 同池,octopus agent 可直接使用。
