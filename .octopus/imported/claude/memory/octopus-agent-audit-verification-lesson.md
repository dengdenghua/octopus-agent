---
name: octopus-agent-audit-verification-lesson
description: 断言前先实证:注释/文档/审查结论会撒谎,grep 空结果≠不存在(命令可能静默失效)。先用已知符号验证命令有效,或直接插桩跑/在旧 commit 开 worktree 对比
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 73dba696-f7dc-4ee6-899f-63f46a601f05
---

在 octopus-agent 项目中，探索型子代理产出的"改进点清单"多次与代码实情不符：

1. 称"HunkView 缺接受/拒绝按钮"——按钮其实已实现，真问题是整个 ItemView 组件树是孤儿代码，生产页走旧消息管线。
2. 称"verify 闭环完全手动"——自动诊断/守卫早已存在，真 bug 是缺 mypy 时注入假阳性失败。
3. 称"断线时 Promise 悬挂、outbox 丢消息无感"——failPending 正确 reject，真缺口只是输入框乐观清空导致草稿丢失。
4. (别人的架构审计, 2026-06)称"Hearts 三心 HA 未实装、只是 Redis 锁"——错:`runtime/core/hearts/` 有 fencing-token Redis 租约(Lua GET+PEXPIRE+holder_id/token)+ `etcd_coordinator` + `acquire_leadership/is_leader` 选举 + `register_branchial` 每通道熔断。是真主备 HA，单机回退 `_AlwaysLeaderGuard`。
5. (同审计)称"Chromatophores 腕间 gossip / Worker 未接入"——过时:并行臂+腕间 SignalBus mesh **已建且已接线**。`runtime/execution/swarm/{runtime.py(ThreadPool 并行),drive.py}` + `realtime_team_stream.py:_drive_swarm_mesh`(创建 `SignalBus()` 组池跑 swarm);`realtime_turn_lifecycle.py:386` 带 topology_id 即进 mesh，按图形状自动选 mesh(并行) vs TeamRunner(串行)。**差点据此重造已存在的东西**。
   - 审计仍**对**的几条:Skin 隐式感知无成体系子系统(散落比喻);目录名错位(`safety/recovery/`=自进化GEPA、`safety/experiments/`=prompt A/B);普通对话默认走中心化 `_drive_react`，mesh/HA 是条件次路径。已加 `__init__` docstring 别名 + core-path.md「默认 vs 条件路径」澄清(commit 33fe97ab)。

6. (本人核查同一份外部审计的测试清单, 2026-06-25)**反向错误——我少报了审查点名的失败**:跟用户说"delegation/swarm/base-prompt 在 main 已绿、报告测试清单过时",实为我按报告中文描述匹配了**名字相近的邻居测试**(`test_delegation_enhancements`/`test_swarm_resource_contention`/`test_dispatcher_context_capability`,都绿),而真正红的是 `test_pipeline_skill::…returns_5`/`test_swarm_drive`(`_FakeSwarm` 缺 `skill_resources`)/`test_system_prompt_size`。**全量一跑,6 红里 4 条正是审查点名的、仍红**;只有 OpenAPI snapshot 那条我跑对了文件、确已绿。审查的测试清单比我当时给的信用准。

7. (2026-07-17，同一轮里我自己翻车 **6 次**，全是同一个错：**把"没有输出"当成"不存在"**)
   - **过时注释撒谎**:`protocol/events.py` 写着 `TURN_PLAN_UPDATED` "reserved but not currently emitted"——实际 `realtime_event_bridge.py` 一直在发。我照抄注释就给用户下了错结论。
   - **文档的 ✅ 撒谎**:`kimi-replay-ux-teardown.md` 的 P1 清单里**至少 7 项早已落地却没打勾**，被当待办反复讨论。
   - **按提案名 grep,漏掉换名实现**:搜 `CompletionReceipt` 一无所获 → 断言"完成态 receipt 没做"，实际它就活在 `message-output-summary.tsx`(artifacts/changes/verifications/extractResultUrl/makeSimilar 全齐)。同理 `AgentComputerPanel` 实为 `agent-workbench-panel.tsx`。**要按能力找,不按名字找。**
   - **grep 路径含 `[` `]` 在 zsh 下静默读空**:`grep -rn X "src/app/.../[thread_id]/page.tsx"` 返回空 → 我断言"预览优先未实现,是唯一缺口"，实际 `page.tsx:2309` 早就实现了,**连我"建议"的 `agentWorkbenchTabTouched` 守门都一模一样早在**。
   - **搜类型名而非消费方式**:面板里 `AgentPhaseSnapshot` 出现 0 次 → 断言"右栏没吃后端快照"，实际它经 `useAgentWorkbenchSnapshot` 消费，且是**快照优先、事件兜底**的正确形态(`agent-workbench-snapshot.ts:108`)。**我刚把"按能力找"写进文档,转头又犯。**
   - **`head` 永远 exit 0**:`grep X | head -2 && echo "有"` → 无论有没有都打印"有"。
   - **`| tail -3` 把自己的证据截没**:后台跑全量测试时管道截断，4 个失败只留下 2 个，我还据此说"提交是绿的"(实为 `-x` 提前停在第 949 个)。

**Why**：子代理在有限上下文里做广度搜索，容易漏掉调用链的关键一环（谁渲染、谁调用、异常是否被接住），得出方向正确但定位错误的结论。**而我自己的失败模式更蠢也更常见:命令本身失效/被截断/匹配错目标时,返回的"空"和"真的不存在"长得一模一样,我却默认当成后者。** 注释和文档是"当时的快照",代码是现在的事实——两者冲突时**永远信代码**。

**How to apply**：把审查结论当"线索"而非"结论"。动手前先追完整链路（组件→消费者→路由；异常→捕获点）。

> **断言"某功能不存在"之前,先证明你的命令能出结果。** 用一个**已知存在**的符号跑同一条命令当健全性检查(例:`grep -rn ChatPageLayout src` 命中 6 处 → 说明这条命令有效,此时 `bottomBar` 返回空才算证据)。再检查三点:① 路径含 `[]`/空格没被正确引用?② 管道里有 `head`/`tail` 吞了输出或退出码?③ 搜的是**提案里的名字**还是**真实能力**?
>
> 更快的办法:**别用 grep 证伪,用运行证实**——插桩跑一遍(本轮就是靠 spy 住 `evaluate_guards` 才三秒定位到真凶 `implementation-write guard` 拦了 57 次,之前对 todo 门的猜测全错)、或在**改动前的 commit 上开 worktree 跑同样的测试**(`git worktree add /tmp/x <ref>` + 软链 `.venv`),一次就能判定"是不是这次引入的回归"。

用 grep 验证"缺失"的东西真的不存在。真正的修复点往往比报告说的更小、更准。**核"测试失败"时反过来也要小心**:报告给的是中文描述,务必先 grep 出**确切 test nodeid** 再跑,别拿名字相近的邻居测试当"复现/不复现"的依据——最稳是直接跑一遍全量(`.venv/bin/python -m pytest -q`),邻居测试绿 ≠ 报告点名的那条绿。
