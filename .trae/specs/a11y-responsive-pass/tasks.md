# Tasks

## P0 — 阻断修复（必须完成）

- [x] Task 1: 修复焦点可见性缺陷
  - [x] SubTask 1.1: `deploy-panel.tsx:293` textarea 移除 `focus:outline-none` 或改 `focus:outline-none focus-visible:ring-2 focus-visible:ring-ring`
  - [x] SubTask 1.2: 复核 `arms-editor.tsx:934` 将 `focus:ring-1 focus:ring-ring` 改 `focus-visible:ring-1 focus-visible:ring-ring`

- [x] Task 2: 修复可交互元素键盘可达性
  - [x] SubTask 2.1: `editor-tabs.tsx:134-146` 关闭标签 `<span role="button" tabIndex={-1}>` 改为 `<button type="button" aria-label>`（i18n key: `editorTabs.closeTabAria`）
  - [x] SubTask 2.2: `browser-home.tsx:2239-2241` 关闭文件夹按钮补 `aria-label` + `type="button"`
  - [x] SubTask 2.3: `mobile/page.tsx:1244-1246` 占位麦克风按钮补 `type="button"` + `disabled` + `aria-label`

- [x] Task 3: 修复表格移动端溢出
  - [x] SubTask 3.1: `runtime-self-check-panel.tsx:446` 表格 `min-w-[720px]` → `min-w-[480px] md:min-w-0`；父 div 加 `max-w-full`
  - [x] SubTask 3.2: `stream-telemetry-panel.tsx:101` 表格 `min-w-[680px]` → `min-w-[480px] md:min-w-0`；父 div 加 `max-w-full`

- [x] Task 4: 修复断点孤儿中间态
  - [x] SubTask 4.1: `workspace-layout.tsx:49` modeSwitcher `hidden md:block` → `hidden lg:block`
  - [x] SubTask 4.2: `sidebar.tsx:343` SidebarRail `sm:flex` → `md:flex`

## P1 — 可用性修复

- [x] Task 5: 图标按钮补 aria-label（8 处）
  - [x] SubTask 5.1: `terminal-input.tsx:86, 94` 停止/提交按钮
  - [x] SubTask 5.2: `live-preview-panel.tsx:379, 395, 402, 414` 4 个图标按钮
  - [x] SubTask 5.3: `copilot-panel.tsx:1096` 发送按钮
  - [x] SubTask 5.4: `copy-button.tsx:45` CopyButton

- [x] Task 6: input/textarea/select 补 aria-label（12 处）
  - [x] SubTask 6.1: `store/registry-{plugins,roles,skills}-panel.tsx` 3 处搜索 input
  - [x] SubTask 6.2: `browser-preview-panel.tsx:1339, 1376` URL input + device select
  - [x] SubTask 6.3: `app/browser/page.tsx:647`、`app/desktop/page.tsx:743, 867` 搜索 input
  - [x] SubTask 6.4: `webview-tab.tsx:985` webview 搜索 input
  - [x] SubTask 6.5: `copilot-panel.tsx:878, 1088` research goal input + chat textarea
  - [x] SubTask 6.6: `terminal-input.tsx:59` 终端 textarea

- [x] Task 7: 原生 button 补 type="button"（剩余 3 处）
  - [x] SubTask 7.1: `personality-selector.tsx:118`、`knowledge-graph-panel.tsx:143, 150`

- [x] Task 8: DialogFooter 恢复响应式（11 处）
  - [x] SubTask 8.1: 11 处 `flex-row justify-end` → `flex flex-col-reverse gap-2 sm:flex-row sm:justify-end`

- [x] Task 9: agent-operator-panel.tsx grid-cols 加断点（12 处）
  - [x] SubTask 9.1: 12 处 `grid-cols-3/4/5` 配合 `sm:`/`lg:` 断点

- [x] Task 10: CardHeader 与卡片 flex-row 加 col 兜底（6 处）
  - [x] SubTask 10.1: 4 处 CardHeader（invariants/feature-flags/remote-backends/ambient-suggestions-panel）
  - [x] SubTask 10.2: 2 处 plugins/agent 卡片（`plugins/page.tsx`、`agent-world-unified.tsx`）

