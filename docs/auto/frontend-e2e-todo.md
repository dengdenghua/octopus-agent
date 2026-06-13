# Frontend E2E QA 待办清单

> 来源：两轮前端端到端探索、Playwright 回归、Vitest 回归和移动端抽查。状态按当前本地环境整理。

## P0 阻断与数据正确性

- [x] 恢复或下线工作流编辑器契约：后端 `/api/workflow-editor` 返回 404，OpenAPI 仍残留工作流编辑器接口；前端已补 `/workspace/workflows` 降级页，避免路由掉出 workspace。
- [x] 修复附件 data URL 回退转 File 时内容变成 `[object Blob]` 的问题。
- [x] 修复实时 Agent 回复中的 React duplicate key 报错，观察到重复 key `A/B/C`。
- [x] 明确 Computer 页面依赖：当前环境缺 `pyautogui` 时页面不可用，应给出可操作错误态或安装引导。

## P1 回归稳定性与核心工作流

- [x] 收敛侧边栏主聊天入口 active 逻辑：仅新建/入口路由高亮，历史线程页不误高亮。
- [x] 临时隐藏聊天工具菜单里的工作流快捷入口，避免用户点击到已失效能力。
- [x] 更新 Playwright E2E：`Chats` 链接、智能订阅页、工作流页等断言已落后于当前 UI。
- [x] 统一游客模式模型选择状态：官方模型禁用时，触发器不应仍显示一个不可用官方模型为当前选择。
- [x] Team 工作模式中，聊天输入产生回复但不更新右侧「待办/计划」面板；已接入 team-task 创建并自动打开右侧待办。
- [x] 知识库搜索输入缺少可见筛选结果、空态或加载反馈。
- [x] 「全部安装」等高风险批量操作增加确认或撤销机制。
- [x] 权限模式菜单把风险说明直接展示在菜单项中，减少只靠 tooltip 的不确定性。

## P2 易用性与打磨

- [x] 移动端 Team 右侧 tabs/buttons 横向溢出。
- [x] 移动端 Agents 分类 chips 横向溢出，需要滚动或折行策略。
- [x] Skills 列表过长且描述密集，建议增加分类、搜索、折叠摘要和安装状态筛选。
- [x] 「创建技能」目前只跳到 `/#/workspace/realtime/new?mode=skill`，建议补结构化字段或向导。
- [x] 登录页协议文案需要加空格/连接词，避免显示成 `同意用户协议其他隐私政策`。
- [x] `/terms` 与 `/privacy` 当前是非 hash 链接，需确认是否由服务端路由承接；否则改为前端路由或外链。
- [x] Agents 市场存在重复/近似条目，例如 `Market Researcher`，建议去重或聚合版本。

## P3 测试可维护性

- [x] 给关键导航、模式切换、工具菜单和搜索框补稳定 `data-testid`。
- [x] 为游客/登录态分别建立模型选择器与权限菜单快照/交互测试。
- [x] 增加移动端 viewport 的 smoke 测试，覆盖 Team、Agents、Skills 三个已发现溢出的页面。

## P4 本轮测试经理巡检

- [x] 路由体检：覆盖 Realtime、Team、Company、Browser、Computer、Agents、Skills、Channels、Knowledge、Observability、Reflex、Diagnostics 等工作区页面，未发现白屏或控制台错误。
- [x] 修复移动端 Team 工作台抽屉：小屏下改为覆盖层，不再挤压聊天主区；移动端 smoke 已主动打开抽屉并检查不产生横向滚动。
- [x] 修复 Reflex 监控页移动端操作区：按钮组小屏换行，避免“编辑规则 / 重新加载 / 重置”跑出视口。
- [x] 修复 Reflex 编辑页失败态：规则文件缺失时只展示失败与重新加载，不再同时显示“加载中”。
