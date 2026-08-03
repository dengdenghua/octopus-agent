# Tasks

## Delta 1 · 预算默认值收敛为单一来源（P0）

- [x] Task 1.1: 在 schema.py 定义权威默认值常量
  - [x] 新增模块级常量（`BUDGET_DEFAULT_MAX_TOKENS` / `BUDGET_DEFAULT_MAX_USD` / `BUDGET_DEFAULT_MAX_LATENCY_MS`），`BudgetConfig` Field 默认值引用这些常量
  - [x] 保持默认值不变（max_tokens=100000、max_usd=1.00、max_latency_ms=600000、model_iteration_timeout_s=120、convergence_max_tokens=2000）

- [x] Task 1.2: 消除镜像硬编码
  - [x] `pause_control.py`：`ActiveTask.max_tokens`/`max_usd` 默认值改为引用权威常量
  - [x] `react_loop.py`：`max_tokens_budget`/`max_usd_budget` 函数默认值改为引用权威常量
  - [x] `cli_run.py`：CLI 默认值改为引用权威常量
  - [x] `presets.py`：移除与 schema 默认值重影的字段，保留差异化覆盖

- [x] Task 1.3: 验证
  - [x] `pytest tests/test_config.py tests/test_budget.py` 通过
  - [x] `tests/test_react_loop.py` 通过
  - [x] 确认 `AgentConfig()` 默认值与修改前一致

## Delta 2 · Deadline 分层聚合（P1）

- [x] Task 2.1: 实现 ModelDeadlinePolicy
  - [x] 在 `react_model_deadlines.py` 新增纯函数 `_stage_model_timeout_s(base, stage)`，合并三个同构函数
  - [x] 保持各阶段 ceiling 语义一致（recovery≤60、post-tool≤90、evidence-synthesis≤120，均受 base 约束）
  - [x] 移除被合并的三个独立函数

- [x] Task 2.2: 更新调用点
  - [x] `react_model_stream.py` 调用点改为调用聚合策略
  - [x] 检查 `react_model_deadlines.py` 内部及 runtime 全部引用并更新

- [x] Task 2.3: 验证
  - [x] `pytest tests/test_react_loop.py` 通过
  - [x] 确认阶段超时行为与拆分前一致

## Delta 3 · 配置去冗余 + 移除模块级 setter（P2）

- [x] Task 3.1: 移除模块级全局与 setter
  - [x] 删除 `_MODEL_ITERATION_TIMEOUT_S_CONFIG` 全局与 `_set_model_iteration_timeout_s()`
  - [x] `react_loop.py` 中 `_set_model_iteration_timeout_s(...)` 调用点改为读取 `budget.model_iteration_timeout_s` 为局部变量并传递
  - [x] `_model_iteration_timeout_s` 改为显式参数注入，不再依赖模块全局

- [x] Task 3.2: 配置收敛为 config 一层
  - [x] `react_model_deadlines.py` 移除 `OCTOPUS_REACT_MODEL_ITERATION_TIMEOUT_S` 等 env var override
  - [x] 保留 `budget.model_iteration_timeout_s` 作为唯一配置入口
  - [x] 更新 `config.example.yaml` 注释，说明超时仅由 config 控制

- [x] Task 3.3: 验证
  - [x] `pytest tests/test_react_loop.py tests/test_config.py` 通过
  - [x] 确认测试通过参数注入而非 monkeypatch 全局 setter
  - [x] 无残留对 `_set_model_iteration_timeout_s` / `_MODEL_ITERATION_TIMEOUT_S_CONFIG` 的引用

# Task Dependencies
- Delta 1 / Delta 2 / Delta 3 相互独立，可并行处理
- 各 Delta 内部 Task 顺序执行（先实现后验证）
- 全部完成后需跑全局回归：`pytest tests/test_react_loop.py tests/test_config.py tests/test_budget.py`