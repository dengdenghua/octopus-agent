# react_guards.py 体检审计与拆分候选

> 审计日期：2026-07-28（HEAD `ed4839192`，工作区干净）。
> 本文件只做审计与方案，不改代码。方法沿用 react_loop 拆分（见 `react-loop-split-plan.md`）。

## 1. 概览

| 指标 | 值 |
|---|---|
| 文件行数 | 4110 |
| 顶层定义 | ~90（def ×88 + class ×2）+ 模块常量 ~20 |
| 上游依赖 | `react_parsing`（57 个 detector 名）、`react_types.ReActStep`、`verification_policy`（4 名）、`react_security_guards`（re-export，L3331） |
| 测试 monkeypatch | **零**——tests 只直接 import 名字，无 `setattr(react_guards, ...)`，无 patch 字符串 |
| 已有抽离先例 | `react_security_guards.py`（387 行，2026-06-06 抽出），经 L3331 带 `# noqa: E402, F401` 的 re-export 保持兼容 |

**调用拓扑**：全部 guard 经模块级 `GUARD_REGISTRY`（L3952–4052，46 个条目）注册，
`evaluate_guards`（L4055–4110）按优先级短路求值；`_final_answer_security_guard`（L3879–3943）
在 registry 之前单独跑 final-answer 文本本身。因此 **registry/evaluator 是依赖图的顶部**：
持有 `GUARD_REGISTRY` 的模块必须能 import 所有 guard 函数 → 簇模块必须位于其下方（叶层），
`react_guards.py` 本体收缩为「registry 核心 + 全部 re-export」。

**外部调用方**（runtime 内，按边统计）：

| 调用方 | 引用的名字 | 拆分后可改指 |
|---|---|---|
| `react_final_answer_guards` | `GuardContext`、`evaluate_guards`、`_goal_requests_code_mutation`、`_incomplete_final_answer_guard`（+L177 懒加载 import） | 前两者留 react_guards；后两者 → 簇 1/4 |
| `react_convergence` | `_explicit_source_paths`、`_path_evidence_matches`、`_successful_read_paths` | → 簇 1 |
| `react_explicit_reads` | `_explicit_source_paths`、`_successful_read_paths`（L124 懒加载） | → 簇 1 |
| `react_prompt_assembly` | `_explicit_source_paths` | → 簇 1 |
| `react_public_updates` | `_explicit_source_paths` | → 簇 1 |
| `react_loop` | `_goal_requests_code_mutation`、`_explicit_source_paths`、`_code_mode_completion_guard`、3 个 write-followup guard、`_completion_phrase_without_todo_guard`（re-export 给 tests） | 保持 re-export 链 |
| `react_in_flight_nudges` | 3 个 write-followup guard、`_completion_phrase_without_todo_guard`、`_code_semantic_followup_guard` | → 簇 3/4/2a |
| `react_execution` | `_goal_requests_code_mutation`、`_code_semantic_followup_guard` | → 簇 1/2a |
| `todo_protocol` | `_has_successful_code_write` | → 簇 4（无回边，安全） |
| `react_security_guards` | `_final_answer_requests_user_help`（L43 **懒加载**，避免循环） | 经 react_guards re-export 继续可用，无需改 |
| `tool_bridge`（gateway） | `_explicit_source_paths`、`_browser_action_evidence`、`_concurrency_semantic_followup_guard`（L2418 懒加载） | → 簇 1/5/2a |
| `safety/evolution/*`、`trust_signal` | `evaluate_guards`、`GuardContext`、`GuardSpec`、`GUARD_REGISTRY`（懒加载）、`_mixed_mode_completion_guard`、`_has_successful_browser_action` | 核心留 react_guards；后两者 → 簇 5 |
| tests（test_react_guards_*、test_guard_* 等 ~20 个文件） | 各 guard 函数直接 import | react_guards re-export 全覆盖 |

## 2. 函数清单（按天然区段）

行区间为当前文件 1-based；「外部」= react_guards.py 之外的引用计数（runtime + tests）。

### §A 目标意图 + 证据路径分析（L131–681，~550 行，含 guard）

