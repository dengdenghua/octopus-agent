# Spec: mode-intent-auto-switch — Checklist

> 最后核查：已完成

## Requirement: 意图分类器
- [x] 纯函数，无 React/网络依赖
- [x] 三组中英词表（develop/audit/uxui）命中正确
- [x] 时间权重：最近消息权重高
- [x] 置信度 `(top-runner)/top`，阈值 HIGH=0.7 / MEDIUM=0.45
- [x] 无命中 → `{ handle: "none", confidence: 0 }`
- [x] 单测覆盖词表/权重/阈值/无命中

## Requirement: 手动覆盖信号外露
- [x] `onManualOverrideChange` prop 存在
- [x] 手动切换回调 `true`
- [x] 换工作区/自动检测回调 `false`
- [x] 单测覆盖回调

## Requirement: 建议条组件
- [x] 弱显示：小字、text-muted-foreground、无气泡阴影
- [x] `[切换]` / `[忽略]` 回调正确
- [x] sessionStorage 记忽略，避免每轮重弹
- [x] 单测覆盖渲染与交互

## Requirement: 页面集成
- [x] 提交时收集最近用户消息（当前 + 前 4 条 human）
- [x] 高置信（auto）→ setProjectAgentMode + toast
- [x] 中置信（suggest）→ 弹建议条
- [x] 手动覆盖时绝不自动切，仅建议
- [x] 仅 `isProjectCodeMode` 生效，跳过 Assistant
- [x] 无意图时不动作

## Requirement: i18n
- [x] 4 语言建议条文案
- [x] 4 语言自动切换 toast
- [x] 模式名复用现有 `t.modes.*`

## Design/Style
- [x] 建议条符合弱显示原则（无装饰动画）
- [x] 不碰 ReasoningMode / 后端协议

## Non-regression
- [x] 无意图时现有模式行为完全不变
- [x] `pnpm tsc --noEmit` 零错误
- [x] `pnpm lint` 无新增 error
- [x] 相关 vitest 全绿