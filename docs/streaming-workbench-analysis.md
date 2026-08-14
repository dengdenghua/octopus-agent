# Octopus Agent 流式架构与工作台渲染分析

**分析日期**: 2026-08-14  
**项目**: octopus-agent (Python FastAPI 后端 + React 前端)

---

## 一、流式架构全景图

### 1.1 整体数据流向

```
用户输入 → WebSocket 连接 → 后端网关 → ReAct/Team 流式引擎
   ↓                              ↓
前端 Realtime Adapter ← WS 事件流 ← 事件桥接层 (_ReactBridgeState)
   ↓
状态更新 (messages/events/phases) → UI 渲染
```

### 1.2 核心组件矩阵

| 层级 | 后端模块 | 前端模块 | 职责 |
|------|----------|----------|------|
| **传输层** | `realtime_gateway.py` | `use-thread-stream-realtime.ts` | WebSocket 连接管理 |
| **协议层** | `realtime_react_stream.py` | `adapter.ts` (未找到,可能在其他路径) | 事件序列化/反序列化 |
| **引擎层** | `react_loop.py` / `_drive_react()` | - | 单agent ReAct 循环 |
| **编排层** | `_realtime_team_stream_mesh.py` | - | 多agent 网格/团队编排 |
| **桥接层** | `_realtime_react_stream_apply.py` | `normalizeCustomToolEvent()` | 事件标准化 |
| **渲染层** | - | `AgentWorkbenchPanel.tsx` | 工作台可视化 |

---

## 二、后端流式引擎剖析

### 2.1 单角色流式引擎 (`_drive_react`)

**文件**: `runtime/sensing/gateway/_realtime_react_stream_drive.py`

#### 核心流程
```python
async def _drive_react(
    runtime: CerebrumRuntime,
    turn: Turn,
    log: EventLog,
    emitter: EventEmitter,
    intent: ParsedIntent,
    provider: ApprovalProvider,
    agent: Any,
    *, model: str | None = None,
) -> None:
```

#### 关键特性

1. **线程隔离执行**
   ```python
   # L267: 队列桥接器 - 64事件缓冲区
   queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(maxsize=64)
   
   # L276: 有界阻塞推送 - 避免死锁
   def _safe_put(event, *, timeout=10.0):
       asyncio.run_coroutine_threadsafe(
           queue.put(event), loop
       ).result(timeout=timeout)
   ```

2. **取消传播机制**
   ```python
   # L274: 每轮一个取消源
   cancel_source = CancellationSource()
   # 通过 scoped_cancellation contextvar 传递给所有工具调用
   ```

3. **子代理生命周期桥接** (L60-241)
   - 监听 journal 的 `__subagent_spawned__` / `__subagent_finished__` 事件
   - 合成 `McpToolCallItem` 注入到 turn 的 items 流
   - 前端的 `mcpItemToLiveEvent()` 零改动即可渲染为 agent tiles

4. **心跳机制**
   ```python
   # _SINGLE_AGENT_HEARTBEAT_INTERVAL_S = 15.0
   # 每15秒发送一次 turn/heartbeat 防止超时
   ```

#### 事件类型矩阵

| 事件类型 | 触发时机 | 前端效果 |
|---------|---------|---------|
| `react_started` | ReAct循环启动 | 记录 task_id |
| `text_delta` | LLM 文本流式输出 | 打字机效果 |
| `thinking_delta` | 推理token流 | 折叠的推理区块 |
| `tool_start` | 工具调用开始 | 工具执行动画 |
| `tool_output_delta` | 工具增量输出 | 实时输出流 |
| `tool_end` | 工具完成 | 结果卡片 |
| `commentary_delta` | 进度叙事 | 步骤卡片 |
| `codebase_grounding` | 注入知识库 | 引用chip |
| `visibility` | 能力路由决策 | 可折叠决策面板 |
| `react_cancelled` | 用户中断 | 状态标记为 INTERRUPTED |
| `react_completed` | 循环结束 | 最终状态同步 |

### 2.2 多角色流式编排 (`_drive_swarm_mesh`)

**文件**: `runtime/sensing/gateway/_realtime_team_stream_mesh.py`

#### 架构决策树

