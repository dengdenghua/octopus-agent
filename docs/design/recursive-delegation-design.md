# 递归委派设计方案（Recursive Delegation）

## 问题陈述

**当前限制**：子代理（ephemeral runner）无法再次委派任务，导致：
- 主代理必须预先规划所有细粒度任务（如 204 个具体检查项）
- 子角色沦为"带标签的函数调用"，专业能力无法发挥
- 无法实现"给维度让子代理自主展开"的层次化编排

**目标**：让子代理获得有限的委派能力，支持 2 层递归：
```
主代理 (planner)
  └─ Security Reviewer (ephemeral, depth=1)
       ├─ 认证模块审计 (ephemeral, depth=2)
       ├─ 注入扫描 (ephemeral, depth=2)
       └─ 密钥管理审计 (ephemeral, depth=2)
```

---

## 核心设计

### 1. 深度控制

```python
# 新增常量
MAX_DELEGATION_DEPTH = 2  # 主代理=0，子代理=1，孙代理=2

# call.context 增加字段
context = {
    "delegation_depth": 1,  # 当前深度
    "parent_agent_id": "security_reviewer",  # 父代理 ID
    "orchestration_token_budget": 50000,  # 可用预算
    "subdelegation_budget": 20000,  # 可分配给子代理的预算
}
```

### 2. 条件注册委派技能

```python
# ephemeral_runner.py:make_llm_ephemeral_runner

def _runner(call: Any) -> str:
    ctx = getattr(call, "context", None) or {}
    depth = ctx.get("delegation_depth", 0)
    allow_subdelegation = ctx.get("allow_subdelegation", False)
    
    # 动态注册委派技能
    local_registry = registry
    if allow_subdelegation and depth < MAX_DELEGATION_DEPTH and registry:
        local_registry = _clone_registry_with_delegation(
            registry,
            depth=depth,
            budget=ctx.get("subdelegation_budget", 0),
            parent_id=call.role_id,
        )
    
    # 后续使用 local_registry 而非 registry
    ...
```

### 3. 预算传递与扣减

```python
# delegation_skills.py:call_agent_parallel

def call_agent_parallel(nodes, context):
    parent_budget = context.get("subdelegation_budget", 0)
    if parent_budget <= 0:
        raise ValueError("No subdelegation budget available")
    
    # 平均分配给子节点（简化版）
    per_node_budget = parent_budget // len(nodes)
    
    for node in nodes:
        node_context = {
            **context,
            "delegation_depth": context.get("delegation_depth", 0) + 1,
            "orchestration_token_budget": per_node_budget,
            "subdelegation_budget": per_node_budget // 2,  # 递归预留
            "parent_agent_id": context.get("agent_id"),
        }
        # spawn with node_context
        ...
```

### 4. 角色专属 system prompt

```python
# agents/security_reviewer/profile.jsonc
{
  "name": "Security Reviewer",
  "delegation_system_prompt": """你是安全审计专家。

你可以使用 call_agent_parallel 将工作拆分为并行子任务。建议拆分维度：
- 认证授权模块审计
- 注入攻击面扫描
- 密钥和敏感数据管理
- API 权限边界检查

每个子任务应该是独立的审计维度，不要过度拆分。""",
  "allowed_tools": ["Read", "Bash", "grep", "call_agent_parallel"],
  "max_subdelegation_spawns": 5
}
```

```python
# runtime/platform/roles/role_loader.py

def load_role_system_prompt(role_id: str, context: dict) -> str:
    profile = load_profile(role_id)
    base_prompt = profile.get("system_prompt", DEFAULT_EPHEMERAL_PROMPT)
    
    # 如果允许子委派，附加委派指导
    if context.get("allow_subdelegation"):
        delegation_prompt = profile.get("delegation_system_prompt", "")
        if delegation_prompt:
            base_prompt = f"{base_prompt}\n\n{delegation_prompt}"
    
    return base_prompt
```

### 5. 进度展示（嵌套树）

前端 `AgentWorkbench` 显示层级关系：

```typescript
interface AgentNode {
  id: string;
  role: string;
  status: "running" | "completed" | "failed";
  depth: number;  // 新增
  parentId: string | null;  // 新增
  children: AgentNode[];  // 新增
}

// 渲染为可折叠树
<AgentCard agent={node}>
  {node.children.length > 0 && (
    <div className="ml-6 border-l-2">
      {node.children.map(child => (
        <AgentCard key={child.id} agent={child} />
      ))}
    </div>
  )}
</AgentCard>
```

