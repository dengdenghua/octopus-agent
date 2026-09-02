---
name: octopus-agent-scorecard-audit-2026-07-18
description: "竞品自评网格是自证叙事(硬编码分数+Path.exists);逐条核查后真差距只几条;#2红验证门禁已修"
metadata: 
  node_type: memory
  type: project
  originSessionId: 7515e253-50ff-4836-a231-b704e6f32e06
---

2026-07-18,用户拿一张"14维度 vs Codex(96-99分,硬落后6/严格没赢10)"网格让逐条实证核查。5 个审计子代理**独立、各自扒到同一结论**:

**这张网格是自证叙事,不是测量。** 分数是 `runtime/safety/evolution/agent_competitor_scorecard.py:57-321` 里**手写的整数字面量**;唯一"计算"的 `codex_gap.py:420-462` 靠 `Path.exists()` + substring grep 判绿;整个 `safety/evolution/*` 只喂 dashboard,`react_loop` 从不 import。每条 gap 措辞就是那文件里自己写的 `next_action`。**别再引用这些数字当"对 Codex 的差距实证"。**

**逐条核查后的真实画像**(file:line 见当时子代理报告):
- **真差距(可修,少数几条)**:①核心编码循环——完成门禁只判"验证跑过/没谎报",不判"绿"(见下,已修一半);②权限沙箱——provenance 验签真但**只算不拦**(`codex_discovery.py:397` `enabled=not error`);③多 agent 编排——collab/team/project 三套独立 store+三套 timeline schema,**无聚合器**统一;④通用 loop——plan/act/verify 被 `_is_code_mode` 门控(`react_loop.py:3393`),非代码只给套话。
- **叙事/底座被低估(其实已建好)**:浏览器桌面(pixel replay/桌面证据/视觉失败→门禁全真且有测)、扩展 hooks 引擎。
- **夸大的"已领先"**:回放审计(只 record→重建→一致性门禁,**无重执行**)、长期记忆(多层自动注入真强但**打分召回 ExperienceLedger 没接进 loop**、查询是 substring-grep 无 embedding)、治理台(审计链真但周期导出/趋势/轮换全无)。**四个"领先"里只有 Agent OS 广度(#14)经得起查。**

**#2 已修一半(commit `894809936`,分支 feat/behavioral-suite-runtime-fixes)**:`_has_successful_verification_observation` 现在红即非成功 + 新 `red-verification guard`(写了代码且最近验证是红的→拦完成)。13 单测+1398 零回归。红检测保守(强信号,"0 failed"/"13 passed"故意不匹配)。**注意 react_guards.py 当时夹着 Codex 未提交的 `_browser_goal_is_ui_only`,我用定向 patch 只提交了自己的 hunk。**

**但拿 memory.crosscutting-change 用 K3 复跑仍 score 0——追到轨迹才发现真机制是第三样:迭代预算耗尽自动暂停,不是红验证也不是仓库上下文。** K3 慢/啰嗦,大仓跨切面重命名把 `max_iterations` 几乎耗在探索+编辑上(214 步、从没跑 pytest),在 `react_loop.py:3451`(`(max_iterations-(i+1))<=3`)触发 `iteration_near_limit` **自动暂停**→"当前进度已暂停并保存,等待继续"(`react_loop.py:3560`)。**这条 pause 路径不走完成 guard**,所以红验证门禁够不着它;`_final_answer_requests_user_help` 对那句实测=False,逃生舱也没触发。无人值守 eval 没人点继续 → 死路 → score 0。

**教训(强化 [[octopus-agent-audit-verification-lesson.md]]):同一失败,审计判"仓库上下文"、我判"验证门禁"、实测是"迭代预算"——三个诊断只有拉真轨迹才对。** memory 例真·下一杠杆 = 提高 `max_iterations` / 让 K3 少过度探索(预算/效率问题),不是加 guard。K3 接入见 [[kimi-k3-volcengine-agent-plan]]。
