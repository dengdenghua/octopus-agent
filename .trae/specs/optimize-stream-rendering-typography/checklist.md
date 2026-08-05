# Checklist

## Delta 1 · CodeBlock 流式防闪烁
- [x] 流式期间不再每次 token 清空高亮，保留上一次高亮
- [x] 高亮仅 debounce（150ms）后替换，非流式立即高亮
- [x] 高亮请求竞态保护 + 卸载/主题切换清理行为不回退
- [x] 既有 `code-block` 相关测试通过（2 个）

## Delta 2 · Mermaid 成图过渡
- [x] 源码态→渲染 SVG 加淡入过渡，无瞬时几何跳变
- [x] 流式态源码块 / 错误态 / 复制按钮行为不变
- [x] 既有 `mermaid-block` 相关测试通过

## Delta 3 · MarkdownContent 完成态去重挂载（已回退）
- [x] 移除 `isLoading` 触发的 `key` 重挂载 → 实现后触发 `aria-busy`/`data-is-animating` 无法清除的回归
- [x] 按 spec 回退预案恢复 `key` 重挂载，保留过渡的干净语义与可访问性
- [x] 回退后 `markdown-content` 相关测试通过（25 个）
- [x] `tsc --noEmit` 通过