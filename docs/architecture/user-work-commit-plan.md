# 未提交工作 · 建议分组提交方案（User-Work Commit Plan）

> 日期：2026-08-18 · 只读分析（未改动你的任何文件）· 关联：[blocks-commit-checklist.md](./blocks-commit-checklist.md)
>
> 目的：把工作区 **144 个未提交文件**（+ 9 个已重新生成的 CI 快照）整理成
> **6 个主题提交**，让 CI 门禁转绿、历史可 review。

## 铁律（沿用组合层清单）

- 只 `git add <显式路径/glob>`，绝不 `git add -A`；
- 每组先跑对应测试再提交；
- **9 个快照文件**（`docs/openapi-snapshot.json` + `docs/auto/*`，已重新生成）
  **必须与产生漂移的源码同一提交**，否则干净 main 会反向不一致。

---

## U1 · 子代理事件 / 生命周期流（最大的主题）

**核心**：`runtime/execution/subagents/*`（bridge / sessions / react_drive / _bridge_trace）、
`suckers/_ephemeral_*`、`sensing/gateway/*`（realtime 流）、
`memory/journal/_journal_models.py`、`platform/process/session.py`、`protocol/items.py`、
`core/cerebrum/_react_execution_dispatch.py`、`tool_engine/_executor_helpers.py`

**前端配套**：`frontend/src/core/threads/*`、`realtime/*`、`messages/*`、`agent-workbench-*`、
`live-tool-timeline`、`work-blocks`、`replay-from-blocks`、`sharing/*`、`cache/*`

**测试**：`tests/test_subagent_*`、`tests/test_realtime_*`、`tests/test_react_loop.py`、
`tests/test_tool_handler_timeout.py`、`tests/test_ephemeral_*`、`tests/test_parallel_task_runner.py`

> 消息建议：`feat(subagent): lifecycle event streaming + workbench lanes`

> ⚠️ 此主题含 `test_subagent_react_chain` 失败——精确诊断见
> [react-chain-failure-diagnosis.md](./react-chain-failure-diagnosis.md)（只读分析：
> `subagent_session_id` 与 react-drive 的交互冲突 + 三种修复选项）。

## U2 · 递归委托（hierarchical delegation）

**核心**：`runtime/execution/suckers/_delegation_skills_parallel.py`、
`delegation_skills.py`、`delegation_result_cache.py`、`role_delegation_guidance.py`（未跟踪）

**测试**：`tests/test_delegation_enhancements.py`、`tests/test_call_agent_parallel_partial.py`、
`tests/test_recursive_delegation_*`（含未跟踪的 `auto_seeding`——其 import `_run_one` 已失效，需先适配）

> 消息建议：`feat(delegation): recursive sub-delegation with depth/budget guards`

## U3 · Evolution 游戏化 UI

**核心**：`frontend/src/components/workspace/evolution-dashboard/*`（15 文件，含未跟踪）、
`evolution/page.tsx`、`sidebar-footer.tsx`、`workspace-sidebar.tsx`、
`agents/agent-role-profile-dialog.tsx`、`i18n/locales/*`、`use-agent-workbench-i18n.ts`

**测试**：`frontend/src/app/workspace/evolution/page.test.tsx` 等

> 消息建议：`feat(ui): gamified evolution dashboard + role level display`

## U4 · 平台治理（request limits / setup）

**核心**：`runtime/platform/ui/_app_setup.py`、`request_limits.py`

**测试**：`tests/test_request_limits.py`、`tests/test_setup_wizard_coverage.py`、
`tests/test_scheduler_runner_stop_coverage.py`

> 消息建议：`fix(platform): request limits + setup wizard hardening`

## U5 · 覆盖率补强 + 杂项

**测试**：`tests/test_*_coverage.py`（wiki / searxng / reflex / code_intel / kimi / ollama /
browser / image_search / swagger 等）、`tests/test_wiki_*.py`、`tests/test_swarm_runtime.py`、
`tests/test_plugin_hub_coverage.py`、`tests/test_loop_store.py`

> 消息建议：`test: broaden coverage + fix coverage gaps`

## U6 · 文档 / 设计资产（未跟踪）

**文件**：`docs/design/*`、`docs/recursive-delegation-implementation.md`、
`frontend/docs/*`、`frontend/src/components/workspace/evolution-dashboard/*.md`、
`AUDIT_REPORT_2026-08-17.md`、`DEEP_EVALUATION_2026-08-17.md`

> 消息建议：`docs: design notes for delegation + evolution`

---

## 提交顺序建议

U1（子代理流）→ U2（递归委托，依赖 U1 的 session 改动）→ U3（Evolution UI，独立）→
U4 → U5 → U6。U1/U2 之间先解决 `test_subagent_react_chain`。

## 验证

每组合并后跑：`.venv/bin/python -m pytest <该组测试> -q` + 前端
`pnpm vitest run <相关目录>`；最后全量回归一次（参考组合层验收基线）。

> 本方案是建议；实际提交边界以你的意图为准。需要我按此方案帮你分批提交（每批先验证）时说一声即可。