```python
# L33-52: 自动选择引擎
def _graph_favors_mesh(graph):
    """
    并行网格适用条件:
    - 节点数 >= 3
    - 拓扑层中存在独立兄弟节点 (widest >= 2)
    
    否则降级到顺序 TeamRunner
    """
```

#### 引擎优先级 (L171-198)

1. **UI 层选择** (`serve_mesh` 上下文参数)
   - `"1"` / `"true"` → 强制网格模式
   - `"0"` / `"false"` → 强制团队模式
   
2. **环境变量** (`OCTOPUS_SERVE_MESH`)
   
3. **自动判断** (`_graph_favors_mesh`)

#### 容错降级 (L98-115)
```python
async def _fallback_to_react():
    # 任何网格故障 → 回退到单agent ReAct
    # 确保编排问题不会导致整轮失败
```

#### 引擎对比

| 特性 | SwarmRuntime (网格) | TeamRunner (团队) |
|------|---------------------|-------------------|
| **并行度** | 真并行 (boids + SignalBus) | 顺序执行 |
| **适用场景** | 宽拓扑图 (>=2层独立节点) | 窄图/顺序图 |
| **协调机制** | Arm-to-Arm 实时协作 | 预定义拓扑 |
| **预算管理** | 共享 Budget (200k tokens) | 按阶段分配 |
| **信号追踪** | SignalBus 收集所有信号 | - |

---

## 三、事件桥接与标准化

### 3.1 后端桥接器 (`_apply_react_event`)

**文件**: `runtime/sensing/gateway/_realtime_react_stream_apply.py`

#### 核心职责

将 ReAct 引擎的内部事件转换为标准化的 `item/*` / `turn/*` / `thread/*` 通知。

#### 状态管理器 (`_ReactBridgeState`)

**文件**: `runtime/sensing/gateway/realtime_event_bridge.py`

```python
class _ReactBridgeState:
    """
    维护流式输出的有状态桥接:
    - 当前活跃的 AgentMessageItem
    - 工具调用栈 (tool_id → McpToolCallItem)
    - 推理内容缓冲
    - 时间线序列号
    """
```

##### 关键方法

| 方法 | 功能 | 协议通知 |
|------|------|---------|
| `append_agent_message()` | 累积文本delta | `item/message/textDelta` |
| `append_reasoning()` | 累积推理token | `item/reasoning/textDelta` |
| `append_commentary()` | 进度叙事 | `item/commentary/textDelta` |
| `start_tool()` | 开启工具调用 | `item/started` |
| `append_tool_output()` | 工具增量输出 | `item/tool/outputDelta` |
| `complete_tool()` | 完成工具 | `item/completed` |
| `track_background_tool()` | 后台工具标记 | `item/tool/background` |
| `flush()` | 提交所有挂起状态 | 多个 `item/completed` |
| `update_grounding_evidence()` | 更新知识库引用 | `turn/grounding` |

#### 特殊事件处理

1. **推理token公开** (L136-148)
   ```python
   # 以前被丢弃,现在路由到 ReasoningItem
   # 前端默认折叠 + 打字机动画
   if kind == "thinking_delta":
       await state.append_reasoning(turn, log, emitter, delta)
   ```

2. **通用叙事过滤** (L119-124)
   ```python
   # 运行时生成的通用进度文案被隐藏
   # 除非明确标记为公开证据
   if progress_source == "runtime" and not public_evidence:
       return
   ```

3. **编排批次桥接** (L33-81)
   ```python
   def _start_orchestrator_bridge(runtime, turn, log, emitter, batch_id):
       """
       订阅并行批次,将任务更新渲染为子代理卡片
       自动终止的后台任务,防止内存泄漏
       """
   ```

### 3.2 前端标准化器 (`normalizeCustomToolEvent`)

**文件**: `frontend/src/core/threads/hooks.ts` (L108-166)

#### 输入格式兼容性

```typescript
// 支持多种后端变体
const name = 
    event.tool_name ?? event.name;
const rawId = 
    event.tool_call_id ?? event.toolUseId ?? event.id;
const input = 
    event.input_preview ?? event.input ?? event.args ?? event.arguments;
```

#### 状态机映射

```typescript
function terminalToolStatus(value: unknown): LiveToolEvent["status"] {
  // 将各种错误状态归一化为 "error"
  if (["error", "failed", "rejected", "cancelled", "timeout"].includes(normalized)) {
    return "error";
  }
  return "done";
}
```