| 函数 | 行区间 | 行数 | 外部调用方 |
|---|---|---|---|
| `_final_answer_requests_user_help` | 131–226 | 96 | react_security_guards（懒加载）、test_react_guards_help_request ×14 |
| `_inspection_goal_text` | 227–244 | 18 | 仅内部 |
| `_goal_requests_project_inspection` | 245–270 | 26 | test_react_loop ×7 |
| `_goal_requests_code_mutation` | 271–346 | 76 | react_execution、react_final_answer_guards、react_loop、tests |
| `_final_answer_claims_no_tool_access` | 347–392 | 46 | 仅内部 |
| `_has_real_react_action` / `_has_successful_tool_observation` | 393–428 | 36 | 仅内部 |
| `_explicitly_requested_tool_names` | 429–465 | 37 | 仅内部 |
| `_tool_has_execution_receipt` / `_explicit_tool_request_guard` | 466–508 | 43 | tests ×4 |
| `_has_successful_code_write` / `_code_mode_missing_write_guard` | 509–548 | 40 | todo_protocol、tests ×6 |
| `_final_answer_claims_tool_was_not_executed` | 549–571 | 23 | 仅内部 |
| `_goal_requires_file_content` | 572–598 | 27 | test_react_loop ×5 |
| `_EXPLICIT_SOURCE_PATH_RE` + `_normalize_evidence_path` + `_explicit_source_paths` + `_path_evidence_matches` + `_successful_read_paths` | 590–681 | 93 | react_convergence、react_explicit_reads、react_prompt_assembly、react_public_updates、react_loop、tool_bridge（**复用最广的一簇**） |

### §B 代码模式证据/完成度 guard（L682–1043，~360 行）

`_code_mode_missing_inspection_tool_guard`（70）、`_code_mode_inspection_answer_fragment_guard`（34+常量）、
`_incomplete_final_answer_guard`（65）、`_code_mode_false_no_tool_guard`（25）、
`_code_mode_false_tool_result_guard`（50）、`_fabricated_citation_guard`（24+常量/helper）、
`_code_mode_completion_guard`（73）。外部：tests、react_final_answer_guards、react_loop。

### §C todo/完成语 guard（L1044–1215，~190 行）

`_has_tool_work_after_latest_todo`（15）、`_todo_protocol_completion_guard`（77）、
`_looks_like_completion_phrase`（6+常量）、`_completion_phrase_without_todo_guard`（77）。
外部：react_in_flight_nudges、react_loop、tests ×14。

### §D 写后验证跟进 guard（L1216–1416，~200 行）

`_unverified_write_followup_guard`（68）、`_failed_verification_followup_guard`（28）、
`_redundant_green_verification_guard`（53）+ 3 个私有 helper/常量。
外部：react_in_flight_nudges、react_loop、tests。

### §E 验证完备性 guard（L1417–1843，~425 行）

`_language_mismatched_verification_guard`（80）、`_path_verification_policy_guard`（44）、
`_new_python_code_without_test_guard`（53）、`_signature_changed_without_typecheck_guard`（36）、
`_wire_schema_change_without_compat_test_guard`（39）、`_new_third_party_import_without_dep_guard`（38）、
`_false_verification_claim_guard`（24）、`_red_verification_observation_guard`（42）+ 8 个小 helper。
外部：仅 tests（每个 guard 一个专门测试文件）。

### §F 轨迹反模式 guard（L1841–3293，~1450 行，全文件最大块）

统一形态：`_X_LOOKBACK = 12` 常量 + `_trajectory_*_hits` 聚合器 + guard 本体。三个子主题：

- **安全/代码气味**（~640 行）：`_commented_out_as_fix_guard`、`_broad_except_suppression_guard`、
  `_frontend_outside_tsconfig_include_guard`、`_oversized_single_edit_guard`、`_secret_in_payload_guard`、
  `_new_destructive_call_guard`、`_sleep_in_production_guard`、`_full_file_rewrite_guard`、
  `_print_in_production_guard`、`_hardcoded_personal_path_guard`、`_async_without_await_guard`、
  `_exception_swallow_via_log_guard`、`_long_function_guard`
- **并发语义**（~390 行）：`_ambiguous_inflight_leader_election_guard`、`_destructive_waiter_result_guard`、
  `_stale_immutable_waiter_snapshot_guard`、`_terminal_pending_entry_leak_guard`、
  `_loader_barrier_deadlock_guard`、`_wait_while_lock_held_guard`、`_path_boundary_decode_guard`
  + 2 个聚合 followup（`_concurrency_semantic_followup_guard` ← tool_bridge；`_code_semantic_followup_guard`
  ← react_execution / react_in_flight_nudges）
- **测试质量**（~390 行）：`_weak_test_assertion_guard`、`_mock_only_test_guard`、
  `_undocumented_skip_guard`、`_deleted_test_guard`、`_generic_test_name_guard`、`_no_assertion_test_guard`

外部：基本只有 tests（每 guard 一个专门测试文件）。

### §G 浏览器完成度 guard（L3347–3541 + L3613–3687，~270 行）

