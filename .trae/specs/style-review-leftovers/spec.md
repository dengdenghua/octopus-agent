# 走查漏网修复 Spec

## Why

发布验收 grep 发现 2 处走查漏网（`url-bar.tsx:413` window.prompt、`reasoning.tsx:128` TextShimmer）和 6 处非标准字号（`text-[7/8/17/22px]`）。这些是前 10 站走查未覆盖的残留，修复后可彻底完成样式统一目标。

## What Changes

- **`url-bar.tsx:413`**：`window.prompt` 替换为 shadcn Dialog（input + 确认/取消），与 `useConfirmDialog` 风格一致
- **`reasoning.tsx:128`**：`<Shimmer>` 降级为 `animate-pulse`（与 agent-progress-pill 的 breathing → animate-pulse 一致），移除 `./shimmer` import
- **`shimmer.tsx`**：如果不再被引用，删除该组件文件
- **6 处非标准字号映射**：
  - `text-[22px]` → `text-xl`（agent-welcome h2，与 account page Credits 一致）
  - `text-[17px]` → `text-base`（clarification-questionnaire h4，配合 `sm:text-lg`）
  - `text-[8px]` × 3 → `text-[10px]`（browser-preview-panel / parallel-agents-panel / workspace-sidebar 徽章）
  - `text-[7px]` → `text-[10px]`（file-lease-indicator AvatarFallback）
- i18n：如 Dialog 需要新 key，同步 4 个 locale + types.ts

## Impact

- Affected code:
  - `frontend/src/components/browser/url-bar.tsx`
  - `frontend/src/components/ai-elements/reasoning.tsx`
  - `frontend/src/components/ai-elements/shimmer.tsx`（可能删除）
  - `frontend/src/components/workspace/clarification-questionnaire.tsx`
  - `frontend/src/components/workspace/agent-welcome.tsx`
  - `frontend/src/components/workspace/browser-preview-panel.tsx`
  - `frontend/src/components/workspace/parallel-agents-panel.tsx`
  - `frontend/src/components/workspace/file-lease-indicator.tsx`
  - `frontend/src/components/workspace/workspace-sidebar.tsx`
  - `frontend/src/core/i18n/locales/`（如需新 key）

## ADDED Requirements

### Requirement: url-bar findInPage 使用 Dialog

`url-bar.tsx` 的 `findInPage` 功能 SHALL 使用 shadcn Dialog 替代 `window.prompt`，提供 input + 确认/取消按钮。

#### Scenario: 用户触发页面查找
- **WHEN** 用户点击查找按钮
- **THEN** 弹出 Dialog，包含 input（placeholder 为 `ub.findPrompt`）和确认/取消按钮
- **WHEN** 用户输入查询词并确认
- **THEN** 执行 `webviewHandle.executeJS` 调用 `window.find`
- **WHEN** 用户取消或输入为空
- **THEN** 关闭 Dialog，不执行查找

### Requirement: reasoning thinking 指示器降级

`reasoning.tsx` 的 thinking 文字 SHALL 使用 `animate-pulse` 替代 `<Shimmer>` 组件，与 agent-progress-pill 等其他"思考中"指示器保持一致。

#### Scenario: streaming 状态
- **WHEN** `streaming === true` 或 `elapsed === 0`
- **THEN** 显示 `t.streaming.thinking` 文字，带 `animate-pulse` 动画
- **WHEN** `shimmer.tsx` 不再被任何文件引用
- **THEN** 删除 `shimmer.tsx`

### Requirement: 非标准字号统一

`frontend/src/` SHALL 不再包含 `text-[7px]` / `text-[8px]` / `text-[17px]` / `text-[22px]`。

#### Scenario: 字号映射
- **WHEN** grep `text-\[(7|8|17|22)px\]` 在 `frontend/src/`
- **THEN** 0 命中

映射规则：
| 原值 | 新值 | 文件 |
|------|------|------|
| `text-[22px]` | `text-xl` | agent-welcome.tsx:55 |
| `text-[17px]` | `text-base` | clarification-questionnaire.tsx:329 |
| `text-[8px]` | `text-[10px]` | browser-preview-panel.tsx:1626 |
| `text-[8px]` | `text-[10px]` | parallel-agents-panel.tsx:446 |
| `text-[7px]` | `text-[10px]` | file-lease-indicator.tsx:115 |
| `text-[8px]` | `text-[10px]` | workspace-sidebar.tsx:1797 |
