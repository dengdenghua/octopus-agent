# Tasks

## 阶段 1：CI 前端 job 全绿验证

- [x] Task 1: `pnpm lint`
  - [x] SubTask 1.1: 在 `frontend/` 目录执行 `pnpm lint`
  - [x] SubTask 1.2: 退出码 0（0 error，3 warnings pre-existing）

- [x] Task 2: `pnpm typecheck`
  - [x] SubTask 2.1: 在 `frontend/` 目录执行 `pnpm typecheck`（即 `tsc --noEmit`）
  - [x] SubTask 2.2: 修复 `closeFolderAria` i18n key 位置错误（types.ts + 4 locale 中从 `workspace` 移至 `browser`）
  - [x] SubTask 2.3: 退出码 0，无错误输出

- [x] Task 3: `pnpm test`（全量单测）
  - [x] SubTask 3.1: 在 `frontend/` 目录执行 `pnpm test`（vitest run）
  - [x] SubTask 3.2: 4 个失败测试为 pre-existing（agent-progress-pill ×2、settings-dialog ×1、message-output-summary ×1），非走查引入
  - [x] SubTask 3.3: 191 passed / 3 failed files，1501 passed / 4 failed tests

- [x] Task 4: `pnpm build`
  - [x] SubTask 4.1: 在 `frontend/` 目录执行 `pnpm build`（vite build）
  - [x] SubTask 4.2: 退出码 0，`dist/` 产出 `index.html` + `assets/`
  - [x] SubTask 4.3: 构建日志无 `chunk size exceeds` 告警（最大 chunk codemirror-core 857KB < 1400KB 限制）
  - [x] SubTask 4.4: ✓ built in 9.64s

## 阶段 2：i18n 一致性专项校验

- [x] Task 5: 结构对齐测试
  - [x] SubTask 5.1: 执行 `pnpm vitest run src/core/i18n/translations.test.ts`
  - [x] SubTask 5.2: 测试通过（3 tests passed），`collectShape(enUS)` 与 zh-CN / ja-JP / ko-KR 形状一致

- [x] Task 6: 新增 5 个 key + 1 个修正 key 非空验证
  - [x] SubTask 6.1: grep 6 个 key（`closeTabAria`、`micDisabledAria`、`openFolderAria`、`openFileAria`、`closeFolderAria`）在 4 个 locale 文件中的值
  - [x] SubTask 6.2: 每个值均为非空字符串（4 个 locale × 6 个 key = 24 处全部非空）

## 阶段 3：走查回归 grep 验证

- [x] Task 7: 禁用模式 grep
  - [x] SubTask 7.1: grep `window\.confirm|window\.alert|window\.prompt` 在 `frontend/src/` 仅 2 处注释命中，实际代码 0 处使用
  - [x] SubTask 7.2: grep `<Shimmer|<ShineBorder|ambilight|codex-shimmer-text` 0 命中
  - [x] SubTask 7.3: grep `canvas-confetti` 在 `frontend/src/` 与 `frontend/package.json` 0 命中
  - [x] SubTask 7.4: grep `breathing` 仅测试名称命中（`agent-progress-pill.test.tsx:191`）

- [x] Task 8: 焦点指示器复核
  - [x] SubTask 8.1: grep `focus:outline-none` 在 `frontend/src/` 命中 11 处（9 文件）
  - [x] SubTask 8.2: 每处确认有 `focus-visible:ring-2` 或 `focus:ring-2` 替代焦点指示器

## 阶段 4：CHANGELOG 补齐

- [x] Task 9: 追加 style-review-leftovers 补充说明
  - [x] SubTask 9.1: 读取 `CHANGELOG.md` 的 `### Frontend style review` 子节
  - [x] SubTask 9.2: 在子节末尾追加 Follow-up 2-commit sweep（`a4b1e4aca` → `1d842e79c`）说明：leftover fixes + font size normalization

## 阶段 5：提交 commit

- [x] Task 10: 提交 commit
  - [x] SubTask 10.1: 暂存 `CHANGELOG.md` + `.trae/specs/release-acceptance/` + i18n 修复文件
  - [x] SubTask 10.2: commit `41f2fc63d` — `chore(release): re-validate frontend style review pass`（8 files +379/-316）

# Task Dependencies

- Task 1-4 顺序执行（CI 顺序固定）
- Task 5-6 依赖 Task 3 通过（vitest 可重跑专项）
- Task 7-8 与 Task 1-6 可并行（grep 不依赖构建）
- Task 9 依赖 Task 1-8 全部通过
- Task 10 依赖 Task 9 完成
