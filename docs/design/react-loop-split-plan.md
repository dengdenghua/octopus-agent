# react_loop.py 拆分方案

> 基于 2026-07-28 依赖分析（57 个模块级辅助函数 + 4150 行 `stream_react_loop` 巨型函数）。
> 目标：不改行为、测试零改动通过，把 `react_loop.py` 从 6272 行降到 ~1500 行的编排核心。

## 进度状态（2026-08 更新）

**Wave 1 ✅ 完成，Wave 2 ✅ 完成，PHASE 3 抽离 ✅ 完成，PHASE 1–2/4/4.5/5 残余 ✅ 完成——
`react_loop.py` 现 1056 行，`stream_react_loop` 为纯编排骨架（~730 行，含注释与 `_LoopState` 装配）。**

行数轨迹：`6272 → 4456（Wave 1）→ 2463（Wave 2）→ 1487（PHASE 3）→ 1324（6g）→ 1056（PHASE 1–2/4/4.5/5 残余）`

Wave 2 提交序列（codex/local-cli-partner-polish 分支）：

| 区段 | commit | 归位 |
|---|---|---|
| 6a cancel/pause guard | `a48c1682f` | `react_loop_controls.py` |
| 6f auto-checkpoint + evaluator | `47b79c779` | `react_checkpointing.py` |
| 7+8 terminal/finalization | `7e45e3303` | 新 `react_terminal.py` |
| 6e 前半 in-flight nudges | `1a83b8950` | 新 `react_in_flight_nudges.py` |
| 6c parse/guard + `_LoopState` 骨架 | `aeb67b087` | 新 `react_loop_state.py` + `react_phase_6c.py` |
| 6d action dispatch + observation | `9e611b444` | `react_execution.py` |
| 6e 后半 guard 状态机 | `fb7ea2212` | `react_final_answer_guards.py` |
| 6b LLM 调用 + 流式锚点 | `220a3edfc` | 新 `react_model_stream.py` |
| PHASE 3 prompt 装配（后补） | `45d3f853a` | 新 `react_prompt_assembly.py` |
| 6g housekeeping（后补） | `bdbefe534` | `react_execution.py`（无 yield，普通函数返回 `_LoopControl`） |
| PHASE 1–2/4/4.5/5 残余（收官） | `57fdaa893` | `react_prompt_assembly.py`（1–2 bootstrap、4/4.5 事件）+ `react_resume.py`（5 resume/grant） |

**行号锚点已全部漂移**：下文各区段的 L-编号对应拆分前的原始文件，仅具历史参考价值；
定位请按 `PHASE n` 注释标记或函数名 grep。

## 现状诊断（拆分前）

| 区段 | 行数 | 性质 |
|---|---|---|
| 模块级辅助函数 ×57（L206–2052） | ~1850 | 多为纯函数，主循环内调用 0–5 次 |
| `stream_react_loop`（L2096–6238） | ~4150 | 单函数内含 PHASE 1–8 标记，嵌套函数 10+ |
| `run_react_loop`（L6239–6272） | ~35 | 薄封装 |

关键约束（来自测试套件）：
- 45 处外部导入 `react_loop`；`monkeypatch.setattr(react_loop, "_model_iteration_timeout_s", ...)` 等补丁点必须保持可补丁。
- 解法沿用项目既有惯例（`realtime_cerebrum.py` 模式）：抽离后在 `react_loop.py` 顶部 re-export，主循环通过模块全局名解析调用 → monkeypatch 继续生效。
- 既有卫星模块已存在：`react_guards / react_parsing / react_context / react_execution / react_checkpointing / react_convergence / react_parallel_dispatch / react_loop_controls / react_types / todo_protocol`——新模块命名延续 `react_*` 风格，抽离前先查重避免重复逻辑。

## Wave 1 · 纯函数簇抽离（低风险，预计 -1500 行）✅ 已完成