---

## 四、前端工作台渲染架构

### 4.1 页面架构 (`RealtimePage`)

**文件**: `frontend/src/app/workspace/realtime/[thread_id]/page.tsx`

#### 组件树

```
RealtimePage (L1126-1134)
  └─ ArtifactsProvider
      └─ RealtimePageContent (L1136-2306)
          ├─ ChatPageLayout
          │   ├─ 顶栏: 标题 + Agent徽章 + REC按钮 + 协作者控制
          │   ├─ MessageList (消息列表)
          │   └─ ChatInputBox (输入框)
          │
          └─ AgentWorkbenchPanel (右侧工作台)
```

#### 状态管理 (L1150-1250)

##### 核心状态
```typescript
// 工作台显示状态
const [agentWorkbenchManuallyOpened, setAgentWorkbenchManuallyOpened] = useState(false);
const [agentWorkbenchTab, setAgentWorkbenchTab] = useState<AgentWorkbenchTabId>("agent");

// 焦点导航状态
const [focusedWorkbenchAgentId, setFocusedWorkbenchAgentId] = useState<string | null>(null);
const [focusedWorkbenchAgentView, setFocusedWorkbenchAgentView] = 
    useState<AgentWorkbenchFocusView | null>(null);
const [focusedWorkbenchEventId, setFocusedWorkbenchEventId] = useState<string | null>(null);

// 活动选择状态
const [focusedWorkbenchProcessEvent, setFocusedWorkbenchProcessEvent] = 
    useState<AgentWorkbenchProcessEventSnapshot | null>(null);
```

##### 协作编排状态 (L1336-1362)
```typescript
const [selectedCollaboratorIds, setSelectedCollaboratorIds] = useState<string[]>([]);
const [teamModeIntent, setTeamModeIntent] = useState<TeamMode>("cluster");

// 协作模式: "chat" | "cluster" | "mesh"
```

### 4.2 工作台面板 (`AgentWorkbenchPanel`)

**文件**: `frontend/src/components/workspace/agent-workbench-panel.tsx`

#### Props 接口 (L70-165)

```typescript
interface AgentWorkbenchPanelProps {
  // 核心数据
  events: LiveToolEvent[];              // 工具调用事件流
  progressOutline?: OutlineRound[];     // 迭代进展大纲
  
  // 焦点导航
  focusedAgentId?: string | null;
  focusedAgentView?: "summary" | "screen" | "role" | null;
  focusedEventId?: string | null;
  
  // 状态标记
  hasAnswer?: boolean;
  isLoading?: boolean;
  runSettled?: boolean;
  runFailed?: boolean;
  paused?: boolean;
  
  // 多人协作
  rosterSeats?: WorkbenchRosterSeat[];
}
```

#### 快照派生 (L169-187)

```typescript
const workbenchSnapshot = useAgentWorkbenchSnapshot(events, {
  deriveAgentTiles,     // 从事件推导子代理卡片
  hasAnswer,
  isLoading,
  runSettled,
  runFailed,
  paused,
  workDir,
});

// 快照输出
const {
  agentTiles,           // 子代理卡片数组
  blocks,               // 工作块 (WorkBlock[])
  currentPhase,         // 当前阶段
  focusedTab,           // 推断的活跃标签页
  inferredWorkDir,      // 推断的工作目录
  phases,               // 阶段数组
  visibleDiffEntries,   // 可见的差异条目
  evidence,             // 证据列表
} = workbenchSnapshot;
```

#### 标签页架构 (L272-422)

##### 可用标签页
```typescript
const workbenchTabs = [
  { id: "diff",      label: "差异",   Icon: ChevronRightIcon },
  { id: "terminal",  label: "终端",   Icon: TerminalIcon },
  { id: "browser",   label: "浏览器", Icon: GlobeIcon },
  { id: "artifacts", label: "产物",   Icon: PackageIcon },
];
```

##### 标签页状态管理 (L278-417)
```typescript
// 默认关闭 diff 和 terminal,浏览器默认打开
const [closedTabs, setClosedTabs] = useState<Set<AgentWorkbenchTabId>>(
  () => new Set(["diff", "terminal"])
);

// 自动打开标签页 (L383-391)
useEffect(() => {
  if (closedTabs.has(effectiveActiveTab)) {
    setClosedTabs((prev) => {
      const next = new Set(prev);
      next.delete(effectiveActiveTab);
      return next;
    });
  }
}, [effectiveActiveTab]);
```

