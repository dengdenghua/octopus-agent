# 过度设计收敛：默认值单一来源、Deadline 聚合、配置去冗余

## Why

审计发现项目存在两类过度设计：**镜像式重复**（同一预算默认值在 6 个文件、8 处硬编码，改一处需同步全部）与**分层式冗余**（为"防模型静默思考跑死"一个目标建了 4 套超时机制 + 模块级可变全局来自洽测试）。这些不产生新能力，只增加维护风险与心智负担。本 spec 用"单一事实来源 + 聚合替代分层 + 精简配置"收敛。

## What Changes

### Delta 1 · 预算默认值收敛为单一来源（P0）
- 在 `runtime/platform/config/schema.py` 定义**唯一权威默认值常量**，`BudgetConfig` 的 Field 默认值引用这些常量
- 删除 `presets.py` / `pause_control.py` / `react_loop.py` / `cli_run.py` 中镜像同一数字的硬编码，改为引用权威常量（或省略、回退到 schema 默认）
- 保留各 preset 的**差异化**覆盖（如 `max_usd=2.00`、`max_tokens=500000`），仅移除与默认值重影的字段

### Delta 2 · Deadline 分层聚合（P1）
- 将 `react_model_deadlines.py` 中 `_model_recovery_timeout_s` / `_model_post_tool_timeout_s` / `_model_evidence_synthesis_timeout_s` 三个同构函数聚合为一个 `ModelDeadlinePolicy`（或纯函数 `_stage_model_timeout_s(base, stage)`）
- 更新 `react_model_stream.py:204-208` 调用点
- 保留 `_model_iteration_timeout_s` 作为基础超时（转为 config 读取）

### Delta 3 · 配置去冗余 + 移除模块级 setter（P2）
- 移除 `_MODEL_ITERATION_TIMEOUT_S_CONFIG` 模块级全局与 `_set_model_iteration_timeout_s()`，改为显式依赖注入
- 配置收敛为 **config 一层**：删除 `OCTOPUS_REACT_MODEL_ITERATION_TIMEOUT_S` 等 env var override，仅保留 `budget.model_iteration_timeout_s`
- `react_loop.py` 中 `_set_model_iteration_timeout_s` 调用点改为读取并传递局部值

## Impact
- Affected specs: 预算（budget）、ReAct 收敛（cerebrum）
- Affected code:
  - `runtime/platform/config/schema.py`、`presets.py`
  - `runtime/core/cerebrum/react_model_deadlines.py`、`react_model_stream.py`、`react_loop.py`、`pause_control.py`
  - `runtime/cli_run.py`
  - 相关测试：`tests/test_react_model_deadlines.py`、`tests/test_react_loop.py`、`tests/test_config.py`、`tests/test_budget.py`

## ADDED Requirements

### Requirement: 预算默认值单一权威来源
系统 SHALL 在 `schema.py` 定义唯一权威预算默认值，所有镜像点引用同一常量而非各自硬编码。

#### Scenario: 修改默认预算
- **WHEN** 需要调整预算默认值
- **THEN** 只需修改 `schema.py` 一处，其余模块自动跟随

### Requirement: Deadline 分层聚合
系统 SHALL 提供单一 `ModelDeadlinePolicy` 抽象，按阶段返回超时，替代多个同构独立函数。

#### Scenario: 阶段超时解析
- **WHEN** 某轮需要 recovery / post-tool / evidence-synthesis 超时
- **THEN** 通过策略按阶段计算，行为与拆分前一致

### Requirement: 配置收敛为 config 一层
系统 SHALL 仅通过 `budget.model_iteration_timeout_s` 配置模型迭代超时，不依赖环境变量或模块级全局。

#### Scenario: 调整迭代超时
- **WHEN** 运维通过 YAML 设置 `budget.model_iteration_timeout_s`
- **THEN** 生效且无全局副作用，测试通过参数注入而非 monkeypatch 全局

## MODIFIED Requirements

### Requirement: BudgetConfig 默认值
`BudgetConfig` 仍为权威默认，新增模块级常量供其它模块引用，行为与当前默认值一致（max_tokens=100000、max_usd=1.00、max_latency_ms=600000、model_iteration_timeout_s=120、convergence_max_tokens=2000）。

## REMOVED Requirements

### Requirement: 模块级迭代超时全局
**Reason**: 为测试 monkeypatch 而设的共享可变全局，引入时序耦合。
**Migration**: 改为显式参数注入 `_finalize_react_turn` / `_phase_6b_model_stream`。

### Requirement: 各镜像点硬编码预算默认值
**Reason**: 同一数字多处硬编码，改一处漏 N 处。
**Migration**: 改为引用 `schema.py` 权威常量。

### Requirement: 环境变量超时 override
**Reason**: 配置三层堆叠（env > config > 默认）假设了不存在的受众。
**Migration**: 收敛为 config 一层 `budget.model_iteration_timeout_s`。