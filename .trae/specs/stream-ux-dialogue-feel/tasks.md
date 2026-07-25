# Tasks: stream-ux-dialogue-feel

## Task 1: 工具→人话映射层（action-display.ts）
- **Priority**: P0
- **Depends on**: 无
- **Description**: 创建纯函数模块 `action-display.ts`，提供工具名→人话语义的映射。
  - 定义 `ActionDisplay` 接口：`{ verb: string, icon: LucideIcon, workbenchTab: string, getObject: (toolInput: Record<string, unknown>) => string }`
  - 覆盖所有核心工具：edit_file/write_file/apply_patch/str_replace（编辑/创建/修改）、run_command/shell_command/exec_shell（运行）、read_file/list_dir/glob/grep（读取/查看/搜索文件）、web_search/web_fetch（搜索网页/浏览）、browser_navigate/browser_click/browser_type（操作浏览器）、todo_write（更新计划）、其他（fallback 拆词）
  - `getObject` 从工具 input 提取人类可读的对象名（文件名、命令首词、搜索查询词等）
  - 纯函数，无 React 依赖
- **Acceptance Criteria**:
  - 每个工具都有对应的 verb 和 icon
  - getObject 从 input 提取的对象名截断到合理长度（文件名 ≤ 40 字符，命令 ≤ 30 字符）
  - 未映射工具不抛错，返回兜底显示
  - 单测覆盖所有映射
- **Files**:
  - Create: `frontend/src/components/workspace/messages/action-display.ts`
  - Create: `frontend/src/components/workspace/messages/action-display.test.ts`

## Task 2: 同类动作聚合器（activity-aggregator.ts）
- **Priority**: P0
- **Depends on**: Task 1
- **Description**: 创建纯函数模块 `activity-aggregator.ts`，将连续同类型工具调用聚合成摘要组。
  - 定义 `ActivityGroup` 类型：`{ kind: 'file_write'|'file_read'|'command'|'search'|'mixed', items: CoTStep[], summary: { verb: string, count: number, unit: string } }`
  - 聚合规则：同 phase 内连续的同类型工具合为一组
  - 聚合摘要文案：file_write→"编辑了 N 个文件"、file_read→"查看了 N 个文件"、command→"运行了 N 条命令"、search→"搜索了 N 次"
  - 不同类型打断时，结束当前组开始新组
  - reasoning/commentary 步骤不参与聚合，保持原样
  - 纯函数，输入步骤数组，输出带分组的步骤数组（分组标记在 metadata 上）
- **Acceptance Criteria**:
  - 3 个连续 edit_file → 一个 "编辑了 3 个文件" 组
  - edit + command + edit → 3 个独立项（不聚合）
  - reasoning 步骤不被聚合
  - 单测覆盖各种聚合场景
- **Files**:
  - Create: `frontend/src/components/workspace/messages/activity-aggregator.ts`
  - Create: `frontend/src/components/workspace/messages/activity-aggregator.test.ts`

## Task 3: 动作行 UI 组件（ActionRow）
- **Priority**: P0
- **Depends on**: Task 1, Task 2
- **Description**: 在 message-group.tsx 中重构工具调用渲染，替换原有工具名+参数行为 ActionRow。
  - 创建 `ActionRow` 子组件（在 message-group.tsx 内或独立文件）
  - 结构：左侧 icon + verb + object，下方弱显示 fact-summary，右侧"详情"按钮
  - 聚合行渲染：Collapsible，header 显示摘要文案，content 内渲染每个子 ActionRow
  - 进行中的动作行显示 spinner 状态
  - 完成的动作行显示 check 或无状态图标
  - 失败的动作行显示 XCircle 图标 + 红色 text
  - 点击"详情"按钮 → emitOpenAgentWorkbench + emitAgentWorkbenchFocus（打开对应 tab）
  - 不改变现有 CoTStep 数据流，只改渲染层
- **Acceptance Criteria**:
  - 所有工具调用行不再显示原始工具名
  - 聚合行正确折叠/展开
  - 进行/完成/失败三态视觉区分
  - "详情"按钮正确联动右侧 Workbench
  - 现有 ToolApprovalCard 不受影响
- **Files**:
  - Modify: `frontend/src/components/workspace/messages/message-group.tsx`
  - Update: `frontend/src/components/workspace/messages/message-group.test.tsx`

## Task 4: 思考块耗时显示
- **Priority**: P0
- **Depends on**: 无
- **Description**: 在 process-trace.tsx 和 chain-of-thought.tsx 中为思考块添加实时耗时。
  - 新增 useElapsedTime hook（或直接在组件内）：从 reasoning 步骤开始时间到当前时间/结束时间计算耗时
  - 进行中：spinner + "思考中…"，每秒更新
  - 完成后：大脑图标 + "思考了 N 秒"
  - 深度思考（content 超过阈值或标记）用不同图标
  - i18n key：`thinking.inProgress`、`thinking.completed`、`thinking.completedWithTime`
- **Acceptance Criteria**:
  - 进行中标题实时更新秒数（不跳变不卡顿）
  - 完成后显示最终耗时
  - 默认折叠状态不变
- **Files**:
  - Modify: `frontend/src/components/workspace/messages/process-trace.tsx`
  - Modify: `frontend/src/components/ai-elements/chain-of-thought.tsx`
  - Modify: `frontend/src/core/i18n/locales/zh-CN.ts`
  - Modify: `frontend/src/core/i18n/locales/en-US.ts`
  - Modify: `frontend/src/core/i18n/locales/ja-JP.ts`
  - Modify: `frontend/src/core/i18n/locales/ko-KR.ts`

