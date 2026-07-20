# Checklist

## 阶段 1：url-bar findInPage Dialog 化

- [x] `url-bar.tsx` 的 `findInPage` 不再使用 `window.prompt`
- [x] Dialog 包含 Input + 确认/取消按钮
- [x] 确认按钮触发 `webviewHandle.executeJS` 调用 `window.find`
- [x] 无需新 i18n key（复用 `t.common.cancel` / `t.common.confirm` / `ub.findPrompt`）

## 阶段 2：reasoning TextShimmer 降级

- [x] `reasoning.tsx` 的 thinking 文字使用 `animate-pulse`
- [x] `import { Shimmer } from "./shimmer"` 已移除
- [x] `shimmer.tsx` 已删除（0 引用）

## 阶段 3：6 处非标准字号映射

- [x] `agent-welcome.tsx:55` `text-[22px]` → `text-xl`
- [x] `clarification-questionnaire.tsx:329` `text-[17px]` → `text-base`
- [x] `browser-preview-panel.tsx:1626` `text-[8px]` → `text-[10px]`
- [x] `parallel-agents-panel.tsx:446` `text-[8px]` → `text-[10px]`
- [x] `file-lease-indicator.tsx:115` `text-[7px]` → `text-[10px]`
- [x] `workspace-sidebar.tsx:1797` `text-[8px]` → `text-[10px]`

## 阶段 4：验证与提交

- [x] `pnpm typecheck` 退出码 0
- [x] `pnpm lint`（受影响文件）退出码 0
- [x] grep `text-\[(7|8|17|22)px\]` 在 `frontend/src/` 0 命中
- [x] grep `window\.(confirm|alert|prompt)` 在 `frontend/src/` 仅 2 处注释命中
- [x] 受影响单测退出码 0
- [ ] commit message: `style(workspace): fix leftover prompt, shimmer, and non-standard font sizes`
