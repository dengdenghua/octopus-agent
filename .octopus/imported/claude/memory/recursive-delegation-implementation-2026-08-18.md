---
name: recursive-delegation-implementation-2026-08-18
description: 三阶段递归委派系统实现完成，支持深度为2的层级代理spawning、预算传播、角色指导注入和前端嵌套显示
metadata: 
  node_type: memory
  type: project
  originSessionId: 149c79d4-2dc0-4586-b126-5aee8ac7e050
  modified: 2026-08-17T18:39:46.872Z
---

## 递归委派系统实现 (2026-08-18)

完成了 octopus-agent 的三阶段递归委派系统，允许子代理生成自己的子代理，最大深度为 2（共 3 层：0→1→2）。

### 三个阶段全部完成

**Phase 1: 核心递归委派逻辑** ✅
- 深度控制：`MAX_DELEGATION_DEPTH = 2`
- 预算传播：每层在兄弟间平分后减半（100k → 25k → 6.25k）
- 条件技能注册：只在允许深度注册 `call_agent_parallel`
- 6 个后端测试全部通过

**Phase 2: 角色专属委派指导** ✅
- 5 个角色（reviewer/researcher/implementer/critic/architect）各有专属指导
- 指导包含：分解维度、编排模式、最佳实践
- 条件注入：仅在 `allow_subdelegation=True` 时注入系统提示词
- 5 个后端测试全部通过

**Phase 3: 前端嵌套显示** ✅
- 发现 `parent_tool_use_id` 已在后端事件中流动，无需修改后端
- 新组件 `NestedAgentTree` 递归渲染代理层级树
- 功能：展开/折叠、深度缩进、状态指示器、排序、选择
- 11 个前端测试全部通过（修复了嵌套按钮的 HTML 合规性问题）

### 关键实现细节

**后端深度传播**（`_delegation_skills_parallel.py`）:
```python
parent_depth = context.get("delegation_depth", 0)
next_depth = parent_depth + 1
can_spawn = next_depth < MAX_DELEGATION_DEPTH  # 2
call_context["delegation_depth"] = next_depth
call_context["allow_subdelegation"] = can_spawn and spec.get("allow_subdelegation")
```

**预算分配公式**:
- Level 0: `B`
- Level 1: `B / N / 2` （N 个兄弟）
- Level 2: `B / (4NM)` （M 个兄弟）

**前端树构建**（`nested-agent-tree.tsx`）:
```typescript
function buildAgentTree(tiles: AgentTile[]): AgentNode[] {
  // 通过 parentToolUseId 构建父子关系
  // 按 startedAt 排序兄弟节点
  // 递归构建深度信息
}
```

**数据流完整链路**:
```
bridge.py (parent_tool_use_id in events)
  → Realtime Gateway (WebSocket)
    → use-thread-stream-realtime.ts (map to parentItemId)
      → AgentTile[] (parentToolUseId)
        → NestedAgentTree (buildAgentTree)
```

### 新增文件清单

**后端 (4 个文件)**:
- `runtime/execution/suckers/role_delegation_guidance.py` - 5 个角色的委派指导
- `tests/test_recursive_delegation_poc.py` - Phase 1 核心逻辑测试（6 tests）
- `tests/test_delegation_guidance_phase2.py` - Phase 2 指导注入测试（5 tests）
- `tests/test_recursive_delegation_e2e.py` - 端到端集成测试（6 tests）

**前端 (2 个文件)**:
- `frontend/src/components/workspace/agent-workbench-panel/nested-agent-tree.tsx` - 嵌套树组件
- `frontend/src/components/workspace/agent-workbench-panel/nested-agent-tree.test.tsx` - 组件测试（11 tests）

**文档 (1 个文件)**:
- `docs/recursive-delegation-implementation.md` - 完整实现文档

**修改的文件 (4 个)**:
- `runtime/execution/suckers/ephemeral_runner.py` - 添加深度限制和条件注册
- `runtime/execution/suckers/delegation_skills.py` - 更新注册函数
- `runtime/execution/suckers/_delegation_skills_parallel.py` - 深度/预算/指导传播
- `runtime/execution/suckers/ephemeral_agents.py` - 系统提示词注入

