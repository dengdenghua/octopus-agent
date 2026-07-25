# Spec: stream-ux-dialogue-feel — Checklist

## Requirement: 工具调用渲染为人话动作行
- [ ] 所有工具调用不再显示原始工具名（edit_file/run_command 等），统一显示为人话动词
- [ ] 文件操作类：编辑/创建/修改/删除 + 文件名
- [ ] 命令类：运行 + 命令摘要
- [ ] 搜索类：搜索 + 查询词摘要
- [ ] 浏览器类：操作浏览器 + 动作
- [ ] 每个动作行下方有弱显示事实摘要（复用升级后的 fact-summary）
- [ ] 未映射工具不报错，fallback 到拆词显示
- [ ] 每个动作行有"展开详情"按钮，点击跳转右侧 Workbench

## Requirement: 同类动作聚合
- [ ] 同一 phase 内连续同类型工具聚合成一行摘要
- [ ] 文件写聚合："编辑了 N 个文件"
- [ ] 文件读聚合："查看了 N 个文件"
- [ ] 命令聚合："运行了 N 条命令"
- [ ] 搜索聚合："搜索了 N 次"
- [ ] 混合类型不聚合
- [ ] 聚合行点击展开看详情
- [ ] 进行中计数实时更新，不闪烁
- [ ] 聚合逻辑不改变原始事件顺序（仅视觉聚合）

## Requirement: 思考块显示耗时
- [ ] 进行中显示 spinner + "思考中…"
- [ ] 完成后显示 "思考了 N 秒"
- [ ] 深度思考 vs 普通思考图标区分
- [ ] 默认折叠，展开看完整内容
- [ ] 计时器准确（从第一个 reasoning token 到最后一个）

## Requirement: 当前帧聚焦
- [ ] 流式进行中，当前 phase 展开，已完成 phase 收敛为摘要行
- [ ] 历史轮次默认收敛为 "✓ 完成了 N 件事"
- [ ] 用户手动展开的块不被自动收回
- [ ] 流式结束后所有 phase 自动展开
- [ ] 收敛摘要行包含 phase 名称 + 关键统计（如"查看了 12 个文件"）

## Requirement: 动作行与右侧 Workbench 联动
- [ ] 文件编辑行 → Workbench Files/diff tab + 定位对应文件
- [ ] 命令行 → Workbench Terminal tab + 定位对应输出
- [ ] 搜索行 → Workbench 对应 tab + 定位搜索结果
- [ ] 右侧事件点击 → 对话区滚动到对应动作行 + 2s 高亮
- [ ] 高亮使用 CSS transition，一次性消退（复用 timeline-linkage 现有机制）
- [ ] 联动不影响 Workbench 其他 tab 的正常使用

## Requirement: Workbench 概要 tab 增强
- [ ] Progress 区：当前 phase + X/Y 任务进度
- [ ] Subagents 区：子 agent 状态（复用现有 parallel-subtasks-grid）
- [ ] Inputs 区：用户请求 + 上传文件
- [ ] Outputs 区：产物清单（artifacts）
- [ ] Files Changed 区：变更文件列表
- [ ] Sources 区：引用来源（如有）
- [ ] 不破坏现有终端/预览/diff/计划/产物 tab 功能

## Design/Style
- [ ] 动作行图标统一 lucide，尺寸 14px，颜色 text-muted-foreground
- [ ] 动作动词用正常字重 text-foreground，对象用 text-muted-foreground
- [ ] 事实摘要 text-xs text-muted-foreground/60，无气泡无阴影
- [ ] 聚合行用 text-sm text-muted-foreground，hover 时 text-foreground
- [ ] 展开/折叠动画用 Collapsible 组件，150ms
- [ ] 高亮动画复用现有 .timeline-item-linkage-highlight CSS
- [ ] 全量 i18n：4 语言（中/英/日/韩）
- [ ] 深色/浅色/liquid glass 主题兼容

## Non-regression
- [ ] 简单对话（无工具调用）行为完全不变
- [ ] 用户消息样式不变
- [ ] 最终回答 markdown 渲染不变
- [ ] 审批卡片（ToolApprovalCard）交互不变
- [ ] 产物 summary 卡片（message-output-summary）位置和功能不变
- [ ] 紧凑模式（selectCompactTimelineItems）语义保真升级，不丢 intent/fact 锚点
- [ ] message-group.tsx 不拆文件，在现有结构内改造
