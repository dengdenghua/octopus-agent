# DSH 功能差距分析报告

完成时间：2025-01-XX

## 📊 总体结论

经过全面代码审查，**Octopus 已经实现了 DSH 的大部分核心功能**。大部分"缺失"功能实际上已有基础实现，只是：
- 命名/组织方式不同
- 缺少部分高级特性
- 接口未完全对齐

---

## ✅ 已完整实现的功能

### 1. 工具流式增量 (tool-call-delta) ✅
**状态**: 已实现

**证据**:
- `runtime/platform/models/llm.py` - `ModelStreamEvent` 包含 `tool_call_delta` 类型
- `runtime/memory/journal/_journal_models.py` - 日志支持 `tool-call-delta` lane
- 支持 `index/call_id/name/arguments_delta` 字段

**实现位置**:
```
runtime/platform/models/llm.py:218-223
runtime/memory/journal/_journal_models.py:45-50
runtime/sensing/model_router/anthropic_router.py (流式解析)
```

**差距**: ❌ 无明显差距

---

### 2. Workflow 编排 ✅
**状态**: 核心已实现，缺少高级特性

**已有实现**:
- ✅ `ParallelAgentOrchestrator` - 多代理编排引擎
- ✅ 依赖管理 - `depends_on` + 拓扑排序
- ✅ 并发控制 - `max_concurrency`
- ✅ Phase 自动划分 - `BatchPhase`
- ✅ WorkContract - 任务合约与作用域隔离
- ✅ 事件流 - `BatchStreamEvent` 实时状态
- ✅ 恢复机制 - `BatchRecoverySnapshot`
- ✅ 前端 UI - `agent-workflow-panel.tsx`

**实现位置**:
```
runtime/execution/parallel_agents/
  ├── orchestrator.py          # 编排引擎
  ├── models.py                # 数据模型
  ├── _orchestrator_scheduler.py  # 调度器
  └── _orchestrator_models.py  # 内部模型

frontend/src/components/workspace/agent-workflow-panel.tsx
```

**差距**: 
- ⚠️ 缺少声明式 DSL (YAML/JSON 定义)
- ⚠️ 缺少条件分支/循环 (if/for/while)
- ⚠️ 缺少可复用步骤模板库
- ⚠️ 前端只有展示，无编辑器

**预计补齐工作量**: 1-2 周

---

### 3. Permission Presets ✅
**状态**: 已完整实现

**已有实现**:
- ✅ 三档预设: `read_only` / `workspace_write` / `full_access`
- ✅ 自动批准模式
- ✅ Profile 切换逻辑

**实现位置**:
```
runtime/safety/approval/permission_profiles.py
```

**差距**: ❌ 无明显差距

---

### 4. Credential References / Identity ✅
**状态**: 已实现

**已有实现**:
- ✅ OS Keychain 集成 - macOS/Linux/Windows
- ✅ 加密存储 - Fernet 对称加密
- ✅ 凭据池管理 - `credential_pool.py`
- ✅ 多 Provider 支持
- ✅ 身份过滤 - `identity_filter.py`

**实现位置**:
```
runtime/platform/credentials/
  ├── secret_store.py          # OS Keychain 后端
  ├── credential_pool.py       # 凭据池
  └── credential_sources.py    # 数据源

runtime/safety/auth/identity.py
runtime/platform/runtime_policy/identity_filter.py
```

**差距**: 
- ⚠️ 可能缺少凭据轮换机制
- ⚠️ 审计日志待确认

**预计补齐工作量**: 2-3 天

---

### 5. 协议层 (类 ACP — Agent Client Protocol) ✅
**状态**: 已有完整的 Realtime Protocol

**已有实现**:
- ✅ JSON-RPC 2.0 封装 - `envelope.py`
- ✅ Item-oriented 状态模型
- ✅ Token-level deltas
- ✅ 双向通信 (client/server methods)
- ✅ 传输无关 (WebSocket/stdio/pipe)

**实现位置**:
```
runtime/protocol/
  ├── envelope.py              # JSON-RPC 封装
  ├── items.py                 # 24+ item 类型
  ├── events.py                # 客户端/服务端方法
  └── realtime_schema.py       # Schema 定义
```

**差距**: 
- ⚠️ 不是标准 ACP 协议 (是自研 Realtime Protocol;ACP = Zed 的 Agent
  Client Protocol,客户端↔agent 互操作,JSON-RPC over stdio,不是 agent
  间协议)
- ⚠️ Zed/VS Code/Cursor 等外部 ACP 客户端无法直接驱动我们

**评估**: 功能等价且更全,但缺标准互操作;低成本加分项是加一层 ACP
server 适配到现有 runtime/protocol,不改变核心架构

---

### 6. SpillStore (本地) ✅
**状态**: 本地实现已完成

**已有实现**:
- ✅ 大输出溢出存储
- ✅ Head/tail 预览
- ✅ 会话隔离 - session-scoped 目录
- ✅ 安全策略 - 0700 权限，随机文件名
- ✅ UTF-8 边界保护
- ✅ 自动跳过 read_file (防止循环)

**实现位置**:
```
runtime/execution/tool_engine/tool_output_spill.py
```

**差距**: 
- ⚠️ 只有本地文件系统，无远端存储 (S3/云存储)

**预计补齐工作量**: 3-5 天 (添加 S3 backend)

---

### 7. Sandbox ✅
**状态**: 已有容器沙箱

**已有实现**:
- ✅ 容器沙箱 - `container_sandbox.py`
- ✅ 通用沙箱抽象 - `sandbox.py`

**实现位置**:
```
runtime/safety/sandboxing/
  ├── sandbox.py               # 抽象接口
  └── container_sandbox.py     # 容器实现
```

**差距**: 
- ⚠️ 无 E2B 云沙箱集成

