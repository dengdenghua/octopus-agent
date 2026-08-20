---
name: octopus-agent-verification-guards
description: "octopus 的 ReAct 循环有 ~30 条确定性验证 guard(react_guards.py)——别误判它\"没有自验证\""
metadata: 
  node_type: memory
  type: project
  originSessionId: 73dba696-f7dc-4ee6-899f-63f46a601f05
---

**别犯我犯过的错**:我曾断言 octopus 最大软差距是"没把 verify-first 烧进循环"。**错得离谱。** `runtime/core/cerebrum/react_guards.py`(~2400 行,目录 §1–§30+)是一套**极完备的确定性验证门控**,在 Final Answer 处硬拒不合格的完成:

- `_todo_protocol_completion_guard`(L506):无 todo 清单 / 有 todo 未 completed / 最后一次 todo_write 后又用了工具 → 拒。
- **§11 `_false_verification_claim_guard`(L1169)**:code 模式 + Final Answer 声称"测试/类型检查/构建通过" + trajectory 里**没有成功的验证观察**(`_has_successful_verification_observation`)→ 拒("verifier 要么失败要么没跑过")。**这就是"已记录 vs 确定性通过"那条缝——早被堵死。**
- §28 commented-out-as-fix:把可执行代码换成注释/空行来"修" bug → 拒。
- §30 broad-except 抑制;§20 弱断言;§23 纯 mock 测试;§27 无断言测试;§25 删测试;§26 泛化测试名;§7 新公开符号无测试;§5 语言特定验证;§6 路径策略验证。
- 在飞行中(loop 内,非 Final Answer)还有 `_completion_phrase_without_todo_guard`:模型 narrate "搞定了" 但下一动作不是 todo_write → 提醒。

调用点:react_loop.py:2590 经 react_guards.py:2422/2428 的 wrapper。`tests/test_react_guards_*.py` 直接覆盖。**已 wired、已测、生效**,不是休眠。

**架构洞察**:正因 octopus 模型无关(没法 post-train 模型养成 verify-first 习惯),它把这条纪律**外挂成确定性硬门控**——这恰是对"模型-harness 协同"结构差距的**正确且聪明的弥补**,某种意义上比 Claude Code(靠模型训练养成该习惯)更**显式严格**。代价:启发式(regex/AST 模式)有误报误漏,不如训练出的判断灵活;且偏 code 模式。

**教训(给我也给未来会话)**:对一个大子系统下架构论断前,**先读那个子系统**。我连着两次"自验证缺失"的论断,都是没读 react_guards.py 拍的脑袋;用 verify-first 核实自己的分析(去读代码)才发现——这正是 react_guards 和我都在强制的同一条纪律。相关 [[octopus-agent-audit-verification-lesson]]。
