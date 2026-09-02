---
name: octopus-agent-react-loop-refactor
description: stream_react_loop 巨型函数拆分进展与该文件的格式雷区
metadata: 
  node_type: memory
  type: project
  originSessionId: 661862e9-5884-4f9a-a170-484329f924df
---

`runtime/core/cerebrum/react_loop.py` 的 `stream_react_loop` 是 ~2600 行单体（8 个 PHASE，函数顶部有 ASCII 导航图）。2026-06-25 评价该框架后，用户选了「拆 stream_react_loop」。已完成（**未提交**，312 测试绿）：

- `_finish_reason_is_length_limited` + `_LENGTH_LIMITED_FINISH_REASONS`：消除 PHASE 6c 两处重复的 length-limited finish_reason 集合。
- `_compute_resume_state` + `_ResumeState` dataclass：把 PHASE 5 resume 块（原 76 行内联、改写 ~9 个闭包变量）外提为纯函数，用「返回聚合对象、调用方解包」绕开作者标注的 "checkpoint/resume coupling" 难点；try/except 和 yield 留调用方。调用块 76→24 行。
- `_tool_call_succeeded`：消除 PHASE 6d 里 tool_ok / retry_ok 两处逐字相同的「工具成功判定」（beak_step 优先，否则看 observation 失败前缀）。
- 新测试：`tests/test_compute_resume_state.py`（4 case）、`tests/test_react_loop_helpers.py`（length + tool-success helper）。

**Why:** 用户选的最高杠杆优化项；拆分让这些逻辑首次可独立单测。

**How to apply / 关键边界:**
- **PHASE 6d 主体不宜外提**：approval 决策、injection-taint 升级（~L2189）、`set_injection_gate_handled` 包裹的执行、untrusted-output fence（~L2419）是安全关键 + yield 密集，动一行可能开安全口子。只做了边角去重，没碰这些。见 [[octopus-audit-false-positives]]
- 基线对照（312 绿）：`.venv/bin/python -m pytest tests/test_react_loop.py tests/test_trajectory_regression.py tests/test_resume.py tests/test_react_auto_checkpoint.py tests/test_checkpoint_mirror.py tests/test_compute_resume_state.py tests/test_react_loop_helpers.py -q`
- 该文件有 **6 处预存 ruff format 漂移**（L579/697/1893/2401/2478/2490 区，全是 native_goal/agent_mode/UsagePricing/duration_ms/diag_text 旧代码），**别全量 `ruff format`**。验自己代码是否合规：`ruff format --diff <file>` 后用**代码内容**（不是符号名）grep——浅缩进下 ruff 会把 <100 字符的布尔表达式合并成单行，我照搬深缩进写法踩过这个坑。见 [[octopus-agent-generated-artifact-drift]]
- 导航图行号随编辑漂移；定位 PHASE 一律 `grep '── PHASE' react_loop.py`。
- 剩余可拆、风险更高：PHASE 6c parse、6d 安全关键路径（需更重安全网）。见 [[octopus-agent-improvement-roadmap]]

**2026-07-10 结论（核实后决定不再深拆）：** 函数现 617–3388 行（~2771）。**安全的纯 helper 已抽完**（137–617 那批：guards/resume-state/final-answer 判定都不共享闭包状态）；剩下的 2768 行正是耦合核心（~25 闭包变量+交错 yield+resume 耦合），强拆会改语义、在最关键循环开正确性口子。导航图注释里 **"See ADR-008" 是假引用**（ADR-008 实为 constitution-profiles，无任何 ADR 提 react_loop）——已把注释改成自足的内联理由。**结论：react_loop 不是可偿还的债，是有真实技术理由的有意单体，别再当 god-function 报或强拆。** 若未来真要拆，必须先建重安全网（trajectory/resume/checkpoint 全回归 + taint/approval 专测）。
