# DSH 功能迁移路线图

基于移植笔记中的「尚未覆盖」清单，按性价比排序的实施计划。

## 🚧 正在进行

### 1. 工具流式增量 (tool-call-delta)
**优先级**: ⭐⭐⭐⭐⭐ (正在做)

**现状**: 
- 我们目前工具参数整块落盘
- 只有 reasoning 有增量泳道

**DSH 优势**:
- 工具参数 JSON 分片带 `index/id/name` 流式入日志
- 前端能实时看到「正在组装的参数」

**实施要点**:
- [ ] 后端：在 `runtime/sensing/model_router/` 中添加工具参数 delta 解析
- [ ] 日志：`runtime/memory/journal/` 增量写入工具参数片段
- [ ] 前端：`frontend/src/components/workspace/` 实时渲染组装中的参数
- [ ] 协议：定义 tool-call-delta 事件格式（index/id/name/partial_json）

**预计工作量**: 3-5 天

---

## 📋 待实施 (大块功能)

### 2. Workflow 编排
**优先级**: ⭐⭐⭐⭐
**代码量**: 552K (packages/workflow in DSH)

**功能描述**:
- 可编程的多步工具编排脚本
- 步骤可复用、可并行
- 类似「agent 里的流水线」

**当前状态**: ✅ **已有基础实现** - `runtime/execution/parallel_agents/`

**已实现功能**:
- ✅ `ParallelAgentOrchestrator` - 多代理编排器，支持依赖图和并发控制
- ✅ `DispatchTaskInput` - 任务定义，支持 `depends_on` 依赖
- ✅ `BatchPhase` - 基于拓扑排序的阶段划分
- ✅ `WorkContract` - 任务合约与作用域管理
- ✅ 线程池/进程隔离 - worker_isolation: auto/thread/process
- ✅ 并发控制 - max_concurrency 限制
- ✅ 事件流 - `BatchStreamEvent` 实时状态更新
- ✅ 恢复机制 - `BatchRecoverySnapshot`

**DSH vs Octopus 差异分析**:

| 特性 | Octopus (已有) | DSH workflow (552K) | 差距 |
|------|----------------|---------------------|------|
| 并行编排 | ✅ ParallelAgentOrchestrator | ✅ | 相当 |
| 依赖管理 | ✅ depends_on + 拓扑排序 | ✅ | 相当 |
| DSL 语法 | ⚠️ 代码定义 | ✅ YAML/JSON 声明式 | **缺** |
| 步骤复用 | ⚠️ 代码级别 | ✅ 模板库 | **缺** |
| 条件分支 | ❌ | ✅ if/switch | **缺** |
| 循环控制 | ❌ | ✅ for/while | **缺** |
| 内置步骤库 | ❌ | ✅ 丰富的预置步骤 | **缺** |
| 可视化编辑 | ⚠️ agent-workflow-panel | ✅ 全功能编辑器 | **缺** |

**待增强**:
- [ ] 声明式 DSL (YAML/JSON) - 目前只能代码定义
- [ ] 条件分支与循环语法
- [ ] 可复用步骤模板库
- [ ] Workflow 持久化与版本管理
- [ ] 可视化 Workflow 编辑器（前端已有基础 UI）
- [ ] Workflow 市场/共享机制

**实施策略**:
```python
# 在现有基础上扩展
runtime/execution/parallel_agents/
  ├── workflow_dsl.py        # 新增：DSL 解析器
  ├── workflow_templates.py  # 新增：步骤模板库
  ├── workflow_conditions.py # 新增：条件分支引擎
  └── workflow_storage.py    # 新增：持久化层

# 前端增强
frontend/src/components/workspace/
  ├── agent-workflow-panel.tsx         # 已有：可视化显示
  ├── workflow-editor.tsx              # 新增：可视化编辑
  └── workflow-template-library.tsx    # 新增：模板库
```

**预计工作量**: 1-2 周（在现有基础上增强，而非从零开始）

---

### 3. Jobs 后台任务
**优先级**: ⭐⭐⭐⭐
**代码量**: 260K (packages/jobs)

**功能描述**:
- `job_output/job_list/job_kill` API
- 每 owner 并发上限控制
- 长任务后台跑、可查、可杀

**当前状态**: ❌ 我们没有

**实施策略**:
```python
# 新增模块结构
runtime/execution/jobs/
  ├── manager.py        # 任务管理器
  ├── queue.py          # 任务队列
  ├── worker.py         # 工作进程
  ├── monitor.py        # 状态监控
  └── limiter.py        # 并发限制

# API 端点
runtime/platform/ui/jobs_router.py
```

