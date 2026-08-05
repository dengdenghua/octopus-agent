# 流式渲染与排版 优化 Spec

## Why

上一轮 `optimize-conversation-stream-workspace` 已解决模式/流式状态/工作区/工作栏四个维度。本轮聚焦**流式渲染管线与排版稳定性**。走查发现：流式态下代码块因每次 token 清空高亮而在"高亮/纯文本"间反复闪烁；Mermaid 图在流结束瞬间从源码 `<pre>` 整体切换成 SVG 造成高度跳动；`MarkdownContent` 在流结束瞬间通过 `key` 强制整棵子树卸载重挂，重新解析全文并让所有代码块重新高亮，产生一次完整重排。这三处都直接影响流式阅读体验与排版稳定性，价值明确、边界清晰。

## What Changes

- **CodeBlock 流式防闪烁**：流式期间不再无条件 `setHtml("")` 清空已有高亮，改为保留上一次高亮、仅 debounce 后替换，避免 token 每来一次就闪回纯文本。
- **Mermaid 成图淡入过渡**：从源码态切换到渲染 SVG 时加淡入过渡，避免高度/宽度突变造成的滚动跳动。
- **完成态去重挂载**：移除 `MarkdownContent` 基于 `isLoading` 的 `key` 重挂载，流结束时仅收敛 fade span，不再整棵子树重挂与全部代码块重新高亮。

## Impact

- Affected specs：无（新建 spec，与既有 stream-ux-* / optimize-conversation-stream-workspace 边界独立）。
- Affected code：
  - `frontend/src/components/ai-elements/code-block.tsx`
  - `frontend/src/components/workspace/messages/mermaid-block.tsx`
  - `frontend/src/components/workspace/messages/markdown-content.tsx`
- 测试：`code-block` / `mermaid-block` / `markdown-content` 相关既有测试需保持通过；新增针对防闪烁与去重挂载的走查/单测。

## ADDED Requirements

### Requirement: CodeBlock 流式保活高亮

流式期间，系统 SHALL 保留上一次已渲染的高亮，仅在 debounce 后基于最新代码替换，SHALL NOT 在每次 token 到达时清空高亮。

#### Scenario: 连续 token 到达
- **WHEN** 流式代码块每个 token 更新 `code`
- **THEN** 高亮 DOM 不被清空，仅 debounce（仍为 150ms）后基于最新代码重新高亮

#### Scenario: 流结束
- **WHEN** `isStreaming` 变为 `false`
- **THEN** 立即（无 debounce）基于最终代码高亮，并保留该高亮

### Requirement: Mermaid 成图淡入

Mermaid 图从源码态切换为渲染 SVG 时，系统 SHALL 使用淡入过渡，避免瞬时几何跳变。

#### Scenario: 流结束后成图
- **WHEN** `isStreaming` 变为 `false` 且 `svg` 就绪
- **THEN** SVG 以淡入方式呈现，替换源码块时高度平滑过渡

### Requirement: MarkdownContent 完成态去重挂载

流结束时，系统 SHALL NOT 通过 `key` 强制整棵子树重挂载；SHALL 仅收敛流式期间产生的 fade span，避免重复解析与全部代码块重新高亮。

#### Scenario: 流结束
- **WHEN** `isLoading` 由 `true` 变为 `false`
- **THEN** 内容就地收敛（fade span 移除），不触发整棵子树卸载重挂

#### Scenario: 回归回退
- **WHEN** 去重挂载引入布局/滚动回归
- **THEN** 可回退到 `key` 重挂载方案（保留过渡的干净语义）

## MODIFIED Requirements

无。

## REMOVED Requirements

无。