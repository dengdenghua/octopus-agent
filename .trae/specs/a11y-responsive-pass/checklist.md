# Checklist

## P0 — 阻断修复

- [x] `deploy-panel.tsx` textarea 不再出现裸 `focus:outline-none`，焦点环可见
- [x] `arms-editor.tsx:934` input 使用 `focus-visible:ring-1` 而非 `focus:ring-1`
- [x] `editor-tabs.tsx` 关闭标签按钮改为 `<button type="button" aria-label>`，键盘 Tab 可达、Enter/Space 可触发
- [x] `browser-home.tsx:2239` 关闭文件夹按钮有 `aria-label` 与 `type="button"`
- [x] `mobile/page.tsx:1244` 麦克风按钮有 `type="button"` 与 `disabled` 与 `aria-label`
- [x] `runtime-self-check-panel.tsx` 表格在 375px 视口下不撑破父容器
- [x] `stream-telemetry-panel.tsx` 表格同上
- [x] `workspace-layout.tsx` modeSwitcher 与 rightPanel 使用同一断点（lg:），无孤儿中间态
- [x] `sidebar.tsx` rail 与 sidebar 容器使用同一断点（md:），无孤儿 rail

## P1 — 可用性修复

- [x] terminal-input.tsx 2 处图标按钮有 `aria-label` 与 `type="button"`
- [x] live-preview-panel.tsx 4 处图标按钮有 `aria-label` 与 `type="button"`
- [x] copilot-panel.tsx 发送按钮有 `aria-label` 与 `type="button"`
- [x] copy-button.tsx `<Button>` 有 `aria-label`
- [x] 12 处 input/textarea/select 有 `aria-label`
- [x] 3 处剩余 button（personality-selector、knowledge-graph-panel×2）有 `type="button"`
- [x] 11 处 DialogFooter 使用 `flex flex-col-reverse gap-2 sm:flex-row sm:justify-end`
- [x] agent-operator-panel.tsx 12 处 `grid-cols-3/4/5` 配合 `sm:`/`lg:` 断点
- [x] 4 处 CardHeader 在移动端堆叠
- [x] 2 处 plugins/agent 卡片在移动端堆叠
- [x] 8 处浮层 `w-[Npx]` 配合 `max-w-[calc(100vw-1rem)]` 或断点兜底

## P2 — 体验优化

- [x] file-tree.tsx 可交互 div 有 `aria-label`
- [x] browser-home.tsx:697 backdrop 有 `aria-hidden="true"`
- [x] 9 处 overflow-x-auto 容器有 `max-w-full`
- [x] agent-operator-panel.tsx 同文件 flex-row 断点统一为 `md:`
- [x] agent-world-unified.tsx 同文件 flex-row 断点统一为 `md:`
- [x] storage/page.tsx 工具栏断点统一为 `lg:`
- [x] appearance-settings-page.tsx `w-[220px]` 改 `w-full sm:w-[220px]`
- [x] reflex/page.tsx flex-row 断点改 `md:`
- [x] intelligence-panel.tsx flex-row 断点改 `md:`
- [x] model-settings-page.tsx:850 flex-row 断点改 `sm:`
- [x] store/*-panel.tsx 4 处 flex-row 断点统一为 `md:`
- [x] observability/page.tsx 同页 grid 节奏统一（md/lg/xl）
- [x] case-study-section.tsx `px-20` 改 `px-4 sm:px-8 lg:px-20`
- [x] evolution-dashboard/index.tsx:273 `xl:grid-cols-1` 复核为 bug，改 `xl:grid-cols-4`

## i18n 与类型安全

- [x] 新增 5 个 i18n key 在 `locales/types.ts` 中声明
- [x] 4 个 locale 文件（zh-CN/en-US/ja-JP/ko-KR）同步包含上述 5 个 key 的翻译
- [x] `pnpm tsc --noEmit` 0 错误

## 测试与回归

- [x] 受影响单测单独跑全部通过（automation-settings 6/6、agent-operator-panel 16/16、chat-input-box 29/29）
- [x] `remote-backends-panel.test.tsx` 通过（受 CardHeader 改造影响）
- [x] `workspace-sidebar.test.tsx` 通过（受 DialogFooter 改造影响）
- [x] `chats-drawer.test.tsx` 通过（受 DialogFooter 改造影响）
- [x] grep 验证：`focus:outline-none` 残留 11 处均有替代焦点指示器（8 处 `focus-visible:`、3 处 `focus:ring-2`/`focus:border-blue-400`），符合 WCAG
- [x] grep 验证：本次修改的 button 均已补 `type="button"`（受影响文件范围内）

## 提交

- [x] commit `3bf7687df`: `style(workspace): a11y + responsive pass for keyboard and mobile usability`
- [x] 仅提交本次走查相关文件（63 files +509/-82），未混入 message-list 与 pre-existing benchmarks/runtime/tests 修改
