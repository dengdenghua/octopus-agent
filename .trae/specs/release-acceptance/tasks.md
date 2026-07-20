# Tasks

## 阶段 1：CI 前端 job 全绿验证

- [x] Task 1: `pnpm install --frozen-lockfile`
  - [x] SubTask 1.1: 在 `frontend/` 目录执行，退出码 0
  - [x] SubTask 1.2: 确认 `node_modules/` 与 `pnpm-lock.yaml` 一致

- [x] Task 2: `pnpm lint`
  - [x] SubTask 2.1: 在 `frontend/` 目录执行 `pnpm exec eslint . --ext .ts,.tsx`
  - [x] SubTask 2.2: 退出码 0（允许 pre-existing warnings，0 error）—— 修复 `file-tree.tsx:385` 三元表达式语句为 if-else

- [x] Task 3: `pnpm typecheck`
  - [x] SubTask 3.1: 在 `frontend/` 目录执行 `pnpm typecheck`（即 `tsc --noEmit`）
  - [x] SubTask 3.2: 退出码 0，无错误输出

- [x] Task 4: `pnpm test`（全量单测）
  - [x] SubTask 4.1: 在 `frontend/` 目录执行 `pnpm test`（vitest run）
  - [x] SubTask 4.2: 退出码 0（全量通过）

- [x] Task 5: `pnpm build`
  - [x] SubTask 5.1: 在 `frontend/` 目录执行 `pnpm build`（vite build）
  - [x] SubTask 5.2: 退出码 0，`dist/` 产出 `index.html` + `assets/`
  - [x] SubTask 5.3: 构建日志无 `chunk size exceeds` 告警（0 个），✓ built in 27.66s

## 阶段 2：i18n 一致性专项校验

- [x] Task 6: 结构对齐测试
  - [x] SubTask 6.1: 执行 `pnpm test -- src/core/i18n/translations.test.ts`
  - [x] SubTask 6.2: 测试通过，`collectShape(enUS)` 与 zh-CN / ja-JP / ko-KR 形状一致

- [x] Task 7: 新增 5 个 key 非空验证
  - [x] SubTask 7.1: grep 5 个 key 在 4 个 locale 文件中的值
  - [x] SubTask 7.2: 每个值均为非空字符串（4 个 locale × 5 个 key = 20 处全部非空）

## 阶段 3：走查回归 grep 验证

- [x] Task 8: 禁用模式 grep
  - [x] SubTask 8.1: grep `window\.confirm|window\.alert|window\.prompt` 在 `frontend/src/` 命中 3 处（2 处注释、1 处 `url-bar.tsx:413` window.prompt pre-existing 漏网，记 P3）
  - [x] SubTask 8.2: grep `<Shimmer` 命中 1 处（`reasoning.tsx:128` ai-elements 包内 TextShimmer，pre-existing，未在走查范围，记 P3）；`<ShineBorder|ambilight|codex-shimmer-text` 0 命中
  - [x] SubTask 8.3: grep `canvas-confetti` 在 `frontend/src/` 与 `frontend/package.json` 0 命中
  - [x] SubTask 8.4: grep `breathing` 仅测试名称命中（`agent-progress-pill.test.tsx:191`，组件用 `animate-spin`）

- [x] Task 9: 焦点指示器复核
  - [x] SubTask 9.1: grep `focus:outline-none` 在 `frontend/src/` 命中 11 处
  - [x] SubTask 9.2: 每处确认有 `focus-visible:` 或 `focus:ring-2` / `focus:border-blue-400` 替代焦点指示器

## 阶段 4：CHANGELOG 补齐

- [x] Task 10: 追加 `### Frontend style review` 子节
  - [x] SubTask 10.1: 读取 `CHANGELOG.md` 第 9 行起的 `[Unreleased] — 2026-06` 段
  - [x] SubTask 10.2: 在 `### Retired artifacts` 之后追加 `### Frontend style review` 子节，收录 10 个 commit（`f5ba93762` → `3bf7687df`）的范围与摘要

## 阶段 5：提交 commit

- [ ] Task 11: 提交 commit
  - [ ] SubTask 11.1: 仅暂存 `CHANGELOG.md` + `.trae/specs/release-acceptance/` + `frontend/src/components/workspace/file-tree.tsx`（lint 修复）
  - [ ] SubTask 11.2: commit message: `docs(changelog): record frontend style review pass`

# Task Dependencies

- Task 1-5 顺序执行（CI 顺序固定）
- Task 6-7 依赖 Task 4 通过（vitest 可重跑专项）
- Task 8-9 与 Task 1-7 可并行（grep 不依赖构建）
- Task 10 依赖 Task 1-9 全部通过
- Task 11 依赖 Task 10 完成
