# Tasks

## 前端组件拆分（3 项）

- [ ] Task 1: 拆分 `chat-input-box.tsx`（1759 行 → ≤600 行）
  - [ ] SubTask 1.1: 提取 `ChatComposer`（输入框 + 编辑器主体）为独立文件
  - [ ] SubTask 1.2: 提取 `MentionPicker`（@提及选择器）为独立文件
  - [ ] SubTask 1.3: 提取 `ResearchSourcePicker`（深度研究源选择器）为独立文件
  - [ ] SubTask 1.4: 提取 `FileAttachment`（文件附件区）为独立文件
  - [ ] SubTask 1.5: 保持 `ChatInputBox` 的 props 接口和 export 不变，确保调用方零改动
  - [ ] SubTask 1.6: 运行 `pnpm test` + `pnpm typecheck` 验证无回归

- [x] Task 2: 拆分 `agent-workbench-panel.tsx`（2091 行 → 519 行）
  - [x] SubTask 2.1: 提取 `MainComputerStatusButton` 为独立文件
    - 证据：`frontend/src/components/workspace/agent-workbench-panel/main-computer-status-button.tsx`
  - [x] SubTask 2.2: 提取 `MachineScopeRail` 为独立文件
    - 证据：`frontend/src/components/workspace/agent-workbench-panel/machine-scope-rail.tsx`
  - [x] SubTask 2.3: 提取 `ComputerScopeSwitch` 为独立文件
    - 证据：`frontend/src/components/workspace/agent-workbench-panel/computer-scope-switch.tsx`
  - [x] SubTask 2.4: 提取 `AgentComputerStatusCard` / `RosterComputerPlaceholder` 为独立文件
    - 证据：`frontend/src/components/workspace/agent-workbench-panel/agent-computer-status-card.tsx`、`roster-computer-placeholder.tsx`
  - [x] SubTask 2.5: 提取 `ActivityTraceView` / `SubagentProcessView` 为独立文件
    - 证据：`frontend/src/components/workspace/agent-workbench-panel/activity-trace-view.tsx`、`subagent-process-view.tsx`
  - [x] SubTask 2.6: 保持 `AgentWorkbenchPanel` 的 props 接口和 `__testing` export 不变
    - 证据：`agent-workbench-panel.tsx:46-49` re-export `hasAgentWorkbenchContent`, `__testing`, `AgentWorkbenchTabId`, `workspaceFocusTabFromEvents`, `WorkbenchRosterSeat`；props 接口在 `agent-workbench-panel.tsx:80-131` 保持不变
  - [x] SubTask 2.7: 运行 `pnpm test` + `pnpm typecheck` 验证无回归
    - 证据：`pnpm typecheck` → 0 errors；`pnpm test -- --run` → 1665 passed, 1 pre-existing failure（`message-list.process-trace.test.tsx` 与本任务无关）；额外提取 `WorkbenchTabHeader`、`BrowserTabPage`、`EmptyShellView`、`AgentKanbanView`、`useWorkbenchSelection` hook 使主文件降至 519 行

- [ ] Task 3: 清理 `messages/skeleton.tsx` 内联样式
  - [ ] SubTask 3.1: 将 11 处 `style={{}}` 提取为 Tailwind class 或 CSS module
  - [ ] SubTask 3.2: 验证 skeleton 动画效果不变

## 前端测试门禁（1 项）

- [x] Task 4: 添加 vitest coverage 阈值
  - [x] SubTask 4.1: `frontend/vite.config.ts` 的 `test:` 块添加 `coverage.provider: 'v8'` + `coverage.thresholds`（ratchet: lines 48 / branches 46 / functions 36 / statements 47，目标逐步提升至 80/75/80/80）
  - [x] SubTask 4.2: 运行 `pnpm test:coverage` 确认当前覆盖率达标（当前 ~50% lines，阈值设为 ratchet 水平防回归）

## Realtime 协议补全（2 项）

- [x] Task 5: A2 — reasoning contentIndex 分桶存储
  - [x] SubTask 5.1: `frontend/src/core/realtime/reducer.ts` 的 reasoning delta 处理改为按 `contentIndex` 分桶（`Map<number, string[]>`），最终渲染时按 index 排序拼接
  - [x] SubTask 5.2: 更新 `preserveCompletedStreamText` 适配分桶结构
  - [x] SubTask 5.3: 补单测：交错 contentIndex delta 场景
  - [x] SubTask 5.4: 运行 `pnpm test src/core/realtime/` 验证

- [x] Task 6: B5 — 兄弟连接扇出 delta
  - [x] SubTask 6.1: `runtime/sensing/gateway/realtime_gateway.py` 的扇出逻辑增加 delta 转发（带 50ms 节流）
  - [x] SubTask 6.2: 确保扇出 delta 不产生 ghost UI（兄弟连接无 reducer 状态时跳过）
  - [x] SubTask 6.3: 补单测：双连接场景的 delta 到达验证
  - [x] SubTask 6.4: 运行 `pytest tests/test_realtime_gateway.py` 验证

## 工程化补全（3 项）

- [ ] Task 7: 添加 release 流水线
  - [ ] SubTask 7.1: 创建 `.github/workflows/release.yml`，触发条件 `on.push.tags: ['v*.*.*']`
  - [ ] SubTask 7.2: Job: 构建 Docker 镜像（复用现有 Dockerfile 多阶段构建）
  - [ ] SubTask 7.3: Job: 推送到 `ghcr.io`，tag 为 git tag 名 + `latest`
  - [ ] SubTask 7.4: Job: 生成 GitHub Release（从 CHANGELOG.md 提取对应版本段落）

- [ ] Task 8: 添加 Dependabot 配置
  - [ ] SubTask 8.1: 创建 `.github/dependabot.yml`
  - [ ] SubTask 8.2: pip 生态：`runtime/` 目录，每周检查，最多 10 个 PR
  - [ ] SubTask 8.3: npm 生态：`frontend/` 目录，每周检查，最多 10 个 PR
  - [ ] SubTask 8.4: github-actions 生态：`.github/workflows/`，每周检查

- [ ] Task 9: 添加 SECURITY.md
  - [ ] SubTask 9.1: 根目录创建 `SECURITY.md`，包含：披露邮箱、响应时间承诺（48h 确认 / 7d 评估 / 90d 修复）、PGP key 占位、不支持范围说明

## 后端安全债务（1 项）

- [ ] Task 10: 清零 bandit MEDIUM 债务
  - [ ] SubTask 10.1: 运行 `bandit -lll -ii -r runtime/` 导出当前全部 MEDIUM 告警
  - [ ] SubTask 10.2: 逐条审计：能修复的修复，无法修复的标注 `# nosec` + 理由注释
  - [ ] SubTask 10.3: 更新 `tools/lint/` 下的 bandit ratchet baseline
  - [ ] SubTask 10.4: CI bandit job 改为 MEDIUM 0 容忍

# Task Dependencies

- Task 1, 2, 3 可并行（独立组件，互不依赖）
- Task 4 独立
- Task 5 依赖 reducer.ts 当前状态（已含 A1/A3 修复），无外部依赖
- Task 6 依赖 realtime_gateway.py 当前状态（已含 B4 修复），无外部依赖
- Task 7, 8, 9 可并行（独立配置文件）
- Task 10 独立
- Task 1-4（前端）与 Task 5-10（后端/工程化）可完全并行
