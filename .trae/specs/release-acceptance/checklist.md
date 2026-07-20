# Checklist

## 阶段 1：CI 前端 job 全绿

- [x] `pnpm install --frozen-lockfile` 退出码 0
- [x] `pnpm lint` 退出码 0（0 error；修复 `file-tree.tsx:385` 三元表达式语句为 if-else）
- [x] `pnpm typecheck` 退出码 0（0 error）
- [x] `pnpm test` 退出码 0（全量通过）
- [x] `pnpm build` 退出码 0，`dist/` 产出 `index.html` + `assets/`，✓ built in 27.66s
- [x] 构建日志无 `chunk size exceeds` 告警（0 个）

## 阶段 2：i18n 一致性

- [x] `pnpm test -- src/core/i18n/translations.test.ts` 通过
- [x] 5 个新增 key 在 4 个 locale 文件中均有非空翻译（20 处全部非空）

## 阶段 3：走查回归 grep

- [x] `window.confirm` / `window.alert` / `window.prompt` 在 `frontend/src/` 仅 3 处命中（2 处注释 + 1 处 `url-bar.tsx:413` pre-existing 漏网，记 P3）
- [x] `<Shimmer` 仅 1 处命中（`reasoning.tsx:128` ai-elements 包内 TextShimmer，pre-existing，记 P3）；`<ShineBorder` / `ambilight` / `codex-shimmer-text` 0 命中
- [x] `canvas-confetti` 在 `frontend/src/` 与 `frontend/package.json` 0 命中
- [x] `breathing` 仅测试名称命中（组件用 `animate-spin`）
- [x] `focus:outline-none` 残留 11 处均有替代焦点指示器（`focus-visible:` / `focus:ring-2` / `focus:border-blue-400`）

## 阶段 4：CHANGELOG

- [x] `CHANGELOG.md` 第 9 行起 `[Unreleased] — 2026-06` 段内包含 `### Frontend style review` 子节
- [x] 子节列出 10 个 style commit（`f5ba93762` → `3bf7687df`）的范围与摘要

## 阶段 5：提交

- [ ] commit message: `docs(changelog): record frontend style review pass`
- [ ] 仅提交 `CHANGELOG.md` + `.trae/specs/release-acceptance/` + `frontend/src/components/workspace/file-tree.tsx`（lint 修复），不混入 pre-existing 的 benchmarks/runtime/tests 修改
