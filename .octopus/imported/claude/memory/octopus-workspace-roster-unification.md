---
name: octopus-workspace-roster-unification
description: "右栏 roster 已统一成共享「工位」seat——别把团队成员改回纵向卡片或标\"不一致\""
metadata: 
  node_type: memory
  type: project
  originSessionId: fbf142eb-1b83-47ab-98f1-a323c8d35e01
---

2026-06-29 统一了两个右侧边栏的 agent roster 呈现。背景：团队模式右栏「群成员」(TeamRoster) 用纵向富卡片，agent 模式右栏「工位」(SubagentDock) 用底部紧凑 pill——用户嫌两边不统一。

**决策（用户拍板）**：以 agent 的**紧凑「工位」seat 为准**，团队成员向它看齐（不是反过来）。

**已落地**（main 未提交）：
- 新建共享原子 `frontend/src/components/workspace/workstation-seat.tsx` = `WorkstationSeat`（头像 emoji/img/icon/首字母 + 名字 + 状态点 + 可选徽章 + 可选 trailing hint；有 onClick 渲染成 button）。**纯表现层**——状态点颜色由调用方传 `dotClassName`，所以语义各自保留（agent=运行时 `agentRunDotClass`，团队 AI=待命、人类=在线/离线）。6 个单测在同目录 `.test.tsx`。
- agent 侧 `agent-workbench-panel.tsx` 的 `SubagentDock`(~L1505) 改用 WorkstationSeat（横向 scroll dock，主控 + subagents）。
- 团队侧 `collab/team-roster.tsx` 改用同一个 WorkstationSeat（flex-wrap）：AI 成员区标题改「工位 · 随时待命」、整张 seat 点击=@mention、保留队长徽章；人类「协作者」带在线点。面板标题仍保留「群成员」(含人类，合理)。

**关键事实**：两个右栏本就共用同一外壳 `ChatPageLayout`（都从 `@/components/workspace/chat-page-layout` 导入、同 `sidebarWidth="min(600px,42vw)"`）——不统一的只是塞进去的 roster 呈现。注意：team members(配置成员池) 与 subagent 工位(运行时工人) 是**不同数据模型**，只统一了表现层不是数据。别和 [[octopus-workspace-dual-surface-design]]（讲左侧 nav 按 surface 切换、别标不一致）搞混——那是左栏，这是右栏 roster。
