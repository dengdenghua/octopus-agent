# Tasks

## 阶段 1：硬编码文案 i18n 化（高优先级，破坏性最大）

- [x] Task 1: 抽取 `deep-research-panel.tsx` 全英文硬编码到 i18n
  - [x] SubTask 1.1: 盘点该文件所有面向用户英文字符串（按钮、标题、描述、状态、错误提示等）
  - [x] SubTask 1.2: 在 `types.ts` 的 `deepResearchPanel` 命名空间下新增对应 key 类型签名
  - [x] SubTask 1.3: 在 zh-CN/en-US/ja-JP/ko-KR 四份 locale 添加翻译
  - [x] SubTask 1.4: 将组件中的字符串字面量替换为 `t.deepResearch.*`
  - [x] SubTask 1.5: 运行 `pnpm tsc --noEmit` 验证

- [x] Task 2: 抽取 `desktop-organizer/page.tsx` 全中文硬编码到 i18n
  - [x] SubTask 2.1: 盘点该文件所有面向用户中文字符串
  - [x] SubTask 2.2: 在 `types.ts` 的 `desktopOrganizerPage` 命名空间下新增对应 key 类型签名
  - [x] SubTask 2.3: 在 4 份 locale 添加翻译
  - [x] SubTask 2.4: 将组件中的字符串字面量替换为 `t.desktopOrganizerPage.*`
  - [x] SubTask 2.5: 运行 `pnpm tsc --noEmit` 验证

## 阶段 2：字号统一（机械替换，工作量最大）

- [x] Task 3: 统一 9 个次级工作台文件的非标准字号
  - [x] SubTask 3.1: 在 `codebase-index-panel.tsx` 将 `text-[10px]/text-[11px]` 改为 `text-xs`
  - [x] SubTask 3.2: 在 `deep-research-panel.tsx` 将 `text-[10px]/text-[11px]` 改为 `text-xs`
  - [x] SubTask 3.3: 在 `execution-plan-review.tsx` 将 `text-[10px]` 改为 `text-xs`
  - [x] SubTask 3.4: 在 `quest-panel.tsx` 将 `text-[10px]` 改为 `text-xs`
  - [x] SubTask 3.5: 在 `observability/page.tsx` 将 `text-[10px]` 改为 `text-xs`
  - [x] SubTask 3.6: tsc 验证 + 运行受影响测试

- [x] Task 4: 统一同目录其他文件的非标准字号（约 145 处，按文件分批）
  - [x] SubTask 4.1: `verify-panel.tsx`、`model-picker.tsx`、`execution-timeline.tsx`
  - [x] SubTask 4.2: `local-brain-setup.tsx`、`live-run-feedback-panel.tsx`、`editor-tabs.tsx`、`credits-badge.tsx`、`capability-quality-strip.tsx`
  - [x] SubTask 4.3: `mobile/page.tsx`、`replay/page.tsx`、`computer/page.tsx`
  - [x] SubTask 4.4: `reflex/gepa-panel.tsx`、`reflex/variant-performance-panel.tsx`、`reflex/edit/{page,card-editor}.tsx`
  - [x] SubTask 4.5: `browser-preview-panel.tsx`、`chats-drawer.tsx`、`channels/page.tsx`、`skills/page.tsx`、`terminal-input.tsx`
  - [x] SubTask 4.6: `messages/message-list-item.tsx`、`personality-selector.tsx`
  - [x] SubTask 4.7: tsc 验证 + 全量单测回归
  - **注**：6 个文件含 `text-[7px]/text-[8px]/text-[17px]/text-[22px]` 超出 9-15px 范围，未动（强行映射破坏视觉）

## 阶段 3：颜色语义化（仅 9 个次级工作台文件）

- [x] Task 5: 在 9 个文件中将硬编码色值改为语义 token
  - [x] SubTask 5.1: `codebase-index-panel.tsx`：`text-yellow-500` → `text-amber-500`、`text-green-500` → `text-emerald-500`
  - [x] SubTask 5.2: `deep-research-panel.tsx`：`text-green-*` → `text-emerald-*`、`bg-green-500/10` → `bg-emerald-500/10`
  - [x] SubTask 5.3: `execution-plan-review.tsx`：`text-red-*` → `text-destructive` 等
  - [x] SubTask 5.4: `quest-panel.tsx`：`text-red-*` → `text-destructive` 等
  - [x] SubTask 5.5: tsc + 受影响测试

## 阶段 4：i18n 一致性回归

- [x] Task 6: 校验 `types.ts` 与 4 份 locale 严格对齐
  - [x] SubTask 6.1: 运行 `pnpm tsc --noEmit`，确认无类型错误
  - [x] SubTask 6.2: 用 grep 扫描 4 份 locale 文件，确认每个 `types.ts` 顶层 key 在 4 份文件中都出现
  - [x] SubTask 6.3: 如发现遗漏 key，补齐翻译（无遗漏）

## 阶段 5：原生控件替换（仅明显场景）

- [x] Task 7: 在 9 个文件中将可替换的原生控件换为 shadcn 组件
  - [x] SubTask 7.1: `codebase-index-panel.tsx` 的搜索 `<input>` → shadcn `Input`
  - [x] SubTask 7.2: `teach-repeat-panel.tsx` 的工作流名 `<input>`/描述 `<textarea>` → shadcn `Input`/`Textarea`
  - [x] SubTask 7.3: `execution-plan-review.tsx` 的步骤描述 `<input>` → shadcn `Input`
  - [x] SubTask 7.4: tsc + 受影响测试

## 阶段 6：验证与提交

- [x] Task 8: 全量验证
  - [x] SubTask 8.1: `pnpm tsc --noEmit` 通过
  - [x] SubTask 8.2: `pnpm vitest run` 受影响单测通过（21/21）
  - [x] SubTask 8.3: 手动 grep 确认 9 个文件中无 `text-[Npx]` 残留
  - [x] SubTask 8.4: 手动 grep 确认 9 个文件中无裸 `text-red-500/text-blue-500/text-green-500` 残留

- [ ] Task 9: 提交 commit
  - [ ] SubTask 9.1: `git add` 受影响文件
  - [ ] SubTask 9.2: commit message 遵循 `style(workspace): ...` 风格

# Task Dependencies
- Task 2 依赖 Task 1（同属硬编码抽取，先做 deep-research 熟悉流程）
- Task 3 依赖 Task 1/2 完成（避免与硬编码抽取冲突）
- Task 4 可与 Task 5/6 并行（机械替换 vs 颜色语义化 vs i18n 回归）
- Task 7 依赖 Task 1/2/3 完成（控件替换需在文案与字号稳定后进行）
- Task 8 依赖所有前置任务完成
- Task 9 依赖 Task 8 通过
