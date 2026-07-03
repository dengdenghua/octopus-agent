# Octopus 前端端到端审计

日期：2026-07-03
范围：本地 e2e 全栈环境，后端 `config.e2e.yaml`，前端 Vite `http://127.0.0.1:13000`。
输出：截图保存在本目录，建议基于本次运行中实际捕获的画面。

## 审计限制

- e2e 配置中认证关闭，`/` 会直接进入工作区；登录、注册、验证码、密码错误等认证路径没有在本轮截图中完整验证。
- Codex 内置浏览器能截图和做只读 DOM 检查，但 DOM snapshot 接口在该页面报错；本报告使用实际截图、URL、控件列表和源码定位作为证据。
- 截图不能证明完整 WCAG 合规性；键盘遍历、屏幕阅读器朗读、真实色彩对比和动效偏好仍需要专项测试。

## 截图证据

1. [01-workspace-new-task-desktop.png](01-workspace-new-task-desktop.png) - 桌面新任务首屏
2. [02-task-submitted-desktop.png](02-task-submitted-desktop.png) - 提交一条提示后的线程状态
3. [03-hub-agents-desktop.png](03-hub-agents-desktop.png) - Hub / 角色库
4. [04-automation-intelligence-desktop.png](04-automation-intelligence-desktop.png) - 自动化订阅空状态
5. [05-local-database-storage-desktop.png](05-local-database-storage-desktop.png) - 本地数据库离线状态
6. [06-settings-modal-desktop.png](06-settings-modal-desktop.png) - 设置弹窗 / 外观
7. [07-workspace-new-task-mobile.png](07-workspace-new-task-mobile.png) - 移动端默认新任务首屏
8. [08-workspace-mobile-right-pane-closed.png](08-workspace-mobile-right-pane-closed.png) - 移动端关闭右窗后的新任务首屏

## 步骤健康度

1. 打开产品进入新任务：中等健康。核心输入可见，视觉干净；右侧空工作台在桌面和移动端都抢占注意力。
2. 提交提示并创建线程：健康。输入、发送、URL 线程化和 mock 回复都跑通；提交后右侧面板自动收起，主内容更聚焦。
3. 进入 Hub / 角色库：中等健康。角色库丰富、可搜索、可开聊；页面标题弱，卡片文案过长，选择成本偏高。
4. 进入自动化：中等偏好。示例 prompt 和空状态有帮助；层级、页面语义和下一步 CTA 仍不够清楚。
5. 进入本地数据库：中等健康。离线降级可用，应用列表保留；服务状态、授权、扫描、效率之间的关系不够直观。
6. 打开设置：健康但偏重。设置覆盖完整、搜索可用；默认页信息密集，局部英文 `Close` 未本地化。
7. 移动端默认新任务：需要关注。默认右窗遮住主要任务流，用户很难立即发现输入区。
8. 移动端关闭右窗后：中等健康。主任务流恢复清晰；顶部与输入栏按钮仍低于常见 44px 触控目标。

## 主要优势

- 新任务输入心智清晰：一句话任务、模型、权限、快捷任务都在同一个构图里。
- 视觉系统统一：浅色、细边框、柔和阴影和图标语言一致，适合工作台产品。
- 复杂能力有入口：Hub、自动化、本地数据库、设置都能覆盖 agent 产品的关键能力。
- 降级状态没有空白：本地数据库服务离线时仍展示列表和重新连接入口。

## UX 风险

1. 移动端默认首屏被右侧工作台占据。`07` 中用户看到的是文件/主控状态，而不是输入框；`08` 关闭右窗后才恢复主任务。根因在 `frontend/src/app/workspace/realtime/[thread_id]/page.tsx` 默认让新线程保持右侧 workbench 可用。
2. 桌面新任务的右侧空状态权重过高。`01` 中右侧“当前没有活跃中的主控执行过程”占据约半屏，和“Work with Octopus”抢注意力。
3. 多个工作区页面缺页面级标题语义。Hub、自动化、本地数据库的 DOM 检查中，识别到的 heading 主要来自命令面板；`WorkspaceHeader` 更像面包屑，不是 h1。
4. Hub 角色卡选择成本高。卡片描述被截断但仍很长，多个“开聊”按钮重复，用户需要读很多文本才能选角色。
5. 自动化页空状态略像配置面板，不像可执行工作流。示例很好，但“草案会出现这里”和“最新动态”之间缺少更强的下一步引导。
6. 本地数据库离线状态没有把恢复路径排成优先级。顶部同时有“重新连接、授权、扫描、效率、离线”，但用户不清楚第一步该做什么。
7. 设置弹窗默认落在外观深层配置，选项很多。对第一次进入设置的用户，账户、模型、权限、隐私这些高风险项反而没有形成任务式入口。

## 可访问性风险

- 移动端多个按钮高度为 30-32px，包括侧栏、REC、右窗、发送和模型按钮，低于常见 44px 触控目标。
- 页面级 h1/heading 缺失会影响屏幕阅读器定位和快速跳转。
- 多处重复通用按钮文案，如“打开”“动作”“开聊”，需要更具体的 aria-label 或上下文绑定。
- 低对比的浅灰文字、细边框、浅色 badge 在强光或低视力场景下可能不够稳，需要跑色彩对比检查。
- 设置弹窗底部出现英文 `Close`，中文界面下会降低一致性，也可能来自默认 Dialog close 文案。

## 优先级建议

1. P0：移动端默认关闭右侧工作台，把工作台改成底部抽屉或用户主动打开的面板。新任务页首先保证输入框和发送路径在首屏清楚可见。
2. P0：把移动端触控目标统一提升到至少 40-44px，尤其是 `ChatInputBox` 工具栏、发送按钮、顶部 REC/右窗按钮。
3. P1：为每个工作区页面补充可见或 visually-hidden 的 h1，并让 `WorkspaceHeader` 同时承载页面标题和面包屑。
4. P1：桌面新任务页降低右侧空 workbench 权重；没有活跃任务时默认收起，或展示更轻的 inline 状态。
5. P1：重做 Hub 卡片信息层级。卡片只保留头像/名称/角色类型/一句话能力/主 CTA，长背景放详情弹窗。
6. P2：自动化空状态改成三步：描述订阅目标、生成草案、启用追踪；右侧草案区在无内容时显示更明确的占位和禁用状态。
7. P2：本地数据库离线时把“重新连接”设为主按钮，把“授权/扫描/效率”作为后续步骤或状态说明。
8. P2：设置弹窗按任务分组增加概览页：账号、模型、执行权限、隐私、安全、外观。保留搜索，但减少默认页的视觉负担。
9. P2：统一中英文与产品术语，例如 `Hub`、`Code`、`Close`、`MCP Servers` 在中文界面中的展示策略。

## 可能的落地点

- 右侧工作台默认开关：`frontend/src/app/workspace/realtime/[thread_id]/page.tsx`
- 输入框和移动触控尺寸：`frontend/src/components/workspace/chat-input-box.tsx`
- 页面标题/面包屑：`frontend/src/components/workspace/workspace-container.tsx`
- Hub 卡片：`frontend/src/app/workspace/agents/page.tsx` 与 `frontend/src/components/workspace/agents/`
- 自动化页：`frontend/src/app/workspace/intelligence/page.tsx` 与 `frontend/src/components/workspace/intelligence-panel.tsx`
- 本地数据库：`frontend/src/app/workspace/storage/page.tsx`
- 设置弹窗：`frontend/src/components/workspace/settings/settings-dialog.tsx`
