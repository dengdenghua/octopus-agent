# 自动化页面 UX/UI 优化 - Product Requirement Document

## Overview
- **Summary**: 将现有自动化页面（/workspace/intelligence）从双 Tab（订阅/定时任务）重构为三 Tab（已配置/执行历史/任务模板）的现代化任务管理界面。任务以极简卡片行展示，执行历史以时间线布局呈现，内置任务模板库支持一键创建，新增"手动新建"和"在对话中创建"双入口，添加本地运行提示条，整体视觉风格对齐项目扁平极简设计规范。
- **Purpose**: 现有页面存在认知负荷过高（10 字段表单）、信息密度不均（订阅列表+报告双栏）、定时任务和订阅割裂、硬编码颜色、无模板引导、无执行状态清晰反馈等问题，需要对齐 TRAE Work 目标设计，降低使用门槛，提升操作效率。
- **Target Users**: 使用 octopus-agent 配置自动化任务（定时订阅、定时扫描、定期报告）的开发者和用户。

## Goals
- G1: 重构页面 Tab 结构为「已配置 / 执行历史 / 任务模板」
- G2: 任务列表改为极简卡片行布局，自然语言调度展示，开关/更多/立即运行操作隐式化
- G3: 执行历史独立 Tab，按日期分组时间线，支持状态/类型/日期筛选
- G4: 任务模板 Tab 展示预设模板卡片网格，点击即用
- G5: 右上角双创建入口（手动新建按钮、在对话中创建按钮）
- G6: 添加蓝色信息提示条，说明本地任务运行限制
- G7: 移除所有硬编码颜色，统一使用语义设计令牌
- G8: 替换深色渐变 ReportCover 为扁平风格
- G9: 加载状态使用骨架屏替代大转圈
- G10: 将 CronSettingsPage 的命令行 cron 功能整合进新设计或移除（cron 为开发者功能，订阅为用户功能，二者合并为统一"任务"概念）

## Non-Goals (Out of Scope)
- 不改动侧边栏导航结构（不新增左侧任务列表面板）
- 不改动后端 API 数据模型（复用现有 intelligence subscriptions + reports + cron 接口）
- 不实现"在对话中创建"的完整 chat 交互流（仅做按钮入口，点击跳转至聊天页并预填 prompt）
- 不做移动端响应式适配优化（保持现有桌面端布局）
- 不改动自进化（/workspace/evolution）页面
- 不改动设置弹窗中的 automation/evolution/cron 设置页

## Background & Context
- 现有 IntelligencePage 使用 2 Tab：subscriptions（IntelligencePanel 复杂表单+列表+报告）和 schedules（CronSettingsPage 命令行 cron）
- IntelligencePanel 包含：AI 生成草稿区域（10+ 字段表单）、订阅卡片列表（带编号、状态 Badge、关键词、调度、报告数、上次运行时间）、右侧报告时间线、下方报告详情大卡片（带深色渐变 ReportCover）
- 后端已有 `/api/intelligence/subscriptions` CRUD、`/api/intelligence/reports`、`/api/cron/` 接口
- 项目 UI 约束：必须使用 shadcn/ui 组件、语义设计令牌、小圆角（5/7/10px）、无阴影/无模糊/无渐变装饰、扁平风格
- 参考截图来自 TRAE Work 产品设计，展示了目标交互范式

