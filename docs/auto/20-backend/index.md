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
  sensing -- 125 --> platform
  safety -- 83 --> platform
  execution -- 76 --> platform
  sensing -- 74 --> memory
  sensing -- 66 --> execution
  sensing -- 56 --> safety
  core -- 54 --> platform
  memory -- 52 --> platform
  execution -- 44 --> safety
  sensing -- 38 --> protocol
  sensing -- 36 --> adapters
  sensing -- 26 --> core
  platform -- 25 --> safety
  execution -- 23 --> memory
  core -- 21 --> safety
  safety -- 21 --> memory
  platform -- 19 --> sensing
  core -- 18 --> execution
  platform -- 18 --> execution
  execution -- 16 --> core
  platform -- 14 --> memory
  safety -- 14 --> adapters
  platform -- 13 --> core
  core -- 11 --> memory
  platform -- 10 --> adapters
  execution -- 8 --> adapters
  safety -- 8 --> execution
  memory -- 7 --> safety
  safety -- 7 --> core
  sensing -- 7 --> projectos
  adapters -- 6 --> platform
  adapters -- 6 --> safety
  memory -- 6 --> protocol
  _cli_commands.py -- 5 --> memory
  _cli_commands.py -- 5 --> platform
  core -- 5 --> adapters
  memory -- 5 --> execution
  adapters -- 4 --> sensing
  cli_core.py -- 4 --> execution
  cli_run.py -- 4 --> execution
  cli_serve.py -- 4 --> adapters
  cli_serve.py -- 4 --> safety
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