### 测试覆盖

**总计 28 个测试**:
- 后端单元测试: 17 个（Phase 1: 6 + Phase 2: 5 + E2E: 6）
- 前端单元测试: 11 个（Phase 3）
- 所有测试状态: ✅ 通过

**前端测试执行**: `pnpm test nested-agent-tree.test.tsx --run`
**后端测试执行**: `make test-unit` (包含所有新测试)

### 使用示例

```python
# 用户提示词（启用 ultracode）
"审查认证系统的安全问题。预算: 200k tokens。"

# Root agent (depth=0, budget=200k) 生成 5 个并行审计:
call_agent_parallel([
    {"agent_id": "reviewer", "prompt": "审计认证和授权", 
     "allow_subdelegation": True},  # 可以继续生成子审计
    {"agent_id": "reviewer", "prompt": "审计注入攻击",
     "allow_subdelegation": True},
    # ... 3 个更多并行通道
])

# 每个 level-1 reviewer (depth=1, budget=20k) 可以生成:
call_agent_parallel([
    {"agent_id": "researcher", "prompt": "研究 JWT 漏洞",
     "allow_subdelegation": True},  # 可以继续生成
    {"agent_id": "code_reviewer", "prompt": "审查 authentication.py",
     "allow_subdelegation": False},  # 终端节点
])

# Level-2 agents (depth=2, budget=5k):
# - 不能再生成（深度限制）
# - 提示词中无委派指导
# - 执行聚焦任务并返回
```

### Why: 解决了什么问题

1. **扇出限制突破**: 之前单层 `call_agent_parallel` 限制为 5-10 个代理，现在可以通过递归实现 5×5=25 个 L1+L2 代理
2. **自然任务分解**: 复杂任务可以按照自然层级分解（审计→维度→具体检查）
3. **预算智能分配**: 自动在层级间分配 token 预算，防止单个分支耗尽
4. **角色专业化**: 每个角色知道如何有效地委派给下级
5. **可视化层级**: 前端清晰展示代理树结构和状态

### How to apply: 如何启用

**立即生效**: 所有修改向后兼容，不需要配置。

**使用递归委派**:
1. 在 `call_agent_parallel` 中设置 `allow_subdelegation: True`
2. 确保有足够的 `subdelegation_budget`（通过 ultracode 或显式设置）
3. 子代理自动获得委派能力（如果深度允许）

**调整深度限制**: 修改 `runtime/execution/suckers/ephemeral_runner.py` 中的 `MAX_DELEGATION_DEPTH`

**添加新角色指导**: 在 `runtime/execution/suckers/role_delegation_guidance.py` 中添加条目

### 兼容性与限制

**向后兼容**: ✅
- 现有代码无需修改
- 不设置 `allow_subdelegation` 时行为与之前完全一致
- 深度限制防止意外的无限递归

**已知限制**:
- 最大深度硬编码为 2（可配置）
- 预算分配策略固定（平分+减半）
- 无循环检测（A→B→A）
- 前端组件未集成到 workbench（需要后续 PR）

**性能考虑**:
- 3 层深度、每层 5 个代理 = 最多 5 + 25 + 125 = 155 个代理
- 建议在 ultracode 模式下使用（明确的高预算场景）
- token 消耗会快速增长（指数级）

### 后续工作

1. **集成到 workbench**: 将 `NestedAgentTree` 集成到现有的 agent workbench 面板
2. **实际 LLM 测试**: 用真实模型验证指导的有效性
3. **预算调优**: 根据实际使用调整分配比例
4. **进度聚合**: 在树节点上展示子树的总进度
5. **循环检测**: 防止代理相互递归生成

### 参考链接

- **完整文档**: `docs/recursive-delegation-implementation.md`
- **内存条目**: `ultracode-fanout-live-verified.md`（之前的单层扇出实现）
- **架构文档**: `docs/architecture/module-map.md`