`_browser_goal_required_evidence`、`_browser_action_evidence`（61，← tool_bridge、tests）、
`_browser_interaction_completion_guard`、`_mixed_mode_completion_guard`（50，← safety/evolution、tests）、
`_has_successful_browser_action`（← agent_loop_quality）、`_browser_goal_is_ui_only`（75，← tests）。
**特殊点**：guard 签名吃 `GuardContext` —— 迁出需要 GuardContext 先下沉（簇 0）。

### §H registry 核心（L3542–4110，~570 行）

`GuardContext`（dataclass）、`GuardSpec`（frozen dataclass）、`_spec_code_mode`/`_spec_security`、
`_invoke_*` 包装器 ×15、`_final_answer_security_guard`（176）、`GUARD_REGISTRY`、`evaluate_guards`。
**这一层必须留在 react_guards.py 或下沉到叶模块，是依赖图顶部。**

## 3. 候选簇

| # | 目标模块（新建） | 内容 | 估计行数 | 依赖方向 | 主要风险 |
|---|---|---|---|---|---|
| 0 | `react_guard_types.py` | `GuardContext`、`GuardSpec`、`_spec_code_mode`、`_spec_security` | ~75 | 只依赖 react_types | 无；tests 从 react_guards import 这两个类 → re-export |
| 1 | `react_goal_analysis.py` | 目标意图 4 函数 + 证据路径 5 函数/常量（§A 中纯分析部分） | ~300 | → react_parsing、react_types | 无 cycle；react_convergence/react_explicit_reads/react_prompt_assembly/react_public_updates/tool_bridge 改指新模块反而**减少** react_guards 的入边 |
| 2a | `react_concurrency_guards.py` | §F 并发语义 7 guard + 2 followup | ~420 | → react_parsing | tool_bridge 有懒加载 import（L2418），改指新模块即可 |
| 2b | `react_test_quality_guards.py` | §F 测试质量 6 guard | ~430 | → react_parsing | 低 |
| 2c | `react_code_smell_guards.py` | §F 安全/代码气味 13 guard | ~680 | → react_parsing | 低 |
| 3 | `react_verification_guards.py` | §D + §E（写后跟进 3 + 验证完备性 8） | ~620 | → react_parsing、verification_policy | react_in_flight_nudges/react_loop 改指或经 re-export |
| 4 | `react_completion_guards.py` | §A 的 claim/显式工具请求部分 + §B + §C + 答案条数 guard（L3718–3800） | ~880 | → react_parsing、簇 1 | **风险最高**：`_final_answer_requests_user_help` 被 react_security_guards 懒加载（经 re-export 保持可用即可，勿动 react_security_guards）；`_has_successful_code_write` ← todo_protocol（改指本模块，无回边） |
| 5 | `react_browser_guards.py` | §G 全部 | ~300 | → react_types、**簇 0**（GuardContext） | 必须在簇 0 之后做；safety/evolution 的 2 个直接 import 改指 |

**留在 react_guards.py（~600–700 行）**：imports + 全量 re-export、`_invoke_*` 包装器、
`_preview_labels`、`_final_answer_security_guard`、`GUARD_REGISTRY`、`evaluate_guards`、
（簇 1 迁出后）其余散件。

预期终态：react_guards.py 4110 → **~650 行**，新增 8 个模块合计 ~3450 行（纯移动，总量不变）。

## 4. 依赖方向与循环风险

```
react_parsing / react_types / verification_policy        （既有叶层）
        ↑
react_guard_types（簇 0）
react_goal_analysis（簇 1）
        ↑
react_concurrency / react_test_quality / react_code_smell
react_verification / react_completion（→ 簇 1）/ react_browser（→ 簇 0）
        ↑
react_guards（registry 核心 + re-export 全部）
        ↑
react_final_answer_guards / react_loop / react_loop_controls / safety.evolution
```

- **现有循环先例**：react_guards ⇄ react_security_guards 已存在（后者懒加载 import 前者）。
  簇 4 迁出 `_final_answer_requests_user_help` 时保持 react_guards re-export，懒加载链不断。
- **react_guards → react_parsing 是单向**；react_parsing 不 import react_guards ✓。
- **todo_protocol → react_guards**（`_has_successful_code_write`）：react_guards 不 import todo_protocol
  （已验证，L975 只是参数名），改指簇 4 无回边。
- **react_final_answer_guards L177 有懒加载 import**——它 import 的名字若迁出，经 re-export 仍可达。
- 每个新模块只 import react_parsing/react_types/verification_policy/簇 0/簇 1，**绝不 import react_guards**
  （registry 顶部单向指下）。
