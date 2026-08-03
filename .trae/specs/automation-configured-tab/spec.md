# 自动化页面「已配置」Tab 实现 - Product Requirement Document

## Overview
- **Summary**: 在自动化（Intelligence）页面的「已配置」Tab 中实现极简的任务卡片列表和蓝色本地运行提示条，替换旧 IntelligencePanel 的复杂 UI，采用符合用户极简设计偏好的扁平列表风格。
- **Purpose**: 将旧的复杂双栏布局（左侧订阅列表 + 右侧报告时间线 + 底部报告详情）简化为单栏极简任务卡片列表，提升页面可读性和操作效率，同时添加本地任务运行提示条告知用户保持电脑唤醒的必要性。
- **Target Users**: 使用 Octopus Agent 自动化功能配置定期任务的用户。

## Goals
- 创建新组件 `AutomationConfiguredTab` 作为「已配置」Tab 的主内容
- 实现蓝色本地运行提示条（LocalTaskBanner），包含保持电脑唤醒的 Switch 开关
- 实现极简任务卡片行列表，包含任务名、模式标签、调度信息、操作按钮和启用开关
- 复用旧组件中的数据获取、变更操作、删除确认等业务逻辑
- 更新 i18n 多语言文案支持新增文本
- 更新页面入口使用新组件

## Non-Goals (Out of Scope)
- 不实现「手动新建」对话框（后续 Task 7 实现）
- 不实现「在对话中创建」功能（后续 Task 8 实现）
- 不实现本地任务（LaptopIcon）区分逻辑，当前所有任务默认视为云端任务
- 不删除旧的 intelligence-panel.tsx 文件（保留但不使用）
- 不实现执行历史 Tab 和任务模板 Tab 的内容
- 不修改任务的创建、编辑等复杂表单逻辑

## Background & Context
- 当前自动化页面的「已配置」Tab 仅显示占位文本
- 旧的 `IntelligencePanel` 组件包含复杂的双栏布局、AI 草稿 builder、报告时间线等，不符合当前极简 UI 设计方向
- 用户偏好 Obsidian 风格的扁平、近单色设计，要求小圆角、无阴影、无渐变、使用语义化颜色令牌
- 需要保持与现有后端 API 的兼容性，复用已有的查询和变更逻辑

## Functional Requirements
- **FR-1**: 顶部蓝色提示条显示「本地任务仅在「电脑保持唤醒」时运行」，右侧包含「保持电脑唤醒」Switch 开关，状态持久化到 localStorage
- **FR-2**: 无任务时显示空状态，包含 CloudIcon、提示文本「还没有自动化任务」和引导文案
- **FR-3**: 有任务时显示任务卡片行列表，每行包含：CloudIcon、任务名、Work 模式 Badge、自然语言调度文本、操作按钮组（hover 显示）、启用 Switch
- **FR-4**: 操作按钮组包含「立即运行」按钮和更多菜单（立即运行、删除）
- **FR-5**: 任务运行中时立即运行按钮显示加载动画（Loader2Icon）
- **FR-6**: 点击 Switch 可切换任务启用/停用状态
- **FR-7**: 删除任务时显示确认 Dialog
- **FR-8**: 所有操作（运行、启用/停用、删除）有 toast 反馈
- **FR-9**: 支持中文、英文、日文、韩文四种语言的文案

## Non-Functional Requirements
- **NFR-1**: 所有颜色使用语义令牌，禁止硬编码颜色值
- **NFR-2**: 圆角规范：卡片 rounded-lg(7px)，按钮 rounded-md(5px)，Badge rounded(3px)
- **NFR-3**: 禁止使用 backdrop-filter、渐变、大阴影（仅允许 shadow-sm 或无阴影）
- **NFR-4**: 使用 shadcn/ui 组件库的标准组件
- **NFR-5**: 使用 lucide-react 图标库
- **NFR-6**: 不引入新的第三方依赖
- **NFR-7**: TypeScript 类型检查通过（除已有 reducer.ts 错误外无新错误）

## Constraints
- **Technical**: React 18, TypeScript, Tailwind CSS, shadcn/ui, @tanstack/react-query, sonner toast
- **Business**: 必须保持与现有后端 API 的兼容
- **Dependencies**: 复用现有组件的 API 调用逻辑和类型定义

## Assumptions
- 旧 `intelligence-panel.tsx` 中的类型定义、API 函数、hooks 逻辑可以直接复制复用
- 当前所有任务默认视为云端任务，使用 CloudIcon
- localStorage key `octopus:keep-awake` 默认值为 true
- 模式标签暂时固定为 "Work"，后续可扩展 Code/Design
- 日韩语言文件暂用中文占位

## Acceptance Criteria

### AC-1: 蓝色本地运行提示条显示
- **Given**: 用户访问自动化页面「已配置」Tab
- **When**: 页面加载完成
- **Then**: 顶部显示蓝色提示条，包含 InfoIcon、提示文字、「保持电脑唤醒」文字和 Switch 开关
- **Verification**: `human-judgment`

### AC-2: 保持唤醒开关持久化
- **Given**: 提示条显示
- **When**: 用户切换 Switch 开关
- **Then**: 开关状态保存到 localStorage key `octopus:keep-awake`，页面刷新后状态保持
- **Verification**: `programmatic`

### AC-3: 空任务状态显示
- **Given**: 没有已配置的自动化任务
- **When**: 页面加载完成
- **Then**: 显示空状态卡片，包含 CloudIcon、「还没有自动化任务」文字和引导文案
- **Verification**: `human-judgment`

### AC-4: 任务卡片列表显示
- **Given**: 存在已配置的自动化任务
- **When**: 页面加载完成
- **Then**: 以行列表形式显示所有任务卡片，每张卡片包含图标、任务名、Work Badge、调度文本、操作按钮区、Switch
- **Verification**: `human-judgment`

### AC-5: 操作按钮 hover 显示
- **Given**: 任务卡片列表显示
- **When**: 鼠标悬停在某张任务卡片上
- **Then**: 该卡片的操作按钮组（立即运行、更多菜单）淡入显示
- **Verification**: `human-judgment`

### AC-6: 立即运行功能
- **Given**: 任务卡片显示
- **When**: 用户点击「立即运行」按钮
- **Then**: 按钮显示加载状态，任务开始执行，完成后显示成功 toast
- **Verification**: `programmatic`

### AC-7: 启用/停用切换
- **Given**: 任务卡片显示
- **When**: 用户点击 Switch 开关
- **Then**: 任务启用状态切换，成功后刷新列表
- **Verification**: `programmatic`

### AC-8: 删除确认
- **Given**: 任务卡片显示
- **When**: 用户点击更多菜单中的「删除」
- **Then**: 显示删除确认 Dialog，确认后删除任务并显示成功 toast
- **Verification**: `programmatic`

### AC-9: i18n 多语言支持
- **Given**: 用户切换语言
- **When**: 页面显示
- **Then**: 所有新增文案根据当前语言正确显示
- **Verification**: `programmatic`

### AC-10: TypeScript 类型检查
- **Given**: 代码修改完成
- **When**: 运行 TypeScript 类型检查
- **Then**: 无新增类型错误（除已有 reducer.ts 错误外）
- **Verification**: `programmatic`

## Open Questions
- 无
