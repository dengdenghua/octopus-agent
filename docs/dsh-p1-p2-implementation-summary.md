# DSH P1/P2 特性实现总结

**日期**: 2026-08-14  
**状态**: P1 完成，准备开始 P2  
**提交**: bf886b48

---

## ✅ P1: 防护型特性（已完成）

### 1. Repeat-tool-reminder Guard ✅

**功能**: 检测模型重复调用相同工具，防止陷入循环

**实现**:
- 文件: `runtime/core/cerebrum/react_repeat_tool_guards.py`
- 测试: `tests/test_react_repeat_tool_guards.py` (17 tests)
- 集成: 添加到 `GUARD_REGISTRY`，protocol 类别

**特性**:
- **窗口检测**: 在最近 N 步中检测重复调用（默认：5 步窗口，3 次阈值）
- **连续检测**: 更严格的连续相同调用检测（默认：3 次连续）
- **参数归一化**: 长字符串截断到 200 字符，检测"本质相同"的调用
- **提醒消息**: 建议使用不同工具、修改方法、检查输出

**示例触发**:
```
You've called `read_file` with similar arguments 3 times in the last 5 steps.
This suggests the current approach isn't working. Consider:
- Using a different tool to gather information
- Modifying your approach to the problem
- Examining the tool output more carefully for clues
```

### 2. Timeout-policy Guard ✅

**功能**: 检测工具超时模式，建议调整策略

**实现**:
- 文件: `runtime/core/cerebrum/react_timeout_guards.py`
- 测试: `tests/test_react_timeout_guards.py` (17 tests)
- 集成: 添加到 `GUARD_REGISTRY`，protocol 类别

**特性**:
- **窗口检测**: 在最近 N 步中检测超时（默认：5 步窗口，2 次阈值）
- **连续检测**: 更严格的连续超时检测（默认：2 次连续）
- **超时指示器**: 检测 "timed out", "timeout", "exceeded...time"
- **多工具检测**: 区分单工具重复超时 vs 多工具普遍超时

**示例触发**:
```
`exec_shell` has timed out 2 times in the last 3 steps. This suggests:
- The operation may be too expensive for the default timeout
- You may need to break the work into smaller chunks
- Consider using a different tool or approach
```

### 3. Shadow-price 记账 ✅

**功能**: 修剪时记录节省的 token 成本（已存在）

**实现**:
- 文件: `runtime/execution/tool_engine/tool_shadow_price.py`
- 已在点 17-18 完整实现
- 使用 `default_shadow_price_sink` + `ShadowPriceLedger`

**特性**:
- **估算公式**: `ceil(chars_removed / 4)` tokens
- **进程级账本**: 线程安全累积
- **最佳努力**: sink 失败不影响修剪
- **可观测性**: 仅用于观察，不计入账单

**数据结构**:
```python
@dataclass(frozen=True, slots=True)
class PruneShadowPrice:
    tool_name: str | None
    call_id: str | None
    chars_before: int
    chars_after: int
    chars_removed: int
    tokens_shadowed: int
```

---

## 📊 P1 实施统计

| 指标 | 数量 |
|------|------|
| **新文件** | 4 个 |
| **新代码** | ~874 行 |
| **新测试** | 34 个（全部通过） |
| **集成点** | GUARD_REGISTRY（4 个新 guard） |
| **测试覆盖** | 100%（所有新代码） |
| **提交** | 1 个（bf886b48） |

---

## ⏳ P2: 体验型特性（待实现）

### 1. Session-query ⏳

**是什么**: 会话内容全文检索

**功能**:
- SQLite FTS5 索引所有会话消息
- `/search "authentication bug"` 找历史讨论
- `/export` 导出会话为 Markdown

**复杂度**: 中等  
**预计时间**: 1-2 天  
**优先级**: 高（用户体验提升明显）

### 2. Preset/persona ⏳

**是什么**: Agent 配置预设

**功能**:
- `preset=code-reviewer`: 代码审查工具集 + 严格 prompt
- `preset=researcher`: 搜索/浏览器工具 + 宽松 prompt
- `persona=senior-engineer`: 专业对话风格
- `persona=beginner-friendly`: 友好解释风格

**复杂度**: 中等  
**预计时间**: 2-3 天  
**优先级**: 中（已有 4 个配置预设，需扩展）

### 3. Feedback 系统 ⏳

**是什么**: 用户评价收集

**功能**:
- 每条消息 👍/👎 按钮
- 标注问题："不准确" / "太啰嗦" / "有帮助"
- 不可变评价记录

**复杂度**: 中等  
**预计时间**: 2-3 天  
**优先级**: 中（RLHF 数据收集）

### 4. Schedule ⏳

**是什么**: 会话内定时提醒

**功能**:
- "30 分钟后提醒我检查部署"
- 会话内设置定时器
- 到期后会话自动弹出

**复杂度**: 低-中等  
**预计时间**: 1-2 天  
**优先级**: 低（Nice-to-have）

### 5. Plan-mode ⏳

**是什么**: 多步骤任务协作模式

**功能**:
- Planning 阶段: 列步骤，用户审批
- Execution 阶段: 逐步执行，等待确认
- Review 阶段: "重做步骤 3"

