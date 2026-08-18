# 深度代码级评价：octopus-agent

> 评价日期：2026-08-17 · 基于对 runtime 核心、agent 定义、记忆学习模块和测试代码的实际阅读

## 一、规划器：不是 prompt 壳，是真正的工程实现

`runtime/core/cerebrum/llm_planner.py`（26KB）不是"调 LLM 生成 JSON"的玩具，而是完整的规划子系统：

- **双实现**：`LLMPlanner`（LLM 驱动）+ `StaticPlanner`（确定性回退），LLM 不可用时系统仍可运行——生产系统的容错设计
- **依赖注入完整**：`SkillRegistry`（技能注册）、`ContextComposer`（上下文组装）、`Journal`（事件日志）、`TaskGraph`/`TaskNode`（任务图模型）——规划器接入整个运行时，不是孤岛
- **有插桩**：`trace_stage` 埋点，规划过程可观测、可审计
- **有记忆持久化**：`learned_memories` 自动落盘，失败只 warning 不崩溃——异常处理成熟

## 二、记忆系统：项目最被低估的部分

`runtime/memory/` 的分层设计（37KB 的 `experience_ledger.py` 是核心证据）：

- **五层记忆架构**：journal（事件日志）→ hemolymph（上下文组装）→ knowledge_graph（知识图谱）→ threads（线程记忆）→ learning（学习闭环）
- **学习闭环是真实代码**：`review_queue`（评审队列）、`promotion_applier`（晋升应用）、`soul_holdout`（灵魂保留集）、`turn_scoring`（回合评分）、`deep_evolution`（深度进化）——21KB-37KB 的实际实现，不是概念文档
- **工程细节到位**：`atomic_write_json`（原子写入）、`read_json_with_backup`（带备份读取）、`TenantScope`/`row_visible`（租户级安全隔离）、`_rrf`（reciprocal-rank fusion，标注 ADR-009 决策记录）
- **自动改进建议**：根据 `citation_coverage < 1.0` 或 `reliability < 0.7` 自动生成"刷新记忆"或"审查低可靠性记忆"动作——自我改进的真实实现

## 三、Agent 定义：角色系统是完整的产品层

`agents/coder/` 展示 agent 定义的完整结构：

- **profile.jsonc**：DID（去中心化身份）、templateId/templateVersion（版本管理）、character_profile（完整角色设定）、capabilities（能力开关）
- **agent-core/ 文档体系**：SOUL.md、IDENTITY.md、AGENTS.md、TOOLS.md、MEMORY.md、HEARTBEAT.md、BOOTSTRAP.md、USER.md——把 agent 当"数字生命"运营
- **SOUL.md 的 Lessons Learned 是真实的**：`mcp_fs_* tools must use persistent client instead of one-shot client — spawning new child processes repeatedly in long tasks exhausts resources and crashes the backend`——踩过坑才写得出的教训
- **26 个 agent**：coder、researcher、desktop_operator、vibe_selling、admin、aoi……多角色编排真实存在

## 四、测试质量：不是凑数，是防回归

`tests/test_subagent_event_bus.py`（11KB）展示测试成熟度：

- **autouse fixture 自动 reset**：每个测试前后重置总线状态，隔离做得好
- **精确计数断言**：`types.count("sub_started") == 1`——"恰好一次"而非"有事件就行"，防重复发布回归
- **集成测试**：mock bridge runner 验证真实链路（parent-thread → subagent → 事件回传）
- **845 个测试文件** + 后端 145 个测试全部通过

## 五、总体判断

**这是一个"把 Agent 系统当操作系统做"的项目，代码质量配得上它的文档野心。**

| 维度 | 评价 |
|---|---|
| 规划器 | 双实现 + 容错 + 可观测，生产级 |
| 记忆系统 | 五层架构 + 学习闭环 + 安全隔离，同类项目罕见 |
| Agent 定义 | 完整产品层（DID/版本/角色/工具契约），非装饰 |
| 测试 | 隔离好、断言精确、有集成测试，防回归意识强 |
| 工程纪律 | 命名迁移有兼容层、依赖有解释、提交规范 |

## 六、残余风险

1. **体量膨胀**：97 个 cerebrum 文件、37KB 的 ledger、26 个 agent——0.2.0 Beta 复杂度已接近成熟产品，维护成本持续上升
2. **验证节奏**：evolution 页面空分支 bug 说明"功能开发速度 > 验证速度"的落差仍存在
3. **单点维护**：提交历史几乎全是 `dangbei` 一人，社区化程度未知

## 一句话

文档说的"Agent OS"不是营销话术——规划、记忆、学习、安全、多角色编排都有真实的高质量代码支撑。这是同类开源项目里少见的"文档与实现匹配"的项目。