## Functional Requirements
- **FR-1**: 页面顶部显示标题「自动化」和描述文字，右上角放置「手动新建」和「在对话中创建」两个按钮
- **FR-2**: Tab 切换组件包含三个 Tab：已配置、执行历史、任务模板，默认选中「已配置」
- **FR-3**: 「已配置」Tab 下，若存在本地任务（云端任务 flag 为 false），显示蓝色信息提示条，说明本地任务仅在电脑保持唤醒时运行，并提供「保持电脑唤醒」开关
- **FR-4**: 「已配置」Tab 下，任务列表以卡片行形式展示，每行包含：云图标/本地图标、任务名称、[Work/Code/Design]模式标签、自然语言调度时间、更多操作菜单（…）、立即运行按钮（⏱）、启用/禁用开关
- **FR-5**: 「已配置」Tab 下，空状态显示引导文案和示例推荐
- **FR-6**: 「执行历史」Tab 下，顶部有筛选栏：状态下拉（全部/成功/失败/运行中）、类型下拉（所有云端任务/本地任务）、日期范围选择器
- **FR-7**: 「执行历史」Tab 下，历史记录按日期分组（今天/昨天/更早），每条记录显示状态图标（绿色对勾/红色叉/灰色等待）、任务名称、模式标签、触发方式（手动触发/定时触发）、耗时
- **FR-8**: 「执行历史」Tab 下，点击历史记录可在右侧面板或新视图查看执行结果（复用现有报告查看逻辑）
- **FR-9**: 「任务模板」Tab 下，以 3 列网格展示预设模板卡片，每个卡片包含：macOS 风格窗口图标（带不同图案区分类型）、模板名称、模板描述；第一个卡片高亮显示当前选中状态
- **FR-10**: 点击模板卡片可直接基于模板创建任务，进入编辑表单预填模板参数
- **FR-11**: 「手动新建」按钮打开任务创建表单（简化版，替代现有 10 字段表单）
- **FR-12**: 「在对话中创建」按钮跳转到聊天页面，自动发送一条引导消息（如"帮我创建一个自动化任务："）
- **FR-13**: 任务启用/禁用开关使用 Switch 组件，启用时为品牌色
- **FR-14**: 任务卡片 hover 时显示更多操作按钮

## Non-Functional Requirements
- **NFR-1**: 所有颜色必须使用语义设计令牌（--foreground, --muted-foreground, --primary, --destructive, --border, --card, --background, --accent, --secondary, --ring, --muted），禁止硬编码 Tailwind 颜色（text-emerald-*, text-amber-*, bg-red-*, text-purple-* 等）
- **NFR-2**: 圆角半径统一使用项目规范：卡片 7px，按钮 5px，Switch 使用组件默认
- **NFR-3**: 禁止使用 backdrop-filter blur、scale 动画、深色渐变背景、网格纹理装饰
- **NFR-4**: 加载状态展示骨架屏（3-4 个灰色卡片行）而非居中大转圈
- **NFR-5**: 页面切换和 Tab 切换响应时间 < 100ms，数据加载显示 loading 状态但不阻塞 UI
- **NFR-6**: i18n 文案使用中文，所有新增文案加入 zh-CN.ts（英文可选）
- **NFR-7**: 复用现有 shadcn/ui 组件（Tabs, Button, Switch, DropdownMenu, Select, Badge, Skeleton 等）
- **NFR-8**: 保持与现有测试兼容，更新受影响的测试用例

## Constraints
- **Technical**: React + TypeScript + shadcn/ui + Tailwind CSS + TanStack Query + i18n；后端 API 不变；必须兼容现有订阅/报告/cron 数据
- **Business**: 不引入新依赖；尽量复用现有工具函数和组件
- **Dependencies**: 现有 `/api/intelligence/*` 和 `/api/cron/*` 接口；现有 i18n 体系；现有 shadcn/ui 组件库

## Assumptions
- 现有 IntelligenceSubscription 数据模型足够支撑新 UI（有 display_name, cadence, schedule_time, enabled, last_run 等字段）
- 现有 IntelligenceReport 数据模型足够支撑执行历史（有 created_at, title, summary, markdown 等字段）
- CronSettingsPage 的命令行 cron 任务可以与 intelligence subscriptions 在 UI 层合并展示，或暂时保留在设置页中不集成到自动化主页
- "在对话中创建" 可以通过 navigate 到聊天页 + URL 参数或全局事件实现，不需要后端改动
- 模板数据可以在前端硬编码预设，不需要后端模板 API
- 蓝色提示条的"电脑保持唤醒"开关在 Web 端无法控制系统休眠，仅作为 UI 提示（开关状态可本地存储）

## Acceptance Criteria

### AC-1: 三 Tab 页面结构
- **Given**: 用户访问 /workspace/intelligence
- **When**: 页面加载完成
- **Then**: 显示标题「自动化」、描述文字、右上角「手动新建」和「在对话中创建」按钮，下方有三个 Tab：已配置、执行历史、任务模板，默认选中「已配置」
- **Verification**: `programmatic`
- **Notes**: 验证 Tab 切换功能正常

### AC-2: 已配置任务列表卡片行
- **Given**: 用户在「已配置」Tab，且有已配置的任务
- **When**: 任务列表加载完成
- **Then**: 每个任务以行卡片展示，包含：图标（云/本地）、任务名、模式标签[Work]、自然语言调度（如"每天 07:00"）、更多菜单按钮、立即运行按钮、Switch 开关
- **Verification**: `human-judgment`
- **Notes**: 视觉走查确认行卡片布局整齐、间距合理、无多余装饰

