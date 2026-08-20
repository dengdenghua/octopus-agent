---
name: octopus-kimi-cluster-ux
description: 把 Kimi「Agent 集群」双栏多-agent UX 移植进 octopus(ClusterWorkbench);含真 axe 实证「比他好」的方法 + worktree 装 optional dep 的隔离法
metadata:
  node_type: memory
  type: project
  originSessionId: ff25d56e-cd25-4c88-9ed5-a162bd9c628b
---

**背景**:用户让我用浏览器(claude-in-chrome)看 Kimi 的「Agent 集群」案例、摸透交互,再基于 octopus 架构实现得更好。

**Kimi Agent 集群 UX(实测 kimi.com/agent-swarm,2 案例 + 回放)**:双栏——左=对话+**步骤时间线**(逐条流式 append,按类型带图标/状态/展开/连接线)+**拟人集群卡**(「N 个并行任务」,每 agent 有名字优伶/普朗/唐墨+头像+编号+任务+进度条+状态);右=「Kimi's Computer」工作区(顶部当前 agent+正在访问的 URL+活动轨迹;底部 agent tab 切换;主区按操作类型切换:iPython 代码/图片生成/网页/Excel 表/checklist `[x]/[-]`)。顶部**阶段进度 N/M + Phase 名**。成果=渲染文件(md/Excel)+预览/下载+**回放/做同款**。

**移植结论**:octopus **零件极全**(数据层甚至比 Kimi 全)——`SwarmSession/SwarmAgent`(有 avatarEmoji/role/motto/hue/skills/progress/tokenUsed)、`TraceEntry`(kind/url)、`agent-phases.ts`(阶段)、`WorkstationSeat`、`live-tool-timeline`、`parallel-subtasks-grid`、`agent-workbench-panel`、`swarm-context`(已供 session/selectedAgentId/setSelectedAgentId + SSE)。差的只是组装成 Kimi 式双栏。

**已建(本地 main,未 push;3 commit `3a41d03c`→`82e9eb52`→`6e3483f8`)**:`frontend/src/components/workspace/swarm/cluster-workbench.tsx` = `<ClusterWorkbench session selectedAgentId onSelectAgent>`,纯展示/props 驱动:左分段进度+拟人 agent 卡;右「octopus's Computer」agent **toolbar**(非 tablist!见下)+ 选中 agent 的类型化 trace 时间线+result。增强(>Kimi):真分段进度条(Kimi 只 N/M 文字)、卡更密(token/rating/skills)、per-agent hue 主题、a11y。`cluster-workbench.test.tsx` 8 测 + `cluster-workbench.axe.test.tsx`。

**「比他好」的实证(不是嘴说)**:worktree 隔离装 axe 跑**真 axe-core 审计**:Kimi agent-swarm 页 = **9 规则 / 528 节点违规**(6 serious:svg-img-alt×281、region×237、color-contrast…);我的组件初审**被 axe 抓到 1 个真 bug**(agent strip 用 `role=tablist` 但 children 是 button → `aria-required-children`)→ 修成 `role=toolbar` → 重审 **0 violations**。**教训:声称 a11y 好必须 axe 实测,我 tablist 就是嘴硬被打脸**。

**关键踩坑/方法**:
- **主仓 `package.json`/`pnpm-lock.yaml` 是双重雷**(并发会话在改 + 预存漂移 11 处 + 并发反复 pnpm install)→ **绝不在主仓 `pnpm add`**(会重写 lockfile 卷漂移+撞并发 pnpm)。装 optional dep 跑审计用 **`git worktree add --detach` + 该 worktree 内 pnpm install/add**(共享 store,9s;独立 lockfile;`cp` 主仓组件进去跑;完事 `worktree remove --force`)。
- axe 进测试栈但**不提 dep**:`cluster-workbench.axe.test.tsx` 用 `it.skipIf(!axe)` + 运行时 `const pkg="vitest-axe"; await import(/* @vite-ignore */ pkg)` 容错——没装则 skip(CI 绿),`pnpm add -D axe-core vitest-axe` 后自动跑真审计。坑:① **Vite 会静态解析 dynamic-import 字面量**(`@ts-expect-error` 压不住,得变量+`@vite-ignore`);② **vitest 把「全 skip 的文件」判 fail(no tests)**→ 加一个 always-run harness 测试垫底。
- 回归:每步 `pnpm test` 全套(936 passed | 2 skipped),别只跑自己那几个(用户因我漏全套回归批评过)。

**未做**:ClusterWorkbench 没接 `swarm-context` 实时跑——接入点 `chats/[thread_id]/page.tsx` + `agent-workbench-panel.tsx`(脏=并发在改)+ `router.tsx`(脏)都是并发热点,wire 一行即可,等并发落定再接。右栏「按操作类型切换」(代码/网页/文件)可复用 `browser-preview-panel`/`artifacts`。见 [[octopus-agent-frontend-optimization]] [[octopus-agent-multiagent-gap]]。