- **re-export 兼容**：tests 对 ~40 个名字直接 `from react_guards import …`；零 monkeypatch，
  故只需名字可达——每个新簇在 react_guards 加一行 `from .react_X import (…)  # noqa: F401`
  （沿用 L3331 先例），或收敛为 `__all__` 钉名（react_loop 拆分惯例）。

## 5. 建议拆分顺序（从小到大，每步一个 commit）

| 步 | 簇 | 行数 | 理由 |
|---|---|---|---|
| 1 | 簇 0 react_guard_types | ~75 | 最小，解锁簇 5；先建立「types 下沉」模式 |
| 2 | 簇 1 react_goal_analysis | ~300 | 纯函数、复用最广；显著减少 react_guards 入边 |
| 3 | 簇 2a react_concurrency_guards | ~420 | 自包含，只有 2 个外部 followup 引用 |
| 4 | 簇 2b react_test_quality_guards | ~430 | 纯 tests 外部引用，最安全 |
| 5 | 簇 3 react_verification_guards | ~620 | 外部引用仅限 tests + 2 个 nudge 模块 |
| 6 | 簇 2c react_code_smell_guards | ~680 | 大块但零 runtime 外部引用 |
| 7 | 簇 4 react_completion_guards | ~880 | 最大且含懒加载耦合，放最后模式最熟时做 |
| 8 | 簇 5 react_browser_guards | ~300 | 依赖簇 0，收尾 |

每步验证五件套（同 react_loop 拆分）：核心测试电池（test_react_loop + test_react_guards_* 全量）
→ ruff → invariant_check → 大范围 `-k "react or cerebrum or guard"` 扫描（预存失败基线 4 个）
→ worktree 提交版自洽。

## 6. react_parsing.py / react_execution.py 体检

**react_parsing.py（3327 行，112 个顶层 def）**：明显的两层结构——
- L1–1472（~1470 行）：核心解析（`_parse_action`/`_parse_step`/Thought 流式/payload 提取/基础 detector），
  被 react_loop、react_execution、react_phase_6c、react_convergence 等广泛引用，**是公共叶层，不应动**。
- L1473–3327（§20–§32+，~1850 行）：**为 react_guards 各簇定制的 detector 尾巴**
  （`_step_introduces_*`/`_payload_has_*`/`_trajectory` 配套检测器）。抽样验证：外部消费者几乎只有
  react_guards 本体 + 对应 guard 测试文件（仅 `_detect_secrets_in_payload` 等个别被
  react_final_answer_guards 直接用）。
- 结论：**Wave 4 的天然候选**——§尾巴可按与 guard 簇相同的主题边界随簇共迁
  （detector 跟着它的 guard 走），或一次性抽成 `react_guard_detectors.py`（~1850 行，太厚，不推荐整体搬）。
  建议等 guard 簇落地后再启动，届时 react_parsing 可回落至 ~1500 行的纯解析层。

**react_execution.py（2281 行）**：三段构成——
- L1–1026（~1000 行）：beak 执行/回执/后台任务/observation shaping 等 ~25 个 helper，
  其中 observation shaping 段（L668–1026，~360 行）是潜在小簇（→ `react_observation_shaping.py`），
  收益一般，可选。
- `_phase_6d_dispatch_and_observe`（L1028–2020，~990 行）：closure 密集的 generator，
  是「耦合核心」——再拆需要再来一轮 `_LoopState` 级别的协议设计（approval/retry/诊断子段），
  **不建议作为下一个目标**。
- `_phase_6g_housekeeping`（L2021–2281，~260 行）：刚迁入，无需动。
- 结论：**无需近期动作**；若一定要动，只做 observation-shaping 小簇（~360 行）。

## 7. 风险清单

| 风险 | 缓解 |
|---|---|
| registry 引用链断裂（GUARD_REGISTRY 引用了迁出的 guard） | registry 留在 react_guards 顶部，簇模块只做叶层；每步跑 test_guard_killswitch / test_react_guard_registry |
| react_security_guards 懒加载断链 | 保持 react_guards re-export `_final_answer_requests_user_help`；勿改 react_security_guards |
| tests 直接 import 失效 | 每簇迁出后 react_guards 补 re-export（`# noqa: F401` 先例或 `__all__` 钉名）；全量 test_react_guards_* 必须零改动通过 |
| tool_bridge / react_final_answer_guards 的懒加载 import | 同样经 re-export 保持可达；grep 懒加载点（L2418 / L177 / L43）逐一核对 |
| ruff 误删 re-export | 沿用 react_loop 惯例：`__all__` 钉名或 noqa 注释 |
