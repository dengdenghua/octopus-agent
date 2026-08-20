---
name: octopus-workspace-dual-surface-design
description: "workspace 双侧栏（协作 surface vs 工具 surface）是产品设计，不是 bug — 别再标\"sidebar 不一致\""
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 1f9d2b5f-f63e-4fc1-8631-547b7fd9611c
---

`/workspace/team`、`/workspace/storage` 显示一套 nav（协作/团队/Hub/自动化/本地数据库/应用/文档/图片/本机/授权目录），`/workspace/channels`、`/workspace/architecture` 显示另一套（Hub/自动化/知识库/插件/自进化）—— 这是 [workspace-sidebar.tsx](frontend/src/components/workspace/workspace-sidebar.tsx) 里 `companySurfaceActive` / `browserSurfaceActive` 切换的**双 surface 设计**：不同模式 → 不同功能集 → 不同 nav。

**Why:** 用户 2026-06-24 明确："两套 nav 设计流式如此，不同模式不同功能"。

**How to apply:**
- 审计/回归时见到两条路径下 sidebar 项不同，不要标"inconsistency"或"sidebar drift"
- 命名差异（如"本地数据库"vs"知识库"）也是 surface 差异的体现，不是术语漂移
- 若要批评，只能针对"surface 切换没有视觉 indicator"这种 onboarding 问题，不要批"两套 nav"本身

相关：[[octopus-agent-context-engineering]]、[[octopus-family-architecture]]。
