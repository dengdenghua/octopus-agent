# Workflow Settlement 通知集成指南

## 概述

Workflow settlement 通知是 DSH 的"结算"机制在 octopus-agent 中的对应实现。当后台工作流完成时，它会通知用户，即使用户在其他标签页或工作区中。

## 架构

### 后端 (已完成)

1. **协议定义** (`runtime/protocol/events.py`)
   - 添加了 `ServerMethod.WORKFLOW_COMPLETED = "workflow/completed"`

2. **通知基础设施** (`runtime/execution/suckers/_delegation_skills_common.py`)
   - 创建了 `workflow_settlement_scope` 上下文管理器
   - 实现了 `_emit_workflow_settlement` 发射函数

3. **工作流观察者** (`runtime/execution/suckers/workflow_skill.py`)
   - `_ProgressObserver.on_end` 方法在工作流完成时发射通知

4. **网关连接** (`runtime/sensing/gateway/_realtime_react_stream_drive.py`)
   - 将 workflow settlement 连接到实时网关的通知系统
   - 使用 `workflow_settlement_scope` 捕获工作流完成事件
   - 通过 WebSocket 发送 `workflow/completed` 通知给客户端

### 前端 (部分完成)

1. **通知 Hook** (`frontend/src/components/workspace/workflow-settlement.tsx`)
   - `useWorkflowSettlement` hook 提供通知处理功能
   - `WorkflowSettlementProvider` 组件包装器

2. **浏览器通知** (`frontend/src/core/notification/hooks.ts`)
   - 已有的 `useNotification` hook 提供浏览器原生通知支持

## 通知流程

```
工作流完成
    ↓
workflow_skill.py: _ProgressObserver.on_end()
    ↓
_delegation_skills_common.py: _emit_workflow_settlement()
    ↓
_realtime_react_stream_drive.py: workflow_settlement_scope callback
    ↓
WebSocket → 客户端 (workflow/completed notification)
    ↓
前端: onNotification callback
    ↓
useWorkflowSettlement → showNotification
    ↓
浏览器原生通知
```

## 集成方法

### 方法 1: 在 use-realtime-thread.ts 中集成 (推荐)

在 `use-realtime-thread.ts` 的 `onNotification` 回调中添加处理：

```typescript
const onNotification = (note: {
  method: string;
  params: Record<string, unknown>;
}): void => {
  // ... 现有代码 ...

  // Handle workflow/completed notifications
  if (note.method === "workflow/completed") {
    // 触发浏览器通知
    // 这需要一个 ref 来访问 showNotification 函数
    // 或者通过事件总线传递
  }

  // ... 现有代码 ...
  applyEvent(note as unknown as ConversationEvent);
};
```

### 方法 2: 在工作区组件中使用 Provider (备选)

在主工作区组件中挂载 `WorkflowSettlementProvider`：

```typescript
import { WorkflowSettlementProvider } from "@/components/workspace/workflow-settlement";

function WorkspaceRealtime({ threadId }: { threadId: string }) {
  return (
    <WorkflowSettlementProvider threadId={threadId}>
      {/* 现有工作区内容 */}
    </WorkflowSettlementProvider>
  );
}
```

然后修改 realtime client 的创建来传递通知处理器。

### 方法 3: 使用自定义事件总线 (最灵活)

创建一个事件总线在 realtime client 和通知组件之间传递消息：

```typescript
// 在 onNotification 回调中
if (note.method === "workflow/completed") {
  window.dispatchEvent(
    new CustomEvent("workflow-completed", { detail: note.params })
  );
}

// 在 useWorkflowSettlement 中
useEffect(() => {
  const handler = (event: CustomEvent) => {
    // 处理通知
  };
  window.addEventListener("workflow-completed", handler);
  return () => window.removeEventListener("workflow-completed", handler);
}, []);
```

## 待完成任务

1. **选择并实现集成方法**
   - 推荐方法 1 或方法 3
   - 需要解决 hook 调用限制（不能在普通回调中调用 hook）

2. **找到正确的挂载点**
   - 确定在哪个组件中添加 `WorkflowSettlementProvider` 或事件监听器
   - 可能的位置：
     - `frontend/src/app/workspace/realtime/[thread_id]/page.tsx`
     - `frontend/src/components/workspace/realtime-workspace.tsx`
     - 或其他顶层工作区组件

3. **测试通知**
   - 触发一个工作流
   - 验证 WebSocket 收到 `workflow/completed` 消息
   - 验证浏览器显示通知

4. **处理权限**
   - 确保用户已授予通知权限
   - 在设置中添加通知开关（如果还没有）

5. **添加单元测试**
   - 测试 `useWorkflowSettlement` hook
   - 测试通知去重逻辑

## 负载示例

从后端发送的 `workflow/completed` 通知负载：

```json
{
  "threadId": "thread-abc123",
  "workflowName": "code-review",
  "workflowDescription": "Review code changes for security issues",
  "runId": "wf_abc123",
  "stopReason": "completed",
  "success": true,
  "agentsStarted": 5,
  "error": null
}
```

## 相关文件

### 后端
- `runtime/protocol/events.py` - 协议定义
- `runtime/execution/suckers/_delegation_skills_common.py` - 通知基础设施
- `runtime/execution/suckers/workflow_skill.py` - 工作流观察者
- `runtime/sensing/gateway/_realtime_react_stream_drive.py` - 网关集成
- `runtime/execution/suckers/delegation_skills.py` - 导出

### 前端
- `frontend/src/components/workspace/workflow-settlement.tsx` - 通知处理
- `frontend/src/core/notification/hooks.ts` - 浏览器通知 API
- `frontend/src/core/realtime/use-realtime-thread.ts` - WebSocket 客户端
- `frontend/src/core/realtime/client.ts` - 底层 WebSocket 客户端
- `frontend/src/core/realtime/reducer.ts` - 状态 reducer

## 测试验证

后端已通过测试：

```bash
$ .venv/bin/python test_workflow_settlement.py
✅ Workflow settlement emission test passed
✅ WorkflowObserver integration test passed
🎉 All tests passed!
```

前端测试待编写。