### AC-3: 本地任务提示条
- **Given**: 用户有本地任务或系统检测到本地环境
- **When**: 进入「已配置」Tab
- **Then**: 任务列表上方显示浅蓝色信息提示条，文字为「本地任务仅在「电脑保持唤醒」时运行」，右侧有「保持电脑唤醒」开关
- **Verification**: `human-judgment`

### AC-4: 执行历史时间线
- **Given**: 用户切换到「执行历史」Tab
- **When**: 历史数据加载完成
- **Then**: 顶部有筛选器（状态、类型、日期范围），历史按日期分组（今天/昨天/日期），每条记录显示状态图标、任务名、模式标签、触发方式、耗时
- **Verification**: `programmatic` + `human-judgment`
- **Notes**: 验证空状态有引导文案

### AC-5: 任务模板网格
- **Given**: 用户切换到「任务模板」Tab
- **When**: 页面渲染
- **Then**: 显示 3 列模板卡片网格，每个卡片包含窗口图标、名称、描述；点击卡片触发创建流程
- **Verification**: `human-judgment`
- **Notes**: 验证卡片 hover 效果、点击反馈

### AC-6: 无硬编码颜色
- **Given**: 代码审查
- **When**: 检查所有新增/修改的前端文件
- **Then**: 不出现 text-emerald-*、text-amber-*、text-red-*、bg-red-*、text-purple-*、text-rose-*、text-sky-* 等硬编码颜色类
- **Verification**: `programmatic`
- **Notes**: 通过 grep 搜索确认

### AC-7: 骨架屏加载
- **Given**: 数据正在加载
- **When**: 用户进入页面或切换 Tab
- **Then**: 显示骨架屏（灰色脉冲行/卡片），不显示居中的大转圈 Loader
- **Verification**: `human-judgment`

### AC-8: ReportCover 扁平风格
- **Given**: 查看报告详情（若保留）
- **When**: 渲染报告封面
- **Then**: 不再使用深色渐变+网格背景，改为扁平浅色背景+左侧色条或纯文字头部
- **Verification**: `human-judgment`

### AC-9: 双创建入口
- **Given**: 用户在自动化页面
- **When**: 点击「手动新建」
- **Then**: 打开任务创建对话框/面板
- **Verification**: `programmatic`

### AC-10: 在对话中创建跳转
- **Given**: 用户在自动化页面
- **When**: 点击「在对话中创建」
- **Then**: 跳转到聊天页面，并预填创建自动化任务的引导 prompt
- **Verification**: `programmatic`
- **Notes**: 可通过 URL 参数或 post-message 事件实现

### AC-11: 调度时间自然语言
- **Given**: 任务有 cadence/schedule_time/schedule_day 字段
- **When**: 渲染任务卡片
- **Then**: 显示如"每天 07:00"、"每周一 09:00"、"每月1号 10:00"等自然语言，不显示 cron 表达式
- **Verification**: `programmatic`

### AC-12: 现有功能不受影响
- **Given**: 现有 intelligence subscriptions CRUD、报告生成、启用/禁用、删除功能
- **When**: 用户执行这些操作
- **Then**: 功能正常工作，数据正确刷新
- **Verification**: `programmatic`
- **Notes**: 通过现有测试用例验证

## Open Questions
- [ ] CronSettingsPage（命令行 cron）是否保留在自动化页面的 Tab 中？建议：不保留，cron 是开发者功能，留在设置页即可，自动化主页只展示 intelligence subscriptions（用户级任务）
- [ ] 执行历史的筛选器是纯前端筛选还是需要后端分页/筛选接口？建议：先用前端筛选（数据量小）
- [ ] "在对话中创建"跳转到聊天页时，是否需要自动选择对应的 agent/workspace？建议：跳转到最近的 chat 并预填消息
- [ ] 模板数量和内容具体是哪些？建议：内置 8 个常用模板（新闻简报、舆情监控、竞品追踪、股价预警、漏洞扫描、Bug 扫描、测试覆盖、变更摘要），与截图一致
- [ ] 执行结果点击后是在当前页面右侧面板展示、弹窗展示、还是跳转到独立页面？建议：截图显示是跳转到对话视图，但实现复杂度高，可先在当前 Tab 内右侧面板展示
