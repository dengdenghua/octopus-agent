---
type: "BackendIndex"
title: "后端架构 · Backend"
description: "Python runtime · 分 6 个子系统 · 左侧树展开看每个子系统详情。"
tags: ["backend"]
tier: "standard"
---
# 后端架构 · Backend

> Python runtime · 分 6 个子系统 · 左侧树展开看每个子系统详情。

| 子系统 | 目录 | 职责 |
| --- | --- | --- |
| Runtime 核心 | `runtime/execution/`, `runtime/core/` | 执行器 · 规划 · 技能注册 · 心跳 |
| Safety | `runtime/safety/` | 宪法 · 免疫 · 生命周期 hooks |
| Memory | `runtime/memory/` | Journal (genome) · Context (hemolymph) |
| Sensing | `runtime/sensing/` | Eyes (model router) · Siphon (HTTP API) |
| Adapters | `runtime/adapters/` | MCP · Channels · 第三方集成 |
| Agents | `agents/` | 预置 agent 的 profile / memory / workspace |

## 依赖关系（自动计算）

每个子系统被**多少**子系统引用 · 静态 AST 扫描 ``from runtime.X ...`` 语句得出。
前端 Wiki 面板会把下面的 ```mermaid``` 渲染成真图。

```mermaid
graph LR
  execution[execution]
  core[core]
  safety[safety]
  memory[memory]
  sensing[sensing]
  adapters[adapters]
  platform[platform]
  sensing -- 129 --> platform
  safety -- 86 --> platform
  sensing -- 83 --> safety
  execution -- 80 --> platform
  sensing -- 76 --> memory
  sensing -- 68 --> execution
  core -- 55 --> platform
  memory -- 54 --> platform
  execution -- 45 --> safety
  sensing -- 39 --> protocol
  sensing -- 32 --> adapters
  sensing -- 30 --> core
  platform -- 29 --> safety
  execution -- 26 --> memory
  core -- 21 --> safety
  safety -- 21 --> memory
  core -- 20 --> execution
  platform -- 19 --> execution
  platform -- 19 --> sensing
  execution -- 16 --> core
  memory -- 16 --> safety
  platform -- 15 --> memory
  core -- 14 --> memory
  platform -- 14 --> core
  safety -- 14 --> adapters
  adapters -- 10 --> safety
  execution -- 9 --> adapters
  platform -- 9 --> adapters
  adapters -- 8 --> platform
  safety -- 8 --> execution
  safety -- 7 --> core
  sensing -- 7 --> projectos
  memory -- 6 --> protocol
  _cli_commands.py -- 5 --> memory
  _cli_commands.py -- 5 --> platform
  cli_serve.py -- 5 --> safety
  core -- 5 --> adapters
  memory -- 5 --> execution
  adapters -- 4 --> sensing
  cli_core.py -- 4 --> execution
  cli_run.py -- 4 --> execution
  cli_serve.py -- 4 --> adapters
  platform -- 4 --> tentacle
  research -- 4 --> platform
  cli_core.py -- 3 --> core
  cli_reflect.py -- 3 --> platform
  cli_run.py -- 3 --> platform
  cli_serve.py -- 3 --> platform
  execution -- 3 --> sensing
  memory -- 3 --> core
  platform -- 3 --> cli
  sensing -- 3 --> workspace
  tour.py -- 3 --> core
  tour.py -- 3 --> safety
  workspace -- 3 --> platform
```

