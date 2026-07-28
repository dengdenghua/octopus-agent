# Reasoning Duration Test Coverage Spec

## Why
`stream-ux-synergy-optimization` Task 15 的代码已实装（完成态读 `reasoning_duration_ms` 回放、进行中态从 `reasoning_started_at` 启动 live 计时），但 SubTask 15.2 要求的单测覆盖缺失。`message-group.test.tsx` 55 个用例中无任何用例验证这两条路径，形成 spec-debt：代码正确性无回归保护。

## What Changes
- 在 `frontend/src/components/workspace/messages/message-group.test.tsx` 新增测试用例，覆盖：
  - **回放路径**：`additional_kwargs.reasoning_duration_ms` 存在时，完成态显示"思考了 Ns"且不启动 live 计时
  - **Live 路径**：`additional_kwargs.reasoning_started_at` 存在且 `isLoading=true` 时，显示"思考中"并从 backend 时间戳启动计时
  - **回退路径**：无 `reasoning_started_at` 的旧数据，live 计时回退到 `Date.now()` 不崩溃
  - **零值容错**：`reasoning_duration_ms=0` 或 `null` 时不显示耗时文案

## Impact
- Affected specs: `stream-ux-synergy-optimization`（闭合 Task 15.2 最后一个 `[ ]`）
- Affected code: `frontend/src/components/workspace/messages/message-group.test.tsx`（仅新增用例，不改实现）
- 无破坏性变更，纯测试补全

## ADDED Requirements
### Requirement: 思考耗时回放显示有单测保护
The system SHALL have unit tests verifying that completed reasoning phases display the duration from `reasoning_duration_ms` and do not start a live timer.

#### Scenario: 回放路径
- **WHEN** AI message carries `additional_kwargs.reasoning_duration_ms` as a positive number
- **THEN** the thinking row displays "思考了 Ns" (localized) and no live timer runs

#### Scenario: Live 路径
- **WHEN** AI message carries `additional_kwargs.reasoning_started_at` (ISO timestamp) and `isLoading=true`
- **THEN** the thinking row displays "思考中" (localized) and the timer starts from the backend timestamp

#### Scenario: 旧数据回退
- **WHEN** `reasoning_started_at` is absent and `isLoading=true`
- **THEN** the timer falls back to `Date.now()` without errors

#### Scenario: 零值容错
- **WHEN** `reasoning_duration_ms` is `0` or `null`
- **THEN** no duration text is rendered
