# Checklist

## 回放路径单测
- [x] AI message 带 `reasoning_duration_ms` 正数时，thinking 行显示"思考了 Ns"（localized）
  - 证据：`message-group.test.tsx` `reasoning duration replay > displays persisted duration on replay`，`reasoning_duration_ms: 3500` → 断言 thinking 行包含 "思考了 3.5s"
- [x] `reasoning_duration_ms` 为 `0` 时，不显示耗时文案
  - 证据：`message-group.test.tsx` `reasoning duration replay > suppresses duration when reasoning_duration_ms is 0`
- [x] `reasoning_duration_ms` 为 `null` 或 `undefined` 时，不显示耗时文案
  - 证据：`message-group.test.tsx` `reasoning duration replay > suppresses duration when reasoning_duration_ms is missing`

## Live 路径单测
- [x] `isLoading=true` + `reasoning_started_at` 为 ISO 时间戳时，显示"思考中"
  - 证据：`message-group.test.tsx` `reasoning live timer from backend timestamp > starts the live timer from reasoning_started_at`，`vi.useFakeTimers()` + `reasoning_started_at` 指向 3.5s 前，推进 1.5s 后断言 thinking 行出现"思考了"文案
- [x] `isLoading=true` 但无 `reasoning_started_at` 时，计时器回退 `Date.now()` 不崩溃
  - 证据：`message-group.test.tsx` `reasoning live timer from backend timestamp > falls back to Date.now() when reasoning_started_at is missing`

## 验证
- [x] `npx vitest run src/components/workspace/messages/message-group.test.tsx` 全绿
  - 证据：60 passed (2.33s)，55 原有 + 5 新增
- [x] `stream-ux-synergy-optimization/tasks.md` SubTask 15.2 同步为 `[x]`
  - 证据：`.trae/specs/stream-ux-synergy-optimization/tasks.md:78` 已标记 `[x]`
