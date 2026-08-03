# Checklist

## Delta 1 · 预算默认值收敛为单一来源（P0）

- [x] `schema.py` 定义权威预算默认值常量，`BudgetConfig` 引用它们
- [x] `pause_control.py` / `react_loop.py` / `cli_run.py` / `presets.py` 不再各自硬编码与 schema 相同的预算数字
- [x] `AgentConfig()` 默认值与修改前一致（max_tokens=100000、max_usd=1.00、max_latency_ms=600000）
- [x] preset 差异化覆盖保留（如 team max_usd=2.00、research max_tokens=500000）

## Delta 2 · Deadline 分层聚合（P1）

- [x] `ModelDeadlinePolicy`（或 `_stage_model_timeout_s`）存在，合并三个同构函数
- [x] `react_model_stream.py` 调用点已更新为聚合策略
- [x] 阶段超时行为与拆分前一致（recovery≤60、post-tool≤90、evidence-synthesis≤120）

## Delta 3 · 配置去冗余 + 移除模块级 setter（P2）

- [x] `_MODEL_ITERATION_TIMEOUT_S_CONFIG` 全局与 `_set_model_iteration_timeout_s()` 已移除
- [x] `react_loop.py` 无 `_set_model_iteration_timeout_s` 调用，改为局部变量传递
- [x] env var override（`OCTOPUS_REACT_MODEL_ITERATION_TIMEOUT_S` 等）已移除
- [x] 超时仅由 `budget.model_iteration_timeout_s` 配置
- [x] `config.example.yaml` 注释已更新

## 全局回归

- [x] `pytest tests/test_react_loop.py tests/test_config.py tests/test_budget.py` 通过
- [x] 无残留对 `_set_model_iteration_timeout_s` / `_MODEL_ITERATION_TIMEOUT_S_CONFIG` 的引用
- [x] 测试通过参数注入而非 monkeypatch 全局 setter