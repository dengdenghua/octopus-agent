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
  sensing -- 83 --> platform
  safety -- 69 --> platform
  execution -- 54 --> platform
  sensing -- 51 --> memory
  memory -- 48 --> platform
  sensing -- 45 --> execution
  sensing -- 42 --> safety
  execution -- 38 --> safety
  sensing -- 33 --> adapters
  core -- 30 --> platform
  execution -- 19 --> memory
  sensing -- 18 --> core
  safety -- 17 --> memory
  sensing -- 17 --> protocol
  execution -- 15 --> core
  platform -- 15 --> execution
  core -- 14 --> safety
  core -- 13 --> execution
  platform -- 13 --> safety
  safety -- 13 --> adapters
  platform -- 12 --> sensing
  platform -- 11 --> memory
  platform -- 10 --> adapters
  core -- 9 --> memory
  platform -- 9 --> core
  execution -- 7 --> adapters
  memory -- 7 --> safety
  safety -- 7 --> core
  safety -- 7 --> execution
  adapters -- 6 --> platform
  sensing -- 6 --> projectos
  cli.py -- 5 --> memory
  cli.py -- 5 --> platform
  core -- 5 --> adapters
  memory -- 5 --> execution
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
  memory -- 3 --> protocol
  tour.py -- 3 --> core
  tour.py -- 3 --> safety
```

