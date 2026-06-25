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
  sensing -- 74 --> platform
  safety -- 61 --> platform
  execution -- 53 --> platform
  sensing -- 47 --> memory
  sensing -- 44 --> execution
  memory -- 41 --> platform
  sensing -- 41 --> safety
  execution -- 36 --> safety
  sensing -- 30 --> adapters
  core -- 29 --> platform
  execution -- 19 --> memory
  sensing -- 19 --> core
  safety -- 17 --> memory
  sensing -- 17 --> protocol
  execution -- 15 --> core
  core -- 14 --> safety
  platform -- 14 --> execution
  safety -- 13 --> adapters
  core -- 12 --> execution
  platform -- 12 --> safety
  platform -- 10 --> core
  platform -- 10 --> memory
  core -- 9 --> memory
  platform -- 9 --> adapters
  platform -- 8 --> sensing
  execution -- 7 --> adapters
  memory -- 7 --> safety
  safety -- 7 --> core
  safety -- 6 --> execution
  adapters -- 5 --> platform
  cli.py -- 5 --> memory
  cli.py -- 5 --> platform
  core -- 5 --> adapters
  cli_core.py -- 4 --> execution
  cli_run.py -- 4 --> execution
  cli_serve.py -- 4 --> adapters
  platform -- 4 --> tentacle
  research -- 4 --> platform
  adapters -- 3 --> safety
  cli_reflect.py -- 3 --> platform
  cli_run.py -- 3 --> platform
  cli_serve.py -- 3 --> platform
  cli_serve.py -- 3 --> safety
  memory -- 3 --> execution
  memory -- 3 --> protocol
  tour.py -- 3 --> core
  tour.py -- 3 --> safety
```

