# Tasks

- [x] Task 1: 补充 reasoning_duration_ms 回放路径单测
  - [x] SubTask 1.1: `message-group.test.tsx` `reasoning duration replay > displays persisted duration on replay` — `public_reasoning_summary: "分析需求"` + `reasoning_duration_ms: 3500`，断言 thinking 行包含 "思考了 3.5s"
  - [x] SubTask 1.2: `message-group.test.tsx` `reasoning duration replay > suppresses duration when reasoning_duration_ms is 0` + `suppresses duration when reasoning_duration_ms is missing` — 0 和 undefined 均不显示耗时

- [x] Task 2: 补充 reasoning_started_at live 路径单测
  - [x] SubTask 2.1: `message-group.test.tsx` `reasoning live timer from backend timestamp > starts the live timer from reasoning_started_at` — `vi.useFakeTimers()` + `reasoning_started_at` 指向 3.5s 前，推进 1.5s 后断言 thinking 行出现"思考了"文案
  - [x] SubTask 2.2: `message-group.test.tsx` `reasoning live timer from backend timestamp > falls back to Date.now() when reasoning_started_at is missing` — 无 `reasoning_started_at` 旧数据，推进时间后断言不崩溃、thinking 行可定位

- [x] Task 3: 验证与同步
  - [x] SubTask 3.1: `npx vitest run src/components/workspace/messages/message-group.test.tsx` → 60 passed (2.33s)
  - [x] SubTask 3.2: 同步 `stream-ux-synergy-optimization/tasks.md` SubTask 15.2 为 `[x]`

# Task Dependencies
- Task 1 和 Task 2 无依赖，可并行
- Task 3 依赖 Task 1/2 完成
