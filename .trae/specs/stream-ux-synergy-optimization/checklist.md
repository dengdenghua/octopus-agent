# Checklist

## 后端协议（4 项）

- [ ] `ReasoningItem` 含 `duration_ms` 字段，完成时填充，旧数据 None 兼容
- [ ] `AgentPhaseSnapshot` 含 `phase_kind` 字段，5 种业务 phase 正确映射，无 todo 时为 other
- [ ] 模型不守 `Update:` 协议时 commentary item 仍生成，协议字段齐全
- [ ] text_delta 路径 strip `<ReasoningBlock>` 等泄漏标签，正常文本不受影响

## 前端体验（9 项）

- [ ] Inputs 区渲染用户原始请求 + 上传文件 + 附件列表，i18n 4 语言
- [ ] 成功的 auto_verification 事件折叠展示而非过滤，失败事件保持展开
- [ ] 流式结束后历史 phase 默认折叠为"✓ 完成了 N 件事"，用户展开后不收回
- [ ] phase 标题优先用后端 `phase_kind`，fallback 到 `businessAgentPhaseKey` 本地映射
- [ ] 聚合行 count 变化走 FlipDisplay 翻转动画，DOM 不重建
- [ ] Workbench 子 agent 区复用 SubtaskHoverPreview，头像 + popover + 跳转
- [ ] sidebar→chat 高亮加边框/缩放，命中聚合组可展开子项
- [ ] timelineExpanded 死代码已删除或接通
- [ ] 移动端 drawer 首次打开非全屏，可手动展开

## 联动（2 项）

- [ ] 后端给了 phase_kind 时前端优先用后端，businessAgentPhaseKey 降级为 fallback
- [ ] 流式中 live 显示思考耗时，结束后从 `ReasoningItem.duration_ms` 读取回放显示

## 回归（3 项）

- [ ] 简单对话（无工具调用）渲染不变
- [ ] markdown 渲染、ToolApprovalCard、message-output-summary 不受影响
- [ ] 4 语言 i18n 无缺失词条
