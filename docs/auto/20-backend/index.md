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
  sensing -- 72 --> platform
  safety -- 57 --> platform
  execution -- 43 --> platform
  sensing -- 42 --> memory
  memory -- 40 --> platform
  sensing -- 38 --> safety
  sensing -- 34 --> execution
  execution -- 32 --> safety
  core -- 28 --> platform
  sensing -- 18 --> core
  safety -- 17 --> memory
  sensing -- 16 --> protocol
  sensing -- 15 --> adapters
  core -- 14 --> safety
  execution -- 14 --> core
  execution -- 13 --> memory
  platform -- 13 --> execution
  platform -- 12 --> safety
  safety -- 12 --> adapters
  core -- 11 --> execution
  platform -- 10 --> core
  platform -- 10 --> memory
  core -- 8 --> memory
  platform -- 8 --> sensing
  execution -- 7 --> adapters
  platform -- 7 --> adapters
  memory -- 6 --> safety
  safety -- 6 --> core
  safety -- 6 --> execution
  adapters -- 5 --> platform
  cli.py -- 5 --> platform
  core -- 5 --> adapters
  cli_core.py -- 4 --> execution
  cli_run.py -- 4 --> execution
  cli_serve.py -- 4 --> adapters
  research -- 4 --> platform
  adapters -- 3 --> safety
  cli.py -- 3 --> memory
  cli_reflect.py -- 3 --> platform
  cli_run.py -- 3 --> platform
  cli_serve.py -- 3 --> platform
  cli_serve.py -- 3 --> safety
  memory -- 3 --> protocol
  tour.py -- 3 --> core
  tour.py -- 3 --> safety
```