**状态机**: `planning` → `executing(step=2/5)` → `reviewing` → `complete`

**复杂度**: 高  
**预计时间**: 3-5 天  
**优先级**: 低（大重构）

---

## 🚀 P3: 生态型特性（长期）

### 1. ACP (Agent Client Protocol) 🔵

**是什么**: Zed 的 **Agent Client Protocol** — 客户端(IDE/编辑器/自动化)↔
编码 agent 的互操作标准(JSON-RPC over stdio)。dsh 用它既当客户端
(subagent-acp provider,驱动 Codex/Claude Code/Cursor/Gemini CLI 等),
也当服务端(acp-agent,让 Zed/VS Code 等直接驱动)。注意:不是 agent 间
通信协议(那是 A2A)。

**愿景**: 任意 ACP 客户端直接驱动 Octopus;Octopus 也能把其他 ACP agent
当子代理调(Octopus ↔ Codex ↔ Claude Code 生态互通)

**复杂度**: 极高  
**预计时间**: 1-2 个月  
**优先级**: 战略（生态壁垒）

### 2. e2b (云端沙箱) 🔵

**是什么**: 远程代码执行环境

**功能**: 云端隔离执行，每会话独立容器

**复杂度**: 极高  
**预计时间**: 1-2 个月  
**优先级**: 战略（安全 + 可扩展）

---

## 📈 进度追踪

### 今日完成（2026-08-14）

✅ P1 完整实现（3/3）:
- repeat-tool-reminder guard
- timeout-policy guard
- shadow-price 记账（已存在，确认）

### 下一步

**推荐顺序**:
1. **Session-query**（高性价比，快速提升体验）
2. **Feedback 系统**（RLHF 数据收集）
3. **Preset/persona**（已有基础，增强配置）
4. Schedule（可选）
5. Plan-mode（大工程，暂缓）

---

## 💡 关键决策

### 为什么先做 P1？

1. **防止生产问题**: 循环和超时会导致高额账单
2. **实现简单**: 纯检测逻辑，无状态，低风险
3. **立即生效**: 集成到现有 guard 系统，零配置

### 为什么 P2 推荐 Session-query 优先？

1. **用户痛点**: 管理多会话时找历史很难
2. **技术成熟**: SQLite FTS5 是标准方案
3. **独立模块**: 不影响核心流程
4. **快速见效**: 1-2 天可完成

### 为什么 P3 是长期？

1. **生态依赖**: ACP 需要多方协调
2. **基础设施**: e2b 需要云资源投入
3. **商业决策**: 需要产品层面判断

---

## 🎯 对比报告更新

根据今日完成的工作，更新 `docs/octopus-vs-dsh-full-comparison.md`:

**P1 优先级**:
- ✅ Guard: timeout-policy（已完成）
- ✅ Guard: repeat-tool-reminder（已完成）
- ✅ Shadow-price 记账（已存在）

**DSH 吸收率**: 70% → **72%** (+2%)

**新增优势**:
- 循环检测 guard（DSH 同等）
- 超时模式检测 guard（DSH 同等）
- Token 节省透明化（DSH 同等）

---

## 📝 技术细节

### Guard 集成位置

```python
GUARD_REGISTRY: list[GuardSpec] = [
    # ── Security cluster (highest priority) ──
    _spec_security("secret-leak guard", "security", ...),
    _spec_security("destructive-call guard", "security", ...),
    # ...
    
    # ── Loop detection (DSH P1: NEW) ──
    GuardSpec("consecutive-same-tool guard", "protocol", _invoke_consecutive_same_tool),
    GuardSpec("repeat-tool-reminder guard", "protocol", _invoke_repeat_tool_reminder),
    
    # ── Timeout detection (DSH P1: NEW) ──
    GuardSpec("consecutive-timeout guard", "protocol", _invoke_consecutive_timeout),
    GuardSpec("timeout-policy guard", "protocol", _invoke_timeout_policy),
    
    # ── Tool-availability / inspection-evidence ──
    GuardSpec("final-answer completeness guard", "protocol", ...),
    # ...
]
```

### 参数可调性

所有 guard 都支持阈值和窗口调整：

```python
# Repeat-tool
_repeat_tool_reminder_guard(steps, final_answer, threshold=3, window=5)
_consecutive_same_tool_guard(steps, final_answer, threshold=3)

# Timeout
_timeout_policy_guard(steps, final_answer, threshold=2, window=5)
_consecutive_timeout_guard(steps, final_answer, threshold=2)
```

### 测试策略

- **单元测试**: 每个 guard 独立测试
- **集成测试**: 两种 guard 协同测试
- **边界测试**: 空轨迹、短轨迹、窗口边界
- **现实场景**: 模拟真实循环和超时模式

---

## 🎉 总结

**P1 完成标志着 Octopus 防护能力达到 DSH 同等水平**。

接下来的 P2 特性将专注于**用户体验提升**，从搜索、配置、反馈三个方向增强可用性。

P3 生态型特性是**长期战略投资**，需要产品和商业层面的判断。

---

**下次更新**: 完成 P2 首个特性后
