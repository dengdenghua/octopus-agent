# 发布验收 Spec

## Why

前 8 站 UX 走查（侧栏导航、消息区、文件查看、Agent 团队、浏览器/计算机、外部连接、次级工作台、国际化一致性、无障碍与响应式）已全部 commit，工作目录累计 9 个 style commit（`30c25757f` → `3bf7687df`）。发布前必须验证这一连串样式重构没有引入回归，且项目仍处于「CI 全绿、构建通过、关键路径可用」的可发布状态。

同时 `CHANGELOG.md` 顶部 `[Unreleased] — 2026-06` 段自 6 月起持续累积变更但未收录本轮 9 个 style commit，发布前需补齐。

## What Changes

- **不改动业务代码**：本 spec 只做验证与文档同步，发现回归时按最小修复原则处理
- 执行 CI 前端 job 的完整顺序：`pnpm install --frozen-lockfile` → `pnpm lint` → `pnpm typecheck` → `pnpm test` → `pnpm build`
- 执行 i18n 一致性专项校验（结构 + 关键 key 抽样）
- 执行走查回归 grep（验证 9 个 style commit 没有遗留被禁用的模式）
- 复核 bundle 体积是否在 `chunkSizeWarningLimit: 1400` 软告警内
- 在 `CHANGELOG.md` 顶部 `[Unreleased] — 2026-06` 段追加 `### Frontend style review` 子节，收录本轮 9 个 commit
- 验收通过后提交 commit

## Impact

- Affected specs: 无（本 spec 是验证型，不修改前 8 站 spec）
- Affected code:
  - `frontend/`（仅验证，不修改）
  - `CHANGELOG.md`（追加子节）
  - `.trae/specs/release-acceptance/`（本 spec 三件套）

## ADDED Requirements

### Requirement: CI 前端 job 全绿

项目 SHALL 通过 CI `frontend` job 的完整顺序验证：`pnpm install --frozen-lockfile` → `pnpm lint`（0 error，允许 pre-existing warnings）→ `pnpm typecheck`（0 error）→ `pnpm test`（全部通过）→ `pnpm build`（成功产出 `dist/`）。

#### Scenario: 全部步骤通过
- **WHEN** 在 `frontend/` 目录依次执行上述 5 个命令
- **THEN** 每个命令退出码均为 0，`dist/` 目录产出 `index.html` 与 `assets/` 子目录

#### Scenario: 单测出现 flaky timeout
- **WHEN** 并发跑全量 vitest 时出现 timeout（如 agent-operator-panel / chat-input-box 在 187 文件并发场景下的已知 flaky）
- **THEN** 单独跑该测试文件验证通过即可视为通过（pre-existing flaky，非本次走查引入）

### Requirement: i18n 一致性

项目 SHALL 保持 4 个 locale 文件（zh-CN / en-US / ja-JP / ko-KR）与 `types.ts` 的结构对齐。本轮走查新增的 5 个 key（`editorTabs.closeTabAria`、`mobile.micDisabledAria`、`fileTree.openFolderAria`、`fileTree.openFileAria`、`browser.closeFolderAria`）SHALL 在所有 locale 中均有非空翻译。

#### Scenario: 结构对齐
- **WHEN** 执行 `pnpm test -- src/core/i18n/translations.test.ts`
- **THEN** 测试通过，`collectShape(enUS)` 与其他 3 个 locale 形状一致

#### Scenario: 新增 key 非空
- **WHEN** 用 grep 抽查 5 个新增 key 在 4 个 locale 文件中的值
- **THEN** 每个值均为非空字符串，不存在 `""` 占位

### Requirement: 走查回归 grep 验证

前 8 站禁用/统一的模式 SHALL 不在 `frontend/src/` 中遗留：

- `window.confirm` / `window.alert` / `window.prompt`（应已全部替换为 `useConfirmDialog`）
- `<Shimmer` / `<ShineBorder` / `ambilight` / `codex-shimmer-text`（装饰性动画已删除）
- `canvas-confetti`（已移除依赖）
- `breathing` keyframes（已降级为 `animate-pulse`）
- 裸 `focus:outline-none`（11 处残留需有 `focus-visible:` 或 `focus:ring-2` 替代）
- `text-[7px]` / `text-[8px]` / `text-[17px]` / `text-[22px]`（6 处非标准字号需用户确认映射规则，本次验收暂不强制）

#### Scenario: 无禁用模式残留
- **WHEN** 对 `frontend/src/` 执行上述 grep
- **THEN** `window.confirm` / `<Shimmer` / `<ShineBorder` / `ambilight` / `codex-shimmer-text` / `canvas-confetti` / `breathing` 均无命中；`focus:outline-none` 残留 11 处均有替代焦点指示器

### Requirement: Bundle 体积复核

构建产出的 chunk 体积 SHALL 在 `chunkSizeWarningLimit: 1400` KB 软告警之内。已知 mermaid chunk ~1.35 MB min / ~350 KB gzip 是 pre-existing 基线，本轮走查不应使任何 chunk 体积显著增长。

#### Scenario: 构建无 chunk 体积告警
- **WHEN** 执行 `pnpm build`
- **THEN** 构建日志不出现 `chunk size exceeds` 告警，或告警数量与走查前基线一致

### Requirement: CHANGELOG 补齐

`CHANGELOG.md` 顶部 `[Unreleased] — 2026-06` 段 SHALL 追加 `### Frontend style review` 子节，收录本轮 9 个 style commit 的摘要。

#### Scenario: 子节已追加
- **WHEN** 读取 `CHANGELOG.md` 第 9 行起的 `[Unreleased] — 2026-06` 段
- **THEN** 段内包含 `### Frontend style review` 子节，列出 9 个 commit 的范围与摘要

## 验证范围（非门禁）

以下项本次验收 **不** 设为门禁，留作 P3 后续独立 spec：

- `eslint-plugin-jsx-a11y` 安装与启用
- `pnpm test:coverage` 覆盖率门槛
- `pnpm format` / `prettier --check` 加入 CI
- `build:analyze` 与 bundle visualizer
- `playwright.config.ts` 默认起 backend
- `test:smoke` / `test:unit` / `test:e2e` 脚本别名
- `check` 与 `typecheck` 脚本去重
- 6 处非标准字号映射规则
- 全量 e2e（`pnpm e2e:full` 需要 backend，本验收环境不强制）
