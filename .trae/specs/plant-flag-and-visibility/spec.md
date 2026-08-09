# 立旗文档 + 可见性原语 Spec

## Why

此前四家"仿生架构"对比（OCT-Agent 八臂+记忆、octopus-agent runtime+黑板+物理在场、明略 Octo 组织协作、腾讯 Octop 多用户助手）结论是"谁更仿生谁更好"。但当前项目缺少一份对外立旗的竞争叙事文档，且 Agent 内部关键决策（为什么激活了这些能力、为什么委派工具可见/不可见、为什么技能目录被截断）对用户完全不可见——正是最近"派生子 agent 为什么没派生""总是硬编码验证提示"等痛点的根源。

本 spec 落地两条最高优先级路径：
1. **立旗文档**：写一份竞品对比 + 差异化叙事的旗标文档，把"仿生架构"从口号变成可核查的立场。
2. **可见性原语**：把 Agent 内部决策变成可观测、可解释的可见产物（why 链），后端记录、前端弱化展示。

## What Changes

- 新增立旗文档 `docs/vision/flag-document.md`：仿生竞品对比矩阵（4 家）、"谁更仿生"证据清单（每条映射到真实代码路径）、5 条超越路径与优先级、需要持续更新的跟踪清单。
- 新增后端可见性 trace 采集模块 `runtime/core/cerebrum/_visibility_trace.py`：统一的 `VisibilityTrace` 接口，记录"决策点 → 依据 → 结论"。
- 在三个关键决策点接入 trace：
  - `activate_capabilities`（capability_router.py）：记录每个激活标签及其命中依据（mode / 关键词）。
  - `_delegation_cap`（_react_context_helpers.py）：记录委派工具（call_agent_parallel / bb_*）暴露或隐藏的原因。
  - `_format_skill_catalog`（_react_context_helpers.py）：记录技能目录总数、保留数、截断数及依据（pinned / TF-IDF 选择）。
- 可见性 trace 随回合事件流推送（`item/visibility` 事件）并持久化到 thread JSONL，可回放。
- 前端工作台右栏新增"可见性"面板：弱化默认展示（折叠、小字、透明底，符合既有 UI 偏好），展示最近一轮的 why 链。

**BREAKING**: 无。所有改动为增量。

## Impact

- Affected specs: 仿生架构（docs/vision/）、Realtime Workbench 事件流、能力路由（Capability Router）、上下文组装（_react_context_helpers）
- Affected code:
  - `docs/vision/flag-document.md`（新增）
  - `runtime/core/cerebrum/_visibility_trace.py`（新增）
  - `runtime/core/cerebrum/capability_router.py`
  - `runtime/core/cerebrum/_react_context_helpers.py`
  - `runtime/sensing/gateway/_realtime_react_stream_apply.py`（item/visibility 事件映射）
  - `frontend/src/components/workspace/`（可见性面板）
  - `frontend/src/components/workspace/agent-workbench-utils.ts`（tab 类型，如需新 tab）

## ADDED Requirements

### Requirement: 立旗文档

系统 SHALL 提供一份描述项目仿生架构竞争立场的文档 `docs/vision/flag-document.md`。

#### Scenario: 竞品对比矩阵
- **WHEN** 读者打开立旗文档
- **THEN** 文档包含 4 家竞品（OCT-Agent、明略 Octo、腾讯 Octop、octopus-agent 自身）的对比矩阵，覆盖仿生程度、记忆、组织协作、物理在场等维度

#### Scenario: 证据可核查
- **WHEN** 文档声称某项能力（如黑板、runtime、委派、技能目录）
- **THEN** 每条主张均映射到仓库内真实代码路径（以相对路径引用），不允许编造未实现能力

#### Scenario: 超越路径与优先级
- **WHEN** 读者查看文档的路径章节
- **THEN** 文档列出 5 条超越路径并标注优先级，且本 spec 落实的前两条（立旗、可见性）标为最高优先级

### Requirement: 可见性 trace 采集

系统 SHALL 在关键决策点记录结构化 why 链（决策点、依据、结论），供回放与前端展示。

#### Scenario: 能力激活可解释
- **WHEN** 一轮 turn 构建时调用 `activate_capabilities`
- **THEN** trace 记录每个激活标签及其命中依据（mode 命中或命中的关键词），且不改变原有激活结果（纯增量记录）

#### Scenario: 委派能力可见性可解释
- **WHEN** `_delegation_cap` 计算委派工具是否进入前置职位列表
- **THEN** trace 记录判定结果（暴露/隐藏）与原因（标签命中 / mode=code / agent_mode=audit / 均未命中）

#### Scenario: 技能目录截断可解释
- **WHEN** `_format_skill_catalog` 因 `max_skills` 截断技能目录
- **THEN** trace 记录技能总数、保留数、截断数，以及保留依据（pinned 优先 / TF-IDF 选择）

### Requirement: 可见性事件流与持久化

系统 SHALL 将每轮 trace 作为事件推送并持久化。

#### Scenario: 事件推送
- **WHEN** turn 流式运行期间产生 trace 记录
- **THEN** 通过现有事件桥发出 `item/visibility` 通知，前端可实时消费

#### Scenario: 持久化回放
- **WHEN** 一轮 turn 结束
- **THEN** trace 写入该 thread 的 JSONL（EventLog 能力），后续可回放查看历史 why 链

### Requirement: 前端可见性面板

系统 SHALL 在工作台右栏提供"可见性"面板展示最近一轮的 why 链。

#### Scenario: 弱化默认展示
- **WHEN** 用户打开工作台右栏
- **THEN** 可见性面板默认折叠、小字、透明底，不打扰主流程；用户点击展开查看

#### Scenario: 展示内容
- **WHEN** 用户展开可见性面板
- **THEN** 面板按时间顺序展示最近一轮的能力激活、委派决策、技能截断等条目，每条含结论与依据
