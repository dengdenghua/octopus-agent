---
name: phase6d-guardian-model-fix
description: "phase6d effective_model used-before-def 修复(f7c2eefc,fix/phase6d-guardian-effective-model);phase6d/guardian 只存在于 codex 分支,worktree 基分支陷阱"
metadata: 
  node_type: memory
  type: project
  originSessionId: 30705ccf-8fb4-4124-8625-91443040da16
  modified: 2026-08-11T06:24:03.942Z
---

2026-08-11 修掉 a850d026 引入的 used-before-def:phase6d 的
`GuardianReviewerConfig(default_model=effective_model)` 先于标量拉取
`effective_model = state.effective_model` 使用,`guardian_review_enabled`
开启时直接 UnboundLocalError。修法=`state.effective_model` 直接引用(类型
str,零前向引用),291/935 行用法在该拉取后无需动。提交 `f7c2eefc` 于分支
`fix/phase6d-guardian-effective-model`(基于 codex/local-cli-partner-polish @
09ad15af)。回归测试:驱动真实 loop 回合(带 guardian_review_enabled 上下文)
验证不再抛异常,修复前红/修复后绿,已随 commit 带上。

**Why:** 两个环境陷阱值得记:(1) `_react_execution_phase6d.py` 及 guardian
评审代码只在 `codex/local-cli-partner-polish` 分支,main 上根本没有这个文件——
给这类文件派 worktree 修复任务时,worktree 基分支必须是 codex 系,否则文件不存在;
(2) 该分支的**已提交 tip 历史上是 import 破损的**:曾有两处提交态债,均已由本会话
以"从定义模块直连导入"模式修掉——`_step_is_failed_execution`(b5e2711d,定义在
`react_todo_protocol_guards.py`)、`classify_turn_failure`(0222d037,定义在
`_react_execution_results.py`);它们被从 `react_guards.py`/`react_execution.py`
导入,而那两个文件的 re-export 只存在于并发会话未提交版。

**2026-08-11 并发会话挂机,本会话接管其全部未提交工作(58 文件 3088+/1076-),
至此分支提交态彻底自洽**:
- 环境降级/guard 线、执行编排线、gateway 流式线、skills 线、前端叙事线、宠物线
  分 6 个主题提交落地(bcbe1357/b94b46fd/88fd160a/9f6ab2ab/a2220d82/a94dc4b4),
  并发会话自己补了个 UI fix(95d2e42c)。干净 tip 收集 10686 全通过、关键 726 测试
  过、全量 10633 过、前端 tsc 0 错误。
- 修了 pet 三缺陷:push_warning 双参 arity(Godot4 单参,双参解析期编译失败)、
  整张情绪网格蒙太奇(region_enabled+region_rect 切 192x208 单帧)、set_mood 不切
  视觉(MOOD_ROW 行映射+帧动画对齐网页端)。
- 13 张 QA 截图移入 .design-qa/(repo 有"设计-QA 根卫生"gitignore 约定),不入库。

**How to apply:** 涉及 phase6d/guardian 的后续改动,先在
`git branch --contains <提交>` / `git cat-file -e` 确认文件所在分支;worktree 基
分支选错就重开;验证前先看并发会话的 `git status`,必要时临时 apply 其 runtime diff。
判读干净 tip 测试结果时:先看收集是否全通过(import 债),再分辨运行期失败是否
因未提交新文件缺失(属并发会话,非自己引入)。mypy ratchet 是这批 bug 的有效
抓门(was:2 NEW effective_model),修完即消。