---

## 实施路径

### Phase 1: 最小 PoC（验证可行性）

**范围**：只支持 depth=1 子代理委派，不动前端。

**改动文件**：
1. `runtime/execution/suckers/ephemeral_runner.py`
   - 增加 `_clone_registry_with_delegation` 函数
   - 在 `_runner` 里条件注册 `call_agent_parallel`

2. `runtime/execution/suckers/delegation_skills.py`
   - `call_agent_parallel` 增加 depth 和 budget 传递

3. `tests/test_recursive_delegation.py` (新增)
   - 端到端测试：主代理 → Security Reviewer → 3 个子审计

**验收标准**：
- Security Reviewer 能成功 spawn 3 个子代理
- 子代理返回结果正确聚合到 Security Reviewer
- 预算扣减正确（孙代理不超父代理配额）

### Phase 2: 角色 system prompt（赋予专业性）

**改动文件**：
1. `agents/security_reviewer/profile.jsonc`
   - 增加 `delegation_system_prompt` 字段

2. `runtime/platform/roles/role_loader.py`
   - `load_role_system_prompt` 函数增加委派提示拼接逻辑

3. 同步更新其他核心角色：
   - `agents/code_reviewer/`
   - `agents/architect/`
   - `agents/researcher/`

**验收标准**：
- Security Reviewer 的 system prompt 包含委派指导
- 子代理能看到"你是 X 专家"的角色定义

### Phase 3: 前端嵌套展示

**改动文件**：
1. `frontend/src/components/workspace/agent-workbench-panel/nested-agent-tree.tsx` (新增)
   - 递归渲染 AgentCard

2. `frontend/src/core/realtime/reducer.ts`
   - 增加 `parentAgentId` 字段处理
   - 构建树形结构

3. `runtime/platform/realtime/event_emitter.py`
   - 子代理事件携带 `parent_agent_id`

**验收标准**：
- 工作台显示树形层级（可折叠）
- 点击子代理能看到其专属转录
- 进度百分比正确聚合

### Phase 4: 安全加固与限制

**改动**：
1. 深度超限保护
2. 预算透支保护（子代理总和不超父预算）
3. 循环委派检测（A 派 B，B 不能再派 A）
4. 审计日志（记录委派链路）

---

## 风险与缓解

### R1: 递归失控（无限套娃）

**缓解**：
- 硬编码 `MAX_DELEGATION_DEPTH = 2`
- 每层预算递减（子代理拿父代理的 50%）
- 超时继承（孙代理不能超父代理剩余时间）

### R2: 预算透支

**缓解**：
- 子代理 spawn 前检查 `subdelegation_budget`
- 实际消耗 token 从父预算扣除
- 超预算时提前终止，返回 partial

### R3: 进度不可见（黑盒）

**缓解**：
- Phase 3 前端嵌套树
- 每层子代理的事件独立推送
- 支持"展开子代理详情"交互

### R4: 兼容性破坏

**缓解**：
- 默认 `allow_subdelegation=False`（向后兼容）
- 只有显式标记的节点才获得委派能力
- 旧代码路径零改动

---

## 对比 Claude Code Workflow

| 维度 | octopus 方案 A | Claude Code |
|------|---------------|-------------|
| 递归深度 | 硬限制 2 层 | 无显式限制（token 自然约束） |
| 预算控制 | 层级配额分配 | 全局共享池 |
| 角色定义 | profile.jsonc + system_prompt | .claude/agents/*.md |
| 编排原语 | call_agent_parallel | agent() / parallel() / pipeline() |
| 进度展示 | 嵌套树（工作台） | CLI 进度树 + journal |

**octopus 的优势**：
- GUI 可视化更直观
- 预算分配更精细（避免子代理抢占）

**octopus 的劣势**：
- 深度限制更严（2 vs 无限）
- 编排原语更少（只有 parallel，没有 pipeline/sequential）

---

## 下一步

1. **立即执行**：Phase 1 PoC（今天下午完成）
2. **本周完成**：Phase 2 角色 prompt
3. **下周排期**：Phase 3 前端展示
4. **持续优化**：Phase 4 安全加固

预计总工程量：**3-4 天**（含测试 + 文档）。
