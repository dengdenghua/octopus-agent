# Octopus-Agent · Code Wiki

> 本文档是对 octopus-agent 仓库的结构化代码百科，涵盖项目整体架构、主要模块职责、关键类与函数、依赖关系及运行方式。
> 生成依据：仓库当前磁盘状态（v0.2.0，Beta）。所有目录与文件均以当前仓库实际结构为准。

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
   - 5.12 [runtime/adapters · 通道与集成](#512-runtimeadapters--通道与集成)
   - 5.13 [frontend · 前端工作台](#513-frontend--前端工作台)
6. [依赖关系](#6-依赖关系)
7. [项目运行方式](#7-项目运行方式)
8. [测试与质量门禁](#8-测试与质量门禁)
9. [附录：关键文件索引](#附录关键文件索引)

---

## 1. 项目定位

Octopus-Agent 是一个**自托管、仿生内核的 Agent OS runtime**，用 Python 构建，附带 React/Electron 工作台。它把 agent 的规划、执行、记忆、安全、成本、审计、反思组织到一条可观测链路里。

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
| `tests/` | 回归、单元和集成测试（数百个测试文件） |
| `agents/` | Agent 定义、preset 和元数据（admin/aoi/coder/general/echo_* 等） |
| `skills/` | 可调用技能与技能元数据 |
| `meta_skills/` | YAML 定义的高阶技能（bug-hunt/code-review/daily-brief 等） |
| `protocols/` | 协议规范资产（budget/digestion/evolution/reflex/swarm 等） |
| `prompts/` | Prompt 模板与变体资产 |
| `demos/` | 可运行示例（bugfix/reflection/evolution 等） |
| `benchmarks/` | 可重复基准测试资产 |
| `extras/` | 桌面附加工程（desktop/package.json） |
| `packaging/` | 桌面打包配置（electron-builder build.yml） |
| `deploy/` | 部署清单（K8s manifests、Prometheus、Grafana） |
| `docs/` | 架构、入门、审计和参考文档 |
| `scripts/` | 项目自动化脚本（gen_wiki.py/e2e_smoke_proof.py 等） |
| `octopus_runtime/` | 薄封装运行时（bootstrap/client/materialize） |
| `tools/` | 开发工具（lint/invariant check） |

### 2.2 运行时模块结构（`runtime/` 实际目录）

```
runtime/
├── core/               规划引擎 + 事件总线 + 进程协调
│   ├── cerebrum/       ReAct 循环 + Planner + 安全守卫 + 状态/恢复 + 思考模式（核心）
│   │   ├── react_loop.py / react_loop_*.py    ReAct 中央循环（拆分为多个模块）
│   │   ├── planner.py / llm_planner.py        规划器（静态/LLM）
│   │   ├── react_guards.py / react_security_guards.py  安全守卫
│   │   ├── token_juicer.py / thinking_mode.py / ai_mode.py / work_mode.py
│   │   ├── react_checkpointing.py / react_resume.py / resume_cli.py / rewind.py
│   │   └── todo_protocol.py / input_mentions.py / pause_control.py / live_steering.py
│   ├── graph_runtime/  GraphRuntime 任务图执行器（runtime.py）
│   ├── hearts/         心脏 facade：协调器 + 选主 + 鳃心泵
│   │   ├── hearts.py / coordinator_health.py / gill_pump.py
│   │   └── coordinator.py / redis_coordinator.py / etcd_coordinator.py
│   └── nerves/         事件总线 + 钩子 + 反射弧
│       ├── bus.py / hooks.py
│       └── reflex/     反射路由器 + 动作 + gating + 规则加载
├── execution/          执行层
│   ├── arms/           Arm Worker 池 + 工具注册表 + 进程树
│   ├── tool_engine/    ToolExecutor 工具执行引擎 + 技能门控
│   ├── suckers/        技能加载器 + 内置技能（registry/builtins/loader/hub）
│   ├── swarm/          多智能体 swarm 运行时
│   ├── parallel_agents/ 并行 agent 编排
│   ├── loops/          Loop 控制器（controller/dispatcher/store/learning/recovery）
│   ├── subagents/      Subagent 桥接与注册表
│   ├── agents/         Agent 定义/分组/预设/加载
│   ├── misc/           杂项（头像/能力目录/并行运行器/技能策略）
│   ├── slash_commands/ 斜杠命令加载
│   └── all_skills/     内置技能资产（browse/pdf/kubectl 等）
├── memory/             记忆与学习
│   ├── journal/        事件日志（SQLite 索引）+ 检查点恢复 + 进度跟踪
│   ├── cowork/         多智能体协作状态机（group/session/service/runtime/presence）
│   ├── hemolymph/      上下文组合器 + 代码索引 + 语义排序
│   ├── knowledge_graph/ 知识图谱（SQLite + Kuzu 双后端）
│   ├── learning/       反思循环 + 经验台账 + 技能晋升
│   ├── threads/        线程存储 + 压缩 + LLM 摘要
│   ├── skills_lib/     技能库 + 策展
│   ├── runtime_state/  运行时状态（黑板/热缓存/hub）
│   ├── users/          用户画像/偏好/检索历史
│   ├── diagnostics/    诊断（错误分类/追踪存储/wiki 编译）
│   └── control_sessions.py / control_sessions_codec.py
├── safety/             安全与治理
│   ├── auth/           信任引擎 + 攻击记忆 + 自适应免疫 + 路径/参数守卫
│   ├── validation/     Constitution 出站检查（规则 + LLM-Judge + prompt 注入）
│   ├── approval/       审批门 + 审批策略 + 取消 + 设备锁
│   ├── audit/          审计链 + 信任网关 + webhook 校验
│   ├── hooks/          工具调用前/后安全钩子
│   ├── budget_breaker/ 预算熔断器
│   ├── evolution/      适应度评估 + 漂移监控 + 自动验证 + 金丝雀
│   ├── experiments/    A/B 实验 + Prompt 变体
│   ├── recovery/       技能锻造 + 基因组注册表 + 原生回放 + 优化器
│   ├── chromatophores/ 信号总线 + Boids 仲裁
│   ├── conflict_resolution/ 冲突解决
│   ├── gene_locks/     基因锁（审批账本 + 简单门）
│   ├── governance/     执行策略治理
│   ├── invariants/     不变量强制
│   ├── organization/   组织拓扑 + 团队运行器
│   ├── replay/         浏览器桌面回放
│   ├── sandboxing/     沙箱（本地 + Docker）
│   └── env_scrub.py    凭据环境清理
├── sensing/            输入与模型路由
│   ├── gateway/        API 网关 + Realtime + 大量 router + agent market 资产
│   └── server/         K8s/SSH/Local 命令执行后端
├── platform/           基础设施
│   ├── ui/             FastAPI 主装配（app.py）+ 大量 router + 内联 HTML
│   ├── process/        Session + EventBus + Streaming + 分布式锁 + 任务监督
│   ├── models/         LLM 数据类型 + 上下文/执行/治理模型
│   ├── io/             原子写入 + 文件租约
│   ├── config/         配置构建器 + Schema + Presets
│   ├── observability/  日志 + 指标 + 脱敏 + 健康探针 + 诊断
│   ├── llm_infra/      LLM 调用器 + 缓存 + 预算跟踪
│   ├── budget/         迭代预算 + 限流 + 定价
│   ├── plugins/        插件注册表 + 加载器 + 技能市场
│   ├── i18n/           国际化（en/zh-CN/ja/ko）
│   ├── migration/      数据迁移（claude/codex/qoder 适配器）
│   ├── lifecycle/      备份/重置/数据迁移/设置向导
│   ├── prompts/        提示词注册表
│   ├── process/        进程/会话/事件总线
│   ├── runtime_policy/ 幂等/重试/工作区策略
│   ├── credentials/    凭据
│   ├── extensions.py   应用扩展点
│   └── step_format.py  步骤格式化
├── protocol/           线协议（JSON-RPC 2.0 + Item 模型 + diff 解析）
├── research/           深度研究管线
├── projectos/          项目引擎（里程碑驱动）
├── tentacle/           跨设备触手（手机/桌面/IoT）
├── workspace/          工作区（挂载 + 成员 + 加密）
├── adapters/           通道适配器（20+ 渠道）+ MCP client + 调度器 + 集成
├── cli.py / cli_*.py   CLI 入口与子命令
├── _cli_commands.py    各 run_* 命令处理器
├── _cli_parser.py      参数解析器
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
| **Eyes（眼）** | 模型路由器（历史命名，见 sensing） | `runtime/sensing/` |
| **Chromatophores（色素细胞）** | 信号总线 + 仲裁 | `runtime/safety/chromatophores/` |
| **Genome（基因组）** | 记忆存储 | `runtime/memory/` |
| **Regeneration（再生）** | 进化循环（学习/锻造） | `runtime/memory/learning/` + `runtime/safety/recovery/` |
| **Camouflage（伪装）** | 策略选择器（A/B 实验） | `runtime/safety/experiments/` |
| **SpinalCord（脊髓）** | 反射层（绕过 LLM 的快速响应） | `runtime/core/nerves/reflex/` |

---

## 4. 核心数据流

```
User Input
    │
    ▼
Sensing (gateway + server backends)          ← 输入网关
    │
    ▼
Cerebrum (react_loop)                        ← 脑
    │  Planner 拆解任务 → 工具调用
    │  安全守卫扫描每一步
    │  TokenJuicer 管理上下文预算
    │
    ▼
Tool Engine (executor)                       ← 臂
    │  执行前: 安全钩子 + path_guard + 技能门控
    │  在沙箱中执行 (local/docker/k8s/ssh)
    │  执行后: journal.write() + 学习
    │
    ▼
Siphon (protocol/envelope)                   ← 线协议
    │  通过 JSON-RPC WebSocket 流式返回
    │  SSE/HTTP fallback 供简单客户端
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

中央执行循环，拆分为多个模块。每个 turn：

1. **Plan**：Planner 决定下一步动作（工具调用或回复）
2. **Guard**：安全守卫检查计划动作
3. **Execute**：工具引擎在沙箱中执行
4. **Observe**：结果反馈进上下文
5. **Repeat**：直到任务完成或预算耗尽

| 类/函数 | 文件 | 作用 |
|---|---|---|
| `stream_react_loop()` / `run_react_loop()` | `cerebrum/react_loop.py` | 中央循环入口（流式/阻塞）。驱动循环迭代、安全守卫、最终答案守护，非类而是模块级函数 |
| `_LoopState` / `_LoopControl` | `cerebrum/react_loop_state.py` | 循环状态存储与迭代控制信号（`_LoopControl` 枚举驱动 RETURN_NONE/BREAK/NEXT_ITERATION） |
| `StaticPlanner` | `cerebrum/planner.py` | 静态规则规划器（`Rule` 驱动，无需 LLM） |
| `LLMPlanner` | `cerebrum/llm_planner.py` | 调用 LLM 并将其输出解析为任务计划（模型选择、提示构建、计划解析） |
| `evaluate_guards()` | `cerebrum/react_guards.py` | 多类安全/质量守卫评估：缺失检查、最终答案、todo 协议、代码模式完成等 |
| `react_security_guards.py` | `cerebrum/react_security_guards.py` | 输入/输出限制与过滤，检测恶意行为 |
| `JuiceStats`（token_juicer） | `cerebrum/token_juicer.py` | 跟踪 Token 使用，监控模型请求/响应 token 数、自定义最大限制 |
| `WorkMode` | `cerebrum/work_mode.py` | 工作环境模式（dev/prod） |
| `ThinkingPlan` / `ThinkingPlanStep` | `cerebrum/thinking_mode.py` | 思考模式：auto/manual，构建分解后的思考计划 |
| `todo_protocol.py` | `cerebrum/todo_protocol.py` | Todo 协议：判断是否要求 todo 协议、渲染协议引导 |
| `PauseController` / `PauseRequest` | `cerebrum/pause_control.py` | 暂停/恢复控制与请求 |
| `append_live_steering_messages()` | `cerebrum/live_steering.py` | 实时转向：写入用户中途转向指令 |
| `CheckpointMirror` / `_rehydrate_messages_from_steps()` | `cerebrum/checkpoint_mirror.py` / `react_checkpointing.py` | 检查点镜像与状态重建 |
| `_ResumeState` / `_ResumedTurn` | `cerebrum/react_resume.py` | 检查点恢复状态 |
| `RewindPoint` / `RewindResult` | `cerebrum/rewind.py` | 回溯到指定点 |
| `ReActStep` / `ReActResult` / `ReActRecipe` | `cerebrum/react_types.py` | ReAct 核心数据类型 |
| `InputMentions` | `cerebrum/input_mentions.py` | 输入中的 @提及 解析 |
| `react_prompt_assembly.py` | `cerebrum/react_prompt_assembly.py` | 提示词组装（拆分子模块 `_react_prompt_assembly_*.py`） |
| `react_terminal.py` / `react_native.py` | `cerebrum/` | 终端模式与原生模式 |

#### 5.1.2 GraphRuntime（图执行器）

| 类/函数 | 文件 | 作用 |
|---|---|---|
| `GraphRuntime` | `graph_runtime/runtime.py` | 主执行器。`run()` 按 DAG 顺序/分层执行任务图，`_run_sequential` 顺序执行，`_run_layered` 拓扑分层并行执行 |
| `resolve_templates()` / `_lookup()` | `graph_runtime/runtime.py` | 模板解析：`{node.field}` 引用前序节点输出 |
| `_topo_layers()` | `graph_runtime/runtime.py` | 拓扑排序分层（Kahn 算法） |
| `_try_replan()` | `graph_runtime/runtime.py` | 节点失败后用 LLM 重新规划替代方案 |
| `TemplateResolutionError` | 同上 | 模板解析异常 |

#### 5.1.3 Hearts（心脏 · 进程协调）

**不是"心跳调度器"**，而是聚合 facade，把"舱壁隔离 + 选主"组合在一起。

| 类/函数 | 文件 | 作用 |
|---|---|---|
| `Hearts` | `core/hearts/hearts.py` | 核心 facade。聚合协调器注册、状态维护、健康监控、异常处理 |
| `Coordinator` (Protocol) | `core/hearts/coordinator.py` | 选主后端协议：acquire/renew/release lease |
| `RedisCoordinator` / `EtcdCoordinator` | `core/hearts/redis_coordinator.py` / `etcd_coordinator.py` | 分布式选主后端 |
| `coordinator_health.py` | `core/hearts/coordinator_health.py` | 选主健康检查 |
| `GillHeartPump` | `core/hearts/gill_pump.py` | 后台泵，预压缩历史/预取记忆，避免主循环阻塞 |

仿生隐喻：章鱼 3 颗心脏——体循环（系统心）驱动内部主循环；鳃循环（鳃心）驱动外部 I/O 交互；两套循环物理隔离（Bulkhead）。

#### 5.1.4 Nerves（神经 · 事件总线 + 钩子 + 反射）

| 类/函数 | 文件 | 作用 |
|---|---|---|
| `bus.py` | `core/nerves/bus.py` | 事件总线，支持发布-订阅与事件路由，组件间通信基座 |
| `hooks.py` | `core/nerves/hooks.py` | 钩子机制，工具调用前/后插入自定义逻辑 |
| `ReflexRouter` | `core/nerves/reflex/reflex_router.py` | 反射弧路由器，处理事件流向与路由分发 |
| `actions.py` | `core/nerves/reflex/actions.py` | 反射动作模块，执行具体业务逻辑 |
| `tiers.py` / `gating.py` / `rules_loader.py` | `core/nerves/reflex/` | 反射分层、灰度、规则加载 |
| `auto_pr.py` / `git_track.py` / `test_runner.py` / `reply_drafter.py` | `core/nerves/reflex/` | 反射动作：自动 PR、git 追踪、测试运行、回复起草 |

`TypedEventBus` 是进程内同步发布-订阅（非分布式消息队列）。反射弧是绕过 LLM 的确定性快速响应通路。

---

### 5.2 runtime/execution · 执行层

#### Arms（腕足 · 进程内 Worker 池）

| 类/函数 | 文件 | 作用 |
|---|---|---|
| `Worker` | `execution/arms/base.py` | Arm 具体实现，持有 affinity 标签与 allowed_skills |
| `ArmPool` | `execution/arms/base.py` | Worker 池管理，按 affinity 分发与回收 |
| `make_code_arm` / `make_search_arm` / `make_file_arm` | `execution/arms/specialized.py` | 特定类型 Worker 工厂函数 |
| `ToolRegistry` | `execution/arms/tool_registry.py` | 工具注册与加载（`ToolProvider`/`ToolDefinition`） |
| `make_web_read_arm` / `make_shell_arm` / `make_general_arm` / `make_all_presets` | `execution/arms/presets.py` | 预定义 Worker 工厂与预设集合 |
| `ByteStreamBuffer` / `LineBuffer` | `execution/arms/output_buffer.py` | 工具输出缓冲（字节流/按行） |
| `PromiseGate` | `execution/arms/promise_gate.py` | 异步操作门控 |
| `ProcessTreeManager` | `execution/arms/process_tree.py` | 进程树管理与跟踪 |
| `EnterpriseDecisionCache` | `execution/arms/enterprise_cache.py` | 企业级决策缓存 |
| `LazyArmPool` / `LazyPool` | `execution/arms/lazy_loader.py` | 惰性加载 Worker 池 |
| `SafeRmProtector` | `execution/arms/safe_rm.py` | 安全删除保护 |
| `ShellStateManager` / `ShellEnvState` | `execution/arms/shell_state_manager.py` / `shell_state.py` | shell 会话状态管理 |

#### Tool Engine（工具执行引擎）

| 类/函数 | 文件 | 作用 |
|---|---|---|
| `ToolExecutor` | `execution/tool_engine/executor.py` | 核心执行引擎，`execute_step()` 执行单步工具调用 |
| `NormalizedToolCall` / `NormalizedToolResult` / `NormalizedToolLifecycleEvent` | `execution/tool_engine/tool_protocol.py` | 工具协议接口（规范化调用/结果/生命周期事件） |
| `GateBlock` / `gate_inner_dispatch()` | `execution/tool_engine/skill_gate.py` | 技能门控，meta-skill 内部派发共享的安全闸门 |
| `EffectStore` (Protocol) / `SQLiteEffectStore` | `execution/tool_engine/effect_store.py` | 工具执行效果存储（协议 + SQLite 实现） |
| `ToolTaxonomy` | `execution/tool_engine/tool_taxonomy.py` | 工具分类体系 |

#### Suckers（吸盘 · 技能加载器）

| 类/函数 | 文件 | 作用 |
|---|---|---|
| `Skill` / `SkillRegistry` | `execution/suckers/registry.py` | 技能模型与注册表 |
| `register_builtins()` / `register_all()` | `execution/suckers/builtins.py` | 内置技能注册（list_cwd/read_file/count_words/hash_text/file_stats） |
| `md_loader.py` | `execution/suckers/loader/md_loader.py` | Markdown 技能描述加载 |
| `install_from_archive()` / `safe_extract_zip()` | `execution/suckers/hub/installer.py` | 技能安装器（安全解压 + 安装） |
| `web_skills.py` / `browser_skills.py` / `code_edit_skills.py` / `memory_skills.py` / `crawler_skills.py` / `cron_skills.py` / `notebook_skills.py` / `lsp_skills.py` / `market_skills.py` / `ephemeral_*.py` | `execution/suckers/` | 各分类技能实现 |

#### Swarm / Parallel Agents / Loops / Subagents

| 类/函数 | 文件 | 作用 |
|---|---|---|
| `SwarmRuntime` | `execution/swarm/runtime.py` | 多智能体 swarm 运行时 |
| `SwarmPlan` / `SwarmEvent` / `AgentHandoff` / `SwarmResult` | `execution/swarm/models.py` | swarm 数据模型（计划/事件/交接/结果） |
| `ParallelAgentOrchestrator` | `execution/parallel_agents/orchestrator.py` | 并行 agent 编排器（`DispatchTaskInput`/`BatchPlan`/`BatchResult` 等模型） |
| `LoopController` | `execution/loops/controller.py` | Loop 控制器（拆分为 `_controller_*` mixin） |
| `LoopRunStore` / `LoopRunDispatcher` / `LoopVerifierRegistry` | `execution/loops/store.py` / `dispatcher.py` / `verifiers.py` | Loop 存储/调度/验证 |
| `call_subagent()` | `execution/subagents/bridge.py` | Subagent 桥接入口（运行时 slot 管理 + 派发） |
| `SubagentRegistry` / `SubagentDefinition` | `execution/subagents/registry.py` | 子代理注册表与定义 |
| `SubagentTurn` | `execution/subagents/memory.py` | 子代理记忆/迭代记录 |
| `Candidate` / `TournamentResult` | `execution/subagents/tournament.py` | 子代理竞赛 |
| `Agent` / `AgentRegistry` | `execution/agents/base.py` | Agent 定义与注册表 |
| `AgentGroup` / `AgentGroupRegistry` | `execution/agents/groups.py` | Agent 分组与注册表 |
| `AgentTemplate` | `execution/agents/loader.py` | Agent 模板加载 |

---

### 5.3 runtime/memory · 记忆与协作

#### Journal（事件日志）

| 类/函数 | 文件 | 作用 |
|---|---|---|
| `Journal` | `memory/journal/_journal_base.py` | 事件日志抽象基类 |
| `InMemoryJournal` / `JSONLJournal` | `memory/journal/journal.py` | 内存/JSONL 两种具体实现 |
| `JournalEvent` + 20+ 子类（`StepEvent`/`TrajectoryEvent`/`ImmuneEvent`/`BudgetEvent`/`TaskStartedEvent`/`ReactCheckpointEvent`/`TokenUsageEvent`/`FileOpEvent` 等） | `memory/journal/_journal_models.py` | 事件模型族 |
| `TaskProgressTracker` / `TaskProgressSnapshot` | `memory/journal/progress_tracker.py` / `progress.py` | 任务进展跟踪 |
| `ResumeInfo` / `CompletedNode` | `memory/journal/resume.py` | 检查点恢复 |
| `JournalIndex` | `memory/journal/sqlite_index.py` | SQLite 快速日志查询索引 |

#### Cowork（多智能体协作状态机）

| 类/函数 | 文件 | 作用 |
|---|---|---|
| `GroupState` / `Member` / `ContextGrant` | `memory/cowork/group.py` | 协作组状态、成员与上下文授予 |
| `CoworkRuntime` | `memory/cowork/runtime.py` | 协作状态机顶层入口 |
| `CollaborationSession` | `memory/cowork/session.py` | 协作会话 |
| `CoworkStore` / `GroupStore` / `CollaborationStore` | `memory/cowork/store.py` / `group_store.py` / `collaboration_store.py` | 协作/分组/协作存储 |
| `PresenceStore` / `MemberPresence` | `memory/cowork/presence.py` | 在线状态 |
| `Task` / `Plan` / `Assignment` | `memory/cowork/models.py` | 协作任务/计划/分配模型 |
| `TurnPlan` / `RoomMessageStore` / `CatchUp` / `AsyncWorkRunner` | `memory/cowork/` | 轮次规划/房间消息/追平/异步工作 |

#### Hemolymph（血淋巴 · 上下文组合器）

| 类/函数 | 文件 | 作用 |
|---|---|---|
| `ContextComposer` | `memory/hemolymph/composer.py` | 组装和过滤上下文（`ContextEngine`/`TruncationContextEngine` 抽象引擎） |
| `embed_model()` / `embed_texts()` / `get_encoder()` | `memory/hemolymph/embedding_backend.py` | 嵌入模型接口（远程/本地封装，函数式） |
| `retrieve_repo_context()` / `build_codebase_context()` | `memory/hemolymph/repo_context.py` | 项目语义信息检索（BM25/RRF） |
| `retrieve_code_context()` / `reciprocal_rank_fusion()` | `memory/hemolymph/code_index.py` | 代码索引快速检索 |
| `rank()` | `memory/hemolymph/semantic_rank.py` | 语义排序 |

#### Knowledge Graph（知识图谱）

| 类/函数 | 文件 | 作用 |
|---|---|---|
| `KnowledgeGraph` | `memory/knowledge_graph/kg.py` | 抽象基类 |
| `SqliteKnowledgeGraph` | `memory/knowledge_graph/sqlite_kg.py` | SQLite 后端 |
| `KuzuKnowledgeGraph` | `memory/knowledge_graph/kuzu_kg.py` | Kuzu 图数据库后端 |
| `Triple` | `memory/knowledge_graph/triple.py` | 三元组模型 |

#### Learning / Threads / 其他

| 模块 | 路径 | 作用 |
|---|---|---|
| Learning | `memory/learning/` | `ExperienceLedger`/`ReviewQueue`/`TurnScore`/`PromotionApplier`/`HoldoutEntry`/`GatePolicy` |
| Threads | `memory/threads/` | `ThreadStateStore`/`EventLog`/`SessionIndex`/`LlmSummariserConfig`/`CompactionPolicy` |
| Skills Lib | `memory/skills_lib/` | `SkillCurator`/`MetaSkill`/`MetaStep`/`MetaEdge`/`AmbientScheduler` |
| Runtime State | `memory/runtime_state/` | `Blackboard`/`SqliteBlackboard`/`MemoryHub`/`SessionHotCache` |
| Users | `memory/users/` | `MentionHistoryStore`/`MentionStat` + 函数式 `profile.py`/`user_store.py`/`distill_user_memory()` |
| Diagnostics | `memory/diagnostics/` | 错误分类/追踪存储/wiki 编译 |

---

### 5.4 runtime/safety · 安全与治理

#### 信任引擎（Immunity / auth）

| 类/函数 | 文件 | 作用 |
|---|---|---|
| `TrustEngine` | `safety/auth/trust_engine.py` | 三层信任检查 |
| `AttackMemory` / `AttackPattern` | `safety/auth/attack_memory.py` | 攻击模式记忆 |
| `AdaptiveImmunity` | `safety/auth/adaptive_immunity.py` | 自适应行为异常评分 |
| `PathVerdict` / `FileWriteVerdict` / `URLVerdict` | `safety/auth/path_guard.py` / `file_safety.py` / `url_guard.py` | 路径/文件/URL 安全判定结果 |
| `Identity` / `IdentityStore` | `safety/auth/identity.py` | 身份与身份存储 |
| `ToolCallGuardrailController` / `GuardrailDecision` / `GuardrailConfig` | `safety/auth/tool_guardrails.py` | 工具护栏 |

#### Constitution Gate（validation）

| Pass | 文件 | 作用 |
|---|---|---|
| Pass 1 — Rule | `safety/validation/rules.py` | 正则/关键词扫描 PII、密钥、API key |
| Pass 2 — Rewrite | `safety/validation/gate.py` | 自动脱敏 |
| Pass 3 — LLM-Judge | `safety/validation/llm_judge.py` | 第二次 LLM 语义检查（可选） |
| Pass 4 — Human-Gate | `safety/approval/approval_gate.py` | 高风险动作审批队列 |
| `prompt_injection.py` / `soul.py` / `trust_signal.py` / `profiles.py` | `safety/validation/` | prompt 注入检测/灵魂/信任信号/画像 |

#### 安全钩子

| 类/函数 | 文件 | 作用 |
|---|---|---|
| `HookEvent` / `PreToolUseEvent` / `PostToolUseEvent` | `safety/hooks/events.py` | 钩子事件基类 |
| `runner.py` | `safety/hooks/runner.py` | 分发助手，按注册顺序遍历 handler |
| `registry.py` / `tool_edge_hooks.py` | `safety/hooks/` | 钩子注册 / 工具边缘钩子 |
| `scrub_credential_env()` | `safety/env_scrub.py` | 为不受限子进程清理环境变量中的凭据 |

#### 其他安全子模块

| 模块 | 路径 | 作用 |
|---|---|---|
| Budget Breaker | `safety/budget_breaker/` | 三态预算熔断器（Green/Yellow/Red） |
| Evolution | `safety/evolution/` | 适应度评估/漂移监控/自动验证/金丝雀（`fitness.py`/`drift_monitor.py`/`auto_verifier.py`/`canary.py`） |
| Experiments | `safety/experiments/` | A/B 实验 + Prompt 变体（`prompt_evolver.py`/`prompt_mutator.py`/`pareto.py`/`auto_retire.py`） |
| Recovery | `safety/recovery/` | 技能锻造 + 基因组注册表 + 原生回放 + 优化器（`skill_forge.py`/`genome_registry.py`/`native_replay.py`/`optimizer_backends.py`） |
| Chromatophores | `safety/chromatophores/` | 信号总线 + Boids 仲裁（`signal_bus.py`/`boids.py`） |
| Approval | `safety/approval/` | 审批门/策略/取消/设备锁 |
| Audit | `safety/audit/` | 审计链/信任网关/webhook 校验 |
| Sandboxing | `safety/sandboxing/` | 沙箱：`SandboxRunner`/`SandboxPolicy`/`SandboxResult`/`Backend`（`sandbox.py`）+ `ContainerSandbox`（`container_sandbox.py`） |
| Invariants | `safety/invariants/` | 不变量强制 |

---

### 5.5 runtime/sensing · 输入与模型路由

| 模块 | 路径 | 作用 |
|---|---|---|
| Gateway | `sensing/gateway/` | API 网关 + Realtime + 大量 router（`_config_*.py`/`_channels_*.py`/`_team_*.py`/`_meta_*.py`）+ agent market 资产（`agent_market_sources/`） |
| Local Backend | `sensing/server/local.py` | 本机命令执行 |
| SSH Backend | `sensing/server/ssh.py` | SSH 远程命令执行 |
| K8s Backend | `sensing/server/k8s.py` | 通过 `kubectl run` 在 K8s 起临时 Pod 执行 |

K8s/SSH 后端均继承 `LocalBackend`/`Sandbox`，统一 `run_command` 返回结构与输出上限。

---

### 5.6 runtime/platform · 平台基础设施

#### 原子 I/O

| 类/函数 | 文件 | 作用 |
|---|---|---|
| `atomic_write_bytes/text/json()` | `platform/io/atomic.py` | 原子写入：写临时文件 → fsync → 滚动 .bak → os.replace |
| `read_json_with_backup()` | 同上 | 读 JSON，主文件损坏自动回退 .bak |
| `LeaseStore` | `platform/io/lease.py` | SQLite 持久化文件租约（带 TTL + 后台清理线程） |

这是整个代码库的持久化地基，被大量文件直接导入。

#### 进程/会话/事件总线（process）

| 类/函数 | 文件 | 作用 |
|---|---|---|
| `Session` / `current_session()` / `session_scope()` | `platform/process/session.py` | 运行时上下文（actor/agent/conversation） |
| `EventBus` | `platform/process/eventbus.py` | 进程级事件总线单例，处理领域事件 |
| `event_bridge.py` | `platform/process/event_bridge.py` | 信号/类型化事件转发到 EventBus |
| `stream_run()` | `platform/process/streaming.py` | 子进程流式执行 + 输出捕获 |
| `TaskSupervisor` | `platform/process/task_supervisor.py` | 后台任务监督（跟踪/生命周期/重试） |
| `StateStore` / `StateBackend` | `platform/process/state.py` | 应用状态存储与后端（Memory/File/SQLite） |
| `distributed_lock.py` / `keyed_lock.py` / `bounded_set.py` | `platform/process/` | 分布式锁/键锁/LRU 有界集合 |
| `ServiceProvider` | `platform/process/service_provider.py` | 服务发现与注入（signal_bus/event_bus 等） |
| `paths.py` / `scope.py` / `tree.py` | `platform/process/` | 路径/作用域/进程树清理 |

#### LLM 数据类型（models）

| 类/函数 | 文件 | 作用 |
|---|---|---|
| `llm.py` | `platform/models/llm.py` | 核心 LLM 数据类型与提示模板 |
| `context.py` / `pipeline.py` / `primitives.py` / `execution.py` / `governance.py` / `rescue_policy.py` / `custom_model_flags.py` | `platform/models/` | 上下文/管线/元语/执行/治理/救援策略/模型标志 |

这些类型下沉到 platform 层，避免 cerebrum/safety/memory 向上依赖 sensing。

#### UI 装配（platform/ui）

| 类/函数 | 文件 | 作用 |
|---|---|---|
| `create_app()` | `platform/ui/app.py` | 主装配函数（~2600 行）：构建 FastAPI，挂载全部 router + 调度器 + 扩展点 |
| `AppState` | `platform/ui/state.py` | 共享 UI 状态：journal/registry/trace_store/task_supervisor |
| `create_health_router()` | `platform/ui/health_router.py` | `/api/health`、`/api/status` 等 |
| `create_browser_router()` | `platform/ui/browser_router.py` | 浏览器会话/标签/中继 |
| `thread_routes.py` | `platform/ui/thread_routes.py` | 线程状态路由 |
| `permissions_router.py` | `platform/ui/permissions_router.py` | 工具审批规则 |
| `cookbook_router.py` | `platform/ui/cookbook_router.py` | 本地模型推荐/通过 ollama 拉取 |
| `searxng_router.py` | `platform/ui/searxng_router.py` | SearXNG 私有搜索后端 |
| `reflex_admin_router.py` | `platform/ui/reflex_admin_router.py` | 反射管理面板 + GEPA 应用 |
| `pages.py` / `_chat_page_html.py` | `platform/ui/` | 零依赖内联 HTML（无 Vite 构建时的回退界面） |
| `load_app_extensions()` / `load_skill_extensions()` | `platform/extensions.py` | 应用/技能扩展点 |

#### 可观测性

| 模块 | 路径 | 作用 |
|---|---|---|
| `Redactor` | `platform/observability/redactor.py` | PII/密钥脱敏 |
| `HealthRegistry` | `platform/observability/health.py` | 健康探针框架 |
| `MetricsRegistry` | `platform/observability/metrics.py` | 零依赖 Prometheus 兼容指标 |
| `Doctor` | `platform/observability/doctor.py` | 环境诊断 |

#### i18n / 插件 / 迁移 / 生命周期

| 模块 | 路径 | 作用 |
|---|---|---|
| i18n | `platform/i18n/` | 支持 en/zh-CN/ja/ko 四语言 |
| Plugins | `platform/plugins/` | 插件注册表/加载器/技能市场 |
| Migration | `platform/migration/` | 数据迁移（claude/codex/qoder 适配器） |
| Lifecycle | `platform/lifecycle/` | 备份/工厂重置/设置向导/数据迁移 |
| LLM Infra | `platform/llm_infra/` | `llm_caller.py`/`llm_cache.py`/`budget_tracker.py` |
| Budget | `platform/budget/` | 迭代预算/限流/定价 |

---

### 5.7 runtime/protocol · 线协议

JSON-RPC 2.0 信封 + 方法名常量 + Item 状态模型，定义 realtime 通道两端契约。

| 类/函数 | 文件 | 作用 |
|---|---|---|
| `JsonRpcRequest` / `JsonRpcResponse` / `Notification` | `protocol/envelope.py` | JSON-RPC 2.0 三种消息类型 |
| `encode_message()` / `decode_message()` | `protocol/envelope.py` | 单行 JSON 编解码 |
| `ClientMethod` / `ServerMethod` | `protocol/events.py` | 客户端/服务端方法名常量 |
| `Item`（判别联合，`_ItemBase` + 20+ 子类：`UserMessageItem`/`AgentMessageItem`/`ReasoningItem`/`PlanItem`/`TodoListItem`/`CommandExecutionItem`/`FileChangeItem`/`McpToolCallItem`/`SubagentItem`/`ApprovalItem`/`VerificationItem`/`ArtifactItem`/`ErrorItem` 等） | `protocol/items.py` | 多类型 Item（由 `ItemType`/`ItemStatus`/`ItemMarker` 枚举区分） |
| `Turn` / `TurnParams` / `TurnStatus` | `protocol/items.py` | Turn 状态模型 |
| `diff_parser.py` | `protocol/diff_parser.py` | diff 解析 |
| `text_limits.py` | `protocol/text_limits.py` | 文本长度限制 |

一个 Turn 是有序 Item 列表；每个可观察 agent 输出都是一个 Item，生命周期统一：`item/started` → 0..n delta → `item/completed`。

---

### 5.8 runtime/research · 深度研究

Perplexity 风格的"提问→搜索→抓取→重排→引用合成"管线。

| 类/函数 | 文件 | 作用 |
|---|---|---|
| `research_answer()` / `research_loop()` | `research/pipeline.py` | 单轮/多轮研究管线 |
| `ResearchAnswer` | `research/pipeline.py` | 管线产物 |
| `build_citation_context()` / `resolve_citations()` | `research/citations.py` | 引用编号渲染 / `[n]` 标记解析 |
| `rerank()` | `research/rerank.py` | 重排（BM25 默认 / Cohere 可选） |
| `ResearchPrefetcher` | `research/prefetch.py` | 深度研究预取 |
| `_deep_research_models.py` / `_deep_research_helpers.py` | `research/` | 深度研究模型与辅助 |

所有阶段均有降级路径（LLM 失败回落关键词检查、cohere 失败回落 BM25、抓取失败保留 snippet）。

---

### 5.9 runtime/projectos · 项目引擎

基于"项目→里程碑→任务 DAG"的三层全局状态，由里程碑（而非循环本身）作为停止条件。

| 类/函数 | 文件 | 作用 |
|---|---|---|
| `ProjectEngine` | `projectos/engine.py` | 核心引擎。`plan()` 把目标转为带里程碑的 Project；`tick()` 循环单步；`run()` 连续 tick |
| `Project` / `Milestone` / `Task` | `projectos/model.py` | 三层数据模型（DAG via depends_on） |
| `ProjectStore` | `projectos/store.py` | SQLite 持久化（终态不可变约束保证幂等） |
| `create_llm_hooks(router)` | `projectos/llm_hooks.py` | 组装智能钩子（LLM 生成里程碑/任务 + subagent 执行 + QA 闸门） |
| `project_process_timeline()` | `projectos/timeline.py` | 进程时间线读模型 |
| `cowork_bridge.py` | `projectos/cowork_bridge.py` | 与协作状态机桥接 |

引擎本身是纯编排，智能通过注入的 LLM 钩子实现：`MS 检查 → 任务分配 → 智能体执行 → QA 评估 → 里程碑闸门`。

---

### 5.10 runtime/tentacle · 跨设备触手

| 类/函数 | 文件 | 作用 |
|---|---|---|
| `Tentacle` (Protocol) / `TentacleType` / `TentacleStatus` | `tentacle/base.py` | 触手协议与类型枚举 |
| `Heartbeat` / `ToolCall` / `ToolResult` | `tentacle/base.py` | 心跳/工具调用/结果数据类 |
| `TentaclePool` | `tentacle/pool.py` | 触手池管理，`select_for_affinity` LEAST_USED 策略选设备 |
| `DeviceLock` | `tentacle/pool.py` | 设备锁 |
| `broadcast()`（模块级，依赖 `run_device_task`） | `tentacle/fleet.py` | 群控：一人驱动 N 台，`asyncio.Semaphore` 反压 |
| `DesktopDevice` | `tentacle/desktop.py` | 把本地桌面包装成触手 |
| `create_tentacle_router()` | `tentacle/dashboard.py` | FastAPI REST/WS API |
| `ios/device.py` | `tentacle/ios/device.py` | iOS 设备管理 |

---

### 5.11 runtime/workspace · 工作区

把"工作区"定义为一等实体：挂载点 + 所有者 + 成员列表。

| 类/函数 | 文件 | 作用 |
|---|---|---|
| `Workspace` / `WorkspaceMember` | `workspace/model.py` | 数据类（mount_type: local/smb/nfs/webdav/sftp/s3） |
| `WorkspaceStore` | `workspace/store.py` | SQLite 持久化 |
| `encrypt_options()` / `decrypt_options()` | `workspace/crypto.py` | 敏感字段按字段 Fernet 加密 |

---

### 5.12 runtime/adapters · 通道与集成

| 模块 | 路径 | 作用 |
|---|---|---|
| Channels | `adapters/channels/` | 20+ 渠道适配器（`base.py`/`manager.py`/`store.py` + Discord/Slack/WeChat/Telegram/Email/Feishu/DingTalk/...） |
| MCP Client | `adapters/mcp_client/` | MCP 协议客户端（`client.py`/`bridge.py`/`oauth.py`/`trust.py`/`types.py`） |
| Scheduler | `adapters/scheduler/` | Cron 调度器（`cron.py`/`runner.py`） |
| Integrations | `adapters/integrations/` | 第三方集成（oct 账号网关） |
| Instrumentation | `adapters/instrumentation/` | OpenTelemetry 追踪 |
| Web Auth | `adapters/web_auth.py` | Web 认证 |

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

前端核心目录 `frontend/src/core/` 按领域组织 API 层。`src/core/README.md` 提供了前端 `@/core/<domain>` 到后端 `runtime/<path>` 的映射表（agents/arena/auth/cowork/mcp/memory/models/oct/skills/tasks/teams 等）。

前端页面位于 `frontend/src/app/`（login/about/workspace 等），workspace 下按能力分页（agents/browser/channels/computer/evolution/knowledge/mcp/mobile/observability/realtime/reflex/replay/skills/storage/team/workflows）。组件位于 `frontend/src/components/`（ui/workspace/messages/ai-elements 等）。

**映射权威来源**：`src/core/README.md` 的 `@/core/<domain>` → `runtime/<path>` 映射表与磁盘结构一致，作为前端 API 层的权威映射。另有一份由 `scripts/gen_wiki.py` 从磁盘结构 + AST 类定义自动生成的 wiki（`docs/auto/`），每次代码改动后运行 `python scripts/gen_wiki.py` 即可保持最新，CI 门禁 `tests/test_auto_docs_fresh.py` 守护其不漂移。

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
| `extract` | trafilatura | 网页正文提取 |
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
| `mantle-ssh` | paramiko | SSH 执行 |
| `swebench` | datasets, swebench | SWE-bench 评估 |
| `docs` | mkdocs | 文档 |
| `all` | 上述全部 | 完整能力 |

### 6.2 模块间依赖方向

```
platform  ← 最底层基座（io/models/observability/i18n/config/process）
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

React 19 + Vite 7 生态，详见 `frontend/package.json`。主要：`@tanstack/react-query`、CodeMirror 6 全家桶、`@xyflow/react`、xterm.js、Radix UI、TailwindCSS 4、Three.js、mermaid、shiki。

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
| `python -m runtime status` | 查看本机能力 |
| `python -m runtime bugfix-demo` | 跑确定性 bugfix demo（不依赖外部 LLM） |
| `python -m runtime serve --port 8000` | 启动 FastAPI Web UI 服务 |
| `python -m runtime ui --port 8000` | 启动 UI（同 serve 的简写） |
| `python -m runtime quickstart --non-interactive --serve` | 引导配置并启动服务 |
| `python -m runtime run "目标"` | 无头模式跑一个目标 |
| `python -m runtime loop "目标"` | 循环模式 |
| `python -m runtime reflect` | 反思/学习 |
| `python -m runtime doctor` | 环境诊断 |
| `python -m runtime project` | 项目引擎 |
| `python -m runtime kg` | 知识图谱 |
| `python -m runtime backup` / `restore` / `export` | 数据备份/恢复/导出 |
| `python -m runtime wiki` | 从 journal 生成 wiki |

CLI 子命令分布在：`cli_core.py`（status/build_stack）、`cli_serve.py`（serve）、`cli_run.py`（run/goal/bench/resume）、`cli_reflect.py`（reflect/loop/optimize/intel）、`cli_code.py`、`cli_mcp.py`、`cli_project.py`、`cli_migrate.py`、`_cli_commands.py`（各 run_* 处理器）。

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

关键配置段：`preset`（预设模板）、`planner`（规划器）、`evolve`（进化）、`budget`（预算硬顶）、`immunity`（三层信任模型）、`intel_sources`（情报源）、`mcp_servers`（MCP 外部服务器）、`safety`（安全守卫）、`oct`（oct 账号网关）、`local_auth`（本地认证）。

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

测试文件位于 `tests/`（数百个文件），覆盖所有核心子系统。`tests/conftest.py` 提供共享 fixture。

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
| `runtime/cli.py` | CLI 主模块（re-export + 分发） |
| `runtime/_cli_commands.py` | 各 run_* 命令处理器 |
| `runtime/_cli_parser.py` | 参数解析器 |
| `runtime/tour.py` | 引导流程 |
| `runtime/platform/ui/app.py` | FastAPI 主装配（~2600 行） |
| `runtime/platform/io/atomic.py` | 原子写入地基 |
| `runtime/platform/models/llm.py` | LLM 数据类型基座 |
| `runtime/core/cerebrum/react_loop.py` | ReAct 中央循环 |
| `runtime/core/graph_runtime/runtime.py` | 图执行器 |
| `runtime/core/hearts/hearts.py` | 心脏 facade |
| `runtime/core/nerves/bus.py` | 事件总线 |
| `runtime/core/nerves/reflex/reflex_router.py` | 反射路由器 |
| `runtime/execution/arms/base.py` | Arm Worker 与 ArmPool |
| `runtime/execution/tool_engine/executor.py` | 工具执行引擎 |
| `runtime/tentacle/base.py` | Tentacle 协议 |
| `runtime/memory/cowork/group.py` | 协作组事件溯源 |
| `runtime/memory/journal/journal.py` | 事件日志 |
| `runtime/safety/hooks/runner.py` | 安全钩子分发 |
| `runtime/safety/env_scrub.py` | 凭据脱敏 |
| `runtime/protocol/envelope.py` | JSON-RPC 2.0 信封 |
| `runtime/protocol/items.py` | Item 状态模型 |
| `runtime/research/pipeline.py` | 研究管线 |
| `runtime/projectos/engine.py` | 项目引擎 |
| `runtime/workspace/store.py` | 工作区持久化 |
| `runtime/adapters/channels/manager.py` | 渠道管理器 |
| `pyproject.toml` | Python 依赖与项目元数据 |
| `config.example.yaml` | 配置示例 |
| `Dockerfile` | 三阶段构建 |
| `docker-compose.yml` | 最小部署栈 |
| `Makefile` | 常用命令快捷方式 |
| `frontend/src/core/README.md` | 前端→后端模块映射 |