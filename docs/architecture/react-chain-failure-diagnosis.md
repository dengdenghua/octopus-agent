# test_subagent_react_chain 失败 · 精确诊断

> 日期：2026-08-18 · 只读分析（未改动任何文件）
> 测试：`tests/realtime_cerebrum/test_subagent_react_chain.py::test_parent_turn_dispatches_child_through_react_loop`
> 状态：**已解决（2026-08-18）**——根因是你未提交的 `react_drive.py` 改动
> （`dispatch_is_restricted` 新增 `subagent_session_id` 条件）导致干净 main 上通过的测试转红。

## 现象

测试前 8 个断言全部通过（react_stack 在上下文中、`react_loop_subagent=True`、
`flip_subagent_thread=True`、子会话独立 thread + 共享 blackboard），
仅最后一个失败：

```
assert child_loop_calls, "child should have been driven through the main react loop"
```

即：**子代理没有被 `react_drive.run_subagent_react_loop` 驱动**（`child_loop_calls` 为空）。

## 根因（调用链证据）

1. `bridge.call_subagent` → `_dispatch` 前（`bridge.py:716`）：
   ```python
   if _active_session["session_id"]:
       dispatch_context = {**(context or {}), "subagent_session_id": _active_session["session_id"]}
   ```
   只要存在**持久子代理会话**，就把 `subagent_session_id` 注入 dispatch context。
   （"one-shot children and remote providers never see it" 的注释假设已失效——
   现在大多数子代理都会拿到持久会话。）

2. `make_llm_ephemeral_runner`（`ephemeral_runner.py:620`）：
   ```python
   if not dispatch_is_restricted(_ctx, _session_meta):
       _result = run_subagent_react_loop(...)   # ← 期望路径
   # else: mini-loop
   ```

3. `react_drive.dispatch_is_restricted`（`react_drive.py`，你未提交的改动）：
   ```python
   return (bool(ctx.get("tool_allowlist_read_only"))
           or bool(meta.get("_locked_write_root"))
           or bool(ctx.get("subagent_session_id")))   # ← 命中
   ```

**结论**：`subagent_session_id` 一出现 → `dispatch_is_restricted=True` → 子代理走 mini-loop
→ `run_subagent_react_loop` 永不调用 → 测试失败。

## 设计张力

- `dispatch_is_restricted` 对 `subagent_session_id` 返回 True 的**意图**：
  带 report 工具的子代理必须走 mini-loop（共享 ReAct registry 无法安全绑定
  per-session 的 report 处理器）。
- 但 react-drive 端态模型的**意图**：普通子代理应走主 react 循环。
- 两者现在冲突：**任何拿到持久会话的子代理都被强制走 mini-loop**，react-drive 模型实际失效。

## 建议修复（三选一，按推荐排序）

1. **只对"需要 report 工具"的子代理注入 `subagent_session_id`**（推荐）：
   在 `bridge.call_subagent` 中，仅当调用方显式请求 report 车道
   （例如 context 带 `subagent_report_delivery` / 显式 `report_session_id`）时才 stamp。
   普通子代理 → 无 `subagent_session_id` → 走 react-drive；带 report 的子代理 → mini-loop。
   同时保留 `dispatch_is_restricted` 的 fail-closed 语义。

2. **收窄 `dispatch_is_restricted`**：仅当 `subagent_session_id` 且确实需要 report 车道
   时才限制 react-drive；否则允许（即使有 session id）。

3. **更新测试预期**：承认持久会话下子代理一律走 mini-loop——但这与
   测试/文档声明的端态模型（"子代理 = 自己的线程走主 react 循环"）矛盾，不推荐。

## 已实施的修复（桥接闸门，调和两测试）

- `bridge.call_subagent`：仅当子代理**非 react 驱动**时才注入 `subagent_session_id`
  （`_react_driven = react_loop_subagent and react_stack`）；
- 保留 `dispatch_is_restricted` 的 session 限制 → **显式 report 车道仍走 mini-loop**；
- 效果：隐式会话的 react 子代理 → react-drive；显式 report 子代理 → mini-loop + report 工具；
  非 react 子代理 → 不变（照常 report）。

验证：`test_subagent_react_chain` 转绿 + `test_subagent_react_drive` 14 个全过 +
子代理/实时/report/委托全套 **301 passed** + 3 个 CI 门禁全绿。

> 该修复位于 `bridge.py`（含你的未提交改动），将随 U1 提交一起入库，无法单独提交。

## 验证方式

修复后运行：
```bash
.venv/bin/python -m pytest "tests/realtime_cerebrum/test_subagent_react_chain.py::test_parent_turn_dispatches_child_through_react_loop" -q
```
应转绿；同时跑 `tests/test_subagent_*` 确认 report 车道（mini-loop）无回归。