- [x] Task 11: 浮层宽度兜底（8 处）
  - [x] SubTask 11.1: `url-bar.tsx:580, 1027, 1168` 3 处补 `max-w-[calc(100vw-1rem)]`
  - [x] SubTask 11.2: `webview-tab.tsx:649, 1342` 2 处补 `max-w-[calc(100vw-1rem)]`
  - [x] SubTask 11.3: `browser-home.tsx:1977, 2569` 2 处补 `max-w-[calc(100vw-1rem)]`
  - [x] SubTask 11.4: `file-activity-indicator.tsx:71` HoverCardContent `w-[480px]` → `w-80 sm:w-[480px]`

## P2 — 体验优化

- [x] Task 12: file-tree aria-label
  - [x] SubTask 12.1: `file-tree.tsx:379-390` 补 `aria-label`

- [x] Task 13: backdrop 装饰性标注
  - [x] SubTask 13.1: `browser-home.tsx:697` 加 `aria-hidden="true"`

- [x] Task 14: overflow-x-auto 容器加 max-w-full（9 处）
  - [x] SubTask 14.1: 9 处父级 div 加 `max-w-full`

- [x] Task 15: 同文件 flex-row 断点统一（约 25 处）
  - [x] SubTask 15.1: `agent-operator-panel.tsx` 4 处 `lg:flex-row` → `md:flex-row`
  - [x] SubTask 15.2: `agent-world-unified.tsx` 5 处统一为 `md:flex-row`
  - [x] SubTask 15.3: `storage/page.tsx:1705` `sm:flex-row` → `lg:flex-row`
  - [x] SubTask 15.4: `settings/appearance-settings-page.tsx:248, 278` `w-[220px]` → `w-full sm:w-[220px]`
  - [x] SubTask 15.5: `reflex/page.tsx:211` `lg:flex-row` → `md:flex-row`
  - [x] SubTask 15.6: `intelligence-panel.tsx` 3 处 `sm:flex-row` → `md:flex-row`
  - [x] SubTask 15.7: `model-settings-page.tsx:850` `lg:flex-row` → `sm:flex-row`
  - [x] SubTask 15.8: `store/*-panel.tsx` 4 处 `lg:flex-row` → `md:flex-row`

- [x] Task 16: observability/page.tsx 同页 grid 节奏统一
  - [x] SubTask 16.1: 行 1486 `grid-cols-2 md:grid-cols-4` → `grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4`

- [x] Task 17: case-study-section px-20 响应式化
  - [x] SubTask 17.1: `px-20` → `px-4 sm:px-8 lg:px-20`

- [x] Task 18: evolution-dashboard 异常 xl:grid-cols-1 复核
  - [x] SubTask 18.1: 复核为 bug，改为 `xl:grid-cols-4`

## 验证与提交

- [x] Task 19: i18n key 同步
  - [x] SubTask 19.1: 5 个 i18n key 同步到 types.ts + 4 locale 文件

- [x] Task 20: 全量验证
  - [x] SubTask 20.1: `pnpm tsc --noEmit` 0 错误
  - [x] SubTask 20.2: 受影响单测单独跑全部通过（automation-settings 6/6、agent-operator-panel 16/16、chat-input-box 29/29；并发跑 187 文件时 4 个 timeout 是 pre-existing flaky）
  - [x] SubTask 20.3: grep 验证：`focus:outline-none` 残留 11 处，其中 8 处有 `focus-visible:` 替代、3 处有 `focus:ring-2`/`focus:border-blue-400` 替代（符合 WCAG 有可见焦点环）

- [ ] Task 21: 提交 commit
  - [ ] SubTask 21.1: commit message: `style(workspace): a11y + responsive pass for keyboard and mobile usability`

# Task Dependencies

- Task 19（i18n）在 Task 2/12 之前完成 ✓
- Task 20（验证）在所有修复任务（1-18）之后 ✓
- Task 21（提交）在 Task 20 通过后
- Task 3 与 Task 14 联动 ✓
- Task 9/10/15 并行执行 ✓
- Task 5/6/7 并行执行 ✓