#### 空壳视图 (L472-502)

当无内容时显示的占位界面:

```typescript
if (emptyShell && !selectedEffectKey && !focusedProcessEvent) {
  return (
    <EmptyShellView
      mainButton={{
        active: effectiveActiveTab === "agent",
        label: isLoading ? "机器人正在启动..." : mainRunStatus.label,
        runState: mainRunState,
      }}
      visibleTabs={visibleTabs}
      browserTabPage={browserTabPage}
      machineRail={machineRail}
    />
  );
}
```

### 4.3 Kanban 视图 (`AgentKanbanView`)

**文件**: `frontend/src/components/workspace/agent-workbench-panel/agent-kanban-view.tsx`

#### 三视图架构 (L115-143)

```typescript
// 顶部切换栏
<div className="flex items-center gap-4 border-b">
  {[
    { id: "summary", label: "进度" },
    ...(selectedAgent ? [
      { id: "screen", label: "执行视图" },
      { id: "role",   label: "角色卡" },
    ] : []),
  ].map((view) => (
    <button onClick={() => setActivityView(view.id)}>
      {view.label}
    </button>
  ))}
</div>
```

#### 视图内容路由 (L162-223)

```typescript
{effectiveActivityView === "summary" ? (
  <AgentSummaryPage
    phases={phases}
    diffEntries={visibleDiffEntries}
    agentTiles={agentTiles}
    blocks={blocks}
    progressOutline={progressOutline}
    groundingSources={groundingSources}
  />
) : effectiveActivityView === "screen" && selectedAgent ? (
  <SubagentProcessView
    agent={selectedAgent}
    blocks={screenBlocks}
    currentBlockId={currentScreenBlockId}
  />
) : selectedAgent ? (
  <AgentCreationCard agent={selectedAgent} />
) : (
  <AgentSummaryPage ... />
)}
```

#### 可见性决策面板 (L226-268)

```typescript
// 默认折叠的能力路由日志
{lastVisibilityEvent && visibilitySteps.length > 0 ? (
  <div className="shrink-0 bg-background/70 pt-2">
    <button onClick={() => setVisibilityOpen(!visibilityOpen)}>
      <ChevronIcon />
      可见性决策面板 ({visibilitySteps.length})
    </button>
    
    {visibilityOpen && (
      <div>
        {visibilitySteps.map((step) => (
          <div>
            <p>{step.conclusion}</p>
            <p>{step.basis}</p>
          </div>
        ))}
      </div>
    )}
  </div>
) : null}
```

### 4.4 子代理进程视图 (`SubagentProcessView`)

**文件**: `frontend/src/components/workspace/agent-workbench-panel/subagent-process-view.tsx`

#### 消息投影 (L81-185)

将子代理的工具事件流转换为标准消息格式:

```typescript
function subagentMessages(agent: AgentTile, blocks: WorkBlock[]): {
  task: Message | null;       // 初始任务
  process: Message[];         // 执行过程 (AIMessage + ToolMessage 交替)
  answer: Message | null;     // 最终答案
} {
  const task = taskText ? {
    id: `subagent-${agent.id}-task`,
    type: "human",
    content: taskText,
  } : null;
  
  const process: Message[] = [];
  
  for (const block of blocks) {
    // 跳过生命周期标记
    if (block.event.lifecycle === "spawned") continue;
    
    // 终结事件 → 提取最终答案
    if (block.event.lifecycle === "finished") {
      answerText = subagentResultText(event);
      continue;
    }
    
    // 构造 AIMessage (工具调用)
    const ai: AIMessage = {
      tool_calls: [{
        id: callId,
        name: event.name,
        args: {
          ...event.input,
          // 流式输出直接注入 args
          ...(event.status === "running" && output ? { output } : {}),
        },
      }],
      additional_kwargs: {
        reasoning_content: thought,
        agent_id: agent.id,
      },
    };
    process.push(ai);
    
    // 构造 ToolMessage (结果)
    if (event.status === "error" || (output && event.status !== "running")) {
      const tool: ToolMessage = {
        type: "tool",
        tool_call_id: callId,
        content: output,
        status: event.status === "error" ? "error" : "success",
      };
      process.push(tool);
    }
  }
  
  return { task, process, answer };
}
```