每簇一个 commit，抽离 + re-export + 跑 `test_react_loop.py` 全量：

| # | 新模块 | 包含函数 | 行区间 | 备注 |
|---|---|---|---|---|
| 1 | `react_model_deadlines.py` | `_model_iteration_timeout_s` 等 7 个超时/deadline 函数 | 1028–1244 | ⚠️ `_model_iteration_timeout_s` 被 7 处测试 monkeypatch——re-export + 6b 调用点经 react_loop 全局名注入（Wave 2 落地） |
| 2 | `react_final_answer_guards.py` | `_looks_like_observation_echo` / `_final_answer_needs_pre_emit_guard` / `_evaluate_final_answer_guards` / `_note_guard_impasse` / `_guard_impasse_final_answer` / `_guard_reason_for_user` / `_unfinished_implementation_recovery_needed` / `_record_rejected_step` | 1452–1672 | 最内聚的一簇，先做 |
| 3 | `react_action_outcomes.py` | `_finish_reason_is_length_limited` / `_tool_call_succeeded` / `_per_action_outcomes` / `_action_fingerprint` / `_deduplicate_actions` / `_action_batch_fingerprint` / `_retry_safe_affinity` | 1246–1360 | 纯函数，零风险 |
| 4 | `react_public_updates.py` | `_safe_public_update` / `_bounded_public_evidence_excerpt` / `_build_public_evidence_narrative_input` / `_public_narrative_language_instruction` / `_observed_read_fallback_update` / `_runtime_fallback_public_update` / `_build_public_action_orientation_input` / `_stream_public_evidence_narrative` / `_public_tool_target` | 206–814 | 含嵌套函数的流式叙事器，整体搬走 |
| 5 | `react_explicit_reads.py` | `_narrow_command_direct_answer` / `_recover_explicit_read_actions` / `_bound_explicit_large_reads` / `_explicit_read_only_goal` / `_explicit_observed_read_sequence` / `_explicit_no_tool_goal` | 237–400, 967–1027 | 与 react_guards 查重 |
| 6 | `react_resume.py` | `_build_resume_context_prompt` / `_resume_context_*` / `_load_*_checkpoint_snapshot` / `_ResumeState` / `_compute_resume_state` | 1673–2012 | 与既有 `resume_cli.py` / `react_checkpointing.py` 划清边界 |
| 7 | `react_browser_iteration.py` | `_ensure_browser_operation_skills` / `_browser_operation_requested` / `_browser_task_iteration_limit` / `_narrow_research_iteration_limit` / `_code_task_iteration_limit` | 1360–1451, 2052–2075 | 或并入 capability_router |
| 8 | 零散 | `_todo_prewrite_guard` / `_todo_completion_before_write_guard` → `todo_protocol.py`；`_native_tool_calls_missing_required_args` / `_safe_react_error_message` → `react_types.py` 或 guards | 815–884, 2013–2051 | 并入既有模块 |

完成后 `react_loop.py` ≈ 4400 行（实际 4456 行，符合预期）。

## Wave 2 · 巨型函数分段（中风险，真正的收益）✅ 已完成

`stream_react_loop` 的 PHASE 标记天然是拆分线。难点：各 phase 共享几十个局部变量。
实际采用的策略（与原文略有出入，以代码为准）：
- `_LoopState` 是平铺 dataclass（`react_loop_state.py`），按 cfg / mode / convo / synced / emit / parse 分组；
  引用类型共享引用原地 mutate，标量在主循环调用点显式 local→state→local 同步（"信箱"）。
- 每个 phase 是 `Generator[dict, None, _LoopControl]`：yield 透传，
  `break → BREAK`、`return None → RETURN_NONE`、外层 `continue → NEXT_ITERATION`、fall-through → `CONTINUE`。
- 会成环的模块间调用（react_parallel_dispatch / react_quiet_evidence / react_action_outcomes / react_execution 互引）
  一律参数注入并在函数体内别名回原名字；monkeypatch 敏感名（`_model_iteration_timeout_s`、
  `next_custom_model_fallback` 经 failover 闭包）从 react_loop 调用点注入，patch 持续有效。
