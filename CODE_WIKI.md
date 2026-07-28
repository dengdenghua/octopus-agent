# Octopus-Agent · Code Wiki

> 本文档是对 octopus-agent 仓库的结构化代码百科，涵盖项目整体架构、主要模块职责、关键类与函数、依赖关系及运行方式。
> 生成依据：仓库当前磁盘状态（v0.2.0，Beta）。

---

## 目录

1. [项目定位](#1-项目定位)
2. [整体架构](#2-整体架构)
3. [仿生命名映射](#3-仿生命名映射)
4. [核心数据流](#4-核心数据流)
5. [主要模块职责](#5-主要模块职责)
   - 5.1 [runtime/core · 规划与神经中枢](#51-runtimecore--规划与神经中枢)
   - 5.2 [runtime/execution · 执行层](#52-runtimeexecution--执行层)
   - 5.3 [runtime/memory · 记忆与协作](#53-runtimememory--记忆与协作)
   - 5.4 [runtime/safety · 安全与治理](#54-runtimesafety--安全与治理)
   - 5.5 [runtime/sensing · 输入与模型路由](#55-runtimesensing--输入与模型路由)
   - 5.6 [runtime/platform · 平台基础设施](#56-runtimeplatform--平台基础设施)
   - 5.7 [runtime/protocol · 线协议](#57-runtimeprotocol--线协议)
   - 5.8 [runtime/research · 深度研究](#58-runtimeresearch--深度研究)
   - 5.9 [runtime/projectos · 项目引擎](#59-runtimeprojectos--项目引擎)
   - 5.10 [runtime/tentacle · 跨设备触手](#510-runtimetentacle--跨设备触手)
   - 5.11 [runtime/workspace · 工作区](#511-runtimeworkspace--工作区)
   - 5.12 [runtime/adapters · 通道适配器](#512-runtimeadapters--通道适配器)
   - 5.13 [frontend · 前端工作台](#513-frontend--前端工作台)
6. [依赖关系](#6-依赖关系)
7. [项目运行方式](#7-项目运行方式)
8. [测试与质量门禁](#8-测试与质量门禁)

---

## 1. 项目定位

Octopus-Agent 是一个**自托管、仿生内核的 Agent OS runtime**，用 Python 构建，附带 React/Electron 工作台。

| 维度 | 说明 |
|---|---|
| 它是什么 | Python Agent OS runtime + React/Electron 工作台 |
| 解决什么 | 把 agent 的规划、执行、记忆、安全、成本、审计、反思组织到一条可观测链路里 |
| 不是什么 | 不是 ChatGPT 替代品，不是 LangChain 封装，不绑定单一 LLM |
| 核心依赖 | `pydantic>=2.12`，其余能力均为 optional extras |
| 成熟度 | Beta v0.2.0 |
| License | Apache-2.0 |
| Python | >=3.11 |

核心心智模型：

```
Goal -> Plan -> Execute -> Observe -> Remember -> Improve
```

---

## 2. 整体架构

### 2.1 仓库根布局

| 路径 | 作用 |
|---|---|
| `runtime/` | Python 运行时与 API 面（核心源码） |
| `frontend/` | React + Vite + Electron 工作区 UI |
| `tests/` | 回归、单元和集成测试（400+ 测试文件） |
| `agents/` | Agent 定义、preset 和元数据（admin/aoi/coder/general 等） |
| `skills/` | 可调用技能与技能元数据 |
| `protocols/` | 协议规范资产（budget/digestion/evolution/reflex/swarm 等） |
| `prompts/` | Prompt 模板与变体资产 |
| `extensions/` | 随运行时发布的扩展 |
| `tools/` | 开发工具（lint/invariant check） |
| `scripts/` | 项目自动化脚本 |
| `deploy/` | 部署清单（K8s manifests、Prometheus、Grafana） |
| `docs/` | 架构、入门、审计和参考文档 |
| `demos/` | 可运行示例 |
| `benchmarks/` | 可重复基准测试资产 |
| `meta_skills/` | YAML 定义的高阶技能（bug-hunt/code-review/daily-brief 等） |

### 2.2 运行时模块结构

```
runtime/
├── core/               规划引擎 + 事件总线 + 进程协调
│   ├── cerebrum/       ReAct 循环 + Planner + 安全检测器
│   ├── hearts/         进程协调（分布式锁、健康检查、鳃心泵）
│   └── nerves/         进程内类型化事件总线 + Reflex 规则引擎
├── execution/          执行层
│   ├── arms/           Worker 池 + 技能路由
│   ├── suckers/        技能加载器（60+ 内置技能）
│   ├── tool_engine/    工具执行引擎
│   ├── swarm/          多智能体 swarm runtime
│   └── parallel_agents/ 并行 agent 编排器
├── memory/             记忆与学习
│   ├── journal/        事件日志 + 检查点恢复
│   ├── hemolymph/      上下文组合器
│   ├── learning/       反思循环 + 技能晋升
│   ├── knowledge_graph/ 知识图谱（SQLite + Kuzu）
│   ├── cowork/         多智能体协作状态机
│   ├── threads/        线程存储 + 压缩 + LLM 摘要
│   └── skills_lib/     技能库 + 策展
├── safety/             安全与治理
│   ├── validation/     Constitution 出站检查（规则 + LLM-Judge）
│   ├── auth/           信任引擎 + 攻击记忆 + 自适应免疫
│   ├── budget_breaker/ 预算熔断器
│   ├── evolution/      适应度评估 + 漂移监控
│   ├── experiments/    A/B 实验 + Prompt 变体
│   ├── recovery/       技能锻造 + 基因组注册表
│   ├── chromatophores/ 信号总线 + Boids 仲裁
│   ├── sandboxing/     沙箱（本地 + Docker）
│   ├── hooks/          工具调用前/后钩子
│   └── invariants/     不变量强制
├── sensing/            输入与模型路由
│   ├── gateway/        API 网关 + Realtime Cerebrum runtime
│   ├── model_router/   LLM provider 路由 + 设备管理
│   ├── normalize/      传感器归一化 + 文件监听
│   └── server/         K8s/SSH 命令执行后端
├── platform/           基础设施
│   ├── config/         配置构建器 + Schema + Presets
│   ├── process/        Session + EventBus + Streaming + 分布式锁
│   ├── ui/             Web UI 路由 + Chat 页面 + 健康
│   ├── io/             原子写入 + 文件租约
│   ├── models/         LLM 管道 + 数据类型
│   ├── observability/  日志 + 指标 + 脱敏 + 健康探针
│   ├── extensions.py   应用扩展发现
│   └── i18n/           国际化（en/zh/ja/ko）
├── protocol/           线协议（JSON-RPC 2.0 + Item 模型）
├── research/           深度研究管线
├── projectos/          项目引擎（里程碑驱动）
├── tentacle/           跨设备触手（手机/桌面/IoT）
├── workspace/          工作区（挂载 + 成员 + 加密）
├── adapters/           通道适配器（20+ 渠道）+ MCP client + 调度器
├── cli.py / cli_*.py   CLI 入口与子命令
└── tour.py             引导流程
```

---

## 3. 仿生命名映射

项目使用"仿生词 → 工程语言"双轨命名（ADR-001 约定）。理解这层映射是阅读代码的前提：

| 仿生词 | 工程对应 | 落地位置 |
|---|---|---|
| **Cerebrum（脑）** | Planner / ReAct 循环 | `runtime/core/cerebrum/` |
| **Hearts（心脏）** | 舱壁隔离 facade：系统调度器 + I/O 熔断器 + 选主 | `runtime/core/hearts/` |
| **Nerves（神经）** | 进程内事件总线 + 工具钩子 + 反射弧 | `runtime/core/nerves/` |
| **Arms（腕足）** | 进程内 Worker 池（专家执行器） | `runtime/execution/arms/` |
| **Tentacle（触手）** | 跨网络远程设备代理 | `runtime/tentacle/` |
| **Sucker / Beak（吸盘/喙）** | 技能 / 工具 | `runtime/execution/suckers/` |
| **Hemolymph（血淋巴）** | 共享上下文 / 黑板 | `runtime/memory/hemolymph/` |
| **Immunity（免疫）** | 信任引擎 + 安全守卫 | `runtime/safety/auth/` |
| **Ink（墨汁）** | 预算守卫（熔断器） | `runtime/safety/budget_breaker/` |
| **Eyes（眼）** | 模型路由器 | `runtime/sensing/model_router/` |
| **Siphon（漏斗）** | I/O 网关 | `runtime/sensing/gateway/` |
| **Chromatophores（色素细胞）** | 信号总线 + 仲裁 | `runtime/safety/chromatophores/` |
| **Genome（基因组）** | 记忆存储 | `runtime/memory/` |
| **Regeneration（再生）** | 进化循环（学习/锻造） | `runtime/memory/learning/` |
| **Camouflage（伪装）** | 策略选择器（A/B 实验） | `runtime/safety/experiments/` |
| **SpinalCord（脊髓）** | 反射层（绕过 LLM 的快速响应） | `runtime/core/nerves/reflex/` |

---

## 4. 核心数据流

```
User Input
    │
    ▼
Sensing (model_router + gateway)        ← Eyes / Siphon
    │
    ▼
Cerebrum (react_loop)                   ← 脑
    │  Planner 拆解任务 → 工具调用
    │  安全检测器扫描每一步
    │  Token juicer 管理上下文预算
    │
    ▼
Tool Engine (executor)                  ← Arms
    │  执行前: immunity.check() + path_guard
    │  在沙箱中执行 (local/docker/k8s/ssh)
    │  执行后: immunity.learn() + journal.write()
    │
    ▼
Siphon (protocol/envelope)              ← 线协议
    │  通过 JSON-RPC WebSocket 流式返回
    │  SSE fallback 供简单客户端
    │
    ▼
Client (frontend / channel adapter)
```

**关键设计原则**：
1. 快路径优先于慢路径——已知工作用反射（reflex）而非 LLM 调用。
2. 每个有意义的动作都在 journal 留下事件痕迹。
3. Agent 受监督：有作用域、有预算、可取消、可检查。
4. 技能是能力，不是魔法——可测试、可审计。
5. 进化是被提议和审查的，不是盲目的自我修改。

---

## 5. 主要模块职责

### 5.1 runtime/core · 规划与神经中枢

#### 5.1.1 Cerebrum（脑 / ReAct 循环）

中央执行循环。每个 turn：
1. **Plan**：LLM 决定下一步动作（工具调用或回复）
2. **Guard**：安全检测器检查计划动作
3. **Execute**：工具引擎在沙箱中执行
4. **Observe**：结果反馈进上下文
5. **Repeat**：直到任务完成或预算耗尽

支持单步与并行分派、写操作后自动诊断、跨会话检查点恢复、暂停/恢复控制。

#### 5.1.2 Hearts（心脏 · 进程协调）

**不是"心跳调度器"**，而是聚合 facade，把"舱壁隔离 + 选主"组合在一起。

| 类/函数 | 文件 | 作用 |
|---|---|---|
| `Hearts` | `core/hearts/hearts.py` | 核心 facade。聚合 `BackgroundRunner`（系统心=内部调度）+ `CircuitBreaker`（鳃心=I/O 熔断）+ `Coordinator`（选主） |
| `HeartsSnapshot` | 同上 | 健康快照，含 systemic/branchial 状态 |
| `Hearts.dispatch_io(channel)` | 同上 | 按通道名取熔断器包 I/O 调用 |
| `Hearts.acquire_leadership(scope)` | 同上 | 选主上下文管理器 |
| `Coordinator` (Protocol) | `core/hearts/coordinator.py` | 选主后端协议：acquire/renew/release lease |
| `InMemoryCoordinator` | 同上 | 单进程内存租约 |
| `FileLockCoordinator` | 同上 | 跨进程文件锁（fcntl/msvcrt） |
| `RedisCoordinator` / `EtcdCoordinator` | 同目录 | 分布式后端 |
| `LeaderGuard` | 同上 | 选主上下文管理器 |
| `GillHeartPump` | `core/hearts/gill_pump.py` | 后台 daemon 线程泵，预压缩历史/预取记忆，避免主循环阻塞 |
| `GillCache` | 同上 | 线程安全的预处理缓存 |

仿生隐喻：章鱼 3 颗心脏——体循环（系统心）驱动内部主循环；鳃循环（鳃心）驱动外部 I/O 交互；两套循环物理隔离（Bulkhead）。鳃心泵在后台把血液（上下文）泵到鳃做"氧合"（预处理）。

#### 5.1.3 Nerves（神经 · 事件总线 + 钩子 + 反射）

| 类/函数 | 文件 | 作用 |
|---|---|---|
| `NervesEvent` | `core/nerves/bus.py` | 所有神经事件的基类（pydantic frozen model） |
| `SkillRegistered` / `SkillRetired` | 同上 | 技能注册/退役事件 |
| `AgentAdded` / `AgentRemoved` | 同上 | Agent 加入/移除事件 |
| `BudgetPressure` | 同上 | 预算压力事件 |
| `ConversationOpened` | 同上 | 会话开启事件 |
| `AbstractEventBus` | 同上 | 总线抽象基类：subscribe/publish/on() |
| `TypedEventBus` | 同上 | 默认实现，线程安全，crash-resilient（吞订阅者异常仅 warning） |
| `HookManager` | `core/nerves/hooks.py` | 工具调用前/后钩子注册中心。pre 钩子可短路，post 钩子链式改写结果 |
| `HookContext` / `HookResult` | 同上 | 钩子上下文与返回值 |
| `Reflex` (ABC) | `core/nerves/reflex/reflex_router.py` | 反射规则抽象基类 |
| `RegexMatcher` / `DeterministicMatcher` / `CacheMatcher` | 同上 | 正则/确定性/LRU 缓存匹配器 |
| `ReflexRouter` | 同上 | 反射路由器，按 priority 遍历规则，带 gating 灰度与热重载 |

`TypedEventBus` 是进程内同步发布-订阅（非分布式消息队列）。反射弧是绕过 LLM 的确定性快速响应通路。

---

### 5.2 runtime/execution · 执行层

#### Arms（腕足 · 进程内 Worker 池）

| 类/函数 | 文件 | 作用 |
|---|---|---|
| `Worker` (= `Arm`) | `execution/arms/base.py` | Arm 具体实现。持有 affinity 标签与 allowed_skills，通过 SignalBus mesh 通信 |
| `Worker.handle(task, budget)` | 同上 | 核心执行：调 `GraphRuntime.run(subgraph)` 执行子图，聚合 trajectory |
| `Worker.can_use(skill_ref)` / `can_handle(task)` | 同上 | 能力判定 |
| `ArmPool` | 同上 | Worker 集合。`pick_for(task)` 按 skill 覆盖度排序选 Arm；`pick_for_intent(intent)` 按 affinity 标签匹配 |
| `send_to_arm` / `drain_mailbox` | 同上 | Arm 间点对点消息 |

Arms 对应章鱼"体内执行臂"——8 条腕足在母体内协同。每条 Arm 是一个专家 Worker，通过 SignalBus 做 mesh 网状通信。

#### Tentacle（触手 · 远程设备代理）

| 类/函数 | 文件 | 作用 |
|---|---|---|
| `Tentacle` (Protocol) | `tentacle/base.py` | 所有 Tentacle 必须实现的 6 个核心点：connect/disconnect/heartbeat/execute + 状态属性 |
| `TentacleType` / `TentacleStatus` | 同上 | 设备类型（MOBILE/DESKTOP/TV/IOT...）/状态枚举 |
| `Heartbeat` / `ToolCall` / `ToolResult` | 同上 | 心跳/工具调用请求/结果数据类 |
| `TentaclePool` | `tentacle/pool.py` | 统一入口。`select_for_affinity` LEAST_USED 策略选设备；`acquire_lock`/`release_lock` 多 Arm 互斥 |
| `DeviceLock` | 同上 | 设备锁 |
| `fleet.broadcast()` | `tentacle/fleet.py` | 群控：一人驱动 N 台，`asyncio.Semaphore` 反压，异常降级不拖垮整批 |
| `DesktopDevice` | `tentacle/desktop.py` | 把本地桌面包装成触手（"自指"触手） |
| `create_tentacle_router()` | `tentacle/dashboard.py` | FastAPI REST/WS API（设备列表/任务/截图/VLM 分析/屏幕流） |
| `TentacleCoordinator` | `tentacle/coordinator.py` | 装配中枢：持有 Pool/ScreenRelay/WSServer/决策引擎 |

Arms vs Tentacle 对照：

| 维度 | Arms | Tentacle |
|---|---|---|
| 通信 | 进程内 SignalBus mesh | 跨网络 WebSocket + JSON-RPC |
| 调度单位 | ArmAssignment（含 subgraph） | ToolCall（单步原子） |
| 选择策略 | 按 skill 覆盖度 | 按 capability + LEAST_USED |
| 互斥 | 无显式锁 | DeviceLock |

---

### 5.3 runtime/memory · 记忆与协作

#### Cowork（多智能体协作状态机）

| 类/函数 | 文件 | 作用 |
|---|---|---|
| `MemberEvent` | `memory/cowork/group.py` | 只追加事件。action: invite/leave/mute/unmute/mode/room_link/workspace_link |
| `GroupState` | 同上 | 折叠结果：roster + mode + event_count |
| `fold_state(events)` | 同上 | 事件溯源核心：按 seq 排序后顺序折叠成 GroupState |
| `visible_message_range(member)` | 同上 | 隐私切片：根据 ContextGrant 计算可见消息区间 |
| `responders(state)` | 同上 | 从协作模式到行为：chat 用 @点名、cluster 由 leader 编排、swarm 并行、project 由引擎调度 |
| `ContextGrant` | 同上 | 历史消息切片授权（all/from_join/range/summary） |
| `CoworkStore` | `memory/cowork/store.py` | 磁盘三件套（plan/assignment/artifact）+ 状态机（PLAN→WORK→SYNTHESIZE→COMPLETE） |
| `KanbanDispatcher` | 同上 | 后台守护线程：过期租约清理 + 失败 synthesize 恢复 |
| `claim_task` / `release_expired_leases` | 同上 | 任务认领（per-path Lock + atomic_write） / 租约释放 |

四种协作模式：`chat`（@点名）、`cluster`（leader 编排）、`swarm`（并行）、`project`（引擎调度）。

#### 其他记忆模块

| 模块 | 路径 | 作用 |
|---|---|---|
| Journal | `memory/journal/` | 事件日志（JSONL）+ 检查点恢复 |
| Hemolymph | `memory/hemolymph/` | 上下文组合器（从 gill cache 读预处理段） |
| Learning | `memory/learning/` | 反思循环 + 技能晋升 |
| Knowledge Graph | `memory/knowledge_graph/` | 知识图谱（SQLite + Kuzu） |
| Threads | `memory/threads/` | 线程存储 + 压缩 + LLM 摘要 |

---

### 5.4 runtime/safety · 安全与治理

#### 信任引擎（Immunity）

三层安全检查（每次工具执行前）：
1. **Tolerance**：自我白名单旁路（内部调用）
2. **Innate + Memory**：信任源白名单 + 攻击模式库
3. **Adaptive**：z-score 行为异常评分（可选）

执行后学习：更新行为基线、晶化攻击模式。

#### Constitution Gate（出站检查）

| Pass | 作用 |
|---|---|
| Pass 1 — Rule | 正则/关键词扫描 PII、密钥、API key |
| Pass 2 — Rewrite | 自动脱敏（`[REDACTED:email]`） |
| Pass 3 — LLM-Judge | 第二次 LLM 调用做语义检查（可选，默认关） |
| Pass 4 — Human-Gate | 高风险动作审批队列 |

#### Budget Breaker（预算熔断器）

三态熔断器：Green（正常）→ Yellow（警告，接近限制）→ Red（熔断，暂停执行需人工确认）。触发条件：单任务 token/cost 限制、连续失败、零信息增益循环。

#### 安全钩子

| 类/函数 | 文件 | 作用 |
|---|---|---|
| `HookEvent` | `safety/hooks/events.py` | 钩子事件基类 |
| `PreToolUseEvent` / `PostToolUseEvent` | 同上 | 工具调用前/后事件（可取消或改 args/output） |
| `UserPromptSubmitEvent` | 同上 | Planner 看到新 user turn 前事件 |
| `StopEvent` / `SessionStartEvent` / `NotificationEvent` | 同上 | turn 结束/会话开始/通知事件 |
| `dispatch_pre_tool()` / `dispatch_post_tool()` 等 | `safety/hooks/runner.py` | 分发助手，按注册顺序遍历 handler |
| `scrub_credential_env()` | `safety/env_scrub.py` | 为不受限子进程清理环境变量中的凭据 |

---

### 5.5 runtime/sensing · 输入与模型路由

| 模块 | 路径 | 作用 |
|---|---|---|
| Gateway | `sensing/gateway/` | API 网关 + Realtime Cerebrum runtime + ~50 个 FastAPI router |
| Model Router | `sensing/model_router/` | LLM provider 路由（Anthropic/OpenAI/Gemini/Mock）+ 设备管理 |
| Normalize | `sensing/normalize/` | 传感器归一化 + 文件监听 |
| K8s Backend | `sensing/server/k8s.py` | 通过 `kubectl run` 在 K8s 起临时 Pod 执行命令 |
| SSH Backend | `sensing/server/ssh.py` | 通过 SSH（CLI 或 paramiko）在远端执行命令 |

K8s/SSH 后端均继承 `LocalBackend`/`Sandbox`，统一 `run_command` 返回结构与 200KB 输出上限。

---

### 5.6 runtime/platform · 平台基础设施

#### 原子 I/O

| 类/函数 | 文件 | 作用 |
|---|---|---|
| `atomic_write_bytes/text/json()` | `platform/io/atomic.py` | 原子写入：写临时文件 → fsync → 滚动 .bak → os.replace |
| `read_json_with_backup()` | 同上 | 读 JSON，主文件损坏自动回退 .bak |
| `_DebouncedWriter` / `debounced_json_writer()` | 同上 | 防抖写入器（高频小改文件） |
| `LeaseStore` | `platform/io/lease.py` | SQLite 持久化文件租约（带 TTL + 后台清理线程） |
| `FileLease` / `LeaseConflictError` | 同上 | 租约记录 / 冲突异常 |

这是整个代码库的持久化地基，被 25+ 文件直接导入。

#### LLM 数据类型

| 类/函数 | 文件 | 作用 |
|---|---|---|
| `Message` / `MessageRole` | `platform/models/llm.py` | 消息模型（支持结构化 content-block） |
| `ModelRequest` / `ModelResponse` | 同上 | 完整请求/响应模型 |
| `ModelRouter` (ABC) | 同上 | 抽象路由器接口，`call()` + `call_stream()` 默认实现 |
| `ToolSpec` / `ToolCall` | 同上 | 工具定义 / 模型发起的工具调用 |
| `ModelStreamEvent` | 同上 | 流式事件（text_delta/thinking_delta/tool_use/done） |
| `thinking_budget_for_effort()` | 同上 | 按 effort 计算 thinking budget |

这些类型下沉到 platform 层，避免 cerebrum/safety/memory 向上依赖 sensing。

#### UI 装配

| 类/函数 | 文件 | 作用 |
|---|---|---|
| `create_app()` | `platform/ui/app.py` | 主装配函数（~2300 行）：构建 FastAPI，挂载 ~50 个 router + 调度器 + 扩展点 |
| `AppState` | `platform/ui/state.py` | 共享 UI 状态：journal/registry/trace_store/task_supervisor |
| `_INDEX_HTML` / `_REFLEX_PANEL_HTML` | `platform/ui/pages.py` | 零依赖内联 HTML（无 Vite 构建时的回退界面） |
| `load_app_extensions()` | `platform/extensions.py` | 发现并运行 `OCTOPUS_APP_EXTENSIONS` 声明的应用扩展 |
| `load_skill_extensions()` | 同上 | 发现并运行 `OCTOPUS_SKILL_EXTENSIONS` 技能扩展 |

#### 可观测性

| 模块 | 路径 | 作用 |
|---|---|---|
| `Redactor` | `platform/observability/redactor.py` | PII/密钥脱敏（9 类：api_key/aws_secret/jwt/email/phone/credit_card/private_key 等） |
| `HealthRegistry` | `platform/observability/health.py` | K8s 健康探针框架（liveness/readiness，并行检查） |
| `MetricsRegistry` | `platform/observability/metrics.py` | 零依赖 Prometheus 兼容 Counter/Gauge/Histogram |
| `configure_logging()` | `platform/observability/logging_config.py` | 集中式日志配置 |
| `StructuredFormatter` | `platform/observability/structured_logging.py` | 结构化 JSON 日志 + correlation ID |
| `Doctor` | `platform/observability/doctor.py` | 环境诊断（Python 版本/依赖/API key/Ollama/配置/数据目录） |

#### i18n

| 函数 | 作用 |
|---|---|
| `_(key, **kwargs)` | 标准翻译 |
| `t(key, *, count, **kwargs)` | 复数感知翻译 |
| `L(key, **kwargs)` | 惰性字符串（模块加载期定义，`__str__` 时解析） |
| `get_safety_relax_markers()` | 跨语言安全放松标记（供 PromptEvolver 检测） |

支持 en/zh-CN/ja/ko 四语言，基于 mtime 的惰性热重载。

---

### 5.7 runtime/protocol · 线协议

JSON-RPC 2.0 信封 + 方法名常量 + Item 状态模型，定义 realtime 通道两端契约。

| 类/函数 | 文件 | 作用 |
|---|---|---|
| `JsonRpcRequest` / `JsonRpcResponse` / `Notification` | `protocol/envelope.py` | JSON-RPC 2.0 三种消息类型 |
| `encode_message()` / `decode_message()` | 同上 | 单行 JSON 编解码 |
| `ClientMethod` (StrEnum) | `protocol/events.py` | 客户端→服务端方法名常量（THREAD_START/TURN_START/STEER/INTERRUPT 等） |
| `ServerMethod` (StrEnum) | 同上 | 服务端→客户端方法名常量（TURN_STARTED/COMPLETED/ITEM_*_DELTA 等） |
| `Item` (discriminated union) | `protocol/items.py` | 14 种 Item 类型（agentMessage/reasoning/commandExecution/fileChange/mcpToolCall 等） |
| `Turn` / `TurnParams` / `TurnStatus` | 同上 | Turn 状态模型 |
| `FileHunk` / `FileChange` | 同上 | 文件变更 hunk 级模型（含 decision: pending/accepted/rejected） |

一个 Turn 是有序 Item 列表；每个可观察 agent 输出都是一个 Item，生命周期统一：`item/started` → 0..n delta → `item/completed`。

---

### 5.8 runtime/research · 深度研究

Perplexity 风格的"提问→搜索→抓取→重排→引用合成"管线。

| 类/函数 | 文件 | 作用 |
|---|---|---|
| `research_answer()` | `research/pipeline.py` | 单轮主管线（6 阶段：query_rewrite → web_search → fetch_url → rerank → render_citation_prompt → resolve_citations） |
| `research_loop()` | 同上 | 多轮（Perplexity Pro 风格），每轮后 LLM 判断是否够答 |
| `ResearchAnswer` | 同上 | 管线产物（含 answer/queries/sources/used_indices） |
| `build_citation_context()` / `resolve_citations()` | `research/citations.py` | 引用编号渲染 / `[n]` 标记解析 |
| `rerank()` | `research/rerank.py` | 重排（BM25 默认零依赖 / Cohere Rerank v3 可选） |
| `ResearchPrefetcher` | `research/prefetch.py` | 深度研究预取（子智能体开工前预热证据池） |

所有阶段均有降级路径（LLM 失败回落关键词检查、cohere 失败回落 BM25、抓取失败保留 snippet）。

---

### 5.9 runtime/projectos · 项目引擎

基于"项目→里程碑→任务 DAG"的三层全局状态，由里程碑（而非循环本身）作为停止条件。

| 类/函数 | 文件 | 作用 |
|---|---|---|
| `ProjectEngine` | `projectos/engine.py` | 核心引擎。`plan()` 把目标转为带里程碑的 Project；`tick()` 循环单步；`run()` 连续 tick |
| `Project` / `Milestone` / `Task` | `projectos/model.py` | 三层数据模型（DAG via depends_on） |
| `ready_tasks(tasks)` | 同上 | 返回 DAG 前沿（依赖全 done 且自身 pending） |
| `ProjectStore` | `projectos/store.py` | SQLite 持久化（终态不可变约束保证幂等） |
| `create_llm_hooks(router)` | `projectos/llm_hooks.py` | 组装智能钩子（LLM 生成里程碑/任务 + subagent 执行 + QA 闸门） |
| `project_process_timeline()` | `projectos/timeline.py` | 进程时间线读模型（给运维呈现可审计时间线） |

引擎本身是纯编排，智能通过注入的 LLM 钩子实现：`MS 检查 → 任务分配 → 智能体执行 → QA 评估 → 里程碑闸门`。

---

### 5.10 runtime/tentacle · 跨设备触手

（详见 5.2 Tentacle 章节）

---

### 5.11 runtime/workspace · 工作区

把"工作区"定义为一等实体：挂载点 + 所有者 + 成员列表。

| 类/函数 | 文件 | 作用 |
|---|---|---|
| `Workspace` / `WorkspaceMember` | `workspace/model.py` | 数据类（mount_type: local/smb/nfs/webdav/sftp/s3） |
| `WorkspaceStore` | `workspace/store.py` | SQLite 持久化（workspaces + workspace_members 两表） |
| `encrypt_options()` / `decrypt_options()` | `workspace/crypto.py` | 敏感字段按字段 Fernet 加密（`ENC:<base64>` 格式） |
| `sync_workspace_members_to_group()` | `workspace/cowork_bridge.py` | 把 workspace 成员同步进 cowork 群组 |

桥接：`cowork_bridge.py` 把 Workspace 的 owner/editor/reviewer/viewer 角色映射到 cowork 的 participant/observer + ContextGrant，决定不同角色在协作线程里能看到的隐私切片。

---

### 5.12 runtime/adapters · 通道适配器

| 模块 | 路径 | 作用 |
|---|---|---|
| Channels | `adapters/channels/` | 20+ 渠道适配器（Discord/Slack/WeChat/Telegram/Email/Feishu/DingTalk/...） |
| MCP Client | `adapters/mcp_client/` | MCP 协议客户端 |
| Scheduler | `adapters/scheduler/` | Cron 调度器（`BackgroundRunner`） |
| Integrations | `adapters/integrations/` | 第三方集成（Molili 认证、local auth） |

---

### 5.13 frontend · 前端工作台

React 19 + Vite 7 + TypeScript + TailwindCSS 4 + Electron 桌面壳。

| 特性 | 说明 |
|---|---|
| 状态管理 | `@tanstack/react-query` |
| 代码编辑器 | CodeMirror 6（含 merge/diff） |
| 终端 | xterm.js |
| 流程图 | `@xyflow/react` |
| Markdown | remark + rehype + KaTeX + Mermaid + Shiki |
| 测试 | Vitest（单元）+ Playwright（E2E） |
| API 类型 | 从 `docs/openapi-snapshot.json` 生成 TypeScript 类型 |

前端核心目录 `frontend/src/core/` 按领域组织 API 层：api/apps/arena/auth/mcp/oct/tasks/teams。

---

## 6. 依赖关系

### 6.1 Python 依赖（pyproject.toml）

核心依赖极简，其余能力通过 optional extras 按需安装：

| Extra | 包 | 作用 |
|---|---|---|
| （核心） | `pydantic>=2.12` | 唯一硬依赖 |
| `minimal` | httpx, python-dotenv | 最小 demo |
| `dev` | pytest, ruff, mypy, bandit, pip-audit | 开发工具链 |
| `serve` | fastapi, uvicorn, pyyaml, python-multipart | Web 服务 |
| `web` | httpx | Web 技能 |
| `anthropic` | anthropic | Anthropic LLM |
| `mcp` | mcp | MCP 客户端 |
| `browser` | playwright | 浏览器技能 |
| `desktop` | pyautogui, pillow | 桌面技能 |
| `code-intel` | tree-sitter | AST 代码搜索 |
| `channels` | httpx, cryptography | 渠道适配器 |
| `hearts-redis` | redis | Redis 选主后端 |
| `hearts-etcd` | etcd3-py | etcd 选主后端 |
| `tracing` | opentelemetry-api, opentelemetry-sdk | OpenTelemetry |
| `local-auth` | bcrypt | 本地认证 |
| `storage` | octopus-storage | File Agent 文档库 |

### 6.2 模块间依赖方向

```
platform  ← 最底层基座（io/models/observability/i18n/config）
    ↑
core      ← 规划与神经中枢（依赖 platform）
    ↑
memory / safety / sensing  ← 中间层（依赖 core + platform）
    ↑
execution / research / projectos / tentacle  ← 上层（依赖中间层）
    ↑
cli / adapters / ui  ← 入口层（装配一切）
```

**关键约束**：`platform/models/llm.py` 的类型下沉到基座层，避免 cerebrum/safety/memory 向上依赖 sensing。

### 6.3 前端依赖

React 19 + Vite 7 生态，详见 `frontend/package.json`。主要：`@tanstack/react-query`、CodeMirror 6 全家桶、`@xyflow/react`、xterm.js、Radix UI、TailwindCSS 4。

---

## 7. 项目运行方式

### 7.1 安装

```bash
# 最小 demo（不需要 LLM key）
pip install -e ".[minimal]"

# 开发环境
pip install -e ".[dev,serve,web]"

# 完整能力环境
pip install -e ".[dev,all]"
python -m playwright install chromium
```

### 7.2 CLI 入口

入口：`python -m runtime <command>`（`runtime/__main__.py` → `runtime/cli.py`）。

| 命令 | 作用 |
|---|---|
| `python -m runtime status` | 查看本机能力（检测已安装的依赖与 LLM router） |
| `python -m runtime bugfix-demo` | 跑确定性 bugfix demo（不依赖外部 LLM） |
| `python -m runtime serve --port 8000` | 启动 FastAPI Web UI 服务 |
| `python -m runtime ui --port 8000` | 启动 UI（同 serve 的简写） |
| `python -m runtime quickstart --non-interactive --serve` | 引导配置并启动服务 |
| `python -m runtime run "目标"` | 无头模式跑一个目标 |
| `python -m runtime loop "目标"` | 循环模式 |
| `python -m runtime reflect` | 反思/学习 |
| `python -m runtime doctor` | 环境诊断 |

CLI 子命令分布在：`cli_core.py`（status/build_stack）、`cli_serve.py`（serve）、`cli_run.py`（run/goal/bench/resume）、`cli_reflect.py`（reflect/loop/optimize）、`cli_code.py`、`cli_mcp.py`、`cli_project.py`、`cli_migrate.py`。

### 7.3 Web UI 端点

```bash
python -m runtime serve --port 8000
# 打开 http://127.0.0.1:8000
```

| 路径 | 作用 |
|---|---|
| `/` | 内置 dashboard |
| `/ui/` | React workspace（需 `frontend/dist`） |
| `/docs` | FastAPI Swagger |
| `/api/health` | 健康检查 |
| `/api/status` | 能力检查 |
| `/api/journal` | 最近事件 |
| `/api/realtime` | JSON-RPC WebSocket realtime 通道 |
| `/metrics` | Prometheus 指标 |
| `/livez` / `/readyz` | K8s 探针 |

### 7.4 前端开发

```bash
cd frontend
corepack enable
pnpm install --frozen-lockfile
pnpm dev              # 仅前端（Vite dev server 代理 /api 到后端）
pnpm dev:full         # 前后端一起起（config.local.yaml）
pnpm electron:dev     # Electron 桌面壳
```

常用检查：`pnpm typecheck` / `pnpm test` / `pnpm build` / `pnpm e2e`。

### 7.5 Docker 部署

```bash
# 最小单容器
cp .env.example .env
cp config.example.yaml config.yaml
docker compose up -d
docker compose logs -f octopus-agent
# → http://localhost:8000/

# 完整栈（含 Redis + Jaeger + Grafana）
docker compose -f docker-compose.full.yml up -d
# → Agent    http://localhost:8000/
# → Jaeger   http://localhost:16686/
# → Grafana  http://localhost:3000/  (admin/admin)
```

Dockerfile 为三阶段多阶段构建：
1. `node:20-alpine` → Vite 构建前端
2. `python:3.12-slim` → pip install 后端依赖
3. `python:3.12-slim` → 最小运行时镜像

### 7.6 K8s 部署

```bash
kubectl apply -k deploy/k8s/
kubectl -n octopus-agent get all,pvc,cm,secret
```

K8s manifests 位于 `deploy/k8s/`（deployment/service/ingress/PVC/configmap/secret/redis）。

### 7.7 配置

主配置文件 `config.yaml`（参考 `config.example.yaml`），所有值可通过 `${ENV_VAR}` 引用环境变量。

关键配置段：

| 段 | 作用 |
|---|---|
| `preset` | 预设模板（personal/team/enterprise/research） |
| `planner` | 规划器（type: static/llm，model，max_nodes） |
| `evolve` | 进化评估模型策略（inherit/cheaper_same_provider/explicit） |
| `budget` | 预算硬顶（max_tokens/max_usd/max_latency_ms） |
| `immunity` | 三层信任模型（trusted_sources/self_whitelist/unknown_policy + adaptive） |
| `intel_sources` | 情报源定时抓取 |
| `mcp_servers` | MCP 外部服务器 |
| `learn` | 学习/反思配置（6 路反思生成器） |
| `safety` | 安全守卫（disabled_guards/guard_overrides/enable_llm_judge/enable_trust_signal） |
| `oct` | oct 账号网关集成 |
| `local_auth` | 本地用户名认证 |

### 7.8 Makefile 常用目标

| 目标 | 作用 |
|---|---|
| `make install` / `make install-all` | 安装开发/全部依赖 |
| `make dev` | 用 config.local.yaml 启动开发服务器 |
| `make up` / `make up-full` | 启动最小/完整 compose 栈 |
| `make test` / `make test-fast` | 测试（带/不带覆盖率） |
| `make lint` | 全部 linter（invariants + mypy + ruff） |
| `make security` | bandit + pip-audit |
| `make frontend-dev` / `make dev-full` | 前端开发 / 前后端一起 |
| `make openapi-snapshot` | 重新生成 OpenAPI 快照 |
| `make bootstrap-skills` | 从 skills.lock.json 同步技能 |
| `make k8s-apply` | 应用 K8s manifests |

---

## 8. 测试与质量门禁

### 8.1 测试

```bash
python -m pytest -q                          # 全部快速测试
python -m pytest -m "not slow and not integration" -v  # 仅单元测试
python -m pytest -m integration -v           # 仅集成测试
```

测试文件位于 `tests/`（400+ 文件），覆盖所有核心子系统。`tests/conftest.py` 提供共享 fixture。

### 8.2 Lint

```bash
ruff check runtime/ tests/ tools/            # 静态检查
ruff format --check runtime/ tests/ tools/   # 格式检查
python -m tools.lint.invariant_check runtime/ tests/  # Octopus 不变量检查
python tools/lint/mypy_ratchet.py            # mypy 棘轮（不新增类型错误）
```

### 8.3 安全

```bash
bandit -r runtime/ -ll -ii                   # 安全扫描
pip-audit                                    # 依赖审计
```

### 8.4 生产就绪门禁

```bash
make production-readiness    # 运行生产就绪门禁（隔离运行时状态）
make verify-local            # 后端/前端/全栈本地稳定性门禁
```

---

## 附录：关键文件索引

| 文件 | 作用 |
|---|---|
| `runtime/__main__.py` | CLI 入口 |
| `runtime/cli.py` | CLI 主模块（re-export + status） |
| `runtime/cli_core.py` | CLI 核心（build_stack, reflex_router） |
| `runtime/cli_serve.py` | serve 命令逻辑 |
| `runtime/tour.py` | 引导流程 |
| `runtime/platform/ui/app.py` | FastAPI 主装配（~2300 行） |
| `runtime/platform/io/atomic.py` | 原子写入地基 |
| `runtime/platform/models/llm.py` | LLM 数据类型基座 |
| `runtime/core/cerebrum/react_loop.py` | ReAct 中央循环 |
| `runtime/core/hearts/hearts.py` | 心脏 facade |
| `runtime/core/nerves/bus.py` | 事件总线 |
| `runtime/core/nerves/reflex/reflex_router.py` | 反射路由器 |
| `runtime/execution/arms/base.py` | Arm Worker 与 ArmPool |
| `runtime/tentacle/base.py` | Tentacle 协议 |
| `runtime/tentacle/coordinator.py` | 触手装配中枢 |
| `runtime/memory/cowork/group.py` | 协作组事件溯源 |
| `runtime/memory/cowork/store.py` | CoworkStore + KanbanDispatcher |
| `runtime/safety/hooks/runner.py` | 安全钩子分发 |
| `runtime/safety/env_scrub.py` | 凭据脱敏 |
| `runtime/protocol/envelope.py` | JSON-RPC 2.0 信封 |
| `runtime/protocol/items.py` | Item 状态模型 |
| `runtime/research/pipeline.py` | 研究管线 |
| `runtime/projectos/engine.py` | 项目引擎 |
| `runtime/workspace/store.py` | 工作区持久化 |
| `pyproject.toml` | Python 依赖与项目元数据 |
| `config.example.yaml` | 配置示例 |
| `Dockerfile` | 三阶段构建 |
| `docker-compose.yml` | 最小部署栈 |
| `Makefile` | 常用命令快捷方式 |