#### 渲染管道 (L197-200+)

```typescript
<MessageGroup
  messages={messages.process}
  isStreaming={agent.status === "running"}
  isCitationReady={false}
/>
```

复用主对话的 `MessageGroup` 组件,确保一致的:
- 思考/执行折叠状态
- 流式打字机效果
- 工具调用卡片样式

### 4.5 选择管理 (`useWorkbenchSelection`)

**文件**: `frontend/src/components/workspace/agent-workbench-panel/use-workbench-selection.ts`

#### 焦点导航协调

处理多种焦点来源的优先级:

```typescript
// 1. 显式事件焦点 (transcript 行点击)
focusedEventId + focusedEventKind + focusedEventView

// 2. 代理焦点 (机器栏点击 / 卡片点击)
focusedAgentId + focusedAgentView

// 3. 效果密钥焦点 (工具结果详情)
focusedEffectKey

// 4. 进程事件快照 (无工具块的 transcript 行)
focusedProcessEvent
```

#### 视图状态机

```typescript
type ActivityView = "summary" | "trace" | "screen" | "role";

// summary: 总览页 (主代理/协作者汇总)
// trace:   执行追踪 (MessageGroup 渲染)
// screen:  独立电脑视图 (子代理沙盒)
// role:    角色卡 (agent 身份信息)
```

---

## 五、单角色 vs 多角色渲染差异

### 5.1 单角色模式

#### 后端流程

```
用户输入
  ↓
realtime_gateway.py: handle_turn_request()
  ↓
_drive_react() 启动 ReAct 循环
  ↓
stream_react_loop() 在工作线程执行
  ↓
事件队列 (asyncio.Queue) ← 工具调用/文本/推理事件
  ↓
_apply_react_event() 转换为 item/* 通知
  ↓
WebSocket 推送到前端
```

#### 前端渲染

```typescript
// 单一主进程
<AgentKanbanView effectiveActivityView="summary">
  <AgentSummaryPage
    phases={phases}             // 单一阶段线
    blocks={blocks}             // 单一工作块流
    agentTiles={[]}             // 空子代理数组
  />
</AgentKanbanView>
```

##### 工作台布局

```
┌─────────────────────────────────────────┐
│ 主控制器: 运行中                         │
├─────────────────────────────────────────┤
│ [进度] 视图                              │
│                                          │
│ ┌─ Phase 1: 分析需求                    │
│ │  ✓ 读取文件                            │
│ │  ⟳ 执行测试                            │
│ │                                        │
│ ├─ Phase 2: 实现修改                    │
│ │  • 待启动                              │
│ │                                        │
│ └─ 产物 (2)                             │
│    └─ src/utils.ts                      │
└─────────────────────────────────────────┘
```

### 5.2 多角色模式 (协作/集群/蜂群)

#### 后端流程选择

```python
# 输入上下文判断
if collaborationEnabled:
    mode = "team"  # 触发编排引擎
    
    # 计划图并选择引擎
    graph = planner.plan(intent)
    
    if _graph_favors_mesh(graph):
        # 并行网格模式
        await _drive_swarm_mesh(
            runtime, turn, log, emitter, intent,
            topology_id="cowork"
        )
    else:
        # 顺序团队模式
        await _drive_team_topology(
            runtime, turn, log, emitter, intent,
            topology_id=teamModeIntent  # "cluster" | "chat"
        )
else:
    # 单角色模式
    await _drive_react(runtime, turn, log, emitter, intent, provider, agent)
```

#### 子代理生命周期事件流

```
主agent: run_orchestration 工具调用
  ↓
Orchestrator: 并行扇出 N 个子agent
  ↓
每个子agent:
  1. spawned 事件 → journal
  2. 执行独立 ReAct 循环
  3. finished 事件 → journal
  ↓
Journal 订阅器 (_start_subagent_lifecycle_bridge)
  ↓
合成 McpToolCallItem (__subagent_spawned__ / __subagent_finished__)
  ↓
注入主 turn 的 items 流
  ↓
WebSocket 推送
  ↓
前端 mcpItemToLiveEvent() 转换为 LiveToolEvent
  ↓
deriveAgentTiles() 聚合为 AgentTile[]
```