**预计补齐工作量**: 5-7 天 (E2B SDK 集成)

---

## ⚠️ 部分实现的功能

### 8. Detached 运行链 + Quiescence Drain ⚠️
**状态**: 有 drain 机制，但未搬 detached 语义

**已有实现**:
- ✅ 多处 drain 方法:
  - `async_runner.drain()` / `drain_all()`
  - `drain_active_turns_for_shutdown()`
  - `drain_mailbox()` 
  - `drain_pending()`

**实现位置**:
```
runtime/memory/cowork/async_runner.py
runtime/sensing/gateway/realtime_cerebrum.py
runtime/execution/arms/base.py
runtime/sensing/gateway/_channels_persist.py
```

**差距**: 
- ⚠️ 缺少 `createDetachedRuns` 显式 API
- ⚠️ Quiescence 语义可能未完整实现

**预计补齐工作量**: 3-5 天

---

### 9. on_report 真撬回合 ⚠️
**状态**: 机制已搬，接线未完

**已有实现**:
- ✅ `wakeup` / `quiet` / `queued` delivery 模式
- ✅ report_delivery 标准化

**实现位置**:
```
runtime/execution/subagents/sessions.py:
  - _normalize_report_delivery()
  - delivery: wakeup/quiet/queued
```

**差距**: 
- ⚠️ wakeup 只落盘，不真开新回合
- ⚠️ 缺「空闲 owner 自动开新父回合」的网关热区

**预计补齐工作量**: 2-3 天

---

### 10. Settlement 通知 ⚠️
**状态**: 机制存在，未完全接通

**差距**: 
- ⚠️ 子代理终止时未主动通知父代理
- ⚠️ 父代理靠 steering 注入而非事件

**预计补齐工作量**: 2-3 天

---

### 11. Quiet/Wakeup 独立调度器 ⚠️
**状态**: 排队语义已对，调度器未独立

**差距**: 
- ⚠️ wakeup 不主动撬回合
- ⚠️ 需要独立调度器线程/进程

**预计补齐工作量**: 3-5 天

---

## ❌ 缺失的功能

### 12. Jobs 后台任务 ❌
**状态**: 完全缺失

**DSH 特性**:
- `job_output` / `job_list` / `job_kill` API
- Per-owner 并发上限
- 任务队列与后台执行

**现状**: 无对应实现

**预计补齐工作量**: 1-2 周

---

### 13. Replay 跨 Writer Wildcard ❌
**状态**: 可能存在性能问题

**差距**: 
- ⚠️ 回放读全量再按订阅过滤
- ⚠️ 无 wildcard 索引优化

**预计补齐工作量**: 2-3 天

---

## 📈 工作量总结

| 优先级 | 功能 | 状态 | 工作量 | 性价比 |
|--------|------|------|--------|--------|
| P0 | ✅ 工具流式增量 | 已完成 | 0 天 | - |
| P0 | ✅ Permission Presets | 已完成 | 0 天 | - |
| P0 | ✅ Credential System | 已完成 | 0 天 | - |
| P1 | ⚠️ on_report 真撬回合 | 接线 | 2-3 天 | ⭐⭐⭐⭐⭐ |
| P1 | ⚠️ Settlement 通知 | 接线 | 2-3 天 | ⭐⭐⭐⭐⭐ |
| P1 | ⚠️ Quiet/Wakeup 调度器 | 接线 | 3-5 天 | ⭐⭐⭐⭐ |
| P2 | ⚠️ Workflow DSL 增强 | 增强 | 1-2 周 | ⭐⭐⭐⭐ |
| P2 | ❌ Jobs 后台任务 | 新建 | 1-2 周 | ⭐⭐⭐⭐ |
| P3 | ⚠️ Detached 运行链 | 补齐 | 3-5 天 | ⭐⭐⭐ |
| P3 | ⚠️ 远端 SpillStore | 扩展 | 3-5 天 | ⭐⭐ |
| P3 | ⚠️ E2B 云沙箱 | 集成 | 5-7 天 | ⭐⭐ |
| P4 | ⚠️ Replay Wildcard | 优化 | 2-3 天 | ⭐⭐ |

**总计工作量**: 约 6-8 周 (包含测试和文档)

---

## 🎯 实施建议

### 第一阶段 (1 周) - 快速收割
1. ✅ on_report 真撬回合 (2-3 天)
2. ✅ Settlement 通知 (2-3 天)
3. ✅ Replay Wildcard 优化 (2-3 天)

**目标**: 接通已有机制，立即提升用户体验

### 第二阶段 (2-3 周) - 核心增强
4. ⚠️ Quiet/Wakeup 独立调度器 (3-5 天)
5. ⚠️ Workflow DSL 增强 (1-2 周)
6. ❌ Jobs 后台任务 (1-2 周)

**目标**: 补齐核心基础设施

### 第三阶段 (2-3 周) - 扩展能力
7. ⚠️ Detached 运行链 (3-5 天)
8. ⚠️ 远端 SpillStore (3-5 天)
9. ⚠️ E2B 云沙箱 (5-7 天)

**目标**: 扩展运行环境能力

---

## 💡 关键发现

1. **Octopus 比预期更完整** - 大部分核心功能已实现
2. **命名差异造成误判** - 很多功能已有，但名字不同
3. **架构更先进** - Realtime Protocol 比 ACP 更现代
4. **主要是接线问题** - 机制都搬了，只是没完全连通

---

## 🚀 立即可做

**最高性价比任务** (1 周内完成):
1. on_report 真撬回合接线
2. Settlement 通知事件桥
3. Replay wildcard 优化

这三项都是"机制已有，接线未完"，可以快速完成并立即见效。

---

*最后更新: 2025-01-XX*
*审查者: Claude Code*