## Task 5: 当前帧聚焦（Phase 自动收敛）
- **Priority**: P1
- **Depends on**: Task 2
- **Description**: 流式进行中自动收敛已完成 phase，只展开当前 phase。
  - 在 convertToSteps 输出后标记每个步骤的 phase 归属和 phase 状态（completed/current/pending）
  - 新增 `usePhaseCollapse` hook（或在现有渲染逻辑中）：
    - 流式中：已完成 phase 的动作行折叠为单行摘要（使用 activity-aggregator 的聚合结果）
    - 当前 phase 展开
    - 用户手动展开的 phase 记录在 Set 中，不被自动折叠
  - 流式结束（最后一条 ai 消息输出完毕且没有新 toolCall）：所有 phase 自动展开
  - 历史轮次（非当前正在流式的消息组）：默认收敛为"✓ 完成了 N 件事"摘要行
- **Acceptance Criteria**:
  - 进行中只显当前 phase
  - 用户展开的块不被收回
  - 流式结束全部展开
  - 历史轮次默认收敛，点击展开
- **Files**:
  - Modify: `frontend/src/components/workspace/messages/message-group.tsx`
  - Modify: `frontend/src/core/threads/progress-outline.ts`

## Task 6: 联动升级到 Workbench 具体证据
- **Priority**: P1
- **Depends on**: Task 3
- **Description**: 扩展 timeline-linkage，联动目标从大纲 item 升级到 Workbench 具体 tab + event。
  - 扩展 `TimelineLinkageTarget`：支持 `{ type: 'workbench', tab: string, eventId: string }`
  - ActionRow 的"详情"按钮：根据 action-display 的 workbenchTab 映射，emit 正确的 workbench focus 事件
  - Workbench 内的事件点击（如 Terminal 中的命令、Files 中的文件变更）：activateTimelineItem 联动对话区
  - 复用现有高亮 CSS 和定时器机制
- **Acceptance Criteria**:
  - 点文件编辑行 → Files/diff tab + 定位
  - 点命令行 → Terminal tab + 定位
  - 右侧点事件 → 对话区滚动+高亮
  - 不破坏现有对话区↔大纲联动
- **Files**:
  - Modify: `frontend/src/core/threads/timeline-linkage.ts`
  - Modify: `frontend/src/components/workspace/messages/message-group.tsx`
  - Modify: `frontend/src/components/workspace/agent-workbench-panel.tsx`
  - Modify: `frontend/src/components/workspace/agent-workbench-pages.tsx`

## Task 7: Workbench 概要 tab 增强
- **Priority**: P1
- **Depends on**: 无
- **Description**: 增强 Workbench 现有的"概要"/"进度"tab，补全六区结构。
  - Progress 区：当前 phase 名 + 进度条 + X/Y 任务数
  - Subagents 区：嵌入现有 parallel-subtasks-grid（如果有子 agent）
  - Inputs 区：显示用户消息摘要 + 上传文件列表
  - Outputs 区：显示 artifacts 列表（复用现有 artifact 数据）
  - Files Changed 区：变更文件列表（从 toolCall 结果中提取）
  - Sources 区：引用来源（从 grounding 数据中提取，如有）
  - 无数据的区不显示（不占空白）
- **Acceptance Criteria**:
  - 六区信息正确显示
  - 无数据的区隐藏
  - 不破坏其他 tab
- **Files**:
  - Modify: `frontend/src/components/workspace/agent-workbench-panel.tsx`
  - Modify: `frontend/src/components/workspace/agent-workbench-pages.tsx`

## Task 8: fact-summary 升级 + i18n 全量
- **Priority**: P0
- **Depends on**: Task 1
- **Description**: 升级 fact-summary.ts 从工具 result 中提取更丰富的事实信息，覆盖所有动作类型。
  - 文件写入：提取写入行数、文件路径
  - 命令执行：提取 exit code、关键输出摘要
  - 文件读取：提取读取行数/大小
  - 搜索：提取匹配数
  - 浏览器操作：提取 URL、页面标题
  - 全量 i18n：动作动词、聚合文案、思考耗时、phase 标签
- **Acceptance Criteria**:
  - 每种工具类型都能提取有意义的事实
  - 无法提取时不编造，返回 null
  - 4 语言文案齐全
- **Files**:
  - Modify: `frontend/src/components/workspace/messages/fact-summary.ts`
  - Modify: `frontend/src/core/i18n/locales/zh-CN.ts`
  - Modify: `frontend/src/core/i18n/locales/en-US.ts`
  - Modify: `frontend/src/core/i18n/locales/ja-JP.ts`
  - Modify: `frontend/src/core/i18n/locales/ko-KR.ts`

## Task 9: 测试验证 + 主题走查
- **Priority**: P0
- **Depends on**: Task 1-8
- **Description**: 运行全量测试，修复 type/lint 错误，三种主题（浅/深/liquid glass）走查。
  - pnpm tsc --noEmit 零错误
  - pnpm lint 零 error（我们改动的文件）
  - pnpm vitest run 相关测试全绿
  - 三种主题下动作行、聚合行、思考块视觉正常
  - 简单对话（无工具）回归测试
- **Acceptance Criteria**:
  - 所有测试通过
  - 三种主题视觉无异常
  - 简单对话不受影响