#### 前端渲染差异

##### Roster 座位系统

```typescript
// L1791-1799: 构建协作花名册
const collaborationRoster: ChatCollaborationRosterEntry[] = [
  {
    agent_id: leaderName,
    name: leaderName,
    display_name: composerDisplayAgent.display_name,
    avatar_url: composerDisplayAgent.avatar_url,
    role: "tl",  // Team Leader
  },
  ...selectedCollaborators.map(agent => ({
    agent_id: agent.name,
    role: "member",
  })),
];
```

##### 机器范围轨道 (`MachineScopeRail`)

**文件**: `frontend/src/components/workspace/agent-workbench-panel/machine-scope-rail.tsx`

```typescript
<MachineScopeRail
  agents={agentTiles}           // 子代理卡片
  leaderSeat={leaderRosterSeat} // 主控制器
  rosterSeats={visibleRosterSeats}  // 协作者座位
  selectedAgentId={selectedAgent?.id}
  onSelectMain={openMainProcess}
  onSelectAgent={openSubagentProcess}
  onSelectRoster={openRosterProcess}
/>
```

渲染为底部轨道,显示:
- 主控制器状态按钮
- 子代理卡片滚动列表 (头像 + 状态)
- 协作者座位列表

##### 多agent 工作台布局

```
┌─────────────────────────────────────────┐
│ 主控制器: 协调中   [进度][执行视图][角色]│
├─────────────────────────────────────────┤
│ [进度] 视图                              │
│                                          │
│ ┌─ 子代理活动                            │
│ │  ┌─ Coder (运行中)                    │
│ │  │  ✓ 分析需求                         │
│ │  │  ⟳ 生成代码                         │
│ │  │                                     │
│ │  ├─ Tester (等待)                     │
│ │  │  • 待 Coder 完成                    │
│ │  │                                     │
│ │  └─ Reviewer (完成)                   │
│ │     ✓ 审查通过                         │
│ │                                        │
│ └─ 产物 (5)                             │
│    ├─ src/feature.ts (Coder)            │
│    └─ tests/feature.test.ts (Tester)   │
├─────────────────────────────────────────┤
│ 🤖 主控 | 👤 Coder | 👤 Tester | 👤 Reviewer │
└─────────────────────────────────────────┘
```

点击子代理后切换到独立电脑视图:

```
┌─────────────────────────────────────────┐
│ Coder   [进度][执行视图][角色]           │
├─────────────────────────────────────────┤
│ [执行视图]                               │
│                                          │
│ 👤 任务: 实现用户认证功能                 │
│                                          │
│ 🤖 Assistant                            │
│ ┌─ 🧠 Thought                           │
│ │  需要先检查现有认证代码...               │
│ │                                        │
│ ├─ 🔧 read_file                         │
│ │  ✓ src/auth/index.ts                 │
│ │                                        │
│ └─ 🔧 write_file                        │
│    ⟳ src/auth/login.ts                 │
│                                          │
│ 🤖 Result                               │
│ 已实现登录功能,包含 JWT 验证...           │
└─────────────────────────────────────────┘
```

---

## 六、关键设计模式

### 6.1 流式状态机

**后端** (`_ReactBridgeState`)

```
IDLE → TEXT_STREAMING → TOOL_RUNNING → TEXT_STREAMING → FLUSH → COMPLETED
  ↓                           ↓
append_agent_message()   start_tool() / complete_tool()
```

**前端** (Message 适配器)

```typescript
// realtime adapter 保持 Message 引用稳定
const messageTextLengthCache = new WeakMap<Message, number>();

// 只重建被 delta 修改的 Message 对象
// 未变对象的引用不变 → WeakMap 缓存命中
```

### 6.2 事件溯源 + 快照派生

#### 事件流是唯一真相源

```typescript
events: LiveToolEvent[]  // 原子事件流
  ↓
useAgentWorkbenchSnapshot()
  ↓
{
  agentTiles,    // 派生: 从 spawned/finished 聚合
  phases,        // 派生: 从 tool_start/tool_end 分组
  blocks,        // 派生: 事件 → WorkBlock 转换
  evidence,      // 派生: 提取文件引用
}
```

#### 增量更新

