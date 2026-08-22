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
  sensing -- 149 --> platform
  sensing -- 114 --> safety
  execution -- 95 --> platform
  safety -- 87 --> platform
  sensing -- 82 --> memory
  sensing -- 80 --> execution
  core -- 58 --> platform
  memory -- 58 --> platform
  execution -- 55 --> safety
  sensing -- 44 --> protocol
  platform -- 36 --> safety
  sensing -- 35 --> adapters
  sensing -- 33 --> core
  execution -- 31 --> memory
  core -- 26 --> execution
  core -- 26 --> safety
  platform -- 25 --> execution
  safety -- 22 --> memory
  platform -- 21 --> sensing
  execution -- 18 --> core
  memory -- 17 --> safety
  platform -- 16 --> memory
  core -- 14 --> memory
  platform -- 14 --> core
  safety -- 14 --> adapters
  sensing -- 13 --> projectos
  platform -- 11 --> adapters
  adapters -- 10 --> safety
  adapters -- 9 --> platform
  execution -- 9 --> adapters
  safety -- 8 --> execution
  safety -- 7 --> core
  memory -- 6 --> protocol
  _cli_commands.py -- 5 --> memory
  _cli_commands.py -- 5 --> platform
  cli_serve.py -- 5 --> safety
  core -- 5 --> adapters
  memory -- 5 --> core
  memory -- 5 --> execution
  adapters -- 4 --> sensing
  cli_core.py -- 4 --> execution
  cli_run.py -- 4 --> execution
  cli_serve.py -- 4 --> adapters
  execution -- 4 --> protocol
  platform -- 4 --> tentacle
  research -- 4 --> platform
  cli_core.py -- 3 --> core
  cli_reflect.py -- 3 --> platform
  cli_run.py -- 3 --> platform
  cli_serve.py -- 3 --> platform
  execution -- 3 --> sensing
  platform -- 3 --> cli
  projectos -- 3 --> execution
  projectos -- 3 --> memory
  projectos -- 3 --> safety
  sensing -- 3 --> workspace
  tour.py -- 3 --> core
  tour.py -- 3 --> safety
  workspace -- 3 --> platform
```

