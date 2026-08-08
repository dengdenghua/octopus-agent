# Octopus-Agent 核心架构分析

> 全面分析 Agent 运行框架、多工作模式、任务生命周期与状态机

生成时间: 2026-08-08

---

## 目录

1. [系统概览](#系统概览)
2. [Agent 运行框架](#agent-运行框架)
3. [多工作模式](#多工作模式)
4. [任务生命周期](#任务生命周期)
5. [状态机与状态管理](#状态机与状态管理)
6. [核心流程图](#核心流程图)

---

## 系统概览

### 架构哲学

Octopus-Agent 采用**仿生架构设计**，以章鱼（Octopus）的生理结构为隐喻：
- **分布式神经系统**：章鱼约 2/3 的神经元分布在八条腕足中，每条腕足可独立决策
- **中枢与反射双通路**：既有中枢大脑（Cerebrum）规划，也有脊髓（Spinal Cord）反射
- **多臂并行执行**：多个 Arm 可同时执行不同任务

### 关键设计原则

1. **反射优先（Reflex First）**
   - 80% 的简单请求不需要 LLM，通过反射层直接处理
   - 降低延迟和成本

2. **规划即地图（Plan as Map）**
   - LLM 只用于一次性规划生成完整的任务图（DAG）
   - 执行阶段纯粹消费 DAG，无需重复调用 LLM

3. **失败即学习（Failure as Learning）**
   - 失败的教训自动沉淀为规则，下次规划时作为先验知识

---

## Agent 运行框架

### 核心组件映射

基于生物隐喻的模块组织（`runtime/` 目录结构）：

| 生物器官 | 功能职责 | 实现路径 |
|---------|---------|---------|
| **Cerebrum（大脑）** | 中枢规划，任务分解 | `runtime/core/cerebrum/` |
| **Spinal Cord（脊髓）** | 反射层，快速响应 | `runtime/core/nerves/reflex/` |
| **Ganglia（神经节）** | TaskGraph 运行时 | `runtime/core/graph_runtime/` |
| **Beak（喙）** | 工具执行引擎 | `runtime/execution/tool_engine/` |
| **Arms（腕足）** | 独立执行单元 | `runtime/execution/arms/` |
| **Hemolymph（血淋巴）** | 共享状态存储 | `runtime/memory/hemolymph/` |
| **Journal（日志）** | 事件总线 | `runtime/memory/journal/` |
| **Siphon（虹吸管）** | 实时网关 | `runtime/sensing/gateway/` |
| **Hearts（心脏）** | 分布式协调 | `runtime/core/hearts/` |

### 双通路决策模型

```
用户请求
   │
   ├─→ Spinal Cord 反射层（快速路径）
   │   ├─ Regex/Keyword 匹配 → 直接返回
   │   ├─ Cache 命中 → 直接返回
   │   ├─ Rule Engine 规则引擎 → 直接返回
   │   └─ 未命中 ↓
   │
   └─→ Cerebrum 规划层（慢速路径）
       └─ LLM 规划 → TaskGraph → 执行
```

**关键优势**：
- 反射层处理成本接近零（无 LLM 调用）
- 命中率高的场景显著降低响应延迟
- Regeneration 组件持续学习，将成熟模式下沉为反射规则

---

## 多工作模式

### WorkMode 统一模型

所有模式信号通过 `runtime/core/cerebrum/work_mode.py` 中的 `WorkMode` 统一解析：

```python
@dataclass(frozen=True)
class WorkMode:
    # 工作空间
    project_workspace: str | None      # 绑定的项目目录
    personal_workspace: str | None     # 个人工作区/cwd
    effective_workspace: str | None    # 有效工作区（优先级）
    
    # 工作类型信号
    mode: str                          # 主模式
    capability_mode: str               # 能力模式
    agent_mode: str                    # 代理模式 (builder/coder/architect)
    personal_mode: str                 # 个人模式 (build/research/general)
    codex_mode: str                    # Codex 模式
    completion_policy: str             # 完成策略
    
    # 派生标志
    is_code: bool                      # 是否为代码模式
    is_goal: bool                      # 是否为目标模式
    is_swarm: bool                     # 是否为 Swarm 模式
```

### 主要工作模式

#### 1. **经典 ReAct 模式**
- 传统的"想一步→做一步→观察"循环
- 每轮都调用 LLM
- 串行执行

#### 2. **Octopus 模式（默认）**
- 一次性规划生成 DAG
- 并行执行多个节点
- 失败自动学习规则

#### 3. **代码模式（Code Mode）**
触发条件：
- `mode == "code"`
- `capability_mode` 存在
- `effective_workspace` 存在

特性：
- 启用文件操作工具
- 自动验证和测试
- 支持 git 集成

#### 4. **目标模式（Goal Mode）**
触发条件：
- `goal_mode == True`
- `codex_mode == "goal"`
- `completion_policy == "goal"`

特性：
- 面向长期目标
- 支持检查点和恢复
- 自动迭代延长

#### 5. **Swarm 模式**
触发条件：
- `mode in {"swarm", "agent_swarm"}`
- `capability_mode in SWARM_ALIASES`

特性：
- 多 Agent 协同
- 网状通信
- 任务自动分配

#### 6. **研究模式（Research Mode）**
特性：
- Web 搜索集成
- 长文档分析
- 知识图谱构建

---

## 任务生命周期

### 完整生命周期状态

```python
RunState = Literal[
    "pending",      # 等待执行
    "running",      # 执行中
    "completed",    # 成功完成
    "failed",       # 执行失败
    "cancelled",    # 已取消
    "partial"       # 部分完成
]
```

### 任务执行流程

#### Phase 1: 意图解析（Intent Parsing）

```
原始输入 → ParsedIntent
├─ intent_type: query/task/event/command/plan/...
├─ normalized_goal: 标准化目标
├─ user_context: 用户上下文
├─ modalities: 模态列表 [text/file/image/audio]
└─ privacy: 隐私级别 (public/internal/confidential)
```

#### Phase 2: 路由决策（Routing）

```python
class RouteDecision:
    path: RoutePath              # "reflex" 或 "deliberative"
    reflex_rule_id: str | None   # 命中的反射规则ID
    reflex_confidence: float     # 反射置信度
    reason: str                  # 路由原因
```

**决策逻辑**：
```
if SpinalCord.try_reflex(intent) → hit:
    return reflex_response  # 快速路径
else:
    Cerebrum.plan(intent)   # 慢速路径
```

#### Phase 3: 规划生成（Planning）

**Cerebrum 规划器**生成 `TaskGraph`：

```python
class TaskGraph:
    task_id: TaskId
    nodes: list[TaskNode]        # 任务节点（DAG）
    edges: list[WorkflowEdge]    # 依赖关系
    budget: BudgetSpec           # 预算限制
    strategy: str                # 执行策略
```

**TaskNode 定义**：
```python
class TaskNode:
    node_id: str
    kind: NodeKind              # sucker/subgraph/validator/branch/...
    skill_ref: SkillId          # 技能引用
    args_template: dict         # 参数模板（支持 {nodeX.output} 引用）
    timeout_ms: int
    failure_retry: int
```

**关键特性**：
- DAG 结构支持并行执行
- 模板系统支持节点间数据传递
- 自动循环检测

#### Phase 4: 执行调度（Execution）

**GraphRuntime** 消费 TaskGraph：

```
1. 拓扑排序（Topological Sort）
   └─ 计算执行层级（layers）

2. 并行执行每一层
   ├─ 解析参数模板 {node.output}
   ├─ 调用 ToolExecutor
   └─ 收集结果

3. 结果传递
   └─ 将 node 输出注入下游节点参数
```

**执行路径**：
```
TaskNode → ToolExecutor → Beak (工具路由)
                           ├─ Immunity (信任检查)
                           ├─ Budget (预算检查)
                           └─ Mantle (沙箱执行)
```

#### Phase 5: 观察与反馈（Observation）

每个步骤生成 `Step` 记录：

```python
class Step:
    step_id: int
    node_id: str
    action: ToolCall              # 执行的动作
    result: ExecutionResult       # 执行结果
    immune_verdict: str           # 信任判决
    args_template: dict           # 原始模板（用于 Skill 锻造）
```

**ExecutionResult 状态**：
```python
ExecutionStatus = Literal[
    "success",              # 成功
    "failed",               # 失败
    "timeout",              # 超时
    "sandbox_violation",    # 沙箱违规
    "circuit_broken",       # 熔断
    "immune_reject"         # 信任拒绝
]
```

#### Phase 6: 终止与总结（Termination）

```
完成条件判断：
├─ 所有节点成功 → completed
├─ 达到迭代上限 → max_iter
├─ 预算耗尽 → budget_exceeded
├─ 用户中止 → user_cancelled
└─ 严重错误 → critical_failure

生成 Trajectory：
├─ 所有 Steps
├─ 成本统计
├─ 成功率
└─ 用户评分（可选）
```

### ReAct 循环状态机

对于使用 ReAct 模式的任务，核心循环在 `runtime/core/cerebrum/react_loop.py`：

```
[初始化] → [Phase 6a: 提示组装]
              ↓
          [Phase 6b: 模型流式调用]
              ↓
          [Phase 6c: 解析与守卫]
              ↓
          [Phase 6d: 分发与观察]
              ↓
          [Phase 6e: 终止守卫]
              ↓
          [Phase 6f: 检查点评估]
              ↓
          [Phase 6g: 清理]
              ↓
          判断是否继续？
          ├─ 是 → 回到 Phase 6b（下一轮）
          └─ 否 → [终止]
```

**循环控制信号**：
```python
class _LoopControl(enum.Enum):
    CONTINUE = "continue"             # 继续下一阶段
    NEXT_ITERATION = "next_iteration" # 跳到下一轮
    BREAK = "break"                   # 退出循环
    RETURN_NONE = "return_none"       # 中止 Turn
```

---

## 状态机与状态管理

### ReAct 循环状态（LoopState）

`runtime/core/cerebrum/react_loop_state.py` 定义了 ReAct 主循环的共享状态：

```python
@dataclass
class _LoopState:
    # ── 配置层（Turn 级别，只读）──
    stack: Any                              # 执行栈
    goal: str                               # 目标
    executor: Any                           # 工具执行器
    react_task_id: Any                      # 任务 ID
    effective_wp: Any                       # 有效工作区
    intent: Any                             # 解析后的意图
    agent: Any                              # Agent 实例
    thread_id: str                          # 线程 ID
    
    # ── 模式标志（Turn 级别）──
    is_code_mode: bool                      # 代码模式
    is_goal_mode: bool                      # 目标模式
    browser_operation_mode: bool            # 浏览器操作模式
    todo_protocol_required: bool            # 需要 TODO 协议
    read_only_turn: bool                    # 只读模式
    no_tool_turn: bool                      # 无工具模式
    
    # ── 对话状态（共享引用，原地修改）──
    steps: list                             # 步骤列表
    executed_beak_steps: list               # 已执行的工具步骤
    messages: list                          # 消息历史
    working_set: dict                       # 工作集
    final_answer_segments: list             # 最终答案片段
    
    # ── 迭代状态（每轮同步）──
    tools_active: bool                      # 工具是否激活
    planning_mode: bool                     # 规划模式
    enable_tools: bool                      # 启用工具
    effective_model: str                    # 有效模型
    current_phase: str                      # 当前阶段
    native_mode: bool                       # 原生模式
    model_failovers: int                    # 模型故障转移次数
    consecutive_format_violations: int      # 连续格式违规
    consecutive_llm_errors: int             # 连续 LLM 错误
    
    # ── 终止累加器（同步进出）──
    final_answer: str | None                # 最终答案
    terminated_reason: str                  # 终止原因
    final_answer_emitted: bool              # 是否已发出最终答案
    
    # ── 解析输出（仅同步输出）──
    resp: Any                               # LLM 响应
    step: ReActStep | None                  # 当前步骤
    maybe_final: str | None                 # 可能的最终答案
```

### 任务运行状态汇总（RunStateSummary）

`runtime/core/cerebrum/run_state.py` 提供状态聚合：

```python
@dataclass(frozen=True)
class RunStateSummary:
    state: RunState        # 总体状态
    total: int             # 总数
    completed: int         # 完成数
    failed: int            # 失败数
    cancelled: int         # 取消数
    running: int           # 运行中
    unknown: int           # 未知状态
    terminal: bool         # 是否终止
    reasons: tuple[str]    # 原因列表
```

**状态收敛逻辑**：
```python
def converge_run_state(statuses: list[str]) -> RunStateSummary:
    if running or unknown:
        state = "running"
    elif completed == total:
        state = "completed"
    elif cancelled == total:
        state = "cancelled"
    elif failed == total:
        state = "failed"
    else:
        state = "partial"  # 混合状态
```

### 工具执行状态

每个工具调用产生 `ExecutionResult`：

```python
class ExecutionResult:
    call_id: UUID
    status: ExecutionStatus         # 执行状态
    output: Any                     # 输出（保留原始类型）
    error_type: str | None          # 错误类型
    exit_code: int | None           # 退出码
    cost: CostEntry                 # 成本
    files_modified: list[str]       # 修改的文件
    network_egress_bytes: int       # 网络出站流量
    
    @property
    def is_attack_like(self) -> bool:
        # 检测潜在攻击信号
        signals = [
            self.status == "sandbox_violation",
            self.exit_code in {124, 137, 139},
            "shell_injection" in self.stderr_tags,
            "path_traversal" in self.stderr_tags,
        ]
        return sum(signals) >= 2
```

### Trajectory（轨迹）状态

完整任务执行轨迹：

```python
class Trajectory:
    trajectory_id: TrajectoryId
    task_id: TaskId
    thread_id: str | None           # 所属会话
    arm_id: ArmId                   # 执行的 Arm
    strategy_id: str                # 策略 ID
    steps: list[Step]               # 所有步骤
    outcome: TrajectoryOutcome      # 最终结果
    started_at: datetime
    completed_at: datetime
    
    @property
    def step_count(self) -> int:
        return len(self.steps)
    
    @property
    def failed_step_count(self) -> int:
        return sum(1 for s in self.steps if not s.success)
```

---

## 核心流程图

### 1. 完整请求处理流程

```
用户请求
   │
   ▼
┌─────────────────┐
│ Spinal Cord     │ 反射层
│ 反射门          │
└────┬───────┬────┘
     │       │
  命中│       │未命中
     │       │
     ▼       ▼
  直接返回  Cerebrum 规划层
           │
           ▼
        生成 TaskGraph (DAG)
           │
           ▼
        GraphRuntime
        拓扑排序
           │
           ▼
        并行执行层级
           │
           ▼
        ToolExecutor
           │
           ├─→ Immunity (信任检查)
           ├─→ Budget (预算检查)
           └─→ Mantle (沙箱执行)
           │
           ▼
        ExecutionResult
           │
           ▼
        所有节点完成？
           │
           ├─ 否 → 继续下一层
           │
           └─ 是 → 生成 Trajectory
                   │
                   ▼
                Journal 记录
                   │
                   ▼
                返回结果
```

### 2. ReAct 循环状态转换

```
[初始化]
   ↓
[Bootstrap: 解析意图]
   ↓
[AssemblePrompt: 构建提示]
   ↓
┌────────────────────────┐
│  ReAct 主循环          │
│                        │
│ Phase 6b: 模型流式调用  │
│    ↓                   │
│ Phase 6c: 解析与守卫    │
│    ↓                   │
│ Phase 6d: 分发与观察    │
│    ↓                   │
│ Phase 6e: 终止守卫      │
│    ↓                   │
│ Phase 6f: 检查点评估    │
│    ↓                   │
│ Phase 6g: 清理          │
│    ↓                   │
│ 判断是否继续？          │
│    ├─ 是 → 回到 6b     │
│    └─ 否 ↓             │
└────────────────────────┘
   ↓
[Finalize: 终止处理]
   ↓
[返回结果]
```

### 3. TaskGraph DAG 执行

```
TaskGraph
   │
   ▼
拓扑排序 → Layer 0 (并行) → Layer 1 (并行) → Layer 2
           ├─ Node A            ├─ Node C            └─ Node D
           └─ Node B            └─ (依赖 A, B)          (依赖 C)
```

### 4. 状态转换图

```
         ┌─────────┐
         │ Pending │ 任务创建
         └────┬────┘
              │ 开始执行
              ▼
         ┌─────────┐
         │ Running │◄────┐ 迭代中
         └────┬────┘     │
              │          │
         ┌────┴────┬─────┴─────┬─────────┐
         │         │           │         │
    成功完成    执行失败    用户取消   部分完成
         │         │           │         │
         ▼         ▼           ▼         ▼
    Completed   Failed    Cancelled  Partial
```

---

## 关键代码位置速查

### 核心运行时
- **ReAct 主循环**: `runtime/core/cerebrum/react_loop.py`
- **GraphRuntime**: `runtime/core/graph_runtime/runtime.py`
- **工作模式解析**: `runtime/core/cerebrum/work_mode.py`
- **循环状态**: `runtime/core/cerebrum/react_loop_state.py`

### 执行引擎
- **工具执行器**: `runtime/execution/tool_engine/executor.py`
- **反射层**: `runtime/core/nerves/reflex/reflex_router.py`

### 网关与协议
- **实时网关**: `runtime/sensing/gateway/realtime_gateway.py`
- **Cerebrum 桥接**: `runtime/sensing/gateway/realtime_cerebrum.py`

### 数据模型
- **管道模型**: `runtime/platform/models/pipeline.py`
- **执行模型**: `runtime/platform/models/execution.py`
- **原语**: `runtime/platform/models/primitives.py`

### 内存与日志
- **事件日志**: `runtime/memory/threads/event_log.py`
- **共享状态**: `runtime/memory/hemolymph/`
- **知识图谱**: `runtime/memory/knowledge_graph/`

---

## 核心设计亮点

### 1. 成本优化的双通路

**问题**：传统 Agent 每个请求都调用 LLM，成本高昂

**解决方案**：
- 反射层（Spinal Cord）处理 80% 简单请求
- 只有复杂任务才进入 Cerebrum
- 失败案例自动下沉为反射规则

**效果**：
- 反射层命中率越高，成本越低
- 延迟从秒级降至毫秒级

### 2. 规划与执行分离

**问题**：经典 ReAct 每轮都要 LLM 介入

**解决方案**：
- LLM 仅用于一次性生成完整 DAG
- 执行阶段纯粹消费 DAG，无需 LLM
- DAG 支持并行执行

**效果**：
- LLM 调用次数减少
- 并行度提升
- 成本可预测

### 3. 故障学习机制

**问题**：相同错误重复发生

**解决方案**：
- Regeneration 自动提取失败规则
- 下次规划时注入 `LEARNED_MITIGATIONS`
- Camouflage 组件 A/B 淘汰低性能策略

**效果**：
- Agent 持续进化
- 故障率逐步降低

### 4. 多维状态管理

**问题**：复杂任务状态难以追踪

**解决方案**：
- LoopState 统一管理 ReAct 循环状态
- RunStateSummary 汇总任务状态
- Trajectory 完整记录执行轨迹

**效果**：
- 状态可追溯
- 支持检查点和恢复
- 便于调试和优化

---

## 总结

Octopus-Agent 是一个**高度模块化、仿生设计的多 Agent 运行时**，核心特点：

1. **双通路决策**：反射层 + 规划层，兼顾速度与能力
2. **规划执行分离**：LLM 只用于规划，执行阶段无 LLM
3. **并行 DAG 执行**：TaskGraph 支持多节点并行
4. **自进化机制**：失败自动学习，规则持续积累
5. **多工作模式**：统一的 WorkMode 模型支持代码、目标、Swarm 等模式
6. **完整状态管理**：从 Intent 到 Trajectory 的全链路追踪

**推荐阅读顺序**（理解核心流程）：

1. `docs/architecture/chat-modes.md` - 理解 Octopus vs ReAct
2. `runtime/core/cerebrum/work_mode.py` - 理解工作模式
3. `runtime/core/cerebrum/react_loop.py` - 理解 ReAct 循环
4. `runtime/core/graph_runtime/runtime.py` - 理解 DAG 执行
5. `runtime/platform/models/pipeline.py` - 理解数据模型

---

**文档版本**: v1.0  
**维护者**: Octopus-Agent Team  
**最后更新**: 2026-08-08