```typescript
// L28-51: upsertLiveToolEvent
function upsertLiveToolEvent(
  events: LiveToolEvent[],
  nextEvent: LiveToolEvent,
): LiveToolEvent[] {
  const existingIndex = events.findIndex(e => e.id === nextEvent.id);
  
  if (existingIndex === -1) {
    return [...events, nextEvent];  // 新事件: 追加
  }
  
  // 现有事件: 合并更新字段
  const merged = { ...existing };
  for (const [key, value] of Object.entries(nextEvent)) {
    if (value !== undefined) {
      merged[key] = value;
    }
  }
  updated[existingIndex] = merged;
  return updated;
}
```

### 6.3 焦点协调 (Focus Coordination)

#### 多来源焦点

1. **Transcript 行点击** → `focusedEventId`
2. **子代理卡片点击** → `focusedAgentId` + `focusedAgentView`
3. **工具结果卡片点击** → `focusedEffectKey`
4. **无工具块的进度行** → `focusedProcessEvent`

#### Nonce 防重复消费

```typescript
// L1176-1177: 焦点 nonce 递增
const [focusedWorkbenchAgentNonce, setFocusedWorkbenchAgentNonce] = useState(0);

// L1124-1130: 事件监听器
useEffect(() => {
  const handler = (event: CustomEvent<AgentWorkbenchFocusDetail>) => {
    setFocusedWorkbenchAgentId(event.detail.agentId);
    setFocusedWorkbenchAgentNonce(n => n + 1);  // 强制刷新
  };
  window.addEventListener(AGENT_WORKBENCH_FOCUS_EVENT, handler);
  return () => window.removeEventListener(AGENT_WORKBENCH_FOCUS_EVENT, handler);
}, []);

// 消费端只在 nonce 变化时响应
useEffect(() => {
  if (!focusedAgentId) return;
  // ...执行焦点导航
}, [focusedAgentId, focusedAgentNonce]);
```

### 6.4 渐进式披露 (Progressive Disclosure)

#### 折叠状态分层

1. **推理内容** (默认折叠)
   ```typescript
   <ReasoningBlock collapsed={!userExpanded}>
     {thinkingContent}
   </ReasoningBlock>
   ```

2. **工具调用** (自动折叠历史,展开当前)
   ```typescript
   const isCurrentTool = tool.status === "running";
   <ToolCallCard collapsed={!isCurrentTool && !userExpanded}>
   ```

3. **子代理详情** (点击展开独立视图)
   ```typescript
   onClick={() => setActivityView("screen")}
   ```

4. **可见性决策** (默认折叠)
   ```typescript
   const [visibilityOpen, setVisibilityOpen] = useState(false);
   ```

---

## 七、性能优化策略

### 7.1 后端

1. **有界队列 + 超时推送**
   ```python
   queue = asyncio.Queue(maxsize=64)
   asyncio.run_coroutine_threadsafe(queue.put(event), loop).result(timeout=10.0)
   ```

2. **心跳去抖动**
   ```python
   _SINGLE_AGENT_HEARTBEAT_INTERVAL_S = 15.0
   # 避免频繁 WebSocket 帧
   ```

3. **子代理生命周期桥接的惰性订阅**
   ```python
   # 只在 journal 为 StreamingJournal 时订阅
   if subscribe is _JournalBase.subscribe:
       return None
   ```

### 7.2 前端

1. **消息引用稳定性 + WeakMap 缓存**
   ```typescript
   const messageTextLengthCache = new WeakMap<Message, number>();
   // 只重新计算修改过的消息
   ```

2. **虚拟化长列表**
   ```typescript
   // MessageList 使用 react-window 虚拟滚动
   // 只渲染视口内的消息
   ```

3. **懒加载组件**
   ```typescript
   const LazyStreamdown = lazy(() => import("@/components/ai-elements/streamdown-host"));
   <Suspense fallback={<div>加载中...</div>}>
     <LazyStreamdown>{content}</LazyStreamdown>
   </Suspense>
   ```

4. **Memo 隔离**
   ```typescript
   export const AgentWorkbenchPanel = memo(AgentWorkbenchPanelImpl);
   export const AgentKanbanView = memo(AgentKanbanViewImpl);
   // 防止父组件重渲染波及大型子树
   ```

---

## 八、已知问题与改进方向

