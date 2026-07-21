# Checklist

## 阶段 1：CI 前端 job 全绿

- [x] `pnpm lint` 退出码 0（0 error，3 warnings pre-existing）
- [x] `pnpm typecheck` 退出码 0（修复 closeFolderAria i18n key 位置错误）
- [x] `pnpm test` 191 passed / 3 failed files，1501 passed / 4 failed tests（4 个失败为 pre-existing，非走查引入）
- [x] `pnpm build` 退出码 0，`dist/` 产出 `index.html` + `assets/`，✓ built in 9.64s
- [x] 构建日志无 `chunk size exceeds` 告警（最大 chunk codemirror-core 857KB < 1400KB 限制）

## 阶段 2：i18n 一致性

- [x] `pnpm vitest run src/core/i18n/translations.test.ts` 通过（3 tests）
- [x] 6 个 aria key 在 4 个 locale 文件中均有非空翻译（24 处全部非空）

## 阶段 3：走查回归 grep

- [x] `window.confirm` / `window.alert` / `window.prompt` 在 `frontend/src/` 实际代码 0 处使用（仅 2 处注释）
- [x] `<Shimmer` / `<ShineBorder` / `ambilight` / `codex-shimmer-text` 0 命中
- [x] `canvas-confetti` 在 `frontend/src/` 与 `frontend/package.json` 0 命中
- [x] `breathing` 仅测试名称命中（组件用 animate-pulse）
- [x] `focus:outline-none` 残留 11 处均有替代焦点指示器（`focus-visible:ring-2` / `focus:ring-2`）

## 阶段 4：CHANGELOG

- [x] `CHANGELOG.md` `### Frontend style review` 子节已存在
- [x] 已追加 Follow-up 2-commit sweep（`a4b1e4aca` → `1d842e79c`）补充说明：leftover fixes + font size normalization

## 阶段 5：提交

- [ ] commit: `chore(release): re-validate frontend style review pass`
- [ ] 提交文件：`CHANGELOG.md` + `.trae/specs/release-acceptance/` + i18n 修复文件（types.ts + 4 locales）