**关键特性**:
- [ ] 任务提交与排队
- [ ] 后台执行与状态跟踪
- [ ] 输出流式获取
- [ ] 任务终止与清理
- [ ] Per-owner 并发控制

**预计工作量**: 1-2 周

---

### 4. Permission Presets (权限预设档位)
**优先级**: ⭐⭐⭐
**代码量**: 小型重构

**功能描述**:
- 预设权限档位一键应用
- 避免每次操作都弹审批

**当前状态**: ⚠️ 我们有审批链但没有预设档

**实施策略**:
```python
# 扩展现有模块
runtime/safety/approval/permission_profiles.py
  - 添加预设配置管理
  - 添加档位切换逻辑

# 前端
frontend/src/core/permissions.ts
  - 添加预设档位 UI
  - 快速切换入口
```

**预设档位建议**:
- `strict`: 每次审批
- `balanced`: 信任常用工具
- `permissive`: 仅危险操作审批
- `auto`: 全部自动批准（开发模式）

**预计工作量**: 3-5 天

---

### 5. Credential References / Identity
**优先级**: ⭐⭐⭐
**代码量**: 中型

**功能描述**:
- 凭据安全引用与身份管理
- 多 provider 凭据不裸露

**当前状态**: ❌ 我们没有

**实施策略**:
```python
# 新增模块
runtime/security/
  ├── credentials/
  │   ├── vault.py          # 凭据保险库
  │   ├── references.py     # 引用管理
  │   └── encryption.py     # 加密存储
  └── identity/
      ├── manager.py        # 身份管理
      └── providers.py      # Provider 适配器
```

**关键特性**:
- [ ] 凭据加密存储
- [ ] 引用而非明文传递
- [ ] 多 provider 支持
- [ ] 凭据轮换
- [ ] 审计日志

**预计工作量**: 1 周

---

### 6. ACP 协议 (Agent Client Protocol)
**优先级**: ⭐⭐
**代码量**: 132K (packages/acp) — 注意:这是 **Zed 的 Agent Client Protocol**,
不是 agent 间通信协议(A2A 才是);dsh 里它同时当**客户端**(subagent-acp
provider,开独立进程用 ACP 驱动 Codex/Claude Code/Cursor/Gemini CLI 等)
和**服务端**(acp-agent 示例,对外暴露 ACP server 让 Zed/VS Code/自动化驱动)。

**功能描述**:
- 对外暴露标准 **客户端↔agent** 互操作协议(JSON-RPC over stdio)
- 任意 ACP 客户端(Zed/VS Code/Cursor/CodeBuddy/Gemini CLI/自动化)可以直接驱动我们
- 反过来我们也可以作为 ACP 客户端,把其他支持 `--acp` 的 agent 当子代理调

**当前状态**: ❌ 我们没有

**实施策略**:
```python
# 新增协议层
runtime/protocols/
  ├── acp/
  │   ├── server.py         # ACP 服务器 (JSON-RPC over stdio)
  │   ├── schema.py         # 协议定义 (initialize / session / prompt / patch)
  │   ├── adapter.py        # Octopus 适配器 (桥到现有 runtime/protocol Realtime)
  │   └── client.py         # ACP 客户端库 (驱动外部 ACP agent)
  └── registry.py           # 协议注册
```

**关键特性**:
- [ ] 能力协商 (initialize → capabilities)
- [ ] 会话生命周期 (session/new, session/prompt, session/update)
- [ ] 文件编辑与补丁协议 (apply_patch / write / get)
- [ ] 工具调用与结果回传
- [ ] 流式 token / 思考过程 (delta 通道)
- [ ] 桥接到现有 Realtime Protocol (WebSocket/stdio 双向)

**预计工作量**: 2 周

---

### 7. E2B 云沙箱 + 远端 SpillStore
**优先级**: ⭐⭐
**代码量**: 中型

**功能描述**:
- 云端执行环境
- 大输出远端存储

**当前状态**: ⚠️ Spill 只有本地文件系统实现

**实施策略**:
```python
# 扩展现有模块
runtime/execution/sandbox/
  ├── e2b_sandbox.py        # E2B 适配器
  └── cloud_executor.py     # 云端执行

runtime/memory/spill/
  ├── remote_store.py       # 远端存储实现
  ├── s3_backend.py         # S3 后端
  └── compression.py        # 压缩传输
```

