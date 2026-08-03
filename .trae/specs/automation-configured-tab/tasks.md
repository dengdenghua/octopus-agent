# 自动化页面「已配置」Tab 实现 - The Implementation Plan

## [ ] Task 1: 创建 automation 目录和新组件文件
- **Priority**: high
- **Depends On**: None
- **Description**: 
  - 创建目录 `src/components/workspace/automation/`
  - 创建 `automation-configured-tab.tsx` 组件文件
  - 从旧 `intelligence-panel.tsx` 复用类型定义（IntelligenceSubscription, IntelligenceReport）、apiFetch 函数、scheduleText 函数、查询键、所有 useMutation 和 useQuery hooks、删除确认 Dialog 逻辑、toast 反馈
  - 实现 LocalTaskBanner（内联在组件中）：蓝色提示条，InfoIcon + 文字 + 保持唤醒 Switch，状态存入 localStorage
  - 实现空状态 UI
  - 实现任务卡片行列表：CloudIcon、任务名、Work Badge、调度文本、操作按钮组（hover 显示）、Switch
  - 使用 shadcn/ui 组件：Button, Switch, Badge, DropdownMenu, Dialog
  - 使用 lucide-react 图标：CloudIcon, InfoIcon, PlayCircleIcon, MoreHorizontalIcon, Trash2Icon, Loader2Icon
  - 所有颜色使用语义令牌，圆角按规范
- **Acceptance Criteria Addressed**: AC-1, AC-2, AC-3, AC-4, AC-5, AC-6, AC-7, AC-8
- **Test Requirements**:
  - `programmatic` TR-1.1: 组件文件创建成功，路径为 src/components/workspace/automation/automation-configured-tab.tsx
  - `programmatic` TR-1.2: 组件正确导入并使用所需的 shadcn/ui 组件和 lucide 图标
  - `programmatic` TR-1.3: localStorage key `octopus:keep-awake` 正确读写，默认值为 true
  - `human-judgement` TR-1.4: UI 样式符合规范：语义化颜色、正确圆角、无硬编码颜色、无阴影/渐变/backdrop-filter
  - `human-judgement` TR-1.5: 任务卡片 hover 时操作按钮淡入显示
- **Notes**: 保留 inferScheduleFromGoal 函数但暂时不使用（新建对话框后续实现）；旧 intelligence-panel.tsx 不删除

## [ ] Task 2: 更新 i18n 多语言文案
- **Priority**: high
- **Depends On**: None
- **Description**:
  - 在 `zh-CN.ts` 的 intelligence 对象中添加新文案：localTaskBanner, keepAwake, noTasksYet, noTasksHint, runNow（已存在）, moreActions, deleteTask, enabled（已存在）, disabled（已存在）, modeWork, lastRun（已存在）, neverRun（已存在）
  - 更新 `en-US.ts` 添加对应英文翻译
  - 更新 `ja-JP.ts` 添加中文占位（或日文翻译）
  - 更新 `ko-KR.ts` 添加中文占位（或韩文翻译）
  - 更新 `types.ts` 的 Translations 类型定义，确保类型一致
- **Acceptance Criteria Addressed**: AC-9
- **Test Requirements**:
  - `programmatic` TR-2.1: zh-CN.ts 中 intelligence 对象包含所有新增文案键
  - `programmatic` TR-2.2: en-US.ts、ja-JP.ts、ko-KR.ts 同步更新
  - `programmatic` TR-2.3: types.ts 中 Translations 类型包含新增字段，类型检查通过
- **Notes**: runNow, enabled, disabled, lastRun, neverRun 已存在无需重复添加；modeWork 值为 "Work"

## [ ] Task 3: 更新 page.tsx 使用新组件
- **Priority**: high
- **Depends On**: Task 1
- **Description**:
  - 在 `src/app/workspace/intelligence/page.tsx` 中导入 AutomationConfiguredTab 组件
  - 将 configured TabsContent 的占位内容替换为 `<AutomationConfiguredTab />`
  - 「手动新建」和「在对话中创建」按钮保持空 onClick（后续 Task 实现）
- **Acceptance Criteria Addressed**: AC-1, AC-3, AC-4
- **Test Requirements**:
  - `programmatic` TR-3.1: page.tsx 正确导入 AutomationConfiguredTab 组件
  - `programmatic` TR-3.2: configured TabsContent 内容替换为新组件
  - `human-judgement` TR-3.3: 页面渲染正常，「已配置」Tab 显示新组件内容

## [ ] Task 4: TypeScript 类型检查验证
- **Priority**: high
- **Depends On**: Task 1, Task 2, Task 3
- **Description**:
  - 运行 TypeScript 类型检查（tsc --noEmit）
  - 修复所有新增的类型错误（除已有 reducer.ts 错误外）
- **Acceptance Criteria Addressed**: AC-10
- **Test Requirements**:
  - `programmatic` TR-4.1: TypeScript 编译无新增错误（除已有 reducer.ts 错误外）
