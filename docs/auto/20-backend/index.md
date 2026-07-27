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
  sensing -- 95 --> platform
  safety -- 81 --> platform
  execution -- 58 --> platform
  sensing -- 54 --> memory
  sensing -- 50 --> execution
  memory -- 49 --> platform
  sensing -- 45 --> safety
  execution -- 40 --> safety
  sensing -- 35 --> adapters
  core -- 32 --> platform
  safety -- 21 --> memory
  execution -- 20 --> memory
  sensing -- 18 --> core
  sensing -- 18 --> protocol
  execution -- 16 --> core
  platform -- 16 --> execution
  core -- 15 --> execution
  core -- 14 --> safety
  platform -- 14 --> safety
  safety -- 14 --> adapters
  platform -- 12 --> sensing
  platform -- 11 --> memory
  core -- 10 --> memory
  platform -- 10 --> adapters
  platform -- 10 --> core
  safety -- 8 --> execution
  execution -- 7 --> adapters
  memory -- 7 --> safety
  safety -- 7 --> core
  sensing -- 7 --> projectos
  adapters -- 6 --> platform
  adapters -- 6 --> safety
  cli.py -- 5 --> memory
  cli.py -- 5 --> platform
  core -- 5 --> adapters
  memory -- 5 --> execution
  adapters -- 4 --> sensing
  cli_core.py -- 4 --> execution
  cli_run.py -- 4 --> execution
  cli_serve.py -- 4 --> adapters
  cli_serve.py -- 4 --> safety
  execution -- 4 --> sensing
  memory -- 4 --> protocol
  platform -- 4 --> tentacle
  research -- 4 --> platform
  cli_core.py -- 3 --> core
  cli_reflect.py -- 3 --> platform
  cli_run.py -- 3 --> platform
  cli_serve.py -- 3 --> platform
  memory -- 3 --> core
  tour.py -- 3 --> core
  tour.py -- 3 --> safety
```

