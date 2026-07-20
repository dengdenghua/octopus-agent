# Tasks

## 阶段 1：url-bar findInPage Dialog 化

- [x] Task 1: 读取 `url-bar.tsx` findInPage 上下文与 i18n key
  - [x] SubTask 1.1: 确认 `ub.findPrompt` 的值与 placeholder 用途
  - [x] SubTask 1.2: `t.common.cancel` 和 `t.common.confirm` 已存在，无需新增 i18n key

- [x] Task 2: 实现 findInPage Dialog
  - [x] SubTask 2.1: 新增 `findDialogOpen` state 与 `findQuery` state
  - [x] SubTask 2.2: 用 shadcn Dialog 替换 `window.prompt`，包含 Input + 确认/取消按钮
  - [x] SubTask 2.3: 确认按钮触发 `webviewHandle.executeJS` 调用 `window.find`
  - [x] SubTask 2.4: 无需新 i18n key

## 阶段 2：reasoning TextShimmer 降级

- [x] Task 3: 降级 reasoning.tsx thinking 指示器
  - [x] SubTask 3.1: `<Shimmer duration={1}>` → `<span className="animate-pulse">`
  - [x] SubTask 3.2: 移除 `import { Shimmer } from "./shimmer"`

- [x] Task 4: 检查 shimmer.tsx 是否还有引用
  - [x] SubTask 4.1: grep 确认 0 引用
  - [x] SubTask 4.2: 已删除 `shimmer.tsx`

## 阶段 3：6 处非标准字号映射

- [x] Task 5: 映射 6 处字号
  - [x] SubTask 5.1: `agent-welcome.tsx:55` `text-[22px]` → `text-xl`
  - [x] SubTask 5.2: `clarification-questionnaire.tsx:329` `text-[17px]` → `text-base`
  - [x] SubTask 5.3: `browser-preview-panel.tsx:1626` `text-[8px]` → `text-[10px]`
  - [x] SubTask 5.4: `parallel-agents-panel.tsx:446` `text-[8px]` → `text-[10px]`
  - [x] SubTask 5.5: `file-lease-indicator.tsx:115` `text-[7px]` → `text-[10px]`
  - [x] SubTask 5.6: `workspace-sidebar.tsx:1797` `text-[8px]` → `text-[10px]`

## 阶段 4：验证与提交

- [x] Task 6: 验证
  - [x] SubTask 6.1: `pnpm typecheck` 退出码 0
  - [x] SubTask 6.2: `pnpm lint`（受影响文件）退出码 0
  - [x] SubTask 6.3: grep `text-\[(7|8|17|22)px\]` 在 `frontend/src/` 0 命中
  - [x] SubTask 6.4: grep `window\.(confirm|alert|prompt)` 在 `frontend/src/` 仅 2 处注释命中
  - [x] SubTask 6.5: 受影响单测退出码 0

- [x] Task 7: 提交 commit
  - [x] SubTask 7.1: commit `a4b1e4aca` — `style(workspace): fix leftover prompt, shimmer, and non-standard font sizes`（12 files +90/-60，含 shimmer.tsx 删除）