**关键特性**:
- [ ] E2B SDK 集成
- [ ] 云沙箱生命周期管理
- [ ] 远端对象存储
- [ ] 增量传输优化

**预计工作量**: 1-2 周

---

### 8. Detached 运行链 + Quiescence Drain
**优先级**: ⭐⭐
**代码量**: 中型

**功能描述**:
- 离屏运行与静默排空语义
- `createDetachedRuns` 机制

**当前状态**: ⚠️ 我们有 guard 但没搬这条

**实施策略**:
```python
# 扩展现有运行链
runtime/core/run/
  ├── detached_run.py       # 离屏运行
  ├── drain.py              # 排空逻辑
  └── lifecycle.py          # 生命周期管理
```

**关键特性**:
- [ ] 运行链脱离主会话
- [ ] 静默排空语义
- [ ] 资源清理保证

**预计工作量**: 5-7 天

---

### 9. Replay 跨 Writer Wildcard
**优先级**: ⭐
**代码量**: 小型优化

**功能描述**:
- 回放支持跨 writer 的 wildcard 语义

**当前状态**: ⚠️ 我们回放读全量再按订阅过滤

**实施策略**:
- 在 `runtime/memory/journal/` 中优化订阅匹配
- 添加 wildcard 模式解析
- 索引优化避免全扫

**预计工作量**: 2-3 天

---

## 🔧 最后一公里 (机制已搬，接线没完)

### 10. on_report 真撬回合
**状态**: 🟡 已有机制，未完全接通

**缺陷**:
- wakeup 现在只落盘不真开新回合
- 缺「空闲 owner 自动开新父回合」的网关热区

**接线任务**:
- [ ] 在 gateway 中添加 wakeup 处理器
- [ ] 实现空闲检测逻辑
- [ ] 自动开启新回合的触发器

**预计工作量**: 2-3 天

---

### 11. Settlement 通知
**状态**: 🟡 已有机制，未完全接通

**缺陷**:
- 子代理结束时应主动通知父代理
- 目前父代理靠下次读取/steering 注入

**接线任务**:
- [ ] 子代理终止时发送 settlement 事件
- [ ] 父代理注册事件监听器
- [ ] 事件桥接到父代理上下文

**预计工作量**: 2-3 天

---

### 12. Quiet/Wakeup 独立调度器
**状态**: 🟡 已有机制，未完全接通

**缺陷**:
- 父代理离线时的排队语义已对
- 但 wakeup 不主动撬回合

**接线任务**:
- [ ] 实现独立调度器线程/进程
- [ ] wakeup 队列管理
- [ ] 主动触发回合机制

**预计工作量**: 3-5 天

---

### 13. 小项
**状态**: 🟡 零散待办

**清单**:
- [ ] Title provider 优先级/模型选择
- [ ] Goal 多目标历史归档
- [ ] 非 subagent store 的 resolver 适配器（纯接入点）

**预计工作量**: 3-5 天（合计）

---

## 📊 总体规划

### 短期 (1-2 周)
1. ✅ 完成工具流式增量 (tool-call-delta) - **正在进行**
2. 🔧 接通最后一公里功能 (#10-#13)
3. 🚀 实现 Permission Presets (#4)

### 中期 (1-2 月)
4. 📦 实现 Jobs 后台任务 (#3)
5. 🔀 实现 Workflow 编排 (#2)
6. 🔐 实现 Credential References (#5)

### 长期 (2-3 月)
7. 🌐 实现 ACP 协议 (#6)
8. ☁️ 实现 E2B 云沙箱 (#7)
9. 🔗 实现 Detached 运行链 (#8)
10. 🎯 优化 Replay Wildcard (#9)

---

## 📝 实施原则

1. **增量迁移**: 不破坏现有功能，逐步添加新能力
2. **接口兼容**: 新旧机制共存，逐步切换
3. **测试先行**: 关键路径必须有单元测试和集成测试
4. **文档同步**: 每个功能配套文档和使用示例
5. **性能监控**: 添加 metrics 和 profiling 点

---

## 🎯 成功标准

- [ ] 工具调用实时反馈延迟 < 100ms
- [ ] Workflow 支持 10+ 并发步骤
- [ ] Jobs 系统支持 100+ 并发任务
- [ ] Permission Presets 覆盖 90% 场景
- [ ] ACP 协议兼容至少 2 个外部 agent
- [ ] E2B 沙箱冷启动 < 5s
- [ ] 所有核心功能测试覆盖率 > 80%

---

*最后更新: 2025-01-XX*
*维护者: Octopus Team*
