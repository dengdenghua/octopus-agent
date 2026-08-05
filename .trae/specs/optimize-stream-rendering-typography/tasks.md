# Tasks

## Delta 1 · CodeBlock 流式防闪烁

- [x] Task 1.1: 流式期间保活已有高亮
  - [x] 修改 `code-block.tsx` useEffect：流式期间不再无条件 `setHtml("")`
  - [x] 保留上一次高亮，仅 debounce（150ms）后基于最新 code 替换
  - [x] 非流式路径保持立即高亮（无 debounce）
  - [x] 补充走查：连续 token 到达时高亮不闪回纯文本
- [x] Task 1.2: 高亮请求竞态保护
  - [x] 复用 `highlightRequestRef` 递增语义，确保过期高亮不覆盖新结果
  - [x] 卸载/主题切换时清理 timer 与挂起请求，行为不回退
  - [x] 既有 `code-block` 相关测试通过（2 个）

## Delta 2 · Mermaid 成图过渡

- [x] Task 2.1: 成图淡入不跳变
  - [x] `mermaid-block.tsx` 从源码态切换到渲染 SVG 时加淡入过渡（复用 `animate-fade-in`）
  - [x] 保持流式态源码块、错误态、复制按钮行为不变
  - [x] 走查：流结束成图时无瞬时高度/宽度跳动
  - [x] 既有 `mermaid-block` 相关测试通过

## Delta 3 · MarkdownContent 完成态去重挂载（已回退）

- [x] Task 3.1: 移除基于 isLoading 的 key 重挂载
  - [x] 尝试去掉 `key={isLoading ? "streaming" : "settled"}`，改为稳定 key —— **实现后触发回归**
- [x] Task 3.2: 回归走查与回退预案
  - [x] 走查确认：去 key 后 `aria-busy`/`data-is-animating` 在流结束无法清除（Streamdown 按内容记忆化时）
  - [x] 实际收益有限：完成时代码块无论是否重挂都会重新高亮一次（isStreaming 翻转触发 else 分支 setHtml("")+立即高亮）
  - [x] 按 spec「Scenario: 回归回退」回退到 `key` 重挂载方案，保留过渡的干净语义与可访问性
  - [x] 回退后 `markdown-content` 相关测试通过（25 个）

# Task Dependencies

- Delta 1 / Delta 2 / Delta 3 相互独立，可并行处理
- Delta 3 风险相对最高，需在 Delta 1/2 完成后单独走查验证，避免与分析结论混淆