### 8.1 前端

#### 问题1: 流式上下文压缩延迟感知
**现状**: `isCompressingContext` 标志存在,但 UI 未充分利用  
**影响**: 用户不知道为何等待  
**改进**: 显示 "正在压缩上下文..." spinner

#### 问题2: 子代理电脑视图无滚动锚点
**现状**: `SubagentProcessView` 渲染 `MessageGroup`,但无自动滚动到最新消息  
**影响**: 用户需手动滚动查看进展  
**改进**: 添加 `scrollToBottom` effect

#### 问题3: 浏览器标签页源切换无平滑过渡
**现状**: `browserSourceOverride` 立即切换,内容闪烁  
**影响**: 用户体验不连贯  
**改进**: 添加淡入淡出动画

### 8.2 后端

#### 问题1: Journal 订阅器内存泄漏风险
**现状**: `_start_subagent_lifecycle_bridge` 返回 unsubscribe,但调用方未必清理  
**影响**: 长时间运行可能累积废弃订阅  
**改进**: 使用 `weakref` 或确保 `_drive_react` finally 块调用清理

#### 问题2: 网格模式降级无日志
**现状**: `_drive_swarm_mesh` 异常回退到 react,但静默失败  
**影响**: 难以诊断编排问题  
**改进**: 记录降级原因到 telemetry

#### 问题3: 工具输出 delta 无背压
**现状**: `append_tool_output` 无限累积,直到 `complete_tool`  
**影响**: 长输出工具 (如大文件读取) 可能撑爆内存  
**改进**: 引入输出块分段提交机制

---

## 九、测试覆盖建议

### 9.1 单元测试

#### 后端
```python
# tests/sensing/gateway/test_react_stream_apply.py
async def test_apply_react_event_text_delta():
    """验证文本 delta 正确累积到 AgentMessageItem"""
    
async def test_subagent_lifecycle_bridge():
    """验证 journal 事件正确合成为 McpToolCallItem"""

# tests/sensing/gateway/test_team_stream_mesh.py
def test_graph_favors_mesh_parallel():
    """验证宽拓扑图选择网格引擎"""
    
def test_graph_favors_mesh_sequential():
    """验证窄图选择团队引擎"""
```

#### 前端
```typescript
// frontend/src/core/threads/hooks.test.ts
describe("upsertLiveToolEvent", () => {
  it("should append new event", () => { ... });
  it("should merge existing event", () => { ... });
});

describe("normalizeCustomToolEvent", () => {
  it("should normalize tool_start", () => { ... });
  it("should map error status", () => { ... });
});
```

### 9.2 集成测试

```python
# tests/integration/test_streaming_e2e.py
@pytest.mark.asyncio
async def test_single_agent_stream():
    """端到端: 单agent 工具调用 → WebSocket 事件流"""
    
@pytest.mark.asyncio
async def test_multi_agent_collaboration():
    """端到端: 协作模式 → 子代理卡片渲染"""
```

### 9.3 性能测试

```python
# tests/performance/test_stream_throughput.py
@pytest.mark.benchmark
async def test_react_stream_latency():
    """基准: 事件桥接延迟 < 50ms (p99)"""
    
@pytest.mark.benchmark
async def test_subagent_spawn_overhead():
    """基准: 10 个并行子agent 扇出时间 < 2s"""
```

---

## 十、总结

### 核心优势

1. **统一协议**: 单agent/多agent 使用同一套 `item/*` 事件协议
2. **增量渲染**: 事件溯源 + 快照派生 = 高效更新
3. **容错降级**: 编排失败 → 单agent 保底
4. **组件复用**: `MessageGroup` 同时服务主进程和子代理视图

### 架构清晰度

- **后端**: 引擎(react/team/mesh) → 桥接(apply) → 协议(item/*)
- **前端**: WebSocket → 适配器(normalize) → 快照(snapshot) → 渲染(workbench)

### 扩展性

- **新工具类型**: 仅需在 `_apply_react_event` 添加新 case
- **新编排模式**: 实现新的 `_drive_*` 函数,复用桥接层
- **新工作台标签页**: 在 `workbenchTabs` 数组添加条目 + 对应渲染组件

---

**文档版本**: v1.0  
**最后更新**: 2026-08-14  
**维护者**: AI Analysis System
