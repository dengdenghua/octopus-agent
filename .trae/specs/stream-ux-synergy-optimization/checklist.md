# Checklist

## 后端协议（4 项）

- [x] `ReasoningItem` 含 `duration_ms` 字段，完成时填充，旧数据 None 兼容
- [x] `AgentPhaseSnapshot` 含 `phase_kind` 字段，5 种业务 phase 正确映射，无 todo 时为 other
- [x] 模型不守 `Update:` 协议时 commentary item 仍生成，协议字段齐全
  - 证据：`runtime/core/cerebrum/react_loop.py:555-580` `_runtime_fallback_public_update()` 函数（CJK 检测 + target 提取）；`:4844-4862` 检测 `_model_supplied_update=False` 时调用 fallback；测试 `tests/test_react_loop.py:1221-1242` 验证 fallback 触发 + `progress_source="runtime"` + `public_evidence=True`
- [x] text_delta 路径 strip `<ReasoningBlock>` 等泄漏标签，正常文本不受影响
  - 证据：`runtime/sensing/gateway/tool_bridge.py:146-170` 三层正则（`_LEAKED_PROTOCOL_BLOCK_RE` 成对块 + `_LEAKED_PROTOCOL_TAG_RE` 单标签 + 共享 `_LEAKED_PROTOCOL_TAG_NAMES`）；`:173` `strip_leaked_protocol_tags()` 函数；`runtime/sensing/gateway/realtime_event_bridge.py:55,312` 在 text_delta 路径调用；测试 `tests/test_realtime_event_bridge.py:62-141` 25+ 用例

## 前端体验（9 项）

- [x] Inputs 区渲染用户原始请求 + 上传文件 + 附件列表，i18n 4 语言
- [x] 成功的 auto_verification 事件折叠展示而非过滤，失败事件保持展开
- [x] 流式结束后历史 phase 默认折叠为"✓ 完成了 N 件事"，用户展开后不收回
- [x] phase 标题优先用后端 `phase_kind`，fallback 到 `businessAgentPhaseKey` 本地映射
- [x] 聚合行 count 变化走 FlipDisplay 翻转动画，DOM 不重建
- [x] Workbench 子 agent 区复用 SubtaskHoverPreview，头像 + popover + 跳转
- [x] sidebar→chat 高亮加边框/缩放，命中聚合组可展开子项
- [x] timelineExpanded 死代码已删除或接通
- [x] 移动端 drawer 首次打开非全屏，可手动展开

## 联动（2 项）

- [x] 后端给了 phase_kind 时前端优先用后端，businessAgentPhaseKey 降级为 fallback
- [x] 流式中 live 显示思考耗时，结束后从 `ReasoningItem.duration_ms` 读取回放显示

## 回归（3 项）

- [x] 简单对话（无工具调用）渲染不变
- [x] markdown 渲染、ToolApprovalCard、message-output-summary 不受影响
- [x] 4 语言 i18n 无缺失词条
