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
  sensing -- 63 --> platform
  memory -- 37 --> platform
  execution -- 36 --> platform
  sensing -- 35 --> memory
  safety -- 34 --> platform
  sensing -- 29 --> execution
  sensing -- 26 --> safety
  core -- 23 --> platform
  execution -- 18 --> safety
  sensing -- 15 --> core
  sensing -- 14 --> adapters
  execution -- 13 --> core
  platform -- 13 --> execution
  safety -- 12 --> adapters
  safety -- 12 --> memory
  execution -- 11 --> memory
  platform -- 11 --> safety
  core -- 10 --> safety
  platform -- 10 --> core
  platform -- 9 --> memory
  core -- 8 --> execution
  core -- 8 --> memory
  platform -- 8 --> sensing
  core -- 7 --> sensing
  execution -- 7 --> adapters
  safety -- 7 --> sensing
  execution -- 6 --> sensing
  memory -- 6 --> safety
  platform -- 6 --> adapters
  safety -- 6 --> core
  cli.py -- 5 --> platform
  core -- 5 --> adapters
  safety -- 5 --> execution
  sensing -- 5 --> protocol
  adapters -- 4 --> platform
  adapters -- 4 --> sensing
  cli_core.py -- 4 --> execution
  cli_run.py -- 4 --> execution
  research -- 4 --> platform
  adapters -- 3 --> safety
  cli.py -- 3 --> memory
  cli_reflect.py -- 3 --> platform
  cli_run.py -- 3 --> platform
  cli_serve.py -- 3 --> adapters
  cli_serve.py -- 3 --> platform
  memory -- 3 --> protocol
  tour.py -- 3 --> core
  tour.py -- 3 --> safety
```

