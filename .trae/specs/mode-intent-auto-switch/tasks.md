# Tasks: mode-intent-auto-switch

## Task 1: 纯函数意图分类器
- **Priority**: P0
- **Depends on**: 无
- **Description**: 创建 `frontend/src/core/modes/intent-classifier.ts`，实现基于关键词词表 + 时间权重评分的意图分类。
  - 定义 `IntentClassification` 类型与 `classifyModeIntent(messages, opts)` 纯函数
  - 三组中英词表（develop / audit / uxui），覆盖本项目高频话术
  - 时间权重（最近 `1.0`，往前 `0.8/0.6/0.45/0.3`，最多 5 条）
  - 置信度 `(top - runner) / top`，阈值 `HIGH=0.7` / `MEDIUM=0.45` 输出 `handle`
  - 无 React/网络依赖
- **Acceptance Criteria**:
  - 词表命中正确（中英混排）
  - 时间权重：最近消息权重高
  - 阈值：>=0.7→auto，>=0.45→suggest，否则 none
  - 无命中 → `{ handle: "none", confidence: 0 }`
  - 单测全绿
- **Files**:
  - Create: `frontend/src/core/modes/intent-classifier.ts`
  - Create: `frontend/src/core/modes/intent-classifier.test.ts`

## Task 2: ModeSelector 外露手动覆盖信号
- **Priority**: P0
- **Depends on**: 无
- **Description**: 在 `mode-selector.tsx` 新增 `onManualOverrideChange?: (isManual: boolean) => void`。
  - `handleToggle` 手动切换时回调 `true`
  - 工作区变化重置、自动检测应用推荐模式时回调 `false`
- **Acceptance Criteria**:
  - 手动切换触发 `true`
  - 自动检测/换工作区触发 `false`
  - 单测覆盖回调
- **Files**:
  - Modify: `frontend/src/components/workspace/mode-selector.tsx`
  - Modify: `frontend/src/components/workspace/mode-selector.test.ts`

## Task 3: 轻量建议条组件
- **Priority**: P1
- **Depends on**: Task 1
- **Description**: 创建 `frontend/src/components/workspace/chat-input-box/mode-intent-suggestion.tsx`。
  - 弱显示小字、无气泡阴影
  - `[切换]` → 回调 `onAccept(mode)`；`[忽略]` → 回调 `onDismiss()`
  - sessionStorage 记忽略，避免每轮重弹
- **Acceptance Criteria**:
  - 正确渲染建议文案与两个按钮
  - 忽略后同会话不再重弹（sessionStorage 生效）
  - 单测覆盖
- **Files**:
  - Create: `frontend/src/components/workspace/chat-input-box/mode-intent-suggestion.tsx`
  - Create: `frontend/src/components/workspace/chat-input-box/mode-intent-suggestion.test.tsx`

## Task 4: 页面集成（提交时触发）
- **Priority**: P0
- **Depends on**: Task 1, Task 2, Task 3
- **Description**: 在 `page.tsx` 提交路径插入意图分类与决策应用。
  - 收集最近用户消息（当前 + 前 4 条 human）
  - `modeManualOverride` 优先：手动→仅建议；无手动→auto 切/suggest 建议/none 无动作
  - auto 切时 `setProjectAgentMode` + toast；suggest 时弹建议条
  - 仅 `isProjectCodeMode` 生效，跳过 `isOctopusAssistant`
- **Acceptance Criteria**:
  - 高置信自动切 + toast
  - 中置信弹建议条
  - 手动覆盖时绝不自动切，仅建议
  - 非项目场景跳过
- **Files**:
  - Modify: `frontend/src/app/workspace/realtime/[thread_id]/page.tsx`
  - Modify: `frontend/src/components/workspace/chat-input-box.tsx`（透传 `onManualOverrideChange`，渲染建议条）

## Task 5: i18n 全量
- **Priority**: P1
- **Depends on**: Task 3
- **Description**: 4 语言新增建议条文案、自动切换 toast、模式名提示。
- **Acceptance Criteria**: 4 语言 key 齐全
- **Files**:
  - Modify: `frontend/src/core/i18n/locales/zh-CN.ts`
  - Modify: `frontend/src/core/i18n/locales/en-US.ts`
  - Modify: `frontend/src/core/i18n/locales/ja-JP.ts`
  - Modify: `frontend/src/core/i18n/locales/ko-KR.ts`

## Task 6: 测试验证 + 回归
- **Priority**: P0
- **Depends on**: Task 1-5
- **Description**: 全量测试 + type/lint 检查，三种主题走查建议条。
  - `pnpm tsc --noEmit` 零错误
  - `pnpm lint` 无新增 error
  - 相关 vitest 全绿
  - 无意图时不动作，现有模式行为不变
- **Acceptance Criteria**: 所有测试通过，回归无影响
- **Files**: 无新增