- ruff 会把"被抽走后不再使用"的 re-export 误删：恢复 import 并把名字钉进 `react_loop.__all__`。

建议顺序（从小到大，每步一个 commit）：

1. **6a** cancel/pause guard（~76 行）→ `react_loop_controls.py`（既有模块，归位）✅
2. **6f** auto-checkpoint + step evaluator（~90 行）→ `react_checkpointing.py`（归位）✅
3. **6c** parse step / format-violation（~420 行）→ 新 `react_phase_6c.py` ✅
4. **7+8** post-loop terminal + finalization（~260 行）→ 新 `react_terminal.py` ✅
5. **6e** in-flight nudges（~190 行）→ 新 `react_in_flight_nudges.py` + guard 状态机段 → `react_final_answer_guards.py` ✅
6. **6b** LLM 调用与流式锚点（实际 ~530 行）→ 新 `react_model_stream.py` ✅
7. **6d** action dispatch + observation（~900 行）→ `react_execution.py`（归位）✅
8. **PHASE 3** system + volatile prompt 装配（~1000 行，顺序配置装配，无状态机）→ 新 `react_prompt_assembly.py`，
   返回 `_PromptAssembly` dataclass（22 个产出字段）✅

完成后 `stream_react_loop` 为编排骨架，`react_loop.py` = 1487 行（目标 ≈1500，达标）。
后续两个后补 commit 进一步降到 1056 行（6g + PHASE 1–2/4/4.5/5 残余，见上表）。

## Wave 3 · 下一步候选

1. ~~**PHASE 1–5 残余**（react_loop.py 内联，合计 ~700 行）~~ ✅ 已全部完成：
   - PHASE 6g housekeeping（循环尾消息拼装，~200 行）——沿用 `_LoopState` 协议收进 `react_execution.py`（`bdbefe534`）；
   - PHASE 4/4.5/5 message bootstrap + resume（~250 行）——4/4.5 收进 `react_prompt_assembly.py`，
     5 的 pause 注册/taint/resume/grant 收进 `react_resume.py`；平凡变量初始化、steering/model failover 闭包
     （守住 `next_custom_model_fallback` patch 点）、realtime preface 留在主函数（`57fdaa893`）；
   - PHASE 1/2 entry guards + mode/budget 检测（~150 行）——收进 `react_prompt_assembly._resolve_turn_bootstrap`（`57fdaa893`）。
2. **react_guards 抽象减法审计**（4122 行）：同法体检；评估"这层守卫能否被一次好的工具调用替代"。
3. **可选体检**：`react_parsing.py` / `react_execution.py`（抽离后体量见长）按同样的内聚度标准过一遍，
   只在存在清晰可分的簇时动手。

## 验证策略（每 commit 必跑）

```bash
.venv/bin/python -m pytest tests/test_react_loop.py tests/test_react_context.py -q
.venv/bin/python -m pytest tests/ -k "react or cerebrum or checkpoint or resume" -q
.venv/bin/python -m ruff check runtime/core/cerebrum/
.venv/bin/python -m tools.lint.invariant_check runtime/core/cerebrum/
```

## 风险清单

| 风险 | 缓解 |
|---|---|
| monkeypatch 失效（测试补丁点搬家后打不上） | re-export + 循环内经 react_loop 全局名调用；Wave 1 每簇先 grep 测试补丁点再动手 |
| 循环内闭包变量被抽离函数引用 | Wave 2 先引入 `_LoopState`，只搬不依赖隐式闭包的块 |
| 循环 import（react_parsing 等已 import react_loop 符号） | 新模块只依赖 react_types / platform；react_loop 单向 import 新模块 |
| 行为漂移 | 抽离=纯移动，不改函数体；每 commit 全量 react 测试 |
